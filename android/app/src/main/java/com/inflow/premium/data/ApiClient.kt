package com.inflow.premium.data

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ApiException(message: String, val statusCode: Int = 0) : Exception(message)

class ApiClient(private val session: SessionManager) {
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private suspend fun requestJson(method: String, path: String, query: Map<String, String> = emptyMap(), body: JSONObject? = null): JSONObject =
        withContext(Dispatchers.IO) {
            val base = (session.baseUrl + path).toHttpUrlOrNull()
                ?: throw ApiException("Invalid server URL: ${session.baseUrl}")
            val urlBuilder = base.newBuilder()
            query.forEach { (k, v) -> urlBuilder.addQueryParameter(k, v) }

            val reqBuilder = Request.Builder().url(urlBuilder.build())
            if (session.token.isNotBlank()) {
                reqBuilder.addHeader("Authorization", "Bearer ${session.token}")
            }
            reqBuilder.addHeader("Accept", "application/json")

            if (method == "POST") {
                val payload = (body ?: JSONObject()).toString().toRequestBody(jsonMedia)
                reqBuilder.post(payload)
            } else {
                reqBuilder.get()
            }

            client.newCall(reqBuilder.build()).execute().use { resp ->
                val raw = resp.body?.string() ?: "{}"
                val json = try {
                    JSONObject(raw)
                } catch (e: Exception) {
                    throw ApiException("Server error (${resp.code})", resp.code)
                }
                if (!resp.isSuccessful || !json.optBoolean("success", resp.isSuccessful)) {
                    val err = json.optString("error").ifBlank { json.optString("message").ifBlank { "Request failed (${resp.code})" } }
                    throw ApiException(err, resp.code)
                }
                json
            }
        }

    suspend fun login(username: String, password: String): JSONObject {
        val body = JSONObject().put("username", username).put("password", password)
        val res = requestJson("POST", "/api/mobile/login", body = body)
        session.token = res.optString("token", "")
        session.saveBootstrap(res)
        return res
    }

    suspend fun bootstrap(): JSONObject {
        val res = requestJson("GET", "/api/mobile/bootstrap")
        session.saveBootstrap(res)
        return res
    }

    data class SalesListResponse(
        val orders: List<SalesOrderSummary>,
        val counts: OrderCounts,
        val effectiveStatus: String,
        val hasMore: Boolean
    )

    suspend fun getSalesOrders(
        branch: String,
        status: String,
        dateFilter: String,
        search: String,
        page: Int
    ): SalesListResponse {
        val q = mutableMapOf(
            "branch" to branch,
            "status" to status,
            "date_filter" to dateFilter,
            "page" to page.toString(),
            "per_page" to "40"
        )
        if (search.isNotBlank()) q["search"] = search

        val json = requestJson("GET", "/api/mobile/sales", query = q)
        val arr = json.optJSONArray("orders") ?: JSONArray()
        val orders = mutableListOf<SalesOrderSummary>()
        for (i in 0 until arr.length()) {
            orders.add(parseOrderSummary(arr.getJSONObject(i)))
        }
        val cObj = json.optJSONObject("counts")
        val counts = if (cObj != null) {
            OrderCounts(
                total = cObj.optInt("total", 0),
                open = cObj.optInt("open", 0),
                paid = cObj.optInt("paid", 0),
                cancelled = cObj.optInt("cancelled", 0)
            )
        } else OrderCounts()

        return SalesListResponse(
            orders = orders,
            counts = counts,
            effectiveStatus = json.optString("effective_status", status),
            hasMore = json.optBoolean("has_more", false)
        )
    }

