package com.inflow.premium.ui

import android.animation.AnimatorListenerAdapter
import android.animation.AnimatorSet
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.graphics.drawable.TransitionDrawable
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.view.animation.OvershootInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.ImageView
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.inflow.premium.R

object BottomNavHelper {

    enum class NavTab {
        SETTINGS, REPORT, HOME, SO, PRODUCT
    }

    private var pendingAnimateTab: NavTab? = null
    private var lastTabIndex: Int = NavTab.HOME.ordinal

    private fun outlineResFor(tab: NavTab): Int = when (tab) {
        NavTab.SETTINGS -> R.drawable.ic_nav_settings_outline
        NavTab.REPORT -> R.drawable.ic_nav_report_outline
        NavTab.HOME -> R.drawable.ic_nav_home_outline
        NavTab.SO -> R.drawable.ic_nav_so_outline
        NavTab.PRODUCT -> R.drawable.ic_nav_product_outline
    }

    private fun filledResFor(tab: NavTab): Int = when (tab) {
        NavTab.SETTINGS -> R.drawable.ic_nav_settings
        NavTab.REPORT -> R.drawable.ic_nav_report
        NavTab.HOME -> R.drawable.ic_nav_home
        NavTab.SO -> R.drawable.ic_nav_so
        NavTab.PRODUCT -> R.drawable.ic_nav_product
    }

