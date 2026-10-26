package com.videosorter.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val Accent = Color(0xFF35D18A)
val AccentDark = Color(0xFF0FA267)
val Danger = Color(0xFFFF6B6B)
val Warn = Color(0xFFF4A259)

private val DarkColors = darkColorScheme(
    primary = Accent,
    onPrimary = Color(0xFF04160D),
    secondary = Accent,
    background = Color(0xFF0A0C0F),
    onBackground = Color(0xFFE8EDF3),
    surface = Color(0xFF11141A),
    onSurface = Color(0xFFE8EDF3),
    surfaceVariant = Color(0xFF161A21),
    onSurfaceVariant = Color(0xFF8D98A8),
    error = Danger,
    outline = Color(0xFF232932),
)

private val LightColors = lightColorScheme(
    primary = AccentDark,
    onPrimary = Color.White,
    secondary = AccentDark,
    background = Color(0xFFEEF1F6),
    onBackground = Color(0xFF0F1A29),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF0F1A29),
    surfaceVariant = Color(0xFFF6F8FB),
    onSurfaceVariant = Color(0xFF5C6675),
    error = Color(0xFFD64545),
    outline = Color(0xFFE0E5EE),
)

private val AppTypography = Typography(
    headlineSmall = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.Bold),
    titleMedium = TextStyle(fontSize = 15.sp, fontWeight = FontWeight.SemiBold),
    bodyMedium = TextStyle(fontSize = 13.sp),
    labelSmall = TextStyle(fontSize = 11.sp),
)

@Composable
fun VideoSorterTheme(mode: String, content: @Composable () -> Unit) {
    val dark = when (mode) {
        "light" -> false
        "dark" -> true
        else -> isSystemInDarkTheme()
    }
    CompositionLocalProvider(LocalDark provides dark) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = AppTypography,
            content = content,
        )
    }
}

/** 主题三档循环：浅色 → 深色 → 跟随系统 */
fun nextThemeMode(mode: String, systemDark: Boolean): String {
    val effectiveLight = when (mode) {
        "light" -> true
        "dark" -> false
        else -> !systemDark
    }
    return when (mode) {
        "light" -> "dark"
        "dark" -> "auto"
        else -> if (effectiveLight) "dark" else "light"
    }
}

fun themeLabel(mode: String) = when (mode) {
    "light" -> "浅色"
    "dark" -> "深色"
    else -> "跟随系统"
}
