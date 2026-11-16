# SINTU Operational Readiness Doctor

Run from the SINTU repository root after installation:

```bash
.venv/bin/python scripts/operational_readiness.py
```

Machine-readable report:

```bash
.venv/bin/python scripts/operational_readiness.py --json
```

Offline configuration-only checks:

```bash
.venv/bin/python scripts/operational_readiness.py --no-network
```

The doctor checks repository/PWA files, core Python imports, FFmpeg/FFprobe,
private environment configuration, admin authentication, separate bridge
credentials, the Termux worker process, API health, local OpenAI-compatible
model reachability, and ComfyUI reachability. It never prints secret values.

A **READY** result means required local files, dependencies, media tools and
security configuration are present. Optional services are shown as warnings
when unavailable; they are not falsely reported as active. A full production
test still requires a real render on the target Android device and owner-managed
Google/YouTube OAuth consent. The doctor does not publish or upload anything.

If the worker is missing, run `bash scripts/start_services.sh`. If the API is
down, inspect `~/.sintu/server.log`; worker diagnostics are in
`~/.sintu/bridge-worker.log`.
