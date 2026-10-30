package com.videosorter.app.ui

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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Undo
import androidx.compose.material.icons.rounded.WarningAmber
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.ApiException
import com.videosorter.app.data.BatchRec
import com.videosorter.app.data.PlanItem
import kotlinx.coroutines.delay

private data class OrgGroup(
    val tagId: Int,
    val name: String,
    val color: String,
    val dir: String,
    val items: List<PlanItem>,
)

@Composable
fun OrganizeScreen(
    api: Api,
    onToast: (String) -> Unit,
    onOrganized: () -> Unit,
) {
    val t = tokens()
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<PlanItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var err by remember { mutableStateOf<String?>(null) }
    var selected by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var touched by remember { mutableStateOf(false) }
    var running by remember { mutableStateOf(false) }
    var pct by remember { mutableFloatStateOf(0f) }
    var records by remember { mutableStateOf<List<BatchRec>>(emptyList()) }
    // 「上次整理失败 N 个」区块：只存在本页内存里，点「知道了」或离开页面就清掉
    val failState = rememberOrganizeFailState()

    val groups = remember(items) {
        items.filter { it.tagId != null }.groupBy { it.tagId!! }.map { (tagId, list) ->
            val first = list.first()
            OrgGroup(
                tagId = tagId,
                name = first.tagName ?: "未命名",
                color = first.tagColor ?: "",
                dir = first.dir,
                items = list,
            )
        }
    }

    suspend fun loadPlan() {
        loading = true
        try {
            val plan = api.preview()
            items = plan.items
            if (!touched) selected = plan.items.mapNotNull { it.tagId }.toSet()
            records = runCatching { api.records() }.getOrDefault(emptyList())
            err = null
        } catch (e: Exception) {
            err = e.message ?: "加载失败"
        } finally {
            loading = false
        }
    }

    LaunchedEffect(Unit) { loadPlan() }

    val chosen = items.filter { it.tagId in selected }
    val chosenBytes = chosen.sumOf { it.size }

    suspend fun run() {
        if (running || chosen.isEmpty()) return
        running = true
        pct = 0f
        try {
            // 目标目录不可写时后端在 execute 就 400（detail 带「不可写：/路径」），
            // 这时还没建任务，直接把它当成「全部失败」展示，不要再弹一句没头没尾的错误
            val out = try {
                api.execute(chosen.mapNotNull { it.tagId }.distinct())
            } catch (e: ApiException) {
                if (e.code == 400 && isUnwritableError(e.message)) {
                    val target = unwritableTarget(e.message)
                    failState.rememberSkipped(chosen.size)
                    onToast("${chosen.size} 个被跳过：目标目录不可写" + if (target.isNotEmpty()) "（$target）" else "")
                    return
                }
                throw e
            }
            // 目标目录不可写被跳过的，先记下来，任务结束后一并说清楚
            if (out.skipped > 0) failState.rememberSkipped(out.skipped)
            while (true) {
                val task = api.task(out.taskId)
                pct = (task.percent.coerceIn(0.0, 100.0) / 100.0).toFloat()
                if (task.status != "running") {
                    val summary = summarizeOrganize(
                        status = task.status,
                        moved = task.moved,
                        failed = task.failedCount,
                        fails = task.failedItems,
                        error = if (task.error.isNotBlank()) task.error else task.message,
                        skipped = out.skipped,
                    )
                    onToast(summary.text)
                    // 有失败（或全失败）就把明细留在页面上：toast 放不下「文件名 · 原因」
                    if (summary.partial || !summary.ok) failState.update(summary)
                    // 部分成功也要刷新列表：失败的那些还在待整理里
                    if (summary.moved > 0) {
                        onOrganized()
                        touched = false
                        loadPlan()
                    } else if (summary.failed > 0) {
                        loadPlan()
                    }
                    break
                }
                delay(400)
            }
        } catch (e: ApiException) {
            // 后端把原因写在 detail 里（如「没有需要整理的视频（需要先打标签）」）
            failState.updateFromError(e.message)
            onToast(e.message ?: "整理失败")
        } catch (e: Exception) {
            onToast(e.message ?: "整理失败")
        } finally {
            running = false
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(start = 18.dp, end = 18.dp, top = 14.dp, bottom = 12.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                Column {
                    Text("整理", color = t.text, fontSize = 21.sp, fontWeight = FontWeight.Bold)
                    Text("把打好标签的视频移动到标签对应的文件夹", color = t.muted2, fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp))
                }
            }

            LazyColumn(
                contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 6.dp, bottom = 170.dp),
                verticalArrangement = Arrangement.spacedBy(9.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(9.dp), modifier = Modifier.padding(bottom = 6.dp)) {
                        SmallStat("待整理", "${items.size}", Modifier.weight(1f))
                        SmallStat("文件夹", "${groups.size}", Modifier.weight(1f))
                        SmallStat("总大小", sizeText(items.sumOf { it.size }), Modifier.weight(1f))
                    }
                }
                if (failState.visible()) {
                    item(key = "organize-failed") {
                        FailBlock(state = failState, onDismiss = { failState.clear() })
                    }
                }
                when {
                    err != null -> item { Text(err!!, color = t.danger, fontSize = 12.sp) }
                    loading -> item { Text("加载中…", color = t.muted, fontSize = 12.sp) }
                    items.isEmpty() -> item {
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .background(t.ink(0.04f))
                                .border(1.dp, t.line, RoundedCornerShape(14.dp))
                                .padding(vertical = 26.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Icon(Icons.Rounded.FolderOpen, contentDescription = null, tint = t.muted2, modifier = Modifier.size(26.dp))
                            Spacer(Modifier.height(10.dp))
                            Text("没有需要整理的视频", color = t.ink(0.8f), fontSize = 13.sp)
                            Spacer(Modifier.height(4.dp))
                            Text("先去播放页给视频打标签", color = t.muted2, fontSize = 11.sp)
                        }
                    }

                    else -> items(groups, key = { it.tagId }) { g ->
                        val on = g.tagId in selected
                        val c = hexColor(g.color)
                        Column(
                            Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.022f))))
                                .border(1.dp, if (on) t.accent.copy(alpha = 0.35f) else t.line, RoundedCornerShape(14.dp))
                                .clickable {
                                    touched = true
                                    selected = if (on) selected - g.tagId else selected + g.tagId
                                }
                                .padding(12.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                Box(
                                    Modifier
                                        .size(19.dp)
                                        .clip(RoundedCornerShape(6.dp))
                                        .background(if (on) t.accent else Color.Transparent)
                                        .border(1.5.dp, if (on) t.accent else t.ink(0.3f), RoundedCornerShape(6.dp)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    if (on) Text("✓", color = Color(0xFF04160D), fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                }
                                Box(
                                    Modifier
                                        .size(28.dp)
                                        .clip(RoundedCornerShape(9.dp))
                                        .background(c.copy(alpha = 0.16f)),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Box(Modifier.size(8.dp).clip(RoundedCornerShape(3.dp)).background(c))
                                }
                                Column(Modifier.weight(1f)) {
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Text(g.name, color = t.text, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold)
                                        Spacer(Modifier.weight(1f))
                                        Text("${g.items.size} 个", color = t.muted2, fontSize = 11.sp)
                                    }
                                    Text(
                                        tailPath(g.dir),
                                        color = t.muted2,
                                        fontSize = 9.5.sp,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.padding(top = 3.dp),
                                    )
                                }
                            }
                            g.items.take(3).forEach { it ->
                                Text(
                                    "· ${it.name}",
                                    color = t.ink(0.5f),
                                    fontSize = 10.sp,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.padding(start = 58.dp, top = 5.dp),
                                )
                            }
                            if (g.items.size > 3) {
                                Text("· 还有 ${g.items.size - 3} 个…", color = t.muted2, fontSize = 10.sp, modifier = Modifier.padding(start = 58.dp, top = 4.dp))
                            }
                        }
                    }
                }
                if (records.isNotEmpty()) {
                    item {
                        Text(
                            "最近整理",
                            color = t.muted2,
                            fontSize = 11.sp,
                            modifier = Modifier.padding(top = 10.dp, bottom = 2.dp, start = 2.dp),
                        )
                    }
                    items(records, key = { "rec-${it.id}" }) { r ->
                        RecRow(
                            rec = r,
                            onUndo = {
                                scope.launch {
                                    runCatching { api.undo(r.id) }
                                        .onSuccess {
                                            onToast("已撤销 · 搬回 ${r.files} 个视频")
                                            onOrganized()
                                            touched = false
                                            loadPlan()
                                        }
                                        .onFailure { onToast(it.message ?: "撤销失败") }
                                }
                            },
                        )
                    }
                }
            }
        }

        // CTA 底下垫一层背景渐变，滚动内容从它下面淡出（否则文字会跟列表糊在一起）
        Box(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .height(230.dp)
                .background(
                    Brush.verticalGradient(
                        0f to Color.Transparent,
                        0.34f to t.bg.copy(alpha = 0.78f),
                        0.62f to t.bg.copy(alpha = 0.98f),
                        1f to t.bg,
                    )
                )
        )

        // 底部 CTA
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(start = 18.dp, end = 18.dp, bottom = 92.dp)
        ) {
            if (chosen.isNotEmpty()) {
                Text(
                    "将移动 ${chosen.size} 个视频 · ${sizeText(chosenBytes)}",
                    color = t.muted2,
                    fontSize = 10.5.sp,
                    modifier = Modifier.padding(bottom = 8.dp, start = 2.dp),
                )
            }
            GradientButton(
                text = when {
                    running -> "正在整理… ${(pct * 100).toInt()}%"
                    chosen.isEmpty() -> "选择要整理的标签"
                    else -> "开始整理 · ${chosen.size} 个"
                },
                onClick = { if (!running) scope.launch { run() } },
                enabled = chosen.isNotEmpty() && !running,
            )
        }

        if (running) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color(0xB804060A))
                    .clickable(enabled = false) {},
                contentAlignment = Alignment.Center,
            ) {
                Column(
                    Modifier
                        .padding(horizontal = 40.dp)
                        .clip(RoundedCornerShape(22.dp))
                        .background(t.panel)
                        .border(1.dp, t.line2, RoundedCornerShape(22.dp))
                        .padding(horizontal = 22.dp, vertical = 22.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("正在整理", color = t.text, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(16.dp))
                    LinearProgressIndicator(
                        progress = { pct },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(6.dp)
                            .clip(RoundedCornerShape(4.dp)),
                        color = t.accent,
                        trackColor = t.ink(0.08f),
                    )
                    Spacer(Modifier.height(10.dp))
                    Text("${(pct * 100).toInt()}% · 正在移动文件", color = t.muted2, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun RecRow(rec: BatchRec, onUndo: () -> Unit) {
    val t = tokens()
    val dirs = rec.dirs.takeLast(2).joinToString(" / ") { it.trimEnd('/').substringAfterLast('/') }
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(t.ink(0.035f))
            .border(1.dp, t.line, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                "整理 ${rec.files} 个${if (dirs.isNotEmpty()) " → $dirs" else ""}",
                color = t.ink(0.82f),
                fontSize = 11.5.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                "${fmtBatchTime(rec.createdAt)}${if (rec.undone != 0) " · 已撤销" else ""}",
                color = t.muted2,
                fontSize = 10.sp,
                modifier = Modifier.padding(top = 2.dp),
            )
        }
        if (rec.undone == 0 && rec.files > 0) {
            Row(
                Modifier
                    .height(26.dp)
                    .clip(RoundedCornerShape(8.dp))
                    .background(t.ink(0.05f))
                    .border(1.dp, t.line2, RoundedCornerShape(8.dp))
                    .clickable(onClick = onUndo)
                    .padding(horizontal = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Icon(Icons.Rounded.Undo, contentDescription = null, tint = t.muted, modifier = Modifier.size(12.dp))
                Text("撤销", color = t.ink(0.75f), fontSize = 11.sp)
            }
        }
    }
}

/** 后端 created_at 形如 2026-10-27T02:15:03 → 10-27 02:15 */
private fun fmtBatchTime(raw: String): String {
    if (raw.length < 16) return raw
    return raw.substring(5, 10) + " " + raw.substring(11, 16)
}

@Composable
private fun SmallStat(label: String, value: String, modifier: Modifier = Modifier) {
    val t = tokens()
    Column(
        modifier
            .clip(RoundedCornerShape(14.dp))
            .background(Brush.linearGradient(listOf(t.ink(0.05f), t.ink(0.02f))))
            .border(1.dp, t.line, RoundedCornerShape(14.dp))
            .padding(horizontal = 12.dp, vertical = 11.dp),
    ) {
        Text(value, color = t.text, fontSize = 17.sp, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(label, color = t.muted2, fontSize = 9.5.sp, modifier = Modifier.padding(top = 3.dp))
    }
}

/** 目标目录只显示尾部两段，例：…/整理/旅行 */
private fun tailPath(dir: String): String {
    val parts = dir.trimEnd('/').split('/').filter { it.isNotEmpty() }
    return if (parts.size <= 2) dir else "…/" + parts.takeLast(2).joinToString("/")
}
/**
 * 「上次整理失败 N 个」区块：列出最多 8 条「文件名 · 原因」+「以及另外 N 条」，
 * 右上角可折叠，「知道了」把整块清掉（状态只在本页 remember 里，不落盘）。
 */
@Composable
private fun FailBlock(state: OrganizeFailState, onDismiss: () -> Unit) {
    val t = tokens()
    val s = state.summary ?: return
    val head = when {
        s.skipped > 0 && s.failed == 0 -> "${s.skipped} 个被跳过：目标目录不可写"
        s.skipped > 0 -> "${failListText(s.failed)} · ${s.skipped} 个被跳过：目标目录不可写"
        else -> failListText(s.failed)
    }
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(t.danger.copy(alpha = 0.10f))
            .border(1.dp, t.danger.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
            .padding(horizontal = 12.dp, vertical = 11.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Rounded.WarningAmber, contentDescription = null, tint = t.danger, modifier = Modifier.size(15.dp))
            Text(head, color = t.danger, fontSize = 12.5.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Box(
                Modifier
                    .clip(RoundedCornerShape(7.dp))
                    .clickable { state.expanded = !state.expanded }
                    .padding(horizontal = 6.dp, vertical = 3.dp),
            ) {
                Text(if (state.expanded) "收起" else "展开", color = t.muted, fontSize = 10.5.sp)
            }
        }
        if (state.expanded) {
            if (s.fails.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                s.fails.take(MAX_SHOWN).forEach { f ->
                    Text(
                        if (f.name.isNotEmpty()) "${f.name} · ${f.reason}" else f.reason,
                        color = t.ink(0.78f),
                        fontSize = 10.5.sp,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 3.dp),
                    )
                }
                val more = s.more + (s.fails.size - MAX_SHOWN).coerceAtLeast(0)
                if (more > 0) {
                    Text("以及另外 $more 条", color = t.muted2, fontSize = 10.5.sp, modifier = Modifier.padding(top = 5.dp))
                }
            } else {
                Spacer(Modifier.height(6.dp))
                Text(
                    "常见原因：目标目录不可写、磁盘已满、源文件已被移动。可到「设置 → 源文件夹」检查目录权限。",
                    color = t.muted2,
                    fontSize = 10.5.sp,
                )
            }
            Spacer(Modifier.height(9.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                Box(
                    Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .background(t.ink(0.06f))
                        .border(1.dp, t.line2, RoundedCornerShape(8.dp))
                        .clickable { onDismiss() }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                ) {
                    Text("知道了", color = t.ink(0.8f), fontSize = 11.sp)
                }
            }
        }
    }
}
