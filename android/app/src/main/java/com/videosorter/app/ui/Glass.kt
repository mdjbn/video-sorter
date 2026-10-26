package com.videosorter.app.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.DriveFileMove
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.ViewList
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlin.math.roundToInt

/* ============================ 状态容器 ============================ */

/** 底部弹层：全局唯一一份，由 MainScreen 挂载，任何页面调用 open() 即可 */
class SheetState {
    var visible by mutableStateOf(false)
        private set
    var title by mutableStateOf("")
        private set
    var subtitle by mutableStateOf<String?>(null)
        private set
    var body: @Composable ColumnScope.() -> Unit = {}
        private set

    fun open(title: String, subtitle: String? = null, body: @Composable ColumnScope.() -> Unit) {
        this.title = title
        this.subtitle = subtitle
        this.body = body
        visible = true
    }

    fun close() {
        visible = false
    }
}

/** 玻璃 toast */
class ToastState {
    var message by mutableStateOf<String?>(null)
        private set
    var isError by mutableStateOf(false)
        private set

    fun show(msg: String, error: Boolean = false) {
        message = msg
        isError = error
    }

    fun clear() {
        message = null
    }
}

@Composable
fun ToastHost(state: ToastState, modifier: Modifier = Modifier) {
    val t = tokens()
    val msg = state.message
    var tick by remember { mutableStateOf(0) }
    androidx.compose.runtime.LaunchedEffect(msg) {
        if (msg != null) {
            delay(2200)
            state.clear()
        }
    }
    AnimatedVisibility(
        visible = msg != null,
        enter = fadeIn(tween(180)) + slideInVertically(tween(220)) { it / 3 },
        exit = fadeOut(tween(180)) + slideOutVertically(tween(220)) { it / 3 },
        modifier = modifier,
    ) {
        Row(
            Modifier
                .background(t.glassStrong, RoundedCornerShape(12.dp))
                .border(1.dp, t.line2, RoundedCornerShape(12.dp))
                .padding(horizontal = 14.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Box(
                Modifier
                    .size(6.dp)
                    .clip(CircleShape)
                    .background(if (state.isError) t.danger else t.accent)
            )
            Text(
                msg ?: "",
                color = t.ink(0.9f),
                fontSize = 11.5.sp,
                maxLines = 2,
            )
        }
    }
    // 让 tick 参与重组时不影响上面的动画（占位，避免未使用告警）
    if (tick < 0) Text("", color = Color.Transparent)
}

@Composable
fun SheetHost(state: SheetState) {
    val t = tokens()
    AnimatedVisibility(
        visible = state.visible,
        enter = fadeIn(tween(160)),
        exit = fadeOut(tween(160)),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color(0x8C04060A))
                .clickable(
                    interactionSource = remember { MutableInteractionSource() },
                    indication = null,
                ) { state.close() },
            contentAlignment = Alignment.BottomCenter,
        ) {
            AnimatedVisibility(
                visible = state.visible,
                enter = slideInVertically(animationSpec = tween(240)) { it },
                exit = slideOutVertically(animationSpec = tween(200)) { it },
            ) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp))
                        .background(t.panel)
                        .border(
                            1.dp,
                            t.ink(0.10f),
                            RoundedCornerShape(topStart = 22.dp, topEnd = 22.dp),
                        )
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                        ) { /* 吃掉点击，避免点内容也关闭 */ }
                        .padding(start = 18.dp, end = 18.dp, top = 10.dp, bottom = 26.dp),
                ) {
                    Box(
                        Modifier
                            .padding(top = 4.dp, bottom = 16.dp)
                            .width(38.dp)
                            .height(4.dp)
                            .clip(RoundedCornerShape(3.dp))
                            .background(t.ink(0.18f))
                            .align(Alignment.CenterHorizontally)
                    )
                    if (state.title.isNotEmpty()) {
                        Text(state.title, color = t.text, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    }
                    state.subtitle?.let {
                        Spacer(Modifier.height(4.dp))
                        Text(it, color = t.muted2, fontSize = 11.5.sp, lineHeight = 18.sp)
                    }
                    state.body(this)
                }
            }
        }
    }
}

