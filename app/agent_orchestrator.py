"""Workflow routing with distinct worker/checker roles and explicit execution limits."""
from copy import deepcopy
from .agents import AGENTS
from .studio_scope import SPECIALIST_ROLES, AGENT_PAIRS, CHECKER_SUFFIX, ROLE_PRESETS, COMMON_ROLES, get_format

WORKFLOW_TEAMS = {
 "shorts":["Master AI","Task Manager","Workflow Agent","Trend Detector","Fact Checker","Audience Analyst","Language Specialist","Script Writer","Storytelling","Filmmaking Director","AI Video Generator","Voice Generator","Sound Designer","Subtitle Creator","Thumbnail Designer","Title Generator","Description Writer","Hashtag & Tag Expert","Quality Enhancer","Testing & QA Agent"],
 "long-video":["Master AI","Task Manager","Workflow Agent","Web Research","Fact Checker","Competitor Analyst","Content Planner","Channel Strategist","Audience Analyst","Script Writer","Storytelling","Documentary Producer","Filmmaking Director","Visual Effects Artist","Voice Generator","Narration Director","Music Composer","Sound Designer","Subtitle Creator","Video Editor","Thumbnail Designer","CTR Optimizer","Title Generator","Description Writer","Testing & QA Agent"],
 "thumbnail":["Master AI","Audience Analyst","Competitor Analyst","Thumbnail Designer","CTR Optimizer","Image Generator","Quality Enhancer","Testing & QA Agent"],
 "script":["Master AI","Language Specialist","Script Writer","Storytelling","Audience Analyst","Fact Checker","Narration Director","Testing & QA Agent"],
 "research":["Master AI","Web Research","Fact Checker","Trend Detector","Competitor Analyst","Keyword Research","Topic Predictor","Audience Analyst","Cyber Security Agent","Testing & QA Agent"],
 "course":["Master AI","Course Designer","Lesson Creator","Educational Expert","Language Specialist","Quiz & Assessment","Cyber Security Agent","Fact Checker","Testing & QA Agent"],
 "social":["Master AI","Audience Analyst","Trend Detector","Content Planner","Language Specialist","Script Writer","Hashtag & Tag Expert","Distribution Manager","Community Manager","Testing & QA Agent"],
 "content":["Master AI","Task Manager","Workflow Agent","Content Planner","Channel Strategist","Audience Analyst","Language Specialist","Script Writer","Fact Checker","Testing & QA Agent"]
}
ROLE_MISSIONS = {
 "Master AI":"Coordinate the brief, specialist work, stage gates and final delivery.",
 "Task Manager":"Break work into ordered, traceable tasks.",
 "Workflow Agent":"Choose the appropriate production preset.",
 "Web Research":"Identify sources and evidence; never invent live research.",
 "Fact Checker":"Check factual claims and flag uncertainty.",
 "Audience Analyst":"Adapt complexity, pacing and language to the audience.",
 "Script Writer":"Write spoken-language-ready scripts.",
 "Storytelling":"Improve hook, narrative tension and payoff.",
 "Documentary Producer":"Shape evidence-led documentary structure.",
 "Filmmaking Director":"Specify framing, camera movement, lighting and continuity.",
 "Video Editor":"Prepare timeline, cuts, transitions and edit notes.",
 "Testing & QA Agent":"Check output completeness and measurable requirements."
}
def _checker_name(role):
    return role + CHECKER_SUFFIX

def workflow_team(workflow: str) -> list[dict]:
    names = WORKFLOW_TEAMS.get(workflow, WORKFLOW_TEAMS["content"])
    result = []
    for name in names:
        result.append({"name":name,"role_type":"specialist","mission":ROLE_MISSIONS.get(name,"Contribute specialist work to the selected workflow.")})
        result.append({"name":_checker_name(name),"role_type":"independent_checker",
                       "checks":name,"mission":"Independently evaluate the submitted work; return PASS/FAIL, evidence, issues and revision instructions."})
    return result

def format_team(format_id: str) -> list[dict]:
    item = get_format(format_id)
    if not item:
        raise KeyError(format_id)
    result = []
    for name in item["roles"]:
        result.extend([
          {"name":name,"role_type":"specialist","mission":ROLE_MISSIONS.get(name,"Perform the assigned specialist task.")},
          {"name":_checker_name(name),"role_type":"independent_checker","checks":name,
           "mission":"Independently verify against acceptance criteria; PASS/FAIL and request revision where needed."}
        ])
    return result

def orchestration_summary() -> dict:
    assigned = {name for team in WORKFLOW_TEAMS.values() for name in team}
    return {
      "catalog_total":len(AGENTS),
      "workflow_teams":len(WORKFLOW_TEAMS),
      "roles_routed":len(assigned),
      "execution_mode":"shared_model_gateway_with_distinct_worker_and_checker_roles",
      "independent_agents_running":0,
      "specialist_catalog_total":len(SPECIALIST_ROLES),
      "independent_checker_catalog_total":len(AGENT_PAIRS),
      "checker_pairs":len(AGENT_PAIRS),
      "checker_policy":"Worker and checker are separate role instances; a checker must not self-approve. Execution is not represented as running background agents until a worker runtime is connected."
    }
