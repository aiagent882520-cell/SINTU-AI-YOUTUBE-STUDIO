"""Central guard for the revenue-first paid-upgrade rule."""
import os

def paid_upgrades_allowed() -> bool:
    return (os.getenv("SINTU_REVENUE_CONFIRMED", "false").strip().lower() == "true"
            and os.getenv("ALLOW_PAID_UPGRADES", "false").strip().lower() == "true")


def production_actions_allowed() -> bool:
    """Video/media production is opt-in and stays paused unless the owner enables it."""
    return os.getenv("SINTU_PRODUCTION_ENABLED", "false").strip().lower() == "true"


def external_publishing_allowed() -> bool:
    """External platform uploads/publishing are opt-in and default to disabled."""
    return os.getenv("SINTU_EXTERNAL_PUBLISHING_ENABLED", "false").strip().lower() == "true"
