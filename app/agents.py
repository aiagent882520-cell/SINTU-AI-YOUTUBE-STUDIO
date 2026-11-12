AGENTS = [
    "Master AI", "Task Manager", "Workflow Agent", "Memory Agent", "Automation Agent",
    "Web Research", "Fact Checker", "Trend Detector", "Competitor Analyst", "Keyword Research",
    "Topic Predictor", "Content Planner", "Channel Strategist", "Audience Analyst", "Content Calendar",
    "Language Specialist", "Script Writer", "Storytelling", "Course Designer", "Lesson Creator",
    "Educational Expert", "Quiz & Assessment", "Image Generator", "2D Animation", "3D Animation",
    "AI Video Generator", "Google Flow Specialist", "Documentary Producer", "Filmmaking Director",
    "Visual Effects Artist", "Voice Generator", "Narration Director", "Music Composer", "Sound Designer",
    "Video Editor", "Subtitle Creator", "Motion Graphics", "Quality Enhancer", "Final Render Agent",
    "Thumbnail Designer", "CTR Optimizer", "Title Generator", "Description Writer", "Hashtag & Tag Expert",
    "YouTube Publisher", "Social Media Publisher", "Scheduler", "Distribution Manager", "Comment Analyzer",
    "Reply Assistant", "Spam Detector", "Community Manager", "Channel Analytics", "CTR & Retention Analyst",
    "Revenue Analyst", "Sponsorship Finder", "Affiliate & Profit Analyst", "Cyber Security Agent",
    "Privacy & Access Agent", "Testing & QA Agent", "System Health Agent"
]


def list_agents():
    return [
        {
            "id": index + 1,
            "name": name,
            "status": "Runnable worker/checker role",
            "execution_mode": "on_demand_local_model",
            "external_integration": "Requires configured platform credentials where applicable"
            if name in {"YouTube Publisher", "Social Media Publisher", "Scheduler", "Channel Analytics"}
            else None,
        }
        for index, name in enumerate(AGENTS)
    ]
