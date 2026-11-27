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

    @JvmStatic
    fun saveDataUrlToCache(context: Context, rawFileName: String, dataUrl: String): Pair<Boolean, File?> {
        return try {
            val base64Part = if (dataUrl.contains(",")) dataUrl.substringAfter(",") else dataUrl
            val bytes = Base64.decode(base64Part, Base64.DEFAULT)
            if (bytes.isEmpty()) return false to null

            val cleanName = rawFileName
                .replace(Regex("[^a-zA-Z0-9._-]"), "_")
                .ifBlank { "Invoice_${System.currentTimeMillis()}.jpg" }
                .let { if (it.endsWith(".jpg", true) || it.endsWith(".jpeg", true)) it else "$it.jpg" }

            val dir = File(context.cacheDir, "share")
            if (!dir.exists()) dir.mkdirs()
            val outFile = File(dir, cleanName)
            FileOutputStream(outFile).use { out ->
                out.write(bytes)
                out.flush()
            }
            true to outFile
        } catch (_: Exception) {
            false to null
        }
    }

    class AndroidGalleryBridge(
        private val context: Context,
        private val saveToGallery: Boolean = true,
        private val onCompleteWithFile: ((Boolean, String, File?) -> Unit)? = null,
        private val onComplete: ((Boolean, String) -> Unit)? = null
    ) {
        constructor(context: Context, onComplete: ((Boolean, String) -> Unit)?) : this(
            context = context,
            saveToGallery = true,
            onCompleteWithFile = null,
            onComplete = onComplete
        )

        private val mainHandler = Handler(Looper.getMainLooper())

        @JavascriptInterface
        fun saveJpg(filename: String, dataUrl: String) {
            val (ok, msg) = if (saveToGallery) {
                saveDataUrlToGallery(context.applicationContext, filename, dataUrl)
            } else {
                true to filename
            }
            val (_, cachedFile) = if (onCompleteWithFile != null) {
                saveDataUrlToCache(context.applicationContext, filename, dataUrl)
            } else {
                false to null
            }
            mainHandler.post {
                if (onCompleteWithFile != null) {
                    onCompleteWithFile.invoke(ok && cachedFile != null, msg, cachedFile)
                } else if (onComplete != null) {
                    onComplete.invoke(ok, msg)
                } else {
                    val toastText = if (ok) "Saved $msg to Gallery!" else "Export failed: $msg"
                    Toast.makeText(context, toastText, Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
