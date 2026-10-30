package com.videosorter.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.drag
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
import androidx.compose.ui.graphics.graphicsLayer
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
    /**
     * 拖动时应该落在哪个位置。
     *
     * @param draggedTop  被拖卡片当前顶边（屏幕坐标）
     * @param rows        各行的实测区间（下标 = 当前列表下标）
     * @param from        被拖卡片起始下标
     * @param count       列表长度
     * @param slotHeight  被拖卡片高度，用它的半格当换位阈值
     *
     * 判据：把每张卡看作占 [top, top+slotHeight) 的槽位。被拖卡片的顶边落在
     * 谁的槽位里，就排到谁那个位置。等价于「越过对方顶边 + 半格」——半格而不是整格，
     * 是因为实拍里 adb 拖一格只走约 220px 而一格 243px，差几像素就白拖一次
     * （表现为「第一次能拖、后面常常拖不动」）。
     */
    fun targetIndex(
        draggedTop: Float,
        rows: List<RowY>,
        from: Int,
        count: Int,
        slotHeight: Float = 0f,
    ): Int {
        if (count <= 0) return 0
        if (rows.isEmpty()) return from.coerceIn(0, count - 1)
        val sorted = rows.sortedBy { it.index }
        // 半格按被拖卡片自己的高度算；没传就用可见行中位高
        val slot = if (slotHeight > 0f) {
            slotHeight
        } else {
            sorted.map { it.bottom - it.top }.sorted().let { it[it.size / 2] }
        }
        // 我的中心落在哪一行里，就占那一行的位置
        val probe = draggedTop + slot / 2f
        for (row in sorted) {
            if (probe < row.bottom) return row.index.coerceIn(0, count - 1)
        }
        // 落到所有行下方 → 最后一个可见行的位置
        return sorted.last().index.coerceIn(0, count - 1)
    }

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
 * 可长按拖动排序的列表行容器（给「整行长按就能拖」的场景用）。
 *
 * 行位置上报仍然由它转发（[onMeasured]），但页面自己做卡片位移，所以这里只管手势与层级。
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
    offsetY: Float = 0f,
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
        // 位移只挂在内层：外层负责测量，必须保持静止，否则测到的 y 会把自己被拖走的那段
        // 位移也算进去（self-referential），行区间一路漂走，落点判断跟着乱跳。
        Box(Modifier.graphicsLayer { translationY = offsetY }) {
            content()
        }
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
            // 一按下就抢下手势：不等系统手指移动阈值。否则在可滚动列表里，
            // 向上的拖动会先被 LazyColumn 当成滚动吃掉（松手时 onDragEnd 也不来），
            // 表现就是「往上拖没反应、往下拖正常」。
            .pointerInput(Unit) {
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    down.consume()
                    onStart()
                    var last = down.position.y
                    // drag(...) 会一直跟到手指抬起或手势被取消，返回 true 才是正常抬起
                    val ok = drag(down.id) { change ->
                        val dy = change.position.y - last
                        last = change.position.y
                        change.consume()
                        if (dy != 0f) onDragBy(dy)
                    }
                    onEnd()
                }
            }
            .clickable(interactionSource = interaction, indication = null) { },
    ) {
        content()
    }
}

/**
 * 拖动排序的共享状态。
 *
 * 关键点：手指移动的量 [travel] **一次拖动内永不归零**，被拖那张卡在原列表里的位置也
 * [slotTop] 一次记死。于是「卡片当前该画在哪」永远是 [slotTop] + [travel]，
 * 不会因为中途换位而漂移——之前用「换位后 reset 偏移」导致标签乱跳，就是这里改掉的。
 */
class DragSortState {
    /** 被拖那张卡当前的下标（会随换位变化，只用来决定「谁在最后画」）。 */
    var dragIndex by mutableStateOf(-1)
        private set

    /** 这次拖动手指累计走了多远（纵轴），从头到尾只增不减。 */
    var travel by mutableStateOf(0f)
        private set

    /** 开始拖时这张卡在原列表里的顶部 y 与高度（未换位坐标系的基准）。 */
    var slotTop by mutableStateOf(0f)
        private set
    var slotHeight by mutableStateOf(0f)
        private set

    /** 被抓起来那张卡在页面上的 y：基准位置 + 手指位移。 */
    val cardTop: Float get() = slotTop + travel

    fun start(index: Int, top: Float, height: Float) {
        dragIndex = index
        travel = 0f
        slotTop = top
        slotHeight = height
    }

    fun dragBy(dy: Float) {
        if (dragIndex < 0) return
        travel += dy
    }

    /** 换位后只改下标，不动 [travel]，卡片因此不会跳。 */
    fun setIndex(index: Int) {
        if (dragIndex < 0) return
        dragIndex = index
    }

    fun end(): Int {
        val i = dragIndex
        dragIndex = -1
        travel = 0f
        return i
    }

    val dragging: Boolean get() = dragIndex >= 0
}
