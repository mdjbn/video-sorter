package com.videosorter.app.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Cached
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.DarkMode
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.LightMode
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.SettingsBrightness
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Tag
import androidx.compose.material.icons.rounded.Dns
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
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.BuildConfig
import com.videosorter.app.data.Api
import com.videosorter.app.data.CacheInfo
import com.videosorter.app.data.Counts
import com.videosorter.app.data.ServerInfo
import com.videosorter.app.data.Session
import com.videosorter.app.data.SessionRow
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video
import kotlinx.coroutines.launch

private val TAG_COLORS = listOf(
    "#f4a259", "#ef5b7b", "#4cc9f0", "#9b8cff",
    "#8d98a8", "#5fe0a8", "#ffd166", "#ff8fab",
)

private fun bytesText(n: Long): String = when {
    n <= 0 -> "0 B"
    n < 1024 -> "$n B"
    n < 1024 * 1024 -> "${n / 1024} KB"
    n < 1024L * 1024 * 1024 -> String.format("%.1f MB", n / 1024.0 / 1024.0)
    else -> String.format("%.2f GB", n / 1024.0 / 1024.0 / 1024.0)
}

private fun shortTime(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    val s = iso.replace("T", " ")
    return if (s.length >= 16) s.substring(5, 16) else s
}

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
    onOpenVideo: (Int) -> Unit = {},
    sheets: SheetState,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current

    var cache by remember { mutableStateOf<CacheInfo?>(null) }
    var history by remember { mutableStateOf<List<Video>>(emptyList()) }
    var sessions by remember { mutableStateOf<List<SessionRow>>(emptyList()) }
    var server by remember { mutableStateOf<ServerInfo?>(null) }
    var scanPct by remember { mutableStateOf<Float?>(null) }

    LaunchedEffect(Unit) {
        runCatching { cache = api.cache() }
        runCatching { server = api.serverInfo() }
        runCatching { history = api.history() }
        runCatching { sessions = api.sessions() }
    }

    fun reloadCache() {
        scope.launch { runCatching { cache = api.cache() } }
    }

    fun scanNow() {
        scope.launch {
            val taskId = runCatching { api.scan() }.getOrNull() ?: run {
                onToast("扫描请求失败"); return@launch
            }
            scanPct = 0f
            repeat(300) {
                val task = runCatching { api.task(taskId) }.getOrNull() ?: return@repeat
                scanPct = (task.percent.coerceIn(0.0, 100.0) / 100.0).toFloat()
                if (task.status != "running") {
                    scanPct = null
                    onToast(task.message.ifEmpty { "扫描完成" })
                    onRefresh()
                    return@launch
                }
                kotlinx.coroutines.delay(350)
            }
            scanPct = null
            onToast("扫描超时")
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(start = 18.dp, end = 18.dp, top = 52.dp, bottom = 120.dp)
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text("设置", fontSize = 21.sp, fontWeight = FontWeight.Bold, color = t.text)
            Spacer(Modifier.width(10.dp))
            Text("单人使用", fontSize = 11.sp, color = t.muted2)
        }
        Spacer(Modifier.height(16.dp))

        // 外观主题
        GroupCard {
            SettingRow(if (themeIsDark(themeMode)) Icons.Rounded.DarkMode else Icons.Rounded.LightMode,
                "外观主题", themeLabel(themeMode), onClick = null, last = false)
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(start = 12.dp, end = 12.dp, top = 2.dp, bottom = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                ThemeChip("浅色", themeMode == "light", Modifier.weight(1f)) { onThemeChange("light") }
                ThemeChip("深色", themeMode == "dark", Modifier.weight(1f)) { onThemeChange("dark") }
                ThemeChip("跟随系统", themeMode == "auto", Modifier.weight(1f)) { onThemeChange("auto") }
            }
        }

        // 主要入口
        GroupCard {
            SettingRow(Icons.Rounded.Dns, "服务器", api.base.replace("http://", ""), {
                scope.launch {
                    runCatching { server = api.serverInfo() }
                    sheets.open("服务器", "连接 · 状态 · 目录") {
                        ServerSheet(api, server, session, onSwitchServer, onToast)
                    }
                }
            })
            SettingRow(Icons.Rounded.Person, "账号", session.lastUser().ifEmpty { "admin" }, {
                scope.launch {
                    runCatching { sessions = api.sessions() }
                    sheets.open("账号", "用户名 · 密码 · 会话") {
                        AccountSheet(api, session, sessions, onToast, onLogout) { sessions = it }
                    }
                }
            })
            SettingRow(Icons.Rounded.CloudUpload, "上传下载", "下载 / 上传视频", { onOpenTransfer() })
            SettingRow(Icons.Rounded.Search, "扫描源文件夹",
                if (scanPct != null) "${(scanPct!! * 100).toInt()}%" else "重新扫描",
                { if (scanPct == null) scanNow() })
            SettingRow(Icons.Rounded.Tag, "标签管理", "${tags.size} 个", {
                sheets.open("标签管理", "标签名就是整理后的文件夹名") {
                    TagsSheet(api, tags, onToast, onRefresh)
                }
            })
            SettingRow(Icons.Rounded.History, "播放历史", "${history.size} 条", {
                scope.launch {
                    runCatching { history = api.history() }
                    sheets.open("播放历史", "点一条继续看") {
                        HistorySheet(api, history, onOpenVideo, onToast) { history = it }
                    }
                }
            })
            SettingRow(Icons.Rounded.Storage, "缓存与储存",
                cache?.let { bytesText(it.totalBytes) } ?: "—", {
                    scope.launch {
                        runCatching { cache = api.cache() }
                        sheets.open("缓存与储存", "封面与转码分片") {
                            CacheSheet(api, cache, onToast) { cache = it }
                        }
                    }
                })
            SettingRow(Icons.Rounded.Info, "关于项目", "v${BuildConfig.VERSION_NAME}", {
                sheets.open("关于项目", "开源 · MIT") {
                    AboutSheet(ctx)
                }
            }, last = true)
        }

        // 连接状态
        GroupCard {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 14.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .background(t.accent)
                )
                Spacer(Modifier.width(8.dp))
                Text("已连接 · 局域网直连", fontSize = 11.sp, color = t.muted)
            }
        }

        GroupCard {
            SettingRow(Icons.Rounded.Logout, "退出登录", "", { onLogout() }, danger = true, last = true)
        }
    }
}

