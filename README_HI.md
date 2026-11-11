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
- Optional Gemini Omni Flash AI video generation (text-to-video and image-to-video) via the Gemini Interactions API. Generated clip IDs are automatically queued in the MP4 renderer; multiple generated clips can be joined in order with optional narration and background music. Supports 3–10 second target-duration MP4 clips (duration is prompt-guided; verify actual output length), text-to-video and image-to-video task modes, 9:16 / 16:9, and 360p / 720p / 1080p / 4K output options; 1080p/4K may be upscaled. Requires `ENABLE_PAID_MEDIA_GENERATION=true`, `GEMINI_API_KEY`, and `MEDIA_GENERATION_TOKEN`; paid usage applies. 2D/3D animation choices are visual-style prompts, not a true 3D scene/model pipeline. Generated clips can be assembled into a final portrait MP4 in order. The AI-clip assembly path probes clip durations/audio, preserves source audio at a reduced ambient level, and can mix optional narration and background music. It supports one timed subtitle line per clip and cut or fade-to-black transitions. Fade is not a cross-dissolve; Mixed timeline mode now supports generated still images and AI video clips in one ordered sequence. Still images use the configured scene duration; AI clips can be trimmed by start/end seconds; the original source file is unchanged. Each video clip has independent original-audio gain (0–200%) before mixing voiceover and background music. The interface automatically queues newly generated images/videos into the mixed timeline. The sequence supports optional voiceover, background music, one timed subtitle line per item, and cut/fade-to-black transitions. The source audio is retained but may need level adjustment per provider clip.
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


### Visual mixed-timeline editor

- Generated still images and AI video clips appear in one ordered visual timeline with image/video previews.
- Move scenes up/down or remove them before rendering.
- Set each still-image scene duration independently (2–12 seconds). AI video duration follows the source clip.
- Choose a cut or fade-to/from-black transition after each scene; the last scene's outgoing transition has no visible effect.
- Edit each scene description and optional subtitle independently. Blank subtitle slots are supported so captions remain aligned after reordering.
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
