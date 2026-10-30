package com.videosorter.app.ui

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.SwapVert
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.videosorter.app.data.Api
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video

private val LIST_FILTERS = listOf("all" to "全部", "idle" to "未标记", "tagged" to "待整理", "organized" to "已整理")

@Composable
fun ListScreen(
    api: Api,
    videos: List<Video>,
    tags: List<Tag>,
    loading: Boolean,
    error: String?,
    status: String,
    selectedTags: Set<Int>,
    query: String,
    onQuery: (String) -> Unit,
    onStatus: (String) -> Unit,
    onToggleTag: (Int) -> Unit,
    onOpen: (Int) -> Unit,
    onTag: (Int, Int?) -> Unit,
    onRefresh: () -> Unit,
    onDownload: (Video) -> Unit,
    onDelete: (Video) -> Unit,
    onOpenTransfer: () -> Unit,
    toast: (String) -> Unit,
    sheets: SheetState,
    // 列表滚动状态由 MainScreen 持有：切到别的 tab 再回来位置不变（AnimatedContent 会重建本组件）
    listState: LazyListState,
) {
    val t = tokens()

    // 状态、标签与搜索词都在 MainScreen 里：前两个走服务端筛选，搜索词由这一层传进来，
    // 这样切到别的 tab 再回视频库，搜出来的结果还在。
    val shown = videos.filter { v -> query.isBlank() || v.name.contains(query, ignoreCase = true) }

    fun openTagSheet(v: Video) {
        sheets.open("给「${v.name}」打标签", "一个视频一个标签，标签决定它会被整理到哪个文件夹") {
            tags.forEach { tag ->
                val on = v.tagId == tag.id
                val c = hexColor(tag.color)
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(11.dp))
                        .clickable {
                            sheets.close()
                            onTag(v.id, if (on) null else tag.id)
                        }
                        .padding(vertical = 12.dp, horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Box(Modifier.size(9.dp).clip(CircleShape).background(c))
                    Text(tag.name, color = t.text, fontSize = 13.5.sp)
                    Spacer(Modifier.weight(1f))
                    if (on) Text("✓", color = t.accent, fontSize = 13.sp)
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(t.line))
            }
            if (v.tagId != null) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(11.dp))
                        .clickable {
                            sheets.close()
                            onTag(v.id, null)
                        }
                        .padding(vertical = 12.dp, horizontal = 4.dp),
                ) {
                    Text("清除标签", color = t.danger, fontSize = 13.sp)
                }
            }
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 12.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            Column {
                Text("视频库", color = t.text, fontSize = 21.sp, fontWeight = FontWeight.Bold)
                Text(
                    "${videos.size} 个视频 · 待整理 ${videos.count { it.tagId != null && !it.isOrganized }}",
                    color = t.muted2,
                    fontSize = 11.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }
            Spacer(Modifier.weight(1f))
            GlassIconButton(Icons.Rounded.Refresh, onClick = onRefresh, contentDescription = "刷新")
            Spacer(Modifier.width(6.dp))
            GlassIconButton(Icons.Rounded.SwapVert, onClick = onOpenTransfer, contentDescription = "传输")
        }

        // 用 BasicTextField 自绘搜索框：Material3 的 TextField 最小高度 56dp，
        // 强压到 44dp 会把 placeholder 的上半截裁掉（真机上很明显）
        val searchShape = RoundedCornerShape(12.dp)
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 18.dp)
                .height(44.dp)
                .clip(searchShape)
                .background(t.ink(0.045f))
                .border(1.dp, t.line, searchShape)
                .padding(horizontal = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                Icons.Rounded.Search,
                contentDescription = null,
                tint = t.muted,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(8.dp))
            Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
                if (query.isEmpty()) {
                    Text("搜索文件名", color = t.muted2, fontSize = 12.5.sp)
                }
                BasicTextField(
                    value = query,
                    onValueChange = onQuery,
                    singleLine = true,
                    textStyle = TextStyle(color = t.text, fontSize = 12.5.sp),
                    cursorBrush = SolidColor(t.accent),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            if (query.isNotEmpty()) {
                Icon(
                    Icons.Rounded.Close,
                    contentDescription = "清空",
                    tint = t.muted,
                    modifier = Modifier
                        .size(14.dp)
                        .clip(CircleShape)
                        .clickable { onQuery("") },
                )
            }
        }

        LazyRow(
            contentPadding = PaddingValues(start = 18.dp, end = 18.dp),
            horizontalArrangement = Arrangement.spacedBy(7.dp),
            modifier = Modifier.padding(top = 11.dp, bottom = 4.dp),
        ) {
            items(LIST_FILTERS) { pair ->
                FilterChipView(label = pair.second, on = status == pair.first) { onStatus(pair.first) }
            }
            items(tags, key = { "tag-${it.id}" }) { tag ->
                // 标签可多选：勾上的标签取并集，再点一次取消
                FilterChipView(
                    label = tag.name,
                    on = selectedTags.contains(tag.id),
                    dot = hexColor(tag.color),
                ) { onToggleTag(tag.id) }
            }
        }

        when {
            error != null -> CenterNote(error, dangerous = true)
            loading && videos.isEmpty() -> CenterNote("加载中…")
            shown.isEmpty() -> CenterNote(
                if (videos.isEmpty()) "还没有视频，去网页端扫描源文件夹" else "没有符合筛选条件的视频"
            )

            else -> LazyColumn(
                state = listState,
                contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 10.dp, bottom = 120.dp),
                verticalArrangement = Arrangement.spacedBy(9.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                // 两组：还没整理的（文件在源文件夹里）/ 已整理到标签文件夹的
                val fromSource = shown.filter { !it.isOrganized }
                val fromTags = shown.filter { it.isOrganized }
                if (fromSource.isNotEmpty()) {
                    item(key = "sec-source") { GroupHead("源文件夹", fromSource.size) }
                    items(fromSource, key = { "s-${it.id}" }) { v ->
                        VideoRow(
                            v = v,
                            thumb = api.thumbUrl(v),
                            onClick = { onOpen(v.id) },
                            onTagClick = { openTagSheet(v) },
                        )
                    }
                }
                if (fromTags.isNotEmpty()) {
                    item(key = "sec-organized") { GroupHead("标签文件夹", fromTags.size) }
                    items(fromTags, key = { "o-${it.id}" }) { v ->
                        VideoRow(
                            v = v,
                            thumb = api.thumbUrl(v),
                            onClick = { onOpen(v.id) },
                            onTagClick = { openTagSheet(v) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterChipView(label: String, on: Boolean, dot: Color? = null, onClick: () -> Unit) {
    val t = tokens()
    Row(
        Modifier
            .height(28.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(if (on) t.accent.copy(alpha = 0.16f) else t.ink(0.05f))
            .border(1.dp, if (on) t.accent.copy(alpha = 0.42f) else t.line, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        dot?.let { Box(Modifier.size(5.dp).clip(CircleShape).background(it)) }
        Text(
            label,
            color = if (on) t.accent else t.muted,
            fontSize = 11.5.sp,
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}

@Composable
private fun VideoRow(
    v: Video,
    thumb: String,
    onClick: () -> Unit,
    onTagClick: () -> Unit,
) {
    val t = tokens()
    val tagColor = if (!v.tagColor.isNullOrEmpty()) hexColor(v.tagColor!!) else t.muted
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.022f))))
            .border(1.dp, t.line, shape)
            .clickable(onClick = onClick)
            .padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        Box(
            Modifier
                .width(76.dp)
                .height(44.dp)
                .clip(RoundedCornerShape(9.dp))
                .background(gradientFor(v.id))
        ) {
            if (thumb.isNotEmpty()) {
                AsyncImage(
                    model = thumb,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            Box(
                Modifier
                    .align(Alignment.BottomEnd)
                    .padding(3.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(Color.Black.copy(alpha = 0.55f))
                    .padding(horizontal = 3.dp, vertical = 1.dp)
            ) {
                Text(fmtDuration(v.duration), color = Color.White, fontSize = 8.5.sp)
            }
            val pos = v.position
            if (pos != null && v.duration > 0) {
                val frac = (pos / v.duration).toFloat().coerceIn(0f, 1f)
                Box(
                    Modifier
                        .align(Alignment.BottomStart)
                        .fillMaxWidth()
                        .height(2.5.dp)
                        .background(Color.Black.copy(alpha = 0.4f))
                ) {
                    Box(Modifier.fillMaxWidth(frac).height(2.5.dp).background(t.accent))
                }
            }
        }
        Column(Modifier.weight(1f)) {
            Text(
                v.name,
                color = t.ink(0.88f),
                fontSize = 12.5.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (v.tagName != null) {
                    TagPill(v.tagName, tagColor)
                } else {
                    Row(
                        Modifier
                            .height(19.dp)
                            .clip(RoundedCornerShape(5.dp))
                            .background(t.ink(0.05f))
                            .border(1.dp, t.ink(0.10f), RoundedCornerShape(5.dp))
                            .clickable(onClick = onTagClick)
                            .padding(horizontal = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("+ 标记", color = t.muted, fontSize = 10.sp)
                    }
                }
                StatusPill(v.isOrganized)
                Spacer(Modifier.weight(1f))
                Text(sizeText(v.size), color = t.muted2, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun CenterNote(text: String, dangerous: Boolean = false) {
    val t = tokens()
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text,
            color = if (dangerous) t.danger else t.muted,
            fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 40.dp),
        )
    }
}

/** 体积人类可读：B / KB / MB / GB 四档（356 KB 以前被显示成 0 MB） */
internal fun sizeText(bytes: Long): String {
    if (bytes <= 0) return "0 B"
    val kb = bytes / 1024.0
    val mb = kb / 1024.0
    val gb = mb / 1024.0
    return when {
        gb >= 1 -> "%.1f GB".format(gb)
        mb >= 1 -> "%.1f MB".format(mb)
        kb >= 1 -> "%.0f KB".format(kb)
        else -> "$bytes B"
    }
}

/** 视频库分组标题：源文件夹 / 标签文件夹 */
@Composable
private fun GroupHead(title: String, count: Int) {
    val t = tokens()
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp, bottom = 1.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(6.dp).clip(CircleShape).background(t.accent),
        )
        Spacer(Modifier.width(8.dp))
        Text(title, color = t.ink(0.9f), fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.width(6.dp))
        Text(
            "$count",
            color = t.accent,
            fontSize = 11.sp,
            modifier = Modifier
                .clip(RoundedCornerShape(999.dp))
                .background(t.accentDim)
                .padding(horizontal = 7.dp, vertical = 1.dp),
        )
    }
}
