# Termux Recovery and Media Repair

## Service watchdog

Running `bash scripts/start_services.sh` starts the API, bridge worker, GitHub relay (when `gh` is authenticated), and the lightweight watchdog.

The watchdog checks every 30 seconds:
- API health at `/api/health`
- Bridge worker PID and command identity
- GitHub relay PID and command identity when GitHub CLI authentication is available

It restarts missing or unhealthy services by invoking the existing safe service launcher. It only signals a PID when its command line matches the expected SINTU process. A mismatched PID is treated as unsafe and is not killed.

Logs are written under `~/.sintu/watchdog.log` and `~/.sintu/recovery.log`.

After deployment, verify real process recovery with:

```bash
.venv/bin/python scripts/watchdog_recovery_test.py --json
```

This test terminates the known bridge worker and API processes, then waits for the watchdog to launch new process identities and restore health. It does not test Android device reboot recovery.

## Media repair

The repair utility scans only top-level `generated_videos/*.mp4` files. It targets audio-profile issues and leaves already-valid files and silent videos unchanged.

Preview the proposed changes without modifying files:

```bash
.venv/bin/python scripts/repair_media.py --json
```

Apply repairs:

```bash
.venv/bin/python scripts/repair_media.py --apply --json
```

For each affected MP4, the utility:
1. Confirms the source is a regular MP4 with an H.264/yuv420p video stream.
2. Re-encodes only the first audio stream to AAC, 48 kHz, stereo.
3. Copies the video stream without re-encoding.
4. Verifies the temporary MP4 with FFprobe and the project media validator.
5. Saves the original file to a unique timestamped backup directory.
6. Atomically replaces the source only after the backup and validation succeed.

Default backups are stored under `media_backups/<UTC timestamp>/` inside the configured SINTU data directory. Existing backup files are never overwritten.

## GitHub allowlisted actions

The GitHub Termux relay and local bridge support these fixed actions:
- `restart_services`
- `watchdog_recovery_test`
- `media_repair`

They do not accept arbitrary shell commands or user-supplied paths. The media-repair action always uses the fixed project media directory and creates backups before replacing files.

## Android boot recovery

`scripts/termux_boot.sh` is the Termux boot entrypoint. Android boot recovery requires the Termux:Boot add-on, battery/background execution permissions, and a real reboot test on the device. Do not mark reboot recovery verified based only on the script being present.

## Queued service restart after code updates

The GitHub relay and bridge worker are long-running processes. A plain `git pull` changes files on disk but does not reload Python code already held in memory. For a queued `restart_services` action, `start_services.sh` now detects only its fixed SINTU relay/worker parent process and schedules a delayed restart. The current job first returns its success result; after a short delay, `restart_termux_workers.sh` checks the fixed PID files and exact command-line identities before sending TERM to the API, bridge worker, and GitHub relay. It then starts the services from the updated checkout. A PID mismatch is never signalled. Manual and watchdog calls do not trigger this delayed self-restart path.
