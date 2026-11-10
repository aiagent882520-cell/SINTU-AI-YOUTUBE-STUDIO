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
- Task history, task detail retrieval, status counters and TXT / Markdown / JSON exports.
- MP4 assembly accepts saved scene-image IDs, optional generated MP3 narration, optional burn-in captions, and a user-uploaded licensed music track (MP3/WAV/M4A/AAC/OGG, 15 MB limit). Music uploads require the media access token; FFmpeg mixes narration and music with configurable music volume and automatic music fade-in/fade-out. Scene transitions support fade or cut. Music rights remain the user's responsibility. Optional Ken Burns slow-zoom-in/out motion is supported; this is not 2D/3D animation.
- Optional Gemini Omni Flash AI video generation (text-to-video and image-to-video) via the Gemini Interactions API. Generated clip IDs are automatically queued in the MP4 renderer; multiple generated clips can be joined in order with optional narration and background music. Supports configurable 3–10 second MP4 clips with generated synchronized audio, text-to-video and image-to-video task modes, 9:16 / 16:9, and 360p / 720p / 1080p / 4K output options; 1080p/4K may be upscaled. Requires `ENABLE_PAID_MEDIA_GENERATION=true`, `GEMINI_API_KEY`, and `MEDIA_GENERATION_TOKEN`; paid usage applies. 2D/3D animation choices are visual-style prompts, not a true 3D scene/model pipeline. Generated clips can be assembled into a final portrait MP4 in order. This assembly mode currently uses hard cuts, does not preserve audio embedded inside source AI clips, and does not yet burn subtitles or mix still-image storyboard scenes into the same clip sequence.
- Optional AI music generation via Stability AI Stable Audio 3.0 text-to-audio API (5–360 seconds, MP3). Requires `ENABLE_PAID_MEDIA_GENERATION=true`, `STABILITY_API_KEY`, and `MEDIA_GENERATION_TOKEN`; paid usage is disabled by default. Generated track can be selected for MP4 rendering.
- SRT subtitle export with configurable per-line timing.\n- Optional OpenAI text-to-speech MP3 voiceover; disabled by default and requires `ENABLE_PAID_MEDIA_GENERATION=true` plus a server-side `OPENAI_API_KEY`. Paid provider usage may apply. The route also requires a server-side `MEDIA_GENERATION_TOKEN` and the same token in the dashboard field; do not reuse your OpenAI API key as this token.
- FastAPI health, provider, agent and workflow endpoints.
- 61-role specialist catalog with workflow-based team routing across all 8 workflows.
- The configured model receives selected role missions in one coordinated request. This is not 61 independent autonomous agents or parallel model sessions.
- Workflow-team API, platform capability API, and explicit provider/integration readiness reporting.
- Basic browser security headers (CSP, frame protection, MIME sniffing protection, referrer and permissions policies).
- API tests for health, catalog, generation flow, task retrieval, export, PWA shell, team routing and capability safety.

## Not yet integrated / not verified

This repository is not yet a complete autonomous video studio. Long-form AI video scene generation and automatic multi-clip assembly, true editable 2D/3D animation rigs and advanced FFmpeg editing/VFX beyond basic slow zoom, YouTube/social OAuth publishing, analytics/revenue connectors, autonomous multi-agent execution, managed database and native Android/iOS apps require further integrations and testing. Basic storyboard MP4 rendering is available only where FFmpeg is installed. A generated script or production package is not a rendered video file. No publishing or external account action occurs automatically.

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
