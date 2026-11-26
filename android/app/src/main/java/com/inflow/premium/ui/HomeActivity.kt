package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityHomeBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.util.Locale

class HomeActivity : AppCompatActivity() {

    private lateinit var binding: ActivityHomeBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var recentAdapter: SalesOrdersAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private val detailLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                loadDashboard()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityHomeBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        if (!session.isMainAdmin()) {
            session.selectedBranch = session.getUserBranchId()?.toString() ?: "main"
        }

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.HOME)

        recentAdapter = SalesOrdersAdapter { order ->
            detailLauncher.launch(
                Intent(this, SalesOrderDetailActivity::class.java)
                    .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, order.id)
            )
        }
        binding.rvRecentOrders.layoutManager = LinearLayoutManager(this)
        binding.rvRecentOrders.adapter = recentAdapter

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadDashboard() }

        binding.btnHomeNewOrder.setOnClickListener {
            detailLauncher.launch(
                Intent(this, SalesOrderDetailActivity::class.java)
                    .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, 0)
            )
        }
        binding.cardHomeOpenOrders.setOnClickListener { openSalesTab() }
        binding.btnQuickSales.setOnClickListener { openSalesTab() }
        binding.btnQuickWebPortal.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra("extra_url", api.buildWebPortalUrl("/"))
            )
        }

        updateToolbarSubtitle()
        loadDashboard()
    }

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            updateToolbarSubtitle()
            loadDashboard()
        }
    }

    private fun openSalesTab() {
        startActivity(
            Intent(this, SalesOrdersActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        )
        @Suppress("DEPRECATION")
        overridePendingTransition(0, 0)
    }

    private fun updateToolbarSubtitle() {
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "all" -> "All Branches"
            branchKey == "main" || branchKey == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        val user = session.getDisplayName().ifBlank { session.getUsername() }
        binding.toolbar.subtitle = "$branchLabel • $user"
    }

    private fun loadDashboard() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val dash = api.getDashboard(session.selectedBranch)
                binding.tvPaidTodayUsd.text = String.format(Locale.US, "$%.2f", dash.todayPaidTotal)
                binding.tvTodayOrderMeta.text = "${dash.todayOrders} orders today • ${dash.paidCountToday} paid"
                binding.tvOpenOrdersCount.text = dash.openCount.toString()
                binding.tvOpenOrdersAmount.text = String.format(Locale.US, "$%.2f open total", dash.openAmount)
                recentAdapter.submitList(dash.recentOrders, append = false)
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@HomeActivity, e.message ?: "Failed to load dashboard", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@HomeActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
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
}
