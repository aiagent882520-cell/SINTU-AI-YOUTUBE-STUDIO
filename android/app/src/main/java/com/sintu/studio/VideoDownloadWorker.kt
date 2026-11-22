package com.sintu.studio

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import android.net.Uri
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ForegroundInfo
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.io.IOException
import java.util.concurrent.CancellationException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Durable, network-constrained MP4 download. WorkManager retries transient failures after app/process death. */
class VideoDownloadWorker(appContext: Context, params: WorkerParameters) :
    CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val videoId = inputData.getString(KEY_VIDEO_ID)
            ?.takeIf { it.matches(Regex("[a-f0-9]{32}")) }
            ?: return@withContext Result.failure(workDataOf(KEY_ERROR to "Invalid SINTU video ID."))

        val baseUrl = applicationContext.getSharedPreferences("sintu_app", Context.MODE_PRIVATE)
            .getString("api_base_url", "http://127.0.0.1:8000/")
            ?: "http://127.0.0.1:8000/"

        try {
            setForeground(createForegroundInfo())
            setProgress(workDataOf(KEY_PROGRESS to "Downloading MP4 to Movies/SINTU…"))
            val uri = SintuApi(applicationContext, baseUrl).downloadVideoToGallery(
                applicationContext,
                videoId
            ) { downloadedBytes, totalBytes ->
                setProgress(workDataOf(KEY_PROGRESS to progressDescription(downloadedBytes, totalBytes)))
                setForeground(createForegroundInfo(downloadedBytes, totalBytes))
            }
            Result.success(workDataOf(KEY_SAVED_URI to uri.toString(), KEY_VIDEO_ID to videoId))
        } catch (error: VideoDownloadHttpException) {
            if (isRetryableVideoDownloadStatus(error.statusCode) && runAttemptCount < MAX_RETRIES) {
                Result.retry()
            } else {
                Result.failure(workDataOf(KEY_ERROR to error.message.orEmpty().take(400)))
            }
        } catch (error: IOException) {
            if (runAttemptCount < MAX_RETRIES) Result.retry()
            else Result.failure(workDataOf(KEY_ERROR to (error.message ?: "Network download failed.").take(400)))
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            Result.failure(workDataOf(KEY_ERROR to (error.message ?: "MP4 download failed.").take(400)))
        }
    }

    private fun createForegroundInfo(downloadedBytes: Long? = null, totalBytes: Long? = null): ForegroundInfo {
        val context = applicationContext
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    DOWNLOAD_CHANNEL_ID,
                    "SINTU video downloads",
                    NotificationManager.IMPORTANCE_LOW
                ).apply {
                    description = "Shows active MP4 downloads and their status."
                    setShowBadge(false)
                }
            )
        }
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
        val contentIntent = launchIntent?.let {
            PendingIntent.getActivity(
                context,
                NOTIFICATION_ID,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        }
        val builder = NotificationCompat.Builder(context, DOWNLOAD_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("SINTU MP4 download")
            .setContentText(progressDescription(downloadedBytes ?: 0L, totalBytes ?: 0L))
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setPriority(NotificationCompat.PRIORITY_LOW)
        if (downloadedBytes != null && totalBytes != null && totalBytes > 0L) {
            builder.setProgress(100, downloadProgressPercent(downloadedBytes, totalBytes) ?: 0, false)
        } else {
            builder.setProgress(0, 0, true)
        }
        val notification = builder.build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        const val TAG = "sintu-video-download"
        private const val DOWNLOAD_CHANNEL_ID = "sintu-video-downloads"
        private const val NOTIFICATION_ID = 29401
        const val KEY_VIDEO_ID = "video_id"
        const val KEY_SAVED_URI = "saved_uri"
        const val KEY_ERROR = "error"
        const val KEY_PROGRESS = "progress"
        private const val MAX_RETRIES = 5

        internal fun progressDescription(downloadedBytes: Long, totalBytes: Long): String {
            val downloadedMb = downloadedBytes.coerceAtLeast(0L) / (1024.0 * 1024.0)
            return if (totalBytes > 0L) {
                val totalMb = totalBytes / (1024.0 * 1024.0)
                "Downloading to Movies/SINTU… ${downloadProgressPercent(downloadedBytes, totalBytes)}% " +
                    "(${String.format(java.util.Locale.US, "%.1f", downloadedMb)}/" +
                    "${String.format(java.util.Locale.US, "%.1f", totalMb)} MB)"
            } else {
                "Downloading to Movies/SINTU… ${String.format(java.util.Locale.US, "%.1f", downloadedMb)} MB"
            }
        }

        fun enqueue(context: Context, videoId: String): java.util.UUID {
            require(videoId.matches(Regex("[a-f0-9]{32}"))) { "Invalid SINTU video ID." }
            val request = OneTimeWorkRequestBuilder<VideoDownloadWorker>()
                .setInputData(workDataOf(KEY_VIDEO_ID to videoId))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 20, TimeUnit.SECONDS)
                .addTag(TAG)
                .addTag("sintu-video-download-$videoId")
                .build()
            WorkManager.getInstance(context.applicationContext)
                .enqueueUniqueWork("sintu-video-download-$videoId", androidx.work.ExistingWorkPolicy.KEEP, request)
            return request.id
        }
    }
}


internal fun downloadProgressPercent(downloadedBytes: Long, totalBytes: Long): Int? {
    if (totalBytes <= 0L) return null
    val bounded = downloadedBytes.coerceIn(0L, totalBytes)
    return ((bounded.toDouble() / totalBytes.toDouble()) * 100.0).toInt().coerceIn(0, 100)
}
