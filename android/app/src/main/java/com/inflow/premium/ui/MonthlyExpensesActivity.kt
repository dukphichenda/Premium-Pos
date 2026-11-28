package com.inflow.premium.ui

import android.app.DatePickerDialog
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.card.MaterialCardView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.CashAccountRow
import com.inflow.premium.data.ExpenseRow
import com.inflow.premium.data.MonthlyExpensesData
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityMonthlyExpensesBinding
import com.inflow.premium.databinding.ItemExpenseRowBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

class MonthlyExpensesActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMonthlyExpensesBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentData: MonthlyExpensesData? = null
    private var selectedMonthKey: String = ""
    private var activeSubTab = 0 // 0=Expenses, 1=Accounts, 2=Summary
    private var selectedPayerFilter = "All"
    private var searchFilter = ""
    private var showAllItems = false

    private var quickPayer = "Chenda"
    private var quickCategory = "General"
    private var quickDateIso = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())

    private val moneyFmt = DecimalFormat("#,##0.00")
    private val numFmt = DecimalFormat("#,##0.##")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityMonthlyExpensesBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.HOME)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = binding.topHeader,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollMonthlyExpenses,
            extraTopDp = 6,
            extraBottomScrollDp = 120
        )

        binding.btnExpBack.setOnClickListener { finish() }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadExpenses() }
        binding.btnExpMonthPicker.setOnClickListener { showMonthPicker() }
        binding.btnExpQuickAddFocus.setOnClickListener {
            selectSubTab(0)
            binding.etQuickExpItem.requestFocus()
        }

        binding.tabExpList.setOnClickListener { selectSubTab(0) }
        binding.tabExpAccounts.setOnClickListener { selectSubTab(1) }
        binding.tabExpSummary.setOnClickListener { selectSubTab(2) }

        binding.btnQuickExpDate.text = SimpleDateFormat("dd-MMM-yyyy", Locale.US).format(Date())
        binding.btnQuickExpDate.setOnClickListener { showQuickDatePicker() }
        binding.btnQuickExpPayer.setOnClickListener { pickQuickOption(isPayer = true) }
        binding.btnQuickExpCategory.setOnClickListener { pickQuickOption(isPayer = false) }
        binding.btnAddMonthlyExpense.setOnClickListener { submitQuickExpense() }

        val calcSubtotalWatcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val p = binding.etQuickExpPrice.text?.toString()?.toDoubleOrNull() ?: 0.0
                val q = binding.etQuickExpQty.text?.toString()?.toDoubleOrNull() ?: 1.0
                binding.tvQuickExpSubtotal.text = "$${moneyFmt.format(p * q)}"
            }
        }
        binding.etQuickExpPrice.addTextChangedListener(calcSubtotalWatcher)
        binding.etQuickExpQty.addTextChangedListener(calcSubtotalWatcher)

        binding.etExpSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                searchFilter = s?.toString()?.trim().orEmpty()
                renderBreakdown()
            }
        })
        binding.btnExpPayerFilter.setOnClickListener { showPayerFilterPicker() }
        binding.btnExpShowMore.setOnClickListener {
            showAllItems = !showAllItems
            renderBreakdown()
        }
        binding.btnAddCashAccount.setOnClickListener { promptAddOrEditAccount(null) }

        loadExpenses()
    }

    private fun selectSubTab(idx: Int) {
        activeSubTab = idx
        val tabs = listOf(binding.tabExpList, binding.tabExpAccounts, binding.tabExpSummary)
        tabs.forEachIndexed { i, tv ->
            if (i == idx) {
                tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
                tv.setTextColor(Color.parseColor("#0A6C62"))
            } else {
                tv.background = null
                tv.setTextColor(Color.parseColor("#64748B"))
            }
        }
        binding.llExpSectionExpenses.visibility = if (idx == 0) View.VISIBLE else View.GONE
        binding.llExpSectionAccounts.visibility = if (idx == 1) View.VISIBLE else View.GONE
        binding.llExpSectionSummary.visibility = if (idx == 2) View.VISIBLE else View.GONE
    }

    private fun loadExpenses() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val data = api.getMonthlyExpenses(selectedMonthKey, session.selectedBranch)
                currentData = data
                selectedMonthKey = data.monthKey
                bindData(data)
            } catch (e: Exception) {
                Toast.makeText(this@MonthlyExpensesActivity, e.message ?: "Failed to load expenses", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun bindData(d: MonthlyExpensesData) {
        binding.btnExpMonthPicker.text = "📅 ${d.monthDisplay} ⌄"
        binding.tvExpTotalHero.text = "$${moneyFmt.format(d.totalExpenses)}"
        binding.tvExpHeroItemsBadge.text = "${d.itemCount} ITEMS"

        binding.tvExpOpeningTag.text = if (d.isManualOpening) "Manual" else "Auto"
        binding.tvExpOpeningVal.text = "$${moneyFmt.format(d.openingBalance)}"
        binding.tvExpOpeningSub.text = if (d.prevMonthDisplay.isNotBlank()) "From ${d.prevMonthDisplay}" else "Opening balance"

        binding.tvExpSalesVal.text = "$${moneyFmt.format(d.salesReceived)}"
        binding.tvExpSalesSub.text = "${d.paidInvoiceCount} orders paid"

        binding.tvExpClearVal.text = "$${numFmt.format(d.clearStm)} / $${numFmt.format(d.clearSk)}"
        binding.tvExpMediaVal.text = "$${moneyFmt.format(d.mediaTotal)}"
        binding.tvExpMediaSub.text = "Sheet: $${moneyFmt.format(d.mediaSheetTotal)}"

        binding.tvExpExpectedVal.text = "$${moneyFmt.format(d.moneyInHand)}"
        val varSign = if (d.cashVariance >= 0) "+" else "-"
        val isShort = d.cashVariance < -0.01
        binding.tvExpVarianceLabel.text = if (isShort) {
            "⚠ Shortage (ខ្វះ) • Counted: $${moneyFmt.format(d.totalCountedCash)}"
        } else {
            "✓ Matched / Surplus • Counted: $${moneyFmt.format(d.totalCountedCash)}"
        }
        binding.tvExpVarianceLabel.setTextColor(Color.parseColor(if (isShort) "#BE123C" else "#047857"))
        binding.tvExpVarianceVal.text = "$varSign$${moneyFmt.format(kotlin.math.abs(d.cashVariance))}"
        binding.tvExpVarianceVal.setTextColor(Color.parseColor(if (isShort) "#BE123C" else "#047857"))

        binding.tabExpList.text = "Expenses (${d.itemCount})"
        binding.tvExpVerifiedLabel.text = "សរុបចំណាយ (Total ${d.itemCount} items)"
        binding.tvExpVerifiedTotal.text = "$${moneyFmt.format(d.totalExpenses)}"
        binding.tvExpTotalCountedFooter.text = "$${moneyFmt.format(d.totalCountedCash)}"

        if (d.payers.isNotEmpty() && !d.payers.contains(quickPayer)) quickPayer = d.payers.first()
        if (d.categories.isNotEmpty() && !d.categories.contains(quickCategory)) quickCategory = d.categories.first()
        binding.btnQuickExpPayer.text = "Paid By: $quickPayer ⌄"
        binding.btnQuickExpCategory.text = "Category: $quickCategory ⌄"

        renderMonthPills(d)
        renderBreakdown()
        renderCashAccountsSummary(d.accounts)
        renderAccountsTab(d)
        renderSummaryTab(d)
    }

    private fun renderMonthPills(d: MonthlyExpensesData) {
        binding.llExpMonthTabs.removeAllViews()
        for (tab in d.monthTabs) {
            val active = tab.key == d.monthKey
            val tv = TextView(this).apply {
                text = if (active) "📅 ${tab.label}" else tab.label
                textSize = 12f
                setTypeface(null, android.graphics.Typeface.BOLD)
                setPadding(dp(12), dp(6), dp(12), dp(6))
                if (active) {
                    setBackgroundResource(R.drawable.bg_pill_teal_solid)
                    backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0A6C62"))
                    setTextColor(Color.WHITE)
                } else {
                    setBackgroundResource(R.drawable.bg_floating_top_capsule)
                    backgroundTintList = null
                    setTextColor(Color.parseColor("#334155"))
                }
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { marginEnd = dp(8) }
                setOnClickListener {
                    if (tab.key != selectedMonthKey) {
                        selectedMonthKey = tab.key
                        showAllItems = false
                        loadExpenses()
                    }
                }
            }
            binding.llExpMonthTabs.addView(tv)
        }
    }

    private fun renderBreakdown() {
        val d = currentData ?: return
        binding.llExpBreakdownList.removeAllViews()
        val filtered = d.expenses.filter { e ->
            val matchPayer = selectedPayerFilter == "All" || e.paidBy.equals(selectedPayerFilter, true)
            val q = searchFilter.lowercase(Locale.US)
            val matchQ = q.isBlank() || e.item.lowercase(Locale.US).contains(q) ||
                e.category.lowercase(Locale.US).contains(q) || e.paidBy.lowercase(Locale.US).contains(q)
            matchPayer && matchQ
        }
        binding.tvExpBreakdownBadge.text = "${filtered.size} total"

        val limit = if (showAllItems) filtered.size else minOf(5, filtered.size)
        val inflater = LayoutInflater.from(this)
        for (idx in 0 until limit) {
            val e = filtered[idx]
            val rb = ItemExpenseRowBinding.inflate(inflater, binding.llExpBreakdownList, false)
            rb.tvExpRowIdx.text = (idx + 1).toString()
            rb.tvExpRowTitle.text = e.item
            if (e.paidBy.isNotBlank()) {
                rb.tvExpRowPayerTag.visibility = View.VISIBLE
                rb.tvExpRowPayerTag.text = "• ${e.paidBy}"
            } else {
                rb.tvExpRowPayerTag.visibility = View.GONE
            }
            rb.tvExpRowMeta.text = "Qty ${numFmt.format(e.quantity)} • ${e.expenseDate} • ${e.category}"
            rb.tvExpRowAmount.text = "$${moneyFmt.format(e.totalPrice)}"
            rb.btnExpRowEdit.setOnClickListener { promptEditExpense(e) }
            rb.btnExpRowDelete.setOnClickListener { confirmDeleteExpense(e) }
            binding.llExpBreakdownList.addView(rb.root)
        }

        val remaining = filtered.size - limit
        if (remaining > 0) {
            binding.btnExpShowMore.visibility = View.VISIBLE
            binding.btnExpShowMore.text = "View remaining $remaining items ⌄"
        } else if (showAllItems && filtered.size > 5) {
            binding.btnExpShowMore.visibility = View.VISIBLE
            binding.btnExpShowMore.text = "Collapse list ⌃"
        } else {
            binding.btnExpShowMore.visibility = View.GONE
        }
    }

    private fun renderCashAccountsSummary(accounts: List<CashAccountRow>) {
        binding.llCashAccountsSummaryGrid.removeAllViews()
        val dotColors = listOf("#2563EB", "#10B981", "#4F46E5", "#F59E0B", "#9333EA", "#0891B2")
        var idx = 0
        while (idx < accounts.size) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = dp(6) }
            }
            for (c in 0 until 2) {
                val acc = accounts.getOrNull(idx + c)
                if (acc != null) {
                    val colorHex = dotColors[(idx + c) % dotColors.size]
                    val cell = LinearLayout(this).apply {
                        orientation = LinearLayout.HORIZONTAL
                        gravity = Gravity.CENTER_VERTICAL
                        layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                            if (c == 0) marginEnd = dp(8)
                        }
                        setOnClickListener { promptAddOrEditAccount(acc) }
                    }
                    val dot = TextView(this).apply {
                        text = "● "
                        setTextColor(Color.parseColor(colorHex))
                        textSize = 11f
                    }
                    val tvName = TextView(this).apply {
                        text = acc.name
                        setTextColor(Color.parseColor("#334155"))
                        textSize = 11.5f
                        layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                    }
                    val tvAmt = TextView(this).apply {
                        text = "$${moneyFmt.format(acc.amount)}"
                        setTextColor(Color.parseColor("#0F172A"))
                        textSize = 11.5f
                        setTypeface(null, android.graphics.Typeface.BOLD)
                    }
                    cell.addView(dot)
                    cell.addView(tvName)
                    cell.addView(tvAmt)
                    row.addView(cell)
                } else {
                    row.addView(View(this).apply { layoutParams = LinearLayout.LayoutParams(0, 1, 1f) })
                }
            }
            binding.llCashAccountsSummaryGrid.addView(row)
            idx += 2
        }
    }

    private fun renderAccountsTab(d: MonthlyExpensesData) {
        binding.llExpSectionAccounts.removeAllViews()
        for (acc in d.accounts) {
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
                setOnClickListener { promptAddOrEditAccount(acc) }
            }
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(dp(14), dp(12), dp(14), dp(12))
            }
            row.addView(TextView(this).apply {
                text = acc.name
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(TextView(this).apply {
                text = "$${moneyFmt.format(acc.amount)}  ✎"
                setTextColor(Color.parseColor("#0A6C62"))
                textSize = 13.5f
                setTypeface(null, android.graphics.Typeface.BOLD)
            })
            card.addView(row)
            binding.llExpSectionAccounts.addView(card)
        }
    }

    private fun renderSummaryTab(d: MonthlyExpensesData) {
        binding.llExpSectionSummary.removeAllViews()
        val byCat = d.expenses.groupBy { it.category.ifBlank { "General" } }
            .mapValues { (_, list) -> list.sumOf { it.totalPrice } }
            .toList()
            .sortedByDescending { it.second }

        for ((cat, amt) in byCat) {
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
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                setPadding(dp(14), dp(12), dp(14), dp(12))
            }
            row.addView(TextView(this).apply {
                text = cat
                setTextColor(Color.parseColor("#0F172A"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(TextView(this).apply {
                text = "$${moneyFmt.format(amt)}"
                setTextColor(Color.parseColor("#DC2626"))
                textSize = 13f
                setTypeface(null, android.graphics.Typeface.BOLD)
            })
            card.addView(row)
            binding.llExpSectionSummary.addView(card)
        }
    }

    private fun showMonthPicker() {
        val tabs = currentData?.monthTabs ?: return
        val labels = tabs.map { it.label }.toTypedArray()
        val checked = tabs.indexOfFirst { it.key == selectedMonthKey }.coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Select Month")
            .setSingleChoiceItems(labels, checked) { dlg, which ->
                selectedMonthKey = tabs[which].key
                showAllItems = false
                dlg.dismiss()
                loadExpenses()
            }
            .setNegativeButton("Close", null)
            .show()
    }

    private fun showQuickDatePicker() {
        val cal = Calendar.getInstance()
        DatePickerDialog(
            this,
            { _, y, m, day ->
                val c = Calendar.getInstance().apply { set(y, m, day) }
                quickDateIso = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(c.time)
                binding.btnQuickExpDate.text = SimpleDateFormat("dd-MMM-yyyy", Locale.US).format(c.time)
            },
            cal.get(Calendar.YEAR),
            cal.get(Calendar.MONTH),
            cal.get(Calendar.DAY_OF_MONTH)
        ).show()
    }

    private fun pickQuickOption(isPayer: Boolean) {
        val d = currentData ?: return
        val opts = if (isPayer) d.payers else d.categories
        if (opts.isEmpty()) return
        LiquidGlassDialog.builder(this)
            .setTitle(if (isPayer) "Paid By" else "Expense Category")
            .setItems(opts.toTypedArray()) { _, which ->
                if (isPayer) {
                    quickPayer = opts[which]
                    binding.btnQuickExpPayer.text = "Paid By: $quickPayer ⌄"
                } else {
                    quickCategory = opts[which]
                    binding.btnQuickExpCategory.text = "Category: $quickCategory ⌄"
                }
            }
            .show()
    }

    private fun showPayerFilterPicker() {
        val d = currentData ?: return
        val opts = listOf("All") + d.payers
        val checked = opts.indexOf(selectedPayerFilter).coerceAtLeast(0)
        LiquidGlassDialog.builder(this)
            .setTitle("Filter by Payer")
            .setSingleChoiceItems(opts.toTypedArray(), checked) { dlg, which ->
                selectedPayerFilter = opts[which]
                binding.btnExpPayerFilter.text = if (selectedPayerFilter == "All") "All Payers ⌄" else "$selectedPayerFilter ⌄"
                dlg.dismiss()
                renderBreakdown()
            }
            .show()
    }

    private fun submitQuickExpense() {
        val item = binding.etQuickExpItem.text?.toString()?.trim().orEmpty()
        val price = binding.etQuickExpPrice.text?.toString()?.toDoubleOrNull() ?: 0.0
        val qty = binding.etQuickExpQty.text?.toString()?.toDoubleOrNull() ?: 1.0
        if (item.isBlank()) {
            Toast.makeText(this, "Enter expense item description", Toast.LENGTH_SHORT).show()
            return
        }
        binding.btnAddMonthlyExpense.isEnabled = false
        uiScope.launch {
            try {
                val msg = api.addExpense(
                    monthKey = selectedMonthKey,
                    branch = session.selectedBranch,
                    item = item,
                    unitPrice = price,
                    quantity = qty,
                    paidBy = quickPayer,
                    category = quickCategory,
                    expenseDateIso = quickDateIso
                )
                binding.etQuickExpItem.setText("")
                binding.etQuickExpPrice.setText("")
                binding.etQuickExpQty.setText("1")
                Toast.makeText(this@MonthlyExpensesActivity, msg, Toast.LENGTH_SHORT).show()
                loadExpenses()
            } catch (e: Exception) {
                Toast.makeText(this@MonthlyExpensesActivity, e.message ?: "Failed to add", Toast.LENGTH_SHORT).show()
            } finally {
                binding.btnAddMonthlyExpense.isEnabled = true
            }
        }
    }

    private fun promptEditExpense(e: ExpenseRow) {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(12), dp(18), dp(8))
        }
        val etItem = EditText(this).apply { setText(e.item); hint = "Description" }
        val etPrice = EditText(this).apply {
            setText(e.unitPrice.toString())
            hint = "Unit Price ($)"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val etQty = EditText(this).apply {
            setText(numFmt.format(e.quantity))
            hint = "Qty"
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
        }
        val etPayer = EditText(this).apply { setText(e.paidBy); hint = "Paid By" }
        val etCat = EditText(this).apply { setText(e.category); hint = "Category" }
        col.addView(etItem); col.addView(etPrice); col.addView(etQty); col.addView(etPayer); col.addView(etCat)

        LiquidGlassDialog.builder(this)
            .setTitle("Edit Expense")
            .setView(col)
            .setPositiveButton("Save") { _, _ ->
                val newItem = etItem.text?.toString()?.trim().orEmpty()
                val newP = etPrice.text?.toString()?.toDoubleOrNull() ?: 0.0
                val newQ = etQty.text?.toString()?.toDoubleOrNull() ?: 1.0
                if (newItem.isNotBlank()) {
                    uiScope.launch {
                        try {
                            api.updateExpense(e.id, newItem, newP, newQ, etPayer.text.toString().trim(), etCat.text.toString().trim())
                            loadExpenses()
                        } catch (ex: Exception) {
                            Toast.makeText(this@MonthlyExpensesActivity, ex.message ?: "Update failed", Toast.LENGTH_SHORT).show()
                        }
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun confirmDeleteExpense(e: ExpenseRow) {
        LiquidGlassDialog.builder(this)
            .setTitle("Delete Expense")
            .setMessage("Delete '${e.item}' ($${moneyFmt.format(e.totalPrice)})?")
            .setPositiveButton("Delete") { _, _ ->
                uiScope.launch {
                    try {
                        api.deleteExpense(e.id)
                        loadExpenses()
                    } catch (ex: Exception) {
                        Toast.makeText(this@MonthlyExpensesActivity, ex.message ?: "Delete failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun promptAddOrEditAccount(existing: CashAccountRow?) {
        val d = currentData ?: return
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(12), dp(18), dp(8))
        }
        val etName = EditText(this).apply {
            hint = "Account name (e.g. ABA Bank)"
            setText(existing?.name.orEmpty())
            isEnabled = existing == null
        }
        val etAmt = EditText(this).apply {
            hint = "Amount ($)"
            setText(existing?.amount?.toString() ?: "")
            inputType = android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
            setSelectAllOnFocus(true)
        }
        col.addView(etName); col.addView(etAmt)

        LiquidGlassDialog.builder(this)
            .setTitle(if (existing == null) "Add Cash/Bank Account" else "Edit ${existing.name}")
            .setView(col)
            .setPositiveButton("Save") { _, _ ->
                val name = etName.text?.toString()?.trim().orEmpty()
                val amt = etAmt.text?.toString()?.toDoubleOrNull() ?: 0.0
                if (name.isBlank()) return@setPositiveButton
                val list = d.accounts.map { it.copy() }.toMutableList()
                val found = list.firstOrNull { it.name.equals(name, true) }
                if (found != null) found.amount = amt else list.add(CashAccountRow(name, amt, String.format(Locale.US, "%.2f", amt)))
                uiScope.launch {
                    try {
                        api.saveExpenseAccounts(selectedMonthKey, session.selectedBranch, list)
                        loadExpenses()
                    } catch (ex: Exception) {
                        Toast.makeText(this@MonthlyExpensesActivity, ex.message ?: "Save failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}
