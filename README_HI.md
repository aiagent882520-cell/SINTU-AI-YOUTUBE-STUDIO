# SINTU AI YOUTUBE STUDIO — Creator Workspace

SINTU AI YOUTUBE STUDIO is a responsive web/PWA creator workspace. It currently provides an AI text-production desk, specialized content workflows, task history, a 61-role legacy registry and a complete worker/checker architecture, and export of generated text packages.

## Run locally

1. Python 3.10+ install karein.
2. `pip install -r requirements.txt`
3. `.env.example` ko copy karke `.env` banayein.
4. Free local AI ke liye Ollama install karein aur ollama pull qwen2.5:3b chalayein. `.env` mein `AI_PROVIDER=local` rakhein. Paid API key zaroori nahi.
5. `uvicorn app.main:app --host 0.0.0.0 --port 8000`
6. Browser mein `http://127.0.0.1:8000` kholein.

- Android phone par same Wi-Fi se access ke liye `START_SINTU_NETWORK.bat` chalayein, Windows Firewall mein sirf Private network par Python allow karein, aur phone browser mein PC ka IPv4 address `http://PC-IP:8000` kholein. LAN HTTP par PWA installation ke liye HTTPS hosting/certificate alag se chahiye.

## AI provider

- `AI_PROVIDER=local` (default): local Ollama model; no API key, subscription, or paid request.
- Paid APIs are locked unless BOTH `SINTU_REVENUE_CONFIRMED=true` and `ALLOW_PAID_UPGRADES=true` are set by the owner after revenue and approval. Paid media generation also needs its separate enable flag.
- `AI_PROVIDER=auto`: free-first and always resolves to local Ollama; it never silently falls back to a paid provider.
- `AI_PROVIDER=openai` or `gemini`: optional paid integrations; enable only after revenue and explicit approval.
- Default local model: `qwen2.5:3b`; configure `OLLAMA_MODEL` and `OLLAMA_BASE_URL` as needed.
- Free voice: optional local Piper executable plus a downloaded voice model at `PIPER_MODEL_PATH`.
- Free images: optional local ComfyUI with an API-format workflow JSON at `COMFYUI_IMAGE_WORKFLOW_PATH`. A basic SD checkpoint workflow template is provided in config/comfyui_image_workflow.example.json; copy it, set your installed open checkpoint filename, and point the environment variable to the copied file. Replace workflow input values with `__SINTU_PROMPT__`, `__SINTU_NEGATIVE__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__`, and `__SINTU_SEED__` placeholders.
- Free short video clips: optional local ComfyUI video workflow at `COMFYUI_VIDEO_WORKFLOW_PATH`; export an API-format workflow from ComfyUI and replace the relevant inputs with `__SINTU_PROMPT__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__`, `__SINTU_FRAMES__`, and `__SINTU_FPS__`. Include an output node that writes an MP4 file into ComfyUI history (for example, a compatible video-combine node). The connector checks all workflow `class_type` values against `/object_info`, compares configured checkpoint/model input choices with ComfyUI's advertised installed files where supported, submits the prompt, polls `/history/{prompt_id}`, surfaces ComfyUI execution errors, and downloads the MP4 through `/view`. WebM/GIF may be discovered in history but are not accepted as final studio clips; MP4 is required by the current renderer. Text-to-video is supported; image-to-video needs a separate workflow connector. Node availability does not prove that model weights, model files, VRAM, or the requested resolution are usable. Install the model and any custom nodes required by the exported workflow, then use the Engine diagnostics before generation.
- Free music: local original procedural ambient soundtrack is the default. `MUSIC_PROVIDER=stability` selects the optional paid provider only after revenue and approval.

If Ollama is not installed/running, generation displays setup guidance and does not call a paid provider. Free local models still require compatible hardware.

## Included in this build

