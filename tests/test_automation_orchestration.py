import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_relay_maps_automation_self_test_to_fixed_script():
    relay = load_module("relay_automation_test", "scripts/github_termux_relay.py")
    assert relay.AUTOMATION_ONLY is True
    assert relay.command_for("automation_self_test", {})[-2:] == [
        "scripts/automation_self_test.py", "--json"
    ]


def test_bridge_worker_maps_only_the_self_test_script():
    worker = load_module("worker_automation_test", "scripts/termux_bridge_worker.py")
    assert worker.command_for({"action": "automation_self_test", "payload": {}})[-2:] == [
        "scripts/automation_self_test.py", "--json"
    ]


def test_api_exposes_self_test_but_keeps_production_paused():
    import app.termux_bridge as bridge
    assert "automation_self_test" in bridge.ALLOWED_ACTIONS
    assert bridge.AUTOMATION_ONLY is True
    assert bridge.PRODUCTION_ACTIONS == {
        "offline_video_e2e", "full_self_test", "full_studio_e2e"
    }


def test_self_test_and_update_script_exist_and_compile():
    import py_compile
    py_compile.compile(str(ROOT / "scripts/automation_self_test.py"), doraise=True)
    assert (ROOT / "scripts/termux_apply_update.sh").is_file()
