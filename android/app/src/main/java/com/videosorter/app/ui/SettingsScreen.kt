package com.videosorter.app.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.DarkMode
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.SwapVert
import androidx.compose.material.icons.rounded.Sync
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.graphics.vector.ImageVector
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
    themeMode: String,
    onThemeChange: (String) -> Unit,
    counts: Counts,
    onToast: (String) -> Unit,
    onRefresh: () -> Unit,
    onLogout: () -> Unit,
    onSwitchServer: (String) -> Unit,
    onOpenTransfer: () -> Unit,
) {
    val t = tokens()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var scanning by remember { mutableStateOf(false) }
    var scanPct by remember { mutableStateOf(0f) }
    val others = remember(api.base) { session.servers().filter { it != api.base } }

    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 120.dp)
    ) {
        Text("设置", color = t.text, fontSize = 21.sp, fontWeight = FontWeight.Bold)

        // ---------------- 外观主题 ----------------
        Spacer(Modifier.height(16.dp))
        SectionLabel("外观主题")
        GroupCard {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                ThemeChip("浅色", themeMode == "light", Modifier.weight(1f)) { onThemeChange("light") }
                ThemeChip("深色", themeMode == "dark", Modifier.weight(1f)) { onThemeChange("dark") }
                ThemeChip("跟随系统", themeMode == "auto", Modifier.weight(1f)) { onThemeChange("auto") }
            }
        }

        // ---------------- 服务器 ----------------
        Spacer(Modifier.height(16.dp))
        SectionLabel("服务器")
        GroupCard {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(11.dp),
            ) {
                RoundIcon(Icons.Rounded.Cloud)
                Column(Modifier.weight(1f)) {
                    Text(
                        api.base.removePrefix("http://").removePrefix("https://"),
                        color = t.text,
                        fontSize = 12.5.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 4.dp)) {
                        Box(Modifier.size(5.dp).clip(RoundedCornerShape(3.dp)).background(t.accent))
                        Text("已连接 · 局域网直连", color = t.muted2, fontSize = 10.5.sp, modifier = Modifier.padding(start = 5.dp))
                    }
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(18.dp),
            ) {
                StatCell("视频", "${counts.all}")
                StatCell("待整理", "${counts.tagged}")
                StatCell("已整理", "${counts.organized}")
                StatCell("标签", "${tags.size}")
            }
            RowDivider()
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable(enabled = !scanning) {
                        scanning = true
                        scanPct = 0f
                        scope.launch {
                            try {
                                val tid = api.scan()
                                while (true) {
                                    val task = api.task(tid)
                                    scanPct = (task.percent.coerceIn(0.0, 100.0) / 100.0).toFloat()
                                    if (task.status != "running") {
                                        onToast(
                                            if (task.status == "done") "扫描完成 · 新增 ${task.done.coerceAtMost(999)}"
                                            else task.message.ifEmpty { "扫描失败" }
                                        )
                                        onRefresh()
                                        break
                                    }
                                    delay(350)
                                }
                            } catch (e: Exception) {
                                onToast(e.message ?: "扫描失败")
                            } finally {
                                scanning = false
                            }
                        }
                    }
                    .padding(horizontal = 14.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(11.dp),
            ) {
                RoundIcon(Icons.Rounded.Sync)
                Column(Modifier.weight(1f)) {
                    Text(
                        if (scanning) "正在扫描… ${(scanPct * 100).toInt()}%" else "扫描源文件夹",
                        color = t.text,
                        fontSize = 12.5.sp,
                    )
                    Text("只扫描新文件，已整理的不动", color = t.muted2, fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
                }
                Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = t.muted2, modifier = Modifier.size(15.dp))
            }
        }

        // ---------------- 传输 ----------------
        Spacer(Modifier.height(16.dp))
        SectionLabel("传输")
        GroupCard {
            SettingRow(Icons.Rounded.SwapVert, "上传 / 下载", "手机 → 服务器，或服务器 → 手机") { onOpenTransfer() }
        }

        // ---------------- 切换服务器 ----------------
        if (others.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            SectionLabel("切换服务器")
            GroupCard {
                others.forEach { url ->
                    SettingRow(Icons.Rounded.Refresh, url.removePrefix("http://"), "已保存的服务器") { onSwitchServer(url) }
                }
            }
        }

        // ---------------- 关于 ----------------
        Spacer(Modifier.height(16.dp))
        SectionLabel("关于")
        GroupCard {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(11.dp),
            ) {
                RoundIcon(Icons.Rounded.Info)
                Text("版本", color = t.text, fontSize = 12.5.sp)
                Spacer(Modifier.weight(1f))
                Text("v${BuildConfig.VERSION_NAME}", color = t.muted2, fontSize = 11.sp)
            }
            RowDivider()
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable {
                        runCatching {
                            ctx.startActivity(
                                Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/mdjbn/video-sorter"))
                            )
                        }
                    }
                    .padding(horizontal = 14.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(11.dp),
            ) {
                RoundIcon(Icons.Rounded.DarkMode)
                Column(Modifier.weight(1f)) {
                    Text("项目主页", color = t.text, fontSize = 12.5.sp)
                    Text("github.com/mdjbn/video-sorter", color = t.muted2, fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
                }
                Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = t.muted2, modifier = Modifier.size(15.dp))
            }
        }

        // ---------------- 退出 ----------------
        Spacer(Modifier.height(18.dp))
        Row(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(t.danger.copy(alpha = 0.1f))
                .border(1.dp, t.danger.copy(alpha = 0.3f), RoundedCornerShape(14.dp))
                .clickable { onLogout() }
                .padding(horizontal = 14.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Rounded.Logout, contentDescription = null, tint = t.danger, modifier = Modifier.size(16.dp))
            Text("退出登录", color = t.danger, fontSize = 13.sp)
        }
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(5.dp).clip(RoundedCornerShape(3.dp)).background(t.muted2))
            Text("数据保存在服务器端，手机只是遥控器", color = t.muted2, fontSize = 10.sp)
        }
    }
}

