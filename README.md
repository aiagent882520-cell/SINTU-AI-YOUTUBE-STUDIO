# SINTU AI YOUTUBE STUDIO

Free-first, local-first AI creator workspace for planning, producing, reviewing, rendering and managing video content.

## Current project capabilities

- FastAPI creator dashboard, admin login, responsive PWA foundation and Hindi-first interface.
- AI production workflows backed by local Ollama or a loopback OpenAI-compatible server (llama.cpp, LocalAI or LM Studio); the Termux bootstrap attempts a RAM/storage-aware Qwen GGUF setup when the Termux package is available; paid providers remain opt-in and locked by policy.
- 60 video-format catalog, 15 studio-module catalog, specialist/checker role registry and format-aware production runtime.
- Production runs execute specialist and independent checker model calls, persist evidence and PASS/FAIL results, pause on failed checks, and run five final review roles. This is a sequential orchestrated runtime, not 61 always-running independent services.
- Local media tools and optional integrations: FFmpeg, Blender, ComfyUI and Piper; availability depends on local installation and hardware.
- Video renderers add the SINTU branding watermark. Final MP4 export supports optional timed SRT subtitle/lyric burn-in through FFmpeg/libass; generated source imagery is kept text-free where the selected image/video engine honors the prompt.
- YouTube OAuth, approved upload, channel analytics/revenue, comment review and publishing-calendar endpoints are present but require owner-provided Google credentials, channel permissions and API enablement.
- Earning System at `/earnings`: income/expense ledger, source categories, status separation, currency-wise monthly summary, targets and CSV export. It does not generate guaranteed income or process payouts.
- Admin-only backup manager: creates integrity-checked SQLite snapshots plus generated media archives, SHA-256 checksums, safe downloads, a five-backup retention limit, and excludes environment/secrets files.

## One-command Android Termux install

Inside Termux, paste this single command and press Enter:

```bash
pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO/main/scripts/termux_one_command.sh -o "$TMPDIR/sintu-install.sh" && bash "$TMPDIR/sintu-install.sh"
```

The installer is free/local-first, safe to rerun, preserves existing project data and `.env`, creates an isolated Python environment, installs Termux media dependencies, checks the app and starts it on `http://127.0.0.1:8000`. Save the first-run admin password printed in Termux. See [Termux installation details](docs/TERMUX_ONE_COMMAND.md).

## Persistent AI Assistant conversations

The dashboard includes a text-chat panel backed by persistent SQLite conversations. Authenticated users can create, list, read, rename, delete and continue their own conversations. Each message uses the existing local-first provider gateway and a bounded recent-history context. Provider-unavailable and generation-failure states are saved explicitly; they are not reported as successful replies.

API: `GET/POST /api/conversations`, `GET/PATCH/DELETE /api/conversations/{conversation_id}`, and `POST /api/conversations/{conversation_id}/messages`.

This is a persistent text-chat foundation, not yet a full multimodal assistant: streaming, file/document upload, image understanding, live web research/citations and general tool calling are not included in this chat route. These capabilities need real integrations and separate tests before being marked complete.

## Quick start

1. Install Python 3.11+.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and review the settings.
4. For free local text generation, run Ollama with a compatible model such as `qwen2.5:3b`, or use a local llama.cpp/LocalAI/LM Studio OpenAI-compatible server.
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

Free local operation requires a validated ComfyUI image workflow, Piper with a Hindi voice model, and FFmpeg/FFprobe. Local ComfyUI/Piper generation does not require a media token; `MEDIA_GENERATION_TOKEN` is checked only when an enabled optional paid image, voice or video provider is actually selected. Original procedural background music is generated locally. This route does not silently call paid providers; missing engines fail closed. The final MP4 receives the SINTU watermark and supports timed subtitle burn-in through FFmpeg/libass. Approved production runs can generate scene-aligned Hindi subtitle tracks automatically; supplied timed SRT tracks are also supported. The rendered result is attached to the run, but `published` remains false and YouTube publishing still requires separate human approval. Scene prompts can be supplied manually or automatically extracted from the approved AI Video Generator / storyboard deliverable; the runtime does not claim long-form AI scene generation beyond the selected storyboard and local render limits.

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


