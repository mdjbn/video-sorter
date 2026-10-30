package com.videosorter.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectDragGesturesAfterLongPress
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListItemInfo
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.zIndex

/**
 * 长按拖动排序用的纯计算，抽成普通函数好写单测（Compose 的手势在单测里跑不起来）。
 *
 * 只做一件事：给定「被拖的那行的中心 y」和「当前每一行的位置」，算出它该落在哪个下标。
 * 判定用的是「另一个行的中心」——拖过别人一半就让位，和网页端一致的直觉。
 */
object DragReorder {

    /** 一行在列表里的位置，只需要用到纵向区间。 */
    data class RowY(val index: Int, val top: Float, val bottom: Float) {
        val center: Float get() = (top + bottom) / 2f
    }

    /**
     * 算落点下标。
     *
     * @param draggedCenter 被拖行的中心 y（跟着手指走之后的实际位置）
     * @param rows 当前可见行（含被拖的那行），按 index 升序
     * @param from 被拖行当前的下标
     * @param count 列表总条数（可见的 + 滚出去的）
     * @return 目标下标，范围收在 0..count-1
     */
    /**
     * 落点下标（相对于**当前还在的**列表，也就是 from 那一行仍在原位的坐标系）。
     *
     * 判据：找到第一个「中心线在我中心线下方」的行，我要插到它前面。
     * 那个行在列表里的下标，就是我的最终下标（因为摘掉自己后插进这个位置，
     * 正好落回同一个视觉位置）。
     * 向下拖时它自然变成 from+1、from+2…；向上拖时变成 from-1、from-2…
     */
    fun targetIndex(draggedCenter: Float, rows: List<RowY>, from: Int, count: Int): Int {
        if (count <= 0) return 0
        if (rows.isEmpty()) return from.coerceIn(0, count - 1)
        // 只看别人的中线：越过一半就换位，拖动时行不会来回抽搐
        val others = rows.filter { it.index != from }.sortedBy { it.index }
        if (others.isEmpty()) return from.coerceIn(0, count - 1)
        val below = others.firstOrNull { it.center > draggedCenter }
        if (below != null) {
            // 插到 below 前面。若我从上方拖来，这个位置就是 below.index - 1；
            // 若我从下方拖来，就是 below.index。统一用「摘掉自己后 below 的新下标」：
            val belowAfterRemoval = if (below.index > from) below.index - 1 else below.index
            return belowAfterRemoval.coerceIn(0, count - 1)
        }
        // 没有任何行在我下方 → 排到最后一个可见行之后
        val bottom = others.last()
        val afterBottom = if (bottom.index > from) bottom.index else bottom.index + 1
        return afterBottom.coerceIn(0, count - 1)
    }

    /** 把手里的列表按 from→to 挪一格，返回新列表（不原地改，方便回滚）。 */
    fun <T> move(list: List<T>, from: Int, to: Int): List<T> {
        if (from == to) return list
        if (from !in list.indices) return list
        val dst = to.coerceIn(0, list.size - 1)
        if (dst == from) return list
        val out = list.toMutableList()
        val item = out.removeAt(from)
        out.add(dst, item)
        return out
    }
}

/** 从 LazyListState 的可见项里取出纵向区间（长按拖动时用来判断落点）。 */
fun LazyListState.visibleRowYs(): List<DragReorder.RowY> =
    layoutInfo.visibleItemsInfo.mapNotNull { info: LazyListItemInfo ->
        DragReorder.RowY(info.index, info.offset.toFloat(), (info.offset + info.size).toFloat())
    }

/**
 * 可长按拖动排序的列表容器。
 *
 * 用法：把 [Modifier.dragHandle] 挂到每一行上（通常是整行），长按后上下拖动就能换位置；
 * 松手时回调 [onDrop]，由页面去调接口保存、失败则回滚。
 *
 * 视觉上只做一件事：被拖的那行抬起来（zIndex 提高 + 半透明），其余的等数据变了自然重排——
 * 数据每次都会真的重新排列，所以松手后不会「弹回去」。
 */
@Composable
fun DragSortItem(
    index: Int,
    count: Int,
    dragging: Boolean,
    startDrag: () -> Unit,
    dragBy: (Float) -> Unit,
    endDrag: () -> Unit,
    onClick: () -> Unit,
    longPressAnywhere: Boolean = true,
    onMeasured: ((Float, Float) -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    // 注意：这里必须自己处理「轻点」。
    // 如果内容里有 .clickable，它会先把按下事件消费掉，外面这层的长按手势就永远等不到
    // awaitLongPressOrCancellation，拖动就完全不响应。
    val interaction = remember { MutableInteractionSource() }
    val base = Modifier
        .fillMaxWidth()
        .zIndex(if (dragging) 1f else 0f)
        .then(
            // 把这一行的纵向区间上报给页面：所有行都在同一个 LazyColumn item 里，
            // LazyListState 量不到单行，只能靠行自己报
            if (onMeasured == null) Modifier else Modifier.onGloballyPositioned { coords ->
                onMeasured(coords.positionInParent().y, coords.positionInParent().y + coords.size.height)
            },
        )
    Box(
        (if (longPressAnywhere) {
            base.pointerInput(index, count) {
                detectDragGesturesAfterLongPress(
                    onDragStart = { startDrag() },
                    onDragEnd = { endDrag() },
                    onDragCancel = { endDrag() },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        dragBy(dragAmount.y)
                    },
                )
            }
        } else {
            base
        })
            // 长按没成立时的普通点击（detectDragGesturesAfterLongPress 不消费短按，这里补上）
            .clickable(
                interactionSource = interaction,
                indication = null,
                onClick = onClick,
            ),
    ) {
        content()
    }
}

/**
 * 行内的拖动手柄：按住就立刻能拖（不必长按），和网页端标签列表的握把一致。
 *
 * 用 `detectDragGestures` 而不是 `detectDragGesturesAfterLongPress`：手指按在手柄上
 * 本来就不会误触，需要的是「一按就能走」。
 */
@Composable
fun DragHandle(
    onStart: () -> Unit,
    onDragBy: (Float) -> Unit,
    onEnd: () -> Unit,
    content: @Composable () -> Unit,
) {
    val interaction = remember { MutableInteractionSource() }
    Box(
        Modifier
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { onStart() },
                    onDragEnd = { onEnd() },
                    onDragCancel = { onEnd() },
                    onDrag = { change, dragAmount ->
                        change.consume()
                        onDragBy(dragAmount.y)
                    },
                )
            }
            .clickable(interactionSource = interaction, indication = null) { },
    ) {
        content()
    }
}

/** 拖动排序的共享状态：记录被拖的行、手指相对行顶的偏移、以及拖动中累计的位移。 */
class DragSortState {
    var dragIndex by mutableStateOf(-1)
        private set
    var dragOffset by mutableStateOf(0f)
        private set

    fun start(index: Int) {
        dragIndex = index
        dragOffset = 0f
    }

    fun dragBy(dy: Float) {
        if (dragIndex < 0) return
        dragOffset += dy
    }

    fun end(): Int {
        val i = dragIndex
        dragIndex = -1
        dragOffset = 0f
        return i
    }

    val dragging: Boolean get() = dragIndex >= 0
}
