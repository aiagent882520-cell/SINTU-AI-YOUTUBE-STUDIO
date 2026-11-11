"""Central guard for the revenue-first paid-upgrade rule."""
import os

def paid_upgrades_allowed() -> bool:
    return (os.getenv("SINTU_REVENUE_CONFIRMED", "false").strip().lower() == "true"
            and os.getenv("ALLOW_PAID_UPGRADES", "false").strip().lower() == "true")
