package com.videosorter.app.data

import android.net.Uri
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.cache.CacheWriter
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import java.io.IOException

/**
 * 预加载：把「下几个视频」的播放数据提前拉进 [MediaCache]。
 *
 * - direct 视频：预取开头 6MB，滑过去时起播几乎瞬间完成；
 * - HLS 视频：先触发服务端转码，等切片就绪后预取前几片。
 * 同一时间只保留一个预加载任务，滑动很快时后面的会取消前面的。
 */
object Preloader {
    /** 每个视频预取的字节数 */
    private const val PRELOAD_BYTES = 6L * 1024 * 1024

    @Volatile
    private var job: Job? = null

    fun warm(scope: CoroutineScope, api: Api, videos: List<Video>, from: Int, count: Int = 2) {
        job?.cancel()
        if (videos.isEmpty()) return
        val end = minOf(videos.size, from + count)
        if (from >= end) return
        job = scope.launch(Dispatchers.IO) {
            for (i in from until end) {
                if (!currentCoroutineContext().isActive) return@launch
                val v = videos[i]
                val info = runCatching { api.play(v.id) }.getOrNull() ?: continue
                val path = when (info.mode) {
                    "direct" -> info.url
                    "hls" -> {
                        // 等服务端把切片转出来，避免预热一个还没生成的 m3u8
                        var ready = false
                        repeat(24) {
                            val st = runCatching { api.hlsStatus(v.id) }.getOrNull()
                            if (st != null && (st.ready || st.finished)) {
                                ready = true
                                return@repeat
                            }
                            if (st != null && !st.error.isNullOrEmpty()) return@repeat
                            delay(250)
                        }
                        if (!ready) null else info.url
                    }
                    else -> null
                } ?: continue
                val target: String = path ?: continue
                val uri = if (target.startsWith("http")) Uri.parse(target) else Uri.parse(api.base + target)
                val ds = runCatching { MediaCache.sourceFactory(api.headers()).createDataSource() }.getOrNull() ?: continue
                try {
                    val spec = DataSpec.Builder()
                        .setUri(uri)
                        .setFlags(DataSpec.FLAG_ALLOW_CACHE_FRAGMENTATION)
                        .build()
                    val listener = object : CacheWriter.ProgressListener {
                        override fun onProgress(requestLength: Long, bytesCached: Long, newBytesCached: Long) {
                            if (bytesCached >= PRELOAD_BYTES) throw Enough()
                        }
                    }
                    CacheWriter(ds, spec, null, listener).cache()
                } catch (_: Enough) {
                    // 预取够了，正常结束
                } catch (_: IOException) {
                    // 网络/服务端问题：预加载失败不影响正常播放
                } finally {
                    runCatching { ds.close() }
                }
            }
        }
    }

    fun cancel() {
        job?.cancel()
        job = null
    }

    private class Enough : IOException()
}
