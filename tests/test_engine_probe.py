import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("engine_probe", ROOT / "scripts" / "engine_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_engine_probe_reports_hardware_without_starting_render(monkeypatch):
    monkeypatch.setattr(probe, "_read_meminfo", lambda: {
        "MemTotal": 8 * 1024**3, "MemAvailable": 4 * 1024**3
    })
    monkeypatch.setattr(probe, "_disk_free", lambda path: 6 * 1024**3)
    monkeypatch.setattr(probe, "_binary", lambda name: None)
    monkeypatch.setattr(probe, "_http_probe", lambda url: {
        "reachable": False, "detail": "ConnectionRefusedError"
    })
    monkeypatch.setattr(probe, "_model_inventory", lambda: [])
    report = probe.build_report()
    assert report["device"]["ram_available_bytes"] == 4 * 1024**3
    assert report["recommendation"]["llama_model_tier"] == "small_1b_to_3b_candidate"
    assert report["recommendation"]["image_model_tier"] == "no_safe_automatic_diffusion_model_download"
    assert report["render_started"] is False
    assert "No model downloads" in report["recommendation"]["install_policy"]


def test_engine_probe_uses_conservative_tier_for_low_resources(monkeypatch):
    monkeypatch.setattr(probe, "_read_meminfo", lambda: {
        "MemTotal": 4 * 1024**3, "MemAvailable": 700 * 1024**2
    })
    monkeypatch.setattr(probe, "_disk_free", lambda path: 300 * 1024**2)
    monkeypatch.setattr(probe, "_binary", lambda name: None)
    monkeypatch.setattr(probe, "_http_probe", lambda url: {
        "reachable": False, "detail": "ConnectionRefusedError"
    })
    monkeypatch.setattr(probe, "_model_inventory", lambda: [])
    report = probe.build_report()
    assert report["recommendation"]["llama_model_tier"] == "no_safe_automatic_model_download"
    assert report["recommendation"]["image_model_tier"] == "no_safe_automatic_diffusion_model_download"
