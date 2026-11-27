package com.inflow.premium.ui

import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.app.Activity
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.animation.OvershootInterpolator
import android.widget.ImageView
import android.widget.TextView
import com.inflow.premium.R

object BottomNavHelper {

    enum class NavTab {
        SETTINGS, REPORT, HOME, SO, PRODUCT
    }

    private var pendingAnimateTab: NavTab? = null

    fun setup(activity: Activity, navRoot: View, activeTab: NavTab) {
        val activeColor = Color.parseColor("#2E9E95")
        val inactiveColor = Color.parseColor("#64748B")

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

        fun targetViewsFor(tab: NavTab): Pair<View, ImageView> = when (tab) {
            NavTab.SETTINGS -> tabSettings to ivSettings
            NavTab.REPORT -> tabReport to ivReport
            NavTab.HOME -> tabHome to ivHome
            NavTab.SO -> tabSo to ivSo
            NavTab.PRODUCT -> tabProduct to ivProduct
        }

        fun playArrivalIfPending() {
            if (pendingAnimateTab == activeTab) {
                pendingAnimateTab = null
                val (c, iv) = targetViewsFor(activeTab)
                animateTabBounce(c, iv, activeTab)
            }
        }

        navRoot.post { playArrivalIfPending() }
        navRoot.viewTreeObserver.addOnWindowFocusChangeListener { hasFocus ->
            if (hasFocus) {
                playArrivalIfPending()
            }
        }

        fun navigateTo(tab: NavTab, cls: Class<*>, container: View, iv: ImageView) {
            container.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
            if (activeTab == tab) {
                animateTabBounce(container, iv, tab)
                return
            }
            pendingAnimateTab = tab
            // Quick tactile press-in animation before switching tabs
            iv.animate().cancel()
            iv.animate()
                .scaleX(0.82f)
                .scaleY(0.82f)
                .setDuration(75L)
                .withEndAction {
                    iv.scaleX = 1f
                    iv.scaleY = 1f
                    val intent = Intent(activity, cls).apply {
                        addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                    }
                    activity.startActivity(intent)
                    @Suppress("DEPRECATION")
                    activity.overridePendingTransition(0, 0)
                }
                .start()
        }

        tabSettings.setOnClickListener { navigateTo(NavTab.SETTINGS, AppSettingsActivity::class.java, tabSettings, ivSettings) }
        tabReport.setOnClickListener { navigateTo(NavTab.REPORT, ReportActivity::class.java, tabReport, ivReport) }
        tabHome.setOnClickListener { navigateTo(NavTab.HOME, HomeActivity::class.java, tabHome, ivHome) }
        tabSo.setOnClickListener { navigateTo(NavTab.SO, SalesOrdersActivity::class.java, tabSo, ivSo) }
        tabProduct.setOnClickListener { navigateTo(NavTab.PRODUCT, ProductsActivity::class.java, tabProduct, ivProduct) }
    }

    private fun animateTabBounce(container: View, iv: ImageView, tab: NavTab) {
        iv.animate().cancel()
        container.animate().cancel()

        iv.scaleX = 0.78f
        iv.scaleY = 0.78f
        iv.translationY = 4f
        container.scaleX = 0.94f
        container.scaleY = 0.94f

        val overshoot = OvershootInterpolator(2.4f)
        val iconSet = AnimatorSet().apply {
            duration = 320L
            interpolator = overshoot
            val anims = mutableListOf<android.animation.Animator>(
                ObjectAnimator.ofFloat(iv, View.SCALE_X, 0.78f, 1.16f, 1f),
                ObjectAnimator.ofFloat(iv, View.SCALE_Y, 0.78f, 1.16f, 1f),
                ObjectAnimator.ofFloat(iv, View.TRANSLATION_Y, 4f, -4f, 0f)
            )
            when (tab) {
                NavTab.SETTINGS -> anims.add(ObjectAnimator.ofFloat(iv, View.ROTATION, -35f, 8f, 0f))
                NavTab.SO, NavTab.PRODUCT -> anims.add(ObjectAnimator.ofFloat(iv, View.ROTATION, -8f, 5f, 0f))
                else -> {}
            }
            playTogether(anims)
        }
        iconSet.start()

        container.animate()
            .scaleX(1f)
            .scaleY(1f)
            .setDuration(240L)
            .setInterpolator(overshoot)
            .start()
    }
}
