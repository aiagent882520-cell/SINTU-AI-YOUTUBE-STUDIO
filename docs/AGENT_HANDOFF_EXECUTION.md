# Agent handoff execution contract

## Execution model

SINTU uses on-demand role invocations through the configured local model gateway. A registry entry is not a continuously running autonomous agent. The runtime invokes one selected format role, persists its builder output, invokes that role's independent checker, and makes the output available to later roles only after the checker returns PASS. Senior management roles run after the selected format specialists and receive the approved specialist and prior management reports. The five final reviewers run after the management chain; Owner Agent runs after those reviewers and cannot authorize external publishing.

## Handoff contract

Each worker receives:
- production run ID and authenticated run owner enforced by the runtime;
- selected format and topic;
- its role mission;
- persisted documentary research evidence when the format requires it;
- only prior specialist/management outputs whose independent checker passed.

Each worker must return a non-empty deliverable no longer than 80,000 characters, state assumptions and unresolved dependencies, preserve supplied claim/source IDs, distinguish completed work from recommendations, and never claim external execution that did not occur. The independent checker returns JSON with decision, evidence, issues, and revision_instructions. Only PASS output is handed to subsequent roles. Approved handoffs and model retry events are persisted in the run event ledger.

## Catalog coverage

- 61 core registry roles.
- 130 unique specialist catalog roles after combining base specialist roles, common format roles, all format presets, 21 feature checker worker roles, and five senior managers.
- 15 roles overlap between core and specialist catalogs.
- 176 unique core/specialist worker roles are included in the full catalog execution, each with a distinct checker.
- Five independent final reviewers run after the worker/checker catalog.
- Full catalog test uses mocked model output and verifies execution plumbing, persistence, checker gates, and audit events. It does not prove real-model quality or that 176 independent autonomous agents are running.
- Consent-based Voice Cloning Agent remains a separately gated capability and must not execute without explicit voice-owner consent and valid rights.

## Reliability boundaries

- Checker-guided revisions are bounded.
- Transient local-provider HTTP 429/500/502/503/504 and empty-response errors receive a bounded retry budget with backoff and audit events.
- Configuration/unavailable-provider errors and non-transient provider errors are not retried automatically.
- Cancellation is honored at safe points; an in-flight external provider call is not forcibly terminated.
- Provider execution is at-least-once if a process crashes after generation but before checkpoint persistence. No exactly-once model-call guarantee is claimed.
- Format-team execution remains sequential; parallel execution is not enabled until dependency isolation and output ownership are proven safe.
