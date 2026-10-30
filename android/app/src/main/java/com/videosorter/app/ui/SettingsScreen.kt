package com.videosorter.app.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Label
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.PlayCircle
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.SwapHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.videosorter.app.BuildConfig
import com.videosorter.app.data.Api
import com.videosorter.app.data.MediaCache
import com.videosorter.app.data.CacheInfo
import com.videosorter.app.data.Counts
import com.videosorter.app.data.Session
import com.videosorter.app.data.SessionRow
import com.videosorter.app.data.Source
import com.videosorter.app.data.Tag
import com.videosorter.app.data.Video
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class SetPage { HOME, SERVER, ACCOUNT, SOURCES, TAGS, HISTORY, CACHE, ABOUT }

private val REPO_URL = "https://github.com/mdjbn/video-sorter"

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
    onOpenVideo: (Int) -> Unit,
    onSubPage: (Boolean) -> Unit = {},
) {
    var page by remember { mutableStateOf(SetPage.HOME) }
    BackHandler(enabled = page != SetPage.HOME) { page = SetPage.HOME }
    LaunchedEffect(page) { onSubPage(page != SetPage.HOME) }
    androidx.compose.runtime.DisposableEffect(Unit) { onDispose { onSubPage(false) } }

    // 进/退二级页面都走横向滑入滑出（返回时反向）
    AnimatedContent(
        targetState = page,
        transitionSpec = {
            if (targetState == SetPage.HOME) {
                (slideInHorizontally(tween(240)) { -it / 4 } + fadeIn(tween(200))) togetherWith
                    (slideOutHorizontally(tween(240)) { it / 3 } + fadeOut(tween(180)))
            } else {
                (slideInHorizontally(tween(240)) { it / 4 } + fadeIn(tween(200))) togetherWith
                    (slideOutHorizontally(tween(240)) { -it / 3 } + fadeOut(tween(180)))
            }
        },
        label = "settings-page",
    ) { p ->
        when (p) {
            SetPage.HOME -> SettingsHome(
            api = api,
            tags = tags,
            session = session,
            themeMode = themeMode,
            onThemeChange = onThemeChange,
            counts = counts,
            onToast = onToast,
            onLogout = onLogout,
            onOpenTransfer = onOpenTransfer,
            onOpen = { page = it },
        )
            SetPage.SERVER -> ServerPage(api, session, onToast, onSwitchServer) { page = SetPage.HOME }
            SetPage.ACCOUNT -> AccountPage(api, session, onToast, onLogout) { page = SetPage.HOME }
            SetPage.SOURCES -> SourcesPage(api, onToast, onRefresh) { page = SetPage.HOME }
            SetPage.TAGS -> TagsPage(api, tags, onToast, onRefresh) { page = SetPage.HOME }
            SetPage.HISTORY -> HistoryPage(api, onToast, onOpenVideo) { page = SetPage.HOME }
            SetPage.CACHE -> CachePage(api, onToast) { page = SetPage.HOME }
            SetPage.ABOUT -> AboutPage { page = SetPage.HOME }
        }
    }
}

@Composable
private fun SettingsHome(
    api: Api,
    tags: List<Tag>,
    session: Session,
    themeMode: String,
    onThemeChange: (String) -> Unit,
    counts: Counts,
    onToast: (String) -> Unit,
    onLogout: () -> Unit,
    onOpenTransfer: () -> Unit,
    onOpen: (SetPage) -> Unit,
) {
    val t = tokens()
    Column(
        Modifier
            .fillMaxSize()
            .background(t.bg)
            .statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(start = 18.dp, end = 18.dp, top = 18.dp, bottom = 120.dp),
    ) {
        Text("设置", fontSize = 21.sp, fontWeight = FontWeight.Bold, color = t.text)
        Spacer(Modifier.height(14.dp))

        // 外观主题
        GroupCard {
            Column(Modifier.padding(14.dp)) {
                Text("外观主题", color = t.ink(0.9f), fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ThemeChip("浅色", themeMode == "light", Modifier.weight(1f)) { onThemeChange("light") }
                    ThemeChip("深色", themeMode == "dark", Modifier.weight(1f)) { onThemeChange("dark") }
                    ThemeChip("跟随系统", themeMode == "auto", Modifier.weight(1f)) { onThemeChange("auto") }
                }
            }
        }
        Spacer(Modifier.height(12.dp))

        // 连接
        GroupCard {
            SettingRow(Icons.Rounded.SwapHoriz, "服务器", session.current, onClick = { onOpen(SetPage.SERVER) })
            RowDivider()
            SettingRow(Icons.Rounded.Person, "账号", "改用户名 / 改密码 / 登录设备") { onOpen(SetPage.ACCOUNT) }
        }
        Spacer(Modifier.height(12.dp))

        // 内容
        GroupCard {
            SettingRow(Icons.Rounded.FolderOpen, "源文件夹", "管理要整理的目录") { onOpen(SetPage.SOURCES) }
            RowDivider()
            SettingRow(Icons.Rounded.Label, "标签管理", tagsSubtitle(tags)) { onOpen(SetPage.TAGS) }
            RowDivider()
            SettingRow(Icons.Rounded.History, "播放历史", "小卡片 · 单条或多选删除") { onOpen(SetPage.HISTORY) }
        }
        Spacer(Modifier.height(12.dp))

        // 系统
        GroupCard {
            SettingRow(Icons.Rounded.Download, "上传下载", "进度与历史 · 上传/下载路径") { onOpenTransfer() }
            RowDivider()
            SettingRow(Icons.Rounded.Storage, "缓存与储存", "封面与转码缓存") { onOpen(SetPage.CACHE) }
        }
        Spacer(Modifier.height(12.dp))

        GroupCard {
            SettingRow(Icons.Rounded.Info, "关于项目", "v${BuildConfig.VERSION_NAME} · MIT") { onOpen(SetPage.ABOUT) }
        }
        Spacer(Modifier.height(12.dp))

        GroupCard {
            SettingRow(Icons.Rounded.Logout, "退出登录", danger = true, chevron = false) {
                onToast("已退出登录")
                onLogout()
            }
        }
    }
}

