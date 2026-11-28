package com.inflow.premium.ui

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityInvoicePrintBinding
import java.io.File

class InvoicePrintActivity : AppCompatActivity() {

    private lateinit var binding: ActivityInvoicePrintBinding
    private lateinit var session: SessionManager
    private var orderNumber: String = "Invoice"
    private var printUrl: String = ""
    private var telegramUrl: String = ""
    private var shareCaption: String = ""
    private var autoExportJpg: Boolean = false
    private var autoShareJpg: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityInvoicePrintBinding.inflate(layoutInflater)
        setContentView(binding.root)
        session = SessionManager(this)

        orderNumber = intent.getStringExtra(EXTRA_ORDER_NUMBER) ?: "Invoice"
        val rawPrintUrl = intent.getStringExtra(EXTRA_PRINT_URL).orEmpty()
        autoExportJpg = intent.getBooleanExtra(EXTRA_AUTO_EXPORT_JPG, false)
        autoShareJpg = intent.getBooleanExtra(EXTRA_AUTO_SHARE_JPG, false)
        val wantsAutoJpg = autoExportJpg || autoShareJpg
        val basePrintUrl = if (rawPrintUrl.startsWith("http")) rawPrintUrl else "${session.baseUrl}$rawPrintUrl"
        printUrl = if (wantsAutoJpg && basePrintUrl.isNotBlank() && !basePrintUrl.contains("autojpg=1")) {
            if (basePrintUrl.contains("?")) "$basePrintUrl&autojpg=1" else "$basePrintUrl?autojpg=1"
        } else {
            basePrintUrl
        }
        telegramUrl = intent.getStringExtra(EXTRA_TELEGRAM_URL).orEmpty()
        shareCaption = intent.getStringExtra(EXTRA_SHARE_CAPTION).orEmpty()
        val customTitle = intent.getStringExtra(EXTRA_TITLE).orEmpty()
        val customPrintBtnText = intent.getStringExtra(EXTRA_PRINT_BTN_TEXT).orEmpty()

        binding.toolbar.title = customTitle.ifBlank { "Invoice • $orderNumber" }
        if (customPrintBtnText.isNotBlank()) {
            binding.btnPrintInvoice.text = customPrintBtnText
        }
        binding.toolbar.setNavigationOnClickListener { finish() }

