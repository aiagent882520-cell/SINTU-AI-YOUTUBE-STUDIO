from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_queued_restart_is_delayed_until_job_acknowledgement():
    launcher = (ROOT / "scripts" / "start_services.sh").read_text()
    assert "SINTU_SKIP_DELAYED_RESTART" in launcher
    assert "scripts/restart_termux_workers.sh" in launcher
    assert "scripts/github_termux_relay.py" in launcher
    assert "scripts/termux_bridge_worker.py" in launcher
    assert "restart scheduled after the current queue result is acknowledged" in launcher


def test_delayed_restart_uses_fixed_pid_files_and_command_identity():
    helper = (ROOT / "scripts" / "restart_termux_workers.sh").read_text()
    assert 'stop_expected "$LOG_DIR/server.pid" "uvicorn app.main:app"' in helper
    assert 'stop_expected "$LOG_DIR/bridge-worker.pid" "scripts/termux_bridge_worker.py"' in helper
    assert 'stop_expected "$LOG_DIR/github-relay.pid" "scripts/github_termux_relay.py"' in helper
    assert 'tr \'\\0\' ' in helper
    assert 'kill -TERM "$pid"' in helper
    assert "kill -KILL" not in helper
    assert "SINTU_SKIP_DELAYED_RESTART=1 bash scripts/start_services.sh" in helper