private fun tagsSubtitle(tags: List<Tag>): String =
    if (tags.isEmpty()) "还没有标签，点右上角 ＋ 新建" else "${tags.size} 个标签 · 每个标签一个目标文件夹"

private fun tagsCountLabel(counts: Counts): String {
    val parts = mutableListOf<String>()
    parts.add("视频 ${counts.all}")
    parts.add("待整理 ${counts.tagged}")
    parts.add("已整理 ${counts.organized}")
    return parts.joinToString(" · ")
}

// ---------------- 服务器 ----------------

@Composable
private fun ServerPage(api: Api, session: Session, onToast: (String) -> Unit, onSwitch: (String) -> Unit, onBack: () -> Unit) {
    // 删除服务器后要重算「其它服务器」列表
    var reloadKey by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    var info by remember { mutableStateOf<com.videosorter.app.data.ServerInfo?>(null) }
    var loading by remember { mutableStateOf(false) }

    fun load() {
        scope.launch {
            loading = true
            info = runCatching { api.serverInfo() }.getOrNull()
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    SubScaffold("服务器", onBack, actions = {
        Box(
            Modifier.size(32.dp).clip(RoundedCornerShape(11.dp)).background(tokens().ink(0.06f)).clickable { load() },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Rounded.Refresh, "刷新", tint = tokens().ink(0.75f), modifier = Modifier.size(16.dp)) }
    }) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            GroupCard {
                SettingRow(Icons.Rounded.SwapHoriz, "当前服务器", session.current, chevron = false)
                RowDivider()
                SettingRow(Icons.Rounded.Info, "在线版本", info?.version ?: if (loading) "读取中…" else "未连接", chevron = false)
                RowDivider()
                SettingRow(
                    Icons.Rounded.Folder,
                    "上传目录",
                    info?.uploadDir?.takeIf { it.isNotEmpty() } ?: "默认",
                    chevron = false,
                )
                RowDivider()
                SettingRow(
                    Icons.Rounded.Storage,
                    "数据目录",
                    info?.dataDir?.takeIf { it.isNotEmpty() } ?: "-",
                    chevron = false,
                )
            }

            Spacer(Modifier.height(16.dp))
            Text("切换服务器", color = t2(), fontSize = 11.sp)
            Spacer(Modifier.height(8.dp))
            val others = remember(reloadKey) { session.servers().filter { it != session.current } }
            if (others.isEmpty()) {
                EmptyNote("还没有其它服务器，登录时填写就会自动记录")
            } else {
                GroupCard {
                    others.forEachIndexed { i, url ->
                        if (i > 0) RowDivider()
                        SettingRow(
                            Icons.Rounded.SwapHoriz, url, "点按切换", chevron = false,
                            trailing = {
                                Icon(
                                    Icons.Rounded.Delete, "删除 $url",
                                    tint = tokens().danger.copy(alpha = 0.8f),
                                    modifier = Modifier
                                        .size(30.dp)
                                        .clip(RoundedCornerShape(10.dp))
                                        .clickable(onClick = {
                                            session.removeServer(url)
                                            onToast("已删除 $url")
                                            reloadKey++
                                        })
                                        .padding(7.dp),
                                )
                            },
                        ) {
                            onToast("切换到 $url")
                            onSwitch(url)
                        }
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

// ---------------- 账号 ----------------

@Composable
private fun AccountPage(api: Api, session: Session, onToast: (String) -> Unit, onLogout: () -> Unit, onBack: () -> Unit) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var editUser by remember { mutableStateOf(false) }
    var userDraft by remember { mutableStateOf(session.lastUser().ifEmpty { "admin" }) }
    var pwd by remember { mutableStateOf(false) }
    var pwdErr by remember { mutableStateOf("") }
    var oldPwd by remember { mutableStateOf("") }
    var newPwd by remember { mutableStateOf("") }
    var sessions by remember { mutableStateOf<List<SessionRow>>(emptyList()) }

    LaunchedEffect(Unit) { sessions = runCatching { api.sessions() }.getOrDefault(emptyList()) }

    SubScaffold("账号", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            GroupCard {
                SettingRow(Icons.Rounded.Person, "用户名", session.lastUser().ifEmpty { "admin" }) {
                    userDraft = session.lastUser().ifEmpty { "admin" }
                    editUser = true
                }
                RowDivider()
                SettingRow(Icons.Rounded.Person, "修改密码", "至少 6 位") { pwdErr = ""; pwd = true }
            }
            Spacer(Modifier.height(16.dp))
            Text("登录设备（${sessions.size}）", color = t.muted2, fontSize = 11.sp)
            Spacer(Modifier.height(8.dp))
            GroupCard {
                if (sessions.isEmpty()) {
                    EmptyNote("暂无其它登录设备")
                } else {
                    sessions.forEachIndexed { i, s ->
                        if (i > 0) RowDivider()
                        SettingRow(
                            Icons.Rounded.Person,
                            s.createdAt.ifEmpty { "会话" },
                            if (s.lastUsedAt.isNullOrEmpty()) "创建于 " + s.createdAt else "最近使用 " + s.lastUsedAt,
                            chevron = false,
                        )
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            GroupCard {
                SettingRow(Icons.Rounded.Logout, "退出所有设备", "会让所有已登录的会话失效", danger = true) {
                    scope.launch {
                        runCatching { api.revokeAll() }
                        sessions = emptyList()
                        onToast("已退出所有设备")
                    }
                }
                RowDivider()
                SettingRow(Icons.Rounded.Logout, "退出登录", danger = true, chevron = false) {
                    onToast("已退出登录")
                    onLogout()
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }

    if (editUser) {
        AlertDialog(
            onDismissRequest = { editUser = false },
            title = { Text("修改用户名", color = t.text, fontSize = 15.sp) },
            text = { GlassField(userDraft, { userDraft = it }, placeholder = "用户名") },
            confirmButton = {
                TextButton(onClick = {
                    editUser = false
                    scope.launch {
                        try {
                            api.changeUsername(userDraft.trim())
                            session.setLastUser(userDraft.trim())
                            onToast("用户名已修改")
                        } catch (e: Throwable) {
                            onToast("修改失败：${e.message ?: ""}")
                        }
                    }
                }) { Text("保存", color = t.accent) }
            },
            dismissButton = { TextButton(onClick = { editUser = false }) { Text("取消", color = t.muted) } },
            containerColor = t.panel,
        )
    }

    if (pwd) {
        AlertDialog(
            onDismissRequest = { pwd = false },
            title = { Text("修改密码", color = t.text, fontSize = 15.sp) },
            text = {
                Column {
                    GlassField(oldPwd, { oldPwd = it }, placeholder = "当前密码", password = true)
                    Spacer(Modifier.height(10.dp))
                    GlassField(newPwd, { newPwd = it }, placeholder = "新密码（至少 6 位）", password = true)
                    if (pwdErr.isNotEmpty()) {
                        Spacer(Modifier.height(10.dp))
                        Text(pwdErr, color = t.danger, fontSize = 11.5.sp)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    // 校验失败时保持弹窗与已输入内容，把错误显示在弹窗里
                    val o = oldPwd
                    val n = newPwd
                    when {
                        o.isEmpty() -> { pwdErr = "请输入当前密码"; return@TextButton }
                        n.length < 6 -> { pwdErr = "新密码至少 6 位"; return@TextButton }
                        n == o -> { pwdErr = "新密码不能与当前密码相同"; return@TextButton }
                    }
                    scope.launch {
                        try {
                            api.changePassword(o, n)
                            pwd = false
                            onToast("密码已修改，请重新登录")
                            onLogout()
                        } catch (e: Throwable) {
                            pwdErr = e.message?.takeIf { it.isNotBlank() } ?: "修改失败，请检查当前密码"
                        }
                    }
                }) { Text("保存", color = t.accent) }
            },
            dismissButton = { TextButton(onClick = { pwd = false }) { Text("取消", color = t.muted) } },
            containerColor = t.panel,
        )
    }
}

// ---------------- 源文件夹 ----------------

@Composable
private fun SourcesPage(api: Api, onToast: (String) -> Unit, onRefresh: () -> Unit, onBack: () -> Unit) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var list by remember { mutableStateOf<List<Source>>(emptyList()) }
    var adding by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<Source?>(null) }
    var draft by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    fun load() {
        scope.launch { list = runCatching { api.sources() }.getOrDefault(emptyList()) }
    }

    LaunchedEffect(Unit) { load() }

    SubScaffold("源文件夹", onBack, actions = {
        Box(
            Modifier.size(32.dp).clip(RoundedCornerShape(11.dp)).background(t.ink(0.06f)).clickable {
                draft = ""
                adding = true
            },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Rounded.Add, "添加", tint = t.ink(0.75f), modifier = Modifier.size(17.dp)) }
    }) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            if (list.isEmpty()) {
                EmptyNote("还没有源文件夹，点右上角 ＋ 添加")
            } else {
                GroupCard {
                    list.forEachIndexed { i, s0 ->
                        if (i > 0) RowDivider()
                        val isUpload = s0.kind == "upload"
                        Row(
                            Modifier.fillMaxWidth()
                                .clickable(enabled = s0.editable) {
                                    editing = s0
                                    draft = s0.path
                                }
                                .padding(horizontal = 14.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            RoundIcon(if (isUpload) Icons.Rounded.CloudUpload else Icons.Rounded.Folder)
                            Spacer(Modifier.width(11.dp))
                            Column(Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        s0.path,
                                        color = t.ink(0.9f),
                                        fontSize = 12.sp,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f, fill = false),
                                    )
                                    if (isUpload) {
                                        Spacer(Modifier.width(6.dp))
                                        Text(
                                            "上传目录",
                                            color = t.accent,
                                            fontSize = 9.5.sp,
                                            modifier = Modifier
                                                .clip(RoundedCornerShape(5.dp))
                                                .background(t.accent.copy(alpha = 0.14f))
                                                .padding(horizontal = 5.dp, vertical = 1.dp),
                                        )
                                    }
                                }
                                Spacer(Modifier.height(3.dp))
                                Text(
                                    buildString {
                                        append("${s0.count} 个视频")
                                        if (!s0.exists) append(" · 目录不存在")
                                        if (isUpload) append(" · 手机/网页上传都存到这里，可改路径不可删除")
                                    },
                                    color = if (s0.exists) t.muted2 else t.danger,
                                    fontSize = 10.sp,
                                )
                            }
                            if (s0.deletable) {
                                Box(
                                    Modifier.size(28.dp).clip(CircleShape).background(t.danger.copy(alpha = 0.12f))
                                        .clickable {
                                            scope.launch {
                                                runCatching { api.removeSource(s0.id) }
                                                load()
                                                onRefresh()
                                                onToast("已移除源目录")
                                            }
                                        },
                                    contentAlignment = Alignment.Center,
                                ) { Icon(Icons.Rounded.Delete, "移除", tint = t.danger, modifier = Modifier.size(14.dp)) }
                            } else {
                                Icon(Icons.Rounded.ChevronRight, null, tint = t.ink(0.3f), modifier = Modifier.size(16.dp))
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            GroupCard {
                SettingRow(Icons.Rounded.Search, "立即扫描", "扫描所有源文件夹（含上传目录）与各标签的目标文件夹", chevron = false) {
                    if (busy) return@SettingRow
                    busy = true
                    scope.launch {
                        try {
                            val taskId = api.scan()
                            while (true) {
                                val task = api.task(taskId)
                                if (task.status != "running") {
                                    onToast("扫描完成：${task.message.ifEmpty { "ok" }}")
                                    break
                                }
                                kotlinx.coroutines.delay(400)
                            }
                            load()
                            onRefresh()
                        } catch (e: Throwable) {
                            onToast("扫描失败：${e.message ?: ""}")
                        } finally {
                            busy = false
                        }
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }

    if (adding) {
        AlertDialog(
            onDismissRequest = { adding = false },
            title = { Text("添加源文件夹", color = t.text, fontSize = 15.sp) },
            text = {
                Column {
                    Text("填服务端上的绝对路径，例如 /volume1/videos", color = t.muted2, fontSize = 11.5.sp)
                    Spacer(Modifier.height(10.dp))
                    GlassField(draft, { draft = it }, placeholder = "/volume1/videos")
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    adding = false
                    scope.launch {
                        try {
                            api.addSource(draft.trim())
                            draft = ""
                            load()
                            onRefresh()
                            onToast("已添加源文件夹")
                        } catch (e: Throwable) {
                            onToast("添加失败：${e.message ?: ""}")
                        }
                    }
                }) { Text("保存", color = t.accent) }
            },
            dismissButton = { TextButton(onClick = { adding = false }) { Text("取消", color = t.muted) } },
            containerColor = t.panel,
        )
    }

    editing?.let { target ->
        val isUpload = target.kind == "upload"
        AlertDialog(
            onDismissRequest = { editing = null },
            title = { Text(if (isUpload) "修改上传目录" else "修改源文件夹", color = t.text, fontSize = 15.sp) },
            text = {
                Column {
                    Text(
                        if (isUpload) "手机端与网页端上传的文件都会存到这里；改完后新的上传落到新目录，已入库的视频不受影响。"
                        else "改成服务端上的另一个目录，之后扫描按新路径进行。",
                        color = t.muted2,
                        fontSize = 11.5.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    GlassField(draft, { draft = it }, placeholder = "/volume1/videos", keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val p = draft.trim()
                    if (p.isEmpty()) {
                        onToast("请填写目录路径")
                        return@TextButton
                    }
                    editing = null
                    scope.launch {
                        try {
                            api.updateSource(target.id, p)
                            load()
                            onRefresh()
                            onToast(if (isUpload) "上传目录已更新" else "源文件夹已更新")
                        } catch (e: Throwable) {
                            onToast("修改失败：${e.message ?: ""}")
                        }
                    }
                }) { Text("保存", color = t.accent) }
            },
            dismissButton = { TextButton(onClick = { editing = null }) { Text("取消", color = t.muted) } },
            containerColor = t.panel,
        )
    }
}

// ---------------- 标签管理 ----------------

private val TAG_COLORS = listOf(
    "#F4A259", "#EF5B7B", "#4CC9F0", "#9B8CFF", "#8D98A8", "#5FECAB", "#FFD166", "#FF7A85",
)

@Composable
private fun TagsPage(api: Api, tags: List<Tag>, onToast: (String) -> Unit, onRefresh: () -> Unit, onBack: () -> Unit) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var scanning by remember { mutableStateOf(false) }
    var scanTagId by remember { mutableStateOf<Int?>(null) }
    var editing by remember { mutableStateOf<Tag?>(null) }
    var creating by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var color by remember { mutableStateOf(TAG_COLORS[0]) }
    var dir by remember { mutableStateOf("") }

    /** 只扫这个标签的文件夹（服务端 tag_ids），整理过的视频就在那里 */
    fun scanOne(tag: Tag) {
        if (scanning) return
        scanning = true
        scanTagId = tag.id
        scope.launch {
            try {
                val taskId = api.scan(tagIds = listOf(tag.id))
                while (true) {
                    val task = api.task(taskId)
                    if (task.status != "running") {
                        onToast("「${tag.name}」扫描完成：${task.message.ifEmpty { "ok" }}")
                        break
                    }
                    kotlinx.coroutines.delay(400)
                }
                onRefresh()
            } catch (e: Throwable) {
                onToast("扫描失败：${e.message ?: ""}")
            } finally {
                scanning = false
                scanTagId = null
            }
        }
    }

    fun openEdit(tag: Tag) {
        editing = tag
        name = tag.name
        color = tag.color.ifEmpty { TAG_COLORS[0] }
        dir = tag.dirPath ?: ""
    }

    SubScaffold("标签管理", onBack, actions = {
        // 扫描：同时覆盖源文件夹与各标签的目标文件夹（整理过的视频就在后者里）
        Box(
            Modifier.size(32.dp).clip(RoundedCornerShape(11.dp)).background(t.ink(0.06f)).clickable {
                if (scanning) return@clickable
                scanning = true
                scope.launch {
                    try {
                        val taskId = api.scan()
                        while (true) {
                            val task = api.task(taskId)
                            if (task.status != "running") {
                                onToast("扫描完成：${task.message.ifEmpty { "ok" }}")
                                break
                            }
                            kotlinx.coroutines.delay(400)
                        }
                        onRefresh()
                    } catch (e: Throwable) {
                        onToast("扫描失败：${e.message ?: ""}")
                    } finally {
                        scanning = false
                    }
                }
            },
            contentAlignment = Alignment.Center,
        ) {
            if (scanning) {
                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 1.6.dp, color = t.accent)
            } else {
                Icon(Icons.Rounded.Refresh, "扫描源文件夹与标签文件夹", tint = t.ink(0.75f), modifier = Modifier.size(17.dp))
            }
        }
        Box(
            Modifier.size(32.dp).clip(RoundedCornerShape(11.dp)).background(t.ink(0.06f)).clickable {
                creating = true; name = ""; color = TAG_COLORS[0]; dir = ""
            },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Rounded.Add, "新建标签", tint = t.ink(0.75f), modifier = Modifier.size(17.dp)) }
    }) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            GroupCard {
                tags.forEachIndexed { i, tag ->
                    if (i > 0) RowDivider()
                    Row(
                        Modifier.fillMaxWidth().clickable { openEdit(tag) }.padding(horizontal = 14.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(10.dp).clip(CircleShape).background(hexColor(tag.color)))
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(tag.name, color = t.ink(0.9f), fontSize = 12.5.sp, fontWeight = FontWeight.Medium)
                            Spacer(Modifier.height(2.dp))
                            Text(
                                "目标：${tag.dirPath?.takeIf { it.isNotEmpty() } ?: "按规则自动（源目录/标签名）"}",
                                color = t.muted2,
                                fontSize = 10.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Text("${tag.count} 个", color = t.muted2, fontSize = 10.5.sp)
                        Spacer(Modifier.width(6.dp))
                        // 每个标签自己的扫描按钮：只扫这个标签对应的文件夹
                        Box(
                            Modifier
                                .size(28.dp)
                                .clip(RoundedCornerShape(10.dp))
                                .background(t.ink(0.05f))
                                .clickable {
                                    if (scanning) onToast("正在扫描，稍等一下") else scanOne(tag)
                                },
                            contentAlignment = Alignment.Center,
                        ) {
                            if (scanTagId == tag.id) {
                                CircularProgressIndicator(
                                    Modifier.size(13.dp),
                                    strokeWidth = 1.6.dp,
                                    color = t.accent,
                                )
                            } else {
                                Icon(
                                    Icons.Rounded.Refresh,
                                    contentDescription = "扫描「${tag.name}」的文件夹",
                                    tint = t.ink(0.55f),
                                    modifier = Modifier.size(15.dp),
                                )
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(10.dp))
            Text(
                "「扫描」会同时遍历源文件夹与上面每个标签的目标文件夹，整理过的视频也能重新入库。",
                color = t.muted2, fontSize = 10.5.sp, lineHeight = 15.sp,
                modifier = Modifier.padding(horizontal = 4.dp),
            )
            Spacer(Modifier.height(24.dp))
        }
    }

    val dialogOpen = editing != null || creating
    if (dialogOpen) {
        AlertDialog(
            onDismissRequest = { editing = null; creating = false },
            title = {
                Text(if (creating) "新建标签" else "编辑标签", color = t.text, fontSize = 15.sp)
            },
            text = {
                Column {
                    GlassField(name, { name = it }, placeholder = "标签名称")
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TAG_COLORS.forEach { c ->
                            Box(
                                Modifier.size(24.dp).clip(CircleShape).background(hexColor(c))
                                    .then(if (c == color) Modifier.border(2.dp, t.text, CircleShape) else Modifier)
                                    .clickable { color = c },
                            )
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    GlassField(
                            dir,
                            { dir = it },
                            placeholder = "目标文件夹（可留空）",
                            keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri,
                        )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "留空时按规则：全局根目录/标签名 → 首个源目录/标签名",
                        color = t.muted2,
                        fontSize = 10.sp,
                    )
                }
            },
            confirmButton = {
                // 顺序按用户要求：删除 / 保存 / 取消
                Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                    if (editing != null) {
                        TextButton(onClick = {
                            val target = editing!!
                            editing = null
                            scope.launch {
                                try {
                                    api.deleteTag(target.id)
                                    onRefresh()
                                    onToast("已删除标签")
                                } catch (e: Throwable) {
                                    onToast("删除失败：${e.message ?: ""}")
                                }
                            }
                        }) { Text("删除", color = t.danger) }
                    }
                    TextButton(onClick = {
                        val n = name.trim()
                        if (n.isEmpty()) {
                            onToast("请填写标签名称")
                            return@TextButton
                        }
                        val target = editing
                        editing = null
                        creating = false
                        scope.launch {
                            try {
                                if (target == null) {
                                    api.createTag(n, color, dir.trim())
                                } else {
                                    api.updateTag(target.id, n, color, dir.trim())
                                }
                                onRefresh()
                                onToast("已保存")
                            } catch (e: Throwable) {
                                onToast("保存失败：${e.message ?: ""}")
                            }
                        }
                    }) { Text("保存", color = t.accent) }
                    TextButton(onClick = { editing = null; creating = false }) {
                        Text("取消", color = t.muted)
                    }
                }
            },
            dismissButton = {},
            containerColor = t.panel,
        )
    }
}

// ---------------- 播放历史 ----------------

@Composable
private fun HistoryPage(api: Api, onToast: (String) -> Unit, onOpenVideo: (Int) -> Unit, onBack: () -> Unit) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<Video>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var selecting by remember { mutableStateOf(false) }
    val picked = remember { mutableStateListOf<Int>() }
    var confirmSingle by remember { mutableStateOf<Video?>(null) }

    fun load() {
        scope.launch {
            loading = true
            items = runCatching { api.history(100) }.getOrDefault(emptyList())
            loading = false
        }
    }

    fun deleteIds(ids: List<Int>) {
        scope.launch {
            ids.forEach { runCatching { api.deleteHistory(it) } }
            picked.clear()
            selecting = false
            load()
            // 删了播放记录 = 续播进度也一起清了，让播放页/视频库重新拉一次列表
            com.videosorter.app.data.LibraryHub.bump()
            onToast("已删除 ${ids.size} 条记录")
        }
    }

    LaunchedEffect(Unit) { load() }

    // 选择模式下先退出选择，再返回上一级
    BackHandler(enabled = selecting) {
        selecting = false
        picked.clear()
    }

    SubScaffold(
        "播放历史",
        onBack,
        actions = {
            TextButton(onClick = {
                selecting = !selecting
                picked.clear()
            }) { Text(if (selecting) "取消" else "选择", color = t.accent, fontSize = 12.sp) }
        },
    ) {
        Box(Modifier.fillMaxSize()) {
            when {
                loading -> EmptyNote("读取中…")
                items.isEmpty() -> EmptyNote("还没有播放记录")
                else -> LazyVerticalGrid(
                    columns = GridCells.Fixed(2),
                    contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 4.dp, bottom = 120.dp),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(items, key = { it.id }) { v ->
                        HistoryCard(
                            api = api,
                            v = v,
                            selecting = selecting,
                            picked = picked.contains(v.id),
                            onTap = {
                                if (selecting) {
                                    if (picked.contains(v.id)) picked.remove(v.id) else picked.add(v.id)
                                } else if (v.deleted) {
                                    onToast("该视频已被删除，无法播放")
                                } else {
                                    onOpenVideo(v.id)
                                }
                            },
                            onLong = { confirmSingle = v },
                        )
                    }
                }
            }

            if (selecting) {
                Row(
                    Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(18.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(t.panel2)
                        .border(1.dp, t.line, RoundedCornerShape(14.dp))
                        .padding(horizontal = 14.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("已选 ${picked.size}", color = t.ink(0.85f), fontSize = 12.sp, modifier = Modifier.weight(1f))
                    TextButton(onClick = {
                        if (picked.size == items.size) picked.clear() else {
                            picked.clear(); items.forEach { picked.add(it.id) }
                        }
                    }) { Text(if (picked.size == items.size) "取消全选" else "全选", color = t.accent, fontSize = 12.sp) }
                    TextButton(onClick = { if (picked.isNotEmpty()) deleteIds(picked.toList()) }) {
                        Text("删除", color = if (picked.isEmpty()) t.muted else t.danger, fontSize = 12.sp)
                    }
                }
            }
        }
    }

    val single = confirmSingle
    if (single != null) {
        AlertDialog(
            onDismissRequest = { confirmSingle = null },
            title = { Text("删除播放记录", color = t.text, fontSize = 15.sp) },
            text = { Text("只删除这条播放历史，视频文件不会动。", color = t.muted2, fontSize = 12.sp) },
            confirmButton = {
                TextButton(onClick = {
                    confirmSingle = null
                    deleteIds(listOf(single.id))
                }) { Text("删除", color = t.danger) }
            },
            dismissButton = { TextButton(onClick = { confirmSingle = null }) { Text("取消", color = t.muted) } },
            containerColor = t.panel,
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun HistoryCard(
    api: Api,
    v: Video,
    selecting: Boolean,
    picked: Boolean,
    onTap: () -> Unit,
    onLong: () -> Unit,
) {
    val t = tokens()
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.02f))))
            .border(1.dp, if (picked) t.accent.copy(alpha = 0.6f) else t.line, RoundedCornerShape(14.dp))
            .combinedClickable(onClick = onTap, onLongClick = onLong)
            .padding(9.dp),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(10.dp))) {
            if (v.deleted) {
                Box(Modifier.fillMaxSize().background(t.ink(0.06f)), contentAlignment = Alignment.Center) {
                    Text("视频已删除", color = t.muted2, fontSize = 11.sp)
                }
            } else {
                AsyncImage(
                    model = api.thumbUrl(v),
                    contentDescription = v.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize().background(gradientFor(v.id)),
                )
            }
            if (v.duration > 1) {
                Box(
                    Modifier.align(Alignment.BottomEnd).padding(5.dp)
                        .clip(RoundedCornerShape(5.dp))
                        .background(Color.Black.copy(alpha = 0.55f))
                        .padding(horizontal = 5.dp, vertical = 1.dp),
                ) { Text(fmtDuration(v.duration), color = Color.White, fontSize = 9.sp) }
            }
            val pos = v.position ?: 0.0
            if (pos > 1 && v.duration > 1) {
                Box(Modifier.align(Alignment.BottomStart).fillMaxWidth().height(2.5.dp).background(Color.Black.copy(alpha = 0.4f))) {
                    Box(
                        Modifier.fillMaxWidth((pos / v.duration).toFloat().coerceIn(0.02f, 1f)).height(2.5.dp)
                            .background(t.accent),
                    )
                }
            }
            if (selecting) {
                Box(
                    Modifier.align(Alignment.TopStart).padding(6.dp).size(20.dp).clip(CircleShape)
                        .background(if (picked) t.accent else Color.Black.copy(alpha = 0.45f))
                        .border(1.dp, Color.White.copy(alpha = 0.7f), CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    if (picked) Icon(Icons.Rounded.Check, null, tint = t.bg, modifier = Modifier.size(13.dp))
                }
            }
        }
        Spacer(Modifier.height(7.dp))
        Text(v.name, color = t.ink(0.88f), fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(3.dp))
        Text(
            buildString {
                val pos = v.position ?: 0.0
                if (pos > 1) append("看到 ${fmtDuration(pos)} · ") else append("未开始 · ")
                append(shortStamp(v.watchedAt))
            },
            color = t.muted2,
            fontSize = 9.5.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private fun shortStamp(iso: String?): String {
    if (iso.isNullOrEmpty()) return "-"
    return runCatching {
        iso.replace("T", " ").take(16).substring(5)
    }.getOrDefault(iso.take(16))
}

// ---------------- 缓存与储存 ----------------

@Composable
private fun CachePage(api: Api, onToast: (String) -> Unit, onBack: () -> Unit) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current
    var info by remember { mutableStateOf<CacheInfo?>(null) }
    var busy by remember { mutableStateOf(false) }

    // 本机播放缓存：上限存 Session 偏好，MediaCache 下次 init（进播放页 / 重启 App）才按新值重建
    var usedBytes by remember { mutableStateOf(MediaCache.sizeBytes()) }
    var activeMb by remember { mutableIntStateOf(MediaCache.activeMb()) }
    var savedMb by remember { mutableIntStateOf(MediaCache.savedMb(ctx)) }
    var pickLimit by remember { mutableStateOf(false) }

    // 进页面时如果缓存实例已被丢弃（改过上限还没进播放页），顺手按新上限建回来
    LaunchedEffect(Unit) {
        runCatching { MediaCache.buildIfNeeded(ctx) }
        usedBytes = MediaCache.sizeBytes()
        activeMb = MediaCache.activeMb()
        savedMb = MediaCache.savedMb(ctx)
    }

    fun load() {
        scope.launch { info = runCatching { api.cache() }.getOrNull() }
    }

    LaunchedEffect(Unit) { load() }

    fun clear(target: String) {
        if (busy) return
        busy = true
        scope.launch {
            try {
                val c = api.clearCache(target)
                info = c
                onToast("已清理，释放 ${sizeText(if (target == "all") info?.totalBytes ?: 0 else 0)}")
            } catch (e: Throwable) {
                onToast("清理失败：${e.message ?: ""}")
            } finally {
                busy = false
            }
        }
    }

    SubScaffold("缓存与储存", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            // ---- 本机播放缓存（手机自己的磁盘，和服务端缓存是两回事）----
            Text(
                "本机播放缓存",
                color = t.muted2,
                fontSize = 11.sp,
                modifier = Modifier.padding(start = 4.dp, bottom = 6.dp),
            )
            GroupCard {
                SettingRow(
                    Icons.Rounded.PlayCircle,
                    "已用 / 上限",
                    "已用 ${cacheBytesText(usedBytes)} / 上限 ${cacheMbText(activeMb)}",
                    chevron = false,
                )
                RowDivider()
                SettingRow(
                    Icons.Rounded.Storage,
                    "缓存上限",
                    if (savedMb != activeMb) {
                        "${cacheMbText(savedMb)} · 重新进入播放页后生效（当前 ${cacheMbText(activeMb)}）"
                    } else {
                        "${cacheMbText(activeMb)} · 越滑越顺，但会占手机空间"
                    },
                ) { pickLimit = true }
            }
            Spacer(Modifier.height(12.dp))
            Text(
                "服务端缓存",
                color = t.muted2,
                fontSize = 11.sp,
                modifier = Modifier.padding(start = 4.dp, bottom = 6.dp),
            )
            GroupCard {
                SettingRow(
                    Icons.Rounded.Storage,
                    "封面缓存",
                    info?.let { "${it.thumbs.count} 个文件 · ${sizeText(it.thumbs.bytes)}" } ?: "读取中…",
                    chevron = false,
                )
                RowDivider()
                SettingRow(
                    Icons.Rounded.Storage,
                    "转码缓存",
                    info?.let { "${it.hls.count} 个文件 · ${sizeText(it.hls.bytes)}" } ?: "读取中…",
                    chevron = false,
                )
                RowDivider()
                SettingRow(
                    Icons.Rounded.Info,
                    "合计占用",
                    info?.let { sizeText(it.totalBytes) } ?: "-",
                    chevron = false,
                )
            }
            Spacer(Modifier.height(12.dp))
            GroupCard {
                SettingRow(Icons.Rounded.Delete, "清理封面缓存", "下次打开会重新生成", chevron = false) { clear("thumbs") }
                RowDivider()
                SettingRow(Icons.Rounded.Delete, "清理转码缓存", "下次播放会重新转码", chevron = false) { clear("hls") }
                RowDivider()
                SettingRow(Icons.Rounded.Delete, "全部清理", danger = true, chevron = false) { clear("all") }
            }
            Spacer(Modifier.height(12.dp))
            GroupCard {
                SettingRow(
                    Icons.Rounded.Folder,
                    "数据目录",
                    info?.dataDir ?: "-",
                    chevron = false,
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }

    // 选缓存上限：写进本机偏好，同时把旧的缓存实例丢掉；等下次进播放页按新上限重建
    if (pickLimit) {
        AlertDialog(
            onDismissRequest = { pickLimit = false },
            title = { Text("缓存上限", color = t.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold) },
            text = {
                Column {
                    Text("播放过的视频会存在手机上，越滑越顺；上限越大占的空间越多。", color = t.muted, fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    CACHE_MB_OPTIONS.forEach { mb ->
                        val on = mb == savedMb
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (on) t.ink(0.07f) else Color.Transparent)
                                .clickable {
                                    MediaCache.setLimitMb(ctx, mb)
                                    savedMb = MediaCache.savedMb(ctx)
                                    activeMb = MediaCache.activeMb()
                                    usedBytes = MediaCache.sizeBytes()
                                    pickLimit = false
                                    onToast("已保存，重新进入播放页后生效")
                                }
                                .padding(horizontal = 10.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                cacheMbText(mb) + if (mb == 512) "（默认）" else "",
                                color = if (on) t.text else t.ink(0.78f),
                                fontSize = 12.5.sp,
                                fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.weight(1f),
                            )
                            if (on) Icon(Icons.Rounded.Check, contentDescription = null, tint = t.text, modifier = Modifier.size(15.dp))
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { pickLimit = false }) { Text("取消", color = t.muted) }
            },
            containerColor = t.panel,
        )
    }
}

// ---------------- 关于 ----------------

@Composable
private fun AboutPage(onBack: () -> Unit) {
    val t = tokens()
    val ctx = LocalContext.current
    SubScaffold("关于项目", onBack) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            GroupCard {
                Column(Modifier.padding(16.dp)) {
                    Text("视频整理", color = t.text, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(4.dp))
                    Text("VIDEO SORTER · 自托管视频分类整理", color = t.muted2, fontSize = 11.sp)
                    Spacer(Modifier.height(10.dp))
                    Text("版本 v${BuildConfig.VERSION_NAME}", color = t.muted, fontSize = 11.5.sp)
                }
            }
            Spacer(Modifier.height(12.dp))
            GroupCard {
                SettingRow(Icons.Rounded.Info, "项目主页", REPO_URL) {
                    runCatching {
                        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(REPO_URL)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    }
                }
                RowDivider()
                SettingRow(Icons.Rounded.Info, "问题反馈", "GitHub Issues", chevron = false) {
                    runCatching {
                        ctx.startActivity(
                            Intent(Intent.ACTION_VIEW, Uri.parse("$REPO_URL/issues"))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                    }
                }
                RowDivider()
                SettingRow(Icons.Rounded.Info, "开源许可", "MIT License", chevron = false)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

private fun fmtStampOf(ms: Long): String = SimpleDateFormat("MM-dd HH:mm", Locale.CHINA).format(Date(ms))

@Composable
private fun t2(): Color = tokens().muted2
