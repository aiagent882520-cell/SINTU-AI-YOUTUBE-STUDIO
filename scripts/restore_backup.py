#!/usr/bin/env python3
"""Offline SINTU Studio backup verifier and safe restore command."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.backup_restore import BackupValidationError, restore_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or safely restore a SINTU AI Studio backup ZIP.")
    parser.add_argument("backup", type=Path, help="Path to the downloaded sintu-backup-*.zip archive")
    parser.add_argument("--verify-only", action="store_true", help="Verify archive contents without changing files")
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("SINTU_DATA_DIR", str(PROJECT_ROOT))),
                        help="SINTU_DATA_DIR (defaults to the project data directory)")
    parser.add_argument("--confirm-restore", action="store_true",
                        help="Explicitly authorize database replacement")
    parser.add_argument("--app-stopped", action="store_true",
                        help="Confirm that the SINTU application and workers are fully stopped")
    args = parser.parse_args()
    try:
        if args.verify_only:
            result = verify_backup(args.backup)
        else:
            if not args.confirm_restore:
                parser.error("restore requires --confirm-restore")
            if not args.app_stopped:
                parser.error("restore requires --app-stopped; stop SINTU Studio first")
            result = restore_backup(args.backup, args.data_dir, app_stopped=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (BackupValidationError, OSError, ValueError) as exc:
        print("Backup operation refused: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
