package com.sintu.studio

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import okhttp3.Cookie
import okhttp3.ResponseBody
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.RequestBody
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import java.io.File
import java.io.ByteArrayOutputStream
import retrofit2.Response
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Streaming
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Header
import retrofit2.http.PUT

data class ImageGenerateRequest(
    val prompt: String,
    val kind: String = "scene",
    val aspect: String = "portrait"
)
data class ImageGenerationResponse(
    val image_id: String,
    val url: String = "",
    val kind: String = "scene",
    val aspect: String = "portrait",
    val width: Int = 0,
    val height: Int = 0,
    val format: String = "",
    val size_bytes: Long = 0,
    val provider: String = "",
    val local: Boolean = true,
    val notice: String = ""
)

data class LoginRequest(val username: String, val password: String, val otp_code: String? = null)
data class LoginResponse(val authenticated: Boolean = false, val username: String = "", val role: String = "")
data class SessionResponse(val authenticated: Boolean = false, val username: String? = null, val role: String? = null, val is_owner: Boolean = false, val features: List<String> = emptyList())
data class ConversationCreateRequest(val title: String = "", val workflow: String = "content")
data class ConversationCreateResponse(val id: Int, val title: String, val workflow: String)
data class ConversationDto(val id: Int, val title: String, val workflow: String, val last_message: String? = null)
data class ConversationsResponse(val conversations: List<ConversationDto> = emptyList())
data class MessageDto(
    val id: Int,
    val role: String,
    val content: String,
    val provider: String = "",
    val model: String = "",
    val status: String = "completed"
)
data class ConversationDtoFull(val id: Int, val title: String, val workflow: String)
data class ConversationDetailResponse(val conversation: ConversationDtoFull, val messages: List<MessageDto> = emptyList())
data class SendMessageRequest(val content: String)
data class SendMessageResponse(val conversation_id: Int, val message: MessageDto)
data class ProjectCreateRequest(
    val name: String,
    val brief: String,
    val format_id: String = "youtube-shorts",
    val language: String = "Hindi",
    val duration_seconds: Int = 60
)
data class ProjectDto(
    val id: String,
    val name: String,
    val format_id: String,
    val status: String,
    val updated_at: String? = null
)
data class ProjectCreateResponse(val project: ProjectDto)
data class ProjectListResponse(val projects: List<ProjectDto> = emptyList())
data class ProjectGenerateRequest(val workflow: String = "shorts")
data class TaskDto(
    val id: Int,
    val status: String,
    val output: String? = null,
    val provider: String? = null,
    val model: String? = null
)
data class ProjectGenerateResponse(val project: ProjectDto, val task: TaskDto)
data class ProductionRunCreateRequest(val format_id: String, val topic: String)
data class ProductionRunCreateResponse(
    val run_id: String,
    val status: String = "queued",
    val detail: String = ""
)
data class ProductionMediaRequest(
    val scene_prompts: List<String> = emptyList(),
    val narration: String? = null,
    val subtitles: List<String> = emptyList(),
    val burn_subtitles: Boolean = true,
    val sound_effects_enabled: Boolean = true,
    val sound_effects_volume: Double = 0.18,
    val seconds_per_scene: Int = 4,
    val resolution: String? = "720x1280",
    val fps: Int = 24,
    val quality: String = "standard"
)

internal fun sessionCookieOrigin(url: HttpUrl): String = "${url.scheme}://${url.host}:${url.port}"

internal class PersistentSessionCookieJar(private val store: SessionCookieStore) : CookieJar {
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        cookies.firstOrNull { it.name == SESSION_COOKIE && it.matches(url) }?.let { cookie ->
            if (cookie.expiresAt <= System.currentTimeMillis()) store.clear()
            else store.save(cookie.toString(), sessionCookieOrigin(url))
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        // Never re-parse a stored cookie against an arbitrary newly configured host:
        // doing so would silently rebind the old session to that host.
        val raw = store.read(sessionCookieOrigin(url)) ?: return emptyList()
        val cookie = Cookie.parse(url, raw) ?: run {
            store.clear()
            return emptyList()
        }
        if (cookie.expiresAt <= System.currentTimeMillis() || !cookie.matches(url)) {
            store.clear()
            return emptyList()
        }
        return listOf(cookie)
    }

    companion object {
        private const val SESSION_COOKIE = "sintu_admin_session"
    }
}

private interface SintuService {
    @POST("api/auth/login")
    suspend fun login(@Body body: LoginRequest): Response<LoginResponse>

