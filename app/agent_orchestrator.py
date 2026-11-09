"""Workflow team routing for the 61-role SINTU AI STUDIO catalog.

This is transparent role orchestration inside one configured model request. It is
not 61 independent background agents or parallel model processes.
"""
from .agents import AGENTS

WORKFLOW_TEAMS = {
    "shorts": ["Master AI", "Task Manager", "Workflow Agent", "Trend Detector", "Fact Checker", "Audience Analyst", "Language Specialist", "Script Writer", "Storytelling", "Filmmaking Director", "AI Video Generator", "Voice Generator", "Sound Designer", "Subtitle Creator", "Thumbnail Designer", "Title Generator", "Description Writer", "Hashtag & Tag Expert", "Quality Enhancer", "Testing & QA Agent"],
    "long-video": ["Master AI", "Task Manager", "Workflow Agent", "Web Research", "Fact Checker", "Competitor Analyst", "Content Planner", "Channel Strategist", "Audience Analyst", "Script Writer", "Storytelling", "Documentary Producer", "Filmmaking Director", "Visual Effects Artist", "Voice Generator", "Narration Director", "Music Composer", "Sound Designer", "Subtitle Creator", "Video Editor", "Thumbnail Designer", "CTR Optimizer", "Title Generator", "Description Writer", "Testing & QA Agent"],
    "thumbnail": ["Master AI", "Audience Analyst", "Competitor Analyst", "Thumbnail Designer", "CTR Optimizer", "Image Generator", "Quality Enhancer", "Testing & QA Agent"],
    "script": ["Master AI", "Language Specialist", "Script Writer", "Storytelling", "Audience Analyst", "Fact Checker", "Narration Director", "Testing & QA Agent"],
    "research": ["Master AI", "Web Research", "Fact Checker", "Trend Detector", "Competitor Analyst", "Keyword Research", "Topic Predictor", "Audience Analyst", "Cyber Security Agent", "Testing & QA Agent"],
    "course": ["Master AI", "Course Designer", "Lesson Creator", "Educational Expert", "Language Specialist", "Quiz & Assessment", "Cyber Security Agent", "Fact Checker", "Testing & QA Agent"],
    "social": ["Master AI", "Audience Analyst", "Trend Detector", "Content Planner", "Language Specialist", "Script Writer", "Hashtag & Tag Expert", "Distribution Manager", "Community Manager", "Testing & QA Agent"],
    "content": ["Master AI", "Task Manager", "Workflow Agent", "Content Planner", "Channel Strategist", "Audience Analyst", "Language Specialist", "Script Writer", "Fact Checker", "Testing & QA Agent"],
}