/* ============================ 基础控件 ============================ */

@Composable
fun GlassIconButton(
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    active: Boolean = false,
    size: Int = 33,
    iconSize: Int = 17,
    contentDescription: String? = null,
) {
    val t = tokens()
    val shape = RoundedCornerShape((size * 0.4f).dp)
    Box(
        modifier
            .size(size.dp)
            .shadow(6.dp, shape)
            .clip(shape)
            .background(if (active) t.accent.copy(alpha = if (t.dark) 0.18f else 0.14f) else t.glass)
            .border(1.dp, if (active) t.accent.copy(alpha = 0.42f) else t.glassBorder, shape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            icon,
            contentDescription = contentDescription,
            tint = if (active) t.accent else t.ink(0.88f),
            modifier = Modifier.size(iconSize.dp),
        )
    }
}

@Composable
fun GlassChip(
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    content: @Composable RowScope.() -> Unit,
) {
    val t = tokens()
    val shape = RoundedCornerShape(16.dp)
    val base = modifier
        .height(31.dp)
        .shadow(6.dp, shape)
        .clip(shape)
        .background(t.glass)
        .border(1.dp, t.glassBorder, shape)
    Row(
        (if (onClick != null) base.clickable(onClick = onClick) else base).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        content = content,
    )
}

@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(14.dp),
    content: @Composable BoxScope.() -> Unit,
) {
    val t = tokens()
    Box(
        modifier
            .clip(shape)
            .background(
                Brush.linearGradient(
                    listOf(t.ink(0.055f), t.ink(0.022f))
                )
            )
            .border(1.dp, t.line, shape),
        content = content,
    )
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    val t = tokens()
    Text(
        text,
        modifier = modifier.padding(top = 6.dp, bottom = 9.dp),
        color = t.muted2,
        fontSize = 11.sp,
        letterSpacing = 0.6.sp,
    )
}

/** 主按钮：绿色渐变胶囊 */
@Composable
fun GradientButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    height: Int = 50,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    val t = tokens()
    val shape = RoundedCornerShape(17.dp)
    val bg = if (enabled) {
        Brush.linearGradient(listOf(Color(0xFF5FECAB), Color(0xFF2FBF7C)))
    } else {
        Brush.linearGradient(listOf(t.ink(0.06f), t.ink(0.06f)))
    }
    Row(
        modifier
            .fillMaxWidth()
            .height(height.dp)
            .clip(shape)
            .background(bg)
            .then(if (enabled) Modifier.clickable(onClick = onClick) else Modifier)
            .then(if (enabled) Modifier else Modifier.border(1.dp, t.ink(0.10f), shape)),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text,
            color = if (enabled) Color(0xFF04160D) else t.muted2,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
        )
        if (enabled) trailing()
    }
}

