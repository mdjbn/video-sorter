package com.videosorter.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp

/** 当前是否深色主题，由 VideoSorterTheme 提供 */
val LocalDark = staticCompositionLocalOf { true }

/** 与网页端 tokens.css 对齐的一套颜色（深/浅两档） */
data class Tokens(
    val dark: Boolean,
    val bg: Color,
    val panel: Color,
    val panel2: Color,
    val text: Color,
    val muted: Color,
    val muted2: Color,
    val line: Color,
    val line2: Color,
    val accent: Color,
    val accent2: Color,
    val accentDim: Color,
    val danger: Color,
    val warn: Color,
    /** 玻璃填充色（半透明） */
    val glass: Color,
    /** 更强一点的玻璃（sheet / 悬浮卡） */
    val glassStrong: Color,
    val glassBorder: Color,
    /** 顶部内高光 */
    val highlight: Color,
    /** 底部信息区渐隐遮罩 */
    val scrim: List<Color>,
) {
    /** 像网页里 rgba(var(--ink), a) 一样按透明度取前景色 */
    fun ink(a: Float): Color = text.copy(alpha = a)
}

private val Dark = Tokens(
    dark = true,
    bg = Color(0xFF0A0C0F),
    panel = Color(0xFF11141A),
    panel2 = Color(0xFF161A21),
    text = Color(0xFFE8EDF3),
    muted = Color(0xFF8D98A8),
    muted2 = Color(0xFF69717F),
    line = Color(0xFF232932),
    line2 = Color(0xFF2C333E),
    accent = Color(0xFF35D18A),
    accent2 = Color(0xFF2BBD7B),
    accentDim = Color(0x1F35D18A),
    danger = Color(0xFFFF6B6B),
    warn = Color(0xFFF4A259),
    glass = Color(0x14FFFFFF),
    glassStrong = Color(0xB3121519),
    glassBorder = Color(0x29FFFFFF),
    highlight = Color(0x30FFFFFF),
    scrim = listOf(Color(0x0006080C), Color(0xB806080C), Color(0xF006080C)),
)

private val Light = Tokens(
    dark = false,
    bg = Color(0xFFEEF1F6),
    panel = Color(0xFFFFFFFF),
    panel2 = Color(0xFFF6F8FB),
    text = Color(0xFF0F1A29),
    muted = Color(0xFF5C6675),
    muted2 = Color(0xFF8A94A3),
    line = Color(0xFFE0E5EE),
    line2 = Color(0xFFD3DAE5),
    accent = Color(0xFF0FA267),
    accent2 = Color(0xFF0C8F5B),
    accentDim = Color(0x1F0FA267),
    danger = Color(0xFFD64545),
    warn = Color(0xFFB9741F),
    glass = Color(0x8CFFFFFF),
    glassStrong = Color(0xF2FFFFFF),
    glassBorder = Color(0x1F0F1A29),
    highlight = Color(0xF2FFFFFF),
    scrim = listOf(Color(0x00F7FAFF), Color(0xE6F7FAFF), Color(0xFFF7FAFF)),
)

@Composable
fun tokens(): Tokens = if (LocalDark.current) Dark else Light

/** 视频没有封面时用的确定性渐变（对齐设计稿的 8 组 GRADS） */
fun gradientFor(id: Int): Brush {
    val pairs = listOf(
        Color(0xFF1F6F5C) to Color(0xFF0A1A19),
        Color(0xFF4A2A6B) to Color(0xFF120B1F),
        Color(0xFF1D3F7A) to Color(0xFF0A1222),
        Color(0xFF7A4A19) to Color(0xFF23160A),
        Color(0xFF1D5A2E) to Color(0xFF0B1D10),
        Color(0xFF5A2350) to Color(0xFF1D0B1A),
        Color(0xFF7A2A2A) to Color(0xFF230C0C),
        Color(0xFF1F4A5E) to Color(0xFF0A171D),
    )
    val p = pairs[((id % pairs.size) + pairs.size) % pairs.size]
    return Brush.linearGradient(listOf(p.first, p.second), start = Offset.Zero, end = Offset(900f, 1400f))
}

/** 页面环境光：两团彩色光斑，让玻璃有东西可折射 */
@Composable
fun AmbientBackdrop(modifier: Modifier = Modifier) {
    val t = tokens()
    val density = LocalDensity.current
    Box(modifier.fillMaxSize().background(t.bg)) {
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.radialGradient(
                        colors = listOf(t.accent.copy(alpha = if (t.dark) 0.14f else 0.10f), Color.Transparent),
                        center = Offset(with(density) { 60.dp.toPx() }, with(density) { (-30).dp.toPx() }),
                        radius = with(density) { 420.dp.toPx() },
                    )
                )
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.radialGradient(
                        colors = listOf(Color(0xFF7E5CFF).copy(alpha = if (t.dark) 0.13f else 0.09f), Color.Transparent),
                        center = Offset(with(density) { 380.dp.toPx() }, with(density) { 420.dp.toPx() }),
                        radius = with(density) { 460.dp.toPx() },
                    )
                )
        )
    }
}

/** #RRGGBB → Color，解析失败回退 */
fun hexColor(hex: String?, fallback: Color = Color(0xFF8D98A8)): Color {
    val h = (hex ?: "").trim().removePrefix("#")
    if (h.length != 6) return fallback
    return runCatching { Color(0xFF000000L or h.toLong(16)) }.getOrDefault(fallback)
}

/** 秒 → 0:04 / 1:02:03 */
fun fmtDuration(sec: Double): String {
    val s = sec.toInt().coerceAtLeast(0)
    val h = s / 3600
    val m = (s % 3600) / 60
    val ss = s % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, ss) else "%d:%02d".format(m, ss)
}
