package com.inflow.premium.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.View
import com.inflow.premium.data.CategoryStockSlice
import kotlin.math.min

class CategoryDonutView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val slices = mutableListOf<CategoryStockSlice>()
    private val oval = RectF()
    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        color = Color.parseColor("#F1F5F9")
    }
    private val arcPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.BUTT
    }
    private val pctPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1E293B")
        textAlign = Paint.Align.CENTER
        typeface = Typeface.DEFAULT_BOLD
        textSize = 14f * resources.displayMetrics.scaledDensity
    }
    private val subPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#94A3B8")
        textAlign = Paint.Align.CENTER
        textSize = 9.5f * resources.displayMetrics.scaledDensity
    }

    fun setData(data: List<CategoryStockSlice>) {
        slices.clear()
        slices.addAll(data)
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val size = min(width, height).toFloat()
        if (size <= 0f) return

        val strokeW = size * 0.17f
        bgPaint.strokeWidth = strokeW
        arcPaint.strokeWidth = strokeW

        val halfStroke = strokeW / 2f + 2f
        val left = (width - size) / 2f + halfStroke
        val top = (height - size) / 2f + halfStroke
        val right = (width + size) / 2f - halfStroke
        val bottom = (height + size) / 2f - halfStroke
        oval.set(left, top, right, bottom)

        canvas.drawArc(oval, 0f, 360f, false, bgPaint)

        if (slices.isEmpty()) return

        var startAngle = -90f
        for (i in slices.indices) {
            val s = slices[i]
            val sweep = ((s.pct / 100.0) * 360.0).toFloat()
            if (sweep > 0.2f) {
                arcPaint.color = COLORS[i % COLORS.size]
                canvas.drawArc(oval, startAngle, sweep, false, arcPaint)
                startAngle += sweep
            }
        }

        val topSlice = slices.first()
        val cx = width / 2f
        val cy = height / 2f
        canvas.drawText("${Math.round(topSlice.pct)}%", cx, cy + 2f * resources.displayMetrics.density, pctPaint)
        val shortName = if (topSlice.name.length > 9) topSlice.name.take(8) + "…" else topSlice.name
        canvas.drawText(shortName, cx, cy + 14f * resources.displayMetrics.density, subPaint)
    }

    companion object {
        val COLORS = intArrayOf(
            Color.parseColor("#0284C7"),
            Color.parseColor("#10B981"),
            Color.parseColor("#F59E0B"),
            Color.parseColor("#EC4899"),
            Color.parseColor("#8B5CF6"),
            Color.parseColor("#06B6D4"),
            Color.parseColor("#64748B")
        )
    }
}
