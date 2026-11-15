# One-command Termux setup

Run inside the official Termux app (Android):

```bash
pkg install -y curl && curl -fsSL https://raw.githubusercontent.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO/feat/one-command-termux-production-bootstrap/scripts/termux_one_command.sh -o "$TMPDIR/sintu-install.sh" && bash "$TMPDIR/sintu-install.sh"
```

The installer is idempotent: it installs Termux packages, clones or fast-forward-updates the selected branch, creates an isolated `.venv`, installs the repository's declared Python requirements, creates a private `.env` only when missing, checks FFmpeg/FFprobe, compiles Python modules and starts Uvicorn on `127.0.0.1:8000`. It preserves existing `.env` and project data.

## Important limits

- This installs the application and available local media utilities; it does not magically install a compatible local LLM or ComfyUI model. Hardware, Android build support, model storage and RAM determine whether those engines can run.
- Ollama is not assumed to be available as a supported Termux package. Configure a reachable local inference endpoint/model only after verifying device compatibility.
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
