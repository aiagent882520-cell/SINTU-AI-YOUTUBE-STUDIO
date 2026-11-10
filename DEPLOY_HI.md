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

4. Open `http://localhost:8000` and check `http://localhost:8000/api/health`.

Docker Compose stores SQLite, generated images, audio, music, and videos in the named `sintu-data` volume mounted at `/data`. Back up this volume. Do not delete it when updating the container.

### Environment variables

Set secrets in the host's secret manager or a protected `.env` file (never commit it):

- `AI_PROVIDER=auto|openai|gemini`
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `STABILITY_API_KEY`
- `MEDIA_GENERATION_TOKEN`
- `ENABLE_PAID_MEDIA_GENERATION=false` (keep false until paid provider costs and credentials are intentionally configured)

API keys are optional for opening the dashboard and using non-provider parts. Paid media generation stays disabled by default.

### Production notes

- A persistent disk/volume is required for the current SQLite database and generated media. The container filesystem alone is not durable.
- Run one app instance when using SQLite. For multi-instance scaling, move tasks and metadata to managed PostgreSQL and media to object storage first.
- Configure HTTPS at the hosting proxy/load balancer. Do not expose the app publicly without authentication and access controls; public deployment is not a substitute for user authentication.
- Configure backups, resource limits, log retention, and monitoring before production use.
- High-resolution video rendering requires sufficient CPU, memory, disk, and execution time.
- YouTube/social publishing and paid AI media providers still require their own supported credentials and permissions.
- A successful Docker build is not a cloud deployment. The host must report healthy and `/api/health` must pass before calling it live.

## FastAPI Cloud note

FastAPI Cloud was considered earlier but no deployment was completed. This Docker setup is platform-neutral and does not create or charge for a hosting account.
