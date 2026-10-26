package com.videosorter.app.ui

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ArrowBack
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.Downloads
import com.videosorter.app.data.Video
import kotlinx.coroutines.launch

@Composable
fun TransferScreen(
    api: Api,
    onBack: () -> Unit,
    onToast: (String) -> Unit,
) {
    val t = tokens()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var tab by remember { mutableStateOf(0) } // 0 上传 / 1 下载
    var uploading by remember { mutableStateOf(false) }
    var uploadName by remember { mutableStateOf("") }
    var videos by remember { mutableStateOf<List<Video>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }

    LaunchedEffect(tab) {
        if (tab == 1) {
            loading = true
            runCatching { api.videos() }.onSuccess { videos = it.items }
            loading = false
        }
    }

    fun fileName(resolver: ContentResolver, uri: Uri): String {
        runCatching {
            resolver.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && c.moveToFirst()) return c.getString(idx) ?: "upload.mp4"
            }
        }
        return "upload.mp4"
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val name = fileName(ctx.contentResolver, uri)
        uploadName = name
        uploading = true
        scope.launch {
            runCatching { api.upload(ctx.contentResolver, uri, name) }
                .onSuccess { onToast(if (it) "上传完成：$name" else "上传失败") }
                .onFailure { onToast("上传失败：${it.message}") }
            uploading = false
        }
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 14.dp, end = 18.dp, top = 12.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            GlassIconButton(Icons.Rounded.ArrowBack, onClick = onBack, contentDescription = "返回")
            Spacer(Modifier.size(12.dp))
            Column {
                Text("传输", color = t.text, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                Text("手机与服务器之间搬视频", color = t.muted2, fontSize = 10.5.sp)
            }
        }

        // 分段
        Row(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 18.dp)
                .clip(RoundedCornerShape(13.dp))
                .background(t.ink(0.05f))
                .padding(4.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            SegButton("上传到服务器", tab == 0, Modifier.weight(1f)) { tab = 0 }
            SegButton("下载到手机", tab == 1, Modifier.weight(1f)) { tab = 1 }
        }

        if (tab == 0) {
            Column(Modifier.padding(horizontal = 18.dp, vertical = 16.dp)) {
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(140.dp)
                        .clip(RoundedCornerShape(16.dp))
                        .background(t.ink(0.03f))
                        .border(1.5.dp, t.ink(0.2f), RoundedCornerShape(16.dp))
                        .clickable(enabled = !uploading) { picker.launch(arrayOf("video/*")) },
                    contentAlignment = Alignment.Center,
                ) {
                    if (uploading) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            CircularProgressIndicator(color = t.accent, strokeWidth = 2.dp, modifier = Modifier.size(26.dp))
                            Spacer(Modifier.height(10.dp))
                            Text("正在上传 $uploadName", color = t.ink(0.7f), fontSize = 11.5.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    } else {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(Icons.Rounded.CloudUpload, contentDescription = null, tint = t.ink(0.7f), modifier = Modifier.size(26.dp))
                            Spacer(Modifier.height(10.dp))
                            Text("选择视频上传", color = t.ink(0.8f), fontSize = 12.5.sp)
                            Text("mp4 / mkv / mov / avi …", color = t.muted2, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
                        }
                    }
                }
                Spacer(Modifier.height(14.dp))
                Text(
                    "上传后自动进入「手机上传」目录并完成扫描，可以直接打标签。",
                    color = t.muted2,
                    fontSize = 10.5.sp,
                    lineHeight = 17.sp,
                )
            }
        } else {
            if (loading) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text("加载中…", color = t.muted, fontSize = 12.sp)
                }
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 12.dp, bottom = 120.dp),
                    verticalArrangement = Arrangement.spacedBy(9.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(videos, key = { it.id }) { v ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(13.dp))
                                .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.022f))))
                                .border(1.dp, t.line, RoundedCornerShape(13.dp))
                                .padding(11.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(11.dp),
                        ) {
                            Box(
                                Modifier
                                    .size(30.dp)
                                    .clip(RoundedCornerShape(9.dp))
                                    .background(Color(0xFF9B8CFF).copy(alpha = 0.16f)),
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(Icons.Rounded.Download, contentDescription = null, tint = Color(0xFF9B8CFF), modifier = Modifier.size(15.dp))
                            }
                            Column(Modifier.weight(1f)) {
                                Text(v.name, color = t.ink(0.88f), fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(
                                    "${fmtDuration(v.duration)} · ${sizeText(v.size)}",
                                    color = t.muted2,
                                    fontSize = 9.5.sp,
                                    modifier = Modifier.padding(top = 3.dp),
                                )
                            }
                            Row(
                                Modifier
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(t.accent.copy(alpha = 0.14f))
                                    .border(1.dp, t.accent.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
                                    .clickable {
                                        runCatching { Downloads.save(ctx, api, v) }
                                            .onSuccess { onToast("开始下载：${v.name}") }
                                            .onFailure { onToast("下载失败：${it.message}") }
                                    }
                                    .padding(horizontal = 10.dp, vertical = 6.dp),
                            ) {
                                Text("下载", color = t.accent, fontSize = 11.sp)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SegButton(label: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = tokens()
    Box(
        modifier
            .height(32.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) t.ink(0.09f) else Color.Transparent)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = if (on) t.ink(0.92f) else t.muted,
            fontSize = 12.sp,
            fontWeight = if (on) FontWeight.Medium else FontWeight.Normal,
        )
    }
}
