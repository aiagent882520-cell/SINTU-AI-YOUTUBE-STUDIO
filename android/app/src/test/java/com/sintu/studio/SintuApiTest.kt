package com.sintu.studio

import org.junit.Assert.assertEquals
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
