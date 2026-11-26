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
    private val numFmt = DecimalFormat("#,##0.##")

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

        binding.btnEditProduct.setOnClickListener { openWebProduct() }
        binding.btnStockAdjust.setOnClickListener { openWebProduct() }
        binding.btnInvAdjust.setOnClickListener { openWebProduct() }

        loadDetail()
    }

    private fun openWebProduct() {
        val url = if (productId > 0) "${session.baseUrl}/products/$productId" else "${session.baseUrl}/products"
        startActivity(Intent(this, MainActivity::class.java).putExtra("extra_url", url))
    }

    private fun loadDetail() {
        if (productId <= 0) return
        binding.progressProdDetail.visibility = View.VISIBLE
        uiScope.launch {
            try {
                val d = api.getProductDetail(productId)
                bindDetail(d)
            } catch (e: Exception) {
                Toast.makeText(this@ProductDetailActivity, e.message ?: "Failed to load product", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressProdDetail.visibility = View.GONE
            }
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

        // Inventory rows
        binding.llInventoryList.removeAllViews()
        val density = resources.displayMetrics.density
        fun dp(v: Int) = (v * density).toInt()

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

        // Pricing & Cost Tiers
        binding.llPricingTiers.removeAllViews()
        for (tier in d.pricingTiers) {
            val card = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                gravity = Gravity.CENTER_HORIZONTAL
                setBackgroundResource(R.drawable.bg_product_thumb)
                setPadding(dp(12), dp(10), dp(12), dp(10))
                layoutParams = LinearLayout.LayoutParams(dp(120), LinearLayout.LayoutParams.WRAP_CONTENT).apply {
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
                text = String.format(Locale.US, "+%.2f%%", tier.marginPct)
                setTextColor(Color.parseColor("#059669"))
                setBackgroundResource(R.drawable.bg_pill_emerald_dark)
                backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
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
                text = String.format(Locale.US, "$%.2f", tier.casePrice)
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
                text = String.format(Locale.US, "$%.3f", tier.unitPrice)
                setTextColor(Color.parseColor("#0F172A"))
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
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_PRODUCT_ID = "extra_product_id"
        const val EXTRA_PRODUCT_SKU = "extra_product_sku"
        const val EXTRA_PRODUCT_NAME = "extra_product_name"
    }
}
