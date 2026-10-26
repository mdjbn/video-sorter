package com.videosorter.app.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.material.icons.rounded.MoreHoriz
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
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
    onIndexChange: (Int) -> Unit,
    onTag: (Int, Int?) -> Unit,
    onCreateTag: (String, String) -> Unit,
    toast: (String) -> Unit,
    sheets: SheetState,
    onOpenList: () -> Unit = {},
    onRefresh: () -> Unit = {},
) {
    val t = tokens()
    val ctx = LocalContext.current
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val dark = t.dark

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
    val pagerState = rememberPagerState(initialPage = startIndex.coerceIn(0, (count - 1).coerceAtLeast(0))) {
        count.coerceAtLeast(1)
    }

    var playing by remember { mutableStateOf(true) }
    var speed by remember { mutableFloatStateOf(1f) }
    var tempSpeed by remember { mutableStateOf<Float?>(null) }
    var position by remember { mutableStateOf(0.0) }
    var duration by remember { mutableStateOf(0.0) }
    var hud by remember { mutableStateOf<HudSpec?>(null) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var loadingSrc by remember { mutableStateOf(true) }
    var lastLoadedId by remember { mutableIntStateOf(-1) }
    var transcodePct by remember { mutableIntStateOf(-1) }

    val current = videos.getOrNull(pagerState.currentPage)

    fun applySpeed() = player.setPlaybackSpeed(tempSpeed ?: speed)

    fun speedText(v: Float): String =
        if (v == 1f) "1.0×" else "%.2f".format(v).trimEnd('0').trimEnd('.') + "×"

    fun cycleSpeed() {
        speed = when (speed) {
            1f -> 1.25f
            1.25f -> 1.5f
            1.5f -> 2f
            2f -> 0.5f
            else -> 1f
        }
        tempSpeed = null
        applySpeed()
        toast("倍速已切换为 ${speedText(speed)}")
    }

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
                delay(700)
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

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                playing = isPlaying
            }

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
            SheetActionRow(Icons.Rounded.Speed, "倍速 · 当前 ${speedText(speed)}") {
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

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        // ---------- 分页（视觉 + 上下滑切视频） ----------
        VerticalPager(
            state = pagerState,
            key = { i -> videos.getOrNull(i)?.id ?: i },
            modifier = Modifier.fillMaxSize(),
            beyondViewportPageCount = 1,
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
                }
            }
        }

        // ---------- 手势层（在 pager 下面，pager 只吃上下滑） ----------
        Box(
            Modifier
                .fillMaxSize()
                .pointerInput(current?.id) {
                    detectTapGestures(
                        onTap = { togglePlay() },
                        onLongPress = {
                            tempSpeed = 2f
                            player.setPlaybackSpeed(2f)
                            hud = HudSpec("2.0×", "加速中 · 松开恢复", 0.4f)
                        },
                        onPress = {
                            // 抬起（或手势取消）后恢复原速
                            tryAwaitRelease()
                            if (tempSpeed != null) {
                                tempSpeed = null
                                applySpeed()
                            }
                            hud = null
                        },
                    )
                }
        )

        // ---------- 顶部（玻璃） ----------
        Row(
            Modifier
                .align(Alignment.TopCenter)
                .statusBarsPadding()
                .fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            GlassChip(onClick = onOpenList) {
                Text("待整理", color = t.ink(0.86f), fontSize = 11.5.sp)
                Text("${counts.tagged}", color = t.accent, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                Text("/ ${counts.all}", color = t.ink(0.5f), fontSize = 11.sp)
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

        // ---------- HUD（长按 / 调速） ----------
        AnimatedVisibility(
            visible = hud != null,
            enter = fadeIn(tween(140)) + scaleIn(tween(180), initialScale = 0.9f),
            exit = fadeOut(tween(120)) + scaleOut(tween(140), targetScale = 0.94f),
            modifier = Modifier.align(Alignment.Center),
        ) {
            hud?.let { spec ->
                Column(
                    Modifier
                        .width(150.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(t.glassStrong)
                        .border(1.dp, t.glassBorder, RoundedCornerShape(18.dp))
                        .padding(horizontal = 16.dp, vertical = 13.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(spec.text, color = t.text, fontSize = 26.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .height(3.dp)
                            .clip(RoundedCornerShape(2.dp))
                            .background(t.ink(0.2f))
                    ) {
                        Box(
                            Modifier
                                .fillMaxWidth(spec.pct)
                                .height(3.dp)
                                .clip(RoundedCornerShape(2.dp))
                                .background(t.accent)
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(spec.label, color = t.ink(0.58f), fontSize = 10.5.sp)
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
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .background(Brush.verticalGradient(t.scrim))
                .navigationBarsPadding()
                .padding(start = 18.dp, end = 18.dp, top = 30.dp, bottom = 92.dp),
        ) {
            current?.let { v ->
                Text(
                    v.name,
                    color = t.ink(0.96f),
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
                        color = t.ink(0.55f),
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
                            .clip(RoundedCornerShape(12.dp))
                            .background(t.ink(0.08f))
                            .border(1.dp, t.line, RoundedCornerShape(12.dp))
                            .clickable { cycleSpeed() }
                            .padding(horizontal = 9.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Icon(Icons.Rounded.Speed, null, tint = t.ink(0.72f), modifier = Modifier.size(14.dp))
                        Text(speedText(speed), color = t.ink(0.88f), fontSize = 11.sp)
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

                Spacer(Modifier.height(12.dp))
                // 标签胶囊 + 新建
                Box(Modifier.fillMaxWidth()) {
                    LazyRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        contentPadding = PaddingValues(end = 40.dp),
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
                                    .clickable { onTag(v.id, if (on) null else tag.id) }
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
                    }
                    // 右端渐隐 + 新建按钮
                    Box(
                        Modifier
                            .align(Alignment.CenterEnd)
                            .width(52.dp)
                            .height(34.dp)
                            .background(
                                Brush.horizontalGradient(
                                    listOf(
                                        (if (dark) Color(0xFF080B10) else Color(0xFFF7FAFF)).copy(alpha = 0f),
                                        (if (dark) Color(0xFF080B10) else Color(0xFFF7FAFF)).copy(alpha = 0.94f),
                                    )
                                )
                            )
                    )
                    Box(
                        Modifier
                            .align(Alignment.CenterEnd)
                            .size(29.dp)
                            .clip(CircleShape)
                            .background(t.glass)
                            .border(1.dp, t.glassBorder, CircleShape)
                            .clickable { openNewTag() },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(Icons.Rounded.Add, contentDescription = "新建标签", tint = t.ink(0.88f), modifier = Modifier.size(15.dp))
                    }
                }

                Spacer(Modifier.height(13.dp))
                // 进度条
                var dragging by remember { mutableStateOf(false) }
                var widthPx by remember { mutableFloatStateOf(1f) }
                var scrub by remember { mutableFloatStateOf(0f) }
                val frac = if (duration > 0) {
                    ((if (dragging) scrub else position.toFloat()) / duration.toFloat()).coerceIn(0f, 1f)
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
                                awaitEachGesture {
                                    val down = awaitFirstDown()
                                    dragging = true
                                    scrub = (down.position.x / widthPx).coerceIn(0f, 1f)
                                    while (true) {
                                        val e = awaitPointerEvent()
                                        val ch = e.changes.firstOrNull { it.id == down.id } ?: break
                                        scrub = (ch.position.x / widthPx).coerceIn(0f, 1f)
                                        ch.consume()
                                        if (!ch.pressed) break
                                    }
                                    if (duration > 0) player.seekTo((scrub * duration * 1000).toLong())
                                    position = (scrub * duration)
                                    dragging = false
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
