# Safe MP4 quarantine (copy-only)

This workflow is for suspected black or corrupt files in `generated_videos/`.
It does not decide whether a black clip is an intentional transition. Human
review and source-provenance checks remain required.

## Safety properties

- A manifest must name each exact relative path and its independently collected
  SHA-256. The tool never guesses filenames or hashes.
- Paths are restricted to MP4 files under `generated_videos/`; traversal and
  symlinks are rejected.
- The default command is a read-only dry run.
- `--apply` creates a content-addressed copy under
  `media_quarantine/<sha256>/<filename>`. It never changes, moves, replaces,
  or deletes the original.
- Existing quarantine copies are never overwritten. A copy is hash-verified
  before it is made visible at its final path.
- This is evidence preservation, not a repair or a publish approval.

## Manifest format

Create a local JSON file only after confirming the exact source names and
hashes on the device. Example structure:

```json
{
  "targets": [
    {
      "path": "generated_videos/EXACT_OWNER_CONFIRMED_FILENAME.mp4",
      "sha256": "64-character-lowercase-sha256-from-the-device"
    }
  ]
}
```

Do not use the placeholder values. Do not infer that the historical candidates
listed in an old issue are the same as a current device's original files.

## Run

From the repository root on the device:

```bash
python scripts/media_quarantine.py \
  --data-dir "$HOME/SINTU-AI-YOUTUBE-STUDIO" \
  --manifest "$HOME/sintu-black-mp4-manifest.json"
```

Review every `WOULD_COPY`, `HASH_MISMATCH`, and `REJECTED` result. Only
after the owner confirms the exact path/hash list, create verified copies:

```bash
python scripts/media_quarantine.py \
  --data-dir "$HOME/SINTU-AI-YOUTUBE-STUDIO" \
  --manifest "$HOME/sintu-black-mp4-manifest.json" \
  --apply
```

Verify the resulting report and compare the original and quarantine-copy
hashes. Keep originals and backups unchanged. Do not repair, regenerate,
publish, or delete a clip until its provenance and visual content have been
reviewed separately.
