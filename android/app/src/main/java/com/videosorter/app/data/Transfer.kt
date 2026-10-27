package com.videosorter.app.data

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okio.BufferedSink
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.TimeUnit

/** 一条传输记录（上传或下载），用于「传输历史」展示。 */
@Serializable
data class TransferItem(
    val name: String,
    val time: Long = 0L,
    val bytes: Long = 0L,
    val ok: Boolean = true,
    val kind: String = "up",          // up | down
    val where: String = "",           // 目标/来源路径
    val uri: String = "",             // 落盘后的 content:// URI（可用来打开文件）
    val videoId: Int = 0,             // 上传成功后的服务端视频 id（删除文件时用）
    val msg: String = "",
)

/** 传输历史（SharedPreferences 里存 JSON，最多 60 条）。 */
object TransferStore {
    private const val PREF = "vs_transfer"
    private const val KEY = "history"
    private val json = Json { ignoreUnknownKeys = true }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREF, Context.MODE_PRIVATE)

    fun load(ctx: Context): List<TransferItem> = runCatching {
        val raw = prefs(ctx).getString(KEY, "[]") ?: "[]"
        json.decodeFromString<List<TransferItem>>(raw)
    }.getOrDefault(emptyList())

    fun add(ctx: Context, item: TransferItem) {
        val list = (listOf(item) + load(ctx)).take(60)
        runCatching { prefs(ctx).edit().putString(KEY, json.encodeToString(list)).apply() }
    }

    fun clear(ctx: Context) {
        runCatching { prefs(ctx).edit().remove(KEY).apply() }
    }

    /** 删除若干条记录（按 time+name+kind 匹配）。 */
    fun remove(ctx: Context, items: List<TransferItem>) {
        if (items.isEmpty()) return
        val drop = items.map { Triple(it.name, it.time, it.kind) }.toSet()
        val left = load(ctx).filterNot { Triple(it.name, it.time, it.kind) in drop }
        runCatching { prefs(ctx).edit().putString(KEY, json.encodeToString(left)).apply() }
    }
}

/** 流式上传：读多少写多少，边写边回报进度（0..1）。 */
private class ProgressBody(
    private val stream: InputStream,
    private val length: Long,
    private val onProgress: (Float) -> Unit,
) : RequestBody() {
    override fun contentType() = "application/octet-stream".toMediaType()
    override fun contentLength() = length

    override fun writeTo(sink: BufferedSink) {
        val buf = ByteArray(64 * 1024)
        var sent = 0L
        var last = 0f
        stream.use { input ->
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                sink.write(buf, 0, n)
                sent += n
                val p = if (length > 0) sent.toFloat() / length else 0f
                if (p - last >= 0.01f || sent == length) {
                    last = p
                    onProgress(p.coerceIn(0f, 1f))
                }
            }
        }
        sink.flush()
        onProgress(1f)
    }
}

data class UploadCandidate(val uri: Uri, val name: String, val size: Long)

object Transfers {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private val json = Json { ignoreUnknownKeys = true }

    fun displayName(resolver: ContentResolver, uri: Uri): Pair<String, Long> {
        var name = uri.lastPathSegment?.substringAfterLast('/') ?: "video.mp4"
        var size = 0L
        runCatching {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
                ?.use { c ->
                    if (c.moveToFirst()) {
                        name = c.getString(0) ?: name
                        size = if (c.isNull(1)) 0L else c.getLong(1)
                    }
                }
        }
        return name to size
    }

