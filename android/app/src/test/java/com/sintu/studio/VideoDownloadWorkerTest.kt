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
        assertEquals(null, downloadProgressPercent(50, -1))
    }

    @Test
    fun progressPercentageDoesNotOverflowForLargeLongValues() {
        assertEquals(50, downloadProgressPercent(Long.MAX_VALUE / 2 + 1, Long.MAX_VALUE))
        assertEquals(99, downloadProgressPercent(Long.MAX_VALUE - 1, Long.MAX_VALUE))
        assertEquals(100, downloadProgressPercent(Long.MAX_VALUE, Long.MAX_VALUE))
    }

    @Test
    fun progressPercentageHandlesZeroAndNegativeDownloads() {
        assertEquals(0, downloadProgressPercent(0, Long.MAX_VALUE))
        assertEquals(0, downloadProgressPercent(-1, Long.MAX_VALUE))
    }

    @Test
    fun notificationProgressTextHandlesKnownAndUnknownContentLength() {
        assertEquals(
            "Downloading to Movies/SINTU… 25% (1.0/4.0 MB)",
            VideoDownloadWorker.progressDescription(1024L * 1024L, 4L * 1024L * 1024L)
        )
        assertEquals(
            "Downloading to Movies/SINTU… 1.0 MB",
            VideoDownloadWorker.progressDescription(1024L * 1024L, 0L)
        )
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
