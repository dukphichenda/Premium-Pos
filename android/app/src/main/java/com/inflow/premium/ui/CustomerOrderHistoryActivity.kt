package com.inflow.premium.ui

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.CustomerHistoryOrder
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityCustomerOrderHistoryBinding
import com.inflow.premium.databinding.ItemCustomerHistoryOrderBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class CustomerOrderHistoryActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCustomerOrderHistoryBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: CustomerHistoryAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var period = "This Month"
    private var statusFilter = "All"
    private var paidByFilter = "All"
    private var query = ""
    private var currentPage = 1
    private var totalPages = 1
    private var paymentMethods: List<String> = emptyList()
    private var searchJob: Job? = null
    private val moneyFmt = DecimalFormat("#,##0.00")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityCustomerOrderHistoryBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = null,
            bottomScrimView = null,
            scrollableView = binding.scrollCustOrderHistory,
            extraTopDp = 4,
            extraBottomScrollDp = 24
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollCustOrderHistory.paddingTop != topH) {
                binding.scrollCustOrderHistory.setPadding(
                    binding.scrollCustOrderHistory.paddingLeft,
                    topH,
                    binding.scrollCustOrderHistory.paddingRight,
                    binding.scrollCustOrderHistory.paddingBottom
                )
            }
        }

        adapter = CustomerHistoryAdapter { o ->
            startActivity(
                Intent(this, SalesOrderDetailActivity::class.java)
                    .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, o.id)
            )
        }
        binding.rvCohOrders.layoutManager = LinearLayoutManager(this)
        binding.rvCohOrders.adapter = adapter

        binding.btnCohBack.setOnClickListener { finish() }
        binding.btnCohRefresh.setOnClickListener { loadReport() }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadReport() }

        binding.chipCohStatus.setOnClickListener { pickStatus() }
        binding.chipCohPaidBy.setOnClickListener { pickPaidBy() }
        binding.chipCohPeriod.setOnClickListener { pickPeriod() }
        binding.chipCohBranch.setOnClickListener {
            if (session.isMainAdmin()) pickBranch()
        }
        updateBranchChipLabel()

        binding.btnCohClearSearch.setOnClickListener { binding.etCohSearch.setText("") }
        binding.btnCohPickCustomer.setOnClickListener { showCustomerPicker() }
        binding.etCohSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnCohClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == query) return
                query = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    currentPage = 1
                    loadReport()
                }
            }
        })

        binding.btnCohPrevPage.setOnClickListener {
            if (currentPage > 1) {
                currentPage -= 1
                loadReport()
            }
        }
        binding.btnCohNextPage.setOnClickListener {
            if (currentPage < totalPages) {
                currentPage += 1
                loadReport()
            }
        }
        binding.btnCohExport.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra("extra_url", api.buildWebPortalUrl("/reports/view/customer-order-history"))
            )
        }

        loadReport()
    }

    private fun updateBranchChipLabel() {
        val key = session.selectedBranch
        val label = when {
            key == "all" -> "All Stores"
            key == "main" || key == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == key }?.name ?: "Branch #$key"
        }
        binding.chipCohBranch.text = "🏪 $label"
    }

    private fun pickStatus() {
        val opts = arrayOf("All", "Open", "Paid")
        val idx = opts.indexOf(statusFilter).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Order Status")
            .setSingleChoiceItems(opts, idx) { dlg, which ->
                statusFilter = opts[which]
                binding.chipCohStatus.text = "🎛 Status: $statusFilter"
                currentPage = 1
                dlg.dismiss()
                loadReport()
            }
            .show()
    }

    private fun pickPaidBy() {
        val opts = listOf("All") + paymentMethods
        val idx = opts.indexOf(paidByFilter).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Payment Method")
            .setSingleChoiceItems(opts.toTypedArray(), idx) { dlg, which ->
                paidByFilter = opts[which]
                binding.chipCohPaidBy.text = "Paid By: $paidByFilter ⌄"
                currentPage = 1
                dlg.dismiss()
                loadReport()
            }
            .show()
    }

    private fun pickPeriod() {
        val opts = arrayOf("Today", "Yesterday", "This Week", "This Month", "Last 30 Days", "All")
        val idx = opts.indexOf(period).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Report Period")
            .setSingleChoiceItems(opts, idx) { dlg, which ->
                period = opts[which]
                binding.chipCohPeriod.text = "📅 $period"
                currentPage = 1
                dlg.dismiss()
                loadReport()
            }
            .show()
    }

    private fun pickBranch() {
        val options = mutableListOf("main" to "Main Store (HQ)")
        for (b in session.getBranches()) {
            if (b.id != "0" && b.id != "main") options.add(b.id to b.name)
        }
        options.add("all" to "All Branches")
        val labels = options.map { it.second }.toTypedArray()
        val idx = options.indexOfFirst { it.first == session.selectedBranch }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Store / Branch")
            .setSingleChoiceItems(labels, idx) { dlg, which ->
                session.selectedBranch = options[which].first
                updateBranchChipLabel()
                currentPage = 1
                dlg.dismiss()
                loadReport()
            }
            .show()
    }

    private fun showCustomerPicker() {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(10), dp(16), dp(8))
        }
        val et = android.widget.EditText(this).apply {
            hint = "Filter customer name or phone..."
            setSingleLine(true)
            setBackgroundResource(R.drawable.bg_product_thumb)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            textSize = 13.5f
        }
        val scroll = androidx.core.widget.NestedScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(300)
            ).apply { topMargin = dp(8) }
        }
        val listCol = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(listCol)
        col.addView(et)
        col.addView(scroll)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Select Customer")
            .setView(col)
            .setNeutralButton("All Customers") { _, _ ->
                binding.etCohSearch.setText("")
            }
            .setNegativeButton("Close", null)
            .create()

        var pickJob: Job? = null
        fun runLookup(qStr: String) {
            pickJob?.cancel()
            pickJob = uiScope.launch {
                try {
                    val res = api.getCustomersCatalog(query = qStr, branchParam = session.selectedBranch)
                    listCol.removeAllViews()
                    for (c in res.customers) {
                        val row = LinearLayout(this@CustomerOrderHistoryActivity).apply {
                            orientation = LinearLayout.VERTICAL
                            setBackgroundResource(R.drawable.bg_product_thumb)
                            setPadding(dp(12), dp(10), dp(12), dp(10))
                            layoutParams = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.MATCH_PARENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT
                            ).apply { bottomMargin = dp(6) }
                        }
                        row.addView(TextView(this@CustomerOrderHistoryActivity).apply {
                            text = c.name
                            setTextColor(Color.parseColor("#0F172A"))
                            textSize = 13f
                            setTypeface(null, android.graphics.Typeface.BOLD)
                        })
                        if (c.phone.isNotBlank()) {
                            row.addView(TextView(this@CustomerOrderHistoryActivity).apply {
                                text = c.phone
                                setTextColor(Color.parseColor("#64748B"))
                                textSize = 11.5f
                            })
                        }
                        row.setOnClickListener {
                            binding.etCohSearch.setText(c.name)
                            dlg.dismiss()
                        }
                        listCol.addView(row)
                    }
                } catch (e: Exception) {
                    Toast.makeText(this@CustomerOrderHistoryActivity, e.message ?: "Lookup failed", Toast.LENGTH_SHORT).show()
                }
            }
        }

        et.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                pickJob?.cancel()
                val qStr = s?.toString()?.trim().orEmpty()
                pickJob = uiScope.launch {
                    delay(250)
                    runLookup(qStr)
                }
            }
        })

        dlg.show()
        runLookup("")
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun loadReport() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getCustomerOrderHistoryReport(
                    branch = session.selectedBranch,
                    dateFilter = period,
                    status = statusFilter,
                    paidBy = paidByFilter,
                    query = query,
                    page = currentPage
                )
                totalPages = res.totalPages
                currentPage = res.page
                paymentMethods = res.paymentMethods

                binding.tvCohTodayLabel.text = res.todayLabel
                binding.tvCohPeriodLabel.text = "📅 Period: ${res.dateFilter}"
                binding.tvCohPageBadge.text = "Page ${res.page} / ${res.totalPages}"
                binding.tvCohPageIndicator.text = "${res.page} / ${res.totalPages}"

                val pageTotal = res.orders.sumOf { it.totalAmount }
                binding.tvCohTotalOrders.text = "${res.totalOrders} Orders"
                binding.tvCohCollectionPct.text = "✓ ${res.collectionPct}% Paid"
                binding.tvCohPeriodRevenue.text = "$${moneyFmt.format(res.periodRevenue)}"
                binding.tvCohFooterTotalAmount.text = "$${moneyFmt.format(res.periodRevenue)}"
                binding.tvCohTotalSub.text = "${res.totalOrders} orders (${res.paidOrders} paid) • Page: $${moneyFmt.format(pageTotal)}"

                adapter.submitList(res.orders)
                binding.tvCohEmpty.visibility = if (res.orders.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: Exception) {
                Toast.makeText(this@CustomerOrderHistoryActivity, e.message ?: "Failed to load report", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}

class CustomerHistoryAdapter(
    private val onClick: (CustomerHistoryOrder) -> Unit
) : RecyclerView.Adapter<CustomerHistoryAdapter.VH>() {

    private val items = mutableListOf<CustomerHistoryOrder>()
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val qtyFmt = DecimalFormat("#,##0.##")

    fun submitList(list: List<CustomerHistoryOrder>) {
        items.clear()
        items.addAll(list)
        notifyDataSetChanged()
    }

    class VH(val b: ItemCustomerHistoryOrderBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(ItemCustomerHistoryOrderBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val o = items[position]
        val b = holder.b
        val ctx = b.root.context
        val dp = { v: Int -> (v * ctx.resources.displayMetrics.density).toInt() }

        val firstChar = o.customerName.trim().firstOrNull()?.uppercaseChar()?.toString() ?: "C"
        b.tvCohAvatar.text = firstChar
        b.tvCohCustName.text = o.customerName
        b.tvCohOrderNum.text = o.orderNumber
        b.tvCohOrderTotal.text = "$${moneyFmt.format(o.totalAmount)}"

        b.llCohOrderLines.removeAllViews()
        o.lines.forEachIndexed { idx, ln ->
            val block = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, dp(8), 0, dp(8))
            }

            val topRow = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            val titleText = if (ln.sku.isNotBlank() && !ln.itemName.startsWith(ln.sku, true)) {
                "${ln.sku} ${ln.itemName}"
            } else {
                ln.itemName
            }
            topRow.addView(TextView(ctx).apply {
                text = titleText
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                    marginEnd = dp(8)
                }
            })
            topRow.addView(TextView(ctx).apply {
                text = "$${moneyFmt.format(ln.subtotal)}"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
            })
            block.addView(topRow)

            if (ln.description.isNotBlank() && !ln.description.equals(ln.itemName, true)) {
                block.addView(TextView(ctx).apply {
                    text = ln.description
                    setTextColor(Color.parseColor("#64748B"))
                    textSize = 11.5f
                    layoutParams = LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { topMargin = dp(2) }
                })
            }

            val metaRow = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(4) }
            }
            metaRow.addView(TextView(ctx).apply {
                text = "Date: ${o.orderDate}   ${if (o.isPaid) "✓ Paid" else "Open"}"
                setTextColor(Color.parseColor(if (o.isPaid) "#059669" else "#D97706"))
                textSize = 11f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            metaRow.addView(TextView(ctx).apply {
                text = "${qtyFmt.format(ln.quantity)} ${ln.uom} × $${String.format(Locale.US, "%.2f", ln.unitPrice)}"
                setTextColor(Color.parseColor("#475569"))
                textSize = 11.5f
            })
            block.addView(metaRow)

            b.llCohOrderLines.addView(block)
            if (idx < o.lines.lastIndex || o.shippingFee > 0.005) {
                b.llCohOrderLines.addView(View(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(1))
                    setBackgroundColor(Color.parseColor("#F1F5F9"))
                })
            }
        }

        if (o.shippingFee > 0.005) {
            val delBlock = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, dp(8), 0, dp(8))
            }
            val top = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            top.addView(TextView(ctx).apply {
                text = "Delivery / ថ្លៃដឹក"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            top.addView(TextView(ctx).apply {
                text = "$${moneyFmt.format(o.shippingFee)}"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
            })
            delBlock.addView(top)
            val meta = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(3) }
            }
            meta.addView(TextView(ctx).apply {
                text = "Date: ${o.orderDate}   ${if (o.isPaid) "✓ Paid" else "Open"}"
                setTextColor(Color.parseColor(if (o.isPaid) "#059669" else "#D97706"))
                textSize = 11f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            meta.addView(TextView(ctx).apply {
                text = "1 ea. × $${moneyFmt.format(o.shippingFee)}"
                setTextColor(Color.parseColor("#475569"))
                textSize = 11.5f
            })
            delBlock.addView(meta)
            b.llCohOrderLines.addView(delBlock)
        }

        b.root.setOnClickListener { onClick(o) }
    }
}
