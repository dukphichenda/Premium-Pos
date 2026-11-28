package com.inflow.premium.ui

import android.app.Activity
import android.app.DatePickerDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.widget.NestedScrollView
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ProductItem
import com.inflow.premium.data.PurchaseOrderDetail
import com.inflow.premium.data.PurchaseOrderLine
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.TransferLocationOption
import com.inflow.premium.data.VendorOption
import com.inflow.premium.databinding.ActivityPurchaseOrderDetailBinding
import com.inflow.premium.databinding.ItemPoLineBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale

class PurchaseOrderDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityPurchaseOrderDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var poId: Int = 0
    private var poNumber: String = "PO"
    private var orderDateDisplay: String = ""
    private var orderDateIso: String = ""
    private var status: String = "ISSUED"
    private var paymentStatus: String = "UNPAID"
    private var vendorId: Int = 0
    private var vendorName: String = "Select Vendor"
    private var locationId: Int = 100
    private var locationName: String = "Main Warehouse"
    private var paidAmount: Double = 0.0

    private var vendors: List<VendorOption> = emptyList()
    private var locations: List<TransferLocationOption> = emptyList()
    private val lines = mutableListOf<PurchaseOrderLine>()

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
        poNumber = intent.getStringExtra(EXTRA_PO_NUMBER).orEmpty().ifBlank { if (poId == 0) "New PO" else "PO" }
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
            extraBottomScrollDp = 128
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

        binding.tvPoVendorName.setOnClickListener { showVendorPicker() }
        binding.tvPoLocationBox.setOnClickListener { showLocationPicker() }
        binding.tvPoOrderedOn.setOnClickListener { showDatePicker() }
        binding.tvPoDetailFulfillBadge.setOnClickListener { showStatusPicker() }
        binding.tvPoDetailPayBadge.setOnClickListener { showPaymentStatusPicker() }
        binding.btnPoAddItem.setOnClickListener { showAddProductDialog() }

        binding.btnPoOpenWeb.setOnClickListener { savePo(markReceiveAndPay = false) }
        binding.btnPoPayReceive.setOnClickListener {
            LiquidGlassDialog.builder(this)
                .setTitle("Receive & Mark Paid")
                .setMessage("Mark $poNumber as RECEIVED & PAID and save changes now?")
                .setPositiveButton("Receive & Pay") { _, _ -> savePo(markReceiveAndPay = true) }
                .setNegativeButton("Cancel", null)
                .show()
        }

        loadDetail()
    }

    private fun openWebPo() {
        val url = if (poId > 0) "${session.baseUrl}/purchases?id=$poId" else "${session.baseUrl}/purchases/new"
        startActivity(Intent(this, MainActivity::class.java).putExtra("extra_url", url))
    }

    private fun loadDetail() {
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
        poId = d.id
        poNumber = d.orderNumber
        orderDateDisplay = d.orderDate
        orderDateIso = d.orderDateIso
        status = d.status.uppercase(Locale.US)
        paymentStatus = d.paymentStatus.uppercase(Locale.US)
        vendorId = d.vendorId
        vendorName = d.vendorName
        locationId = d.locationId
        locationName = d.locationName
        paidAmount = d.paidAmount
        vendors = d.vendors
        locations = d.locations

        lines.clear()
        lines.addAll(d.lines)

        binding.tvPoHeaderTitle.text = poNumber
        binding.tvPoDetailNumber.text = poNumber
        binding.tvPoAssignedTo.text = d.assignedTo
        binding.etPoNotes.setText(d.notes)

        renderHeaderFields()
        renderLinesAndTotals()
    }

    private fun renderHeaderFields() {
        val isFulfilled = status in setOf("RECEIVED", "FULFILLED", "COMPLETED")
        val isPaid = paymentStatus == "PAID"

        binding.tvPoStepPurchase.text = "Purchase (${lines.size})"
        binding.tvPoStepReceive.text = if (isFulfilled) "✓ Receive (100%)" else "Pending Receive"

        binding.tvPoDetailFulfillBadge.text = "${status.lowercase(Locale.US).replaceFirstChar { it.uppercaseChar() }} ⌄"
        if (isFulfilled) {
            binding.tvPoDetailFulfillBadge.setTextColor(Color.parseColor("#047857"))
            binding.tvPoDetailFulfillBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
        } else {
            binding.tvPoDetailFulfillBadge.setTextColor(Color.parseColor("#92400E"))
            binding.tvPoDetailFulfillBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
        }

        binding.tvPoDetailPayBadge.text = "${paymentStatus.lowercase(Locale.US).replaceFirstChar { it.uppercaseChar() }} ⌄"
        if (isPaid) {
            binding.tvPoDetailPayBadge.setTextColor(Color.parseColor("#059669"))
            binding.tvPoDetailPayBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
        } else {
            binding.tvPoDetailPayBadge.setTextColor(Color.parseColor("#B45309"))
            binding.tvPoDetailPayBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
        }

        binding.tvPoOrderedOn.text = "${orderDateDisplay.ifBlank { "Select Date" }} ⌄"
        binding.tvPoVendorName.text = "${vendorName.ifBlank { "Select Vendor" }} ⌄"
        binding.tvPoLocationBox.text = "📍 ${locationName.ifBlank { "Main Warehouse" }} ⌄"
    }

    private fun renderLinesAndTotals() {
        var total = 0.0
        for (ln in lines) {
            ln.subtotal = ln.quantity * ln.unitPrice
            total += ln.subtotal
        }
        val isPaid = paymentStatus == "PAID"
        val effectivePaid = if (isPaid) total else if (paymentStatus == "UNPAID") 0.0 else paidAmount.coerceAtMost(total)
        val balance = (total - effectivePaid).coerceAtLeast(0.0)

        binding.tvPoStepPurchase.text = "Purchase (${lines.size})"
        binding.tvPoBalanceLabel.text = if (isPaid) "PAID IN FULL" else "UNPAID BALANCE"
        binding.tvPoBalanceAmount.text = if (isPaid) "$${moneyFmt.format(total)}" else "$${moneyFmt.format(balance)}"
        binding.tvPoFooterBalance.text = "$${moneyFmt.format(balance)}"
        binding.tvPoItemsTitle.text = "ITEMS ORDERED (${lines.size})"

        binding.llPoLines.removeAllViews()
        val inflater = LayoutInflater.from(this)
        lines.forEachIndexed { idx, line ->
            val lb = ItemPoLineBinding.inflate(inflater, binding.llPoLines, false)
            lb.tvPoLineName.text = line.productName.ifBlank { line.sku }
            lb.tvPoLineSku.text = line.sku.ifBlank { "Tap to edit qty / cost" }
            lb.tvPoLineSubtotal.text = "$${moneyFmt.format(line.subtotal)}"
            lb.tvPoLineQty.text = "${qtyFmt.format(line.quantity)} ${line.uom} ✎"
            lb.tvPoLineUnitCost.text = "@ $${moneyFmt.format(line.unitPrice)} / ${line.uom}"
            ImageLoader.load(uiScope, session.baseUrl, line.imageUrl, lb.ivPoLineThumb, lb.ivPoLineIcon)
            lb.root.setOnClickListener { showEditLineDialog(idx) }
            binding.llPoLines.addView(lb.root)
        }
    }

    private fun showVendorPicker() {
        if (vendors.isEmpty()) {
            Toast.makeText(this, "No vendors available", Toast.LENGTH_SHORT).show()
            return
        }
        val names = vendors.map { it.name }.toTypedArray()
        val checked = vendors.indexOfFirst { it.id == vendorId }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Select Vendor")
            .setSingleChoiceItems(names, checked) { dlg, which ->
                vendorId = vendors[which].id
                vendorName = vendors[which].name
                renderHeaderFields()
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showLocationPicker() {
        val opts = locations.ifEmpty {
            session.getLocations().map { TransferLocationOption(it.id, it.name, false) }
        }
        if (opts.isEmpty()) return
        val names = opts.map { it.name }.toTypedArray()
        val checked = opts.indexOfFirst { it.id == locationId }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Receive To Warehouse")
            .setSingleChoiceItems(names, checked) { dlg, which ->
                locationId = opts[which].id
                locationName = opts[which].name
                renderHeaderFields()
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showDatePicker() {
        val cal = Calendar.getInstance()
        try {
            SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(orderDateIso)?.let { cal.time = it }
        } catch (_: Exception) {}
        DatePickerDialog(
            this,
            { _, y, m, day ->
                val c = Calendar.getInstance().apply { set(y, m, day) }
                orderDateIso = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(c.time)
                orderDateDisplay = SimpleDateFormat("MMM dd, yyyy", Locale.US).format(c.time)
                renderHeaderFields()
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun showStatusPicker() {
        val keys = arrayOf("DRAFT", "ISSUED", "RECEIVED")
        val labels = arrayOf("Draft", "Issued (Open)", "Received (Fulfilled)")
        val checked = keys.indexOf(status).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("PO Status")
            .setSingleChoiceItems(labels, checked) { dlg, which ->
                status = keys[which]
                renderHeaderFields()
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showPaymentStatusPicker() {
        val keys = arrayOf("UNPAID", "PAID")
        val labels = arrayOf("Unpaid", "Paid in Full")
        val checked = keys.indexOf(if (paymentStatus == "PAID") "PAID" else "UNPAID").coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Payment Status")
            .setSingleChoiceItems(labels, checked) { dlg, which ->
                paymentStatus = keys[which]
                renderHeaderFields()
                renderLinesAndTotals()
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showEditLineDialog(index: Int) {
        if (index !in lines.indices) return
        val ln = lines[index]
        val dp = resources.displayMetrics.density
        val pad = (18 * dp).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (10 * dp).toInt(), pad, 0)
        }
        val etQty = EditText(this).apply {
            hint = "Quantity"
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(qtyFmt.format(ln.quantity).replace(",", ""))
        }
        val etCost = EditText(this).apply {
            hint = "Unit Cost ($)"
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(String.format(Locale.US, "%.4f", ln.unitPrice).trimEnd('0').trimEnd('.'))
        }
        val etUom = EditText(this).apply {
            hint = "UOM (e.g. pcs., cases)"
            setText(ln.uom)
            isSingleLine = true
        }
        box.addView(TextView(this).apply { text = "Quantity"; textSize = 11.5f; setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_secondary)) })
        box.addView(etQty)
        box.addView(TextView(this).apply { text = "Unit Cost ($)"; textSize = 11.5f; setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_secondary)) })
        box.addView(etCost)
        box.addView(TextView(this).apply { text = "Unit (UOM)"; textSize = 11.5f; setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_secondary)) })
        box.addView(etUom)

        LiquidGlassDialog.builder(this)
            .setTitle(ln.productName.ifBlank { ln.sku })
            .setView(box)
            .setPositiveButton("Update") { _, _ ->
                val q = etQty.text.toString().trim().toDoubleOrNull()
                val c = etCost.text.toString().trim().toDoubleOrNull()
                if (q == null || q <= 0.0 || c == null || c < 0.0) {
                    Toast.makeText(this, "Enter valid quantity and cost", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                ln.quantity = q
                ln.unitPrice = c
                ln.uom = etUom.text.toString().trim().ifBlank { ln.uom }
                ln.subtotal = q * c
                renderLinesAndTotals()
            }
            .setNeutralButton("Remove") { _, _ ->
                lines.removeAt(index)
                renderLinesAndTotals()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showAddProductDialog() {
        val dp = resources.displayMetrics.density
        val pad = (16 * dp).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (10 * dp).toInt(), pad, pad)
        }
        val etSearch = EditText(this).apply {
            hint = "Search product name, SKU or barcode..."
            isSingleLine = true
        }
        val resultsScroll = NestedScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (340 * dp).toInt())
        }
        val resultsList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        resultsScroll.addView(resultsList)
        root.addView(etSearch)
        root.addView(resultsScroll)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Add Item to PO")
            .setView(root)
            .setNegativeButton("Close", null)
            .create()

        var searchJob: Job? = null
        fun runSearch(q: String) {
            searchJob?.cancel()
            searchJob = uiScope.launch {
                if (q.isNotEmpty()) delay(220)
                try {
                    val prods = api.searchProducts(q, 100, locationId)
                    resultsList.removeAllViews()
                    if (prods.isEmpty()) {
                        resultsList.addView(TextView(this@PurchaseOrderDetailActivity).apply {
                            text = "No products found"
                            setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_secondary))
                            setPadding(8, 20, 8, 20)
                        })
                    } else {
                        for (p in prods) {
                            resultsList.addView(buildProductPickCard(p, dlg))
                        }
                    }
                } catch (_: Exception) {}
            }
        }

        etSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                runSearch(s?.toString()?.trim().orEmpty())
            }
        })

        dlg.show()
        runSearch("")
    }

    private fun buildProductPickCard(p: ProductItem, dlg: androidx.appcompat.app.AlertDialog): View {
        val dp = resources.displayMetrics.density
        val card = MaterialCardView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = (8 * dp).toInt() }
            radius = 12 * dp
            cardElevation = 0f
            strokeWidth = (1 * dp).toInt()
            strokeColor = ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.surface_stroke)
            setCardBackgroundColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.surface_card))
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val p12 = (12 * dp).toInt()
            setPadding(p12, (10 * dp).toInt(), p12, (10 * dp).toInt())
        }
        inner.addView(TextView(this).apply {
            text = p.name.ifBlank { p.sku }
            setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_primary))
            textSize = 13.5f
            setTypeface(null, Typeface.BOLD)
        })
        inner.addView(TextView(this).apply {
            text = "${p.sku}  •  Avail: ${qtyFmt.format(p.stockAvailable)} ${p.uom}"
            setTextColor(ContextCompat.getColor(this@PurchaseOrderDetailActivity, R.color.text_secondary))
            textSize = 11.5f
        })
        card.addView(inner)
        card.setOnClickListener {
            val existing = lines.indexOfFirst { it.productId == p.id && p.id > 0 }
            if (existing >= 0) {
                dlg.dismiss()
                showEditLineDialog(existing)
            } else {
                lines.add(
                    PurchaseOrderLine(
                        id = 0,
                        productId = p.id,
                        sku = p.sku,
                        productName = p.name,
                        imageUrl = p.imageUrl,
                        quantity = 1.0,
                        uom = p.uom.ifBlank { "pcs." },
                        unitPrice = p.defaultPrice,
                        subtotal = p.defaultPrice
                    )
                )
                renderLinesAndTotals()
                dlg.dismiss()
                showEditLineDialog(lines.lastIndex)
            }
        }
        return card
    }

    private fun savePo(markReceiveAndPay: Boolean) {
        if (vendorId <= 0) {
            Toast.makeText(this, "Select a vendor first", Toast.LENGTH_SHORT).show()
            return
        }
        if (lines.isEmpty()) {
            Toast.makeText(this, "Add at least one item first", Toast.LENGTH_SHORT).show()
            return
        }
        val targetStatus = if (markReceiveAndPay) "RECEIVED" else status
        val targetPay = if (markReceiveAndPay) "PAID" else paymentStatus
        val total = lines.sumOf { it.quantity * it.unitPrice }
        val targetPaid = if (targetPay == "PAID") total else if (targetPay == "UNPAID") 0.0 else paidAmount

        binding.btnPoOpenWeb.isEnabled = false
        binding.btnPoPayReceive.isEnabled = false
        uiScope.launch {
            try {
                val (savedId, msg) = api.savePurchaseOrder(
                    poId = poId,
                    orderNumber = poNumber,
                    vendorId = vendorId,
                    locationId = locationId,
                    orderDateIso = orderDateIso.ifBlank { SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Calendar.getInstance().time) },
                    status = targetStatus,
                    paymentStatus = targetPay,
                    paidAmount = targetPaid,
                    notes = binding.etPoNotes.text?.toString()?.trim().orEmpty(),
                    lines = lines
                )
                poId = savedId
                Toast.makeText(this@PurchaseOrderDetailActivity, msg, Toast.LENGTH_SHORT).show()
                setResult(Activity.RESULT_OK)
                loadDetail()
            } catch (e: Exception) {
                Toast.makeText(this@PurchaseOrderDetailActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
            } finally {
                binding.btnPoOpenWeb.isEnabled = true
                binding.btnPoPayReceive.isEnabled = true
            }
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
