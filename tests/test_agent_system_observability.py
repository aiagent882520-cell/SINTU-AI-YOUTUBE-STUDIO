from app.agents import list_agents
from app.agent_orchestrator import orchestration_summary


def test_agent_catalog_does_not_claim_registered_roles_are_running():
    agents = list_agents()
    assert len(agents) == 61
    assert all("not a continuously running agent" in agent["status"] for agent in agents)
    assert all(agent["execution_mode"] == "invoked_on_demand_through_local_model_gateway"
               for agent in agents)


def test_orchestration_reports_no_independent_background_fleet():
    summary = orchestration_summary()
    assert summary["catalog_total"] == 61
    assert summary["independent_agents_running"] == 0
    assert summary["checker_pairs"] == summary["independent_checker_catalog_total"]
