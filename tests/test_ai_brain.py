import pytest

from app import ai_brain

def test_provider_status_never_exposes_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    status = ai_brain.provider_status()
    assert status["openai"]["configured"] is True
    assert "secret-test-value" not in repr(status)

def test_auto_provider_requires_a_key(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai_brain.ProviderNotConfigured):
        ai_brain._selected_provider()

def test_auto_provider_selects_openai_first(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    assert ai_brain._selected_provider() == "openai"

def test_explicit_provider_without_key_fails(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ai_brain.ProviderNotConfigured):
        ai_brain._selected_provider()
