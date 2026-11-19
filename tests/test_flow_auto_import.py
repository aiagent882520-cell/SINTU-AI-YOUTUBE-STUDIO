from pathlib import Path

from app.flow_auto_import import FlowAutoImporter
from app.video_renderer import RenderFailed


def test_flow_auto_import_waits_for_stable_file_and_deduplicates(tmp_path):
    downloads = tmp_path / "Download"
    videos = tmp_path / "generated_ai_videos"
    data = tmp_path / "data"
    downloads.mkdir()
    source = downloads / "flow-result.mp4"
    source.write_bytes(b"verified video bytes")

    def validator(path):
        assert path.read_bytes() == b"verified video bytes"
        return {"duration": 4}

    importer = FlowAutoImporter(data, videos, [downloads], validator=validator)
    assert importer.scan_once() == 0  # first sighting: wait for download to finish
    assert importer.scan_once() == 1
    imported = list(videos.glob("*.mp4"))
    assert len(imported) == 1
    assert imported[0].read_bytes() == source.read_bytes()
    assert source.exists()  # never delete or move the user's download
    assert importer.scan_once() == 0
    assert len(list(videos.glob("*.mp4"))) == 1


def test_flow_auto_import_rejects_invalid_video_and_retries(tmp_path):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    source = downloads / "not-a-video.mp4"
    source.write_bytes(b"not an mp4")

    def validator(_path):
        raise RenderFailed("Invalid MP4 container")

    importer = FlowAutoImporter(tmp_path / "data", tmp_path / "videos", [downloads], validator=validator)
    importer.scan_once()
    assert importer.scan_once() == 0
    assert importer.status()["skipped_or_invalid"] == 1
    assert not list((tmp_path / "videos").glob("*.mp4"))
    assert source.exists()


def test_flow_auto_import_ignores_non_mp4_and_symlink(tmp_path):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "notes.txt").write_text("ignore")
    target = downloads / "real.mp4"
    target.write_bytes(b"video")
    link = downloads / "linked.mp4"
    link.symlink_to(target)
    importer = FlowAutoImporter(tmp_path / "data", tmp_path / "videos", [downloads],
                                 validator=lambda _path: {})
    importer.scan_once()
    assert importer.scan_once() == 0
    assert not list((tmp_path / "videos").glob("*.mp4"))



def test_flow_auto_import_auto_renders_batch_after_quiet_period(tmp_path, monkeypatch):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "clip.mp4").write_bytes(b"valid")
    calls = []

    def validator(_path):
        return {"duration": 3}

    def renderer(items, title, scenes, **kwargs):
        calls.append((items, title, scenes, kwargs))
        return {"video_id": "final123", "url": "/api/videos/final123"}

    monkeypatch.setenv("SINTU_FLOW_AUTO_RENDER", "true")
    importer = FlowAutoImporter(tmp_path / "data", tmp_path / "videos",
                                [downloads], validator=validator, renderer=renderer)
    importer.scan_once()
    importer.scan_once()
    assert len(importer.pending) == 1
    result = importer.flush_pending(force=True)
    assert result["video_id"] == "final123"
    assert len(calls) == 1
    assert calls[0][0][0]["kind"] == "video"
    assert calls[0][2] == ["Google Flow video clip 1"]
    assert importer.pending == []
    assert importer.status()["last_render"]["video_id"] == "final123"


def test_flow_auto_render_can_be_disabled(tmp_path, monkeypatch):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "clip.mp4").write_bytes(b"valid")
    calls = []
    importer = FlowAutoImporter(
        tmp_path / "data", tmp_path / "videos", [downloads],
        validator=lambda _path: {"duration": 3},
        renderer=lambda *args, **kwargs: calls.append(args) or {"ok": True},
    )
    importer.scan_once()
    importer.scan_once()
    monkeypatch.setenv("SINTU_FLOW_AUTO_RENDER", "false")
    assert importer.flush_pending(force=True) is None
    assert not calls
    assert len(importer.pending) == 1


