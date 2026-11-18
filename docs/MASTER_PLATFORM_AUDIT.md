# SINTU AI YOUTUBE STUDIO — Master Platform Audit

**Audit date:** 2026-11-18  
**Repository:** `aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO`  
**Audited main commit:** `d2a7c4f4da394c0b00e67d91f97a3a27e5d1c646`  
**Source of truth:** `app/studio_scope.py`, `app/production_catalog.py`, repository Git tree, README and current GitHub/Termux evidence.

## Executive finding

The repository is a substantial Python/FastAPI + responsive browser PWA/Termux creator workspace. It is **not yet a complete autonomous AI assistant platform or native Android application**. Registered modules and formats are not proof that each one has a dedicated working engine or passed an individual render test.

Release status: **NOT READY**. Media production and external publishing remain fail-closed/disabled.

## Repository inventory

- Backend: Python 3 / FastAPI; SQLite persistence; authentication/roles; API middleware; production runtime and orchestration.
- Frontend: `app/static/` HTML/CSS/JavaScript responsive dashboard and PWA service worker.
- Android: Termux install/start/restart/watchdog/bridge scripts; browser PWA support. No native Android Gradle project, manifest, Kotlin/Java source, or APK build configuration exists in the audited Git tree.
- AI text: local Ollama/OpenAI-compatible gateway with optional external adapters. Current Android evidence says Ollama endpoint/model was unavailable at the last engine probe.
- Images/video: ComfyUI connector and workflow templates; actual ComfyUI service/workflow/model availability is not established on the Android device.
- Audio: Piper if a model is configured; eSpeak NG fallback; procedural music and sound effects; FFmpeg mixing/rendering.
- Rendering: FFmpeg/FFprobe MP4 assembly, storyboard/AI clip/mixed timeline paths, 2D procedural animation and Blender integration.
- Research: role/prompt/checklist workflow exists; no verified live web-research/citation connector is established by this repository audit.
- YouTube: OAuth/token storage/channel/analytics/upload routes and mocked integration tests exist; real owner OAuth/channel/upload are not verified. Public publishing remains disabled by safety policy.
- Earnings: local bookkeeping ledger and estimated-revenue sync integration; not a payment processor or revenue guarantee.
- Subscription/billing: no verified complete user subscription/usage-billing system identified in this tree.
- CI: `.github/workflows/tests.yml` and `.github/workflows/project-health.yml`.

## Status definitions

- **COMPLETE AND VERIFIED:** UI + backend + required engine + real output + failure handling + relevant E2E evidence.
- **IMPLEMENTED BUT UNVERIFIED:** implementation appears complete but required runtime/E2E evidence is missing.
- **PARTIALLY IMPLEMENTED:** registry, workflow, UI or backend exists but important integration/capability is missing.
- **NOT IMPLEMENTED:** no implementation found in the audited repository tree.
- **BLOCKED BY EXTERNAL DEPENDENCY:** code path exists but a required model, service, credential, hardware or owner action is unavailable.

## All 15 registered Studio modules

| # | Module | Current status | Evidence / limitation |
|---:|---|---|---|
| 1 | AI Topic Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 2 | AI Writing Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 3 | AI Prompt Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 4 | AI Storyboard Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 5 | AI Image Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 6 | AI Video Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 7 | 2D Animation Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 8 | 3D Animation Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 9 | AI Film Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 10 | Documentary Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 11 | AI Voice Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 12 | AI Music Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 13 | AI Editing Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 14 | Quality Control Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |
| 15 | YouTube Publishing Studio | PARTIALLY IMPLEMENTED | Listed in module registry; no independent end-to-end acceptance evidence for the complete module |

The 15 names above are copied from `STUDIO_MODULES`, not inferred. The separate eight pipeline stages are Brief & goals; Research & fact check; Writing & storyboard; Design & asset creation; Media production; Post-production; Independent quality gates; Final output & publishing.

## All 60 registered video formats

The following rows are extracted from `_FORMAT_ROWS` in the source tree. The listed ratio, resolution and duration are catalog metadata, not measured output guarantees.

