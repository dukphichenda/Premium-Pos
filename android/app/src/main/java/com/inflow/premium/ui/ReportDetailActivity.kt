package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.DeliveryOrderItem
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityReportDetailBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class ReportDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReportDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var mode = MODE_PROFIT
    private var period = "This Month"
    private var query = ""
    private var searchJob: Job? = null
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val qtyFmt = DecimalFormat("#,##0.##")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityReportDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        mode = intent.getStringExtra(EXTRA_MODE) ?: MODE_PROFIT
        period = intent.getStringExtra(EXTRA_PERIOD) ?: "This Month"

        if (mode == MODE_HQ && (!session.isMainAdmin() || session.getUserBranchId() != null)) {
            Toast.makeText(this, "Restricted to Headquarters only", Toast.LENGTH_SHORT).show()
            finish()
            return
        }

        binding.tvRepDetTitle.text = when (mode) {
            MODE_DELIVERY -> "Delivery Assign"
            MODE_BRANCH -> "Sales Summary"
            MODE_HQ -> "HQ Earnings"
            else -> "Profit Report"
        }

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = null,
            bottomScrimView = null,
            scrollableView = binding.scrollRepDetail,
            extraTopDp = 4,
            extraBottomScrollDp = 32
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollRepDetail.paddingTop != topH) {
                binding.scrollRepDetail.setPadding(
                    binding.scrollRepDetail.paddingLeft,
                    topH,
                    binding.scrollRepDetail.paddingRight,
                    binding.scrollRepDetail.paddingBottom
                )
            }
        }

        binding.btnRepDetBack.setOnClickListener { finish() }
        binding.btnRepDetRefresh.setOnClickListener { loadData() }
        binding.swipeRefresh.setOnRefreshListener { loadData() }
        binding.btnRepDetFilter.setOnClickListener { showPeriodPicker() }
        binding.btnRepDetMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Period: $period")
            popup.menu.add(0, 2, 2, "Open in Web Reports")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> showPeriodPicker()
                    2 -> {
                        val key = when (mode) {
                            MODE_DELIVERY -> "delivery-person-assign"
                            MODE_BRANCH -> "branch-sales-summary"
                            MODE_HQ -> "hq-branch-earnings"
                            else -> "sales-order-profit"
                        }
                        startActivity(
                            Intent(this, MainActivity::class.java)
                                .putExtra("extra_url", api.buildWebPortalUrl("/reports/view/$key"))
                        )
                    }
                }
                true
            }
            popup.show()
        }

        binding.etRepDetSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                if (q == query) return
                query = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    loadData()
                }
            }
        })

        loadData()
    }

    private fun showPeriodPicker() {
        val opts = arrayOf("Today", "Yesterday", "This Week", "This Month", "Last 30 Days", "All")
        val idx = opts.indexOf(period).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Report Period")
            .setSingleChoiceItems(opts, idx) { d, which ->
                period = opts[which]
                d.dismiss()
                loadData()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun loadData() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                when (mode) {
                    MODE_PROFIT -> renderProfit()
                    MODE_DELIVERY -> renderDelivery()
                    MODE_BRANCH -> renderBranchSummary(false)
                    MODE_HQ -> renderBranchSummary(true)
                }
            } catch (e: Exception) {
                Toast.makeText(this@ReportDetailActivity, e.message ?: "Failed to load report", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private suspend fun renderProfit() {
        val res = api.getProfitReport(session.selectedBranch, period, query)
        binding.tvRepHeroLabel.text = "TOTAL GROSS PROFIT"
        binding.tvRepHeroValue.text = "$${moneyFmt.format(res.grossProfit)}"
        binding.tvRepHeroBadge.text = String.format(Locale.US, "+%.1f%% margin", res.marginPct)
        binding.tvRepSub1Label.text = "Total Sales"
        binding.tvRepSub1Val.text = "$${moneyFmt.format(res.totalSales)}"
        binding.tvRepSub2Label.text = "Total Costing"
        binding.tvRepSub2Val.text = "$${moneyFmt.format(res.totalCost)}"
        binding.tvRepSectionTitle.text = "ORDER PROFIT BREAKDOWN"
        binding.tvRepSectionCount.text = "${res.paidCount} Paid / ${res.totalOrders} Orders"

        binding.llRepDetailRows.removeAllViews()
        for (o in res.orders) {
            val card = makeCard()
            val inner = makeCol(12)
            val row1 = makeRow()
            row1.addView(makeBold("${o.orderNumber}  •  ${o.orderDate}", "#0F172A", 13f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row1.addView(makePill(if (o.isPaid) "✓ Paid • ${o.paymentMethod}" else "Open", if (o.isPaid) "#059669" else "#EA580C", if (o.isPaid) "#DCFCE7" else "#FFF7ED"))
            inner.addView(row1)
            inner.addView(makeBold(o.customerName, "#0F172A", 13.5f).apply {
                layoutParams = lpWrap(top = 6)
            })
            val foot = makeRow().apply { layoutParams = lpMatch(top = 8) }
            foot.addView(makeMuted("Sales $${moneyFmt.format(o.sales)}  |  Cost $${moneyFmt.format(o.cost)}", 12f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            val profColor = if (o.profit >= 0) "#059669" else "#DC2626"
            val sign = if (o.profit >= 0) "+" else "-"
            foot.addView(makeBold("$sign$${moneyFmt.format(kotlin.math.abs(o.profit))}", profColor, 13.5f))
            inner.addView(foot)
            card.addView(inner)
            card.setOnClickListener {
                startActivity(Intent(this, SalesOrderDetailActivity::class.java).putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, o.id))
            }
            binding.llRepDetailRows.addView(card)
        }
    }

    private suspend fun renderDelivery() {
        val res = api.getDeliveryReport(session.selectedBranch, period, query)
        binding.tvRepHeroLabel.text = "TOTAL ORDERS TO DISPATCH"
        binding.tvRepHeroValue.text = "${res.totalOrders} orders  •  $${moneyFmt.format(res.totalSales)}"
        binding.tvRepHeroBadge.text = period
        binding.tvRepSub1Label.text = "Assigned"
        binding.tvRepSub1Val.text = "${res.assignedCount} ✓ Active"
        binding.tvRepSub2Label.text = "Unassigned"
        binding.tvRepSub2Val.text = "${res.unassignedCount} Pending"
        binding.tvRepSectionTitle.text = "ORDERS TO DISPATCH"
        binding.tvRepSectionCount.text = "${res.orders.size} orders"

        binding.llRepDetailRows.removeAllViews()
        for (o in res.orders) {
            val card = makeCard()
            val inner = makeCol(12)
            val row1 = makeRow()
            row1.addView(makeBold("${o.orderNumber}  •  ${o.orderDate}", "#4F46E5", 13.5f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row1.addView(makeBold("$${moneyFmt.format(o.totalAmount)}", "#0F172A", 14.5f))
            inner.addView(row1)
            inner.addView(makeBold(o.customerName, "#0F172A", 13f).apply { layoutParams = lpWrap(top = 6) })
            if (o.phone.isNotBlank() || o.address.isNotBlank()) {
                inner.addView(makeMuted("${o.phone}  ${o.address}".trim(), 11.5f).apply { layoutParams = lpWrap(top = 2) })
            }
            val assignRow = makeRow().apply { layoutParams = lpMatch(top = 8) }
            assignRow.addView(makeMuted("Driver Assign", 12f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            val driverBtn = makePill(
                if (o.deliveryMan.isBlank()) "🛵 -- Unassigned -- ⌄" else "🛵 ${o.deliveryMan} ⌄",
                if (o.deliveryMan.isBlank()) "#B45309" else "#059669",
                if (o.deliveryMan.isBlank()) "#FEF3C7" else "#DCFCE7"
            )
            driverBtn.setOnClickListener { showDriverPicker(o) }
            assignRow.addView(driverBtn)
            inner.addView(assignRow)
            card.addView(inner)
            binding.llRepDetailRows.addView(card)
        }
    }

    private fun showDriverPicker(order: DeliveryOrderItem) {
        val drivers = listOf("Unassigned") + session.getDeliveryMen().map { it.name }
        val idx = drivers.indexOfFirst {
            if (order.deliveryMan.isBlank()) it == "Unassigned" else it.equals(order.deliveryMan, true)
        }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Assign Driver • ${order.orderNumber}")
            .setSingleChoiceItems(drivers.toTypedArray(), idx) { d, which ->
                val chosen = if (which == 0) "" else drivers[which]
                d.dismiss()
                uiScope.launch {
                    try {
                        api.assignDeliveryMan(order.id, chosen)
                        Toast.makeText(this@ReportDetailActivity, "Driver updated", Toast.LENGTH_SHORT).show()
                        loadData()
                    } catch (e: Exception) {
                        Toast.makeText(this@ReportDetailActivity, e.message ?: "Assign failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private suspend fun renderBranchSummary(hqMode: Boolean) {
        val branchParam = if (hqMode) "all" else session.selectedBranch
        val res = api.getBranchSummaryReport(branchParam, period, query, if (hqMode) "hq" else "branch")

        if (hqMode) {
            val margin = if (res.totalBranchCost > 0) (res.totalHqEarning / res.totalBranchCost) * 100.0 else 0.0
            binding.tvRepHeroLabel.text = "HQ NET EARNINGS"
            binding.tvRepHeroValue.text = "$${moneyFmt.format(res.totalHqEarning)}"
            binding.tvRepHeroBadge.text = String.format(Locale.US, "↑ +%.1f%% margin", margin)
            binding.tvRepSub1Label.text = "Total Billed"
            binding.tvRepSub1Val.text = "$${moneyFmt.format(res.totalBranchCost)}"
            binding.tvRepSub2Label.text = "HQ Costing"
            binding.tvRepSub2Val.text = "$${moneyFmt.format(res.totalHqCost)}"
            binding.tvRepSectionTitle.text = "ITEM EARNINGS BREAKDOWN"
        } else {
            val margin = if (res.totalSales > 0) (res.totalBranchProfit / res.totalSales) * 100.0 else 0.0
            binding.tvRepHeroLabel.text = "TOTAL SALES REVENUE"
            binding.tvRepHeroValue.text = "$${moneyFmt.format(res.totalSales)}"
            binding.tvRepHeroBadge.text = String.format(Locale.US, "+%.1f%% profit", margin)
            binding.tvRepSub1Label.text = "Branch Cost"
            binding.tvRepSub1Val.text = "$${moneyFmt.format(res.totalBranchCost)}"
            binding.tvRepSub2Label.text = "Qty Sold"
            binding.tvRepSub2Val.text = "${qtyFmt.format(res.totalQty)} pcs"
            binding.tvRepSectionTitle.text = "SOLD PRODUCTS"
        }
        binding.tvRepSectionCount.text = "${res.items.size} items"

        binding.llRepDetailRows.removeAllViews()
        for (it in res.items) {
            val card = makeCard()
            val inner = makeCol(12)
            val row1 = makeRow()
            row1.addView(makePill(it.sku, "#4338CA", "#EEF2FF"))
            row1.addView(makePill(it.categoryName, "#475569", "#F1F5F9").apply {
                (layoutParams as? LinearLayout.LayoutParams)?.marginStart = dp(6)
            })
            row1.addView(View(this).apply { layoutParams = LinearLayout.LayoutParams(0, 1, 1f) })
            val delta = if (hqMode) it.hqEarning else it.branchProfit
            val sign = if (delta >= 0) "+" else "-"
            val color = if (delta >= 0) "#059669" else "#DC2626"
            val bg = if (delta >= 0) "#DCFCE7" else "#FEE2E2"
            row1.addView(makePill("$sign$${moneyFmt.format(kotlin.math.abs(delta))}", color, bg))
            inner.addView(row1)

            inner.addView(makeBold(it.productName, "#0F172A", 13f).apply { layoutParams = lpWrap(top = 6) })
            val cases = if (it.ratio > 1) it.qtySold / it.ratio else it.qtySold
            val metricsText = if (hqMode) {
                "Qty: ${qtyFmt.format(it.qtySold)} ${it.uom} (${String.format(Locale.US, "%.1f", cases)} cs)  •  Billed $${moneyFmt.format(it.branchCost)}  |  HQ $${moneyFmt.format(it.hqCost)}"
            } else {
                "Qty: ${qtyFmt.format(it.qtySold)} ${it.uom}  •  Sales $${moneyFmt.format(it.salesAmount)}  |  Cost $${moneyFmt.format(it.branchCost)}"
            }
            inner.addView(makeMuted(metricsText, 11.5f).apply { layoutParams = lpWrap(top = 6) })
            card.addView(inner)
            binding.llRepDetailRows.addView(card)
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()
    private fun lpWrap(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { topMargin = dp(top) }
    private fun lpMatch(top: Int = 0) = lpWrap(top)
    private fun makeCard() = MaterialCardView(this).apply {
        setCardBackgroundColor(Color.WHITE)
        radius = dp(14).toFloat()
        cardElevation = dp(1).toFloat()
        strokeColor = Color.parseColor("#E2E8F0")
        strokeWidth = dp(1)
        layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(8) }
    }
    private fun makeCol(padDp: Int) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(padDp), dp(padDp), dp(padDp), dp(padDp))
    }
    private fun makeRow() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
    }
    private fun makeBold(txt: String, hex: String, sp: Float) = TextView(this).apply {
        text = txt
        setTextColor(Color.parseColor(hex))
        textSize = sp
        setTypeface(null, android.graphics.Typeface.BOLD)
    }
    private fun makeMuted(txt: String, sp: Float) = TextView(this).apply {
        text = txt
        setTextColor(Color.parseColor("#64748B"))
        textSize = sp
    }
    private fun makePill(txt: String, fgHex: String, bgHex: String) = TextView(this).apply {
        text = txt
        setTextColor(Color.parseColor(fgHex))
        setBackgroundResource(R.drawable.bg_pill_emerald_dark)
        backgroundTintList = ColorStateList.valueOf(Color.parseColor(bgHex))
        setPadding(dp(8), dp(3), dp(8), dp(3))
        textSize = 11f
        setTypeface(null, android.graphics.Typeface.BOLD)
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_MODE = "extra_mode"
        const val EXTRA_PERIOD = "extra_period"
        const val MODE_PROFIT = "profit"
        const val MODE_DELIVERY = "delivery"
        const val MODE_BRANCH = "branch"
        const val MODE_HQ = "hq"
    }
}
