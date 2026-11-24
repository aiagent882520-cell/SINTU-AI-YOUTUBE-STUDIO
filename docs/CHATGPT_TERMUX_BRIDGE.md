# ChatGPT ↔ Termux Bridge

SINTU includes a small authenticated job queue so a ChatGPT Action (or another
trusted HTTPS client) can request a predefined operation and a worker running
inside Termux can execute it locally.

## Security model

- The API accepts only these 18 fixed actions: `git_status`, `git_pull_ff_only`, `run_tests`, `main_worktree_tests`, `compile_check`, `automation_self_test`, `health_audit`, `operational_readiness`, `live_preflight`, `engine_probe`, `safe_optional_install`, `restart_services`, `media_repair`, `media_forensics`, `watchdog_recovery_test`, `offline_video_e2e`, `full_self_test`, `full_studio_e2e`.
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
- `main_worktree_tests` (fetches `origin/main` and runs the full pytest suite in `~/.sintu/worktrees/main`; refuses symlinks, unregistered directories, dirty worktrees, or a HEAD mismatch; never resets, stashes, cleans, or overwrites the primary checkout)
- `compile_check`
- `health_audit`
- `operational_readiness` (JSON readiness report; never prints secret values)
- `live_preflight` (checks local model/media engine availability without generating media)
- `offline_video_e2e` (creates a real local branded MP4 using procedural visuals and local Hindi voice; optional topic is limited to 300 characters)
- `full_self_test` (runs readiness, the full pytest suite, offline MP4 generation and final media-quality audit in one job; optional topic is limited to 300 characters; paused by default in automation-only mode)

Jobs and bounded output are persisted in `sintu_termux_bridge.sqlite3`.


## Three-part development loop

1. ChatGPT is the planning/review layer and uses the connected GitHub integration to inspect code, create branches/commits/PRs, and read CI results.
2. GitHub stores the canonical project, runs the automated test/security matrix, and blocks unverified changes from being treated as release-ready.
3. The Termux worker executes only allowlisted local checks/build tasks on the Android device and posts bounded logs/status back to SINTU.

The installer starts the local worker automatically, but does not create a public tunnel. For cloud ChatGPT Action access, a secured HTTPS tunnel plus Action configuration are still required. Normal ChatGPT conversations do not gain direct access to Android shell just because this API exists. GitHub work can still be performed through an authorized GitHub connector; local device execution remains unavailable to cloud ChatGPT until the worker is reachable through the secured endpoint.


## GitHub relay mode (no public tunnel)

For normal ChatGPT conversations using the connected GitHub app, the repository
also supports a GitHub Issues mailbox. ChatGPT creates a labeled command issue;
the Android Termux relay polls GitHub, validates the JSON body and trusted
author, executes only the fixed allowlist, then comments the result and closes
the issue. This avoids exposing the phone or SINTU API to the public internet.

### One-time Android authorization

The installer installs GitHub CLI when available. Sign in once from Termux:

```bash
gh auth login
```

Choose GitHub.com, HTTPS, and browser/device login. Grant the CLI access to
read/write repository issues. Do not paste the device code, token, or private
`.env` into ChatGPT. Then rerun the safe installer; it starts
`scripts/github_termux_relay.py` automatically and installs labels. Keep the
relay process alive; Termux:Boot starts it after reboot when the add-on is
installed/enabled.

### Queue a device job from ChatGPT

Create a GitHub issue in this repository with label
`sintu-command-queued`, a title beginning `SINTU-CMD:`, and a body whose first line is a single-line JSON object.
The issue must be authored by the configured owner account
(`SINTU_GITHUB_ALLOWED_ACTOR`, default `aiagent882520-cell`).

Example:

```json
{"action":"operational_readiness"}
```

Allowed actions (exactly): `git_status`, `git_pull_ff_only`, `run_tests`, `main_worktree_tests`, `compile_check`, `automation_self_test`, `health_audit`, `operational_readiness`, `live_preflight`, `engine_probe`, `safe_optional_install`, `restart_services`, `media_repair`, `media_forensics`, `watchdog_recovery_test`, `offline_video_e2e`, `full_self_test`, `full_studio_e2e`.

The first line of the issue body must be one single-line JSON object with `action` required and no keys other than `action`, `topic`, and `test_path`. Optional explanatory Markdown may follow on later lines; do not put prose before the JSON line. `test_path` is optional only for
`run_tests` and must name an existing Python file directly inside `tests/`;
without it, the full pytest suite runs. `main_worktree_tests` accepts no extra fields and runs against a dedicated clean worktree, preserving local changes in the user's primary checkout. `topic` is optional only for
`offline_video_e2e`, `full_self_test`, and `full_studio_e2e`, and must contain
1–300 characters. Every other action accepts no additional fields. For example,
`full_project_task`, `priority`, `goals`, and `constraints` are not supported.

`SINTU_AUTOMATION_ONLY` defaults to `true`. In this mode,
`offline_video_e2e`, `full_self_test`, `full_studio_e2e`, and `media_repair` are
rejected. `media_repair` invokes `repair_media.py --apply`: it backs up then
replaces existing MP4 files, so it remains blocked by default and must never be
queued without explicit owner authorization and a reviewed backup plan.

The relay accepts only issues from the configured owner, with a title beginning
`SINTU-CMD:` and the `sintu-command-queued` label. It processes oldest-first;
claims older than 40 minutes are requeued, command execution times out at 30
minutes, and result output is capped at 20,000 characters. No shell commands,
arbitrary paths, executable names, or environment changes are accepted.

The worker changes the label to running, adds a claim comment, executes the
job, posts a bounded result, labels it done/failed, and closes the issue.
ChatGPT can then read the result using the GitHub app. Do not put secrets in
issue titles or bodies.

The original authenticated localhost bridge remains available for a dedicated
HTTPS Action client. GitHub relay mode is the preferred route when using the
ordinary ChatGPT app with a connected GitHub account.