ROLE_MISSIONS = {
    "Master AI": "Own the brief, coordinate specialist perspectives, resolve conflicts and produce the final deliverable.",
    "Task Manager": "Break the request into ordered tasks and preserve constraints.",
    "Workflow Agent": "Select and enforce the correct production workflow.",
    "Web Research": "Identify evidence needs and trustworthy sources; never fabricate live research.",
    "Fact Checker": "Flag factual claims, uncertainty and verification requirements.",
    "Trend Detector": "Suggest trend signals and explain when live data is unavailable.",
    "Competitor Analyst": "Propose ethical competitor-analysis dimensions without inventing observations.",
    "Keyword Research": "Suggest search-intent and keyword clusters; label estimates.",
    "Topic Predictor": "Suggest testable topic opportunities, not guaranteed outcomes.",
    "Content Planner": "Structure the content objective, format and publishing plan.",
    "Channel Strategist": "Align the package with channel positioning and audience.",
    "Audience Analyst": "Adapt complexity, language, pacing and CTA to the audience.",
    "Content Calendar": "Suggest a realistic sequence and cadence.",
    "Language Specialist": "Keep language natural, consistent and localized.",
    "Script Writer": "Write clear, spoken-language-ready copy.",
    "Storytelling": "Strengthen hook, narrative tension, payoff and pacing.",
    "Course Designer": "Build measurable learning progression.",
    "Lesson Creator": "Create teachable explanations, examples and activities.",
    "Educational Expert": "Check level, pedagogy and learning objectives.",
    "Quiz & Assessment": "Create answerable questions and a transparent answer key.",
    "Image Generator": "Write specific visual-generation prompts; do not claim images were generated.",
    "2D Animation": "Specify 2D motion, staging and transitions.",
    "3D Animation": "Specify 3D scene, camera, lighting and motion requirements.",
    "AI Video Generator": "Prepare shot-level text-to-video prompts; do not claim rendered footage.",
    "Google Flow Specialist": "Prepare Flow-compatible scene direction; no unsupported integration claims.",
    "Documentary Producer": "Shape evidence-led documentary structure.",
    "Filmmaking Director": "Specify framing, camera movement, lighting and continuity.",
    "Visual Effects Artist": "Specify VFX layers and compositing requirements.",
    "Voice Generator": "Prepare narration text and voice direction; do not claim audio was generated.",
    "Narration Director": "Set delivery, pronunciation, pauses and emphasis.",
    "Music Composer": "Describe original music direction and licensing needs.",
    "Sound Designer": "Specify sound effects, ambience and mix cues.",
    "Video Editor": "Prepare timeline, cuts, transitions and edit notes.",
    "Subtitle Creator": "Prepare readable subtitle text and timing guidance.",
    "Motion Graphics": "Specify titles, lower thirds, charts and motion.",
    "Quality Enhancer": "Review clarity, continuity, accessibility and output constraints.",
    "Final Render Agent": "Prepare export settings; do not claim a render exists.",
    "Thumbnail Designer": "Create distinct, mobile-readable thumbnail concepts.",
    "CTR Optimizer": "Improve clarity and curiosity; never guarantee CTR.",
    "Title Generator": "Create accurate, compelling title variants.",
    "Description Writer": "Write useful descriptions and chapters.",
    "Hashtag & Tag Expert": "Suggest relevant tags without keyword stuffing.",
    "YouTube Publisher": "Prepare upload metadata; publishing requires user-approved OAuth.",
    "Social Media Publisher": "Adapt assets per platform; posting requires official authorization.",
    "Scheduler": "Propose schedule; no posts are scheduled by this role alone.",
    "Distribution Manager": "Plan platform-specific distribution.",
    "Comment Analyzer": "Classify comment themes and sentiment when data is supplied.",
    "Reply Assistant": "Draft respectful replies; do not post without approval.",
    "Spam Detector": "Flag likely spam for human review.",
    "Community Manager": "Suggest community engagement and escalation.",
    "Channel Analytics": "Interpret supplied channel metrics; separate facts from estimates.",
    "CTR & Retention Analyst": "Analyze supplied CTR and retention data; do not invent metrics.",
    "Revenue Analyst": "Model scenarios from supplied data, not guaranteed income.",
    "Sponsorship Finder": "Prepare sponsor-fit criteria and outreach drafts.",
    "Affiliate & Profit Analyst": "Estimate unit economics from explicit assumptions.",
    "Cyber Security Agent": "Keep security content defensive and labs explicitly authorized.",
    "Privacy & Access Agent": "Minimize personal data and protect credentials.",
    "Testing & QA Agent": "Check completeness, consistency and policy constraints.",
    "System Health Agent": "Identify operational health checks and failure signals.",
    "Memory Agent": "Carry project context only when explicitly supplied to the workflow.",
    "Automation Agent": "Identify safe repeatable steps and approval gates.",
}

def workflow_team(workflow: str) -> list[dict]:
    names = WORKFLOW_TEAMS.get(workflow, WORKFLOW_TEAMS["content"])
    return [
        {"name": name, "mission": ROLE_MISSIONS.get(name, "Contribute specialist review to the requested workflow.")}
        for name in names
    ]

def orchestration_summary() -> dict:
    assigned = {name for team in WORKFLOW_TEAMS.values() for name in team}
    return {
        "catalog_total": len(AGENTS),
        "workflow_teams": len(WORKFLOW_TEAMS),
        "roles_routed": len(assigned),
        "execution_mode": "single_model_multi_role_prompt",
        "independent_agents_running": 0,
    }
