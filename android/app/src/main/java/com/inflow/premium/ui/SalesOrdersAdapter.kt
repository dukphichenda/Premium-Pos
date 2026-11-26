package com.inflow.premium.ui

import android.content.res.ColorStateList
import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.inflow.premium.R
import com.inflow.premium.data.SalesOrderSummary
import com.inflow.premium.databinding.ItemSalesOrderBinding
import java.util.Locale

class SalesOrdersAdapter(
    private val onClick: (SalesOrderSummary) -> Unit
) : RecyclerView.Adapter<SalesOrdersAdapter.VH>() {

    private val items = mutableListOf<SalesOrderSummary>()

    fun submitList(newItems: List<SalesOrderSummary>, append: Boolean = false) {
        if (!append) {
            items.clear()
        }
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val binding = ItemSalesOrderBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return VH(binding)
    }

    override fun onBindViewHolder(holder: VH, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class VH(private val binding: ItemSalesOrderBinding) : RecyclerView.ViewHolder(binding.root) {
        fun bind(item: SalesOrderSummary) {
            val ctx = binding.root.context
            binding.tvOrderNum.text = item.orderNumber
            binding.tvOrderDate.text = item.orderDateDisplay.ifBlank { item.orderDate }
            binding.tvCustomerName.text = item.customerName.ifBlank { "Walk-In Customer" }

            val itemWord = if (item.lineCount == 1) "item" else "items"
            val phonePart = if (item.customerPhone.isNotBlank()) " • ${item.customerPhone}" else ""
            val branchPart = if (item.branchName.isNotBlank()) " • ${item.branchName}" else ""
            binding.tvMetaLeft.text = "${item.lineCount} $itemWord$phonePart$branchPart"

            binding.tvTotalAmount.text = String.format(Locale.US, "$%.2f", item.totalAmount)

            val badgeText = item.fulfillmentBadge.ifBlank { item.status }
            binding.tvStatusBadge.text = badgeText

            val (fgColorRes, bgColorRes) = when {
                item.status.equals("Cancelled", ignoreCase = true) ->
                    R.color.cancel_red to R.color.cancel_red_bg
                item.paymentStatus.equals("Paid", ignoreCase = true) ||
                    item.status.equals("Fulfilled", ignoreCase = true) ||
                    badgeText.equals("Paid", ignoreCase = true) ->
                    R.color.paid_green to R.color.paid_green_bg
                else ->
                    R.color.open_orange to R.color.open_orange_bg
            }

            binding.tvStatusBadge.setTextColor(ContextCompat.getColor(ctx, fgColorRes))
            binding.tvStatusBadge.backgroundTintList =
                ColorStateList.valueOf(ContextCompat.getColor(ctx, bgColorRes))

            binding.root.setOnClickListener { onClick(item) }
        }
    }
}
