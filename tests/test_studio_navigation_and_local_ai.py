from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/style.css").read_text(encoding="utf-8")
JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
SETUP = (ROOT / "scripts/setup_local_ai_termux.sh").read_text(encoding="utf-8")
START = (ROOT / "scripts/start_local_ai_termux.sh").read_text(encoding="utf-8")


def test_studio_sidebar_links_resolve_to_real_sections():
    ids = set(re.findall(r'id="([^"]+)"', HTML))
    targets = re.findall(r'<a\s+href="#([^"]+)"', HTML)
    assert len(targets) >= 10
    assert targets
    assert set(targets).issubset(ids)


def test_provider_navigation_requires_both_owner_granted_features():
    assert 'data-feature-all="ai_settings,integrations"' in HTML
    assert 'querySelectorAll("[data-feature-all]")' in JS
    assert "required.every(feature => allowed.has(feature))" in JS


def test_local_ai_diagnostics_report_actual_local_runtime():
    assert 'id="localAiRuntimeStatus"' in HTML
    assert 'id="localAiRefresh"' in HTML
    assert 'request("/api/providers")' in JS
    assert "renderLocalAiRuntime(providers)" in JS
    assert "local.openai_compatible" in JS
    assert "Paid fallback stays disabled" in JS


def test_termux_bootstrap_is_guarded_and_preserves_existing_config():
    assert 'pkg install -y llama-cpp' in SETUP
    assert 'MIN_RAM_KB=900000' in SETUP
    assert 'MIN_DISK_KB=1250000' in SETUP
    assert '47475546' in SETUP
    assert 'No .env secrets or paid-provider settings were changed.' in SETUP
    assert '127.0.0.1' in START
    assert '--host 127.0.0.1' in START
    assert '0.0.0.0' not in START


def test_production_readiness_panel_reports_real_capabilities_and_labels_fallbacks():
    assert 'id="productionReadinessStatus"' in HTML
    assert 'id="productionReadinessRefresh"' in HTML
    assert 'request("/api/capabilities")' in JS
    assert "renderProductionReadiness(capabilities)" in JS
    assert "workflows,capabilities] = await Promise.all" in JS
    assert "PROCEDURAL FALLBACK · NOT AI" in JS
    assert "PIPER / HINDI TTS MODEL MISSING" in JS
    assert "BLOCKED · LOCAL VIDEO WORKFLOW MISSING" in JS
    assert "FFMPEG" in JS
