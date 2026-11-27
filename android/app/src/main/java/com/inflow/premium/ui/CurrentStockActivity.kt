package com.inflow.premium.ui

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.StockMatrixCategory
import com.inflow.premium.data.StockMatrixItem
import com.inflow.premium.databinding.ActivityCurrentStockBinding
import com.inflow.premium.databinding.ItemStockMatrixBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class CurrentStockActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCurrentStockBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: StockMatrixAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentSearch = ""
    private var selectedCategoryId: Int? = null
    private var currentPage = 1
    private var categoriesLoaded = false
    private var searchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityCurrentStockBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.HOME)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollCurrentStock,
            extraTopDp = 6,
            extraBottomScrollDp = 120
        )

        adapter = StockMatrixAdapter { item ->
            startActivity(
                Intent(this, ProductDetailActivity::class.java)
                    .putExtra(ProductDetailActivity.EXTRA_PRODUCT_ID, item.id)
                    .putExtra(ProductDetailActivity.EXTRA_PRODUCT_SKU, item.sku)
                    .putExtra(ProductDetailActivity.EXTRA_PRODUCT_NAME, item.name)
            )
        }
        binding.rvStockMatrix.layoutManager = LinearLayoutManager(this)
        binding.rvStockMatrix.adapter = adapter

        binding.btnStockBack.setOnClickListener { finish() }
        binding.btnStockRefresh.setOnClickListener {
            currentPage = 1
            loadStockMatrix(append = false)
        }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener {
            currentPage = 1
            loadStockMatrix(append = false)
        }

        binding.btnStockAdjust.setOnClickListener { openWebPath("/inventory/adjustments/new") }
        binding.btnStockTransfer.setOnClickListener {
            startActivity(Intent(this, StockTransfersActivity::class.java))
        }

        binding.btnStockClearSearch.setOnClickListener {
            binding.etStockSearch.setText("")
        }
        binding.etStockSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnStockClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentSearch) return
                currentSearch = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(320)
                    currentPage = 1
                    loadStockMatrix(append = false)
                }
            }
        })
        binding.etStockSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                searchJob?.cancel()
                currentSearch = binding.etStockSearch.text?.toString()?.trim().orEmpty()
                currentPage = 1
                loadStockMatrix(append = false)
                true
            } else {
                false
            }
        }

        binding.btnLoadMoreStock.setOnClickListener {
            currentPage += 1
            loadStockMatrix(append = true)
        }

        loadStockMatrix(append = false)
    }

    private fun openWebPath(path: String) {
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("extra_url", api.buildWebPortalUrl(path))
        )
    }

    private fun loadStockMatrix(append: Boolean) {
        if (!append) binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getStockMatrix(currentSearch, selectedCategoryId, currentPage)
                val moneyFmt = DecimalFormat("#,##0.00")
                val valPrefix = if (res.netValuation < 0) "$-" else "$"
                binding.tvNetValuation.text = "$valPrefix${moneyFmt.format(kotlin.math.abs(res.netValuation))}"
                binding.tvNetValuation.setTextColor(
                    Color.parseColor(if (res.netValuation < 0) "#FB7185" else "#34D399")
                )
                binding.tvNegativeStockSummary.text = "● ${res.negativeCount} Items Negative Stock"
                binding.tvTotalSkus.text = "${res.totalSkus} SKUs"
                binding.tvWarehouseCountBadge.text = "${res.warehouseCount} Warehouses"

                if (!categoriesLoaded && res.categories.isNotEmpty()) {
                    categoriesLoaded = true
                    renderCategoryChips(res.categories)
                }

                adapter.submitList(res.items, append = append)
                binding.tvEmptyStock.visibility = if (adapter.itemCount == 0) View.VISIBLE else View.GONE
                binding.btnLoadMoreStock.visibility = if (res.hasMore) View.VISIBLE else View.GONE
            } catch (e: Exception) {
                Toast.makeText(this@CurrentStockActivity, e.message ?: "Failed to load stock", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun renderCategoryChips(categories: List<StockMatrixCategory>) {
        binding.llStockCategories.removeAllViews()
        val density = resources.displayMetrics.density
        fun dp(v: Int) = (v * density).toInt()

        val allEntries = listOf(StockMatrixCategory(0, "All Categories")) + categories
        for (cat in allEntries) {
            val isSelected = (cat.id == 0 && selectedCategoryId == null) || (cat.id == selectedCategoryId)
            val tv = TextView(this).apply {
                text = cat.name
                textSize = 12f
                setTypeface(null, android.graphics.Typeface.BOLD)
                setPadding(dp(14), dp(8), dp(14), dp(8))
                setBackgroundResource(
                    if (isSelected) R.drawable.bg_pill_teal_solid else R.drawable.bg_floating_top_capsule
                )
                if (isSelected) {
                    backgroundTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#0B172A"))
                    setTextColor(Color.WHITE)
                } else {
                    backgroundTintList = null
                    setTextColor(Color.parseColor("#334155"))
                }
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { marginEnd = dp(8) }
                setOnClickListener {
                    selectedCategoryId = if (cat.id == 0) null else cat.id
                    renderCategoryChips(categories)
                    currentPage = 1
                    loadStockMatrix(append = false)
                }
            }
            binding.llStockCategories.addView(tv)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}

class StockMatrixAdapter(
    private val onClick: (StockMatrixItem) -> Unit
) : RecyclerView.Adapter<StockMatrixAdapter.VH>() {

    private val items = mutableListOf<StockMatrixItem>()
    private val numFmt = DecimalFormat("#,##0.##")
    private val moneyFmt = DecimalFormat("#,##0.00")

    fun submitList(newItems: List<StockMatrixItem>, append: Boolean) {
        if (!append) items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    class VH(val b: ItemStockMatrixBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val b = ItemStockMatrixBinding.inflate(LayoutInflater.from(parent.context), parent, false)
        return VH(b)
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val b = holder.b
        val ctx = b.root.context

        b.tvStockName.text = item.name.ifBlank { item.sku }
        b.tvStockCategory.text = item.categoryName.uppercase(Locale.US)
        b.tvStockSkuUom.text = "${item.sku} (${item.uom})"

        b.tvStockTotalQty.text = numFmt.format(item.totalQty)
        b.tvStockTotalQty.setTextColor(
            Color.parseColor(
                when {
                    item.totalQty < 0 -> "#DC2626"
                    item.totalQty > 0 -> "#059669"
                    else -> "#64748B"
                }
            )
        )

        val valStr = if (item.totalValue < 0) {
            "$-${moneyFmt.format(kotlin.math.abs(item.totalValue))}"
        } else {
            "$${moneyFmt.format(item.totalValue)}"
        }
        b.tvStockTotalVal.text = valStr
        b.tvStockTotalVal.setTextColor(
            Color.parseColor(if (item.totalValue < 0) "#DC2626" else "#0F172A")
        )

        b.llWarehouseBreakdown.removeAllViews()
        item.warehouses.forEachIndexed { idx, wh ->
            val col = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                gravity = if (idx == item.warehouses.lastIndex && item.warehouses.size > 1) {
                    Gravity.END
                } else {
                    Gravity.START
                }
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            val tvWhName = TextView(ctx).apply {
                text = wh.name
                setTextColor(Color.parseColor("#64748B"))
                textSize = 11f
                maxLines = 1
            }
            val qtyStr = if (wh.qty > 0) "+${numFmt.format(wh.qty)}" else numFmt.format(wh.qty)
            val tvWhQty = TextView(ctx).apply {
                text = qtyStr
                setTextColor(
                    Color.parseColor(
                        when {
                            wh.qty < 0 -> "#DC2626"
                            wh.qty > 0 -> "#059669"
                            else -> "#64748B"
                        }
                    )
                )
                textSize = 12.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            col.addView(tvWhName)
            col.addView(tvWhQty)
            b.llWarehouseBreakdown.addView(col)
        }

        b.root.setOnClickListener { onClick(item) }
    }
}
