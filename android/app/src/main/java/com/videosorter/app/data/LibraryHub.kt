package com.videosorter.app.data

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue

/**
 * 视频列表的「需要刷新」信号：在别处改了会影响列表状态的接口（例如删除播放记录会清掉续播进度），
 * 改完把版本号 +1，播放页/列表页监听到变化就重新拉一次列表。
 */
object LibraryHub {
    var version by mutableIntStateOf(0)
        private set

    fun bump() {
        version += 1
    }
}
