package com.inflow.premium.ui

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import com.inflow.premium.data.MonthlyChartPoint
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max

class MonthlySalesChartView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyleAttr: Int = 0
) : View(context, attrs, defStyleAttr) {

    private val points = mutableListOf<MonthlyChartPoint>()
    private var selectedIndex: Int = -1

    private val touchSlop = ViewConfiguration.get(context).scaledTouchSlop
    private var downX = 0f
    private var downY = 0f
    private var isHorizontalDrag = false

    private val moneyFmt = DecimalFormat("$#,##0.00;-$#,##0.00", DecimalFormatSymbols(Locale.US))

    private val axisPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#E2E8F0")
        strokeWidth = 2f
    }
    private val highlightBandPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#EFF6FF")
    }
    private val guideLinePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#94A3B8")
        strokeWidth = 1.2f * resources.displayMetrics.density
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

    private val tooltipBgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.argb(244, 15, 23, 42) // #0F172A
    }
    private val tooltipBorderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#334155")
        style = Paint.Style.STROKE
        strokeWidth = 1f * resources.displayMetrics.density
    }
    private val tooltipTitlePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        textSize = 10.5f * resources.displayMetrics.scaledDensity
    }
    private val tooltipLabelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#CBD5E1")
        textSize = 9.5f * resources.displayMetrics.scaledDensity
    }
    private val tooltipValuePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        textAlign = Paint.Align.RIGHT
        textSize = 9.5f * resources.displayMetrics.scaledDensity
    }
    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    private val rect = RectF()
    private val tooltipRect = RectF()

    fun setData(data: List<MonthlyChartPoint>) {
        points.clear()
        points.addAll(data)
        selectedIndex = -1
        invalidate()
    }

    private fun indexForX(x: Float): Int {
        if (points.isEmpty() || width <= 0) return -1
        val slotW = width.toFloat() / points.size.toFloat()
        return (x / slotW).toInt().coerceIn(0, points.lastIndex)
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (points.isEmpty() || width <= 0) return super.onTouchEvent(event)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.x
                downY = event.y
                isHorizontalDrag = false
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = abs(event.x - downX)
                val dy = abs(event.y - downY)
                if (!isHorizontalDrag && dx > touchSlop && dx > dy * 1.15f) {
                    isHorizontalDrag = true
                    parent?.requestDisallowInterceptTouchEvent(true)
                }
                if (isHorizontalDrag) {
                    val idx = indexForX(event.x)
                    if (idx != selectedIndex) {
                        selectedIndex = idx
                        invalidate()
                    }
                    return true
                }
            }
            MotionEvent.ACTION_UP -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                if (isHorizontalDrag) {
                    isHorizontalDrag = false
                    return true
                }
                val dx = abs(event.x - downX)
                val dy = abs(event.y - downY)
                if (dx <= touchSlop * 2f && dy <= touchSlop * 2f) {
                    val tapped = indexForX(event.x)
                    selectedIndex = if (selectedIndex == tapped) -1 else tapped
                    performClick()
                    invalidate()
                    return true
                }
            }
            MotionEvent.ACTION_CANCEL -> {
                parent?.requestDisallowInterceptTouchEvent(false)
                isHorizontalDrag = false
            }
        }
        return super.onTouchEvent(event)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 0f || h <= 0f) return

        val d = resources.displayMetrics.density
        val bottomLabelH = 22f * d
        val chartBottom = h - bottomLabelH
        val chartTop = 10f * d
        val availH = (chartBottom - chartTop).coerceAtLeast(10f)

        canvas.drawLine(0f, chartBottom, w, chartBottom, axisPaint)

        if (points.isEmpty()) return

        val maxVal = max(
            1.0,
            points.maxOf { max(it.paidSales, max(it.openSales, max(0.0, it.profit))) }
        )

        val count = points.size
        val slotW = w / count.toFloat()
        val corner = 3f * d
        val hasSelection = selectedIndex in points.indices
        var selectedCenterX = 0f
        var selectedGroupTopY = chartBottom

        for (i in points.indices) {
            val pt = points[i]
            val slotLeft = i * slotW
            val centerX = slotLeft + slotW / 2f
            val isSelected = i == selectedIndex

            if (isSelected) {
                val pad = (slotW * 0.08f).coerceAtLeast(2f * d)
                rect.set(slotLeft + pad, chartTop, slotLeft + slotW - pad, chartBottom)
                canvas.drawRoundRect(rect, 6f * d, 6f * d, highlightBandPaint)
                selectedCenterX = centerX
            }

            val barAlpha = if (!hasSelection || isSelected) 255 else 95
            paidPaint.alpha = barAlpha
            openPaint.alpha = barAlpha
            profitPaint.alpha = barAlpha

            val hasProfit = pt.profit > 0.01
            val hasOpen = pt.openSales > 0.01
            val barCount = 1 + (if (hasOpen) 1 else 0) + (if (hasProfit) 1 else 0)
            val gap = 1.5f * d
            val maxBarW = 8f * d
            val barW = ((slotW * 0.72f - gap * (barCount - 1)) / barCount).coerceIn(3f, maxBarW)
            val groupW = barCount * barW + (barCount - 1) * gap
            var curX = centerX - groupW / 2f
            var groupMinTop = chartBottom

            fun drawBar(value: Double, paint: Paint) {
                val barH = ((value / maxVal).coerceIn(0.0, 1.0) * availH).toFloat()
                    .coerceAtLeast(if (value > 0.0) 3f else 0f)
                if (barH > 0f) {
                    val topY = chartBottom - barH
                    if (topY < groupMinTop) groupMinTop = topY
                    rect.set(curX, topY, curX + barW, chartBottom)
                    canvas.drawRoundRect(rect, corner, corner, paint)
                }
                curX += barW + gap
            }

            drawBar(pt.paidSales, paidPaint)
            if (hasOpen) drawBar(pt.openSales, openPaint)
            if (hasProfit) drawBar(pt.profit, profitPaint)

            if (isSelected) {
                selectedGroupTopY = groupMinTop
            }

            if (isSelected || count <= 7 || i % 2 == 0 || i == count - 1) {
                labelPaint.color = when {
                    isSelected -> Color.parseColor("#0F172A")
                    i == count - 1 -> Color.parseColor("#334155")
                    else -> Color.parseColor("#94A3B8")
                }
                labelPaint.typeface = if (isSelected) {
                    Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
                } else {
                    Typeface.DEFAULT
                }
                canvas.drawText(pt.label, centerX, h - 4f * d, labelPaint)
            }
        }

        // Reset paint alphas cleanly
        paidPaint.alpha = 255
        openPaint.alpha = 255
        profitPaint.alpha = 255
        labelPaint.typeface = Typeface.DEFAULT

        if (hasSelection) {
            drawTooltip(canvas, points[selectedIndex], selectedCenterX, selectedGroupTopY, w, d)
        }
    }

    private fun drawTooltip(
        canvas: Canvas,
        pt: MonthlyChartPoint,
        centerX: Float,
        barTopY: Float,
        viewW: Float,
        d: Float
    ) {
        val title = pt.monthLabel.ifBlank { pt.label }
        val rows = mutableListOf<Triple<Int, String, String>>()
        rows.add(Triple(Color.parseColor("#38BDF8"), "Paid", moneyFmt.format(pt.paidSales)))
        if (pt.openSales > 0.01) {
            rows.add(Triple(Color.parseColor("#FBBF24"), "Open", moneyFmt.format(pt.openSales)))
        }
        rows.add(Triple(Color.parseColor("#34D399"), "Profit", moneyFmt.format(pt.profit)))

        val padH = 9f * d
        val padV = 6f * d
        val dotR = 3f * d
        val rowGap = 3.5f * d
        val headerGap = 5f * d

        val titleFm = tooltipTitlePaint.fontMetrics
        val titleH = titleFm.descent - titleFm.ascent
        val rowFm = tooltipLabelPaint.fontMetrics
        val rowH = rowFm.descent - rowFm.ascent

        var maxRowW = tooltipTitlePaint.measureText(title)
        for ((_, label, value) in rows) {
            val lw = dotR * 2f + 5f * d + tooltipLabelPaint.measureText(label)
            val vw = tooltipValuePaint.measureText(value)
            val totalRowW = lw + 12f * d + vw
            if (totalRowW > maxRowW) maxRowW = totalRowW
        }

        val boxW = (maxRowW + padH * 2f).coerceAtLeast(112f * d).coerceAtMost(viewW - 8f * d)
        val boxH = padV * 2f + titleH + headerGap + rows.size * rowH + (rows.size - 1) * rowGap

        val boxLeft = (centerX - boxW / 2f).coerceIn(4f * d, (viewW - boxW - 4f * d).coerceAtLeast(4f * d))
        val boxTop = 2f * d
        val boxBottom = boxTop + boxH

        if (barTopY > boxBottom + 2f * d) {
            canvas.drawLine(centerX, boxBottom, centerX, barTopY - 2f * d, guideLinePaint)
        }

        tooltipRect.set(boxLeft, boxTop, boxLeft + boxW, boxBottom)
        val radius = 7f * d
        canvas.drawRoundRect(tooltipRect, radius, radius, tooltipBgPaint)
        canvas.drawRoundRect(tooltipRect, radius, radius, tooltipBorderPaint)

        var curY = boxTop + padV - titleFm.ascent
        canvas.drawText(title, boxLeft + padH, curY, tooltipTitlePaint)
        curY += titleFm.descent + headerGap - rowFm.ascent

        for (rIdx in rows.indices) {
            val (dotColor, label, value) = rows[rIdx]
            val dotCy = curY + (rowFm.ascent + rowFm.descent) / 2f
            dotPaint.color = dotColor
            canvas.drawCircle(boxLeft + padH + dotR, dotCy, dotR, dotPaint)

            canvas.drawText(label, boxLeft + padH + dotR * 2f + 5f * d, curY, tooltipLabelPaint)
            canvas.drawText(value, boxLeft + boxW - padH, curY, tooltipValuePaint)
            if (rIdx < rows.lastIndex) {
                curY += rowH + rowGap
            }
        }
    }
}
