"""Routing policy for local procedural 2D production formats."""
from .documentary_research import DOCUMENTARY_FORMAT_IDS

PROCEDURAL_2D_FORMAT_IDS = frozenset({"2d-cartoon", "story-animation"}) | DOCUMENTARY_FORMAT_IDS


def uses_procedural_2d(format_id: str) -> bool:
    """Use local scene-aware 2D for animation formats and all research-gated documentaries."""
    return format_id in PROCEDURAL_2D_FORMAT_IDS