    suspend fun getSalesOrderDetail(orderId: Int): SalesOrderDetail {
        val json = requestJson("GET", "/api/mobile/sales/$orderId")
        val o = json.getJSONObject("order")
        val linesArr = json.optJSONArray("lines") ?: JSONArray()
        val lines = mutableListOf<OrderLineItem>()
        for (i in 0 until linesArr.length()) {
            val l = linesArr.getJSONObject(i)
            lines.add(
                OrderLineItem(
                    id = l.optInt("id", 0),
                    productId = l.optInt("product_id"),
                    sku = l.optString("product_sku", ""),
                    productName = l.optString("product_name", ""),
                    description = l.optString("description", ""),
                    quantity = l.optDouble("quantity", 1.0),
                    uom = l.optString("uom", "pcs."),
                    baseUom = l.optString("base_uom", "pcs."),
                    salesUom = l.optString("sales_uom", ""),
                    salesUomRatioStd = l.optDouble("sales_uom_ratio_std", 1.0),
                    unitPrice = l.optDouble("unit_price", 0.0),
                    discountPercent = l.optDouble("discount_percent", 0.0),
                    pricingSchemeId = l.optInt("pricing_scheme_id", 100)
                )
            )
        }

        return SalesOrderDetail(
            id = o.optInt("id"),
            orderNumber = o.optString("order_number", ""),
            orderDate = o.optString("order_date", ""),
            status = o.optString("status", "OPEN"),
            paymentStatus = o.optString("payment_status", "UNPAID"),
            isPaid = json.optBoolean("is_paid", false),
            customerId = if (o.isNull("customer_id")) null else o.optInt("customer_id"),
            customerName = o.optString("customer_name", ""),
            customerContact = o.optString("customer_contact", ""),
            customerPhone = o.optString("customer_phone", ""),
            customerAddress = o.optString("customer_address", ""),
            branchId = if (o.isNull("branch_id")) null else o.optInt("branch_id"),
            branchName = o.optString("branch_name", "Main Store (HQ)"),
            locationId = o.optInt("location_id", 100),
            locationName = o.optString("location_name", "Main Warehouse"),
            pricingSchemeId = o.optInt("pricing_scheme_id", 100),
            paymentMethod = o.optString("payment_method", "ABA Bank").ifBlank { "ABA Bank" },
            deliveryMan = o.optString("delivery_man", ""),
            deliveryFeeKhr = o.optDouble("delivery_fee_khr", 0.0),
            notes = o.optString("notes", ""),
            totalAmount = o.optDouble("total_amount", 0.0),
            paidAmount = o.optDouble("paid_amount", 0.0),
            balanceDue = o.optDouble("balance_due", 0.0),
            khrRate = json.optDouble("khr_rate", 4100.0),
            printUrl = json.optString("print_url", ""),
            labelPrintUrl = json.optString("label_print_url", ""),
            telegramUrl = json.optString("telegram_url", ""),
            shareCaption = json.optString("share_caption", ""),
            lines = lines
        )
    }

    suspend fun saveSalesOrder(
        orderId: Int,
        customerId: Int,
        branchId: Int?,
        locationId: Int,
        orderDate: String,
        pricingSchemeId: Int,
        contact: String,
        phone: String,
        address: String,
        deliveryMan: String,
        deliveryFeeKhr: Double,
        paymentMethod: String,
        notes: String,
        lines: List<OrderLineItem>,
        markCompletePay: Boolean = false
    ): JSONObject {
        val linesJson = JSONArray()
        for (l in lines) {
            linesJson.put(
                JSONObject()
                    .put("product_id", l.productId)
                    .put("description", l.description)
                    .put("quantity", l.quantity)
                    .put("unit_price", l.unitPrice)
                    .put("discount_percent", l.discountPercent)
                    .put("uom", l.uom)
                    .put("pricing_scheme_id", l.pricingSchemeId)
            )
        }
        val body = JSONObject()
            .put("customer_id", customerId)
            .put("branch_id", branchId?.toString() ?: "")
            .put("location_id", locationId)
            .put("order_date", orderDate)
            .put("pricing_scheme_id", pricingSchemeId)
            .put("customer_contact", contact)
            .put("customer_phone", phone)
            .put("customer_address", address)
            .put("delivery_man", deliveryMan)
            .put("delivery_fee_khr", deliveryFeeKhr)
            .put("payment_method", paymentMethod)
            .put("notes", notes)
            .put("lines", linesJson)
            .put("mark_complete_pay", if (markCompletePay) "1" else "0")

        val path = if (orderId > 0) "/api/mobile/sales/$orderId/save" else "/api/mobile/sales/save"
        return requestJson("POST", path, body = body)
    }

    suspend fun completePay(orderId: Int, paymentMethod: String): JSONObject {
        val body = JSONObject().put("payment_method", paymentMethod)
        return requestJson("POST", "/api/mobile/sales/$orderId/complete_pay", body = body)
    }

