package com.inflow.premium.data

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

class SessionManager(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("inflow_mobile_session", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = (prefs.getString("base_url", "https://premiumpos.cloud") ?: "https://premiumpos.cloud").trimEnd('/')
        set(value) = prefs.edit().putString("base_url", value.trimEnd('/')).apply()

    var token: String
        get() = prefs.getString("auth_token", "") ?: ""
        set(value) = prefs.edit().putString("auth_token", value).apply()

    var selectedBranch: String
        get() = prefs.getString("selected_branch", "main") ?: "main"
        set(value) = prefs.edit().putString("selected_branch", value).apply()

    var defaultKhrRate: Double
        get() = prefs.getFloat("default_khr_rate", 4100f).toDouble()
        set(value) = prefs.edit().putFloat("default_khr_rate", value.toFloat()).apply()

    var hqLogoUrl: String
        get() = prefs.getString("hq_logo_url", "") ?: ""
        set(value) = prefs.edit().putString("hq_logo_url", value).apply()

    fun isLoggedIn(): Boolean = token.isNotBlank()

    fun saveBootstrap(json: JSONObject) {
        val u = json.optJSONObject("user")
        if (u != null) {
            prefs.edit()
                .putInt("user_id", u.optInt("id", 0))
                .putString("username", u.optString("username", ""))
                .putString("display_name", u.optString("display_name", ""))
                .putString("role", u.optString("role", ""))
                .putInt("user_branch_id", if (u.isNull("branch_id")) -1 else u.optInt("branch_id", -1))
                .putBoolean("is_main_admin", u.optBoolean("is_main_admin", false))
                .apply()
            if (!u.optBoolean("is_main_admin", false) && !u.isNull("branch_id")) {
                selectedBranch = u.optInt("branch_id").toString()
            }
        }
        if (json.has("hq_logo_url")) {
            hqLogoUrl = json.optString("hq_logo_url", "")
        }
        if (json.has("default_khr_rate")) {
            defaultKhrRate = json.optDouble("default_khr_rate", 4100.0)
        }
        json.optJSONArray("branches")?.let { prefs.edit().putString("branches_json", it.toString()).apply() }
        json.optJSONArray("pricing_schemes")?.let { prefs.edit().putString("schemes_json", it.toString()).apply() }
        json.optJSONArray("locations")?.let { prefs.edit().putString("locations_json", it.toString()).apply() }
        json.optJSONArray("delivery_men")?.let { prefs.edit().putString("delivery_men_json", it.toString()).apply() }
        json.optJSONArray("categories")?.let { prefs.edit().putString("categories_json", it.toString()).apply() }
    }

    fun isMainAdmin(): Boolean = prefs.getBoolean("is_main_admin", false)
    fun getUserBranchId(): Int? {
        val v = prefs.getInt("user_branch_id", -1)
        return if (v > 0) v else null
    }
    fun getDisplayName(): String = prefs.getString("display_name", "")?.ifBlank { getUsername() } ?: ""
    fun getUsername(): String = prefs.getString("username", "") ?: ""

    fun getBranches(): List<BranchItem> {
        val list = mutableListOf<BranchItem>()
        if (isMainAdmin()) {
            list.add(BranchItem("main", "HQ", "Main Store (HQ)", hqLogoUrl))
            list.add(BranchItem("all", "ALL", "All Stores Combined", hqLogoUrl))
        }
        val raw = prefs.getString("branches_json", "[]") ?: "[]"
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                BranchItem(
                    id = o.optInt("id").toString(),
                    code = o.optString("code", ""),
                    name = o.optString("name", ""),
                    logoUrl = o.optString("logo_url", "")
                )
            )
        }
        return list
    }

    fun getLogoUrlForBranch(branchKey: String): String {
        if (branchKey == "main" || branchKey == "0" || branchKey == "all" || branchKey.isBlank()) {
            return hqLogoUrl
        }
        val match = getBranches().firstOrNull { it.id == branchKey }?.logoUrl?.trim().orEmpty()
        return match.ifBlank { hqLogoUrl }
    }

    fun getProductCategories(): List<ProductCategoryOption> {
        val list = mutableListOf<ProductCategoryOption>()
        val raw = prefs.getString("categories_json", "[]") ?: "[]"
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(ProductCategoryOption(o.optInt("id", 0), o.optString("name", "")))
        }
        return list
    }

    fun getPricingSchemes(): List<PricingSchemeItem> {
        val list = mutableListOf<PricingSchemeItem>()
        val raw = prefs.getString("schemes_json", "[]") ?: "[]"
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(PricingSchemeItem(o.optInt("id", 100), o.optString("name", "Retail 1")))
        }
        if (list.isEmpty()) list.add(PricingSchemeItem(100, "Retail 1"))
        return list
    }

    fun getLocations(): List<LocationItem> {
        val list = mutableListOf<LocationItem>()
        val raw = prefs.getString("locations_json", "[]") ?: "[]"
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(LocationItem(o.optInt("id", 100), o.optString("name", "Main Warehouse")))
        }
        if (list.isEmpty()) list.add(LocationItem(100, "Main Warehouse"))
        return list
    }

    fun getDeliveryMen(): List<DeliveryManItem> {
        val list = mutableListOf<DeliveryManItem>()
        val raw = prefs.getString("delivery_men_json", "[]") ?: "[]"
        val arr = JSONArray(raw)
        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(DeliveryManItem(o.optInt("id", 0), o.optString("name", ""), o.optString("phone", "")))
        }
        return list
    }

    var dismissedOtaVersionCode: Int
        get() = prefs.getInt("dismissed_ota_vc", 0)
        set(value) = prefs.edit().putInt("dismissed_ota_vc", value).apply()

    var autoOtaUpdate: Boolean
        get() = prefs.getBoolean("auto_ota_update", true)
        set(value) = prefs.edit().putBoolean("auto_ota_update", value).apply()

    var themeMode: String
        get() = prefs.getString("theme_mode", "system") ?: "system"
        set(value) = prefs.edit().putString("theme_mode", value).apply()

    fun logout() {
        val savedUrl = baseUrl
        val savedTheme = themeMode
        prefs.edit().clear().putString("base_url", savedUrl).putString("theme_mode", savedTheme).apply()
    }
}