- Responsive mobile-first Hindi creator dashboard / installable PWA foundation.
- Dedicated AI workflows: Shorts, long video, thumbnail concepts, script/storytelling, research/fact-check plan, course/lesson/quiz, social content, general content.
- Free-first local Ollama text generation; OpenAI/Gemini remain optional and never auto-selected.
- Task history, task detail retrieval, status counters and TXT / Markdown / JSON exports.
- MP4 assembly accepts saved scene-image IDs, optional generated MP3 narration, a mandatory SINTU AI YOUTUBE STUDIO watermark logo, and a user-uploaded licensed music track (MP3/WAV/M4A/AAC/OGG, 15 MB limit). Music uploads require the media access token; FFmpeg mixes narration and music with configurable music volume and automatic music fade-in/fade-out. Scene transitions support fade or cut. Music rights remain the user's responsibility. Optional Ken Burns slow-zoom-in/out motion is supported; this is not 2D/3D animation.
- Optional Gemini Omni Flash AI video generation (text-to-video and image-to-video) via the Gemini Interactions API; this is a paid connector locked until revenue and explicit approval. Generated clip IDs are automatically queued in the MP4 renderer; multiple generated clips can be joined in order with optional narration and background music. Supports 3–10 second target-duration MP4 clips (duration is prompt-guided; verify actual output length), text-to-video and image-to-video task modes, 9:16 / 16:9, and 360p / 720p / 1080p / 4K output options; 1080p/4K may be upscaled. Requires `ENABLE_PAID_MEDIA_GENERATION=true`, `GEMINI_API_KEY`, and `MEDIA_GENERATION_TOKEN`; paid usage applies. 2D/3D animation choices are visual-style prompts, not a true 3D scene/model pipeline. Generated clips can be assembled into a final portrait MP4 in order. The AI-clip assembly path probes clip durations/audio, preserves source audio at a reduced ambient level, and can mix optional narration and background music. It rejects subtitle/caption burn-in and supports cut or fade-to-black transitions. Fade is not a cross-dissolve; Mixed timeline mode now supports generated still images and AI video clips in one ordered sequence. Still images use the configured scene duration; AI clips can be trimmed by start/end seconds; the original source file is unchanged. Each video clip has independent original-audio gain (0–200%) before mixing voiceover and background music. The interface automatically queues newly generated images/videos into the mixed timeline. The sequence supports optional voiceover, background music, mandatory brand watermark and no subtitle/text overlays, and cut/fade-to-black transitions. The source audio is retained but may need level adjustment per provider clip.
- Free original procedural ambient soundtrack generation (WAV) is available locally with no API key. Optional Stability AI Stable Audio generation (MP3) remains a paid connector and requires revenue, explicit approval, and MUSIC_PROVIDER=stability.
- Optional SRT sidecar export is a separate text file only; SRT is never burned into the exported MP4.\n- Optional free local Piper text-to-speech (WAV) is available when a Piper executable and voice model are installed. OpenAI text-to-speech remains a paid connector locked until revenue and explicit approval. The route also requires a server-side `MEDIA_GENERATION_TOKEN` and the same token in the dashboard field; do not reuse your OpenAI API key as this token.
- FastAPI health, provider, agent and workflow endpoints.
- Existing 61-role registry retained for compatibility, plus 100+ specialist roles with a distinct independent checker role for every specialist.
- All 60 approved video formats, 15 Studio Modules, format-specific role presets, 8 production stages and checker PASS/FAIL revision gates.
- Free-first engine policy: Ollama, ComfyUI, Blender, FFmpeg, Piper and SQLite; no required paid API, subscription or cloud GPU.
- Persistent /api/studio endpoints provide worker/checker production runs, PASS/FAIL revision gates, human approval, project memory, assets, version snapshots and a render queue.
- Local-first provider guard prevents paid model/media calls until revenue is confirmed and the owner explicitly enables upgrades.
- Local AI worker and independent checker use two separate Ollama requests per role pair; actual execution requires the local Ollama runtime.
- The role registry separates every specialist from its checker. The current shared-model gateway is not a claim that all role workers are running as independent background processes; actual worker execution is reported separately.
- Workflow-team API, platform capability API, and explicit provider/integration readiness reporting.
- Basic browser security headers (CSP, frame protection, MIME sniffing protection, referrer and permissions policies).
- API tests for health, catalog, generation flow, task retrieval, export, PWA shell, team routing and capability safety.

