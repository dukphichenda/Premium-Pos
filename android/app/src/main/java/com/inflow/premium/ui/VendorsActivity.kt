package com.inflow.premium.ui

import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.MainActivity
import com.inflow.premium.R
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.SessionManager
import com.inflow.premium.data.VendorItem
import com.inflow.premium.databinding.ActivityVendorsBinding
import com.inflow.premium.databinding.ItemVendorBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.text.DecimalFormat
import java.util.Locale

class VendorsActivity : AppCompatActivity() {

    private lateinit var binding: ActivityVendorsBinding
    private lateinit var session: SessionManager
    private lateinit var api: ApiClient
    private lateinit var adapter: VendorsAdapter
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private var currentFilter = "all"
    private var currentSearch = ""
    private var searchJob: Job? = null
    private val moneyFmt = DecimalFormat("#,##0.00")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(this)
        if (!session.isLoggedIn()) {
            finish()
            return
        }

        binding = ActivityVendorsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        api = ApiClient(session)

        BottomNavHelper.setup(this, binding.bottomNav.root, BottomNavHelper.NavTab.HOME)
        EdgeToEdgeHelper.apply(
            activity = this,
            rootView = binding.root,
            topContentView = null,
            topScrimView = binding.topScrim,
            bottomNavContainer = binding.bottomNav.root,
            bottomScrimView = binding.bottomScrim,
            scrollableView = binding.scrollVendors,
            extraTopDp = 10,
            extraBottomScrollDp = 120
        )

        adapter = VendorsAdapter(
            onDetailsOrPay = { v ->
                if (v.openPayable > 0.005) {
                    startActivity(
                        Intent(this, PurchaseOrdersActivity::class.java)
                    )
                } else {
                    openWebPath("/vendors")
                }
            },
            onNewPo = { v ->
                openWebPath("/purchases/new?vendor_id=${v.id}")
            }
        )
        binding.rvVendors.layoutManager = LinearLayoutManager(this)
        binding.rvVendors.adapter = adapter

        binding.btnVenBack.setOnClickListener { finish() }
        binding.btnAddVendor.setOnClickListener { promptAddVendor() }
        binding.swipeRefresh.setColorSchemeResources(R.color.primary, R.color.primary_dark)
        binding.swipeRefresh.setOnRefreshListener { loadVendors() }

        binding.pillVenAll.setOnClickListener { selectFilter("all") }
        binding.pillVenPayable.setOnClickListener { selectFilter("payable") }
        binding.pillVenCambodia.setOnClickListener { selectFilter("cambodia") }
        binding.pillVenRecent.setOnClickListener { selectFilter("recent") }

