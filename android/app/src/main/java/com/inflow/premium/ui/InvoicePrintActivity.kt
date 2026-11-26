package com.inflow.premium.ui

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.net.Uri
import android.os.Bundle
import android.print.PrintAttributes
import android.print.PrintManager
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityInvoicePrintBinding
import java.io.File
import java.io.FileOutputStream

class InvoicePrintActivity : AppCompatActivity() {

    private lateinit var binding: ActivityInvoicePrintBinding
    private lateinit var session: SessionManager
    private var orderNumber: String = "Invoice"
    private var printUrl: String = ""
    private var telegramUrl: String = ""
    private var shareCaption: String = ""
    private var autoExportJpg: Boolean = false
    private var hasAutoExported: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WebView.enableSlowWholeDocumentDraw()
        binding = ActivityInvoicePrintBinding.inflate(layoutInflater)
        setContentView(binding.root)
        session = SessionManager(this)

        orderNumber = intent.getStringExtra(EXTRA_ORDER_NUMBER) ?: "Invoice"
        val rawPrintUrl = intent.getStringExtra(EXTRA_PRINT_URL).orEmpty()
        printUrl = if (rawPrintUrl.startsWith("http")) rawPrintUrl else "${session.baseUrl}$rawPrintUrl"
        telegramUrl = intent.getStringExtra(EXTRA_TELEGRAM_URL).orEmpty()
        shareCaption = intent.getStringExtra(EXTRA_SHARE_CAPTION).orEmpty()
        val customTitle = intent.getStringExtra(EXTRA_TITLE).orEmpty()
        val customPrintBtnText = intent.getStringExtra(EXTRA_PRINT_BTN_TEXT).orEmpty()
        autoExportJpg = intent.getBooleanExtra(EXTRA_AUTO_EXPORT_JPG, false)

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
        binding.webInvoice.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (autoExportJpg && !hasAutoExported) {
                    hasAutoExported = true
                    binding.webInvoice.postDelayed({ exportInvoiceJpg() }, 500)
                }
            }
        }

        if (printUrl.isNotBlank()) {
            binding.webInvoice.loadUrl(printUrl)
        } else {
            Toast.makeText(this, "Print URL unavailable", Toast.LENGTH_SHORT).show()
        }

        binding.btnShareInvoice.setOnClickListener { shareInvoice() }
        binding.btnPrintInvoice.setOnClickListener { printWebPage() }
    }

    private fun exportInvoiceJpg() {
        try {
            val w = binding.webInvoice.width.coerceAtLeast(720)
            @Suppress("DEPRECATION")
            val contentH = (binding.webInvoice.contentHeight * binding.webInvoice.scale).toInt()
            val h = contentH.coerceAtLeast(binding.webInvoice.height).coerceIn(400, 4200)
            binding.webInvoice.measure(
                View.MeasureSpec.makeMeasureSpec(w, View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(h, View.MeasureSpec.EXACTLY)
            )
            val bitmap = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            canvas.drawColor(android.graphics.Color.WHITE)
            binding.webInvoice.draw(canvas)

            val file = File(cacheDir, "${orderNumber.replace(" ", "_")}.jpg")
            FileOutputStream(file).use { out ->
                bitmap.compress(Bitmap.CompressFormat.JPEG, 92, out)
            }
            bitmap.recycle()

            val uri = FileProvider.getUriForFile(this, "${packageName}.fileprovider", file)
            val share = Intent(Intent.ACTION_SEND).apply {
                type = "image/jpeg"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_TEXT, shareCaption.ifBlank { "Invoice $orderNumber" })
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivity(Intent.createChooser(share, "Export Invoice JPG"))
        } catch (e: Exception) {
            Toast.makeText(this, "JPG export failed: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun shareInvoice() {
        if (telegramUrl.isNotBlank()) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(telegramUrl)))
                return
            } catch (_: Exception) {
            }
        }
        val text = buildString {
            if (shareCaption.isNotBlank()) {
                append(shareCaption)
            } else {
                append("Invoice $orderNumber")
            }
            if (printUrl.isNotBlank()) {
                append("\n")
                append(printUrl)
            }
        }
        val sendIntent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_SUBJECT, "Sales Order $orderNumber")
            putExtra(Intent.EXTRA_TEXT, text)
        }
        startActivity(Intent.createChooser(sendIntent, "Share Invoice"))
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
    }
}
