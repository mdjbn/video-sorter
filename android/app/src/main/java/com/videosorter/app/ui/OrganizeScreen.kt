package com.videosorter.app.ui

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.videosorter.app.data.Api
import com.videosorter.app.data.Plan
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private fun c(hex: String?): Color = runCatching {
    Color(android.graphics.Color.parseColor(hex ?: "#8d98a8"))
}.getOrDefault(Color(0xFF8D98A8))

@Composable
fun OrganizeScreen(api: Api, onToast: (String) -> Unit, onOrganized: () -> Unit) {
    var plan by remember { mutableStateOf<Plan?>(null) }
    var loading by remember { mutableStateOf(true) }
    var selected by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var touched by remember { mutableStateOf(false) }
    var expanded by remember { mutableStateOf<Set<Int>>(emptySet()) }
    var running by remember { mutableStateOf(false) }
    var percent by remember { mutableStateOf(0f) }
    var msg by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    suspend fun load(): Plan? = try {
        val p = api.preview()
        plan = p
        val ids = p.items.mapNotNull { it.tagId }.distinct().toSet()
        if (!touched) selected = ids
        p
    } catch (e: Exception) {
        onToast(e.message ?: "预览失败")
        null
    } finally {
        loading = false
    }

    LaunchedEffect(Unit) { load() }

    val groups = remember(plan) { plan?.items?.groupBy { it.tagId } ?: emptyMap() }
    val selItems = remember(plan, selected) {
        plan?.items?.filter { item -> item.tagId?.let { it in selected } == true } ?: emptyList()
    }
    val selBytes = selItems.sumOf { it.size }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("整理", fontSize = 19.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            TextButton(onClick = { scope.launch { load() } }) { Text("刷新") }
        }
        Text(
            "勾选要整理的标签，点开始整理会把这些视频移动到各自的目标文件夹。",
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))

        when {
            loading -> Box(Modifier.fillMaxWidth().height(120.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            groups.isEmpty() -> Box(Modifier.fillMaxWidth().height(160.dp), contentAlignment = Alignment.Center) {
                Text("没有待整理的视频\n先去播放页给视频打标签", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> {
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    groups.forEach { (tagId, items) ->
                        val first = items.first()
                        val on = tagId != null && tagId in selected
                        val open = tagId != null && tagId in expanded
                        item(key = "g${tagId}") {
                            Column(
                                Modifier
                                    .fillMaxWidth()
                                    .background(MaterialTheme.colorScheme.surface, RoundedCornerShape(14.dp))
                                    .padding(horizontal = 6.dp, vertical = 4.dp),
                            ) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Checkbox(
                                        checked = on,
                                        onCheckedChange = { ck ->
                                            touched = true
                                            val id = tagId ?: return@Checkbox
                                            selected = if (ck) selected + id else selected - id
                                        },
                                    )
                                    Box(Modifier.size(9.dp).background(c(first.tagColor), RoundedCornerShape(3.dp)))
                                    Spacer(Modifier.width(8.dp))
                                    Text(first.tagName ?: "未命名", fontSize = 14.sp, fontWeight = FontWeight.Medium)
                                    Text(" ${items.size} 个", fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    Spacer(Modifier.weight(1f))
                                    Text(
                                        "→ " + (first.dir.split("/").filter { it.isNotEmpty() }.takeLast(2).joinToString("/")),
                                        fontSize = 10.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    if (tagId != null) {
                                        Box(
                                            Modifier
                                                .size(28.dp)
                                                .clickable { expanded = if (open) expanded - tagId else expanded + tagId },
                                            contentAlignment = Alignment.Center,
                                        ) {
                                            Icon(
                                                if (open) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                                                contentDescription = null,
                                                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                                modifier = Modifier.size(18.dp),
                                            )
                                        }
                                    }
                                }
                                if (open) {
                                    items.forEach { it2 ->
                                        Row(
                                            Modifier
                                                .fillMaxWidth()
                                                .padding(start = 44.dp, end = 10.dp, bottom = 6.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Text(
                                                it2.name,
                                                fontSize = 12.sp,
                                                color = MaterialTheme.colorScheme.onSurface,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                                modifier = Modifier.weight(1f),
                                            )
                                            Text(
                                                if (it2.size < 1024 * 1024) "${it2.size / 1024} KB"
                                                else "%.1f MB".format(it2.size / 1024.0 / 1024.0),
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

                Spacer(Modifier.height(10.dp))
                if (running) {
                    Text(msg.ifBlank { "正在整理…" }, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    LinearProgressIndicator(progress = { percent }, modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                    Spacer(Modifier.height(12.dp))
                } else {
                    Button(
                        onClick = {
                            val ids = selected.toList()
                            if (ids.isEmpty()) return@Button
                            running = true
                            percent = 0f
                            msg = "准备移动 ${selItems.size} 个视频"
                            scope.launch {
                                try {
                                    val out = api.execute(ids)
                                    while (true) {
                                        val t = api.task(out.taskId)
                                        percent = (t.percent / 100.0).toFloat()
                                        msg = t.message.ifBlank { "正在整理…" }
                                        if (t.status != "running") {
                                            onToast(if (t.status == "done") "已整理 ${selItems.size} 个视频" else "整理失败：${t.message}")
                                            touched = false
                                            onOrganized()
                                            load()
                                            break
                                        }
                                        delay(400)
                                    }
                                } catch (e: Exception) {
                                    onToast(e.message ?: "整理失败")
                                } finally {
                                    running = false
                                }
                            }
                        },
                        enabled = selected.isNotEmpty(),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                    ) {
                        Text("开始整理 · ${selItems.size} 个 · ${selBytes / 1024 / 1024} MB")
                    }
                }
                Spacer(Modifier.height(14.dp))
            }
        }
    }
}
