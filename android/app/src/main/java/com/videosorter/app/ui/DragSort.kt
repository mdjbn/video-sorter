package com.videosorter.app.ui

/**
 * 标签排序用的小工具。
 *
 * 早先是「长按/握把拖动」的排序实现，手势在可滚动列表里要和 LazyColumn 抢事件，
 * 偶发失效且很难调试（详见 HANDOFF §8.24–§8.26）。现已改成卡片右侧的上移/下移按钮，
 * 这里只留下「把某项从 from 挪到 to」这一个纯函数。
 */
object DragReorder {
    /** 返回 [list] 把 [from] 挪到 [to] 之后的新列表；下标越界或原地不动时原样返回。 */
    fun <T> move(list: List<T>, from: Int, to: Int): List<T> {
        if (from == to) return list
        if (from !in list.indices || to !in list.indices) return list
        val out = list.toMutableList()
        out.add(to, out.removeAt(from))
        return out
    }
}
