package com.inflow.premium.data

data class UserInfo(
    val id: Int,
    val username: String,
    val displayName: String,
    val role: String,
    val branchId: Int?,
    val isMainAdmin: Boolean
)

data class BranchItem(
    val id: String,
    val code: String,
    val name: String
)

data class PricingSchemeItem(
    val id: Int,
    val name: String
)

data class LocationItem(
    val id: Int,
    val name: String
)

data class DeliveryManItem(
    val id: Int,
    val name: String,
    val phone: String
)

data class OrderCounts(
    val total: Int = 0,
    val open: Int = 0,
    val paid: Int = 0,
    val cancelled: Int = 0
)

data class SalesOrderSummary(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val orderDateDisplay: String,
    val status: String,
    val paymentStatus: String,
    val fulfillmentBadge: String,
    val customerId: Int?,
    val customerName: String,
    val customerPhone: String,
    val customerAddress: String,
    val branchId: Int?,
    val branchName: String,
    val totalAmount: Double,
    val paidAmount: Double,
    val balanceDue: Double,
    val paymentMethod: String,
    val deliveryMan: String,
    val deliveryFeeKhr: Double,
    val lineCount: Int
)

data class OrderLineItem(
    val id: Int = 0,
    val productId: Int,
    val sku: String,
    val productName: String,
    var description: String = "",
    var quantity: Double = 1.0,
    var uom: String = "pcs.",
    val baseUom: String = "pcs.",
    val salesUom: String = "",
    val salesUomRatioStd: Double = 1.0,
    var unitPrice: Double = 0.0,
    var discountPercent: Double = 0.0,
    var pricingSchemeId: Int = 100
) {
    val subtotal: Double
        get() = (quantity * unitPrice) * (1.0 - (discountPercent / 100.0))
}

data class SalesOrderDetail(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val status: String,
    val paymentStatus: String,
    val isPaid: Boolean,
    val customerId: Int?,
    val customerName: String,
    val customerContact: String,
    val customerPhone: String,
    val customerAddress: String,
    val branchId: Int?,
    val branchName: String,
    val locationId: Int,
    val locationName: String,
    val pricingSchemeId: Int,
    val paymentMethod: String,
    val deliveryMan: String,
    val deliveryFeeKhr: Double,
    val notes: String,
    val totalAmount: Double,
    val paidAmount: Double,
    val balanceDue: Double,
    val khrRate: Double,
    val printUrl: String,
    val telegramUrl: String,
    val shareCaption: String,
    val lines: MutableList<OrderLineItem>
)

data class CustomerItem(
    val id: Int,
    val name: String,
    val contactName: String,
    val phone: String,
    val address: String,
    val defaultPricingSchemeId: Int,
    val branchId: Int?
)

data class ProductItem(
    val id: Int,
    val sku: String,
    val name: String,
    val uom: String,
    val salesUom: String,
    val salesUomRatioStd: Double,
    val unitPrice: Double,
    val defaultPrice: Double,
    val schemePrices: Map<String, Double>,
    val stockAvailable: Double
)
