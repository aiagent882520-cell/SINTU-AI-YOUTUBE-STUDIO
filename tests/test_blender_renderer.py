from pathlib import Path
import pytest
from app import blender_renderer

def test_blender_scene_validation_rejects_unsafe_or_invalid_shapes():
    with pytest.raises(ValueError):
        blender_renderer.validate_scene("Bad", [{"shape":"python"}], 5, "1280x720", 24)
    with pytest.raises(ValueError):
        blender_renderer.validate_scene("Bad", [{"shape":"cube","location":[0,0,999]}], 5, "1280x720", 24)

def test_blender_scene_render_uses_local_executable_and_validated_json(tmp_path, monkeypatch):
    monkeypatch.setattr(blender_renderer, "BLENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(blender_renderer, "blender_executable", lambda: "/usr/bin/blender")
    captured = {}
    def fake_run(command, **kwargs):
        captured["command"] = command
        output = Path(command[-1])
        output.write_bytes(b"0000ftypmp42mock-video")
        return type("Result", (), {"returncode":0,"stdout":"","stderr":""})()
    monkeypatch.setattr(blender_renderer.subprocess, "run", fake_run)
    result = blender_renderer.render_scene("SINTU 3D", [{"shape":"sphere","name":"Hero","color":[0.2,0.4,0.8,1]}], 5, "1280x720", 24)
    assert result["local"] is True
    assert result["format"] == "MP4 / H.264"
    assert "--background" in captured["command"]
    assert Path(captured["command"][-1]).is_file()


def test_blender_embedded_script_has_valid_python_syntax():
    compile(blender_renderer.BLENDER_SCRIPT, "<sintu-blender-script>", "exec")
