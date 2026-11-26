package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.inflow.premium.MainActivity
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.PurchaseOrderDetail
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityPurchaseOrderDetailBinding
import com.inflow.premium.databinding.ItemPoLineBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class PurchaseOrderDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPurchaseOrderDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var poId: Int = 0
    private var poNumber: String = "PO"
    private val moneyFmt = DecimalFormat("#,##0.00")
    private val qtyFmt = DecimalFormat("#,##0.##")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityPurchaseOrderDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        poId = intent.getIntExtra(EXTRA_PO_ID, 0)
        poNumber = intent.getStringExtra(EXTRA_PO_NUMBER).orEmpty().ifBlank { "PO" }
        binding.tvPoHeaderTitle.text = poNumber
        binding.tvPoDetailNumber.text = poNumber

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollPoDetail,
            extraTopDp = 4,
            extraBottomScrollDp = 120
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollPoDetail.paddingTop != topH) {
                binding.scrollPoDetail.setPadding(
                    binding.scrollPoDetail.paddingLeft,
                    topH,
                    binding.scrollPoDetail.paddingRight,
                    binding.scrollPoDetail.paddingBottom
                )
            }
        }

        binding.btnPoDetBack.setOnClickListener { finish() }
        binding.btnPoDetRefresh.setOnClickListener { loadDetail() }
        binding.btnPoDetMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            popup.menu.add(0, 1, 1, "Open in Web App")
            popup.menu.add(0, 2, 2, "Refresh")
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> openWebPo()
                    2 -> loadDetail()
                }
                true
            }
            popup.show()
        }

        binding.btnPoOpenWeb.setOnClickListener { openWebPo() }
        binding.btnPoPayReceive.setOnClickListener { openWebPo() }

        loadDetail()
    }

    private fun openWebPo() {
        val url = if (poId > 0) "${session.baseUrl}/purchases?id=$poId" else "${session.baseUrl}/purchases"
        startActivity(Intent(this, MainActivity::class.java).putExtra("extra_url", url))
    }

    private fun loadDetail() {
        if (poId <= 0) return
        binding.progressPoDetail.visibility = View.VISIBLE
        uiScope.launch {
            try {
                val d = api.getPurchaseOrderDetail(poId)
                bindDetail(d)
            } catch (e: Exception) {
                Toast.makeText(this@PurchaseOrderDetailActivity, e.message ?: "Failed to load PO", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressPoDetail.visibility = View.GONE
            }
        }
    }

    private fun bindDetail(d: PurchaseOrderDetail) {
        binding.tvPoHeaderTitle.text = d.orderNumber
        binding.tvPoDetailNumber.text = d.orderNumber
        binding.tvPoStepPurchase.text = "Purchase (${d.lines.size})"
        binding.tvPoStepReceive.text = if (d.isFulfilled) "✓ Receive (100%)" else "Pending Receive"

        binding.tvPoDetailFulfillBadge.text = if (d.isFulfilled) "Fulfilled" else "Unfulfilled"
        binding.tvPoDetailPayBadge.text = if (d.isPaid) "Paid" else "Unpaid"
        if (d.isPaid) {
            binding.tvPoDetailPayBadge.setTextColor(Color.parseColor("#059669"))
            binding.tvPoDetailPayBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
        }

        binding.tvPoOrderedOn.text = d.orderDate.ifBlank { "—" }
        binding.tvPoAssignedTo.text = d.assignedTo
        binding.tvPoVendorName.text = d.vendorName
        binding.tvPoLocationBox.text = "📍 ${d.locationName}"

        val balText = "$${moneyFmt.format(d.balanceDue)}"
        binding.tvPoBalanceLabel.text = if (d.isPaid) "PAID IN FULL" else "UNPAID BALANCE"
        binding.tvPoBalanceAmount.text = if (d.isPaid) "$${moneyFmt.format(d.totalAmount)}" else balText
        binding.tvPoFooterBalance.text = balText

        binding.tvPoItemsTitle.text = "ITEMS ORDERED (${d.lines.size})"
        binding.llPoLines.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (line in d.lines) {
            val lb = ItemPoLineBinding.inflate(inflater, binding.llPoLines, false)
            lb.tvPoLineName.text = line.productName.ifBlank { line.sku }
            lb.tvPoLineSku.text = line.sku
            lb.tvPoLineSubtotal.text = "$${moneyFmt.format(line.subtotal)}"
            lb.tvPoLineQty.text = "${qtyFmt.format(line.quantity)} ${line.uom}"
            lb.tvPoLineUnitCost.text = "@ $${moneyFmt.format(line.unitPrice)} / ${line.uom}"
            ImageLoader.load(uiScope, session.baseUrl, line.imageUrl, lb.ivPoLineThumb, lb.ivPoLineIcon)
            binding.llPoLines.addView(lb.root)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_PO_ID = "extra_po_id"
        const val EXTRA_PO_NUMBER = "extra_po_number"
    }
}
