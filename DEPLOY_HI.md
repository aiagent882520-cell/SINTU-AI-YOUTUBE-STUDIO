# SINTU AI STUDIO — Deployment

## Docker deployment (generic container host)

The repository now includes a Docker image with Python 3.11, FFmpeg, and DejaVu fonts. It listens on `PORT` (default 8000).

### Run locally or on a Docker-capable server

1. Install Docker Engine / Docker Desktop.
2. Clone this repository.
3. From the repository folder, run:

```bash
docker compose up --build -d
```

4. Before first start, copy `.env.example` to `.env` and set a unique long `SINTU_ADMIN_PASSWORD` plus a random `SINTU_SESSION_SECRET` (at least 32 characters). Never commit this file.
5. Run `docker compose up --build -d` and open `http://localhost:8000`. Sign in with the admin username/password you set. The health endpoint `/api/health` remains public for container health checks.

Docker Compose stores SQLite, generated images, audio, music, and videos in the named `sintu-data` volume mounted at `/data`. Back up this volume. Do not delete it when updating the container.

### Environment variables

Set secrets in the host's secret manager or a protected `.env` file (never commit it):

- `AI_PROVIDER=auto|openai|gemini`
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `STABILITY_API_KEY`
- `MEDIA_GENERATION_TOKEN`
- `ENABLE_PAID_MEDIA_GENERATION=false` (keep false until paid provider costs and credentials are intentionally configured)
- `SINTU_AUTH_REQUIRED=true`, `SINTU_ADMIN_USERNAME`, `SINTU_ADMIN_PASSWORD`, `SINTU_SESSION_SECRET` (minimum 32 random characters)
- Set `SINTU_COOKIE_SECURE=true` behind HTTPS; Compose defaults to false only for local HTTP testing.

API keys are optional for opening the dashboard and using non-provider parts. Paid media generation stays disabled by default.

### Production notes

- A persistent disk/volume is required for the current SQLite database and generated media. The container filesystem alone is not durable.
- Run one app instance when using SQLite. For multi-instance scaling, move tasks and metadata to managed PostgreSQL and media to object storage first.
- Admin login protects dashboard and API routes with a signed, HttpOnly, SameSite=Strict 12-hour session cookie and a basic per-process login-attempt limit. Keep a strong unique admin password and random session secret.
- Configure HTTPS at the hosting proxy/load balancer and set `SINTU_COOKIE_SECURE=true`. Do not expose the app publicly without HTTPS, authentication and access controls; add stronger shared rate limiting/WAF before high-risk public use.
- Configure backups, resource limits, log retention, and monitoring before production use.
- High-resolution video rendering requires sufficient CPU, memory, disk, and execution time.
- YouTube/social publishing and paid AI media providers still require their own supported credentials and permissions.
- A successful Docker build is not a cloud deployment. The host must report healthy and `/api/health` must pass before calling it live.

## FastAPI Cloud note

FastAPI Cloud was considered earlier but no deployment was completed. This Docker setup is platform-neutral and does not create or charge for a hosting account.


## Admin accounts, roles, and security audit

- On first start, the configured `SINTU_ADMIN_USERNAME` and strong `SINTU_ADMIN_PASSWORD` create the initial admin account, only when the user table is empty for that username.
- Passwords are stored as PBKDF2-HMAC-SHA256 hashes; plaintext passwords are not stored or returned by user APIs.
- Admin can create users, change roles, reset passwords, and disable/reactivate accounts from the Security & User Management panel.
- Roles: `admin` has full access; `editor` can use creator workflows but cannot access user management/audit; `viewer` is read-only.
- The system prevents an admin from disabling/demoting their own active admin account and prevents disabling/demoting the last active admin.
- Security audit records write requests with actor, role, HTTP method/path, status, IP address, and timestamp. It intentionally does not store request bodies or passwords.
- User deactivation takes effect on the next request because each signed session is checked against the current user record.
- Audit storage is in the same SQLite database volume; protect and back it up as operational/security data.

- Editors can create content and use generation workflows, but cannot perform update/delete operations or administer accounts. Viewers remain read-only.
- Admins can reset an existing account password from the user list; use a unique 12+ character temporary password and share it securely.


## AI provider control panel

Admin dashboard ke **AI Provider Settings** section mein `auto`, `openai`, ya `gemini` provider preference choose karein. Selection persistent SQLite settings mein save hota hai aur new AI text generation requests par apply hota hai. Selected provider ki key server environment mein configured honi chahiye. Dashboard API keys ko kabhi accept/display/store nahi karta; unhe hosting secret manager mein hi set karein. Integration cards readiness aur missing OAuth integrations dikhate hain. Paid media setting environment-controlled rehti hai; dashboard se paid generation enable nahi hota.