## Earning System

- Main dashboard se **Earning System** kholein: `/earnings`.
- Income sources: YouTube ads/memberships/Supers, affiliate, sponsorship, brand deals, digital products, services, licensing aur other.
- Income/expense ledger with confirmed, received, estimated, pending and cancelled states; currency-wise monthly summaries; monthly target/progress; CSV export.
- Estimated aur pending amounts ko received cash nahi maana jata. Different currencies ko bina FX rate ke combine nahi kiya jata.
- This is a bookkeeping and planning foundation, not a payment processor or earnings guarantee. Automatic affiliate attribution, sponsor marketplace, payouts, and automatic YouTube revenue import still require provider-specific integrations and verification.
- API endpoints: `/api/earnings/summary`, `/api/earnings/records`, `/api/earnings/target`, `/api/earnings/export.csv`.
- Local SQLite data file: `sintu_earnings.sqlite3` under `SINTU_DATA_DIR` (or the project data directory). Back up this file with the rest of the local database data.

## Not yet integrated / not verified

This repository is still under active implementation and is not yet a fully autonomous video studio. Long-form AI video scene generation and automatic multi-clip assembly, true editable 2D/3D animation rigs and advanced FFmpeg editing/VFX beyond basic slow zoom, YouTube/social OAuth publishing, analytics/revenue connectors, autonomous multi-agent execution, managed database and native Android/iOS apps require further integrations and testing. Basic storyboard MP4 rendering is available only where FFmpeg is installed. A generated script or production package is not a rendered video file. No publishing or external account action occurs automatically.

## Production notes

- Cloud deployment and live health check must be completed separately.
- SQLite on an ephemeral cloud filesystem is not durable production storage; use managed PostgreSQL before relying on long-term task history.
- Configure secrets in the hosting provider's secret manager. Never commit keys or paste them into chat.
- Public publishing, destructive actions and financial actions must require human approval.
- Paid APIs, paid subscriptions and paid cloud GPUs remain disabled by default. Upgrade only after revenue and explicit user approval.
- Agent statuses must not be marked active without verified implementation and tests.

## Test

```bash
pip install -r requirements-dev.txt
pytest -q
```


### Visual mixed-timeline editor

- Generated still images and AI video clips appear in one ordered visual timeline with image/video previews.
- Move scenes up/down or remove them before rendering.
- Set each still-image scene duration independently (2–12 seconds). AI video duration follows the source clip.
- Choose a cut or fade-to/from-black transition after each scene; the last scene's outgoing transition has no visible effect.
- Edit each scene description independently. Scene descriptions remain in project metadata and are never printed over the video.
- Voiceover and background music continue to mix across the assembled timeline.
- This is a sequential editor, not a multi-track nonlinear editor: no cross-dissolves, keyframes, or frame-accurate scrubbing yet.


### Video trim and sequence preview

- AI video timeline items expose start/end time fields; the selected segment is encoded to a temporary file for rendering, leaving the original generated clip unchanged.
- A browser sequence preview plays timeline images and video sources in order and respects image durations and video trim points. It is a source-sequence check, not a pixel-identical preview of final FFmpeg transitions, subtitles, or audio mix.
- Video trim ranges are checked against source duration by FFprobe; server must provide FFmpeg and FFprobe.

- Per-video source audio level can be adjusted independently from mute to 200% gain; browser preview honors up to 100%, while FFmpeg applies the full selected gain during final render.
- Final MP4 export profiles: 720x1280 portrait, 1080x1920 Full HD portrait, 1080x1080 square, 1280x720 landscape, or 1920x1080 Full HD landscape; 24/30/60 FPS; Standard/High/Maximum H.264 CRF quality presets. Output dimensions describe the render canvas, not guaranteed native source detail; lower-resolution sources may be upscaled. Higher settings increase processing time and output size. No native 4K/8K guarantee.


## Admin: AI Provider Settings & Integrations

