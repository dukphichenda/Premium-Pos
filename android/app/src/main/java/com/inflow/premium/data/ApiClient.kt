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

    private fun parseDoubleMap(obj: JSONObject?): Map<String, Double> {
        if (obj == null) return emptyMap()
        val map = mutableMapOf<String, Double>()
        val keys = obj.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            map[k] = obj.optDouble(k, 0.0)
        }
        return map
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
                    pricingSchemeId = l.optInt("pricing_scheme_id", 100),
                    schemePricesPcs = parseDoubleMap(l.optJSONObject("scheme_prices_pcs"))
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

    suspend fun searchProductsCatalog(
        query: String,
        schemeId: Int,
        locationId: Int,
        categoryId: Int = 0,
        stockLevel: String = "all"
    ): ProductCatalogResult {
        val params = mutableMapOf(
            "q" to query,
            "scheme_id" to schemeId.toString(),
            "location_id" to locationId.toString(),
            "limit" to "60"
        )
        if (categoryId > 0) params["category_id"] = categoryId.toString()
        if (stockLevel != "all" && stockLevel.isNotBlank()) params["stock_level"] = stockLevel
        val json = requestJson("GET", "/api/mobile/products", params)
        val arr = json.optJSONArray("products") ?: JSONArray()
        val list = mutableListOf<ProductItem>()
        for (i in 0 until arr.length()) {
            val p = arr.getJSONObject(i)
            val spMap = parseDoubleMap(p.optJSONObject("scheme_prices"))
            val spPcsMap = parseDoubleMap(p.optJSONObject("scheme_prices_pcs"))
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
                    schemePricesPcs = spPcsMap,
                    stockAvailable = p.optDouble("stock_available", 0.0),
                    imageUrl = p.optString("image_url", ""),
                    barcode = p.optString("barcode", ""),
                    categoryName = p.optString("category_name", ""),
                    pricePerPcs = p.optDouble("price_per_pcs", p.optDouble("unit_price", 0.0))
                )
            )
        }
        val catArr = json.optJSONArray("categories") ?: JSONArray()
        val cats = mutableListOf<ProductCategoryOption>()
        for (i in 0 until catArr.length()) {
            val c = catArr.getJSONObject(i)
            cats.add(ProductCategoryOption(c.optInt("id"), c.optString("name", "")))
        }
        val total = json.optInt("total_count", list.size)
        return ProductCatalogResult(list, total, cats)
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
        val ptObj = p.optJSONObject("price_table")
        val priceTable = ptObj?.let {
            val dlArr = it.optJSONArray("detail_lines") ?: JSONArray()
            val dl = mutableListOf<String>()
            for (k in 0 until dlArr.length()) dl.add(dlArr.optString(k))
            ProductPriceTable(
                catColor = it.optString("cat_color", "#00A3E0"),
                dimStr = it.optString("dim_str", ""),
                detailLines = dl,
                tierQty1 = it.optInt("tier_qty_1", 100),
                tierQty2 = it.optInt("tier_qty_2", 400),
                tierQty3 = it.optInt("tier_qty_3", 800),
                uPrice1 = it.optDouble("u_price_1", 0.0),
                uPrice2 = it.optDouble("u_price_2", 0.0),
                uPrice3 = it.optDouble("u_price_3", 0.0),
                totPrice1 = it.optDouble("tot_price_1", 0.0),
                totPrice2 = it.optDouble("tot_price_2", 0.0),
                totPrice3 = it.optDouble("tot_price_3", 0.0)
            )
        }
        val bomsArr = p.optJSONArray("boms") ?: JSONArray()
        val boms = mutableListOf<ProductBomComponent>()
        for (i in 0 until bomsArr.length()) {
            val r = bomsArr.getJSONObject(i)
            boms.add(ProductBomComponent(r.optInt("id"), r.optInt("component_id"), r.optString("sku"), r.optString("name"), r.optString("uom", "pcs."), r.optDouble("quantity", 0.0), r.optDouble("unit_cost", 0.0)))
        }
        val vendArr = p.optJSONArray("vendors") ?: JSONArray()
        val vendors = mutableListOf<ProductVendorItem>()
        for (i in 0 until vendArr.length()) {
            val r = vendArr.getJSONObject(i)
            vendors.add(ProductVendorItem(r.optInt("id"), r.optString("name"), r.optString("phone"), r.optString("item_code"), r.optDouble("cost", 0.0)))
        }
        fun parseOrders(arrName: String): List<ProductOrderHistoryRow> {
            val arr = p.optJSONArray(arrName) ?: JSONArray()
            val out = mutableListOf<ProductOrderHistoryRow>()
            for (i in 0 until arr.length()) {
                val r = arr.getJSONObject(i)
                out.add(ProductOrderHistoryRow(r.optInt("order_id"), r.optString("order_number"), r.optString("order_date"), r.optString("status"), r.optString("party_name"), r.optDouble("quantity", 0.0), r.optString("uom", "pcs."), r.optDouble("total_amount", 0.0)))
            }
            return out
        }
        val movArr = p.optJSONArray("movement_history") ?: JSONArray()
        val movements = mutableListOf<ProductMovementRow>()
        for (i in 0 until movArr.length()) {
            val r = movArr.getJSONObject(i)
            movements.add(ProductMovementRow(r.optInt("id"), r.optString("movement_type"), r.optDouble("quantity", 0.0), r.optString("created_at"), r.optString("reference_number"), r.optString("from_location"), r.optString("to_location")))
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
            pricingTiers = tierList,
            priceTable = priceTable,
            boms = boms,
            vendors = vendors,
            orderHistory = parseOrders("order_history"),
            purchaseHistory = parseOrders("purchase_history"),
            movementHistory = movements
        )
    }

    suspend fun getPurchaseOrders(query: String, statusFilter: String): PurchaseOrderListResult {
        val json = requestJson(
            "GET",
            "/api/mobile/purchases",
            mapOf("q" to query, "status" to statusFilter, "limit" to "50")
        )
        val arr = json.optJSONArray("orders") ?: JSONArray()
        val list = mutableListOf<PurchaseOrderListItem>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                PurchaseOrderListItem(
                    id = o.optInt("id"),
                    orderNumber = o.optString("order_number", ""),
                    orderDate = o.optString("order_date", ""),
                    status = o.optString("status", "ISSUED"),
                    paymentStatus = o.optString("payment_status", "UNPAID"),
                    total = o.optDouble("total", 0.0),
                    vendorName = o.optString("vendor_name", "Vendor"),
                    isFulfilled = o.optBoolean("is_fulfilled", false),
                    isPaid = o.optBoolean("is_paid", false)
                )
            )
        }
        return PurchaseOrderListResult(list, json.optInt("total_count", list.size))
    }

    suspend fun getPurchaseOrderDetail(poId: Int): PurchaseOrderDetail {
        val json = requestJson("GET", "/api/mobile/purchases/$poId")
        val o = json.getJSONObject("order")
        val arr = o.optJSONArray("lines") ?: JSONArray()
        val lines = mutableListOf<PurchaseOrderLine>()
        for (i in 0 until arr.length()) {
            val l = arr.getJSONObject(i)
            lines.add(
                PurchaseOrderLine(
                    id = l.optInt("id"),
                    productId = l.optInt("product_id", 0),
                    sku = l.optString("sku", ""),
                    productName = l.optString("product_name", ""),
                    imageUrl = l.optString("image_url", ""),
                    quantity = l.optDouble("quantity", 0.0),
                    uom = l.optString("uom", "pcs."),
                    unitPrice = l.optDouble("unit_price", 0.0),
                    subtotal = l.optDouble("subtotal", 0.0)
                )
            )
        }
        val venArr = json.optJSONArray("vendors") ?: JSONArray()
        val vendors = mutableListOf<VendorOption>()
        for (i in 0 until venArr.length()) {
            val v = venArr.getJSONObject(i)
            vendors.add(VendorOption(v.optInt("id"), v.optString("name", "Vendor"), v.optString("phone", "")))
        }
        val locArr = json.optJSONArray("locations") ?: JSONArray()
        val locations = mutableListOf<TransferLocationOption>()
        for (i in 0 until locArr.length()) {
            val l = locArr.getJSONObject(i)
            locations.add(TransferLocationOption(l.optInt("id"), l.optString("name", "Warehouse"), l.optBoolean("is_default", false)))
        }
        return PurchaseOrderDetail(
            id = o.optInt("id"),
            orderNumber = o.optString("order_number", ""),
            orderDate = o.optString("order_date", ""),
            orderDateIso = o.optString("order_date_iso", ""),
            status = o.optString("status", "ISSUED"),
            paymentStatus = o.optString("payment_status", "UNPAID"),
            isFulfilled = o.optBoolean("is_fulfilled", false),
            isPaid = o.optBoolean("is_paid", false),
            vendorId = o.optInt("vendor_id", 0),
            vendorName = o.optString("vendor_name", "Vendor"),
            locationId = o.optInt("location_id", 100),
            locationName = o.optString("location_name", "Main Warehouse"),
            assignedTo = o.optString("assigned_to", "Admin"),
            totalAmount = o.optDouble("total_amount", 0.0),
            paidAmount = o.optDouble("paid_amount", 0.0),
            balanceDue = o.optDouble("balance_due", 0.0),
            notes = o.optString("notes", ""),
            lines = lines,
            vendors = vendors,
            locations = locations
        )
    }

    suspend fun savePurchaseOrder(
        poId: Int,
        orderNumber: String,
        vendorId: Int,
        locationId: Int,
        orderDateIso: String,
        status: String,
        paymentStatus: String,
        paidAmount: Double,
        notes: String,
        lines: List<PurchaseOrderLine>
    ): Pair<Int, String> {
        val lineArr = JSONArray()
        for (ln in lines) {
            lineArr.put(
                JSONObject().apply {
                    put("product_id", ln.productId)
                    put("product_name", ln.productName)
                    put("quantity", ln.quantity)
                    put("unit_cost", ln.unitPrice)
                    put("uom", ln.uom)
                }
            )
        }
        val body = JSONObject().apply {
            if (poId > 0) put("po_id", poId)
            put("order_number", orderNumber)
            put("vendor_id", vendorId)
            put("location_id", locationId)
            put("order_date", orderDateIso)
            put("status", status)
            put("payment_status", paymentStatus)
            put("paid_amount", paidAmount)
            put("notes", notes)
            put("lines", lineArr)
        }
        val json = requestJson("POST", "/api/mobile/purchases/save", body = body)
        return json.optInt("po_id", poId) to json.optString("message", "Purchase order saved")
    }

    suspend fun getCustomersCatalog(query: String, branchParam: String): CustomerCatalogResult {
        val json = requestJson(
            "GET",
            "/api/mobile/customers",
            mapOf("q" to query, "branch" to branchParam, "limit" to "60")
        )
        val arr = json.optJSONArray("customers") ?: JSONArray()
        val list = mutableListOf<CustomerCatalogItem>()
        for (i in 0 until arr.length()) {
            val c = arr.getJSONObject(i)
            list.add(
                CustomerCatalogItem(
                    id = c.optInt("id"),
                    name = c.optString("name", ""),
                    contactName = c.optString("contact_name", ""),
                    phone = c.optString("phone", ""),
                    address = c.optString("address", ""),
                    defaultPricingSchemeId = c.optInt("default_pricing_scheme_id", 100),
                    isActive = c.optBoolean("is_active", true),
                    openBalance = c.optDouble("open_balance", 0.0)
                )
            )
        }
        return CustomerCatalogResult(
            customers = list,
            totalCount = json.optInt("total_count", list.size),
            totalDue = json.optDouble("total_due", 0.0)
        )
    }

    suspend fun getCustomerDetail(customerId: Int): CustomerDetail {
        val json = requestJson("GET", "/api/mobile/customers/$customerId")
        val c = json.getJSONObject("customer")
        val arr = c.optJSONArray("orders") ?: JSONArray()
        val orders = mutableListOf<CustomerOrderHistoryItem>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            orders.add(
                CustomerOrderHistoryItem(
                    id = o.optInt("id"),
                    orderNumber = o.optString("order_number", ""),
                    orderDate = o.optString("order_date", ""),
                    status = o.optString("status", "OPEN"),
                    paymentStatus = o.optString("payment_status", "UNPAID"),
                    totalAmount = o.optDouble("total_amount", 0.0),
                    paidAmount = o.optDouble("paid_amount", 0.0),
                    balanceDue = o.optDouble("balance_due", 0.0),
                    locationName = o.optString("location_name", "Main Warehouse"),
                    itemsSummary = o.optString("items_summary", ""),
                    totalQty = o.optDouble("total_qty", 0.0)
                )
            )
        }
        return CustomerDetail(
            id = c.optInt("id"),
            name = c.optString("name", ""),
            contactName = c.optString("contact_name", ""),
            phone = c.optString("phone", ""),
            email = c.optString("email", ""),
            address = c.optString("address", ""),
            pricingSchemeName = c.optString("pricing_scheme_name", "Retail 1"),
            branchName = c.optString("branch_name", "Main Store (HQ)"),
            paymentTerms = c.optString("payment_terms", "Due on Receipt"),
            notes = c.optString("notes", ""),
            isActive = c.optBoolean("is_active", true),
            createdAt = c.optString("created_at", ""),
            totalSpent = c.optDouble("total_spent", 0.0),
            openBalance = c.optDouble("open_balance", 0.0),
            orders = orders
        )
    }

    suspend fun getProfitReport(branch: String, dateFilter: String, query: String): ProfitReportResult {
        val json = requestJson(
            "GET",
            "/api/mobile/reports/profit",
            mapOf("branch" to branch, "date_filter" to dateFilter, "q" to query)
        )
        val arr = json.optJSONArray("orders") ?: JSONArray()
        val list = mutableListOf<ProfitOrderItem>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                ProfitOrderItem(
                    id = o.optInt("id"),
                    orderNumber = o.optString("order_number", ""),
                    orderDate = o.optString("order_date", ""),
                    customerName = o.optString("customer_name", ""),
                    paymentMethod = o.optString("payment_method", "Cash"),
                    isPaid = o.optBoolean("is_paid", false),
                    sales = o.optDouble("sales", 0.0),
                    cost = o.optDouble("cost", 0.0),
                    profit = o.optDouble("profit", 0.0)
                )
            )
        }
        return ProfitReportResult(
            totalOrders = json.optInt("total_orders", list.size),
            paidCount = json.optInt("paid_count", 0),
            totalSales = json.optDouble("total_sales", 0.0),
            totalCost = json.optDouble("total_cost", 0.0),
            grossProfit = json.optDouble("gross_profit", 0.0),
            marginPct = json.optDouble("margin_pct", 0.0),
            orders = list
        )
    }

    suspend fun getDeliveryReport(branch: String, dateFilter: String, query: String): DeliveryReportResult {
        val json = requestJson(
            "GET",
            "/api/mobile/reports/delivery",
            mapOf("branch" to branch, "date_filter" to dateFilter, "q" to query)
        )
        val arr = json.optJSONArray("orders") ?: JSONArray()
        val list = mutableListOf<DeliveryOrderItem>()
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                DeliveryOrderItem(
                    id = o.optInt("id"),
                    orderNumber = o.optString("order_number", ""),
                    orderDate = o.optString("order_date", ""),
                    totalAmount = o.optDouble("total_amount", 0.0),
                    isPaid = o.optBoolean("is_paid", false),
                    paymentMethod = o.optString("payment_method", "Cash"),
                    customerName = o.optString("customer_name", ""),
                    phone = o.optString("phone", ""),
                    address = o.optString("address", ""),
                    deliveryMan = o.optString("delivery_man", "")
                )
            )
        }
        return DeliveryReportResult(
            totalOrders = json.optInt("total_orders", list.size),
            totalSales = json.optDouble("total_sales", 0.0),
            assignedCount = json.optInt("assigned_count", 0),
            unassignedCount = json.optInt("unassigned_count", 0),
            orders = list
        )
    }

    suspend fun assignDeliveryMan(orderId: Int, deliveryMan: String) {
        val body = JSONObject().apply {
            put("order_id", orderId)
            put("delivery_man", deliveryMan)
        }
        requestJson("POST", "/api/mobile/reports/delivery/assign", body = body)
    }

    suspend fun getBranchSummaryReport(branch: String, dateFilter: String, query: String, mode: String): BranchSummaryReportResult {
        val json = requestJson(
            "GET",
            "/api/mobile/reports/branch-summary",
            mapOf("branch" to branch, "date_filter" to dateFilter, "q" to query, "mode" to mode)
        )
        val arr = json.optJSONArray("items") ?: JSONArray()
        val list = mutableListOf<BranchProductSummaryItem>()
        for (i in 0 until arr.length()) {
            val it = arr.getJSONObject(i)
            list.add(
                BranchProductSummaryItem(
                    id = it.optInt("id"),
                    sku = it.optString("sku", ""),
                    productName = it.optString("product_name", ""),
                    categoryName = it.optString("category_name", "General"),
                    uom = it.optString("uom", "pcs."),
                    salesUom = it.optString("sales_uom", "case"),
                    ratio = it.optDouble("ratio", 1.0),
                    qtySold = it.optDouble("qty_sold", 0.0),
                    salesAmount = it.optDouble("sales_amount", 0.0),
                    branchCost = it.optDouble("branch_cost", 0.0),
                    branchProfit = it.optDouble("branch_profit", 0.0),
                    hqCost = it.optDouble("hq_cost", 0.0),
                    hqEarning = it.optDouble("hq_earning", 0.0)
                )
            )
        }
        return BranchSummaryReportResult(
            totalSales = json.optDouble("total_sales", 0.0),
            totalBranchCost = json.optDouble("total_branch_cost", 0.0),
            totalBranchProfit = json.optDouble("total_branch_profit", 0.0),
            totalHqCost = json.optDouble("total_hq_cost", 0.0),
            totalHqEarning = json.optDouble("total_hq_earning", 0.0),
            totalQty = json.optDouble("total_qty", 0.0),
            items = list
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
            storeLogoUrl = json.optString("store_logo_url", ""),
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

    suspend fun getStockMatrix(search: String, categoryId: Int?, page: Int = 1): StockMatrixResponse {
        val params = mutableMapOf("page" to page.toString())
        if (search.isNotBlank()) params["q"] = search
        if (categoryId != null && categoryId > 0) params["category_id"] = categoryId.toString()
        val json = requestJson("GET", "/api/mobile/stock-matrix", params)

        val catsArr = json.optJSONArray("categories") ?: JSONArray()
        val categories = mutableListOf<StockMatrixCategory>()
        for (i in 0 until catsArr.length()) {
            val c = catsArr.getJSONObject(i)
            categories.add(StockMatrixCategory(id = c.optInt("id"), name = c.optString("name", "")))
        }

        val itemsArr = json.optJSONArray("items") ?: JSONArray()
        val items = mutableListOf<StockMatrixItem>()
        for (i in 0 until itemsArr.length()) {
            val it = itemsArr.getJSONObject(i)
            val whArr = it.optJSONArray("warehouses") ?: JSONArray()
            val whList = mutableListOf<StockWarehouseQty>()
            for (j in 0 until whArr.length()) {
                val w = whArr.getJSONObject(j)
                whList.add(
                    StockWarehouseQty(
                        id = w.optInt("id"),
                        name = w.optString("name", ""),
                        qty = w.optDouble("qty", 0.0)
                    )
                )
            }
            items.add(
                StockMatrixItem(
                    id = it.optInt("id"),
                    sku = it.optString("sku", ""),
                    name = it.optString("name", ""),
                    uom = it.optString("uom", "pcs."),
                    categoryName = it.optString("category_name", "General"),
                    unitCost = it.optDouble("unit_cost", 0.0),
                    totalQty = it.optDouble("total_qty", 0.0),
                    totalValue = it.optDouble("total_value", 0.0),
                    warehouses = whList
                )
            )
        }

        return StockMatrixResponse(
            totalSkus = json.optInt("total_skus", 0),
            negativeCount = json.optInt("negative_count", 0),
            netValuation = json.optDouble("net_valuation", 0.0),
            warehouseCount = json.optInt("warehouse_count", 0),
            hasMore = json.optBoolean("has_more", false),
            categories = categories,
            items = items
        )
    }

    suspend fun getTransfersList(status: String, query: String, warehouseId: Int?): StockTransferListResult {
        val params = mutableMapOf("status" to status)
        if (query.isNotBlank()) params["q"] = query
        if (warehouseId != null && warehouseId > 0) params["warehouse_id"] = warehouseId.toString()
        val json = requestJson("GET", "/api/mobile/transfers", params)

        val stObj = json.optJSONObject("stats") ?: JSONObject()
        val stats = StockTransferListStats(
            total = stObj.optInt("total", 0),
            draft = stObj.optInt("draft", 0),
            completed = stObj.optInt("completed", 0),
            totalUnits = stObj.optDouble("total_units", 0.0)
        )

        val locsArr = json.optJSONArray("locations") ?: JSONArray()
        val locs = mutableListOf<TransferLocationOption>()
        for (i in 0 until locsArr.length()) {
            val l = locsArr.getJSONObject(i)
            locs.add(TransferLocationOption(l.optInt("id"), l.optString("name", ""), l.optBoolean("is_default", false)))
        }

        val trArr = json.optJSONArray("transfers") ?: JSONArray()
        val list = mutableListOf<StockTransferSummary>()
        for (i in 0 until trArr.length()) {
            val t = trArr.getJSONObject(i)
            list.add(
                StockTransferSummary(
                    id = t.optInt("id"),
                    transferNumber = t.optString("transfer_number", ""),
                    transferDate = t.optString("transfer_date", ""),
                    transferDateIso = t.optString("transfer_date_iso", ""),
                    status = t.optString("status", "DRAFT"),
                    notes = t.optString("notes", ""),
                    fromLocationId = t.optInt("from_location_id"),
                    fromLocationName = t.optString("from_location_name", ""),
                    toLocationId = t.optInt("to_location_id"),
                    toLocationName = t.optString("to_location_name", ""),
                    itemCount = t.optInt("item_count", 0),
                    totalUnits = t.optDouble("total_units", 0.0)
                )
            )
        }
        return StockTransferListResult(stats, locs, list)
    }

    suspend fun getTransferDetail(trfId: Int): StockTransferDetail {
        val json = requestJson("GET", "/api/mobile/transfers/$trfId")
        val locsArr = json.optJSONArray("locations") ?: JSONArray()
        val locs = mutableListOf<TransferLocationOption>()
        for (i in 0 until locsArr.length()) {
            val l = locsArr.getJSONObject(i)
            locs.add(TransferLocationOption(l.optInt("id"), l.optString("name", ""), l.optBoolean("is_default", false)))
        }
        val t = json.getJSONObject("transfer")
        val linesArr = t.optJSONArray("lines") ?: JSONArray()
        val lines = mutableListOf<StockTransferLine>()
        for (i in 0 until linesArr.length()) {
            val ln = linesArr.getJSONObject(i)
            lines.add(
                StockTransferLine(
                    productId = ln.optInt("product_id"),
                    sku = ln.optString("sku", ""),
                    name = ln.optString("name", ""),
                    uom = ln.optString("uom", "pcs."),
                    baseUom = ln.optString("base_uom", "pcs."),
                    salesUom = ln.optString("sales_uom", ""),
                    salesRatio = ln.optDouble("sales_ratio", 1.0),
                    uomFactor = ln.optDouble("uom_factor", 1.0),
                    sourceOnHand = ln.optDouble("source_on_hand", 0.0),
                    sourceAvailable = ln.optDouble("source_available", 0.0),
                    quantity = ln.optDouble("quantity", 1.0)
                )
            )
        }
        return StockTransferDetail(
            id = t.optInt("id", 0),
            transferNumber = t.optString("transfer_number", ""),
            transferDate = t.optString("transfer_date", ""),
            transferDateIso = t.optString("transfer_date_iso", ""),
            status = t.optString("status", "DRAFT"),
            fromLocationId = t.optInt("from_location_id"),
            fromLocationName = t.optString("from_location_name", ""),
            toLocationId = t.optInt("to_location_id"),
            toLocationName = t.optString("to_location_name", ""),
            notes = t.optString("notes", ""),
            locations = locs,
            lines = lines
        )
    }

    suspend fun searchTransferProducts(query: String, fromLocationId: Int): List<TransferCatalogProduct> {
        val json = requestJson(
            "GET",
            "/api/mobile/transfers/products-lookup",
            mapOf("q" to query, "from_location_id" to fromLocationId.toString())
        )
        val arr = json.optJSONArray("products") ?: JSONArray()
        val list = mutableListOf<TransferCatalogProduct>()
        for (i in 0 until arr.length()) {
            val p = arr.getJSONObject(i)
            list.add(
                TransferCatalogProduct(
                    id = p.optInt("id"),
                    sku = p.optString("sku", ""),
                    name = p.optString("name", ""),
                    uom = p.optString("uom", "pcs."),
                    salesUom = p.optString("sales_uom", ""),
                    salesRatio = p.optDouble("sales_ratio", 1.0),
                    sourceOnHand = p.optDouble("source_on_hand", 0.0),
                    sourceAvailable = p.optDouble("source_available", 0.0)
                )
            )
        }
        return list
    }

    suspend fun saveTransfer(
        transferId: Int,
        transferNumber: String,
        fromLocationId: Int,
        toLocationId: Int,
        transferDateIso: String,
        notes: String,
        status: String,
        lines: List<StockTransferLine>
    ): Pair<Int, String> {
        val lineArr = JSONArray()
        for (ln in lines) {
            lineArr.put(
                JSONObject().apply {
                    put("product_id", ln.productId)
                    put("quantity", ln.quantity)
                    put("uom", ln.uom)
                    put("uom_factor", ln.uomFactor)
                    put("source_on_hand", ln.sourceOnHand)
                    put("source_available", ln.sourceAvailable)
                }
            )
        }
        val body = JSONObject().apply {
            if (transferId > 0) put("transfer_id", transferId)
            put("transfer_number", transferNumber)
            put("from_location_id", fromLocationId)
            put("to_location_id", toLocationId)
            put("transfer_date_iso", transferDateIso)
            put("notes", notes)
            put("status", status)
            put("lines", lineArr)
        }
        val json = requestJson("POST", "/api/mobile/transfers/save", body = body)
        return json.optInt("transfer_id", transferId) to json.optString("message", "Saved")
    }

    suspend fun deleteTransfer(trfId: Int): String {
        val json = requestJson("POST", "/api/mobile/transfers/$trfId/delete", body = JSONObject())
        return json.optString("message", "Deleted")
    }

    suspend fun getAdjustmentsList(
        status: String = "all",
        query: String = "",
        locationId: Int? = null
    ): StockAdjustmentListResult {
        val params = mutableMapOf("status" to status, "q" to query)
        if (locationId != null && locationId > 0) {
            params["location_id"] = locationId.toString()
        }
        val json = requestJson("GET", "/api/mobile/adjustments", params)
        val statsObj = json.optJSONObject("stats") ?: JSONObject()
        val stats = StockAdjustmentStats(
            total = statsObj.optInt("total", 0),
            draft = statsObj.optInt("draft", 0),
            completed = statsObj.optInt("completed", 0)
        )
        val locsArr = json.optJSONArray("locations") ?: JSONArray()
        val locs = mutableListOf<TransferLocationOption>()
        for (i in 0 until locsArr.length()) {
            val l = locsArr.getJSONObject(i)
            locs.add(TransferLocationOption(l.optInt("id"), l.optString("name", ""), l.optBoolean("is_default", false)))
        }
        val arr = json.optJSONArray("adjustments") ?: JSONArray()
        val list = mutableListOf<StockAdjustmentSummary>()
        for (i in 0 until arr.length()) {
            val a = arr.getJSONObject(i)
            list.add(
                StockAdjustmentSummary(
                    id = a.optInt("id"),
                    adjustmentNumber = a.optString("adjustment_number", ""),
                    adjustmentDate = a.optString("adjustment_date", ""),
                    adjustmentDateIso = a.optString("adjustment_date_iso", ""),
                    status = a.optString("status", "COMPLETED"),
                    reason = a.optString("reason", "Correction"),
                    notes = a.optString("notes", ""),
                    locationId = a.optInt("location_id"),
                    locationName = a.optString("location_name", ""),
                    createdBy = a.optString("created_by", ""),
                    itemCount = a.optInt("item_count", 0),
                    netChangeUnits = a.optDouble("net_change_units", 0.0)
                )
            )
        }
        return StockAdjustmentListResult(stats, locs, list)
    }

    suspend fun getAdjustmentDetail(adjId: Int): StockAdjustmentDetail {
        val json = requestJson("GET", "/api/mobile/adjustments/$adjId")
        val locsArr = json.optJSONArray("locations") ?: JSONArray()
        val locs = mutableListOf<TransferLocationOption>()
        for (i in 0 until locsArr.length()) {
            val l = locsArr.getJSONObject(i)
            locs.add(TransferLocationOption(l.optInt("id"), l.optString("name", ""), l.optBoolean("is_default", false)))
        }
        val catsArr = json.optJSONArray("categories") ?: JSONArray()
        val cats = mutableListOf<AdjustmentCategoryOption>()
        for (i in 0 until catsArr.length()) {
            val c = catsArr.getJSONObject(i)
            cats.add(AdjustmentCategoryOption(c.optInt("id"), c.optString("name", ""), c.optInt("product_count", 0)))
        }
        val a = json.getJSONObject("adjustment")
        val linesArr = a.optJSONArray("lines") ?: JSONArray()
        val lines = mutableListOf<StockAdjustmentLine>()
        for (i in 0 until linesArr.length()) {
            val ln = linesArr.getJSONObject(i)
            lines.add(
                StockAdjustmentLine(
                    productId = ln.optInt("product_id"),
                    sku = ln.optString("sku", ""),
                    name = ln.optString("name", ""),
                    uom = ln.optString("uom", "pcs."),
                    baseUom = ln.optString("base_uom", "pcs."),
                    salesUom = ln.optString("sales_uom", ""),
                    salesRatio = ln.optDouble("sales_ratio", 1.0),
                    uomFactor = ln.optDouble("uom_factor", 1.0),
                    imageUrl = ln.optString("image_url", ""),
                    sublocation = ln.optString("sublocation", ""),
                    oldQty = ln.optDouble("old_qty", 0.0),
                    diffQty = ln.optDouble("diff_qty", 0.0),
                    newQty = ln.optDouble("new_qty", 0.0),
                    onHandQty = ln.optDouble("on_hand_qty", 0.0),
                    reservedQty = ln.optDouble("reserved_qty", 0.0)
                )
            )
        }
        return StockAdjustmentDetail(
            id = a.optInt("id", 0),
            adjustmentNumber = a.optString("adjustment_number", ""),
            adjustmentDate = a.optString("adjustment_date", ""),
            adjustmentDateIso = a.optString("adjustment_date_iso", ""),
            status = a.optString("status", "DRAFT"),
            locationId = a.optInt("location_id"),
            locationName = a.optString("location_name", ""),
            auditor = a.optString("auditor", ""),
            refDoc = a.optString("ref_doc", ""),
            auditDept = a.optString("audit_dept", ""),
            reason = a.optString("reason", "Correction"),
            notes = a.optString("notes", ""),
            itemsChanged = a.optInt("items_changed", lines.size),
            netChangeUnits = a.optDouble("net_change_units", 0.0),
            totalActiveProducts = json.optInt("total_active_products", 0),
            locations = locs,
            categories = cats,
            lines = lines
        )
    }

    suspend fun searchAdjustmentProducts(
        query: String,
        locationId: Int,
        categoryIds: List<Int> = emptyList(),
        fetchAll: Boolean = false,
        sortBy: String = ""
    ): List<AdjustmentCatalogProduct> {
        val params = mutableMapOf(
            "q" to query,
            "location_id" to locationId.toString()
        )
        if (categoryIds.isNotEmpty()) {
            params["category_ids"] = categoryIds.joinToString(",")
        }
        if (fetchAll) {
            params["all"] = "true"
        }
        if (sortBy.isNotBlank()) {
            params["sort_by"] = sortBy
        }
        val json = requestJson("GET", "/api/mobile/adjustments/products-lookup", params)
        val arr = json.optJSONArray("products") ?: JSONArray()
        val list = mutableListOf<AdjustmentCatalogProduct>()
        for (i in 0 until arr.length()) {
            val p = arr.getJSONObject(i)
            list.add(
                AdjustmentCatalogProduct(
                    id = p.optInt("id"),
                    sku = p.optString("sku", ""),
                    name = p.optString("name", ""),
                    uom = p.optString("uom", "pcs."),
                    salesUom = p.optString("sales_uom", ""),
                    salesRatio = p.optDouble("sales_ratio", 1.0),
                    imageUrl = p.optString("image_url", ""),
                    categoryName = p.optString("category_name", "General"),
                    onHandQty = p.optDouble("on_hand_qty", 0.0),
                    reservedQty = p.optDouble("reserved_qty", 0.0),
                    sublocation = p.optString("sublocation", "")
                )
            )
        }
        return list
    }

    suspend fun saveAdjustment(
        adjustmentId: Int,
        adjustmentNumber: String,
        locationId: Int,
        adjustmentDateIso: String,
        reason: String,
        notes: String,
        auditor: String,
        refDoc: String,
        auditDept: String,
        status: String,
        lines: List<StockAdjustmentLine>
    ): Pair<Int, String> {
        val lineArr = JSONArray()
        for (ln in lines) {
            lineArr.put(
                JSONObject().apply {
                    put("product_id", ln.productId)
                    put("uom", ln.uom)
                    put("uom_factor", ln.uomFactor)
                    put("sublocation", ln.sublocation)
                    put("change_qty", ln.diffQty)
                    put("final_qty", ln.newQty)
                    put("reserved_qty", ln.reservedQty)
                    put("reserved_edited", ln.reservedEdited)
                }
            )
        }
        val body = JSONObject().apply {
            if (adjustmentId > 0) put("adjustment_id", adjustmentId)
            put("adjustment_number", adjustmentNumber)
            put("location_id", locationId)
            put("adjustment_date_iso", adjustmentDateIso)
            put("reason", reason)
            put("notes", notes)
            put("auditor", auditor)
            put("ref_doc", refDoc)
            put("audit_dept", auditDept)
            put("status", status)
            put("lines", lineArr)
        }
        val json = requestJson("POST", "/api/mobile/adjustments/save", body = body)
        return json.optInt("adjustment_id", adjustmentId) to json.optString("message", "Saved")
    }

    suspend fun deleteAdjustment(adjId: Int): String {
        val json = requestJson("POST", "/api/mobile/adjustments/$adjId/delete", body = JSONObject())
        return json.optString("message", "Deleted")
    }

    suspend fun getMonthlyExpenses(monthKey: String, branch: String): MonthlyExpensesData {
        val params = mutableMapOf("branch" to branch)
        if (monthKey.isNotBlank()) params["month"] = monthKey
        val json = requestJson("GET", "/api/mobile/expenses/monthly", params)

        val tabsArr = json.optJSONArray("month_tabs") ?: JSONArray()
        val tabs = mutableListOf<ExpenseMonthTab>()
        for (i in 0 until tabsArr.length()) {
            val t = tabsArr.getJSONObject(i)
            tabs.add(ExpenseMonthTab(t.optString("key", ""), t.optString("label", "")))
        }

        val accArr = json.optJSONArray("accounts") ?: JSONArray()
        val accounts = mutableListOf<CashAccountRow>()
        for (i in 0 until accArr.length()) {
            val a = accArr.getJSONObject(i)
            accounts.add(CashAccountRow(a.optString("name", ""), a.optDouble("amount", 0.0), a.optString("expr", "0.00")))
        }

        val catsArr = json.optJSONArray("categories") ?: JSONArray()
        val cats = mutableListOf<String>()
        for (i in 0 until catsArr.length()) cats.add(catsArr.optString(i, ""))

        val payersArr = json.optJSONArray("payers") ?: JSONArray()
        val payers = mutableListOf<String>()
        for (i in 0 until payersArr.length()) payers.add(payersArr.optString(i, ""))

        val expArr = json.optJSONArray("expenses") ?: JSONArray()
        val exps = mutableListOf<ExpenseRow>()
        for (i in 0 until expArr.length()) {
            val e = expArr.getJSONObject(i)
            exps.add(
                ExpenseRow(
                    id = e.optInt("id"),
                    item = e.optString("item", ""),
                    category = e.optString("category", "General"),
                    paidBy = e.optString("paid_by", ""),
                    unitPrice = e.optDouble("unit_price", 0.0),
                    quantity = e.optDouble("quantity", 1.0),
                    totalPrice = e.optDouble("total_price", 0.0),
                    expenseDate = e.optString("expense_date", ""),
                    expenseDateIso = e.optString("expense_date_iso", ""),
                    notes = e.optString("notes", "")
                )
            )
        }

        return MonthlyExpensesData(
            monthKey = json.optString("month_key", ""),
            monthDisplay = json.optString("month_display", ""),
            prevMonthDisplay = json.optString("prev_month_display", ""),
            monthTabs = tabs,
            totalExpenses = json.optDouble("total_expenses", 0.0),
            itemCount = json.optInt("item_count", exps.size),
            openingBalance = json.optDouble("opening_balance", 0.0),
            isManualOpening = json.optBoolean("is_manual_opening", false),
            salesReceived = json.optDouble("sales_received", 0.0),
            paidInvoiceCount = json.optInt("paid_invoice_count", 0),
            clearStm = json.optDouble("clear_stm", 0.0),
            clearSk = json.optDouble("clear_sk", 0.0),
            mediaTotal = json.optDouble("media_total", 0.0),
            mediaSheetTotal = json.optDouble("media_sheet_total", 0.0),
            moneyInHand = json.optDouble("money_in_hand", 0.0),
            totalCountedCash = json.optDouble("total_counted_cash", 0.0),
            cashVariance = json.optDouble("cash_variance", 0.0),
            accounts = accounts,
            categories = cats,
            payers = payers,
            expenses = exps
        )
    }

    suspend fun addExpense(
        monthKey: String,
        branch: String,
        item: String,
        unitPrice: Double,
        quantity: Double,
        paidBy: String,
        category: String,
        expenseDateIso: String
    ): String {
        val body = JSONObject().apply {
            put("month_key", monthKey)
            put("branch", branch)
            put("item", item)
            put("unit_price", unitPrice)
            put("quantity", quantity)
            put("total_price", unitPrice * quantity)
            put("paid_by", paidBy)
            put("category", category)
            put("expense_date", expenseDateIso)
        }
        val json = requestJson("POST", "/api/mobile/expenses/add", body = body)
        return json.optString("message", "Added expense")
    }

    suspend fun updateExpense(
        expId: Int,
        item: String,
        unitPrice: Double,
        quantity: Double,
        paidBy: String,
        category: String
    ): String {
        val body = JSONObject().apply {
            put("item", item)
            put("unit_price", unitPrice)
            put("quantity", quantity)
            put("total_price", unitPrice * quantity)
            put("paid_by", paidBy)
            put("category", category)
        }
        val json = requestJson("POST", "/api/mobile/expenses/$expId/update", body = body)
        return json.optString("message", "Updated expense")
    }

    suspend fun deleteExpense(expId: Int): String {
        val json = requestJson("POST", "/api/mobile/expenses/$expId/delete", body = JSONObject())
        return json.optString("message", "Deleted")
    }

    suspend fun saveExpenseAccounts(monthKey: String, branch: String, accounts: List<CashAccountRow>): String {
        val arr = JSONArray()
        for (a in accounts) {
            arr.put(
                JSONObject().apply {
                    put("name", a.name)
                    put("amount", a.amount)
                    put("expr", String.format(java.util.Locale.US, "%.2f", a.amount))
                }
            )
        }
        val body = JSONObject().apply {
            put("month_key", monthKey)
            put("branch", branch)
            put("accounts", arr)
        }
        val json = requestJson("POST", "/api/mobile/expenses/accounts/update", body = body)
        return json.optString("message", "Accounts updated")
    }

    suspend fun getVendorsList(query: String, filter: String): VendorListResult {
        val params = mutableMapOf("filter" to filter)
        if (query.isNotBlank()) params["q"] = query
        val json = requestJson("GET", "/api/mobile/vendors", params)

        val stObj = json.optJSONObject("stats") ?: JSONObject()
        val stats = VendorListStats(
            totalVendors = stObj.optInt("total_vendors", 0),
            totalPurchased = stObj.optDouble("total_purchased", 0.0),
            openPayable = stObj.optDouble("open_payable", 0.0),
            dueCount = stObj.optInt("due_count", 0),
            totalPoOrders = stObj.optInt("total_po_orders", 0),
            cambodiaCount = stObj.optInt("cambodia_count", 0),
            recentCount = stObj.optInt("recent_count", 0)
        )
        val arr = json.optJSONArray("vendors") ?: JSONArray()
        val list = mutableListOf<VendorItem>()
        for (i in 0 until arr.length()) {
            val v = arr.getJSONObject(i)
            list.add(
                VendorItem(
                    id = v.optInt("id"),
                    name = v.optString("name", ""),
                    contactName = v.optString("contact_name", ""),
                    phone = v.optString("phone", ""),
                    email = v.optString("email", ""),
                    country = v.optString("country", "Cambodia"),
                    city = v.optString("city", ""),
                    address1 = v.optString("address1", ""),
                    poCount = v.optInt("po_count", 0),
                    totalPurchased = v.optDouble("total_purchased", 0.0),
                    openPayable = v.optDouble("open_payable", 0.0),
                    lastPoDate = v.optString("last_po_date", "")
                )
            )
        }
        return VendorListResult(stats, list)
    }

    suspend fun createVendor(
        name: String,
        contactName: String,
        phone: String,
        country: String,
        city: String
    ): String {
        val body = JSONObject().apply {
            put("name", name)
            put("contact_name", contactName)
            put("phone", phone)
            put("country", country)
            put("city", city)
        }
        val json = requestJson("POST", "/api/mobile/vendors/create", body = body)
        return json.optString("message", "Vendor created")
    }

    suspend fun getCustomerOrderHistoryReport(
        branch: String,
        dateFilter: String,
        status: String,
        paidBy: String,
        query: String,
        page: Int
    ): CustomerOrderHistoryReport {
        val params = mutableMapOf(
            "branch" to branch,
            "date_filter" to dateFilter,
            "status" to status,
            "paid_by" to paidBy,
            "page" to page.toString()
        )
        if (query.isNotBlank()) params["q"] = query
        val json = requestJson("GET", "/api/mobile/reports/customer-order-history", params)

        val pmsArr = json.optJSONArray("payment_methods") ?: JSONArray()
        val pms = mutableListOf<String>()
        for (i in 0 until pmsArr.length()) pms.add(pmsArr.optString(i, ""))

        val ordArr = json.optJSONArray("orders") ?: JSONArray()
        val orders = mutableListOf<CustomerHistoryOrder>()
        for (i in 0 until ordArr.length()) {
            val o = ordArr.getJSONObject(i)
            val lArr = o.optJSONArray("lines") ?: JSONArray()
            val lines = mutableListOf<CustomerHistoryLine>()
            for (j in 0 until lArr.length()) {
                val ln = lArr.getJSONObject(j)
                lines.add(
                    CustomerHistoryLine(
                        sku = ln.optString("sku", ""),
                        itemName = ln.optString("item_name", "Item"),
                        description = ln.optString("description", ""),
                        quantity = ln.optDouble("quantity", 1.0),
                        uom = ln.optString("uom", "pcs."),
                        unitPrice = ln.optDouble("unit_price", 0.0),
                        subtotal = ln.optDouble("subtotal", 0.0)
                    )
                )
            }
            orders.add(
                CustomerHistoryOrder(
                    id = o.optInt("id"),
                    orderNumber = o.optString("order_number", ""),
                    orderDate = o.optString("order_date", ""),
                    customerId = o.optInt("customer_id"),
                    customerName = o.optString("customer_name", "Walk-in Customer"),
                    isPaid = o.optBoolean("is_paid", false),
                    paymentMethod = o.optString("payment_method", "Cash"),
                    shippingFee = o.optDouble("shipping_fee", 0.0),
                    totalAmount = o.optDouble("total_amount", 0.0),
                    lines = lines
                )
            )
        }

        return CustomerOrderHistoryReport(
            dateFilter = json.optString("date_filter", dateFilter),
            todayLabel = json.optString("today_label", ""),
            page = json.optInt("page", 1),
            totalPages = json.optInt("total_pages", 1),
            totalOrders = json.optInt("total_orders", 0),
            paidOrders = json.optInt("paid_orders", 0),
            collectionPct = json.optInt("collection_pct", 0),
            periodRevenue = json.optDouble("period_revenue", 0.0),
            paymentMethods = pms,
            orders = orders
        )
    }

    suspend fun getPriceList(query: String = "", categoryId: Int? = null): PriceListResult {
        val params = mutableMapOf<String, String>()
        if (query.isNotBlank()) params["q"] = query
        if (categoryId != null && categoryId > 0) params["category_id"] = categoryId.toString()
        val json = requestJson("GET", "/api/mobile/price-list", params)

        val catsArr = json.optJSONArray("categories") ?: JSONArray()
        val categories = mutableListOf<PriceListCategory>()
        for (i in 0 until catsArr.length()) {
            val c = catsArr.getJSONObject(i)
            categories.add(
                PriceListCategory(
                    id = c.optInt("id"),
                    name = c.optString("name", "General"),
                    color = c.optString("color", "#047857"),
                    productCount = c.optInt("product_count", 0)
                )
            )
        }

        val schArr = json.optJSONArray("pricing_schemes") ?: JSONArray()
        val schemes = mutableListOf<PricingSchemeItem>()
        for (i in 0 until schArr.length()) {
            val s = schArr.getJSONObject(i)
            schemes.add(
                PricingSchemeItem(
                    id = s.optInt("id"),
                    name = s.optString("name", "Retail 1"),
                    currency = s.optString("currency", "USD"),
                    isDefault = s.optBoolean("is_default", false)
                )
            )
        }

        val itemsArr = json.optJSONArray("items") ?: JSONArray()
        val items = mutableListOf<PriceListCardItem>()
        for (i in 0 until itemsArr.length()) {
            val p = itemsArr.getJSONObject(i)
            val dlArr = p.optJSONArray("detail_lines") ?: JSONArray()
            val detailLines = mutableListOf<String>()
            for (j in 0 until dlArr.length()) detailLines.add(dlArr.optString(j, ""))
            items.add(
                PriceListCardItem(
                    id = p.optInt("id"),
                    sku = p.optString("sku", ""),
                    name = p.optString("name", ""),
                    uom = p.optString("uom", "pcs."),
                    categoryId = p.optInt("category_id", 0),
                    categoryName = p.optString("category_name", "General"),
                    imageUrl = p.optString("image_url", ""),
                    badge = p.optString("badge", ""),
                    dimStr = p.optString("dim_str", ""),
                    pcsCase = p.optDouble("pcs_case", 400.0),
                    packsPerCase = p.optDouble("packs_per_case", 8.0),
                    pcsPerPack = p.optDouble("pcs_per_pack", 50.0),
                    detailLines = detailLines,
                    tierQty1 = p.optInt("tier_qty_1", 100),
                    tierQty2 = p.optInt("tier_qty_2", 200),
                    tierQty3 = p.optInt("tier_qty_3", 400),
                    uPrice1 = p.optDouble("u_price_1", 0.0),
                    uPrice2 = p.optDouble("u_price_2", 0.0),
                    uPrice3 = p.optDouble("u_price_3", 0.0),
                    totPrice1 = p.optDouble("tot_price_1", 0.0),
                    totPrice2 = p.optDouble("tot_price_2", 0.0),
                    totPrice3 = p.optDouble("tot_price_3", 0.0),
                    schemePricesPcs = parseDoubleMap(p.optJSONObject("scheme_prices_pcs"))
                )
            )
        }

        return PriceListResult(
            totalProducts = json.optInt("total_products", items.size),
            filteredCount = json.optInt("filtered_count", items.size),
            categories = categories,
            pricingSchemes = schemes,
            items = items
        )
    }

    suspend fun getSettingsOverview(): MobileSettingsOverview {
        val json = requestJson("GET", "/api/mobile/settings/overview")
        val c = json.optJSONObject("company") ?: JSONObject()
        val company = CompanySettingsData(
            name = c.optString("name", ""),
            phone = c.optString("phone", ""),
            email = c.optString("email", ""),
            website = c.optString("website", ""),
            address1 = c.optString("address1", ""),
            city = c.optString("city", ""),
            country = c.optString("country", ""),
            taxNumber = c.optString("tax_number", ""),
            currencyCode = c.optString("currency_code", "USD"),
            currencySymbol = c.optString("currency_symbol", "$"),
            decimalPlacesPrice = c.optInt("decimal_places_price", 2),
            decimalPlacesCost = c.optInt("decimal_places_cost", 3),
            decimalPlacesQty = c.optInt("decimal_places_qty", 0),
            decimalPlacesMarkup = c.optInt("decimal_places_markup", 2),
            decimalPlacesTotal = c.optInt("decimal_places_total", 2),
            decimalPlacesMeasurement = c.optInt("decimal_places_measurement", 2)
        )
        val invObj = json.optJSONObject("invoice_settings") ?: JSONObject()
        val invoice = InvoiceSettingsData(
            shopNameKh = invObj.optString("shop_name_kh", ""),
            shopNameEn = invObj.optString("shop_name_en", ""),
            invoiceTitleKh = invObj.optString("invoice_title_kh", "វិក្កយបត្រ"),
            invoiceTitleEn = invObj.optString("invoice_title_en", "INVOICE"),
            phone = invObj.optString("phone", ""),
            vatTin = invObj.optString("vat_tin", ""),
            enableKhrTotal = invObj.optBoolean("enable_khr_total", true),
            khrExchangeRate = invObj.optDouble("khr_exchange_rate", 4100.0),
            bankName = invObj.optString("bank_name", ""),
            accountName = invObj.optString("account_name", ""),
            accountNumber = invObj.optString("account_number", ""),
            paymentTerms = invObj.optString("payment_terms", ""),
            footerNotesEn = invObj.optString("footer_notes_en", ""),
            showSku = invObj.optBoolean("show_sku", true),
            showTax = invObj.optBoolean("show_tax", false),
            showSignature = invObj.optBoolean("show_signature", true)
        )
        val schArr = json.optJSONArray("pricing_schemes") ?: JSONArray()
        val schemes = mutableListOf<SettingsSchemeInfo>()
        for (i in 0 until schArr.length()) {
            val s = schArr.getJSONObject(i)
            schemes.add(SettingsSchemeInfo(s.optInt("id"), s.optString("name", ""), s.optString("currency", "USD"), s.optBoolean("is_active", true), s.optBoolean("is_default", false)))
        }
        val locArr = json.optJSONArray("locations") ?: JSONArray()
        val locations = mutableListOf<SettingsLocationInfo>()
        for (i in 0 until locArr.length()) {
            val l = locArr.getJSONObject(i)
            locations.add(SettingsLocationInfo(l.optInt("id"), l.optString("name", ""), l.optBoolean("is_default", false), l.optBoolean("is_central", false)))
        }
        val catArr = json.optJSONArray("categories") ?: JSONArray()
        val categories = mutableListOf<AdjustmentCategoryOption>()
        for (i in 0 until catArr.length()) {
            val ct = catArr.getJSONObject(i)
            categories.add(AdjustmentCategoryOption(ct.optInt("id"), ct.optString("name", ""), ct.optInt("product_count", 0)))
        }
        val usrArr = json.optJSONArray("users") ?: JSONArray()
        val users = mutableListOf<SettingsUserInfo>()
        for (i in 0 until usrArr.length()) {
            val u = usrArr.getJSONObject(i)
            users.add(SettingsUserInfo(u.optInt("id"), u.optString("username", ""), u.optString("display_name", ""), u.optString("role", "user"), u.optBoolean("is_active", true), u.optString("branch_name", "")))
        }
        val bkArr = json.optJSONArray("backups") ?: JSONArray()
        val backups = mutableListOf<SettingsBackupInfo>()
        for (i in 0 until bkArr.length()) {
            val b = bkArr.getJSONObject(i)
            backups.add(SettingsBackupInfo(b.optString("filename", ""), b.optString("formatted_size", ""), b.optString("created_at", "")))
        }
        val counts = json.optJSONObject("counts") ?: JSONObject()
        return MobileSettingsOverview(
            company = company,
            invoice = invoice,
            pricingSchemes = schemes,
            locations = locations,
            categories = categories,
            users = users,
            backups = backups,
            productsCount = counts.optInt("products", 0),
            customersCount = counts.optInt("customers", 0),
            salesOrdersCount = counts.optInt("sales_orders", 0),
            locationsCount = counts.optInt("locations", locations.size)
        )
    }

    suspend fun saveCompanySettings(data: CompanySettingsData): String {
        val body = JSONObject().apply {
            put("name", data.name)
            put("phone", data.phone)
            put("email", data.email)
            put("website", data.website)
            put("address1", data.address1)
            put("city", data.city)
            put("country", data.country)
            put("tax_number", data.taxNumber)
        }
        val json = requestJson("POST", "/api/mobile/settings/company", body = body)
        return json.optString("message", "Saved")
    }

    suspend fun savePricingSettings(
        currencyCode: String,
        currencySymbol: String,
        khrRate: Double,
        enableKhrTotal: Boolean,
        defaultSchemeId: Int?
    ): String {
        val body = JSONObject().apply {
            put("currency_code", currencyCode)
            put("currency_symbol", currencySymbol)
            put("khr_exchange_rate", khrRate)
            put("enable_khr_total", enableKhrTotal)
            if (defaultSchemeId != null && defaultSchemeId > 0) put("default_scheme_id", defaultSchemeId)
        }
        val json = requestJson("POST", "/api/mobile/settings/pricing", body = body)
        return json.optString("message", "Saved")
    }

    suspend fun saveDecimalSettings(
        price: Int,
        cost: Int,
        qty: Int,
        markup: Int,
        total: Int,
        measurement: Int
    ): String {
        val body = JSONObject().apply {
            put("decimal_places_price", price)
            put("decimal_places_cost", cost)
            put("decimal_places_qty", qty)
            put("decimal_places_markup", markup)
            put("decimal_places_total", total)
            put("decimal_places_measurement", measurement)
        }
        val json = requestJson("POST", "/api/mobile/settings/decimals", body = body)
        return json.optString("message", "Saved")
    }

    suspend fun saveInvoiceSettings(inv: InvoiceSettingsData): String {
        val body = JSONObject().apply {
            put("shop_name_kh", inv.shopNameKh)
            put("shop_name_en", inv.shopNameEn)
            put("invoice_title_kh", inv.invoiceTitleKh)
            put("invoice_title_en", inv.invoiceTitleEn)
            put("phone", inv.phone)
            put("vat_tin", inv.vatTin)
            put("bank_name", inv.bankName)
            put("account_name", inv.accountName)
            put("account_number", inv.accountNumber)
            put("payment_terms", inv.paymentTerms)
            put("footer_notes_en", inv.footerNotesEn)
            put("show_sku", inv.showSku)
            put("show_tax", inv.showTax)
            put("show_signature", inv.showSignature)
        }
        val json = requestJson("POST", "/api/mobile/settings/invoice", body = body)
        return json.optString("message", "Saved")
    }

    suspend fun toggleUserActive(uid: Int): Pair<Boolean, String> {
        val json = requestJson("POST", "/api/mobile/settings/users/$uid/toggle", body = JSONObject())
        return json.optBoolean("is_active", true) to json.optString("message", "Updated")
    }

    suspend fun createCloudBackup(): String {
        val json = requestJson("POST", "/api/mobile/settings/backup/create", body = JSONObject())
        return json.optString("message", "Backup created")
    }

    suspend fun checkAppUpdate(): AppUpdateInfo {
        val json = requestJson("GET", "/api/mobile/app-update")
        return AppUpdateInfo(
            versionCode = json.optInt("version_code", 1),
            versionName = json.optString("version_name", "1.0.0"),
            apkAvailable = json.optBoolean("apk_available", false),
            apkUrl = json.optString("apk_url", "/static/downloads/inFlow-Premium.apk"),
            apkSizeBytes = json.optLong("apk_size_bytes", 0L),
            apkSizeMb = json.optString("apk_size_mb", "0.0 MB"),
            releaseNotes = json.optString("release_notes", "")
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
