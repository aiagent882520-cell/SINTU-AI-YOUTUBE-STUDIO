# Termux black-MP4 forensic run (read-only)

This run is required to turn the three confirmed black-video investigations from timestamp-only candidates into evidence-backed source mapping. It reads local media, logs, SQLite databases and source assets. It does not repair, overwrite, move, delete, regenerate, upload or publish anything.

## Before running

- Run this on the Android phone where the five target MP4s and SINTU data live.
- The default installer path is `$HOME/SINTU-AI-YOUTUBE-STUDIO`. If you used a custom `SINTU_APP_DIR`, change `APP_DIR` below.
- The scanner needs the app's existing virtualenv, Pillow, FFmpeg and FFprobe.
- Ensure the five target files are in `$APP_DIR/generated_videos/`, and the relevant logs, SQLite files and generated assets remain in the app data directory.
- This uses the forensic scanner from PR #201's branch; it does not require merging that PR.

## Exact command

Paste the complete block into Termux:

```bash
set -u
APP_DIR="$HOME/SINTU-AI-YOUTUBE-STUDIO"
REPORT="$HOME/sintu-forensics-report.txt"
SCANNER="$HOME/.sintu/media_forensics-pr201.py"

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  echo "ERROR: SINTU virtualenv not found at $APP_DIR/.venv/bin/python"
  exit 2
fi
if [ ! -d "$APP_DIR/generated_videos" ]; then
  echo "ERROR: generated_videos folder not found: $APP_DIR/generated_videos"
  exit 2
fi

mkdir -p "$HOME/.sintu"
curl -fL --retry 3 \
  "https://raw.githubusercontent.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO/feature/forensic-source-asset-reference-tracing/scripts/media_forensics.py" \
  -o "$SCANNER" || exit 3

SINTU_DATA_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" "$SCANNER" > "$REPORT"
RESULT=$?

echo "Forensic scanner exit code: $RESULT"
echo "Report saved to: $REPORT"
echo "Report size: $(wc -c < "$REPORT") bytes"
echo "Read-only scan finished. Do not edit or delete the original media."
```

Exit code 0 means all five target inspections completed without a forensic-tool failure; it does **not** mean the videos are healthy. Exit code 1 means at least one target could not be fully inspected; the report still contains per-file evidence. Codes 2/3 above indicate local setup/download blockers.

## Share the report

Attach `sintu-forensics-report.txt` from the Termux home directory to the SINTU project conversation. The report includes target SHA-256 hashes, stream metadata, decoded-frame samples, black-frame measurements, backup hashes, candidate image/audio/WAV metadata, production log matches, SQLite reference matches, environment details and explicit safety flags.

The scanner redacts common token/secret fields and bounds log excerpts, but inspect the report before sharing. Do not send your `.env`, OAuth credentials, access tokens, refresh tokens, private keys or model files.

## Interpretation rules

- Timestamp-nearby image/audio assets are candidates, not proof of source mapping.
- A production log or database reference matching an asset path/stem is stronger linkage evidence, but must still be checked against the correct render/job ID and timestamps.
- No match means provenance is still unknown; it does not prove no source asset existed.
- Keep the original MP4s and backups unchanged. Any future repair must write to a separate output path and pass independent frame/audio validation.

## Optional human-visible contact sheets

The scanner can also export five decoded frames per target (first, quarter, middle, three-quarter and last) so a person can inspect dark footage instead of relying only on luma statistics. The output directory must be outside the SINTU data directory. Existing review JPEGs are never overwritten.

Run the same read-only scan with an additional output directory:

```bash
REPORT="$HOME/sintu-forensics-report-with-contact-sheets.txt"
REVIEW_DIR="$HOME/sintu-forensic-contact-sheets"
SINTU_DATA_DIR="$APP_DIR" "$APP_DIR/.venv/bin/python" "$SCANNER" --contact-sheet-dir "$REVIEW_DIR" > "$REPORT"
RESULT=$?
echo "Forensic scanner exit code: $RESULT"
echo "Review sheets: $REVIEW_DIR"
ls -lh "$REVIEW_DIR"
```

Each JPEG contains the five sampled frames with timestamps and measured pixel metrics. A `PASS` sheet has all five frames extracted; `PARTIAL` means at least one timestamp could not be rendered and must not be treated as a complete visual review. This export does not repair or alter source MP4s. Review the two dark-visible clips manually and keep the three pixel-confirmed black originals blocked. Share the report and contact sheets only after checking them for private content.