/** 标签色块胶囊 */
@Composable
fun TagPill(name: String, color: Color, modifier: Modifier = Modifier, withDot: Boolean = true) {
    Row(
        modifier
            .height(19.dp)
            .clip(RoundedCornerShape(5.dp))
            .background(color.copy(alpha = 0.16f))
            .border(1.dp, color.copy(alpha = 0.34f), RoundedCornerShape(5.dp))
            .padding(horizontal = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        if (withDot) {
            Box(Modifier.size(4.dp).clip(CircleShape).background(color))
        }
        Text(name, color = color, fontSize = 10.sp)
    }
}

@Composable
fun StatusPill(organized: Boolean, modifier: Modifier = Modifier) {
    val t = tokens()
    Row(
        modifier
            .height(19.dp)
            .clip(RoundedCornerShape(5.dp))
            .background(if (organized) t.accent.copy(alpha = 0.11f) else t.ink(0.05f))
            .border(
                1.dp,
                if (organized) t.accent.copy(alpha = 0.26f) else t.ink(0.10f),
                RoundedCornerShape(5.dp),
            )
            .padding(horizontal = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            if (organized) "✓ 已整理" else "未整理",
            color = if (organized) t.accent else t.muted,
            fontSize = 10.sp,
        )
    }
}

/* ============================ 液态玻璃 Tab Bar ============================ */

private data class TabSpec(val icon: ImageVector, val label: String)

private val TABS = listOf(
    TabSpec(Icons.Rounded.PlayArrow, "播放"),
    TabSpec(Icons.Rounded.ViewList, "列表"),
    TabSpec(Icons.Rounded.DriveFileMove, "整理"),
    TabSpec(Icons.Rounded.Tune, "设置"),
)

@Composable
fun LiquidTabBar(
    current: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
    visible: Boolean = true,
) {
    val t = tokens()
    val widthDp = 238.dp
    val indicatorW = (238f - 12f) / 4f
    val target = indicatorW * current
    val animatedX by animateFloatAsState(
        targetValue = target,
        animationSpec = spring(dampingRatio = 0.72f, stiffness = Spring.StiffnessMediumLow),
        label = "tab-indicator",
    )
    val shape = RoundedCornerShape(22.dp)

    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(tween(260)) { it * 2 } + fadeIn(tween(200)),
        exit = slideOutVertically(tween(220)) { it * 2 } + fadeOut(tween(160)),
        modifier = modifier,
    ) {
        Box(
            Modifier
                .padding(bottom = 20.dp)
                .width(widthDp)
                .height(56.dp)
                .shadow(20.dp, shape)
                .clip(shape)
                .background(t.glass)
                .border(1.dp, t.ink(0.14f), shape)
                .padding(horizontal = 6.dp),
        ) {
            // 顶部液态高光
            Box(
                Modifier
                    .matchParentSize()
                    .background(
                        Brush.linearGradient(
                            listOf(t.highlight.copy(alpha = 0.16f), Color.Transparent, t.ink(0.04f))
                        )
                    )
            )
            // 指示块
            Box(
                Modifier
                    .offset { IntOffset((animatedX * 1f).dp.roundToPx(), 0) }
                    .padding(vertical = 6.dp)
                    .width(indicatorW.dp)
                    .height(44.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(t.ink(0.14f))
                    .border(1.dp, t.ink(0.22f), RoundedCornerShape(16.dp))
            )
            Row(Modifier.matchParentSize(), verticalAlignment = Alignment.CenterVertically) {
                TABS.forEachIndexed { i, spec ->
                    val on = i == current
                    val scale by animateFloatAsState(
                        targetValue = if (on) 1.06f else 1f,
                        animationSpec = spring(dampingRatio = 0.5f, stiffness = Spring.StiffnessMedium),
                        label = "tab-scale-$i",
                    )
                    Box(
                        Modifier
                            .weight(1f)
                            .fillMaxSize()
                            .clickable(
                                interactionSource = remember { MutableInteractionSource() },
                                indication = null,
                            ) { onSelect(i) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            spec.icon,
                            contentDescription = spec.label,
                            tint = if (on) t.accent else t.muted,
                            modifier = Modifier
                                .size(22.dp)
                                .graphicsLayer {
                                    scaleX = scale
                                    scaleY = scale
                                    translationY = if (on) -1.dp.toPx() else 0f
                                },
                        )
                    }
                }
            }
        }
    }
}

/** 完成动画用的小勾 */
@Composable
fun DoneBadge(size: Int = 46) {
    val t = tokens()
    Box(
        Modifier
            .size(size.dp)
            .clip(CircleShape)
            .background(t.accent.copy(alpha = 0.14f))
            .border(1.dp, t.accent.copy(alpha = 0.3f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Rounded.Check, contentDescription = null, tint = t.accent, modifier = Modifier.size(22.dp))
    }
}
