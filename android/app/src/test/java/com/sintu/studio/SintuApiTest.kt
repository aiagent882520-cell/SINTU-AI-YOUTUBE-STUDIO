package com.sintu.studio

import okhttp3.HttpUrl.Companion.toHttpUrl
import com.google.gson.Gson
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.fail
import org.junit.Test

class SintuApiTest {
    @Test
    fun httpsRemoteUrlIsAcceptedAndNormalized() {
        assertEquals("https://studio.example.com/", SintuApi.normalizeBaseUrl("https://studio.example.com"))
    }

    @Test
    fun httpsBasePathIsPreserved() {
        assertEquals("https://studio.example.com/sintu/", SintuApi.normalizeBaseUrl("https://studio.example.com/sintu"))
    }

    @Test
    fun sameDeviceLoopbackHttpIsAllowed() {
        assertEquals("http://127.0.0.1:8000/", SintuApi.normalizeBaseUrl("http://127.0.0.1:8000"))
        assertEquals("http://localhost:8000/", SintuApi.normalizeBaseUrl("http://localhost:8000/"))
    }

    @Test
    fun remotePlainHttpIsRejected() {
        assertRejected("http://studio.example.com")
        assertRejected("http://[::1]:8000")
    }

    @Test
    fun persistedSessionCookieOriginIsHostAndPortBound() {
        val studio = sessionCookieOrigin("https://studio.example.com/".toHttpUrl())
        assertEquals("https://studio.example.com:443", studio)
        assertNotEquals(studio, sessionCookieOrigin("https://attacker.example/".toHttpUrl()))
        assertNotEquals(studio, sessionCookieOrigin("https://studio.example.com:8443/".toHttpUrl()))
    }

    @Test
    fun credentialsAndQueryAreRejected() {
        assertRejected("https://user:pass@studio.example.com")
        assertRejected("https://studio.example.com/?token=secret")
    }

    private fun assertRejected(url: String) {
        try {
            SintuApi.normalizeBaseUrl(url)
            fail("Expected URL to be rejected: $url")
        } catch (_: IllegalArgumentException) {
            // Expected: insecure or malformed URL must fail closed.
        }
    }

    private class FakeSessionCookieStore : SessionCookieStore {
        var value: String? = null
        var origin: String? = null
        var clearCount: Int = 0

        override fun save(value: String, origin: String) {
            this.value = value
            this.origin = origin
        }

        override fun read(origin: String): String? {
            if (this.origin != origin) {
                clear()
                return null
            }
            return value
        }

        override fun clear() {
            value = null
            origin = null
            clearCount++
        }
    }

    @Test
    fun cookieJarPersistsAndReloadsCookieForIssuingOrigin() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val url = "https://studio.example.com/".toHttpUrl()
        val cookie = okhttp3.Cookie.parse(
            url, "sintu_admin_session=secret; Path=/; HttpOnly"
        )!!

        jar.saveFromResponse(url, listOf(cookie))

        assertEquals("https://studio.example.com:443", store.origin)
        assertEquals("secret", jar.loadForRequest(url).single().value)
    }

    @Test
    fun cookieJarClearsCookieWhenSchemeChanges() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val https = "https://studio.example.com/".toHttpUrl()
        val cookie = okhttp3.Cookie.parse(
            https, "sintu_admin_session=secret; Path=/; HttpOnly"
        )!!
        jar.saveFromResponse(https, listOf(cookie))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(
            "http://studio.example.com/".toHttpUrl()
        ))
        assertEquals(1, store.clearCount)
    }

    @Test
    fun cookieJarClearsCookieWhenPortChanges() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val original = "https://studio.example.com/".toHttpUrl()
        val cookie = okhttp3.Cookie.parse(
            original, "sintu_admin_session=secret; Path=/; HttpOnly"
        )!!
        jar.saveFromResponse(original, listOf(cookie))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(
            "https://studio.example.com:8443/".toHttpUrl()
        ))
        assertEquals(1, store.clearCount)
    }

    @Test
    fun cookieJarClearsExpiredCookie() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val url = "https://studio.example.com/".toHttpUrl()
        val expired = okhttp3.Cookie.Builder()
            .name("sintu_admin_session")
            .value("secret")
            .hostOnlyDomain(url.host)
            .path("/")
            .expiresAt(System.currentTimeMillis() - 1_000)
            .httpOnly()
            .build()
        store.save(expired.toString(), sessionCookieOrigin(url))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(url))
        assertEquals(1, store.clearCount)
    }

    @Test
    fun cookieJarClearsMalformedPersistedCookie() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val url = "https://studio.example.com/".toHttpUrl()
        store.save("this-is-not-a-cookie", sessionCookieOrigin(url))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(url))
        assertEquals(1, store.clearCount)
    }


    @Test
    fun offlineMediaDefaultsUsePhoneSafeRenderProfile() {
        val request = ProductionMediaRequest()
        assertEquals("720x1280", request.resolution)
        assertEquals(24, request.fps)
        assertEquals("standard", request.quality)
        assertEquals(true, request.burn_subtitles)
    }

    @Test
    fun cookieJarClearsCookieWhenHostChanges() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val original = "https://studio.example.com/".toHttpUrl()
        val cookie = okhttp3.Cookie.parse(
            original, "sintu_admin_session=secret; Path=/; HttpOnly"
        )!!
        jar.saveFromResponse(original, listOf(cookie))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(
            "https://attacker.example/".toHttpUrl()
        ))
        assertEquals(1, store.clearCount)
    }

    @Test
    fun cookieJarClearsPersistedValueWhenRedirectTargetChangesOrigin() {
        val store = FakeSessionCookieStore()
        val jar = PersistentSessionCookieJar(store)
        val original = "https://studio.example.com/".toHttpUrl()
        val cookie = okhttp3.Cookie.parse(
            original, "sintu_admin_session=secret; Path=/; HttpOnly"
        )!!
        jar.saveFromResponse(original, listOf(cookie))

        assertEquals(emptyList<okhttp3.Cookie>(), jar.loadForRequest(
            "https://evil.example/".toHttpUrl()
        ))
        assertEquals(null, store.value)
        assertEquals(null, store.origin)
    }
    @Test
    fun imageRequestUsesServerFieldNamesAndKeepsSelectedAspect() {
        val json = Gson().toJson(ImageGenerateRequest(
            prompt = "A fort at sunrise",
            kind = "scene",
            aspect = "portrait"
        ))
        assertTrue(json.contains("\"prompt\":\"A fort at sunrise\""))
        assertTrue(json.contains("\"kind\":\"scene\""))
        assertTrue(json.contains("\"aspect\":\"portrait\""))
    }

    @Test
    fun imageResponsePreservesProviderAndNoticeForHonestUiLabeling() {
        val response = Gson().fromJson(
            """{"image_id":"0123456789abcdef0123456789abcdef","url":"/api/images/0123456789abcdef0123456789abcdef","kind":"scene","aspect":"portrait","width":768,"height":1360,"format":"JPEG","size_bytes":12345,"provider":"SINTU Procedural Art (offline)","local":true,"notice":"not a generative-AI image"}""",
            ImageGenerationResponse::class.java
        )
        assertEquals("0123456789abcdef0123456789abcdef", response.image_id)
        assertEquals("SINTU Procedural Art (offline)", response.provider)
        assertTrue(response.local)
        assertTrue(response.notice.contains("not a generative-AI image"))
        assertFalse(response.provider.contains("ComfyUI"))
        assertEquals(768, response.width)
        assertEquals(1360, response.height)
    }

}
