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
    for name in ("termux_apply_update.sh", "restart_termux_workers.sh"):
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
