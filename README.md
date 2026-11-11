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

## Quick start

1. Install Python 3.10+.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and review the settings.
4. For free local text generation, install Ollama and pull a compatible model such as `qwen2.5:3b`.
5. Start the app: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
6. Open `http://127.0.0.1:8000`. After login, use the **Earning System** link or visit `/earnings`.

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

## Important limitations

A format being listed does not mean every format has passed full production rendering tests. A role catalog is not proof of 61 autonomous agents running as separate services. Google Flow, platform permissions, actual YouTube monetization eligibility, automated payout collection, live hosting and end-to-end production on the owner's machine require separate setup and verification. Public publishing and financial actions must remain explicitly approved by the owner.
