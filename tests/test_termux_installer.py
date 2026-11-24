from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_termux_installer_has_valid_bash_syntax():
    bash = shutil.which("bash")
    if not bash:
        return
    script = ROOT / "scripts" / "termux_one_command.sh"
    result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_termux_update_and_restart_helpers_have_valid_bash_syntax():
    bash = shutil.which("bash")
    if not bash:
        return
    for name in ("termux_apply_update.sh", "restart_termux_workers.sh", "termux_relay_bootstrap.sh"):
        script = ROOT / "scripts" / name
        result = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_termux_update_uses_fast_forward_and_graceful_identity_checked_restart():
    update = (ROOT / "scripts" / "termux_apply_update.sh").read_text(encoding="utf-8")
    restart = (ROOT / "scripts" / "restart_termux_workers.sh").read_text(encoding="utf-8")
    assert "git pull --ff-only origin main" in update
    assert "bash scripts/restart_termux_workers.sh" in update
    assert "kill -9" not in update.lower()
    assert "git reset --hard" not in update
    assert "stop_expected" in restart
    assert "kill -TERM" in restart
    assert "kill -KILL" not in restart
    assert "render-worker.pid" in restart


def test_hindi_readme_points_to_canonical_one_command_installer():
    readme = (ROOT / "README_HI.md").read_text(encoding="utf-8")
    assert "scripts/termux_one_command.sh" in readme
    assert "START_SINTU_TERMUX.sh" not in readme.split("## Complete video-format groups", 1)[0]


def test_dirty_checkout_relay_bootstrap_restarts_only_the_verified_relay():
    bootstrap = (ROOT / "scripts" / "termux_relay_bootstrap.sh").read_text(encoding="utf-8")
    assert 'relay_pid_file="$HOME/.sintu/github-relay.pid"' in bootstrap
    assert "gh auth status" in bootstrap
    assert "labels=sintu-command-running" in bootstrap
    assert "active_count=" in bootstrap
    assert "2400" in bootstrap
    assert bootstrap.index("active_count=") < bootstrap.index('kill -TERM "$relay_pid"')
    assert '"/proc/$relay_pid/cmdline"' in bootstrap
    assert 'ps -o args= -p "$relay_pid"' in bootstrap
    assert '"scripts/github_termux_relay.py"' in bootstrap
    assert 'kill -TERM "$relay_pid"' in bootstrap
    assert "did not stop after TERM" in bootstrap
    assert "kill -KILL" not in bootstrap
    assert bootstrap.index('kill -TERM "$relay_pid"') < bootstrap.index("bash scripts/start_services.sh")
    assert 'new_relay_pid="$(cat "$HOME/.sintu/github-relay.pid"' in bootstrap
    assert 'new_relay_cmdline' in bootstrap
    assert 'github-relay.heartbeat' in bootstrap
    assert "git reset --hard" not in bootstrap
    assert "git clean" not in bootstrap
    assert "git stash" not in bootstrap
