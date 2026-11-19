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
- Running jobs can be cancelled only while an FFmpeg process registered for that queue item is active.
- Cancellation sends terminate, waits for a bounded grace period, then kills the process if needed.
- The render worker writes the terminal `cancelled` state only after the process has stopped and renderer cleanup has unwound.
- Cancellation is process-local and currently assumes a single API worker. Do not run multiple Uvicorn workers or multiple app instances with this registry.

## Limitations

- FFprobe validation, image generation, procedural animation generation, and gaps between FFmpeg stages do not emit percentage progress and are not instantly interruptible.
- A percentage describes the active final encoding stage, not an aggregate estimate of all pre-processing work.
- This implementation does not make FastAPI BackgroundTasks a durable external worker.
- Android physical-device validation is still required.
