# One-command Termux setup

Run inside the official Termux app (Android):

```bash
pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO/main/scripts/termux_one_command.sh -o "$TMPDIR/sintu-install.sh" && bash "$TMPDIR/sintu-install.sh"
```

On the first run, the installer prints the generated admin username and password once. Save them privately; the password is not printed again on later runs.

The installer is idempotent: it installs Termux packages, clones or fast-forward-updates the selected branch, creates an isolated `.venv`, installs the repository's declared Python requirements, creates a private `.env` only when missing, checks FFmpeg/FFprobe, compiles Python modules and starts Uvicorn on `127.0.0.1:8000`. It preserves existing `.env` and project data. When the Termux `llama-cpp` package is available, it can select and download an official Qwen GGUF model based on detected RAM/free storage and start a loopback llama.cpp server; if package, network, RAM or storage checks fail, the studio install continues without it.

## Important limits

- This installs the application and available local media utilities. It also attempts to install Termux `llama-cpp` and download a Qwen GGUF model when the package is available and available RAM/storage meet safe thresholds. This optional step can be skipped when the package or network is unavailable. ComfyUI workflows and image/video models still require separate compatible setup.
- The installer also attempts the Termux `espeak` package (the Termux package name for eSpeak NG) as a free Hindi TTS fallback. It is synthetic speech, not a natural neural voice; review pronunciation before publishing.
- Ollama is not assumed to be available as a supported Termux package. The local llama.cpp server uses `127.0.0.1:8080`; SINTU detects it automatically. If the installer skips it, configure a compatible local model endpoint after verifying device compatibility.
- YouTube/Meta/TikTok publishing requires the owner's developer app credentials, OAuth consent and platform permissions. The installer never fabricates credentials or publishes without authorization.
- The generated admin password is in the new `.env`; keep it private. If the app's current auth bootstrap does not print credentials, inspect `.env` locally.
- The app is bound to localhost, not exposed to public networks.
- This bootstrap does not claim that all agent roles run as independent daemons. The production runtime remains an orchestrated worker/checker pipeline, and any incomplete integration must remain visibly unavailable rather than report a false success.

## Manual operations

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
tail -f ~/.sintu/server.log
kill "$(cat ~/.sintu/server.pid)"
```