| # | Format ID | Format | Group | Ratio | Catalog resolution | Catalog duration | Status |
|---:|---|---|---|---|---|---|---|
| 1 | `youtube-shorts` | YouTube Shorts | Short-form | 9:16 | 1080x1920 | 15–60 sec | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 2 | `youtube-long` | Long-form YouTube videos | Long-form | 16:9 | 1920x1080 | 5–60+ min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 3 | `instagram-reels` | Reels | Short-form | 9:16 | 1080x1920 | 15–90 sec | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 4 | `podcast` | Podcasts | Audio/Video | 16:9 or 9:16 | 1920x1080 | 5–120 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 5 | `educational` | Educational videos | Learning | 16:9 | 1920x1080 | 3–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 6 | `advertisement` | Advertisements | Commercial | 16:9 or 9:16 | 1080p | 6–90 sec | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 7 | `vlog` | Vlogs | Creator | 16:9 or 9:16 | 1920x1080 | 1–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 8 | `gaming` | Gaming videos | Gaming | 16:9 | 1920x1080 | 1–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 9 | `documentary` | Historical documentaries | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 10 | `nature-documentary` | Nature documentaries | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 11 | `investigative-documentary` | Investigative documentaries | Documentary | 16:9 | 1920x1080 | 10–90 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 12 | `science-documentary` | Science documentaries | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 13 | `biography` | Biographies | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 14 | `mystery-documentary` | Mystery documentaries | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 15 | `travel-documentary` | Travel documentaries | Documentary | 16:9 | 1920x1080 | 5–45 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 16 | `crime-documentary` | Crime documentaries | Documentary | 16:9 | 1920x1080 | 8–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 17 | `2d-cartoon` | 2D cartoon animation | 2D Animation | 16:9 or 9:16 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 18 | `anime` | Anime animation | 2D Animation | 16:9 or 9:16 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 19 | `motion-graphics` | Motion graphics | Motion Design | 16:9 or 9:16 | 1920x1080 | 15 sec–5 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 20 | `whiteboard-animation` | Whiteboard animation | 2D Animation | 16:9 | 1920x1080 | 1–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 21 | `story-animation` | Story animation | 2D Animation | 16:9 or 9:16 | 1920x1080 | 1–15 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 22 | `cut-out-animation` | Cut-out animation | 2D Animation | 16:9 | 1920x1080 | 1–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 23 | `3d-animation` | 3D character animation | 3D Animation | 16:9 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 24 | `3d-architectural-animation` | 3D architectural animation | 3D Animation | 16:9 | 1920x1080 | 30 sec–5 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 25 | `3d-product-animation` | 3D product animation | 3D Animation | 16:9 or 9:16 | 1920x1080 | 15 sec–3 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 26 | `3d-simulation` | 3D simulation | 3D Animation | 16:9 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 27 | `3d-fantasy-animation` | 3D fantasy animation | 3D Animation | 16:9 | 1920x1080 | 1–20 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 28 | `3d-vfx-animation` | 3D VFX animation | 3D Animation | 16:9 | 1920x1080 | 15 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 29 | `cinematic-movie` | Cinematic movies | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 30 | `short-film` | Short films | Film | 16:9 | 1920x1080 | 1–40 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 31 | `fantasy-film` | Fantasy films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 32 | `sci-fi-film` | Sci-fi films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 33 | `action-film` | Action films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 34 | `romantic-film` | Romantic films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 35 | `horror-film` | Horror films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 36 | `historical-film` | Historical films | Film | 16:9 | 1920x1080 | 5–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 37 | `stop-motion` | Stop motion | Stop Motion | 16:9 | 1920x1080 | 30 sec–20 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 38 | `clay-animation` | Clay animation | Stop Motion | 16:9 | 1920x1080 | 30 sec–20 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 39 | `puppet-animation` | Puppet animation | Stop Motion | 16:9 | 1920x1080 | 1–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 40 | `frame-by-frame` | Frame-by-frame animation | 2D Animation | 16:9 | 1920x1080 | 15 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 41 | `white-background-explainer` | White background explainer | Explainer | 16:9 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 42 | `kinetic-typography` | Kinetic typography | Motion Design | 16:9 or 9:16 | 1920x1080 | 15 sec–5 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 43 | `lyric-video` | Lyric videos | Music | 16:9 or 9:16 | 1920x1080 | 1–6 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 44 | `music-video` | Music videos | Music | 16:9 or 9:16 | 1920x1080 | 1–8 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 45 | `visual-effects-video` | Visual effects videos | VFX | 16:9 | 1920x1080 | 15 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 46 | `green-screen` | Green screen videos | Live Action | 16:9 or 9:16 | 1920x1080 | 15 sec–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 47 | `virtual-production` | Virtual production | Film | 16:9 | 1920x1080 | 1–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 48 | `360-video` | 360-degree videos | Immersive | 2:1 / 360 | 3840x1920 | 1–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 49 | `vr-video` | VR videos | Immersive | VR | Platform-dependent | 1–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 50 | `ar-video` | AR videos | Immersive | AR | Platform-dependent | 15 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 51 | `live-action` | Live-action videos | Live Action | 16:9 or 9:16 | 1920x1080 | 15 sec–180 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 52 | `hybrid-2d-3d` | Hybrid 2D + 3D videos | Hybrid Animation | 16:9 | 1920x1080 | 30 sec–20 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 53 | `ai-avatar` | AI avatar videos | Avatar | 9:16 or 16:9 | 1080x1920 | 30 sec–15 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 54 | `talking-photo` | Talking photo videos | Avatar | 9:16 or 16:9 | 1080x1920 | 15 sec–5 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 55 | `product-demonstration` | Product demonstration videos | Commercial | 16:9 or 9:16 | 1920x1080 | 30 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 56 | `training-corporate` | Training/corporate videos | Business | 16:9 | 1920x1080 | 2–60 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 57 | `news-reportage` | News/reportage videos | News | 16:9 or 9:16 | 1920x1080 | 1–30 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 58 | `sports-highlights` | Sports highlights | Sports | 16:9 | 1920x1080 | 30 sec–15 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 59 | `event-video` | Event videos | Event | 16:9 | 1920x1080 | 1–120 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |
| 60 | `timelapse-hyperlapse` | Timelapse/hyperlapse videos | Cinematic | 16:9 | 1920x1080 | 15 sec–10 min | PARTIALLY IMPLEMENTED — catalog/preset present; individual real render not evidenced |

