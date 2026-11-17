from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_queued_restart_uses_trusted_executor_environment_marker():
    launcher = (ROOT / "scripts" / "start_services.sh").read_text()
    relay = (ROOT / "scripts" / "github_termux_relay.py").read_text()
    worker = (ROOT / "scripts" / "termux_bridge_worker.py").read_text()
    assert "SINTU_SKIP_DELAYED_RESTART" in launcher
    assert "SINTU_QUEUE_EXECUTOR" in launcher
    assert "github_termux_relay" in launcher
    assert "termux_bridge_worker" in launcher
    assert "SINTU_QUEUE_EXECUTOR" in relay
    assert '"github_termux_relay"' in relay
    assert "SINTU_QUEUE_EXECUTOR" in worker
    assert '"termux_bridge_worker"' in worker
    assert "scripts/restart_termux_workers.sh" in launcher
    assert "restart scheduled after the current queue result is acknowledged" in launcher


def test_delayed_restart_uses_fixed_pid_files_and_command_identity():
    helper = (ROOT / "scripts" / "restart_termux_workers.sh").read_text()
    assert 'stop_expected "$LOG_DIR/server.pid" "uvicorn app.main:app"' in helper
    assert 'stop_expected "$LOG_DIR/bridge-worker.pid" "scripts/termux_bridge_worker.py"' in helper
    assert 'stop_expected "$LOG_DIR/github-relay.pid" "scripts/github_termux_relay.py"' in helper
    assert 'tr \'\\0\' ' in helper
    assert 'kill -TERM "$pid"' in helper
    assert "kill -KILL" not in helper
    assert "env -u SINTU_QUEUE_EXECUTOR -u SINTU_SKIP_DELAYED_RESTART bash scripts/start_services.sh" in helper
