# SINTU AI STUDIO — Deployment

## Docker deployment (generic container host)

The repository now includes a Docker image with Python 3.11, FFmpeg, and DejaVu fonts. It listens on `PORT` (default 8000). Docker Compose forwards the optional OpenAI, Gemini, Stability, YouTube, Meta and TikTok server-side environment variables into the container; empty credentials keep those integrations disconnected.

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
- `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI`, `YOUTUBE_TOKEN_ENCRYPTION_KEY`
- `META_APP_ID`, `META_APP_SECRET`, `META_REDIRECT_URI`, `META_GRAPH_API_VERSION`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`
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


## YouTube channel OAuth and upload
1. Google Cloud Console mein project banayein, **YouTube Data API v3** enable karein aur OAuth consent screen configure karein.
2. OAuth Client ID type **Web application** banayein. Authorized redirect URI ko deployed domain ke saath exact set karein: `https://YOUR-DOMAIN/api/admin/youtube/oauth/callback`.
3. Hosting secret manager mein `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REDIRECT_URI` aur stable `YOUTUBE_TOKEN_ENCRYPTION_KEY` set karein. Fernet key generate karne ke liye Python: `from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())`.
4. HTTPS par admin login karein aur YouTube Channel Connection panel se Google consent complete karein. OAuth state 10 minute ka, single-use aur current admin session se bound hai. Tokens Fernet encryption ke saath SQLite mein store hote hain; browser ko kabhi nahi bheje jate.
5. Calendar mein YouTube/Shorts item add karke approve karein, MP4 render karein, phir explicit admin upload action se video bhejein. Default privacy **private** hai; public/unlisted ke liye admin ka explicit selection zaroori hai.
6. Upload ke liye YouTube Data API quota apply hota hai. Google OAuth verification/testing-user restrictions bhi apply ho sakti hain. App automatic scheduled uploads nahi chalata; publish ek explicit manual action hai.
7. Token encryption key ko securely backup karein. Key lost/change hone par stored refresh tokens decrypt nahi honge aur channel ko reconnect karna padega.


## Instagram aur Facebook Page connection
1. Meta for Developers mein app create karein; Facebook Login aur Instagram Graph API products add karein.
2. Valid OAuth Redirect URI exact set karein: `https://YOUR-DOMAIN/api/admin/meta/oauth/callback`.
3. Server secrets set karein: `META_APP_ID`, `META_APP_SECRET`, `META_REDIRECT_URI`, aur pehle se generated `YOUTUBE_TOKEN_ENCRYPTION_KEY`.
4. SINTU Admin panel mein **Connect Facebook Page** karke Page permissions approve karein.
5. Approved Facebook calendar item par rendered MP4 ID se **Publish Facebook video** karein.
6. Instagram ke liye Page se linked Instagram **Business/Creator** account chahiye. Approved Instagram item par public HTTPS MP4 URL aur caption dein; Meta URL se video fetch karke Reel publish karega. Local-only MP4 URL supported nahi.
7. Meta App Review/Advanced Access, Business Verification, Page role, account eligibility aur Graph API rate limits apply. Public users ke launch se pehle Meta approval complete karein.
8. Publishing hamesha manual admin confirmation se hoti hai; scheduled auto-publishing abhi enabled nahi.


## TikTok Direct Post connection
1. TikTok for Developers par app banayein; **Login Kit** aur **Content Posting API** products add karein.
2. `user.info.basic` aur `video.publish` scopes request/approval karein.
3. Login Kit Web Redirect URI mein exact HTTPS URL register karein: `https://YOUR-DOMAIN/api/admin/tiktok/oauth/callback`.
4. Server environment mein `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` aur stable `YOUTUBE_TOKEN_ENCRYPTION_KEY` set karein.
5. SINTU Admin panel mein Connect TikTok karke account authorize karein.
6. Calendar mein TikTok item approve karein, rendered MP4 ID select karein, TikTok creator ke live privacy options mein se visibility choose karein, caption review karein aur AI-generated label sahi select karein.
7. Video transfer ke baad **Check TikTok status** dabayein. Calendar tabhi Published hoga jab TikTok `PUBLISH_COMPLETE` return kare.
8. TikTok Content Posting API ka app audit required hai public visibility restrictions hatane ke liye. Unaudited client ka Direct Post private-only hota hai. Scope approval, app audit, user authorization aur TikTok rate/creator limits apply.
9. Scheduling ke time automatic publish enabled nahi hai; admin explicit publish action deta hai.
