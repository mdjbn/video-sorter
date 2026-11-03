package com.videosorter.app.ui

import com.videosorter.app.data.LastScan
import com.videosorter.app.data.ScanDirResult
import com.videosorter.app.data.ScanOut

/**
 * 扫描/整理任务的状态判定与文案。
 *
 * 这些逻辑以前散落在页面代码里、写成了 `if (task.status != "running") { 认为完成 }`，
 * 后端 v1.3.9 加了排队态 `queued` 之后，那句话会把「刚排上队」误判成「已经扫完」——
 * 用户点一下扫描立刻看到「扫描完成」，其实一个文件都还没扫。抽出来就能单测锁住。
 */
object TaskFlow {

    /** 终态：只有这三种才算跑完了，`queued` / `running` 都还得等。 */
    private val TERMINAL = setOf("done", "error", "cancelled")

    fun isFinished(status: String): Boolean = status in TERMINAL

    /** 还在排队（已创建、尚未开始）。 */
    fun isQueued(status: String): Boolean = status == "queued"

    /** 轮询时是否还要继续等。 */
    fun shouldKeepPolling(status: String): Boolean = !isFinished(status)

    /**
     * 提交扫描后的即时提示：在跑 / 排队第几位 / 复用了已有任务。
     * 返回空串表示不用提示（正常开始扫描）。
     */
    fun submitHint(out: ScanOut): String = when {
        out.merged -> "同样的扫描已经在队列里了，等它跑完"
        out.queued && out.position > 1 -> "已排队，前面还有 ${out.position - 1} 个扫描"
        out.queued -> "已排队，下一个就轮到"
        else -> ""
    }

    /**
     * 任务结束时的提示语。失败要把原因带出来，不能只说「完成」。
     * @param label 任务名，例如「扫描」「「旅行」扫描」
     */
    fun finishMessage(status: String, message: String, error: String, label: String = "扫描"): String =
        when (status) {
            "cancelled" -> "$label 已取消"
            "error" -> "$label 失败：${error.ifBlank { message }.ifBlank { "未知原因" }}"
            else -> "$label 完成：${message.ifBlank { "ok" }}"
        }
}

/** 把一次扫描的总账拼成一句人话，例如「新增 3 · 更新 1 · 失败 1」。 */
object ScanText {

    /** 总账短句；全零时给「没有变化」。 */
    fun summary(added: Int, updated: Int, skipped: Int, missing: Int, failed: Int): String {
        val bits = buildList {
            if (added > 0) add("新增 $added")
            if (updated > 0) add("更新 $updated")
            if (missing > 0) add("丢失 $missing")
            if (failed > 0) add("失败 $failed")
        }
        return if (bits.isEmpty()) "没有变化" else bits.joinToString(" · ")
    }

    /** 单个目录的短结果：没有视频 / 没有变化 / 新增 N · 更新 N。 */
    fun dirResult(d: ScanDirResult): String {
        if (d.found == 0) return "没有视频"
        val bits = buildList {
            if (d.added > 0) add("新增 ${d.added}")
            if (d.updated > 0) add("更新 ${d.updated}")
            if (d.failed > 0) add("失败 ${d.failed}")
        }
        return if (bits.isEmpty()) "没有变化" else bits.joinToString(" · ")
    }

    /** 一个目录一行，用于把逐目录结果拼成一条多行提示。 */
    fun dirResultLine(d: ScanDirResult): String {
        val kind = if (d.kind == "tag") "标签" else "源文件夹"
        return "$kind「${d.name}」：${dirResult(d)}"
    }

    /** 上次扫描的那一句（时间 + 结果），没扫过返回「未扫描」。 */
    fun lastScanLine(lastScanAt: String?, lastScan: LastScan?): String {
        val whenText = if (lastScanAt.isNullOrBlank()) "" else ScanTime.human(lastScanAt)
        if (whenText.isEmpty()) return "未扫描"
        val result = when {
            lastScan == null -> null
            lastScan.found == 0 -> "没有视频"
            else -> summary(lastScan.added, lastScan.updated, lastScan.skipped, 0, lastScan.failed)
        }
        return if (result == null) "扫于 $whenText" else "扫于 $whenText · $result"
    }
}

/**
 * 把后端的时间串变短：`2026-11-03T16:25:39+08:00` → `今天 16:25` / `昨天 16:25` / `11-01 16:25`。
 *
 * 后端只给 ISO 串，Android 端不想为了格式化引入 java.time 解析（minSdk 24 要 desugaring），
 * 所以直接按位置切。解析不了就原样返回，绝不抛异常。
 */
object ScanTime {

    /** ISO 串 → (月, 日, 时, 分)；不合格返回 null。 */
    private fun parts(raw: String): List<Int>? {
        if (raw.length < 16) return null
        return runCatching {
            listOf(
                raw.substring(5, 7).toInt(),
                raw.substring(8, 10).toInt(),
                raw.substring(11, 13).toInt(),
                raw.substring(14, 16).toInt(),
            )
        }.getOrNull()
    }

    fun human(raw: String, todayYmd: Triple<Int, Int, Int>? = null): String {
        val p = parts(raw) ?: return raw
        val (mon, day, hour, minute) = p
        val clock = "%02d:%02d".format(hour, minute)
        val today = todayYmd ?: currentYmd()
        if (today != null) {
            val (ty, tm, td) = today
            if (mon == tm && day == td) return "今天 $clock"
            // 「昨天」只看日期差一天，跨月/跨年交给 isYesterday 用日历判断，避免手写月份边界
            if (isDayBefore(ty, tm, td, mon, day)) return "昨天 $clock"
        }
        return "%02d-%02d %s".format(mon, day, clock)
    }

    /**
     * 扫描出来的日期是不是「今天的前一天」。
     * 「今天」直接取 [currentYmd] 用的那个时钟，保证和调用方看到的"今天"是同一时刻，
     * 不依赖设备时钟（否则单测里传入固定日期时会和真实时间打架，跨月就判错）。
     */
    private fun isDayBefore(ty: Int, tm: Int, td: Int, mon: Int, day: Int): Boolean = runCatching {
        val cal = java.util.Calendar.getInstance()
        cal.clear()   // 必须清：否则 Calendar 会带上当前时分秒/时区偏移，跨月退一天可能退错
        cal.set(ty, tm - 1, td)
        cal.add(java.util.Calendar.DAY_OF_MONTH, -1)
        cal.get(java.util.Calendar.YEAR) >= 0 &&
            cal.get(java.util.Calendar.MONTH) + 1 == mon &&
            cal.get(java.util.Calendar.DAY_OF_MONTH) == day
    }.getOrDefault(false)

    /** 设备本地日期；取不到就返回 null（那就退化成 MM-dd HH:mm）。 */
    private fun currentYmd(): Triple<Int, Int, Int>? = runCatching {
        val c = java.util.Calendar.getInstance()
        Triple(c.get(java.util.Calendar.YEAR), c.get(java.util.Calendar.MONTH) + 1, c.get(java.util.Calendar.DAY_OF_MONTH))
    }.getOrNull()
}
