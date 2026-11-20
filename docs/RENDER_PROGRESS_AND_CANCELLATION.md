# Render queue progress and cancellation

## Progress contract

- FFmpeg `-progress pipe:1 -nostats` is enabled only for the main render encode stages that have a known output duration.
- The runner parses FFmpeg `out_time_ms` and converts it to a bounded percentage.
- A running job is capped at 99%. The queue marks 100% only after the renderer returns successfully and the output verification path completes.
- Progress is persisted in the owner-scoped `studio_render_queue.progress_json` field and exposed as `progress` by the queue API.
- Progress is monotonic within one job. The UI refreshes the queue and displays the persisted percentage.

## Cancellation contract

- The API first resolves the queue item under the authenticated owner.
- Queued jobs use the existing queued-to-cancelled transition.
- Running jobs persist an owner-scoped `cancel_requested` intent in SQLite under `BEGIN IMMEDIATE`; the active lease token fences the worker acknowledgement.
- The lease-owning durable worker polls cancellation intent and terminates only the FFmpeg/FFprobe child registered for that queue item. The process runner uses terminate, bounded wait, then kill fallback.
- The worker writes terminal `cancelled` only after the child exits and the renderer's temporary-directory cleanup unwinds; it then clears lease owner/token/expiry and cancellation intent.
- If the worker crashes after cancellation was requested, expired-lease recovery finalizes the job as `cancelled` rather than requeueing it. No process-local API registry is used as the cross-process signal path.

## Limitations

- FFprobe validation, image generation, procedural animation generation, and gaps between FFmpeg stages do not emit percentage progress and are not instantly interruptible.
- A percentage describes the active final encoding stage, not an aggregate estimate of all pre-processing work.
- This implementation does not make FastAPI BackgroundTasks a durable external worker.
- Android physical-device validation is still required.

## Operational safeguard

Until cancellation is moved to a cross-process worker/lease design, production deployment must run exactly one Uvicorn worker and one application instance for this in-memory process registry. The queue database remains durable, but the live process handle itself is not shared between workers.
