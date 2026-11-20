from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from scripts.github_termux_relay import write_relay_heartbeat

SELF_TEST_PATH = Path(__file__).resolve().parents[1] / "scripts" / "automation_self_test.py"
SPEC = importlib.util.spec_from_file_location("sintu_automation_self_test", SELF_TEST_PATH)
automation_self_test = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(automation_self_test)


def test_relay_heartbeat_is_atomically_written_without_credentials(tmp_path):
    target = tmp_path / ".sintu" / "github-relay.heartbeat"

    write_relay_heartbeat(target)

    assert target.is_file()
    assert target.read_text(encoding="utf-8").endswith("+00:00")
    assert list(target.parent.iterdir()) == [target]


def test_automation_self_test_rejects_missing_relay_heartbeat(tmp_path):
    with pytest.raises(RuntimeError, match="has not recorded"):
        automation_self_test.relay_heartbeat_status(tmp_path / "missing")


def test_automation_self_test_rejects_stale_relay_heartbeat(tmp_path):
    target = tmp_path / "github-relay.heartbeat"
    target.write_text("old poll", encoding="utf-8")
    os.utime(target, (100.0, 100.0))

    with pytest.raises(RuntimeError, match="stale"):
        automation_self_test.relay_heartbeat_status(target, now=2201.0)


def test_automation_self_test_accepts_recent_relay_heartbeat(tmp_path):
    target = tmp_path / "github-relay.heartbeat"
    target.write_text("successful poll", encoding="utf-8")
    os.utime(target, (2195.0, 2195.0))

    assert automation_self_test.relay_heartbeat_status(target, now=2200.0) == {
        "last_successful_poll_age_seconds": 5.0
    }
