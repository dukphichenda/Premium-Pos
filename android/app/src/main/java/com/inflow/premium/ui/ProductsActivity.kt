package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.ProductCategoryOption
import com.inflow.premium.data.ProductItem
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityProductsBinding
import com.inflow.premium.databinding.ItemProductCatalogBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class ProductsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityProductsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: ProductCatalogAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var selectedSchemeId = 100
    private var selectedLocationId = 100
    private var selectedCategoryId = 0
    private var selectedStockLevel = "all"
    private var currentQuery = ""
    private var sortAsc = true
    private var searchJob: Job? = null
    private val loadedItems = mutableListOf<ProductItem>()
    private val productCategories = mutableListOf<ProductCategoryOption>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityProductsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.PRODUCT)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.rvProducts,
            extraTopDp = 4,
            extraBottomScrollDp = 104
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.rvProducts.paddingTop != topH) {
                binding.rvProducts.setPadding(
                    binding.rvProducts.paddingLeft,
                    topH,
                    binding.rvProducts.paddingRight,
                    binding.rvProducts.paddingBottom
                )
            }
        }

        selectedSchemeId = session.getPricingSchemes().firstOrNull()?.id ?: 100
        selectedLocationId = session.getLocations().firstOrNull()?.id ?: 100
        productCategories.addAll(session.getProductCategories())
        updateFilterBadge()

        adapter = ProductCatalogAdapter(uiScope, session.baseUrl) { item ->
            val intent = Intent(this, ProductDetailActivity::class.java).apply {
                putExtra(ProductDetailActivity.EXTRA_PRODUCT_ID, item.id)
                putExtra(ProductDetailActivity.EXTRA_PRODUCT_SKU, item.sku)
                putExtra(ProductDetailActivity.EXTRA_PRODUCT_NAME, item.name)
            }
            startActivity(intent)
        }
        binding.rvProducts.layoutManager = LinearLayoutManager(this)
        binding.rvProducts.adapter = adapter

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadProducts() }

        binding.btnProdBack.setOnClickListener { finish() }
        binding.btnProdFilters.setOnClickListener { showFilterMenu() }
        binding.btnProdAdd.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java).putExtra(
                    "extra_url",
                    "${session.baseUrl}/products/new"
                )
            )
        }
        binding.btnProdRefresh.setOnClickListener { loadProducts() }
        binding.btnProdMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            val schemeName = session.getPricingSchemes().firstOrNull { it.id == selectedSchemeId }?.name ?: "Retail 1"
            val locName = session.getLocations().firstOrNull { it.id == selectedLocationId }?.name ?: "Main Warehouse"
            popup.menu.add(0, 1, 1, "Price Group: $schemeName")
            popup.menu.add(0, 2, 2, "Warehouse: $locName")
            popup.menu.add(0, 3, 3, if (sortAsc) "Sort Z → A" else "Sort A → Z")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> showSchemePicker()
                    2 -> showLocationPicker()
                    3 -> toggleSort()
                }
                true
            }
            popup.show()
        }

        binding.btnClearSearch.setOnClickListener {
            binding.etProductSearch.setText("")
        }

        binding.etProductSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                binding.btnClearSearch.visibility = if (q.isNotEmpty()) View.VISIBLE else View.GONE
                if (q == currentQuery) return
                currentQuery = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    loadProducts()
                }
            }
        })

        binding.etProductSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                searchJob?.cancel()
                currentQuery = binding.etProductSearch.text?.toString()?.trim().orEmpty()
                loadProducts()
                true
            } else {
                false
            }
        }

        loadProducts()
    }

    override fun onResume() {
        super.onResume()
        if (::binding.isInitialized) {
            binding.etProductSearch.clearFocus()
            binding.root.requestFocus()
            BottomNavHelper.dismissKeyboardAndClearFocus(this)
        }
    }

    private fun toggleSort() {
        sortAsc = !sortAsc
        applySortedList()
    }

    private fun applySortedList() {
        val sorted = if (sortAsc) {
            loadedItems.sortedBy { it.sku.lowercase(Locale.US) }
        } else {
            loadedItems.sortedByDescending { it.sku.lowercase(Locale.US) }
        }
        adapter.submitList(sorted)
    }

    private fun updateFilterBadge() {
        val defaultScheme = session.getPricingSchemes().firstOrNull()?.id ?: 100
        val defaultLoc = session.getLocations().firstOrNull()?.id ?: 100
        var active = 0
        if (selectedCategoryId > 0) active++
        if (selectedStockLevel != "all") active++
        if (selectedSchemeId != defaultScheme) active++
        if (selectedLocationId != defaultLoc) active++
        if (active > 0) {
            binding.tvFilterCount.visibility = View.VISIBLE
            binding.tvFilterCount.text = active.toString()
        } else {
            binding.tvFilterCount.visibility = View.GONE
        }
    }

    private fun stockLevelLabel(key: String): String = when (key) {
        "in_stock" -> "In Stock (> 0)"
        "low_stock" -> "Low Stock"
        "out_of_stock" -> "Out of Stock (≤ 0)"
        else -> "All Levels"
    }

    private fun showFilterMenu() {
        val catName = if (selectedCategoryId > 0) {
            productCategories.firstOrNull { it.id == selectedCategoryId }?.name ?: "Selected"
        } else {
            "All Categories"
        }
        val stockName = stockLevelLabel(selectedStockLevel)
        val schemeName = session.getPricingSchemes().firstOrNull { it.id == selectedSchemeId }?.name ?: "Retail 1"
        val locName = session.getLocations().firstOrNull { it.id == selectedLocationId }?.name ?: "Main Warehouse"
        val options = arrayOf(
            "Category: $catName",
            "Stock Level: $stockName",
            "Price Group: $schemeName",
            "Warehouse: $locName"
        )
        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Product Filters")
            .setItems(options) { d, which ->
                d.dismiss()
                when (which) {
                    0 -> showCategoryPicker()
                    1 -> showStockLevelPicker()
                    2 -> showSchemePicker()
                    3 -> showLocationPicker()
                }
            }
            .setNeutralButton("Reset") { d, _ ->
                selectedCategoryId = 0
                selectedStockLevel = "all"
                selectedSchemeId = session.getPricingSchemes().firstOrNull()?.id ?: 100
                selectedLocationId = session.getLocations().firstOrNull()?.id ?: 100
                updateFilterBadge()
                d.dismiss()
                loadProducts()
            }
            .setPositiveButton("Apply Filters") { d, _ ->
                d.dismiss()
                loadProducts()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .create()
        attachEscClose(dlg)
        dlg.show()
    }

    private fun showCategoryPicker() {
        val opts = mutableListOf(ProductCategoryOption(0, "All Categories"))
        opts.addAll(productCategories)
        val labels = opts.map { it.name }.toTypedArray()
        val checked = opts.indexOfFirst { it.id == selectedCategoryId }.coerceAtLeast(0)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Category")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedCategoryId = opts[which].id
                updateFilterBadge()
                d.dismiss()
                loadProducts()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun showStockLevelPicker() {
        val keys = arrayOf("all", "in_stock", "low_stock", "out_of_stock")
        val labels = arrayOf("All Stock Levels", "In Stock (> 0)", "Low Stock", "Out of Stock (≤ 0)")
        val checked = keys.indexOf(selectedStockLevel).coerceAtLeast(0)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Stock Level (Qty Available)")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedStockLevel = keys[which]
                updateFilterBadge()
                d.dismiss()
                loadProducts()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun showSchemePicker() {
        val schemes = session.getPricingSchemes()
        if (schemes.isEmpty()) return
        val labels = schemes.map { it.name }.toTypedArray()
        val checked = schemes.indexOfFirst { it.id == selectedSchemeId }.coerceAtLeast(0)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Price Group")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedSchemeId = schemes[which].id
                updateFilterBadge()
                d.dismiss()
                loadProducts()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun showLocationPicker() {
        val locs = session.getLocations()
        if (locs.isEmpty()) return
        val labels = locs.map { it.name }.toTypedArray()
        val checked = locs.indexOfFirst { it.id == selectedLocationId }.coerceAtLeast(0)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Warehouse / Location")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedLocationId = locs[which].id
                updateFilterBadge()
                d.dismiss()
                loadProducts()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun loadProducts() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.searchProductsCatalog(
                    query = currentQuery,
                    schemeId = selectedSchemeId,
                    locationId = selectedLocationId,
                    categoryId = selectedCategoryId,
                    stockLevel = selectedStockLevel
                )
                if (res.categories.isNotEmpty()) {
                    productCategories.clear()
                    productCategories.addAll(res.categories)
                }
                loadedItems.clear()
                loadedItems.addAll(res.products)
                applySortedList()
                binding.tvEmptyProducts.visibility = if (res.products.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@ProductsActivity, e.message ?: "Failed to load products", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@ProductsActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
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

    private class ProductCatalogAdapter(
        private val scope: CoroutineScope,
        private val baseUrl: String,
        private val onClick: (ProductItem) -> Unit
    ) : RecyclerView.Adapter<ProductCatalogAdapter.VH>() {
        private val items = mutableListOf<ProductItem>()
        private val numFmt = DecimalFormat("#,##0")

        fun submitList(newItems: List<ProductItem>) {
            items.clear()
            items.addAll(newItems)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val binding = ItemProductCatalogBinding.inflate(
                LayoutInflater.from(parent.context),
                parent,
                false
            )
            return VH(binding)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val p = items[position]
            val b = holder.binding
            b.tvProdName.text = p.name.ifBlank { p.sku }
            b.tvProdSku.text = p.sku
            b.tvProdKitBadge.visibility = if (p.isKit) View.VISIBLE else View.GONE

            ImageLoader.load(scope, baseUrl, p.imageUrl, b.ivProdThumb, b.ivProdIcon)

            val stockStr = if (p.stockAvailable == p.stockAvailable.toLong().toDouble()) {
                numFmt.format(p.stockAvailable.toLong())
            } else {
                String.format(Locale.US, "%.2f", p.stockAvailable)
            }
            b.tvProdStock.text = "Available: $stockStr ${p.uom}"
            if (p.stockAvailable > 0) {
                b.tvProdStock.setTextColor(Color.parseColor("#059669"))
                b.tvProdStock.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            } else {
                b.tvProdStock.setTextColor(Color.parseColor("#DC2626"))
                b.tvProdStock.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEE2E2"))
            }

            val hasCase = p.salesUom.isNotBlank() && !p.salesUom.equals(p.uom, ignoreCase = true) && p.salesUomRatioStd > 1.0
            val perPcsPrice = when {
                p.pricePerPcs > 0 -> p.pricePerPcs
                hasCase && p.unitPrice > 2.0 -> p.unitPrice / p.salesUomRatioStd
                else -> p.unitPrice
            }
            val priceStr = if (perPcsPrice >= 1.0) {
                String.format(Locale.US, "$%.2f / %s", perPcsPrice, p.uom)
            } else {
                String.format(Locale.US, "$%.4f / %s", perPcsPrice, p.uom)
            }
            b.tvProdPrice.text = priceStr

            b.root.setOnClickListener { onClick(p) }
        }

        override fun getItemCount(): Int = items.size

        class VH(val binding: ItemProductCatalogBinding) : RecyclerView.ViewHolder(binding.root)
    }
}
