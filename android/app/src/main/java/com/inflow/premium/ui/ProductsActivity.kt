package com.inflow.premium.ui

import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
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
import java.util.Locale

class ProductsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityProductsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: ProductCatalogAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var selectedSchemeId = 100
    private var selectedLocationId = 100
    private var currentQuery = ""
    private var searchJob: Job? = null

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

        selectedSchemeId = session.getPricingSchemes().firstOrNull()?.id ?: 100
        selectedLocationId = session.getLocations().firstOrNull()?.id ?: 100
        updateFilterLabels()

        adapter = ProductCatalogAdapter()
        binding.rvProducts.layoutManager = LinearLayoutManager(this)
        binding.rvProducts.adapter = adapter

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadProducts() }

        binding.btnProdScheme.setOnClickListener { showSchemePicker() }
        binding.btnProdLocation.setOnClickListener { showLocationPicker() }

        binding.etProductSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
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

    private fun updateFilterLabels() {
        val schemeName = session.getPricingSchemes().firstOrNull { it.id == selectedSchemeId }?.name ?: "Retail 1"
        val locName = session.getLocations().firstOrNull { it.id == selectedLocationId }?.name ?: "Main Warehouse"
        binding.btnProdScheme.text = "Price: $schemeName"
        binding.btnProdLocation.text = "Stock: $locName"
    }

    private fun showSchemePicker() {
        val schemes = session.getPricingSchemes()
        if (schemes.isEmpty()) return
        val labels = schemes.map { it.name }.toTypedArray()
        val checked = schemes.indexOfFirst { it.id == selectedSchemeId }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Price Group")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedSchemeId = schemes[which].id
                updateFilterLabels()
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

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Warehouse / Location")
            .setSingleChoiceItems(labels, checked) { d, which ->
                selectedLocationId = locs[which].id
                updateFilterLabels()
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
                val list = api.searchProducts(currentQuery, selectedSchemeId, selectedLocationId)
                adapter.submitList(list)
                binding.tvEmptyProducts.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
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

    private class ProductCatalogAdapter : RecyclerView.Adapter<ProductCatalogAdapter.VH>() {
        private val items = mutableListOf<ProductItem>()

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
            holder.binding.tvProdSku.text = p.sku
            holder.binding.tvProdName.text = p.name
            holder.binding.tvProdPrice.text = String.format(Locale.US, "$%.4f", p.unitPrice)
            val stockStr = if (p.stockAvailable == p.stockAvailable.toLong().toDouble()) {
                p.stockAvailable.toLong().toString()
            } else {
                String.format(Locale.US, "%.2f", p.stockAvailable)
            }
            val casePart = if (p.salesUom.isNotBlank() && !p.salesUom.equals(p.uom, ignoreCase = true)) {
                val rStr = if (p.salesUomRatioStd == p.salesUomRatioStd.toLong().toDouble()) p.salesUomRatioStd.toLong().toString() else String.format(Locale.US, "%.2f", p.salesUomRatioStd)
                " • 1 ${p.salesUom} = $rStr ${p.uom}"
            } else ""
            holder.binding.tvProdMeta.text = "UOM: ${p.uom}$casePart • Stock: $stockStr"
        }

        override fun getItemCount(): Int = items.size

        class VH(val binding: ItemProductCatalogBinding) : RecyclerView.ViewHolder(binding.root)
    }
}
