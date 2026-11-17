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
