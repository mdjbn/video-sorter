package com.videosorter.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.videosorter.app.data.FailedItem
import kotlin.math.roundToLong

/**
 * 整理完成后的「怎么说」——纯函数，便于单测（见 LogicTest.organize*）。
 *
 * 后端的三种落点：
 * - 全部成功：任务 status = done，result.moved = N，result.failed = []
 * - 部分失败：任务 status = done，result.moved = X，result.failed = [{video_id,name,error} …]
 * - 全部失败 / 崩溃：任务 status = error，error 里是异常文本（`PermissionError: …`）
 */

/** 一条失败原因（界面上渲染成「文件名 · 原因」） */
data class OrgFail(val name: String, val reason: String)

/** 一次整理的结果摘要 */
data class OrganizeSummary(
    /** 全成功 */
    val ok: Boolean,
    /** 部分失败（有成功的也有失败的） */
    val partial: Boolean,
    val moved: Int,
    val failed: Int,
    /** toast 文案 */
    val text: String,
    /** 失败明细（最多 [MAX_SHOWN] 条，给人看的） */
    val fails: List<OrgFail>,
    /** 失败条数超过 [MAX_SHOWN] 时多出来的数量 */
    val more: Int,
    /** 目标目录不可写被跳过的数量 */
    val skipped: Int,
)

/** 界面上最多列几条失败明细（再多就只给「以及另外 N 条」） */
const val MAX_SHOWN = 8

/** 失败的「文件 · 原因」最多取几条，防止后端返回几百条把界面撑爆 */
private const val MAX_KEPT = 50

/** 后端异常文本太长（traceback）时截断 */
internal fun shortReason(raw: String): String {
    val one = raw.replace('\n', ' ').replace(Regex("\\s+"), " ").trim()
    if (one.isEmpty()) return "原因未知"
    return if (one.length <= 80) one else one.take(78) + "…"
}

fun failListText(count: Int): String = if (count > 1) "上次整理失败 $count 个" else "上次整理失败"

/**
 * 把一次任务轮询的最终状态 + execute 返回的 skipped 拼成界面要展示的摘要。
 *
 * @param status  任务最终状态（"done" / "error" / 其他）
 * @param moved   成功移动数
 * @param failed  失败条数
 * @param fails   失败明细
 * @param error   任务级错误文本（status == "error" 时后端写在 task.error）
 * @param skipped 目标目录不可写被跳过的数量（execute 返回；null = 不知道）
 */
fun summarizeOrganize(
    status: String,
    moved: Int,
    failed: Int,
    fails: List<FailedItem>,
    error: String,
    skipped: Int? = null,
): OrganizeSummary {
    val sk = (skipped ?: 0).coerceAtLeast(0)
    val skipTail = if (sk > 0) "，$sk 个被跳过：目标目录不可写" else ""
    val kept = fails
        .map { OrgFail(name = it.name, reason = shortReason(it.error)) }
        .take(MAX_KEPT)
    val failCount = maxOf(failed, kept.size)

    // 后端把整批判成 error（status == "error"）：即使没有 failed 明细（比如整批被写权限挡住、
    // 或第一下就抛异常），对用户来说也是「整批失败」，原因在任务级 error 里。
    // 必须先于「全成功」判断，否则 error + 无明细会被误报成「已整理 0 个视频」。
    if (status == "error" && moved == 0) {
        val reason = if (error.isNotBlank()) shortReason(error) else "整理失败"
        val list = kept.ifEmpty { listOf(OrgFail(name = "", reason = reason)) }
        return OrganizeSummary(
            ok = false,
            partial = false,
            moved = 0,
            failed = if (failCount > 0) failCount else 1,
            text = "全部整理失败：$reason" + skipTail,
            fails = list,
            more = (failCount - list.size).coerceAtLeast(0),
            skipped = sk,
        )
    }

    // 全成功
    if (failCount == 0) {
        return OrganizeSummary(
            ok = true,
            partial = false,
            moved = moved,
            failed = 0,
            text = "已整理 $moved 个视频" + skipTail,
            fails = emptyList(),
            more = 0,
            skipped = sk,
        )
    }

    // 一个都没成功：不管后端 status 是 error 还是 done，对用户来说都是「整批失败」，
    // toast 直接给原因（task.error），明细同样留在页面上
    if (moved == 0) {
        val reason = if (error.isNotBlank()) shortReason(error) else "整理失败"
        val list = kept.ifEmpty { listOf(OrgFail(name = "", reason = shortReason(error))) }
        return OrganizeSummary(
            ok = false,
            partial = false,
            moved = 0,
            failed = failCount,
            text = reason + skipTail,
            fails = list,
            more = (failCount - list.size).coerceAtLeast(0),
            skipped = sk,
        )
    }

    // 部分失败：成功 X、失败 Y，明细放界面上（toast 放不下多行）
    return OrganizeSummary(
        ok = false,
        partial = true,
        moved = moved,
        failed = failCount,
        text = "已移动 $moved 个，失败 $failCount 个" + skipTail,
        fails = kept,
        more = (failCount - kept.size).coerceAtLeast(0),
        skipped = sk,
    )
}

