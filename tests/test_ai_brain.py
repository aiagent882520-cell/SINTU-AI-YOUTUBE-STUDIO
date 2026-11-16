import pytest

from app import ai_brain

def test_provider_status_never_exposes_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-value")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(ai_brain, "_ollama_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    monkeypatch.setattr(ai_brain, "_local_openai_compatible_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "auto", "base_url": "http://127.0.0.1:8080/v1"
    })
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
    monkeypatch.setattr(ai_brain, "_active_local_backend", lambda: {
        "backend": "ollama", "service_running": True, "model_available": True,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return "निर्माण पैकेज"

    monkeypatch.setattr(ai_brain, "_generate_ollama", fake_generate)
    result = ai_brain.generate_text("भारत के रहस्य पर वीडियो बनाओ", "shorts")
    assert result["output"] == "निर्माण पैकेज"
    assert "At least 95% Hindi" in captured["prompt"]
    assert "Generated visual assets must be text-free" in captured["prompt"]
    assert "separate timed text track" in captured["prompt"]
    assert "SINTU AI YOUTUBE STUDIO brand watermark" in captured["prompt"]


def test_auto_local_backend_falls_back_to_compatible_server(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_BACKEND", "auto")
    monkeypatch.setattr(ai_brain, "_ollama_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    monkeypatch.setattr(ai_brain, "_local_openai_compatible_status", lambda: {
        "service_running": True, "model_available": True,
        "model": "qwen2.5-3b-instruct", "base_url": "http://127.0.0.1:8080/v1"
    })
    selected = ai_brain._active_local_backend()
    assert selected["backend"] == "openai-compatible"
    assert selected["model"] == "qwen2.5-3b-instruct"


def test_local_openai_compatible_response_is_parsed(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"choices":[{"message":{"content":"\\u0928\\u092e\\u0938\\u094d\\u0924\\u0947"}}]}'

    monkeypatch.setattr(ai_brain.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    result = ai_brain._generate_openai_compatible("hello", {
        "base_url": "http://127.0.0.1:8080/v1", "model": "local-model"
    })
    assert result == "नमस्ते"


def test_local_openai_compatible_status_discovers_first_model(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'{"data":[{"id":"qwen-local"}]}'

    monkeypatch.setenv("LOCAL_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("LOCAL_OPENAI_MODEL", "auto")
    monkeypatch.setattr(ai_brain.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    status = ai_brain._local_openai_compatible_status()
    assert status["service_running"] is True
    assert status["model_available"] is True
    assert status["model"] == "qwen-local"


def test_local_openai_compatible_rejects_remote_endpoint(monkeypatch):
    monkeypatch.setenv("LOCAL_OPENAI_BASE_URL", "http://example.com/v1")
    status = ai_brain._local_openai_compatible_status()
    assert status["service_running"] is False
    assert status["model_available"] is False


def test_invalid_local_backend_preference_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("LOCAL_AI_BACKEND", "unknown-backend")
    monkeypatch.setattr(ai_brain, "_ollama_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    monkeypatch.setattr(ai_brain, "_local_openai_compatible_status", lambda: {
        "service_running": True, "model_available": True,
        "model": "qwen-local", "base_url": "http://127.0.0.1:8080/v1"
    })
    assert ai_brain._active_local_backend()["backend"] == "openai-compatible"


def test_deepseek_provider_status_never_exposes_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-secret-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setattr(ai_brain, "_ollama_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    monkeypatch.setattr(ai_brain, "_local_openai_compatible_status", lambda: {
        "service_running": False, "model_available": False,
        "model": "auto", "base_url": "http://127.0.0.1:8080/v1"
    })
    status = ai_brain.provider_status()
    assert status["deepseek"] == {"configured": True, "model": "deepseek-flash"}
    assert "deepseek-secret-test" not in repr(status)


def test_deepseek_provider_is_locked_until_revenue_and_approval(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setenv("SINTU_REVENUE_CONFIRMED", "false")
    monkeypatch.setenv("ALLOW_PAID_UPGRADES", "false")
    with pytest.raises(ai_brain.ProviderNotConfigured, match="Paid upgrade locked"):
        ai_brain._selected_provider()


def test_deepseek_chat_completion_uses_official_compatible_endpoint(monkeypatch):
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return b'{"choices":[{"message":{"content":"Namaste from DeepSeek"}}]}'
    captured = {}
    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = request.data.decode("utf-8")
        return FakeResponse()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    monkeypatch.setattr(ai_brain.urllib.request, "urlopen", fake_urlopen)
    assert ai_brain._generate_deepseek("hello") == "Namaste from DeepSeek"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    assert '"model": "deepseek-flash"' in captured["body"]


def test_documentary_brain_uses_evidence_led_cinematic_workflow(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setattr(ai_brain, "_active_local_backend", lambda: {
        "backend": "ollama", "service_running": True, "model_available": True,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return "डॉक्यूमेंट्री निर्माण पैकेज"

    monkeypatch.setattr(ai_brain, "_generate_ollama", fake_generate)
    result = ai_brain.generate_text("भारत के प्राचीन किलों पर डॉक्यूमेंट्री", "documentary")
    assert result["output"] == "डॉक्यूमेंट्री निर्माण पैकेज"
    assert "experienced documentary showrunner" in captured["prompt"]
    assert "evidence ledger" in captured["prompt"]
    assert "scene-by-scene shot list" in captured["prompt"]
    assert "PREMIUM CINEMATIC / DOCUMENTARY ACCEPTANCE STANDARD" in captured["prompt"]
    assert "never invent interviews" in captured["prompt"]
    assert "static image slideshow" in captured["prompt"]


def test_film_brain_requires_screenplay_and_camera_craft(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "local")
    monkeypatch.setattr(ai_brain, "_active_local_backend", lambda: {
        "backend": "ollama", "service_running": True, "model_available": True,
        "model": "qwen2.5:3b", "base_url": "http://127.0.0.1:11434"
    })
    captured = {}

    def fake_generate(prompt):
        captured["prompt"] = prompt
        return "फिल्म पैकेज"

    monkeypatch.setattr(ai_brain, "_generate_ollama", fake_generate)
    ai_brain.generate_text("एक ऐतिहासिक फिल्म बनाओ", "film")
    assert "feature-film director" in captured["prompt"]
    assert "complete screenplay" in captured["prompt"]
    assert "motivated camera movement" in captured["prompt"]
    assert "character/prop/wardrobe continuity" in captured["prompt"]
