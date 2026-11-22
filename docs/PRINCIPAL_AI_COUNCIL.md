# Principal AI Council — current implementation contract

## Principal identities

| Principal ID | Provider | Role |
|---|---|---|
| `chatgpt` | OpenAI API | Master Principal AI / Master Director |
| `gemini` | Gemini API | Principal AI |
| `claude` | Anthropic Messages API | Principal AI |
| `deepseek` | DeepSeek API | Principal AI |

The ChatGPT consumer subscription is not an OpenAI API credential. Each provider must be configured through the server's secret environment. API keys are never accepted from this API or returned to the browser.

## Current behavior

- The Owner-only Council status API reports credential configuration and the existing paid-upgrade policy separately from live provider health.
- A configured key is reported as `credentials_configured_not_live_verified`; the status endpoint does not perform a live health check.
- Cloud calls remain blocked unless the existing revenue-confirmed and explicit paid-upgrade flags permit them.
- Each Principal is called independently. Model output must contain a JSON vote (`APPROVE`, `REJECT`, or `ABSTAIN`), rationale, and evidence. Invalid or missing votes are not counted.
- All four Principal votes are required for a major decision. Three approvals are a strict majority. A 2–2 tie or unclear result is marked `needs_research_and_revote`.
- Major decisions require a three-of-four majority plus Owner approval. Security, architecture, and production-release decisions require unanimity plus Owner approval.
- Code integration, paid actions, public publishing, and external data sharing require Owner approval.
- If any Principal is unavailable, the decision is blocked. A configured local model may provide an advisory only; it never counts as one of the four votes.
- Decisions and votes are stored in the existing SINTU database. Council audit events use a SHA-256 hash chain that can detect alteration; it is not a claim of an external immutable ledger.
- The Council records recommendations only. It does not merge code, deploy, publish, change permissions, or spend money.

## Owner-only API

- `GET /api/admin/principal-ai/council/status`
- `POST /api/admin/principal-ai/council/decisions`
- `GET /api/admin/principal-ai/council/decisions`
- `GET /api/admin/principal-ai/council/decisions/{decision_id}`
- `POST /api/admin/principal-ai/council/decisions/{decision_id}/owner-approval`

Supported decision types: `major`, `security`, `architecture`, `production_release`, `paid_action`, `public_publish`, `external_data_sharing`, and `code_integration`.

## Owner-governed knowledge and remaining work

- The Owner-scoped Knowledge Graph is implemented in `app/principal_knowledge_graph.py`: each Principal can have private nodes; shared nodes are visible across the Council; new nodes default to `unverified`; the Owner can verify or dispute entries; edges connect related nodes.
- Knowledge audit events are append-only and hash-chained. The audit chain is tamper-evident within the SINTU database, not an external immutable ledger.
- Owner identity is a separate `is_owner` account flag, bootstrapped from `SINTU_OWNER_USERNAME` (defaults to `SINTU_ADMIN_USERNAME`). Owner mobile TOTP enrollment is provided by `scripts/setup_owner_otp.py`; the Owner login requires a six-digit authenticator code by default.
- Per-agent authentication keys/digital signatures, isolated per-agent code sandboxes, automatic research/re-vote rounds, per-agent task dashboards, and live provider connectivity still require implementation or live verification.
- The Council status dashboard remains a readiness view, not proof that all four providers are operational. Paid provider calls remain locked until revenue is confirmed and the Owner explicitly enables them.
