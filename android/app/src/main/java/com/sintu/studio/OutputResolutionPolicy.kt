package com.sintu.studio

/** Keep native render choices aligned with app.video_renderer.OUTPUT_PROFILES. */
internal object OutputResolutionPolicy {
    val supported: Set<String> = linkedSetOf(
        "720x1280",
        "1080x1920",
        "1080x1080",
        "1280x720",
        "1920x1080"
    )

    fun isSupported(value: String): Boolean = value.trim() in supported
}
