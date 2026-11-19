# Android-first offline media path

SINTU's Android/Termux media-assembly path must not require a desktop GPU,
ComfyUI server, model download, cloud account, or paid API. The separate
specialist text-generation stage has an additional local-model requirement,
documented below.

## Engines used on a phone

| Stage | Free local path | Honest capability label |
|---|---|---|
| Scene images | `app.procedural_art` via Pillow | Procedural illustration; **not generative AI** |
| Hindi narration | Piper Hindi model when already installed; otherwise eSpeak NG Hindi | Local TTS; eSpeak NG is synthetic |
| Background music | SINTU Procedural Composer | Procedurally synthesized audio; **not an AI music model** |
| Video assembly | FFmpeg / FFprobe | Actual MP4 encoding, stream validation and media audit |
| Optional generative image engine | A separately configured and validated ComfyUI host | Local generative AI only when the server, workflow, nodes and models are verified |


## Text-generation requirement (separate from media assembly)

The full specialist production run at `/api/production/runs` requires a
working local text model through Ollama or a loopback OpenAI-compatible server
(for example, a llama.cpp server). The procedural image, TTS, music and FFmpeg
fallbacks do not replace an LLM and are not themselves AI script generation.

- If no local text model is available, the Android client must report that
  prerequisite and must not create a production run that will immediately fail.
- Do not automatically install a runtime or download model weights on a
  low-memory phone. A model must be chosen and its memory, storage, language
  quality and license checked before an owner-approved installation.
- A user-supplied Hindi narration and scene prompts can still be rendered with
  the local media engines where the relevant rendering route is enabled.

## Low-resource safety

- Do not download Stable Diffusion weights or build PyTorch automatically on
  the Android phone.
- Do not treat a reachable ComfyUI URL or a configured workflow file alone as
  proof that image generation works.
- Keep image dimensions bounded by the selected output profile and clean up
  partial assets when a render fails.
- Discover the Termux `espeak-ng` executable before the Debian-compatible
  `espeak` name. An explicitly configured `ESPEAK_EXECUTABLE` remains
  authoritative and is not silently replaced.
- Keep paid providers disabled unless the owner explicitly enables them after
  the project earns revenue.

## What a successful offline render proves

A passing render proves that the selected procedural/local assets were
assembled into a valid MP4 and passed the configured media checks. It does not
prove generative-AI image/video creation, natural human-quality narration, or
that every catalogued video format has a complete dedicated engine.

## Device validation

Run the normal Termux self-test and project health/forensic audits on the
actual phone after updating. CI on a hosted Linux runner is useful regression
evidence, but it is not a substitute for a real on-device render, thermal,
storage, memory, and recovery test.


## Persistent offline media library

The browser/PWA media library now has a device-local IndexedDB queue and a server-side content-addressed media index:

- Import image, audio or video files into IndexedDB while offline. The file Blob and queue state survive page reloads; browser storage quota and eviction policies still apply.
- When online, the client retries queued uploads in the foreground and when the browser reports network restoration. A manual sync button can force a retry. This does **not** claim Android OS background execution or guaranteed upload while the browser is closed.
- Server import is streamed to a temporary file, limited to 256 MiB per item, hashed with SHA-256 and atomically linked into `SINTU_DATA_DIR/offline_media`. The SQLite index makes repeated uploads of identical bytes idempotent, including renamed duplicates.
- Downloads verify the indexed SHA-256 before serving. Unsafe symlinks, unsupported extensions, empty/oversized files and tampered stored content are rejected. Stale partial upload files older than 24 hours are cleaned; recent `.part` files are preserved.
- The server stores the original media bytes; it does not claim that an imported file is valid/renderable until a dedicated media probe is run.
- Queue status `SYNCED` means the server accepted and indexed the exact bytes; it does not mean the file was decoded, rendered or published.

Remaining work: Android native WorkManager/background retry, cancellation and resume of interrupted large uploads, authenticated device testing, and end-to-end media decode validation remain separate tasks.
