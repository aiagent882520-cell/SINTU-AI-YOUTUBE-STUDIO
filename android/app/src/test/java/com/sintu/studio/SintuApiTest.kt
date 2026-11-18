package com.sintu.studio

import okhttp3.HttpUrl.Companion.toHttpUrl
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
}
