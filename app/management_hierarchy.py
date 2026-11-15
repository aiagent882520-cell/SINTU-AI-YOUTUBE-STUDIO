"""SINTU supervisory chain and feature-specific independent checker assignments.

ChatGPT is represented as the external supervisory/advisory layer. Termux does not
embed or impersonate the ChatGPT service; local agent execution uses the configured
free local model gateway.
"""
from copy import deepcopy

TOP_SUPERVISOR = {
    "name": "ChatGPT Supervisor",
    "level": 0,
    "role": "Chief AI Advisor",
    "execution_mode": "external_chatgpt_assistant_not_embedded_in_termux",
    "mission": "Set architecture, review plans, provide guidance and help the owner resolve escalations.",
    "local_execution": False,
}

SENIOR_MANAGERS = [
    {
        "name": "HR Agent",
        "level": 1,
        "mission": "Own agent roles, assignment, capability records, workload, training and performance reviews.",
        "supervises": "All specialist and checker agents",
    },
    {
        "name": "Manager Agent",
        "level": 2,
        "mission": "Assign daily tasks, maintain task order, track progress and coordinate worker/checker hand-offs.",
        "supervises": "Feature teams and their checker queues",
    },
    {
        "name": "GM Agent",
        "level": 3,
        "mission": "Coordinate the complete production workflow, dependencies, schedule and department delivery.",
        "supervises": "All production departments",
    },
    {
        "name": "HO Agent",
        "level": 4,
        "mission": "Oversee policy, factual standards, copyright, privacy, security, audit records and operating rules.",
        "supervises": "Compliance and quality gates across the studio",
    },
    {
        "name": "Owner Agent",
        "level": 5,
        "mission": "Review business readiness, free-first budget, final quality reports and prepare an owner approval request.",
        "supervises": "Final release readiness; cannot replace the human owner's approval",
    },
]

FEATURE_CHECKER_PAIRS = [
    {"feature": "Research & fact checking", "agent": "Fact Checker", "checker": "Fact Checker Checker"},
    {"feature": "Hindi script & story", "agent": "Script Writer", "checker": "Script Writer Checker"},
    {"feature": "Storyboard & scene order", "agent": "Scene Order Agent", "checker": "Scene Order Agent Checker"},
    {"feature": "2D animation", "agent": "2D Animator", "checker": "2D Animator Checker"},
    {"feature": "Camera movement", "agent": "Camera Movement Planner", "checker": "Camera Movement Planner Checker"},
    {"feature": "Hindi narration", "agent": "Hindi Narration Agent", "checker": "Hindi Narration Agent Checker"},
    {"feature": "Background music", "agent": "Background Music Agent", "checker": "Background Music Agent Checker"},
    {"feature": "Sound effects", "agent": "Sound Effects Agent", "checker": "Sound Effects Agent Checker"},
    {"feature": "Editing & audio mixing", "agent": "Video Editor", "checker": "Video Editor Checker"},
    {"feature": "Subtitles", "agent": "Subtitle Agent", "checker": "Subtitle Agent Checker"},
    {"feature": "Transitions", "agent": "Transition Designer", "checker": "Transition Designer Checker"},
    {"feature": "Branding & watermark", "agent": "Branding Agent", "checker": "Branding Agent Checker"},
    {"feature": "Visual quality", "agent": "Visual Consistency Agent", "checker": "Visual Consistency Agent Checker"},
    {"feature": "Audio quality", "agent": "Audio Quality Agent", "checker": "Audio Quality Agent Checker"},
    {"feature": "Copyright & originality", "agent": "Copyright Checker Agent", "checker": "Copyright Checker Agent Checker"},
    {"feature": "Final MP4 export", "agent": "Final Render Agent", "checker": "Final Render Agent Checker"},
    {"feature": "YouTube SEO & publishing", "agent": "Upload Agent", "checker": "Upload Agent Checker"},
]

FEATURE_ROLE_NAMES = tuple(dict.fromkeys(
    role
    for pair in FEATURE_CHECKER_PAIRS
    for role in (pair["agent"],)
))
SENIOR_MANAGER_NAMES = tuple(item["name"] for item in SENIOR_MANAGERS)


def management_hierarchy() -> dict:
    """Return a fresh serializable view of the supervisory chain."""
    return {
        "top_supervisor": deepcopy(TOP_SUPERVISOR),
        "senior_managers": deepcopy(SENIOR_MANAGERS),
        "feature_checker_pairs": deepcopy(FEATURE_CHECKER_PAIRS),
        "senior_manager_total": len(SENIOR_MANAGERS),
        "feature_checker_total": len(FEATURE_CHECKER_PAIRS),
        "rule": (
            "Every feature worker has a distinct checker. The five senior agents supervise "
            "the complete feature teams. The Owner Agent may recommend release, but only "
            "the authenticated human owner can approve publishing. ChatGPT is an external "
            "advisor and is not falsely represented as a local Termux process."
        ),
    }
