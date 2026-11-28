package com.inflow.premium.ui

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.content.pm.PackageInfoCompat
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.inflow.premium.data.ApiClient
import com.inflow.premium.data.AppUpdateInfo
import com.inflow.premium.data.SessionManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

object InAppUpdater {

    private var sessionCheckedOnce = false
    private var pendingApkFile: File? = null
    private var awaitingInstallPermission = false

    private val downloadClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    fun checkIfNeededOnce(
        activity: Activity,
        session: SessionManager,
        api: ApiClient,
        scope: CoroutineScope
    ) {
        cleanupCachedUpdates(activity)
        if (!session.autoOtaUpdate || sessionCheckedOnce) return
        sessionCheckedOnce = true
        checkForUpdate(activity, session, api, scope, quietIfLatest = true)
    }

    fun checkForUpdate(
        activity: Activity,
        session: SessionManager,
        api: ApiClient,
        scope: CoroutineScope,
        quietIfLatest: Boolean
    ) {
        scope.launch {
            try {
                val info = api.checkAppUpdate()
                if (activity.isFinishing || activity.isDestroyed) return@launch

                val pInfo = activity.packageManager.getPackageInfo(activity.packageName, 0)
                val currentCode = PackageInfoCompat.getLongVersionCode(pInfo).toInt()
                val currentName = pInfo.versionName ?: "1.0.0"

                if (!info.apkAvailable || info.versionCode <= currentCode) {
                    if (!quietIfLatest) {
                        LiquidGlassDialog.builder(activity)
                            .setTitle("Up to Date")
                            .setMessage("You are already on the latest version (v$currentName).")
                            .setPositiveButton("OK", null)
                            .show()
                    }
                    return@launch
                }

                if (quietIfLatest && session.dismissedOtaVersionCode == info.versionCode) {
                    return@launch
                }

                val msg = buildString {
                    append("A new version v${info.versionName} (${info.apkSizeMb}) is ready to update directly in-app.\n\n")
                    append("Installed: v$currentName")
                    if (info.releaseNotes.isNotBlank()) {
                        append("\n\nWhat's new:\n${info.releaseNotes}")
                    }
                }

                LiquidGlassDialog.builder(activity)
                    .setTitle("OTA Update Available")
                    .setMessage(msg)
                    .setPositiveButton("Update Now") { _, _ ->
                        startInAppDownload(activity, session, info, scope)
                    }
                    .setNegativeButton("Later") { _, _ ->
                        session.dismissedOtaVersionCode = info.versionCode
                    }
                    .show()
            } catch (e: Exception) {
                if (!quietIfLatest && !activity.isFinishing && !activity.isDestroyed) {
                    Toast.makeText(activity, e.message ?: "Update check failed", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    private fun startInAppDownload(
        activity: Activity,
        session: SessionManager,
        info: AppUpdateInfo,
        scope: CoroutineScope
    ) {
        val dp = activity.resources.displayMetrics.density
        val pad = (20 * dp).toInt()
        val box = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, (12 * dp).toInt(), pad, (12 * dp).toInt())
        }
        val tvProgress = TextView(activity).apply {
            text = "Connecting to server..."
            setTextColor(Color.parseColor("#0F172A"))
            textSize = 13.5f
        }
        val progressBar = ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progress = 0
            isIndeterminate = true
            setPadding(0, (12 * dp).toInt(), 0, 0)
        }
        box.addView(tvProgress)
        box.addView(progressBar)

        val progressDlg = LiquidGlassDialog.builder(activity)
            .setTitle("Updating to v${info.versionName}")
            .setView(box)
            .setCancelable(false)
            .create()
        progressDlg.show()

        scope.launch {
            try {
                val apkFile = withContext(Dispatchers.IO) {
                    val base = session.baseUrl.trimEnd('/')
                    val url = if (info.apkUrl.startsWith("http")) info.apkUrl else "$base${info.apkUrl}"
                    val req = Request.Builder().url(url).get().build()
                    downloadClient.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) {
                            throw IllegalStateException("Download failed (HTTP ${resp.code})")
                        }
                        val body = resp.body ?: throw IllegalStateException("Empty update package")
                        val total = body.contentLength().takeIf { it > 0 } ?: info.apkSizeBytes

                        val outDir = File(activity.cacheDir, "updates").apply { mkdirs() }
                        val outFile = File(outDir, "inFlow-Premium-update.apk")
                        if (outFile.exists()) outFile.delete()

                        body.byteStream().use { input ->
                            FileOutputStream(outFile).use { output ->
                                val buf = ByteArray(16 * 1024)
                                var downloaded = 0L
                                var lastPct = -1
                                while (true) {
                                    val read = input.read(buf)
                                    if (read <= 0) break
                                    output.write(buf, 0, read)
                                    downloaded += read
                                    if (total > 0) {
                                        val pct = ((downloaded * 100) / total).toInt().coerceIn(0, 100)
                                        if (pct != lastPct) {
                                            lastPct = pct
                                            val dlMb = downloaded / (1024.0 * 1024.0)
                                            val totMb = total / (1024.0 * 1024.0)
                                            withContext(Dispatchers.Main) {
                                                if (progressDlg.isShowing) {
                                                    progressBar.isIndeterminate = false
                                                    progressBar.progress = pct
                                                    tvProgress.text = String.format(
                                                        "Downloading in-app update... %d%% (%.1f / %.1f MB)",
                                                        pct, dlMb, totMb
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                                output.flush()
                            }
                        }
                        if (outFile.length() < 100_000L) {
                            throw IllegalStateException("Downloaded package appears incomplete")
                        }
                        outFile
                    }
                }

                if (progressDlg.isShowing) progressDlg.dismiss()
                if (!activity.isFinishing && !activity.isDestroyed) {
                    launchPackageInstaller(activity, apkFile)
                }
            } catch (e: Exception) {
                if (progressDlg.isShowing) progressDlg.dismiss()
                if (!activity.isFinishing && !activity.isDestroyed) {
                    LiquidGlassDialog.builder(activity)
                        .setTitle("Update Failed")
                        .setMessage(e.message ?: "Could not complete direct update.")
                        .setPositiveButton("Close", null)
                        .show()
                }
            }
        }
    }

    fun resumePendingInstall(activity: Activity) {
        val pending = pendingApkFile ?: return
        if (!awaitingInstallPermission) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !activity.packageManager.canRequestPackageInstalls()) {
            return
        }
        awaitingInstallPermission = false
        pendingApkFile = null
        launchPackageInstaller(activity, pending)
    }

    private fun launchPackageInstaller(activity: Activity, apkFile: File) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !activity.packageManager.canRequestPackageInstalls()) {
            pendingApkFile = apkFile
            awaitingInstallPermission = true
            LiquidGlassDialog.builder(activity)
                .setTitle("Allow In-App Updates")
                .setMessage("Enable \"Allow from this source\" once so inFlow Premium can install Over-the-Air updates directly.")
                .setPositiveButton("Allow") { _, _ ->
                    val intent = Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:${activity.packageName}")
                    )
                    activity.startActivity(intent)
                }
                .setNegativeButton("Cancel") { _, _ ->
                    awaitingInstallPermission = false
                    pendingApkFile = null
                }
                .show()
            return
        }

        val apkUri = FileProvider.getUriForFile(
            activity,
            "${activity.packageName}.fileprovider",
            apkFile
        )
        val installIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(apkUri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        activity.startActivity(installIntent)
    }

    private fun cleanupCachedUpdates(activity: Activity) {
        try {
            val dir = File(activity.cacheDir, "updates")
            if (dir.exists()) {
                dir.listFiles()?.forEach { f ->
                    if (System.currentTimeMillis() - f.lastModified() > 24 * 60 * 60 * 1000L) {
                        f.delete()
                    }
                }
            }
        } catch (_: Exception) {}
    }
}
