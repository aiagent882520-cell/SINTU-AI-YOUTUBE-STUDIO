# SINTU AI YOUTUBE STUDIO — production runtime

## Local-first production run API

The format-aware production runtime is persistent and uses the selected format's specialist roles with separate checker invocations. It records worker outputs, checker evidence and issues in SQLite. A checker that does not return valid PASS/FAIL JSON fails closed. Five independent review roles run after all specialist/checker pairs pass.

- `POST /api/production/runs` with `{"format_id":"youtube-shorts","topic":"..."}` queues a background production package run.
- `GET /api/production/runs/{run_id}` returns status, per-role records, evidence, issues and deliverables.
- Requires a configured local Ollama model. It never silently falls back to a paid provider.
- Failed checker gates pause the run. Provider unavailability is recorded as blocked.
- Completion means a production package and reviewer reports were generated; it does not mean an MP4 was rendered or published.
- YouTube publishing remains a separate approval-gated action.

The runtime uses one model request per specialist, one separate request per checker, and five reviewer requests. Long format presets may therefore take substantial time and local compute.

## Google Flow import recovery

Termux watches the configured Android Downloads folders for stable MP4 files. Imported clips are validated with FFprobe, copied (never moved) into SINTU storage, and queued for automatic compilation. The pending queue is persisted in `flow_auto_pending.json`; it is restored when the app restarts. Queue entries are acknowledged only after a successful render, so a failed FFmpeg compilation remains eligible for retry. Source downloads are never deleted. Set `SINTU_FLOW_AUTO_RENDER=false` to disable compilation while retaining imported queue entries.

## Restart recovery and approved checkpoints

On application startup, runs left in `running` or `reviewing` are moved to `paused` with a restart-recovery note. Resuming a paused run reuses specialist outputs only when their independent checker passed, and reuses final reviewer reports only when their persisted verdict passed. Work that had no passing checkpoint is executed again. This avoids silently treating interrupted or unchecked work as approved. Publishing still requires the authenticated owner's separate approval.

## Render-time motion quality gate

Storyboard rendering defaults to a per-scene cinematic zoom/pan. Storyboards longer than eight seconds cannot select static/no-motion mode. Before a long MP4 is published to the output directory, the renderer samples actual decoded frames and rejects frozen or slideshow-like motion; camera-motion storyboards require at least 60% moving sampled transitions, while assembled source-video timelines require at least 20%. The measured motion ratio is returned with render metadata. A failed quality gate deletes the temporary render instead of exposing a weak MP4.

The render API and Studio UI now default to slow cinematic zoom-in. Explicit static/no-motion mode is limited to clips of eight seconds or less. The same sampled-motion verifier also runs before a long MP4 can be passed to YouTube upload verification, so a frozen export is blocked before publishing.


## Upload-time visual integrity gate

Every upload path that calls `verify_publishable_mp4` must fail closed if FFprobe or FFmpeg is unavailable, the MP4/container/video stream is invalid, duration/frame metadata is inconsistent, or frame decoding fails. The gate detects full-duration black output and rejects a black interval at least `max(2.5 seconds, 25% of clip duration)`. It samples up to 600 decoded frames uniformly across the entire clip (up to 2 frames/second), and requires at least 70% of sampled frames to contain visible pixel content. The report includes black intervals, longest black segment, sample count and visible-frame count. This is a conservative technical screen, not a substitute for human review of narrative quality or actual playback on the target device.
