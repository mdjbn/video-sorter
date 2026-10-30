package com.videosorter.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.videosorter.app.data.Api
import com.videosorter.app.data.ApiException
import com.videosorter.app.data.Counts
import com.videosorter.app.data.LibraryHub
import com.videosorter.app.data.Transfers
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
    // 设置页是否处于二级页面（二级页面要隐藏 tab 栏）
    var settingsSub by remember { mutableStateOf(false) }

    // 系统返回手势：传输页 → 回到浏览页；其它 tab → 回到播放页；播放页才退出 App
    BackHandler(enabled = transferOpen || tab != 0) {
        if (transferOpen) transferOpen = false else tab = 0
    }
    var videos by remember { mutableStateOf<List<Video>>(emptyList()) }
    var counts by remember { mutableStateOf(Counts()) }
    var tags by remember { mutableStateOf<List<Tag>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var playerIndex by remember { mutableIntStateOf(0) }
    // 第一次拉到列表时用「上次播放的视频」定位，之后的过滤不要来回跳。
    // 这个值必须在发起任何网络请求之前读出来：reload 中间有多次挂起，期间界面可能已经
    // 把「第一个视频」写回存储，事后再读就拿不到真正的上次位置了。
    val bootLastVideoId = remember(api.base) { session.lastVideoId(api.base) }
    var resumedOnce by remember { mutableStateOf(false) }
    // 续播位置确定之前先别渲染播放页，否则会先画出第一个视频再切过去（闪一下）
    var bootResolved by remember(api.base) { mutableStateOf(false) }
    // 视频库筛选（服务端筛选）：状态 + 多个标签，播放器与视频库共用同一份结果
    var statusFilter by remember { mutableStateOf("all") }
    var tagFilter by remember { mutableStateOf<Set<Int>>(emptySet()) }
    // 视频库搜索词放在这一层：切到别的 tab 再回来（ListScreen 被销毁重建）也不会丢
    var libQuery by rememberSaveable { mutableStateOf("") }
    // 视频库的滚动位置同理：AnimatedContent 切 tab 会重建 ListScreen，state 提上来才留得住
    val libListState = rememberLazyListState()
    // 播放页是否处于横屏全屏：全屏时把底部标签栏一起藏掉，画面才真的铺满
    var playerFullscreen by remember { mutableStateOf(false) }

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
            val page = api.videos(filter = statusFilter, tags = tagFilter)
            videos = page.items
            counts = page.counts
            tags = api.tags()
            if (!resumedOnce) {
                val idx = videos.indexOfFirst { it.id == bootLastVideoId }
                if (idx >= 0) playerIndex = idx
                resumedOnce = true
            }
            bootResolved = true
            if (playerIndex >= videos.size) playerIndex = 0
            error = null
        } catch (e: Exception) {
            if (!authFail(e)) error = friendlyError(e)
        } finally {
            loading = false
            bootResolved = true
        }
    }

    // 别处改了播放记录（进度被清掉）时，把视频列表重新拉一趟，避免卡片上还挂着旧进度
    LaunchedEffect(LibraryHub.version) {
        if (LibraryHub.version > 0) reload(silent = true)
    }

    fun applyFilter(next: String, tags: Set<Int>) {
        val changed = next != statusFilter || tags != tagFilter
        statusFilter = next
        tagFilter = tags
        if (changed) scope.launch { reload(silent = true) }
    }

    fun markTag(videoId: Int, tagId: Int?) {
        scope.launch {
            runCatching { api.setTag(videoId, tagId) }
                .onSuccess { reload(silent = true) }
                .onFailure { if (!authFail(it)) toast(it.message ?: "标记失败", err = true) }
        }
    }


    fun downloadVideo(v: Video) {
        scope.launch {
            val key = TransferHub.start(v.name, "down")
            try {
                val res = Transfers.download(ctx, api, v, downloadTree(ctx)) { p ->
                    TransferHub.progress(key, p)
                }
                com.videosorter.app.data.TransferStore.add(
                    ctx,
                    com.videosorter.app.data.TransferItem(
                        name = v.name,
                        time = System.currentTimeMillis(),
                        bytes = v.size,
                        ok = true,
                        kind = "down",
                        where = res.where,
                        uri = res.uri,
                    ),
                )
                toast("已下载：${res.where}")
            } catch (e: Throwable) {
                val msg = e.message ?: "下载失败"
                TransferHub.fail(key, msg)
                com.videosorter.app.data.TransferStore.add(
                    ctx,
                    com.videosorter.app.data.TransferItem(
                        name = v.name,
                        time = System.currentTimeMillis(),
                        bytes = v.size,
                        ok = false,
                        kind = "down",
                        msg = msg,
                    ),
                )
                toast("下载失败：$msg", err = true)
            } finally {
                TransferHub.done(key)
            }
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
                0 -> if (!bootResolved) {
                    Box(Modifier.fillMaxSize().background(Color.Black))
                } else PlayerScreen(
                    api = api,
                    onFullscreenChange = { playerFullscreen = it },
                    videos = videos,
                    tags = tags,
                    counts = counts,
                    startIndex = playerIndex,
                    onIndexChange = { idx ->
                        playerIndex = idx
                        // 只在用户真的换片时落盘：启动初次的组合不能写，否则会把「第一个视频」覆盖上去
                        videos.getOrNull(idx)?.let { session.setLastVideoId(it.id, api.base) }
                    },
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
                    onDownload = ::downloadVideo,
                )

                1 -> ListScreen(
                    api = api,
                    videos = videos,
                    tags = tags,
                    loading = loading,
                    error = error,
                    status = statusFilter,
                    selectedTags = tagFilter,
                    query = libQuery,
                    onQuery = { libQuery = it },
                    onStatus = { next ->
                        applyFilter(next, if (next == "all") emptySet() else tagFilter)
                    },
                    onToggleTag = { id ->
                        val next = if (tagFilter.contains(id)) tagFilter - id else tagFilter + id
                        applyFilter(statusFilter, next)
                    },
                    onOpen = { id ->
                        val idx = videos.indexOfFirst { it.id == id }
                        if (idx >= 0) {
                            playerIndex = idx
                            tab = 0
                        }
                    },
                    onTag = { videoId, tagId -> markTag(videoId, tagId) },
                    onRefresh = { scope.launch { reload() } },
                    onDownload = ::downloadVideo,
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
                    listState = libListState,
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
                    onSubPage = { settingsSub = it },
                    onOpenVideo = { id ->
                        val idx = videos.indexOfFirst { it.id == id }
                        if (idx >= 0) {
                            playerIndex = idx
                            tab = 0
                        } else {
                            toast("这条记录的视频已不在库里")
                        }
                    },
                )

                else -> TransferScreen(
                    api = api,
                    onBack = { transferOpen = false },
                    onToast = { toast(it) },
                    onChanged = { scope.launch { reload(silent = true) } },
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
                    if (it != 3) settingsSub = false
                    tab = it
                },
                visible = !transferOpen && !sheets.visible && !settingsSub && !playerFullscreen,
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
