# SINTU Complete AI Production Factory — Architecture Contract

Status: architecture proposal; implementation and provider connectivity are not implied by this document.
Owner: SINTU Owner.
Master AI / project lead: ChatGPT (OpenAI).
Default operating policy: free-first, open-source-first, local-first where hardware permits.

## 1. Executive rule

SINTU is a complete creator and media-production factory, not a directory of AI products. One brief should be able to flow through research, planning, writing, visual development, audio, editing, review, packaging, distribution planning, analytics and earnings records. Every stage must create inspectable artifacts and pass an explicit quality gate before the next stage.

ChatGPT is the Master AI Brain, Principal Director, chief architect and project-wide coordinator. It owns task decomposition, workflow selection, specialist assignment, cross-department decisions, evidence requirements, final synthesis and release recommendations. Other models are specialist advisors/workers; they do not silently replace the Master AI or become project owner.

The current ChatGPT consumer subscription is not automatically an API credential. A deployed SINTU runtime can call an OpenAI model only when the Owner configures a supported OpenAI API credential and explicitly enables that provider. ChatGPT acting as project lead in this development conversation does not mean a background ChatGPT process is permanently running inside SINTU.

## 2. AI leadership and decision authority

| Layer | Responsibility | Authority |
|---|---|---|
| Owner | Product owner, account owner, approvals, budgets, release and access control | Final authority |
| ChatGPT Master AI | Principal Director, project lead, architecture coordination, task routing, final synthesis and quality oversight | Leads and recommends; cannot override Owner |
| Principal AI Council | Gemini, Claude, DeepSeek and other configured models | Independent evidence-based advice and review |
| Department directors | Research, writing, design, image, video, audio, marketing, security, finance and QA | Coordinate their department tasks |
| Specialist workers | Execute a scoped deliverable | No authority beyond assigned capability |
| Independent checkers | Verify work against acceptance criteria | PASS/FAIL with evidence; cannot approve their own work |
| Automation/runtime | Execute approved deterministic actions | Enforces policy and capability limits; does not invent consent |

Major decisions follow the existing Principal AI Council contract. Council votes are not execution permissions. Owner approval remains mandatory for architecture/security/release decisions, paid actions, public publishing, code integration where required, external data sharing, account permissions and irreversible actions. Never allow an AI agent to self-approve a release or its own failed check.

## 3. Department and tool catalogue

The catalogue is capability-oriented. Tools listed as candidates are not claimed to be installed, licensed for every use, connected, or tested. Provider adapters must be added only after license, API terms, authentication, privacy, cost, rate-limit and output-quality checks.

### A. Research, discovery and strategy
- Free/open: web search, Google Trends, YouTube search/Studio, Google Scholar, Semantic Scholar, arXiv, Crossref, OpenAlex, Wikipedia as a starting point, Reddit public discussions, RSS, browser automation where permitted.
- Optional paid: Perplexity plans, Elicit, Scite, Consensus, Semrush, Ahrefs, BuzzSumo, Similarweb.
- Outputs: research brief, source register, publication dates, evidence excerpts, uncertainty labels, competitor matrix, trend report, keyword map, audience personas and content opportunity score.
- Rule: cite sources, distinguish fact/inference/opinion, check dates and copyright, never fabricate browsing.

### B. Topic, channel and content planning
- Free/open: YouTube Studio analytics, Google Trends, spreadsheets, Python/pandas, keyword planner free features, Reddit and platform-native search.
- Optional paid: vidIQ, TubeBuddy, Semrush, Ahrefs, Exploding Topics.
- Outputs: topic backlog, demand/competition estimates, content calendar, audience fit, series plan, title/thumbnail hypotheses and promotion schedule.
- Rule: do not promise virality, ranking or revenue.

### C. Writing, scripting and editorial
- Free options: local Ollama/llama.cpp models, DeepSeek/Gemini/Claude free tiers where offered, LanguageTool, Vale, LibreOffice.
- Optional paid: OpenAI API, Claude API, Gemini API, Jasper, Grammarly Pro, ProWritingAid.
- Outputs: outlines, scripts, screenplay, documentary narration, dialogue, hooks, short-form variants, descriptions, chapters, captions, translations and editorial notes.
- Review: originality, factual claims, readability, language, tone, age suitability, attribution and plagiarism-risk review.

