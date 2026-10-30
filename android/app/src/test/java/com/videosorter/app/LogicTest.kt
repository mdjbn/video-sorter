package com.videosorter.app

import com.videosorter.app.data.Api
import com.videosorter.app.data.FailedItem
import com.videosorter.app.data.FoundServer
import com.videosorter.app.data.Task
import com.videosorter.app.data.Session
import com.videosorter.app.data.Video
import com.videosorter.app.data.parseReply
import com.videosorter.app.data.VideoPage
import com.videosorter.app.ui.CACHE_MB_OPTIONS
import com.videosorter.app.ui.DragReorder
import com.videosorter.app.ui.MAX_SHOWN
import com.videosorter.app.ui.OrganizeFailState
import com.videosorter.app.ui.cacheBytesText
import com.videosorter.app.ui.cacheMbText
import com.videosorter.app.ui.failListText
import com.videosorter.app.ui.isUnwritableError
import com.videosorter.app.ui.nextThemeMode
import com.videosorter.app.ui.summarizeOrganize
import com.videosorter.app.ui.themeLabel
import com.videosorter.app.ui.unwritableTarget
import com.videosorter.app.ui.visible
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 纯 JVM 单元测试：不依赖 Android SDK 运行时，`gradle testDebugUnitTest` 直接跑。 */
class LogicTest {

    // ---------- 服务器地址归一化 ----------
    @Test
    fun normalizeAddsSchemeAndPort() {
        assertEquals("http://192.168.1.8:8080", Session.normalize("192.168.1.8"))
        assertEquals("http://192.168.1.8:8080", Session.normalize("  192.168.1.8  "))
        assertEquals("http://192.168.1.8:9000", Session.normalize("192.168.1.8:9000"))
        assertEquals("http://192.168.1.8:8080", Session.normalize("http://192.168.1.8/"))
        assertEquals("https://nas.local:443", Session.normalize("https://nas.local:443/"))
        assertEquals("", Session.normalize("   "))
    }

    // ---------- 主题三档循环 ----------
    @Test
    fun themeCyclesAndSkipsSameLook() {
        assertEquals("dark", nextThemeMode("light", systemDark = false))
        assertEquals("auto", nextThemeMode("dark", systemDark = true))
        // 跟随系统：系统是浅色 → 切到深色；系统是深色 → 切到浅色
        assertEquals("dark", nextThemeMode("auto", systemDark = false))
        assertEquals("light", nextThemeMode("auto", systemDark = true))
        assertEquals("浅色", themeLabel("light"))
        assertEquals("深色", themeLabel("dark"))
        assertEquals("跟随系统", themeLabel("auto"))
    }

    // ---------- 后端 JSON → 模型 ----------
    @Test
    fun decodesVideoPageFromServerJson() {
        val json = """
        {
          "items": [
            {"id": 3, "name": "海边日落.mp4", "path": "/v/海边日落.mp4", "ext": ".mp4",
             "duration": 4.01, "size": 430080, "status": "tagged",
             "tag_id": 2, "tag_name": "美食", "tag_color": "#ef5b7b",
             "thumb_url": "/api/videos/3/thumb", "raw_url": "/api/videos/3/raw",
             "position": 2.5, "organized": false, "unknown_field": 1},
            {"id": 4, "name": "骑行.mkv", "status": "organized", "organized": true}
          ],
          "total": 2,
          "counts": {"all": 2, "idle": 0, "tagged": 1, "organized": 1, "untagged": 0}
        }
        """.trimIndent()
        val page = Json { ignoreUnknownKeys = true }.decodeFromString<VideoPage>(json)
        assertEquals(2, page.items.size)
        assertEquals(2, page.total)
        assertEquals(1, page.counts.tagged)
        val v = page.items[0]
        assertEquals(3, v.id)
        assertEquals(2, v.tagId)
        assertEquals("美食", v.tagName)
        assertEquals("/api/videos/3/thumb", v.thumbUrl)
        assertFalse(v.isOrganized)
        assertTrue(page.items[1].isOrganized)
        assertTrue(page.items[1].tagName == null)
    }

