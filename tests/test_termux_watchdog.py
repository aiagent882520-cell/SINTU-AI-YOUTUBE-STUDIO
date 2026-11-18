from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_termux_watchdog_script_has_valid_bash_syntax():
    script = ROOT / "scripts" / "termux_watchdog.sh"
    assert script.is_file()
    subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, text=True)


def test_service_launcher_starts_watchdog():
    launcher = (ROOT / "scripts" / "start_services.sh").read_text(encoding="utf-8")
    assert "scripts/termux_watchdog.sh" in launcher
    assert "watchdog.pid" in launcher


def test_service_launcher_explains_when_github_issue_relay_cannot_start():
    launcher = (ROOT / "scripts" / "start_services.sh").read_text(encoding="utf-8")
    assert "GitHub CLI (gh) is not installed" in launcher
    assert "GitHub CLI is not authenticated" in launcher
    assert "gh auth login" in launcher
    assert "GitHub command issues will remain queued" in launcher
    assert "GitHub issue relay: $GITHUB_RELAY_STATUS." in launcher
    assert "gh auth status >/dev/null 2>&1" in launcher


def test_watchdog_clears_reused_pid_reference_without_signalling_unrelated_process():
    script = (ROOT / "scripts" / "termux_watchdog.sh").read_text(encoding="utf-8")
    assert "Cannot verify PID" in script
    assert "Stale PID reference" in script
    assert 'rm -f "$file"' in script
    assert "not signalling unrelated process" in script
    assert "return 1" in script
    assert 'if [ "$restart" -eq 1 ] && [ "$unsafe" -eq 0 ]; then' in script
