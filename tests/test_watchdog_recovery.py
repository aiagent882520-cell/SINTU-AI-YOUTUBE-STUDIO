from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_watchdog_recovery_script_compiles():
    script = ROOT / "scripts" / "watchdog_recovery_test.py"
    compile(script.read_text(encoding="utf-8"), str(script), "exec")


def test_watchdog_recovery_test_only_targets_known_sintu_process_markers():
    source = (ROOT / "scripts" / "watchdog_recovery_test.py").read_text(encoding="utf-8")
    assert '"scripts/termux_watchdog.sh"' in source
    assert '"scripts/termux_bridge_worker.py"' in source
    assert '"uvicorn app.main:app"' in source
    assert "refusing to signal it" in source
