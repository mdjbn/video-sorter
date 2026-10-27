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
 * 全局 401 通知：任何接口（视频 / 标签 / 设置 / 缓存 …）返回 401 时，
 * 说明登录态已经失效（改密码、被踢下线、token 过期、退出所有设备）。
 * UI 注册回调后统一回到登录页，避免「设置页里还在转圈、却不回登录」。
 */
object AuthEvents {
    @Volatile
    var onUnauthorized: (() -> Unit)? = null
}

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
            "PUT" -> b.put(jsonBody ?: EMPTY)
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
                if (resp.code == 401) runCatching { AuthEvents.onUnauthorized?.invoke() }
                throw ApiException(resp.code, msg)
            }
            text
        }
    }

    private suspend inline fun <reified T> getJson(path: String): T =
        json.decodeFromString(exec(build(path, "GET")))

    private suspend inline fun <reified T> sendJson(path: String, method: String, body: String): T =
        json.decodeFromString(exec(build(path, method, body)))

    /**
     * 健康检查。/api/health 里既有字符串也有布尔/数字，反序列化成 Map<String, String> 会抛
     * 类型错误（曾导致登录页误报「连不上服务器」），这里按 JsonObject 解析，宽松判定 ok。
     */
    /** 播放与预加载都要带的请求头（令牌） */
    fun headers(): Map<String, String> =
        buildMap {
            token?.takeIf { it.isNotEmpty() }?.let { put("Authorization", "Bearer $it") }
        }

    suspend fun ping(): Boolean = runCatching {
        val obj = json.parseToJsonElement(exec(build("/api/health", "GET"))).jsonObject
        (obj["ok"]?.jsonPrimitive?.content ?: "true") == "true"
    }.getOrDefault(false)

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

    suspend fun createTag(name: String, color: String, dirPath: String? = null): Tag =
        sendJson(
            "/api/tags",
            "POST",
            json.encodeToString(NewTagIn(name, color, dirPath?.takeIf { it.isNotBlank() })),
        )

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
    /** HLS 转码进度：非直放格式首次播放要等 ffmpeg 切完片 */
    suspend fun hlsStatus(videoId: Int): HlsStatus = getJson("/api/videos/$videoId/hlsstatus")

    suspend fun saveProgress(videoId: Int, position: Double, duration: Double) {
        runCatching { exec(build("/api/videos/$videoId/history", "POST", json.encodeToString(HistIn(position, duration)))) }
    }

    // 服务端是 POST /api/organize/preview（之前写成 GET，手机端一直收到 404「接口不存在」）
    suspend fun preview(): Plan = sendJson("/api/organize/preview", "POST", "{}")

    suspend fun execute(tagIds: List<Int>): ExecOut =
        sendJson("/api/organize/execute", "POST", """{"tag_ids":${json.encodeToString(tagIds)}}""")

    suspend fun task(id: String): Task = getJson("/api/tasks/$id")

    suspend fun rename(videoId: Int, name: String) {
        exec(build("/api/videos/$videoId/rename", "POST", """{"name":${json.encodeToString(name)}}"""))
    }

    suspend fun deleteVideo(videoId: Int, withFile: Boolean) {
        exec(build("/api/videos/$videoId?file=$withFile", "DELETE"))
    }

    // 服务端是 POST /api/scan
    suspend fun scan(): String = sendJson<ScanOut>("/api/scan", "POST", "{}").taskId

    // ---------- 源文件夹 / 上传目录 / 单条历史 ----------

    suspend fun sources(): List<Source> = getJson<SourceList>("/api/sources").sources

    suspend fun updateSource(id: Int, path: String): SourceOut =
        sendJson("/api/sources/$id", "PUT", """{"path":${json.encodeToString(path)}}""")

    suspend fun addSource(path: String): Source =
        sendJson<SourceOut>("/api/sources", "POST", """{"path":${json.encodeToString(path)}}""").source

    suspend fun removeSource(id: Int) {
        sendJson<OkOut>("/api/sources/$id", "DELETE", "{}")
    }

    suspend fun setUploadDir(path: String) {
        sendJson<OkOut>("/api/settings", "PUT", """{"upload_dir":${json.encodeToString(path)}}""")
    }

    suspend fun deleteHistory(videoId: Int) {
        sendJson<OkOut>("/api/history/$videoId", "DELETE", "{}")
    }

    // ---------- 服务器 / 账号 / 标签管理 / 播放历史 / 缓存（设置页二级页面） ----------

    suspend fun serverInfo(): ServerInfo = getJson("/api/info")

    suspend fun history(limit: Int = 60): List<Video> =
        getJson<ItemsPage>("/api/history?limit=$limit").items

    suspend fun clearHistory() {
        sendJson<OkOut>("/api/history", "DELETE", "{}")
    }

    suspend fun cache(): CacheInfo = getJson("/api/cache")

    suspend fun clearCache(target: String = "all"): CacheInfo =
        sendJson("/api/cache/clear", "POST", """{"target":"$target"}""")

    suspend fun updateTag(id: Int, name: String? = null, color: String? = null, dirPath: String? = null): Tag {
        val parts = buildList {
            if (name != null) add("\"name\":${json.encodeToString(name)}")
            if (color != null) add("\"color\":${json.encodeToString(color)}")
            if (dirPath != null) add("\"dir_path\":${json.encodeToString(dirPath)}")
        }
        return sendJson<TagOut>("/api/tags/$id", "PATCH", "{${parts.joinToString(",")}}").tag
    }

    suspend fun deleteTag(id: Int) {
        sendJson<OkOut>("/api/tags/$id", "DELETE", "{}")
    }

    suspend fun changePassword(old: String, new: String): String =
        sendJson<MessageOut>("/api/auth/password", "POST",
            """{"old_password":${json.encodeToString(old)},"new_password":${json.encodeToString(new)}}""").message

    suspend fun changeUsername(name: String): String =
        sendJson<MessageOut>("/api/auth/username", "POST",
            """{"username":${json.encodeToString(name)}}""").message

    suspend fun sessions(): List<SessionRow> = getJson<SessionPage>("/api/auth/sessions").sessions

    suspend fun revokeAll(): String =
        sendJson<MessageOut>("/api/auth/revoke-all", "POST", "{}").message

    suspend fun records(): List<BatchRec> = getJson<BatchPage>("/api/organize/records").items

    suspend fun undo(batchId: String) {
        sendJson<OkOut>("/api/organize/undo/$batchId", "POST", "{}")
    }


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