**Format status rationale:** all 60 are present in the format registry and role presets. The repository does not currently provide evidence of a successful real, individual render acceptance test for every format. Therefore none is marked COMPLETE AND VERIFIED. Some specialist formats (native 3D, 360/VR/AR, virtual production, AI avatar/talking photo and live capture) require engines/capture/model support beyond generic MP4 assembly and are additionally dependency-blocked until configured and tested.

## Capability audit summary

| Capability | Status | Current evidence / gap |
|---|---|---|
| Responsive website/PWA | IMPLEMENTED BUT UNVERIFIED | Browser UI and service worker exist; no production domain/deployment or cross-device release evidence. |
| Native Android app/APK | NOT IMPLEMENTED | No Android Gradle/manifest/Kotlin/Java project in repository tree; current Android path is Termux + browser PWA. |
| Persistent text-chat assistant | PARTIALLY IMPLEMENTED | PR #183 adds owner-scoped SQLite conversations, bounded multi-turn context, create/list/read/rename/delete, responsive PWA chat UI and blocked/failed message persistence. CI API/UI tests pass; live LLM availability, streaming, file/image inputs, research citations and tool calling remain unverified/not implemented. |
| Local LLM | BLOCKED BY EXTERNAL DEPENDENCY on audited Android setup | Ollama integration exists; Android probe found no reachable model endpoint/model at last recorded probe. |
| Multi-provider text adapters | IMPLEMENTED BUT UNVERIFIED | Local-first gateway and optional provider adapters exist; paid adapters remain locked by policy. |
| Live web research with source citations | PARTIALLY IMPLEMENTED | Research/fact-check roles and prompt workflow exist; live retrieval/citation pipeline not evidenced. |
| Document upload/analysis and image understanding | NOT VERIFIED | No complete end-to-end evidence found in this audit. |
| ComfyUI image/video | BLOCKED BY EXTERNAL DEPENDENCY | Connector/workflow support exists; Android ComfyUI/model/workflow not configured/reachable in last probe. |
| Hindi TTS | IMPLEMENTED BUT UNVERIFIED for quality | eSpeak NG fallback exists; Piper neural Hindi voice model not configured in last probe. Human pronunciation review required. |
| Music and procedural SFX | IMPLEMENTED BUT UNVERIFIED | Procedural generators exist; output-quality acceptance is not a substitute for human listening review. |
| 2D cartoon/story animation | IMPLEMENTED BUT UNVERIFIED | Procedural frame-by-frame vector animation code exists; every format still needs individual render verification. |
| Generic FFmpeg MP4 assembly | IMPLEMENTED BUT UNVERIFIED | Renderer and CI offline E2E exist; real Android generative AI pipeline is not established. |
| Timeline editor comparable to a professional NLE | PARTIALLY IMPLEMENTED | Mixed timeline/scene ordering/render queue backend paths exist; full interactive editing parity is not evidenced. |
| Persistent task/run orchestration | IMPLEMENTED BUT UNVERIFIED | SQLite runs, worker/checker gates and recovery paths exist; autonomous live inference depends on local engines. |
| YouTube OAuth and upload | IMPLEMENTED BUT UNVERIFIED | Routes and mocked API tests exist; real owner consent/channel/upload are not evidenced. |
| Public YouTube publishing | BLOCKED BY SAFETY POLICY | Explicit publishing gate is disabled; do not enable without separate owner authorization and readiness evidence. |
| Earning ledger | IMPLEMENTED BUT UNVERIFIED | Bookkeeping and estimated revenue fields exist; not billing/payment processing. |
| Multi-user SaaS isolation/subscription/usage billing | NOT VERIFIED | No complete tenant isolation, subscription or billing acceptance evidence in this audit. |

