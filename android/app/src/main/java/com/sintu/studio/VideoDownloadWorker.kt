package com.sintu.studio

import android.content.Context
import android.net.Uri
import androidx.work.BackoffPolicy
import androidx.work.Constraints
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
            setProgress(workDataOf(KEY_PROGRESS to "Downloading MP4 to Movies/SINTU…"))
            val uri = SintuApi(applicationContext, baseUrl).downloadVideoToGallery(applicationContext, videoId)
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

    companion object {
        const val TAG = "sintu-video-download"
        const val KEY_VIDEO_ID = "video_id"
        const val KEY_SAVED_URI = "saved_uri"
        const val KEY_ERROR = "error"
        const val KEY_PROGRESS = "progress"
        private const val MAX_RETRIES = 5

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
