"""Offline-first production catalog for SINTU AI STUDIO.

This catalog describes production formats and required pipeline stages. It does not
claim that external AI providers or publishing accounts are connected.
"""
VIDEO_FORMATS = [
 {"id":"youtube-shorts","name":"YouTube Shorts","category":"Short-form","aspect_ratio":"9:16","recommended_resolution":"1080x1920","duration":"15–60 sec (up to platform limit)","stage":"ready_for_api","description":"Fast vertical storytelling, facts, hooks and CTA."},
 {"id":"youtube-long","name":"YouTube Long-form","category":"Long-form","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"5–60+ min","stage":"production_workflow","description":"Documentary, tutorials, explainers, reviews and storytelling."},
 {"id":"youtube-live-promo","name":"Live / Premiere Promo","category":"Promotion","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"15–90 sec","stage":"production_workflow","description":"Announcement trailers and event countdown promos."},
 {"id":"instagram-reels","name":"Instagram Reels","category":"Short-form","aspect_ratio":"9:16","recommended_resolution":"1080x1920","duration":"15–90 sec","stage":"production_workflow","description":"Vertical reels, product stories and creator clips."},
 {"id":"facebook-reels","name":"Facebook Reels","category":"Short-form","aspect_ratio":"9:16","recommended_resolution":"1080x1920","duration":"15–90 sec","stage":"production_workflow","description":"Vertical social clips and community-first videos."},
 {"id":"tiktok","name":"TikTok Video","category":"Short-form","aspect_ratio":"9:16","recommended_resolution":"1080x1920","duration":"15–90 sec","stage":"production_workflow","description":"Hook-led vertical clips and trends; trend verification needs live research."},
 {"id":"square-social","name":"Square Social Video","category":"Social","aspect_ratio":"1:1","recommended_resolution":"1080x1080","duration":"15–90 sec","stage":"production_workflow","description":"Feed-native square video for social platforms."},
 {"id":"landscape-social","name":"Landscape Social Video","category":"Social","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"15 sec–5 min","stage":"production_workflow","description":"Wide social explainers and announcements."},
 {"id":"documentary","name":"Documentary","category":"Long-form","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"8–60 min","stage":"production_workflow","description":"Research-led narrative, interviews, archive and b-roll."},
 {"id":"educational","name":"Educational / Tutorial","category":"Learning","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"3–30 min","stage":"production_workflow","description":"Step-by-step lessons, demonstrations and screen-led teaching."},
 {"id":"course-lesson","name":"Course Lesson","category":"Learning","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"5–25 min","stage":"production_workflow","description":"Structured lesson with objectives, examples, recap and quiz."},
 {"id":"explainer","name":"Animated Explainer","category":"Animation","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"30 sec–5 min","stage":"prompt_and_storyboard","description":"Motion-graphic and illustration-style explainer; editable animation rigs are not included."},
 {"id":"2d-cartoon","name":"2D Cartoon Story","category":"Animation","aspect_ratio":"16:9 or 9:16","recommended_resolution":"1920x1080","duration":"30 sec–10 min","stage":"prompt_and_storyboard","description":"2D visual style and storyboard; full character-rig animation requires a later engine."},
 {"id":"3d-animation","name":"3D Animation Story","category":"Animation","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"30 sec–10 min","stage":"prompt_and_storyboard","description":"3D-style scene prompts and shot planning; no native 3D scene renderer yet."},
 {"id":"ai-avatar","name":"AI Avatar Presenter","category":"Avatar","aspect_ratio":"9:16 or 16:9","recommended_resolution":"1080x1920","duration":"30 sec–15 min","stage":"integration_required","description":"Presenter script and shot plan; talking-avatar provider integration required."},
 {"id":"faceless","name":"Faceless Channel Video","category":"Creator","aspect_ratio":"16:9","recommended_resolution":"1920x1080","duration":"3–20 min","stage":"production_workflow","description":"Narration, stock/AI visuals, captions and b-roll."},
 {"id":"product-ad","name":"Product / Brand Ad","category":"Commercial","aspect_ratio":"9:16 or 16:9","recommended_resolution":"1080p","duration":"6–60 sec","stage":"production_workflow","description":"Product showcase, benefits, proof points and CTA."},
 {"id":"music-video","name":"Music Video / Lyric Video","category":"Music","aspect_ratio":"16:9 or 9:16","recommended_resolution":"1080p","duration":"1–6 min","stage":"production_workflow","description":"Music-led visual sequence; use music you own or are licensed to use."},
 {"id":"podcast-clips","name":"Podcast Clips","category":"Creator","aspect_ratio":"9:16","recommended_resolution":"1080x1920","duration":"30–90 sec","stage":"production_workflow","description":"Speaker highlights, captions and reframed excerpts."},
 {"id":"slideshow","name":"Photo Slideshow","category":"Basic video","aspect_ratio":"16:9 or 9:16","recommended_resolution":"1080p","duration":"15 sec–10 min","stage":"renderer_supported","description":"Still-image timeline with narration, captions, music and transitions."},
 {"id":"story-video","name":"Story / Mystery Video","category":"Storytelling","aspect_ratio":"9:16 or 16:9","recommended_resolution":"1080p","duration":"30 sec–20 min","stage":"production_workflow","description":"Suspense-led narrative, scene prompts, sound cues and reveal."},
 {"id":"news-summary","name":"News / Current Affairs Explainer","category":"Information","aspect_ratio":"16:9 or 9:16","recommended_resolution":"1080p","duration":"1–12 min","stage":"research_required","description":"Requires current source verification before publishing."}
]
PIPELINE = [
 {"id":"brief","name":"Brief & goals","description":"Topic, audience, language, platform, duration and CTA."},
 {"id":"research","name":"Research & fact check","description":"Evidence checklist, source requirements and uncertainty labels."},
 {"id":"script","name":"Script & storyboard","description":"Hook, narration, scenes, shot prompts, on-screen text and pacing."},
 {"id":"assets","name":"Visual and audio assets","description":"Image/video prompts, voice, music and sound-effect requirements."},
 {"id":"edit","name":"Timeline & editing","description":"Sequence, trims, subtitles, audio levels and transitions."},
 {"id":"quality","name":"Quality assurance","description":"Aspect ratio, timing, spelling, audio, rights and factual review."},
 {"id":"export","name":"Export & delivery","description":"MP4 plus script, subtitles, metadata and project manifest."},
 {"id":"publish","name":"Approval & publishing","description":"Human approval, connected platform account and publish confirmation."}
]
PRESETS = [
 {"id":"mystery-short","name":"Hindi Mystery Short","format":"youtube-shorts","duration_seconds":60,"language":"Hindi","tone":"Suspenseful, factual","prompt":"भारत की एक रहस्यमयी जगह पर 60 सेकंड का तथ्य-जाँचा हुआ YouTube Short बनाओ। मजबूत hook, 6–8 scenes, Hindi voiceover, हर scene का visual prompt, on-screen text, sound cues, CTA, description और hashtags दो। अप्रमाणित दावों को स्पष्ट चिह्नित करो।"},
 {"id":"documentary","name":"Documentary Starter","format":"documentary","duration_seconds":600,"language":"Hindi","tone":"Cinematic, informative","prompt":"इस विषय पर research-led documentary package बनाओ: audience, objective, verified facts vs claims to verify, opening hook, chapters, full narration, scene-by-scene visual prompts, b-roll, music/SFX, thumbnail, metadata और source checklist।"},
 {"id":"faceless","name":"Faceless Explainer","format":"faceless","duration_seconds":480,"language":"Hindi","tone":"Clear, engaging","prompt":"इस topic पर faceless YouTube explainer बनाओ। Full narration, timestamped scenes, b-roll/AI visual prompts, captions, transitions, sound design, title, thumbnail concept, description और tags शामिल करो।"},
 {"id":"course","name":"Course Lesson","format":"course-lesson","duration_seconds":600,"language":"Hindi","tone":"Teacher-like","prompt":"इस विषय पर structured video lesson बनाओ: learning objectives, prerequisites, chapter plan, simple examples, narration, visuals, recap, quiz with answers and assignment।"},
 {"id":"product-ad","name":"Product Promo","format":"product-ad","duration_seconds":30,"language":"Hindi","tone":"Persuasive, truthful","prompt":"इस product के लिए 30-second ad package बनाओ। Target audience, problem, truthful benefits, shot list, voiceover, on-screen copy, CTA और platform variants दो। Unsupported claims न जोड़ो।"}
]
def production_catalog():
 return {"version":1,"formats":VIDEO_FORMATS,"pipeline":PIPELINE,"presets":PRESETS,
         "export_profiles":[{"id":"portrait_hd","label":"Portrait HD","width":720,"height":1280},{"id":"portrait_full_hd","label":"Portrait Full HD","width":1080,"height":1920},{"id":"square","label":"Square","width":1080,"height":1080},{"id":"landscape_hd","label":"Landscape HD","width":1280,"height":720},{"id":"landscape_full_hd","label":"Landscape Full HD","width":1920,"height":1080}],
         "frame_rates":[24,30,60],
         "notes":["Catalog entries describe production targets, not guaranteed provider capability.","True editable 2D/3D rigs, avatar rendering and 4K/8K native rendering need dedicated integrations.","API keys can be added later in server-side environment settings; never put secrets in browser code."]}
