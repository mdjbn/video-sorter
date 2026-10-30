package com.videosorter.app.ui

/**
 * 拖进度条时「播完了怎么办」——纯决策，便于单测（见 LogicTest.scrub*）。
 *
 * 背景：进度条是「按住预览、松手才 seek」的交互，视频在这期间照常播放。
 * 如果按住的时候正好把视频看到结尾，老行为是立刻自动切下一个视频——
 * 用户手还按在进度条上、正想往回拖，画面却已经换成别的片子了。
 *
 * 现在：先停在结尾不许跳；松手时 seek 到滑块位置，再恢复播放。
 * 两条规则抽在这里，`PlayerScreen` 只负责照着做。
 */
object ScrubEnd {

    /** 播放器进入 STATE_ENDED 时该做什么。 */
    enum class OnEnded {
        /** 没人按着进度条：照旧，自动播放下一个。 */
        ADVANCE,

        /** 正按着进度条预览：停在结尾，等松手。 */
        HOLD,
    }

    /** 松手时该怎么恢复播放。 */
    enum class OnRelease {
        /** 把 playWhenReady 设回 true 就行（播放器还在播放状态，只是被暂停了）。 */
        RESUME,

        /**
         * 预览期间已经播到结尾：播放器停在 STATE_ENDED。
         * Media3 里这个状态是粘住的——只把 playWhenReady 设回 true 不会自己恢复，
         * 必须再调一次 seek/play()（这里用 play()），否则松手后画面一动不动。
         */
        RESTART,
    }

    fun onEnded(scrubbing: Boolean): OnEnded =
        if (scrubbing) OnEnded.HOLD else OnEnded.ADVANCE

    fun onRelease(endedWhileScrubbing: Boolean): OnRelease =
        if (endedWhileScrubbing) OnRelease.RESTART else OnRelease.RESUME
}
