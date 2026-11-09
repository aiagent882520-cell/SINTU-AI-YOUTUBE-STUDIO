"""Provider adapter and workflow-aware production brain for SINTU AI STUDIO.

Secrets are read only from server environment variables. Never return or log API keys.
"""
import json
import os
import urllib.error
import urllib.request

from dotenv import load_dotenv

from .agent_orchestrator import workflow_team, orchestration_summary

load_dotenv()

SYSTEM_INSTRUCTIONS = (
    "You are SINTU AI STUDIO's production assistant. Create complete, practical "
    "creator deliverables in the user's language. Follow the selected workflow's "
    "output structure. Be factual: distinguish verified facts from assumptions, "
    "never invent sources, and flag claims needing verification. Respect copyright "
    "and platform policies. A prompt is not permission to publish, spend money, "
    "or access accounts. Never claim a video was rendered, uploaded, or published "
    "when you only generated text."
)

WORKFLOW_GUIDES = {
    "shorts": """Create a production-ready vertical YouTube Short.
Return: (1) 3 clickable but truthful title options, (2) a 1-2 second opening hook,
(3) timestamped scene table covering the requested duration (default 60 seconds),
(4) exact Hindi/selected-language voiceover, (5) visual direction and a separate
image/video-generation prompt for every scene, (6) on-screen text, (7) music and
sound-effect cues, (8) ending CTA, (9) description, hashtags and tags, and
(10) fact-check/copyright notes. Keep narration natural and timed to the scenes.""",
    "long-video": """Create a complete long-form video production package.
Return: audience and objective; 3 title options; a truthful thumbnail concept;
opening hook; chapter/timestamp outline; full narration script; scene-by-scene
visual direction and generation prompts; b-roll, graphics, music and SFX cues;
description, chapters, hashtags and tags; fact-check notes. Clearly label any
estimated runtime.""",
    "thumbnail": """Create 3 distinct high-click-potential thumbnail concepts.
For each provide: one focal subject, composition, background, facial/emotional
direction if relevant, 2-5 word readable text, contrast and color direction,
mobile readability check, and a precise image-generation prompt. Do not promise
a CTR; explain that performance must be tested with real analytics.""",
    "script": """Write a polished, engaging script in the requested language.
Include audience, tone, hook, complete spoken narration, scene/visual cues,
transitions, pacing, ending and optional CTA. Avoid filler and unsupported claims.""",
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
    workflow_key = (workflow or "content").strip().lower()
    guide = WORKFLOW_GUIDES.get(workflow_key, WORKFLOW_GUIDES["content"])
    user_input = (
        f"Selected workflow: {workflow_key}\n"
        f"Workflow production requirements:\n{guide}\n\n"
        f"Assigned specialist roles and responsibilities:\n{json.dumps(workflow_team(workflow_key), ensure_ascii=False, indent=2)}\n\n"
        f"Orchestration mode: {orchestration_summary()['execution_mode']}. This is one model request guided by specialist roles, not separate autonomous agents.\n\n"
        f"User topic / prompt / script:\n{prompt.strip()}\n\n"
        "Follow the workflow requirements while honoring the user's exact topic, "
        "language, audience, duration and constraints. If a detail is missing, "
        "make a sensible clearly stated assumption instead of blocking."
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
