"""Complete, free-first SINTU production architecture.

This is a capability and workflow registry. A registry entry is not a claim that
its external engine is installed or that an autonomous process is currently running.
"""
from copy import deepcopy

# id, display name, category, aspect ratio, resolution, duration, stage, preset
_FORMAT_ROWS = [
("youtube-shorts","YouTube Shorts","Short-form","9:16","1080x1920","15–60 sec","ready_for_api","short"),
("youtube-long","Long-form YouTube videos","Long-form","16:9","1920x1080","5–60+ min","production_workflow","long"),
("instagram-reels","Reels","Short-form","9:16","1080x1920","15–90 sec","production_workflow","short"),
("podcast","Podcasts","Audio/Video","16:9 or 9:16","1920x1080","5–120 min","production_workflow","podcast"),
("educational","Educational videos","Learning","16:9","1920x1080","3–30 min","production_workflow","education"),
("advertisement","Advertisements","Commercial","16:9 or 9:16","1080p","6–90 sec","production_workflow","ad"),
("vlog","Vlogs","Creator","16:9 or 9:16","1920x1080","1–30 min","production_workflow","live"),
("gaming","Gaming videos","Gaming","16:9","1920x1080","1–60 min","production_workflow","live"),
("documentary","Historical documentaries","Documentary","16:9","1920x1080","8–60 min","production_workflow","documentary"),
("nature-documentary","Nature documentaries","Documentary","16:9","1920x1080","8–60 min","production_workflow","documentary"),
("investigative-documentary","Investigative documentaries","Documentary","16:9","1920x1080","10–90 min","research_required","documentary"),
("science-documentary","Science documentaries","Documentary","16:9","1920x1080","8–60 min","research_required","documentary"),
("biography","Biographies","Documentary","16:9","1920x1080","8–60 min","research_required","documentary"),
("mystery-documentary","Mystery documentaries","Documentary","16:9","1920x1080","8–60 min","research_required","documentary"),
("travel-documentary","Travel documentaries","Documentary","16:9","1920x1080","5–45 min","production_workflow","documentary"),
("crime-documentary","Crime documentaries","Documentary","16:9","1920x1080","8–60 min","research_required","documentary"),
("2d-cartoon","2D cartoon animation","2D Animation","16:9 or 9:16","1920x1080","30 sec–10 min","prompt_and_storyboard","2d"),
("anime","Anime animation","2D Animation","16:9 or 9:16","1920x1080","30 sec–10 min","prompt_and_storyboard","2d"),
("motion-graphics","Motion graphics","Motion Design","16:9 or 9:16","1920x1080","15 sec–5 min","production_workflow","motion"),
("whiteboard-animation","Whiteboard animation","2D Animation","16:9","1920x1080","1–10 min","prompt_and_storyboard","2d"),
("story-animation","Story animation","2D Animation","16:9 or 9:16","1920x1080","1–15 min","prompt_and_storyboard","2d"),
("cut-out-animation","Cut-out animation","2D Animation","16:9","1920x1080","1–10 min","prompt_and_storyboard","2d"),
("3d-animation","3D character animation","3D Animation","16:9","1920x1080","30 sec–10 min","prompt_and_storyboard","3d"),
("3d-architectural-animation","3D architectural animation","3D Animation","16:9","1920x1080","30 sec–5 min","prompt_and_storyboard","3d"),
("3d-product-animation","3D product animation","3D Animation","16:9 or 9:16","1920x1080","15 sec–3 min","prompt_and_storyboard","3d"),
("3d-simulation","3D simulation","3D Animation","16:9","1920x1080","30 sec–10 min","prompt_and_storyboard","3d"),
("3d-fantasy-animation","3D fantasy animation","3D Animation","16:9","1920x1080","1–20 min","prompt_and_storyboard","3d"),
("3d-vfx-animation","3D VFX animation","3D Animation","16:9","1920x1080","15 sec–10 min","prompt_and_storyboard","3d"),
("cinematic-movie","Cinematic movies","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("short-film","Short films","Film","16:9","1920x1080","1–40 min","production_workflow","film"),
("fantasy-film","Fantasy films","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("sci-fi-film","Sci-fi films","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("action-film","Action films","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("romantic-film","Romantic films","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("horror-film","Horror films","Film","16:9","1920x1080","5–180 min","production_workflow","film"),
("historical-film","Historical films","Film","16:9","1920x1080","5–180 min","research_required","film"),
("stop-motion","Stop motion","Stop Motion","16:9","1920x1080","30 sec–20 min","production_workflow","stop"),
("clay-animation","Clay animation","Stop Motion","16:9","1920x1080","30 sec–20 min","production_workflow","stop"),
("puppet-animation","Puppet animation","Stop Motion","16:9","1920x1080","1–30 min","production_workflow","stop"),
("frame-by-frame","Frame-by-frame animation","2D Animation","16:9","1920x1080","15 sec–10 min","prompt_and_storyboard","2d"),
("white-background-explainer","White background explainer","Explainer","16:9","1920x1080","30 sec–10 min","production_workflow","education"),
("kinetic-typography","Kinetic typography","Motion Design","16:9 or 9:16","1920x1080","15 sec–5 min","production_workflow","motion"),
("lyric-video","Lyric videos","Music","16:9 or 9:16","1920x1080","1–6 min","production_workflow","music"),
("music-video","Music videos","Music","16:9 or 9:16","1920x1080","1–8 min","production_workflow","music"),
("visual-effects-video","Visual effects videos","VFX","16:9","1920x1080","15 sec–10 min","production_workflow","vfx"),
("green-screen","Green screen videos","Live Action","16:9 or 9:16","1920x1080","15 sec–30 min","production_workflow","live"),
("virtual-production","Virtual production","Film","16:9","1920x1080","1–180 min","integration_required","film"),
("360-video","360-degree videos","Immersive","2:1 / 360","3840x1920","1–30 min","integration_required","immersive"),
("vr-video","VR videos","Immersive","VR","Platform-dependent","1–30 min","integration_required","immersive"),
("ar-video","AR videos","Immersive","AR","Platform-dependent","15 sec–10 min","integration_required","immersive"),
("live-action","Live-action videos","Live Action","16:9 or 9:16","1920x1080","15 sec–180 min","production_workflow","live"),
("hybrid-2d-3d","Hybrid 2D + 3D videos","Hybrid Animation","16:9","1920x1080","30 sec–20 min","production_workflow","hybrid"),
("ai-avatar","AI avatar videos","Avatar","9:16 or 16:9","1080x1920","30 sec–15 min","integration_required","avatar"),
("talking-photo","Talking photo videos","Avatar","9:16 or 16:9","1080x1920","15 sec–5 min","integration_required","avatar"),
("product-demonstration","Product demonstration videos","Commercial","16:9 or 9:16","1920x1080","30 sec–10 min","production_workflow","ad"),
("training-corporate","Training/corporate videos","Business","16:9","1920x1080","2–60 min","production_workflow","education"),
("news-reportage","News/reportage videos","News","16:9 or 9:16","1920x1080","1–30 min","research_required","news"),
("sports-highlights","Sports highlights","Sports","16:9","1920x1080","30 sec–15 min","production_workflow","live"),
("event-video","Event videos","Event","16:9","1920x1080","1–120 min","production_workflow","live"),
("timelapse-hyperlapse","Timelapse/hyperlapse videos","Cinematic","16:9","1920x1080","15 sec–10 min","production_workflow","film"),
]

COMMON_ROLES = ["Master AI Director", "Production Planner", "Audience Analyst", "Prompt Writer", "Video Editor", "Final Output Agent"]
ROLE_PRESETS = {
 "short": ["Topic Researcher","Topic Writer","Research Analyst","Fact Checker","Story Writer","Script Writer","Dialogue Writer","Storyboard Artist","Visual Designer","Image Generation Agent","Video Generation Agent","Voice Generation Agent","Sound Designer","Subtitle Agent","Thumbnail Designer","YouTube SEO Agent","Final Render Agent"],
 "long": ["Topic Researcher","Research Analyst","Fact Checker","Audience Analyst","Story Writer","Script Writer","Screenplay Writer","Storyboard Artist","Cinematographer","Video Generation Agent","Voice Director","Music Composer","Sound Designer","Video Editor","Color Correction Agent","Subtitle Agent","Thumbnail Designer","YouTube SEO Agent","Final Render Agent"],
 "documentary": ["Topic Researcher","Research Analyst","Story Researcher","Fact Checker","Audience Analyst","Story Writer","Script Writer","Screenplay Writer","Documentary Producer","Storyboard Artist","Cinematographer","Image Generation Agent","Video Generation Agent","Voice Director","Voice Generation Agent","Music Composer","Sound Designer","Video Editor","Subtitle Agent","YouTube SEO Agent","Final Render Agent"],
 "education": ["Topic Researcher","Research Analyst","Fact Checker","Audience Analyst","Topic Writer","Script Writer","Storyboard Artist","Graphic Designer","Infographic Designer","Image Generation Agent","Voice Generation Agent","Subtitle Agent","Video Editor","Final Render Agent"],
 "ad": ["Audience Analyst","Research Analyst","Fact Checker","Creative Director","Script Writer","Dialogue Writer","Concept Artist","Graphic Designer","Product Designer","Cinematographer","Image Generation Agent","Video Generation Agent","Music Composer","Sound Designer","Video Editor","Color Correction Agent","Final Render Agent"],
 "live": ["Production Planner","Cinematographer","Recording Agent","Background Designer","Visual Effects Agent","Video Editor","Visual Editor","Colorist","Audio Editor","Audio Mixer","Subtitle Agent","Final Render Agent"],
 "podcast": ["Topic Researcher","Audience Analyst","Topic Writer","Script Writer","Recording Agent","Voice Director","Audio Editor","Audio Mixer","Subtitle Agent","Video Editor","Thumbnail Designer"],
 "2d": ["R&D Agent","Concept Artist","Character Designer","Layout Agent","Storyboard Artist","Background Designer","2D Animator","Character Animator","Motion Graphics Artist","2D VFX Agent","Compositing Agent","Recording Agent","Final Render Agent"],
 "3d": ["R&D Agent","Concept Artist","Character Designer","Layout Agent","Modeling Agent","Texturing Agent","Text Training Agent","Rigging Setup Agent","Rigging Agent","Character Animator","3D Animator","Lighting Agent","VFX Agent","Compositing Agent","Rendering Specialist","Final Render Agent"],
 "motion": ["Graphic Designer","Visual Designer","Layout Agent","Motion Graphics Artist","2D Animator","Compositing Agent","Sound Designer","Video Editor","Final Render Agent"],
 "film": ["R&D Agent","Story Researcher","Fact Checker","Story Writer","Screenplay Writer","Dialogue Writer","Creative Director","Film Director","Cinematographer","Production Planner","Concept Artist","Storyboard Artist","Character Designer","Modeling Agent","Texturing Agent","Rigging Setup Agent","3D Animator","Recording Agent","VFX Agent","Lighting Agent","Compositing Agent","Color Correction Agent","Cinematic Editor","Audio Mixer","Final Render Agent"],
 "stop": ["R&D Agent","Concept Artist","Story Writer","Storyboard Artist","Layout Agent","Character Designer","Recording Agent","2D Animator","Video Editor","Compositing Agent","Final Render Agent"],
 "music": ["Music Composer","Sound Designer","Audio Editor","Audio Mixer","Motion Graphics Artist","Visual Editor","Subtitle Agent","Video Editor","Final Render Agent"],
 "vfx": ["R&D Agent","Cinematographer","Modeling Agent","Texturing Agent","Lighting Agent","VFX Agent","2D VFX Agent","Compositing Agent","VFX Compositor","Color Correction Agent","Final Render Agent"],
 "immersive": ["R&D Agent","Concept Artist","3D Modeler","Texturing Agent","Lighting Agent","3D Animator","VFX Agent","Compositing Agent","Rendering Specialist","Final Render Agent"],
 "hybrid": ["R&D Agent","Concept Artist","Layout Agent","2D Animator","Modeling Agent","Texturing Agent","Rigging Setup Agent","3D Animator","Motion Graphics Artist","VFX Agent","Compositing Agent","Final Render Agent"],
 "avatar": ["Script Writer","AI Avatar Agent","Voice Director","Voice Generation Agent","Lip Sync Agent","Character Consistency Agent","Video Editor","Subtitle Agent","Final Render Agent"],
 "news": ["Topic Researcher","Research Analyst","Story Researcher","Fact Checker","Audience Analyst","Script Writer","Recording Agent","Cinematographer","Video Editor","Subtitle Agent","Final Approval Agent"],
}

SPECIALIST_ROLES = [
"Master AI Director","Task Manager","Workflow Agent","Memory Agent","Automation Agent",
"Topic Researcher","Topic Writer","Research Analyst","Story Researcher","Fact Checker","Audience Analyst",
"Story Writer","Script Writer","Screenplay Writer","Dialogue Writer","Prompt Writer","Concept Artist","Layout Agent","R&D Agent","Storyboard Artist","Creative Director","Film Director","Animation Director","Cinematographer","Production Planner",
"Graphic Designer","Thumbnail Designer","Background Designer","Visual Designer","Logo Designer","Infographic Designer","Character Designer","Image Generation Agent","Video Generation Agent","Scene Generation Agent","Character Consistency Agent","Background Generation Agent","Visual Effects Agent","AI Avatar Agent","Lip Sync Agent",
"2D Animator","3D Animator","Character Animator","Motion Graphics Artist","Modeling Agent","3D Modeler","Texturing Agent","Text Training Agent","Rigging Setup Agent","Rigging Agent","Lighting Agent","Rendering Specialist","Recording Agent","Compositing Agent","2D VFX Agent","VFX Agent","Color Correction Agent","Final Output Agent",
"Voice Director","Voice Generation Agent","Consent-based Voice Cloning Agent","Music Composer","Sound Designer","Audio Editor","Audio Mixer","Subtitle Agent","Video Editor","Visual Editor","Cinematic Editor","Colorist","Transition Designer","Camera Movement Planner","VFX Compositor","Final Render Agent",
"Script Quality Agent","Video Quality Agent","Audio Quality Agent","Visual Consistency Agent","Copyright Checker Agent","Subtitle Quality Agent","Final Approval Agent","YouTube SEO Agent","Title Writer","Description Writer","Tags Researcher","Hashtag Researcher","Thumbnail Optimizer","Upload Agent","Scheduling Agent","Analytics Agent","Growth Strategist","Content Planner","Project Manager","Asset Manager","Security & Privacy Agent","Cost & Resource Manager"
]
CHECKER_SUFFIX = " Checker"
AGENT_PAIRS = [
 {"specialist": role, "checker": role + CHECKER_SUFFIX, "independent": True,
  "checker_mission": "Independently verify the specialist output against explicit acceptance criteria; return PASS or FAIL, evidence, issues and required revisions."}
 for role in SPECIALIST_ROLES
]
CHECKER_NAMES = {item["checker"] for item in AGENT_PAIRS}

STUDIO_MODULES = [
"AI Topic Studio","AI Writing Studio","AI Prompt Studio","AI Storyboard Studio","AI Image Studio",
"AI Video Studio","2D Animation Studio","3D Animation Studio","AI Film Studio","Documentary Studio",
"AI Voice Studio","AI Music Studio","AI Editing Studio","Quality Control Studio","YouTube Publishing Studio"
]

PIPELINE = [
 {"id":"brief","name":"Brief & goals","description":"Topic, audience, language, platform, duration and CTA."},
 {"id":"research","name":"Research & fact check","description":"Evidence checklist, source requirements and uncertainty labels."},
 {"id":"script","name":"Writing & storyboard","description":"Topic, story, script, screenplay, dialogue, narration, prompts and shot plan."},
 {"id":"design","name":"Design & asset creation","description":"Layout, concept art, characters, backgrounds, graphics, image and scene assets."},
 {"id":"production","name":"Media production","description":"Applicable 2D/3D, modeling, texturing, rigging, animation, recording, VFX and lighting."},
 {"id":"post","name":"Post-production","description":"Compositing, motion graphics, editing, color correction, sound and subtitles."},
 {"id":"quality","name":"Independent quality gates","description":"Each worker has a separate checker; failed work is revised and re-checked."},
 {"id":"delivery","name":"Final output & publishing","description":"Render, export, human approval, YouTube SEO, upload, scheduling and analytics."}
]

FREE_FIRST_POLICY = {
 "budget_target_inr": 0,
 "required_paid_services": False,
 "default_provider": "local",
 "paid_upgrades_allowed_before_revenue": False,
 "paid_upgrades_require_user_approval": True,
 "upgrade_trigger": "Only after the project earns revenue, and only with explicit user approval.",
 "priority": ["local open-source", "free hosted tiers with no payment commitment", "optional paid services after revenue"],
 "local_engines": ["Ollama", "ComfyUI", "Blender", "FFmpeg", "Piper", "SQLite"],
 "limitations": ["Free cloud quotas can change.", "Heavy local video/image models may exceed an 8 GB RAM laptop; use lightweight workflows or an actually free hosted tier.", "No paid cloud/GPU/API may be silently enabled."]
}

ENGINE_CATALOG = [
 {"id":"local-llm","name":"Ollama","category":"Text AI","cost":"free","required":False,"notes":"Local model runtime; user installs a compatible model."},
 {"id":"image","name":"ComfyUI + open models","category":"Image generation","cost":"free","required":False,"notes":"Local GPU/RAM requirements vary by model."},
 {"id":"video","name":"Open video models / free tier when available","category":"Video generation","cost":"free-first","required":False,"notes":"No unlimited free cloud generation is promised."},
 {"id":"3d","name":"Blender","category":"3D production","cost":"free","required":False,"notes":"Local 3D authoring and rendering; performance depends on hardware."},
 {"id":"render","name":"FFmpeg","category":"Editing and rendering","cost":"free","required":False,"notes":"Local video assembly and export."},
 {"id":"voice","name":"Piper and compatible open TTS","category":"Voice","cost":"free","required":False,"notes":"Voice quality and language availability depend on installed model."},
 {"id":"music","name":"Original/free-license audio tools","category":"Music and SFX","cost":"free-first","required":False,"notes":"Respect licenses; do not use unlicensed tracks."},
 {"id":"database","name":"SQLite / PostgreSQL","category":"Storage","cost":"free","required":False,"notes":"Local-first storage."}
]

def video_formats():
    result = []
    for fid, name, category, ratio, resolution, duration, stage, preset in _FORMAT_ROWS:
        role_names = list(dict.fromkeys(COMMON_ROLES + ROLE_PRESETS[preset]))
        result.append({
            "id": fid, "name": name, "category": category, "aspect_ratio": ratio,
            "recommended_resolution": resolution, "duration": duration, "stage": stage,
            "description": f"{name}: format-specific production preset with only relevant stages and specialist/checker pairs.",
            "preset": preset, "roles": role_names,
            "checker_roles": [role + CHECKER_SUFFIX for role in role_names]
        })
    return result

def get_format(format_id):
    return next((item for item in video_formats() if item["id"] == format_id), None)

def agent_registry():
    return {
        "specialist_total": len(SPECIALIST_ROLES),
        "checker_total": len(AGENT_PAIRS),
        "total_role_instances": len(SPECIALIST_ROLES) + len(AGENT_PAIRS),
        "checker_pairs": deepcopy(AGENT_PAIRS),
        "rule": "A specialist cannot approve its own work. A checker is a separate role with independent acceptance criteria and PASS/FAIL output."
    }

def production_plan(format_id):
    selected = get_format(format_id)
    if not selected:
        raise KeyError(format_id)
    tasks = []
    for index, stage in enumerate(PIPELINE, 1):
        applicable = selected["roles"] if stage["id"] in {"brief","research","script","design","production","post","quality","delivery"} else []
        if stage["id"] == "research" and selected["stage"] not in {"research_required"}:
            applicable = [r for r in applicable if r in {"Topic Researcher","Research Analyst","Fact Checker","Audience Analyst"}]
        worker_checker_pairs = [
            {"worker": role, "checker": role + CHECKER_SUFFIX, "worker_status":"pending",
             "checker_status":"blocked_until_worker_submission", "gate":"checker_must_pass"}
            for role in applicable
        ]
        tasks.append({"order": index, "stage": stage["id"], "name": stage["name"],
                      "description": stage["description"], "required": True,
                      "worker_checker_pairs": worker_checker_pairs,
                      "gate": "PASS required; FAIL returns task for revision and independent re-check."})
    return {"format": selected, "pipeline": deepcopy(tasks),
            "approval_required_before_publish": True,
            "paid_services_enabled": False,
            "execution_status": "plan_only_no_external_agents_started"}

def scope_summary():
    return {
        "video_format_count": len(_FORMAT_ROWS),
        "studio_module_count": len(STUDIO_MODULES),
        "specialist_count": len(SPECIALIST_ROLES),
        "independent_checker_count": len(AGENT_PAIRS),
        "free_first_policy": deepcopy(FREE_FIRST_POLICY),
        "studio_modules": list(STUDIO_MODULES),
        "engines": deepcopy(ENGINE_CATALOG),
        "checker_rule": "Separate checker role; no self-approval; PASS/FAIL with revision loop."
    }
