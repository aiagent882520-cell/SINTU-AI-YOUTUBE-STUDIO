# Termux durable render worker recovery

This procedure is fail-closed. It never prints .env values, deletes queue rows or media, and refuses to restart the worker while a render is active.

## Update and validate

```bash
cd "$HOME/SINTU-AI-YOUTUBE-STUDIO"
git fetch origin
git switch main
git pull --ff-only origin main
bash scripts/termux_render_worker_recovery_test.sh
```

The script records a report under reports/, runs subprocess-cancellation, SQLite lease/recovery, worker and API regression suites, and compiles the application. It reports process identity without exposing credentials or render payloads.

## Controlled worker restart

Only after the normal test run succeeds and no queue item is running:

```bash
SINTU_DEVICE_RESTART=1 bash scripts/termux_render_worker_recovery_test.sh
```

The script verifies the PID command line before SIGTERM, refuses to signal an unrelated/reused PID, refuses to force-kill an unresponsive worker, starts services through the normal supervisor and verifies the new render-worker PID identity.

## Physical Android reboot acceptance

1. Run the update/validation command above and retain the report.
2. Confirm there are no active queue jobs before reboot. Do not reboot during a render.
3. Reboot Android from the device power menu.
4. Open Termux and run:

```bash
cd "$HOME/SINTU-AI-YOUTUBE-STUDIO"
bash scripts/termux_render_worker_recovery_test.sh
```

5. Confirm API health, ~/.sintu/render-worker.pid identity, worker log startup and SQLite queue recovery. An interrupted job must be requeued or dead-lettered by its retry budget; a cancellation-requested job must recover as cancelled.
6. Attach only the generated text report and redacted worker log lines. Never share .env, OAuth credentials, tokens, private keys, source media or model files.

## Evidence boundary

GitHub CI and local subprocess tests do not prove that this phone rebooted or that Android background execution survives OEM battery management. Physical reboot acceptance remains pending until the post-reboot report is collected from the device.
