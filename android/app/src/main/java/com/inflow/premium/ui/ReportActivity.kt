package com.inflow.premium.ui

import android.content.Intent
import android.os.Bundle
import android.view.KeyEvent
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityReportBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class ReportActivity : AppCompatActivity() {

    private lateinit var binding: ActivityReportBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private var currentDateFilter = "Today"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            redirectToLogin()
            return
        }

        binding = ActivityReportBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.REPORT)

        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadReport() }
        binding.btnReportDate.setOnClickListener { showDateFilterDialog() }
        binding.btnReportWeb.setOnClickListener {
            startActivity(
                Intent(this, MainActivity::class.java)
                    .putExtra("extra_url", api.buildWebPortalUrl("/reports"))
            )
        }

        updateBranchSubtitle()
        loadReport()
    }

    override fun onResume() {
        super.onResume()
        if (::session.isInitialized) {
            updateBranchSubtitle()
            loadReport()
        }
    }

    private fun updateBranchSubtitle() {
        val branchKey = session.selectedBranch
        val branchLabel = when {
            branchKey == "all" -> "All Branches"
            branchKey == "main" || branchKey == "0" -> "Main Store (HQ)"
            else -> session.getBranches().firstOrNull { it.id == branchKey }?.name ?: "Branch #$branchKey"
        }
        binding.toolbar.subtitle = branchLabel
    }

    private fun showDateFilterDialog() {
        val keys = arrayOf("Today", "Yesterday", "This Week", "This Month", "Last 30 Days", "All")
        val labels = arrayOf("Today", "Yesterday", "This Week", "This Month", "Last 30 Days", "All Dates")
        val idx = keys.indexOf(currentDateFilter).coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Report Period")
            .setSingleChoiceItems(labels, idx) { d, which ->
                currentDateFilter = keys[which]
                binding.btnReportDate.text = "Period: ${labels[which]}"
                d.dismiss()
                loadReport()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun loadReport() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val rep = api.getReportsSummary(session.selectedBranch, currentDateFilter)
                binding.tvGrossSales.text = String.format(Locale.US, "$%.2f", rep.grossSales)
                binding.tvSalesSplit.text = String.format(
                    Locale.US,
                    "Paid: $%.2f (%d) • Open: $%.2f (%d)",
                    rep.paidSales,
                    rep.paidCount,
                    rep.openSales,
                    rep.openCount
                )
                val df = DecimalFormat("#,##0")
                binding.tvDeliveryFees.text =
                    "Delivery Fees: ${df.format(Math.round(rep.deliveryFeesKhr))} KHR • Cancelled: ${rep.cancelledCount}"

                binding.llPaymentBreakdown.removeAllViews()
                if (rep.paymentBreakdown.isEmpty()) {
                    addEmptyLine(binding.llPaymentBreakdown, "No paid transactions in this period")
                } else {
                    for (pm in rep.paymentBreakdown) {
                        addKeyValueRow(
                            binding.llPaymentBreakdown,
                            "${pm.paymentMethod} (${pm.count})",
                            String.format(Locale.US, "$%.2f", pm.amount)
                        )
                    }
                }

                binding.llTopProducts.removeAllViews()
                if (rep.topProducts.isEmpty()) {
                    addEmptyLine(binding.llTopProducts, "No items sold in this period")
                } else {
                    for (tp in rep.topProducts) {
                        val qtyStr = if (tp.qty == tp.qty.toLong().toDouble()) tp.qty.toLong().toString() else String.format(Locale.US, "%.2f", tp.qty)
                        val title = if (tp.sku.isNotBlank()) "${tp.sku} • ${tp.productName}" else tp.productName
                        addKeyValueRow(
                            binding.llTopProducts,
                            "$title (Qty: $qtyStr)",
                            String.format(Locale.US, "$%.2f", tp.amount)
                        )
                    }
                }
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    redirectToLogin()
                    return@launch
                }
                Toast.makeText(this@ReportActivity, e.message ?: "Failed to load report", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@ReportActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun addEmptyLine(container: LinearLayout, msg: String) {
        val tv = TextView(this).apply {
            text = msg
            setTextColor(ContextCompat.getColor(this@ReportActivity, R.color.gray))
            textSize = 13f
        }
        container.addView(tv)
    }

    private fun addKeyValueRow(container: LinearLayout, left: String, right: String) {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = (6 * resources.displayMetrics.density).toInt() }
        }
        val tvLeft = TextView(this).apply {
            text = left
            setTextColor(ContextCompat.getColor(this@ReportActivity, R.color.black))
            textSize = 13f
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val tvRight = TextView(this).apply {
            text = right
            setTextColor(ContextCompat.getColor(this@ReportActivity, R.color.primary_dark))
            textSize = 13.5f
            setTypeface(null, android.graphics.Typeface.BOLD)
            setPadding((8 * resources.displayMetrics.density).toInt(), 0, 0, 0)
        }
        row.addView(tvLeft)
        row.addView(tvRight)
        container.addView(row)
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
}
