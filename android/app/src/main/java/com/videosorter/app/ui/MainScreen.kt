package com.videosorter.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.graphics.vector.ImageVector
import com.videosorter.app.data.Api
import com.videosorter.app.data.ApiException
import com.videosorter.app.data.Counts
import com.videosorter.app.data.Downloads
import com.videosorter.app.data.Session
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video
import kotlinx.coroutines.launch

private data class TabItem(val label: String, val icon: ImageVector)

@Composable
fun MainScreen(
    api: Api,
    session: Session,
    themeMode: String,
    onThemeChange: (String) -> Unit,
    onLogout: () -> Unit,
    onSwitchServer: (String) -> Unit = {},
) {
    var tab by remember { mutableIntStateOf(0) }
    var videos by remember { mutableStateOf<List<Video>>(emptyList()) }
    var counts by remember { mutableStateOf(Counts()) }
    var tags by remember { mutableStateOf<List<Tag>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    /** 把异常压成一句人话，避免把整段 JSON 解析栈糊在页面上 */
    fun friendlyError(e: Throwable): String {
        val raw = (e.message ?: e::class.simpleName ?: "未知错误").replace("\n", " ")
        val brief = raw.take(110)
        return "加载失败：$brief" + if (raw.length > 110) "…" else ""
    }
    var playerIndex by remember { mutableIntStateOf(0) }
    val ctx = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    fun toast(msg: String) {
        scope.launch { snackbar.showSnackbar(msg) }
    }

    /** token 失效时统一回登录页，避免界面上一直报「加载失败」。 */
    fun authFail(e: Throwable): Boolean {
        if (e is ApiException && e.code == 401) {
            session.clearToken(api.base)
            toast("登录已过期，请重新登录")
            onLogout()
            return true
        }
        return false
    }

    suspend fun reload(silent: Boolean = false) {
        if (!silent) loading = true
        try {
            val page = api.videos()
            videos = page.items
            counts = page.counts
            tags = api.tags()
            if (playerIndex >= videos.size) playerIndex = 0
            error = null
        } catch (e: Exception) {
            if (!authFail(e)) error = friendlyError(e)
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { reload() }

    val tabs = listOf(
        TabItem("播放", Icons.Default.PlayArrow),
        TabItem("列表", Icons.Default.List),
        TabItem("整理", Icons.Default.Sort),
        TabItem("设置", Icons.Default.Settings),
    )

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
                tabs.forEachIndexed { i, item ->
                    NavigationBarItem(
                        selected = tab == i,
                        onClick = { tab = i },
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = null,
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = MaterialTheme.colorScheme.primary,
                            unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            indicatorColor = MaterialTheme.colorScheme.primary.copy(alpha = 0.14f),
                        ),
                    )
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad)) {
            when (tab) {
                0 -> PlayerScreen(
                    api = api,
                    videos = videos,
                    tags = tags,
                    counts = counts,
                    startIndex = playerIndex,
                    onIndexChange = { playerIndex = it },
                    onTag = { videoId, tagId ->
                        scope.launch {
                            runCatching { api.setTag(videoId, tagId) }
                                .onSuccess { reload(silent = true) }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "标记失败") }
                        }
                    },
                    onCreateTag = { name, color ->
                        scope.launch {
                            runCatching { api.createTag(name, color) }
                                .onSuccess { reload(silent = true) }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "创建失败") }
                        }
                    },
                )

                1 -> ListScreen(
                    api = api,
                    videos = videos,
                    tags = tags,
                    loading = loading,
                    error = error,
                    onOpen = { id ->
                        val idx = videos.indexOfFirst { it.id == id }
                        if (idx >= 0) { playerIndex = idx; tab = 0 }
                    },
                    onTag = { videoId, tagId ->
                        scope.launch {
                            runCatching { api.setTag(videoId, tagId) }
                                .onSuccess { reload(silent = true) }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "标记失败") }
                        }
                    },
                    onRefresh = { scope.launch { reload() } },
                    onDownload = { v ->
                        runCatching { Downloads.save(ctx, api, v) }
                            .onSuccess { toast("开始下载：${v.name}") }
                            .onFailure { toast("下载失败：${it.message}") }
                    },
                    onDelete = { v ->
                        scope.launch {
                            runCatching { api.deleteVideo(v.id, false) }
                                .onSuccess { reload(silent = true); toast("已删除记录") }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "删除失败") }
                        }
                    },
                )

                2 -> OrganizeScreen(
                    api = api,
                    onToast = ::toast,
                    onOrganized = { scope.launch { reload(silent = true) } },
                )

                else -> SettingsScreen(
                    api = api,
                    session = session,
                    tags = tags,
                    themeMode = themeMode,
                    onThemeChange = onThemeChange,
                    counts = counts,
                    onToast = ::toast,
                    onRefresh = { scope.launch { reload() } },
                    onLogout = {
                        scope.launch { runCatching { api.logout() } }
                        onLogout()
                    },
                    onSwitchServer = onSwitchServer,
                )
            }
        }
    }
}
