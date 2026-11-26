package com.inflow.premium.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import android.view.View
import android.widget.ImageView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

object ImageLoader {
    private val cache = object : LruCache<String, Bitmap>(16 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .build()

    fun load(
        scope: CoroutineScope,
        baseUrl: String,
        rawUrl: String?,
        imageView: ImageView,
        fallbackView: View? = null
    ) {
        val trimmed = rawUrl?.trim().orEmpty()
        if (trimmed.isBlank()) {
            imageView.setImageDrawable(null)
            imageView.visibility = View.GONE
            fallbackView?.visibility = View.VISIBLE
            return
        }
        val fullUrl = when {
            trimmed.startsWith("http://") || trimmed.startsWith("https://") -> trimmed
            trimmed.startsWith("/") -> "${baseUrl.trimEnd('/')}$trimmed"
            else -> "${baseUrl.trimEnd('/')}/$trimmed"
        }

        imageView.tag = fullUrl
        val cached = cache.get(fullUrl)
        if (cached != null) {
            imageView.setImageBitmap(cached)
            imageView.visibility = View.VISIBLE
            fallbackView?.visibility = View.GONE
            return
        }

        imageView.visibility = View.GONE
        fallbackView?.visibility = View.VISIBLE

        scope.launch {
            val bmp = withContext(Dispatchers.IO) {
                try {
                    val req = Request.Builder().url(fullUrl).build()
                    client.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) return@withContext null
                        val bytes = resp.body?.bytes() ?: return@withContext null
                        BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                    }
                } catch (_: Exception) {
                    null
                }
            }
            if (bmp != null) {
                cache.put(fullUrl, bmp)
                if (imageView.tag == fullUrl) {
                    imageView.setImageBitmap(bmp)
                    imageView.visibility = View.VISIBLE
                    fallbackView?.visibility = View.GONE
                }
            }
        }
    }
}
