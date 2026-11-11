import pytest

from app import ai_brain

def test_provider_status_never_exposes_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    status = ai_brain.provider_status()
    assert status["openai"]["configured"] is True
    assert "secret-test-value" not in repr(status)

def test_auto_provider_is_always_free_local(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert ai_brain._selected_provider() == "local"

def test_auto_provider_never_selects_paid_keys(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    assert ai_brain._selected_provider() == "local"

def test_explicit_provider_is_locked_until_revenue_and_approval(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "false")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "false")
    with pytest.raises(ai_brain.ProviderNotConfigured, match="Paid upgrade locked"):
        ai_brain._selected_provider()

def test_explicit_provider_without_key_fails(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai_brain.ProviderNotConfigured):
        ai_brain._selected_provider()


def test_video_generation_prompt_enforces_hindi_and_no_text_overlay(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "local")
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return "निर्माण पैकेज"

    monkeypatch.setattr(ai_brain, "_generate_ollama", fake_generate)
    monkeypatch.setattr(ai_brain, "_ollama_status", lambda: {"service_running": True, "model_available": True})
    result = ai_brain.generate_text("भारत के रहस्य पर वीडियो बनाओ", "shorts")
    assert result["output"] == "निर्माण पैकेज"
    assert "At least 95% Hindi" in captured["prompt"]
    assert "NO text overlay" in captured["prompt"]
    assert "SINTU AI YOUTUBE STUDIO brand watermark logo" in captured["prompt"]
