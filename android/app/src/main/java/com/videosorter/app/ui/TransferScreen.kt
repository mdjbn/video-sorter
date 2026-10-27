
package com.videosorter.app.ui

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.TransferItem
import com.videosorter.app.data.TransferStore
import java.io.File
import com.videosorter.app.data.Transfers
import com.videosorter.app.data.UploadCandidate
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 进行中的传输任务（上传/下载共用），进度用 Compose 状态存。 */
data class TransferJob(
    val key: Long,
    val name: String,
    val kind: String,
    val pct: Float = 0f,
    val failed: String? = null,
)

/** 全局可见的传输进度表：列表页发起下载后，传输页能看到进度。 */
object TransferHub {
    val jobs = mutableStateListOf<TransferJob>()

    fun start(name: String, kind: String): Long {
        val key = System.currentTimeMillis() + jobs.size
        jobs.add(TransferJob(key, name, kind))
        return key
    }

    fun progress(key: Long, pct: Float) {
        val i = jobs.indexOfFirst { it.key == key }
        if (i >= 0) jobs[i] = jobs[i].copy(pct = pct.coerceIn(0f, 1f))
    }

    fun fail(key: Long, msg: String) {
        val i = jobs.indexOfFirst { it.key == key }
        if (i >= 0) jobs[i] = jobs[i].copy(failed = msg)
    }

    fun done(key: Long) {
        jobs.removeAll { it.key == key }
    }
}

private const val PREFS = "vs_transfer_cfg"
private const val KEY_TREE = "download_tree"

fun downloadTree(ctx: Context): Uri? =
    runCatching { ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_TREE, null) }
        .getOrNull()?.let { Uri.parse(it) }

fun saveDownloadTree(ctx: Context, uri: Uri) {
    runCatching {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_TREE, uri.toString()).apply()
    }
}