private fun themeIsDark(mode: String) = mode == "dark"

@Composable
private fun GroupCard(content: @Composable ColumnScope.() -> Unit) {
    val t = tokens()
    Column(
        Modifier
            .fillMaxWidth()
            .padding(bottom = 14.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(
                Brush.verticalGradient(
                    listOf(t.glass, t.glass.copy(alpha = 0.35f))
                )
            )
            .border(1.dp, t.line, RoundedCornerShape(16.dp))
    ) { content() }
}

@Composable
private fun SettingRow(
    icon: ImageVector,
    title: String,
    value: String,
    onClick: (() -> Unit)?,
    danger: Boolean = false,
    last: Boolean = false,
) {
    val t = tokens()
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable { onClick() } else Modifier)
            .padding(horizontal = 14.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            Modifier
                .size(26.dp)
                .clip(RoundedCornerShape(8.dp))
                .background(if (danger) t.danger.copy(alpha = 0.14f) else t.glass),
            contentAlignment = Alignment.Center
        ) {
            Icon(icon, null, tint = if (danger) t.danger else t.muted, modifier = Modifier.size(15.dp))
        }
        Spacer(Modifier.width(11.dp))
        Text(
            title, fontSize = 12.5.sp,
            color = if (danger) t.danger else t.text,
            modifier = Modifier.weight(1f)
        )
        if (value.isNotEmpty()) {
            Text(value, fontSize = 11.sp, color = t.muted2, maxLines = 1)
        }
        if (onClick != null) {
            Spacer(Modifier.width(6.dp))
            Icon(Icons.Rounded.ChevronRight, null, tint = t.muted2, modifier = Modifier.size(15.dp))
        }
    }
    if (!last) RowDivider()
}

@Composable
private fun RowDivider() {
    val t = tokens()
    Box(
        Modifier
            .fillMaxWidth()
            .padding(start = 51.dp)
            .height(1.dp)
            .background(t.line)
    )
}

