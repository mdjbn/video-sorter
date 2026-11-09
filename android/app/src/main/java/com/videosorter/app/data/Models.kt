package com.videosorter.app.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonPrimitive

@Serializable
data class LoginIn(val username: String, val password: String, val remember: Boolean = true)

@Serializable
data class User(val id: Int = 0, val username: String = "admin")

@Serializable
data class AuthOut(
    val token: String = "",
    val user: User? = null,
    // 还在用首装默认口令（admin1234）时后端会返回 true，App 先弹「设置新密码」再放行
    @SerialName("must_change_password") val mustChangePassword: Boolean = false,
)

@Serializable
data class Counts(
    val all: Int = 0,
    val idle: Int = 0,
    val tagged: Int = 0,
    val organized: Int = 0,
    val untagged: Int = 0,
)

@Serializable
data class Video(
    val id: Int,
    /** 后端字段名是 filename（不是 name），不加这个映射文件名永远是空串 */
    @SerialName("filename") val name: String = "",
    val path: String = "",
    val ext: String = "",
    val duration: Double = 0.0,
    val size: Long = 0,
    val status: String = "idle",
    @SerialName("tag_id") val tagId: Int? = null,
    @SerialName("tag_name") val tagName: String? = null,
    @SerialName("tag_color") val tagColor: String? = null,
    @SerialName("thumb_url") val thumbUrl: String? = null,
    @SerialName("raw_url") val rawUrl: String? = null,
    /** 播放进度（秒）；后端在无播放历史时返回 null，不能声明为非空 Double */
    val position: Double? = null,
    @SerialName("watched_at") val watchedAt: String? = null,
    /** 播放记录里视频文件已被删除（服务端用快照信息返回） */
    val deleted: Boolean = false,
    val organized: Boolean = false,
) {
    val isOrganized: Boolean get() = organized || status == "organized"
}

@Serializable
data class VideoPage(
    val items: List<Video> = emptyList(),
    val total: Int = 0,
    val counts: Counts = Counts(),
)

@Serializable
data class Tag(
    val id: Int,
    val name: String,
    val color: String = "#8d98a8",
    val count: Int = 0,
    @SerialName("dir_path") val dirPath: String? = null,
    @SerialName("effective_dir") val dir: String? = null,
    /** 上次扫描这个标签目录的时间（ISO 时间串）。**没扫过时后端给 null**，所以这里必须可空——
     *  写成非空 String 会让 kotlinx 直接抛 JsonDecodingException，整个标签列表都拿不到。 */
    @SerialName("last_scan_at") val lastScanAt: String? = null,
    /** 上次扫描的结果摘要：{kind,name,found,added,updated,skipped,failed} */
    @SerialName("last_scan") val lastScan: LastScan? = null,
    /** 新建标签时建议的目录（服务端按「根目录/标签名」推出来） */
    @SerialName("default_dir") val defaultDir: String = "",
)

/** 一个目录上一次扫描的结果（源文件夹和标签都用这个结构）。 */
@Serializable
data class LastScan(
    val kind: String = "",
    val name: String = "",
    val found: Int = 0,
    val added: Int = 0,
    val updated: Int = 0,
    val skipped: Int = 0,
    val failed: Int = 0,
)

@Serializable
data class TagList(val tags: List<Tag> = emptyList())

@Serializable
/**
 * 新建标签。dir_path 是**必填**的（v1.3.9 起后端 Pydantic 不给默认值）：
 * 服务端原来可以留空、按「根目录/标签名」隐式推导，但那会让「这个标签的文件到底在哪个
 * 目录」变成猜的，也让目录重叠检查无从下手，所以改成必须显式给。
 */
data class NewTagIn(val name: String, val color: String = "#8d98a8", @SerialName("dir_path") val dirPath: String)

@Serializable
data class PlanItem(
    @SerialName("video_id") val videoId: Int,
    val name: String = "",
    @SerialName("tag_id") val tagId: Int? = null,
    @SerialName("tag_name") val tagName: String? = null,
    @SerialName("tag_color") val tagColor: String? = null,
    val from: String = "",
    val to: String = "",
    val dir: String = "",
    val size: Long = 0,
)

@Serializable
data class Plan(
    val items: List<PlanItem> = emptyList(),
    val total: Int = 0,
    @SerialName("total_bytes") val totalBytes: Long = 0,
)

@Serializable
data class ExecOut(
    @SerialName("task_id") val taskId: String = "",
    val planned: Int = 0,
    /** 目标目录不可写等原因被跳过的数量（后端 execute 新增字段，老版本没有 → 0） */
    val skipped: Int = 0,
    val bytes: Long = 0,
)

/**
 * 整理任务结果里的「单个视频失败」条目：后端是
 * `{"video_id": 3, "name": "海边.mp4", "error": "PermissionError: …"}`。
 */
@Serializable
data class FailedItem(
    @SerialName("video_id") val videoId: Int = 0,
    val name: String = "",
    val error: String = "",
)

/**
 * `result.failed` 在新后端是 `[{video_id,name,error}, …]`，在老后端只是失败条数 `2`。
 * 这里两种都接住：读数组得到明细，读数字则逐条补成占位条目（名字留空，只计数）。
 */
object FailedListSerializer : KSerializer<List<FailedItem>> {
    private val listSerializer = kotlinx.serialization.builtins.ListSerializer(FailedItem.serializer())

    override val descriptor = PrimitiveSerialDescriptor("FailedList", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): List<FailedItem> {
        val input = decoder as? JsonDecoder
            ?: return listSerializer.deserialize(decoder)
        return when (val el = input.decodeJsonElement()) {
            is JsonArray -> input.json.decodeFromJsonElement(listSerializer, el)
            is JsonPrimitive -> {
                val n = el.content.toIntOrNull() ?: 0
                List(n.coerceIn(0, 500)) { FailedItem(error = "原因未知") }
            }
            else -> throw SerializationException("result.failed 既不是数组也不是数字：$el")
        }
    }

