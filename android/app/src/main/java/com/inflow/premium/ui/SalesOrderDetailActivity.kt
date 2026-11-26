package com.inflow.premium.ui

import android.app.Activity
import android.app.DatePickerDialog
import android.app.Dialog
import android.content.Intent
import android.content.res.ColorStateList
import android.net.Uri
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.PopupMenu
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.ApiException
import com.inflow.premium.data.CustomerItem
import com.inflow.premium.data.OrderLineItem
import com.inflow.premium.data.ProductItem
import com.inflow.premium.data.SalesOrderDetail
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivitySalesOrderDetailBinding
import com.inflow.premium.databinding.DialogPickerBinding
import com.inflow.premium.databinding.DialogQuickCustomerBinding
import com.inflow.premium.databinding.ItemOrderLineBinding
import com.inflow.premium.databinding.ItemPickerRowBinding
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
import java.util.Date
import java.util.Locale

class SalesOrderDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySalesOrderDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var orderId: Int = 0
    private var orderNumber: String = "New Order"
    private var orderDate: String = ""
    private var status: String = "OPEN"
    private var paymentStatus: String = "UNPAID"
    private var isPaid: Boolean = false

    private var customerId: Int? = null
    private var customerName: String = ""
    private var branchId: Int? = null
    private var locationId: Int = 100
    private var pricingSchemeId: Int = 100
    private var deliveryMan: String = ""
    private var paymentMethod: String = "ABA Bank"
    private var khrRate: Double = 4100.0
    private var printUrl: String = ""
    private var labelPrintUrl: String = ""
    private var telegramUrl: String = ""
    private var shareCaption: String = ""
    private val lines = mutableListOf<OrderLineItem>()
    private var isSaving = false
    // Export JPG is handled by launching InvoicePrintActivity with auto-export flag

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivitySalesOrderDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        orderId = intent.getIntExtra(EXTRA_ORDER_ID, 0)
        khrRate = session.defaultKhrRate

        setupToolbar()
        setupListeners()
        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.SO)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollDetail,
            extraTopDp = 2,
            extraBottomScrollDp = 220
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollDetail.paddingTop != topH) {
                binding.scrollDetail.setPadding(
                    binding.scrollDetail.paddingLeft,
                    topH,
                    binding.scrollDetail.paddingRight,
                    binding.scrollDetail.paddingBottom
                )
            }
        }

        if (orderId > 0) {
            loadOrderDetail()
        } else {
            initNewOrderDefaults()
        }
    }

    private fun setupToolbar() {
        binding.btnDetailBack.setOnClickListener { finish() }
        binding.btnDetailRefresh.setOnClickListener {
            if (orderId > 0) {
                loadOrderDetail()
            } else {
                Toast.makeText(this, "New draft order", Toast.LENGTH_SHORT).show()
            }
        }
        binding.btnDetailMore.setOnClickListener { anchor ->
            val popup = PopupMenu(this, anchor)
            val editable = isEditable()
            val canPrintLabel = orderId > 0 && (labelPrintUrl.isNotBlank() || printUrl.isNotBlank())
            if (orderId > 0 && printUrl.isNotBlank()) {
                popup.menu.add(0, 1, 1, "Print Invoice")
            }
            if (canPrintLabel) {
                popup.menu.add(0, 2, 2, "Print Delivery Label")
            }
            if (orderId > 0) {
                popup.menu.add(0, 3, 3, "Share / Telegram")
            }
            if (orderId > 0 && editable) {
                popup.menu.add(0, 4, 4, "Cancel Order")
            }
            if (popup.menu.size() == 0) {
                Toast.makeText(this, "Save the order first for print & share", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            popup.setOnMenuItemClickListener { item ->
                when (item.itemId) {
                    1 -> openPrintPreview()
                    2 -> openLabelPrintPreview()
                    3 -> shareOrder()
                    4 -> confirmCancelOrder()
                }
                true
            }
            popup.show()
        }
    }

    private fun setupListeners() {
        binding.btnOrderDate.setOnClickListener { if (isEditable()) showDatePicker() }
        binding.btnBranchSelect.setOnClickListener {
            if (isEditable() && session.isMainAdmin()) showBranchPicker()
        }
        binding.btnSchemeSelect.setOnClickListener { if (isEditable()) showSchemePicker() }
        binding.btnSelectCustomer.setOnClickListener { if (isEditable()) openCustomerPicker() }
        binding.tvSelectedCustomer.setOnClickListener { if (isEditable()) openCustomerPicker() }
        binding.btnToggleCustEdit.setOnClickListener {
            val isShown = binding.llCustomerEditFields.visibility == View.VISIBLE
            binding.llCustomerEditFields.visibility = if (isShown) View.GONE else View.VISIBLE
            binding.btnToggleCustEdit.text = if (isShown) "Edit" else "Done"
        }
        binding.btnCallCustomer.setOnClickListener {
            val phone = binding.etPhone.text?.toString()?.trim().orEmpty()
            if (phone.isNotBlank()) {
                startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:$phone")))
            }
        }
        binding.btnAddProduct.setOnClickListener { if (isEditable()) openProductPicker() }
        binding.btnDeliveryMan.setOnClickListener { if (isEditable()) showDeliveryManPicker() }
        binding.btnPrintDeliveryLabel.setOnClickListener { openLabelPrintPreview() }

        binding.btnDockNew.setOnClickListener { resetToNewOrder() }
        binding.btnDockCopy.setOnClickListener { copyCurrentOrder() }
        binding.btnDockPreview.setOnClickListener { openPrintPreview() }
        binding.btnDockExportJpg.setOnClickListener { openExportJpg() }
        binding.btnDockDelete.setOnClickListener { confirmCancelOrder() }

        binding.etDeliveryFee.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) { recalculateTotals() }
        })
    }

    private fun resetToNewOrder() {
        orderId = 0
        orderNumber = "New Sales Order"
        customerId = null
        customerName = ""
        deliveryMan = ""
        printUrl = ""
        labelPrintUrl = ""
        telegramUrl = ""
        shareCaption = ""
        lines.clear()
        binding.tvSelectedCustomer.text = "Tap 'Change' to choose customer"
        binding.tvCustomerAddressSummary.text = ""
        binding.tvCustomerAddressSummary.visibility = View.GONE
        binding.etContact.setText("")
        binding.etPhone.setText("")
        binding.etAddress.setText("")
        binding.etDeliveryFee.setText("0")
        binding.etNotes.setText("")
        initNewOrderDefaults()
        Toast.makeText(this, "Started new draft Sales Order", Toast.LENGTH_SHORT).show()
    }

    private fun copyCurrentOrder() {
        orderId = 0
        orderNumber = "Copy • Draft"
        status = "OPEN"
        paymentStatus = "UNPAID"
        isPaid = false
        orderDate = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        printUrl = ""
        labelPrintUrl = ""
        telegramUrl = ""
        shareCaption = ""
        val copied = lines.map { it.copy(id = 0) }
        lines.clear()
        lines.addAll(copied)
        renderHeaderAndActions()
        renderLines()
        recalculateTotals()
        Toast.makeText(this, "Copied to new draft — tap Save to create", Toast.LENGTH_SHORT).show()
    }

    private fun initNewOrderDefaults() {
        orderDate = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        status = "OPEN"
        paymentStatus = "UNPAID"
        isPaid = false
        branchId = if (!session.isMainAdmin()) {
            session.getUserBranchId()
        } else {
            session.selectedBranch.toIntOrNull()?.takeIf { it > 0 }
        }
        locationId = session.getLocations().firstOrNull()?.id ?: 100
        pricingSchemeId = session.getPricingSchemes().firstOrNull()?.id ?: 100
        khrRate = session.defaultKhrRate

        renderHeaderAndActions()
        renderLines()
        recalculateTotals()
    }

    private fun loadOrderDetail() {
        setBusy(true)
        uiScope.launch {
            try {
                val d = api.getSalesOrderDetail(orderId)
                applyDetail(d)
            } catch (e: ApiException) {
                if (e.statusCode == 401) {
                    session.logout()
                    finish()
                    return@launch
                }
                Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Failed to load order", Toast.LENGTH_SHORT).show()
            } catch (e: Exception) {
                Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Network error", Toast.LENGTH_SHORT).show()
            } finally {
                setBusy(false)
            }
        }
    }

    private fun applyDetail(d: SalesOrderDetail) {
        orderId = d.id
        orderNumber = d.orderNumber
        orderDate = d.orderDate
        status = d.status
        paymentStatus = d.paymentStatus
        isPaid = d.isPaid
        customerId = d.customerId
        customerName = d.customerName
        branchId = d.branchId
        locationId = d.locationId
        pricingSchemeId = d.pricingSchemeId
        deliveryMan = d.deliveryMan
        paymentMethod = d.paymentMethod
        khrRate = if (d.khrRate > 0) d.khrRate else session.defaultKhrRate
        printUrl = d.printUrl
        labelPrintUrl = d.labelPrintUrl
        telegramUrl = d.telegramUrl
        shareCaption = d.shareCaption

        lines.clear()
        lines.addAll(d.lines)

        binding.tvSelectedCustomer.text = customerName.ifBlank { "Tap 'Select Customer' to choose" }
        binding.etContact.setText(d.customerContact)
        binding.etPhone.setText(d.customerPhone)
        binding.etAddress.setText(d.customerAddress)
        binding.etDeliveryFee.setText(formatNumber(d.deliveryFeeKhr, 0))
        binding.etNotes.setText(d.notes)

        renderHeaderAndActions()
        renderLines()
        recalculateTotals()
    }

    private fun isEditable(): Boolean {
        val up = status.uppercase(Locale.US)
        return !isPaid && up != "CANCELLED" && up != "CANCELED"
    }

    private fun renderHeaderAndActions() {
        binding.tvDetailTitle.text = if (orderId > 0) orderNumber else "New Sales Order"
        binding.btnOrderDate.text = orderDate

        val branchLabel = if (branchId == null || branchId == 0) {
            "Main Store (HQ)"
        } else {
            session.getBranches().firstOrNull { it.id == branchId.toString() }?.name ?: "Branch #$branchId"
        }
        binding.btnBranchSelect.text = branchLabel

        val schemeLabel = session.getPricingSchemes().firstOrNull { it.id == pricingSchemeId }?.name ?: "Retail"
        binding.btnSchemeSelect.text = schemeLabel

        binding.btnDeliveryMan.text = if (deliveryMan.isBlank()) "Delivery: Unassigned" else "Delivery: $deliveryMan"

        val phone = binding.etPhone.text?.toString()?.trim().orEmpty()
        binding.btnCallCustomer.text = phone
        binding.btnCallCustomer.visibility = if (phone.isNotBlank()) View.VISIBLE else View.GONE

        val addr = binding.etAddress.text?.toString()?.trim().orEmpty()
        binding.tvCustomerAddressSummary.text = addr
        binding.tvCustomerAddressSummary.visibility = if (addr.isNotBlank()) View.VISIBLE else View.GONE

        val isCancelled = status.equals("CANCELLED", ignoreCase = true) || status.equals("CANCELED", ignoreCase = true)
        val (badgeLabel, fgRes, bgRes) = when {
            isCancelled -> Triple("CANCELLED", R.color.cancel_red, R.color.cancel_red_bg)
            isPaid -> Triple("PAID • $paymentMethod", R.color.paid_green, R.color.paid_green_bg)
            else -> Triple("OPEN", R.color.open_orange, R.color.open_orange_bg)
        }
        binding.tvDetailStatusBadge.text = badgeLabel
        binding.tvDetailStatusBadge.setTextColor(ContextCompat.getColor(this, fgRes))
        binding.tvDetailStatusBadge.backgroundTintList =
            ColorStateList.valueOf(ContextCompat.getColor(this, bgRes))

        val editable = isEditable()
        binding.btnOrderDate.isEnabled = editable
        binding.btnBranchSelect.isEnabled = editable && session.isMainAdmin()
        binding.btnSchemeSelect.isEnabled = editable
        binding.btnSelectCustomer.visibility = if (editable) View.VISIBLE else View.GONE
        binding.btnToggleCustEdit.visibility = if (editable) View.VISIBLE else View.GONE
        binding.etContact.isEnabled = editable
        binding.etPhone.isEnabled = editable
        binding.etAddress.isEnabled = editable
        binding.btnAddProduct.visibility = if (editable) View.VISIBLE else View.GONE
        binding.btnDeliveryMan.isEnabled = editable
        binding.etDeliveryFee.isEnabled = editable
        binding.etNotes.isEnabled = editable

        val canPrintLabel = orderId > 0 && (labelPrintUrl.isNotBlank() || printUrl.isNotBlank())
        binding.btnPrintDeliveryLabel.visibility = if (canPrintLabel) View.VISIBLE else View.GONE
        binding.btnDockDelete.visibility = if (orderId > 0 && editable) View.VISIBLE else View.GONE

        when {
            isPaid -> {
                binding.btnActionLeft.text = "Print Invoice"
                binding.btnActionLeft.setOnClickListener { openPrintPreview() }

                binding.btnActionRight.text = "Reopen Order"
                binding.btnActionRight.backgroundTintList =
                    ColorStateList.valueOf(ContextCompat.getColor(this, R.color.open_orange))
                binding.btnActionRight.setOnClickListener { confirmReopenOrder() }
            }
            isCancelled -> {
                binding.btnActionLeft.text = "Share"
                binding.btnActionLeft.setOnClickListener { shareOrder() }

                binding.btnActionRight.text = "Reopen Order"
                binding.btnActionRight.backgroundTintList =
                    ColorStateList.valueOf(ContextCompat.getColor(this, R.color.primary))
                binding.btnActionRight.setOnClickListener { confirmReopenOrder() }
            }
            else -> {
                binding.btnActionLeft.text = "Save"
                binding.btnActionLeft.setOnClickListener { saveOrder(markCompletePay = false) }

                binding.btnActionRight.text = "Complete & Pay ›"
                binding.btnActionRight.backgroundTintList =
                    ColorStateList.valueOf(android.graphics.Color.parseColor("#0A6C62"))
                binding.btnActionRight.setOnClickListener { showPaymentMethodDialog() }
            }
        }
    }

    private fun renderLines() {
        binding.llLinesContainer.removeAllViews()
        binding.tvItemsTitle.text = "ORDER ITEMS (${lines.size})"
        binding.tvNoItems.visibility = if (lines.isEmpty()) View.VISIBLE else View.GONE

        val editable = isEditable()
        val inflater = LayoutInflater.from(this)

        for (idx in lines.indices) {
            val line = lines[idx]
            val lb = ItemOrderLineBinding.inflate(inflater, binding.llLinesContainer, false)

            lb.tvLineSku.text = line.sku.ifBlank { "#${line.productId}" }
            lb.tvLineName.text = line.productName
            lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
            lb.etLineQty.setText(formatNumber(line.quantity, 2))
            lb.etLinePrice.setText(formatNumber(line.unitPrice, 4))
            lb.btnLineUom.text = line.uom.ifBlank { line.baseUom }

            lb.btnDeleteLine.visibility = if (editable) View.VISIBLE else View.GONE
            lb.btnQtyMinus.isEnabled = editable
            lb.btnQtyPlus.isEnabled = editable
            lb.etLineQty.isEnabled = editable
            lb.etLinePrice.isEnabled = editable
            lb.btnLineUom.isEnabled = editable && line.salesUom.isNotBlank() &&
                !line.salesUom.equals(line.baseUom, ignoreCase = true)

            lb.btnDeleteLine.setOnClickListener {
                lines.removeAt(idx)
                renderLines()
                recalculateTotals()
            }

            lb.btnQtyMinus.setOnClickListener {
                val next = (line.quantity - 1.0).coerceAtLeast(1.0)
                line.quantity = next
                lb.etLineQty.setText(formatNumber(next, 2))
                lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
                recalculateTotals()
            }

            lb.btnQtyPlus.setOnClickListener {
                val next = line.quantity + 1.0
                line.quantity = next
                lb.etLineQty.setText(formatNumber(next, 2))
                lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
                recalculateTotals()
            }

            lb.btnLineUom.setOnClickListener {
                if (line.salesUom.isBlank() || line.salesUom.equals(line.baseUom, ignoreCase = true)) {
                    return@setOnClickListener
                }
                val ratio = if (line.salesUomRatioStd > 0) line.salesUomRatioStd else 1.0
                if (line.uom.equals(line.baseUom, ignoreCase = true)) {
                    line.uom = line.salesUom
                    line.unitPrice = line.unitPrice * ratio
                } else {
                    line.uom = line.baseUom
                    line.unitPrice = line.unitPrice / ratio
                }
                lb.btnLineUom.text = line.uom
                lb.etLinePrice.setText(formatNumber(line.unitPrice, 4))
                lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
                recalculateTotals()
            }

            lb.etLineQty.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    val v = s?.toString()?.toDoubleOrNull() ?: 0.0
                    if (v != line.quantity) {
                        line.quantity = v
                        lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
                        recalculateTotals()
                    }
                }
            })

            lb.etLinePrice.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                override fun afterTextChanged(s: Editable?) {
                    val v = s?.toString()?.toDoubleOrNull() ?: 0.0
                    if (v != line.unitPrice) {
                        line.unitPrice = v
                        lb.tvLineSubtotal.text = String.format(Locale.US, "$%.2f", line.subtotal)
                        recalculateTotals()
                    }
                }
            })

            binding.llLinesContainer.addView(lb.root)
        }
    }

    private fun recalculateTotals() {
        val subtotalUsd = lines.sumOf { it.subtotal }
        val feeKhr = binding.etDeliveryFee.text?.toString()?.toDoubleOrNull() ?: 0.0
        val rate = if (khrRate > 0) khrRate else 4100.0
        val totalKhr = Math.round(subtotalUsd * rate) + Math.round(feeKhr)

        binding.tvSummaryTotalUsd.text = String.format(Locale.US, "$%.2f", subtotalUsd)
        val df = DecimalFormat("#,##0")
        binding.tvSummaryTotalKhr.text = "≈ ${df.format(totalKhr)} KHR"
    }

    private fun showDatePicker() {
        val cal = Calendar.getInstance()
        try {
            val parts = orderDate.split("-")
            if (parts.size == 3) {
                cal.set(parts[0].toInt(), parts[1].toInt() - 1, parts[2].toInt())
            }
        } catch (_: Exception) {
        }

        val dlg = DatePickerDialog(
            this,
            { _, year, month, dayOfMonth ->
                orderDate = String.format(Locale.US, "%04d-%02d-%02d", year, month + 1, dayOfMonth)
                binding.btnOrderDate.text = orderDate
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        )
        dlg.setCancelable(false)
        dlg.setCanceledOnTouchOutside(false)
        dlg.setOnKeyListener { d, keyCode, event ->
            if (event.action == KeyEvent.ACTION_UP &&
                (keyCode == KeyEvent.KEYCODE_ESCAPE || keyCode == KeyEvent.KEYCODE_BACK)
            ) {
                d.dismiss()
                true
            } else {
                false
            }
        }
        dlg.show()
    }

    private fun showBranchPicker() {
        val opts = mutableListOf<Pair<Int?, String>>()
        opts.add(null to "Main Store (HQ)")
        for (b in session.getBranches()) {
            val bid = b.id.toIntOrNull()
            if (bid != null && bid > 0) {
                opts.add(bid to b.name)
            }
        }
        val labels = opts.map { it.second }.toTypedArray()
        val checked = opts.indexOfFirst { it.first == branchId }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Store / Branch")
            .setSingleChoiceItems(labels, checked) { d, which ->
                branchId = opts[which].first
                binding.btnBranchSelect.text = opts[which].second
                d.dismiss()
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
        val checked = schemes.indexOfFirst { it.id == pricingSchemeId }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Price Group")
            .setSingleChoiceItems(labels, checked) { d, which ->
                pricingSchemeId = schemes[which].id
                binding.btnSchemeSelect.text = schemes[which].name
                d.dismiss()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun showDeliveryManPicker() {
        val list = session.getDeliveryMen()
        val names = mutableListOf("Unassigned")
        names.addAll(list.map { it.name })
        val checked = names.indexOfFirst {
            if (deliveryMan.isBlank()) it == "Unassigned" else it.equals(deliveryMan, ignoreCase = true)
        }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Delivery Courier / Rider")
            .setSingleChoiceItems(names.toTypedArray(), checked) { d, which ->
                deliveryMan = if (which == 0) "" else names[which]
                binding.btnDeliveryMan.text =
                    if (deliveryMan.isBlank()) "Delivery: Unassigned" else "Delivery: $deliveryMan"
                d.dismiss()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun openCustomerPicker() {
        val dlg = Dialog(this)
        val pb = DialogPickerBinding.inflate(layoutInflater)
        dlg.setContentView(pb.root)
        dlg.setCancelable(false)
        dlg.setCanceledOnTouchOutside(false)
        dlg.setOnKeyListener { d, keyCode, event ->
            if (event.action == KeyEvent.ACTION_UP &&
                (keyCode == KeyEvent.KEYCODE_ESCAPE || keyCode == KeyEvent.KEYCODE_BACK)
            ) {
                d.dismiss()
                true
            } else {
                false
            }
        }
        dlg.window?.setLayout(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
        dlg.window?.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)

        pb.tvPickerTitle.text = "Select Customer"
        pb.btnPickerQuickAdd.visibility = View.VISIBLE
        pb.etPickerSearch.hint = "Search customer name or phone..."

        val rows = mutableListOf<CustomerItem>()
        val pickerAdapter = PickerAdapter { pos ->
            val c = rows[pos]
            applySelectedCustomer(c)
            dlg.dismiss()
        }
        pb.rvPicker.layoutManager = LinearLayoutManager(this)
        pb.rvPicker.adapter = pickerAdapter

        pb.btnPickerClose.setOnClickListener { dlg.dismiss() }
        pb.btnPickerQuickAdd.setOnClickListener {
            openQuickAddCustomerDialog { created ->
                applySelectedCustomer(created)
                dlg.dismiss()
            }
        }

        var job: Job? = null
        fun runSearch(q: String) {
            job?.cancel()
            job = uiScope.launch {
                pb.progressPicker.visibility = View.VISIBLE
                try {
                    val branchParam = branchId?.toString() ?: session.selectedBranch
                    val res = api.searchCustomers(q, branchParam)
                    rows.clear()
                    rows.addAll(res)
                    pickerAdapter.setItems(res.map {
                        Triple(
                            it.name,
                            if (it.contactName.isNotBlank()) "${it.contactName} • ${it.phone}" else it.phone,
                            it.address
                        )
                    })
                } catch (e: Exception) {
                    Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Search failed", Toast.LENGTH_SHORT).show()
                } finally {
                    pb.progressPicker.visibility = View.GONE
                }
            }
        }

        pb.etPickerSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                job?.cancel()
                job = uiScope.launch {
                    delay(280)
                    runSearch(q)
                }
            }
        })

        runSearch("")
        dlg.show()
    }

    private fun applySelectedCustomer(c: CustomerItem) {
        customerId = c.id
        customerName = c.name
        binding.tvSelectedCustomer.text = c.name
        binding.etContact.setText(c.contactName)
        binding.etPhone.setText(c.phone)
        binding.etAddress.setText(c.address)
        if (c.defaultPricingSchemeId > 0) {
            pricingSchemeId = c.defaultPricingSchemeId
        }
        renderHeaderAndActions()
    }

    private fun openQuickAddCustomerDialog(onCreated: (CustomerItem) -> Unit) {
        val qb = DialogQuickCustomerBinding.inflate(layoutInflater)
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Quick Add Customer")
            .setView(qb.root)
            .setPositiveButton("Create Customer", null)
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()

        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.setOnShowListener {
            val btnOk = dlg.getButton(AlertDialog.BUTTON_POSITIVE)
            btnOk.setOnClickListener {
                val name = qb.etQcName.text?.toString()?.trim().orEmpty()
                if (name.isBlank()) {
                    Toast.makeText(this, "Customer name is required", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                btnOk.isEnabled = false
                uiScope.launch {
                    try {
                        val created = api.quickAddCustomer(
                            name = name,
                            contactName = qb.etQcContact.text?.toString()?.trim().orEmpty(),
                            phone = qb.etQcPhone.text?.toString()?.trim().orEmpty(),
                            address = qb.etQcAddress.text?.toString()?.trim().orEmpty(),
                            branchId = branchId
                        )
                        dlg.dismiss()
                        onCreated(created)
                    } catch (e: Exception) {
                        btnOk.isEnabled = true
                        Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Failed to create customer", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
        dlg.show()
    }

    private fun openProductPicker() {
        val dlg = Dialog(this)
        val pb = DialogPickerBinding.inflate(layoutInflater)
        dlg.setContentView(pb.root)
        dlg.setCancelable(false)
        dlg.setCanceledOnTouchOutside(false)
        dlg.setOnKeyListener { d, keyCode, event ->
            if (event.action == KeyEvent.ACTION_UP &&
                (keyCode == KeyEvent.KEYCODE_ESCAPE || keyCode == KeyEvent.KEYCODE_BACK)
            ) {
                d.dismiss()
                true
            } else {
                false
            }
        }
        dlg.window?.setLayout(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.WRAP_CONTENT
        )
        dlg.window?.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)

        pb.tvPickerTitle.text = "Add Product (Read-Only Catalog)"
        pb.btnPickerQuickAdd.visibility = View.GONE
        pb.etPickerSearch.hint = "Search SKU or product name..."

        val products = mutableListOf<ProductItem>()
        val pickerAdapter = PickerAdapter { pos ->
            addOrIncrementProduct(products[pos])
            dlg.dismiss()
        }
        pb.rvPicker.layoutManager = LinearLayoutManager(this)
        pb.rvPicker.adapter = pickerAdapter

        pb.btnPickerClose.setOnClickListener { dlg.dismiss() }

        var job: Job? = null
        fun runSearch(q: String) {
            job?.cancel()
            job = uiScope.launch {
                pb.progressPicker.visibility = View.VISIBLE
                try {
                    val res = api.searchProducts(q, pricingSchemeId, locationId)
                    products.clear()
                    products.addAll(res)
                    pickerAdapter.setItems(res.map {
                        Triple(
                            "${it.sku} • ${it.name}",
                            "UOM: ${it.uom} • Stock: ${formatNumber(it.stockAvailable, 2)}",
                            String.format(Locale.US, "$%.4f", it.unitPrice)
                        )
                    })
                } catch (e: Exception) {
                    Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Product lookup failed", Toast.LENGTH_SHORT).show()
                } finally {
                    pb.progressPicker.visibility = View.GONE
                }
            }
        }

        pb.etPickerSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                job?.cancel()
                job = uiScope.launch {
                    delay(280)
                    runSearch(q)
                }
            }
        })

        runSearch("")
        dlg.show()
    }

    private fun addOrIncrementProduct(p: ProductItem) {
        val base = p.uom.ifBlank { "pcs." }
        val existing = lines.firstOrNull { it.productId == p.id && it.uom.equals(base, ignoreCase = true) }
        if (existing != null) {
            existing.quantity += 1.0
        } else {
            val price = p.schemePrices[pricingSchemeId.toString()] ?: p.unitPrice
            lines.add(
                OrderLineItem(
                    productId = p.id,
                    sku = p.sku,
                    productName = p.name,
                    quantity = 1.0,
                    uom = base,
                    baseUom = base,
                    salesUom = p.salesUom,
                    salesUomRatioStd = p.salesUomRatioStd,
                    unitPrice = price,
                    pricingSchemeId = pricingSchemeId
                )
            )
        }
        renderLines()
        recalculateTotals()
    }

    private fun showPaymentMethodDialog() {
        if (customerId == null || customerId == 0) {
            Toast.makeText(this, "Please select a customer first", Toast.LENGTH_SHORT).show()
            return
        }
        if (lines.isEmpty()) {
            Toast.makeText(this, "Please add at least one product", Toast.LENGTH_SHORT).show()
            return
        }
        val methods = arrayOf("ABA Bank", "Cash", "ACLEDA", "KB PRASAC")
        var selectedIdx = methods.indexOfFirst { it.equals(paymentMethod, ignoreCase = true) }.coerceAtLeast(0)

        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Complete & Pay")
            .setSingleChoiceItems(methods, selectedIdx) { _, which ->
                selectedIdx = which
            }
            .setPositiveButton("Confirm Payment") { _, _ ->
                paymentMethod = methods[selectedIdx]
                saveOrder(markCompletePay = true)
            }
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun saveOrder(markCompletePay: Boolean) {
        if (isSaving) return
        val cid = customerId
        if (cid == null || cid == 0) {
            Toast.makeText(this, "Please select a customer", Toast.LENGTH_SHORT).show()
            return
        }
        if (lines.isEmpty()) {
            Toast.makeText(this, "Please add at least one product", Toast.LENGTH_SHORT).show()
            return
        }

        isSaving = true
        setBusy(true)
        val feeKhr = binding.etDeliveryFee.text?.toString()?.toDoubleOrNull() ?: 0.0
        val contact = binding.etContact.text?.toString()?.trim().orEmpty()
        val phone = binding.etPhone.text?.toString()?.trim().orEmpty()
        val address = binding.etAddress.text?.toString()?.trim().orEmpty()
        val notes = binding.etNotes.text?.toString()?.trim().orEmpty()

        uiScope.launch {
            try {
                val res = api.saveSalesOrder(
                    orderId = orderId,
                    customerId = cid,
                    branchId = branchId,
                    locationId = locationId,
                    orderDate = orderDate,
                    pricingSchemeId = pricingSchemeId,
                    contact = contact,
                    phone = phone,
                    address = address,
                    deliveryMan = deliveryMan,
                    deliveryFeeKhr = feeKhr,
                    paymentMethod = paymentMethod,
                    notes = notes,
                    lines = lines,
                    markCompletePay = markCompletePay
                )
                val returnedId = res.optInt("order_id", res.optInt("id", orderId))
                if (returnedId > 0) {
                    orderId = returnedId
                }
                setResult(Activity.RESULT_OK)
                Toast.makeText(
                    this@SalesOrderDetailActivity,
                    if (markCompletePay) "Order completed & paid!" else "Sales order saved!",
                    Toast.LENGTH_SHORT
                ).show()

                if (orderId > 0) {
                    val fresh = api.getSalesOrderDetail(orderId)
                    applyDetail(fresh)
                }
            } catch (e: ApiException) {
                Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Save failed", Toast.LENGTH_LONG).show()
            } catch (e: Exception) {
                Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Network error", Toast.LENGTH_LONG).show()
            } finally {
                isSaving = false
                setBusy(false)
            }
        }
    }

    private fun confirmReopenOrder() {
        if (orderId <= 0) return
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Reopen Order")
            .setMessage("Reopen $orderNumber back to OPEN status for editing?")
            .setPositiveButton("Reopen") { _, _ ->
                setBusy(true)
                uiScope.launch {
                    try {
                        api.reopenOrder(orderId)
                        setResult(Activity.RESULT_OK)
                        val fresh = api.getSalesOrderDetail(orderId)
                        applyDetail(fresh)
                        Toast.makeText(this@SalesOrderDetailActivity, "Order reopened", Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Failed to reopen", Toast.LENGTH_LONG).show()
                    } finally {
                        setBusy(false)
                    }
                }
            }
            .setNegativeButton("Cancel") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun confirmCancelOrder() {
        if (orderId <= 0) return
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle("Cancel Order")
            .setMessage("Are you sure you want to cancel $orderNumber?")
            .setPositiveButton("Cancel Order") { _, _ ->
                setBusy(true)
                uiScope.launch {
                    try {
                        api.cancelOrder(orderId)
                        setResult(Activity.RESULT_OK)
                        val fresh = api.getSalesOrderDetail(orderId)
                        applyDetail(fresh)
                        Toast.makeText(this@SalesOrderDetailActivity, "Order cancelled", Toast.LENGTH_SHORT).show()
                    } catch (e: Exception) {
                        Toast.makeText(this@SalesOrderDetailActivity, e.message ?: "Failed to cancel", Toast.LENGTH_LONG).show()
                    } finally {
                        setBusy(false)
                    }
                }
            }
            .setNegativeButton("Keep Order") { d, _ -> d.dismiss() }
            .setCancelable(false)
            .create()
        attachEscClose(dlg)
        dlg.setCanceledOnTouchOutside(false)
        dlg.show()
    }

    private fun openPrintPreview() {
        if (orderId <= 0 || printUrl.isBlank()) {
            Toast.makeText(this, "Save the order first to preview", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(
            Intent(this, InvoicePrintActivity::class.java)
                .putExtra(InvoicePrintActivity.EXTRA_ORDER_NUMBER, orderNumber)
                .putExtra(InvoicePrintActivity.EXTRA_PRINT_URL, printUrl)
                .putExtra(InvoicePrintActivity.EXTRA_TELEGRAM_URL, telegramUrl)
                .putExtra(InvoicePrintActivity.EXTRA_SHARE_CAPTION, shareCaption)
        )
    }

    private fun openExportJpg() {
        if (orderId <= 0 || printUrl.isBlank()) {
            Toast.makeText(this, "Save the order first to export JPG", Toast.LENGTH_SHORT).show()
            return
        }
        // Launch InvoicePrintActivity with auto-export flag.
        // The visible WebView renders the invoice fully, html2canvas works correctly,
        // and the AndroidGalleryBridge JS interface saves the JPG directly to Gallery.
        val intent = Intent(this, InvoicePrintActivity::class.java).apply {
            putExtra(InvoicePrintActivity.EXTRA_ORDER_NUMBER, orderNumber)
            putExtra(InvoicePrintActivity.EXTRA_PRINT_URL, printUrl)
            putExtra(InvoicePrintActivity.EXTRA_TELEGRAM_URL, telegramUrl)
            putExtra(InvoicePrintActivity.EXTRA_SHARE_CAPTION, shareCaption)
            putExtra(InvoicePrintActivity.EXTRA_TITLE, "Exporting • $orderNumber")
            putExtra(InvoicePrintActivity.EXTRA_AUTO_EXPORT_JPG, true)
        }
        startActivity(intent)
    }

    private fun openLabelPrintPreview() {
        val resolvedLabelUrl = when {
            labelPrintUrl.isNotBlank() -> labelPrintUrl
            printUrl.isNotBlank() -> printUrl.replace("type=invoice", "type=label")
            else -> ""
        }
        if (orderId <= 0 || resolvedLabelUrl.isBlank()) {
            Toast.makeText(this, "Save the order first to print delivery label", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(
            Intent(this, InvoicePrintActivity::class.java)
                .putExtra(InvoicePrintActivity.EXTRA_ORDER_NUMBER, orderNumber)
                .putExtra(InvoicePrintActivity.EXTRA_PRINT_URL, resolvedLabelUrl)
                .putExtra(InvoicePrintActivity.EXTRA_TELEGRAM_URL, "")
                .putExtra(InvoicePrintActivity.EXTRA_SHARE_CAPTION, "Delivery Label $orderNumber")
                .putExtra(InvoicePrintActivity.EXTRA_TITLE, "Delivery Label • $orderNumber")
                .putExtra(InvoicePrintActivity.EXTRA_PRINT_BTN_TEXT, "Print Label")
        )
    }

    private fun shareOrder() {
        if (telegramUrl.isNotBlank()) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(telegramUrl)))
                return
            } catch (_: Exception) {
            }
        }
        val fullPrint = if (printUrl.startsWith("http")) printUrl else "${session.baseUrl}$printUrl"
        val text = buildString {
            append(if (shareCaption.isNotBlank()) shareCaption else "Sales Order $orderNumber")
            if (printUrl.isNotBlank()) {
                append("\n")
                append(fullPrint)
            }
        }
        val sendIntent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(sendIntent, "Share Sales Order"))
    }

    private fun setBusy(busy: Boolean) {
        binding.progressDetail.visibility = if (busy) View.VISIBLE else View.GONE
        binding.btnActionLeft.isEnabled = !busy
        binding.btnActionRight.isEnabled = !busy
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

    private fun formatNumber(value: Double, decimals: Int): String {
        if (decimals == 0) return Math.round(value).toString()
        val s = String.format(Locale.US, "%.${decimals}f", value)
        return if (s.contains('.')) s.trimEnd('0').trimEnd('.') else s
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    private class PickerAdapter(
        private val onPick: (Int) -> Unit
    ) : RecyclerView.Adapter<PickerAdapter.VH>() {

        private val data = mutableListOf<Triple<String, String, String>>()

        fun setItems(items: List<Triple<String, String, String>>) {
            data.clear()
            data.addAll(items)
            notifyDataSetChanged()
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val binding = ItemPickerRowBinding.inflate(
                LayoutInflater.from(parent.context),
                parent,
                false
            )
            return VH(binding)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            val (title, sub, right) = data[position]
            holder.binding.tvPickTitle.text = title
            holder.binding.tvPickSub.text = sub
            holder.binding.tvPickRight.text = right
            holder.binding.tvPickRight.visibility = if (right.isBlank()) View.GONE else View.VISIBLE
            holder.binding.root.setOnClickListener { onPick(position) }
        }

        override fun getItemCount(): Int = data.size

        class VH(val binding: ItemPickerRowBinding) : RecyclerView.ViewHolder(binding.root)
    }

    companion object {
        const val EXTRA_ORDER_ID = "extra_order_id"
    }
}