## Current Android and CI evidence (2026-11-18)

- Main commit `6c1eb2d`; GitHub Actions run #1301 completed **success**. This is repository CI evidence, not a device generation test.
- Termux Issue #178: latest main fast-forward pull succeeded.
- Termux Issue #179: service restart command succeeded; result says restart was scheduled after current queue result acknowledgement.
- Termux Issue #180: Android regression suite **614 passed, 5 warnings**.
- Termux Issue #187 (post-PR183): Android health audit **15 PASS / 3 FAIL**, pytest **617 passed, 5 warnings**. The three remaining failed media checks are:
  - `3f4c2151e8e640109f464b2c2e9b7569.mp4`
  - `59430f1fb7fd4bdf80cf8b7d9f456098.mp4`
  - `8cfe9da88d5c43d184f3572e371ff4a6.mp4`
- Android health audit #181 found the two previously disputed dim-visible files now PASS under the calibrated pixel checks. This does not resolve the three confirmed full-black files.
- Termux Issue #182: automation self-test **7/7 checks passed** (repository/origin, Python 3.14.10, GitHub CLI auth, API health, worker/bridge and relay singleton).
- Fresh Android engine probe (2026-11-18, Issue #188): Android 15 ARM64, 8 CPU cores, 3,762,049,024 bytes total RAM and 1,290,792,960 bytes available; approx 29.1 GB free storage. `llama-server` binary exists but is not reachable and no GGUF model files are present. `stable-diffusion.cpp` binaries are absent; ComfyUI is unreachable and no workflow is configured. Probe performed no model downloads/builds and started no render. Automatic heavy model download is unsafe on current free RAM; no generative AI image/video model can be claimed available. Issue #189 confirms core_ready=true but production_ready=false due to `local_ai_model` and `comfyui`. Earlier eSpeak NG and FFmpeg/FFprobe availability was reported by the prior Termux health checks; verify again before relying on it.
- No real topic-to-video run using Ollama + ComfyUI + configured neural Hindi voice has been evidenced on Android.

## Critical open blockers

1. Three true full-duration black MP4s remain unresolved. Originals/backups must remain untouched; no speculative regeneration or deletion. Their source/render provenance is still unknown.
2. Local AI generation is blocked until compatible Ollama/model, ComfyUI workflow/models and appropriate hardware/server are configured and tested.
3. Native Android app is absent; current PWA/Termux approach is not an APK.
4. Research/citation, document/image understanding, multi-conversation assistant, subscription/tenant isolation and full editor workflows need implementation or stronger evidence.
5. All 60 format-specific render acceptance tests are outstanding.
6. Real YouTube OAuth/channel connection/upload and production website deployment are not verified.
7. PR #183 assistant chat is now present in the PWA/API but live local-model inference is still blocked by engine availability; streaming, document/image input, web research/citations and tool calling remain open.
8. Full Android reboot/Termux:Boot recovery is not yet verified.

## Execution sequence

1. Keep all production/public-publishing gates disabled while three black MP4 failures and engine readiness remain unresolved.
2. Complete forensic source provenance and safe owner-reviewed repair/replacement for the three black videos; never overwrite originals.
3. Re-probe Android resources and engine availability; configure only hardware-compatible free/open-source local engines or an explicitly optional owner-controlled remote engine.
4. Implement the general AI assistant, research/citations, document/image inputs, persistent conversations and task graph against real engines.
5. Audit and integrate each of the 15 modules with a dedicated acceptance test.
6. Add format-specific rendering profiles, capabilities and individual acceptance tests for all 60 formats; block unsupported native exports.
7. Build and test a native Android application separately from the PWA/Termux launcher.
8. Complete website production build/deployment preparation, tenant/data isolation and security/recovery tests.
9. Verify real local topic-to-video E2E and representative formats; then run the full release gate matrix.
10. Update this audit and `PROJECT_EXECUTION_STATE.md` with commit hashes, logs, exact counts and blockers after each verified tranche.

## Safety invariants

- Free/open-source first; no mandatory paid API, subscription or cloud GPU.
- Do not install/download heavy models without a fresh resource/capacity check.
- Do not claim a model, workflow or voice exists unless runtime diagnostics prove it.
- Never overwrite/delete originals; repair to new files with verified backups and human review.
- No public upload, live publishing, external deployment, billing activation or irreversible action without explicit owner authorization.
- A passing CI suite is not proof that all formats, engines, Android hardware or live publishing work.