    suspend fun reopenOrder(orderId: Int): JSONObject =
        requestJson("POST", "/api/mobile/sales/$orderId/reopen", body = JSONObject())

    suspend fun cancelOrder(orderId: Int): JSONObject =
        requestJson("POST", "/api/mobile/sales/$orderId/cancel", body = JSONObject())

    suspend fun searchCustomers(query: String, branch: String): List<CustomerItem> {
        val json = requestJson("GET", "/api/mobile/customers", mapOf("q" to query, "branch" to branch, "limit" to "50"))
        val arr = json.optJSONArray("customers") ?: JSONArray()
        val list = mutableListOf<CustomerItem>()
        for (i in 0 until arr.length()) {
            val c = arr.getJSONObject(i)
            list.add(
                CustomerItem(
                    id = c.optInt("id"),
                    name = c.optString("name", ""),
                    contactName = c.optString("contact_name", ""),
                    phone = c.optString("phone", ""),
                    address = c.optString("address", ""),
                    defaultPricingSchemeId = c.optInt("default_pricing_scheme_id", 100),
                    branchId = if (c.isNull("branch_id")) null else c.optInt("branch_id")
                )
            )
        }
        return list
    }

    suspend fun quickAddCustomer(name: String, contactName: String, phone: String, address: String, branchId: Int?): CustomerItem {
        val body = JSONObject()
            .put("name", name)
            .put("contact_name", contactName)
            .put("phone", phone)
            .put("address", address)
            .put("branch_id", branchId?.toString() ?: "")
        val res = requestJson("POST", "/api/mobile/customers/quick-add", body = body)
        val c = res.getJSONObject("customer")
        return CustomerItem(
            id = c.optInt("id"),
            name = c.optString("name", ""),
            contactName = c.optString("contact_name", ""),
            phone = c.optString("phone", ""),
            address = c.optString("address", ""),
            defaultPricingSchemeId = c.optInt("default_pricing_scheme_id", 100),
            branchId = if (c.isNull("branch_id")) null else c.optInt("branch_id")
        )
    }

    suspend fun searchProducts(query: String, schemeId: Int, locationId: Int): List<ProductItem> {
        return searchProductsCatalog(query, schemeId, locationId).products
    }

