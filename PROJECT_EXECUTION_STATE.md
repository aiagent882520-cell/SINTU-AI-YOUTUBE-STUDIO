# SINTU Project Execution State

Last updated: 2026-11-17 (UTC)

This file records evidence-backed status. A task is not complete merely because a script or configuration exists.

## Completed and verified

- GitHub-to-Termux issue relay is installed and has executed allowlisted commands on the Android Termux device.
- Issue #69 completed on the actual Android Termux device: `506 passed, 5 warnings, 0 failed` in 171.75 seconds. The issue is closed with a SUCCESS result comment.
- Issue #74 fast-forwarded Termux from `4a8a162` to `a04cf48`; its stale `running` label was corrected to `sintu-command-done` and the issue closed.
- Earlier Android automation self-test #66 passed 7/7 checks (repository, origin, Python environment, GitHub CLI authentication, API, bridge worker, relay singleton).
- Earlier Android operational readiness #67: core ready; 10 pass, 2 warnings, 0 failures. Warnings were the unavailable local AI model and ComfyUI endpoints.
- PR #73 merged. It isolates two tests from Termux-specific environment leakage; Android full test run #69 subsequently passed.
- Android device probe #68: Android 15, ARM64, 8 CPU cores, about 1.06 GiB available RAM at probe time, about 26.8 GiB free storage. `llama-server` binary exists, but no GGUF model is installed. ComfyUI and Stable Diffusion runtime/workflow are absent.
- FFmpeg, FFprobe, and eSpeak are available on the device according to the previous device audits.
- GitHub relay command execution remains allowlisted; the bridge uses separate API and worker bearer credentials and a SQLite-backed queue.

## In progress

- Issue #77: fresh Android health/media audit. Termux has claimed it; final report not yet received.
- Issue #76: Android operational-readiness report queued.
- Issue #75: fresh Android automation self-test queued.
- PR #78: watchdog and bridge allowlist parity. CI is queued; not merged or deployed yet.

## Known blockers / not verified

- AI production remains paused by `SINTU_AUTOMATION_ONLY=true`.
- No safe local text model download was selected because available RAM was below the conservative threshold. Do not force a model download on this device.
- ComfyUI / diffusion image generation is not installed or verified on this Android device.
- Historical media audit #71 found generated MP4 files with audio sample rates other than 48 kHz and at least one mono-audio file. The new #77 audit must establish current scope; repair is not yet verified.
- A Termux boot entrypoint exists, but a real device reboot recovery test has not been performed.
- Process-kill recovery via the proposed watchdog is not verified until PR #78 passes CI, is merged, is deployed to Termux, and the device demonstrates recovery.
- No complete AI-generated topic-to-final-MP4 production run has been verified. Existing CI video E2E is not evidence of a real local generative-AI production run.
- No public upload/publishing has been performed.

## Next execution order

1. Receive and inspect #77, #76, and #75 results; repair any current failures.
2. Merge PR #78 only after CI passes; deploy it to Termux and verify process-kill recovery.
3. Run Android regression again after deployment.
4. Repair media-generation output defaults and re-audit all generated media.
5. Re-evaluate local inference based on fresh RAM/accelerator evidence; choose a compatible documented alternative if on-device generation is unsafe.
6. Integrate and verify image and voice workflows.
7. Run one real local end-to-end video and validate the final MP4.
8. Verify backup/restore and, when the device owner can test it, actual reboot recovery.

## Safety constraints

- Free/open-source tools first; no paid service is required.
- Never expose credentials or allow arbitrary shell execution.
- Keep production paused until core automation and regression are stable.
- Do not publish videos without explicit approval.
