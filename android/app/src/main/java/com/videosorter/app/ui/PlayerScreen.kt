package com.videosorter.app.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.VerticalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.draw.blur
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
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
import kotlinx.coroutines.delay

private val TAG_COLORS = listOf(
    "#f4a259", "#ef5b7b", "#4cc9f0", "#9b8cff",
    "#35d18a", "#f2c14e", "#ef7d4f", "#8d98a8",
)

private fun parseColor(hex: String?): Color = runCatching {
    Color(android.graphics.Color.parseColor(hex ?: "#8d98a8"))
}.getOrDefault(Color(0xFF8D98A8))

private fun fmtTime(sec: Double): String {
    val s = sec.toInt().coerceAtLeast(0)
    val h = s / 3600
    val m = (s % 3600) / 60
    val ss = s % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, ss) else "%d:%02d".format(m, ss)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PlayerScreen(
    api: Api,
    videos: List<Video>,
    tags: List<Tag>,
    counts: Counts,
    startIndex: Int,
    onIndexChange: (Int) -> Unit,
    onTag: (Int, Int?) -> Unit,
    onCreateTag: (String, String) -> Unit,
) {
    val ctx = LocalContext.current
    // 媒体请求也要带 Bearer 令牌：/api/videos/{id}/raw 与 HLS 分片都要求鉴权，
    // 否则 ExoPlayer 会拿到 401 并报 ERROR_CODE_IO_BAD_HTTP_STATUS。
    val player = remember(api.token) {
        val headers = buildMap {
            api.token?.takeIf { it.isNotEmpty() }?.let { put("Authorization", "Bearer $it") }
        }
        val httpFactory = androidx.media3.datasource.DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(headers)
            .setAllowCrossProtocolRedirects(true)
        ExoPlayer.Builder(ctx)
            .setMediaSourceFactory(androidx.media3.exoplayer.source.DefaultMediaSourceFactory(httpFactory))
            .build()
            .apply { playWhenReady = true }
    }
    val count = videos.size
    val pagerState = rememberPagerState(initialPage = startIndex.coerceIn(0, (count - 1).coerceAtLeast(0))) { count.coerceAtLeast(1) }

    var playing by remember { mutableStateOf(true) }
    var speed by remember { mutableFloatStateOf(1f) }
    var tempSpeed by remember { mutableStateOf<Float?>(null) }
    var position by remember { mutableStateOf(0.0) }
    var duration by remember { mutableStateOf(0.0) }
    var seeking by remember { mutableStateOf(false) }
    var hud by remember { mutableStateOf(false) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var loadingSrc by remember { mutableStateOf(true) }
    var showNewTag by remember { mutableStateOf(false) }
    var newTagName by remember { mutableStateOf("") }
    var newTagColor by remember { mutableIntStateOf(0) }
    var lastLoadedId by remember { mutableIntStateOf(-1) }
    /** >=0 表示正在等 ffmpeg 转码（长视频/非直放格式首次播放） */
    var transcodePct by remember { mutableIntStateOf(-1) }

    val current = videos.getOrNull(pagerState.currentPage)

    fun applySpeed() = player.setPlaybackSpeed(tempSpeed ?: speed)

    // 页面切换 → 换片
    LaunchedEffect(pagerState.currentPage, current?.id) {
        val v = current ?: return@LaunchedEffect
        onIndexChange(pagerState.currentPage)
        if (v.id == lastLoadedId) return@LaunchedEffect
        lastLoadedId = v.id
        errorMsg = null
        loadingSrc = true
        position = 0.0
        val info = runCatching { api.play(v.id) }.getOrNull()
        if (info == null || info.mode == "error") {
            errorMsg = info?.message ?: "无法获取播放地址"
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
                kotlinx.coroutines.delay(700)
            }
            transcodePct = -1
        }
        val url = api.base + (info.url ?: "")
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        applySpeed()
        val resume = v.position ?: 0.0
        if (resume > 3) player.seekTo((resume * 1000).toLong())
    }

    // 播放状态 / 进度回调
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_READY) loadingSrc = false
                if (state == Player.STATE_ENDED) {
                    // 播完自动下一个
                    if (pagerState.currentPage + 1 < count) onIndexChange(pagerState.currentPage + 1)
                }
            }
            override fun onPlayerError(error: androidx.media3.common.PlaybackException) {
                errorMsg = "播放失败：${error.errorCodeName}"
                loadingSrc = false
            }
        }
        player.addListener(listener)
        onDispose { player.removeListener(listener) }
    }

    LaunchedEffect(Unit) {
        while (true) {
            position = player.currentPosition / 1000.0
            duration = (player.duration.takeIf { it > 0 } ?: 0L) / 1000.0
            delay(250)
        }
    }

    // 每 5 秒保存一次进度
    LaunchedEffect(current?.id, playing) {
        val v = current ?: return@LaunchedEffect
        while (playing) {
            delay(5000)
            runCatching { api.saveProgress(v.id, player.currentPosition / 1000.0, duration) }
        }
    }

    // 播放器实例会随 token 变化重建，必须按实例释放，否则旧实例泄漏（同时占着解码器）
    DisposableEffect(player) { onDispose { player.release() } }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        // 背景：当前视频封面放大模糊后铺底，宽屏视频上下就不会是死黑一片
        val bgUrl = current?.let { api.thumbUrl(it) } ?: ""
        if (bgUrl.isNotEmpty()) {
            AsyncImage(
                model = bgUrl,
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize().blur(28.dp),
            )
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.45f)))
        }
        // 播放器画面
        AndroidView(
            factory = { c ->
                PlayerView(c).apply {
                    useController = false
                    this.player = player
                    setShutterBackgroundColor(android.graphics.Color.BLACK)
                }
            },
            modifier = Modifier.fillMaxSize(),
        )

        // 手势层
        Box(
            Modifier
                .fillMaxSize()
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = {
                            tempSpeed = null
                            applySpeed()
                            when {
                                player.isPlaying -> player.pause()
                                // 播完后轻点是「重播」，直接 play() 不会有任何反应
                                player.playbackState == Player.STATE_ENDED -> { player.seekTo(0); player.play() }
                                else -> player.play()
                            }
                        },
                        onLongPress = { tempSpeed = 2f; applySpeed(); hud = true },
                    )
                }
                .pointerInput(Unit) {
                    awaitPointerEventScope {
                        while (true) {
                            val e = awaitPointerEvent(PointerEventPass.Final)
                            if (tempSpeed != null && e.changes.isNotEmpty() && e.changes.none { it.pressed }) {
                                tempSpeed = null
                                hud = false
                                player.setPlaybackSpeed(speed)
                            }
                        }
                    }
                }
                .pointerInput(Unit) {
                    var seekTo = 0.0
                    detectHorizontalDragGestures(
                        onDragStart = { seeking = true; seekTo = position },
                        onHorizontalDrag = { change, delta ->
                            change.consume()
                            if (duration > 0) {
                                seekTo = (seekTo + delta / 300.0 * duration).coerceIn(0.0, duration)
                                position = seekTo
                            }
                        },
                        onDragEnd = {
                            if (duration > 0) player.seekTo((seekTo * 1000).toLong())
                            seeking = false
                        },
                        onDragCancel = { seeking = false },
                    )
                },
        )

        // 分页手势层（透明，只负责上下滑切换）
        VerticalPager(
            state = pagerState,
            key = { i -> videos.getOrNull(i)?.id ?: i },
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 0,
        ) { _ -> Box(Modifier.fillMaxSize()) }

        // HUD
        AnimatedVisibility(visible = hud, enter = fadeIn(), exit = fadeOut(), modifier = Modifier.align(Alignment.Center)) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("2.0×", fontSize = 40.sp, fontWeight = FontWeight.Bold, color = Color.White)
                Spacer(Modifier.height(4.dp))
                Text("长按加速 · 松开恢复", fontSize = 12.sp, color = Color.White.copy(alpha = 0.7f))
            }
        }

        if (!playing && !loadingSrc && errorMsg == null) {
            Box(Modifier.align(Alignment.Center).size(72.dp).background(Color.Black.copy(alpha = 0.35f), CircleShape), contentAlignment = Alignment.Center) {
                Icon(Icons.Default.PlayArrow, contentDescription = null, tint = Color.White, modifier = Modifier.size(40.dp))
            }
        }

        // 空态 / 加载态 / 转码态互斥
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
                    .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(12.dp))
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(noteText, color = Color.White.copy(alpha = 0.92f), fontSize = 13.sp)
            }
        }

        if (emptyState) {
            Box(Modifier.align(Alignment.Center), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("还没有视频", color = Color.White, fontSize = 15.sp)
                    Spacer(Modifier.height(6.dp))
                    Text("先去管理页添加源文件夹并扫描", color = Color.White.copy(alpha = 0.6f), fontSize = 12.sp)
                }
            }
        }

        // 底部信息与控件
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .background(
                    Brush.verticalGradient(
                        listOf(Color.Transparent, Color.Black.copy(alpha = 0.55f), Color.Black.copy(alpha = 0.9f))
                    )
                )
                .padding(start = 16.dp, end = 16.dp, top = 40.dp, bottom = 18.dp),
        ) {
            current?.let { v ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        v.name,
                        color = Color.White,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    Spacer(Modifier.width(8.dp))
                    val stText = if (v.isOrganized) "已整理" else if (v.tagId != null) "待整理" else "未标记"
                    Text(
                        stText,
                        fontSize = 10.sp,
                        color = if (v.isOrganized) Accent else Color.White.copy(alpha = 0.7f),
                        modifier = Modifier
                            .background(Color.White.copy(alpha = 0.12f), RoundedCornerShape(20.dp))
                            .padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
                Spacer(Modifier.height(10.dp))

                // 标签小胶囊
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        tags.take(5).forEach { t ->
                            val on = v.tagId == t.id
                            val c = parseColor(t.color)
                            Box(
                                Modifier
                                    .background(if (on) c.copy(alpha = 0.9f) else Color.White.copy(alpha = 0.12f), RoundedCornerShape(20.dp))
                                    .clickable { onTag(v.id, if (on) null else t.id) }
                                    .padding(horizontal = 10.dp, vertical = 6.dp),
                            ) {
                                Text(
                                    t.name,
                                    fontSize = 11.sp,
                                    color = if (on) Color(0xFF04160D) else Color.White.copy(alpha = 0.9f),
                                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                                )
                            }
                        }
                    }
                    Box(
                        Modifier
                            .size(28.dp)
                            .background(Color.White.copy(alpha = 0.14f), CircleShape)
                            .clickable { showNewTag = true },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Default.Add, contentDescription = "新建标签", tint = Color.White, modifier = Modifier.size(16.dp))
                    }
                }

                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(fmtTime(position), color = Color.White.copy(alpha = 0.75f), fontSize = 11.sp)
                    Slider(
                        value = if (duration > 0) (position / duration).toFloat().coerceIn(0f, 1f) else 0f,
                        onValueChange = { f ->
                            if (duration > 0) {
                                seeking = true
                                position = (f * duration).coerceIn(0.0, duration)
                            }
                        },
                        onValueChangeFinished = {
                            if (duration > 0) player.seekTo((position * 1000).toLong())
                            seeking = false
                        },
                        colors = SliderDefaults.colors(
                            thumbColor = Accent,
                            activeTrackColor = Accent,
                            inactiveTrackColor = Color.White.copy(alpha = 0.24f),
                        ),
                        modifier = Modifier
                            .weight(1f)
                            .padding(horizontal = 8.dp)
                            .height(24.dp),
                    )
                    Text(fmtTime(duration), color = Color.White.copy(alpha = 0.75f), fontSize = 11.sp)
                }

                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier
                            .background(Color.White.copy(alpha = 0.12f), RoundedCornerShape(20.dp))
                            .clickable {
                                speed = when (speed) {
                                    1f -> 1.25f
                                    1.25f -> 1.5f
                                    1.5f -> 2f
                                    2f -> 0.5f
                                    0.5f -> 1f
                                    else -> 1f
                                }
                                applySpeed()
                            }
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    ) {
                        Text("${speed}×", color = Color.White, fontSize = 11.sp)
                    }
                    val pending = counts.tagged
                    Text(
                        "待整理 $pending / ${counts.all}",
                        fontSize = 11.sp,
                        color = Color.White.copy(alpha = 0.6f),
                    )
                }
            }
        }
    }

    if (showNewTag) {
        AlertDialog(
            onDismissRequest = { showNewTag = false },
            title = { Text("新建标签") },
            text = {
                Column {
                    Text("标签名将作为整理时的文件夹名，可在管理页修改路径。", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = newTagName,
                        onValueChange = { newTagName = it.take(20) },
                        singleLine = true,
                        placeholder = { Text("例如：宠物 / 2025 旅行") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        TAG_COLORS.forEachIndexed { i, hex ->
                            Box(
                                Modifier
                                    .size(26.dp)
                                    .background(parseColor(hex), CircleShape)
                                    .clickable { newTagColor = i }
                                    .padding(0.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                if (i == newTagColor) {
                                    Text("✓", color = Color.White, fontSize = 12.sp)
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val name = newTagName.trim()
                        if (name.isNotEmpty()) {
                            onCreateTag(name, TAG_COLORS[newTagColor])
                            newTagName = ""
                            showNewTag = false
                        }
                    },
                ) { Text("创建并标记") }
            },
            dismissButton = { TextButton(onClick = { showNewTag = false }) { Text("取消") } },
        )
    }
}
