package com.videosorter.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.videosorter.app.data.Api
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video

private fun colorOf(hex: String?): Color = runCatching {
    Color(android.graphics.Color.parseColor(hex ?: "#8d98a8"))
}.getOrDefault(Color(0xFF8D98A8))

private fun dur(sec: Double): String {
    val s = sec.toInt()
    return if (s >= 3600) "%d:%02d:%02d".format(s / 3600, (s % 3600) / 60, s % 60) else "%d:%02d".format(s / 60, s % 60)
}

@Composable
@OptIn(ExperimentalFoundationApi::class)
fun ListScreen(
    api: Api,
    videos: List<Video>,
    tags: List<Tag>,
    loading: Boolean,
    error: String?,
    onOpen: (Int) -> Unit,
    onTag: (Int, Int?) -> Unit,
    onRefresh: () -> Unit,
    onDownload: (Video) -> Unit = {},
    onDelete: (Video) -> Unit = {},
) {
    var filter by remember { mutableStateOf("all") }
    var tagPick by remember { mutableStateOf<Video?>(null) }
    var menuFor by remember { mutableStateOf<Video?>(null) }

    val shown = remember(videos, filter) {
        when (filter) {
            "idle" -> videos.filter { it.tagId == null && !it.isOrganized }
            "tagged" -> videos.filter { it.tagId != null && !it.isOrganized }
            "organized" -> videos.filter { it.isOrganized }
            else -> videos
        }
    }
    val filters = listOf(
        "all" to "全部",
        "idle" to "未标记",
        "tagged" to "待整理",
        "organized" to "已整理",
    )

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("视频库", fontSize = 19.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Text("${shown.size} 个", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LazyRow(contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(filters) { (key, label) ->
                val on = filter == key
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = if (on) MaterialTheme.colorScheme.primary.copy(alpha = 0.16f) else MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.clickable { filter = key },
                ) {
                    Text(
                        label,
                        fontSize = 12.sp,
                        color = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                    )
                }
            }
        }

        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            error != null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error, fontSize = 13.sp, color = MaterialTheme.colorScheme.error)
                    TextButton(onClick = onRefresh) { Text("重试") }
                }
            }
            shown.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("没有符合条件的视频", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> LazyColumn(
                contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(shown, key = { it.id }) { v ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(MaterialTheme.colorScheme.surface)
                            .combinedClickable(
                                onClick = { onOpen(v.id) },
                                onLongClick = { menuFor = v },
                            )
                            .padding(10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            Modifier
                                .width(104.dp)
                                .aspectRatio(16f / 9f)
                                .clip(RoundedCornerShape(9.dp))
                                .background(MaterialTheme.colorScheme.surfaceVariant),
                        ) {
                            val url = api.thumbUrl(v)
                            if (url.isNotEmpty()) {
                                AsyncImage(
                                    model = url,
                                    contentDescription = null,
                                    contentScale = ContentScale.Crop,
                                    modifier = Modifier.fillMaxSize(),
                                )
                            }
                            Box(
                                Modifier
                                    .align(Alignment.BottomEnd)
                                    .padding(4.dp)
                                    .background(Color.Black.copy(alpha = 0.6f), RoundedCornerShape(4.dp))
                                    .padding(horizontal = 4.dp, vertical = 1.dp),
                            ) {
                                Text(dur(v.duration), color = Color.White, fontSize = 9.sp)
                            }
                        }
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(
                                v.name,
                                fontSize = 13.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                fontWeight = FontWeight.Medium,
                            )
                            Spacer(Modifier.height(6.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                val t = tags.firstOrNull { it.id == v.tagId }
                                if (t != null) {
                                    Box(
                                        Modifier
                                            .background(colorOf(t.color).copy(alpha = 0.16f), RoundedCornerShape(20.dp))
                                            .padding(horizontal = 8.dp, vertical = 2.dp),
                                    ) {
                                        Text(t.name, fontSize = 10.sp, color = colorOf(t.color))
                                    }
                                } else {
                                    Box(
                                        Modifier
                                            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(20.dp))
                                            .clickable { tagPick = v }
                                            .padding(horizontal = 8.dp, vertical = 2.dp),
                                    ) {
                                        Text("+ 标记", fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                                if (v.isOrganized) {
                                    Spacer(Modifier.width(6.dp))
                                    Text("已整理", fontSize = 10.sp, color = MaterialTheme.colorScheme.primary)
                                }
                                Spacer(Modifier.weight(1f))
                                Text(
                                    "${(v.size / 1024 / 1024.0).let { if (it < 1) "<1" else it.toInt().toString() }} MB",
                                    fontSize = 10.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    val picking = tagPick
    if (picking != null) {
        AlertDialog(
            onDismissRequest = { tagPick = null },
            title = { Text("选择标签", fontSize = 16.sp) },
            text = {
                Column {
                    tags.forEach { t ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onTag(picking.id, t.id); tagPick = null }
                                .padding(vertical = 11.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(9.dp).background(colorOf(t.color), RoundedCornerShape(3.dp)))
                            Spacer(Modifier.width(10.dp))
                            Text(t.name, fontSize = 14.sp)
                            Spacer(Modifier.weight(1f))
                            Text("${t.count}", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    TextButton(onClick = { onTag(picking.id, null); tagPick = null }) { Text("清除标签", color = MaterialTheme.colorScheme.error) }
                }
            },
            confirmButton = { TextButton(onClick = { tagPick = null }) { Text("取消") } },
        )
    }

    // 长按菜单：下载到手机 / 删除记录
    val menu = menuFor
    if (menu != null) {
        AlertDialog(
            onDismissRequest = { menuFor = null },
            title = { Text(menu.name, fontSize = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    TextButton(onClick = { menuFor = null; onDownload(menu) }, modifier = Modifier.fillMaxWidth()) {
                        Text("下载到手机", fontSize = 13.sp)
                    }
                    TextButton(onClick = { menuFor = null; onDelete(menu) }, modifier = Modifier.fillMaxWidth()) {
                        Text("删除记录（保留文件）", fontSize = 13.sp)
                    }
                    TextButton(onClick = { menuFor = null }, modifier = Modifier.fillMaxWidth()) {
                        Text("取消", fontSize = 13.sp)
                    }
                }
            },
            confirmButton = {},
        )
    }
}
