# ChatGPT to Termux full-studio automation

## End-to-end command path

ChatGPT creates a GitHub issue in this repository with the `sintu-command-queued` label. The Android Termux GitHub relay accepts only issues created by the configured repository owner, validates the JSON body, runs a fixed allowlisted command, and posts the result as an issue comment.

The GitHub issue contract is JSON-only: required `action`; optional `topic` only for `offline_video_e2e`, `full_self_test`, and `full_studio_e2e` (1–300 characters); optional `test_path` only for `run_tests` (an existing `tests/*.py` file). No other keys are accepted, and `full_project_task` is not a supported action. The issue must be authored by the configured owner, titled with the `SINTU-CMD:` prefix, and labeled `sintu-command-queued`.

**Safety default:** `SINTU_AUTOMATION_ONLY=true` blocks `full_studio_e2e`, `full_self_test`, `offline_video_e2e`, and the mutating `media_repair` action. Do not queue the production example below while this mode is enabled; it will be rejected. Use `{"action":"operational_readiness"}` for a read-only device readiness check.

```json
{
  "action": "full_studio_e2e",
  "topic": "भारत के प्राचीन किलों की अनसुनी कहानियाँ"
}
```

Issue title must begin with `SINTU-CMD:`, for example `SINTU-CMD: full_studio_e2e`.

## What full_studio_e2e does

It calls the existing `scripts/live_e2e.py --full-studio-e2e` path. That workflow:
1. Runs the registered specialist agent catalog (61 builders and independent checkers).
2. Runs the five final reviewers and stops if any quality gate fails.
3. Extracts the approved AI Video Generator scene prompts.
4. Generates local ComfyUI clips and renders a branded MP4.
5. Attaches the verified render to the production run.
6. Returns the run ID, video metadata, and local render path in the GitHub issue result.

It does not publish or upload to a social platform.

## Runtime requirements and recovery

- Termux API, bridge worker, and GitHub issue relay must be running.
- GitHub CLI must be authenticated as the allowed repository owner.
- The phone must have a working local text model for the agent/checker calls.
- ComfyUI must be reachable with a validated video workflow and its required models.
- FFmpeg/FFprobe must be installed.
- The command is subject to the relay's 30-minute subprocess timeout. A failed job posts the failure details; it is not reported as a completed render.

For preflight, queue `live_preflight` or `operational_readiness`. `full_self_test` remains paused by default until the owner deliberately changes the safety setting on the device. The command relay never accepts arbitrary shell commands. A relay claim/result comment is required before any device execution can be considered verified.
