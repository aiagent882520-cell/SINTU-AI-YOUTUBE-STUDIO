# SINTU AI YOUTUBE STUDIO

Free-first, local-first AI creator workspace for planning, producing, reviewing, rendering and managing video content.

## Current project capabilities

- FastAPI creator dashboard, admin login, responsive PWA foundation and Hindi-first interface.
- AI production workflows backed by a configurable local Ollama provider; paid providers remain opt-in and locked by policy.
- 60 video-format catalog, 15 studio-module catalog, specialist/checker role registry and format-aware production runtime.
- Production runs execute specialist and independent checker model calls, persist evidence and PASS/FAIL results, pause on failed checks, and run five final review roles. This is a sequential orchestrated runtime, not 61 always-running independent services.
- Local media tools and optional integrations: FFmpeg, Blender, ComfyUI and Piper; availability depends on local installation and hardware.
- Video renderers add SINTU branding watermark and reject subtitle/caption burn-in; generated source imagery can still contain accidental text.
- YouTube OAuth, approved upload, channel analytics/revenue, comment review and publishing-calendar endpoints are present but require owner-provided Google credentials, channel permissions and API enablement.
- Earning System at `/earnings`: income/expense ledger, source categories, status separation, currency-wise monthly summary, targets and CSV export. It does not generate guaranteed income or process payouts.
- Admin-only backup manager: creates integrity-checked SQLite snapshots plus generated media archives, SHA-256 checksums, safe downloads, a five-backup retention limit, and excludes environment/secrets files.

## Quick start

1. Install Python 3.11+.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and review the settings.
4. For free local text generation, install Ollama and pull a compatible model such as `qwen2.5:3b`.
5. Start the app: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
6. Open `http://127.0.0.1:8000`. After login, use the **Earning System** link or visit `/earnings`.

## Backup and recovery

Admin users can create a backup with `POST /api/admin/backups`, list archives with `GET /api/admin/backups`, and download one with `GET /api/admin/backups/{backup_id}`. Each ZIP contains a SQLite online-backup snapshot, generated image/video/audio/music files, a manifest and SHA-256 hashes. Archives are capped at 2 GiB and 10,000 files; only the five newest verified backups are retained. Environment files, API keys, OAuth secrets, source code and model weights are deliberately excluded. Store downloaded backups securely; they contain creator data and encrypted platform tokens. Restore is a deliberate operator action and is not automated by this API.

## Application firewall and security

- Admin authentication is required by default; password hashes use PBKDF2, sessions are signed and HttpOnly, and role-based access is enforced.
- Application firewall supports optional IP/CIDR allowlisting (`SINTU_ALLOWED_IPS`), per-client API rate limiting (`SINTU_RATE_LIMIT_PER_MINUTE`), same-origin checks for state-changing browser requests, security headers, and HTTPS HSTS.
- Login has a separate failed-attempt throttle; security-relevant state-changing requests are written to the audit log.
- The in-process limiter is per worker and resets on restart. For internet-facing deployments, also use a maintained OS/network firewall and a TLS reverse proxy/WAF with shared rate limiting; do not expose the app directly to the public internet.
- IP allowlisting is optional; set it only when the deployment has stable trusted client IPs. Do not trust arbitrary `X-Forwarded-For` headers.

## Free-first policy

- No paid API, subscription or cloud GPU is required for the core local-first setup.
- Paid providers/media connectors are disabled until revenue is confirmed and the owner explicitly enables them.
- Local AI/media generation depends on installed models, storage, RAM, GPU and CPU capability. Low-spec computers may only handle planning, scripts and lightweight rendering.
- External OAuth integrations require credentials configured as server-side environment secrets. Never commit credentials or tokens.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

See [Hindi setup and capability notes](README_HI.md) for Windows, local engines, video workflow and integration details.

## One-step Local Media Production API

After a production run passes its builder/checker and final-review gates, call `POST /api/production/runs/{run_id}/produce-media` with up to 25 scene prompts, optional narration (or a Script Writer deliverable), seconds per scene, resolution, FPS and quality. The endpoint requires the run to belong to the current account and to be completed, and it only accepts formats with a supported generic export profile.

Free local operation requires a validated ComfyUI image workflow, Piper with a Hindi voice model, and FFmpeg/FFprobe. Local ComfyUI/Piper generation does not require a media token; `MEDIA_GENERATION_TOKEN` is checked only when an enabled optional paid image, voice or video provider is actually selected. Original procedural background music is generated locally. This route does not silently call paid providers; missing engines fail closed. The final MP4 receives the SINTU watermark and no burned-in subtitles. The rendered result is attached to the run, but `published` remains false and YouTube publishing still requires separate human approval. Scene prompts can be supplied manually or automatically extracted from the approved AI Video Generator / storyboard deliverable; the runtime does not claim long-form AI scene generation beyond the selected storyboard and local render limits.

## Important limitations

A format being listed does not mean every format has passed full production rendering tests. A role catalog is not proof of 61 autonomous agents running as separate services. Google Flow, platform permissions, actual YouTube monetization eligibility, automated payout collection, live hosting and end-to-end production on the owner's machine require separate setup and verification. Public publishing and financial actions must remain explicitly approved by the owner.


### Backup verification and offline restore

Administrators can verify every backup from the dashboard; verification checks the ZIP structure, manifest, SHA-256 for every included file, and SQLite integrity. A restore is deliberately an offline operator action, not an in-app button: stop the SINTU service and all workers first, then run:

```bash
python scripts/restore_backup.py /path/to/sintu-backup-YYYYMMDDTHHMMSSZ-id.zip --verify-only
python scripts/restore_backup.py /path/to/sintu-backup-YYYYMMDDTHHMMSSZ-id.zip --confirm-restore --app-stopped
```

The restore command creates a verified pre-restore SQLite safety copy under `backups/`, atomically replaces the database, adds missing generated media, and never overwrites existing media. Existing same-name media is preserved and reported as a conflict. Restore does not restore API keys, OAuth secrets, environment files, or application code. Review the JSON result and restart the service only after a successful restore.


### Recovery validation and complete local data backup

New backups include the main Studio database and, when present, the separate earnings ledger database (`sintu_earnings.sqlite3`), plus approved generated-media folders. The dashboard shows backup count, total archive storage and latest-backup age; this inventory is not a substitute for the per-archive Verify operation. Verify checks ZIP structure, every SHA-256 digest, SQLite integrity and foreign-key consistency.

Offline restore validates the required application tables before installing databases and validates them again after installation. It restores the earnings ledger when that database is present in the archive, keeps pre-restore safety copies, and reports media conflicts without overwriting existing files. Restore remains an explicit offline operation while the service and workers are stopped.