- Admin dashboard me **AI Provider Settings** se `auto`, `openai`, ya `gemini` preference select karke SQLite mein persist kar sakte hain. New text generation requests saved selection follow karte hain.
- Provider selection tabhi save hota hai jab selected OpenAI/Gemini API key server environment mein configured ho. `auto` configured provider ko choose karta hai.
- Dashboard sirf key configured hai ya nahi aur model ka naam dikhata hai; secret key kabhi read, accept, display, ya browser mein store nahi hoti.
- Paid media, FFmpeg, YouTube/social publishing aur analytics readiness clearly show hoti hai. YouTube/social/analytics OAuth abhi connected nahi hai.
- Claude, DeepSeek, GLM, Doubao aur Kimi current text adapter mein implemented nahi hain; unko connected/available nahi dikhaya jata.


## Content Calendar & Scheduling
- Content ideas/prompts ko YouTube, Shorts, Instagram, Facebook, TikTok aur website ke liye date/time ke saath save karein.
- Date/time ISO-8601 timezone ke saath store hota hai; dashboard mein local time dikhaya jata hai.
- Naye calendar items default **Needs approval** status mein rehte hain. Admin/editor approval ya cancellation action alag se hota hai.
- Yeh calendar/planning workflow hai, automatic publisher nahi. OAuth/platform APIs, account authorization, upload processing aur explicit publish action abhi alag integration work hai. Approved item apne aap publish nahi hota.


### Instagram aur Facebook publishing
Meta OAuth se Facebook Page connect karne ke baad approved calendar item ka rendered MP4 Facebook Page par manually upload ho sakta hai. Instagram Reels ke liye linked Professional (Business/Creator) account aur Meta ke liye publicly accessible HTTPS MP4 URL required hai. Meta App Review/permissions aur rate limits apply; automatic scheduled publishing enabled nahi hai.


### TikTok Direct Post
TikTok Login Kit OAuth, encrypted server-side tokens, creator privacy options, approved calendar items se MP4 Direct Post upload aur publish-status polling add kiya gaya. TikTok Developer App, Login Kit, Content Posting API, `video.publish` approval, user consent aur app audit required ho sakte hain. Unaudited app posts private-only rehte hain. Video transfer aur final TikTok publishing alag states hain.


### Unified Publishing Dashboard & History
Admin dashboard mein YouTube, YouTube Shorts, Facebook, Instagram aur TikTok ke platform publish events ek jagah dekh sakte hain. Platform/status filters, event totals, timestamps, external post IDs aur available post links dikhte hain. History ab se record hoti hai; pehle ke publish records automatically reconstruct/backfill nahi kiye ja sakte. TikTok transfer aur final processing states alag events hain.


### YouTube Channel Analytics
Admin-only dashboard reads official YouTube Analytics API reports for the connected channel: daily views, estimated watch minutes, average view duration, subscribers gained/lost, and top videos by views. Date range is selectable (up to 365 days). Google Cloud must have YouTube Analytics API enabled, and the connected Google account must own or manage the channel. Recent metrics can be delayed. This initial report also requests estimated revenue, estimated ad revenue, Premium revenue, gross ad revenue, ad impressions and playback-based CPM when the channel is in YPP and monetary OAuth permission is granted. Revenue is estimated and may be adjusted at month end. Thumbnail impressions and CTR use the YouTube Reporting API channel_reach_basic_a1 daily report; an admin must enable the report job, and the first report may take 24 hours or longer.

### Publishing Performance Overview
Admin-only dashboard summarizes up to 250 actual recorded publishing events, grouped by platform and status. These internal event counts are separate from YouTube channel analytics.

### Social Publishing Control Center
Admin dashboard mein YouTube, Facebook/Instagram aur TikTok ke connection status, server OAuth credentials aur token encryption readiness ek combined panel mein dikhte hain. Connected account ka status actual OAuth connection se aata hai; "Ready to connect" ka matlab credentials configured hain, account connected nahi. Public publishing ke liye har post par admin approval aur platform permissions phir bhi required hain.

### Scheduled Publishing Queue
Admin dashboard mein approval-pending, agle 24 ghante ke approved posts, due posts aur future schedule alag counters ke saath dikhte hain. Queue UTC timestamps ko browser ke local timezone mein display karti hai. Yeh scheduler abhi reminder/queue mode mein hai; public publishing apne-aap nahi hoti. Har platform par publish karne ke liye admin ka separate confirmation aur connected official account zaroori hai.


