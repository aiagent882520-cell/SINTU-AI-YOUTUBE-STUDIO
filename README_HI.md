# SINTU AI STUDIO — Creator Workspace

SINTU AI STUDIO is a responsive web/PWA creator workspace. It currently provides an AI text-production desk, specialized content workflows, task history, a 61-role registry, and export of generated text packages.

## Run locally

1. Python 3.10+ install karein.
2. `pip install -r requirements.txt`
3. `.env.example` ko copy karke `.env` banayein.
4. API key sirf local/server `.env` ya hosting provider ke secret manager mein add karein.
5. `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. Browser mein `http://127.0.0.1:8000` kholein.

## AI provider

- `AI_PROVIDER=auto`: OpenAI configured ho to OpenAI, warna Gemini.
- `AI_PROVIDER=openai`: OpenAI Responses API.
- `AI_PROVIDER=gemini`: Google Gemini generateContent API.
- `OPENAI_MODEL` default `gpt-5.5`; `GEMINI_MODEL` default `gemini-2.5-flash`.

API keys and billing are separate from a ChatGPT or Google AI Studio consumer subscription. Provider use can incur charges. Without a configured key, generation is blocked clearly; no fake output is returned.

## Included in this build

- Responsive mobile-first Hindi creator dashboard / installable PWA foundation.
- Dedicated AI workflows: Shorts, long video, thumbnail concepts, script/storytelling, research/fact-check plan, course/lesson/quiz, social content, general content.
- Workflow-aware OpenAI and Gemini text generation adapters.
- Task history, task detail retrieval, status counters and TXT export.
- FastAPI health, provider, agent and workflow endpoints.
- 61-role agent registry. The registry is a roadmap/catalog, not 61 independently running autonomous agents.
- API tests for health, catalog, generation flow, task retrieval and export.

## Not yet integrated / not verified

This repository is not yet a complete autonomous video studio. Actual image/video generation, AI voice, music licensing/provider, FFmpeg rendering pipeline, YouTube/social OAuth publishing, analytics/revenue connectors, autonomous multi-agent execution, managed database and native Android/iOS apps require further integrations and testing. A generated script or production package is not a rendered video file. No publishing or external account action occurs automatically.

## Production notes

- Cloud deployment and live health check must be completed separately.
- SQLite on an ephemeral cloud filesystem is not durable production storage; use managed PostgreSQL before relying on long-term task history.
- Configure secrets in the hosting provider's secret manager. Never commit keys or paste them into chat.
- Public publishing, destructive actions and financial actions must require human approval.
- Paid APIs remain unused until explicitly configured; review provider pricing before enabling.
- Agent statuses must not be marked active without verified implementation and tests.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```
