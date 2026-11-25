# SINTU local AI image generation

SINTU supports real local generative image creation through ComfyUI. The bundled
workflow uses the standard ComfyUI SDXL nodes and the checkpoint
`sd_xl_base_1.0.safetensors`. It accepts SINTU prompt, width, height and seed
placeholders and saves generated images through ComfyUI's API.

## Configure

1. Install and run ComfyUI on the same computer/device as SINTU at
   `http://127.0.0.1:8188`.
2. Install an SDXL-compatible checkpoint in ComfyUI's
   `models/checkpoints` directory. The bundled workflow defaults to
   `sd_xl_base_1.0.safetensors`.
3. From the SINTU repository run `bash scripts/setup_comfyui_image.sh`.
4. Restart SINTU and inspect `GET /api/media/image/status` (or the image
   status endpoint exposed by the installed app) for ComfyUI availability.
5. Generate a scene with the image-generation API/UI. SINTU validates and
   stores the returned image locally.

## Device constraints

ComfyUI and SDXL are resource-intensive. Android/Termux phones usually cannot
run SDXL reliably; use a capable local PC on the same trusted network or a
supported local ComfyUI host. The current ComfyUI client intentionally permits
loopback/Docker-host endpoints only; do not expose ComfyUI's unauthenticated
port to the public internet.

The app's procedural renderer is an illustration fallback, not generative AI.
A Wikimedia Commons photograph is a real source photograph, not AI generation.
SINTU reports the provider so these outputs are not confused. Paid APIs remain
disabled by default and are not required for the local ComfyUI path.


## Strict documentary media acceptance

The normal offline E2E can use explicitly labelled local fallbacks so CI remains
fully offline. That is not proof of generative-AI imagery or natural narration.
After configuring ComfyUI and a Piper Hindi voice model, run:

```bash
python scripts/live_e2e.py --offline-video --require-ai-images --require-piper-voice
```

This strict mode fails unless **all 15 scene images** report the
`ComfyUI (local AI)` provider and the narration engine reports `Piper TTS`.
It rejects procedural illustrations, Wikimedia photographs, and eSpeak as
substitutes for those two acceptance requirements. The JSON result records
per-scene providers and the selected voice engine. The command renders a
local test video; it does not publish or upload anything.

For an image-only acceptance run, omit `--require-piper-voice`; for a voice-only
acceptance run, omit `--require-ai-images`. Real pronunciation and overall
voice naturalness still require listening review by the owner before release.