### YouTube Audience Retention
- Admin-only endpoint: `GET /api/admin/youtube/retention?video_id=VIDEO_ID`.
- Returns the official per-video audience-retention curve using `elapsedVideoTimeRatio`, `audienceWatchRatio`, `relativeRetentionPerformance`, `startedWatching`, and `stoppedWatching`.
- One video ID per query; defaults to the latest 28 complete days and accepts a maximum 365-day date range.
- Requires an authenticated admin, connected YouTube channel, and YouTube Analytics API access. Retention availability depends on YouTube's reporting for that video.
- Audience watch ratio is not a unique-viewer percentage and can exceed 100% when viewers rewind; relative retention is a 0–1 comparison against videos of similar length.


### YouTube Comments Analyzer
- Admin-only endpoint: `GET /api/admin/youtube/comments?limit=50` (1–100 recent channel comments).
- Reads recent top-level channel comments using YouTube Data API v3 and the connected channel.
- Shows simple keyword-based possible-spam, positive, negative and question labels plus suggested reply drafts.
- Labels are heuristic triage, not an AI verdict. Reply suggestions are drafts only; this feature does not publish replies, delete, hide or approve comments.
- Requires YouTube Data API v3 enabled and an authenticated connected channel with comment-read access.


### YouTube Comments pagination
The admin comments analyzer loads 50 comments per page from the official YouTube Data API. Use **Load more comments** to continue with the API-provided page token; counts and displayed comments accumulate for the current refresh session. Labels remain keyword heuristics and reply suggestions remain draft-only.
\n\nThe comments panel can export the currently loaded comments as CSV. Active search and category filters are applied to the export; loading more comments adds them to the available export set.\n

### Manual YouTube comment review
Admins can assign an internal review status (Pending, Reviewed, Follow-up, Resolved) and save a private note in SINTU's SQLite database. The state is keyed by YouTube comment ID and is shown again when comments are loaded. This is an internal workflow only: it does not delete, hide, approve, report, or reply to comments on YouTube.


Community review queue controls: admins can filter loaded comments by category and internal review status, search comment text/author/private notes, and sort by newest, likes, or possible-spam heuristic. CSV export uses the same active filters and sort order. These are internal triage controls; YouTube-side moderation remains manual and separate.


Persistent Community Review Queue: saved comment reviews now keep a snapshot of author, comment text, video ID, publication time, likes, heuristic category, internal status, private note and last-updated timestamp. Admins can retrieve the queue independently of the currently loaded YouTube comment page, filter by status and page through saved records. This snapshot is internal to SINTU and does not perform YouTube moderation actions.

Saved Community Review Queue controls now support searching across author, saved comment text, internal notes and video ID; category filtering for spam/sentiment/question labels; and sorting by most recently reviewed, most liked, or possible-spam first. Filters and search work with server-side pagination.

Saved Community Review Queue CSV export downloads every matching saved review, not only the currently visible page. Export respects the selected review status, category, search text and sorting order.

Admins can update the status and internal note of previously saved queue entries directly from the Saved Community Review Queue. Saving updates only SINTU's internal record and never deletes, hides, approves or replies to a YouTube comment.


Review History / Audit Trail records each saved comment review creation and update with UTC timestamp, previous and new status, and whether the internal note changed. Admins can inspect the latest 100 events per saved comment from the queue. History stores change metadata rather than duplicating private note contents; it is an internal SINTU audit trail and does not reflect or trigger YouTube moderation actions.


Bulk Community Review lets admins select up to 100 saved comments from the visible queue pages and apply one internal review status (Pending, Follow-up, Reviewed or Resolved). Every affected comment receives an audit-history event. The operation validates that every selected record exists before changing any record; if one is missing, no partial update is applied. A confirmation is shown before the bulk update. This feature never deletes, hides, approves or replies to comments on YouTube.


