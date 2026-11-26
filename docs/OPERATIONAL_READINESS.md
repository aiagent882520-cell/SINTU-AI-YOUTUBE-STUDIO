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
credentials, the Termux worker process, Piper Hindi neural voice executable/model,
API health, local OpenAI-compatible model reachability, and ComfyUI reachability. It never prints secret values.

A **READY** result means required local files, dependencies, media tools and
security configuration are present. Optional services are shown as warnings
when unavailable; they are not falsely reported as active. A full production
test still requires a real render on the target Android device and owner-managed
Google/YouTube OAuth consent. The doctor does not publish or upload anything.

If the worker is missing, run `bash scripts/start_services.sh`. If the API is
down, inspect `~/.sintu/server.log`; worker diagnostics are in
`~/.sintu/bridge-worker.log`.

## One-command full self-test

Run \`python scripts/sintu_self_test.py\` from the repository root. It executes the operational readiness doctor, full pytest suite, a real offline Hindi MP4 render, and a final media-quality audit. It writes a redacted summary to \`$SINTU_DATA_DIR/sintu_self_test_report.json\` (or the repository data directory when unset). Optional development shortcuts are \`--skip-tests\` and \`--skip-video\`; the secure Termux bridge exposes the complete workflow as \`full_self_test\`. The check uses local FFmpeg/eSpeak and procedural visuals; it does not call paid APIs or publish to YouTube.
