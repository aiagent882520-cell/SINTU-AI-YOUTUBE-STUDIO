# SINTU Production Factory API

The production factory is a free-first orchestration layer over the existing durable
specialist/builder/checker runtime.

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
