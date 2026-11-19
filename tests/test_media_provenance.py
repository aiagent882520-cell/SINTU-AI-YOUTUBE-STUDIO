import json
from pathlib import Path

import pytest

from app.media_provenance import write_render_manifest


def test_render_manifest_records_content_hashes_without_absolute_paths_or_topic(tmp_path):
    output = tmp_path / "generated_videos" / "final.mp4"
    image = tmp_path / "generated_images" / "scene.jpg"
    music = tmp_path / "generated_music" / "score.wav"
    for path, data in ((output, b"final-mp4"), (image, b"scene-image"), (music, b"music-wav")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    result = write_render_manifest(
        data_dir=tmp_path,
        run_id="a" * 32,
        format_id="youtube-shorts",
        topic="private topic text",
        output_path=output,
        asset_paths=[image, music],
        settings={"resolution": "720x1280", "fps": 30},
        engines={"image": "local-comfyui", "music": "procedural"},
    )

    manifest_path = tmp_path / result["manifest_path"]
    stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1
    assert stored["run_id"] == "a" * 32
    assert stored["output"]["path"] == "generated_videos/final.mp4"
    assert stored["output"]["sha256"] == __import__("hashlib").sha256(b"final-mp4").hexdigest()
    assert [item["path"] for item in stored["inputs"]] == [
        "generated_images/scene.jpg", "generated_music/score.wav"
    ]
    assert all("sha256" in item and "size_bytes" in item for item in stored["inputs"])
    assert "private topic text" not in manifest_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in manifest_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_run_id", ["../escape", "A" * 32, "short"])
def test_render_manifest_rejects_invalid_run_id(tmp_path, bad_run_id):
    output = tmp_path / "final.mp4"
    output.write_bytes(b"video")
    with pytest.raises(ValueError, match="run ID"):
        write_render_manifest(
            data_dir=tmp_path,
            run_id=bad_run_id,
            format_id="youtube-shorts",
            topic="topic",
            output_path=output,
            asset_paths=[],
        )


def test_render_manifest_rejects_assets_outside_data_directory(tmp_path):
    output = tmp_path / "final.mp4"
    output.write_bytes(b"video")
    outside = tmp_path.parent / "outside.wav"
    outside.write_bytes(b"audio")
    try:
        with pytest.raises(ValueError, match="inside DATA_DIR"):
            write_render_manifest(
                data_dir=tmp_path,
                run_id="b" * 32,
                format_id="youtube-shorts",
                topic="topic",
                output_path=output,
                asset_paths=[outside],
            )
    finally:
        outside.unlink(missing_ok=True)


def test_render_manifest_rejects_missing_render_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_render_manifest(
            data_dir=tmp_path,
            run_id="c" * 32,
            format_id="youtube-shorts",
            topic="topic",
            output_path=tmp_path / "missing.mp4",
            asset_paths=[],
        )