    @POST("api/auth/logout")
    suspend fun logout(): Response<Map<String, Any>>

    @GET("api/auth/session")
    suspend fun session(): Response<SessionResponse>

    @GET("api/images/capabilities")
    suspend fun imageCapabilities(): Response<Map<String, Any?>>

    @POST("api/images")
    suspend fun generateImage(@Body body: ImageGenerateRequest): Response<ImageGenerationResponse>

    @Streaming
    @GET("api/images/{imageId}")
    suspend fun imageFile(@Path("imageId") imageId: String): Response<ResponseBody>


    @GET("api/providers")
    suspend fun providerStatus(): Response<Map<String, Any?>>

    @GET("api/conversations")
    suspend fun conversations(): Response<ConversationsResponse>

    @POST("api/conversations")
    suspend fun createConversation(@Body body: ConversationCreateRequest): Response<ConversationCreateResponse>

    @GET("api/conversations/{id}")
    suspend fun conversation(@Path("id") id: Int): Response<ConversationDetailResponse>

    @POST("api/conversations/{id}/messages")
    suspend fun sendMessage(@Path("id") id: Int, @Body body: SendMessageRequest): Response<SendMessageResponse>

    @DELETE("api/conversations/{id}")
    suspend fun deleteConversation(@Path("id") id: Int): Response<Map<String, Any>>

    @GET("api/projects")
    suspend fun projects(): Response<ProjectListResponse>

    @POST("api/projects")
    suspend fun createProject(@Body body: ProjectCreateRequest): Response<ProjectCreateResponse>

    @POST("api/projects/{id}/generate")
    suspend fun generateProject(@Path("id") id: String, @Body body: ProjectGenerateRequest): Response<ProjectGenerateResponse>

    @POST("api/production/runs")
    suspend fun startProductionRun(@Body body: ProductionRunCreateRequest): Response<ProductionRunCreateResponse>

    @GET("api/production/runs/{runId}")
    suspend fun productionRunStatus(@Path("runId") runId: String): Response<Map<String, Any?>>

    @POST("api/production/runs/{runId}/produce-media")
    suspend fun produceApprovedMedia(
        @Path("runId") runId: String,
        @Body body: ProductionMediaRequest
    ): Response<Map<String, Any?>>

    @POST("api/offline-media/uploads")
    suspend fun createOfflineMediaUpload(@Query("filename") filename: String, @Query("size_bytes") sizeBytes: Long, @Query("sha256") sha256: String): Response<Map<String, Any?>>

    @GET("api/offline-media/uploads/{uploadId}")
    suspend fun offlineMediaUploadStatus(@Path("uploadId") uploadId: String): Response<Map<String, Any?>>

    @PUT("api/offline-media/uploads/{uploadId}/chunks")
    suspend fun uploadOfflineMediaChunk(@Path("uploadId") uploadId: String, @Query("offset") offset: Long, @Header("X-Chunk-SHA256") chunkSha256: String, @Body body: RequestBody): Response<Map<String, Any?>>

    @POST("api/offline-media/uploads/{uploadId}/complete")
    suspend fun completeOfflineMediaUpload(@Path("uploadId") uploadId: String): Response<Map<String, Any?>>

    @Streaming
    @GET("api/videos/{videoId}")
    suspend fun videoFile(@Path("videoId") videoId: String): Response<ResponseBody>
}

internal class VideoDownloadHttpException(val statusCode: Int, message: String) : java.io.IOException(message)

internal fun isRetryableVideoDownloadStatus(code: Int): Boolean =
    code == 408 || code == 429 || code in 500..599

class SintuApi(context: Context, baseUrl: String) {
    val normalizedBaseUrl: String = normalizeBaseUrl(baseUrl)
    private val sessionStore = SecureSessionStore(context.applicationContext)
    private val service: SintuService

    init {
        val client = OkHttpClient.Builder()
            .cookieJar(PersistentSessionCookieJar(sessionStore))
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .callTimeout(240, TimeUnit.SECONDS)
            .build()
        service = Retrofit.Builder()
            .baseUrl(normalizedBaseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SintuService::class.java)
    }

    suspend fun login(username: String, password: String, otpCode: String? = null): LoginResponse =
        service.login(LoginRequest(username, password, otpCode)).bodyOrThrow()

    suspend fun logout() {
        try { service.logout() } finally { sessionStore.clear() }
    }

    suspend fun session(): SessionResponse = service.session().bodyOrThrow()
    suspend fun imageCapabilities(): Map<String, Any?> = service.imageCapabilities().bodyOrThrow()

