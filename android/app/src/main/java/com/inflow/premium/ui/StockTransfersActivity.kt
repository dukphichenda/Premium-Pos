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
import com.inflow.premium.data.StockTransferSummary
import com.inflow.premium.data.TransferLocationOption
import com.inflow.premium.databinding.ActivityStockTransfersBinding
import com.inflow.premium.databinding.ItemStockTransferBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat

class StockTransfersActivity : AppCompatActivity() {

    private lateinit var binding: ActivityStockTransfersBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: StockTransfersAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentStatus = "all"
    private var currentSearch = ""
    private var selectedWarehouseId: Int? = null
    private var locationOptions: List<TransferLocationOption> = emptyList()
    private var searchJob: Job? = null

    private val detailLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                loadTransfers()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityStockTransfersBinding.inflate(layoutInflater)
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
            scrollableView = binding.scrollTransfers,
            extraTopDp = 6,
            extraBottomScrollDp = 120
        )

        adapter = StockTransfersAdapter(
            onOpen = { trf -> openTransferDetail(trf.id) },
            onDeleteDraft = { trf -> confirmDeleteDraft(trf) }
        )
        binding.rvTransfers.layoutManager = LinearLayoutManager(this)
        binding.rvTransfers.adapter = adapter

        binding.btnTrfBack.setOnClickListener { finish() }
        binding.btnNewTransfer.setOnClickListener { openTransferDetail(0) }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadTransfers() }

        binding.pillTrfAll.setOnClickListener { selectStatus("all") }
        binding.pillTrfDraft.setOnClickListener { selectStatus("draft") }
        binding.pillTrfCompleted.setOnClickListener { selectStatus("completed") }
        binding.btnWarehouseFilter.setOnClickListener { showWarehousePicker() }

        binding.btnTrfClearSearch.setOnClickListener { binding.etTrfSearch.setText("") }
        binding.etTrfSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnTrfClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentSearch) return
                currentSearch = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(300)
                    loadTransfers()
                }
            }
        })

        loadTransfers()
    }

    private fun openTransferDetail(trfId: Int) {
        detailLauncher.launch(
            Intent(this, StockTransferDetailActivity::class.java)
                .putExtra(StockTransferDetailActivity.EXTRA_TRANSFER_ID, trfId)
        )
    }

    private fun selectStatus(st: String) {
        if (currentStatus == st) return
        currentStatus = st
        updateFilterPillsUi()
        loadTransfers()
    }

    private fun updateFilterPillsUi() {
        val pills = listOf(
            binding.pillTrfAll to "all",
            binding.pillTrfDraft to "draft",
            binding.pillTrfCompleted to "completed"
        )
        for ((tv, key) in pills) {
            if (currentStatus == key) {
                tv.setBackgroundResource(R.drawable.bg_pill_teal_solid)
                tv.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0B172A"))
                tv.setTextColor(Color.WHITE)
            } else {
                tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
                tv.backgroundTintList = null
                tv.setTextColor(Color.parseColor("#334155"))
            }
        }
    }

    private fun showWarehousePicker() {
        if (locationOptions.isEmpty()) return
        val names = listOf("All Warehouses") + locationOptions.map { it.name }
        val checkedIdx = if (selectedWarehouseId == null) 0 else {
            (locationOptions.indexOfFirst { it.id == selectedWarehouseId } + 1).coerceAtLeast(0)
        }
        MaterialAlertDialogBuilder(this)
            .setTitle("Warehouse Route")
            .setSingleChoiceItems(names.toTypedArray(), checkedIdx) { dlg, which ->
                if (which == 0) {
                    selectedWarehouseId = null
                    binding.tvSelectedWarehouseFilter.text = "All Warehouses ⌄"
                } else {
                    val loc = locationOptions[which - 1]
                    selectedWarehouseId = loc.id
                    binding.tvSelectedWarehouseFilter.text = "${loc.name} ⌄"
                }
                dlg.dismiss()
                loadTransfers()
            }
            .setNegativeButton("Close") { d, _ -> d.dismiss() }
            .show()
    }

    private fun confirmDeleteDraft(trf: StockTransferSummary) {
        MaterialAlertDialogBuilder(this)
            .setTitle("Delete Draft Transfer")
            .setMessage("Delete draft ${trf.transferNumber}?")
            .setPositiveButton("Delete") { _, _ ->
                uiScope.launch {
                    try {
                        val msg = api.deleteTransfer(trf.id)
                        Toast.makeText(this@StockTransfersActivity, msg, Toast.LENGTH_SHORT).show()
                        loadTransfers()
                    } catch (e: Exception) {
                        Toast.makeText(this@StockTransfersActivity, e.message ?: "Delete failed", Toast.LENGTH_SHORT).show()
                    }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun loadTransfers() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getTransfersList(currentStatus, currentSearch, selectedWarehouseId)
                locationOptions = res.locations
                val numFmt = DecimalFormat("#,##0.##")

                binding.tvKpiTotalTransfers.text = res.stats.total.toString()
                binding.tvKpiDraftTransfers.text = res.stats.draft.toString()
                binding.tvKpiCompletedTransfers.text = res.stats.completed.toString()
                binding.tvKpiTotalUnits.text = numFmt.format(res.stats.totalUnits)

                binding.pillTrfAll.text = "All (${res.stats.total})"
                binding.pillTrfDraft.text = "Draft Requests (${res.stats.draft})"
                binding.pillTrfCompleted.text = "Completed (${res.stats.completed})"

                adapter.submitList(res.transfers)
                binding.tvEmptyTransfers.visibility = if (res.transfers.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: Exception) {
                Toast.makeText(this@StockTransfersActivity, e.message ?: "Failed to load transfers", Toast.LENGTH_SHORT).show()
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

class StockTransfersAdapter(
    private val onOpen: (StockTransferSummary) -> Unit,
    private val onDeleteDraft: (StockTransferSummary) -> Unit
) : RecyclerView.Adapter<StockTransfersAdapter.VH>() {

    private val items = mutableListOf<StockTransferSummary>()
    private val numFmt = DecimalFormat("#,##0.##")

    fun submitList(list: List<StockTransferSummary>) {
        items.clear()
        items.addAll(list)
        notifyDataSetChanged()
    }

    class VH(val b: ItemStockTransferBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(ItemStockTransferBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val trf = items[position]
        val b = holder.b
        val isCompleted = trf.status.equals("COMPLETED", ignoreCase = true)

        b.tvTrfNumber.text = trf.transferNumber
        b.tvTrfDate.text = "• ${trf.transferDate}"
        b.tvTrfSourceName.text = trf.fromLocationName
        b.tvTrfDestName.text = trf.toLocationName
        b.tvTrfItemCount.text = "${trf.itemCount} ITEMS"
        b.tvTrfUnitsCount.text = "${numFmt.format(trf.totalUnits)} pcs"

        if (isCompleted) {
            b.vTrfAccentBar.setBackgroundColor(Color.parseColor("#10B981"))
            b.tvTrfStatusBadge.text = "✓ DONE"
            b.tvTrfStatusBadge.setTextColor(Color.parseColor("#047857"))
            b.tvTrfStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#DCFCE7"))
            b.btnTrfDeleteDraft.visibility = View.GONE
            b.btnTrfPrimaryAction.text = "View 👁"
            b.btnTrfPrimaryAction.setBackgroundResource(R.drawable.bg_floating_top_capsule)
            b.btnTrfPrimaryAction.backgroundTintList = null
            b.btnTrfPrimaryAction.setTextColor(Color.parseColor("#0F172A"))
        } else {
            b.vTrfAccentBar.setBackgroundColor(Color.parseColor("#F59E0B"))
            b.tvTrfStatusBadge.text = "✏️ DRAFT"
            b.tvTrfStatusBadge.setTextColor(Color.parseColor("#B45309"))
            b.tvTrfStatusBadge.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FEF3C7"))
            b.btnTrfDeleteDraft.visibility = View.VISIBLE
            b.btnTrfDeleteDraft.setOnClickListener { onDeleteDraft(trf) }
            b.btnTrfPrimaryAction.text = "Edit / Complete →"
            b.btnTrfPrimaryAction.setBackgroundResource(R.drawable.bg_pill_teal_solid)
            b.btnTrfPrimaryAction.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0A6C62"))
            b.btnTrfPrimaryAction.setTextColor(Color.WHITE)
        }

        b.root.setOnClickListener { onOpen(trf) }
        b.btnTrfPrimaryAction.setOnClickListener { onOpen(trf) }
    }
}
