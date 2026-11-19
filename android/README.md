# SINTU Native Android Client

This is the native Android application project, separate from the browser PWA and Termux service launcher.

## Current implemented client flows

- Secure admin login against the SINTU FastAPI server.
- Configurable server URL; HTTPS is required for remote servers. Cleartext HTTP is restricted by Android network security config to localhost/127.0.0.1 for same-device Termux.
- The HttpOnly `sintu_admin_session` cookie is persisted encrypted with an AES-GCM key held by Android Keystore.
- Persistent multi-conversation assistant: create, select, send, read and delete conversations.
- Create a YouTube Shorts production project, request a script/scene production package, and browse saved projects.
- Native Image Studio calls the authenticated server image API, previews returned JPEGs, and saves images to Pictures/SINTU. The UI reports the actual provider; ComfyUI output is AI inference, while the procedural fallback is explicitly not AI-generated.
- Image prompts/settings and the Video Studio production run state use Compose saved-instance-state so Android can restore them after activity recreation when Android supplies saved state.
- Explicitly reports that script/scene generation is not the same as final MP4 rendering.

## Build

Requires JDK 17, Android SDK Platform 35 and Gradle 8.9.

```bash
gradle -p android testDebugUnitTest assembleDebug assembleRelease
```

The debug APK is installable for device testing. The release APK produced by this workflow is unsigned; production signing requires the owner's private keystore and must not be committed to the repository.

## Current limitations

This first native client tranche is not yet a complete parity release. Background upload/download recovery, native video preview/download, media library management, full timeline editing, offline project queueing, notifications, accessibility/device-size test matrix and signed release package remain outstanding. Real chat/generation also depends on the configured SINTU backend and available AI engines.

## CI build evidence

The GitHub Actions workflow `.github/workflows/android-app.yml` runs the URL-validation unit tests and assembles both `app-debug.apk` and `app-release-unsigned.apk`. The debug and unsigned release APKs are uploaded together as the `sintu-android-apks` workflow artifact. A successful CI build proves compilation/package creation, not installation or functional testing on a physical Android device.