@Composable
private fun GroupCard(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    val t = tokens()
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.02f))))
            .border(1.dp, t.line, RoundedCornerShape(16.dp)),
        content = content,
    )
}

@Composable
private fun RowDivider() {
    val t = tokens()
    Box(Modifier.fillMaxWidth().height(1.dp).padding(start = 14.dp).background(t.line))
}

@Composable
private fun RoundIcon(icon: ImageVector, danger: Boolean = false) {
    val t = tokens()
    Box(
        Modifier
            .size(26.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(if (danger) t.danger.copy(alpha = 0.14f) else t.ink(0.06f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, contentDescription = null, tint = if (danger) t.danger else t.ink(0.7f), modifier = Modifier.size(14.dp))
    }
}

@Composable
private fun StatCell(label: String, value: String) {
    val t = tokens()
    Column {
        Text(value, color = t.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        Text(label, color = t.muted2, fontSize = 9.5.sp, modifier = Modifier.padding(top = 2.dp))
    }
}

@Composable
private fun SettingRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    danger: Boolean = false,
    onClick: () -> Unit,
) {
    val t = tokens()
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        RoundIcon(icon, danger)
        Column(Modifier.weight(1f)) {
            Text(title, color = if (danger) t.danger else t.text, fontSize = 12.5.sp)
            Text(subtitle, color = t.muted2, fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
        }
        Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = t.muted2, modifier = Modifier.size(15.dp))
    }
}

@Composable
private fun ThemeChip(label: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = tokens()
    Box(
        modifier
            .height(34.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) t.accent.copy(alpha = 0.16f) else t.ink(0.05f))
            .border(1.dp, if (on) t.accent.copy(alpha = 0.45f) else t.line, RoundedCornerShape(10.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label,
            color = if (on) t.accent else t.muted,
            fontSize = 12.sp,
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
        )
    }
}
