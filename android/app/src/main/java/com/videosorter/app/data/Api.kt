package com.videosorter.app.data

import android.content.ContentResolver
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val code: Int, message: String) : IOException(message)

/**
 * 极简 REST 客户端：OkHttp + kotlinx.serialization。
 * 认证用 Authorization: Bearer，未登录时服务端返回 401，由 UI 引导回登录页。
 */
class Api(baseUrl: String, var token: String? = null) {

    val base: String = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true; explicitNulls = false }
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    fun thumbUrl(v: Video): String =
        if (v.thumbUrl.isNullOrEmpty()) "" else base + v.thumbUrl

    private fun build(path: String, method: String, body: String? = null): Request {
        val b = Request.Builder().url(base + path).header("Accept", "application/json")
        token?.takeIf { it.isNotEmpty() }?.let { b.header("Authorization", "Bearer $it") }
        val jsonBody = (body ?: if (method == "POST" || method == "PATCH" || method == "PUT") "{}" else null)
            ?.toRequestBody(JSON)
        when (method) {
            "POST" -> b.post(jsonBody ?: EMPTY)
            "PATCH" -> b.patch(jsonBody ?: EMPTY)
            "DELETE" -> b.delete()
            else -> b.get()
        }
        return b.build()
    }

    private suspend fun exec(request: Request): String = withContext(Dispatchers.IO) {
        client.newCall(request).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val msg = runCatching {
                    val obj = json.parseToJsonElement(text).jsonObject
                    (obj["detail"] ?: obj["error"])?.jsonPrimitive?.content
                }.getOrNull() ?: "请求失败（${resp.code}）"
                throw ApiException(resp.code, msg)
            }
            text
        }
    }

    private suspend inline fun <reified T> getJson(path: String): T =
        json.decodeFromString(exec(build(path, "GET")))

    private suspend inline fun <reified T> sendJson(path: String, method: String, body: String): T =
        json.decodeFromString(exec(build(path, method, body)))

    suspend fun ping(): Boolean = runCatching { getJson<Map<String, String>>("/api/health"); true }.getOrDefault(false)

    suspend fun login(user: String, pass: String): AuthOut {
        val out: AuthOut = sendJson("/api/auth/login", "POST", json.encodeToString(LoginIn(user, pass, true)))
        token = out.token
        return out
    }

    suspend fun me(): User = getJson("/api/auth/me")

    suspend fun logout() {
        runCatching { exec(build("/api/auth/logout", "POST")) }
        token = null
    }

    suspend fun tags(): List<Tag> = getJson<TagList>("/api/tags").tags

    suspend fun createTag(name: String, color: String): Tag =
        sendJson("/api/tags", "POST", json.encodeToString(NewTagIn(name, color)))

    suspend fun videos(filter: String = "all", q: String = "", tagId: Int? = null): VideoPage {
        val query = buildString {
            append("/api/videos?limit=500&sort=added&order=asc")
            when {
                filter == "tagged" -> append("&status=tagged")
                filter == "idle" -> append("&status=idle")
                filter == "organized" -> append("&status=organized")
                filter == "untagged" -> append("&status=untagged")
            }
            if (tagId != null) append("&tag=").append(tagId)
            if (q.isNotBlank()) append("&q=").append(Uri.encode(q))
        }
        return getJson(query)
    }

    suspend fun setTag(videoId: Int, tagId: Int?) {
        exec(build("/api/videos/$videoId/tag", "POST", json.encodeToString(TagIn(tagId))))
    }

    suspend fun play(videoId: Int): PlayInfo = getJson("/api/videos/$videoId/play")

    suspend fun saveProgress(videoId: Int, position: Double, duration: Double) {
        runCatching { exec(build("/api/videos/$videoId/history", "POST", json.encodeToString(HistIn(position, duration)))) }
    }

    suspend fun preview(): Plan = getJson("/api/organize/preview")

    suspend fun execute(tagIds: List<Int>): ExecOut =
        sendJson("/api/organize/execute", "POST", """{"tag_ids":${json.encodeToString(tagIds)}}""")

    suspend fun task(id: String): Task = getJson("/api/tasks/$id")

    suspend fun rename(videoId: Int, name: String) {
        exec(build("/api/videos/$videoId/rename", "POST", """{"name":${json.encodeToString(name)}}"""))
    }

    suspend fun deleteVideo(videoId: Int, withFile: Boolean) {
        exec(build("/api/videos/$videoId?file=$withFile", "DELETE"))
    }

    suspend fun scan(): String = getJson<ScanOut>("/api/scan").taskId

    /** 上传手机里的视频到服务器 */
    suspend fun upload(resolver: ContentResolver, uri: Uri, fileName: String, tagId: Int? = null): Boolean {
        val bytes = withContext(Dispatchers.IO) { resolver.openInputStream(uri)?.use { it.readBytes() } } ?: return false
        val body: RequestBody = bytes.toRequestBody("application/octet-stream".toMediaType())
        val builder = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", fileName, body)
        if (tagId != null) builder.addFormDataPart("tag_id", tagId.toString())
        val req = Request.Builder()
            .url(base + "/api/upload")
            .header("Accept", "application/json")
            .apply { token?.takeIf { it.isNotEmpty() }?.let { header("Authorization", "Bearer $it") } }
            .post(builder.build())
            .build()
        val text = exec(req)
        return text.contains("\"ok\":true")
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
        private val EMPTY = ByteArray(0).toRequestBody(null, 0, 0)
    }
}