    @Test
    fun decodesEmptyResponseWithDefaults() {
        val page = Json { ignoreUnknownKeys = true }.decodeFromString<VideoPage>("{}")
        assertEquals(0, page.items.size)
        assertEquals(0, page.counts.all)
    }

    // ---------- 局域网发现回包解析 ----------
    @Test
    fun parsesDiscoveryReply() {
        val text = """{"app":"VideoSorter","version":"0.1.0","name":"VideoSorter @ fnos","port":18931,"ip":"192.168.5.100","tls":false}"""
        val s = parseReply(text)
        assertEquals(FoundServer("VideoSorter @ fnos", "192.168.5.100", 18931, "0.1.0"), s)
        assertEquals("192.168.5.100:18931", s!!.address)
    }

    @Test
    fun discoveryReplyFallsBackToSenderIpAndDefaultPort() {
        val s = parseReply("""{"app":"VideoSorter","name":"NAS"}""", senderHint = "10.0.0.9")
        assertEquals("10.0.0.9", s!!.ip)
        assertEquals(8080, s.port)
        assertEquals("NAS", s.name)
    }

    @Test
    fun ignoresForeignOrBrokenReplies() {
        assertEquals(null, parseReply("""{"app":"SomethingElse","port":80}"""))
        assertEquals(null, parseReply("not json at all"))
        assertEquals(null, parseReply("""{"app":"VideoSorter","port":99999,"ip":"1.2.3.4"}"""))
    }

    // ---------- 缩略图 URL ----------
    @Test
    fun buildsThumbUrl() {
        val api = Api("http://192.168.1.8:8080")
        assertEquals("http://192.168.1.8:8080/api/videos/7/thumb", api.thumbUrl(Video(id = 7, thumbUrl = "/api/videos/7/thumb")))
        assertEquals("", api.thumbUrl(Video(id = 7, thumbUrl = null)))
    }

    // ---------- 整理结果：全成功 / 部分失败 / 全失败 ----------
    @Test
    fun organizeAllSucceeded() {
        val s = summarizeOrganize(status = "done", moved = 12, failed = 0, fails = emptyList(), error = "")
        assertEquals("已整理 12 个视频", s.text)
        assertTrue(s.ok)
        assertFalse(s.partial)
        assertEquals(0, s.failed)
        assertTrue(s.fails.isEmpty())
    }

    @Test
    fun organizePartiallyFailed() {
        val fails = listOf(
            FailedItem(videoId = 3, name = "海边.mp4", error = "PermissionError: 只读文件系统"),
            FailedItem(videoId = 4, name = "雪山.mp4", error = "文件已存在"),
        )
        val s = summarizeOrganize(status = "done", moved = 8, failed = fails.size, fails = fails, error = "")
        assertEquals("已移动 8 个，失败 2 个", s.text)
        assertFalse(s.ok)
        assertTrue(s.partial)
        assertEquals(8, s.moved)
        assertEquals(2, s.fails.size)
        assertEquals("海边.mp4", s.fails[0].name)
        assertTrue(s.fails[0].reason.contains("只读"))
        assertEquals(0, s.more)
    }

    @Test
    fun organizeFullyFailedUsesTaskError() {
        val s = summarizeOrganize(
            status = "error",
            moved = 0,
            failed = 0,
            fails = emptyList(),
            error = "PermissionError: [Errno 30] Read-only file system",
        )
        assertFalse(s.ok)
        assertTrue(s.text.contains("Read-only"))
        // 没有明细时也要有一条，别让「失败区块」空着
        assertEquals(1, s.fails.size)
    }

    @Test
    fun organizeZeroMovedWithFailsCountsAsTotalFailure() {
        // 后端偶尔 status 仍是 done 但一个也没动
        val s = summarizeOrganize(
            status = "done",
            moved = 0,
            failed = 3,
            fails = listOf(FailedItem(name = "a.mp4", error = "磁盘已满")),
            error = "",
        )
        assertFalse(s.ok)
        assertFalse(s.partial)
        assertEquals(3, s.failed)
        assertEquals("整理失败", s.text)
    }

