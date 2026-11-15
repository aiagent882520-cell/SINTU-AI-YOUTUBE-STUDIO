"""Provider adapter and workflow-aware production brain for SINTU AI STUDIO.

Secrets are read only from server environment variables. Never return or log API keys.
"""
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

from .agent_orchestrator import workflow_team, orchestration_summary
from .policy import paid_upgrades_allowed

load_dotenv()

SYSTEM_INSTRUCTIONS = (
    "You are SINTU AI STUDIO's production assistant. Create complete, practical "
    "creator deliverables in the user's language. Follow the selected workflow's "
    "output structure. Be factual: distinguish verified facts from assumptions, "
    "never invent sources, and flag claims needing verification. Respect copyright "
    "and platform policies. For video deliverables, default to Hindi: at least 95% of all narration, dialogue, titles, descriptions and production notes must be natural Hindi; use English only for unavoidable proper nouns, technical terms or user-requested phrases. Do not add subtitles, captions, karaoke words, lower-thirds, labels or visible text over the video. Spoken words must never appear as on-screen text. Visual prompts must explicitly request clean text-free frames. The final renderer adds only the SINTU AI YOUTUBE STUDIO brand watermark logo. A prompt is not permission to publish, spend money, "
    "or access accounts. Never claim a video was rendered, uploaded, or published "
    "when you only generated text."
)

WORKFLOW_GUIDES = {
    "shorts": """Create a production-ready vertical YouTube Short.
Return: (1) 3 clickable but truthful title options, (2) a 1-2 second opening hook,
(3) timestamped scene table covering the requested duration (default 60 seconds),
(4) exact Hindi voiceover, (5) visual direction and a separate
image/video-generation prompt for every scene, (6) music and
sound-effect cues, (7) ending CTA, (9) description, hashtags and tags, and
(10) fact-check/copyright notes. Keep narration natural and timed to the scenes.""",
    "long-video": """Create a complete long-form video production package.
Return: audience and objective; 3 title options; a truthful thumbnail concept;
opening hook; chapter/timestamp outline; full narration script; scene-by-scene
visual direction and generation prompts; b-roll, graphics, music and SFX cues;
description, chapters, hashtags and tags; fact-check notes. Clearly label any
estimated runtime.""",
    "thumbnail": """Create 3 distinct high-click-potential thumbnail concepts.
For each provide: one focal subject, composition, background, facial/emotional
direction if relevant, contrast and color direction, mobile readability check,
and a precise image-generation prompt. Thumbnail text stays separate from video frames. Do not promise
a CTR; explain that performance must be tested with real analytics.""",
    "script": """Write a polished, engaging script in the requested language.
Include audience, tone, hook, complete Hindi spoken narration, scene/visual cues,
transitions, pacing, ending and optional CTA. Do not request visible text overlays. Avoid filler and unsupported claims.""",
    "research": """Prepare a research brief, not fabricated live research.
Separate established background knowledge, claims requiring current verification,
and open questions. Give search queries and trustworthy source types to consult.
Never invent URLs, citations, statistics, or claim that live browsing occurred.""",
    "course": """Design a teachable lesson or course module.
Include learner level, prerequisites, measurable objectives, ordered lesson
sections, simple explanations, examples, safe practical activities, recap,
10-question quiz with answer key, assignment, and further-study topics.
For cybersecurity, restrict practice to authorized labs and defensive learning.""",
    "social": """Create a platform-ready social content pack.
Include platform-specific copy, 3 caption variants, opening line, CTA,
relevant hashtags, suggested visual/reel direction, and accessibility-friendly
alt text. Do not claim posting or scheduling has happened.""",
    "content": """Create a clear content package with concept, target audience,
hook, structured outline, draft, visual suggestions, CTA and metadata.""",
}

class ProviderNotConfigured(Exception):
    pass

class ProviderRequestError(Exception):
    pass

def _ollama_status():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        names = [str(item.get("name", "")) for item in payload.get("models", [])]
        available = any(name == model or name.startswith(model + ":") for name in names)
        return {"service_running": True, "model_available": available, "model": model, "base_url": base_url}
    except Exception:
        return {"service_running": False, "model_available": False, "model": model, "base_url": base_url}


