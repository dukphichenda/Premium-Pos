package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityReportBinding
import com.inflow.premium.databinding.ItemReportCardBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class ReportActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReportBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentDateFilter = "This Month"
    private var currentQuery = ""
    private val moneyFmt = DecimalFormat("#,##0.00")

    private data class ReportModule(
        val title: String,
        val desc: String,
        val categoryTag: String,
        val subTag: String,
        val actionText: String,
        val iconRes: Int,
        val iconBgHex: String,
        val iconTintHex: String,
        val hqOnly: Boolean = false,
        val onOpen: () -> Unit
    )

    private val modules = listOf(
        ReportModule(
            title = "Sales reports",
            desc = "Comprehensive sales volume, gross profit, and revenue breakdown across orders.",
            categoryTag = "Financial",
            subTag = "Profit & Margin",
            actionText = "Open ›",
            iconRes = R.drawable.ic_nav_report,
            iconBgHex = "#EFF6FF",
            iconTintHex = "#1D4ED8",
            onOpen = { openReportDetail(ReportDetailActivity.MODE_PROFIT) }
        ),
        ReportModule(
            title = "Delivery Person Assign",
            desc = "Assign and track delivery couriers, delivery runs, and dispatch fulfillment status.",
            categoryTag = "Operations",
            subTag = "Active Fleet",
            actionText = "Track ›",
            iconRes = R.drawable.ic_wf_transfer,
            iconBgHex = "#F0FDF4",
            iconTintHex = "#059669",
            onOpen = { openReportDetail(ReportDetailActivity.MODE_DELIVERY) }
        ),
        ReportModule(
            title = "Customer order history",
            desc = "Complete chronological order records, statements, and paid invoices per customer.",
            categoryTag = "CRM & Sales",
            subTag = "Ledger sync",
            actionText = "View ›",
            iconRes = R.drawable.ic_wf_customer,
            iconBgHex = "#EEF2FF",
            iconTintHex = "#4F46E5",
            onOpen = { startActivity(Intent(this, CustomerOrderHistoryActivity::class.java)) }
        ),
        ReportModule(
            title = "Inventory valuation",
            desc = "Current on-hand stock cost valuation, retail markup, and asset balance.",
            categoryTag = "Stock & Assets",
            subTag = "Catalog Audit",
            actionText = "Audit ›",
            iconRes = R.drawable.ic_nav_product,
            iconBgHex = "#FFF7ED",
            iconTintHex = "#D97706",
            onOpen = {
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .putExtra("extra_url", api.buildWebPortalUrl("/reports/view/inventory-valuation"))
                )
            }
        ),
        ReportModule(
            title = "Branch sales summary",
            desc = "Comparison of branch sales, items sold, and branch costing calculations.",
            categoryTag = "Multi-Branch",
            subTag = "Consolidated",
            actionText = "Compare ›",
            iconRes = R.drawable.ic_wf_branches,
            iconBgHex = "#ECFEFF",
            iconTintHex = "#0891B2",
            onOpen = { openReportDetail(ReportDetailActivity.MODE_BRANCH) }
        ),
        ReportModule(
            title = "HQ branch earnings",
            desc = "HQ earnings breakdown: Qty Sold × (Branch Cost - HQ Costing).",
            categoryTag = "HQ Executive",
            subTag = "Royalties",
            actionText = "Formula ›",
            iconRes = R.drawable.ic_nav_home,
            iconBgHex = "#FAF5FF",
            iconTintHex = "#7C3AED",
            hqOnly = true,
            onOpen = { openReportDetail(ReportDetailActivity.MODE_HQ) }
        )
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityReportBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.REPORT)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollReport,
            extraTopDp = 4,
            extraBottomScrollDp = 108
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollReport.paddingTop != topH) {
                binding.scrollReport.setPadding(
                    binding.scrollReport.paddingLeft,
                    topH,
                    binding.scrollReport.paddingRight,
                    binding.scrollReport.paddingBottom
                )
            }
        }

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadSummary() }
        binding.btnReportFilter.setOnClickListener { showPeriodPicker() }
        binding.btnReportRefresh.setOnClickListener { loadSummary() }
        binding.btnReportWebSource.setOnClickListener { openWebReports() }
        binding.btnReportMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Period: $currentDateFilter")
            popup.menu.add(0, 2, 2, "Open Full Web Reports")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> showPeriodPicker()
                    2 -> openWebReports()
                }
                true
            }
            popup.show()
        }

        renderModules()
        loadSummary()
    }

    private fun openReportDetail(mode: String) {
        startActivity(
            Intent(this, ReportDetailActivity::class.java)
                .putExtra(ReportDetailActivity.EXTRA_MODE, mode)
                .putExtra(ReportDetailActivity.EXTRA_PERIOD, currentDateFilter)
        )
    }

    private fun openWebReports() {
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("extra_url", api.buildWebPortalUrl("/reports"))
        )
    }

    private fun showPeriodPicker() {
        val opts = arrayOf("Today", "Yesterday", "This Week", "This Month", "Last 30 Days", "All")
        val idx = opts.indexOf(currentDateFilter).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Executive Overview Period")
            .setSingleChoiceItems(opts, idx) { d, which ->
                currentDateFilter = opts[which]
                binding.btnReportFilter.text = "$currentDateFilter ⌄"
                d.dismiss()
                loadSummary()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun loadSummary() {
        binding.swipeRefresh.isRefreshing = true
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "all" -> "All Stores"
            branchKey == "main" || branchKey == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        binding.tvExecScope.text = branchLabel

        uiScope.launch {
            try {
                val s = api.getReportsSummary(branchKey, currentDateFilter)
                binding.tvExecGrossSales.text = "$${moneyFmt.format(s.grossSales)}"
                binding.tvExecPaidSub.text = "${s.paidCount} paid"
                binding.tvExecPendingVal.text = "$${moneyFmt.format(s.openSales)}"
                binding.tvExecOpenSub.text = "${s.openCount} orders"
                binding.tvExecOrderCount.text = "${s.orderCount} total"
                binding.tvReportPeriodBadge.text = "• $currentDateFilter"
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@ReportActivity, e.message ?: "Failed to load overview", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@ReportActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun isBranchLogin(): Boolean =
        !session.isMainAdmin() || session.getUserBranchId() != null

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            renderModules()
        }
    }

    private fun renderModules() {
        val branchRestricted = isBranchLogin()
        val filtered = modules.filter { m ->
            if (m.hqOnly && branchRestricted) return@filter false
            currentQuery.isBlank() ||
                m.title.contains(currentQuery, ignoreCase = true) ||
                m.desc.contains(currentQuery, ignoreCase = true) ||
                m.categoryTag.contains(currentQuery, ignoreCase = true)
        }
        binding.tvReportModuleCount.text = "${filtered.size} Core Modules"
        binding.llReportCards.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (m in filtered) {
            val cb = ItemReportCardBinding.inflate(inflater, binding.llReportCards, false)
            cb.tvReportTitle.text = "${m.title}  ›"
            cb.tvReportDesc.text = m.desc
            cb.ivReportIcon.setImageResource(m.iconRes)
            cb.flReportIconBg.backgroundTintList = ColorStateList.valueOf(Color.parseColor(m.iconBgHex))
            cb.ivReportIcon.imageTintList = ColorStateList.valueOf(Color.parseColor(m.iconTintHex))
            cb.tvReportMetricBadge.text = m.categoryTag
            cb.tvReportMetricBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#F1F5F9"))
            cb.tvReportMetricBadge.setTextColor(Color.parseColor("#334155"))
            cb.tvReportSubMeta.text = "${m.subTag}   •   ${m.actionText}"
            cb.root.setOnClickListener { m.onOpen() }
            binding.llReportCards.addView(cb.root)
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
