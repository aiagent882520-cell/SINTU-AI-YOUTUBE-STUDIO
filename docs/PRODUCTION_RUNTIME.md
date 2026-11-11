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