    fun setup(activity: Activity, navRoot: View, activeTab: NavTab) {
        val activeColor = ContextCompat.getColor(activity, R.color.nav_active_tint)
        val inactiveColor = ContextCompat.getColor(activity, R.color.nav_inactive_tint)

        val capsule = navRoot.findViewById<View>(R.id.navCapsulePill)
        val tabsRow = navRoot.findViewById<View>(R.id.navTabsRow)
        val glassPill = navRoot.findViewById<View>(R.id.navGlassPill)

        fun positionGlassPill(index: Int, animateFrom: Int? = null) {
            if (glassPill == null || tabsRow == null) return
            val rowW = tabsRow.width
            if (rowW <= 0) return
            val tabW = rowW / 5f
            val targetW = tabW.toInt().coerceAtLeast(1)
            val lp = glassPill.layoutParams
            if (lp.width != targetW) {
                lp.width = targetW
                glassPill.layoutParams = lp
            }
            val targetX = index * tabW
            if (animateFrom != null && animateFrom != index) {
                glassPill.animate().cancel()
                glassPill.translationX = animateFrom * tabW
                val glide = AnimatorSet().apply {
                    duration = 340L
                    interpolator = OvershootInterpolator(1.05f)
                    playTogether(
                        ObjectAnimator.ofFloat(glassPill, View.TRANSLATION_X, animateFrom * tabW, targetX),
                        ObjectAnimator.ofFloat(glassPill, View.SCALE_X, 1f, 1.15f, 0.96f, 1f),
                        ObjectAnimator.ofFloat(glassPill, View.SCALE_Y, 1f, 0.90f, 1.04f, 1f)
                    )
                }
                glide.start()
            } else {
                glassPill.translationX = targetX
                glassPill.scaleX = 1f
                glassPill.scaleY = 1f
            }
        }

        fun syncLandscapeSize() {
            if (capsule == null) return
            val dm = activity.resources.displayMetrics
            val isLandscape = dm.widthPixels > dm.heightPixels
            val targetW = if (isLandscape) {
                (minOf(dm.widthPixels, dm.heightPixels) - (28 * dm.density).toInt())
                    .coerceAtLeast((300 * dm.density).toInt())
            } else {
                ViewGroup.LayoutParams.MATCH_PARENT
            }
            val lp = capsule.layoutParams
            if (lp.width != targetW) {
                lp.width = targetW
                capsule.layoutParams = lp
            }
            positionGlassPill(activeTab.ordinal)
        }
        syncLandscapeSize()
        navRoot.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> syncLandscapeSize() }
        tabsRow?.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
            if (pendingAnimateTab != activeTab) {
                positionGlassPill(activeTab.ordinal)
            }
        }

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

        fun styleItem(tab: NavTab, container: View, iv: ImageView, tv: TextView, isActive: Boolean) {
            val c = if (isActive) activeColor else inactiveColor
            container.background = null
            if (isActive) {
                iv.setImageResource(filledResFor(tab))
            } else {
                iv.setImageResource(outlineResFor(tab))
            }
            iv.imageTintList = ColorStateList.valueOf(c)
            tv.setTextColor(c)
            tv.setTypeface(null, Typeface.BOLD)
        }

        styleItem(NavTab.SETTINGS, tabSettings, ivSettings, tvSettings, activeTab == NavTab.SETTINGS)
        styleItem(NavTab.REPORT, tabReport, ivReport, tvReport, activeTab == NavTab.REPORT)
        styleItem(NavTab.HOME, tabHome, ivHome, tvHome, activeTab == NavTab.HOME)
        styleItem(NavTab.SO, tabSo, ivSo, tvSo, activeTab == NavTab.SO)
        styleItem(NavTab.PRODUCT, tabProduct, ivProduct, tvProduct, activeTab == NavTab.PRODUCT)

        fun targetViewsFor(tab: NavTab): Triple<View, ImageView, TextView> = when (tab) {
            NavTab.SETTINGS -> Triple(tabSettings, ivSettings, tvSettings)
            NavTab.REPORT -> Triple(tabReport, ivReport, tvReport)
            NavTab.HOME -> Triple(tabHome, ivHome, tvHome)
            NavTab.SO -> Triple(tabSo, ivSo, tvSo)
            NavTab.PRODUCT -> Triple(tabProduct, ivProduct, tvProduct)
        }

        fun playArrivalIfPending() {
            if (pendingAnimateTab == activeTab) {
                val fromIdx = lastTabIndex
                pendingAnimateTab = null
                lastTabIndex = activeTab.ordinal
                positionGlassPill(activeTab.ordinal, animateFrom = fromIdx)
                val (c, iv, tv) = targetViewsFor(activeTab)
                animateTabFillAndBounce(activity, c, iv, tv, activeTab, activeColor, inactiveColor)
            } else {
                lastTabIndex = activeTab.ordinal
                positionGlassPill(activeTab.ordinal)
            }
        }

        navRoot.post { playArrivalIfPending() }
        navRoot.viewTreeObserver.addOnWindowFocusChangeListener { hasFocus ->
            if (hasFocus) {
                playArrivalIfPending()
            }
        }

        fun navigateTo(tab: NavTab, cls: Class<*>, container: View, iv: ImageView, tv: TextView) {
            container.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
            if (activeTab == tab) {
                // Liquid droplet ripple when tapping current tab
                glassPill?.let { gp ->
                    AnimatorSet().apply {
                        duration = 280L
                        interpolator = OvershootInterpolator(1.6f)
                        playTogether(
                            ObjectAnimator.ofFloat(gp, View.SCALE_X, 1f, 1.12f, 0.96f, 1f),
                            ObjectAnimator.ofFloat(gp, View.SCALE_Y, 1f, 0.90f, 1.04f, 1f)
                        )
                    }.start()
                }
                animateTabFillAndBounce(activity, container, iv, tv, tab, activeColor, inactiveColor)
                return
            }
            lastTabIndex = activeTab.ordinal
            pendingAnimateTab = tab
            dismissKeyboardAndClearFocus(activity)
            // Elastic liquid-glass glide preview before switching activity
            positionGlassPill(tab.ordinal, animateFrom = activeTab.ordinal)
            iv.animate().cancel()
            iv.imageTintList = ColorStateList.valueOf(activeColor)
            iv.animate()
                .scaleX(0.84f)
                .scaleY(0.84f)
                .setDuration(85L)
                .withEndAction {
                    iv.scaleX = 1f
                    iv.scaleY = 1f
                    iv.imageTintList = ColorStateList.valueOf(inactiveColor)
                    val intent = Intent(activity, cls).apply {
                        addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
                    }
                    activity.startActivity(intent)
                    @Suppress("DEPRECATION")
                    activity.overridePendingTransition(0, 0)
                }
                .start()
        }

        tabSettings.setOnClickListener { navigateTo(NavTab.SETTINGS, AppSettingsActivity::class.java, tabSettings, ivSettings, tvSettings) }
        tabReport.setOnClickListener { navigateTo(NavTab.REPORT, ReportActivity::class.java, tabReport, ivReport, tvReport) }
        tabHome.setOnClickListener { navigateTo(NavTab.HOME, HomeActivity::class.java, tabHome, ivHome, tvHome) }
        tabSo.setOnClickListener { navigateTo(NavTab.SO, SalesOrdersActivity::class.java, tabSo, ivSo, tvSo) }
        tabProduct.setOnClickListener { navigateTo(NavTab.PRODUCT, ProductsActivity::class.java, tabProduct, ivProduct, tvProduct) }
    }

    fun dismissKeyboardAndClearFocus(activity: Activity) {
        val focused = activity.currentFocus
        val root = activity.window?.decorView
        val token = focused?.windowToken ?: root?.windowToken
        focused?.clearFocus()
        if (token != null) {
            val imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE) as? InputMethodManager
            imm?.hideSoftInputFromWindow(token, 0)
        }
    }

    private fun animateTabFillAndBounce(
        activity: Activity,
        container: View,
        iv: ImageView,
        tv: TextView,
        tab: NavTab,
        activeColor: Int,
        inactiveColor: Int
    ) {
        iv.animate().cancel()
        container.animate().cancel()

        val outline = ContextCompat.getDrawable(activity, outlineResFor(tab))?.mutate()
        val filled = ContextCompat.getDrawable(activity, filledResFor(tab))?.mutate()
        if (outline != null && filled != null) {
            val transition = TransitionDrawable(arrayOf(outline, filled)).apply {
                isCrossFadeEnabled = true
            }
            iv.setImageDrawable(transition)
            transition.startTransition(260)
        } else {
            iv.setImageResource(filledResFor(tab))
        }

        val colorAnim = ValueAnimator.ofArgb(inactiveColor, activeColor).apply {
            duration = 260L
            addUpdateListener { va ->
                val c = va.animatedValue as Int
                iv.imageTintList = ColorStateList.valueOf(c)
                tv.setTextColor(c)
            }
            addListener(object : AnimatorListenerAdapter() {
                override fun onAnimationEnd(animation: android.animation.Animator) {
                    iv.setImageResource(filledResFor(tab))
                    iv.imageTintList = ColorStateList.valueOf(activeColor)
                    tv.setTextColor(activeColor)
                }
            })
        }
        colorAnim.start()

        iv.scaleX = 0.80f
        iv.scaleY = 0.80f
        iv.translationY = 3f
        val overshoot = OvershootInterpolator(2.2f)
        val iconSet = AnimatorSet().apply {
            duration = 320L
            interpolator = overshoot
            val anims = mutableListOf<android.animation.Animator>(
                ObjectAnimator.ofFloat(iv, View.SCALE_X, 0.80f, 1.16f, 1f),
                ObjectAnimator.ofFloat(iv, View.SCALE_Y, 0.80f, 1.16f, 1f),
                ObjectAnimator.ofFloat(iv, View.TRANSLATION_Y, 3f, -3.5f, 0f)
            )
            when (tab) {
                NavTab.SETTINGS -> anims.add(ObjectAnimator.ofFloat(iv, View.ROTATION, -35f, 8f, 0f))
                NavTab.SO, NavTab.PRODUCT -> anims.add(ObjectAnimator.ofFloat(iv, View.ROTATION, -8f, 5f, 0f))
                else -> {}
            }
            playTogether(anims)
        }
        iconSet.start()
    }
}
