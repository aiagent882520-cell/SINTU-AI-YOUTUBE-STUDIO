package com.sintu.studio

import android.content.Context
import android.net.Uri
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException

internal fun isRetryableOfflineUploadHttpStatus(code: Int): Boolean =
    code == 408 || code == 429 || code in 500..599

/**
 * Resumable across process death at the job level: WorkManager persists the request and retries
 * the whole file transfer when connectivity returns. Individual uploads are streamed from a
 * temporary file; chunk-level resume is intentionally not claimed.
 */
class OfflineMediaUploadWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val rawUri = inputData.getString(KEY_URI) ?: return@withContext Result.failure(failureData("Missing media URI."))
        val filename = inputData.getString(KEY_FILENAME)?.takeIf { it.isNotBlank() }
            ?: return@withContext Result.failure(error("Missing media filename."))
        val mimeType = inputData.getString(KEY_MIME)?.ifBlank { null } ?: "application/octet-stream"
        val uri = try { Uri.parse(rawUri) } catch (_: Exception) {
            return@withContext Result.failure(error("Invalid media URI."))
        }
        if (uri.scheme != "content") return@withContext Result.failure(error("Only Android document-provider URIs are accepted."))

        val baseUrl = applicationContext.getSharedPreferences("sintu_app", Context.MODE_PRIVATE)
            .getString("api_base_url", "http://127.0.0.1:8000/")
            ?: "http://127.0.0.1:8000/"
        val temp = File(applicationContext.cacheDir, "offline-media-$id.part")
        try {
            applicationContext.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(temp).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        if (isStopped) return@withContext Result.retry()
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        if (total > MAX_BYTES) {
                            return@withContext Result.failure(error("Media exceeds the 256 MiB upload limit."))
                        }
                        output.write(buffer, 0, count)
                    }
                    output.fd.sync()
                }
            } ?: return@withContext Result.failure(error("Android cannot read the selected media URI. Re-select the file."))
            if (!temp.isFile || temp.length() <= 0L) {
                return@withContext Result.failure(error("Selected media file is empty."))
            }

            val api = SintuApi(applicationContext, baseUrl)
            val response = api.importOfflineMedia(temp, filename, mimeType)
            val media = response["media"] as? Map<*, *>
            val sha = media?.get("sha256")?.toString().orEmpty()
            Result.success(workDataOf(
                "sha256" to sha,
                "duplicate" to (response["duplicate"] as? Boolean ?: false),
                "filename" to filename
            ))
        } catch (error: HttpException) {
            if (isRetryableOfflineUploadHttpStatus(error.code())) {
                Result.retry()
            } else {
                Result.failure(error(error.message().take(300)))
            }
        } catch (error: IOException) {
            Result.retry()
        } catch (error: SecurityException) {
            Result.failure(failureData("Android document permission expired. Re-select the media file."))
        } catch (error: Exception) {
            Result.failure(failureData(error.message ?: "Offline media upload failed."))
        } finally {
            temp.delete()
        }
    }

    private fun failureData(message: String) = workDataOf(KEY_ERROR to message.take(500))

    companion object {
        const val TAG = "sintu-offline-media-upload"
        const val KEY_URI = "content_uri"
        const val KEY_FILENAME = "filename"
        const val KEY_MIME = "mime_type"
        const val KEY_ERROR = "error"
        private const val MAX_BYTES = 256L * 1024L * 1024L

        fun enqueue(context: Context, uri: Uri, filename: String, mimeType: String): UUID {
            require(uri.scheme == "content") { "Only Android document-provider URIs are supported." }
            require(filename.isNotBlank() && filename.length <= 180) { "Invalid media filename." }
            val request = OneTimeWorkRequestBuilder<OfflineMediaUploadWorker>()
                .setInputData(Data.Builder()
                    .putString(KEY_URI, uri.toString())
                    .putString(KEY_FILENAME, filename)
                    .putString(KEY_MIME, mimeType)
                    .build())
                .setConstraints(Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .addTag(TAG)
                .build()
            WorkManager.getInstance(context.applicationContext)
                .enqueueUniqueWork("sintu-offline-media-${request.id}", ExistingWorkPolicy.KEEP, request)
            return request.id
        }
    }
}
