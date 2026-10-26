package com.videosorter.app.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class LoginIn(val username: String, val password: String, val remember: Boolean = true)

@Serializable
data class User(val id: Int = 0, val username: String = "admin")

@Serializable
data class AuthOut(val token: String = "", val user: User? = null)

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
    @SerialName("effective_dir") val dir: String? = null,
)

@Serializable
data class TagList(val tags: List<Tag> = emptyList())

@Serializable
data class NewTagIn(val name: String, val color: String = "#8d98a8", @SerialName("dir_path") val dirPath: String? = null)

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
data class ExecOut(@SerialName("task_id") val taskId: String = "", val planned: Int = 0)

@Serializable
data class Task(
    val id: String = "",
    val status: String = "",
    val percent: Double = 0.0,
    val message: String = "",
    val done: Int = 0,
    val total: Int = 0,
)

@Serializable
data class PlayInfo(val mode: String = "error", val url: String? = null, val message: String? = null)

@Serializable
data class TagIn(val tag_id: Int?)

@Serializable
data class HistIn(val position: Double, val duration: Double)

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
data class ScanOut(@SerialName("task_id") val taskId: String = "")
