package com.videosorter.app

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import coil.Coil
import coil.ImageLoader
import androidx.compose.runtime.DisposableEffect
import com.videosorter.app.data.Api
import com.videosorter.app.data.AuthEvents
import com.videosorter.app.data.Session
import com.videosorter.app.ui.LoginScreen
import com.videosorter.app.ui.MainScreen
import com.videosorter.app.ui.VideoSorterTheme
import okhttp3.OkHttpClient

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        installImageLoader()
        // 播放缓存（预加载写入、播放读取）
        com.videosorter.app.data.MediaCache.init(applicationContext)
        setContent { AppRoot() }
    }

    /**
     * 缩略图接口也要 Bearer 令牌（`/api/videos/{id}/thumb` 未登录返回 401），
     * 而 Coil 自己的 OkHttpClient 不带任何请求头 → 列表缩略图全空白。
     * 这里给它挂一个拦截器，token 每次请求时实时读取（登录/切换服务器后自动生效）。
     */
    private fun installImageLoader() {
        val session = Session(this)
        val client = OkHttpClient.Builder()
            .addInterceptor { chain ->
                val req = chain.request()
                val token = session.token(session.current)
                if (req.url.encodedPath.startsWith("/api/") && token.isNotEmpty()) {
                    chain.proceed(req.newBuilder().header("Authorization", "Bearer $token").build())
                } else {
                    chain.proceed(req)
                }
            }
            .build()
        Coil.setImageLoader(ImageLoader.Builder(this).okHttpClient(client).build())
    }
}

@Composable
private fun AppRoot() {
    val ctx = LocalContext.current
    val session = remember { Session(ctx) }
    var themeMode by remember { mutableStateOf(session.theme) }
    var api by remember { mutableStateOf<Api?>(null) }

    // 启动时若有已保存的服务器 + token，直接用
    remember {
        val saved = session.current
        if (saved.isNotBlank()) {
            val token = session.token(saved)
            if (token.isNotBlank()) api = Api(saved, token)
        }
        true
    }

    // 任意接口 401 → 清令牌回登录页（在后台线程触发，必须切回主线程改 Compose 状态）
    val mainHandler = remember { Handler(Looper.getMainLooper()) }
    DisposableEffect(Unit) {
        AuthEvents.onUnauthorized = {
            mainHandler.post {
                session.current.let { session.clearToken(it) }
                api = null
            }
        }
        onDispose { AuthEvents.onUnauthorized = null }
    }

    VideoSorterTheme(mode = themeMode) {
        val current = api
        if (current == null) {
            LoginScreen(
                session = session,
                themeMode = themeMode,
                onThemeChange = { themeMode = it; session.theme = it },
                onLoggedIn = { a, user ->
                    session.addServer(a.base)
                    session.setToken(a.token ?: "", a.base)
                    session.setLastUser(user, a.base)
                    api = a
                },
            )
        } else {
            MainScreen(
                api = current,
                session = session,
                themeMode = themeMode,
                onThemeChange = { themeMode = it; session.theme = it },
                onLogout = {
                    session.clearToken(current.base)
                    api = null
                },
                onSwitchServer = { url ->
                    session.current = url
                    val token = session.token(url)
                    api = if (token.isNotBlank()) Api(url, token) else null
                },
            )
        }
    }
}
