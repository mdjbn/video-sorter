package com.videosorter.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.videosorter.app.data.Api
import com.videosorter.app.data.Session
import com.videosorter.app.ui.LoginScreen
import com.videosorter.app.ui.MainScreen
import com.videosorter.app.ui.VideoSorterTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { AppRoot() }
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