@Composable
fun TransferScreen(
    api: Api,
    onBack: () -> Unit,
    onToast: (String) -> Unit,
) {
    val t = tokens()
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()

    var tab by remember { mutableIntStateOf(0) }
    var uploadDir by remember { mutableStateOf("") }
    var treeUri by remember { mutableStateOf(downloadTree(ctx)) }
    var hist by remember { mutableStateOf(TransferStore.load(ctx)) }
    var editingPath by remember { mutableStateOf(false) }
    var pathDraft by remember { mutableStateOf("") }
    var selecting by remember { mutableStateOf(false) }
    val picked = remember { mutableStateListOf<TransferItem>() }
    var pendingDelete by remember { mutableStateOf<List<TransferItem>?>(null) }

    BackHandler(enabled = true) { onBack() }

    fun reloadHistory() {
        hist = TransferStore.load(ctx)
    }

    fun exitSelect() {
        selecting = false
        picked.clear()
    }

    fun treeLabel(uri: Uri?): String {
        if (uri == null) return "下载/VideoSorter（默认）"
        return runCatching {
            val id = DocumentsContract.getTreeDocumentId(uri)
            id.substringAfter(':', id).ifEmpty { id }
        }.getOrDefault("已选择自定义目录")
    }

    fun doDelete(items: List<TransferItem>, withFile: Boolean) {
        if (items.isEmpty()) return
        scope.launch {
            var files = 0
            if (withFile) {
                items.forEach { item ->
                    runCatching {
                        when {
                            item.kind == "up" && item.videoId > 0 -> {
                                api.deleteVideo(item.videoId, true); files++
                            }
                            item.uri.isNotEmpty() -> {
                                deleteLocalUri(ctx, item.uri); files++
                            }
                        }
                    }
                }
            }
            TransferStore.remove(ctx, items)
            exitSelect()
            pendingDelete = null
            reloadHistory()
            onToast(if (withFile) "已删除 ${items.size} 条记录 · $files 个文件" else "已删除 ${items.size} 条记录")
        }
    }

    // 进入页面 / 切换分段 / 有传输任务结束时都重新读一次历史（原来只在首次组合时读，导致记录不刷新）
    LaunchedEffect(tab) { reloadHistory() }
    LaunchedEffect(TransferHub.jobs.size) { reloadHistory() }

    LaunchedEffect(Unit) {
        runCatching { api.serverInfo().uploadDir }.getOrNull()?.let { uploadDir = it }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        uris.forEach { uri ->
            scope.launch {
                val (name, size) = Transfers.displayName(ctx.contentResolver, uri)
                val key = TransferHub.start(name, "up")
                try {
                    val vid = Transfers.upload(api, ctx.contentResolver, UploadCandidate(uri, name, size)) { p ->
                        TransferHub.progress(key, p)
                    }
                    TransferStore.add(
                        ctx,
                        TransferItem(
                            name = name,
                            time = System.currentTimeMillis(),
                            bytes = size,
                            ok = true,
                            kind = "up",
                            where = uploadDir,
                            videoId = vid,
                        )
                    )
                    reloadHistory()
                    onToast("已上传 $name")
                } catch (e: Throwable) {
                    TransferHub.fail(key, e.message ?: "上传失败")
                    TransferStore.add(
                        ctx,
                        TransferItem(
                            name = name,
                            time = System.currentTimeMillis(),
                            bytes = size,
                            ok = false,
                            kind = "up",
                            where = uploadDir,
                            msg = e.message ?: ""
                        )
                    )
                    reloadHistory()
                    onToast("上传失败：${e.message ?: ""}")
                } finally {
                    TransferHub.done(key)
                }
            }
        }
    }

    val treePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            runCatching {
                ctx.contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )
            }
            saveDownloadTree(ctx, uri)
            treeUri = uri
            onToast("下载目录：${treeLabel(uri)}")
        }
    }

    Box(Modifier.fillMaxSize().background(t.bg)) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            // 页头
            Row(
                Modifier.fillMaxWidth().padding(start = 12.dp, end = 18.dp, top = 6.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    Modifier.size(32.dp).clip(RoundedCornerShape(11.dp))
                        .background(t.ink(0.06f)).border(1.dp, t.line2, RoundedCornerShape(11.dp))
                        .clickable { onBack() },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, "返回", tint = t.ink(0.8f), modifier = Modifier.size(17.dp))
                }
                Text("传输", fontSize = 21.sp, fontWeight = FontWeight.Bold, color = t.text)
                if (selecting) {
                    Spacer(Modifier.weight(1f))
                    Text("已选 ${picked.size}", color = t.muted2, fontSize = 11.5.sp)
                    Spacer(Modifier.width(6.dp))
                    TextButton(onClick = { exitSelect() }) { Text("取消", color = t.muted, fontSize = 12.sp) }
                }
            }

            // 分段
            Row(
                Modifier.padding(horizontal = 18.dp).fillMaxWidth()
                    .clip(RoundedCornerShape(13.dp))
                    .background(t.ink(0.05f))
                    .padding(4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                SegButton("上传到服务器", tab == 0, Modifier.weight(1f)) { exitSelect(); tab = 0 }
                SegButton("下载到手机", tab == 1, Modifier.weight(1f)) { exitSelect(); tab = 1 }
            }

            Column(Modifier.fillMaxWidth().weight(1f).verticalScroll(rememberScrollState()).padding(18.dp)) {
                if (tab == 0) {
                    GroupCard {
                        SettingRow(
                            icon = Icons.Rounded.Folder,
                            title = "上传路径",
                            subtitle = uploadDir.ifEmpty { "服务端默认目录" },
                            onClick = {
                                pathDraft = uploadDir
                                editingPath = true
                            },
                        )
                    }

                    val upJobs = TransferHub.jobs.filter { it.kind == "up" }
                    if (upJobs.isNotEmpty()) {
                        SectionLabel("正在上传")
                        GroupCard {
                            upJobs.forEachIndexed { i, job ->
                                if (i > 0) RowDivider()
                                JobRow(job)
                            }
                        }
                    }

                    SectionLabel("上传历史")
                    val upHist = hist.filter { it.kind == "up" }
                    if (upHist.isEmpty()) {
                        HistEmpty("还没有上传记录，点右下角 ＋ 选择视频")
                    } else {
                        GroupCard {
                            upHist.forEachIndexed { i, item ->
                                if (i > 0) RowDivider()
                                HistRow(
                                    item,
                                    selected = item in picked,
                                    selecting = selecting,
                                    onLong = {
                                        if (!selecting) { selecting = true; picked.clear(); picked.add(item) }
                                    },
                                    onToggle = { if (item in picked) picked.remove(item) else picked.add(item) },
                                    onDelete = { pendingDelete = listOf(item) },
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(96.dp))
                } else {
                    GroupCard {
                        SettingRow(
                            icon = Icons.Rounded.Folder,
                            title = "下载路径",
                            subtitle = if (treeUri == null) "下载/VideoSorter（默认）" else "已选：" + treeLabel(treeUri),
                            onClick = { treePicker.launch(null) },
                        )
                        RowDivider()
                        SettingRow(
                            icon = Icons.Rounded.Folder,
                            title = "恢复默认目录",
                            subtitle = "保存到系统的「下载/VideoSorter」",
                            onClick = {
                                runCatching {
                                    ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY_TREE).apply()
                                }
                                treeUri = null
                                onToast("已恢复默认下载目录")
                            },
                        )
                    }

                    val downJobs = TransferHub.jobs.filter { it.kind == "down" }
                    if (downJobs.isNotEmpty()) {
                        SectionLabel("正在下载")
                        GroupCard {
                            downJobs.forEachIndexed { i, job ->
                                if (i > 0) RowDivider()
                                JobRow(job)
                            }
                        }
                    }

                    SectionLabel("下载历史")
                    val downHist = hist.filter { it.kind == "down" }
                    if (downHist.isEmpty()) {
                        HistEmpty("还没有下载记录，在列表页长按视频选「下载到手机」")
                    } else {
                        GroupCard {
                            downHist.forEachIndexed { i, item ->
                                if (i > 0) RowDivider()
                                HistRow(
                                    item,
                                    selected = item in picked,
                                    selecting = selecting,
                                    onClick = if (selecting) null else ({ openDownloaded(ctx, item, onToast) }),
                                    onLong = {
                                        if (!selecting) { selecting = true; picked.clear(); picked.add(item) }
                                    },
                                    onToggle = { if (item in picked) picked.remove(item) else picked.add(item) },
                                    onDelete = { pendingDelete = listOf(item) },
                                )
                            }
                        }
                    }
                    Spacer(Modifier.height(40.dp))
                }
            }
        }

        // 上传页右下角圆形 ＋
        if (tab == 0) {
            Box(
                Modifier.align(Alignment.BottomEnd)
                    .padding(end = 20.dp, bottom = 26.dp)
                    .size(58.dp)
                    .background(
                        Brush.linearGradient(listOf(t.accent, t.accent2)),
                        CircleShape,
                    )
                    .clickable { picker.launch("video/*") },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.Add, "选择视频上传", tint = t.bg, modifier = Modifier.size(30.dp))
            }
        }

        // 多选删除条
        if (selecting) {
            Row(
                Modifier.align(Alignment.BottomCenter)
                    .padding(start = 18.dp, end = 18.dp, bottom = 26.dp)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .background(t.panel)
                    .border(1.dp, t.line, RoundedCornerShape(16.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("已选 ${picked.size} 条", color = t.ink(0.8f), fontSize = 12.sp, modifier = Modifier.weight(1f))
                TextButton(onClick = {
                    val all = if (tab == 0) hist.filter { it.kind == "up" } else hist.filter { it.kind == "down" }
                    if (picked.size == all.size) picked.clear() else { picked.clear(); picked.addAll(all) }
                }) { Text("全选", color = t.muted, fontSize = 12.sp) }
                TextButton(enabled = picked.isNotEmpty(), onClick = { pendingDelete = picked.toList() }) {
                    Text("删除", color = if (picked.isEmpty()) t.muted2 else t.danger, fontSize = 12.sp)
                }
            }
        }
    }

    pendingDelete?.let { items ->
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text("删除 ${items.size} 条记录", color = t.text, fontSize = 15.sp) },
            text = {
                Text(
                    "「仅删除记录」只清空传输历史；「同时删除文件」还会" +
                        (if (items.all { it.kind == "up" }) "从服务器删除对应视频（不可恢复）。" else "删除手机上的文件。"),
                    color = t.muted2,
                    fontSize = 11.5.sp,
                )
            },
            confirmButton = {
                TextButton(onClick = { doDelete(items, true) }) { Text("同时删除文件", color = t.danger) }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { pendingDelete = null }) { Text("取消", color = t.muted) }
                    TextButton(onClick = { doDelete(items, false) }) { Text("仅删除记录", color = t.accent) }
                }
            },
            containerColor = t.panel,
        )
    }

    if (editingPath) {
        AlertDialog(
            onDismissRequest = { editingPath = false },
            title = { Text("上传路径", color = t.text, fontSize = 15.sp) },
            text = {
                Column {
                    Text("服务端保存上传文件的目录；留空则用默认目录。", color = t.muted2, fontSize = 11.5.sp)
                    Spacer(Modifier.height(10.dp))
                    GlassField(
                        pathDraft,
                        { pathDraft = it },
                        placeholder = "例如 /volume1/videos/上传",
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri,
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    editingPath = false
                    scope.launch {
                        try {
                            val want = pathDraft.trim()
                            api.setUploadDir(want)
                            val real = runCatching { api.serverInfo().uploadDir }.getOrDefault(want)
                            uploadDir = real
                            onToast(if (real.isEmpty()) "上传路径已保存（服务端默认目录）" else "上传路径已保存：$real")
                        } catch (e: Throwable) {
                            onToast("保存失败：${e.message ?: ""}")
                        }
                    }
                }) { Text("保存", color = t.accent) }
            },
            dismissButton = {
                TextButton(onClick = { editingPath = false }) { Text("取消", color = t.muted) }
            },
            containerColor = t.panel,
        )
    }
}

