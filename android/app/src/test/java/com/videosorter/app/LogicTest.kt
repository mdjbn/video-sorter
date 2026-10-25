package com.videosorter.app

import com.videosorter.app.data.Session
import com.videosorter.app.data.VideoPage
import com.videosorter.app.ui.nextThemeMode
import com.videosorter.app.ui.themeLabel
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
}
