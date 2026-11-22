from app import main
from app import access_control


def test_production_factory_plan_endpoint_is_registered_and_feature_gated():
    route = next(
        route for route in main.app.routes
        if getattr(route, "path", None) == "/api/production-factory/plan"
    )
    assert "POST" in route.methods
    assert access_control.feature_for_path("/api/production-factory/plan") == "production"


def test_production_factory_plan_endpoint_returns_non_executing_plan():
    payload = main.ProductionFactoryPlanInput(topic="Hindi space explainer", format_id="educational")
    result = main.production_factory_plan(payload)
    assert result["topic"] == "Hindi space explainer"
    assert result["execution_started"] is False
    assert result["publishing_enabled"] is False
    assert len(result["stages"]) >= 10
