# ChatGPT ↔ Termux Bridge

SINTU includes a small authenticated job queue so a ChatGPT Action (or another
trusted HTTPS client) can request a predefined operation and a worker running
inside Termux can execute it locally.

## Security model

- The API accepts only a fixed action allowlist: `git_status`,
  `git_pull_ff_only`, `run_tests`, `compile_check`, and `health_audit`.
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
SINTU_BRIDGE_TOKEN=replace-with-a-long-random-secret
SINTU_BRIDGE_BASE_URL=http://127.0.0.1:8000
```

Start SINTU, then start the worker in another Termux session:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
.venv/bin/python scripts/termux_bridge_worker.py
```

Check the worker log/status from the API using the same bearer token. Stop the
worker with Ctrl+C.

## ChatGPT Action

The OpenAPI contract is in `docs/CHATGPT_TERMUX_BRIDGE_OPENAPI.yaml`. In a
ChatGPT environment that supports custom GPT Actions, configure its server
URL to the HTTPS endpoint you control and set Bearer authentication to the
same secret. Do not use a plain HTTP public endpoint.

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

Jobs and bounded output are persisted in `sintu_termux_bridge.sqlite3`.
