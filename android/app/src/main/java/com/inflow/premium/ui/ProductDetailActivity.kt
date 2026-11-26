package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.card.MaterialCardView
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ProductDetail
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityProductDetailBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class ProductDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityProductDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var productId: Int = 0
    private var productSku: String = ""
    private var currentDetail: ProductDetail? = null
    private var activeTab = TAB_OVERVIEW
    private val numFmt = DecimalFormat("#,##0.##")
    private val moneyFmt = DecimalFormat("#,##0.00")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityProductDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        productId = intent.getIntExtra(EXTRA_PRODUCT_ID, 0)
        productSku = intent.getStringExtra(EXTRA_PRODUCT_SKU).orEmpty()
        val initialName = intent.getStringExtra(EXTRA_PRODUCT_NAME).orEmpty()

        binding.tvProdDetHeaderSku.text = if (productSku.isNotBlank()) "$productSku •" else "Product"
        if (initialName.isNotBlank()) binding.tvProdDetailName.text = initialName

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollProductDetail,
            extraTopDp = 4,
            extraBottomScrollDp = 110
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollProductDetail.paddingTop != topH) {
                binding.scrollProductDetail.setPadding(
                    binding.scrollProductDetail.paddingLeft,
                    topH,
                    binding.scrollProductDetail.paddingRight,
                    binding.scrollProductDetail.paddingBottom
                )
            }
        }

        binding.btnProdDetBack.setOnClickListener { finish() }
        binding.btnProdDetRefresh.setOnClickListener { loadDetail() }
        binding.btnProdDetMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Open in Web App")
            popup.menu.add(0, 2, 2, "Refresh")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> openWebProduct()
                    2 -> loadDetail()
                }
                true
            }
            popup.show()
        }

        binding.tabOverview.setOnClickListener { switchTab(TAB_OVERVIEW) }
        binding.tabKit.setOnClickListener { switchTab(TAB_KIT) }
        binding.tabVendors.setOnClickListener { switchTab(TAB_VENDORS) }
        binding.tabOrderHistory.setOnClickListener { switchTab(TAB_ORDERS) }
        binding.tabPurchaseHistory.setOnClickListener { switchTab(TAB_PURCHASES) }
        binding.tabMovementHistory.setOnClickListener { switchTab(TAB_MOVEMENTS) }

        binding.btnEditProduct.setOnClickListener { openWebProduct() }
        binding.btnStockAdjust.setOnClickListener { openWebProduct() }
        binding.btnInvAdjust.setOnClickListener { openWebProduct() }
        binding.btnOpenWebPriceCard.setOnClickListener { openWebProduct("#productPriceCardSection") }

        loadDetail()
    }

    private fun openWebProduct(hash: String = "") {
        val path = if (productId > 0) "/products/$productId$hash" else "/products"
        startActivity(
            Intent(this, MainActivity::class.java).putExtra("extra_url", api.buildWebPortalUrl(path))
        )
    }

    private fun loadDetail() {
        if (productId <= 0) return
        binding.progressProdDetail.visibility = View.VISIBLE
        uiScope.launch {
            try {
                val d = api.getProductDetail(productId)
                currentDetail = d
                bindDetail(d)
                renderActiveTab()
            } catch (e: Exception) {
                Toast.makeText(this@ProductDetailActivity, e.message ?: "Failed to load product", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressProdDetail.visibility = View.GONE
            }
        }
    }

    private fun switchTab(tab: String) {
        activeTab = tab
        renderActiveTab()
    }

    private fun styleTab(tv: TextView, selected: Boolean) {
        if (selected) {
            tv.setBackgroundResource(R.drawable.bg_pill_teal_solid)
            tv.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0284C7"))
            tv.setTextColor(Color.WHITE)
        } else {
            tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
            tv.backgroundTintList = null
            tv.setTextColor(Color.parseColor("#475569"))
        }
    }

    private fun renderActiveTab() {
        styleTab(binding.tabOverview, activeTab == TAB_OVERVIEW)
        styleTab(binding.tabKit, activeTab == TAB_KIT)
        styleTab(binding.tabVendors, activeTab == TAB_VENDORS)
        styleTab(binding.tabOrderHistory, activeTab == TAB_ORDERS)
        styleTab(binding.tabPurchaseHistory, activeTab == TAB_PURCHASES)
        styleTab(binding.tabMovementHistory, activeTab == TAB_MOVEMENTS)

        if (activeTab == TAB_OVERVIEW) {
            binding.llSectionOverview.visibility = View.VISIBLE
            binding.llSectionTabContent.visibility = View.GONE
            return
        }

        binding.llSectionOverview.visibility = View.GONE
        binding.llSectionTabContent.visibility = View.VISIBLE
        binding.llSectionTabContent.removeAllViews()

        val d = currentDetail ?: return
        when (activeTab) {
            TAB_KIT -> renderBomTab(d)
            TAB_VENDORS -> renderVendorsTab(d)
            TAB_ORDERS -> renderOrderHistoryTab(d, isPo = false)
            TAB_PURCHASES -> renderOrderHistoryTab(d, isPo = true)
            TAB_MOVEMENTS -> renderMovementsTab(d)
        }
    }

    private fun bindDetail(d: ProductDetail) {
        productSku = d.sku
        binding.tvProdDetHeaderSku.text = "${d.sku} •"
        binding.tvProdDetailSku.text = "SKU: ${d.sku}"
        binding.tvProdDetailName.text = d.name.ifBlank { d.sku }
        binding.tvProdCategory.text = d.categoryName.ifBlank { "Uncategorized" }
        binding.tvProdBarcode.text = d.barcode.ifBlank { "—" }
        binding.tvProdDescription.text = d.description.ifBlank { "No product description" }

        binding.tabKit.text = "Combined / Kit (${d.boms.size})"
        binding.tabOrderHistory.text = "Order history (${d.orderHistory.size})"

        if (d.isActive) {
            binding.tvProdActiveBadge.text = "ACTIVE ITEM"
            binding.tvProdActiveBadge.setTextColor(Color.parseColor("#059669"))
            binding.tvProdActiveBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
        } else {
            binding.tvProdActiveBadge.text = "INACTIVE"
            binding.tvProdActiveBadge.setTextColor(Color.parseColor("#DC2626"))
            binding.tvProdActiveBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEE2E2"))
        }

        ImageLoader.load(uiScope, session.baseUrl, d.imageUrl, binding.ivProdHero, binding.ivProdHeroPlaceholder)

        binding.tvTotalOnHand.text = numFmt.format(d.totalOnHand)
        binding.tvTotalOnHandUnit.text = "${d.uom} on hand"

        val density = resources.displayMetrics.density
        fun dp(v: Int) = (v * density).toInt()

        binding.llInventoryList.removeAllViews()
        val invList = d.inventory.ifEmpty {
            listOf(com.inflow.premium.data.ProductInventoryLocation(100, d.defaultLocationName, 0.0, 0.0))
        }
        val maxStock = invList.maxOf { it.onHand }.coerceAtLeast(1.0)
        for (loc in invList) {
            val box = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setBackgroundResource(R.drawable.bg_product_thumb)
                setPadding(dp(10), dp(10), dp(10), dp(10))
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(8) }
            }
            val topRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            val tvLoc = TextView(this).apply {
                text = loc.locationName
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 12.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            val tvQty = TextView(this).apply {
                text = "${numFmt.format(loc.onHand)} ${d.uom}"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 12.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            topRow.addView(tvLoc)
            topRow.addView(tvQty)
            box.addView(topRow)

            val pb = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
                max = 100
                progress = ((loc.onHand / maxStock) * 100).toInt().coerceIn(5, 100)
                progressTintList = ColorStateList.valueOf(
                    if (loc.onHand > d.reorderPoint) Color.parseColor("#F59E0B") else Color.parseColor("#EF4444")
                )
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    dp(8)
                ).apply { topMargin = dp(6) }
            }
            box.addView(pb)

            val footRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(4) }
            }
            val tvReorder = TextView(this).apply {
                text = "Reorder Point: ${numFmt.format(d.reorderPoint)} ${d.uom}"
                setTextColor(Color.parseColor("#64748B"))
                textSize = 11f
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            val tvHealth = TextView(this).apply {
                text = if (loc.onHand > d.reorderPoint) "Healthy Stock" else "Low Stock"
                setTextColor(if (loc.onHand > d.reorderPoint) Color.parseColor("#059669") else Color.parseColor("#DC2626"))
                textSize = 11f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            footRow.addView(tvReorder)
            footRow.addView(tvHealth)
            box.addView(footRow)
            binding.llInventoryList.addView(box)
        }

        // Storage Info
        binding.tvStorageDefaultLoc.text = d.defaultLocationName.ifBlank { "Main Warehouse" }
        binding.tvStorageSubloc.text = d.sublocation.ifBlank { "Unassigned" }
        binding.tvStorageReorderQty.text = if (d.reorderQty > 0) numFmt.format(d.reorderQty) else "—"
        binding.tvStorageStdCost.text = String.format(Locale.US, "$%.4f", d.standardCost)

        // UOM & Packaging
        binding.tvStdUomBadge.text = "Standard: ${d.uom}"
        binding.tvSalesUomVal.text = d.salesUom.ifBlank { d.uom }
        binding.tvPurchasingUomVal.text = d.purchasingUom.ifBlank { d.salesUom.ifBlank { d.uom } }
        binding.tvConversionRate.text = if (d.salesUom.isNotBlank() && !d.salesUom.equals(d.uom, true)) {
            "Conversion Rate: 1.000 ${d.salesUom} = ${String.format(Locale.US, "%.3f", d.salesUomRatioStd)} ${d.uom}"
        } else {
            "Conversion Rate: 1.000 ${d.uom}"
        }
        binding.tvDimL.text = numFmt.format(d.length)
        binding.tvDimW.text = numFmt.format(d.width)
        binding.tvDimH.text = numFmt.format(d.height)

        // Pricing & Cost Tiers (Corrected per-case and per-pcs)
        binding.llPricingTiers.removeAllViews()
        for (tier in d.pricingTiers) {
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                setBackgroundResource(R.drawable.bg_product_thumb)
                setPadding(dp(12), dp(10), dp(12), dp(10))
                layoutParams = LinearLayout.LayoutParams(dp(124), LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                    marginEnd = dp(8)
                }
            }
            val tvName = TextView(this).apply {
                text = tier.schemeName
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 12.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            val tvMargin = TextView(this).apply {
                val sign = if (tier.marginPct >= 0) "+" else ""
                text = String.format(Locale.US, "%s%.2f%%", sign, tier.marginPct)
                setTextColor(if (tier.marginPct >= 0) Color.parseColor("#059669") else Color.parseColor("#DC2626"))
                setBackgroundResource(R.drawable.bg_pill_emerald_dark)
                backgroundTintList = ColorStateList.valueOf(
                    Color.parseColor(if (tier.marginPct >= 0) "#DCFCE7" else "#FEE2E2")
                )
                setPadding(dp(8), dp(2), dp(8), dp(2))
                textSize = 10.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(4) }
            }
            val tvCaseLbl = TextView(this).apply {
                text = if (d.salesUom.isNotBlank()) d.salesUom else "Case"
                setTextColor(Color.parseColor("#64748B"))
                textSize = 10.5f
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(8) }
            }
            val tvCasePrice = TextView(this).apply {
                text = "$${moneyFmt.format(tier.casePrice)}"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 14f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }
            val tvUnitLbl = TextView(this).apply {
                text = d.uom
                setTextColor(Color.parseColor("#64748B"))
                textSize = 10.5f
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(6) }
            }
            val tvUnitPrice = TextView(this).apply {
                text = String.format(Locale.US, "$%.4f", tier.unitPrice)
                setTextColor(Color.parseColor("#0A6C62"))
                textSize = 12.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            }

            card.addView(tvName)
            card.addView(tvMargin)
            card.addView(tvCaseLbl)
            card.addView(tvCasePrice)
            card.addView(tvUnitLbl)
            card.addView(tvUnitPrice)
            binding.llPricingTiers.addView(card)
        }

        // Bottom Product Price Table Card
        val pt = d.priceTable
        if (pt != null) {
            binding.cardPriceTable.visibility = View.VISIBLE
            val accentColor = try {
                Color.parseColor(pt.catColor)
            } catch (_: Exception) {
                Color.parseColor("#00A3E0")
            }
            binding.vPriceTableAccent.setBackgroundColor(accentColor)
            binding.llPriceTableHeader.setBackgroundColor(accentColor)
            binding.tvPriceTableSpecs.text = pt.detailLines.joinToString("\n").ifBlank { pt.dimStr }

            binding.llPriceTableRows.removeAllViews()
            val tierRows = listOf(
                Triple("${pt.tierQty1} ${d.uom}", pt.uPrice1, pt.totPrice1),
                Triple("${pt.tierQty2} ${d.uom}", pt.uPrice2, pt.totPrice2),
                Triple("${pt.tierQty3} ${d.uom}", pt.uPrice3, pt.totPrice3)
            )
            tierRows.forEachIndexed { idx, (qtyLabel, unitP, totP) ->
                val row = LinearLayout(this).apply {
                    orientation = LinearLayout.HORIZONTAL
                    setPadding(dp(10), dp(8), dp(10), dp(8))
                    if (idx % 2 == 1) setBackgroundColor(Color.parseColor("#F8FAFC"))
                }
                val tvQ = TextView(this).apply {
                    text = qtyLabel
                    setTextColor(Color.parseColor("#0F172A"))
                    textSize = 12f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.1f)
                }
                val tvU = TextView(this).apply {
                    text = String.format(Locale.US, "$%.4f", unitP)
                    gravity = Gravity.CENTER
                    setTextColor(Color.parseColor("#334155"))
                    textSize = 12f
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                }
                val tvT = TextView(this).apply {
                    text = "$${moneyFmt.format(totP)}"
                    gravity = Gravity.END
                    setTextColor(accentColor)
                    textSize = 12.5f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                }
                row.addView(tvQ)
                row.addView(tvU)
                row.addView(tvT)
                binding.llPriceTableRows.addView(row)
            }
        } else {
            binding.cardPriceTable.visibility = View.GONE
        }
    }

    private fun renderBomTab(d: ProductDetail) {
        if (d.boms.isEmpty()) {
            binding.llSectionTabContent.addView(makeEmptyState("No Combined / Kit components defined for this item."))
            return
        }
        for (b in d.boms) {
            val card = makeCard()
            val col = makeCol(12)
            col.addView(makeBold("${b.sku} • ${b.name}", "#0F172A", 13f))
            col.addView(makeMuted("Qty: ${numFmt.format(b.quantity)} ${b.uom}  •  Unit Cost: $${String.format(Locale.US, "%.4f", b.unitCost)}", 12f).apply {
                layoutParams = lpWrap(top = 4)
            })
            card.addView(col)
            card.setOnClickListener {
                if (b.componentId > 0) {
                    startActivity(Intent(this, ProductDetailActivity::class.java).putExtra(EXTRA_PRODUCT_ID, b.componentId))
                }
            }
            binding.llSectionTabContent.addView(card)
        }
    }

    private fun renderVendorsTab(d: ProductDetail) {
        if (d.vendors.isEmpty()) {
            binding.llSectionTabContent.addView(makeEmptyState("No linked product vendors found."))
            return
        }
        for (v in d.vendors) {
            val card = makeCard()
            val col = makeCol(12)
            col.addView(makeBold(v.name, "#0F172A", 13.5f))
            val info = buildString {
                if (v.itemCode.isNotBlank()) append("Code: ${v.itemCode}  •  ")
                if (v.phone.isNotBlank()) append("📞 ${v.phone}  •  ")
                append("Cost: $${String.format(Locale.US, "%.4f", v.cost)}")
            }
            col.addView(makeMuted(info, 12f).apply { layoutParams = lpWrap(top = 4) })
            card.addView(col)
            binding.llSectionTabContent.addView(card)
        }
    }

    private fun renderOrderHistoryTab(d: ProductDetail, isPo: Boolean) {
        val list = if (isPo) d.purchaseHistory else d.orderHistory
        if (list.isEmpty()) {
            binding.llSectionTabContent.addView(
                makeEmptyState(if (isPo) "No purchase order history found." else "No sales order history found.")
            )
            return
        }
        for (o in list) {
            val card = makeCard()
            val col = makeCol(12)
            val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            top.addView(makeBold("${o.orderNumber}  •  ${o.orderDate}", if (isPo) "#6D4C2B" else "#0A6C62", 13f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            top.addView(makeBold(o.status, "#475569", 11.5f))
            col.addView(top)
            col.addView(makeBold(o.partyName.ifBlank { "—" }, "#0F172A", 13f).apply { layoutParams = lpWrap(top = 4) })
            col.addView(makeMuted("Qty: ${numFmt.format(o.quantity)} ${o.uom}  •  Total: $${moneyFmt.format(o.totalAmount)}", 12f).apply {
                layoutParams = lpWrap(top = 4)
            })
            card.addView(col)
            card.setOnClickListener {
                if (isPo) {
                    startActivity(
                        Intent(this, PurchaseOrderDetailActivity::class.java)
                            .putExtra(PurchaseOrderDetailActivity.EXTRA_PO_ID, o.orderId)
                            .putExtra(PurchaseOrderDetailActivity.EXTRA_PO_NUMBER, o.orderNumber)
                    )
                } else {
                    startActivity(
                        Intent(this, SalesOrderDetailActivity::class.java)
                            .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, o.orderId)
                    )
                }
            }
            binding.llSectionTabContent.addView(card)
        }
    }

    private fun renderMovementsTab(d: ProductDetail) {
        if (d.movementHistory.isEmpty()) {
            binding.llSectionTabContent.addView(makeEmptyState("No recent stock movements recorded."))
            return
        }
        for (m in d.movementHistory) {
            val card = makeCard()
            val col = makeCol(12)
            val top = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            top.addView(makeBold(m.movementType, "#0284C7", 12.5f).apply {
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            val sign = if (m.quantity >= 0) "+" else ""
            top.addView(makeBold("$sign${numFmt.format(m.quantity)} ${d.uom}", if (m.quantity >= 0) "#059669" else "#DC2626", 13f))
            col.addView(top)
            val route = listOfNotNull(
                m.fromLocation.takeIf { it.isNotBlank() },
                m.toLocation.takeIf { it.isNotBlank() }
            ).joinToString(" → ")
            col.addView(makeMuted("${m.createdAt}  ${if (route.isNotBlank()) "• $route" else ""}  ${m.referenceNumber}".trim(), 11.5f).apply {
                layoutParams = lpWrap(top = 4)
            })
            card.addView(col)
            binding.llSectionTabContent.addView(card)
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()
    private fun lpWrap(top: Int = 0) = LinearLayout.LayoutParams(
        LinearLayout.LayoutParams.MATCH_PARENT,
        LinearLayout.LayoutParams.WRAP_CONTENT
    ).apply { topMargin = dp(top) }
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
    private fun makeEmptyState(msg: String) = TextView(this).apply {
        text = msg
        gravity = Gravity.CENTER
        setTextColor(Color.parseColor("#64748B"))
        textSize = 13f
        setPadding(dp(16), dp(24), dp(16), dp(24))
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_PRODUCT_ID = "extra_product_id"
        const val EXTRA_PRODUCT_SKU = "extra_product_sku"
        const val EXTRA_PRODUCT_NAME = "extra_product_name"

        private const val TAB_OVERVIEW = "overview"
        private const val TAB_KIT = "kit"
        private const val TAB_VENDORS = "vendors"
        private const val TAB_ORDERS = "orders"
        private const val TAB_PURCHASES = "purchases"
        private const val TAB_MOVEMENTS = "movements"
    }
}