### D. Thumbnail, brand, graphic and 2D design
- Free/open: GIMP, Krita, Inkscape, Photopea free tier, Penpot, ImageMagick, ComfyUI with appropriately licensed models, Stable Diffusion/FLUX model variants subject to their own licenses.
- Optional paid: Photoshop, Illustrator, Canva Pro, Midjourney, Ideogram, Leonardo, Adobe Firefly, Recraft.
- Outputs: thumbnails, channel art, banners, posters, logos, lower-thirds, title cards, overlays, watermark templates, social cards and brand kits.
- Review: dimensions, legibility at mobile size, contrast, safe margins, brand consistency, rights and text correctness.

### E. Diagrams, data graphics and presentations
- Free/open: Mermaid, diagrams.net, Excalidraw, Graphviz, PlantUML, Matplotlib, Plotly, LibreOffice Impress.
- Optional paid: Visio, Lucidchart, Miro, Whimsical, Tableau.
- Outputs: flowcharts, mind maps, system architecture, storyboards, charts, timelines, infographics and slide decks.
- Review: source data, labels, units, accessible contrast and diagram correctness.

### F. 3D, animation, VFX and compositing
- Free/open: Blender, FreeCAD, OpenSCAD, MeshLab, Godot, Natron, OpenToonz, Krita animation, Manim, ComfyUI-compatible workflows.
- Optional paid: Maya, 3ds Max, Cinema 4D, ZBrush, Houdini, Substance 3D, Spline.
- Outputs: 3D assets, scenes, product renders, character animation, motion graphics, simulations, compositing and VFX.
- Review: geometry, rigging, lighting, render time, hardware fit, asset licenses and continuity.

### G. Video generation, editing and rendering
- Free/open: FFmpeg/FFprobe, Kdenlive, Shotcut, Blender, OpenShot, OBS, PySceneDetect, Remotion, local ComfyUI workflows and open video models when hardware/license permit.
- Optional paid: DaVinci Resolve Studio, Premiere Pro, Runway, Kling, Luma, Pika, HeyGen, Synthesia, Veo, Sora and other providers subject to availability and API terms.
- Stock/archives: Pexels, Pixabay, Wikimedia Commons, Internet Archive and other sources only under each asset's actual license and attribution requirements.
- Outputs: Shorts, long-form, explainers, documentaries, tutorials, ads, trailers, podcasts, screen recordings, avatar videos, clips and localized versions.
- Review: decode, duration, resolution, frame rate, audio, black frames, freeze frames, motion, subtitle sync, transitions, watermark, render integrity and visual spot-checks.

### H. Voice, speech, dubbing, music and sound
- Free/open: Whisper, WhisperX, Piper, Audacity, Ardour, SoX, local TTS/ASR models and original procedural audio.
- Optional paid: OpenAI speech APIs, ElevenLabs, PlayHT, Murf, Azure Speech, Google Cloud TTS, Suno and licensed music libraries.
- Outputs: narration, transcription, subtitles, translation, dubbing, voice-over, ambience, foley, sound effects, music beds and mix/master.
- Rule: voice cloning requires explicit informed consent and rights; music/voice commercial rights must be checked per plan and provider.

### I. PDF, document, publishing and file conversion
- Free/open: LibreOffice, Pandoc, ReportLab, Tesseract, Stirling-PDF, OCRmyPDF, ImageMagick and FFmpeg.
- Optional paid: Acrobat Pro, ABBYY FineReader, Foxit, Nitro, CloudConvert.
- Outputs: PDF, DOCX, PPTX, XLSX, e-books, reports, transcripts, metadata and accessible documents.
- Review: fonts, layout, OCR accuracy, links, page count, metadata, accessibility and export integrity.

### J. Social publishing, promotion and community
- Free: platform-native creator studios, Meta Business Suite, YouTube Studio, RSS and approved scheduling APIs.
- Optional paid: Buffer, Metricool, Hootsuite, Sprout Social, HubSpot and social listening products.
- Outputs: channel-specific copy, captions, post variants, campaign plans, community response drafts, moderation queues and calendars.
- Rule: no automatic public posting, messaging, paid promotion or moderation action without configured permissions and explicit Owner policy/approval.

