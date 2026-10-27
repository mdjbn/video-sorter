package com.videosorter.app.data

import android.content.Context
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.database.StandaloneDatabaseProvider
import java.io.File

/**
 * 播放缓存：所有播放请求都经过 CacheDataSource，预加载写进来的数据在真正播放时直接命中。
 *
 * 用途：上下滑切换视频时，下一个视频已经缓存了开头几 MB，起播明显更快；
 * HLS 切片也会被缓存，重复播放同一视频不再走网络。
 */
object MediaCache {
    private const val MAX_BYTES = 512L * 1024 * 1024

    @Volatile
    private var cache: SimpleCache? = null

    fun init(ctx: Context) {
        if (cache != null) return
        synchronized(this) {
            if (cache != null) return
            val dir = File(ctx.cacheDir, "media")
            cache = SimpleCache(
                dir,
                LeastRecentlyUsedCacheEvictor(MAX_BYTES),
                StandaloneDatabaseProvider(ctx),
            )
        }
    }

    fun httpFactory(headers: Map<String, String>): DefaultHttpDataSource.Factory =
        DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(headers)
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15000)
            .setReadTimeoutMs(20000)

    fun sourceFactory(headers: Map<String, String>): CacheDataSource.Factory {
        val c = cache ?: error("MediaCache 未初始化")
        return CacheDataSource.Factory()
            .setCache(c)
            .setUpstreamDataSourceFactory(httpFactory(headers))
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
    }

    fun sizeBytes(): Long = cache?.cacheSpace ?: 0L
}