/**
 * execute 接口的 400 是否属于「目标目录不可写」。后端 detail 形如
 * `目标目录不可写：/volume1/整理/旅行：（PermissionError: 只读文件系统）`
 */
fun isUnwritableError(message: String?): Boolean {
    val m = message ?: return false
    return m.contains("不可写") || m.contains("Permission denied", ignoreCase = true) ||
        m.contains("Read-only", ignoreCase = true) || m.contains("只读")
}

/** 后端 detail 里的路径（「目标目录不可写：」后面那一段），取不到就返回原文 */
fun unwritableTarget(message: String?): String {
    val m = message ?: return ""
    val after = m.substringAfter("不可写", "").trimStart('：', ':', ' ')
    val path = after.substringBefore('：').substringBefore('\n').trim()
    return path.ifEmpty { m.replace('\n', ' ').trim() }
}

/** 字节数 → 「512 MB」这类文案（设置项用，固定按 MB/GB 取整） */
fun cacheMbText(mb: Int): String = if (mb >= 1024 && mb % 1024 == 0) "${mb / 1024} GB" else "$mb MB"

/** 实际字节 → 同样的口径（SimpleCache 实际值可能略小于设定值） */
fun cacheBytesText(bytes: Long): String {
    if (bytes <= 0) return "0 MB"
    val mb = bytes.toDouble() / 1024.0 / 1024.0
    return if (mb >= 1024) "%.1f GB".format(mb / 1024.0) else "${mb.roundToLong()} MB"
}

/** 设置页可选的缓存上限档位（MB） */
val CACHE_MB_OPTIONS = listOf(256, 512, 1024, 2048, 4096)

/**
 * 整理页的「上次整理失败」区块状态。只活在整理页内（remember），
 * 不做跨进程持久化 —— 用户点「知道了」或者关掉页面就消失。
 */
class OrganizeFailState {
    var summary by mutableStateOf<OrganizeSummary?>(null)
        private set

    /** 展开/收起（默认展开，失败就是要让人看见） */
    var expanded by mutableStateOf(true)

    /** 记住这次的失败明细，供界面展示 */
    fun update(s: OrganizeSummary) {
        summary = if (s.ok && s.skipped == 0) null else s
        expanded = true
    }

    /** 全部失败但没有明细时，用任务级错误造一条，别让区块空着 */
    fun updateFromError(message: String?) {
        val m = message?.takeIf { it.isNotBlank() } ?: return
        val s = summarizeOrganize(
            status = "error",
            moved = 0,
            failed = 1,
            fails = emptyList(),
            error = m,
        )
        summary = s
        expanded = true
    }

    fun rememberSkipped(count: Int) {
        if (count <= 0) return
        val s = summarizeOrganize(status = "done", moved = 0, failed = 0, fails = emptyList(), error = "", skipped = count)
        summary = s
        expanded = true
    }

    fun clear() {
        summary = null
    }
}

/** 把失败区块的显示状态挂进 Compose（页面销毁即丢弃，符合「不跨进程持久化」） */
@Composable
fun rememberOrganizeFailState(): OrganizeFailState = remember { OrganizeFailState() }

/** 失败区块是否该出现（有失败或跳过） */
fun OrganizeFailState.visible(): Boolean {
    val s = summary ?: return false
    return s.failed > 0 || s.skipped > 0
}
