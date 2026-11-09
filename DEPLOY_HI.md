# SINTU AI STUDIO — Cloud Deployment

## FastAPI Cloud readiness

- Entrypoint: `app.main:app` (configured in `pyproject.toml`)
- Dependencies: `requirements.txt`
- Local secrets and SQLite files excluded by `.fastapicloudignore`
- Runtime health check: `/api/health`

## Deployment account step

Sign in to FastAPI Cloud with the GitHub account that owns this repository, then create/link an app from `aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO`. Deployment requires an authenticated FastAPI Cloud account and a deployment session/token.

## Required environment variables

Set these in the cloud app's Environment Variables / Secrets settings, never in GitHub files:

- `AI_PROVIDER` = `auto`, `openai`, or `gemini`
- `OPENAI_API_KEY` (optional)
- `OPENAI_MODEL` (optional)
- `GEMINI_API_KEY` (optional)
- `GEMINI_MODEL` (optional)

No API key is included in this repository.

## Important data limitation

The current SQLite database is stored on the app filesystem. Cloud instances may scale to zero or be replaced, so SQLite on local app storage is not a production-persistent database. Connect managed PostgreSQL before relying on saved prompts/results in production.

## Verification after deploy

1. Open `/api/health` and confirm `status: ok`.
2. Open `/api/providers` and confirm provider configuration status (no key values should ever be shown).
3. Generate a small text request after adding a provider secret.
4. Confirm generated output and task status.
5. Confirm persistence after a new deployment only after PostgreSQL is connected.

Deployment is not complete until the cloud platform reports a successful deployment and the live health endpoint passes.
