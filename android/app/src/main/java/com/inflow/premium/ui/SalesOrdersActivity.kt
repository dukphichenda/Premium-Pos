package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivitySalesOrdersBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class SalesOrdersActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySalesOrdersBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: SalesOrdersAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentStatus = "Open"
    private var currentDateFilter = "All"
    private var currentSearch = ""
    private var currentPage = 1
    private var hasMore = false
    private var isLoading = false
    private var suppressChipEvent = false
    private var searchJob: Job? = null

    private val detailLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                currentPage = 1
                loadOrders(append = false)
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivitySalesOrdersBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        if (!session.isMainAdmin()) {
            session.selectedBranch = session.getUserBranchId()?.toString() ?: "main"
        }

        setupRecycler()
        setupFilters()
        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.SO)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.rvOrders,
            fabView = binding.fabNewOrder,
            extraTopDp = 4,
            extraBottomScrollDp = 152
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.rvOrders.paddingTop != topH) {
                binding.rvOrders.setPadding(
                    binding.rvOrders.paddingLeft,
                    topH,
                    binding.rvOrders.paddingRight,
                    binding.rvOrders.paddingBottom
                )
            }
        }

        binding.fabNewOrder.setOnClickListener {
            openOrderDetail(0)
        }

        refreshBootstrapThenLoad()
    }

    override fun onResume() {
        super.onResume()
        if (::binding.isInitialized) {
            binding.etSearch.clearFocus()
            binding.root.requestFocus()
            BottomNavHelper.dismissKeyboardAndClearFocus(this)
        }
    }

    private fun setupRecycler() {
        adapter = SalesOrdersAdapter { order ->
            openOrderDetail(order.id)
        }
        val lm = LinearLayoutManager(this)
        binding.rvOrders.layoutManager = lm
        binding.rvOrders.adapter = adapter

        binding.rvOrders.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(recyclerView: RecyclerView, dx: Int, dy: Int) {
                if (dy <= 0 || isLoading || !hasMore) return
                val visible = lm.childCount
                val total = lm.itemCount
                val firstVisible = lm.findFirstVisibleItemPosition()
                if (firstVisible + visible >= total - 5) {
                    currentPage += 1
                    loadOrders(append = true)
                }
            }
        })

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener {
            currentPage = 1
            loadOrders(append = false)
        }
    }

    private fun setupFilters() {
        binding.chipGroupStatus.setOnCheckedStateChangeListener { _, checkedIds ->
            if (suppressChipEvent) return@setOnCheckedStateChangeListener
            val checkedId = checkedIds.firstOrNull() ?: return@setOnCheckedStateChangeListener
            val newStatus = when (checkedId) {
                R.id.chipOpen -> "Open"
                R.id.chipPaid -> "Paid"
                R.id.chipCancelled -> "Cancelled"
                R.id.chipAll -> "All"
                else -> "Open"
            }
            if (newStatus != currentStatus) {
                currentStatus = newStatus
                currentPage = 1
                loadOrders(append = false)
            }
        }

        binding.btnDateFilter.setOnClickListener { showDateFilterDialog() }

        binding.btnClearSearch.setOnClickListener {
            binding.etSearch.setText("")
        }

        binding.etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentSearch) return
                currentSearch = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(350)
                    currentPage = 1
                    loadOrders(append = false)
                }
            }
        })

        binding.etSearch.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEARCH) {
                searchJob?.cancel()
                currentSearch = binding.etSearch.text?.toString()?.trim().orEmpty()
                currentPage = 1
                loadOrders(append = false)
                true
            } else {
                false
            }
        }
    }

    private fun refreshBootstrapThenLoad() {
        uiScope.launch {
            try {
                api.bootstrap()
                if (!session.isMainAdmin()) {
                    session.selectedBranch = session.getUserBranchId()?.toString() ?: "main"
                }
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
            } catch (_: Exception) {
            }
            currentPage = 1
            loadOrders(append = false)
        }
    }

    private fun loadOrders(append: Boolean) {
        if (isLoading && append) return
        isLoading = true
        if (!append) {
            binding.swipeRefresh.isRefreshing = true
        }

        uiScope.launch {
            try {
                val res = api.getSalesOrders(
                    branch = session.selectedBranch,
                    status = currentStatus,
                    dateFilter = currentDateFilter,
                    search = currentSearch,
                    page = currentPage
                )
                hasMore = res.hasMore
                adapter.submitList(res.orders, append = append)
                binding.tvEmptyOrders.visibility =
                    if (adapter.itemCount == 0) View.VISIBLE else View.GONE

                binding.chipOpen.text = "Open (${res.counts.open})"
                binding.chipPaid.text = "Paid (${res.counts.paid})"
                binding.chipCancelled.text = "Cancelled (${res.counts.cancelled})"
                binding.chipAll.text = "All (${res.counts.total})"

                if (res.effectiveStatus.isNotBlank() &&
                    !res.effectiveStatus.equals(currentStatus, ignoreCase = true)
                ) {
                    currentStatus = res.effectiveStatus
                    suppressChipEvent = true
                    when (currentStatus.lowercase()) {
                        "open" -> binding.chipGroupStatus.check(R.id.chipOpen)
                        "paid" -> binding.chipGroupStatus.check(R.id.chipPaid)
                        "cancelled" -> binding.chipGroupStatus.check(R.id.chipCancelled)
                        else -> binding.chipGroupStatus.check(R.id.chipAll)
                    }
                    suppressChipEvent = false
                }
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    Toast.makeText(this@SalesOrdersActivity, "Session expired. Please sign in.", Toast.LENGTH_SHORT).show()
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@SalesOrdersActivity, e.message ?: "Failed to load orders", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@SalesOrdersActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                isLoading = false
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun showDateFilterDialog() {
        val keys = arrayOf("All", "Today", "Yesterday", "This Week", "This Month", "Last 30 Days")
        val labels = arrayOf("All Dates", "Today", "Yesterday", "This Week", "This Month", "Last 30 Days")
        val checkedIdx = keys.indexOf(currentDateFilter).coerceAtLeast(0)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Date Filter")
            .setSingleChoiceItems(labels, checkedIdx) { dialog, which ->
                currentDateFilter = keys[which]
                binding.btnDateFilter.text = labels[which]
                dialog.dismiss()
                currentPage = 1
                loadOrders(append = false)
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
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

    private fun openOrderDetail(orderId: Int) {
        val intent = Intent(this, SalesOrderDetailActivity::class.java)
            .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, orderId)
        detailLauncher.launch(intent)
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
}
