package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.CustomerCatalogItem
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityCustomersBinding
import com.inflow.premium.databinding.ItemCustomerRowBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class CustomersActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCustomersBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: CustomersAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentQuery = ""
    private var balanceFilter = "All" // All, With Balance
    private var searchJob: Job? = null
    private val allLoaded = mutableListOf<CustomerCatalogItem>()
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val intFmt = DecimalFormat("#,###")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityCustomersBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.rvCustomers,
            extraTopDp = 4,
            extraBottomScrollDp = 64
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.rvCustomers.paddingTop != topH) {
                binding.rvCustomers.setPadding(
                    binding.rvCustomers.paddingLeft,
                    topH,
                    binding.rvCustomers.paddingRight,
                    binding.rvCustomers.paddingBottom
                )
            }
        }

        adapter = CustomersAdapter { c ->
            val intent = Intent(this, CustomerDetailActivity::class.java).apply {
                putExtra(CustomerDetailActivity.EXTRA_CUSTOMER_ID, c.id)
                putExtra(CustomerDetailActivity.EXTRA_CUSTOMER_NAME, c.name)
            }
            startActivity(intent)
        }
        binding.rvCustomers.layoutManager = LinearLayoutManager(this)
        binding.rvCustomers.adapter = adapter

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadCustomers() }

        binding.btnCustBack.setOnClickListener { finish() }
        binding.btnCustFilterPill.setOnClickListener { showFilterDialog() }
        binding.tvCustFiltersBtn.setOnClickListener { showFilterDialog() }
        binding.btnCustAdd.setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java).putExtra("extra_url", "${session.baseUrl}/customers/new"))
        }
        binding.btnCustRefresh.setOnClickListener { loadCustomers() }
        binding.btnCustMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Filter Balance")
            popup.menu.add(0, 2, 2, "Open in Web App")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> showFilterDialog()
                    2 -> startActivity(
                        Intent(this, MainActivity::class.java).putExtra("extra_url", "${session.baseUrl}/customers")
                    )
                }
                true
            }
            popup.show()
        }

        binding.etCustSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                if (q == currentQuery) return
                currentQuery = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    loadCustomers()
                }
            }
        })

        binding.etCustSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                searchJob?.cancel()
                currentQuery = binding.etCustSearch.text?.toString()?.trim().orEmpty()
                loadCustomers()
                true
            } else {
                false
            }
        }

        loadCustomers()
    }

    private fun showFilterDialog() {
        val opts = arrayOf("All", "With Open Balance")
        val idx = if (balanceFilter == "With Balance") 1 else 0
        LiquidGlassDialog.builder(this)
            .setTitle("Customer Filter")
            .setSingleChoiceItems(opts, idx) { d, which ->
                balanceFilter = if (which == 1) "With Balance" else "All"
                binding.btnCustFilterPill.text = if (which == 1) "Due ⌄" else "All ⌄"
                d.dismiss()
                applyFilter()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun applyFilter() {
        val filtered = if (balanceFilter == "With Balance") {
            allLoaded.filter { it.openBalance > 0.001 }
        } else {
            allLoaded
        }
        adapter.submitList(filtered)
        binding.tvEmptyCust.visibility = if (filtered.isEmpty()) View.VISIBLE else View.GONE
    }

    private fun loadCustomers() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getCustomersCatalog(currentQuery, session.selectedBranch)
                allLoaded.clear()
                allLoaded.addAll(res.customers)
                applyFilter()
                binding.tvCustTotalCount.text = "${intFmt.format(res.totalCount)} Customers"
                binding.tvCustFooterTotal.text = "Total: ${res.totalCount}"
                binding.tvCustFooterDue.text = "Due: $${moneyFmt.format(res.totalDue)}"
            } catch (e: ApiException) {
                Toast.makeText(this@CustomersActivity, e.message ?: "Failed to load customers", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@CustomersActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    private class CustomersAdapter(
        private val onClick: (CustomerCatalogItem) -> Unit
    ) : RecyclerView.Adapter<CustomersAdapter.VH>() {
        private val items = mutableListOf<CustomerCatalogItem>()
        private val moneyFmt = DecimalFormat("#,##0.00")

        fun submitList(newItems: List<CustomerCatalogItem>) {
            items.clear()
            items.addAll(newItems)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val binding = ItemCustomerRowBinding.inflate(LayoutInflater.from(parent.context), parent, false)
            return VH(binding)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val c = items[position]
            val b = holder.binding
            b.tvCustName.text = c.name
            b.tvCustBalancePill.text = "$${moneyFmt.format(c.openBalance)}"
            if (c.openBalance > 0.001) {
                b.tvCustBalancePill.setTextColor(Color.parseColor("#DC2626"))
                b.tvCustBalancePill.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEE2E2"))
            } else {
                b.tvCustBalancePill.setTextColor(Color.parseColor("#334155"))
                b.tvCustBalancePill.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#F1F5F9"))
            }
            b.tvCustActiveBadge.text = if (c.isActive) "Active" else "Inactive"
            b.tvCustPhone.text = c.phone.ifBlank { c.contactName.ifBlank { "—" } }
            b.root.setOnClickListener { onClick(c) }
        }

        override fun getItemCount(): Int = items.size

        class VH(val binding: ItemCustomerRowBinding) : RecyclerView.ViewHolder(binding.root)
    }
}
