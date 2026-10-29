package com.videosorter.app.ui

import kotlinx.coroutines.withTimeoutOrNull

import androidx.compose.foundation.gestures.waitForUpOrCancellation

import androidx.compose.foundation.gestures.awaitFirstDown

import androidx.compose.foundation.gestures.awaitEachGesture

import androidx.compose.ui.input.pointer.pointerInput

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** 设置页/二级页统一卡片：浅渐变 + 细边，不用灰底。 */
@Composable
fun GroupCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val t = tokens()
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Brush.linearGradient(listOf(t.ink(0.055f), t.ink(0.02f))))
            .border(1.dp, t.line, RoundedCornerShape(16.dp)),
        content = content,
    )
}

@Composable
fun RowDivider() {
    val t = tokens()
    Box(Modifier.fillMaxWidth().padding(start = 14.dp).height(1.dp).background(t.line))
}

@Composable
fun RoundIcon(icon: ImageVector, danger: Boolean = false) {
    val t = tokens()
    Box(
        Modifier.size(26.dp).clip(RoundedCornerShape(8.dp))
            .background(if (danger) t.danger.copy(alpha = 0.14f) else t.ink(0.06f)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(icon, null, tint = if (danger) t.danger else t.ink(0.7f), modifier = Modifier.size(14.dp))
    }
}

@Composable
fun SettingRow(
    icon: ImageVector,
    title: String,
    subtitle: String? = null,
    danger: Boolean = false,
    chevron: Boolean = true,
    trailing: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    val t = tokens()
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable { onClick() } else Modifier)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RoundIcon(icon, danger)
        Spacer(Modifier.width(11.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                color = if (danger) t.danger else t.ink(0.9f),
                fontSize = 12.5.sp,
                fontWeight = FontWeight.Medium,
            )
            if (subtitle != null) {
                Spacer(Modifier.height(2.dp))
                Text(subtitle, color = t.muted2, fontSize = 10.sp, maxLines = 2)
            }
        }
        if (trailing != null) {
            Spacer(Modifier.width(8.dp))
            trailing()
        }
        if (chevron) {
            Icon(Icons.Rounded.ChevronRight, null, tint = t.muted2, modifier = Modifier.size(15.dp))
        }
    }
}

@Composable
fun ThemeChip(label: String, on: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val t = tokens()
    Box(
        modifier
            .height(34.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) t.accentDim else t.ink(0.05f))
            .border(1.dp, if (on) t.accent.copy(alpha = 0.45f) else t.line, RoundedCornerShape(10.dp))
            .clickable { onClick() },
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (on) t.accent else t.muted, fontSize = 11.5.sp, fontWeight = if (on) FontWeight.Medium else FontWeight.Normal)
    }
}

@Composable
fun GlassField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String = "",
    label: String? = null,
    singleLine: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Text,
    password: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val t = tokens()
    Column(modifier) {
        if (label != null) {
            Text(label, color = t.muted, fontSize = 11.sp)
            Spacer(Modifier.height(6.dp))
        }
        Box(
            Modifier
                .fillMaxWidth()
                .height(40.dp)
                .clip(RoundedCornerShape(11.dp))
                .background(t.ink(0.06f))
                .border(1.dp, t.line2, RoundedCornerShape(11.dp))
                .padding(horizontal = 12.dp),
            contentAlignment = Alignment.CenterStart,
        ) {
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                singleLine = singleLine,
                textStyle = TextStyle(color = t.ink(0.9f), fontSize = 13.sp),
                cursorBrush = SolidColor(t.accent),
                keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(keyboardType = keyboardType),
                visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
                modifier = Modifier.fillMaxWidth(),
                decorationBox = { inner ->
                    if (value.isEmpty()) Text(placeholder, color = t.muted2, fontSize = 13.sp)
                    inner()
                },
            )
        }
    }
}

@Composable
fun EmptyNote(text: String) {
    val t = tokens()
    Box(Modifier.fillMaxWidth().padding(vertical = 18.dp), contentAlignment = Alignment.Center) {
        Text(text, color = t.muted2, fontSize = 11.5.sp)
    }
}

/** 二级页面外壳：返回 + 标题 + 内容（可滚动）。 */
@Composable
fun SubScaffold(
    title: String,
    onBack: () -> Unit,
    actions: (@Composable RowScope.() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val t = tokens()
    Column(Modifier.fillMaxSize().background(t.bg).statusBarsPadding()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 14.dp, top = 6.dp, bottom = 10.dp),
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
            Text(title, fontSize = 19.sp, fontWeight = FontWeight.Bold, color = t.text, modifier = Modifier.weight(1f))
            if (actions != null) actions()
        }
        Column(Modifier.fillMaxSize(), content = content)
    }
}

/**
 * 点按 / 长按：长按在「松手之后」才回调，避免长按弹层刚出现就被这次抬手的 UP 关掉。
 * 滚动（快速取消）不会误触发。
 */
fun Modifier.tapOrLongPress(onTap: () -> Unit, onLongPress: () -> Unit): Modifier =
    this.pointerInput(onTap, onLongPress) {
        awaitEachGesture {
            awaitFirstDown(requireUnconsumed = false)
            val start = System.currentTimeMillis()
            val released = withTimeoutOrNull(viewConfiguration.longPressTimeoutMillis + 20) {
                waitForUpOrCancellation()
            }
            if (released != null) {
                onTap()
            } else if (System.currentTimeMillis() - start >= viewConfiguration.longPressTimeoutMillis - 40) {
                waitForUpOrCancellation()
                onLongPress()
            }
        }
    }
