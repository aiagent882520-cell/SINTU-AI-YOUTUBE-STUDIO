# Local ComfyUI workflows for SINTU

Place ComfyUI **API-format** workflow exports in this directory:

- `image_api.json` — image workflow, with `__SINTU_PROMPT__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__` placeholders.
- `video_api.json` — video workflow, with `__SINTU_PROMPT__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__`, `__SINTU_FRAMES__`, and `__SINTU_FPS__` placeholders.

Docker Compose mounts this directory read-only at `/app/config/comfyui`. Install the workflow's custom nodes and model weights in the ComfyUI host installation, not in this directory. Do not commit large model files, private workflows, tokens, or generated media.

The video graph is model/node specific; SINTU deliberately does not invent a generic ComfyUI video graph that may not run on your installed setup. Validate the graph in ComfyUI first, then run `python scripts/live_e2e.py --generate-video` or `--full-studio-e2e`.
