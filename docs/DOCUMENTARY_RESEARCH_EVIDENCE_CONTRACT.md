# Documentary research evidence contract

SINTU documentary production must preserve a traceable evidence ledger before narration and editing.

## Package shape

A package uses `schema_version: 1`, a topic, a timezone-aware `researched_at` timestamp, source records, and claim records.

Each source records a stable ID, title, publisher/issuing body, public HTTP(S) URL, access date, source classification, optional publication date, and optional short evidence excerpt.

Each claim records a stable ID, exact claim text, type (`factual`, `interpretive`, or `production_note`), evidence status (`corroborated`, `single_source`, `disputed`, or `unverified`), referenced source IDs, and editorial notes explaining the relationship between evidence and claim.

## Fail-closed rules

- Factual claims marked corroborated, single-source, or disputed must cite known source IDs.
- Corroborated factual claims must reference at least two differently named publishers. This is a structural minimum only; different publisher names do not prove source independence.
- Unverified factual claims may remain in the research ledger but produce warnings and must not be narrated as established fact.
- Disputed claims produce warnings and must be presented with the disagreement.
- Citation references must resolve; duplicate IDs, invalid dates, missing publisher metadata, unsafe/private URLs, and unsupported schema values fail validation.
- Cited claims need editorial notes describing why the cited material is relevant.

## Acceptance boundary

`validate_research_package()` is a structural and traceability validator. It does not browse the web, fetch URLs, authenticate publishers, inspect source contents, judge evidence quality, establish independence, or prove that a source supports a claim. A valid result is **not** a factual-accuracy PASS. Live research and independent editorial fact-checking remain required before a documentary is approved for rendering or publishing.

This contract does not call paid services and does not access private credentials or local device data.


## Production API integration

Documentary formats must submit `research_evidence` in `POST /api/production/runs` before any worker is scheduled. The package is validated, owner-scoped, stored immutably with a SHA-256 digest, and retrievable through `GET /api/production/runs/{run_id}/research-evidence`. A documentary media render rechecks the persisted digest and structural contract and records the digest in the render manifest.

The production gate requires at least one factual claim and requires each factual claim to be marked `corroborated` with references to at least two differently named publishers. This is a structural gate only: it does not fetch URLs or prove that cited sources support claims. Human fact-checking remains mandatory, and the API explicitly returns that limitation.
