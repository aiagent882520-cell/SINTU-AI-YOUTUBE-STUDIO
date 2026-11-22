# SINTU Production Factory API

The production factory is a free-first orchestration layer over the existing durable
specialist/builder/checker runtime.

## Check live host readiness

`GET /api/production-factory/health`

Returns a secret-free snapshot of the selected Master Brain, local model availability,
optional remote-provider configuration flags, and image/voice/music/video engine
readiness on the current server. It does not make paid API calls or claim that a
configured credential has been tested against the vendor.

## Plan a workflow

`POST /api/production-factory/plan`

Request JSON:

```json
{
  "topic": "Hindi science explainer",
  "format_id": "educational"
}
```

The response contains an ordered 11-stage plan: intake, research, strategy, writing,
visuals, audio, assembly, quality, Owner review, publishing and analytics. Planning
does not enqueue work or perform external actions. Provider matches are candidates,
not installation or health attestations.

## Monitor recent runs

`GET /api/production-factory/runs?limit=20`

Returns an Owner-scoped dashboard summary of recent runs, grouped by status, with
topic, format, current role, timestamps, attempts and safe result-presence metadata.
It deliberately omits full scripts and artifact payloads. The limit is capped at 100.

## Start an internal production run

`POST /api/production-factory/runs`

Uses the existing `ProductionRunInput` schema and delegates to the existing persistent
production worker. The worker retains its run state, lease fencing, retry limits,
cancellation checkpoints and builder/checker/reviewer quality gates.

A completed script/package is not the same as a rendered video or a published video.
Media rendering remains behind its existing quality and production gates. External
publishing remains separately disabled unless the Owner explicitly enables it and
approves the action.

## Provider and approval policy

- Local/free providers are preferred.
- Paid providers are blocked unless the server's revenue-confirmed and paid-upgrade
  settings allow them and the Owner explicitly approves the activation.
- Publishing, scheduling, external sharing and source deletion require explicit Owner
  approval.
- Never treat a catalogue entry as proof of credentials, installation, licensing,
  capacity or live availability.
- Do not delete or overwrite original media as part of recovery or automation.


## Durable queued-run recovery

At application startup, SINTU first recovers expired worker leases, then starts an in-process
supervisor that polls the persistent production-run database for `queued` jobs. It uses
the runtime's atomic fenced worker claim, so it can safely race with the request-scoped
FastAPI background task or another server process without executing the same run twice.

Only `queued` jobs are automatically picked up. A `paused` job is intentionally excluded:
it can mean an independent checker failed, documentary evidence is missing or corrupt,
or a human-review gate was reached. Such a run must be explicitly resumed by an Owner
after reviewing its checkpoint. Shutdown stops queue polling without forcibly interrupting
an active model call; an interrupted lease is recovered on a later startup.

## Generate a final local MP4 from an approved run

`POST /api/production/runs/{run_id}/produce-media`

The endpoint is Owner-scoped and accepts only a run whose specialist builders,
independent checkers and final reviewers completed successfully. If scene prompts
and narration are omitted, it extracts them from the approved deliverables. It
then requires the free local image and Hindi voice engines, generates original
local background music, renders with FFmpeg, checks the render quality report,
writes a provenance manifest and attaches the result to the run.

The Production Factory dashboard exposes this action only for completed runs and
asks for confirmation before starting. Once a render is attached, the run summary exposes only a validated video ID
and safe local video URL, so the dashboard can reopen the MP4 after refresh without
re-running media generation. The dashboard requests `burn_subtitles=false`
to respect the clean-frame video policy. A successful result includes the renderer's
video URL. A missing local engine returns an explicit unavailable response; the
dashboard does not fall back to paid providers.

This action creates a local MP4 only. It does not upload or publish to YouTube.
Publishing remains a separate Owner-approved operation. Documentary runs still
require intact source-linked research evidence, and structural traceability is not
a substitute for human fact-checking.
