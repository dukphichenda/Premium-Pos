package com.inflow.premium.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import com.inflow.premium.data.MonthlyChartPoint
import kotlin.math.max

class MonthlySalesChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val points = mutableListOf<MonthlyChartPoint>()

    private val axisPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E2E8F0")
        strokeWidth = 2f
    }
    private val paidPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#0EA5E9")
    }
    private val openPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#F59E0B")
    }
    private val profitPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#10B981")
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#94A3B8")
        textAlign = Paint.Align.CENTER
        textSize = 9.5f * resources.displayMetrics.scaledDensity
    }
    private val rect = RectF()

    fun setData(data: List<MonthlyChartPoint>) {
        points.clear()
        points.addAll(data)
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        val bottomLabelH = 22f * resources.displayMetrics.density
        val chartBottom = h - bottomLabelH
        val chartTop = 8f * resources.displayMetrics.density
        val availH = (chartBottom - chartTop).coerceAtLeast(10f)

        canvas.drawLine(0f, chartBottom, w, chartBottom, axisPaint)

        if (points.isEmpty()) return

        val maxVal = max(
            1.0,
            points.maxOf { max(it.paidSales, max(it.openSales, max(0.0, it.profit))) }
        )

        val count = points.size
        val slotW = w / count.toFloat()
        val corner = 3f * resources.displayMetrics.density

        for (i in points.indices) {
            val pt = points[i]
            val slotLeft = i * slotW
            val centerX = slotLeft + slotW / 2f

            val hasProfit = pt.profit > 0.01
            val hasOpen = pt.openSales > 0.01
            val barCount = 1 + (if (hasOpen) 1 else 0) + (if (hasProfit) 1 else 0)
            val gap = 1.5f * resources.displayMetrics.density
            val maxBarW = 8f * resources.displayMetrics.density
            val barW = ((slotW * 0.72f - gap * (barCount - 1)) / barCount).coerceIn(3f, maxBarW)
            val groupW = barCount * barW + (barCount - 1) * gap
            var curX = centerX - groupW / 2f

            fun drawBar(value: Double, paint: Paint) {
                val barH = ((value / maxVal).coerceIn(0.0, 1.0) * availH).toFloat()
                    .coerceAtLeast(if (value > 0.0) 3f else 0f)
                if (barH > 0f) {
                    rect.set(curX, chartBottom - barH, curX + barW, chartBottom)
                    canvas.drawRoundRect(rect, corner, corner, paint)
                }
                curX += barW + gap
            }

            drawBar(pt.paidSales, paidPaint)
            if (hasOpen) drawBar(pt.openSales, openPaint)
            if (hasProfit) drawBar(pt.profit, profitPaint)

            if (count <= 7 || i % 2 == 0 || i == count - 1) {
                labelPaint.color = if (i == count - 1) Color.parseColor("#334155") else Color.parseColor("#94A3B8")
                canvas.drawText(pt.label, centerX, h - 4f * resources.displayMetrics.density, labelPaint)
            }
        }
    }
}
