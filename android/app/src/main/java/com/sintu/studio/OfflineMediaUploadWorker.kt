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
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.HttpException

internal fun isRetryableOfflineUploadHttpStatus(code: Int): Boolean =
    code == 408 || code == 429 || code in 500..599

internal fun sha256Hex(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

internal fun sha256File(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().buffered().use { input ->
        val buffer = ByteArray(64 * 1024)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            digest.update(buffer, 0, count)
        }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
}

/** WorkManager persists the job and the server session ID; each retry resumes from its verified offset. */
class OfflineMediaUploadWorker(appContext: Context, params: WorkerParameters) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val rawUri = inputData.getString(KEY_URI) ?: return@withContext Result.failure(failureData("Missing media URI."))
        val filename = inputData.getString(KEY_FILENAME)?.takeIf { it.isNotBlank() }
            ?: return@withContext Result.failure(failureData("Missing media filename."))
        val mimeType = inputData.getString(KEY_MIME)?.ifBlank { null } ?: "application/octet-stream"
        val uri = try { Uri.parse(rawUri) } catch (_: Exception) {
            return@withContext Result.failure(failureData("Invalid media URI."))
        }
        if (uri.scheme != "content") return@withContext Result.failure(failureData("Only Android document-provider URIs are accepted."))

        val baseUrl = applicationContext.getSharedPreferences("sintu_app", Context.MODE_PRIVATE)
            .getString("api_base_url", "http://127.0.0.1:8000/") ?: "http://127.0.0.1:8000/"
        val temp = File(applicationContext.cacheDir, "offline-media-$id.part")
        val sessionPrefs = applicationContext.getSharedPreferences("sintu_upload_sessions", Context.MODE_PRIVATE)
        val sessionKey = "upload_$id"
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
                        if (total > MAX_BYTES) return@withContext Result.failure(failureData("Media exceeds the 256 MiB upload limit."))
                        output.write(buffer, 0, count)
                    }
                    output.fd.sync()
                }
            } ?: return@withContext Result.failure(failureData("Android cannot read the selected media URI. Re-select the file."))
            if (!temp.isFile || temp.length() <= 0L) return@withContext Result.failure(failureData("Selected media file is empty."))

            val api = SintuApi(applicationContext, baseUrl)
            val fileSha = sha256File(temp)
            var uploadId = sessionPrefs.getString(sessionKey, null)
            var status: Map<String, Any?>? = null
            if (uploadId != null) {
                try { status = api.offlineMediaUploadStatus(activeUploadId) }
                catch (error: HttpException) {
                    if (error.code() == 404) { uploadId = null } else throw error
                }
            }
            if (uploadId == null) {
                val created = api.createOfflineMediaUpload(filename, temp.length(), fileSha)
                uploadId = created["upload_id"]?.toString()
                    ?: throw IllegalStateException("Server did not return an upload session ID.")
                sessionPrefs.edit().putString(sessionKey, uploadId).apply()
                status = api.offlineMediaUploadStatus(uploadId)
            }
            if (status?.get("size_bytes").asLongOrNull() != temp.length()) {
                throw IllegalStateException("Saved upload session does not match the selected media size.")
            }
            val activeUploadId = uploadId ?: throw IllegalStateException("Server did not provide an upload session ID.")
            var offset = status?.get("offset").asLongOrNull() ?: 0L
            if (offset !in 0..temp.length()) throw IllegalStateException("Server returned an invalid upload offset.")
            RandomAccessFile(temp, "r").use { source ->
                while (offset < temp.length()) {
                    if (isStopped) return@withContext Result.retry()
                    val count = minOf(CHUNK_BYTES.toLong(), temp.length() - offset).toInt()
                    val bytes = ByteArray(count)
                    source.seek(offset)
                    source.readFully(bytes)
                    try {
                        val response = api.uploadOfflineMediaChunk(activeUploadId, offset, bytes, sha256Hex(bytes))
                        offset = response["offset"].asLongOrNull()
                            ?: throw IllegalStateException("Server did not confirm the chunk offset.")
                    } catch (conflict: HttpException) {
                        if (conflict.code() != 409) throw conflict
                        val refreshed = api.offlineMediaUploadStatus(uploadId)
                        val serverOffset = refreshed["offset"].asLongOrNull()
                            ?: throw IllegalStateException("Server did not return a resume offset.")
                        if (serverOffset == offset) throw conflict
                        offset = serverOffset
                    }
                    if (offset !in 0..temp.length()) throw IllegalStateException("Server returned an invalid upload offset.")
                }
            }
            val completed = api.completeOfflineMediaUpload(activeUploadId)
            val media = completed["media"] as? Map<*, *>
            val sha = media?.get("sha256")?.toString().orEmpty()
            if (sha != fileSha) throw IllegalStateException("Server completed the upload with an unexpected SHA-256.")
            sessionPrefs.edit().remove(sessionKey).apply()
            Result.success(workDataOf("sha256" to sha, "duplicate" to (completed["duplicate"] as? Boolean ?: false), "filename" to filename))
        } catch (error: HttpException) {
            if (isRetryableOfflineUploadHttpStatus(error.code()) || error.code() == 409) Result.retry()
            else Result.failure(failureData(error.message().take(300)))
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

    private fun Any?.asLongOrNull(): Long? = (this as? Number)?.toLong() ?: this?.toString()?.toLongOrNull()
    private fun failureData(message: String) = workDataOf(KEY_ERROR to message.take(500))

    companion object {
        const val TAG = "sintu-offline-media-upload"
        const val KEY_URI = "content_uri"
        const val KEY_FILENAME = "filename"
        const val KEY_MIME = "mime_type"
        const val KEY_ERROR = "error"
        private const val MAX_BYTES = 256L * 1024L * 1024L
        private const val CHUNK_BYTES = 4 * 1024 * 1024

        fun enqueue(context: Context, uri: Uri, filename: String, mimeType: String): UUID {
            require(uri.scheme == "content") { "Only Android document-provider URIs are supported." }
            require(filename.isNotBlank() && filename.length <= 180) { "Invalid media filename." }
            val request = OneTimeWorkRequestBuilder<OfflineMediaUploadWorker>()
                .setInputData(Data.Builder().putString(KEY_URI, uri.toString()).putString(KEY_FILENAME, filename).putString(KEY_MIME, mimeType).build())
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 15, TimeUnit.SECONDS)
                .addTag(TAG).build()
            WorkManager.getInstance(context.applicationContext)
                .enqueueUniqueWork("sintu-offline-media-${request.id}", ExistingWorkPolicy.KEEP, request)
            return request.id
        }
    }
}