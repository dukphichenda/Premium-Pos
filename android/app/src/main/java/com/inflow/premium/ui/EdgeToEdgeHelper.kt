package com.inflow.premium.ui

import android.graphics.Color
import android.os.Build
import android.view.View
import android.view.ViewGroup
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

object EdgeToEdgeHelper {

    fun apply(
        activity: AppCompatActivity,
        rootView: View,
        topContentView: View?,
        topScrimView: View?,
        bottomNavContainer: View?,
        bottomScrimView: View?,
        scrollableView: View? = null,
        fabView: View? = null,
        extraTopDp: Int = 8,
        extraBottomScrollDp: Int = 100
    ) {
        val window = activity.window
        WindowCompat.setDecorFitsSystemWindows(window, false)
        @Suppress("DEPRECATION")
        window.statusBarColor = Color.TRANSPARENT
        @Suppress("DEPRECATION")
        window.navigationBarColor = Color.TRANSPARENT

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
            window.isStatusBarContrastEnforced = false
        }

        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
        }

        val density = activity.resources.displayMetrics.density
        fun dp(v: Int): Int = (v * density).toInt()

        ViewCompat.setOnApplyWindowInsetsListener(rootView) { _, windowInsets ->
            val sysBars = windowInsets.getInsets(
                WindowInsetsCompat.Type.statusBars() or WindowInsetsCompat.Type.displayCutout()
            )
            val navBars = windowInsets.getInsets(WindowInsetsCompat.Type.navigationBars())

            val topInset = sysBars.top
            val bottomInset = navBars.bottom

            topContentView?.setPadding(
                topContentView.paddingLeft,
                topInset + dp(extraTopDp),
                topContentView.paddingRight,
                topContentView.paddingBottom
            )

            topScrimView?.let { v ->
                val lp = v.layoutParams
                val targetH = topInset + dp(34)
                if (lp.height != targetH) {
                    lp.height = targetH
                    v.layoutParams = lp
                }
            }

            bottomNavContainer?.setPadding(
                bottomNavContainer.paddingLeft,
                bottomNavContainer.paddingTop,
                bottomNavContainer.paddingRight,
                bottomInset + dp(10)
            )

            bottomScrimView?.let { v ->
                val lp = v.layoutParams
                val targetH = bottomInset + dp(96)
                if (lp.height != targetH) {
                    lp.height = targetH
                    v.layoutParams = lp
                }
            }

            scrollableView?.setPadding(
                scrollableView.paddingLeft,
                if (topContentView == null) topInset + dp(extraTopDp) else scrollableView.paddingTop,
                scrollableView.paddingRight,
                bottomInset + dp(extraBottomScrollDp)
            )

            fabView?.let { fab ->
                val lp = fab.layoutParams as? ViewGroup.MarginLayoutParams
                val targetMargin = bottomInset + dp(88)
                if (lp != null && lp.bottomMargin != targetMargin) {
                    lp.bottomMargin = targetMargin
                    fab.layoutParams = lp
                }
            }

            windowInsets
        }
        ViewCompat.requestApplyInsets(rootView)
    }

    fun applySimpleLightStatus(activity: AppCompatActivity, rootView: View) {
        val window = activity.window
        WindowCompat.setDecorFitsSystemWindows(window, false)
        @Suppress("DEPRECATION")
        window.statusBarColor = Color.TRANSPARENT
        @Suppress("DEPRECATION")
        window.navigationBarColor = Color.TRANSPARENT
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.isNavigationBarContrastEnforced = false
            window.isStatusBarContrastEnforced = false
        }
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
        }
        ViewCompat.setOnApplyWindowInsetsListener(rootView) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        ViewCompat.requestApplyInsets(rootView)
    }
}
