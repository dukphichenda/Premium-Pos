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
    val labelPrintUrl: String = "",
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
    val stockAvailable: Double,
    val imageUrl: String = "",
    val barcode: String = "",
    val categoryName: String = ""
)

data class ProductCatalogResult(
    val products: List<ProductItem>,
    val totalCount: Int
)

data class ProductInventoryLocation(
    val locationId: Int,
    val locationName: String,
    val available: Double,
    val onHand: Double
)

data class ProductPricingTier(
    val schemeId: Int,
    val schemeName: String,
    val unitPrice: Double,
    val casePrice: Double,
    val marginPct: Double
)

data class ProductDetail(
    val id: Int,
    val sku: String,
    val name: String,
    val description: String,
    val barcode: String,
    val categoryName: String,
    val isActive: Boolean,
    val imageUrl: String,
    val uom: String,
    val salesUom: String,
    val salesUomRatioStd: Double,
    val purchasingUom: String,
    val defaultPrice: Double,
    val standardCost: Double,
    val defaultLocationName: String,
    val sublocation: String,
    val reorderPoint: Double,
    val reorderQty: Double,
    val length: Double,
    val width: Double,
    val height: Double,
    val totalOnHand: Double,
    val inventory: List<ProductInventoryLocation>,
    val pricingTiers: List<ProductPricingTier>
)

data class PurchaseOrderListItem(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val status: String,
    val paymentStatus: String,
    val total: Double,
    val vendorName: String,
    val isFulfilled: Boolean,
    val isPaid: Boolean
)

data class PurchaseOrderListResult(
    val orders: List<PurchaseOrderListItem>,
    val totalCount: Int
)

data class PurchaseOrderLine(
    val id: Int,
    val sku: String,
    val productName: String,
    val imageUrl: String,
    val quantity: Double,
    val uom: String,
    val unitPrice: Double,
    val subtotal: Double
)

data class PurchaseOrderDetail(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val status: String,
    val paymentStatus: String,
    val isFulfilled: Boolean,
    val isPaid: Boolean,
    val vendorName: String,
    val locationName: String,
    val assignedTo: String,
    val totalAmount: Double,
    val paidAmount: Double,
    val balanceDue: Double,
    val notes: String,
    val lines: List<PurchaseOrderLine>
)

data class CustomerCatalogItem(
    val id: Int,
    val name: String,
    val contactName: String,
    val phone: String,
    val address: String,
    val defaultPricingSchemeId: Int,
    val isActive: Boolean,
    val openBalance: Double
)

data class CustomerCatalogResult(
    val customers: List<CustomerCatalogItem>,
    val totalCount: Int,
    val totalDue: Double
)

data class CustomerOrderHistoryItem(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val status: String,
    val paymentStatus: String,
    val totalAmount: Double,
    val paidAmount: Double,
    val balanceDue: Double,
    val locationName: String,
    val itemsSummary: String,
    val totalQty: Double
)

data class CustomerDetail(
    val id: Int,
    val name: String,
    val contactName: String,
    val phone: String,
    val email: String,
    val address: String,
    val pricingSchemeName: String,
    val branchName: String,
    val paymentTerms: String,
    val notes: String,
    val isActive: Boolean,
    val createdAt: String,
    val totalSpent: Double,
    val openBalance: Double,
    val orders: List<CustomerOrderHistoryItem>
)

data class ProfitOrderItem(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val customerName: String,
    val paymentMethod: String,
    val isPaid: Boolean,
    val sales: Double,
    val cost: Double,
    val profit: Double
)

data class ProfitReportResult(
    val totalOrders: Int,
    val paidCount: Int,
    val totalSales: Double,
    val totalCost: Double,
    val grossProfit: Double,
    val marginPct: Double,
    val orders: List<ProfitOrderItem>
)

data class DeliveryOrderItem(
    val id: Int,
    val orderNumber: String,
    val orderDate: String,
    val totalAmount: Double,
    val isPaid: Boolean,
    val paymentMethod: String,
    val customerName: String,
    val phone: String,
    val address: String,
    var deliveryMan: String
)

data class DeliveryReportResult(
    val totalOrders: Int,
    val totalSales: Double,
    val assignedCount: Int,
    val unassignedCount: Int,
    val orders: List<DeliveryOrderItem>
)

data class BranchProductSummaryItem(
    val id: Int,
    val sku: String,
    val productName: String,
    val categoryName: String,
    val uom: String,
    val salesUom: String,
    val ratio: Double,
    val qtySold: Double,
    val salesAmount: Double,
    val branchCost: Double,
    val branchProfit: Double,
    val hqCost: Double,
    val hqEarning: Double
)

data class BranchSummaryReportResult(
    val totalSales: Double,
    val totalBranchCost: Double,
    val totalBranchProfit: Double,
    val totalHqCost: Double,
    val totalHqEarning: Double,
    val totalQty: Double,
    val items: List<BranchProductSummaryItem>
)

data class MonthlyChartPoint(
    val label: String,
    val monthLabel: String,
    val paidSales: Double,
    val openSales: Double,
    val profit: Double
)

data class CategoryStockSlice(
    val name: String,
    val value: Double,
    val pct: Double
)

data class DashboardSummary(
    val storeName: String,
    val storeBadge: String,
    val fulfillmentName: String,
    val activeBranchesCount: Int,
    val inventoryValuation: Double,
    val lowStockCount: Int,
    val pendingPurchaseOrders: Int,
    val monthSalesTotal: Double,
    val monthPaidTotal: Double,
    val totalReceivables: Double,
    val todayOrders: Int,
    val todayPaidTotal: Double,
    val paidCountToday: Int,
    val openCount: Int,
    val openAmount: Double,
    val totalOrders: Int,
    val totalProducts: Int,
    val khrRate: Double,
    val monthlyChart: List<MonthlyChartPoint>,
    val categoryStock: List<CategoryStockSlice>,
    val recentOrders: List<SalesOrderSummary>
)

data class PaymentBreakdownItem(
    val paymentMethod: String,
    val count: Int,
    val amount: Double
)

data class TopProductItem(
    val sku: String,
    val productName: String,
    val qty: Double,
    val amount: Double
)

data class ReportSummary(
    val dateFilter: String,
    val orderCount: Int,
    val paidCount: Int,
    val openCount: Int,
    val cancelledCount: Int,
    val grossSales: Double,
    val paidSales: Double,
    val openSales: Double,
    val deliveryFeesKhr: Double,
    val paymentBreakdown: List<PaymentBreakdownItem>,
    val topProducts: List<TopProductItem>
)
