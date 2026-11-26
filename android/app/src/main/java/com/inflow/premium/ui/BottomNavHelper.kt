package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.view.View
import android.widget.ImageView
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.inflow.premium.R

object BottomNavHelper {

    enum class NavTab {
        SETTINGS, REPORT, HOME, SO, PRODUCT
    }

    fun setup(activity: Activity, navRoot: View, activeTab: NavTab) {
        val activeColor = ContextCompat.getColor(activity, R.color.primary_dark)
        val inactiveColor = ContextCompat.getColor(activity, R.color.gray)

        val tabSettings = navRoot.findViewById<View>(R.id.navTabSettings)
        val ivSettings = navRoot.findViewById<ImageView>(R.id.ivNavSettings)
        val tvSettings = navRoot.findViewById<TextView>(R.id.tvNavSettings)
        val indSettings = navRoot.findViewById<View>(R.id.indNavSettings)

        val tabReport = navRoot.findViewById<View>(R.id.navTabReport)
        val ivReport = navRoot.findViewById<ImageView>(R.id.ivNavReport)
        val tvReport = navRoot.findViewById<TextView>(R.id.tvNavReport)
        val indReport = navRoot.findViewById<View>(R.id.indNavReport)

        val tabHomeLabel = navRoot.findViewById<View>(R.id.navTabHomeLabel)
        val btnHomeCircle = navRoot.findViewById<View>(R.id.btnNavHomeCircle)
        val tvHome = navRoot.findViewById<TextView>(R.id.tvNavHome)
        val indHome = navRoot.findViewById<View>(R.id.indNavHome)

        val tabSo = navRoot.findViewById<View>(R.id.navTabSo)
        val ivSo = navRoot.findViewById<ImageView>(R.id.ivNavSo)
        val tvSo = navRoot.findViewById<TextView>(R.id.tvNavSo)
        val indSo = navRoot.findViewById<View>(R.id.indNavSo)

        val tabProduct = navRoot.findViewById<View>(R.id.navTabProduct)
        val ivProduct = navRoot.findViewById<ImageView>(R.id.ivNavProduct)
        val tvProduct = navRoot.findViewById<TextView>(R.id.tvNavProduct)
        val indProduct = navRoot.findViewById<View>(R.id.indNavProduct)

        fun styleItem(iv: ImageView?, tv: TextView, ind: View, isActive: Boolean) {
            val c = if (isActive) activeColor else inactiveColor
            iv?.imageTintList = ColorStateList.valueOf(c)
            tv.setTextColor(c)
            tv.setTypeface(null, if (isActive) Typeface.BOLD else Typeface.NORMAL)
            ind.visibility = if (isActive) View.VISIBLE else View.INVISIBLE
        }

        styleItem(ivSettings, tvSettings, indSettings, activeTab == NavTab.SETTINGS)
        styleItem(ivReport, tvReport, indReport, activeTab == NavTab.REPORT)
        styleItem(null, tvHome, indHome, activeTab == NavTab.HOME)
        styleItem(ivSo, tvSo, indSo, activeTab == NavTab.SO)
        styleItem(ivProduct, tvProduct, indProduct, activeTab == NavTab.PRODUCT)

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
        btnHomeCircle.setOnClickListener { navigateTo(NavTab.HOME, HomeActivity::class.java) }
        tabHomeLabel.setOnClickListener { navigateTo(NavTab.HOME, HomeActivity::class.java) }
        tabSo.setOnClickListener { navigateTo(NavTab.SO, SalesOrdersActivity::class.java) }
        tabProduct.setOnClickListener { navigateTo(NavTab.PRODUCT, ProductsActivity::class.java) }
    }
}