def _local_openai_compatible_status():
    """Probe a loopback OpenAI-compatible server (llama.cpp, LocalAI, LM Studio)."""
    base_url = os.getenv("LOCAL_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
    configured_model = os.getenv("LOCAL_OPENAI_MODEL", "auto").strip()
    try:
        from urllib.parse import urlsplit
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Local model endpoint must use HTTP loopback or the Docker host bridge.")
        request = urllib.request.Request(base_url + "/models")
        api_key = os.getenv("LOCAL_OPENAI_API_KEY", "").strip()
        if api_key:
            request.add_header("Authorization", "Bearer " + api_key)
        with urllib.request.urlopen(request, timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        models = payload.get("data", []) if isinstance(payload, dict) else []
        names = [str(item.get("id", "")) for item in models if isinstance(item, dict) and item.get("id")]
        selected = names[0] if configured_model == "auto" and names else configured_model
        available = bool(names) and (configured_model == "auto" or configured_model in names)
        return {"service_running": True, "model_available": available,
                "model": selected, "base_url": base_url}
    except Exception:
        return {"service_running": False, "model_available": False,
                "model": configured_model, "base_url": base_url}


def _active_local_backend():
    """Choose a ready free local engine; never fall through to a paid provider."""
    requested = os.getenv("LOCAL_AI_BACKEND", "auto").strip().lower()
    ollama = _ollama_status()
    compatible = _local_openai_compatible_status() if requested in {"auto", "openai-compatible", "llama.cpp", "llamacpp"} else {
        "service_running": False, "model_available": False,
        "model": os.getenv("LOCAL_OPENAI_MODEL", "auto"),
        "base_url": os.getenv("LOCAL_OPENAI_BASE_URL", "http://127.0.0.1:8080/v1"),
    }
    if requested not in {"auto", "ollama", "openai-compatible", "llama.cpp", "llamacpp"}:
        requested = "auto"
    if requested in {"auto", "ollama"} and ollama["model_available"]:
        return {"backend": "ollama", **ollama}
    if requested in {"auto", "openai-compatible", "llama.cpp", "llamacpp"} and compatible["model_available"]:
        return {"backend": "openai-compatible", **compatible}
    if requested == "ollama":
        return {"backend": "ollama", **ollama}
    if requested != "auto":
        return {"backend": "openai-compatible", **compatible}
    return {"backend": "none",
            "service_running": bool(ollama["service_running"] or compatible["service_running"]),
            "model_available": False, "model": ollama.get("model"),
            "base_url": ollama.get("base_url"),
            "alternate_backend": compatible}


def _generate_local(user_input: str) -> str:
    backend = _active_local_backend()
    if not backend["model_available"]:
        raise ProviderNotConfigured(
            "Free local AI model is not ready. Start Ollama with OLLAMA_MODEL, or start a loopback "
            "OpenAI-compatible llama.cpp server at LOCAL_OPENAI_BASE_URL and set LOCAL_OPENAI_MODEL=auto. "
            "No paid API will be used automatically."
        )
    if backend["backend"] == "ollama":
        return _generate_ollama(user_input)
    return _generate_openai_compatible(user_input, backend)


def _generate_openai_compatible(user_input: str, backend: dict) -> str:
    """Call a local llama.cpp/LocalAI/LM Studio OpenAI-compatible chat endpoint."""
    base_url = backend["base_url"].rstrip("/")
    payload = {
        "model": backend["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": user_input},
        ],
        "temperature": 0.7,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    api_key = os.getenv("LOCAL_OPENAI_API_KEY", "").strip()
    if api_key:
        request.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderRequestError(f"Local OpenAI-compatible server returned HTTP {exc.code}. Check the loaded model and endpoint.") from None
    except (urllib.error.URLError, TimeoutError):
        raise ProviderNotConfigured("Local OpenAI-compatible model server is not reachable. No paid API will be used.") from None
    choices = data.get("choices", [])
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    if isinstance(content, list):
        content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ProviderRequestError("Local OpenAI-compatible server returned an empty response.")
    return content.strip()

def provider_status(selected_override=None):
    selected = (selected_override or os.getenv("AI_PROVIDER", "local")).strip().lower()
    if selected not in {"auto", "local", "openai", "gemini"}:
        selected = "auto"
    local_status = _active_local_backend()
    compatible_status = _local_openai_compatible_status()
    return {
        "selected": selected,
        "paid_upgrades_allowed": paid_upgrades_allowed(),
        "local": {
            "configured": local_status["model_available"],
            "service_running": local_status["service_running"],
            "model_available": local_status["model_available"],
            "model": local_status.get("model") or os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
            "base_url": local_status.get("base_url") or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            "backend": local_status["backend"],
            "backend_preference": os.getenv("LOCAL_AI_BACKEND", "auto"),
            "openai_compatible": {
                "service_running": compatible_status["service_running"],
                "model_available": compatible_status["model_available"],
                "model": compatible_status["model"],
                "base_url": compatible_status["base_url"],
            },
        },
        "openai": {
            "configured": bool(os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("OPENAI_MODEL", "gpt-5.5"),
        },
        "gemini": {
            "configured": bool(os.getenv("GEMINI_API_KEY")),
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        },
    }

def _selected_provider(selected_override=None):
    selected = (selected_override or os.getenv("AI_PROVIDER", "local")).strip().lower()
    status = provider_status(selected)
    if selected in {"auto", "local"}:
        # Free-first: auto always selects the local model. Paid providers are never auto-enabled.
        return "local"
    if selected not in ("openai", "gemini"):
        raise ProviderRequestError("AI_PROVIDER must be auto, local, openai, or gemini.")
    if not paid_upgrades_allowed():
        raise ProviderNotConfigured("Paid upgrade locked: SINTU must earn revenue first and the user must explicitly approve paid upgrades.")
    if not status[selected]["configured"]:
        raise ProviderNotConfigured(f"{selected} selected hai, lekin uski API key server par set nahi hai.")
    return selected

def generate_text(prompt: str, workflow: str, provider_override=None) -> dict:
    provider = _selected_provider(provider_override)
    workflow_key = (workflow or "content").strip().lower()
    guide = WORKFLOW_GUIDES.get(workflow_key, WORKFLOW_GUIDES["content"])
    user_input = (
        "MANDATORY VIDEO LANGUAGE AND VISUAL POLICY (overrides generic templates):\n"
        "- Default language is Hindi (Devanagari). At least 95% Hindi; English maximum 5%, only essential terms/proper nouns.\n"
        "- Voiceover, dialogue, narration and spoken lines must be Hindi.\n"
        "- NO text overlay in the video: no subtitles, captions, transcript, karaoke, labels, titles, lower-thirds or speech-to-text.\n"
        "- The ONLY permitted visible overlay is the SINTU AI YOUTUBE STUDIO brand watermark logo, added by the renderer.\n"
        "- Every visual/image/video prompt must include: clean frame, no text, no letters, no subtitles, no watermark, no logo.\n"
        "- Metadata may be provided separately as plain text outside the video.\n"
        "- Never burn narration or subtitles into the video.\n\n"
        f"Selected workflow: {workflow_key}\n"
        f"Workflow production requirements:\n{guide}\n\n"
        f"Assigned specialist roles and responsibilities:\n{json.dumps(workflow_team(workflow_key), ensure_ascii=False, indent=2)}\n\n"
        f"Orchestration mode: {orchestration_summary()['execution_mode']}. This is one model request guided by specialist roles, not separate autonomous agents.\n\n"
        f"User topic / prompt / script:\n{prompt.strip()}\n\n"
        "Follow the workflow requirements while honoring the user topic, language, audience, duration and constraints. If a detail is missing, make a sensible clearly stated assumption instead of blocking."
    )
    try:
        if provider == "local":
            output = _generate_local(user_input)
        elif provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=60.0, max_retries=1)
            response = client.responses.create(
                model=os.getenv("OPENAI_MODEL", "gpt-5.5"),
                instructions=SYSTEM_INSTRUCTIONS,
                input=user_input,
            )
            output = response.output_text
        else:
            output = _generate_gemini(user_input)
    except (ProviderNotConfigured, ProviderRequestError):
        raise
    except Exception as exc:
        raise ProviderRequestError(f"AI provider request failed ({type(exc).__name__}). Check model, key, quota, and network.") from None
    if not output or not output.strip():
        raise ProviderRequestError("AI provider returned an empty response.")
    return {"provider": provider, "model": provider_status()[provider]["model"], "output": output.strip()}

def _generate_gemini(user_input: str) -> str:
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTIONS}]},
        "contents": [{"role": "user", "parts": [{"text": user_input}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderRequestError(f"Gemini API returned HTTP {exc.code}. Check key, model, and quota.") from None
    except (urllib.error.URLError, TimeoutError):
        raise ProviderRequestError("Gemini API connection timed out or network is unavailable.") from None
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in parts if part.get("text"))


def _generate_ollama(user_input: str) -> str:
    """Generate text through a local Ollama server; no API key or paid service."""
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    payload = {
        "model": model,
        "prompt": SYSTEM_INSTRUCTIONS + "\n\n" + user_input,
        "stream": False,
        "options": {"temperature": 0.7},
    }
    request = urllib.request.Request(
        base_url + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderRequestError(f"Local Ollama returned HTTP {exc.code}. Check the local model service.") from None
    except (urllib.error.URLError, TimeoutError):
        raise ProviderNotConfigured(
            "Free local AI abhi available nahi hai. Ollama install/start karein, phir ollama pull qwen2.5:3b chalayein. Paid API automatically use nahi hogi."
        ) from None
    output = data.get("response", "")
    if not isinstance(output, str) or not output.strip():
        raise ProviderRequestError("Local Ollama returned an empty response.")
    return output.strip()
