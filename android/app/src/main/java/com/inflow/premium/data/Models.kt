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
    val categoryName: String = "",
    val pricePerPcs: Double = unitPrice
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

data class ProductPriceTable(
    val catColor: String,
    val dimStr: String,
    val detailLines: List<String>,
    val tierQty1: Int,
    val tierQty2: Int,
    val tierQty3: Int,
    val uPrice1: Double,
    val uPrice2: Double,
    val uPrice3: Double,
    val totPrice1: Double,
    val totPrice2: Double,
    val totPrice3: Double
)

data class ProductBomComponent(
    val id: Int,
    val componentId: Int,
    val sku: String,
    val name: String,
    val uom: String,
    val quantity: Double,
    val unitCost: Double
)

data class ProductVendorItem(
    val id: Int,
    val name: String,
    val phone: String,
    val itemCode: String,
    val cost: Double
)

data class ProductOrderHistoryRow(
    val orderId: Int,
    val orderNumber: String,
    val orderDate: String,
    val status: String,
    val partyName: String,
    val quantity: Double,
    val uom: String,
    val totalAmount: Double
)

data class ProductMovementRow(
    val id: Int,
    val movementType: String,
    val quantity: Double,
    val createdAt: String,
    val referenceNumber: String,
    val fromLocation: String,
    val toLocation: String
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
    val pricingTiers: List<ProductPricingTier>,
    val priceTable: ProductPriceTable? = null,
    val boms: List<ProductBomComponent> = emptyList(),
    val vendors: List<ProductVendorItem> = emptyList(),
    val orderHistory: List<ProductOrderHistoryRow> = emptyList(),
    val purchaseHistory: List<ProductOrderHistoryRow> = emptyList(),
    val movementHistory: List<ProductMovementRow> = emptyList()
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

data class StockWarehouseQty(
    val id: Int,
    val name: String,
    val qty: Double
)

data class StockMatrixCategory(
    val id: Int,
    val name: String
)

data class StockMatrixItem(
    val id: Int,
    val sku: String,
    val name: String,
    val uom: String,
    val categoryName: String,
    val unitCost: Double,
    val totalQty: Double,
    val totalValue: Double,
    val warehouses: List<StockWarehouseQty>
)

data class StockMatrixResponse(
    val totalSkus: Int,
    val negativeCount: Int,
    val netValuation: Double,
    val warehouseCount: Int,
    val hasMore: Boolean,
    val categories: List<StockMatrixCategory>,
    val items: List<StockMatrixItem>
)

data class TransferLocationOption(
    val id: Int,
    val name: String,
    val isDefault: Boolean = false
)

data class StockTransferListStats(
    val total: Int,
    val draft: Int,
    val completed: Int,
    val totalUnits: Double
)

data class StockTransferSummary(
    val id: Int,
    val transferNumber: String,
    val transferDate: String,
    val transferDateIso: String,
    val status: String,
    val notes: String,
    val fromLocationId: Int,
    val fromLocationName: String,
    val toLocationId: Int,
    val toLocationName: String,
    val itemCount: Int,
    val totalUnits: Double
)

data class StockTransferListResult(
    val stats: StockTransferListStats,
    val locations: List<TransferLocationOption>,
    val transfers: List<StockTransferSummary>
)

data class StockTransferLine(
    val productId: Int,
    val sku: String,
    val name: String,
    val uom: String,
    val baseUom: String,
    val salesUom: String,
    val salesRatio: Double,
    val uomFactor: Double,
    var sourceOnHand: Double,
    var sourceAvailable: Double,
    var quantity: Double
)

data class StockTransferDetail(
    val id: Int,
    val transferNumber: String,
    val transferDate: String,
    val transferDateIso: String,
    val status: String,
    val fromLocationId: Int,
    val fromLocationName: String,
    val toLocationId: Int,
    val toLocationName: String,
    val notes: String,
    val locations: List<TransferLocationOption>,
    val lines: MutableList<StockTransferLine>
)

data class TransferCatalogProduct(
    val id: Int,
    val sku: String,
    val name: String,
    val uom: String,
    val salesUom: String,
    val salesRatio: Double,
    val sourceOnHand: Double,
    val sourceAvailable: Double
)

data class ExpenseMonthTab(
    val key: String,
    val label: String
)

data class ExpenseRow(
    val id: Int,
    val item: String,
    val category: String,
    val paidBy: String,
    val unitPrice: Double,
    val quantity: Double,
    val totalPrice: Double,
    val expenseDate: String,
    val expenseDateIso: String,
    val notes: String
)

data class CashAccountRow(
    var name: String,
    var amount: Double,
    var expr: String
)

data class MonthlyExpensesData(
    val monthKey: String,
    val monthDisplay: String,
    val prevMonthDisplay: String,
    val monthTabs: List<ExpenseMonthTab>,
    val totalExpenses: Double,
    val itemCount: Int,
    val openingBalance: Double,
    val isManualOpening: Boolean,
    val salesReceived: Double,
    val paidInvoiceCount: Int,
    val clearStm: Double,
    val clearSk: Double,
    val mediaTotal: Double,
    val mediaSheetTotal: Double,
    val moneyInHand: Double,
    val totalCountedCash: Double,
    val cashVariance: Double,
    val accounts: List<CashAccountRow>,
    val categories: List<String>,
    val payers: List<String>,
    val expenses: List<ExpenseRow>
)

data class VendorListStats(
    val totalVendors: Int,
    val totalPurchased: Double,
    val openPayable: Double,
    val dueCount: Int,
    val totalPoOrders: Int,
    val cambodiaCount: Int,
    val recentCount: Int
)

data class VendorItem(
    val id: Int,
    val name: String,
    val contactName: String,
    val phone: String,
    val email: String,
    val country: String,
    val city: String,
    val address1: String,
    val poCount: Int,
    val totalPurchased: Double,
    val openPayable: Double,
    val lastPoDate: String
)

data class VendorListResult(
    val stats: VendorListStats,
    val vendors: List<VendorItem>
)