@Composable
private fun ThemeChip(text: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = tokens()
    Box(
        modifier
            .height(34.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) t.accentDim else t.ink(0.06f))
            .border(1.dp, if (on) t.accent.copy(alpha = 0.5f) else t.line, RoundedCornerShape(10.dp))
            .clickable { onClick() },
        contentAlignment = Alignment.Center
    ) {
        Text(text, fontSize = 11.5.sp, color = if (on) t.accent else t.muted2,
            fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
    }
}

@Composable
private fun SheetLabel(text: String) {
    val t = tokens()
    Text(text, fontSize = 10.5.sp, color = t.muted2, modifier = Modifier.padding(top = 12.dp, bottom = 6.dp))
}

@Composable
private fun GlassInput(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    password: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
) {
    val t = tokens()
    var show by remember { mutableStateOf(false) }
    Row(
        Modifier
            .fillMaxWidth()
            .height(42.dp)
            .clip(RoundedCornerShape(11.dp))
            .background(t.glass.copy(alpha = 0.55f))
            .border(1.dp, t.line2, RoundedCornerShape(11.dp))
            .padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(Modifier.weight(1f)) {
            if (value.isEmpty()) Text(placeholder, fontSize = 12.5.sp, color = t.muted2)
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = true,
                textStyle = TextStyle(fontSize = 12.5.sp, color = t.text),
                cursorBrush = SolidColor(t.accent),
                visualTransformation = if (password && !show) PasswordVisualTransformation()
                else VisualTransformation.None,
                keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (password) {
            Text(
                if (show) "隐藏" else "显示",
                fontSize = 10.5.sp,
                color = t.accent,
                modifier = Modifier
                    .padding(start = 8.dp)
                    .clickable { show = !show }
            )
        }
    }
}

@Composable
private fun SkinButton(text: String, enabled: Boolean = true, danger: Boolean = false, onClick: () -> Unit) {
    val t = tokens()
    Box(
        Modifier
            .fillMaxWidth()
            .height(42.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(
                when {
                    !enabled -> SolidColor(t.glass.copy(alpha = 0.35f))
                    danger -> SolidColor(t.danger.copy(alpha = 0.16f))
                    else -> Brush.linearGradient(listOf(Color(0xFF5FECAB), Color(0xFF2FBF7C)))
                }
            )
            .border(
                1.dp,
                when {
                    !enabled -> t.line
                    danger -> t.danger.copy(alpha = 0.4f)
                    else -> Color.Transparent
                },
                RoundedCornerShape(12.dp)
            )
            .then(if (enabled) Modifier.clickable { onClick() } else Modifier),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold,
            color = when {
                !enabled -> t.muted2
                danger -> t.danger
                else -> Color(0xFF04160D)
            }
        )
    }
}

// ---------------- 服务器 ----------------

@Composable
private fun ServerSheet(
    api: Api,
    server: ServerInfo?,
    session: Session,
    onSwitchServer: (String) -> Unit,
    onToast: (String) -> Unit,
) {
    val t = tokens()
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        SheetLabel("当前服务器")
        Text(api.base, fontSize = 13.sp, color = t.text, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(4.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(6.dp).clip(CircleShape).background(if (server != null) t.accent else t.danger))
            Spacer(Modifier.width(6.dp))
            Text(
                if (server != null) "在线 · v${server.version}" else "离线或未响应",
                fontSize = 11.sp, color = t.muted2
            )
        }
        SheetLabel("运行环境")
        Text("平台 ${server?.platform.orEmpty().ifEmpty { "—" }}", fontSize = 11.sp, color = t.muted)
        Text("Python ${server?.python.orEmpty().ifEmpty { "—" }}", fontSize = 11.sp, color = t.muted)
        Text(
            "ffmpeg ${if (server?.mediaReady == true) "已就绪" else "未找到（将只能直放）"}",
            fontSize = 11.sp, color = if (server?.mediaReady == true) t.muted else t.warn
        )
        SheetLabel("目录")
        Text("数据 ${server?.dataDir.orEmpty().ifEmpty { "—" }}", fontSize = 10.5.sp, color = t.muted2)
        Text("上传 ${server?.uploadDir.orEmpty().ifEmpty { "—" }}", fontSize = 10.5.sp, color = t.muted2)

        val others = session.servers().filter { it != api.base }
        if (others.isNotEmpty()) {
            SheetLabel("切换服务器")
            others.forEach { url ->
                Row(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .clickable { onSwitchServer(url); onToast("正在切换到 $url") }
                        .padding(vertical = 10.dp, horizontal = 2.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Rounded.Dns, null, tint = t.muted2, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(url, fontSize = 12.sp, color = t.text, modifier = Modifier.weight(1f))
                    Text("切换", fontSize = 11.sp, color = t.accent)
                }
            }
        }
        Spacer(Modifier.height(14.dp))
    }
}

// ---------------- 账号 ----------------

@Composable
private fun AccountSheet(
    api: Api,
    session: Session,
    sessions: List<SessionRow>,
    onToast: (String) -> Unit,
    onLogout: () -> Unit,
    onSessions: (List<SessionRow>) -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var user by remember { mutableStateOf(session.lastUser().ifEmpty { "admin" }) }
    var oldPwd by remember { mutableStateOf("") }
    var newPwd by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        SheetLabel("用户名")
        GlassInput(user, { user = it }, "用户名")
        Spacer(Modifier.height(8.dp))
        SkinButton("保存用户名", enabled = !busy && user.isNotBlank()) {
            scope.launch {
                busy = true
                runCatching { api.changeUsername(user.trim()) }
                    .onSuccess { onToast("用户名已更新"); session.setLastUser(user.trim()) }
                    .onFailure { onToast(it.message ?: "修改失败") }
                busy = false
            }
        }

        SheetLabel("修改密码")
        GlassInput(oldPwd, { oldPwd = it }, "当前密码", password = true)
        Spacer(Modifier.height(8.dp))
        GlassInput(newPwd, { newPwd = it }, "新密码（至少 6 位）", password = true)
        Spacer(Modifier.height(8.dp))
        SkinButton("保存密码", enabled = !busy && oldPwd.isNotEmpty() && newPwd.length >= 6) {
            scope.launch {
                busy = true
                runCatching { api.changePassword(oldPwd, newPwd) }
                    .onSuccess {
                        onToast(it.ifEmpty { "密码已更新" })
                        oldPwd = ""; newPwd = ""
                    }
                    .onFailure { onToast(it.message ?: "修改失败") }
                busy = false
            }
        }

        SheetLabel("登录会话（${sessions.size} 个）")
        sessions.take(4).forEach { s ->
            Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Rounded.Check, null, tint = t.accent, modifier = Modifier.size(13.dp))
                Spacer(Modifier.width(7.dp))
                Text(
                    "登录于 ${shortTime(s.createdAt)}" + if (s.lastUsedAt != null) " · 最近 ${shortTime(s.lastUsedAt)}" else "",
                    fontSize = 11.sp, color = t.muted2
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        SkinButton("退出所有设备", enabled = !busy, danger = true) {
            scope.launch {
                busy = true
                runCatching { api.revokeAll() }
                    .onSuccess { onToast(it.ifEmpty { "已退出所有设备" }); runCatching { onSessions(api.sessions()) } }
                    .onFailure { onToast(it.message ?: "操作失败") }
                busy = false
            }
        }
        Spacer(Modifier.height(10.dp))
        SkinButton("退出登录", danger = true) { onLogout() }
        Spacer(Modifier.height(14.dp))
    }
}

// ---------------- 标签管理 ----------------

@Composable
private fun TagsSheet(
    api: Api,
    tags: List<Tag>,
    onToast: (String) -> Unit,
    onChanged: () -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var name by remember { mutableStateOf("") }
    var color by remember { mutableStateOf(TAG_COLORS.first()) }
    var editing by remember { mutableStateOf<Tag?>(null) }
    var editName by remember { mutableStateOf("") }
    var editDir by remember { mutableStateOf("") }
    var editColor by remember { mutableStateOf(TAG_COLORS.first()) }

    if (editing != null) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
            Text("编辑「${editing!!.name}」", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = t.text)
            SheetLabel("标签名 = 文件夹名")
            GlassInput(editName, { editName = it }, "标签名")
            SheetLabel("颜色")
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                TAG_COLORS.forEach { c ->
                    Box(
                        Modifier
                            .size(26.dp)
                            .clip(CircleShape)
                            .background(hexColor(c))
                            .border(2.dp, if (c == editColor) t.text else Color.Transparent, CircleShape)
                            .clickable { editColor = c }
                    )
                }
            }
            SheetLabel("目标文件夹（留空=默认）")
            GlassInput(editDir, { editDir = it }, "/volume1/videos/整理/${editing!!.name}")
            Spacer(Modifier.height(14.dp))
            SkinButton("保存") {
                scope.launch {
                    runCatching {
                        api.updateTag(editing!!.id, name = editName.trim(), color = editColor,
                            dirPath = editDir.trim())
                    }.onSuccess { onToast("已保存"); editing = null; onChanged() }
                        .onFailure { onToast(it.message ?: "保存失败") }
                }
            }
            Spacer(Modifier.height(8.dp))
            SkinButton("删除标签", danger = true) {
                scope.launch {
                    runCatching { api.deleteTag(editing!!.id) }
                        .onSuccess { onToast("已删除（视频回到未标记）"); editing = null; onChanged() }
                        .onFailure { onToast(it.message ?: "删除失败") }
                }
            }
            Spacer(Modifier.height(8.dp))
            SkinButton("返回列表", danger = false) { editing = null }
            Spacer(Modifier.height(14.dp))
        }
        return
    }

    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        tags.forEach { tag ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .clickable {
                        editing = tag
                        editName = tag.name
                        editDir = tag.dirPath ?: ""
                        editColor = TAG_COLORS.firstOrNull { it.equals(tag.color, true) } ?: TAG_COLORS.first()
                    }
                    .padding(vertical = 9.dp, horizontal = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(Modifier.size(10.dp).clip(CircleShape).background(hexColor(tag.color)))
                Spacer(Modifier.width(9.dp))
                Column(Modifier.weight(1f)) {
                    Text(tag.name, fontSize = 12.5.sp, color = t.text)
                    Text(
                        tag.dirPath?.takeIf { it.isNotBlank() } ?: tag.dir ?: "默认目录",
                        fontSize = 9.5.sp, color = t.muted2, maxLines = 1
                    )
                }
                Text("${tag.count} 个", fontSize = 10.5.sp, color = t.muted2)
                Spacer(Modifier.width(6.dp))
                Icon(Icons.Rounded.ChevronRight, null, tint = t.muted2, modifier = Modifier.size(14.dp))
            }
            RowDivider()
        }

        SheetLabel("新建标签")
        GlassInput(name, { name = it }, "例如：宠物 / 2025 旅行")
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            TAG_COLORS.forEach { c ->
                Box(
                    Modifier
                        .size(26.dp)
                        .clip(CircleShape)
                        .background(hexColor(c))
                        .border(2.dp, if (c == color) t.text else Color.Transparent, CircleShape)
                        .clickable { color = c }
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        SkinButton("创建标签", enabled = name.isNotBlank()) {
            scope.launch {
                runCatching { api.createTag(name.trim(), color) }
                    .onSuccess { onToast("已创建「${name.trim()}」"); name = ""; onChanged() }
                    .onFailure { onToast(it.message ?: "创建失败") }
            }
        }
        Spacer(Modifier.height(14.dp))
    }
}

