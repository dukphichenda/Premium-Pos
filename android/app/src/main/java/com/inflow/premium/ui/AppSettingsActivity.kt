package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
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

    private data class SettingItemDef(
        val title: String,
        val subtitle: String,
        val iconRes: Int,
        val bgHex: String,
        val webPath: String,
        val adminOnly: Boolean = false
    )

    private val companyDefs = listOf(
        SettingItemDef("Company Profile", "Address, tax ID, contacts & branches", R.drawable.ic_wf_branches, "#EA580C", "/settings?tab=tabCompany"),
        SettingItemDef("Pricing & Currency", "KHR rate, price tiers & multi-currency", R.drawable.ic_wf_expenses, "#059669", "/settings?tab=tabPricing"),
        SettingItemDef("Decimal Precision", "Unit pricing, tax & currency rounding", R.drawable.ic_nav_report, "#0284C7", "/settings?tab=tabDecimals"),
        SettingItemDef("Invoice Customization", "Headers, logos, thermal 80mm slip layout", R.drawable.ic_nav_so, "#0D9488", "/settings?tab=tabInvoice"),
        SettingItemDef("Users & Permissions", "Cashier access, admin roles, audit log", R.drawable.ic_wf_customer, "#7C3AED", "/settings?tab=tabUsers", adminOnly = true),
        SettingItemDef("Import & Export Data", "Excel/CSV product catalog & customer lists", R.drawable.ic_wf_transfer, "#4F46E5", "/settings?tab=tabImport"),
        SettingItemDef("Backup & Restore (.sql)", "Daily cloud snapshot, local archive restore", R.drawable.ic_nav_settings, "#475569", "/settings?tab=tabBackup")
    )

    private val systemDefs = listOf(
        SettingItemDef("Locations & Warehouses", "Warehouse hubs & branch fulfillment", R.drawable.ic_wf_branches, "#0891B2", "/locations"),
        SettingItemDef("Categories", "Product categories & price table styles", R.drawable.ic_nav_product, "#D97706", "/categories"),
        SettingItemDef("Import Data Wizard", "Import orders, customers & inventory", R.drawable.ic_wf_po, "#10B981", "/data/import"),
        SettingItemDef("Export Data Center", "Download Excel & CSV backups", R.drawable.ic_nav_report, "#6366F1", "/data/export"),
        SettingItemDef("inFlow SQL Migration", "Connect & migrate legacy SQL database", R.drawable.ic_wf_vendor, "#64748B", "/settings/migration")
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

        bindInfo()
        renderBranchesList()
        renderSettingsGroup(binding.llCompanySettings, companyDefs)
        renderSettingsGroup(binding.llSystemPrefs, systemDefs)

        binding.tvActiveStoreChip.setOnClickListener {
            if (session.isMainAdmin()) showBranchPicker()
        }

        binding.btnSettingSync.setOnClickListener {
            binding.btnSettingSync.isEnabled = false
            uiScope.launch {
                try {
                    api.bootstrap()
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
            branchKey == "all" -> "All Branches"
            branchKey == "main" || branchKey == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        binding.tvSettingUser.text = "$name (@${session.getUsername()})"
        val host = session.baseUrl.removePrefix("https://").removePrefix("http://").trimEnd('/')
        val df = DecimalFormat("#,##0")
        binding.tvSettingServerRate.text = "$host • 1 USD = ${df.format(Math.round(session.defaultKhrRate))} KHR"
        binding.tvSettingRole.text = "• Active Store: $branchLabel"
        binding.tvActiveStoreChip.text = branchLabel
        val verName = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "3.1.0"
        } catch (_: Exception) {
            "3.1.0"
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
                if (b.id != "0" && b.id != "main") {
                    options.add(Triple(b.id, b.name, "Outlet Branch • Isolated Scope"))
                }
            }
            options.add(Triple("all", "All Branches (Consolidated)", "View combined outlets"))
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
            val isSelected = current == id || (id == "main" && (current == "0" || current.isBlank()))
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
            rb.root.setOnClickListener { openWebPath(item.webPath) }
            container.addView(rb.root)
        }
    }

    private fun showBranchPicker() {
        val options = mutableListOf<Pair<String, String>>()
        options.add("main" to "Main Store (HQ)")
        for (b in session.getBranches()) {
            if (b.id != "0" && b.id != "main") {
                options.add(b.id to b.name)
            }
        }
        options.add("all" to "All Branches")

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
