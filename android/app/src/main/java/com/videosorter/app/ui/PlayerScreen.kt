package com.videosorter.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Fullscreen
import androidx.compose.material.icons.rounded.Label
import androidx.compose.material.icons.rounded.LabelOff
import androidx.compose.material.icons.rounded.MoreHoriz
import androidx.compose.material.icons.rounded.FullscreenExit
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import com.videosorter.app.data.Api
import com.videosorter.app.data.Counts
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.math.abs
import kotlin.math.roundToInt

private val TAG_COLORS = listOf(
    "#f4a259", "#ef5b7b", "#4cc9f0", "#9b8cff",
    "#35d18a", "#f2c14e", "#ef7d4f", "#8d98a8",
)

private data class HudSpec(val text: String, val label: String, val pct: Float)

@Composable
fun PlayerScreen(
    api: Api,
    onDownload: (Video) -> Unit = {},
    videos: List<Video>,
    tags: List<Tag>,
    counts: Counts,
    startIndex: Int,
    // 在列表被重新拉取（换筛选、改标签）后，靠这个 id 把播放位置接回原来那条视频：
    // 只按数组下标定位的话，一旦列表顺序变了就会莫名其妙跳片。
    startVideoId: Int = -1,
    onIndexChange: (Int) -> Unit,
    onTag: (Int, Int?) -> Unit,
    onCreateTag: (String, String) -> Unit,
    toast: (String) -> Unit,
    sheets: SheetState,
    onOpenList: () -> Unit = {},
    onRefresh: () -> Unit = {},
    onFullscreenChange: (Boolean) -> Unit = {},
) {
    val t = tokens()
    val ctx = LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val dark = t.dark
    // 横屏全屏：只由这个按钮控制，不跟随手机旋转（列表/设置等其他页面永远竖屏）
    var fullscreen by remember { mutableStateOf(false) }
    FullscreenEffect(fullscreen)
    LaunchedEffect(fullscreen) { onFullscreenChange(fullscreen) }
    // 全屏时返回键先退出全屏，而不是直接退出 App / 跳回列表
    BackHandler(enabled = fullscreen) { fullscreen = false }
    // 离开播放页时把外层状态复位，否则切到列表页底部标签栏会是隐藏的
    DisposableEffect(Unit) {
        onDispose { onFullscreenChange(false) }
    }

    // 媒体请求也要带 Bearer 令牌：/api/videos/{id}/raw 与 HLS 分片都要求鉴权，
    // 否则 ExoPlayer 会拿到 401 并报 ERROR_CODE_IO_BAD_HTTP_STATUS。
    val player = remember(api.token) {
        // 设置页改过「播放缓存上限」后旧缓存已被丢弃，进播放页时按新上限重建才是安全时机
        //（正在用着的 SimpleCache 不能 release，ExoPlayer 会直接抛 IllegalStateException）
        com.videosorter.app.data.MediaCache.buildIfNeeded(ctx)
        // 走带磁盘缓存的 DataSource：预加载写进来的数据，真正播放时直接命中缓存
        val cacheFactory = com.videosorter.app.data.MediaCache.sourceFactory(api.headers(), ctx)
        val loadControl = androidx.media3.exoplayer.DefaultLoadControl.Builder()
            .setBufferDurationsMs(2_000, 30_000, 250, 600)
            .setPrioritizeTimeOverSizeThresholds(true)
            .build()
        ExoPlayer.Builder(ctx)
            .setMediaSourceFactory(androidx.media3.exoplayer.source.DefaultMediaSourceFactory(cacheFactory))
            .setLoadControl(loadControl)
            .build()
            .apply { playWhenReady = true }
    }

    val count = videos.size
    // 初始页：优先按视频 id 找（列表可能因为筛选/改标签而重排过），找不到才退回下标
    val initialPage = remember {
        val byId = if (startVideoId > 0) videos.indexOfFirst { it.id == startVideoId } else -1
        (if (byId >= 0) byId else startIndex).coerceIn(0, (count - 1).coerceAtLeast(0))
    }
    val pagerState = rememberPagerState(initialPage = initialPage) {
        count.coerceAtLeast(1)
    }

    // 预加载后面 2 个视频（换片时会先取消上一轮预加载）
    LaunchedEffect(pagerState.currentPage, count) {
        if (count > 0) {
            com.videosorter.app.data.Preloader.warm(scope, api, videos, pagerState.currentPage + 1, 2)
        }
    }

    // 正在按外部指定位置滚动 pager（此时 currentPage 的变化不该回报给上层，否则会把
    // 「续播定位」当成用户换片，直接把位置改回第一个）
    var pagerSyncing by remember { mutableStateOf(false) }
    // 首次按 startIndex 定位完成之前，pager 的 currentPage 不算数（否则会把续播定位冲掉）
    var syncReady by remember { mutableStateOf(false) }
    // 上一次看到的列表条数：用来区分「只是重排」和「筛选结果真变了」
    var lastCount by remember { mutableIntStateOf(count) }

    // 记住「正在播的是哪条视频」，列表重排后按它把 pager 拨回去。
    //
    // 这是「改标签不再跳片」的核心：列表是服务端筛选结果，改标签/换筛选会把同一条视频
    // 挪到别的下标（甚至整个掉出去）。pager 盯的是下标，所以内容一换它就会显示成另一条。
    // 用 id 记身份，列表一变就按 id 重新对齐，播放器感知不到任何「换片」。
    var playingVideoId by remember { mutableIntStateOf(-1) }

    // 列表内容变了（同一个 currentPage 指向了别的视频）→ 按 id 把 pager 拨回原视频
    LaunchedEffect(videos) {
        if (!syncReady || pagerSyncing || count <= 0) return@LaunchedEffect
        val wantId = when {
            // 上层明确指定了要播哪条 → 以它为准
            startVideoId > 0 -> startVideoId
            // 否则维持当前正在播的那条
            else -> playingVideoId
        }
        if (wantId <= 0) return@LaunchedEffect
        val idx = videos.indexOfFirst { it.id == wantId }
        if (idx < 0) return@LaunchedEffect           // 这条已不在筛选里：原地不动，继续播它
        if (idx == pagerState.currentPage) return@LaunchedEffect
        pagerSyncing = true
        try {
            pagerState.scrollToPage(idx)             // 瞬间对齐，不做滚动动画，用户看不到位移
        } finally {
            pagerSyncing = false
        }
    }

    // 外部指定要播第几个（续播定位、播放历史跳转、整理页跳转、播完自动下一个）→ 同步到 pager。
    //
    // 关键约束：**列表重排不该换片**。改标签会让服务端筛选结果变样（比如正在按「旅行」筛选，
    // 把这个视频改成「美食」，它就掉出列表了），重拉后下标对应的已经是别的视频。
    // 所以定位优先用 id：id 还在列表里就按 id 找；id 不见了（被筛掉/被删）才退回下标。
    LaunchedEffect(startIndex, startVideoId, count) {
        if (count <= 0) {
            syncReady = true
            return@LaunchedEffect
        }
        val byId = if (startVideoId > 0) videos.indexOfFirst { it.id == startVideoId } else -1
        // 当前正在播的那条还在列表里 → 什么都不用做（列表重排而已，别打断播放）
        val curId = videos.getOrNull(pagerState.currentPage)?.id
        if (startVideoId > 0 && curId == startVideoId) {
            syncReady = true
            return@LaunchedEffect
        }
        // startVideoId=-1（当前视频被筛掉、上层已放弃按 id 定位）且列表条数没变 → 是重排，
        // 不是用户要换片，保持原位。条数变了才说明筛选结果真变了，按 startIndex 走。
        if (startVideoId <= 0 && count == lastCount) {
            syncReady = true
            return@LaunchedEffect
        }
        val target = if (byId >= 0) byId else startIndex
        if (target in 0 until count && target != pagerState.currentPage) {
            pagerSyncing = true
            try {
                // 还没露过面（启动续播）就瞬间定位，避免「先显示第一个视频再滑上去」的闪烁
                if (!syncReady) pagerState.scrollToPage(target) else pagerState.animateScrollToPage(target)
            } finally {
                pagerSyncing = false
            }
        }
        lastCount = count
        syncReady = true
    }

    var playing by remember { mutableStateOf(true) }
    var speed by remember { mutableFloatStateOf(1f) }
    var tempSpeed by remember { mutableStateOf<Float?>(null) }
    var lockedSpeed by remember { mutableStateOf<Float?>(null) }
    var position by remember { mutableStateOf(0.0) }
    var duration by remember { mutableStateOf(0.0) }
    // 正在拖进度条（拖动期间 position 是预览值，轮询不要覆盖它）
    var scrubActive by remember { mutableStateOf(false) }
    // 拖进度条期间视频正好播完了：压住「自动下一个」，等松手 seek 完再继续。
    // 不压的话，用户手指还按在进度条上、正想往回拖，画面已经跳到下一个视频了。
    var endedWhileScrubbing by remember { mutableStateOf(false) }
    var hud by remember { mutableStateOf<HudSpec?>(null) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var loadingSrc by remember { mutableStateOf(true) }
    var lastLoadedId by remember { mutableIntStateOf(-1) }
    var lastReloadKey by remember { mutableIntStateOf(0) }
    // 标签栏显隐（底部那排标签胶囊）
    var tagsOpen by rememberSaveable { mutableStateOf(true) }
    // 新视频的第一帧是否已经出来：没有之前用封面盖住，避免看到上一个视频的残留画面
    var videoReady by remember { mutableStateOf(false) }
    var transcodePct by remember { mutableIntStateOf(-1) }
    // 当前这路是不是服务端转码（HLS）。直连原文件失败时要靠它决定「换转码重试」还是「报错」
    var usingHls by remember { mutableStateOf(false) }
    // 直连失败 → 换成转码版重放：改这个 key 让下面的 LaunchedEffect 重跑一次
    var reloadKey by remember { mutableIntStateOf(0) }

    val current = videos.getOrNull(pagerState.currentPage)

    /** 切到服务端转码版重来一次（同一个视频，不换页）。 */
    fun pickHlsMode(videoId: Int) {
        if (usingHls) return
        api.markHlsFallback(videoId)
        usingHls = true
        errorMsg = null
        reloadKey++
    }

    fun effSpeed() = tempSpeed ?: lockedSpeed ?: speed

    fun applySpeed() = player.setPlaybackSpeed(effSpeed())

    /**
     * 保存进度：播到结尾（含结尾 1.5 秒内）就记成 0，
     * 否则会留下 00:15/00:15 这种记录，下次进来又卡在结尾。
     */
    fun savePos(videoId: Int) {
        val dur = if (duration > 0) duration else (player.duration.coerceAtLeast(0L) / 1000.0)
        var pos = player.currentPosition / 1000.0
        if (dur > 0 && pos >= dur - 1.5) pos = 0.0
        if (pos < 0) pos = 0.0
        scope.launch { runCatching { api.saveProgress(videoId, pos, dur) } }
    }

    fun speedText(v: Float): String {
        val text = if (v % 1f == 0f) "%.1f".format(v) else "%.2f".format(v).trimEnd('0').trimEnd('.')
        return "$text×"
    }

    fun cycleSpeed() {
        speed = when (speed) {
            1f -> 1.25f
            1.25f -> 1.5f
            1.5f -> 2f
            2f -> 0.5f
            else -> 1f
        }
        tempSpeed = null
        lockedSpeed = null
        applySpeed()
        toast("倍速已切换为 ${speedText(speed)}")
    }

    // 页面切换 → 换片
    LaunchedEffect(pagerState.currentPage, current?.id, reloadKey) {
        val v = current ?: return@LaunchedEffect
        // 列表还没到 / 正在按外部位置同步时不要回报，避免启动瞬间把定位覆盖成 0
        if (syncReady && !pagerSyncing && count > 0) onIndexChange(pagerState.currentPage)
        // 真的换了片（用户翻页 / 外部跳转）才更新身份。列表重排时 pager 还没对齐，
        // 这里的 v 可能已经是别的视频，绝不能拿去覆盖「正在播哪条」。
        if (v.id != lastLoadedId) playingVideoId = v.id
        // reloadKey 变化（直连失败改走转码）时同一视频要重新加载一次，所以不能只看 videoId
        if (v.id == lastLoadedId && reloadKey == lastReloadKey) return@LaunchedEffect
        if (v.id != lastLoadedId) usingHls = api.hlsFallback(v.id)
        lastLoadedId = v.id
        lastReloadKey = reloadKey
        errorMsg = null
        loadingSrc = true
        position = 0.0
        // 换片：立刻盖住封面，并把上一路彻底停掉，否则新 surface 会先画出旧视频的最后一帧
        videoReady = false
        runCatching {
            player.stop()
            player.clearMediaItems()
        }
        // 服务端优先给「直连原文件」（手机能硬解 MKV/HEVC/AC3，不转码、不占 NAS）；
        // 若这台机器的解码器吃不下、之前已经失败过一次，这里直接要转码版。
        val wantHls = usingHls
        var info = runCatching {
            if (wantHls) api.playTranscode(v.id) else api.play(v.id)
        }.getOrNull()
        if (info == null || info.mode == "error") {
            errorMsg = info?.message ?: "无法获取播放地址"
            loadingSrc = false
            return@LaunchedEffect
        }
        // 文件已被删除/移走：别把不存在的地址交给播放器（会报容器解析失败）
        if (info.mode == "missing") {
            errorMsg = "视频文件不存在（可能已被删除或移动），重新扫描源文件夹可更新"
            loadingSrc = false
            return@LaunchedEffect
        }
        // HLS 模式要等切片就绪：直接给 ExoPlayer 一个还没生成的 m3u8 会 404 失败
        if (info.mode == "hls") {
            transcodePct = 0
            var misses = 0
            while (transcodePct >= 0) {
                val st = runCatching { api.hlsStatus(v.id) }.getOrNull()
                if (st == null) {
                    misses++
                    if (misses > 6) break
                } else {
                    if (st.error.isNotEmpty()) {
                        errorMsg = "转码失败：${st.error}"
                        loadingSrc = false
                        transcodePct = -1
                        return@LaunchedEffect
                    }
                    if (st.ready) break
                    transcodePct = st.percent
                }
                delay(700)
            }
            transcodePct = -1
        }
        usingHls = info.mode == "hls"
        val url = api.base + (info.url ?: "")
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        applySpeed()
        // 续播：只有「看到一半」才跳过去；已经看到结尾（进度接近总时长）的当作从头播，
        // 否则 seek 到时长末尾会立刻 STATE_ENDED，看起来就是「打不开、直接跳下一个」
        val resume = v.position ?: 0.0
        val totalSec = if (v.duration > 0) v.duration else 0.0
        val nearEnd = totalSec > 0 && resume >= totalSec - 2.0
        if (resume > 3 && !nearEnd) player.seekTo((resume * 1000).toLong())
    }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }

            override fun onRenderedFirstFrame() {
                videoReady = true
            }

            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) loadingSrc = false
                if (state == Player.STATE_ENDED) {
                    // 播完了：进度记 0（下次从头播），再自动下一个
                    current?.let { savePos(it.id) }
                    if (ScrubEnd.onEnded(scrubActive) == ScrubEnd.OnEnded.HOLD) {
                        // 用户正按着进度条预览：先停在这里，不要跳下一个。
                        // 松手后进度条那段逻辑会 seek 到滑块位置并恢复播放，
                        // endedWhileScrubbing 在那里被消费掉。
                        endedWhileScrubbing = true
                        player.playWhenReady = false
                    } else if (pagerState.currentPage + 1 < count) {
                        onIndexChange(pagerState.currentPage + 1)
                    }
                }
            }

            override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                // 直连原文件失败（这台机器的解码器吃不下这个编码）→ 记下来并换成服务端转码版
                // 重来一次；已经在转码模式还失败就如实报错，免得来回重试。
                val v = current
                if (v != null && !usingHls) {
                    pickHlsMode(v.id)
                    return
                }
                errorMsg = "播放失败：${error.errorCodeName}"
                loadingSrc = false
                videoReady = true
            }
        }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }

    // 手势只允许落在视频画面里（上下黑边不响应），这里持续跟踪画面矩形
    var videoRect by remember { mutableStateOf(androidx.compose.ui.geometry.Rect.Zero) }
    var surfaceW by remember { mutableFloatStateOf(1f) }
    var surfaceH by remember { mutableFloatStateOf(1f) }
    LaunchedEffect(Unit) {
        while (true) {
            if (!scrubActive) position = player.currentPosition / 1000.0
            duration = (player.duration.takeIf { it > 0 } ?: 0L) / 1000.0
            val vs = player.videoSize
            if (vs.width > 0 && vs.height > 0) {
                // PlayerView 默认 RESIZE_MODE_FIT：按比例缩放后居中
                val scale = minOf(surfaceW / vs.width, surfaceH / vs.height)
                val w = vs.width * scale
                val h = vs.height * scale
                videoRect = androidx.compose.ui.geometry.Rect(
                    left = (surfaceW - w) / 2f,
                    top = (surfaceH - h) / 2f,
                    right = (surfaceW + w) / 2f,
                    bottom = (surfaceH + h) / 2f,
                )
            }
            delay(250)
        }
    }

    // 每 5 秒保存一次进度
    LaunchedEffect(current?.id, playing) {
        val v = current ?: return@LaunchedEffect
        while (playing) {
            delay(5000)
            savePos(v.id)
        }
    }

    // 播放器实例会随 token 变化重建，必须按实例释放，否则旧实例泄漏（同时占着解码器）
    DisposableEffect(player) { onDispose { player.release() } }

    fun togglePlay() {
        tempSpeed = null
        applySpeed()
        when {
            player.isPlaying -> player.pause()
            player.playbackState == Player.STATE_ENDED -> {
                player.seekTo(0); player.play()
            }

            else -> player.play()
        }
    }

    fun openRename(v: Video) {
        sheets.open("重命名", "只改文件名，保留扩展名") {
            var name by remember { mutableStateOf(v.name.substringBeforeLast('.')) }
            val shape = RoundedCornerShape(11.dp)
            TextField(
                value = name,
                onValueChange = { name = it.take(80) },
                singleLine = true,
                placeholder = { Text("文件名", color = t.muted2, fontSize = 13.sp) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { }),
                shape = shape,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = t.ink(0.06f),
                    unfocusedContainerColor = t.ink(0.06f),
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    focusedTextColor = t.text,
                    unfocusedTextColor = t.text,
                    cursorColor = t.accent,
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 14.dp)
                    .border(1.dp, t.line2, shape),
            )
            Row(Modifier.fillMaxWidth().padding(top = 18.dp), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                SheetButton("取消", primary = false, modifier = Modifier.weight(1f)) { sheets.close() }
                SheetButton("保存", primary = true, modifier = Modifier.weight(1f)) {
                    val newName = name.trim()
                    sheets.close()
                    if (newName.isEmpty()) return@SheetButton
                    scope.launch {
                        val ext = v.name.substringAfterLast('.', "")
                        val full = if (ext.isEmpty() || newName.endsWith(".$ext")) newName else "$newName.$ext"
                        runCatching { api.rename(v.id, full) }
                            .onSuccess { toast("已重命名"); onRefresh() }
                            .onFailure { toast("重命名失败：${it.message}") }
                    }
                }
            }
        }
    }

    fun openMore(v: Video) {
        sheets.open(v.name, "网页端也能做这些操作") {
            SheetActionRow(Icons.Rounded.Edit, "重命名") {
                sheets.close()
                openRename(v)
            }
            SheetActionRow(Icons.Rounded.Download, "下载到手机") {
                sheets.close()
                onDownload(v)
            }
            SheetActionRow(Icons.Rounded.Speed, "倍速 · 当前 ${speedText(effSpeed())}${if (lockedSpeed != null) "（已固定）" else ""}") {
                cycleSpeed()
                sheets.close()
            }
            SheetActionRow(Icons.Rounded.Delete, "删除视频", danger = true) {
                sheets.close()
                sheets.open("删除视频", "会同时删除服务器上的文件，不可恢复") {
                    Row(Modifier.fillMaxWidth().padding(top = 18.dp), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                        SheetButton("取消", primary = false, modifier = Modifier.weight(1f)) { sheets.close() }
                        SheetButton("删除", primary = true, danger = true, modifier = Modifier.weight(1f)) {
                            sheets.close()
                            scope.launch {
                                runCatching { api.deleteVideo(v.id, true) }
                                    .onSuccess { toast("已删除"); onRefresh() }
                                    .onFailure { toast("删除失败：${it.message}") }
                            }
                        }
                    }
                }
            }
        }
    }

    fun openNewTag() {
        sheets.open("新建标签", "标签名就是整理后的文件夹名，路径可在网页端改") {
            var name by remember { mutableStateOf("") }
            var colorIdx by remember { mutableIntStateOf(0) }
            val shape = RoundedCornerShape(11.dp)
            TextField(
                value = name,
                onValueChange = { name = it.take(20) },
                singleLine = true,
                placeholder = { Text("例如：宠物 / 2025 旅行", color = t.muted2, fontSize = 13.sp) },
                shape = shape,
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = t.ink(0.06f),
                    unfocusedContainerColor = t.ink(0.06f),
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                    focusedTextColor = t.text,
                    unfocusedTextColor = t.text,
                    cursorColor = t.accent,
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 14.dp)
                    .border(1.dp, t.line2, shape),
            )
            Row(
                Modifier.fillMaxWidth().padding(top = 14.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                TAG_COLORS.forEachIndexed { i, hex ->
                    val c = hexColor(hex)
                    Box(
                        Modifier
                            .size(26.dp)
                            .clip(CircleShape)
                            .background(c)
                            .then(
                                if (i == colorIdx) Modifier.border(2.dp, t.text, CircleShape)
                                else Modifier
                            )
                            .clickable { colorIdx = i }
                    )
                }
            }
            Row(Modifier.fillMaxWidth().padding(top = 18.dp), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                SheetButton("取消", primary = false, modifier = Modifier.weight(1f)) { sheets.close() }
                SheetButton("创建", primary = true, modifier = Modifier.weight(1f)) {
                    val n = name.trim()
                    if (n.isEmpty()) return@SheetButton
                    onCreateTag(n, TAG_COLORS[colorIdx])
                    sheets.close()
                    toast("已创建标签「$n」")
                }
            }
        }
    }

    // 全屏时控件默认收起来只留画面；暂停，或播放中轻点屏幕，就把控件浮出来。
    // 注意不能用 AnimatedVisibility 包：它会打断修饰符原先所在的布局作用域，
    // 里面写的 .align(Alignment.TopCenter) 会失效，整块跑到左上角去。
    // 用 remember 持有的 State 作为唯一真相来源：手势层闭包里读到的 .value 永远是最新的，
    // 界面也直接读同一个对象，两边不会分叉。
    val fullscreenChromeRef = remember { mutableStateOf(false) }
    val fullscreenChrome = fullscreenChromeRef.value
    val chromeVisible = !fullscreen || fullscreenChrome || !playing
    // 手势层的 pointerInput lambda 只在 key 变化时重建，闭包里的普通变量会一直是旧值。
    // 这里用 remember 持有的 State 对象做「引用」，在 lambda 里读 .value 才能拿到最新状态。
    val fullscreenRef = remember { mutableStateOf(fullscreen) }
    val playingRef = remember { mutableStateOf(playing) }
    fullscreenRef.value = fullscreen
    playingRef.value = playing
    val chromeAlpha by animateFloatAsState(
        targetValue = if (chromeVisible) 1f else 0f,
        animationSpec = tween(200),
        label = "chrome-alpha",
    )

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        // 续播定位完成前先空一帧：否则会先露出第一个视频再滑上去（闪烁）
        if (count > 0 && !syncReady) {
            Box(Modifier.fillMaxSize().background(Color.Black))
            return@Box
        }
        // ---------- 分页（视觉 + 上下滑切视频） ----------
        VerticalPager(
            state = pagerState,
            key = { i -> videos.getOrNull(i)?.id ?: i },
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 1,
            userScrollEnabled = false,
        ) { page ->
            val v = videos.getOrNull(page)
            val off = ((pagerState.currentPage - page) + pagerState.currentPageOffsetFraction)
            Box(
                Modifier
                    .fillMaxSize()
                    .graphicsLayer {
                        val a = abs(off).coerceIn(0f, 1f)
                        scaleX = 1f - 0.06f * a
                        scaleY = 1f - 0.06f * a
                        alpha = 1f - 0.55f * a
                        translationY = off * 24.dp.toPx()
                    }
            ) {
                // 背景：封面模糊 + 渐变压暗，宽屏视频上下不至于死黑
                if (v != null) {
                    val bg = api.thumbUrl(v)
                    Box(Modifier.fillMaxSize().background(gradientFor(v.id)))
                    AsyncImage(
                        model = bg,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize().blur(38.dp),
                        // 缩略图放大后颜色非常艳（尤其 B 站类截图），降饱和 + 模糊才像设计稿的“氛围底”
                        colorFilter = ColorFilter.colorMatrix(
                            ColorMatrix().apply { setToSaturation(0.28f) }
                        ),
                    )
                    // 压暗：缩略图被放大 30dp 模糊后颜色很艳，不加这层整屏会像调色盘
                    Box(
                        Modifier
                            .fillMaxSize()
                            .background(
                                Brush.verticalGradient(
                                    listOf(
                                        Color.Black.copy(alpha = 0.58f),
                                        Color.Black.copy(alpha = 0.22f),
                                        Color.Black.copy(alpha = 0.74f),
                                    )
                                )
                            )
                    )
                    Box(
                        Modifier
                            .fillMaxSize()
                            .background(
                                Brush.radialGradient(
                                    listOf(Color.Transparent, Color.Black.copy(alpha = 0.55f)),
                                    radius = 1100f,
                                )
                            )
                    )
                }
                if (page == pagerState.currentPage) {
                    AndroidView(
                        factory = { c ->
                            PlayerView(c).apply {
                                useController = false
                                isClickable = false
                                isFocusable = false
                                this.player = player
                                setShutterBackgroundColor(android.graphics.Color.BLACK)
                            }
                        },
                        modifier = Modifier.fillMaxSize(),
                    )
                    // 第一帧出来之前用封面盖住：换片时 ExoPlayer 的 surface 会先画出上一个视频的残留帧
                    val coverAlpha by animateFloatAsState(
                        targetValue = if (videoReady) 0f else 1f,
                        animationSpec = tween(220),
                        label = "video-cover",
                    )
                    if (coverAlpha > 0.01f) {
                        Box(Modifier.fillMaxSize().graphicsLayer { alpha = coverAlpha }) {
                            if (v != null) {
                                AsyncImage(
                                    model = api.thumbUrl(v),
                                    contentDescription = null,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize().blur(26.dp),
                                    colorFilter = ColorFilter.colorMatrix(
                                        ColorMatrix().apply { setToSaturation(0.5f) }
                                    ),
                                )
                            }
                            Box(
                                Modifier
                                    .fillMaxSize()
                                    .background(Color.Black.copy(alpha = 0.42f))
                            )
                        }
                    }
                }
            }
        }

        // ---------- 手势层：轻点播放/暂停、长按 2×、长按后下滑锁定/取消固定、上下滑切视频 ----------
        var gestureW by remember { mutableFloatStateOf(1f) }
        Box(
            Modifier
                .fillMaxSize()
                .onSizeChanged {
                    gestureW = it.width.toFloat().coerceAtLeast(1f)
                    surfaceW = it.width.toFloat().coerceAtLeast(1f)
                    surfaceH = it.height.toFloat().coerceAtLeast(1f)
                }
                // fullscreen 必须进 key：否则手势闭包捕获的是旧的 fullscreen/chromeVisible，
                // 全屏下轻点永远走成「暂停」而不是「唤出控件」
                .pointerInput(current?.id, lockedSpeed, fullscreen) {
                    val dragThreshold = 56.dp.toPx()
                    // 双击左右半屏快进/回退
                    val doubleTapMs = viewConfiguration.doubleTapTimeoutMillis
                    var lastTapAt = 0L
                    var lastTapX = 0f
                    var lastTapY = 0f
                    var singleTapJob: Job? = null
                    fun seekBy(seconds: Double) {
                        val total = if (duration > 0) duration else (current?.duration ?: 0.0)
                        if (total <= 0) return
                        val target = (player.currentPosition / 1000.0 + seconds).coerceIn(0.0, total)
                        player.seekTo((target * 1000).toLong())
                        position = target
                        hud = HudSpec(
                            if (seconds > 0) "+${seconds.toInt()} 秒" else "${seconds.toInt()} 秒",
                            fmtDuration(target),
                            (target / total).toFloat().coerceIn(0f, 1f),
                        )
                        scope.launch {
                            delay(720)
                            hud = null
                        }
                    }
                    // 横向滑动 320px ≈ 1.0 倍速增量
                    val speedRange = 320f
                    awaitEachGesture {
                        val down = awaitFirstDown(requireUnconsumed = false)
                        // 命中进度条等控件时，那一层已经消费了按下事件 —— 这里直接让开，避免抢走拖动
                        if (down.isConsumed) return@awaitEachGesture
                        // 上下黑边里点按/双击不响应，但上下滑切视频要能整块屏幕起手。
                        // 全屏时整块屏幕都算视频区：黑边里的点按、双击快进也一并生效，
                        // 否则横屏时画面上下各有一条黑边，正好是手指最容易落到的地方。
                        val inPicture = fullscreen || videoRect.height <= 0f ||
                            (down.position.y >= videoRect.top && down.position.y <= videoRect.bottom &&
                                down.position.x >= videoRect.left && down.position.x <= videoRect.right)
                        val startY = down.position.y
                        val startX = down.position.x
                        val longPressMs = viewConfiguration.longPressTimeoutMillis
                        val slop = viewConfiguration.touchSlop
                        val base = speed
                        var longPressed = false
                        var draggedDown = false
                        var swipeDir = 0
                        var adjustSpeed = 0f
                        var middleZone = false
                        var done = false
                        val began = System.currentTimeMillis()

                        while (!done) {
                            val elapsed = System.currentTimeMillis() - began
                            val wait = if (longPressed) Long.MAX_VALUE else (longPressMs - elapsed).coerceAtLeast(1L)
                            val ev = if (wait == Long.MAX_VALUE) awaitPointerEvent()
                                     else withTimeoutOrNull(wait) { awaitPointerEvent() }
                            if (ev == null) {
                                longPressed = true
                                // 分区：中间 1/3 左右拖动调速；两侧长按 2× 加速（下滑固定/恢复）
                                middleZone = startX > gestureW * 0.33f && startX < gestureW * 0.67f
                                if (middleZone) {
                                    hud = HudSpec(speedText(speed), "左右拖动调速 · 松手应用", 0.4f)
                                } else {
                                    tempSpeed = 2f
                                    player.setPlaybackSpeed(2f)
                                    hud = HudSpec(
                                        "2.0×",
                                        if (lockedSpeed == null) "加速中 · 下滑松手固定" else "加速中 · 下滑松手恢复",
                                        0.4f,
                                    )
                                }
                                continue
                            }
                            val ch = ev.changes.firstOrNull() ?: continue
                            val dy = ch.position.y - startY
                            val dx = ch.position.x - startX
                            if (!longPressed) {
                                if (swipeDir == 0 && abs(dy) > slop && abs(dy) > abs(dx)) {
                                    swipeDir = if (dy < 0) 1 else -1
                                }
                                if (!ch.pressed) {
                                    if (swipeDir == 0 && !ch.isConsumed && inPicture) {
                                        val now = System.currentTimeMillis()
                                        val isDouble = now - lastTapAt <= doubleTapMs &&
                                            abs(startX - lastTapX) < gestureW * 0.18f &&
                                            abs(startY - lastTapY) < 140f
                                        if (isDouble) {
                                            singleTapJob?.cancel()
                                            lastTapAt = 0L
                                            // 右半屏快进 10 秒，左半屏回退 5 秒
                                            if (startX >= gestureW / 2f) seekBy(10.0) else seekBy(-5.0)
                                        } else {
                                            lastTapAt = now
                                            lastTapX = startX
                                            lastTapY = startY
                                            singleTapJob?.cancel()
                                            singleTapJob = scope.launch {
                                                delay(doubleTapMs.toLong())
                                                // 直接读源状态，避免闭包拿到过期的派生值
                                                val fs = fullscreenRef.value
                                                if (fs) {
                                                    // 全屏：暂停时轻点先恢复播放并收起控件；播放中轻点则切换控件显隐
                                                    if (!playingRef.value) {
                                                        fullscreenChromeRef.value = false
                                                        togglePlay()
                                                    } else {
                                                        fullscreenChromeRef.value = !fullscreenChromeRef.value
                                                    }
                                                } else {
                                                    togglePlay()
                                                }
                                            }
                                        }
                                    }
                                    done = true
                                }
                            } else if (ch.pressed) {
                                if (middleZone) {
                                    // 中间区：只做左右调速
                                    if (abs(dx) > slop) {
                                        adjustSpeed = (base + dx / speedRange).coerceIn(0.5f, 3f)
                                        player.setPlaybackSpeed(adjustSpeed)
                                        hud = HudSpec(speedText(adjustSpeed), "松手应用该倍速", adjustSpeed / 3f)
                                    }
                                } else {
                                    // 两侧：2× 加速，下滑可固定/恢复
                                    draggedDown = dy > dragThreshold
                                    if (draggedDown) {
                                        hud = HudSpec(
                                            "2.0×",
                                            if (lockedSpeed == null) "松手固定 2×" else "松手恢复",
                                            1f,
                                        )
                                    } else {
                                        hud = HudSpec(
                                            "2.0×",
                                            if (lockedSpeed == null) "加速中 · 下滑松手固定" else "加速中 · 下滑松手恢复",
                                            0.4f,
                                        )
                                    }
                                }
                            } else {
                                done = true
                            }
                        }

                        if (longPressed) {
                            tempSpeed = null
                            when {
                                middleZone && adjustSpeed > 0f -> {
                                    speed = adjustSpeed
                                    applySpeed()
                                    toast("倍速已调整为 ${speedText(speed)}")
                                }
                                draggedDown -> {
                                    lockedSpeed = if (lockedSpeed == null) 2f else null
                                    applySpeed()
                                    toast(
                                        if (lockedSpeed != null) "已固定 2.0× 倍速"
                                        else "已取消固定，恢复 ${speedText(speed)} 倍速",
                                    )
                                }
                                adjustSpeed > 0f -> {
                                    speed = adjustSpeed
                                    lockedSpeed = null
                                    applySpeed()
                                    toast("倍速已调整为 ${speedText(speed)}")
                                }
                                else -> applySpeed()
                            }
                            hud = null
                        } else if (swipeDir != 0) {
                            val target = pagerState.currentPage + swipeDir
                            if (target in 0 until count) {
                                scope.launch { pagerState.animateScrollToPage(target) }
                            }
                        }
                    }
                }
        )

        // ---------- 顶部（玻璃） ----------
        // 全屏时一起淡出：只留视频画面
        // 全屏收起来时这一层不参与命中测试（用 heightIn 里的 0 高度做不到，这里靠
        // wrapContentHeight + 只在可见时组合内容），手势层才能照常收事件。
        Row(
            Modifier
                .align(Alignment.TopCenter)
                .then(if (fullscreen) Modifier else Modifier.statusBarsPadding())
                .fillMaxWidth()
                .graphicsLayer { alpha = chromeAlpha }
                .padding(start = 16.dp, end = 16.dp, top = if (fullscreen) 12.dp else 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (chromeVisible) {
            GlassChip(onClick = onOpenList) {
                Text("待整理", color = t.ink(0.86f), fontSize = 11.5.sp)
                // 用当前列表范围统计，筛选后与视频库保持一致
                Text("${videos.count { !it.isOrganized }}", color = t.accent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                Text("/ ${videos.size}", color = t.ink(0.5f), fontSize = 11.sp)
            }
            }
        }

        // ---------- 中央播放键 ----------
        AnimatedVisibility(
            visible = !playing && !loadingSrc && errorMsg == null && count > 0,
            enter = fadeIn(tween(180)) + scaleIn(tween(220), initialScale = 0.86f),
            exit = fadeOut(tween(140)) + scaleOut(tween(160), targetScale = 0.9f),
            modifier = Modifier.align(Alignment.Center),
        ) {
            Box(
                Modifier
                    .size(74.dp)
                    .clip(CircleShape)
                    .background(if (dark) Color(0x57121519) else Color(0xA8FFFFFF))
                    .border(1.dp, t.ink(0.2f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    Icons.Rounded.PlayArrow,
                    contentDescription = null,
                    tint = if (dark) Color.White else t.ink(0.82f),
                    modifier = Modifier.size(30.dp),
                )
            }
        }

        // ---------- HUD（长按 / 调速）：小卡片、偏上、只显示倍速、半透明 ----------
        AnimatedVisibility(
            visible = hud != null,
            enter = fadeIn(tween(120)) + scaleIn(tween(160), initialScale = 0.92f),
            exit = fadeOut(tween(110)) + scaleOut(tween(130), targetScale = 0.95f),
            modifier = Modifier.align(Alignment.TopCenter),
        ) {
            hud?.let { spec ->
                Box(
                    Modifier
                        .padding(top = 96.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(if (dark) Color(0x8A0E1218) else Color(0x8AFFFFFF))
                        .border(1.dp, t.glassBorder, RoundedCornerShape(14.dp))
                        .padding(horizontal = 18.dp, vertical = 9.dp),
                ) {
                    Text(spec.text, color = t.text, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                }
            }
        }

        // ---------- 加载 / 转码 / 错误 / 空态 ----------
        val emptyState = count == 0 && !loadingSrc && errorMsg == null
        val noteText = when {
            errorMsg != null -> errorMsg
            transcodePct >= 0 -> "首次播放需转码处理 · ${transcodePct}%"
            loadingSrc && count > 0 -> "加载中…"
            else -> null
        }
        if (noteText != null) {
            Box(
                Modifier
                    .align(Alignment.Center)
                    .clip(RoundedCornerShape(12.dp))
                    .background(t.glassStrong)
                    .border(1.dp, t.glassBorder, RoundedCornerShape(12.dp))
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            ) {
                Text(noteText, color = t.ink(0.92f), fontSize = 13.sp)
            }
        }
        if (emptyState) {
            Column(
                Modifier.align(Alignment.Center),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("还没有视频", color = t.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Text("去网页端添加源文件夹并扫描", color = t.muted, fontSize = 12.sp)
            }
        }

        // ---------- 底部信息 ----------
        // 试做版：完全去掉底部渐隐，画面一刀不糊
        // 全屏时整块隐藏（淡出），只留画面；退出全屏再淡回来
        // 全屏时控件浮在视频上方，垫一层下深上浅的渐变，保证文字和胶囊看得清
        if (fullscreen && chromeVisible) {
            Box(
                Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .height(200.dp)
                    .graphicsLayer { alpha = chromeAlpha }
                    .background(
                        Brush.verticalGradient(
                            listOf(Color.Transparent, Color.Black.copy(alpha = 0.92f))
                        )
                    )
            )
        }
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .navigationBarsPadding()
                .graphicsLayer { alpha = chromeAlpha }
                // 竖屏底部要避开 tab 栏（92dp）；全屏时贴屏幕底边即可（系统栏已隐藏）
                .padding(
                    start = 18.dp,
                    end = 18.dp,
                    top = 30.dp,
                    bottom = if (fullscreen) 14.dp else 92.dp,
                ),
        ) {
            if (chromeVisible) {
            current?.let { v ->
                // 浅色主题也统一用白字（和深色主题一致），再压一层深色阴影，
                // 这样画面偏亮时也能看清
                val infoInk = Color.White
                val infoHalo = Shadow(Color(0x99000000), Offset(0f, 1f), 10f)
                Text(
                    v.name,
                    color = infoInk,
                    style = TextStyle(shadow = infoHalo),
                    fontSize = 15.5.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(5.dp))
                val folder = v.path.substringBeforeLast('/', "").substringAfterLast('/')
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        listOfNotNull(
                            folder.takeIf { it.isNotEmpty() },
                            fmtDuration(duration.takeIf { it > 0 } ?: v.duration),
                            sizeText(v.size),
                            if (v.isOrganized) "已整理" else if (v.tagId != null) "待整理" else "未标记",
                        ).joinToString(" · "),
                        color = Color(0xE6FFFFFF),
                        style = TextStyle(shadow = infoHalo),
                        fontSize = 10.5.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    // 「更多」左边的倍速快捷按钮：点一次切下一档
                    Row(
                        Modifier
                            .height(30.dp)
                            .shadow(6.dp, RoundedCornerShape(12.dp))
                            .clip(RoundedCornerShape(12.dp))
                            .background(t.glass)
                            .border(1.dp, t.glassBorder, RoundedCornerShape(12.dp))
                            .clickable { cycleSpeed() }
                            .padding(horizontal = 9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Icon(Icons.Rounded.Speed, null, tint = t.ink(0.72f), modifier = Modifier.size(14.dp))
                        Text(
                            speedText(effSpeed()),
                            color = if (lockedSpeed != null) t.accent else t.ink(0.88f),
                            fontSize = 11.sp,
                        )
                    }
                    Spacer(Modifier.width(6.dp))
                    // 标签栏开关：「···」左边，收起后整块标签区折起来，上方信息一起下移
                    GlassIconButton(
                        icon = if (tagsOpen) Icons.Rounded.LabelOff else Icons.Rounded.Label,
                        onClick = { tagsOpen = !tagsOpen },
                        size = 30,
                        iconSize = 16,
                        contentDescription = if (tagsOpen) "收起标签栏" else "展开标签栏",
                    )
                    Spacer(Modifier.width(6.dp))
                    // 全屏按钮：放在「更多」左边，进出全屏用缩放 + 淡入淡出
                    AnimatedVisibility(
                        visible = true,
                        enter = fadeIn(tween(200)) + scaleIn(tween(220), initialScale = 0.86f),
                        exit = fadeOut(tween(160)) + scaleOut(tween(160), targetScale = 0.86f),
                    ) {
                        GlassIconButton(
                            icon = if (fullscreen) Icons.Rounded.FullscreenExit else Icons.Rounded.Fullscreen,
                            onClick = { fullscreen = !fullscreen },
                            size = 30,
                            iconSize = 16,
                            contentDescription = if (fullscreen) "退出全屏" else "横屏全屏播放",
                        )
                    }
                    Spacer(Modifier.width(6.dp))
                    // 「更多」放在信息区右侧（原在右上角，按设计反馈下移）
                    GlassIconButton(
                        icon = Icons.Rounded.MoreHoriz,
                        onClick = { openMore(v) },
                        size = 30,
                        iconSize = 16,
                        contentDescription = "更多",
                    )
                }

                // 标签胶囊 + 新建（可收起：收起后这一块高度归零，上面的标题/信息跟着下移）
                AnimatedVisibility(
                    visible = tagsOpen,
                    enter = expandVertically(tween(240), expandFrom = Alignment.Bottom) + fadeIn(tween(200)),
                    exit = shrinkVertically(tween(220), shrinkTowards = Alignment.Bottom) + fadeOut(tween(140)),
                    label = "tag-bar",
                ) {
                Column {
                Spacer(Modifier.height(12.dp))
                LazyRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    contentPadding = PaddingValues(end = 8.dp),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    items(tags, key = { it.id }) { tag ->
                        val on = v.tagId == tag.id
                        val c = hexColor(tag.color)
                        Row(
                            Modifier
                                .height(28.dp)
                                .clip(RoundedCornerShape(14.dp))
                                .background(if (on) c else t.glass)
                                .border(1.dp, if (on) Color.Transparent else t.glassBorder, RoundedCornerShape(14.dp))
                                // 不要点击水波纹：标签点下去立刻亮起就算反馈了，涟漪反而像卡了一下
                                .clickable(
                                    interactionSource = remember { MutableInteractionSource() },
                                    indication = null,
                                ) { onTag(v.id, if (on) null else tag.id) }
                                .padding(horizontal = 9.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                        ) {
                            Box(
                                Modifier
                                    .size(5.dp)
                                    .clip(CircleShape)
                                    .background(if (on) Color(0xFF062016) else t.ink(0.7f))
                            )
                            Text(
                                tag.name,
                                color = if (on) Color(0xFF062016) else t.ink(0.7f),
                                fontSize = 11.sp,
                                fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                            )
                        }
                    }
                    // 新建标签：当作最后一个「标签胶囊」排在列表末尾，跟着一起滚动
                    item(key = "new-tag") {
                        Row(
                            Modifier
                                .height(28.dp)
                                .clip(RoundedCornerShape(14.dp))
                                .background(t.glass)
                                .border(1.dp, t.glassBorder, RoundedCornerShape(14.dp))
                                .clickable { openNewTag() }
                                .padding(horizontal = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                        ) {
                            Icon(
                                Icons.Rounded.Add,
                                contentDescription = "新建标签",
                                tint = t.ink(0.88f),
                                modifier = Modifier.size(14.dp),
                            )
                            Text(
                                "新建",
                                color = t.ink(0.7f),
                                fontSize = 11.sp,
                            )
                        }
                    }
                }
                }
                }

                Spacer(Modifier.height(13.dp))
                // 进度条
                var dragging by remember { mutableStateOf(false) }
                var widthPx by remember { mutableFloatStateOf(1f) }
                var scrub by remember { mutableFloatStateOf(0f) }
                // scrub 本身已经是 0..1 的比例，不能再除以 duration（否则滑块会跑到最左边）
                val frac = if (dragging) {
                    scrub.coerceIn(0f, 1f)
                } else if (duration > 0) {
                    (position.toFloat() / duration.toFloat()).coerceIn(0f, 1f)
                } else {
                    0f
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier
                            .weight(1f)
                            .height(28.dp)
                            .onSizeChanged { widthPx = it.width.toFloat().coerceAtLeast(1f) }
                            .pointerInput(duration) {
                                // 相对拖动：按下时滑块从当前位置冒出，手指往前/后移动多少，
                                // 滑块就往前/后移动多少；拖动过程中不 seek（视频照常播），松手才 seek
                                awaitEachGesture {
                                    val down = awaitFirstDown(requireUnconsumed = true)
                                    // 消费按下：告诉下层的「点按播放/长按倍速」手势层，这一下是进度条在拖
                                    down.consume()
                                    val w = size.width.toFloat().coerceAtLeast(1f)
                                    val total = duration
                                    if (total <= 0.0) return@awaitEachGesture
                                    dragging = true
                                    scrubActive = true
                                    val base = position.coerceIn(0.0, total)
                                    scrub = (base / total).toFloat().coerceIn(0f, 1f)
                                    val startX = down.position.x
                                    while (true) {
                                        val ev = awaitPointerEvent()
                                        val ch = ev.changes.firstOrNull() ?: break
                                        ch.consume()
                                        val dx = ch.position.x - startX
                                        scrub = ((base + (dx / w) * total) / total).toFloat().coerceIn(0f, 1f)
                                        if (!ch.pressed) break
                                    }
                                    // 松手才真正跳过去（拖动期间不打断播放）
                                    val target = scrub * total
                                    position = target
                                    // 先把拖动标记清掉再动播放器：下面 seek 到结尾附近会再触发一次
                                    // STATE_ENDED，那时必须走「正常播完」的分支
                                    dragging = false
                                    scrubActive = false
                                    val mode = ScrubEnd.onRelease(endedWhileScrubbing)
                                    endedWhileScrubbing = false
                                    player.seekTo((target * 1000).toLong())
                                    when (mode) {
                                        ScrubEnd.OnRelease.RESTART -> player.play()
                                        ScrubEnd.OnRelease.RESUME -> player.playWhenReady = true
                                    }
                                }
                            },
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        val barH by animateDpAsState(if (dragging) 6.dp else 3.5.dp, label = "bar-h")
                        Box(
                            Modifier
                                .fillMaxWidth()
                                .height(barH)
                                .clip(RoundedCornerShape(3.dp))
                                .background(t.ink(0.2f))
                        )
                        Box(
                            Modifier
                                .fillMaxWidth(frac)
                                .height(barH)
                                .clip(RoundedCornerShape(3.dp))
                                .background(t.accent)
                        )
                        if (dragging) {
                            Box(
                                Modifier
                                    .offset { IntOffset((frac * widthPx - 10f).roundToInt(), 0) }
                                    .size(11.dp)
                                    .clip(CircleShape)
                                    .background(Color.White)
                            )
                        }
                    }
                    Spacer(Modifier.width(10.dp))
                    Text(
                        "${fmtDuration(if (dragging) (scrub * duration) else position)} ",
                        color = t.ink(0.7f),
                        fontSize = 10.sp,
                    )
                    Text("/ ${fmtDuration(duration.takeIf { it > 0 } ?: v.duration)}", color = t.ink(0.42f), fontSize = 10.sp)
                }
            }
            }
        }

        // ---------- 全屏按钮：放在「更多」左边 ----------
        // 始终浮在画面右下角（全屏时也留着，否则退不出去）；进出全屏用缩放 + 淡入淡出做动画
    }
}

/* ---------------- 弹层里用的两个小组件 ---------------- */

@Composable
fun SheetActionRow(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    val t = tokens()
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        Icon(
            icon,
            contentDescription = null,
            tint = if (danger) t.danger else t.ink(0.7f),
            modifier = Modifier.size(17.dp),
        )
        Text(label, color = if (danger) t.danger else t.text, fontSize = 13.sp)
    }
    Box(Modifier.fillMaxWidth().height(1.dp).background(t.line))
}

@Composable
fun SheetButton(
    label: String,
    primary: Boolean,
    modifier: Modifier = Modifier,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    val t = tokens()
    val shape = RoundedCornerShape(13.dp)
    Box(
        modifier
            .height(44.dp)
            .clip(shape)
            .then(
                if (primary) Modifier.background(Brush.linearGradient(listOf(Color(0xFF5FECAB), Color(0xFF2FBF7C))))
                else Modifier.background(t.ink(0.07f)).border(1.dp, t.line2, shape)
            )
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = when {
                primary && danger -> Color(0xFF7A1010)
                primary -> Color(0xFF04160D)
                else -> t.ink(0.7f)
            },
            fontSize = 13.5.sp,
            fontWeight = if (primary) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}
