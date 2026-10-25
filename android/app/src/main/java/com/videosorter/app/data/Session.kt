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
            if (current == url) putString("current", list.firstOrNull() ?: "")
        }
    }

    fun token(base: String = current): String = prefs.getString("token:" + normalize(base), "") ?: ""

    fun setToken(token: String, base: String = current) {
        prefs.edit { putString("token:" + normalize(base), token) }
    }

    fun clearToken(base: String = current) {
        prefs.edit { remove("token:" + normalize(base)) }
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
