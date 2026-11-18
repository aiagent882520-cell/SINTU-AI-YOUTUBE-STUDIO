package com.sintu.studio

import android.content.Context
import android.net.Uri
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import retrofit2.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

data class LoginRequest(val username: String, val password: String)
data class LoginResponse(val authenticated: Boolean = false, val username: String = "", val role: String = "")
data class SessionResponse(val authenticated: Boolean = false, val username: String? = null, val role: String? = null)
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

private class PersistentSessionCookieJar(private val store: SecureSessionStore) : CookieJar {
    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        cookies.firstOrNull { it.name == SESSION_COOKIE }?.let { cookie ->
            if (cookie.expiresAt <= System.currentTimeMillis()) store.clear()
            else store.save(cookie.toString())
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val raw = store.read() ?: return emptyList()
        val cookie = Cookie.parse(url, raw) ?: run {
            store.clear()
            return emptyList()
        }
        if (cookie.expiresAt <= System.currentTimeMillis()) {
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
}

class SintuApi(context: Context, baseUrl: String) {
    val normalizedBaseUrl: String = normalizeBaseUrl(baseUrl)
    private val sessionStore = SecureSessionStore(context.applicationContext)
    private val service: SintuService

    init {
        val client = OkHttpClient.Builder()
            .cookieJar(PersistentSessionCookieJar(sessionStore))
            .build()
        service = Retrofit.Builder()
            .baseUrl(normalizedBaseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SintuService::class.java)
    }

    suspend fun login(username: String, password: String): LoginResponse =
        service.login(LoginRequest(username, password)).bodyOrThrow()

    suspend fun logout() {
        try { service.logout() } finally { sessionStore.clear() }
    }

    suspend fun session(): SessionResponse = service.session().bodyOrThrow()
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

    companion object {
        fun normalizeBaseUrl(raw: String): String {
            val value = raw.trim()
            val uri = Uri.parse(value)
            val scheme = uri.scheme?.lowercase()
            val host = uri.host?.lowercase()
            require(uri.userInfo == null && host != null) { "Enter a valid SINTU server URL." }
            val loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
            require(scheme == "https" || (scheme == "http" && loopback)) {
                "Use HTTPS for remote servers. HTTP is allowed only for localhost/127.0.0.1."
            }
            require(uri.query == null && uri.fragment == null) { "Server URL must not include query or fragment." }
            return if (value.endsWith("/")) value else "$value/"
        }
    }
}

private fun <T> Response<T>.bodyOrThrow(): T {
    if (!isSuccessful) {
        val detail = errorBody()?.string()?.take(1200)
        throw IllegalStateException(detail?.takeIf { it.isNotBlank() } ?: "SINTU server returned HTTP $code().")
    }
    return body() ?: throw IllegalStateException("SINTU server returned an empty response.")
}