### K. Monetization and business intelligence
- Free/open: SINTU earnings ledger, Python/pandas, DuckDB, Metabase, spreadsheets and YouTube analytics exports.
- Optional paid: Power BI, Tableau, Mixpanel, Amplitude, Shopify, Patreon and affiliate platforms.
- Outputs: revenue/expense tracking, RPM/CPM analysis, sponsorship research, affiliate comparisons, product ideas, membership plans, forecasts and profit reports.
- Rule: estimates are not guaranteed earnings; never fabricate payouts or connect payment/bank accounts without explicit Owner setup and authorization.

### L. Security, privacy, compliance and trust
- Free/open: Semgrep, Bandit, Ruff, Gitleaks, Trivy, OWASP ZAP, Dependency Review, CodeQL where available, ClamAV, pytest security tests and audit logs.
- Optional paid: Snyk, Burp Suite Professional, enterprise SIEM/EDR and managed WAF.
- Outputs: threat models, dependency/SBOM reports, secret scans, vulnerability triage, access reviews, privacy assessments and incident reports.
- Rule: least privilege, secret redaction, tenant isolation, audit trails, no unapproved external data transfer, no destructive security testing against third parties.

### M. Coding, integrations, automation and infrastructure
- Free/open: Python, FastAPI, PostgreSQL, SQLite, Redis, n8n, Dify, Flowise, LangGraph, Ollama, llama.cpp, Open WebUI, Docker, GitHub Actions, Playwright, Selenium and pytest.
- Optional paid: managed cloud, hosted databases, API gateways, observability platforms, Cursor/Copilot and commercial agent services.
- Outputs: provider adapters, jobs, workflows, APIs, dashboards, backups, deployment manifests, tests and monitoring.
- Rule: adapters use timeouts, bounded retries, idempotency, rate limits, structured errors, health checks and explicit budget limits.

## 4. Provider registry and selection contract

SINTU must maintain a central provider registry rather than hard-code vendors into individual departments. Each provider entry records:
- stable provider and capability IDs;
- supported tasks, models, modalities and output formats;
- local/cloud, free/paid/limited-free classification;
- license and commercial-use notes;
- API availability and documented endpoint/schema;
- credential state (never expose secret values);
- estimated cost, quota, rate limits and maximum output;
- privacy/data-retention notes;
- hardware/runtime prerequisites;
- health/last-tested status and test evidence;
- fallback providers and known limitations.

Provider selection order:
1. Owner policy and capability grants.
2. Required quality, format and license constraints.
3. Free/local candidates that are actually available and meet hardware limits.
4. Configured free-tier cloud providers within their published limits.
5. Paid providers only when revenue-confirmed policy and explicit Owner enablement are both satisfied.
6. If no safe provider qualifies, fail clearly or return a draft/manual workflow; never silently bill or pretend success.

A tool being in this catalogue does not mean SINTU has integrated it. Integration status must be one of: planned, adapter-in-progress, credentials-missing, configured-unverified, live-verified, degraded, disabled-by-policy, retired.

## 5. End-to-end production pipeline

1. Intake: user brief, language, audience, platform, format, duration, aspect ratio, deadline, budget and rights constraints.
2. Master AI plan: ChatGPT creates a structured production brief, deliverables, task graph, provider plan and acceptance criteria.
3. Research: gather dated sources, primary evidence, competitor context and claims register.
4. Strategy: choose topic angle, audience promise, format and distribution plan.
5. Writing: outline, script, fact-check, editorial review and Owner approval of sensitive claims.
6. Pre-production: storyboard, shot list, visual style, asset list, voice direction, music direction and watermark/template.
7. Asset creation: images, diagrams, 3D, footage, animation, narration, music and sound effects.
8. Assembly: timeline, cuts, transitions, titles, captions, audio mix, color and branding.
9. Automated QA: schema checks, source/license checks, text checks, media metadata/decode, black/freeze/motion, audio peaks/silence, subtitle timing, resolution and watermark.
10. Independent review: specialist checker plus separate final QA; failed gates return to the responsible stage.
11. Owner review: preview and approve final creative deliverables.
12. Export: create requested formats and checksums; preserve source assets and immutable originals.
13. Promotion pack: title, description, chapters, hashtags, thumbnail variants, captions, platform-specific copy and schedule proposal.
14. Publish: only through Owner-approved connected accounts and explicit per-action approval.
15. Analytics: ingest authorized platform metrics, compare hypotheses and report evidence.
16. Earnings: record actual transactions separately from forecasts and opportunities.

