from app import video_generator


def test_store_video_atomically_writes_final_mp4(tmp_path, monkeypatch):
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", tmp_path)
    video_id, output = video_generator._store_video_atomically(b"validated-mp4")
    assert output == tmp_path / f"{video_id}.mp4"
    assert output.read_bytes() == b"validated-mp4"
    assert len(list(tmp_path.glob("*.mp4"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_store_video_atomically_cleans_partial_file_on_replace_error(tmp_path, monkeypatch):
    monkeypatch.setattr(video_generator, "AI_VIDEO_DIR", tmp_path)

    def fail_replace(source, destination):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(video_generator.os, "replace", fail_replace)
    try:
        video_generator._store_video_atomically(b"validated-mp4")
    except video_generator.VideoGenerationFailed as exc:
        assert "safely save" in str(exc)
    else:
        raise AssertionError("Expected a safe storage failure")
    assert list(tmp_path.iterdir()) == []
