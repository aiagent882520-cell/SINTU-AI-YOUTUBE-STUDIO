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


## Physical Android device acceptance

CI APK compilation is not a physical-device test. Build a debug APK on a host with JDK 17 and Android SDK 35:

```bash
gradle -p android assembleDebug
```

Connect and authorize exactly one phone with USB debugging enabled, then run from the repository root:

```bash
bash scripts/android_physical_device_smoke.sh android/app/build/outputs/apk/debug/app-debug.apk
```

The script installs/updates the debug package, launches it, checks that the process remains alive, records Android release/ABI/display and memory diagnostics, and scans fresh AndroidRuntime logs for a fatal crash. It writes android-device-acceptance.txt. If multiple phones are connected, set ANDROID_SERIAL. For a release APK use ANDROID_PACKAGE=com.sintu.studio.

This is only an install/launch smoke test. Complete the following manual acceptance on the same physical device before marking the Android module complete:

1. Configure the backend URL (same-device Termux can use http://127.0.0.1:8000/; remote backends must use HTTPS).
2. Sign in with a real test account; verify session persistence and logout.
3. Create/select a conversation, send a message, restart the app and verify history.
4. Create a project and verify backend persistence.
5. Import media using the document picker; verify WorkManager upload progress, retry after network loss, and no duplicate upload.
6. Create a production run, verify approval gates, render a real MP4, download it to the gallery and play it.
7. Force-stop/relaunch during a queued upload; verify recovery and permission handling.
8. Repeat on small and large screen sizes; inspect TalkBack labels, keyboard navigation and memory/crash logs.

Do not attach credentials, cookies, .env files, or private media to the report. A PASS from this script must be labelled PHYSICAL INSTALL/LAUNCH SMOKE PASS, not full Android acceptance.
