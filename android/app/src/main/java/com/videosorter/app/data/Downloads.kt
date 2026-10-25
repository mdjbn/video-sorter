package com.videosorter.app.data

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment

/**
 * 「下载到手机」：用系统 DownloadManager 抓服务器的 /raw 流（支持 Range，断点续传由系统负责）。
 * 文件落在 下载/VideoSorter/ 下，通知栏可见进度。
 */
object Downloads {
    fun save(context: Context, api: Api, video: Video): Long {
        val url = "${api.base}/api/videos/${video.id}/raw"
        val req = DownloadManager.Request(Uri.parse(url))
            .setTitle(video.name)
            .setDescription("视频整理 · 下载到本机")
            .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, "VideoSorter/${video.name}")
            .setMimeType("video/*")
        api.token?.takeIf { it.isNotEmpty() }?.let { req.addRequestHeader("Authorization", "Bearer $it") }
        val dm = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        return dm.enqueue(req)
    }
}
