"""Free, deterministic procedural sound effects for local SINTU video renders."""
from array import array
import math
from pathlib import Path
import random
import re
import sys
import wave

SAMPLE_RATE = 22050
MAX_DURATION_SECONDS = 1800
MAX_SCENES = 25

_KEYWORDS = {
    "impact": ("battle", "war", "fight", "explosion", "attack", "impact", "युद्ध", "लड़ाई", "धमाका", "हमला"),
    "wind": ("mystery", "night", "forest", "wind", "secret", "जंगल", "रहस्य", "रात", "हवा"),
    "water": ("water", "river", "rain", "ocean", "sea", "समुद्र", "नदी", "बारिश", "पानी"),
    "footsteps": ("walk", "walking", "footstep", "steps", "चलना", "कदम", "दौड़"),
    "gate": ("gate", "door", "fort", "castle", "किला", "दरवाजा", "दरवाज़ा", "फाटक"),
}


def _scene_effect(text: str) -> str | None:
    value = text.lower()
    for kind, words in _KEYWORDS.items():
        if any(word in value for word in words):
            return "impact" if kind == "gate" else kind
    return None


def _sample(kind: str, t: float, duration: float, rng: random.Random) -> float:
    x = min(1.0, max(0.0, t / duration))
    noise = rng.uniform(-1.0, 1.0)
    if kind == "whoosh":
        envelope = math.sin(math.pi * x) ** 1.35
        frequency = 240.0 - 150.0 * x
        return envelope * (0.56 * math.sin(2 * math.pi * frequency * t) + 0.24 * noise)
    if kind == "impact":
        envelope = math.exp(-8.5 * t)
        return envelope * (0.72 * math.sin(2 * math.pi * 68 * t) + 0.18 * noise)
    if kind == "wind":
        envelope = 0.25 + 0.75 * math.sin(math.pi * x)
        return envelope * (0.35 * noise + 0.28 * math.sin(2 * math.pi * 74 * t))
    if kind == "water":
        envelope = math.sin(math.pi * x) ** 0.6
        return envelope * (0.42 * noise + 0.14 * math.sin(2 * math.pi * 230 * t))
    if kind == "footsteps":
        pulse = 0.0
        for onset in (0.06, 0.39):
            local = t - onset
            if local >= 0:
                pulse += math.exp(-25 * local) * (0.55 * math.sin(2 * math.pi * 72 * local) + 0.12 * noise)
        return pulse
    return 0.0


def generate_scene_sound_effects(scenes: list[str], durations: list[float],
                                 output_path: Path, volume: float = 0.18) -> dict | None:
    """Build an original mono WAV cue track; no external API, sample pack or copyrighted audio."""
    if not scenes or len(scenes) > MAX_SCENES or len(scenes) != len(durations):
        raise ValueError("Sound effect track needs 1–25 scene descriptions and matching durations.")
    if not isinstance(volume, (int, float)) or not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError("Sound effect volume must be between 0 and 1.")
    clean_durations = [float(value) for value in durations]
    if any(not math.isfinite(value) or value <= 0 for value in clean_durations):
        raise ValueError("Sound effect scene durations must be positive finite numbers.")
    total_duration = sum(clean_durations)
    if total_duration > MAX_DURATION_SECONDS:
        raise ValueError("Sound effect track cannot exceed 30 minutes.")

    cues = []
    cursor = 0.0
    for index, (scene, duration) in enumerate(zip(scenes, clean_durations)):
        if index:
            cues.append({"kind": "whoosh", "start": max(0.0, cursor - 0.18), "duration": 0.48, "scene": index + 1})
        kind = _scene_effect(str(scene))
        if kind:
            cue_duration = min(duration, 1.15 if kind in {"wind", "water"} else 0.78)
            cues.append({"kind": kind, "start": cursor + min(0.12, duration * 0.12),
                         "duration": cue_duration, "scene": index + 1})
        cursor += duration

    if not cues or volume == 0:
        return None

    sample_count = int(math.ceil(total_duration * SAMPLE_RATE))
    track = array("h", [0]) * sample_count
    for cue_index, cue in enumerate(cues):
        start_sample = int(cue["start"] * SAMPLE_RATE)
        count = min(int(cue["duration"] * SAMPLE_RATE), sample_count - start_sample)
        rng = random.Random(f"sintu-sfx-{cue['kind']}-{cue['scene']}-{cue_index}")
        for offset in range(count):
            t = offset / SAMPLE_RATE
            sample = _sample(cue["kind"], t, cue["duration"], rng)
            value = int(sample * volume * 32767)
            position = start_sample + offset
            track[position] = max(-32768, min(32767, track[position] + value))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.byteorder != "little":
        track.byteswap()
    with wave.open(str(output_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(track.tobytes())
    return {
        "path": output_path,
        "duration_seconds": round(total_duration, 3),
        "sample_rate": SAMPLE_RATE,
        "cue_count": len(cues),
        "cues": cues,
        "provider": "SINTU Procedural Sound Effects (local, original)",
    }