## Android and local AI engine options

SINTU first uses a ready Ollama model. With `LOCAL_AI_BACKEND=auto`, it can also use a local OpenAI-compatible server such as llama.cpp, LocalAI or LM Studio. For llama.cpp, start its server on loopback (for example, `llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8080`) and configure:

```dotenv
AI_PROVIDER=local
LOCAL_AI_BACKEND=auto
LOCAL_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
LOCAL_OPENAI_MODEL=auto
```

The server must expose `/v1/models` and `/v1/chat/completions`. SINTU checks the advertised model and never sends prompts to a public endpoint through this setting. On Termux, the one-command installer attempts to install the `llama-cpp` package and download an official Qwen GGUF model only when available-memory and free-storage thresholds are met. Outside that supported bootstrap path, install llama.cpp and choose a quantized model that fits the device. No paid API is selected.


## ChatGPT ↔ GitHub ↔ Android Termux automation

The control plane uses GitHub Issues as a mailbox. A command issue must be opened by the configured repository owner, have a title beginning `SINTU-CMD:`, and carry the `sintu-command-queued` label. Its body must be flat JSON, for example:

```json
{"action":"automation_self_test"}
```

The Termux relay accepts only fixed allowlisted actions; arbitrary shell commands are never accepted. Results are posted as an issue comment and the issue is closed with a success/failure label. The relay uses a process lock to prevent two local relay instances from consuming the same queue. The authenticated local bridge is a separate queue; it never executes commands itself, and the local worker maps jobs to fixed argument vectors.

For the initial update after this PR is merged, run this single command in Termux:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO && bash scripts/termux_apply_update.sh
```

It fast-forwards `main`, stops only recorded PIDs whose command lines match the expected SINTU service, starts API/worker/relay, and checks API health. Install Termux:Boot and grant the required battery/background permissions if automatic restart after Android reboot is desired. Android may still suspend background work; use Termux wake-lock and disable battery optimization where supported.

Run a control-plane diagnostic from Termux with:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO && .venv/bin/python scripts/automation_self_test.py --json
```

The diagnostic checks repository identity, virtualenv, GitHub CLI authentication, API reachability, bridge worker heartbeat, and the relay singleton lock. It does not run video rendering. Production actions remain blocked by default through `SINTU_AUTOMATION_ONLY=true`; keep this enabled until the complete control-plane round trip is verified and production is explicitly resumed.


## Advanced firewall and Android phone safety

SINTU includes an application-layer firewall: loopback-only service binding, admin authentication, dedicated bridge tokens, fixed command allowlists, API rate limiting, same-origin checks, security headers and audit logging. The read-only Android-safe configuration audit is documented in [Advanced Firewall & Android Safety](docs/ADVANCED_FIREWALL_ANDROID_SAFETY.md) (Hindi: [फ़ोन सुरक्षा](docs/README_HI_FIREWALL.md)). Run ` .venv/bin/python scripts/firewall_safety_audit.py --json` in Termux to inspect settings. It never changes Android firewall, VPN, DNS, Wi-Fi, mobile data or routing, so it cannot deliberately interrupt other phone apps. It reports unsafe settings rather than silently rewriting configuration.


## Production and external publishing safety gates

Video/media rendering and asset-generation endpoints are disabled by default unless
`SINTU_PRODUCTION_ENABLED=true` is explicitly set by the owner after all required
forensic, regression, worker, health and device gates pass. YouTube, Meta and TikTok
upload/publishing endpoints (including YouTube public-approval creation) are separately
disabled unless `SINTU_EXTERNAL_PUBLISHING_ENABLED=true` is explicitly set. Both
flags default to `false`; enabling one does not enable the other. Revoking an
existing public approval remains available while publishing is disabled. These
server-side gates apply even when an administrator is authenticated or OAuth
credentials are configured.
