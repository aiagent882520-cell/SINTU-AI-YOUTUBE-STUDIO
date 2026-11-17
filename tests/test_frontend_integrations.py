from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deepseek_is_visible_in_creator_provider_availability():
    app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'providers.deepseek?.configured' in app_js
    assert 'available.push("DeepSeek (optional)")' in app_js


def test_admin_provider_selector_includes_deepseek():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert '<option value="deepseek">DeepSeek</option>' in html


def test_google_flow_and_ai_studio_handoffs_are_explicitly_available():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'id="openGoogleFlow"' in html
    assert 'id="openAIStudioBuild"' in html
    assert 'https://labs.google/fx/tools/flow' in app_js
    assert 'https://aistudio.google.com/apps' in app_js
    assert "not a direct API connection" in html
    assert "project generation runs in Google AI Studio, not inside SINTU" in html
