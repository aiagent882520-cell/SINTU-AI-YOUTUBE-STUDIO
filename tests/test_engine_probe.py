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


def test_comfyui_setup_gate_blocks_android_termux_even_with_large_resources():
    gate = probe._comfyui_setup_gate(
        termux=True, available_ram_bytes=16 * 1024**3, free_disk_bytes=40 * 1024**3
    )
    assert gate["status"] == "blocked"
    assert gate["eligible_for_manual_review"] is False
    assert gate["auto_install_allowed"] is False
    assert gate["install_performed"] is False
    assert any("Termux" in reason for reason in gate["reasons"])


def test_comfyui_setup_gate_blocks_low_ram_and_storage():
    gate = probe._comfyui_setup_gate(
        termux=False, available_ram_bytes=7 * 1024**3, free_disk_bytes=19 * 1024**3
    )
    assert gate["status"] == "blocked"
    assert gate["eligible_for_manual_review"] is False
    assert len(gate["reasons"]) == 2


def test_comfyui_setup_gate_only_allows_manual_review_on_suitable_separate_host():
    gate = probe._comfyui_setup_gate(
        termux=False, available_ram_bytes=12 * 1024**3, free_disk_bytes=30 * 1024**3
    )
    assert gate["status"] == "eligible_for_manual_review"
    assert gate["eligible_for_manual_review"] is True
    assert gate["auto_install_allowed"] is False
    assert gate["install_performed"] is False


def test_comfyui_setup_gate_treats_unknown_storage_as_unsafe():
    gate = probe._comfyui_setup_gate(
        termux=False, available_ram_bytes=12 * 1024**3, free_disk_bytes=None
    )
    assert gate["status"] == "blocked"
    assert gate["eligible_for_manual_review"] is False
