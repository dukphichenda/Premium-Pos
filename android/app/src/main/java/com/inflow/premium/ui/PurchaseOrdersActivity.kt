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
import com.inflow.premium.data.PurchaseOrderListItem
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityPurchaseOrdersBinding
import com.inflow.premium.databinding.ItemPurchaseOrderBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class PurchaseOrdersActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPurchaseOrdersBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: PoAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentStatus = "All"
    private var currentQuery = ""
    private var searchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityPurchaseOrdersBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = null,
            bottomScrimView = null,
            scrollableView = binding.rvPurchaseOrders,
            extraTopDp = 4,
            extraBottomScrollDp = 24
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.rvPurchaseOrders.paddingTop != topH) {
                binding.rvPurchaseOrders.setPadding(
                    binding.rvPurchaseOrders.paddingLeft,
                    topH,
                    binding.rvPurchaseOrders.paddingRight,
                    binding.rvPurchaseOrders.paddingBottom
                )
            }
        }

        adapter = PoAdapter { po ->
            val intent = Intent(this, PurchaseOrderDetailActivity::class.java).apply {
                putExtra(PurchaseOrderDetailActivity.EXTRA_PO_ID, po.id)
                putExtra(PurchaseOrderDetailActivity.EXTRA_PO_NUMBER, po.orderNumber)
            }
            startActivity(intent)
        }
        binding.rvPurchaseOrders.layoutManager = LinearLayoutManager(this)
        binding.rvPurchaseOrders.adapter = adapter

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadPurchaseOrders() }

        binding.btnPoBack.setOnClickListener { finish() }
        binding.btnPoStatusPill.setOnClickListener { showStatusDialog() }
        binding.tvPoFiltersBtn.setOnClickListener { showStatusDialog() }
        binding.btnPoAdd.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java).putExtra("extra_url", "${session.baseUrl}/purchases/new")
            )
        }
        binding.btnPoRefresh.setOnClickListener { loadPurchaseOrders() }
        binding.btnPoMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Filter Status")
            popup.menu.add(0, 2, 2, "Open in Web App")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> showStatusDialog()
                    2 -> startActivity(
                        Intent(this, MainActivity::class.java).putExtra("extra_url", "${session.baseUrl}/purchases?view=table")
                    )
                }
                true
            }
            popup.show()
        }

        binding.etPoSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                if (q == currentQuery) return
                currentQuery = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    loadPurchaseOrders()
                }
            }
        })

        binding.etPoSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                searchJob?.cancel()
                currentQuery = binding.etPoSearch.text?.toString()?.trim().orEmpty()
                loadPurchaseOrders()
                true
            } else {
                false
            }
        }

        loadPurchaseOrders()
    }

    private fun showStatusDialog() {
        val opts = arrayOf("All", "Unfulfilled", "Fulfilled")
        val idx = opts.indexOf(currentStatus).coerceAtLeast(0)
        MaterialAlertDialogBuilder(this)
            .setTitle("Purchase Order Status")
            .setSingleChoiceItems(opts, idx) { d, which ->
                currentStatus = opts[which]
                binding.btnPoStatusPill.text = "$currentStatus ⌄"
                d.dismiss()
                loadPurchaseOrders()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun loadPurchaseOrders() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getPurchaseOrders(currentQuery, currentStatus)
                adapter.submitList(res.orders)
                binding.tvPoCountBadge.text = "(${res.totalCount})"
                binding.tvEmptyPo.visibility = if (res.orders.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: ApiException) {
                Toast.makeText(this@PurchaseOrdersActivity, e.message ?: "Failed to load POs", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@PurchaseOrdersActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    private class PoAdapter(
        private val onClick: (PurchaseOrderListItem) -> Unit
    ) : RecyclerView.Adapter<PoAdapter.VH>() {
        private val items = mutableListOf<PurchaseOrderListItem>()
        private val moneyFmt = DecimalFormat("#,##0.00")

        fun submitList(newItems: List<PurchaseOrderListItem>) {
            items.clear()
            items.addAll(newItems)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val binding = ItemPurchaseOrderBinding.inflate(LayoutInflater.from(parent.context), parent, false)
            return VH(binding)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val po = items[position]
            val b = holder.binding
            b.tvPoNumber.text = po.orderNumber
            b.tvPoVendor.text = po.vendorName
            b.tvPoTotal.text = "$${moneyFmt.format(po.total)}"
            b.tvPoDate.text = po.orderDate

            if (po.isFulfilled) {
                b.tvPoStatusBadge.text = "FULFILLED"
                b.tvPoStatusBadge.setTextColor(Color.WHITE)
                b.tvPoStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#6D4C2B"))
            } else {
                b.tvPoStatusBadge.text = "UNFULFILLED"
                b.tvPoStatusBadge.setTextColor(Color.parseColor("#6D4C2B"))
                b.tvPoStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            }

            b.root.setOnClickListener { onClick(po) }
        }

        override fun getItemCount(): Int = items.size

        class VH(val binding: ItemPurchaseOrderBinding) : RecyclerView.ViewHolder(binding.root)
    }
}
