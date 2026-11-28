package com.inflow.premium.ui

import android.content.Context
import android.content.DialogInterface
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.core.content.ContextCompat
import androidx.core.widget.NestedScrollView
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R

object LiquidGlassDialog {
    fun builder(context: Context): MaterialAlertDialogBuilder = ModernSheetDialogBuilder(context)
}

/**
 * Modern Bottom-Sheet Modal Builder matching the clean card-radio bottom sheet design:
 * - Blurred dim backdrop behind the sheet (Android 12+ hardware blur + clean dim)
 * - Rounded top-corner bottom sheet with centered drag handle, bold title & circular close (×) button
 * - Card-style radio / action / multi-choice option rows with active teal border & radio ring
 * - Full-width solid rounded CTA button at the bottom
 */
private class ModernSheetDialogBuilder(private val ctx: Context) :
    MaterialAlertDialogBuilder(ctx, R.style.ThemeOverlay_InFlow_LiquidGlassDialog) {

    private var sheetTitle: CharSequence? = null
    private var sheetMessage: CharSequence? = null
    private var sheetCustomView: View? = null

    private var singleItems: Array<CharSequence>? = null
    private var singleChecked: Int = 0
    private var singleListener: DialogInterface.OnClickListener? = null

    private var plainItems: Array<CharSequence>? = null
    private var plainListener: DialogInterface.OnClickListener? = null

    private var multiItems: Array<CharSequence>? = null
    private var multiChecked: BooleanArray? = null
    private var multiListener: DialogInterface.OnMultiChoiceClickListener? = null

    private var posText: CharSequence? = null
    private var posListener: DialogInterface.OnClickListener? = null
    private var hasPosButton: Boolean = false

    private var negText: CharSequence? = null
    private var negListener: DialogInterface.OnClickListener? = null

    private var neuText: CharSequence? = null
    private var neuListener: DialogInterface.OnClickListener? = null

    override fun setTitle(title: CharSequence?): MaterialAlertDialogBuilder {
        sheetTitle = title
        return this
    }

    override fun setTitle(titleId: Int): MaterialAlertDialogBuilder {
        sheetTitle = ctx.getString(titleId)
        return this
    }

    override fun setMessage(message: CharSequence?): MaterialAlertDialogBuilder {
        sheetMessage = message
        return this
    }

    override fun setMessage(messageId: Int): MaterialAlertDialogBuilder {
        sheetMessage = ctx.getString(messageId)
        return this
    }

    override fun setView(view: View?): MaterialAlertDialogBuilder {
        sheetCustomView = view
        return this
    }

    override fun setItems(items: Array<CharSequence>?, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        plainItems = items
        plainListener = listener
        return this
    }

    override fun setSingleChoiceItems(
        items: Array<CharSequence>?,
        checkedItem: Int,
        listener: DialogInterface.OnClickListener?
    ): MaterialAlertDialogBuilder {
        singleItems = items
        singleChecked = checkedItem.coerceAtLeast(0)
        singleListener = listener
        return this
    }

    override fun setMultiChoiceItems(
        items: Array<CharSequence>?,
        checkedItems: BooleanArray?,
        listener: DialogInterface.OnMultiChoiceClickListener?
    ): MaterialAlertDialogBuilder {
        multiItems = items
        multiChecked = checkedItems
        multiListener = listener
        return this
    }

    override fun setPositiveButton(text: CharSequence?, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        posText = text
        posListener = listener
        hasPosButton = text != null
        return this
    }

    override fun setPositiveButton(textId: Int, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        return setPositiveButton(ctx.getString(textId), listener)
    }

    override fun setNegativeButton(text: CharSequence?, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        negText = text
        negListener = listener
        return this
    }

    override fun setNegativeButton(textId: Int, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        return setNegativeButton(ctx.getString(textId), listener)
    }

    override fun setNeutralButton(text: CharSequence?, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        neuText = text
        neuListener = listener
        return this
    }

    override fun setNeutralButton(textId: Int, listener: DialogInterface.OnClickListener?): MaterialAlertDialogBuilder {
        return setNeutralButton(ctx.getString(textId), listener)
    }

    override fun create(): AlertDialog {
        val dp = ctx.resources.displayMetrics.density
        fun Int.dp(): Int = (this * dp).toInt()
        val isDark = ThemeHelper.isNightMode(ctx)

        val textPrimary = ContextCompat.getColor(ctx, R.color.text_primary)
        val textSecondary = ContextCompat.getColor(ctx, R.color.text_secondary)
        val cardBg = if (isDark) Color.parseColor("#1E293B") else Color.WHITE
        val cardStroke = if (isDark) Color.parseColor("#334155") else Color.parseColor("#E2E8F0")
        val selectedBg = if (isDark) Color.parseColor("#103235") else Color.parseColor("#F0FDFA")
        val tealAccent = if (isDark) Color.parseColor("#14B8A6") else Color.parseColor("#0A6C62")
        val ctaBg = Color.parseColor("#0A6C62")
        val closeCircleBg = if (isDark) Color.parseColor("#1E293B") else Color.parseColor("#F1F5F9")
        val handleColor = if (isDark) Color.parseColor("#475569") else Color.parseColor("#CBD5E1")

        // Preserve AlertDialog's native button bar ONLY when caller explicitly passed null listener
        // so callers that hook dlg.getButton(AlertDialog.BUTTON_POSITIVE) inside setOnShowListener keep working.
        val needsNativeButtons = hasPosButton && posListener == null

        val root = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(20.dp(), 12.dp(), 20.dp(), if (needsNativeButtons) 8.dp() else 22.dp())
        }

        // Top drag handle bar
        val handle = View(ctx).apply {
            layoutParams = LinearLayout.LayoutParams(42.dp(), 4.dp()).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = 14.dp()
            }
            background = GradientDrawable().apply {
                cornerRadius = 999f
                setColor(handleColor)
            }
        }
        root.addView(handle)

        var createdDialog: AlertDialog? = null

        // Header Row: Bold Title + Circular Close (×) Button
        if (!sheetTitle.isNullOrBlank()) {
            val headerRow = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = 14.dp() }
            }
            val tvTitle = TextView(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                text = sheetTitle
                setTextColor(textPrimary)
                textSize = 18f
                setTypeface(null, Typeface.BOLD)
            }
            val btnClose = TextView(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(32.dp(), 32.dp()).apply { marginStart = 10.dp() }
                gravity = Gravity.CENTER
                text = "✕"
                setTextColor(textSecondary)
                textSize = 13f
                setTypeface(null, Typeface.BOLD)
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(closeCircleBg)
                }
                isClickable = true
                isFocusable = true
                setOnClickListener {
                    val d = createdDialog
                    if (d != null) {
                        negListener?.onClick(d, DialogInterface.BUTTON_NEGATIVE)
                        d.dismiss()
                    }
                }
            }
            headerRow.addView(tvTitle)
            headerRow.addView(btnClose)
            root.addView(headerRow)
        }

        // Optional Message
        if (!sheetMessage.isNullOrBlank()) {
            root.addView(TextView(ctx).apply {
                text = sheetMessage
                setTextColor(textSecondary)
                textSize = 14f
                setLineSpacing(4f, 1.1f)
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { bottomMargin = 14.dp() }
            })
        }

        // Scrollable Body Container (caps tall lists gracefully)
        val maxScrollH = (ctx.resources.displayMetrics.heightPixels * 0.56f).toInt()
        val scrollWrap = NestedScrollView(ctx).apply {
            isFillViewport = false
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        }
        val bodyList = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
        }
        scrollWrap.addView(bodyList)

        var selectedIdx = singleChecked
        var hasScrollBody = false

        fun makeOptionCardBg(selected: Boolean): GradientDrawable = GradientDrawable().apply {
            cornerRadius = 14.dp().toFloat()
            setColor(if (selected) selectedBg else cardBg)
            setStroke(if (selected) 2.dp() else 1.dp(), if (selected) tealAccent else cardStroke)
        }

        fun makeRadioIndicator(selected: Boolean): View {
            val outer = FrameLayout(ctx).apply {
                layoutParams = LinearLayout.LayoutParams(22.dp(), 22.dp())
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setColor(Color.TRANSPARENT)
                    setStroke(if (selected) 2.dp() else 1.5f.let { (it * dp).toInt().coerceAtLeast(1) }, if (selected) tealAccent else cardStroke)
                }
            }
            if (selected) {
                outer.addView(View(ctx).apply {
                    layoutParams = FrameLayout.LayoutParams(10.dp(), 10.dp(), Gravity.CENTER)
                    background = GradientDrawable().apply {
                        shape = GradientDrawable.OVAL
                        setColor(tealAccent)
                    }
                })
            }
            return outer
        }

        // 1. Single-Choice Radio Cards (Exact Image 3 Style)
        singleItems?.let { items ->
            hasScrollBody = true
            val rowRefs = mutableListOf<Triple<LinearLayout, TextView, FrameLayout>>()
            fun refreshRadioStates() {
                rowRefs.forEachIndexed { i, (row, tv, indHost) ->
                    val isSel = i == selectedIdx
                    row.background = makeOptionCardBg(isSel)
                    tv.setTextColor(if (isSel) tealAccent else textPrimary)
                    tv.setTypeface(null, if (isSel) Typeface.BOLD else Typeface.NORMAL)
                    indHost.removeAllViews()
                    indHost.addView(makeRadioIndicator(isSel))
                }
            }
            items.forEachIndexed { idx, label ->
                val row = LinearLayout(ctx).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = Gravity.CENTER_VERTICAL
                    setPadding(16.dp(), 14.dp(), 16.dp(), 14.dp())
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply { bottomMargin = 10.dp() }
                    isClickable = true
                    isFocusable = true
                }
                val tv = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    text = label
                    textSize = 14.5f
                }
                val indHost = FrameLayout(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(22.dp(), 22.dp()).apply { marginStart = 12.dp() }
                }
                row.addView(tv)
                row.addView(indHost)
                row.setOnClickListener {
                    selectedIdx = idx
                    refreshRadioStates()
                }
                rowRefs.add(Triple(row, tv, indHost))
                bodyList.addView(row)
            }
            refreshRadioStates()
        }

        // 2. Plain Action Cards (e.g., Product Filters)
        plainItems?.let { items ->
            hasScrollBody = true
            items.forEachIndexed { idx, label ->
                val row = LinearLayout(ctx).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = Gravity.CENTER_VERTICAL
                    setPadding(16.dp(), 14.dp(), 16.dp(), 14.dp())
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply { bottomMargin = 10.dp() }
                    background = makeOptionCardBg(false)
                    isClickable = true
                    isFocusable = true
                }
                val tv = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    text = label
                    setTextColor(textPrimary)
                    textSize = 14.5f
                    setTypeface(null, Typeface.BOLD)
                }
                val chev = TextView(ctx).apply {
                    text = "›"
                    setTextColor(textSecondary)
                    textSize = 18f
                    setTypeface(null, Typeface.BOLD)
                    layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
                        marginStart = 10.dp()
                    }
                }
                row.addView(tv)
                row.addView(chev)
                row.setOnClickListener {
                    createdDialog?.let { d ->
                        plainListener?.onClick(d, idx)
                        if (d.isShowing) d.dismiss()
                    }
                }
                bodyList.addView(row)
            }
        }

        // 3. Multi-Choice Toggle Cards
        multiItems?.let { items ->
            hasScrollBody = true
            val checks = multiChecked ?: BooleanArray(items.size)
            items.forEachIndexed { idx, label ->
                val row = LinearLayout(ctx).apply {
                    orientation = LinearLayout.HORIZONTAL
                    gravity = Gravity.CENTER_VERTICAL
                    setPadding(16.dp(), 13.dp(), 16.dp(), 13.dp())
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT
                    ).apply { bottomMargin = 9.dp() }
                    isClickable = true
                    isFocusable = true
                }
                val tv = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    text = label
                    textSize = 14f
                }
                val badge = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(22.dp(), 22.dp()).apply { marginStart = 10.dp() }
                    gravity = Gravity.CENTER
                    textSize = 12f
                    setTypeface(null, Typeface.BOLD)
                }
                fun syncRow() {
                    val sel = checks[idx]
                    row.background = makeOptionCardBg(sel)
                    tv.setTextColor(if (sel) tealAccent else textPrimary)
                    tv.setTypeface(null, if (sel) Typeface.BOLD else Typeface.NORMAL)
                    badge.text = if (sel) "✓" else ""
                    badge.setTextColor(Color.WHITE)
                    badge.background = GradientDrawable().apply {
                        cornerRadius = 6.dp().toFloat()
                        setColor(if (sel) tealAccent else Color.TRANSPARENT)
                        setStroke(if (sel) 0 else 1.5f.let { (it * dp).toInt().coerceAtLeast(1) }, cardStroke)
                    }
                }
                syncRow()
                row.addView(tv)
                row.addView(badge)
                row.setOnClickListener {
                    checks[idx] = !checks[idx]
                    syncRow()
                    createdDialog?.let { d -> multiListener?.onClick(d, idx, checks[idx]) }
                }
                bodyList.addView(row)
            }
        }

        if (hasScrollBody) {
            scrollWrap.addOnLayoutChangeListener { v, _, _, _, _, _, _, _, _ ->
                if (v.height > maxScrollH) {
                    val lp = v.layoutParams
                    lp.height = maxScrollH
                    v.layoutParams = lp
                }
            }
            root.addView(scrollWrap)
        }

        // 4. Custom View (kept outside NestedScrollView so inner RecyclerViews / ScrollViews measure & scroll natively)
        sheetCustomView?.let { custom ->
            (custom.parent as? ViewGroup)?.removeView(custom)
            root.addView(custom)
        }

        // Bottom CTA Buttons (Image 3 Full-Width Rounded Pill Button)
        if (!needsNativeButtons) {
            val primaryLabel = when {
                !posText.isNullOrBlank() -> posText.toString()
                singleItems != null -> "Apply"
                else -> null
            }

            if (primaryLabel != null) {
                val btnPrimary = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        48.dp()
                    ).apply { topMargin = 8.dp() }
                    gravity = Gravity.CENTER
                    text = primaryLabel
                    setTextColor(Color.WHITE)
                    textSize = 14.5f
                    setTypeface(null, Typeface.BOLD)
                    background = GradientDrawable().apply {
                        cornerRadius = 14.dp().toFloat()
                        setColor(ctaBg)
                    }
                    isClickable = true
                    isFocusable = true
                    setOnClickListener {
                        val d = createdDialog ?: return@setOnClickListener
                        if (singleItems != null && singleListener != null) {
                            singleListener?.onClick(d, selectedIdx)
                        }
                        if (posListener != null) {
                            posListener?.onClick(d, DialogInterface.BUTTON_POSITIVE)
                        }
                        if (d.isShowing) d.dismiss()
                    }
                }
                root.addView(btnPrimary)
            }

            if (!neuText.isNullOrBlank()) {
                val btnNeutral = TextView(ctx).apply {
                    layoutParams = LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        44.dp()
                    ).apply { topMargin = 8.dp() }
                    gravity = Gravity.CENTER
                    text = neuText
                    setTextColor(tealAccent)
                    textSize = 13.5f
                    setTypeface(null, Typeface.BOLD)
                    background = GradientDrawable().apply {
                        cornerRadius = 14.dp().toFloat()
                        setColor(selectedBg)
                        setStroke(1.dp(), tealAccent)
                    }
                    isClickable = true
                    isFocusable = true
                    setOnClickListener {
                        val d = createdDialog ?: return@setOnClickListener
                        neuListener?.onClick(d, DialogInterface.BUTTON_NEUTRAL)
                        if (d.isShowing) d.dismiss()
                    }
                }
                root.addView(btnNeutral)
            }
        } else {
            super.setPositiveButton(posText, null)
            if (negText != null) super.setNegativeButton(negText, negListener)
            if (neuText != null) super.setNeutralButton(neuText, neuListener)
        }

        super.setView(root)
        val surfaceBg = ContextCompat.getDrawable(ctx, R.drawable.bg_bottom_sheet_surface)
        if (surfaceBg != null) {
            super.setBackground(surfaceBg)
        }

        val dialog = super.create()
        createdDialog = dialog
        root.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(v: View) {
                applyBottomSheetWindow(dialog, surfaceBg)
            }
            override fun onViewDetachedFromWindow(v: View) = Unit
        })
        applyBottomSheetWindow(dialog, surfaceBg)
        return dialog
    }

    override fun show(): AlertDialog {
        val dialog = super.show()
        applyBottomSheetWindow(dialog, ContextCompat.getDrawable(ctx, R.drawable.bg_bottom_sheet_surface))
        return dialog
    }

    private fun applyBottomSheetWindow(dialog: AlertDialog, surfaceBg: android.graphics.drawable.Drawable?) {
        val dp = ctx.resources.displayMetrics.density
        dialog.window?.let { win ->
            if (surfaceBg != null) win.setBackgroundDrawable(surfaceBg)
            win.setGravity(Gravity.BOTTOM)
            win.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            win.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            win.setDimAmount(0.36f)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                win.addFlags(WindowManager.LayoutParams.FLAG_BLUR_BEHIND)
                win.attributes = win.attributes.apply {
                    blurBehindRadius = (26 * dp).toInt()
                }
            }
        }
    }
}