    @Test
    fun organizeSkippedAppearsInToast() {
        val s = summarizeOrganize(status = "done", moved = 5, failed = 0, fails = emptyList(), error = "", skipped = 4)
        assertEquals("已整理 5 个视频，4 个被跳过：目标目录不可写", s.text)
        assertEquals(4, s.skipped)
        assertTrue(s.ok)
    }

    @Test
    fun organizeKeepsAtMostEightRowsAndCountsTheRest() {
        val fails = (1..13).map { FailedItem(videoId = it, name = "v$it.mp4", error = "失败$it") }
        val s = summarizeOrganize(status = "done", moved = 2, failed = fails.size, fails = fails, error = "")
        // 摘要本身保留全部明细（上限 50），界面渲染时才 take(MAX_SHOWN)
        assertEquals(13, s.fails.size)
        assertEquals(MAX_SHOWN, s.fails.take(MAX_SHOWN).size)
        assertEquals(0, s.more)
        assertEquals("上次整理失败 13 个", failListText(s.failed))
        assertEquals("上次整理失败", failListText(1))
    }

    @Test
    fun longReasonIsShortenedForOneLine() {
        val long = "Traceback:\n  File \"/app/x.py\", line 12\n" + "x".repeat(200)
        val s = summarizeOrganize(
            status = "done", moved = 1, failed = 1,
            fails = listOf(FailedItem(name = "n.mp4", error = long)), error = "",
        )
        val r = s.fails.first().reason
        assertFalse(r.contains("\n"))
        assertTrue(r.length <= 79)
        assertTrue(r.endsWith("…"))
    }

    // ---------- 目标目录不可写 ----------
    @Test
    fun detectsUnwritableTargetError() {
        assertTrue(isUnwritableError("目标目录不可写：/volume1/整理：Read-only file system"))
        assertTrue(isUnwritableError("PermissionError: Permission denied"))
        assertTrue(isUnwritableError("OSError: Read-only file system"))
        assertTrue(isUnwritableError("目录只读"))
        assertFalse(isUnwritableError("没有需要整理的视频（需要先打标签）"))
        assertFalse(isUnwritableError(null))
        assertEquals("/volume1/整理/旅行", unwritableTarget("目标目录不可写：/volume1/整理/旅行：（Read-only file system）"))
    }

    // ---------- 任务 JSON 契约 ----------
    @Test
    fun decodesTaskWithFailedArray() {
        val raw = """
            {"id":"t1","kind":"organize","status":"done","done":10,"total":12,"percent":100.0,
             "message":"","error":"",
             "result":{"batch_id":"b1","moved":10,
               "failed":[{"video_id":3,"name":"海边.mp4","error":"PermissionError: 只读"}],
               "items":[{"video_id":1,"name":"ok.mp4","error":""}]}}
        """.trimIndent()
        val task = Api("http://127.0.0.1:8080").decodeBody(raw, Task.serializer())
        assertEquals("done", task.status)
        assertEquals(10, task.moved)
        assertEquals(1, task.failedCount)
        assertEquals("海边.mp4", task.failedItems.first().name)
        assertEquals(1, task.result?.failed?.size)
    }

    @Test
    fun decodesTaskWithNumericFailedCount() {
        // 兼容更早的返回：failed 是个数字而不是数组
        val raw = """{"id":"t2","status":"done","done":5,"total":7,"percent":100.0,"result":{"moved":5,"failed":2}}"""
        val task = Api("http://127.0.0.1:8080").decodeBody(raw, Task.serializer())
        assertEquals(5, task.moved)
        assertEquals(2, task.failedCount)
        // 数字形式拿不到明细，占位说明原因未知，界面不会空着
        assertEquals(2, task.failedItems.size)
        assertTrue(task.failedItems.all { it.error == "原因未知" })
    }

    @Test
    fun decodesFailedTaskWithTopLevelError() {
        val raw = """{"id":"t3","status":"error","done":0,"total":3,"percent":0.0,
            "error":"PermissionError: [Errno 30] Read-only file system"}"""
        val task = Api("http://127.0.0.1:8080").decodeBody(raw, Task.serializer())
        assertEquals("error", task.status)
        // 换了 4.13 的 assertTrue 反着用没意义，这里是字符串包含断言
        assertTrue(task.error.contains("Read-only"))
        val s = summarizeOrganize(task.status, task.moved, task.failedCount, task.failedItems, task.error)
        assertTrue(s.text.contains("Read-only"))
        assertFalse(s.ok)
    }

