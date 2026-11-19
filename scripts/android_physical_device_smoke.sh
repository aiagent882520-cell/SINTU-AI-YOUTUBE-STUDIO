#!/usr/bin/env bash
# Physical-device install/launch smoke test. Run from a host with Android platform-tools.
set -euo pipefail

ADB="${ADB:-adb}"
APK="${1:-android/app/build/outputs/apk/debug/app-debug.apk}"
PACKAGE="${ANDROID_PACKAGE:-com.sintu.studio.debug}"
REPORT="${ANDROID_DEVICE_REPORT:-android-device-acceptance.txt}"
SERIAL="${ANDROID_SERIAL:-}"

if [[ ! -f "$APK" ]]; then
  echo "BLOCKED: APK not found: $APK" >&2
  echo "Build it with: gradle -p android assembleDebug" >&2
  exit 2
fi
if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "BLOCKED: adb is not installed or not on PATH." >&2
  exit 2
fi

adb_args=()
if [[ -n "$SERIAL" ]]; then adb_args+=(-s "$SERIAL"); fi
devices="$("$ADB" "${adb_args[@]}" devices | awk 'NR>1 && $2=="device" {print $1}')"
count="$(printf '%s\n' "$devices" | sed '/^$/d' | wc -l | tr -d ' ')"
if [[ "$count" != "1" ]]; then
  echo "BLOCKED: expected exactly one authorized online Android device; found $count." >&2
  "$ADB" "${adb_args[@]}" devices -l >&2 || true
  exit 2
fi
if [[ -z "$SERIAL" ]]; then SERIAL="$(printf '%s\n' "$devices" | head -n1)"; fi
adb_args=(-s "$SERIAL")

{
  echo "diagnostic=SINTU_ANDROID_PHYSICAL_DEVICE_SMOKE"
  echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "device_serial=$SERIAL"
  echo "apk=$APK"
  echo "package=$PACKAGE"
  "$ADB" "${adb_args[@]}" shell getprop ro.build.version.release | sed 's/^/android_release=/'
  "$ADB" "${adb_args[@]}" shell getprop ro.product.cpu.abi | sed 's/^/device_abi=/'
  "$ADB" "${adb_args[@]}" shell wm size | sed 's/^/display_size=/'
  "$ADB" "${adb_args[@]}" shell wm density | sed 's/^/display_density=/'
} > "$REPORT"

"$ADB" "${adb_args[@]}" logcat -c
"$ADB" "${adb_args[@]}" install -r "$APK" | tee -a "$REPORT"
"$ADB" "${adb_args[@]}" shell am force-stop "$PACKAGE" || true
"$ADB" "${adb_args[@]}" shell monkey -p "$PACKAGE" 1 | tee -a "$REPORT"

pid=""
for _ in $(seq 1 15); do
  pid="$("$ADB" "${adb_args[@]}" shell pidof "$PACKAGE" 2>/dev/null | tr -d '\r' || true)"
  [[ -n "$pid" ]] && break
  sleep 1
done
if [[ -z "$pid" ]]; then
  echo "app_launch=FAIL" | tee -a "$REPORT"
  "$ADB" "${adb_args[@]}" logcat -d -v brief -s AndroidRuntime:E | tee -a "$REPORT"
  echo "FAIL: app process did not remain alive after launch. Report: $REPORT" >&2
  exit 1
fi
echo "app_launch=PASS" | tee -a "$REPORT"
echo "app_pid=$pid" | tee -a "$REPORT"
"$ADB" "${adb_args[@]}" shell dumpsys meminfo "$PACKAGE" | tee -a "$REPORT"
crashes="$("$ADB" "${adb_args[@]}" logcat -d -v brief -s AndroidRuntime:E | grep -E 'FATAL EXCEPTION|Process: '"$PACKAGE" || true)"
if [[ -n "$crashes" ]]; then
  echo "crash_log=FAIL" | tee -a "$REPORT"
  printf '%s\n' "$crashes" | tee -a "$REPORT"
  echo "FAIL: AndroidRuntime crash found. Report: $REPORT" >&2
  exit 1
fi
echo "crash_log=PASS" | tee -a "$REPORT"
echo "manual_acceptance_required=login, backend, chat, projects, media import/upload, render, playback, background recovery, permissions, offline/online"
echo "PASS: install and launch smoke only. This does NOT prove authenticated workflows or editor acceptance."
echo "Report: $REPORT"
