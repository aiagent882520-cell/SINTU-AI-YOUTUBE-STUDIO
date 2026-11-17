# SINTU Project Execution State

Last updated: 2026-11-17 (UTC)

Evidence-backed state only. A script existing is not proof that its runtime behavior has been verified.

## Completed and verified

- GitHub issue relay has executed allowlisted commands on the actual Android Termux device.
- Issue #69 completed on Android Termux: **506 passed, 5 warnings, 0 failed** in 171.75 seconds. Issue closed with SUCCESS.
- Issue #74 fast-forwarded Termux from `4a8a162` to `a04cf48`; stale running label corrected to done and issue closed.
- Issue #75 fresh Android automation self-test: **7/7 passed** (repository, Git origin, Python 3.14.10, GitHub CLI auth, API health, bridge worker, relay singleton).
- Issue #76 fresh Android operational readiness: **10 passed, 2 warnings, 0 failed**. Core ready; production not ready.
- Issue #77 fresh Android health audit: Python compile PASS and pytest **506 passed, 5 warnings**. Media audit found **6/15 MP4 pass and 9/15 fail** due audio sample rate (8 files not 48 kHz) or channel layout (1 file mono). No black-frame or motion failures were reported for the checked files.
- PR #73 merged; it isolated Termux-specific environment overrides in two tests. Android regression after that fix passed.
- Android device probe #68: Android 15, ARM64, 8 CPU cores, approximately 1.06 GiB available RAM at probe time, approximately 26.8 GiB free storage. `llama-server` binary exists but no GGUF model is installed. ComfyUI and Stable Diffusion runtime/workflow are absent.
- FFmpeg, FFprobe, eSpeak, API, GitHub CLI authentication, bridge credentials, worker, PWA and local repository checks passed on Android.
- SQLite bridge queue supports persistent job records and requeues jobs abandoned for more than 35 minutes. GitHub relay recovers stale claims after 40 minutes.
- PR #78 adds a 30-second Termux watchdog, safe process command-line checks, bridge allowlist parity for `safe_optional_install`, and regression tests. GitHub CI run #1053 passed all seven jobs: Python 3.11/3.12/3.13/3.14, dependency security audit, production Docker build/health, offline branded video E2E and motion audit. PR is not yet merged/deployed.

## Current blockers / not verified

- The nine legacy MP4 audio-format failures have not yet been repaired. New renderer paths explicitly resample/mix to AAC 48 kHz stereo; legacy outputs still need safe backup and repair.
- AI production remains paused by `SINTU_AUTOMATION_ONLY=true`.
- No safe local text model was downloaded because available RAM was below the conservative threshold. Do not force a download.
- ComfyUI / diffusion image generation is not installed or verified on this Android device.
- A Termux:Boot entrypoint exists, but a real device reboot recovery test has not been performed.
- PR #78 watchdog process-kill recovery is not verified until it is merged, deployed to Termux and tested by terminating a SINTU process.
- No complete local generative-AI topic-to-final-MP4 production run has been verified. CI offline render is not proof of generative AI image/video generation on the phone.
- No public upload or publishing has been performed.

## Next execution order

1. Merge PR #78 after its passing CI, update Termux and verify watchdog recovery after killing a service process.
2. Add a backup-first media repair command, repair the nine legacy MP4 audio streams and rerun Android media audit.
3. Re-run full Android regression after deployment.
4. Re-evaluate local inference using fresh RAM/accelerator evidence; document a compatible alternative if on-device generation is unsafe.
5. Integrate and verify image and voice workflows.
6. Run one real local end-to-end video and validate the final MP4.
7. Verify backup/restore and actual Android reboot recovery when the device owner can test it.

## Safety constraints

- Free/open-source tools first; no paid service is required.
- Never expose credentials or allow arbitrary shell execution.
- Keep generative production paused until core automation and regression are stable.
- Do not publish videos without explicit approval.
