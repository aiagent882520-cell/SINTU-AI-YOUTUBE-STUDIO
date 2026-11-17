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

- Default visibility is `private`; `unlisted` is allowed only through the existing approved calendar flow.
- `public` is always rejected with HTTP 403 before token access or any Google network request. No public approval endpoint is enabled. This is intentional and remains in force unless the owner gives a separate explicit authorization in a future instruction.
- No automated test performs a real Google/YouTube request or upload.
- Session persistence requires a valid Fernet encryption key and a connected YouTube OAuth channel. Without them, local protocol tests still run but live upload remains unavailable.
- The server process must use the same persistent SINTU SQLite database and encryption key after restart. Restoring the database without the matching key makes saved session URLs undecryptable; the system fails closed.
- The source MP4 is read-only during upload. The endpoint enforces the existing final media quality gate and 512 MiB size limit.

## Verification

Run:

```bash
python -m pytest tests/test_youtube_upload_recovery.py tests/test_api.py -q
```

Protocol tests cover partial acknowledgements, status probes after disconnect, restart recovery, already-completed sessions, expired sessions, malformed ranges, zero-byte files, changed files, bounded no-progress responses, state-transition safety, encrypted persistence, idempotent duplicate requests, and public-upload rejection.

Live YouTube verification remains pending until owner-managed OAuth credentials, encryption key, and channel connection are configured. No live upload is authorized by this documentation.
