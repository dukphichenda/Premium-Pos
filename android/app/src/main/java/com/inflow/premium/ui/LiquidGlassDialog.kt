package com.inflow.premium.ui

import android.content.Context
import android.graphics.drawable.InsetDrawable
import androidx.core.content.ContextCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.R

object LiquidGlassDialog {
    fun builder(context: Context): MaterialAlertDialogBuilder {
        val b = MaterialAlertDialogBuilder(context, R.style.ThemeOverlay_InFlow_LiquidGlassDialog)
        val glass = ContextCompat.getDrawable(context, R.drawable.bg_liquid_glass_dialog)
        if (glass != null) {
            val inset = (16 * context.resources.displayMetrics.density).toInt()
            b.setBackground(InsetDrawable(glass, inset, inset, inset, inset))
        }
        return b
    }
}
