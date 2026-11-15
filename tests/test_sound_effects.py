import wave

import pytest

from app.sound_effects import generate_scene_sound_effects


def test_procedural_sound_effects_create_original_wav_and_scene_cues(tmp_path):
    path = tmp_path / "scene-sfx.wav"
    result = generate_scene_sound_effects(
        ["पुराने किले का दरवाज़ा", "रात का रहस्य और जंगल", "नदी के किनारे बारिश"],
        [3, 3, 3], path, volume=0.2,
    )
    assert result is not None
    assert result["provider"] == "SINTU Procedural Sound Effects (local, original)"
    assert result["cue_count"] >= 5
    assert {cue["kind"] for cue in result["cues"]} >= {"impact", "whoosh", "wind", "water"}
    assert path.is_file() and path.stat().st_size > 1000
    with wave.open(str(path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 22050
        assert audio.getnframes() == 9 * 22050
        assert max(audio.readframes(audio.getnframes())) > 0


def test_procedural_sound_effects_are_deterministic(tmp_path):
    scenes = ["युद्ध का दृश्य", "रहस्यमयी जंगल"]
    first = generate_scene_sound_effects(scenes, [2, 2], tmp_path / "a.wav")
    second = generate_scene_sound_effects(scenes, [2, 2], tmp_path / "b.wav")
    assert first["cues"] == second["cues"]
    assert (tmp_path / "a.wav").read_bytes() == (tmp_path / "b.wav").read_bytes()


@pytest.mark.parametrize("scenes,durations,volume", [
    ([], [], 0.2),
    (["one"], [], 0.2),
    (["one"], [0], 0.2),
    (["one"], [1], 1.1),
])
def test_procedural_sound_effects_reject_invalid_inputs(tmp_path, scenes, durations, volume):
    with pytest.raises(ValueError):
        generate_scene_sound_effects(scenes, durations, tmp_path / "invalid.wav", volume)



def test_procedural_sound_effects_can_be_silenced(tmp_path):
    result = generate_scene_sound_effects(["युद्ध का दृश्य"], [2], tmp_path / "silent.wav", volume=0)
    assert result is None
    assert not (tmp_path / "silent.wav").exists()
