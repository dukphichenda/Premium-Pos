package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.view.Gravity
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.CategoryStockSlice
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityHomeBinding
import com.inflow.premium.databinding.DialogQuickCustomerBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class HomeActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHomeBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private val detailLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                loadDashboard()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityHomeBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        if (!session.isMainAdmin()) {
            session.selectedBranch = session.getUserBranchId()?.toString() ?: "main"
        }

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.HOME)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = null,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollHome,
            extraTopDp = 12,
            extraBottomScrollDp = 104
        )

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadDashboard() }

        setupActions()
        loadDashboard()
    }

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            loadDashboard()
        }
    }

    private fun setupActions() {
        binding.btnHomeBranchSwitch.setOnClickListener {
            if (session.isMainAdmin()) showBranchPicker()
        }

        val openNewSo = View.OnClickListener {
            detailLauncher.launch(
                Intent(this, SalesOrderDetailActivity::class.java)
                    .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, 0)
            )
        }
        binding.btnActionNewSo.setOnClickListener(openNewSo)
        binding.wfSalesOrder.setOnClickListener { switchToTab(SalesOrdersActivity::class.java) }

        binding.btnActionNewPo.setOnClickListener { openWebPath("/purchases/new") }
        binding.wfPo.setOnClickListener { startActivity(Intent(this, PurchaseOrdersActivity::class.java)) }

        binding.btnActionNewCustomer.setOnClickListener { openQuickAddCustomerDialog() }

        binding.wfInventory.setOnClickListener { switchToTab(ProductsActivity::class.java) }
        binding.cardKpiProducts.setOnClickListener { switchToTab(ProductsActivity::class.java) }

        binding.wfPriceList.setOnClickListener { startActivity(Intent(this, PriceListActivity::class.java)) }
        binding.wfCustomer.setOnClickListener { startActivity(Intent(this, CustomersActivity::class.java)) }
        binding.wfExpenses.setOnClickListener { startActivity(Intent(this, MonthlyExpensesActivity::class.java)) }
        binding.wfReports.setOnClickListener { switchToTab(ReportActivity::class.java) }
        binding.wfTransfer.setOnClickListener { startActivity(Intent(this, StockTransfersActivity::class.java)) }
        binding.wfStockAdjust.setOnClickListener { startActivity(Intent(this, StockAdjustmentsActivity::class.java)) }

        binding.cardKpiMonthSales.setOnClickListener { switchToTab(SalesOrdersActivity::class.java) }
        binding.cardKpiReceivables.setOnClickListener { switchToTab(SalesOrdersActivity::class.java) }
        binding.cardKpiLowStock.setOnClickListener { startActivity(Intent(this, CurrentStockActivity::class.java)) }
        binding.cardKpiPendingPos.setOnClickListener { openWebPath("/purchase-orders") }
        binding.cardBranchPerformance.setOnClickListener { openWebPath("/branches") }
    }

    private fun switchToTab(cls: Class<*>) {
        startActivity(
            Intent(this, cls).addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        )
        @Suppress("DEPRECATION")
        overridePendingTransition(0, 0)
    }

    private fun openWebPath(path: String) {
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("extra_url", api.buildWebPortalUrl(path))
        )
    }

    private fun showBranchPicker() {
        if (session.selectedBranch == "all") {
            session.selectedBranch = "main"
        }

        val options = mutableListOf<Pair<String, String>>()
        options.add("main" to "Main Store (HQ)")
        for (b in session.getBranches()) {
            val lower = b.name.lowercase()
            if (b.id != "0" && b.id != "main" && !b.code.equals("ALL", true) &&
                !lower.contains("all stores") && !lower.contains("all branch") && !lower.contains("consolidated")
            ) {
                options.add(b.id to b.name)
            }
        }

        val labels = options.map { it.second }.toTypedArray()
        val checkedIdx = options.indexOfFirst { it.first == session.selectedBranch }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Select Store / Branch")
            .setSingleChoiceItems(labels, checkedIdx) { dialog, which ->
                session.selectedBranch = options[which].first
                dialog.dismiss()
                loadDashboard()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun loadDashboard() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val dash = api.getDashboard(session.selectedBranch)
                val moneyFmt = DecimalFormat("#,##0.00")

                val badgeRaw = dash.storeBadge.trim().uppercase(Locale.US)
                val shortCode = when {
                    session.selectedBranch == "main" || dash.storeName.contains("HQ", ignoreCase = true) -> "HQ"
                    session.selectedBranch == "all" -> "ALL"
                    badgeRaw.isNotBlank() && badgeRaw.length <= 4 -> badgeRaw
                    else -> dash.storeName.trim().take(3).uppercase(Locale.US).ifBlank { "BR" }
                }
                binding.tvHomeBranchCode.text = shortCode
                val shortWh = dash.fulfillmentName.removePrefix("Main ").trim().ifBlank { dash.fulfillmentName }
                binding.tvMetaFulfillment.text = "📍 $shortWh"
                binding.tvMetaCatalog.text = "📦 ${dash.totalProducts} Items"
                binding.tvMetaBranches.text = "🏢 ${dash.activeBranchesCount} Outlets"

                binding.tvKpiInvValue.text = "$${moneyFmt.format(dash.inventoryValuation)}"
                binding.tvKpiProducts.text = "${dash.totalProducts} items"
                binding.tvKpiMonthTitle.text = "MONTH SALES (${dash.storeBadge.uppercase(Locale.US)})"
                binding.tvKpiMonthSales.text = "$${moneyFmt.format(dash.monthSalesTotal)}"
                binding.tvKpiMonthSub.text =
                    "Paid: $${moneyFmt.format(dash.monthPaidTotal)} • ${dash.openCount} open"
                binding.tvKpiReceivables.text = "$${moneyFmt.format(dash.totalReceivables)}"
                binding.tvKpiLowStock.text = dash.lowStockCount.toString()
                binding.tvKpiPendingPos.text = "${dash.pendingPurchaseOrders} POs"

                binding.tvChartBadge.text =
                    if (session.selectedBranch == "main") "HQ DIRECT SALES" else dash.storeBadge.uppercase(Locale.US)
                binding.chartMonthlySales.setData(dash.monthlyChart)
                binding.chartCategoryDonut.setData(dash.categoryStock)
                renderCategoryLegend(dash.categoryStock)
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@HomeActivity, e.message ?: "Failed to load dashboard", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@HomeActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun renderCategoryLegend(slices: List<CategoryStockSlice>) {
        binding.llCategoryLegend.removeAllViews()
        val colors = CategoryDonutView.COLORS
        for (i in slices.indices) {
            val s = slices[i]
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = (4 * resources.displayMetrics.density).toInt() }
            }

            val dotSize = (8 * resources.displayMetrics.density).toInt()
            val dot = View(this).apply {
                layoutParams = LinearLayout.LayoutParams(dotSize, dotSize).apply {
                    marginEnd = (6 * resources.displayMetrics.density).toInt()
                }
                background = GradientDrawable().apply {
                    shape = GradientDrawable.RECTANGLE
                    cornerRadius = 2 * resources.displayMetrics.density
                    setColor(colors[i % colors.size])
                }
            }

            val label = TextView(this).apply {
                text = "${s.name} (${Math.round(s.pct)}%)"
                setTextColor(ContextCompat.getColor(this@HomeActivity, R.color.black))
                textSize = 10.5f
                maxLines = 1
            }

            row.addView(dot)
            row.addView(label)
            binding.llCategoryLegend.addView(row)
        }
    }

    private fun openQuickAddCustomerDialog() {
        val qb = DialogQuickCustomerBinding.inflate(layoutInflater)
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Quick Add Customer")
            .setView(qb.root)
            .setPositiveButton("Create Customer", null)
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()

        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.setOnShowListener {
            val btnOk = dlg.getButton(AlertDialog.BUTTON_POSITIVE)
            btnOk.setOnClickListener {
                val name = qb.etQcName.text?.toString()?.trim().orEmpty()
                if (name.isBlank()) {
                    Toast.makeText(this, "Customer name is required", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                val bId = session.selectedBranch.toIntOrNull()
                btnOk.isEnabled = false
                uiScope.launch {
                    try {
                        val created = api.quickAddCustomer(
                            name = name,
                            contactName = qb.etQcContact.text?.toString()?.trim().orEmpty(),
                            phone = qb.etQcPhone.text?.toString()?.trim().orEmpty(),
                            address = qb.etQcAddress.text?.toString()?.trim().orEmpty(),
                            branchId = bId
                        )
                        dlg.dismiss()
                        Toast.makeText(
                            this@HomeActivity,
                            "Customer added: ${created.name}",
                            Toast.LENGTH_SHORT
                        ).show()
                    } catch (e: Exception) {
                        btnOk.isEnabled = true
                        Toast.makeText(
                            this@HomeActivity,
                            e.message ?: "Failed to create customer",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            }
        }
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
