package com.inflow.premium.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.inflow.premium.data.SessionManager
import com.inflow.premium.databinding.ActivityInvoicePrintBinding

class InvoicePrintActivity : AppCompatActivity() {

    private lateinit var binding: ActivityInvoicePrintBinding
    private lateinit var session: SessionManager
    private var orderNumber: String = "Invoice"
    private var printUrl: String = ""
    private var telegramUrl: String = ""
    private var shareCaption: String = ""

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityInvoicePrintBinding.inflate(layoutInflater)
        setContentView(binding.root)
        session = SessionManager(this)

        orderNumber = intent.getStringExtra(EXTRA_ORDER_NUMBER) ?: "Invoice"
        val rawPrintUrl = intent.getStringExtra(EXTRA_PRINT_URL).orEmpty()
        printUrl = if (rawPrintUrl.startsWith("http")) rawPrintUrl else "${session.baseUrl}$rawPrintUrl"
        telegramUrl = intent.getStringExtra(EXTRA_TELEGRAM_URL).orEmpty()
        shareCaption = intent.getStringExtra(EXTRA_SHARE_CAPTION).orEmpty()

        binding.toolbar.title = "Invoice • $orderNumber"
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
        }

        if (printUrl.isNotBlank()) {
            binding.webInvoice.loadUrl(printUrl)
        } else {
            Toast.makeText(this, "Print URL unavailable", Toast.LENGTH_SHORT).show()
        }

        binding.btnShareInvoice.setOnClickListener { shareInvoice() }
        binding.btnPrintInvoice.setOnClickListener { printWebPage() }
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
    }
}
