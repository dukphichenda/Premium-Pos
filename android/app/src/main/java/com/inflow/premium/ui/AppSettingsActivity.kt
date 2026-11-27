package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.BranchInfo
import com.inflow.premium.data.CompanySettingsData
import com.inflow.premium.data.InvoiceSettingsData
import com.inflow.premium.data.MobileSettingsOverview
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityAppSettingsBinding
import com.inflow.premium.databinding.ItemSettingRowBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class AppSettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityAppSettingsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var cachedOverview: MobileSettingsOverview? = null

    private data class SettingItemDef(
        val key: String,
        val title: String,
        val subtitle: String,
        val iconRes: Int,
        val bgHex: String,
        val webPath: String,
        val adminOnly: Boolean = false
    )

    private val companyDefs = listOf(
        SettingItemDef("company", "Company Profile", "Address, tax ID, contacts & branches", R.drawable.ic_wf_branches, "#EA580C", "/settings?tab=tabCompany"),
        SettingItemDef("pricing", "Pricing & Currency", "KHR rate, price tiers & multi-currency", R.drawable.ic_wf_expenses, "#059669", "/settings?tab=tabPricing"),
        SettingItemDef("decimals", "Decimal Precision", "Unit pricing, tax & currency rounding", R.drawable.ic_nav_report, "#0284C7", "/settings?tab=tabDecimals"),
        SettingItemDef("invoice", "Invoice Customization", "Headers, logos, thermal 80mm slip layout", R.drawable.ic_nav_so, "#0D9488", "/settings?tab=tabInvoice"),
        SettingItemDef("users", "Users & Permissions", "Cashier access, admin roles, audit log", R.drawable.ic_wf_customer, "#7C3AED", "/settings?tab=tabUsers", adminOnly = true),
        SettingItemDef("import_export", "Import & Export Data", "Excel/CSV product catalog & customer lists", R.drawable.ic_wf_transfer, "#4F46E5", "/settings?tab=tabImport"),
        SettingItemDef("backup", "Backup & Restore (.sql)", "Daily cloud snapshot, local archive restore", R.drawable.ic_nav_settings, "#475569", "/settings?tab=tabBackup")
    )

    private val systemDefs = listOf(
        SettingItemDef("locations", "Locations & Warehouses", "Warehouse hubs & branch fulfillment", R.drawable.ic_wf_branches, "#0891B2", "/locations"),
        SettingItemDef("categories", "Categories", "Product categories & price table styles", R.drawable.ic_nav_product, "#D97706", "/categories"),
        SettingItemDef("import_wizard", "Import Data Wizard", "Import orders, customers & inventory", R.drawable.ic_wf_po, "#10B981", "/data/import"),
        SettingItemDef("export_center", "Export Data Center", "Download Excel & CSV backups", R.drawable.ic_nav_report, "#6366F1", "/data/export"),
        SettingItemDef("migration", "inFlow SQL Migration", "Connect & migrate legacy SQL database", R.drawable.ic_wf_vendor, "#64748B", "/settings/migration")
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityAppSettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.SETTINGS)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = null,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollSettings,
            extraTopDp = 12,
            extraBottomScrollDp = 150
        )

        if (session.selectedBranch == "all") {
            session.selectedBranch = "main"
        }

        bindInfo()
        renderBranchesList()
        renderSettingsGroup(binding.llCompanySettings, companyDefs)
        renderSettingsGroup(binding.llSystemPrefs, systemDefs)
        prefetchOverview()

        binding.tvActiveStoreChip.setOnClickListener {
            if (session.isMainAdmin()) showBranchPicker()
        }

        binding.btnSettingSync.setOnClickListener {
            binding.btnSettingSync.isEnabled = false
            uiScope.launch {
                try {
                    api.bootstrap()
                    cachedOverview = api.getSettingsOverview()
                    bindInfo()
                    renderBranchesList()
                    Toast.makeText(this@AppSettingsActivity, "Metadata synced successfully", Toast.LENGTH_SHORT).show()
                } catch (e: Exception) {
                    Toast.makeText(this@AppSettingsActivity, e.message ?: "Sync failed", Toast.LENGTH_SHORT).show()
                } finally {
                    binding.btnSettingSync.isEnabled = true
                }
            }
        }

        binding.btnOpenWebPortal.setOnClickListener { openWebPath("/") }
        binding.btnCheckUpdate.setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("${session.baseUrl}/download-app")))
        }
        binding.btnSignOut.setOnClickListener { confirmSignOut() }
    }

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            bindInfo()
            renderBranchesList()
        }
    }

    private fun isRealBranch(b: BranchInfo): Boolean {
        if (b.id == "0" || b.id == "main" || b.id.equals("all", ignoreCase = true)) return false
        if (b.code.equals("ALL", ignoreCase = true)) return false
        val lower = b.name.lowercase()
        if (lower.contains("all stores") || lower.contains("all branch") || lower.contains("consolidated")) return false
        return true
    }

    private fun prefetchOverview() {
        uiScope.launch {
            try {
                cachedOverview = api.getSettingsOverview()
            } catch (_: Exception) {}
        }
    }

    private fun openWebPath(path: String) {
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("extra_url", api.buildWebPortalUrl(path))
        )
    }

    private fun bindInfo() {
        val name = session.getDisplayName().ifBlank { session.getUsername() }
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "main" || branchKey == "0" || branchKey == "all" || branchKey.isBlank() -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey && isRealBranch(it) }?.name ?: "Main Store (HQ)"
        }
        binding.tvSettingUser.text = "$name (@${session.getUsername()})"
        val host = session.baseUrl.removePrefix("https://").removePrefix("http://").trimEnd('/')
        val df = DecimalFormat("#,##0")
        binding.tvSettingServerRate.text = "$host • 1 USD = ${df.format(Math.round(session.defaultKhrRate))} KHR"
        binding.tvSettingRole.text = "• Active Store: $branchLabel"
        binding.tvActiveStoreChip.text = branchLabel
        val verName = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "3.4.0"
        } catch (_: Exception) {
            "3.4.0"
        }
        binding.btnCheckUpdate.text = "App Version $verName • Check APK Updates"
    }

    private fun renderBranchesList() {
        binding.llBranchSwitchList.removeAllViews()
        val inflater = LayoutInflater.from(this)
        val options = mutableListOf<Triple<String, String, String>>()

        if (session.isMainAdmin()) {
            options.add(Triple("main", "Main Store (HQ Enterprise)", "Active Primary Branch"))
            for (b in session.getBranches()) {
                if (isRealBranch(b)) {
                    options.add(Triple(b.id, b.name, "Outlet Branch • Isolated Scope"))
                }
            }
        } else {
            val bid = session.getUserBranchId()?.toString() ?: session.selectedBranch
            val bName = session.getBranches().firstOrNull { it.id == bid }?.name ?: "Assigned Branch"
            options.add(Triple(bid, bName, "Assigned Store Context"))
        }

        val current = session.selectedBranch
        options.forEachIndexed { idx, (id, title, subtitle) ->
            val rb = ItemSettingRowBinding.inflate(inflater, binding.llBranchSwitchList, false)
            rb.tvSetTitle.text = title
            rb.tvSetSubtitle.text = subtitle
            val isSelected = current == id || (id == "main" && (current == "0" || current == "all" || current.isBlank()))
            rb.flSetIconBg.backgroundTintList = ColorStateList.valueOf(
                Color.parseColor(if (id == "main") "#E0F2FE" else "#F1F5F9")
            )
            rb.ivSetIcon.setImageResource(R.drawable.ic_wf_branches)
            rb.ivSetIcon.imageTintList = ColorStateList.valueOf(
                Color.parseColor(if (id == "main") "#0284C7" else "#475569")
            )
            if (isSelected) {
                rb.tvSetCheck.visibility = View.VISIBLE
                rb.tvSetSubtitle.setTextColor(Color.parseColor("#059669"))
            } else {
                rb.tvSetCheck.visibility = View.GONE
            }
            rb.vSetDivider.visibility = if (idx == options.lastIndex) View.GONE else View.VISIBLE
            rb.root.setOnClickListener {
                if (session.isMainAdmin()) {
                    session.selectedBranch = id
                    bindInfo()
                    renderBranchesList()
                    Toast.makeText(this, "Switched to $title", Toast.LENGTH_SHORT).show()
                }
            }
            binding.llBranchSwitchList.addView(rb.root)
        }
    }

    private fun renderSettingsGroup(container: LinearLayout, defs: List<SettingItemDef>) {
        container.removeAllViews()
        val visible = defs.filter { !it.adminOnly || session.isMainAdmin() }
        val inflater = LayoutInflater.from(this)
        visible.forEachIndexed { idx, item ->
            val rb = ItemSettingRowBinding.inflate(inflater, container, false)
            rb.tvSetTitle.text = item.title
            rb.tvSetSubtitle.text = item.subtitle
            rb.flSetIconBg.backgroundTintList = ColorStateList.valueOf(Color.parseColor(item.bgHex))
            rb.ivSetIcon.setImageResource(item.iconRes)
            rb.ivSetIcon.imageTintList = ColorStateList.valueOf(Color.WHITE)
            rb.tvSetCheck.visibility = View.GONE
            rb.vSetDivider.visibility = if (idx == visible.lastIndex) View.GONE else View.VISIBLE
            rb.root.setOnClickListener { handleSettingClick(item) }
            container.addView(rb.root)
        }
    }

    private fun handleSettingClick(item: SettingItemDef) {
        when (item.key) {
            "import_wizard", "export_center", "migration" -> openWebPath(item.webPath)
            else -> withOverview { ov ->
                when (item.key) {
                    "company" -> showCompanyProfileDialog(ov)
                    "pricing" -> showPricingCurrencyDialog(ov)
                    "decimals" -> showDecimalPrecisionDialog(ov)
                    "invoice" -> showInvoiceCustomizationDialog(ov)
                    "users" -> showUsersDialog(ov)
                    "import_export" -> showImportExportDialog(ov)
                    "backup" -> showBackupDialog(ov)
                    "locations" -> showLocationsDialog(ov)
                    "categories" -> showCategoriesDialog(ov)
                    else -> openWebPath(item.webPath)
                }
            }
        }
    }

    private fun withOverview(onReady: (MobileSettingsOverview) -> Unit) {
        val existing = cachedOverview
        if (existing != null) {
            onReady(existing)
            return
        }
        Toast.makeText(this, "Loading settings...", Toast.LENGTH_SHORT).show()
        uiScope.launch {
            try {
                val ov = api.getSettingsOverview()
                cachedOverview = ov
                onReady(ov)
            } catch (e: Exception) {
                Toast.makeText(this@AppSettingsActivity, e.message ?: "Failed to load settings", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun buildFormBox(): Pair<ScrollView, LinearLayout> {
        val dp = resources.displayMetrics.density
        val pad = (18 * dp).toInt()
        val scroll = ScrollView(this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (8 * dp).toInt(), pad, (8 * dp).toInt())
        }
        scroll.addView(col)
        return scroll to col
    }

    private fun addField(parent: LinearLayout, label: String, initial: String, inputType: Int = InputType.TYPE_CLASS_TEXT): EditText {
        val dp = resources.displayMetrics.density
        parent.addView(TextView(this).apply {
            text = label
            textSize = 11.5f
            setTextColor(Color.parseColor("#64748B"))
            setTypeface(null, Typeface.BOLD)
            setPadding(0, (8 * dp).toInt(), 0, (2 * dp).toInt())
        })
        val et = EditText(this).apply {
            setText(initial)
            this.inputType = inputType
            textSize = 14f
        }
        parent.addView(et)
        return et
    }

    private fun showCompanyProfileDialog(ov: MobileSettingsOverview) {
        val (scroll, col) = buildFormBox()
        val c = ov.company
        val etName = addField(col, "Company Name", c.name)
        val etPhone = addField(col, "Phone", c.phone, InputType.TYPE_CLASS_PHONE)
        val etEmail = addField(col, "Email", c.email, InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS)
        val etWeb = addField(col, "Website", c.website)
        val etAddr = addField(col, "Address", c.address1)
        val etCity = addField(col, "City", c.city)
        val etCountry = addField(col, "Country", c.country)
        val etTax = addField(col, "VAT / Tax Number", c.taxNumber)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Company Profile")
            .setView(scroll)
            .setPositiveButton("Save") { _, _ ->
                val updated = c.copy(
                    name = etName.text.toString().trim(),
                    phone = etPhone.text.toString().trim(),
                    email = etEmail.text.toString().trim(),
                    website = etWeb.text.toString().trim(),
                    address1 = etAddr.text.toString().trim(),
                    city = etCity.text.toString().trim(),
                    country = etCountry.text.toString().trim(),
                    taxNumber = etTax.text.toString().trim()
                )
                uiScope.launch {
                    try {
                        val msg = api.saveCompanySettings(updated)
                        cachedOverview = api.getSettingsOverview()
                        Toast.makeText(this@AppSettingsActivity, msg, Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .create()
        attachEscClose(dlg)
        dlg.show()
    }

    private fun showPricingCurrencyDialog(ov: MobileSettingsOverview) {
        val (scroll, col) = buildFormBox()
        val c = ov.company
        val inv = ov.invoice
        val etCode = addField(col, "Currency Code", c.currencyCode)
        val etSym = addField(col, "Currency Symbol", c.currencySymbol)
        val etKhr = addField(col, "KHR Exchange Rate (per $1 USD)", DecimalFormat("#0.##").format(inv.khrExchangeRate), InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL)

        val swKhr = SwitchCompat(this).apply {
            text = "Show KHR Total on Invoices"
            isChecked = inv.enableKhrTotal
            setPadding(0, (12 * resources.displayMetrics.density).toInt(), 0, 8)
        }
        col.addView(swKhr)

        var selectedSchemeId = ov.pricingSchemes.firstOrNull { it.isDefault }?.id
        if (ov.pricingSchemes.isNotEmpty()) {
            val tvScheme = TextView(this).apply {
                val curName = ov.pricingSchemes.firstOrNull { it.id == selectedSchemeId }?.name ?: ov.pricingSchemes.first().name
                text = "Default Price Scheme: $curName (Tap to change)"
                setTextColor(Color.parseColor("#0A6C62"))
                setTypeface(null, Typeface.BOLD)
                setPadding(0, 14, 0, 8)
            }
            tvScheme.setOnClickListener {
                val names = ov.pricingSchemes.map { it.name }.toTypedArray()
                val idx = ov.pricingSchemes.indexOfFirst { it.id == selectedSchemeId }.coerceAtLeast(0)
                MaterialAlertDialogBuilder(this)
                    .setTitle("Default Pricing Scheme")
                    .setSingleChoiceItems(names, idx) { d, which ->
                        val s = ov.pricingSchemes[which]
                        selectedSchemeId = s.id
                        tvScheme.text = "Default Price Scheme: ${s.name}"
                        d.dismiss()
                    }
                    .show()
            }
            col.addView(tvScheme)
        }

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Pricing & Currency")
            .setView(scroll)
            .setPositiveButton("Save") { _, _ ->
                val rate = etKhr.text.toString().trim().toDoubleOrNull() ?: inv.khrExchangeRate
                uiScope.launch {
                    try {
                        val msg = api.savePricingSettings(
                            currencyCode = etCode.text.toString().trim().ifBlank { "USD" },
                            currencySymbol = etSym.text.toString().trim().ifBlank { "$" },
                            khrRate = rate,
                            enableKhrTotal = swKhr.isChecked,
                            defaultSchemeId = selectedSchemeId
                        )
                        api.bootstrap()
                        cachedOverview = api.getSettingsOverview()
                        bindInfo()
                        Toast.makeText(this@AppSettingsActivity, msg, Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .create()
        attachEscClose(dlg)
        dlg.show()
    }

    private fun showDecimalPrecisionDialog(ov: MobileSettingsOverview) {
        val (scroll, col) = buildFormBox()
        val c = ov.company
        val etPrice = addField(col, "Unit Price Decimals", c.decimalPlacesPrice.toString(), InputType.TYPE_CLASS_NUMBER)
        val etCost = addField(col, "Product Cost Decimals", c.decimalPlacesCost.toString(), InputType.TYPE_CLASS_NUMBER)
        val etQty = addField(col, "Quantity Decimals", c.decimalPlacesQty.toString(), InputType.TYPE_CLASS_NUMBER)
        val etMarkup = addField(col, "Markup % Decimals", c.decimalPlacesMarkup.toString(), InputType.TYPE_CLASS_NUMBER)
        val etTotal = addField(col, "Order Total Decimals", c.decimalPlacesTotal.toString(), InputType.TYPE_CLASS_NUMBER)
        val etMeas = addField(col, "Measurements Decimals", c.decimalPlacesMeasurement.toString(), InputType.TYPE_CLASS_NUMBER)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Decimal Precision")
            .setView(scroll)
            .setPositiveButton("Save") { _, _ ->
                uiScope.launch {
                    try {
                        val msg = api.saveDecimalSettings(
                            price = (etPrice.text.toString().toIntOrNull() ?: 2).coerceIn(0, 6),
                            cost = (etCost.text.toString().toIntOrNull() ?: 3).coerceIn(0, 6),
                            qty = (etQty.text.toString().toIntOrNull() ?: 0).coerceIn(0, 4),
                            markup = (etMarkup.text.toString().toIntOrNull() ?: 2).coerceIn(0, 4),
                            total = (etTotal.text.toString().toIntOrNull() ?: 2).coerceIn(0, 4),
                            measurement = (etMeas.text.toString().toIntOrNull() ?: 2).coerceIn(0, 4)
                        )
                        cachedOverview = api.getSettingsOverview()
                        Toast.makeText(this@AppSettingsActivity, msg, Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .create()
        attachEscClose(dlg)
        dlg.show()
    }

    private fun showInvoiceCustomizationDialog(ov: MobileSettingsOverview) {
        val (scroll, col) = buildFormBox()
        val inv = ov.invoice
        val etShopKh = addField(col, "Shop Name (Khmer)", inv.shopNameKh)
        val etShopEn = addField(col, "Shop Name (English)", inv.shopNameEn)
        val etTitleKh = addField(col, "Invoice Title (Khmer)", inv.invoiceTitleKh)
        val etTitleEn = addField(col, "Invoice Title (English)", inv.invoiceTitleEn)
        val etPhone = addField(col, "Invoice Phone", inv.phone, InputType.TYPE_CLASS_PHONE)
        val etTin = addField(col, "VAT TIN", inv.vatTin)
        val etBank = addField(col, "Bank Name", inv.bankName)
        val etAccName = addField(col, "Account Name", inv.accountName)
        val etAccNum = addField(col, "Account Number", inv.accountNumber)
        val etTerms = addField(col, "Payment Terms", inv.paymentTerms)
        val etFooter = addField(col, "Footer Notes", inv.footerNotesEn)

        val swSku = SwitchCompat(this).apply { text = "Show SKU on Invoice"; isChecked = inv.showSku }
        val swTax = SwitchCompat(this).apply { text = "Show Tax Line"; isChecked = inv.showTax }
        val swSig = SwitchCompat(this).apply { text = "Show Signatures"; isChecked = inv.showSignature }
        col.addView(swSku); col.addView(swTax); col.addView(swSig)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Invoice Customization")
            .setView(scroll)
            .setPositiveButton("Save") { _, _ ->
                val updated = inv.copy(
                    shopNameKh = etShopKh.text.toString().trim(),
                    shopNameEn = etShopEn.text.toString().trim(),
                    invoiceTitleKh = etTitleKh.text.toString().trim(),
                    invoiceTitleEn = etTitleEn.text.toString().trim(),
                    phone = etPhone.text.toString().trim(),
                    vatTin = etTin.text.toString().trim(),
                    bankName = etBank.text.toString().trim(),
                    accountName = etAccName.text.toString().trim(),
                    accountNumber = etAccNum.text.toString().trim(),
                    paymentTerms = etTerms.text.toString().trim(),
                    footerNotesEn = etFooter.text.toString().trim(),
                    showSku = swSku.isChecked,
                    showTax = swTax.isChecked,
                    showSignature = swSig.isChecked
                )
                uiScope.launch {
                    try {
                        val msg = api.saveInvoiceSettings(updated)
                        cachedOverview = api.getSettingsOverview()
                        Toast.makeText(this@AppSettingsActivity, msg, Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNeutralButton("Web Preview") { _, _ -> openWebPath("/settings?tab=tabInvoice") }
            .setNegativeButton("Cancel", null)
            .create()
        attachEscClose(dlg)
        dlg.show()
    }

    private fun showUsersDialog(ov: MobileSettingsOverview) {
        if (ov.users.isEmpty()) {
            Toast.makeText(this, "No users loaded", Toast.LENGTH_SHORT).show()
            return
        }
        val labels = ov.users.map { u ->
            val st = if (u.isActive) "ACTIVE" else "DISABLED"
            "${u.displayName} (@${u.username}) • ${u.role} [$st]\n${u.branchName}"
        }.toTypedArray()

        MaterialAlertDialogBuilder(this)
            .setTitle("Users & Permissions (Tap to Toggle)")
            .setItems(labels) { d, which ->
                val u = ov.users[which]
                uiScope.launch {
                    try {
                        val (newActive, msg) = api.toggleUserActive(u.id)
                        u.isActive = newActive
                        Toast.makeText(this@AppSettingsActivity, msg, Toast.LENGTH_SHORT).show()
                        d.dismiss()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNeutralButton("Manage Roles (Web)") { _, _ -> openWebPath("/settings?tab=tabUsers") }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showImportExportDialog(ov: MobileSettingsOverview) {
        val summary = "Database Summary:\n" +
            "• Products: ${ov.productsCount}\n" +
            "• Customers: ${ov.customersCount}\n" +
            "• Sales Orders: ${ov.salesOrdersCount}\n" +
            "• Warehouses: ${ov.locationsCount}"
        MaterialAlertDialogBuilder(this)
            .setTitle("Import & Export Data")
            .setMessage(summary)
            .setPositiveButton("Import Wizard") { _, _ -> openWebPath("/data/import") }
            .setNeutralButton("Export Data Center") { _, _ -> openWebPath("/data/export") }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showBackupDialog(ov: MobileSettingsOverview) {
        val msg = if (ov.backups.isEmpty()) {
            "No local SQL backups found yet."
        } else {
            ov.backups.take(8).joinToString("\n") { "• ${it.filename} (${it.formattedSize})" }
        }
        MaterialAlertDialogBuilder(this)
            .setTitle("Backup & Restore (.sql)")
            .setMessage(msg)
            .setPositiveButton("+ Create Backup Now") { _, _ ->
                Toast.makeText(this, "Creating SQL backup...", Toast.LENGTH_SHORT).show()
                uiScope.launch {
                    try {
                        val resMsg = api.createCloudBackup()
                        cachedOverview = api.getSettingsOverview()
                        Toast.makeText(this@AppSettingsActivity, resMsg, Toast.LENGTH_LONG).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@AppSettingsActivity, e.message ?: "Backup failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNeutralButton("Restore Options (Web)") { _, _ -> openWebPath("/settings?tab=tabBackup") }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showLocationsDialog(ov: MobileSettingsOverview) {
        val items = ov.locations.map { l ->
            val tags = buildList {
                if (l.isCentral) add("HQ")
                if (l.isDefault) add("Default")
            }.joinToString(", ")
            if (tags.isNotEmpty()) "${l.name} ($tags)" else l.name
        }.toTypedArray()
        MaterialAlertDialogBuilder(this)
            .setTitle("Locations & Warehouses (${ov.locations.size})")
            .setItems(items, null)
            .setPositiveButton("Stock Transfers") { _, _ ->
                startActivity(Intent(this, StockTransfersActivity::class.java))
            }
            .setNeutralButton("Stock Adjust") { _, _ ->
                startActivity(Intent(this, StockAdjustmentsActivity::class.java))
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showCategoriesDialog(ov: MobileSettingsOverview) {
        val items = ov.categories.map { "${it.name} (${it.productCount} items)" }.toTypedArray()
        MaterialAlertDialogBuilder(this)
            .setTitle("Product Categories (${ov.categories.size})")
            .setItems(items) { _, _ ->
                startActivity(Intent(this, PriceListActivity::class.java))
            }
            .setPositiveButton("Open Price List") { _, _ ->
                startActivity(Intent(this, PriceListActivity::class.java))
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showBranchPicker() {
        val options = mutableListOf<Pair<String, String>>()
        options.add("main" to "Main Store (HQ)")
        for (b in session.getBranches()) {
            if (isRealBranch(b)) {
                options.add(b.id to b.name)
            }
        }

        val labels = options.map { it.second }.toTypedArray()
        val checkedIdx = options.indexOfFirst { it.first == session.selectedBranch }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Default Active Store / Branch")
            .setSingleChoiceItems(labels, checkedIdx) { dialog, which ->
                session.selectedBranch = options[which].first
                bindInfo()
                renderBranchesList()
                dialog.dismiss()
                Toast.makeText(this, "Switched to ${options[which].second}", Toast.LENGTH_SHORT).show()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun confirmSignOut() {
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Sign Out")
            .setMessage("Sign out of ${session.getDisplayName().ifBlank { session.getUsername() }}?")
            .setPositiveButton("Sign Out") { _, _ -> redirectToLogin() }
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun attachEscClose(dialog: AlertDialog) {
        dialog.setOnKeyListener { d, keyCode, event ->
            if (event.action == KeyEvent.ACTION_UP &&
                (keyCode == KeyEvent.KEYCODE_ESCAPE || keyCode == KeyEvent.KEYCODE_BACK)
            ) {
                d.dismiss()
                true
            } else {
                false
            }
        }
    }

    private fun redirectToLogin() {
        session.logout()
        startActivity(Intent(this, LoginActivity::class.java))
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}
