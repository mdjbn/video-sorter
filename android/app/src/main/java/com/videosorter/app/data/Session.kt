package com.videosorter.app.data

import android.content.Context
import androidx.core.content.edit
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * 本地会话：服务器列表 + 每台服务器的登录 token + 主题偏好。
 * 三端（服务端/网页端/手机端）各自独立，手机端可保存多台服务器。
 */
class Session(context: Context) {

    private val prefs = context.getSharedPreferences("vs_session", Context.MODE_PRIVATE)
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }

    var theme: String
        get() = prefs.getString("theme", "auto") ?: "auto"
        set(v) = prefs.edit { putString("theme", v) }

    /** 已保存的服务器地址，最近使用的在前 */
    fun servers(): List<String> = runCatching {
        json.decodeFromString<List<String>>(prefs.getString("servers", "[]") ?: "[]")
    }.getOrDefault(emptyList())

    var current: String
        get() = prefs.getString("current", "") ?: ""
        set(v) = prefs.edit { putString("current", v) }

    fun addServer(base: String) {
        val url = normalize(base)
        if (url.isEmpty()) return
        val list = servers().toMutableList()
        list.remove(url)
        list.add(0, url)
        prefs.edit {
            putString("servers", json.encodeToString(list.take(8)))
            putString("current", url)
        }
    }

    fun removeServer(base: String) {
        val url = normalize(base)
        val list = servers().filter { it != url }
        prefs.edit {
            putString("servers", json.encodeToString(list))
            remove("token:" + url)
            remove("tokenexp:" + url)
            remove("pass:" + url)
            if (current == url) putString("current", list.firstOrNull() ?: "")
        }
    }

    fun token(base: String = current): String = prefs.getString("token:" + normalize(base), "") ?: ""

    fun setToken(token: String, base: String = current) {
        prefs.edit { putString("token:" + normalize(base), token) }
    }

    fun clearToken(base: String = current) {
        prefs.edit {
            remove("token:" + normalize(base))
            remove("tokenexp:" + normalize(base))
        }
    }

    /** 勾选「保存密码」时把密码也存本地，下次打开自动填好 */
    var savePassword: Boolean
        get() = prefs.getBoolean("save_password", false)
        set(v) = prefs.edit { putBoolean("save_password", v) }

    /** 勾选「七天内保持登录」：令牌落盘并带 7 天有效期；不勾则只在本次运行内有效 */
    var keepLogin: Boolean
        get() = prefs.getBoolean("keep_login", true)
        set(v) = prefs.edit { putBoolean("keep_login", v) }

    fun password(base: String = current): String =
        if (!savePassword) "" else prefs.getString("pass:" + normalize(base), "") ?: ""

    fun setPassword(pass: String, base: String = current) {
        prefs.edit {
            if (savePassword && pass.isNotEmpty()) putString("pass:" + normalize(base), pass)
            else remove("pass:" + normalize(base))
        }
    }

    /** 令牌写入：keepDays > 0 表示这么多天内免登录，0 表示只在本次运行内有效 */
    fun setTokenWithExpiry(token: String, base: String = current, keepDays: Int = 7) {
        val exp = if (keepDays > 0) System.currentTimeMillis() + keepDays * 24L * 3600_000L else 0L
        prefs.edit {
            putString("token:" + normalize(base), token)
            putLong("tokenexp:" + normalize(base), exp)
        }
    }

    /** 取可用令牌：过期的当成没有（老版本没有 exp 字段的按永久有效，保持兼容） */
    fun validToken(base: String = current): String {
        val url = normalize(base)
        val t = prefs.getString("token:$url", "") ?: ""
        if (t.isEmpty()) return ""
        if (!prefs.contains("tokenexp:$url")) return t
        val exp = prefs.getLong("tokenexp:$url", 0L)
        return if (exp == 0L || System.currentTimeMillis() < exp) t else ""
    }

    /** 上次播到哪个视频：重新打开 App 从这里继续，而不是每次都从第一个开始 */
    fun lastVideoId(base: String = current): Int = prefs.getInt("lastvideo:" + normalize(base), 0)

    fun setLastVideoId(id: Int, base: String = current) {
        // commit = true：立即落盘，避免刚换完片就被系统杀掉进程导致记录丢失
        prefs.edit(commit = true) { putInt("lastvideo:" + normalize(base), id) }
    }

    fun lastUser(base: String = current): String = prefs.getString("user:" + normalize(base), "admin") ?: "admin"

    fun setLastUser(user: String, base: String = current) {
        prefs.edit { putString("user:" + normalize(base), user) }
    }

    companion object {
        /** 补全协议、去掉尾部斜杠、补默认端口 */
        fun normalize(raw: String): String {
            var s = raw.trim()
            if (s.isEmpty()) return ""
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
            s = s.trimEnd('/')
            val afterScheme = s.substringAfter("://")
            if (!afterScheme.contains(":")) s = "$s:8080"
            return s
        }
    }
}
