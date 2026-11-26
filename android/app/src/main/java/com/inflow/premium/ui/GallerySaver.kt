package com.inflow.premium.ui

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream

object GallerySaver {

    @JvmStatic
    fun saveDataUrlToGallery(context: Context, rawFileName: String, dataUrl: String): Pair<Boolean, String> {
        return try {
            val base64Part = if (dataUrl.contains(",")) dataUrl.substringAfter(",") else dataUrl
            val bytes = Base64.decode(base64Part, Base64.DEFAULT)
            if (bytes.isEmpty()) {
                return false to "Empty image data"
            }

            val cleanName = rawFileName
                .replace(Regex("[^a-zA-Z0-9._-]"), "_")
                .ifBlank { "Invoice_${System.currentTimeMillis()}.jpg" }
                .let { if (it.endsWith(".jpg", true) || it.endsWith(".jpeg", true)) it else "$it.jpg" }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val values = ContentValues().apply {
                    put(MediaStore.Images.Media.DISPLAY_NAME, cleanName)
                    put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
                    put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/inFlow")
                    put(MediaStore.Images.Media.IS_PENDING, 1)
                }
                val resolver = context.contentResolver
                val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                    ?: return false to "Could not create MediaStore entry"

                resolver.openOutputStream(uri)?.use { out ->
                    out.write(bytes)
                    out.flush()
                } ?: return false to "Failed to open gallery output stream"

                values.clear()
                values.put(MediaStore.Images.Media.IS_PENDING, 0)
                resolver.update(uri, values, null, null)
                true to cleanName
            } else {
                val dir = File(
                    Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
                    "inFlow"
                )
                if (!dir.exists()) dir.mkdirs()
                val outFile = File(dir, cleanName)
                FileOutputStream(outFile).use { out ->
                    out.write(bytes)
                    out.flush()
                }
                MediaScannerConnection.scanFile(
                    context,
                    arrayOf(outFile.absolutePath),
                    arrayOf("image/jpeg"),
                    null
                )
                true to cleanName
            }
        } catch (e: Exception) {
            false to (e.message ?: "Failed to save image")
        }
    }

    class AndroidGalleryBridge(
        private val context: Context,
        private val onComplete: ((Boolean, String) -> Unit)? = null
    ) {
        private val mainHandler = Handler(Looper.getMainLooper())

        @JavascriptInterface
        fun saveJpg(filename: String, dataUrl: String) {
            val (ok, msg) = saveDataUrlToGallery(context.applicationContext, filename, dataUrl)
            mainHandler.post {
                if (onComplete != null) {
                    onComplete.invoke(ok, msg)
                } else {
                    val toastText = if (ok) "Saved $msg to Gallery!" else "Export failed: $msg"
                    Toast.makeText(context, toastText, Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