Community assignment and follow-up: admins can assign selected saved comment reviews to an internal owner/team label and set an optional follow-up date. The operation is limited to 100 selected records, validates all IDs before updating any, and records old/new owner and follow-up date in the internal audit history. These are internal SINTU fields only; no YouTube moderation or reply action is triggered.


Follow-up dashboard: the saved community review queue can be filtered by internal owner and follow-up date (overdue, today, upcoming or unscheduled). The workload summary reports total, overdue, due-today, upcoming, unscheduled and resolved counts, with counts grouped by internal assignee. This is a dashboard summary, not a push notification or scheduled reminder; no YouTube action is performed.


Due follow-up inbox: the community review dashboard now lists open overdue and due-today follow-ups (resolved and future-dated items are excluded), shows the owner and due date, and lets an operator open the matching filtered queue. This is an in-app internal work queue, not a push notification, and it does not perform moderation or publishing actions on YouTube.


Team performance metrics: the community follow-up workload summary now reports open and resolved review counts, overall resolution rate, and per-owner resolution rate and follow-up-date coverage, alongside overdue and due-date counts. These are descriptive metrics from SINTU's saved internal queue only; they are not YouTube channel analytics or a standalone employee-performance assessment.


Follow-up workload CSV export: the community review workload panel can download a CSV containing the overall queue totals and per-owner open/resolved counts, overdue/due-today/upcoming counts, resolution rate, and follow-up coverage. The export is based only on SINTU's internal saved review records; it does not trigger YouTube actions.


## Complete Production Studio (API-independent foundation)

- Production format catalog includes Shorts, long-form, Reels, TikTok, square/landscape social, documentary, tutorials, course lessons, explainers, 2D/3D-style storyboards, avatar presenter briefs, faceless videos, ads, music videos, podcast clips, slideshows, mystery stories and current-affairs explainers.
- Every format includes aspect ratio, recommended resolution, duration guidance and an honest readiness label.
- End-to-end pipeline checklist: brief, research/fact-check, script/storyboard, assets, edit, QA, export and approval/publishing.
- Ready-made Hindi presets and a project brief builder are available without provider API keys.
- Drafts are saved locally in the current browser/device and can be exported as JSON. They are not cloud-synced.
- The catalog is a target-format list, not a promise that every format can already be rendered. Native 2D/3D rigs, talking-avatar rendering, autonomous agents and platform publishing still need their dedicated engines and approvals.


### Server-synced Production Projects

- Production Studio briefs can be saved to the authenticated user's SQLite workspace through `POST /api/projects`; drafts are no longer limited to one browser.
- List, open, update, delete and JSON export endpoints are available. Project records are scoped to the signed-in username; project IDs are random 128-bit hex identifiers.
- The UI keeps an offline local-browser fallback if server sync is unavailable. Local fallback drafts remain on that browser and are not automatically synchronized.
- Server project data is stored in the configured SINTU data directory. Use a persistent volume and backups in deployment.
- These project records store planning briefs and pipeline metadata; they do not imply that AI generation, video rendering or social publishing has occurred.


### Production Brief to AI Package

- Production Studio includes a direct action that sends the current brief to the existing AI generation API and selects a workflow based on the chosen format (Shorts, long-form, course, social, script or research).
- Successful output is saved in the existing task history and shown in the Production Studio. Provider-not-configured and provider errors are shown honestly; no placeholder output is fabricated.
- The button uses the same server-side OpenAI/Gemini provider configuration as the rest of the app. API keys remain server-side.


- AI generation is linked to a saved project through `POST /api/projects/{project_id}/generate`; the generated task ID and latest status are recorded on that project. The generation endpoint enforces the existing workflow catalog and provider configuration.


### PWA Offline Shell

- The service worker cache version is incremented when the shell changes and includes the production studio JavaScript/CSS plus a static offline fallback page.
- Authenticated dashboard HTML and API responses are not cached. Offline mode shows a safe reconnect page rather than caching private account data.


## One-click Windows start

