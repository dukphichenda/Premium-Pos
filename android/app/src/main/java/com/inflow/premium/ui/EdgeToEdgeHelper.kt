package com.inflow.premium.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.Shader
import android.graphics.drawable.BitmapDrawable
import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import kotlin.math.max
import kotlin.math.min

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

        val isDark = ThemeHelper.isNightMode(activity)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = !isDark
            isAppearanceLightNavigationBars = !isDark
        }

        val density = activity.resources.displayMetrics.density
        fun dp(v: Int): Int = (v * density).toInt()
        val initialScrollPadTop = scrollableView?.paddingTop ?: 0
        var lastTopInset = 0

        fun syncFloatingTopMetrics(topInset: Int) {
            val headerBottom = topContentView?.height?.takeIf { it > 0 } ?: 0
            topScrimView?.let { v ->
                val lp = v.layoutParams
                val targetH = if (topContentView != null) {
                    max(topInset + dp(52), headerBottom + dp(10))
                } else {
                    topInset + dp(22)
                }
                if (lp.height != targetH) {
                    lp.height = targetH
                    v.layoutParams = lp
                }
            }
            if (topContentView != null && scrollableView != null && headerBottom > 0) {
                val desiredTop = max(initialScrollPadTop, headerBottom + dp(6))
                if (scrollableView.paddingTop != desiredTop) {
                    scrollableView.setPadding(
                        scrollableView.paddingLeft,
                        desiredTop,
                        scrollableView.paddingRight,
                        scrollableView.paddingBottom
                    )
                }
            }
        }

        ViewCompat.setOnApplyWindowInsetsListener(rootView) { _, windowInsets ->
            val sysBars = windowInsets.getInsets(
                WindowInsetsCompat.Type.statusBars() or WindowInsetsCompat.Type.displayCutout()
            )
            val navBars = windowInsets.getInsets(WindowInsetsCompat.Type.navigationBars())

            val topInset = sysBars.top
            val bottomInset = navBars.bottom
            lastTopInset = topInset

            topContentView?.setPadding(
                topContentView.paddingLeft,
                topInset + dp(extraTopDp),
                topContentView.paddingRight,
                topContentView.paddingBottom
            )

            bottomNavContainer?.setPadding(
                bottomNavContainer.paddingLeft,
                bottomNavContainer.paddingTop,
                bottomNavContainer.paddingRight,
                (bottomInset * 0.85f).toInt() + dp(12)
            )

            bottomScrimView?.let { v ->
                val lp = v.layoutParams
                val targetH = bottomInset + dp(104)
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

            syncFloatingTopMetrics(topInset)

            fabView?.let { fab ->
                val lp = fab.layoutParams as? ViewGroup.MarginLayoutParams
                val targetMargin = bottomInset + dp(96)
                if (lp != null && lp.bottomMargin != targetMargin) {
                    lp.bottomMargin = targetMargin
                    fab.layoutParams = lp
                }
            }

            windowInsets
        }
        topContentView?.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
            syncFloatingTopMetrics(lastTopInset)
        }
        ViewCompat.requestApplyInsets(rootView)

        if (topScrimView != null && scrollableView != null) {
            installTopStatusBlur(topScrimView, scrollableView)
        }
    }

    /**
     * Real-time Telegram-style frosted blur across the status bar region:
     * samples the live scrolled content beneath [topScrimView] (capturing the inner child
     * of ScrollView/NestedScrollView so scrollY offsets are honored accurately), applies a
     * smooth dual box-blur + bright frosted glaze + feathered alpha mask.
     */
    private fun installTopStatusBlur(topScrimView: View, scrollableView: View) {
        val scale = 0.24f
        var needsBlur = true
        var lastScrollY = Int.MIN_VALUE
        var smallBmp: Bitmap? = null
        var outBmp: Bitmap? = null
        var smallPixels: IntArray? = null
        var tempPixels: IntArray? = null

        val filterPaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
        val tintPaint = Paint()
        val maskPaint = Paint().apply {
            xfermode = PorterDuffXfermode(PorterDuff.Mode.DST_IN)
        }
        val scrimLoc = IntArray(2)
        val targetLoc = IntArray(2)

        fun resolveCaptureTarget(): View {
            // ScrollView / NestedScrollView store scroll offset in mScrollY without shifting child.top,
            // so View.draw(canvas) would otherwise render scrollY=0; drawing child(0) with its window
            // location reflects the exact scrolled content underneath the status bar.
            if ((scrollableView is android.widget.ScrollView || scrollableView is androidx.core.widget.NestedScrollView) &&
                scrollableView is ViewGroup &&
                scrollableView.childCount > 0
            ) {
                return scrollableView.getChildAt(0)
            }
            return scrollableView
        }

        fun updateBlurDrawable() {
            val w = topScrimView.width
            val h = topScrimView.height
            if (w <= 0 || h <= 0 || scrollableView.width <= 0 || scrollableView.height <= 0) return

            val sw = max(6, (w * scale).toInt())
            val sh = max(6, (h * scale).toInt())

            val sb = smallBmp?.takeIf { it.width == sw && it.height == sh }
                ?: Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888).also { smallBmp = it }
            val ob = outBmp?.takeIf { it.width == sw && it.height == sh }
                ?: Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888).also { outBmp = it }

            val target = resolveCaptureTarget()
            topScrimView.getLocationInWindow(scrimLoc)
            target.getLocationInWindow(targetLoc)
            val dx = (targetLoc[0] - scrimLoc[0]).toFloat()
            val dy = (targetLoc[1] - scrimLoc[1]).toFloat()

            val isDark = ThemeHelper.isNightMode(topScrimView.context)
            val c = Canvas(sb)
            c.drawColor(Color.parseColor(if (isDark) "#0B1220" else "#F8FAFC"))
            c.save()
            c.scale(scale, scale)
            c.translate(dx, dy)
            target.draw(c)
            c.restore()

            val len = sw * sh
            val pix = smallPixels?.takeIf { it.size == len } ?: IntArray(len).also { smallPixels = it }
            val tmp = tempPixels?.takeIf { it.size == len } ?: IntArray(len).also { tempPixels = it }
            sb.getPixels(pix, 0, sw, 0, 0, sw, sh)
            boxBlurPass(pix, tmp, sw, sh, radius = 4)
            boxBlurPass(pix, tmp, sw, sh, radius = 3)
            sb.setPixels(pix, 0, sw, 0, 0, sw, sh)

            val outCanvas = Canvas(ob)
            outCanvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
            outCanvas.drawBitmap(sb, 0f, 0f, filterPaint)

            // Frosted glaze adapting cleanly to Light or Dark mode
            val r = if (isDark) 11 else 248
            val g = if (isDark) 18 else 250
            val b = if (isDark) 32 else 252
            tintPaint.shader = LinearGradient(
                0f, 0f, 0f, sh.toFloat(),
                intArrayOf(
                    Color.argb(216, r, g, b),
                    Color.argb(165, r, g, b),
                    Color.argb(72, r, g, b),
                    Color.argb(0, r, g, b)
                ),
                floatArrayOf(0f, 0.42f, 0.76f, 1f),
                Shader.TileMode.CLAMP
            )
            outCanvas.drawRect(0f, 0f, sw.toFloat(), sh.toFloat(), tintPaint)

            // Smooth 6-stop feathered alpha mask dissolving cleanly with zero hard edge or shadow band
            maskPaint.shader = LinearGradient(
                0f, 0f, 0f, sh.toFloat(),
                intArrayOf(
                    Color.argb(252, 0, 0, 0),
                    Color.argb(215, 0, 0, 0),
                    Color.argb(138, 0, 0, 0),
                    Color.argb(62, 0, 0, 0),
                    Color.argb(16, 0, 0, 0),
                    Color.argb(0, 0, 0, 0)
                ),
                floatArrayOf(0f, 0.28f, 0.52f, 0.74f, 0.90f, 1f),
                Shader.TileMode.CLAMP
            )
            outCanvas.drawRect(0f, 0f, sw.toFloat(), sh.toFloat(), maskPaint)

            topScrimView.background = BitmapDrawable(topScrimView.resources, ob)
        }

        scrollableView.viewTreeObserver.addOnScrollChangedListener {
            val curY = scrollableView.scrollY
            if (curY != lastScrollY || scrollableView is androidx.recyclerview.widget.RecyclerView) {
                lastScrollY = curY
                needsBlur = true
                topScrimView.postInvalidateOnAnimation()
            }
        }
        scrollableView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
            needsBlur = true
        }
        topScrimView.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ ->
            needsBlur = true
        }

        val preDrawListener = ViewTreeObserver.OnPreDrawListener {
            if (needsBlur && topScrimView.isAttachedToWindow) {
                needsBlur = false
                try {
                    updateBlurDrawable()
                } catch (_: Throwable) {
                }
            }
            true
        }
        topScrimView.viewTreeObserver.addOnPreDrawListener(preDrawListener)
    }

    private fun boxBlurPass(pix: IntArray, tmp: IntArray, w: Int, h: Int, radius: Int) {
        if (radius <= 0 || w <= 1 || h <= 1) return
        val div = radius * 2 + 1
        // Horizontal pass
        for (y in 0 until h) {
            val rowOff = y * w
            var rSum = 0
            var gSum = 0
            var bSum = 0
            for (k in -radius..radius) {
                val c = pix[rowOff + min(w - 1, max(0, k))]
                rSum += (c ushr 16) and 0xFF
                gSum += (c ushr 8) and 0xFF
                bSum += c and 0xFF
            }
            for (x in 0 until w) {
                tmp[rowOff + x] = (0xFF shl 24) or ((rSum / div) shl 16) or ((gSum / div) shl 8) or (bSum / div)
                val addIdx = min(w - 1, x + radius + 1)
                val remIdx = max(0, x - radius)
                val cAdd = pix[rowOff + addIdx]
                val cRem = pix[rowOff + remIdx]
                rSum += ((cAdd ushr 16) and 0xFF) - ((cRem ushr 16) and 0xFF)
                gSum += ((cAdd ushr 8) and 0xFF) - ((cRem ushr 8) and 0xFF)
                bSum += (cAdd and 0xFF) - (cRem and 0xFF)
            }
        }
        // Vertical pass
        for (x in 0 until w) {
            var rSum = 0
            var gSum = 0
            var bSum = 0
            for (k in -radius..radius) {
                val c = tmp[min(h - 1, max(0, k)) * w + x]
                rSum += (c ushr 16) and 0xFF
                gSum += (c ushr 8) and 0xFF
                bSum += c and 0xFF
            }
            for (y in 0 until h) {
                pix[y * w + x] = (0xFF shl 24) or ((rSum / div) shl 16) or ((gSum / div) shl 8) or (bSum / div)
                val addIdx = min(h - 1, y + radius + 1)
                val remIdx = max(0, y - radius)
                val cAdd = tmp[addIdx * w + x]
                val cRem = tmp[remIdx * w + x]
                rSum += ((cAdd ushr 16) and 0xFF) - ((cRem ushr 16) and 0xFF)
                gSum += ((cAdd ushr 8) and 0xFF) - ((cRem ushr 8) and 0xFF)
                bSum += (cAdd and 0xFF) - (cRem and 0xFF)
            }
        }
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
        val isDark = ThemeHelper.isNightMode(activity)
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = !isDark
            isAppearanceLightNavigationBars = !isDark
        }
        ViewCompat.setOnApplyWindowInsetsListener(rootView) { v, windowInsets ->
            val insets = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(insets.left, insets.top, insets.right, insets.bottom)
            windowInsets
        }
        ViewCompat.requestApplyInsets(rootView)
    }
}
