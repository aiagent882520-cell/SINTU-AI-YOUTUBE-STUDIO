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



def test_delivery_package_contains_verified_media_captions_and_truthful_project_limits(tmp_path):
    import hashlib
    import zipfile

    from app.media_provenance import create_delivery_package

    run_id = "d" * 32
    output = tmp_path / "generated_videos" / "final.mp4"
    image = tmp_path / "generated_images" / "scene.jpg"
    voice = tmp_path / "generated_audio" / "voice.wav"
    music = tmp_path / "generated_music" / "score.wav"
    thumbnail = tmp_path / "production_thumbnails" / f"{run_id}.jpg"
    for path, data in ((output, b"verified-mp4"), (image, b"scene-image"),
                       (voice, b"hindi-voice"), (music, b"original-score"),
                       (thumbnail, b"thumbnail-jpeg")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    provenance = write_render_manifest(
        data_dir=tmp_path, run_id=run_id, format_id="youtube-shorts",
        topic="Hindi science", output_path=output,
        asset_paths=[image, voice, music, thumbnail],
        quality_report={"verified": True, "black_frame_check": "PASS"},
        settings={"resolution": "720x1280", "fps": 30},
    )
    package = create_delivery_package(
        data_dir=tmp_path, run_id=run_id,
        render_manifest_path=provenance["manifest_path"],
        captions=["पहला दृश्य", "दूसरा दृश्य"], seconds_per_caption=4,
        metadata={"topic": "Hindi science", "format_id": "youtube-shorts"},
        deliverables={"Script Writer": "नमूना स्क्रिप्ट", "Title Generator": '{"title": "नमूना शीर्षक"}', "Description Writer": "Description: नमूना विवरण", "Localization Translator": '{"translations": {"en": ["First scene", "Second scene"]}}'},
        research_evidence={"status": "STRUCTURAL_TRACEABILITY_VALIDATED_NOT_FACT_VERIFIED"},
    )

    archive_path = tmp_path / package["path"]
    assert package["verified"] is True
    assert package["editable_project_included"] is False
    assert package["rights_certificates_included"] is False
    assert package["captions_included"] is True
    assert package["thumbnail_included"] is True
    assert package["translations_included"] is True
    assert package["translation_languages"] == ["en"]
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == package["sha256"]
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        assert "captions/subtitles.hi.srt" in names
        assert "captions/subtitles.en.srt" in names
        assert "00:00:04,000 --> 00:00:08,000" in archive.read("captions/subtitles.en.srt").decode("utf-8")
        assert "metadata/platform-publishing.json" in names
        platform_metadata = json.loads(archive.read("metadata/platform-publishing.json"))
        assert platform_metadata["title"] == "नमूना शीर्षक"
        assert platform_metadata["description"] == "नमूना विवरण"
        assert "tags" in platform_metadata["missing_fields"]
        assert "project/deliverables.json" in names
        assert "reports/quality-report.json" in names
        assert "research/research-evidence.json" in names
        assert "provenance/render-manifest.json" in names
        assert any(name.startswith("video/") for name in names)
        assert any(name.startswith("images/") for name in names)
        assert any(name.startswith("thumbnails/") for name in names)
        assert sum(name.startswith("audio/") for name in names) == 2
        captions = archive.read("captions/subtitles.hi.srt").decode("utf-8")
        assert "00:00:00,000 --> 00:00:04,000" in captions
        assert "00:00:04,000 --> 00:00:08,000" in captions
        readme = archive.read("README.txt").decode("utf-8")
        assert "editable timeline/project file is not exported" in readme
        assert "not a separately art-directed or text-designed cover" in readme
        assert "rights certificates were not supplied" in readme
        index = json.loads(archive.read("PACKAGE-MANIFEST.json"))
        assert index["verified"] is True
        assert "translated subtitle tracks (Hindi captions only)" not in index["not_included"]
        assert "cannot hash itself" in index["self_hash_note"]
        for record in index["entries"]:
            archived = archive.read(record["path"])
            assert len(archived) == record["size_bytes"]
            assert hashlib.sha256(archived).hexdigest() == record["sha256"]
        assert len(index["entries"]) == package["file_count"] - 1


def test_delivery_package_rejects_media_changed_after_provenance(tmp_path):
    from app.media_provenance import create_delivery_package

    run_id = "e" * 32
    output = tmp_path / "generated_videos" / "final.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"verified-before")
    provenance = write_render_manifest(
        data_dir=tmp_path, run_id=run_id, format_id="youtube-shorts",
        topic="topic", output_path=output, asset_paths=[],
        quality_report={"verified": True},
    )
    output.write_bytes(b"tampered-after")
    with pytest.raises(ValueError, match="size changed|hash changed"):
        create_delivery_package(
            data_dir=tmp_path, run_id=run_id,
            render_manifest_path=provenance["manifest_path"],
            captions=[], seconds_per_caption=4, metadata={},
        )


def test_delivery_package_rejects_manifest_for_another_run(tmp_path):
    from app.media_provenance import create_delivery_package

    output = tmp_path / "final.mp4"
    output.write_bytes(b"verified")
    provenance = write_render_manifest(
        data_dir=tmp_path, run_id="f" * 32, format_id="youtube-shorts",
        topic="topic", output_path=output, asset_paths=[],
        quality_report={"verified": True},
    )
    with pytest.raises(ValueError, match="this run's verified"):
        create_delivery_package(
            data_dir=tmp_path, run_id="a" * 32,
            render_manifest_path=provenance["manifest_path"],
            captions=[], seconds_per_caption=4, metadata={},
        )



def test_video_frame_thumbnail_is_extracted_and_validated_locally(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from PIL import Image
    import app.video_renderer as renderer

    run_id = "9" * 32
    video = tmp_path / "generated_videos" / "render.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"verified-mp4-fixture")
    monkeypatch.setattr(renderer, "DATA_DIR", tmp_path)
    monkeypatch.setattr(renderer.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    def fake_ffmpeg(args, **kwargs):
        destination = Path(args[-1])
        Image.new("RGB", (1280, 720), (30, 60, 90)).save(destination, format="JPEG")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(renderer.render_process, "run_render_process", fake_ffmpeg)
    result = renderer.create_video_frame_thumbnail(video, run_id)

    assert result["relative_path"] == f"production_thumbnails/{run_id}.jpg"
    assert result["width"] == 1280 and result["height"] == 720
    assert result["source"] == "verified MP4 representative frame (local FFmpeg)"
    with Image.open(result["path"]) as image:
        assert image.format == "JPEG"
        assert image.size == (1280, 720)


def test_video_frame_thumbnail_rejects_invalid_run_id(tmp_path):
    import app.video_renderer as renderer

    video = tmp_path / "render.mp4"
    video.write_bytes(b"video")
    with pytest.raises(ValueError, match="run ID"):
        renderer.create_video_frame_thumbnail(video, "../unsafe")

def test_platform_metadata_extracts_only_source_backed_fields():
    from app.media_provenance import extract_platform_metadata

    result = extract_platform_metadata({
        "Title Generator": '{"title": "भारत के 5 अद्भुत तथ्य"}',
        "Description Writer": "Description: इस वीडियो में पाँच रोचक तथ्यों को समझें।",
        "YouTube SEO Tags Expert": "Tags: विज्ञान, भारत, रोचक तथ्य\nHashtags: #विज्ञान, #भारत",
    })
    assert result["platform"] == "youtube"
    assert result["status"] == "partial"
    assert result["title"] == "भारत के 5 अद्भुत तथ्य"
    assert result["description"].startswith("इस वीडियो में")
    assert result["tags"] == ["विज्ञान", "भारत", "रोचक तथ्य"]
    assert result["hashtags"] == ["#विज्ञान", "#भारत"]
    assert result["category"] is None
    assert result["missing_fields"] == ["category"]
    assert result["source_roles"]["title"] == "Title Generator"


def test_platform_metadata_does_not_guess_missing_values_or_use_unrelated_text():
    from app.media_provenance import extract_platform_metadata

    result = extract_platform_metadata({"Script Writer": "Title: This is narration, not publishing metadata."})
    assert result["status"] == "missing"
    assert all(result[field] is None for field in ("title", "description", "tags", "hashtags", "category"))
    assert len(result["missing_fields"]) == 5

def test_translated_captions_require_complete_localization_tracks():
    from app.media_provenance import extract_translated_captions

    valid = {
        "Localization Translator": '{"translations": {"en": ["First scene", "Second scene"], "es": ["Primera escena", "Segunda escena"]}}',
        "Script Writer": '{"translations": {"fr": ["Un", "Deux"]}}',
    }
    result = extract_translated_captions(valid, 2)
    assert result == {"en": ["First scene", "Second scene"], "es": ["Primera escena", "Segunda escena"]}
    assert extract_translated_captions({"Translator": '{"translations": {"en": ["only one"]}}'}, 2) == {}
    assert extract_translated_captions({"Translator": '{"translations": {"hi": ["एक", "दो"], "../bad": ["x", "y"]}}'}, 2) == {}
