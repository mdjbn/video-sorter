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
 *
 * 上限可配置（设置 → 缓存与储存 → 本机播放缓存上限），存 SharedPreferences `media_cache_mb`。
 * **生效时机是「下一次 init」**：正在播的 ExoPlayer / CacheDataSource 持有旧 SimpleCache 实例，
 * 当场 release 会让它们抛 IllegalStateException，所以 [setLimitMb] 只写偏好并丢弃实例，
 * 由下一次 [init]（MainActivity.onCreate，或播放页发现缓存被丢弃时）按新上限重建。
 */
object MediaCache {
    /** 没设过偏好时的默认上限 */
    const val DEFAULT_MB = 512

    @Volatile
    private var cache: SimpleCache? = null

    @Volatile
    private var limitMb: Int = DEFAULT_MB

    /** 本次进程内 SimpleCache 实际建过几次（诊断/单测用）+ 建它时用的上限 */
    @Volatile
    var buildCount: Int = 0
        private set

    /** 用当前偏好里的上限建（或复用）缓存。多次调用幂等。 */
    fun init(ctx: Context) {
        if (cache != null) return
        val app = ctx.applicationContext ?: ctx
        val mb = Session(app).mediaCacheMb
        // 先同步登记上限（立刻可读，避免 UI 上「上限」短暂显示默认值），再建实例
        synchronized(this) { limitMb = normalizeMb(mb) }
        buildIfNeeded(app)
    }

    /** 已建就复用；被 setLimitMb 丢弃过就按当前偏好重建。并发安全（播放页/预加载/启动都会调）。 */
    fun buildIfNeeded(ctx: Context) {
        if (cache != null) return
        val app = ctx.applicationContext ?: ctx
        val mb = normalizeMb(Session(app).mediaCacheMb)
        synchronized(this) {
            if (cache != null) return
            limitMb = mb
            cache = build(app, mb)
        }
    }

    /**
     * 改上限：先 release 旧实例再改字段（顺序不能反，否则 build 里可能拿到已释放的实例），
     * 全程 synchronized。释放后 cache 是 null，下一次 [init] 会用新上限重建。
     */
    fun setLimitMb(ctx: Context, mb: Int) {
        val app = ctx.applicationContext ?: ctx
        val safe = normalizeMb(mb)
        Session(app).mediaCacheMb = safe
        synchronized(this) {
            val old = cache
            cache = null
            limitMb = safe
            old?.let { runCatching { it.release() } }
        }
    }

    /** 当前上限（字节）；偏好里改过但还没生效时仍返回「正在用的」那个 */
    fun limitBytes(): Long = limitMb.toLong() * 1024L * 1024L

    /** 偏好里保存的上限（MB）—— 设置页显示「下次生效」用 */
    fun savedMb(ctx: Context): Int = normalizeMb(Session(ctx.applicationContext ?: ctx).mediaCacheMb)

    /** 正在使用的上限（MB） */
    fun activeMb(): Int = limitMb

    fun httpFactory(headers: Map<String, String>): DefaultHttpDataSource.Factory =
        DefaultHttpDataSource.Factory()
            .setDefaultRequestProperties(headers)
            .setAllowCrossProtocolRedirects(true)
            .setConnectTimeoutMs(15000)
            .setReadTimeoutMs(20000)

    fun sourceFactory(headers: Map<String, String>): CacheDataSource.Factory = sourceFactory(headers, null)

    /**
     * 播放页/预加载入口：传 ctx 时会在缓存被 [setLimitMb] 丢弃后按新上限重建（下次进播放页即生效）；
     * 不传就要求已经 init 过，否则报「未初始化」。
     */
    fun sourceFactory(headers: Map<String, String>, ctx: Context?): CacheDataSource.Factory {
        if (ctx != null) buildIfNeeded(ctx)
        return CacheDataSource.Factory()
            .setCache(requireCache())
            .setUpstreamDataSourceFactory(httpFactory(headers))
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
    }

    fun requireCache(): SimpleCache = cache ?: error("MediaCache 未初始化")

    fun sizeBytes(): Long = cache?.cacheSpace ?: 0L

    private fun build(app: Context, mb: Int): SimpleCache {
        buildCount += 1
        return SimpleCache(
            File(app.cacheDir, "media"),
            LeastRecentlyUsedCacheEvictor(mb.toLong() * 1024L * 1024L),
            StandaloneDatabaseProvider(app),
        )
    }

    private fun normalizeMb(mb: Int): Int =
        mb.coerceIn(Session.CACHE_MB_MIN, Session.CACHE_MB_MAX)
}