// ---------------- 播放历史 ----------------

@Composable
private fun HistorySheet(
    api: Api,
    history: List<Video>,
    onOpenVideo: (Int) -> Unit,
    onToast: (String) -> Unit,
    onReload: (List<Video>) -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    if (history.isEmpty()) {
        Text("还没有播放记录，去播放页看几个视频吧。", fontSize = 12.sp, color = t.muted2)
        return
    }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        history.take(20).forEach { v ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .clickable { onOpenVideo(v.id); onToast("已跳到「${v.name}」") }
                    .padding(vertical = 9.dp, horizontal = 2.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(Icons.Rounded.History, null, tint = t.muted2, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(9.dp))
                Column(Modifier.weight(1f)) {
                    Text(v.name, fontSize = 12.sp, color = t.text, maxLines = 1)
                    val pos = v.position ?: 0.0
                    Text(
                        "${fmtDuration(pos)} / ${fmtDuration(v.duration)} · ${shortTime(v.watchedAt)}",
                        fontSize = 9.5.sp, color = t.muted2
                    )
                }
                Text(
                    v.tagName ?: "未标记", fontSize = 10.sp,
                    color = if (v.tagName != null) hexColor(v.tagColor) else t.muted2
                )
            }
            RowDivider()
        }
        Spacer(Modifier.height(12.dp))
        SkinButton("清除全部历史", danger = true) {
            scope.launch {
                runCatching { api.clearHistory() }
                    .onSuccess { onToast("已清除播放历史"); runCatching { onReload(api.history()) } }
                    .onFailure { onToast(it.message ?: "清除失败") }
            }
        }
        Spacer(Modifier.height(14.dp))
    }
}

