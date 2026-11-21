# Production runtime cancellation and recovery

## State model

Production runs use the following additional states and fields:

- `cancel_requested`: durable owner cancellation intent.
- `cancelling`: an active worker has been asked to stop at a safe boundary.
- `cancelled`: terminal cancellation state; a cancelled run cannot be claimed again.
- `worker_token`: a random fencing token assigned during the atomic worker claim.
- `lease_expires_at`: worker lease deadline (15 minutes, renewed around model calls).
- `attempt_count`: number of successful atomic run claims.

The runtime creates an append-only `production_run_events` record for run creation, worker claims, cancellation requests, state transitions, restart recovery and stale-worker recovery.

## API

- `POST /api/production/runs/{run_id}/cancel` — authenticated owner-only cancellation request.
- `GET /api/production/runs/{run_id}/events` — authenticated owner-only transition audit.

Queued and paused runs become cancelled immediately. Running and reviewing runs become cancelling. The worker checks cancellation before and after each model call and before persisting its result. A provider call already in progress cannot be forcibly interrupted by this runtime; cancellation takes effect when that call returns or fails. The API therefore reports `cancelling` until the worker reaches a safe point.

## Recovery and safety

- Worker claims are atomic and fenced by a unique token. A worker whose token is no longer current cannot persist a step or change the run state.
- Leases are renewed before and after model calls. Expired leases are recovered to paused, or cancelled if cancellation was requested. Reading/polling a run triggers the stale-lease scan, so a crashed worker is not left reported as running indefinitely when the run is next inspected. Startup recovery immediately handles legacy active rows without fencing metadata, but does not steal a fresh lease from another live worker process; fenced rows are recovered only after lease expiry.
- Application restart converts interrupted active runs to paused, or to cancelled when a cancellation was pending.
- Approved builder/checker checkpoints remain in SQLite and are reused when a paused run resumes.
- Cancellation never deletes partial outputs, completed checkpoints, user media or source assets.
- Completed, failed, blocked and cancelled runs are terminal for cancellation purposes.
- Model calls exceeding the configured 300-second runtime budget are paused after the provider returns; this is a response-time guard, not a mechanism to kill an in-flight provider process.

## Explicit limitations

This runtime is local-first and does not publish to YouTube. Provider calls have at-least-once behavior across a crash between provider completion and checkpoint persistence; no exactly-once guarantee is claimed for an external model provider. The current orchestration remains sequential; parallel specialist execution is not enabled by this change.