@Composable
private fun JobRow(job: TransferJob) {
    val t = tokens()
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (job.kind == "up") Icons.Rounded.Upload else Icons.Rounded.Download,
                null,
                tint = if (job.kind == "up") t.accent else t.muted,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(job.name, color = t.ink(0.88f), fontSize = 12.5.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            val pct = (job.pct * 100).toInt()
            Text(
                job.failed?.let { "失败" } ?: "$pct%",
                color = if (job.failed != null) t.danger else t.muted2,
                fontSize = 11.sp,
            )
        }
        Spacer(Modifier.height(7.dp))
        GlassProgress(job.pct, job.failed != null)
        if (job.failed != null) {
            Text(job.failed, color = t.danger, fontSize = 10.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun GlassProgress(pct: Float, failed: Boolean) {
    val t = tokens()
    Box(
        Modifier.fillMaxWidth().height(3.dp).clip(RoundedCornerShape(3.dp)).background(t.ink(0.12f))
    ) {
        Box(
            Modifier.fillMaxWidth(if (failed) 1f else pct.coerceIn(0f, 1f)).height(3.dp)
                .clip(RoundedCornerShape(3.dp))
                .background(
                    if (failed) androidx.compose.ui.graphics.SolidColor(t.danger)
                    else Brush.horizontalGradient(listOf(t.accent2, t.accent))
                )
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun HistRow(
    item: TransferItem,
    selected: Boolean = false,
    selecting: Boolean = false,
    onClick: (() -> Unit)? = null,
    onLong: (() -> Unit)? = null,
    onToggle: (() -> Unit)? = null,
    onDelete: (() -> Unit)? = null,
) {
    val t = tokens()
    Row(
        Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = { if (selecting) onToggle?.invoke() else onClick?.invoke() },
                onLongClick = { onLong?.invoke() },
            )
            .padding(start = 14.dp, end = 10.dp, top = 12.dp, bottom = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(26.dp).clip(RoundedCornerShape(8.dp))
                .background(if (item.kind == "up") t.accentDim else t.ink(0.06f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (item.kind == "up") Icons.Rounded.Upload else Icons.Rounded.Download,
                null,
                tint = if (item.ok) (if (item.kind == "up") t.accent else t.ink(0.7f)) else t.danger,
                modifier = Modifier.size(14.dp),
            )
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(
                item.name,
                color = t.ink(0.88f),
                fontSize = 12.5.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(3.dp))
            Text(
                buildString {
                    append(sizeText(item.bytes))
                    append(" · ")
                    append(fmtStamp(item.time))
                    if (item.where.isNotEmpty()) {
                        append(" · ")
                        append(item.where.takeLast(28))
                    }
                    if (!item.ok && item.msg.isNotEmpty()) {
                        append(" · ")
                        append(item.msg.take(24))
                    }
                },
                color = if (item.ok) t.muted2 else t.danger,
                fontSize = 10.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(8.dp))
        // 状态打钩向左移
        if (item.ok) {
            Icon(Icons.Rounded.Check, null, tint = t.accent, modifier = Modifier.size(14.dp))
        }
        if (selecting) {
            Spacer(Modifier.width(10.dp))
            Box(
                Modifier.size(20.dp).clip(CircleShape)
                    .background(if (selected) t.accent else t.ink(0.06f))
                    .border(1.dp, if (selected) t.accent else t.line2, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                if (selected) {
                    Icon(Icons.Rounded.Check, null, tint = t.bg, modifier = Modifier.size(13.dp))
                }
            }
        } else if (onDelete != null) {
            Spacer(Modifier.width(6.dp))
            Box(
                Modifier.size(30.dp).clip(RoundedCornerShape(10.dp))
                    .background(t.ink(0.05f))
                    .clickable { onDelete() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Rounded.Delete, "删除记录", tint = t.muted, modifier = Modifier.size(15.dp))
            }
        }
    }
}

private fun fmtStamp(ms: Long): String {
    if (ms <= 0L) return ""
    val cal = java.util.Calendar.getInstance().apply { timeInMillis = ms }
    return String.format(
        "%02d-%02d %02d:%02d",
        cal.get(java.util.Calendar.MONTH) + 1,
        cal.get(java.util.Calendar.DAY_OF_MONTH),
        cal.get(java.util.Calendar.HOUR_OF_DAY),
        cal.get(java.util.Calendar.MINUTE),
    )
}

private fun deleteLocalUri(ctx: Context, uriString: String) {
    val uri = Uri.parse(uriString)
    val cr = ctx.contentResolver
    val ok = runCatching { DocumentsContract.deleteDocument(cr, uri) }.getOrDefault(false) ||
        runCatching { cr.delete(uri, null, null) > 0 }.getOrDefault(false)
    if (!ok) {
        uri.path?.let { p -> runCatching { File(p).delete() } }
    }
}

@Composable
private fun HistEmpty(text: String) {
    val t = tokens()
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, color = t.muted2, fontSize = 11.5.sp)
    }
}

// ---------- Compose 兼容小助手（避免到处 import 运行时 API） ----------


@Composable
private fun SegButton(label: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = tokens()
    Box(
        modifier
            .height(32.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) t.ink(0.09f) else androidx.compose.ui.graphics.Color.Transparent)
            .clickable { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (on) t.ink(0.9f) else t.muted, fontSize = 12.sp,
            fontWeight = if (on) FontWeight.Medium else FontWeight.Normal)
    }
}


/** 点下载历史 → 用系统播放器打开已下载的视频。 */
private fun openDownloaded(
    ctx: Context,
    item: TransferItem,
    onToast: (String) -> Unit,
) {
    if (!item.ok) {
        onToast("这条记录没有下载成功")
        return
    }
    val uri = item.uri.takeIf { it.isNotEmpty() }?.let { runCatching { Uri.parse(it) }.getOrNull() }
    if (uri == null) {
        onToast("找不到文件（可能是旧记录，或文件已被移动）")
        return
    }
    val mime = when {
        item.name.endsWith(".mkv", true) -> "video/x-matroska"
        item.name.endsWith(".webm", true) -> "video/webm"
        item.name.endsWith(".mov", true) -> "video/quicktime"
        item.name.endsWith(".avi", true) -> "video/x-msvideo"
        else -> "video/mp4"
    }
    val intent = Intent(Intent.ACTION_VIEW)
        .setDataAndType(uri, mime)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { ctx.startActivity(intent) }
        .onFailure { onToast("没有可以打开这个视频的应用") }
}
