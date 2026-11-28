package com.inflow.premium

import android.app.Application
import com.inflow.premium.data.SessionManager
import com.inflow.premium.ui.ThemeHelper

class InFlowApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val session = SessionManager(this)
        ThemeHelper.apply(session.themeMode)
    }
}