Every stage stores run ID, input/output artifact references, provider/model, prompt/version, source/license evidence, cost estimate/actual, timestamps, worker/checker result and audit event. Runs must be resumable and idempotent.

## 6. Quality gates and non-negotiable safeguards

- No stage is PASS merely because a model returned text or a provider returned HTTP 200.
- Every deliverable is validated against its declared schema and acceptance criteria.
- A checker must be distinct from the worker role; critical deliverables need independent review.
- Research claims need source URLs and dates; unsupported claims are labeled or removed.
- Media outputs must be decoded and sampled; black/frozen media must fail the gate.
- Never overwrite or delete source assets during generation, repair, remux or quarantine.
- Watermarks, logos, templates and stock assets must have traceable ownership/license.
- Preserve project/user data, backups and historical media. No destructive cleanup without Owner approval.
- Do not expose API keys, OAuth tokens, private prompts or personal data in logs or browser payloads.
- Tenant and role permissions are enforced server-side, not only in the UI.
- Paid APIs, subscriptions, cloud GPUs, storage and promotion spend remain disabled until revenue is confirmed and the Owner explicitly enables them.
- Public publishing, public deployment, financial transactions, permission changes and external data sharing require the relevant Owner authorization.
- If a model/tool is unavailable, report unavailable; do not simulate successful execution.

## 7. Hardware-aware deployment profiles

- Android/Termux: orchestration, dashboard, lightweight text tasks, uploads, monitoring and small utilities; do not assume it can run large diffusion/video models.
- Standard CPU computer: planning, writing, research, light image processing, FFmpeg at modest settings and local small language models.
- GPU workstation: ComfyUI, local diffusion/video models, Blender rendering, local ASR/TTS and batch media processing based on measured VRAM/RAM/disk.
- Optional cloud worker: only Owner-approved, budget-capped jobs; shut down idle resources and log actual costs.

Runtime capability probes must run before large model downloads or render jobs. Never auto-install heavyweight models on a low-memory Android device.

## 8. Delivery milestones

- M0 — Inventory: map existing SINTU routes, roles, engines, provider configs, tests and gaps to this architecture.
- M1 — Core contracts: provider registry schema, capability interface, policy engine, cost estimator, audit and artifact manifest.
- M2 — Master orchestration: ChatGPT-led workflow planner, specialist/checker routing, checkpoints, retry/resume and Owner dashboard.
- M3 — Creative verticals: research/writing, thumbnail/image/diagram, audio, video/3D, PDF/document adapters.
- M4 — Distribution/business: metadata packs, scheduling proposals, analytics and earnings reports.
- M5 — Security and release: threat model, integration tests, media QA, load/recovery tests, deployment and Owner acceptance.
- M6 — Provider expansion: add more free and paid tools only through the registry and only after acceptance tests.

## 9. Current-state truth

The repository already has a local-first FastAPI studio, a local model gateway, a Principal AI Council contract, a specialist/checker role registry, format-aware production runtime, optional ComfyUI/Piper/FFmpeg/Blender integrations, YouTube endpoints requiring Owner credentials, and an earnings ledger. These foundations are not proof that every department or provider is production-ready.

The current documented chat route is text-only and does not itself provide full multimodal tool calling, live research/citations, or file/image understanding. Principal provider credentials and live health are separate from the user's ChatGPT subscription. Real local generation requires validated workflows, models, executables and suitable hardware. Physical Android acceptance, live YouTube OAuth/upload, and complete end-to-end media production require separate evidence.

This document defines the target architecture and acceptance contract; it does not mark planned integrations complete.
