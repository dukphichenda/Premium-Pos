package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.inflow.premium.MainActivity
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.CustomerDetail
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityCustomerDetailBinding
import com.inflow.premium.databinding.ItemCustomerOrderBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class CustomerDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCustomerDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var customerId: Int = 0
    private var customerPhone: String = ""
    private var customerEmail: String = ""
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val qtyFmt = DecimalFormat("#,##0.##")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityCustomerDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        customerId = intent.getIntExtra(EXTRA_CUSTOMER_ID, 0)
        val initialName = intent.getStringExtra(EXTRA_CUSTOMER_NAME).orEmpty()
        if (initialName.isNotBlank()) {
            binding.tvCustDetHeaderName.text = "$initialName •"
            binding.tvCustDetFullName.text = initialName
        }

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollCustDetail,
            extraTopDp = 4,
            extraBottomScrollDp = 110
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollCustDetail.paddingTop != topH) {
                binding.scrollCustDetail.setPadding(
                    binding.scrollCustDetail.paddingLeft,
                    topH,
                    binding.scrollCustDetail.paddingRight,
                    binding.scrollCustDetail.paddingBottom
                )
            }
        }

        binding.btnCustDetBack.setOnClickListener { finish() }
        binding.btnCustDetRefresh.setOnClickListener { loadDetail() }
        binding.btnCustDetMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Open in Web App")
            popup.menu.add(0, 2, 2, "New Sales Order")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> openWebCustomer()
                    2 -> openCreateSo()
                }
                true
            }
            popup.show()
        }

        binding.btnCustCall.setOnClickListener {
            if (customerPhone.isNotBlank()) {
                startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$customerPhone")))
            } else {
                Toast.makeText(this, "No phone number", Toast.LENGTH_SHORT).show()
            }
        }
        binding.btnCustEmail.setOnClickListener {
            if (customerEmail.isNotBlank()) {
                startActivity(Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:$customerEmail")))
            } else {
                Toast.makeText(this, "No email address", Toast.LENGTH_SHORT).show()
            }
        }
        binding.btnCustCreateSo.setOnClickListener { openCreateSo() }
        binding.btnCustOpenSo.setOnClickListener { openCreateSo() }
        binding.btnCustEditProfile.setOnClickListener { openWebCustomer() }

        loadDetail()
    }

    private fun openWebCustomer() {
        val url = if (customerId > 0) "${session.baseUrl}/customers/$customerId" else "${session.baseUrl}/customers"
        startActivity(Intent(this, MainActivity::class.java).putExtra("extra_url", url))
    }

    private fun openCreateSo() {
        startActivity(
            Intent(this, SalesOrderDetailActivity::class.java)
                .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, 0)
        )
    }

    private fun loadDetail() {
        if (customerId <= 0) return
        binding.progressCustDetail.visibility = View.VISIBLE
        uiScope.launch {
            try {
                val d = api.getCustomerDetail(customerId)
                bindDetail(d)
            } catch (e: Exception) {
                Toast.makeText(this@CustomerDetailActivity, e.message ?: "Failed to load customer", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressCustDetail.visibility = View.GONE
            }
        }
    }

    private fun bindDetail(d: CustomerDetail) {
        customerPhone = d.phone
        customerEmail = d.email

        binding.tvCustDetHeaderName.text = "${d.name} •"
        binding.tvCustDetFullName.text = d.contactName.ifBlank { d.name }
        binding.tvCustDetStatus.text = if (d.isActive) "• Active Customer" else "• Inactive"
        binding.tvCustDetSince.text = buildString {
            if (d.createdAt.isNotBlank()) append("Since: ${d.createdAt} • ")
            append(d.branchName)
        }
        binding.tvCustDetOpenBal.text = "$${moneyFmt.format(d.openBalance)}"
        binding.btnCustCall.text = if (d.phone.isNotBlank()) "📞 ${d.phone}" else "📞 No phone"
        binding.btnCustEmail.text = if (d.email.isNotBlank()) "✉ ${d.email}" else "✉ No email"

        binding.tvCustDetScheme.text = d.pricingSchemeName
        binding.tvCustDetTerms.text = d.paymentTerms
        binding.tvCustDetSpent.text = "$${moneyFmt.format(d.totalSpent)} USD"
        binding.tvCustDetAddress.text = d.address.ifBlank { "No address on file" }
        binding.tvCustDetNotes.text = d.notes.ifBlank { "No remarks or delivery preferences" }

        binding.tabCustOrders.text = "Orders (${d.orders.size})"
        binding.llCustOrders.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (o in d.orders) {
            val ob = ItemCustomerOrderBinding.inflate(inflater, binding.llCustOrders, false)
            ob.tvCustOrderNum.text = "#${o.orderNumber}"
            ob.tvCustOrderDate.text = o.orderDate
            val isPaid = o.paymentStatus.equals("PAID", true) || o.status.equals("PAID", true)
            ob.tvCustOrderBadge.text = if (isPaid) "PAID" else "OPEN"
            if (isPaid) {
                ob.tvCustOrderBadge.setTextColor(Color.parseColor("#059669"))
                ob.tvCustOrderBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            } else {
                ob.tvCustOrderBadge.setTextColor(Color.parseColor("#EA580C"))
                ob.tvCustOrderBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FFF7ED"))
            }
            ob.tvCustOrderItems.text = o.itemsSummary.ifBlank { "Sales Order" }
            ob.tvCustOrderMeta.text = "Qty: ${qtyFmt.format(o.totalQty)} • ${o.locationName}"
            ob.tvCustOrderTotal.text = "Total: $${moneyFmt.format(o.totalAmount)}"
            ob.root.setOnClickListener {
                startActivity(
                    Intent(this, SalesOrderDetailActivity::class.java)
                        .putExtra(SalesOrderDetailActivity.EXTRA_ORDER_ID, o.id)
                )
            }
            binding.llCustOrders.addView(ob.root)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_CUSTOMER_ID = "extra_customer_id"
        const val EXTRA_CUSTOMER_NAME = "extra_customer_name"
    }
}
