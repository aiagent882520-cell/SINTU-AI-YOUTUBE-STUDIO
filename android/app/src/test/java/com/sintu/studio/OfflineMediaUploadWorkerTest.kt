package com.sintu.studio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OfflineMediaUploadWorkerTest {
    @Test
    fun retriesTemporaryTimeoutAndRateLimitResponses() {
        assertTrue(isRetryableOfflineUploadHttpStatus(408))
        assertTrue(isRetryableOfflineUploadHttpStatus(429))
    }

    @Test
    fun retriesServerErrors() {
        assertTrue(isRetryableOfflineUploadHttpStatus(500))
        assertTrue(isRetryableOfflineUploadHttpStatus(502))
        assertTrue(isRetryableOfflineUploadHttpStatus(599))
    }

    @Test
    fun doesNotRetryAuthenticationOrValidationErrors() {
        assertFalse(isRetryableOfflineUploadHttpStatus(400))
        assertFalse(isRetryableOfflineUploadHttpStatus(401))
        assertFalse(isRetryableOfflineUploadHttpStatus(403))
        assertFalse(isRetryableOfflineUploadHttpStatus(404))
        assertFalse(isRetryableOfflineUploadHttpStatus(413))
    }

    @Test
    fun doesNotTreatNonHttpCodesAsRetryable() {
        assertFalse(isRetryableOfflineUploadHttpStatus(0))
        assertFalse(isRetryableOfflineUploadHttpStatus(499))
        assertFalse(isRetryableOfflineUploadHttpStatus(600))
    }
}