// ---------------- 缓存与储存 ----------------

@Composable
private fun CacheSheet(
    api: Api,
    cache: CacheInfo?,
    onToast: (String) -> Unit,
    onReload: (CacheInfo) -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    val c = cache
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatBox("封面", bytesText(c?.thumbs?.bytes ?: 0L), "${c?.thumbs?.count ?: 0} 张", Modifier.weight(1f))
            StatBox("转码", bytesText(c?.hls?.bytes ?: 0L), "${c?.hls?.count ?: 0} 个文件", Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        StatBox("合计", bytesText(c?.totalBytes ?: 0L), "数据目录", Modifier.fillMaxWidth())
        Spacer(Modifier.height(6.dp))
        Text(c?.dataDir.orEmpty(), fontSize = 10.sp, color = t.muted2)

        SheetLabel("清理")
        SkinButton("清除封面（会按需重新生成）", danger = true) {
            scope.launch {
                runCatching { api.clearCache("thumbs") }
                    .onSuccess { onToast("已清除封面缓存"); onReload(it) }
                    .onFailure { onToast(it.message ?: "清理失败") }
            }
        }
        Spacer(Modifier.height(8.dp))
        SkinButton("清除转码缓存", danger = true) {
            scope.launch {
                runCatching { api.clearCache("hls") }
                    .onSuccess { onToast("已清除转码缓存"); onReload(it) }
                    .onFailure { onToast(it.message ?: "清理失败") }
            }
        }
        Spacer(Modifier.height(8.dp))
        SkinButton("全部清除", danger = true) {
            scope.launch {
                runCatching { api.clearCache("all") }
                    .onSuccess { onToast("已清除全部缓存"); onReload(it) }
                    .onFailure { onToast(it.message ?: "清理失败") }
            }
        }
        Spacer(Modifier.height(14.dp))
    }
}

