package com.sintu.studio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VideoDownloadWorkerTest {
    @Test
    fun retriesTransientHttpStatusesOnly() {
        listOf(408, 429, 500, 502, 503, 599).forEach {
            assertTrue("Expected HTTP $it to be retryable", isRetryableVideoDownloadStatus(it))
        }
        listOf(200, 301, 400, 401, 403, 404, 422, 600).forEach {
            assertFalse("Expected HTTP $it not to be retryable", isRetryableVideoDownloadStatus(it))
        }
    }
}