    suspend fun generateImage(prompt: String, kind: String, aspect: String): ImageGenerationResponse =
        service.generateImage(ImageGenerateRequest(prompt.trim(), kind, aspect)).bodyOrThrow()

    suspend fun downloadImageBytes(imageId: String): ByteArray = withContext(Dispatchers.IO) {
        require(imageId.matches(Regex("[a-f0-9]{32}"))) { "Invalid SINTU image ID." }
        val response = service.imageFile(imageId)
        if (!response.isSuccessful) {
            val detail = response.errorBody()?.string()?.take(1000)
            throw IllegalStateException(detail?.takeIf { it.isNotBlank() }
                ?: "SINTU image download failed with HTTP ${response.code()}.")
        }
        val body = response.body() ?: throw IllegalStateException("SINTU server returned an empty image.")
        try {
            if (body.contentLength() > MAX_IMAGE_DOWNLOAD_BYTES) {
                throw IllegalStateException("Image exceeds the 15 MB phone-download limit.")
            }
            val output = ByteArrayOutputStream(
                body.contentLength().takeIf { it in 1..MAX_IMAGE_DOWNLOAD_BYTES.toLong() }?.toInt() ?: 64 * 1024
            )
            body.byteStream().use { input ->
                val buffer = ByteArray(32 * 1024)
                var total = 0
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= MAX_IMAGE_DOWNLOAD_BYTES) {
                        "Image response exceeds the 15 MB phone-download limit."
                    }
                    output.write(buffer, 0, count)
                }
            }
            val bytes = output.toByteArray()
            require(bytes.isNotEmpty()) { "SINTU server returned an empty image." }
            require(bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() && bytes[2] == 0xFF.toByte()) {
                "SINTU image response is not a valid JPEG."
            }
            bytes
        } finally { body.close() }
    }

    suspend fun saveImageToGallery(context: Context, imageId: String): Uri =
        withContext(Dispatchers.IO) {
            require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                "Gallery image save requires Android 10 or newer."
            }
            val bytes = downloadImageBytes(imageId)
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, "SINTU_${imageId}.jpg")
                put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/SINTU")
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val resolver = context.applicationContext.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Android could not create a Pictures/SINTU image.")
            try {
                resolver.openOutputStream(uri, "w")?.use { it.write(bytes); it.flush() }
                    ?: throw IllegalStateException("Android could not open the image destination.")
                resolver.update(uri, ContentValues().apply {
                    put(MediaStore.MediaColumns.IS_PENDING, 0)
                }, null, null)
                uri
            } catch (error: Exception) {
                resolver.delete(uri, null, null)
                throw error
            }
        }

    suspend fun providerStatus(): Map<String, Any?> = service.providerStatus().bodyOrThrow()
    suspend fun conversations(): ConversationsResponse = service.conversations().bodyOrThrow()
    suspend fun createConversation(workflow: String): ConversationCreateResponse =
        service.createConversation(ConversationCreateRequest(workflow = workflow)).bodyOrThrow()
    suspend fun conversation(id: Int): ConversationDetailResponse = service.conversation(id).bodyOrThrow()
    suspend fun sendMessage(id: Int, content: String): SendMessageResponse =
        service.sendMessage(id, SendMessageRequest(content)).bodyOrThrow()
    suspend fun deleteConversation(id: Int) { service.deleteConversation(id).bodyOrThrow() }
    suspend fun projects(): ProjectListResponse = service.projects().bodyOrThrow()
    suspend fun createProject(body: ProjectCreateRequest): ProjectCreateResponse =
        service.createProject(body).bodyOrThrow()
    suspend fun generateProject(id: String): ProjectGenerateResponse =
        service.generateProject(id, ProjectGenerateRequest()).bodyOrThrow()
    suspend fun startProductionRun(formatId: String, topic: String): ProductionRunCreateResponse =
        service.startProductionRun(ProductionRunCreateRequest(formatId, topic)).bodyOrThrow()
    suspend fun productionRunStatus(runId: String): Map<String, Any?> =
        service.productionRunStatus(runId).bodyOrThrow()
    suspend fun produceApprovedMedia(
        runId: String,
        resolution: String = "720x1280"
    ): Map<String, Any?> = service.produceApprovedMedia(
        runId,
        ProductionMediaRequest(resolution = resolution, fps = 24, quality = "standard")
    ).bodyOrThrow()

    suspend fun createOfflineMediaUpload(filename: String, sizeBytes: Long, sha256: String): Map<String, Any?> =
        service.createOfflineMediaUpload(filename, sizeBytes, sha256).bodyOrThrow()

    suspend fun offlineMediaUploadStatus(uploadId: String): Map<String, Any?> =
        service.offlineMediaUploadStatus(uploadId).bodyOrThrow()

    suspend fun uploadOfflineMediaChunk(uploadId: String, offset: Long, bytes: ByteArray, sha256: String): Map<String, Any?> {
        val mediaType = "application/octet-stream".toMediaTypeOrNull()!!
        return service.uploadOfflineMediaChunk(uploadId, offset, sha256, okhttp3.RequestBody.create(mediaType, bytes)).bodyOrThrow()
    }

    suspend fun completeOfflineMediaUpload(uploadId: String): Map<String, Any?> =
        service.completeOfflineMediaUpload(uploadId).bodyOrThrow()

    suspend fun downloadVideoToGallery(context: Context, videoId: String): Uri =
        withContext(Dispatchers.IO) {
            require(videoId.matches(Regex("[a-f0-9]{32}"))) { "Invalid SINTU video ID." }
            require(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                "Gallery download requires Android 10 or newer."
            }
            val response = service.videoFile(videoId)
            if (!response.isSuccessful) {
                val detail = response.errorBody()?.string()?.take(1000)
                throw VideoDownloadHttpException(response.code(), detail?.takeIf { it.isNotBlank() }
                    ?: "SINTU video download failed with HTTP ${response.code()}.")
            }
            val body = response.body()
                ?: throw IllegalStateException("SINTU server returned an empty MP4.")
            val maxBytes = 500L * 1024L * 1024L
            try {
                if (body.contentLength() > maxBytes) {
                    throw IllegalStateException("MP4 exceeds the 500 MB phone-download limit.")
                }
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, "SINTU_${videoId}.mp4")
                    put(MediaStore.MediaColumns.MIME_TYPE, "video/mp4")
                    put(MediaStore.MediaColumns.RELATIVE_PATH,
                        Environment.DIRECTORY_MOVIES + "/SINTU")
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
                val resolver = context.applicationContext.contentResolver
                val uri = resolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
                    ?: throw IllegalStateException("Android could not create a Movies/SINTU file.")
                try {
                    val output = resolver.openOutputStream(uri, "w")
                        ?: throw IllegalStateException("Android could not open the MP4 destination.")
                    body.byteStream().use { input ->
                        output.use { destination ->
                            val buffer = ByteArray(64 * 1024)
                            var total = 0L
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                total += count
                                if (total > maxBytes) {
                                    throw IllegalStateException("MP4 exceeded the 500 MB download limit.")
                                }
                                destination.write(buffer, 0, count)
                            }
                            destination.flush()
                        }
                    }
                    val ready = ContentValues().apply {
                        put(MediaStore.MediaColumns.IS_PENDING, 0)
                    }
                    resolver.update(uri, ready, null, null)
                    uri
                } catch (error: Exception) {
                    resolver.delete(uri, null, null)
                    throw error
                }
            } finally {
                body.close()
            }
        }

    companion object {
        fun normalizeBaseUrl(raw: String): String {
            val value = raw.trim()
            val uri = try { java.net.URI(value) } catch (_: Exception) {
                throw IllegalArgumentException("Enter a valid SINTU server URL.")
            }
            val scheme = uri.scheme?.lowercase()
            val host = uri.host?.lowercase()
            val loopback = host == "localhost" || host == "127.0.0.1"
            require(uri.rawUserInfo == null && host != null) { "Enter a valid SINTU server URL." }
            require(scheme == "https" || (scheme == "http" && loopback)) {
                "Use HTTPS for remote servers. HTTP is allowed only for localhost/127.0.0.1."
            }
            require(uri.rawQuery == null && uri.rawFragment == null) { "Server URL must not include query or fragment." }
            return if (value.endsWith("/")) value else "$value/"
        }
    }
}

private const val MAX_IMAGE_DOWNLOAD_BYTES = 15 * 1024 * 1024

private fun <T> Response<T>.bodyOrThrow(): T {
    if (!isSuccessful) {
        val detail = errorBody()?.string()?.take(1200)
        throw IllegalStateException(detail?.takeIf { it.isNotBlank() } ?: "SINTU server returned HTTP ${code()}.")
    }
    return body() ?: throw IllegalStateException("SINTU server returned an empty response.")
}
