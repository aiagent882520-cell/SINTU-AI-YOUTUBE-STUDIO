# YouTube resumable upload recovery

The YouTube upload endpoint uses a durable SQLite state record keyed by calendar item. A record is bound to the rendered video ID, connected channel ID, exact title, description hash, privacy, file size and SHA-256. Reusing a calendar item with different media or metadata is rejected instead of silently creating a second video.

## State model

`QUEUED -> INITIALIZING -> UPLOADING -> PAUSED -> RESUMING -> VERIFYING -> COMPLETED`

Failure paths use `ERROR` and `EXPIRED`; `CANCELLED` is terminal. Invalid state transitions are rejected. A completed record is idempotent: retry returns its already-verified YouTube video ID without another upload.

## Recovery protocol

- Session creation is performed through Google's resumable-upload API.
- The session URI is encrypted with the configured `YOUTUBE_TOKEN_ENCRYPTION_KEY` (Fernet), never stored as plaintext, and never included in logs or API responses.
- Media is sent in 8 MiB chunks (a multiple of Google's 256 KiB alignment) with an explicit `Content-Range`.
- Only Google's `308` response `Range` header advances the persisted acknowledged offset. A local byte counter is not treated as proof of receipt.
- After a network interruption or process restart, the worker sends a zero-byte status probe (`Content-Range: bytes */size`) and resumes at the server-acknowledged byte.
- Transient failures use bounded exponential backoff. Expired sessions are marked `EXPIRED`; the next explicit retry creates a new session. A changed file fingerprint is rejected.
- OAuth is refreshed once after an authorization failure. The final YouTube video ID is then looked up with the YouTube Data API before the job is marked `COMPLETED`.
- A crash after upload completion but before local completion persistence leaves a `VERIFYING` record. The next retry verifies the stored video ID rather than starting another upload.

## Safety and limitations

- Default visibility is `private`; `unlisted` is allowed only through the approved calendar flow.
- Public visibility requires a separate authenticated admin/owner approval action with the exact confirmation phrase `I CONFIRM PUBLIC VISIBILITY`. The approval is bound to the calendar item, video ID, connected channel ID, exact title and MP4 SHA-256; it expires after 10 minutes, is consumed once, and can be revoked.
- The one-time approval token is returned once, stored only as a SHA-256 digest, and supplied in the `X-SINTU-Public-Approval` header. It is not placed in the URL, stored in plaintext, or included in logs/status responses.
- Public-intended uploads are first created and uploaded as `private`. Only after the MP4 has uploaded and the video ID/channel have been verified does the API re-check the active approval and issue a separate YouTube `videos.update` visibility change to `public`. It then verifies the public status.
- Resume/retry checks the same approval binding and expiry/revocation state. If approval expires or is revoked while uploading, the job pauses and the video remains private. A fresh owner approval can replace an expired/revoked approval for the same exact content.
- A revocation blocks any pending/resumed public visibility action. Revoking after the public change has already been applied is recorded but does not automatically make an already-public video private.
- No public approval is issued and no public upload is performed by automated tests or this implementation work. The owner must separately invoke the approval endpoint for a specific video before any public visibility change can occur.
- No automated test performs a real Google/YouTube request or upload.
- Session persistence requires a valid Fernet encryption key and a connected YouTube OAuth channel. Without them, local protocol tests still run but live upload remains unavailable.
- The server process must use the same persistent SINTU SQLite database and encryption key after restart. Restoring the database without the matching key makes saved session URLs undecryptable; the system fails closed.
- The source MP4 is read-only during upload. The endpoint enforces the existing final media quality gate and 512 MiB size limit.

## Verification

Run:

```bash
python -m pytest tests/test_youtube_upload_recovery.py tests/test_api.py -q
```

Protocol tests cover partial acknowledgements, status probes after disconnect, restart recovery, already-completed sessions, expired sessions, malformed ranges, zero-byte files, changed files, bounded no-progress responses, state-transition safety, encrypted persistence, idempotent duplicate requests, private-first public approval, approval expiry/revocation, and worker allowlist isolation.

Live YouTube verification remains pending until owner-managed OAuth credentials, encryption key, and channel connection are configured. No live upload is authorized by this documentation.

- Upload progress/status is available from `GET /api/admin/youtube/uploads/{calendar_id}`. It returns the state, acknowledged bytes, file size, progress percentage, video ID and processing status; it deliberately omits the encrypted session URI and approval digest.
- An incomplete upload can be cancelled through `POST /api/admin/youtube/uploads/{calendar_id}/cancel`. The local job becomes terminal `CANCELLED`; the abandoned Google session is not reused and may remain server-side until it expires.

### Owner approval API flow

1. An authenticated admin posts `calendar_id`, `video_id`, `title`, the connected `channel_id`, and the exact confirmation phrase to `POST /api/admin/youtube/public-approvals`.
2. The response displays the exact title/channel/video and returns a one-time `approval_token`. Store it privately; it is not retrievable later.
3. The admin calls the existing publish endpoint with `privacy_status=public` and sends the token in `X-SINTU-Public-Approval`. The token is never placed in the URL.
4. To revoke before the public visibility change, post the token in the JSON body to `POST /api/admin/youtube/public-approvals/revoke`.
5. Upload progress can be inspected with `GET /api/admin/youtube/uploads/{calendar_id}`; session URI and approval digest are omitted.

The public approval API creates no approval automatically and no approval is created by scheduled/background workers.

Duplicate protection is channel-wide for an exact MP4 SHA-256, not just per calendar item. A different calendar item cannot upload the same file to the same channel while any prior job is active, failed, expired or completed; a prior job must be explicitly cancelled first. The cancelled calendar record itself remains terminal. The duplicate check runs before OAuth or Google network access.
