package com.videosorter.app.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.videosorter.app.data.Api
import com.videosorter.app.data.ApiException
import com.videosorter.app.data.Counts
import com.videosorter.app.data.Downloads
import com.videosorter.app.data.Session
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video
import kotlinx.coroutines.launch

private const val TAB_TRANSFER = 4

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
    var transferOpen by remember { mutableStateOf(false) }
    var videos by remember { mutableStateOf<List<Video>>(emptyList()) }
    var counts by remember { mutableStateOf(Counts()) }
    var tags by remember { mutableStateOf<List<Tag>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var playerIndex by remember { mutableIntStateOf(0) }

    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val sheets = remember { SheetState() }
    val toastState = remember { ToastState() }

    fun toast(msg: String, err: Boolean = false) = toastState.show(msg, err)

    /** 把异常压成一句人话，避免把整段 JSON 解析栈糊在页面上 */
    fun friendlyError(e: Throwable): String {
        val raw = (e.message ?: e::class.simpleName ?: "未知错误").replace("\n", " ")
        val brief = raw.take(110)
        return "加载失败：$brief" + if (raw.length > 110) "…" else ""
    }

    /** token 失效时统一回登录页，避免界面上一直报「加载失败」。 */
    fun authFail(e: Throwable): Boolean {
        if (e is ApiException && e.code == 401) {
            session.clearToken(api.base)
            toast("登录已过期，请重新登录", err = true)
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

    fun markTag(videoId: Int, tagId: Int?) {
        scope.launch {
            runCatching { api.setTag(videoId, tagId) }
                .onSuccess { reload(silent = true) }
                .onFailure { if (!authFail(it)) toast(it.message ?: "标记失败", err = true) }
        }
    }

    LaunchedEffect(Unit) { reload() }

    Box(Modifier.fillMaxSize()) {
        AmbientBackdrop()

        AnimatedContent(
            targetState = if (transferOpen) TAB_TRANSFER else tab,
            transitionSpec = {
                if (targetState == TAB_TRANSFER || initialState == TAB_TRANSFER) {
                    (slideInHorizontally(tween(260)) { if (targetState == TAB_TRANSFER) it / 3 else -it / 4 } + fadeIn(tween(200)))
                        .togetherWith(slideOutHorizontally(tween(240)) { if (targetState == TAB_TRANSFER) -it / 5 else it / 4 } + fadeOut(tween(150)))
                } else {
                    (fadeIn(tween(220)) + scaleIn(tween(260), initialScale = 0.985f))
                        .togetherWith(fadeOut(tween(150)) + scaleOut(tween(200), targetScale = 1.01f))
                }
            },
            modifier = Modifier.fillMaxSize(),
            label = "tab-content",
        ) { target ->
            when (target) {
                0 -> PlayerScreen(
                    api = api,
                    videos = videos,
                    tags = tags,
                    counts = counts,
                    startIndex = playerIndex,
                    onIndexChange = { playerIndex = it },
                    onTag = { videoId, tagId -> markTag(videoId, tagId) },
                    onCreateTag = { name, color ->
                        scope.launch {
                            runCatching { api.createTag(name, color) }
                                .onSuccess { reload(silent = true) }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "创建失败", err = true) }
                        }
                    },
                    toast = ::toast,
                    sheets = sheets,
                    onOpenList = { tab = 1 },
                    onRefresh = { scope.launch { reload(silent = true) } },
                )

                1 -> ListScreen(
                    api = api,
                    videos = videos,
                    tags = tags,
                    loading = loading,
                    error = error,
                    onOpen = { id ->
                        val idx = videos.indexOfFirst { it.id == id }
                        if (idx >= 0) {
                            playerIndex = idx
                            tab = 0
                        }
                    },
                    onTag = { videoId, tagId -> markTag(videoId, tagId) },
                    onRefresh = { scope.launch { reload() } },
                    onDownload = { v ->
                        runCatching { Downloads.save(ctx, api, v) }
                            .onSuccess { toast("开始下载：${v.name}") }
                            .onFailure { toast("下载失败：${it.message}", err = true) }
                    },
                    onDelete = { v ->
                        scope.launch {
                            runCatching { api.deleteVideo(v.id, false) }
                                .onSuccess { reload(silent = true); toast("已删除记录") }
                                .onFailure { if (!authFail(it)) toast(it.message ?: "删除失败", err = true) }
                        }
                    },
                    onOpenTransfer = { transferOpen = true },
                    toast = ::toast,
                    sheets = sheets,
                )

                2 -> OrganizeScreen(
                    api = api,
                    onToast = { toast(it) },
                    onOrganized = { scope.launch { reload(silent = true) } },
                )

                3 -> SettingsScreen(
                    api = api,
                    session = session,
                    tags = tags,
                    themeMode = themeMode,
                    onThemeChange = onThemeChange,
                    counts = counts,
                    onToast = { toast(it) },
                    onRefresh = { scope.launch { reload() } },
                    onLogout = {
                        scope.launch { runCatching { api.logout() } }
                        onLogout()
                    },
                    onSwitchServer = onSwitchServer,
                    onOpenTransfer = { transferOpen = true },
                    onOpenVideo = { id ->
                        val idx = videos.indexOfFirst { it.id == id }
                        if (idx >= 0) {
                            playerIndex = idx
                            tab = 0
                        }
                    },
                    sheets = sheets,
                )

                else -> TransferScreen(
                    api = api,
                    onBack = { transferOpen = false },
                    onToast = { toast(it) },
                )
            }
        }

        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .navigationBarsPadding()
        ) {
            LiquidTabBar(
                current = tab,
                onSelect = {
                    transferOpen = false
                    tab = it
                },
                visible = !transferOpen,
            )
        }

        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .navigationBarsPadding()
                .padding(bottom = 152.dp, start = 18.dp, end = 18.dp)
        ) {
            ToastHost(toastState)
        }

        SheetHost(sheets)
    }
}
