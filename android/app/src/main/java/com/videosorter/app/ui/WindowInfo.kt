package com.videosorter.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.widthIn
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 当前窗口尺寸（dp）。
 *
 * 以前只看手机，所有页面都按「竖屏、约 390dp 宽」写死。现在平板（横屏 1205dp）和
 * 手机横屏（约 840dp）都要能用，所以把「够不够宽」抽出来统一判断，别在各页面里
 * 到处写 `LocalConfiguration.current.screenWidthDp`。
 */
data class WinSize(val wDp: Int, val hDp: Int) {
    /** 手机竖屏：单列布局。 */
    val compact: Boolean get() = wDp < 600

    /** 平板，或手机横过来。 */
    val wide: Boolean get() = wDp >= 600

    /** 横屏（宽 > 高），上下空间紧张。 */
    val landscape: Boolean get() = wDp > hDp
}

@Composable
fun winSize(): WinSize {
    val c = LocalConfiguration.current
    return WinSize(c.screenWidthDp, c.screenHeightDp)
}

/**
 * 给内容加一个最大宽度并居中。
 *
 * 表格、表单这类东西在大屏上被拉满一整行会非常难读（标签在左、值在 1200dp 外的右端）。
 * 限宽后视觉焦点集中，和网页端的做法一致。
 */
@Composable
fun ReadableWidth(
    max: Dp = 760.dp,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Box(modifier, contentAlignment = Alignment.TopCenter) {
        Box(Modifier.widthIn(max = max), contentAlignment = Alignment.TopStart) {
            content()
        }
    }
}

/**
 * 内容居中所需的左右留白：窗口很宽时把内容夹在 [maxContent] 宽度内居中。
 *
 * 只改 padding 就能达到「居中限宽」的效果，不用把每个页面的 Column 结构都重排一遍
 * （设置首页、整理页、登录页这些都是 fillMaxSize + verticalScroll 的写法，套一层 Box 反而容易出问题）。
 */
@Composable
fun centeredSidePadding(maxContent: Dp = 720.dp, base: Dp = 18.dp): Dp {
    val w = winSize().wDp
    val need = maxContent.value + base.value * 2
    return if (w <= need) base else ((w - maxContent.value) / 2).dp
}
