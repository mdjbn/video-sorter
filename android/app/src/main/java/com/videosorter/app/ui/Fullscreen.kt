package com.videosorter.app.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ActivityInfo
import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * 播放页的「横屏全屏」。
 *
 * 方向策略（v1.4.0 起）：**全 App 跟随设备旋转**。
 * 平板横屏、手机横过来都要能用，所以不再无条件锁竖屏——只有点了「横屏全屏」时才强制
 * 转成横屏，退出全屏时交还给系统（SCREEN_ORIENTATION_UNSPECIFIED），设备怎么拿就怎么显示：
 *   · 手机开着自动旋转 → 跟着手转；关着自动旋转 → 保持竖屏（系统行为，我们不再干预）
 *   · 平板横着拿 → 一直是横屏
 *
 * 系统栏（状态栏 + 导航栏）在全屏时隐藏，退出时恢复。
 */
@Composable
fun FullscreenEffect(fullscreen: Boolean) {
    val ctx = LocalContext.current
    val activity = rememberActivity(ctx) ?: return
    // 状态变化时读最新的值，避免回调里拿到旧的 lambda
    val current by rememberUpdatedState(fullscreen)

    // 方向：全屏时强制横屏；退出全屏交还给系统，让平板/手机按自己拿的方向显示
    LaunchedEffect(fullscreen) {
        activity.requestedOrientation =
            if (fullscreen) ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            else ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
    }

    // 系统栏：隐藏 / 恢复。退出页面时一定还原，否则返回列表页会没有状态栏
    DisposableEffect(activity, fullscreen) {
        val window = activity.window
        val controller = WindowCompat.getInsetsController(window, window.decorView)
        if (current) {
            WindowCompat.setDecorFitsSystemWindows(window, false)
            controller.systemBarsBehavior =
                WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            controller.hide(WindowInsetsCompat.Type.systemBars())
        } else {
            controller.show(WindowInsetsCompat.Type.systemBars())
            WindowCompat.setDecorFitsSystemWindows(window, true)
        }
        onDispose {
            // 离开播放页/退出全屏时恢复系统栏，避免「退出 App 后别的页面没有状态栏」
            controller.show(WindowInsetsCompat.Type.systemBars())
            WindowCompat.setDecorFitsSystemWindows(window, true)
            // 离开播放页时把方向控制权还给系统（不能再锁竖屏，否则平板横屏会被掰回来）
            activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        }
    }
}

/** 从 Compose 的 Context 里往上找 Activity（有些版本外面裹了 ContextWrapper）。 */
private fun rememberActivity(ctx: Context): Activity? {
    var c: Context? = ctx
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

/** 系统版本是否 >= N（全屏 API 的最低要求），保留给样式差异用。 */
internal fun supportsImmersive(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.N
