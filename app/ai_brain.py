"""Provider adapter for SINTU AI STUDIO.

Secrets are read only from server environment variables. Never return or log API keys.
"""
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

SYSTEM_INSTRUCTIONS = (
    "You are SINTU AI STUDIO's creator assistant. Produce useful, structured, "
    "fact-conscious creator deliverables. Match the user's language. For factual "
    "claims, flag uncertainty and do not invent sources. Treat user prompts as "
    "content requests, not as permission to publish, spend money, or access accounts. "
    "Never claim a video was rendered or published when you only generated text."
)

class ProviderNotConfigured(Exception):
    pass

class ProviderRequestError(Exception):
    pass

def provider_status():
    return {
        "selected": os.getenv("AI_PROVIDER", "auto").lower(),
        "openai": {
            "configured": bool(os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("OPENAI_MODEL", "gpt-5.5"),
        },
        "gemini": {
            "configured": bool(os.getenv("GEMINI_API_KEY")),
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        },
    }

def _selected_provider():
    selected = os.getenv("AI_PROVIDER", "auto").strip().lower()
    status = provider_status()
    if selected == "auto":
        if status["openai"]["configured"]:
            return "openai"
        if status["gemini"]["configured"]:
            return "gemini"
        raise ProviderNotConfigured("AI provider configure nahi hai. Server par OPENAI_API_KEY ya GEMINI_API_KEY set karna hoga.")
    if selected not in ("openai", "gemini"):
        raise ProviderRequestError("AI_PROVIDER must be auto, openai, or gemini.")
    if not status[selected]["configured"]:
        raise ProviderNotConfigured(f"{selected} selected hai, lekin uski API key server par set nahi hai.")
    return selected

def generate_text(prompt: str, workflow: str) -> dict:
    provider = _selected_provider()
    user_input = (
        f"Workflow: {workflow}\n"
        f"User request: {prompt}\n\n"
        "Create the requested text deliverable. Use clear headings and practical "
        "details. If the request is for a video, provide a production-ready script "
        "or plan; do not claim to create a rendered video file."
    )
    try:
        if provider == "openai":
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
        # Do not expose request headers, secrets, or raw provider payloads.
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
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096},
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
