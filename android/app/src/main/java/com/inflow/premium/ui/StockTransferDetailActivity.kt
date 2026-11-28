package com.inflow.premium.ui

import android.app.Activity
import android.app.DatePickerDialog
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.NestedScrollView
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.StockTransferDetail
import com.inflow.premium.data.StockTransferLine
import com.inflow.premium.data.TransferCatalogProduct
import com.inflow.premium.data.TransferLocationOption
import com.inflow.premium.databinding.ActivityStockTransferDetailBinding
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

class StockTransferDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityStockTransferDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var transferId: Int = 0
    private var transferNumber: String = ""
    private var transferDateIso: String = ""
    private var transferStatus: String = "DRAFT"
    private var fromLocId: Int = 0
    private var toLocId: Int = 0
    private var locations: List<TransferLocationOption> = emptyList()
    private val lines = mutableListOf<StockTransferLine>()
    private val numFmt = DecimalFormat("#,##0.##")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityStockTransferDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        transferId = intent.getIntExtra(EXTRA_TRANSFER_ID, 0)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollTransferDetail,
            extraTopDp = 4,
            extraBottomScrollDp = 100
        )
        binding.topHeader.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
            val topH = v.height
            if (topH > 0 && binding.scrollTransferDetail.paddingTop != topH) {
                binding.scrollTransferDetail.setPadding(
                    binding.scrollTransferDetail.paddingLeft,
                    topH,
                    binding.scrollTransferDetail.paddingRight,
                    binding.scrollTransferDetail.paddingBottom
                )
            }
        }

        binding.btnTrfDetBack.setOnClickListener { finish() }
        binding.btnTrfCancel.setOnClickListener { finish() }
        binding.btnTrfDetRefresh.setOnClickListener { loadDetail() }

        binding.btnTrfScheduledDate.setOnClickListener {
            if (!isCompleted()) showDatePicker()
        }
        binding.btnTrfFromWarehouse.setOnClickListener {
            if (!isCompleted()) pickWarehouse(isSource = true)
        }
        binding.btnTrfToWarehouse.setOnClickListener {
            if (!isCompleted()) pickWarehouse(isSource = false)
        }
        binding.btnSwapWarehouses.setOnClickListener {
            if (!isCompleted() && fromLocId > 0 && toLocId > 0) {
                val tmp = fromLocId
                fromLocId = toLocId
                toLocId = tmp
                updateWarehouseLabels()
            }
        }
        binding.btnTrfClearAll.setOnClickListener {
            if (!isCompleted()) {
                lines.clear()
                renderLines()
            }
        }
        binding.btnTrfQuickPick.setOnClickListener {
            if (!isCompleted()) openCatalogPicker()
        }
        binding.btnTrfAddFromCatalog.setOnClickListener {
            if (!isCompleted()) openCatalogPicker()
        }

        binding.btnTrfSaveDraft.setOnClickListener { submitTransfer("DRAFT") }
        binding.btnTrfComplete.setOnClickListener {
            LiquidGlassDialog.builder(this)
                .setTitle("Complete Stock Transfer")
                .setMessage("Move ${lines.size} item(s) immediately from ${locName(fromLocId)} to ${locName(toLocId)}?")
                .setPositiveButton("Complete Transfer") { _, _ -> submitTransfer("COMPLETED") }
                .setNegativeButton("Cancel", null)
                .show()
        }

        loadDetail()
    }

    private fun isCompleted(): Boolean = transferStatus.equals("COMPLETED", ignoreCase = true)

    private fun locName(id: Int): String = locations.firstOrNull { it.id == id }?.name ?: "Warehouse"

    private fun loadDetail() {
        binding.progressTrfDetail.visibility = View.VISIBLE
        uiScope.launch {
            try {
                val d = api.getTransferDetail(transferId)
                bindDetail(d)
            } catch (e: Exception) {
                Toast.makeText(this@StockTransferDetailActivity, e.message ?: "Failed to load transfer", Toast.LENGTH_SHORT).show()
            } finally {
                binding.progressTrfDetail.visibility = View.GONE
            }
        }
    }

    private fun bindDetail(d: StockTransferDetail) {
        transferId = d.id
        transferNumber = d.transferNumber
        transferDateIso = d.transferDateIso
        transferStatus = d.status
        fromLocId = d.fromLocationId
        toLocId = d.toLocationId
        locations = d.locations

        lines.clear()
        lines.addAll(d.lines)

        binding.tvTrfDetHeaderNum.text = d.transferNumber
        binding.btnTrfScheduledDate.text = "📅 ${d.transferDate}"
        binding.etTrfNotes.setText(d.notes)
        updateWarehouseLabels()

        if (isCompleted()) {
            binding.tvTrfDetStatusBadge.text = "✓ COMPLETED"
            binding.tvTrfDetStatusBadge.setTextColor(Color.parseColor("#047857"))
            binding.tvTrfDetStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            binding.llTrfAddItemControls.visibility = View.GONE
            binding.btnTrfClearAll.visibility = View.GONE
            binding.llTrfBottomActions.visibility = View.GONE
            binding.etTrfNotes.isEnabled = false
        } else {
            binding.tvTrfDetStatusBadge.text = "✏️ DRAFT"
            binding.tvTrfDetStatusBadge.setTextColor(Color.parseColor("#B45309"))
            binding.tvTrfDetStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            binding.llTrfAddItemControls.visibility = View.VISIBLE
            binding.btnTrfClearAll.visibility = View.VISIBLE
            binding.llTrfBottomActions.visibility = View.VISIBLE
            binding.etTrfNotes.isEnabled = true
        }

        renderLines()
    }

    private fun updateWarehouseLabels() {
        val fromLoc = locations.firstOrNull { it.id == fromLocId }
        val toLoc = locations.firstOrNull { it.id == toLocId }
        binding.tvTrfFromWarehouse.text = if (fromLoc?.isDefault == true) "${fromLoc.name} (Default)" else (fromLoc?.name ?: "Select Warehouse")
        binding.tvTrfToWarehouse.text = if (toLoc?.isDefault == true) "${toLoc.name} (Default)" else (toLoc?.name ?: "Select Warehouse")
    }

    private fun showDatePicker() {
        val cal = Calendar.getInstance()
        try {
            val parsed = SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(transferDateIso)
            if (parsed != null) cal.time = parsed
        } catch (_: Exception) {
        }
        DatePickerDialog(
            this,
            { _, y, m, day ->
                val c = Calendar.getInstance().apply { set(y, m, day) }
                transferDateIso = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(c.time)
                binding.btnTrfScheduledDate.text = "📅 ${SimpleDateFormat("dd - MMM - yyyy", Locale.US).format(c.time)}"
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun pickWarehouse(isSource: Boolean) {
        if (locations.isEmpty()) return
        val names = locations.map { if (it.isDefault) "${it.name} (Default)" else it.name }.toTypedArray()
        val curId = if (isSource) fromLocId else toLocId
        val checked = locations.indexOfFirst { it.id == curId }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle(if (isSource) "From Warehouse (Source)" else "To Warehouse (Destination)")
            .setSingleChoiceItems(names, checked) { dlg, which ->
                val picked = locations[which].id
                if (isSource) fromLocId = picked else toLocId = picked
                updateWarehouseLabels()
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun openCatalogPicker() {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(10), dp(16), dp(8))
        }
        val et = EditText(this).apply {
            hint = "Search SKU or product name..."
            setSingleLine(true)
            setBackgroundResource(R.drawable.bg_product_thumb)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            textSize = 13.5f
        }
        val scroll = NestedScrollView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(320)
            ).apply { topMargin = dp(8) }
        }
        val listCol = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll.addView(listCol)
        container.addView(et)
        container.addView(scroll)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Add Item From Catalog")
            .setView(container)
            .setNegativeButton("Close", null)
            .create()

        var searchJob: Job? = null
        fun runSearch(q: String) {
            searchJob?.cancel()
            searchJob = uiScope.launch {
                try {
                    val prods = api.searchTransferProducts(q, fromLocId)
                    listCol.removeAllViews()
                    if (prods.isEmpty()) {
                        listCol.addView(TextView(this@StockTransferDetailActivity).apply {
                            text = "No matching products"
                            gravity = Gravity.CENTER
                            setPadding(dp(12), dp(24), dp(12), dp(24))
                            setTextColor(Color.parseColor("#64748B"))
                        })
                        return@launch
                    }
                    for (p in prods) {
                        val row = LinearLayout(this@StockTransferDetailActivity).apply {
                            orientation = LinearLayout.VERTICAL
                            setBackgroundResource(R.drawable.bg_product_thumb)
                            setPadding(dp(12), dp(10), dp(12), dp(10))
                            layoutParams = LinearLayout.LayoutParams(
                                LinearLayout.LayoutParams.MATCH_PARENT,
                                LinearLayout.LayoutParams.WRAP_CONTENT
                            ).apply { bottomMargin = dp(6) }
                        }
                        val tvTitle = TextView(this@StockTransferDetailActivity).apply {
                            text = "${p.sku} • ${p.name}"
                            setTextColor(Color.parseColor("#0F172A"))
                            textSize = 12.5f
                            setTypeface(null, android.graphics.Typeface.BOLD)
                        }
                        val tvStock = TextView(this@StockTransferDetailActivity).apply {
                            text = "Source On Hand: ${numFmt.format(p.sourceOnHand)} ${p.uom}"
                            setTextColor(
                                Color.parseColor(if (p.sourceOnHand > 0) "#059669" else "#DC2626")
                            )
                            textSize = 11.5f
                        }
                        row.addView(tvTitle)
                        row.addView(tvStock)
                        row.setOnClickListener {
                            addOrIncrementProduct(p)
                            dlg.dismiss()
                        }
                        listCol.addView(row)
                    }
                } catch (e: Exception) {
                    Toast.makeText(this@StockTransferDetailActivity, e.message ?: "Search failed", Toast.LENGTH_SHORT).show()
                }
            }
        }

        et.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                searchJob?.cancel()
                val q = s?.toString()?.trim().orEmpty()
                searchJob = uiScope.launch {
                    delay(260)
                    runSearch(q)
                }
            }
        })

        dlg.show()
        runSearch("")
    }

    private fun addOrIncrementProduct(p: TransferCatalogProduct) {
        val existing = lines.firstOrNull { it.productId == p.id }
        if (existing != null) {
            existing.quantity += 1.0
        } else {
            lines.add(
                StockTransferLine(
                    productId = p.id,
                    sku = p.sku,
                    name = p.name,
                    uom = p.uom,
                    baseUom = p.uom,
                    salesUom = p.salesUom,
                    salesRatio = p.salesRatio,
                    uomFactor = 1.0,
                    sourceOnHand = p.sourceOnHand,
                    sourceAvailable = p.sourceAvailable,
                    quantity = 1.0
                )
            )
        }
        renderLines()
    }

    private fun renderLines() {
        binding.llTrfLines.removeAllViews()
        val totalUnits = lines.sumOf { it.quantity * it.uomFactor }
        binding.tvTrfItemsBadge.text = "${lines.size} ITEMS"
        binding.tvTrfUnitsBadge.text = "${numFmt.format(totalUnits)} UNITS"

        if (lines.isEmpty()) {
            binding.llTrfEmptyLines.visibility = View.VISIBLE
            binding.llTrfLines.visibility = View.GONE
            return
        }
        binding.llTrfEmptyLines.visibility = View.GONE
        binding.llTrfLines.visibility = View.VISIBLE

        val readOnly = isCompleted()
        lines.forEachIndexed { idx, ln ->
            val card = MaterialCardView(this).apply {
                setCardBackgroundColor(Color.WHITE)
                radius = dp(14).toFloat()
                cardElevation = dp(1).toFloat()
                strokeColor = Color.parseColor("#E2E8F0")
                strokeWidth = dp(1)
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(8) }
            }
            val col = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(12), dp(12), dp(12), dp(12))
            }

            val topRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            val tvTitle = TextView(this).apply {
                text = "${ln.sku} • ${ln.name}"
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            }
            topRow.addView(tvTitle)
            if (!readOnly) {
                val tvDel = TextView(this).apply {
                    text = "✕"
                    setTextColor(Color.parseColor("#DC2626"))
                    textSize = 14f
                    setPadding(dp(8), dp(2), dp(4), dp(2))
                    setOnClickListener {
                        lines.removeAt(idx)
                        renderLines()
                    }
                }
                topRow.addView(tvDel)
            }
            col.addView(topRow)

            val tvAvail = TextView(this).apply {
                text = "Source Stock: ${numFmt.format(ln.sourceOnHand)} ${ln.baseUom}"
                setTextColor(Color.parseColor(if (ln.sourceOnHand > 0) "#059669" else "#DC2626"))
                textSize = 11.5f
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(4) }
            }
            col.addView(tvAvail)

            val ctrlRow = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(10) }
            }

            if (readOnly) {
                ctrlRow.addView(TextView(this).apply {
                    text = "Transferred Qty: ${numFmt.format(ln.quantity)} ${ln.uom}"
                    setTextColor(Color.parseColor("#0A6C62"))
                    textSize = 13f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                })
            } else {
                val btnMinus = TextView(this).apply {
                    text = "−"
                    gravity = Gravity.CENTER
                    setBackgroundResource(R.drawable.bg_product_thumb)
                    setTextColor(Color.parseColor("#0F172A"))
                    textSize = 16f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    layoutParams = LinearLayout.LayoutParams(dp(36), dp(34))
                    setOnClickListener {
                        if (ln.quantity > 1) {
                            ln.quantity -= 1.0
                            renderLines()
                        }
                    }
                }
                val tvQty = TextView(this).apply {
                    text = numFmt.format(ln.quantity)
                    gravity = Gravity.CENTER
                    setTextColor(Color.parseColor("#0F172A"))
                    textSize = 14f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    setPadding(dp(14), dp(4), dp(14), dp(4))
                    setOnClickListener { promptQtyEdit(idx) }
                }
                val btnPlus = TextView(this).apply {
                    text = "+"
                    gravity = Gravity.CENTER
                    setBackgroundResource(R.drawable.bg_product_thumb)
                    setTextColor(Color.parseColor("#0A6C62"))
                    textSize = 16f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    layoutParams = LinearLayout.LayoutParams(dp(36), dp(34))
                    setOnClickListener {
                        ln.quantity += 1.0
                        renderLines()
                    }
                }
                val tvUom = TextView(this).apply {
                    text = ln.uom
                    setBackgroundResource(R.drawable.bg_pill_slate_controls)
                    backgroundTintList = ColorStateList.valueOf(Color.parseColor("#E0F2FE"))
                    setTextColor(Color.parseColor("#0284C7"))
                    textSize = 11.5f
                    setTypeface(null, android.graphics.Typeface.BOLD)
                    setPadding(dp(12), dp(6), dp(12), dp(6))
                    layoutParams = LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.WRAP_CONTENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                    ).apply { marginStart = dp(10) }
                    setOnClickListener {
                        if (ln.salesUom.isNotBlank() && ln.salesRatio > 1.0) {
                            if (ln.uom == ln.baseUom) {
                                lines[idx] = ln.copy(uom = ln.salesUom, uomFactor = ln.salesRatio)
                            } else {
                                lines[idx] = ln.copy(uom = ln.baseUom, uomFactor = 1.0)
                            }
                            renderLines()
                        }
                    }
                }
                ctrlRow.addView(btnMinus)
                ctrlRow.addView(tvQty)
                ctrlRow.addView(btnPlus)
                ctrlRow.addView(tvUom)
            }

            col.addView(ctrlRow)
            card.addView(col)
            binding.llTrfLines.addView(card)
        }
    }

    private fun promptQtyEdit(idx: Int) {
        val et = EditText(this).apply {
            setText(numFmt.format(lines[idx].quantity))
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
            setSelectAllOnFocus(true)
        }
        LiquidGlassDialog.builder(this)
            .setTitle("Enter Transfer Qty")
            .setView(et)
            .setPositiveButton("OK") { _, _ ->
                val v = et.text?.toString()?.toDoubleOrNull()
                if (v != null && v > 0) {
                    lines[idx].quantity = v
                    renderLines()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun submitTransfer(targetStatus: String) {
        if (fromLocId <= 0 || toLocId <= 0 || fromLocId == toLocId) {
            Toast.makeText(this, "Choose distinct source & destination warehouses", Toast.LENGTH_SHORT).show()
            return
        }
        if (lines.isEmpty()) {
            Toast.makeText(this, "Add at least one item to transfer", Toast.LENGTH_SHORT).show()
            return
        }

        if (targetStatus == "COMPLETED") {
            val hasInsufficient = lines.any { ln ->
                (ln.quantity * ln.uomFactor) > ln.sourceAvailable
            }
            if (hasInsufficient) {
                LiquidGlassDialog.builder(this)
                    .setTitle("Insufficient Source Stock")
                    .setMessage("Warning: One or more items have insufficient available stock in the source warehouse. Completing this transfer may cause negative inventory. Proceed anyway?")
                    .setPositiveButton("Proceed Anyway") { _, _ ->
                        executeSubmitTransfer(targetStatus)
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
                return
            }
        }
        executeSubmitTransfer(targetStatus)
    }

    private fun executeSubmitTransfer(targetStatus: String) {
        binding.progressTrfDetail.visibility = View.VISIBLE
        binding.btnTrfSaveDraft.isEnabled = false
        binding.btnTrfComplete.isEnabled = false
        val notes = binding.etTrfNotes.text?.toString()?.trim().orEmpty()

        uiScope.launch {
            try {
                val (_, msg) = api.saveTransfer(
                    transferId = transferId,
                    transferNumber = transferNumber,
                    fromLocationId = fromLocId,
                    toLocationId = toLocId,
                    transferDateIso = transferDateIso,
                    notes = notes,
                    status = targetStatus,
                    lines = lines
                )
                Toast.makeText(this@StockTransferDetailActivity, msg, Toast.LENGTH_SHORT).show()
                setResult(Activity.RESULT_OK)
                finish()
            } catch (e: Exception) {
                Toast.makeText(this@StockTransferDetailActivity, e.message ?: "Save failed", Toast.LENGTH_LONG).show()
            } finally {
                binding.progressTrfDetail.visibility = View.GONE
                binding.btnTrfSaveDraft.isEnabled = true
                binding.btnTrfComplete.isEnabled = true
            }
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_TRANSFER_ID = "extra_transfer_id"
    }
}
