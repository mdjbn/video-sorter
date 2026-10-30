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
 * 需求是「只加全屏按钮，不跟随手机旋转」：整个 App 已经不锁方向了（Manifest 里去掉了
 * screenOrientation），但方向完全由这里按 [fullscreen] 状态强制指定——
 * 全屏时 SCREEN_ORIENTATION_LANDSCAPE，退出时 SCREEN_ORIENTATION_PORTRAIT。
 * 因为其他地方从不调整方向，所以列表/设置/登录页永远保持竖屏，旋手机也不会转。
 *
 * 系统栏（状态栏 + 导航栏）在全屏时隐藏，退出时恢复。
 */
@Composable
fun FullscreenEffect(fullscreen: Boolean) {
    val ctx = LocalContext.current
    val activity = rememberActivity(ctx) ?: return
    // 状态变化时读最新的值，避免回调里拿到旧的 lambda
    val current by rememberUpdatedState(fullscreen)

    // 方向：跟随 fullscreen 状态
    LaunchedEffect(fullscreen) {
        activity.requestedOrientation =
            if (fullscreen) ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            else ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
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
            activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
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
