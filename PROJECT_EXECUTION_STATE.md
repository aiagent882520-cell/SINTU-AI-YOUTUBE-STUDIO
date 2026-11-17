# SINTU AI YOUTUBE STUDIO — execution state

Last updated: 2026-11-17 15:52 UTC

## Current verified snapshot

- Repository: `aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO`, default branch `main`.
- GitHub repository inspection found no currently open issues at snapshot time. Issues #85–#89 are closed; new post-repair verification issues #90 and #91 are queued for Termux.
- Latest deployed code reported by the device: merge commit `b4c4240af80fa0d6b4d4f97c021a8615d76fed6c` (PR #83). Device fast-forwarded from `1dffb1d`, services started, API health returned healthy.
- Firewall audit on the actual Android phone: **8/8 checks passed**, zero errors and zero warnings in summary. Loopback-only bind, 300 requests/minute API limit, admin auth, bridge/session secrets configured. Audit did not change Android firewall, VPN, DNS, Wi-Fi, mobile data, or routing.
- Issue #69: Android test result **506 passed, 5 warnings, 0 failed** in 171.75s; issue closed.
- Issue #89: latest Android automation self-test **7/7 passed**. Verified repo/origin, Python 3.14.10, GitHub CLI authentication (credentials hidden), API health, bridge worker and relay singleton.
- Issue #88: operational readiness **10 passed, 2 warnings, 0 failures**; `core_ready=true`, `production_ready=false`. Warnings were missing reachable local AI model endpoint and ComfyUI endpoint.
- Issue #85: fresh Android resource/engine probe:
  - Android 15, ARM64/aarch64, 8 CPU cores.
  - Total RAM 3,762,049,024 bytes; available RAM 1,106,878,464 bytes at probe time.
  - Home free storage 29,733,658,624 bytes.
  - `llama-server` binary exists, but no GGUF models and no reachable local inference endpoint.
  - Stable Diffusion cpp binaries absent; ComfyUI unreachable and workflow not configured.
  - Probe performed no model download, build, or render. Safe recommendation: no automatic model download or diffusion install under current RAM conditions.
- Issue #86: backup-first media repair succeeded on actual Termux:
  - 15 MP4 files examined; 9 repaired; 6 already valid; 0 failed.
  - Repair backup directory: `media_backups/20261117T145353965118Z`.
  - All repaired audio streams reported AAC, 48 kHz, stereo. Video streams copied without re-encoding. Originals preserved in backup directory.
- Issue #87: health audit ran before the media repair had completed. It reported Python compile PASS and **531 pytest passed, 5 warnings**, but its media checks still found the pre-repair 9 audio-format failures. This report is stale for media state and must not be used as current media verification.
- New Issue #90 (`health_audit`) was created after repair to rerun the full Android health/regression/media audit. New Issue #91 (`live_preflight`) was created to inspect the current production engines and YouTube configuration. Both were queued at last check; results pending.
- Historical watchdog test verified actual API and bridge-worker process termination/recovery. Full Android device reboot/Termux:Boot recovery is still unverified.

## Current code capabilities (code presence is not runtime proof)

- ChatGPT/GitHub/Termux Issue relay: authenticated actor, fixed allowlist, strict payload fields, no arbitrary shell; task labels and result comments.
- Android services: FastAPI, bridge worker, GitHub relay, watchdog and Termux boot entrypoint.
- Production runtime: persistent SQLite runs, specialist/checker/reviewer gates, pause/recovery checkpoints; local media rendering via FFmpeg; optional ComfyUI/Piper engines; eSpeak fallback; subtitle track generation; thumbnail image route.
- Media validator: MP4 metadata, H.264/yuv420p, AAC 48 kHz stereo, duration, black-frame and sampled-motion checks; publish gate calls `verify_publishable_mp4`.
- YouTube implementation: OAuth state/session checks, encrypted token storage, refresh-token flow, channel lookup, resumable upload endpoint and approved-calendar-item gate exist in `app/main.py`. Tests cover OAuth callback and approval/file preconditions. Runtime credentials, real channel connection, real upload and quota status are not verified.
- YouTube publish endpoint defaults `privacy_status=private` and accepts private/unlisted/public. It currently uploads a single streamed payload after creating the resumable session; no on-device evidence yet for a real resumable interruption/resume, scheduled publishing, quota tracking, or upload retry. Public publish must remain disabled unless owner explicitly approves.
- CI workflow `.github/workflows/tests.yml` covers Python 3.11–3.14, dependency audit, Docker build/health, offline branded video E2E and media motion audit. The offline E2E is not proof of local generative AI availability on Android.

## Warnings and known limitations

- The 2 readiness warnings are hardware/engine availability warnings, not failed core automation tests: no local text model endpoint and no ComfyUI image/video engine. Do not install large models or ComfyUI automatically with only ~1.03 GiB free RAM.
- Android pytest warnings in the earlier 531-pass run: Starlette TestClient/httpx deprecation and FastAPI `@app.on_event` startup/shutdown deprecations (5 warnings total). Tests passed; deprecation cleanup is not yet implemented.
- eSpeak is available as a lightweight synthetic Hindi TTS fallback; pronunciation/voice quality needs human review. It is not a neural Piper voice.
- A complete real generative-AI topic-to-MP4 run on Android is not verified. CI offline video rendering and procedural image fallback are not represented as generative AI.
- YouTube OAuth environment values and channel connection have not been verified on-device. No upload or public publishing has been performed.
- Full device reboot recovery has not been verified.

## Next execution order

1. Complete Issues #90 and #91 after Termux relay processes them; ensure health audit runs after Issue #86 repair.
2. If #90 reports media failures, inspect actual file/report and repair only with backup; do not close as pass without evidence.
3. Run current Android regression and update counts from #90, not historical #87.
4. Review production preflight (#91): local text, image, voice, music, FFmpeg, YouTube OAuth config and channel status. Never reveal secret values.
5. Fix only confirmed code defects; run local/CI tests before merging.
6. Keep production mode paused until a real device-compatible generation path is available and verified.
7. Complete YouTube OAuth only after owner configures Google Cloud OAuth credentials and consents; private/unlisted upload test only with explicit owner authorization. Never public-publish without explicit approval.
8. Test actual Android reboot/Termux:Boot with device owner participation.
9. Re-run final full-studio E2E only when dependencies are genuinely available; distinguish generated MP4 from simulated/offline test artifacts.

## Safety invariants

- Free/open-source first; no paid APIs required.
- No model download/build without fresh resource evidence and safe capacity.
- No arbitrary shell execution through GitHub relay.
- Preserve originals and create backups before repair.
- Publishing is separate from rendering; no automatic public publishing.
- A queued/running job is not a completed job. A script existing is not runtime verification.