1. Install Python 3.10 or newer on Windows.
2. Download/clone the repository and double-click `START_SINTU_WINDOWS.bat`.
3. The launcher creates a private `.venv`, installs Python packages, creates a random local admin password/session secret in the ignored `.env`, and starts the dashboard at `http://127.0.0.1:8000`.
4. The first run prints the admin username and newly generated password in the command window. Save that password. The launcher does not create API keys; add provider credentials to `.env` later if/when needed.
5. Keep the command window open while using SINTU. FFmpeg is optional for video rendering; install it separately if local MP4 rendering is needed.

- Generated task output is fetched through the project-owner-checked route `GET /api/projects/{project_id}/task-output`, rather than exposing another user's task by ID from the Production Studio card.


## Full studio execution
- Production Studio shows all 60 formats, 15 modules and every specialist/checker pair.
- Save a project, then create a production run. Each worker task is queued in order and later tasks stay blocked until the independent checker passes the current task.
- Use Run All Specialists + Checkers for one-click sequential background execution through Ollama. Each specialist and checker receives a separate local-model request. The run pauses on the first checker FAIL or local-model error, can be resumed, and final completion requires explicit human approval.
- Project memory, asset metadata, version snapshots and render queue are stored in the local SQLite database and scoped to the signed-in owner.
- The render queue is durable and can execute jobs through the existing FFmpeg renderer. The one-click agent pipeline runs as an in-process background task; its progress is persisted in SQLite and can be resumed after a server restart.

## Windows setup
1. Run START_SINTU_WINDOWS.bat to create the virtual environment, install Python dependencies and start the dashboard.
2. Install Ollama separately, then run `ollama pull qwen2.5:3b` in CMD. On an 8 GB RAM computer, use a small quantized model and keep expectations modest.
3. Install FFmpeg and ensure `ffmpeg` is on PATH for MP4 export. Blender can be installed and added to PATH for local 3D scene rendering; ComfyUI and Piper can be installed later as needed.
4. Keep `.env` private. API keys, OAuth credentials, paid models, cloud GPUs and subscriptions are not required to start the core studio.


### Free local media connectors
- Piper TTS: set PIPER_EXECUTABLE and PIPER_MODEL_PATH to an installed Piper binary and compatible voice model. The API serves local WAV output without a media token.
- ComfyUI images: export a workflow in API format, set COMFYUI_IMAGE_WORKFLOW_PATH, and replace prompt/negative/width/height/seed inputs with the documented SINTU placeholders. ComfyUI is restricted to localhost.
- SINTU अब केवल JSON file मौजूद होने पर ComfyUI को Ready नहीं दिखाता: workflow node structure और `__SINTU_PROMPT__` placeholder validate होते हैं, फिर local `/system_stats` health probe होता है। Dashboard अलग-अलग बताता है कि workflow valid है या ComfyUI server offline है।
- Image workflow starter: `config/comfyui_image_workflow.example.json` को copy करें, `YOUR_OPEN_MODEL_CHECKPOINT.safetensors` को अपने installed checkpoint के exact filename से बदलें, और ComfyUI के API prompt format में export की गई file का path `COMFYUI_IMAGE_WORKFLOW_PATH` में दें। यह template standard ComfyUI nodes पर आधारित है; checkpoint/model डाउनलोड अलग से करना होगा।
- Procedural music: original ambient WAV generation works without a model or API. It is a procedural soundtrack, not a trained generative music model.
- Video AI: local ComfyUI video workflow support is available when you install/configure a compatible open model and workflow. Gemini remains an optional paid connector. FFmpeg/Blender handle editing/rendering; no unlimited free cloud text-to-video model is promised for low-memory hardware.


### Free local Blender 3D rendering
- The dashboard includes a Local Blender 3D Studio panel. It accepts a validated JSON list of primitive objects (cube, sphere, cylinder, cone, torus या monkey head) and renders an animated H.264 MP4 through Blender in background mode.
- No Python code from the user is executed; only supported JSON shapes, positions, scales and colors are accepted.
- Install Blender, add its executable to PATH, or set BLENDER_EXECUTABLE. This creates starter 3D scenes and turntable-style object animation; advanced character modeling/rigging still needs compatible Blender assets and specialist workflows.


