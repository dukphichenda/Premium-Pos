package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.StockAdjustmentSummary
import com.inflow.premium.data.TransferLocationOption
import com.inflow.premium.databinding.ActivityStockAdjustmentsBinding
import com.inflow.premium.databinding.ItemStockAdjustmentBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class StockAdjustmentsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityStockAdjustmentsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: StockAdjustmentsAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentStatus = "all"
    private var currentSearch = ""
    private var selectedLocationId: Int? = null
    private var locationOptions: List<TransferLocationOption> = emptyList()
    private var searchJob: Job? = null

    private val detailLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                loadAdjustments()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityStockAdjustmentsBinding.inflate(layoutInflater)
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
            scrollableView = binding.scrollAdjustments,
            extraTopDp = 6,
            extraBottomScrollDp = 120
        )

        adapter = StockAdjustmentsAdapter(
            onOpen = { adj -> openAdjustmentDetail(adj.id) },
            onDeleteDraft = { adj -> confirmDeleteDraft(adj) }
        )
        binding.rvAdjustments.layoutManager = LinearLayoutManager(this)
        binding.rvAdjustments.adapter = adapter

        binding.btnAdjBack.setOnClickListener { finish() }
        binding.btnNewAdjustment.setOnClickListener { openAdjustmentDetail(0) }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadAdjustments() }

        binding.tabAdjAll.setOnClickListener { selectStatus("all") }
        binding.tabAdjDraft.setOnClickListener { selectStatus("draft") }
        binding.tabAdjCompleted.setOnClickListener { selectStatus("completed") }

        binding.btnAdjWarehouseFilter.setOnClickListener { showWarehousePicker() }
        binding.tvAdjActiveWarehouse.setOnClickListener {
            selectedLocationId = null
            binding.tvAdjActiveWarehouse.visibility = View.GONE
            loadAdjustments()
        }

        binding.btnAdjClearSearch.setOnClickListener { binding.etAdjSearch.setText("") }
        binding.etAdjSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnAdjClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentSearch) return
                currentSearch = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(280)
                    loadAdjustments()
                }
            }
        })

        updateTabUi()
        loadAdjustments()
    }

    private fun openAdjustmentDetail(adjId: Int) {
        detailLauncher.launch(
            Intent(this, StockAdjustmentDetailActivity::class.java)
                .putExtra(StockAdjustmentDetailActivity.EXTRA_ADJUSTMENT_ID, adjId)
                .putExtra(StockAdjustmentDetailActivity.EXTRA_FROM_HISTORY, true)
        )
    }

    private fun selectStatus(status: String) {
        if (currentStatus == status) return
        currentStatus = status
        updateTabUi()
        loadAdjustments()
    }

    private fun updateTabUi() {
        val tabs = listOf(
            binding.tabAdjAll to "all",
            binding.tabAdjDraft to "draft",
            binding.tabAdjCompleted to "completed"
        )
        for ((tv, key) in tabs) {
            if (currentStatus == key) {
                tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
                tv.setTextColor(Color.parseColor("#0F172A"))
            } else {
                tv.background = null
                tv.setTextColor(Color.parseColor("#64748B"))
            }
        }
    }

    private fun showWarehousePicker() {
        if (locationOptions.isEmpty()) return
        val names = listOf("All Warehouses") + locationOptions.map { it.name }
        val checkedIdx = if (selectedLocationId == null) 0 else {
            (locationOptions.indexOfFirst { it.id == selectedLocationId } + 1).coerceAtLeast(0)
        }
        MaterialAlertDialogBuilder(this)
            .setTitle("Filter by Warehouse")
            .setSingleChoiceItems(names.toTypedArray(), checkedIdx) { dlg, which ->
                if (which == 0) {
                    selectedLocationId = null
                    binding.tvAdjActiveWarehouse.visibility = View.GONE
                } else {
                    val loc = locationOptions[which - 1]
                    selectedLocationId = loc.id
                    binding.tvAdjActiveWarehouse.text = "${loc.name}  ✕"
                    binding.tvAdjActiveWarehouse.visibility = View.VISIBLE
                }
                dlg.dismiss()
                loadAdjustments()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun confirmDeleteDraft(adj: StockAdjustmentSummary) {
        MaterialAlertDialogBuilder(this)
            .setTitle("Delete Draft Adjustment")
            .setMessage("Delete draft ${adj.adjustmentNumber}?")
            .setPositiveButton("Delete") { _, _ ->
                uiScope.launch {
                    try {
                        val msg = api.deleteAdjustment(adj.id)
                        Toast.makeText(this@StockAdjustmentsActivity, msg, Toast.LENGTH_SHORT).show()
                        loadAdjustments()
                    } catch (e: Exception) {
                        Toast.makeText(this@StockAdjustmentsActivity, e.message ?: "Delete failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun loadAdjustments() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getAdjustmentsList(currentStatus, currentSearch, selectedLocationId)
                locationOptions = res.locations
                binding.tvAdjRecordsBadge.text = "${res.stats.total} records"
                adapter.submitList(res.adjustments)
                binding.tvEmptyAdjustments.visibility = if (res.adjustments.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: Exception) {
                Toast.makeText(this@StockAdjustmentsActivity, e.message ?: "Failed to load adjustments", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        uiScope.cancel()
    }
}

class StockAdjustmentsAdapter(
    private val onOpen: (StockAdjustmentSummary) -> Unit,
    private val onDeleteDraft: (StockAdjustmentSummary) -> Unit
) : RecyclerView.Adapter<StockAdjustmentsAdapter.VH>() {

    private val items = mutableListOf<StockAdjustmentSummary>()

    fun submitList(list: List<StockAdjustmentSummary>) {
        items.clear()
        items.addAll(list)
        notifyDataSetChanged()
    }

    class VH(val b: ItemStockAdjustmentBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(ItemStockAdjustmentBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val adj = items[position]
        val b = holder.b
        val isDraft = adj.status.equals("DRAFT", ignoreCase = true)

        b.tvAdjNumber.text = adj.adjustmentNumber
        b.tvAdjMetaDateLoc.text = "🕒 ${adj.adjustmentDate}  •  ${adj.locationName}"
        b.tvAdjReasonChip.text = adj.reason.ifBlank { "Correction" }
        b.tvAdjItemCountChip.text = "${adj.itemCount} items"

        if (isDraft) {
            b.tvAdjStatusBadge.text = "DRAFT"
            b.tvAdjStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            b.tvAdjStatusBadge.setTextColor(Color.parseColor("#B45309"))
            b.tvAdjItemCountChip.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            b.tvAdjItemCountChip.setTextColor(Color.parseColor("#B45309"))
        } else {
            b.tvAdjStatusBadge.text = "DONE"
            b.tvAdjStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            b.tvAdjStatusBadge.setTextColor(Color.parseColor("#047857"))
            b.tvAdjItemCountChip.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#ECFDF5"))
            b.tvAdjItemCountChip.setTextColor(Color.parseColor("#047857"))
        }

        b.cardAdjRow.setOnClickListener { onOpen(adj) }
        b.cardAdjRow.setOnLongClickListener {
            if (isDraft) {
                onDeleteDraft(adj)
                true
            } else {
                false
            }
        }
    }
}
