# Local ComfyUI workflows for SINTU

Place ComfyUI **API-format** workflow exports in this directory:

- `image_api.json` — image workflow, with `__SINTU_PROMPT__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__` placeholders.
- `video_api.json` — video workflow, with `__SINTU_PROMPT__`, `__SINTU_WIDTH__`, `__SINTU_HEIGHT__`, `__SINTU_FRAMES__`, and `__SINTU_FPS__` placeholders.

Docker Compose mounts this directory read-only at `/app/config/comfyui`. Install the workflow's custom nodes and model weights in the ComfyUI host installation, not in this directory. Do not commit large model files, private workflows, tokens, or generated media.

The video graph is model/node specific; SINTU deliberately does not invent a generic ComfyUI video graph that may not run on your installed setup. Validate the graph in ComfyUI first, then run `python scripts/live_e2e.py --generate-video` or `--full-studio-e2e`.

## Safe host selection

Do not install ComfyUI, PyTorch, custom nodes, or diffusion weights inside the current Android/Termux phone environment. SINTU's read-only `scripts/engine_probe.py` reports a ComfyUI setup gate and deliberately blocks Termux. For a separately managed non-Termux host, the gate only marks the host eligible for **manual review** when it sees at least 8 GiB currently available RAM and 20 GiB free disk. These are conservative screening thresholds, not a guarantee that a particular checkpoint, resolution, or workflow will fit; GPU/driver compatibility, model size/license, Python/PyTorch support, and workflow-specific custom nodes must still be checked.

The probe never installs software, downloads models, starts ComfyUI, changes services, or starts a render. `auto_install_allowed` and `install_performed` remain false. Until a suitable host and a verified API-format workflow are configured, use SINTU Procedural Art and label it accurately as a procedural fallback, not generative AI.


## Explicit CPU fallback launcher (separate Linux host only)

On a separately managed Linux host that already has ComfyUI and a compatible PyTorch install, run:

```bash
COMFYUI_ROOT="$HOME/ComfyUI" COMFYUI_DEVICE=cpu bash scripts/start_comfyui_cpu.sh
```

The launcher verifies the existing checkout and Python executable, prints the installed PyTorch/CUDA/MPS capability, and starts ComfyUI with `--cpu`. With `COMFYUI_DEVICE=auto`, it selects CPU only when both CUDA and Apple MPS are unavailable. It does not install Python packages, download model weights, modify firewall rules, or claim that inference works. A compatible checkpoint and API-format workflow still need to be installed and verified. CPU inference can be extremely slow and memory-intensive; check the model's license and the host's available RAM before use.

The default listener is loopback-only (`127.0.0.1:8188`). Change `COMFYUI_LISTEN` only when a separately secured Docker/host network requires it; never expose the unauthenticated ComfyUI port to the public internet. Termux/Android remains unsupported for this model-host setup.