    /** 流式上传一个 Uri 到服务端，返回服务端返回的 videoId（失败抛异常）。 */
    suspend fun upload(
        api: Api,
        resolver: ContentResolver,
        candidate: UploadCandidate,
        onProgress: (Float) -> Unit,
    ): Int = withContext(Dispatchers.IO) {
        val stream = resolver.openInputStream(candidate.uri)
            ?: throw IllegalStateException("无法读取文件")
        val body = ProgressBody(stream, candidate.size, onProgress)
        val builder = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", candidate.name, body)
        val req = Request.Builder()
            .url(api.base + "/api/upload")
            .header("Accept", "application/json")
            .apply { api.token?.takeIf { it.isNotEmpty() }?.let { header("Authorization", "Bearer $it") } }
            .post(builder.build())
            .build()
        client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val msg = runCatching {
                    json.decodeFromString<UploadErrorOut>(text).let { it.detail ?: it.error }
                }.getOrNull().takeUnless { it.isNullOrEmpty() } ?: "上传失败（${resp.code}）"
                throw ApiException(resp.code, msg)
            }
            val out = runCatching { json.decodeFromString<UploadOut>(text) }.getOrNull()
                ?: throw IllegalStateException("服务端返回异常")
            out.video?.id ?: 0
        }
    }

    /** 下载到手机：优先用用户选择的 SAF 目录，其次 下载/VideoSorter/。 */
    data class DownloadResult(val where: String, val uri: String)

    suspend fun download(
        ctx: Context,
        api: Api,
        video: Video,
        treeUri: Uri?,
        onProgress: (Float) -> Unit,
    ): DownloadResult = withContext(Dispatchers.IO) {
        val resolver = ctx.contentResolver
        val name = uniqueName(video.name)
        val (out, where, uriStr) = openSink(ctx, treeUri, name)
        val url = api.base + "/api/videos/${video.id}/raw"
        val req = Request.Builder().url(url)
            .apply { api.token?.takeIf { it.isNotEmpty() }?.let { header("Authorization", "Bearer $it") } }
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                runCatching { out.close() }
                throw ApiException(resp.code, "下载失败（${resp.code}）")
            }
            val total = resp.body?.contentLength() ?: -1L
            var got = 0L
            var last = 0f
            resp.body?.byteStream()?.use { input ->
                out.use { os -> copyWithProgress(input, os, total) { p ->
                    if (p - last >= 0.01f || p >= 1f) { last = p; onProgress(p) }
                } }
            }
            got = if (total > 0) total else got
            onProgress(1f)
        }
        DownloadResult(where, uriStr)
    }

    private fun copyWithProgress(input: InputStream, out: OutputStream, total: Long, onProgress: (Float) -> Unit) {
        val buf = ByteArray(128 * 1024)
        var done = 0L
        while (true) {
            val n = input.read(buf)
            if (n <= 0) break
            out.write(buf, 0, n)
            done += n
            if (total > 0) onProgress((done.toFloat() / total).coerceIn(0f, 1f))
        }
        out.flush()
    }

    private fun uniqueName(name: String): String = name.ifBlank { "video.mp4" }

    private fun openSink(ctx: Context, treeUri: Uri?, name: String): Triple<OutputStream, String, String> {
        val resolver = ctx.contentResolver
        if (treeUri != null) {
            runCatching {
                val docId = DocumentsContract.getTreeDocumentId(treeUri)
                val parent = DocumentsContract.buildDocumentUriUsingTree(treeUri, docId)
                val created = DocumentsContract.createDocument(resolver, parent, "video/mp4", name)
                if (created != null) {
                    val os = resolver.openOutputStream(created)
                    if (os != null) return Triple(os, "自定义目录/$name", created.toString())
                }
            }
        }
        // 回退：系统「下载」目录下建 VideoSorter 子目录
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = android.content.ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, "video/mp4")
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/VideoSorter")
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
            if (uri != null) {
                val os = resolver.openOutputStream(uri)
                if (os != null) return Triple(os, "下载/VideoSorter/$name", uri.toString())
            }
        }
        @Suppress("DEPRECATION")
        val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "VideoSorter")
        dir.mkdirs()
        val f = File(dir, name)
        return Triple(FileOutputStream(f), "下载/VideoSorter/$name", "")
    }
}

@Serializable
private data class UploadErrorOut(val detail: String? = null, val error: String? = null)

@Serializable
private data class UploadOut(val ok: Boolean = true, val video: Video? = null)
