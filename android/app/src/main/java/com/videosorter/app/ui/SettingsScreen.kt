package com.videosorter.app.ui

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.BuildConfig
import com.videosorter.app.data.Api
import com.videosorter.app.data.Counts
import com.videosorter.app.data.Session
import com.videosorter.app.data.Tag
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    api: Api,
    session: Session,
    tags: List<Tag>,
    counts: Counts,
    themeMode: String,
    onThemeChange: (String) -> Unit,
    onToast: (String) -> Unit,
    onRefresh: () -> Unit,
    onLogout: () -> Unit,
    onSwitchServer: (String) -> Unit = {},
) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf("") }
    var progress by remember { mutableStateOf(0f) }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        val name = runCatching {
            ctx.contentResolver.query(uri, null, null, null, null)?.use { cur ->
                val i = cur.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cur.moveToFirst() && i >= 0) cur.getString(i) else null
            }
        }.getOrNull() ?: "upload.mp4"
        busy = "上传中"
        scope.launch {
            val ok = runCatching { api.upload(ctx.contentResolver, uri, name) }.getOrDefault(false)
            busy = ""
            onToast(if (ok) "上传完成，正在后台扫描" else "上传失败")
            if (ok) {
                runCatching {
                    val tid = api.scan()
                    while (true) {
                        val t = api.task(tid)
                        progress = (t.percent / 100.0).toFloat()
                        if (t.status != "running") break
                        delay(400)
                    }
                }
                progress = 0f
                onRefresh()
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp),
    ) {
        Spacer(Modifier.height(12.dp))
        Text("设置", fontSize = 19.sp, fontWeight = FontWeight.Bold)
        Text("单人使用 · 数据都在服务器上", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(14.dp))

        // 外观主题
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(14.dp))
                .padding(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("外观主题", fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                Text(themeLabel(themeMode), fontSize = 12.sp, color = MaterialTheme.colorScheme.primary)
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("light" to "浅色", "dark" to "深色", "auto" to "跟随系统").forEach { (key, label) ->
                    val on = themeMode == key
                    Box(
                        Modifier
                            .weight(1f)
                            .background(
                                if (on) MaterialTheme.colorScheme.primary.copy(alpha = 0.16f) else MaterialTheme.colorScheme.surfaceVariant,
                                RoundedCornerShape(10.dp),
                            )
                            .clickable { onThemeChange(key) }
                            .padding(vertical = 9.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            label,
                            fontSize = 12.sp,
                            color = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(10.dp))

        // 服务器
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(14.dp))
                .padding(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("服务器", fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                Box(Modifier.size(7.dp).background(Accent, CircleShape))
                Spacer(Modifier.width(6.dp))
                Text("已连接", fontSize = 11.sp, color = MaterialTheme.colorScheme.primary)
            }
            Spacer(Modifier.height(6.dp))
            Text(api.base, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Text("视频 ${counts.all}", fontSize = 12.sp)
                Text("待整理 ${counts.tagged}", fontSize = 12.sp)
                Text("已整理 ${counts.organized}", fontSize = 12.sp)
                Text("标签 ${tags.size}", fontSize = 12.sp)
            }
            Spacer(Modifier.height(10.dp))
            OutlinedButton(
                onClick = {
                    if (busy.isNotEmpty()) return@OutlinedButton
                    busy = "扫描中"
                    scope.launch {
                        try {
                            val tid = api.scan()
                            while (true) {
                                val t = api.task(tid)
                                progress = (t.percent / 100.0).toFloat()
                                if (t.status != "running") {
                                    onToast(t.message.ifBlank { "扫描完成" })
                                    break
                                }
                                delay(400)
                            }
                        } catch (e: Exception) {
                            onToast(e.message ?: "扫描失败")
                        } finally {
                            busy = ""
                            progress = 0f
                            onRefresh()
                        }
                    }
                },
                shape = RoundedCornerShape(10.dp),
            ) {
                Text(if (busy == "扫描中") "扫描中…" else "扫描源文件夹", fontSize = 12.sp)
            }
            if (busy.isNotEmpty()) {
                LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            }
            val others = session.servers().filter { it != api.base }
            if (others.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text("切换服务器", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(6.dp))
                others.take(5).forEach { url ->
                    Box(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 3.dp)
                            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(9.dp))
                            .clickable { onSwitchServer(url) }
                            .padding(horizontal = 12.dp, vertical = 9.dp),
                    ) {
                        Text(url.removePrefix("http://"), fontSize = 12.sp)
                    }
                }
            }
        }
        Spacer(Modifier.height(10.dp))

        // 上传下载
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(14.dp))
                .padding(14.dp),
        ) {
            Text("上传下载", fontSize = 14.sp, fontWeight = FontWeight.Medium)
            Text("把手机里的视频传到服务器，直接在播放页打标签。", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = { picker.launch(arrayOf("video/*")) },
                enabled = busy.isEmpty(),
                shape = RoundedCornerShape(10.dp),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary),
            ) {
                Text(if (busy == "上传中") "上传中…" else "选择视频上传", fontSize = 12.sp)
            }
        }
        Spacer(Modifier.height(10.dp))

        // 关于
        Column(
            Modifier
                .fillMaxWidth()
                .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(14.dp))
                .padding(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("关于项目", fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                Text("v" + BuildConfig.VERSION_NAME, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                "视频整理 · VideoSorter\n自托管的视频扫描与标签整理工具，数据保存在你自己的服务器上。",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                lineHeight = 17.sp,
            )
        }
        Spacer(Modifier.height(16.dp))

        OutlinedButton(
            onClick = onLogout,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().height(46.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
        ) {
            Text("退出登录", fontSize = 13.sp)
        }
        Spacer(Modifier.height(20.dp))
    }
}
