package com.sintu.studio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VideoDownloadWorkerTest {
    @Test
    fun progressPercentageIsBoundedAndHandlesUnknownLength() {
        assertEquals(25, downloadProgressPercent(25, 100))
        assertEquals(100, downloadProgressPercent(150, 100))
        assertEquals(0, downloadProgressPercent(-10, 100))
        assertEquals(null, downloadProgressPercent(50, 0))
    }

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