def test_flow_pending_queue_survives_importer_restart(tmp_path, monkeypatch):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "clip.mp4").write_bytes(b"valid")
    monkeypatch.setenv("SINTU_FLOW_AUTO_RENDER", "true")
    data = tmp_path / "data"
    videos = tmp_path / "videos"
    first = FlowAutoImporter(data, videos, [downloads], validator=lambda _p: {"duration": 3})
    first.scan_once()
    first.scan_once()
    queued_id = first.pending[0]
    assert (data / "flow_auto_pending.json").is_file()

    restarted = FlowAutoImporter(data, videos, [downloads], validator=lambda _p: {"duration": 3})
    assert restarted.pending == [queued_id]
    assert restarted.status()["pending_clips"] == 1


def test_flow_pending_queue_is_retained_after_render_failure_and_restart(tmp_path, monkeypatch):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "clip.mp4").write_bytes(b"valid")
    monkeypatch.setenv("SINTU_FLOW_AUTO_RENDER", "true")

    def broken_renderer(*_args, **_kwargs):
        raise RuntimeError("temporary encoder failure")

    data = tmp_path / "data"
    videos = tmp_path / "videos"
    importer = FlowAutoImporter(data, videos, [downloads],
                                validator=lambda _p: {"duration": 3}, renderer=broken_renderer)
    importer.scan_once()
    importer.scan_once()
    queued = list(importer.pending)
    assert importer.flush_pending(force=True) is None
    assert importer.pending == queued

    restarted = FlowAutoImporter(data, videos, [downloads],
                                 validator=lambda _p: {"duration": 3}, renderer=broken_renderer)
    assert restarted.pending == queued
    assert restarted.status()["last_render_error"] == ""


def test_flow_pending_queue_is_acknowledged_only_after_successful_render(tmp_path, monkeypatch):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "clip.mp4").write_bytes(b"valid")
    monkeypatch.setenv("SINTU_FLOW_AUTO_RENDER", "true")
    data = tmp_path / "data"
    videos = tmp_path / "videos"
    importer = FlowAutoImporter(
        data, videos, [downloads], validator=lambda _p: {"duration": 3},
        renderer=lambda *_args, **_kwargs: {"video_id": "rendered"},
    )
    importer.scan_once()
    importer.scan_once()
    assert importer.flush_pending(force=True) == {"video_id": "rendered"}
    assert importer.pending == []
    assert (data / "flow_auto_pending.json").read_text("utf-8") == "[]"


def test_flow_auto_import_deduplicates_identical_content_across_download_paths(tmp_path):
    import json

    downloads = tmp_path / "Download"
    downloads.mkdir()
    (downloads / "first.mp4").write_bytes(b"same verified payload")
    (downloads / "second.mp4").write_bytes(b"same verified payload")
    importer = FlowAutoImporter(
        tmp_path / "data", tmp_path / "videos", [downloads],
        validator=lambda _path: {"duration": 4},
    )
    assert importer.scan_once() == 0
    assert importer.scan_once() == 1
    assert len(list((tmp_path / "videos").glob("*.mp4"))) == 1
    assert importer.imported == 1
    assert importer.skipped == 1
    ledger = json.loads((tmp_path / "data" / "flow_auto_imported.json").read_text("utf-8"))
    records = list(ledger.values())
    assert sum(1 for record in records if isinstance(record, dict) and record.get("video_id")) == 1
    assert sum(1 for record in records if isinstance(record, dict) and record.get("duplicate_of")) == 1
    assert all(len(record["sha256"]) == 64 for record in records if isinstance(record, dict))


def test_flow_auto_import_reimports_changed_source_content(tmp_path):
    downloads = tmp_path / "Download"
    downloads.mkdir()
    source = downloads / "clip.mp4"
    source.write_bytes(b"first video")
    importer = FlowAutoImporter(
        tmp_path / "data", tmp_path / "videos", [downloads],
        validator=lambda _path: {"duration": 4},
    )
    importer.scan_once()
    assert importer.scan_once() == 1
    source.write_bytes(b"second and different video")
    assert importer.scan_once() == 0
    assert importer.scan_once() == 1
    assert len(list((tmp_path / "videos").glob("*.mp4"))) == 2
    assert len(importer.pending) == 2
