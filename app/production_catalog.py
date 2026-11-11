"""Offline-first catalog for all approved SINTU video formats and workflows."""
from copy import deepcopy
from .studio_scope import PIPELINE, video_formats, STUDIO_MODULES, ENGINE_CATALOG, FREE_FIRST_POLICY, agent_registry, scope_summary

PRESETS = [
 {"id":"mystery-short","name":"Hindi Mystery Short","format":"youtube-shorts","duration_seconds":60,"language":"Hindi","tone":"Suspenseful, factual","prompt":"भारत की एक रहस्यमयी जगह पर 60 सेकंड का तथ्य-जाँचा हुआ YouTube Short बनाओ। कम से कम 95% स्वाभाविक हिंदी (देवनागरी) रखो। मजबूत आरंभ, 6–8 दृश्य, हिंदी वॉइसओवर, हर दृश्य का अलग दृश्य-निर्माण निर्देश, ध्वनि संकेत, समापन संदेश, विवरण और हैशटैग दो। किसी दृश्य में शब्द, अक्षर, उपशीर्षक, कैप्शन, लोगो या watermark जनरेट न करना; अंतिम वीडियो में SINTU AI YOUTUBE STUDIO का लोगो watermark renderer अपने आप लगाएगा। बोले गए शब्द स्क्रीन पर कभी न लिखना। अप्रमाणित दावों को स्पष्ट चिह्नित करो।"},
 {"id":"documentary","name":"Documentary Starter","format":"documentary","duration_seconds":600,"language":"Hindi","tone":"Cinematic, informative","prompt":"इस विषय पर कम से कम 95% हिंदी में शोध-आधारित डॉक्यूमेंट्री पैकेज बनाओ: दर्शक, उद्देश्य, सत्यापित तथ्य और जाँचने योग्य दावे, आरंभ, अध्याय, पूरी हिंदी वॉइसओवर, दृश्य-दर-दृश्य दृश्य-निर्माण निर्देश, अतिरिक्त दृश्य, संगीत/ध्वनि, thumbnail, metadata और स्रोत-जाँच सूची। वीडियो के किसी frame में कोई लिखावट नहीं; SINTU watermark अंतिम renderer लगाएगा।"},
 {"id":"faceless","name":"Faceless Explainer","format":"youtube-long","duration_seconds":480,"language":"Hindi","tone":"Clear, engaging","prompt":"इस विषय पर कम से कम 95% हिंदी में faceless YouTube explainer बनाओ। पूरी हिंदी वॉइसओवर, समय-चिह्नित दृश्य, अतिरिक्त दृश्य/AI visual prompts, transitions, sound design, title, thumbnail concept, description और tags दो। वीडियो में subtitles/captions/text overlays नहीं होंगे; SINTU watermark renderer लगाएगा।"},
 {"id":"course","name":"Course Lesson","format":"educational","duration_seconds":600,"language":"Hindi","tone":"Teacher-like","prompt":"इस विषय पर कम से कम 95% हिंदी में structured video lesson बनाओ: सीखने के लक्ष्य, आवश्यक पूर्वज्ञान, अध्याय योजना, सरल उदाहरण, हिंदी narration, visuals, recap, quiz और assignment। वीडियो के अंदर कोई text overlay नहीं होगा; SINTU watermark renderer लगाएगा।"},
 {"id":"product-ad","name":"Product Promo","format":"advertisement","duration_seconds":30,"language":"Hindi","tone":"Persuasive, truthful","prompt":"इस product के लिए 30-second ad package बनाओ। कम से कम 95% हिंदी voiceover, target audience, समस्या, सत्यापित लाभ, shot list, दृश्य निर्देश, CTA और platform variants दो। वीडियो में on-screen copy या कोई text overlay नहीं होगा; SINTU watermark renderer लगाएगा। Unsupported claims न जोड़ो।"}
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