## Mandatory video branding and clean-frame policy
- हर final MP4 export (storyboard, AI clips, mixed timeline और Blender 3D) में SINTU AI YOUTUBE STUDIO का logo watermark नीचे दाएँ अपने-आप लगाया जाता है।
- वीडियो narration/dialogue कम से कम 95% हिंदी (देवनागरी) होनी चाहिए; voiceover generator इससे कम हिंदी text अस्वीकार करता है।
- Scene titles, descriptions, spoken words, subtitles, captions, transcripts, karaoke highlights और दूसरे text overlays वीडियो frames पर नहीं लिखे जाते। Render API subtitle/caption payload अस्वीकार करता है और Blender scene builder 3D text objects अस्वीकार करता है।
- AI visual prompts request clean frames with no generated logos or watermarks; the final renderer adds the official SINTU brand mark after the visual is generated.
- Thumbnail and YouTube metadata text are separate assets and are not burned into video frames.
- SRT sidecar generation, if used, creates a separate file; it is not included in the MP4.


### 60 format render capability map
- `GET /api/rendering/formats` सभी 60 catalog formats के export profiles, default resolution, FPS options, H.264 output, watermark policy और current capability limits देता है।
- `GET /api/rendering/formats/{format_id}` किसी एक format का profile देता है।
- `POST /api/render` में optional `format_id` देने पर उसी format की default resolution लागू होती है; 360°, VR, AR और virtual-production requests specialised renderer तैयार होने तक 501 के साथ रोकी जाती हैं।
- Generic FFmpeg export केवल supplied scene images या MP4 clips को assemble करता है; यह अपने-आप AI scenes generate नहीं करता।
- 360°, VR, AR और virtual-production formats को specialised pipeline बनने तक स्पष्ट रूप से blocked दिखाया जाता है। बाकी formats के लिए भी native generation को अभी ready नहीं बताया गया है।
- 3D/film/hybrid formats में Blender optional native engine है; Blender installation और configured scene workflow जरूरी है।
- Format profiles का automated test है; सभी 60 formats का full production shoot/render QA अभी complete नहीं है।

### Production run से final MP4 export
- `POST /api/production/runs` से format-specific Builder/Checker और पाँच final reviewer gates वाला package बनता है।
- सभी gates PASS होकर run `completed` होने के बाद ही `POST /api/production/runs/{run_id}/render` final MP4 export कर सकता है।
- Render request में उसी format का `format_id`, scene descriptions और उपलब्ध scene image IDs / AI video IDs / voiceover ID / music ID दें। Existing FFmpeg renderer SINTU watermark लगाकर MP4 बनाएगा।
- Render result production run में attach होता है; `GET /api/production/runs/{run_id}` में render metadata दिखाई देता है।
- Mixed timeline के लिए अब structured `timeline_items` भी उपलब्ध है: हर item में `kind` (`image` या `video`), `asset_id`, image के लिए `duration`, video के लिए `trim_start` / optional `trim_end`, `audio_volume` और `transition` दें। पुराने string-based `timeline` requests backward-compatible हैं।
- उदाहरण: `{"timeline_items":[{"kind":"image","asset_id":"<32-char-image-id>","duration":5,"transition":"fade"},{"kind":"video","asset_id":"<32-char-video-id>","trim_start":1.5,"trim_end":6,"audio_volume":0.25,"transition":"cut"}]}`. यह केवल पहले से generated assets को जोड़ता है; AI video generation engine अपने-आप नहीं चलाता।
- यह final assembly stage supplied media पर निर्भर है। AI image/video assets अपने-आप generate नहीं होते; उनके local engines/workflows पहले configure और run करने होंगे।
- YouTube publishing इस endpoint से नहीं होती; अलग OAuth connection और explicit human approval जरूरी है।

### Dashboard engine diagnostics
- Image और AI Video capability status अब local ComfyUI की server reachability, workflow validity, node verification, missing custom nodes और missing model choices dashboard पर दिखाता है।
- ये diagnostics ComfyUI `/system_stats` और `/object_info` के advertised data पर आधारित हैं; model weights का वास्तविक load, GPU memory sufficiency और सफल render अलग runtime test से ही confirm होंगे।
- Local workflow file path या API credentials dashboard response में expose नहीं किए जाते।
