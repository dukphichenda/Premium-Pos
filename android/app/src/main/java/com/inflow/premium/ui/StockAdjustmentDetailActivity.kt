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
import androidx.core.widget.NestedScrollView
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.AdjustmentCatalogProduct
import com.inflow.premium.data.AdjustmentCategoryOption
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.StockAdjustmentDetail
import com.inflow.premium.data.StockAdjustmentLine
import com.inflow.premium.data.TransferLocationOption
import com.inflow.premium.databinding.ActivityStockAdjustmentDetailBinding
import com.inflow.premium.databinding.ItemStockAdjustmentLineBinding
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
import kotlin.math.abs

class StockAdjustmentDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityStockAdjustmentDetailBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var adjustmentId: Int = 0
    private var fromHistory: Boolean = false
    private var adjustmentNumber: String = ""
    private var adjustmentDateDisplay: String = ""
    private var adjustmentDateIso: String = ""
    private var status: String = "DRAFT"
    private var locationId: Int = 0
    private var locationName: String = ""
    private var auditor: String = ""
    private var refDoc: String = ""
    private var auditDept: String = ""
    private var reason: String = "Correction"
    private var notes: String = ""
    private var showCustomFieldsPanel: Boolean = false
    private var showRemarksEditor: Boolean = false
    private var lineFilterQuery: String = ""
    private var currentSortKey: String = "default"
    private var totalActiveProducts: Int = 0

    private var locations: List<TransferLocationOption> = emptyList()
    private var categories: List<AdjustmentCategoryOption> = emptyList()
    private val lines = mutableListOf<StockAdjustmentLine>()
    private val numFmt = DecimalFormat("#,##0.##")

    private val reasons = arrayOf(
        "Correction",
        "Integration import",
        "Internal usage",
        "Write-Off",
        "Physical Recount / Cycle Count",
        "Damaged / Broken Goods",
        "Loss / Shrinkage / Theft"
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityStockAdjustmentDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        adjustmentId = intent.getIntExtra(EXTRA_ADJUSTMENT_ID, 0)
        fromHistory = intent.getBooleanExtra(EXTRA_FROM_HISTORY, false)

        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomDockGroup,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollAdjustmentDetail,
            extraTopDp = 6,
            extraBottomScrollDp = 100
        )

        binding.btnAdjDetBack.setOnClickListener { finish() }
        binding.btnAdjCancelAction.setOnClickListener { finish() }
        binding.btnAdjDetHistory.setOnClickListener {
            if (fromHistory) {
                finish()
            } else {
                startActivity(Intent(this, StockAdjustmentsActivity::class.java))
                finish()
            }
        }
        binding.btnAdjDetMore.setOnClickListener { showMoreMenu(it) }

        binding.tvAdjDetailNumber.setOnClickListener {
            if (!isCompleted()) editAdjNumberDialog()
        }
        binding.btnToggleCustomFields.setOnClickListener {
            showCustomFieldsPanel = !showCustomFieldsPanel
            updateCustomFieldsVisibility()
        }
        binding.btnAddRemarksLink.setOnClickListener {
            showRemarksEditor = true
            updateRemarksVisibility()
            binding.etAdjRemarks.requestFocus()
        }

        binding.btnAdjLocation.setOnClickListener {
            if (!isCompleted()) showWarehousePicker()
        }
        binding.btnAdjDate.setOnClickListener {
            if (!isCompleted()) showDatePicker()
        }
        binding.btnEditCustomFields.setOnClickListener {
            if (!isCompleted()) showCustomFieldsDialog()
        }
        binding.btnAdjReason.setOnClickListener {
            if (!isCompleted()) showReasonPicker()
        }

        binding.btnAddByCategory.setOnClickListener {
            if (!isCompleted()) showCategoryBatchPicker()
        }
        binding.btnAddAllProducts.setOnClickListener {
            if (!isCompleted()) confirmAddAllProducts()
        }
        binding.btnAdjSortLines.setOnClickListener {
            if (!isCompleted()) showSortLinesDialog()
        }
        binding.btnCleanZeros.setOnClickListener {
            if (!isCompleted()) cleanZeroChanges()
        }
        binding.btnAdjClearAll.setOnClickListener {
            if (!isCompleted()) confirmClearAllLines()
        }
        binding.etAdjFilterLoaded.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                lineFilterQuery = s?.toString()?.trim().orEmpty()
                renderLines()
            }
        })

        binding.btnAdjAddItem.setOnClickListener {
            if (!isCompleted()) showAddProductDialog()
        }
        binding.tvAdjEmptyLines.setOnClickListener {
            if (!isCompleted()) showAddProductDialog()
        }
        binding.btnAdjPrintWeb.setOnClickListener {
            if (adjustmentId > 0) {
                startActivity(
                    Intent(this, MainActivity::class.java)
                        .putExtra("extra_url", api.buildWebPortalUrl("/inventory/adjustments/$adjustmentId"))
                )
            }
        }
        binding.btnAdjSaveDraft.setOnClickListener { submitAdjustment("DRAFT") }
        binding.btnAdjComplete.setOnClickListener { confirmComplete() }

        loadDetail()
    }

    private fun isCompleted(): Boolean = status.equals("COMPLETED", ignoreCase = true)

    private fun loadDetail() {
        uiScope.launch {
            try {
                val detail = api.getAdjustmentDetail(adjustmentId)
                bindDetail(detail)
            } catch (e: Exception) {
                Toast.makeText(this@StockAdjustmentDetailActivity, e.message ?: "Failed to load adjustment", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun bindDetail(d: StockAdjustmentDetail) {
        adjustmentNumber = d.adjustmentNumber
        adjustmentDateDisplay = d.adjustmentDate
        adjustmentDateIso = d.adjustmentDateIso
        status = d.status
        locationId = d.locationId
        locationName = d.locationName
        auditor = d.auditor
        refDoc = d.refDoc
        auditDept = d.auditDept
        reason = d.reason.ifBlank { "Correction" }
        notes = d.notes
        locations = d.locations
        categories = d.categories
        totalActiveProducts = d.totalActiveProducts
        lines.clear()
        lines.addAll(d.lines)

        binding.tvAdjDetailNumber.text = adjustmentNumber
        binding.btnAdjLocation.text = "📍 ${locationName.ifBlank { "Select Warehouse" }} ⌄"
        binding.btnAdjDate.text = "📅 $adjustmentDateDisplay"
        binding.tvAdjAuditor.text = auditor.ifBlank { "-" }
        binding.tvAdjRefDoc.text = refDoc.ifBlank { "-" }
        binding.tvAdjAuditDept.text = auditDept.ifBlank { "-" }

        val completed = isCompleted()
        binding.btnAdjReason.text = if (completed) reason else "$reason ⌄"

        val prodCountLabel = if (totalActiveProducts > 0) " ($totalActiveProducts)" else ""
        binding.btnAddAllProducts.text = "📦 Add All Products$prodCountLabel"

        if (completed) {
            binding.tvAdjDetStatusPill.text = "✓ COMPLETED"
            binding.tvAdjDetStatusPill.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            binding.tvAdjDetStatusPill.setTextColor(Color.parseColor("#047857"))
            binding.btnToggleCustomFields.visibility = View.GONE
            showCustomFieldsPanel = true
            updateCustomFieldsVisibility()

            binding.btnAddRemarksLink.visibility = View.GONE
            binding.tvAdjRemarksStatic.visibility = View.VISIBLE
            binding.etAdjRemarks.visibility = View.GONE
            if (notes.isBlank()) {
                binding.tvAdjRemarksStatic.text = "No remarks recorded."
                binding.tvAdjRemarksStatic.setTypeface(null, Typeface.ITALIC)
            } else {
                binding.tvAdjRemarksStatic.text = notes
                binding.tvAdjRemarksStatic.setTypeface(null, Typeface.NORMAL)
            }

            binding.cardAdjBatchToolbar.visibility = View.GONE
            binding.btnAdjAddItem.visibility = View.GONE
            binding.btnAdjPrintWeb.visibility = View.VISIBLE
            binding.cardAdjActionsDock.visibility = View.GONE
        } else {
            binding.tvAdjDetStatusPill.text = if (adjustmentId == 0) "NEW" else "✏️ DRAFT"
            binding.tvAdjDetStatusPill.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            binding.tvAdjDetStatusPill.setTextColor(Color.parseColor("#B45309"))
            binding.btnToggleCustomFields.visibility = View.VISIBLE
            showCustomFieldsPanel = refDoc.isNotBlank() || auditDept.isNotBlank()
            updateCustomFieldsVisibility()

            showRemarksEditor = notes.isNotBlank()
            binding.etAdjRemarks.setText(notes)
            updateRemarksVisibility()

            binding.cardAdjBatchToolbar.visibility = View.VISIBLE
            binding.btnAdjAddItem.visibility = View.VISIBLE
            binding.btnAdjPrintWeb.visibility = View.GONE
            binding.cardAdjActionsDock.visibility = View.VISIBLE
        }

        renderLines()
    }

    private fun updateCustomFieldsVisibility() {
        binding.btnEditCustomFields.visibility = if (showCustomFieldsPanel) View.VISIBLE else View.GONE
        binding.btnToggleCustomFields.text = if (showCustomFieldsPanel) "− Hide custom fields" else "+ Add custom fields"
    }

    private fun updateRemarksVisibility() {
        if (isCompleted()) return
        binding.tvAdjRemarksStatic.visibility = View.GONE
        if (showRemarksEditor) {
            binding.btnAddRemarksLink.visibility = View.GONE
            binding.etAdjRemarks.visibility = View.VISIBLE
        } else {
            binding.btnAddRemarksLink.visibility = View.VISIBLE
            binding.etAdjRemarks.visibility = View.GONE
        }
    }

    private fun updateAdjustmentSummary() {
        var netChange = 0.0
        var changedCount = 0
        for (ln in lines) {
            netChange += ln.diffQty
            if (abs(ln.diffQty) > 0.0001) changedCount++
        }
        val itemsChangedLabel = if (changedCount > 0) changedCount else lines.size
        binding.tvAdjItemsChanged.text = "●  $itemsChangedLabel Items Changed"

        val baseUnitLabel = lines.firstOrNull()?.baseUom?.replaceFirstChar { it.uppercaseChar() } ?: "Pcs"
        val sign = if (netChange > 0.0001) "+" else ""
        binding.tvAdjNetChange.text = "$sign${numFmt.format(netChange)} $baseUnitLabel"
        when {
            netChange > 0.0001 -> {
                binding.tvAdjNetChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
                binding.tvAdjNetChange.setTextColor(Color.parseColor("#047857"))
            }
            netChange < -0.0001 -> {
                binding.tvAdjNetChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEE2E2"))
                binding.tvAdjNetChange.setTextColor(Color.parseColor("#B91C1C"))
            }
            else -> {
                binding.tvAdjNetChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#F1F5F9"))
                binding.tvAdjNetChange.setTextColor(Color.parseColor("#475569"))
            }
        }
    }

    private fun updateLineChangeVisuals(lb: ItemStockAdjustmentLineBinding, ln: StockAdjustmentLine, factor: Double) {
        val chgDisp = ln.diffQty / factor
        val diffSign = if (chgDisp > 0.0001) "+" else ""
        lb.tvAdjLineChange.text = "$diffSign${numFmt.format(chgDisp)}"
        when {
            ln.diffQty > 0.0001 -> {
                lb.boxAdjChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#ECFDF5"))
                lb.tvAdjLineChange.setTextColor(Color.parseColor("#047857"))
            }
            ln.diffQty < -0.0001 -> {
                lb.boxAdjChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF2F2"))
                lb.tvAdjLineChange.setTextColor(Color.parseColor("#DC2626"))
            }
            else -> {
                lb.boxAdjChange.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#F1F5F9"))
                lb.tvAdjLineChange.setTextColor(Color.parseColor("#475569"))
            }
        }
    }

    private fun updateLineFooter(lb: ItemStockAdjustmentLineBinding, ln: StockAdjustmentLine) {
        val sublocDisp = ln.sublocation.ifBlank { "—" }
        lb.tvAdjLineMetaFooter.text =
            "On Hand: ${numFmt.format(ln.newQty)} ${ln.baseUom}   •   Subloc: $sublocDisp"
    }

    private fun formatEditableNumber(v: Double): String {
        val formatted = numFmt.format(if (abs(v) < 0.0001) 0.0 else v)
        return formatted.replace(",", "")
    }

    private fun renderLines() {
        val completed = isCompleted()
        binding.containerAdjLines.removeAllViews()
        updateAdjustmentSummary()

        val fq = lineFilterQuery.lowercase(Locale.US)
        val filteredIndices = lines.indices.filter { idx ->
            if (fq.isEmpty()) true else {
                val ln = lines[idx]
                ln.name.lowercase(Locale.US).contains(fq) || ln.sku.lowercase(Locale.US).contains(fq)
            }
        }

        binding.tvBreakdownHeader.text = if (fq.isEmpty()) {
            "ITEMIZED BREAKDOWN (${lines.size})"
        } else {
            "ITEMIZED BREAKDOWN (${filteredIndices.size}/${lines.size})"
        }
        binding.tvAdjEmptyLines.visibility = if (filteredIndices.isEmpty() && !completed) View.VISIBLE else View.GONE

        val inflater = LayoutInflater.from(this)
        filteredIndices.forEachIndexed { displayOrder, realIdx ->
            val ln = lines[realIdx]
            val lb = ItemStockAdjustmentLineBinding.inflate(inflater, binding.containerAdjLines, false)

            val hasAltUom = ln.salesUom.isNotBlank() && ln.salesRatio > 1.0 && !ln.salesUom.equals(ln.baseUom, true)
            val dispUomLabel = if (!completed && hasAltUom) "${ln.uom.uppercase(Locale.US)} ⇄" else ln.uom.uppercase(Locale.US)
            lb.tvAdjLineUom.text = dispUomLabel
            lb.tvAdjLineName.text = ln.name
            lb.tvAdjLineSku.text = ln.sku
            lb.tvAdjLineIndex.text = "#%02d".format(displayOrder + 1)

            if (ln.imageUrl.isNotBlank()) {
                lb.ivAdjLineThumb.visibility = View.VISIBLE
                ImageLoader.load(uiScope, session.baseUrl, ln.imageUrl, lb.ivAdjLineThumb)
            } else {
                lb.ivAdjLineThumb.visibility = View.VISIBLE
                lb.ivAdjLineThumb.setImageResource(android.R.drawable.ic_menu_gallery)
            }

            val factor = if (ln.uomFactor > 0.0) ln.uomFactor else 1.0
            val initDisp = ln.oldQty / factor
            val resDisp = ln.reservedQty / factor
            val availDisp = (ln.newQty - ln.reservedQty) / factor

            lb.tvAdjLineInitial.text = numFmt.format(initDisp)
            updateLineChangeVisuals(lb, ln, factor)
            updateLineFooter(lb, ln)

            var isProgrammaticUpdate = true
            lb.etAdjLineReserved.setText(formatEditableNumber(resDisp))
            lb.etAdjLineAvailable.setText(formatEditableNumber(availDisp))
            isProgrammaticUpdate = false

            if (!completed) {
                lb.btnRemoveAdjLine.visibility = View.VISIBLE
                lb.rowAdjQuickSteps.visibility = View.VISIBLE
                lb.btnRemoveAdjLine.setOnClickListener {
                    lines.removeAt(realIdx)
                    renderLines()
                }
                if (hasAltUom) {
                    lb.tvAdjLineUom.setOnClickListener {
                        val switchingToSales = ln.uom.equals(ln.baseUom, true)
                        if (switchingToSales) {
                            ln.uom = ln.salesUom
                            ln.uomFactor = ln.salesRatio
                        } else {
                            ln.uom = ln.baseUom
                            ln.uomFactor = 1.0
                        }
                        renderLines()
                    }
                }
                lb.btnStepMinus10.setOnClickListener { applyLineDelta(realIdx, -10.0 * factor) }
                lb.btnStepMinus1.setOnClickListener { applyLineDelta(realIdx, -1.0 * factor) }
                lb.btnStepPlus1.setOnClickListener { applyLineDelta(realIdx, 1.0 * factor) }
                lb.btnStepPlus10.setOnClickListener { applyLineDelta(realIdx, 10.0 * factor) }

                lb.boxAdjChange.setOnClickListener { editLineQtyDialog(realIdx, editAvailable = false) }
                lb.boxAdjReserved.setOnClickListener {
                    lb.etAdjLineReserved.requestFocus()
                    lb.etAdjLineReserved.setSelection(lb.etAdjLineReserved.text.length)
                }
                lb.boxAdjAvailable.setOnClickListener {
                    lb.etAdjLineAvailable.requestFocus()
                    lb.etAdjLineAvailable.setSelection(lb.etAdjLineAvailable.text.length)
                }

                lb.etAdjLineReserved.addTextChangedListener(object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                    override fun afterTextChanged(s: Editable?) {
                        if (isProgrammaticUpdate) return
                        val v = s?.toString()?.trim()?.replace(",", "")?.toDoubleOrNull() ?: return
                        ln.reservedQty = v * factor
                        ln.reservedEdited = true
                        isProgrammaticUpdate = true
                        lb.etAdjLineAvailable.setText(formatEditableNumber((ln.newQty - ln.reservedQty) / factor))
                        isProgrammaticUpdate = false
                        updateLineFooter(lb, ln)
                    }
                })

                lb.etAdjLineAvailable.addTextChangedListener(object : TextWatcher {
                    override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                    override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
                    override fun afterTextChanged(s: Editable?) {
                        if (isProgrammaticUpdate) return
                        val v = s?.toString()?.trim()?.replace(",", "")?.toDoubleOrNull() ?: return
                        ln.newQty = (v * factor) + ln.reservedQty
                        ln.diffQty = ln.newQty - ln.oldQty
                        updateLineChangeVisuals(lb, ln, factor)
                        updateLineFooter(lb, ln)
                        updateAdjustmentSummary()
                    }
                })
            } else {
                lb.btnRemoveAdjLine.visibility = View.GONE
                lb.rowAdjQuickSteps.visibility = View.GONE
                lb.etAdjLineReserved.isEnabled = false
                lb.etAdjLineReserved.isFocusable = false
                lb.etAdjLineReserved.isFocusableInTouchMode = false
                lb.etAdjLineReserved.isCursorVisible = false
                lb.etAdjLineAvailable.isEnabled = false
                lb.etAdjLineAvailable.isFocusable = false
                lb.etAdjLineAvailable.isFocusableInTouchMode = false
                lb.etAdjLineAvailable.isCursorVisible = false
            }

            binding.containerAdjLines.addView(lb.root)
        }
    }

    private fun applyLineDelta(index: Int, baseDelta: Double) {
        if (index !in lines.indices) return
        val ln = lines[index]
        ln.diffQty += baseDelta
        ln.newQty = ln.oldQty + ln.diffQty
        renderLines()
    }

    private fun editLineQtyDialog(index: Int, editAvailable: Boolean) {
        val ln = lines[index]
        val factor = if (ln.uomFactor > 0.0) ln.uomFactor else 1.0
        val dp = resources.displayMetrics.density
        val pad = (18 * dp).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (10 * dp).toInt(), pad, 0)
        }
        val infoTv = TextView(this).apply {
            text = "${ln.name}\nInitial: ${numFmt.format(ln.oldQty / factor)} ${ln.uom}  •  Reserved: ${numFmt.format(ln.reservedQty / factor)} ${ln.uom}" +
                if (factor > 1.0) " (1 ${ln.uom} = ${numFmt.format(factor)} ${ln.baseUom})" else ""
            setTextColor(Color.parseColor("#475569"))
            textSize = 12.5f
        }
        val input = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL or InputType.TYPE_NUMBER_FLAG_SIGNED
            val initialVal = if (editAvailable) (ln.newQty - ln.reservedQty) / factor else ln.diffQty / factor
            setText(numFmt.format(initialVal).replace(",", ""))
            setSelection(text.length)
            hint = if (editAvailable) "Enter available qty (${ln.uom})" else "Enter +/- change (${ln.uom})"
        }
        box.addView(infoTv)
        box.addView(input)

        LiquidGlassDialog.builder(this)
            .setTitle(if (editAvailable) "Set Qty Available (${ln.uom})" else "Set Change (${ln.uom})")
            .setView(box)
            .setPositiveButton("Apply") { _, _ ->
                val v = input.text.toString().trim().toDoubleOrNull()
                if (v == null) {
                    Toast.makeText(this, "Enter a valid number", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                val baseVal = v * factor
                if (editAvailable) {
                    ln.newQty = baseVal + ln.reservedQty
                    ln.diffQty = ln.newQty - ln.oldQty
                } else {
                    ln.diffQty = baseVal
                    ln.newQty = ln.oldQty + baseVal
                }
                renderLines()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun editAdjNumberDialog() {
        val dp = resources.displayMetrics.density
        val pad = (18 * dp).toInt()
        val input = EditText(this).apply {
            setText(adjustmentNumber)
            setSelection(text.length)
            isSingleLine = true
        }
        val wrap = LinearLayout(this).apply {
            setPadding(pad, (8 * dp).toInt(), pad, 0)
            addView(input)
        }
        LiquidGlassDialog.builder(this)
            .setTitle("Stock Adjustment Number")
            .setView(wrap)
            .setPositiveButton("OK") { _, _ ->
                val v = input.text.toString().trim()
                if (v.isNotEmpty()) {
                    adjustmentNumber = v
                    binding.tvAdjDetailNumber.text = adjustmentNumber
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showCategoryBatchPicker() {
        if (categories.isEmpty()) {
            Toast.makeText(this, "No product categories found", Toast.LENGTH_SHORT).show()
            return
        }
        val labels = categories.map { "${it.name} (${it.productCount})" }.toTypedArray()
        val checked = BooleanArray(categories.size)
        LiquidGlassDialog.builder(this)
            .setTitle("Add Products by Category")
            .setMultiChoiceItems(labels, checked) { _, which, isChecked ->
                checked[which] = isChecked
            }
            .setPositiveButton("Add Selected") { _, _ ->
                val chosenIds = categories.indices.filter { checked[it] }.map { categories[it].id }
                if (chosenIds.isEmpty()) {
                    Toast.makeText(this, "Select at least one category", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                batchAddProducts(categoryIds = chosenIds, fetchAll = false)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun confirmAddAllProducts() {
        val countHint = if (totalActiveProducts > 0) "$totalActiveProducts active products" else "all active products"
        LiquidGlassDialog.builder(this)
            .setTitle("Add All Products")
            .setMessage("Load $countHint in $locationName into this adjustment list?")
            .setPositiveButton("Load All") { _, _ ->
                batchAddProducts(categoryIds = emptyList(), fetchAll = true)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun batchAddProducts(categoryIds: List<Int>, fetchAll: Boolean) {
        uiScope.launch {
            try {
                val prods = api.searchAdjustmentProducts(
                    query = "",
                    locationId = locationId,
                    categoryIds = categoryIds,
                    fetchAll = fetchAll,
                    sortBy = if (currentSortKey == "default") "name" else currentSortKey
                )
                val existingIds = lines.map { it.productId }.toHashSet()
                var added = 0
                for (p in prods) {
                    if (existingIds.add(p.id)) {
                        lines.add(
                            StockAdjustmentLine(
                                productId = p.id,
                                sku = p.sku,
                                name = p.name,
                                uom = p.uom,
                                baseUom = p.uom,
                                salesUom = p.salesUom,
                                salesRatio = p.salesRatio,
                                uomFactor = 1.0,
                                imageUrl = p.imageUrl,
                                sublocation = p.sublocation,
                                oldQty = p.onHandQty,
                                diffQty = 0.0,
                                newQty = p.onHandQty,
                                onHandQty = p.onHandQty,
                                reservedQty = p.reservedQty,
                                categoryName = p.categoryName
                            )
                        )
                        added++
                    }
                }
                renderLines()
                Toast.makeText(
                    this@StockAdjustmentDetailActivity,
                    if (added > 0) "Added $added product(s)" else "All matching products already loaded",
                    Toast.LENGTH_SHORT
                ).show()
            } catch (e: Exception) {
                Toast.makeText(this@StockAdjustmentDetailActivity, e.message ?: "Batch load failed", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun showSortLinesDialog() {
        val opts = arrayOf("Name (A–Z)", "By Category", "Lowest Stock First", "Highest Stock First")
        val keys = arrayOf("name", "category", "lowest", "highest")
        val checked = keys.indexOf(currentSortKey).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Arrange Items By")
            .setSingleChoiceItems(opts, checked) { dlg, which ->
                currentSortKey = keys[which]
                binding.btnAdjSortLines.text = "⇅ ${opts[which]} ⌄"
                when (currentSortKey) {
                    "category" -> lines.sortWith(compareBy({ it.categoryName.lowercase(Locale.US) }, { it.name.lowercase(Locale.US) }))
                    "lowest" -> lines.sortWith(compareBy({ it.onHandQty }, { it.name.lowercase(Locale.US) }))
                    "highest" -> lines.sortWith(compareByDescending<StockAdjustmentLine> { it.onHandQty }.thenBy { it.name.lowercase(Locale.US) })
                    else -> lines.sortBy { it.name.lowercase(Locale.US) }
                }
                dlg.dismiss()
                renderLines()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun cleanZeroChanges() {
        val before = lines.size
        lines.removeAll { abs(it.diffQty) < 0.0001 }
        val removed = before - lines.size
        renderLines()
        Toast.makeText(
            this,
            if (removed > 0) "Removed $removed unchanged (0) item(s)" else "No 0-change items to clean",
            Toast.LENGTH_SHORT
        ).show()
    }

    private fun confirmClearAllLines() {
        if (lines.isEmpty()) return
        LiquidGlassDialog.builder(this)
            .setTitle("Clear All Items")
            .setMessage("Remove all ${lines.size} item(s) from this list?")
            .setPositiveButton("Clear All") { _, _ ->
                lines.clear()
                renderLines()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showWarehousePicker() {
        if (locations.isEmpty()) return
        val names = locations.map { it.name }.toTypedArray()
        val checked = locations.indexOfFirst { it.id == locationId }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Select Warehouse")
            .setSingleChoiceItems(names, checked) { dlg, which ->
                val loc = locations[which]
                locationId = loc.id
                locationName = loc.name
                binding.btnAdjLocation.text = "📍 $locationName ⌄"
                dlg.dismiss()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showDatePicker() {
        val cal = Calendar.getInstance()
        try {
            val sdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)
            sdf.parse(adjustmentDateIso)?.let { cal.time = it }
        } catch (_: Exception) {}
        DatePickerDialog(
            this,
            { _, y, m, day ->
                val c = Calendar.getInstance().apply { set(y, m, day) }
                adjustmentDateIso = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(c.time)
                adjustmentDateDisplay = SimpleDateFormat("dd MMM yyyy", Locale.US).format(c.time)
                binding.btnAdjDate.text = "📅 $adjustmentDateDisplay"
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun showReasonPicker() {
        val checked = reasons.indexOfFirst { it.equals(reason, ignoreCase = true) }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Adjustment Reason")
            .setSingleChoiceItems(reasons, checked) { dlg, which ->
                reason = reasons[which]
                binding.btnAdjReason.text = "$reason ⌄"
                dlg.dismiss()
            }
            .setNeutralButton("Custom...") { _, _ ->
                val input = EditText(this).apply {
                    setText(reason)
                    hint = "Enter custom reason"
                }
                val pad = (18 * resources.displayMetrics.density).toInt()
                val wrap = LinearLayout(this).apply {
                    setPadding(pad, (8 * resources.displayMetrics.density).toInt(), pad, 0)
                    addView(input)
                }
                LiquidGlassDialog.builder(this)
                    .setTitle("Custom Reason")
                    .setView(wrap)
                    .setPositiveButton("OK") { _, _ ->
                        val v = input.text.toString().trim()
                        if (v.isNotEmpty()) {
                            reason = v
                            binding.btnAdjReason.text = "$reason ⌄"
                        }
                    }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showCustomFieldsDialog() {
        val dp = resources.displayMetrics.density
        val pad = (18 * dp).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (8 * dp).toInt(), pad, 0)
        }
        val etAud = EditText(this).apply {
            hint = "Auditor / Counted By"
            setText(auditor)
        }
        val etRef = EditText(this).apply {
            hint = "Reference SO / PO #"
            setText(refDoc)
        }
        val etDept = EditText(this).apply {
            hint = "Audit Dept / Tag"
            setText(auditDept)
        }
        box.addView(etAud)
        box.addView(etRef)
        box.addView(etDept)

        LiquidGlassDialog.builder(this)
            .setTitle("Custom Fields")
            .setView(box)
            .setPositiveButton("Save") { _, _ ->
                auditor = etAud.text.toString().trim()
                refDoc = etRef.text.toString().trim()
                auditDept = etDept.text.toString().trim()
                binding.tvAdjAuditor.text = auditor.ifBlank { "-" }
                binding.tvAdjRefDoc.text = refDoc.ifBlank { "-" }
                binding.tvAdjAuditDept.text = auditDept.ifBlank { "-" }
                showCustomFieldsPanel = true
                updateCustomFieldsVisibility()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showMoreMenu(anchor: View) {
        val menu = PopupMenu(this, anchor)
        if (adjustmentId > 0) {
            menu.menu.add(0, 1, 0, "Open in Web Portal")
        }
        if (adjustmentId > 0 && !isCompleted()) {
            menu.menu.add(0, 2, 1, "Delete Draft")
        }
        menu.setOnMenuItemClickListener { item ->
            when (item.itemId) {
                1 -> {
                    startActivity(
                        Intent(this, MainActivity::class.java)
                            .putExtra("extra_url", api.buildWebPortalUrl("/inventory/adjustments/$adjustmentId"))
                    )
                    true
                }
                2 -> {
                    confirmDeleteDraft()
                    true
                }
                else -> false
            }
        }
        menu.show()
    }

    private fun confirmDeleteDraft() {
        LiquidGlassDialog.builder(this)
            .setTitle("Delete Draft")
            .setMessage("Delete draft $adjustmentNumber?")
            .setPositiveButton("Delete") { _, _ ->
                uiScope.launch {
                    try {
                        val msg = api.deleteAdjustment(adjustmentId)
                        Toast.makeText(this@StockAdjustmentDetailActivity, msg, Toast.LENGTH_SHORT).show()
                        setResult(Activity.RESULT_OK)
                        finish()
                    } catch (e: Exception) {
                        Toast.makeText(this@StockAdjustmentDetailActivity, e.message ?: "Delete failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showAddProductDialog() {
        if (locationId <= 0) {
            Toast.makeText(this, "Select a warehouse first", Toast.LENGTH_SHORT).show()
            return
        }
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
            layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (360 * dp).toInt())
        }
        val resultsList = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        resultsScroll.addView(resultsList)
        root.addView(etSearch)
        root.addView(resultsScroll)

        val dlg = LiquidGlassDialog.builder(this)
            .setTitle("Add Product ($locationName)")
            .setView(root)
            .setNegativeButton("Close", null)
            .create()

        var searchJob: Job? = null
        fun runSearch(q: String) {
            searchJob?.cancel()
            searchJob = uiScope.launch {
                if (q.isNotEmpty()) delay(220)
                try {
                    val prods = api.searchAdjustmentProducts(q, locationId)
                    resultsList.removeAllViews()
                    if (prods.isEmpty()) {
                        resultsList.addView(TextView(this@StockAdjustmentDetailActivity).apply {
                            text = "No matching products"
                            setTextColor(Color.parseColor("#64748B"))
                            setPadding(8, 24, 8, 24)
                        })
                    } else {
                        for (p in prods) {
                            resultsList.addView(buildCatalogPickCard(p, dlg))
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

    private fun buildCatalogPickCard(p: AdjustmentCatalogProduct, dlg: androidx.appcompat.app.AlertDialog): View {
        val dp = resources.displayMetrics.density
        val card = MaterialCardView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = (8 * dp).toInt() }
            radius = 12 * dp
            cardElevation = 0f
            strokeWidth = (1 * dp).toInt()
            strokeColor = Color.parseColor("#E2E8F0")
            setCardBackgroundColor(Color.WHITE)
        }
        val inner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val p12 = (12 * dp).toInt()
            setPadding(p12, (10 * dp).toInt(), p12, (10 * dp).toInt())
        }
        inner.addView(TextView(this).apply {
            text = p.name
            setTextColor(Color.parseColor("#0F172A"))
            textSize = 13.5f
            setTypeface(null, Typeface.BOLD)
        })
        inner.addView(TextView(this).apply {
            text = "${p.sku}  •  On Hand: ${numFmt.format(p.onHandQty)} ${p.uom}"
            setTextColor(Color.parseColor("#64748B"))
            textSize = 11.5f
        })
        card.addView(inner)
        card.setOnClickListener {
            val existing = lines.indexOfFirst { it.productId == p.id }
            if (existing >= 0) {
                dlg.dismiss()
                editLineQtyDialog(existing, editAvailable = true)
            } else {
                lines.add(
                    StockAdjustmentLine(
                        productId = p.id,
                        sku = p.sku,
                        name = p.name,
                        uom = p.uom,
                        baseUom = p.uom,
                        salesUom = p.salesUom,
                        salesRatio = p.salesRatio,
                        uomFactor = 1.0,
                        imageUrl = p.imageUrl,
                        sublocation = p.sublocation,
                        oldQty = p.onHandQty,
                        diffQty = 0.0,
                        newQty = p.onHandQty,
                        onHandQty = p.onHandQty,
                        reservedQty = p.reservedQty,
                        categoryName = p.categoryName
                    )
                )
                renderLines()
                dlg.dismiss()
                editLineQtyDialog(lines.lastIndex, editAvailable = true)
            }
        }
        return card
    }

    private fun confirmComplete() {
        if (lines.isEmpty()) {
            Toast.makeText(this, "Add at least one product first", Toast.LENGTH_SHORT).show()
            return
        }
        LiquidGlassDialog.builder(this)
            .setTitle("Adjust Stock")
            .setMessage("Apply stock count changes in $locationName for $adjustmentNumber? Inventory quantities will be updated immediately.")
            .setPositiveButton("Adjust stock") { _, _ -> submitAdjustment("COMPLETED") }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun submitAdjustment(targetStatus: String) {
        if (lines.isEmpty()) {
            Toast.makeText(this, "Add at least one product first", Toast.LENGTH_SHORT).show()
            return
        }
        val notesText = if (showRemarksEditor) binding.etAdjRemarks.text.toString().trim() else notes
        binding.btnAdjSaveDraft.isEnabled = false
        binding.btnAdjComplete.isEnabled = false
        uiScope.launch {
            try {
                val (newId, msg) = api.saveAdjustment(
                    adjustmentId = adjustmentId,
                    adjustmentNumber = adjustmentNumber,
                    locationId = locationId,
                    adjustmentDateIso = adjustmentDateIso,
                    reason = reason,
                    notes = notesText,
                    auditor = auditor,
                    refDoc = refDoc,
                    auditDept = auditDept,
                    status = targetStatus,
                    lines = lines
                )
                adjustmentId = newId
                Toast.makeText(this@StockAdjustmentDetailActivity, msg, Toast.LENGTH_SHORT).show()
                setResult(Activity.RESULT_OK)
                loadDetail()
            } catch (e: Exception) {
                Toast.makeText(this@StockAdjustmentDetailActivity, e.message ?: "Save failed", Toast.LENGTH_SHORT).show()
            } finally {
                binding.btnAdjSaveDraft.isEnabled = true
                binding.btnAdjComplete.isEnabled = true
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }

    companion object {
        const val EXTRA_ADJUSTMENT_ID = "extra_adjustment_id"
        const val EXTRA_FROM_HISTORY = "extra_from_history"
    }
}