@Composable
private fun StatBox(label: String, value: String, sub: String, modifier: Modifier = Modifier) {
    val t = tokens()
    Column(
        modifier
            .clip(RoundedCornerShape(14.dp))
            .background(Brush.verticalGradient(listOf(t.glass, t.glass.copy(alpha = 0.35f))))
            .border(1.dp, t.line, RoundedCornerShape(14.dp))
            .padding(horizontal = 12.dp, vertical = 11.dp)
    ) {
        Text(label, fontSize = 10.sp, color = t.muted2)
        Spacer(Modifier.height(3.dp))
        Text(value, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = t.text)
        Text(sub, fontSize = 9.5.sp, color = t.muted2)
    }
}

// ---------------- 关于 ----------------

@Composable
private fun AboutSheet(ctx: android.content.Context) {
    val t = tokens()
    Column(Modifier.fillMaxWidth()) {
        Text("视频整理 · VideoSorter", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = t.text)
        Spacer(Modifier.height(4.dp))
        Text("v${BuildConfig.VERSION_NAME} · MIT License", fontSize = 11.sp, color = t.muted2)
        Spacer(Modifier.height(12.dp))
        Text(
            "自托管的视频分类整理工具：扫描源文件夹 → 播放并打标签 → 一键按标签整理到对应文件夹，支持撤销。",
            fontSize = 11.5.sp, color = t.muted
        )
        Spacer(Modifier.height(14.dp))
        Row(
            Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .clickable {
                    runCatching {
                        ctx.startActivity(
                            Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/mdjbn/video-sorter"))
                        )
                    }
                }
                .padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(Icons.Rounded.Info, null, tint = t.accent, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Text("github.com/mdjbn/video-sorter", fontSize = 12.sp, color = t.accent)
        }
        Spacer(Modifier.height(6.dp))
        Text("默认账号 admin / admin1234 · 请部署后尽快修改", fontSize = 10.5.sp, color = t.muted2)
        Spacer(Modifier.height(14.dp))
    }
}
