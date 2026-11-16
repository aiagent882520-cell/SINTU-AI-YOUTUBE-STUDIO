# ChatGPT ↔ Termux Bridge

SINTU includes a small authenticated job queue so a ChatGPT Action (or another
trusted HTTPS client) can request a predefined operation and a worker running
inside Termux can execute it locally.

## Security model

- The API accepts only a fixed action allowlist: `git_status`,
  `git_pull_ff_only`, `run_tests`, `compile_check`, `health_audit`, `operational_readiness`, `live_preflight`, and `offline_video_e2e`.
- No arbitrary shell text, executable path, environment variable, or command
  arguments are accepted from the remote caller.
- A random bearer token of at least 32 characters is required on every route.
- The worker maps actions to fixed argument arrays and never uses
  `shell=True`.
- Keep SINTU bound to localhost. If remote ChatGPT access is required, expose
  only this API through a separately configured HTTPS tunnel/reverse proxy,
  protect it with TLS and the bearer token, and do not expose the full dashboard
  or admin API. A tunnel URL is public internet-facing even if hard to guess.

## Enable locally in Termux

From the SINTU project directory:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Add the generated value to the private `.env` file (do not paste it into chat
or commit it):

```dotenv
SINTU_BRIDGE_TOKEN=generate-a-different-long-random-secret-for-chatgpt
SINTU_BRIDGE_WORKER_TOKEN=generate-another-long-random-secret-for-termux-worker
SINTU_BRIDGE_BASE_URL=http://127.0.0.1:8000
```

The one-command Termux installer creates both random bridge credentials in the private `.env` and starts the worker automatically after the API health check. For a manual start or recovery:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
.venv/bin/python scripts/termux_bridge_worker.py
```

For Android reboot startup, the installer also installs a Termux:Boot entrypoint. The separate Termux:Boot add-on must be installed/enabled; see `TERMUX_ONE_COMMAND.md`.

Check the worker log/status from the API using the ChatGPT bearer token for status/job creation and the separate worker bearer token for polling/completion. Stop the
worker with Ctrl+C.

## ChatGPT Action

The OpenAPI contract is in `docs/CHATGPT_TERMUX_BRIDGE_OPENAPI.yaml`. In a
ChatGPT environment that supports custom GPT Actions, configure its server
URL to the HTTPS endpoint you control and set Bearer authentication to the
same secret. Do not use a plain HTTP public endpoint.

The bridge uses two independent secrets: `SINTU_BRIDGE_TOKEN` for the ChatGPT/API client and `SINTU_BRIDGE_WORKER_TOKEN` for the Termux worker. Generate both independently and never share either in a public repository or chat.

The current Termux installation binds to `127.0.0.1`; ChatGPT cannot reach
that loopback address from the cloud or Android app. A secure HTTPS tunnel or
hosted relay and a ChatGPT Action-capable client are separate setup
requirements. This repository change does not silently create a tunnel or
grant ChatGPT direct access to the phone.

## Example safe jobs

- `git_status`
- `git_pull_ff_only`
- `run_tests` (optionally one Python test file directly inside `tests/`)
- `compile_check`
- `health_audit`
- `operational_readiness` (JSON readiness report; never prints secret values)
- `live_preflight` (checks local model/media engine availability without generating media)
- `offline_video_e2e` (creates a real local branded MP4 using procedural visuals and local Hindi voice; optional topic is limited to 300 characters)
- `full_self_test` (runs readiness, the full pytest suite, offline MP4 generation and final media-quality audit in one job; optional topic is limited to 300 characters)

Jobs and bounded output are persisted in `sintu_termux_bridge.sqlite3`.


## Three-part development loop

1. ChatGPT is the planning/review layer and uses the connected GitHub integration to inspect code, create branches/commits/PRs, and read CI results.
2. GitHub stores the canonical project, runs the automated test/security matrix, and blocks unverified changes from being treated as release-ready.
3. The Termux worker executes only allowlisted local checks/build tasks on the Android device and posts bounded logs/status back to SINTU.

The installer starts the local worker automatically, but does not create a public tunnel. For cloud ChatGPT Action access, a secured HTTPS tunnel plus Action configuration are still required. Normal ChatGPT conversations do not gain direct access to Android shell just because this API exists. GitHub work can still be performed through an authorized GitHub connector; local device execution remains unavailable to cloud ChatGPT until the worker is reachable through the secured endpoint.
