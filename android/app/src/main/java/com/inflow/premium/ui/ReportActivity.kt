package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.ReportSummary
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityReportBinding
import com.inflow.premium.databinding.ItemReportCardBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class ReportActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReportBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentDateFilter = "Today"
    private var currentCategory = "Sales" // Sales, Recent, Stock
    private var currentQuery = ""
    private var latestSummary: ReportSummary? = null

    private data class ReportDef(
        val category: String,
        val title: String,
        val desc: String,
        val iconRes: Int,
        val iconBgHex: String,
        val iconTintHex: String,
        val badgeBgHex: String,
        val badgeTextHex: String,
        val webPath: String,
        val metricProvider: (ReportSummary?) -> Pair<String, String>
    )

    private val moneyFmt = DecimalFormat("#,##0.00")

    private val reportDefs = listOf(
        ReportDef(
            category = "Sales",
            title = "Product sales ›",
            desc = "Summary or breakdown of products and how well they have been selling.",
            iconRes = R.drawable.ic_nav_product,
            iconBgHex = "#FFF7ED",
            iconTintHex = "#D97706",
            badgeBgHex = "#F1F5F9",
            badgeTextHex = "#0F172A",
            webPath = "/reports/product-sales"
        ) { s ->
            val top = s?.topProducts?.firstOrNull()
            val badge = if (top != null) "Top: $${moneyFmt.format(top.total)}" else "Top: $0.00"
            val sub = if (top != null) "• ${top.name.take(22)}" else "• Updated now"
            badge to sub
        },
        ReportDef(
            category = "Sales",
            title = "Product price list ›",
            desc = "List of products, with prices and active pricing tier rules.",
            iconRes = R.drawable.ic_wf_inventory,
            iconBgHex = "#FFF1F2",
            iconTintHex = "#E11D48",
            badgeBgHex = "#F1F5F9",
            badgeTextHex = "#0F172A",
            webPath = "/products"
        ) { _ -> "Catalog Tiers" to "• Includes Wholesale" },
        ReportDef(
            category = "Sales",
            title = "Operations ›",
            desc = "List of Sales with their statuses & open orders awaiting fulfillment.",
            iconRes = R.drawable.ic_wf_transfer,
            iconBgHex = "#EFF6FF",
            iconTintHex = "#2563EB",
            badgeBgHex = "#FEF3C7",
            badgeTextHex = "#B45309",
            webPath = "/sales"
        ) { s ->
            val openCnt = s?.openCount ?: 0
            "$openCnt Open Orders" to "• Priority routing"
        },
        ReportDef(
            category = "Sales",
            title = "Sales order summary ›",
            desc = "Summary of financial information for selected sales orders.",
            iconRes = R.drawable.ic_nav_so,
            iconBgHex = "#F8FAFC",
            iconTintHex = "#475569",
            badgeBgHex = "#F1F5F9",
            badgeTextHex = "#0F172A",
            webPath = "/reports"
        ) { s ->
            val gross = s?.grossSales ?: 0.0
            val cnt = s?.orderCount ?: 0
            "Gross: $${moneyFmt.format(gross)}" to "• $cnt Invoices"
        },
        ReportDef(
            category = "Sales",
            title = "Sales order profit ›",
            desc = "List of sales orders and their gross profit & margin analysis.",
            iconRes = R.drawable.ic_nav_report,
            iconBgHex = "#F0FDF4",
            iconTintHex = "#059669",
            badgeBgHex = "#DCFCE7",
            badgeTextHex = "#059669",
            webPath = "/reports"
        ) { s ->
            val gross = s?.grossSales ?: 0.0
            val profit = s?.grossProfit ?: 0.0
            val margin = if (gross > 0) (profit / gross) * 100.0 else 0.0
            String.format(Locale.US, "Avg Margin: %.1f%%", margin) to "• Profit $${moneyFmt.format(profit)}"
        },
        ReportDef(
            category = "Sales",
            title = "Delivery Person Assign ›",
            desc = "Assign and track delivery persons for sales orders with customer details.",
            iconRes = R.drawable.ic_wf_customer,
            iconBgHex = "#FEF2F2",
            iconTintHex = "#DC2626",
            badgeBgHex = "#EFF6FF",
            badgeTextHex = "#1D4ED8",
            webPath = "/reports/delivery"
        ) { s ->
            val paid = s?.paidTotal ?: 0.0
            "Paid: $${moneyFmt.format(paid)}" to "• Delivery Sync"
        },
        ReportDef(
            category = "Recent",
            title = "Sales by product details ›",
            desc = "Detailed itemized line transactions of products sold over time.",
            iconRes = R.drawable.ic_nav_report,
            iconBgHex = "#F1F5F9",
            iconTintHex = "#334155",
            badgeBgHex = "#F1F5F9",
            badgeTextHex = "#0F172A",
            webPath = "/reports"
        ) { _ -> "Export CSV / PDF" to "• Itemized SKU" },
        ReportDef(
            category = "Stock",
            title = "Customer order history ›",
            desc = "Complete chronological order and invoice history per customer.",
            iconRes = R.drawable.ic_wf_customer,
            iconBgHex = "#EEF2FF",
            iconTintHex = "#4F46E5",
            badgeBgHex = "#EEF2FF",
            badgeTextHex = "#4F46E5",
            webPath = "/customers"
        ) { s ->
            val unpaid = s?.unpaidBalance ?: 0.0
            "Unpaid: $${moneyFmt.format(unpaid)}" to "• Customer Profiles"
        }
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
            extraBottomScrollDp = 104
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
        binding.swipeRefresh.setOnRefreshListener { loadReport() }
        binding.btnReportBack.setOnClickListener { finish() }
        binding.btnReportRefresh.setOnClickListener { loadReport() }
        binding.btnReportMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Open Full Web Reports")
            popup.setOnMenuItemClickListener {
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .putExtra("extra_url", api.buildWebPortalUrl("/reports"))
                )
                true
            }
            popup.show()
        }

        binding.pillPeriodToday.setOnClickListener { selectPeriod("Today") }
        binding.pillPeriodWeek.setOnClickListener { selectPeriod("This Week") }
        binding.pillPeriodMonth.setOnClickListener { selectPeriod("This Month") }
        binding.pillPeriodAll.setOnClickListener { selectPeriod("All") }

        binding.tabReportSales.setOnClickListener { selectCategory("Sales") }
        binding.tabReportRecent.setOnClickListener { selectCategory("Recent") }
        binding.tabReportStock.setOnClickListener { selectCategory("Stock") }

        binding.etReportSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                currentQuery = s?.toString()?.trim().orEmpty()
                renderCards()
            }
        })

        updateBranchSubtitle()
        updatePeriodPills()
        updateCategoryTabs()
        renderCards()
        loadReport()
    }

    private fun selectPeriod(period: String) {
        currentDateFilter = period
        updatePeriodPills()
        loadReport()
    }

    private fun selectCategory(cat: String) {
        currentCategory = cat
        updateCategoryTabs()
        renderCards()
    }

    private fun stylePill(tv: TextView, active: Boolean) {
        if (active) {
            tv.setBackgroundResource(R.drawable.bg_pill_teal_solid)
            tv.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0F172A"))
            tv.setTextColor(Color.WHITE)
        } else {
            tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
            tv.backgroundTintList = null
            tv.setTextColor(Color.parseColor("#334155"))
        }
    }

    private fun updatePeriodPills() {
        stylePill(binding.pillPeriodToday, currentDateFilter == "Today")
        stylePill(binding.pillPeriodWeek, currentDateFilter == "This Week")
        stylePill(binding.pillPeriodMonth, currentDateFilter == "This Month")
        stylePill(binding.pillPeriodAll, currentDateFilter == "All")
    }

    private fun updateCategoryTabs() {
        stylePill(binding.tabReportSales, currentCategory == "Sales")
        stylePill(binding.tabReportRecent, currentCategory == "Recent")
        stylePill(binding.tabReportStock, currentCategory == "Stock")
    }

    private fun updateBranchSubtitle() {
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "all" -> "All Branches"
            branchKey == "main" || branchKey == "0" -> "Sales Reports"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        binding.tvReportHeaderSub.text = "• $branchLabel"
    }

    private fun loadReport() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                latestSummary = api.getReportsSummary(session.selectedBranch, currentDateFilter)
                renderCards()
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@ReportActivity, e.message ?: "Failed to load report", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@ReportActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun renderCards() {
        val filtered = reportDefs.filter { def ->
            val matchCat = currentCategory == "Sales" || def.category == currentCategory
            val matchQuery = currentQuery.isBlank() ||
                def.title.contains(currentQuery, ignoreCase = true) ||
                def.desc.contains(currentQuery, ignoreCase = true)
            matchCat && matchQuery
        }

        binding.tvReportShowingCount.text = "Showing ${filtered.size} reports"
        binding.llReportCards.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (def in filtered) {
            val cb = ItemReportCardBinding.inflate(inflater, binding.llReportCards, false)
            cb.tvReportTitle.text = def.title
            cb.tvReportDesc.text = def.desc
            cb.ivReportIcon.setImageResource(def.iconRes)
            cb.flReportIconBg.backgroundTintList = ColorStateList.valueOf(Color.parseColor(def.iconBgHex))
            cb.ivReportIcon.imageTintList = ColorStateList.valueOf(Color.parseColor(def.iconTintHex))

            val (badgeText, subText) = def.metricProvider(latestSummary)
            cb.tvReportMetricBadge.text = badgeText
            cb.tvReportMetricBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor(def.badgeBgHex))
            cb.tvReportMetricBadge.setTextColor(Color.parseColor(def.badgeTextHex))
            cb.tvReportSubMeta.text = subText

            cb.root.setOnClickListener {
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .putExtra("extra_url", api.buildWebPortalUrl(def.webPath))
                )
            }
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
