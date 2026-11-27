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
                val targetH = topInset + dp(56)
                if (lp.height != targetH) {
                    lp.height = targetH
                    v.layoutParams = lp
                }
            }

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
        ViewCompat.requestApplyInsets(rootView)

        if (topScrimView != null && scrollableView != null) {
            installTopStatusBlur(topScrimView, scrollableView)
        }
    }

    /**
     * Real-time Telegram-style frosted blur across the status bar region:
     * samples only [scrollableView] underneath [topScrimView] at 1/8 resolution,
     * applies a fast dual box-blur + smooth top-to-bottom fade mask so scrolled text/cards
     * soften into translucent frosted glass beneath status bar icons.
     */
    private fun installTopStatusBlur(topScrimView: View, scrollableView: View) {
        val scale = 0.16f
        var needsBlur = true
        var lastScrollMarker = Int.MIN_VALUE
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
        val scrollLoc = IntArray(2)

        fun updateBlurDrawable() {
            val w = topScrimView.width
            val h = topScrimView.height
            if (w <= 0 || h <= 0 || scrollableView.width <= 0 || scrollableView.height <= 0) return

            val sw = max(4, (w * scale).toInt())
            val sh = max(4, (h * scale).toInt())

            val sb = smallBmp?.takeIf { it.width == sw && it.height == sh }
                ?: Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888).also { smallBmp = it }
            val ob = outBmp?.takeIf { it.width == sw && it.height == sh }
                ?: Bitmap.createBitmap(sw, sh, Bitmap.Config.ARGB_8888).also { outBmp = it }

            topScrimView.getLocationInWindow(scrimLoc)
            scrollableView.getLocationInWindow(scrollLoc)
            val dx = (scrollLoc[0] - scrimLoc[0]).toFloat()
            val dy = (scrollLoc[1] - scrimLoc[1]).toFloat()

            val c = Canvas(sb)
            c.drawColor(Color.parseColor("#F8FAFC"))
            c.save()
            c.scale(scale, scale)
            c.translate(dx, dy)
            scrollableView.draw(c)
            c.restore()

            val len = sw * sh
            val pix = smallPixels?.takeIf { it.size == len } ?: IntArray(len).also { smallPixels = it }
            val tmp = tempPixels?.takeIf { it.size == len } ?: IntArray(len).also { tempPixels = it }
            sb.getPixels(pix, 0, sw, 0, 0, sw, sh)
            boxBlurPass(pix, tmp, sw, sh, radius = 4)
            boxBlurPass(pix, tmp, sw, sh, radius = 3)
            boxBlurPass(pix, tmp, sw, sh, radius = 2)
            sb.setPixels(pix, 0, sw, 0, 0, sw, sh)

            val outCanvas = Canvas(ob)
            outCanvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
            outCanvas.drawBitmap(sb, 0f, 0f, filterPaint)

            // More transparent frosted glass glaze combined with soft top-to-bottom gradient
            tintPaint.shader = LinearGradient(
                0f, 0f, 0f, sh.toFloat(),
                intArrayOf(
                    Color.argb(148, 255, 255, 255),
                    Color.argb(90, 248, 250, 252),
                    Color.argb(26, 248, 250, 252),
                    Color.argb(0, 248, 250, 252)
                ),
                floatArrayOf(0f, 0.45f, 0.78f, 1f),
                Shader.TileMode.CLAMP
            )
            outCanvas.drawRect(0f, 0f, sw.toFloat(), sh.toFloat(), tintPaint)

            // Smooth 5-stop feathered alpha mask so blur dissolves seamlessly without any hard line
            maskPaint.shader = LinearGradient(
                0f, 0f, 0f, sh.toFloat(),
                intArrayOf(
                    Color.argb(245, 0, 0, 0),
                    Color.argb(215, 0, 0, 0),
                    Color.argb(128, 0, 0, 0),
                    Color.argb(38, 0, 0, 0),
                    Color.argb(0, 0, 0, 0)
                ),
                floatArrayOf(0f, 0.30f, 0.60f, 0.84f, 1f),
                Shader.TileMode.CLAMP
            )
            outCanvas.drawRect(0f, 0f, sw.toFloat(), sh.toFloat(), maskPaint)

            topScrimView.background = BitmapDrawable(topScrimView.resources, ob)
        }

        scrollableView.setOnScrollChangeListener { _, _, scrollY, _, _ ->
            if (scrollY != lastScrollMarker) {
                lastScrollMarker = scrollY
                needsBlur = true
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
        WindowInsetsControllerCompat(window, window.decorView).apply {
            isAppearanceLightStatusBars = true
            isAppearanceLightNavigationBars = true
        }
        ViewCompat.setOnApplyWindowInsetsListener(rootView) { v, windowInsets ->
            val insets = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(insets.left, insets.top, insets.right, insets.bottom)
            windowInsets
        }
        ViewCompat.requestApplyInsets(rootView)
    }
}
