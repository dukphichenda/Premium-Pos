package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import com.inflow.premium.R

object BottomNavHelper {

    enum class NavTab {
        SETTINGS, REPORT, HOME, SO, PRODUCT
    }

    fun setup(activity: Activity, navRoot: View, activeTab: NavTab) {
        val activeColor = Color.parseColor("#2E9E95")
        val inactiveColor = Color.parseColor("#111827")

        val tabSettings = navRoot.findViewById<View>(R.id.navTabSettings)
        val ivSettings = navRoot.findViewById<ImageView>(R.id.ivNavSettings)
        val tvSettings = navRoot.findViewById<TextView>(R.id.tvNavSettings)

        val tabReport = navRoot.findViewById<View>(R.id.navTabReport)
        val ivReport = navRoot.findViewById<ImageView>(R.id.ivNavReport)
        val tvReport = navRoot.findViewById<TextView>(R.id.tvNavReport)

        val tabHome = navRoot.findViewById<View>(R.id.navTabHome)
        val ivHome = navRoot.findViewById<ImageView>(R.id.ivNavHome)
        val tvHome = navRoot.findViewById<TextView>(R.id.tvNavHome)

        val tabSo = navRoot.findViewById<View>(R.id.navTabSo)
        val ivSo = navRoot.findViewById<ImageView>(R.id.ivNavSo)
        val tvSo = navRoot.findViewById<TextView>(R.id.tvNavSo)

        val tabProduct = navRoot.findViewById<View>(R.id.navTabProduct)
        val ivProduct = navRoot.findViewById<ImageView>(R.id.ivNavProduct)
        val tvProduct = navRoot.findViewById<TextView>(R.id.tvNavProduct)

        fun styleItem(container: View, iv: ImageView, tv: TextView, isActive: Boolean) {
            val c = if (isActive) activeColor else inactiveColor
            if (isActive) {
                container.setBackgroundResource(R.drawable.bg_nav_active_pill)
            } else {
                container.background = null
            }
            iv.imageTintList = ColorStateList.valueOf(c)
            tv.setTextColor(c)
            tv.setTypeface(null, Typeface.BOLD)
        }

        styleItem(tabSettings, ivSettings, tvSettings, activeTab == NavTab.SETTINGS)
        styleItem(tabReport, ivReport, tvReport, activeTab == NavTab.REPORT)
        styleItem(tabHome, ivHome, tvHome, activeTab == NavTab.HOME)
        styleItem(tabSo, ivSo, tvSo, activeTab == NavTab.SO)
        styleItem(tabProduct, ivProduct, tvProduct, activeTab == NavTab.PRODUCT)

        fun navigateTo(tab: NavTab, cls: Class<*>) {
            if (activeTab == tab) return
            val intent = Intent(activity, cls).apply {
                addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
            }
            activity.startActivity(intent)
            @Suppress("DEPRECATION")
            activity.overridePendingTransition(0, 0)
        }

        tabSettings.setOnClickListener { navigateTo(NavTab.SETTINGS, AppSettingsActivity::class.java) }
        tabReport.setOnClickListener { navigateTo(NavTab.REPORT, ReportActivity::class.java) }
        tabHome.setOnClickListener { navigateTo(NavTab.HOME, HomeActivity::class.java) }
        tabSo.setOnClickListener { navigateTo(NavTab.SO, SalesOrdersActivity::class.java) }
        tabProduct.setOnClickListener { navigateTo(NavTab.PRODUCT, ProductsActivity::class.java) }
    }
}
