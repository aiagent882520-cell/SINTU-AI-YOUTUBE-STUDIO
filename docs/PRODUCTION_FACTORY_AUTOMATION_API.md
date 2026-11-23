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

The response contains an ordered 21-stage plan: intake, planning, research, fact-check,
strategy, script, storyboard, character bible, visual development, generation, audio,
editing, localization, branding, quality, Owner review, render, package, publishing,
analytics/earnings and learning. Planning does not enqueue work or perform external actions. During
actual runs, existing specialist/checker roles are mapped to applicable stage
checkpoints through quality; actual render and delivery-package work is performed only
through the authenticated Owner-triggered local media endpoint, while publishing,
analytics and learning remain separate follow-up executors. Each new run now persists an ordered 21-row
stage ledger in the runtime SQLite database, including department, approval policy,
status, evidence, issues and timestamps. `GET /api/production/runs/{run_id}` returns the full Owner-scoped ledger; the Factory run-details panel displays all 21 rows, while the recent-runs summary exposes only stage counts by status. The ledger has fenced worker completion,
evidence-required completion and explicit Owner gates for Owner review/publishing.
Stage claims are ordered and fenced by the active run lease; expired worker recovery
returns in-flight stage rows to paused so a new lease can resume them. Owner gates are
surfaced as `awaiting_owner` and cannot be self-approved by the worker. The existing specialist/checker worker now routes matched specialist roles into
applicable stages (intake through quality), orders those role groups by stage, and
advances a stage only after its assigned workers pass independent checkers. Stages
with no matching role in the selected format are explicitly marked `skipped` rather
than falsely completed. The Owner Agent can only place Owner Review into
`awaiting_owner`; its recommendation is not human approval. The authenticated Owner's confirmed local media-generation action advances render and package only after verified MP4/provenance and a verified delivery ZIP have been built. The result's `pipeline_dispatch.completed_stage_ids` and `deferred_stage_ids` are updated as those stages complete. Publishing, analytics and learning remain pending for separate executors. Text-only roles such as Final Render Agent, Upload Agent and Analytics Agent are not treated as proof that those real operations occurred; they remain visible as unmapped worker roles. Existing pre-ledger completed runs are backfilled with earlier stages marked `skipped` (no historical stage evidence is inferred) and Owner Review set to `awaiting_owner`. Therefore this is partial stage dispatch, not full 21-stage execution. The worker also attaches a deterministic `role_stage_map` to the final package, showing which format-team specialists match each stage and which roles remain unmapped. This map is diagnostic metadata; it does not itself execute a stage or certify a stage as complete. Provider
matches are candidates, not installation or health attestations.

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
The authenticated Owner's explicit local media-generation request completes the
`owner_review` stage with an evidence record; an AI Owner Agent READY recommendation
cannot do this. The media endpoint rejects blocked Owner Review checkpoints. External
publishing remains separately disabled and requires its own explicit Owner approval.

## Provider and approval policy

- Local/free providers are preferred.
- Paid providers are blocked unless the server's revenue-confirmed and paid-upgrade
  settings allow them and the Owner explicitly approves the activation.
- Publishing, scheduling, external sharing and source deletion require explicit Owner
  approval.
- Never treat a catalogue entry as proof of credentials, installation, licensing,
  capacity or live availability.
- Do not delete or overwrite original media as part of recovery or automation.


## Deferred specialist roles and side-effect boundaries

The role router reports `deferred_worker_roles` separately from general unmapped roles.
Roles such as Final Render Agent, Final Output Agent, Upload Agent, Scheduling Agent,
Analytics Agent, Asset Manager, Memory Agent and Automation Agent may still receive
ordinary text-only specialist/checker invocations when present in a format preset.
Those invocations can produce plans, checklists or recommendations only; they do not
execute rendering, packaging, uploads, scheduling, analytics retrieval or learning
operations. Their names in a preset are not proof that those operations occurred.

The run result keeps these roles visible alongside deferred stage IDs. Dedicated
side-effect executors must be integrated and independently tested before their stages
can be reported as complete. Upload and scheduling remain Owner-approved external
side effects; a text response from an Upload Agent never performs a publish.

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
asks for confirmation before starting. The dashboard requests `burn_subtitles=false`
to respect the clean-frame video policy. A successful result includes the renderer's
video URL. After a render is attached, the run summary exposes only a validated
video ID and safe local video URL, allowing the dashboard to reopen the MP4 after
refresh without regenerating it. A missing local engine returns an explicit
unavailable response; the dashboard does not fall back to paid providers.

### Build and download the verified local delivery ZIP

A successful local render now builds `production_packages/{run_id}-delivery.zip`
before the package stage is marked complete. The archive includes the verified MP4,
all input assets recorded in the render provenance manifest, timed Hindi SRT captions
(even when captions are not burned into the MP4), a 1280x720 representative-frame thumbnail
extracted from the verified MP4, production metadata, specialist deliverables, the
renderer quality report, the render provenance manifest and source-linked research
evidence when present. Translated subtitle tracks are not generated by this render
action; the README and package index list that omission alongside the unavailable
editable timeline project and per-asset rights certificates. The included thumbnail
is a representative frame, not a separately art-directed or text-designed cover. A
package index records each payload member's size and SHA-256; every archived member is
re-hashed and the ZIP is CRC-checked before it is accepted. The index documents that it
cannot hash itself; the ZIP itself has a persisted SHA-256 and byte size.

`GET /api/production/runs/{run_id}/package` downloads the archive only for the
authenticated Owner who owns that run. The route validates the expected run-specific
path, file size and SHA-256 before returning it. Package creation is local-only and
does not publish, upload, share or modify source assets. Studio backups now include
production thumbnails, provenance manifests and delivery ZIPs under the existing
2 GiB backup safety limit; restore remains additive and does not overwrite existing media.

The current renderer does not export an editable timeline/project file or per-asset
third-party rights certificates. The ZIP README and package manifest explicitly list
those omissions; users must verify rights before external distribution. These items
are not represented as completed deliverables.

This action creates local media and a verified delivery ZIP only. It does not upload or publish to YouTube.
Publishing remains a separate Owner-approved operation. Documentary runs still
require intact source-linked research evidence, and structural traceability is not
a substitute for human fact-checking.