        binding.btnVenClearSearch.setOnClickListener { binding.etVenSearch.setText("") }
        binding.etVenSearch.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val raw = s?.toString().orEmpty()
                binding.btnVenClearSearch.visibility = if (raw.isEmpty()) View.GONE else View.VISIBLE
                val q = raw.trim()
                if (q == currentSearch) return
                currentSearch = q
                searchJob?.cancel()
                searchJob = uiScope.launch {
                    delay(280)
                    loadVendors()
                }
            }
        })

        loadVendors()
    }

    private fun openWebPath(path: String) {
        startActivity(
            Intent(this, MainActivity::class.java).putExtra("extra_url", api.buildWebPortalUrl(path))
        )
    }

    private fun selectFilter(flt: String) {
        if (currentFilter == flt) return
        currentFilter = flt
        val map = listOf(
            binding.pillVenAll to "all",
            binding.pillVenPayable to "payable",
            binding.pillVenCambodia to "cambodia",
            binding.pillVenRecent to "recent"
        )
        for ((tv, key) in map) {
            if (key == currentFilter) {
                tv.setBackgroundResource(R.drawable.bg_pill_teal_solid)
                tv.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#0B172A"))
                tv.setTextColor(Color.WHITE)
            } else {
                tv.setBackgroundResource(R.drawable.bg_floating_top_capsule)
                tv.backgroundTintList = null
                tv.setTextColor(Color.parseColor(if (key == "payable") "#DC2626" else "#334155"))
            }
        }
        loadVendors()
    }

    private fun formatCompactMoney(v: Double): String {
        return if (v >= 1_000_000.0) {
            String.format(Locale.US, "$%.1fM", v / 1_000_000.0)
        } else {
            "$${moneyFmt.format(v)}"
        }
    }

    private fun loadVendors() {
        binding.swipeRefresh.isRefreshing = true
        uiScope.launch {
            try {
                val res = api.getVendorsList(currentSearch, currentFilter)
                binding.tvVenTotalPurchased.text = formatCompactMoney(res.stats.totalPurchased)
                binding.tvVenTotalPoCount.text = "${res.stats.totalPoOrders} Total PO orders"
                binding.tvVenOpenPayable.text = "$${moneyFmt.format(res.stats.openPayable)}"
                binding.tvVenDueBadge.text = "${res.stats.dueCount} Due"
                binding.tvVenActiveCount.text = "From ${res.stats.totalVendors} active accounts"

                binding.pillVenAll.text = "All (${res.stats.totalVendors})"
                binding.pillVenPayable.text = "● Has Open Payable (${res.stats.dueCount})"

                adapter.submitList(res.vendors)
                binding.tvEmptyVendors.visibility = if (res.vendors.isEmpty()) View.VISIBLE else View.GONE
            } catch (e: Exception) {
                Toast.makeText(this@VendorsActivity, e.message ?: "Failed to load vendors", Toast.LENGTH_SHORT).show()
            } finally {
                binding.swipeRefresh.isRefreshing = false
            }
        }
    }

    private fun promptAddVendor() {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(12), dp(18), dp(8))
        }
        val etName = EditText(this).apply { hint = "Vendor Name *" }
        val etContact = EditText(this).apply { hint = "Contact Person" }
        val etPhone = EditText(this).apply { hint = "Phone Number"; inputType = android.text.InputType.TYPE_CLASS_PHONE }
        val etCountry = EditText(this).apply { hint = "Country"; setText("Cambodia") }
        val etCity = EditText(this).apply { hint = "City" }
        col.addView(etName); col.addView(etContact); col.addView(etPhone); col.addView(etCountry); col.addView(etCity)

        MaterialAlertDialogBuilder(this)
            .setTitle("Add New Vendor")
            .setView(col)
            .setPositiveButton("Create") { _, _ ->
                val name = etName.text?.toString()?.trim().orEmpty()
                if (name.isBlank()) {
                    Toast.makeText(this, "Vendor name required", Toast.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                uiScope.launch {
                    try {
                        val msg = api.createVendor(
                            name = name,
                            contactName = etContact.text.toString().trim(),
                            phone = etPhone.text.toString().trim(),
                            country = etCountry.text.toString().trim(),
                            city = etCity.text.toString().trim()
                        )
                        Toast.makeText(this@VendorsActivity, msg, Toast.LENGTH_SHORT).show()
                        loadVendors()
                    } catch (ex: Exception) {
                        Toast.makeText(this@VendorsActivity, ex.message ?: "Failed to create vendor", Toast.LENGTH_SHORT).show()
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

class VendorsAdapter(
    private val onDetailsOrPay: (VendorItem) -> Unit,
    private val onNewPo: (VendorItem) -> Unit
) : RecyclerView.Adapter<VendorsAdapter.VH>() {

    private val items = mutableListOf<VendorItem>()
    private val moneyFmt = DecimalFormat("#,##0.00")

    fun submitList(list: List<VendorItem>) {
        items.clear()
        items.addAll(list)
        notifyDataSetChanged()
    }

    class VH(val b: ItemVendorBinding) : RecyclerView.ViewHolder(b.root)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        return VH(ItemVendorBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val v = items[position]
        val b = holder.b
        val hasDue = v.openPayable > 0.005

        val words = v.name.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
        val initials = when {
            words.size >= 2 -> "${words[0].first()}${words[1].first()}".uppercase(Locale.US)
            words.size == 1 -> words[0].take(2).uppercase(Locale.US)
            else -> "VN"
        }
        b.tvVenInitials.text = initials
        b.tvVenName.text = v.name

        val metaParts = listOfNotNull(
            v.contactName.takeIf { it.isNotBlank() },
            v.country.takeIf { it.isNotBlank() },
            v.phone.takeIf { it.isNotBlank() }
        )
        b.tvVenContactMeta.text = metaParts.joinToString(" • ").ifBlank { "Supplier account" }

        b.tvVenPurchased.text = if (v.totalPurchased >= 1_000_000.0) {
            String.format(Locale.US, "Purchased: $%.1fM", v.totalPurchased / 1_000_000.0)
        } else {
            "Purchased: $${moneyFmt.format(v.totalPurchased)}"
        }
        b.tvVenOrderCount.text = "Orders: ${v.poCount} PO${if (v.poCount == 1) "" else "s"}"

        if (hasDue) {
            b.cardVendorRoot.strokeColor = Color.parseColor("#FCA5A5")
            b.tvVenInitials.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FFE4E6"))
            b.tvVenInitials.setTextColor(Color.parseColor("#BE123C"))
            b.tvVenStatusTag.visibility = View.VISIBLE
            b.tvVenStatusTag.text = "Pending"
            b.tvVenDueCaption.visibility = View.VISIBLE
            b.tvVenBalance.text = "$${moneyFmt.format(v.openPayable)}"
            b.tvVenBalance.setTextColor(Color.parseColor("#DC2626"))
            b.tvVenBalance.background = null
            b.btnVenDetailsOrPay.text = "Pay"
            b.btnVenDetailsOrPay.setBackgroundResource(R.drawable.bg_pill_slate_controls)
            b.btnVenDetailsOrPay.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#FFE4E6"))
            b.btnVenDetailsOrPay.setTextColor(Color.parseColor("#BE123C"))
        } else {
            b.cardVendorRoot.strokeColor = Color.parseColor("#E2E8F0")
            b.tvVenInitials.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#ECFDF5"))
            b.tvVenInitials.setTextColor(Color.parseColor("#0A6C62"))
            b.tvVenStatusTag.visibility = View.GONE
            b.tvVenDueCaption.visibility = View.GONE
            b.tvVenBalance.text = "$0.00"
            b.tvVenBalance.setTextColor(Color.parseColor("#059669"))
            b.tvVenBalance.setBackgroundResource(R.drawable.bg_pill_slate_controls)
            b.tvVenBalance.backgroundTintList = ColorStateList.valueOf(Color.parseColor("#ECFDF5"))
            b.tvVenBalance.setPadding(18, 4, 18, 4)
            b.btnVenDetailsOrPay.text = "Details"
            b.btnVenDetailsOrPay.setBackgroundResource(R.drawable.bg_product_thumb)
            b.btnVenDetailsOrPay.backgroundTintList = null
            b.btnVenDetailsOrPay.setTextColor(Color.parseColor("#334155"))
        }

        b.btnVenDetailsOrPay.setOnClickListener { onDetailsOrPay(v) }
        b.btnVenNewPo.setOnClickListener { onNewPo(v) }
        b.root.setOnClickListener { onDetailsOrPay(v) }
    }
}
