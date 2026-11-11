"""Offline-first catalog for all approved SINTU video formats and workflows."""
from copy import deepcopy
from .studio_scope import PIPELINE, video_formats, STUDIO_MODULES, ENGINE_CATALOG, FREE_FIRST_POLICY, agent_registry, scope_summary

PRESETS = [
 {"id":"mystery-short","name":"Hindi Mystery Short","format":"youtube-shorts","duration_seconds":60,"language":"Hindi","tone":"Suspenseful, factual","prompt":"भारत की एक रहस्यमयी जगह पर 60 सेकंड का तथ्य-जाँचा हुआ YouTube Short बनाओ। मजबूत hook, 6–8 scenes, Hindi voiceover, हर scene का visual prompt, on-screen text, sound cues, CTA, description और hashtags दो। अप्रमाणित दावों को स्पष्ट चिह्नित करो।"},
 {"id":"documentary","name":"Documentary Starter","format":"historical-documentary","duration_seconds":600,"language":"Hindi","tone":"Cinematic, informative","prompt":"इस विषय पर research-led documentary package बनाओ: audience, objective, verified facts vs claims to verify, opening hook, chapters, full narration, scene-by-scene visual prompts, b-roll, music/SFX, thumbnail, metadata और source checklist।"},
 {"id":"faceless","name":"Faceless Explainer","format":"youtube-long","duration_seconds":480,"language":"Hindi","tone":"Clear, engaging","prompt":"इस topic पर faceless YouTube explainer बनाओ। Full narration, timestamped scenes, b-roll/AI visual prompts, captions, transitions, sound design, title, thumbnail concept, description और tags शामिल करो।"},
 {"id":"course","name":"Course Lesson","format":"educational","duration_seconds":600,"language":"Hindi","tone":"Teacher-like","prompt":"इस विषय पर structured video lesson बनाओ: learning objectives, prerequisites, chapter plan, simple examples, narration, visuals, recap, quiz with answers and assignment।"},
 {"id":"product-ad","name":"Product Promo","format":"advertisement","duration_seconds":30,"language":"Hindi","tone":"Persuasive, truthful","prompt":"इस product के लिए 30-second ad package बनाओ। Target audience, problem, truthful benefits, shot list, voiceover, on-screen copy, CTA और platform variants दो। Unsupported claims न जोड़ो।"}
]

def production_catalog():
    return {
      "version": 2,
      "formats": video_formats(),
      "pipeline": deepcopy(PIPELINE),
      "presets": deepcopy(PRESETS),
      "studio_modules": list(STUDIO_MODULES),
      "engines": deepcopy(ENGINE_CATALOG),
      "free_first_policy": deepcopy(FREE_FIRST_POLICY),
      "agent_registry": agent_registry(),
      "scope": scope_summary(),
      "export_profiles":[
        {"id":"portrait_hd","label":"Portrait HD","width":720,"height":1280},
        {"id":"portrait_full_hd","label":"Portrait Full HD","width":1080,"height":1920},
        {"id":"square","label":"Square","width":1080,"height":1080},
        {"id":"landscape_hd","label":"Landscape HD","width":1280,"height":720},
        {"id":"landscape_full_hd","label":"Landscape Full HD","width":1920,"height":1080}],
      "frame_rates":[24,30,60],
      "notes":[
        "All 60 approved video formats are catalogued with format-specific role presets.",
        "Every listed specialist has a distinct checker role; plan entries are templates, not proof that external workers are running.",
        "Local/open-source tools are the default. Paid APIs, subscriptions and cloud GPUs remain disabled until revenue and explicit user approval.",
        "A format preset selects relevant roles; it does not force irrelevant production stages.",
        "External generation, OAuth publishing and hardware-heavy rendering require their respective engines and configuration."
      ]
    }