    suspend fun searchProductsCatalog(query: String, schemeId: Int, locationId: Int): ProductCatalogResult {
        val json = requestJson(
            "GET",
            "/api/mobile/products",
            mapOf("q" to query, "scheme_id" to schemeId.toString(), "location_id" to locationId.toString(), "limit" to "50")
        )
        val arr = json.optJSONArray("products") ?: JSONArray()
        val list = mutableListOf<ProductItem>()
        for (i in 0 until arr.length()) {
            val p = arr.getJSONObject(i)
            val spObj = p.optJSONObject("scheme_prices")
            val spMap = mutableMapOf<String, Double>()
            if (spObj != null) {
                val keys = spObj.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    spMap[k] = spObj.optDouble(k, 0.0)
                }
            }
            list.add(
                ProductItem(
                    id = p.optInt("id"),
                    sku = p.optString("sku", ""),
                    name = p.optString("name", ""),
                    uom = p.optString("uom", "pcs."),
                    salesUom = p.optString("sales_uom", ""),
                    salesUomRatioStd = p.optDouble("sales_uom_ratio_std", 1.0),
                    unitPrice = p.optDouble("unit_price", 0.0),
                    defaultPrice = p.optDouble("default_price", 0.0),
                    schemePrices = spMap,
                    stockAvailable = p.optDouble("stock_available", 0.0),
                    imageUrl = p.optString("image_url", ""),
                    barcode = p.optString("barcode", ""),
                    categoryName = p.optString("category_name", "")
                )
            )
        }
        val total = json.optInt("total_count", list.size)
        return ProductCatalogResult(list, total)
    }

    suspend fun getProductDetail(productId: Int): ProductDetail {
        val json = requestJson("GET", "/api/mobile/products/$productId")
        val p = json.getJSONObject("product")
        val invArr = p.optJSONArray("inventory") ?: JSONArray()
        val invList = mutableListOf<ProductInventoryLocation>()
        for (i in 0 until invArr.length()) {
            val row = invArr.getJSONObject(i)
            invList.add(
                ProductInventoryLocation(
                    locationId = row.optInt("location_id"),
                    locationName = row.optString("location_name", "Warehouse"),
                    available = row.optDouble("available", 0.0),
                    onHand = row.optDouble("on_hand", 0.0)
                )
            )
        }
        val tierArr = p.optJSONArray("pricing_tiers") ?: JSONArray()
        val tierList = mutableListOf<ProductPricingTier>()
        for (i in 0 until tierArr.length()) {
            val row = tierArr.getJSONObject(i)
            tierList.add(
                ProductPricingTier(
                    schemeId = row.optInt("scheme_id"),
                    schemeName = row.optString("scheme_name", "Tier"),
                    unitPrice = row.optDouble("unit_price", 0.0),
                    casePrice = row.optDouble("case_price", 0.0),
                    marginPct = row.optDouble("margin_pct", 0.0)
                )
            )
        }
        return ProductDetail(
            id = p.optInt("id"),
            sku = p.optString("sku", ""),
            name = p.optString("name", ""),
            description = p.optString("description", ""),
            barcode = p.optString("barcode", ""),
            categoryName = p.optString("category_name", "Uncategorized"),
            isActive = p.optBoolean("is_active", true),
            imageUrl = p.optString("image_url", ""),
            uom = p.optString("uom", "pcs."),
            salesUom = p.optString("sales_uom", ""),
            salesUomRatioStd = p.optDouble("sales_uom_ratio_std", 1.0),
            purchasingUom = p.optString("purchasing_uom", ""),
            defaultPrice = p.optDouble("default_price", 0.0),
            standardCost = p.optDouble("standard_cost", 0.0),
            defaultLocationName = p.optString("default_location_name", "Main Warehouse"),
            sublocation = p.optString("sublocation", "Unassigned"),
            reorderPoint = p.optDouble("reorder_point", 0.0),
            reorderQty = p.optDouble("reorder_qty", 0.0),
            length = p.optDouble("length", 0.0),
            width = p.optDouble("width", 0.0),
            height = p.optDouble("height", 0.0),
            totalOnHand = p.optDouble("total_on_hand", 0.0),
            inventory = invList,
            pricingTiers = tierList
        )
    }

    private fun parseOrderSummary(o: JSONObject): SalesOrderSummary {
        return SalesOrderSummary(
            id = o.optInt("id"),
            orderNumber = o.optString("order_number", ""),
            orderDate = o.optString("order_date", ""),
            orderDateDisplay = o.optString("order_date_display", o.optString("order_date", "")),
            status = o.optString("status", "OPEN"),
            paymentStatus = o.optString("payment_status", "UNPAID"),
            fulfillmentBadge = o.optString("fulfillment_badge", "Open"),
            customerId = if (o.isNull("customer_id")) null else o.optInt("customer_id"),
            customerName = o.optString("customer_name", "No Customer"),
            customerPhone = o.optString("customer_phone", ""),
            customerAddress = o.optString("customer_address", ""),
            branchId = if (o.isNull("branch_id")) null else o.optInt("branch_id"),
            branchName = o.optString("branch_name", "Main Store (HQ)"),
            totalAmount = o.optDouble("total_amount", 0.0),
            paidAmount = o.optDouble("paid_amount", 0.0),
            balanceDue = o.optDouble("balance_due", 0.0),
            paymentMethod = o.optString("payment_method", ""),
            deliveryMan = o.optString("delivery_man", ""),
            deliveryFeeKhr = o.optDouble("delivery_fee_khr", 0.0),
            lineCount = o.optInt("line_count", 0)
        )
    }

    suspend fun getDashboard(branch: String): DashboardSummary {
        val json = requestJson("GET", "/api/mobile/dashboard", mapOf("branch" to branch))
        val arr = json.optJSONArray("recent_orders") ?: JSONArray()
        val recent = mutableListOf<SalesOrderSummary>()
        for (i in 0 until arr.length()) {
            recent.add(parseOrderSummary(arr.getJSONObject(i)))
        }
        val mArr = json.optJSONArray("monthly_chart") ?: JSONArray()
        val monthly = mutableListOf<MonthlyChartPoint>()
        for (i in 0 until mArr.length()) {
            val m = mArr.getJSONObject(i)
            monthly.add(
                MonthlyChartPoint(
                    label = m.optString("label", ""),
                    monthLabel = m.optString("month_label", ""),
                    paidSales = m.optDouble("paid_sales", 0.0),
                    openSales = m.optDouble("open_sales", 0.0),
                    profit = m.optDouble("profit", 0.0)
                )
            )
        }
        val cArr = json.optJSONArray("category_stock") ?: JSONArray()
        val categories = mutableListOf<CategoryStockSlice>()
        for (i in 0 until cArr.length()) {
            val c = cArr.getJSONObject(i)
            categories.add(
                CategoryStockSlice(
                    name = c.optString("name", "Other"),
                    value = c.optDouble("value", 0.0),
                    pct = c.optDouble("pct", 0.0)
                )
            )
        }
        return DashboardSummary(
            storeName = json.optString("store_name", "Main Store (HQ)"),
            storeBadge = json.optString("store_badge", "Enterprise HQ"),
            fulfillmentName = json.optString("fulfillment_name", "Main Warehouse"),
            activeBranchesCount = json.optInt("active_branches_count", 0),
            inventoryValuation = json.optDouble("inventory_valuation", 0.0),
            lowStockCount = json.optInt("low_stock_count", 0),
            pendingPurchaseOrders = json.optInt("pending_purchase_orders", 0),
            monthSalesTotal = json.optDouble("month_sales_total", 0.0),
            monthPaidTotal = json.optDouble("month_paid_total", 0.0),
            totalReceivables = json.optDouble("total_receivables", 0.0),
            todayOrders = json.optInt("today_orders", 0),
            todayPaidTotal = json.optDouble("today_paid_total", 0.0),
            paidCountToday = json.optInt("paid_count_today", 0),
            openCount = json.optInt("open_count", 0),
            openAmount = json.optDouble("open_amount", 0.0),
            totalOrders = json.optInt("total_orders", 0),
            totalProducts = json.optInt("total_products", 0),
            khrRate = json.optDouble("khr_rate", 4100.0),
            monthlyChart = monthly,
            categoryStock = categories,
            recentOrders = recent
        )
    }

    suspend fun getReportsSummary(branch: String, dateFilter: String): ReportSummary {
        val json = requestJson(
            "GET",
            "/api/mobile/reports/summary",
            mapOf("branch" to branch, "date_filter" to dateFilter)
        )
        val payArr = json.optJSONArray("payment_breakdown") ?: JSONArray()
        val payments = mutableListOf<PaymentBreakdownItem>()
        for (i in 0 until payArr.length()) {
            val p = payArr.getJSONObject(i)
            payments.add(
                PaymentBreakdownItem(
                    paymentMethod = p.optString("payment_method", "Unspecified"),
                    count = p.optInt("count", 0),
                    amount = p.optDouble("amount", 0.0)
                )
            )
        }
        val prodArr = json.optJSONArray("top_products") ?: JSONArray()
        val topProducts = mutableListOf<TopProductItem>()
        for (i in 0 until prodArr.length()) {
            val tp = prodArr.getJSONObject(i)
            topProducts.add(
                TopProductItem(
                    sku = tp.optString("sku", ""),
                    productName = tp.optString("product_name", "Item"),
                    qty = tp.optDouble("qty", 0.0),
                    amount = tp.optDouble("amount", 0.0)
                )
            )
        }
        return ReportSummary(
            dateFilter = json.optString("date_filter", dateFilter),
            orderCount = json.optInt("order_count", 0),
            paidCount = json.optInt("paid_count", 0),
            openCount = json.optInt("open_count", 0),
            cancelledCount = json.optInt("cancelled_count", 0),
            grossSales = json.optDouble("gross_sales", 0.0),
            paidSales = json.optDouble("paid_sales", 0.0),
            openSales = json.optDouble("open_sales", 0.0),
            deliveryFeesKhr = json.optDouble("delivery_fees_khr", 0.0),
            paymentBreakdown = payments,
            topProducts = topProducts
        )
    }

    fun buildWebPortalUrl(nextPath: String = "/"): String {
        val tok = session.token
        return if (tok.isNotBlank()) {
            "${session.baseUrl}/api/mobile/web-handoff?token=${Uri.encode(tok)}&next=${Uri.encode(nextPath)}"
        } else {
            "${session.baseUrl}$nextPath"
        }
    }
}