        binding.webInvoice.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            useWideViewPort = true
            loadWithOverviewMode = true
            builtInZoomControls = true
            displayZoomControls = false
        }

        // Register the Gallery / Share bridge: when the web JS calls
        // AndroidGalleryBridge.saveJpg(filename, dataUrl), either save directly to Gallery
        // or open the Android system Share Sheet with the JPG image.
        binding.webInvoice.addJavascriptInterface(
            GallerySaver.AndroidGalleryBridge(
                context = this,
                saveToGallery = !autoShareJpg,
                onCompleteWithFile = { ok, info, cachedFile ->
                    if (autoShareJpg) {
                        if (ok && cachedFile != null) {
                            launchImageShareChooser(cachedFile)
                            Handler(Looper.getMainLooper()).postDelayed({ finish() }, 400)
                        } else {
                            Toast.makeText(this, "Share failed: $info", Toast.LENGTH_LONG).show()
                        }
                    } else {
                        val msg = if (ok) "Saved $info to Gallery!" else "Export failed: $info"
                        Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
                        if (autoExportJpg) {
                            Handler(Looper.getMainLooper()).postDelayed({ finish() }, 1200)
                        }
                    }
                }
            ),
            "AndroidGalleryBridge"
        )

        // Fallback: if the web triggers a data:image download instead of calling the bridge
        binding.webInvoice.setDownloadListener { url, _, _, _, _ ->
            if (url != null && url.startsWith("data:image/")) {
                if (autoShareJpg) {
                    val (ok, cachedFile) = GallerySaver.saveDataUrlToCache(this, "Invoice_$orderNumber.jpg", url)
                    if (ok && cachedFile != null) {
                        launchImageShareChooser(cachedFile)
                        Handler(Looper.getMainLooper()).postDelayed({ finish() }, 400)
                    } else {
                        Toast.makeText(this, "Share image failed", Toast.LENGTH_LONG).show()
                    }
                } else {
                    val (ok, info) = GallerySaver.saveDataUrlToGallery(this, "Invoice_$orderNumber.jpg", url)
                    val msg = if (ok) "Saved $info to Gallery!" else "Export failed: $info"
                    Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
                    if (autoExportJpg) {
                        Handler(Looper.getMainLooper()).postDelayed({ finish() }, 1200)
                    }
                }
            }
        }

        binding.webInvoice.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }
        }

        if (printUrl.isNotBlank()) {
            when {
                autoShareJpg -> Toast.makeText(this, "Preparing invoice image to share...", Toast.LENGTH_SHORT).show()
                autoExportJpg -> Toast.makeText(this, "Exporting invoice JPG to Gallery...", Toast.LENGTH_SHORT).show()
            }
            binding.webInvoice.loadUrl(printUrl)
        } else {
            Toast.makeText(this, "Print URL unavailable", Toast.LENGTH_SHORT).show()
        }

        binding.btnShareInvoice.setOnClickListener { shareInvoice() }
        binding.btnPrintInvoice.setOnClickListener { printWebPage() }
    }

    private fun launchImageShareChooser(file: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", file)
        val sendIntent = Intent(Intent.ACTION_SEND).apply {
            type = "image/jpeg"
            putExtra(Intent.EXTRA_STREAM, uri)
            clipData = ClipData.newRawUri("Invoice Image", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val chooser = Intent.createChooser(sendIntent, null).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(chooser)
    }

    private fun shareInvoice() {
        autoShareJpg = true
        Toast.makeText(this, "Preparing invoice image to share...", Toast.LENGTH_SHORT).show()
        binding.webInvoice.evaluateJavascript(
            """
            (function() {
                if (typeof exportInvoiceAsJpg === 'function') { exportInvoiceAsJpg(); return 'fn'; }
                var btn = document.querySelector('[onclick*="exportInvoiceAsJpg"], #btnExportJpg, .btn-export-jpg');
                if (btn) { btn.click(); return 'btn'; }
                return 'none';
            })();
            """.trimIndent()
        ) { result ->
            if (result == "\"none\"" || result == "null") {
                val base = printUrl.replace("&autojpg=1", "").replace("?autojpg=1", "")
                if (base.isNotBlank()) {
                    val reloadUrl = if (base.contains("?")) "$base&autojpg=1" else "$base?autojpg=1"
                    binding.webInvoice.loadUrl(reloadUrl)
                }
            }
        }
    }

    private fun printWebPage() {
        val printManager = getSystemService(Context.PRINT_SERVICE) as? PrintManager
        if (printManager == null) {
            Toast.makeText(this, "Print service not available", Toast.LENGTH_SHORT).show()
            return
        }
        val jobName = "inFlow_$orderNumber"
        val adapter = binding.webInvoice.createPrintDocumentAdapter(jobName)
        printManager.print(jobName, adapter, PrintAttributes.Builder().build())
    }

    companion object {
        const val EXTRA_ORDER_NUMBER = "extra_order_number"
        const val EXTRA_PRINT_URL = "extra_print_url"
        const val EXTRA_TELEGRAM_URL = "extra_telegram_url"
        const val EXTRA_SHARE_CAPTION = "extra_share_caption"
        const val EXTRA_TITLE = "extra_title"
        const val EXTRA_PRINT_BTN_TEXT = "extra_print_btn_text"
        const val EXTRA_AUTO_EXPORT_JPG = "extra_auto_export_jpg"
        const val EXTRA_AUTO_SHARE_JPG = "extra_auto_share_jpg"
    }
}
