package com.inflow.premium.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
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
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.PriceListCardItem
import com.inflow.premium.data.PriceListCategory
import com.inflow.premium.data.PricingSchemeItem
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityPriceListBinding
import com.inflow.premium.databinding.ItemPriceListCardBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class PriceListActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPriceListBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: PriceListAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var allItems: List<PriceListCardItem> = emptyList()
    private var categories: List<PriceListCategory> = emptyList()
    private var schemes: List<PricingSchemeItem> = emptyList()
    private var selectedCategoryId: Int? = null
    private var selectedSchemeId: Int = 100
    private var usePackUom: Boolean = true
    private var currentQuery: String = ""
    private var totalProductCount: Int = 0
    private var searchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityPriceListBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = null,
            bottomScrimView = null,
            scrollableView = binding.scrollPriceList,
            extraTopDp = 6,
            extraBottomScrollDp = 24
        )

        adapter = PriceListAdapter(
            scope = uiScope,
            baseUrl = session.baseUrl,
            onCopy = { item, summary ->
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText(item.sku, summary))
                Toast.makeText(this, "Copied ${item.sku} price", Toast.LENGTH_SHORT).show()
            },
            onOpenDetail = { item ->
                startActivity(
                    Intent(this, ProductDetailActivity::class.java)
                        .putExtra(ProductDetailActivity.EXTRA_PRODUCT_ID, item.id)
                        .putExtra(ProductDetailActivity.EXTRA_PRODUCT_SKU, item.sku)
                        .putExtra(ProductDetailActivity.EXTRA_PRODUCT_NAME, item.name)
                )
            }
        )
        binding.rvPriceList.layoutManager = LinearLayoutManager(this)
        binding.rvPriceList.adapter = adapter

        binding.btnPlBack.setOnClickListener { finish() }
        binding.btnPlPrint.setOnClickListener { openWebPriceList() }
        binding.btnPlPdf.setOnClickListener { openWebPriceList() }
        binding.btnPlScheme.setOnClickListener { showSchemePicker() }
        binding.btnPlUomMode.setOnClickListener {
            usePackUom = !usePackUom
            binding.btnPlUomMode.text = if (usePackUom) "UOM: Pack (ដុំ)" else "UOM: Piece (ប្រអប់)"
            adapter.updateSchemeAndMode(selectedSchemeId, usePackUom)
        }

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadPriceList() }

        binding.btnPlClearSearch.setOnClickListener { binding.etPlSearch.setText("") }
        binding.etPlSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnPlClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentQuery) return
                currentQuery = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(220)
                    applyClientFilter()
                }
            }
        })
        binding.etPlSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                BottomNavHelper.dismissKeyboardAndClearFocus(this)
                applyClientFilter()
                true
            } else false
        }

        loadPriceList()
    }

    override fun onResume() {
        super.onResume()
        if (::binding.isInitialized) {
            binding.etPlSearch.clearFocus()
            binding.root.requestFocus()
            BottomNavHelper.dismissKeyboardAndClearFocus(this)
        }
    }

    private fun openWebPriceList() {
        startActivity(
            Intent(this, MainActivity::class.java)
                .putExtra("extra_url", api.buildWebPortalUrl("/inventory/price-list"))
        )
    }

    private fun loadPriceList() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getPriceList()
                totalProductCount = res.totalProducts
                categories = res.categories
                schemes = res.pricingSchemes.ifEmpty { session.getPricingSchemes() }
                allItems = res.items

                val defaultScheme = schemes.firstOrNull { it.isDefault } ?: schemes.firstOrNull()
                if (schemes.none { it.id == selectedSchemeId } && defaultScheme != null) {
                    selectedSchemeId = defaultScheme.id
                }
                val schName = schemes.firstOrNull { it.id == selectedSchemeId }?.name ?: "Retail 1"
                binding.btnPlScheme.text = "Scheme: $schName ⌄"
                binding.tvPlCountPill.text = "${res.totalProducts} items"

                renderCategoryChips()
                applyClientFilter()
            } catch (e: Exception) {
                Toast.makeText(this@PriceListActivity, e.message ?: "Failed to load Price List", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun renderCategoryChips() {
        binding.llPriceCatChips.removeAllViews()
        val density = resources.displayMetrics.density
        fun dp(v: Int) = (v * density).toInt()

        fun addChip(label: String, isActive: Boolean, onClick: () -> Unit) {
            val tv = TextView(this).apply {
                text = label
                textSize = 11.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
                setPadding(dp(12), dp(7), dp(12), dp(7))
                if (isActive) {
                    setBackgroundResource(R.drawable.bg_pill_teal_solid)
                    backgroundTintList = ColorStateList.valueOf(Color.parseColor("#047857"))
                    setTextColor(Color.WHITE)
                } else {
                    setBackgroundResource(R.drawable.bg_floating_top_capsule)
                    setTextColor(Color.parseColor("#334155"))
                }
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { marginEnd = dp(6) }
                setOnClickListener { onClick() }
            }
            binding.llPriceCatChips.addView(tv)
        }

        addChip("All Products ($totalProductCount)", selectedCategoryId == null) {
            selectedCategoryId = null
            renderCategoryChips()
            applyClientFilter()
        }
        for (c in categories) {
            addChip("${c.name} (${c.productCount})", selectedCategoryId == c.id) {
                selectedCategoryId = c.id
                renderCategoryChips()
                applyClientFilter()
            }
        }
    }

    private fun applyClientFilter() {
        val q = currentQuery.trim().lowercase(Locale.US)
        val filtered = allItems.filter { p ->
            val matchCat = selectedCategoryId == null || p.categoryId == selectedCategoryId
            val matchQ = q.isEmpty() ||
                p.sku.lowercase(Locale.US).contains(q) ||
                p.name.lowercase(Locale.US).contains(q) ||
                p.categoryName.lowercase(Locale.US).contains(q) ||
                p.dimStr.lowercase(Locale.US).contains(q)
            matchCat && matchQ
        }
        binding.tvPlFilteredBadge.text = "${filtered.size} Products"
        binding.tvEmptyPriceList.visibility = if (filtered.isEmpty()) View.VISIBLE else View.GONE
        adapter.submit(filtered, selectedSchemeId, usePackUom)
    }

    private fun showSchemePicker() {
        if (schemes.isEmpty()) return
        val names = schemes.map { it.name }.toTypedArray()
        val checked = schemes.indexOfFirst { it.id == selectedSchemeId }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Pricing Scheme")
            .setSingleChoiceItems(names, checked) { dlg, which ->
                val chosen = schemes[which]
                selectedSchemeId = chosen.id
                binding.btnPlScheme.text = "Scheme: ${chosen.name} ⌄"
                adapter.updateSchemeAndMode(selectedSchemeId, usePackUom)
                dlg.dismiss()
            }
            .setNegativeButton("Close", null)
            .show()
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}

class PriceListAdapter(
    private val scope: CoroutineScope,
    private val baseUrl: String,
    private val onCopy: (PriceListCardItem, String) -> Unit,
    private val onOpenDetail: (PriceListCardItem) -> Unit
) : RecyclerView.Adapter<PriceListAdapter.VH>() {

    private val items = mutableListOf<PriceListCardItem>()
    private var schemeId: Int = 100
    private var usePackUom: Boolean = true
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val qtyFmt = DecimalFormat("#,##0.##")

    fun submit(list: List<PriceListCardItem>, scheme: Int, packMode: Boolean) {
        items.clear()
        items.addAll(list)
        schemeId = scheme
        usePackUom = packMode
        notifyDataSetChanged()
    }

    fun updateSchemeAndMode(scheme: Int, packMode: Boolean) {
        schemeId = scheme
        usePackUom = packMode
        notifyDataSetChanged()
    }

    class VH(val b: ItemPriceListCardBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(ItemPriceListCardBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val p = items[position]
        val b = holder.b
        val ctx = b.root.context
        val dp = { v: Int -> (v * ctx.resources.displayMetrics.density).toInt() }

        b.tvPlItemSku.text = p.sku.ifBlank { "#${p.id}" }
        b.tvPlItemName.text = p.name.ifBlank { p.sku }

        if (p.badge.isNotBlank()) {
            b.tvPlCapacityBadge.visibility = View.VISIBLE
            b.tvPlCapacityBadge.text = p.badge
        } else {
            b.tvPlCapacityBadge.visibility = View.GONE
        }
        ImageLoader.load(scope, baseUrl, p.imageUrl, b.ivPlItemPhoto, b.tvPlPhotoFallback)

        // Packaging spec rows
        b.llPlSpecsCol.removeAllViews()
        val lines = p.detailLines.ifEmpty { listOfNotNull(p.dimStr.takeIf { it.isNotBlank() }) }
        val icons = arrayOf("↔", "📦", "⛁", "📦")
        var idx = 0
        var rowIdx = 0
        while (idx < lines.size) {
            val cur = lines[idx]
            val next = lines.getOrNull(idx + 1)
            val pairSub = if (next != null && next.trim().startsWith("(")) {
                idx += 2
                next.trim()
            } else {
                idx += 1
                null
            }
            val row = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(0, dp(3), 0, dp(3))
            }
            row.addView(TextView(ctx).apply {
                text = icons.getOrElse(rowIdx) { "•" }
                textSize = 11f
                setTextColor(Color.parseColor("#047857"))
                setPadding(0, 0, dp(6), 0)
            })
            val col = LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            col.addView(TextView(ctx).apply {
                text = if (pairSub != null) "$cur $pairSub" else cur
                setTextColor(Color.parseColor("#1E293B"))
                textSize = 11f
                setTypeface(null, android.graphics.Typeface.BOLD)
            })
            row.addView(col)
            b.llPlSpecsCol.addView(row)
            rowIdx++
        }

        // Compute tier rates from schemePricesPcs if switching schemes cleanly
        val schemePcs = p.schemePricesPcs[schemeId.toString()]?.takeIf { it > 0.0 }
        val ratio2 = if (p.uPrice1 > 0) (p.uPrice2 / p.uPrice1) else 0.96
        val ratio3 = if (p.uPrice1 > 0) (p.uPrice3 / p.uPrice1) else 0.92
        val u1 = schemePcs ?: p.uPrice1
        val u2 = if (schemePcs != null) schemePcs * ratio2 else p.uPrice2
        val u3 = if (schemePcs != null) schemePcs * ratio3 else p.uPrice3
        val t1 = if (schemePcs != null) u1 * p.tierQty1 else p.totPrice1
        val t2 = if (schemePcs != null) u2 * p.tierQty2 else p.totPrice2
        val t3 = if (schemePcs != null) u3 * p.tierQty3 else p.totPrice3

        val detectedKhUnit = lines.firstOrNull { it.contains("1 ដុំ") }
            ?.substringAfterLast(" ")?.trim()?.takeIf { it.isNotBlank() } ?: "ប្រអប់"
        val pcsPerPack = if (p.pcsPerPack > 1.0) p.pcsPerPack else 1.0

        val tiers = listOf(
            Triple(p.tierQty1, u1, t1),
            Triple(p.tierQty2, u2, t2),
            Triple(p.tierQty3, u3, t3)
        )
        b.llPlTierRows.removeAllViews()
        val copyLines = mutableListOf("${p.sku} — ${p.name}")
        tiers.forEachIndexed { tIdx, (qtyPcs, uPcs, tot) ->
            val isLast = tIdx == tiers.lastIndex
            val row = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(8), dp(7), dp(8), dp(7))
                setBackgroundResource(if (isLast) R.drawable.bg_pill_slate_controls else R.drawable.bg_product_thumb)
                backgroundTintList = ColorStateList.valueOf(
                    Color.parseColor(if (isLast) "#ECFDF5" else "#FFFFFF")
                )
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(5) }
            }

            val qtyDisplay = if (!usePackUom && pcsPerPack > 1.0 && qtyPcs % pcsPerPack.toInt() == 0) {
                qtyFmt.format(qtyPcs)
            } else {
                qtyFmt.format(qtyPcs)
            }
            val qtyBadge = TextView(ctx).apply {
                text = qtyDisplay
                setBackgroundResource(R.drawable.bg_product_thumb)
                setPadding(dp(8), dp(3), dp(8), dp(3))
                setTextColor(Color.parseColor("#047857"))
                textSize = 11.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            val labelTv = TextView(ctx).apply {
                text = " $detectedKhUnit(PCS) = "
                setTextColor(Color.parseColor("#475569"))
                textSize = 11.5f
            }
            val totalTv = TextView(ctx).apply {
                text = "${moneyFmt.format(tot)} $"
                setTextColor(Color.parseColor("#047857"))
                textSize = 13.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            val unitDec = if ((uPcs * 1000.0) % 1.0 != 0.0) 4 else 3
            val unitStr = "(${String.format(Locale.US, "%.${unitDec}f", uPcs)} $/PCS)"
            val unitTv = TextView(ctx).apply {
                text = unitStr
                setBackgroundResource(R.drawable.bg_pill_slate_controls)
                backgroundTintList = ColorStateList.valueOf(
                    Color.parseColor(if (isLast) "#D1FAE5" else "#F1F5F9")
                )
                setPadding(dp(8), dp(4), dp(8), dp(4))
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 11f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }

            row.addView(qtyBadge)
            row.addView(labelTv)
            row.addView(totalTv)
            row.addView(unitTv)
            b.llPlTierRows.addView(row)
            copyLines.add("$qtyPcs $detectedKhUnit = $${moneyFmt.format(tot)} $unitStr")
        }

        b.btnPlCopy.setOnClickListener { onCopy(p, copyLines.joinToString("\n")) }
        b.btnPlDetail.setOnClickListener { onOpenDetail(p) }
    }
}