    override fun serialize(encoder: Encoder, value: List<FailedItem>) {
        listSerializer.serialize(encoder, value)
    }
}

@Serializable
data class TaskResult(
    @SerialName("batch_id") val batchId: String = "",
    val moved: Int = 0,
    @Serializable(with = FailedListSerializer::class)
    val failed: List<FailedItem> = emptyList(),
    val items: List<FailedItem> = emptyList(),
    // 以下只在扫描任务里有：总账 + 每个目录一条明细
    val added: Int = 0,
    val updated: Int = 0,
    val skipped: Int = 0,
    val missing: Int = 0,
    val dirs: List<ScanDirResult> = emptyList(),
)

/** GET /api/tags/default-dir */
@Serializable
data class DefaultDirOut(val dir: String = "")

/** 扫描时每个目录（源文件夹 / 标签文件夹）各自的战果。 */
@Serializable
data class ScanDirResult(
    val kind: String = "",
    val id: Int = 0,
    val name: String = "",
    val path: String = "",
    val found: Int = 0,
    val added: Int = 0,
    val updated: Int = 0,
    val skipped: Int = 0,
    val failed: Int = 0,
)

@Serializable
data class Task(
    val id: String = "",
    val status: String = "",
    val percent: Double = 0.0,
    val message: String = "",
    val done: Int = 0,
    val total: Int = 0,
    /** status == "error" 时的失败原因（后端 tasks.fail() 写进来的） */
    val error: String = "",
    /** 后端任务结果 result：{batch_id, moved, failed:[…], items:[…]} */
    val result: TaskResult? = null,
) {
    /** 整理成功移动的数量（没有 result 时退回任务进度） */
    val moved: Int
        get() = result?.moved ?: if (status == "done") done else 0

    /** 失败条数：新后端给明细数组，老后端只给一个数字 */
    val failedCount: Int
        get() = maxOf(result?.failed?.size ?: 0, result?.items?.count { it.error.isNotEmpty() } ?: 0)

    /** 失败原因列表（新后端才有 name/error 明细） */
    val failedItems: List<FailedItem>
        get() = (result?.failed ?: emptyList()).ifEmpty { result?.items.orEmpty().filter { it.error.isNotEmpty() } }
}

@Serializable
data class PlayInfo(val mode: String = "error", val url: String? = null, val message: String? = null)

@Serializable
data class TagIn(val tag_id: Int?)

@Serializable
data class HistIn(val position: Double, val duration: Double)

@Serializable
data class BatchRec(
    val id: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val undone: Int = 0,
    val files: Int = 0,
    val dirs: List<String> = emptyList(),
)

@Serializable
data class BatchPage(val items: List<BatchRec> = emptyList())

@Serializable
data class OkOut(val ok: Boolean = true)

@Serializable
data class HlsStatus(
    val status: String = "",
    val percent: Int = 0,
    val ready: Boolean = false,
    val finished: Boolean = false,
    val error: String = "",
)

@Serializable
data class ScanOut(
    @SerialName("task_id") val taskId: String = "",
    /** 排在队尾（前面还有活）时为 true */
    val queued: Boolean = false,
    /** 队列里的位置，1 是下一个就轮到；0 表示已经在跑 */
    val position: Int = 0,
    /** 同样的扫描已经在队列里了，复用了那条任务 */
    val merged: Boolean = false,
)

@Serializable
data class CacheBucket(val count: Int = 0, val bytes: Long = 0)

/** GET /api/cache */
@Serializable
data class CacheInfo(
    val thumbs: CacheBucket = CacheBucket(),
    val hls: CacheBucket = CacheBucket(),
    @SerialName("total_bytes") val totalBytes: Long = 0,
    @SerialName("data_dir") val dataDir: String = "",
    @SerialName("thumb_dir") val thumbDir: String = "",
    @SerialName("hls_dir") val hlsDir: String = "",
)

/** 只关心 items 的列表响应（播放历史） */
@Serializable
data class ItemsPage(val items: List<Video> = emptyList())

@Serializable
data class SessionRow(
    val token: String = "",
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("last_used_at") val lastUsedAt: String? = null,
)

@Serializable
data class SessionPage(val sessions: List<SessionRow> = emptyList())

/** GET /api/info */
@Serializable
data class ServerInfo(
    val version: String = "",
    @SerialName("data_dir") val dataDir: String = "",
    @SerialName("upload_dir") val uploadDir: String = "",
    @SerialName("web_dir") val webDir: String = "",
    val platform: String = "",
    val python: String = "",
    val ffmpeg: String = "",
    @SerialName("media_ready") val mediaReady: Boolean = false,
)

@Serializable
data class MessageOut(val ok: Boolean = true, val message: String = "")

@Serializable
data class TagOut(val ok: Boolean = true, val tag: Tag)

@Serializable
data class Source(
    val id: Int = 0,
    val path: String = "",
    val count: Int = 0,
    val exists: Boolean = true,
    /** "" 普通源目录；"upload" 内置上传目录（可改路径，不可删除） */
    val kind: String = "",
    val editable: Boolean = true,
    val deletable: Boolean = true,
    /** 上次扫描这个源目录的时间（ISO 时间串）。没扫过时后端给 null，必须可空。 */
    @SerialName("last_scan_at") val lastScanAt: String? = null,
    /** 上次扫描的结果摘要 */
    @SerialName("last_scan") val lastScan: LastScan? = null,
)

@Serializable
data class SourceList(val sources: List<Source> = emptyList())

@Serializable
data class SourceOut(val ok: Boolean = true, val source: Source = Source())