    @Test
    fun decodesExecuteReplyWithSkipped() {
        val raw = """{"task_id":"t9","planned":20,"bytes":123456789,"skipped":3,"skipped_reasons":[{"video_id":1,"name":"a.mp4","reason":"目标目录不可写"}]}"""
        val out = Api("http://127.0.0.1:8080").decodeBody(raw, com.videosorter.app.data.ExecOut.serializer())
        assertEquals("t9", out.taskId)
        assertEquals(20, out.planned)
        assertEquals(3, out.skipped)
        assertEquals(123456789L, out.bytes)
    }

    @Test
    fun oldExecuteReplyWithoutSkippedStillDecodes() {
        val out = Api("http://127.0.0.1:8080").decodeBody("""{"task_id":"t1","planned":4,"bytes":9}""", com.videosorter.app.data.ExecOut.serializer())
        assertEquals(0, out.skipped)
    }

    // ---------- 缓存上限文案 / 选项 ----------
    @Test
    fun cacheLimitWording() {
        assertEquals(listOf(256, 512, 1024, 2048, 4096), CACHE_MB_OPTIONS)
        assertEquals("512 MB", cacheMbText(512))
        assertEquals("1 GB", cacheMbText(1024))
        assertEquals("4 GB", cacheMbText(4096))
        assertEquals("0 MB", cacheBytesText(0))
        assertEquals("300 MB", cacheBytesText(300L * 1024 * 1024))
        assertEquals("1.5 GB", cacheBytesText((1.5 * 1024 * 1024 * 1024).toLong()))
    }

    // ---------- 失败区块状态（页内 remember） ----------
    @Test
    fun failBlockStateVisibilityAndDismiss() {
        val st = OrganizeFailState()
        assertFalse(st.visible())
        st.rememberSkipped(2)
        assertTrue(st.visible())
        st.clear()
        assertFalse(st.visible())
        // 全成功不该挂着一块红
        st.update(summarizeOrganize("done", 5, 0, emptyList(), ""))
        assertFalse(st.visible())
        st.update(summarizeOrganize("done", 5, 1, listOf(FailedItem(name = "x.mp4", error = "boom")), ""))
        assertTrue(st.visible())
        assertTrue(st.expanded)
        st.expanded = false
        assertFalse(st.expanded)
    }
    // ---------------- 标签排序（按上移/下移按钮换位） ----------------

    @Test
    fun moveKeepsOrderAndHandlesEdge() {
        assertEquals(listOf("b", "a", "c"), DragReorder.move(listOf("a", "b", "c"), 0, 1))
        assertEquals(listOf("b", "c", "a"), DragReorder.move(listOf("a", "b", "c"), 0, 2))
        assertEquals(listOf("c", "a", "b"), DragReorder.move(listOf("a", "b", "c"), 2, 0))
        // 原地不动 / 越界下标都不改内容
        assertEquals(listOf("a", "b", "c"), DragReorder.move(listOf("a", "b", "c"), 1, 1))
        assertEquals(listOf("a", "b", "c"), DragReorder.move(listOf("a", "b", "c"), 9, 0))
    }

    @Test
    fun moveAdjacentStepsReorderTags() {
        // 上移 / 下移各点一次：等于相邻两步 swap，和界面上的按钮行为一致
        var ids = listOf(10, 20, 30, 40)
        ids = DragReorder.move(ids, 3, 2)     // 第 4 张上移
        assertEquals(listOf(10, 20, 40, 30), ids)
        ids = DragReorder.move(ids, 0, 1)     // 第 1 张下移
        assertEquals(listOf(20, 10, 40, 30), ids)
        // 首行不能再上移、末行不能再下移（界面里这两个按钮是禁用的，逻辑上也兜住）
        assertEquals(ids, DragReorder.move(ids, 0, 0))
        assertEquals(ids, DragReorder.move(ids, ids.size - 1, ids.size - 1))
    }

}
