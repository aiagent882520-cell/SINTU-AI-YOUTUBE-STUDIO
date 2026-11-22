package com.sintu.studio

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OutputResolutionPolicyTest {
    @Test
    fun acceptsEveryServerOutputProfile() {
        assertTrue(OutputResolutionPolicy.isSupported("720x1280"))
        assertTrue(OutputResolutionPolicy.isSupported("1080x1920"))
        assertTrue(OutputResolutionPolicy.isSupported("1080x1080"))
        assertTrue(OutputResolutionPolicy.isSupported("1280x720"))
        assertTrue(OutputResolutionPolicy.isSupported("1920x1080"))
    }

    @Test
    fun rejectsUnsupportedOrMalformedProfiles() {
        assertFalse(OutputResolutionPolicy.isSupported(""))
        assertFalse(OutputResolutionPolicy.isSupported("720p"))
        assertFalse(OutputResolutionPolicy.isSupported("4096x4096"))
        assertFalse(OutputResolutionPolicy.isSupported("720x1280;rm -rf"))
    }

    @Test
    fun trimsWhitespaceWithoutChangingTheProfile() {
        assertTrue(OutputResolutionPolicy.isSupported(" 720x1280 "))
    }
}
