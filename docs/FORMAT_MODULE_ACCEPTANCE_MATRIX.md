# SINTU format and module acceptance matrix

> Generated from `app/studio_scope.py` on 2026-11-19 at main SHA `4edbdb90efbf8ee3cb0a08cd5be9a5db80e9ae23`.
> IMPORTANT: Catalog registration is not implementation proof. Every row starts UNVERIFIED until its own acceptance test produces and inspects a real output.

## Video formats (60)

| # | Format ID | Catalog name | Declared stage | Preset | Acceptance status | Evidence required |
|---:|---|---|---|---|---|---|
| 1 | `youtube-shorts` | YouTube Shorts | `ready_for_api` | `short` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 2 | `youtube-long` | Long-form YouTube videos | `production_workflow` | `long` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 3 | `instagram-reels` | Reels | `production_workflow` | `short` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 4 | `podcast` | Podcasts | `production_workflow` | `podcast` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 5 | `educational` | Educational videos | `production_workflow` | `education` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 6 | `advertisement` | Advertisements | `production_workflow` | `ad` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 7 | `vlog` | Vlogs | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 8 | `gaming` | Gaming videos | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 9 | `documentary` | Historical documentaries | `production_workflow` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 10 | `nature-documentary` | Nature documentaries | `production_workflow` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 11 | `investigative-documentary` | Investigative documentaries | `research_required` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 12 | `science-documentary` | Science documentaries | `research_required` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 13 | `biography` | Biographies | `research_required` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 14 | `mystery-documentary` | Mystery documentaries | `research_required` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 15 | `travel-documentary` | Travel documentaries | `production_workflow` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 16 | `crime-documentary` | Crime documentaries | `research_required` | `documentary` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 17 | `2d-cartoon` | 2D cartoon animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 18 | `anime` | Anime animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 19 | `motion-graphics` | Motion graphics | `production_workflow` | `motion` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 20 | `whiteboard-animation` | Whiteboard animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 21 | `story-animation` | Story animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 22 | `cut-out-animation` | Cut-out animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 23 | `3d-animation` | 3D character animation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 24 | `3d-architectural-animation` | 3D architectural animation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 25 | `3d-product-animation` | 3D product animation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 26 | `3d-simulation` | 3D simulation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 27 | `3d-fantasy-animation` | 3D fantasy animation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 28 | `3d-vfx-animation` | 3D VFX animation | `prompt_and_storyboard` | `3d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 29 | `cinematic-movie` | Cinematic movies | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 30 | `short-film` | Short films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 31 | `fantasy-film` | Fantasy films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 32 | `sci-fi-film` | Sci-fi films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 33 | `action-film` | Action films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 34 | `romantic-film` | Romantic films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 35 | `horror-film` | Horror films | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 36 | `historical-film` | Historical films | `research_required` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 37 | `stop-motion` | Stop motion | `production_workflow` | `stop` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 38 | `clay-animation` | Clay animation | `production_workflow` | `stop` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 39 | `puppet-animation` | Puppet animation | `production_workflow` | `stop` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 40 | `frame-by-frame` | Frame-by-frame animation | `prompt_and_storyboard` | `2d` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 41 | `white-background-explainer` | White background explainer | `production_workflow` | `education` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 42 | `kinetic-typography` | Kinetic typography | `production_workflow` | `motion` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 43 | `lyric-video` | Lyric videos | `production_workflow` | `music` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 44 | `music-video` | Music videos | `production_workflow` | `music` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 45 | `visual-effects-video` | Visual effects videos | `production_workflow` | `vfx` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 46 | `green-screen` | Green screen videos | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 47 | `virtual-production` | Virtual production | `integration_required` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 48 | `360-video` | 360-degree videos | `integration_required` | `immersive` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 49 | `vr-video` | VR videos | `integration_required` | `immersive` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 50 | `ar-video` | AR videos | `integration_required` | `immersive` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 51 | `live-action` | Live-action videos | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 52 | `hybrid-2d-3d` | Hybrid 2D + 3D videos | `production_workflow` | `hybrid` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 53 | `ai-avatar` | AI avatar videos | `integration_required` | `avatar` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 54 | `talking-photo` | Talking photo videos | `integration_required` | `avatar` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 55 | `product-demonstration` | Product demonstration videos | `production_workflow` | `ad` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 56 | `training-corporate` | Training/corporate videos | `production_workflow` | `education` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 57 | `news-reportage` | News/reportage videos | `research_required` | `news` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 58 | `sports-highlights` | Sports highlights | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 59 | `event-video` | Event videos | `production_workflow` | `live` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |
| 60 | `timelapse-hyperlapse` | Timelapse/hyperlapse videos | `production_workflow` | `film` | **PROFILE TESTED / RENDER UNVERIFIED** | Real format-specific render, decoded-frame/audio checks, duration and aspect-ratio validation |


### Per-format profile contract evidence (not render acceptance)
- PR #247 merged at `55fe5493a7aaf6769e3a0bc06429f76b4c943a5e`.
- Exact-head CI run `44749186261`: 8/8 PASS; 817 tests passed on each of Python 3.11, 3.12, 3.13 and 3.14; security audit, Chromium, offline video E2E and Docker build passed.
- `tests/test_format_specific_acceptance.py` names and validates each of the 60 format IDs independently, including resolution/FPS/output contract, source requirements, explicit capability limitations, format-specific worker roles and independent checker mapping.
- This is profile/role contract coverage only. All 60 remain **RENDER UNVERIFIED** until each has its own format-appropriate generated MP4, decoded-frame/audio/duration/aspect-ratio evidence and human review. Specialized 360/VR/AR/virtual-production pipelines remain blocked.

## Studio modules (15)

| # | Module | Registry status | Functional acceptance status | Evidence required |
|---:|---|---|---|---|
| 1 | AI Topic Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 2 | AI Writing Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 3 | AI Prompt Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 4 | AI Storyboard Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 5 | AI Image Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 6 | AI Video Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 7 | 2D Animation Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 8 | 3D Animation Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 9 | AI Film Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 10 | Documentary Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 11 | AI Voice Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 12 | AI Music Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 13 | AI Editing Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 14 | Quality Control Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |
| 15 | YouTube Publishing Studio | Registered | **UNVERIFIED** | UI action + backend route + engine execution + persisted output + failure/retry test |

## Shared acceptance gates

- [ ] Feature has a real backend implementation; a catalog name or UI card alone does not count.
- [ ] Frontend action invokes the correct authenticated API and renders loading, success, empty and error states.
- [ ] Inputs are validated and outputs are persisted with owner/project isolation.
- [ ] Tests exercise both success and failure paths; external engines are not mocked for the acceptance run.
- [ ] Video output is an actual MP4 decoded by FFmpeg/FFprobe; metadata alone is insufficient.
- [ ] Frames are sampled across the full duration and checked for visible content; audio stream is decoded and checked when expected.
- [ ] Source assets, engine/model identity, command, logs, output SHA-256 and timing are recorded.
- [ ] Android and website integration are independently tested; CI builds are not physical-device evidence.

## Known scope constraints from the catalog

- `integration_required` formats (including 360/VR/AR/virtual production and avatar integrations) require dedicated engines and are not considered implemented by generic FFmpeg export.
- `prompt_and_storyboard` indicates planning capability, not an actual specialized animation or 3D render engine.
- `ready_for_api` / `production_workflow` are catalog classifications, not test results.
- The module list is a registry definition, not proof that all 15 modules are operational.

## Current execution note

- This matrix deliberately makes no blanket COMPLETE claim.
- Update a row only with a commit/CI run and a reproducible artifact or physical-device report supporting the exact acceptance criteria.
- Keep unsupported hardware/model integrations marked BLOCKED, not PASS.
