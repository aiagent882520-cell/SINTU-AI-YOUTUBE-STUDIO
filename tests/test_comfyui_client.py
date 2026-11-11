import json

from app import comfyui_client


def api_workflow():
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "model.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {
            "text": "__SINTU_PROMPT__", "clip": ["1", 1],
            "width": "__SINTU_WIDTH__", "height": "__SINTU_HEIGHT__",
            "frames": "__SINTU_FRAMES__", "fps": "__SINTU_FPS__",
        }},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
    }


def mock_comfy_request(url, data=None, timeout=30):
    if url.endswith("/system_stats"):
        return b'{"system":{}}'
    return b'{"CheckpointLoaderSimple": {}, "CLIPTextEncode": {}, "SaveImage": {}}'


def test_comfyui_placeholder_replacement_supports_nested_workflows():
    workflow = {"6": {"inputs": {"text": "__SINTU_PROMPT__", "negative": "__SINTU_NEGATIVE__",
                                 "width": "__SINTU_WIDTH__", "height": "__SINTU_HEIGHT__",
                                 "seed": "__SINTU_SEED__"}}}
    result = comfyui_client._replace_placeholders(workflow, "A cinematic scene", "watermark", 720, 1280, 12345)
    assert result["6"]["inputs"] == {"text": "A cinematic scene", "negative": "watermark",
                                     "width": 720, "height": 1280, "seed": 12345}


def test_comfyui_workflow_status_checks_live_server_and_installed_nodes(tmp_path, monkeypatch):
    image_workflow = tmp_path / "image.json"
    video_workflow = tmp_path / "video.json"
    image_workflow.write_text(json.dumps(api_workflow()), encoding="utf-8")
    video_workflow.write_text(json.dumps(api_workflow()), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(image_workflow))
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(video_workflow))
    monkeypatch.setattr(comfyui_client, "_request", mock_comfy_request)
    image_status = comfyui_client.image_workflow_status()
    video_status = comfyui_client.video_workflow_status()
    assert image_status["available"] is True
    assert image_status["server_reachable"] is True
    assert image_status["workflow_valid"] is True
    assert video_status["available"] is True
    assert video_status["nodes_verified"] is True
    assert video_status["missing_nodes"] == []


def test_comfyui_reports_missing_custom_nodes(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    data = api_workflow()
    data["4"] = {"class_type": "VHS_VideoCombine", "inputs": {"images": ["3", 0]}}
    workflow.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(workflow))
    monkeypatch.setattr(comfyui_client, "_request", mock_comfy_request)
    status = comfyui_client.video_workflow_status()
    assert status["server_reachable"] is True
    assert status["nodes_verified"] is True
    assert status["missing_nodes"] == ["VHS_VideoCombine"]
    assert status["available"] is False
    assert "VHS_VideoCombine" in status["reason"]


def test_comfyui_reports_server_unavailable_even_when_workflow_is_valid(tmp_path, monkeypatch):
    workflow = tmp_path / "image.json"
    workflow.write_text(json.dumps(api_workflow()), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(workflow))
    def unavailable(*args, **kwargs):
        raise TimeoutError("offline")
    monkeypatch.setattr(comfyui_client, "_request", unavailable)
    status = comfyui_client.image_workflow_status()
    assert status["workflow_configured"] is True
    assert status["workflow_valid"] is True
    assert status["server_reachable"] is False
    assert status["available"] is False
    assert "did not respond" in status["reason"]


def test_comfyui_rejects_invalid_workflow_nodes(tmp_path, monkeypatch):
    workflow = tmp_path / "image.json"
    workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(workflow))
    status = comfyui_client.image_workflow_status()
    assert status["available"] is False
    assert status["workflow_valid"] is False
    assert "non-empty" in status["reason"]


def test_comfyui_rejects_non_loopback_server(tmp_path, monkeypatch):
    workflow = tmp_path / "image.json"
    workflow.write_text(json.dumps(api_workflow()), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "https://example.com")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(workflow))
    status = comfyui_client.image_workflow_status()
    assert status["available"] is False
    assert "localhost" in status["reason"]


def test_comfyui_allows_docker_host_bridge_for_local_service(tmp_path, monkeypatch):
    workflow = tmp_path / "image.json"
    workflow.write_text(json.dumps(api_workflow()), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://host.docker.internal:8188")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(workflow))
    monkeypatch.setattr(comfyui_client, "_request", mock_comfy_request)
    assert comfyui_client.image_workflow_status()["available"] is True


def test_comfyui_video_workflow_requires_frame_and_fps_placeholders(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    data = api_workflow()
    del data["2"]["inputs"]["frames"]
    del data["2"]["inputs"]["fps"]
    workflow.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(workflow))
    status = comfyui_client.video_workflow_status()
    assert status["available"] is False
    assert "__SINTU_FRAMES__" in status["reason"]
    assert "__SINTU_FPS__" in status["reason"]


def test_comfyui_video_output_finds_mp4_and_webm_metadata():
    entry = {"outputs": {
        "12": {"gifs": [
            {"filename": "preview.gif", "subfolder": "clips", "type": "output"},
            {"filename": "final.mp4", "subfolder": "clips", "type": "output"},
        ]},
        "13": {"videos": [{"filename": "alternate.webm", "type": "output"}]},
    }}
    items = comfyui_client._video_output_items(entry)
    assert [item["filename"] for item in items] == ["preview.gif", "final.mp4", "alternate.webm"]
    assert next(item for item in items if item["filename"] == "final.mp4")["subfolder"] == "clips"


def test_comfyui_video_output_ignores_malformed_nodes_and_entries():
    entry = {"outputs": {
        "1": None,
        "2": {"gifs": "not-a-list", "videos": [None, "clip.mp4", {"filename": 42}]},
    }}
    assert comfyui_client._video_output_items(entry) == []


def test_comfyui_video_history_error_extracts_execution_failure():
    entry = {"status": {"messages": [
        ["execution_start", {}],
        ["execution_error", {"exception_message": "Missing model weights"}],
    ]}}
    assert comfyui_client._video_history_error(entry) == "Missing model weights"


def test_comfyui_video_history_without_failure_returns_none():
    assert comfyui_client._video_history_error({"status": {"messages": [["execution_success", {}]]}}) is None


def test_comfyui_video_generation_polls_history_and_downloads_mp4(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "TextEncode", "inputs": {"text": "__SINTU_PROMPT__"}},
        "2": {"class_type": "VideoSampler", "inputs": {
            "width": "__SINTU_WIDTH__", "height": "__SINTU_HEIGHT__",
            "length": "__SINTU_FRAMES__", "fps": "__SINTU_FPS__",
        }},
    }), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(workflow))
    monkeypatch.setattr(comfyui_client, "video_workflow_status", lambda: {
        "available": True, "base_url": "http://127.0.0.1:8188"
    })
    monkeypatch.setattr(comfyui_client.time, "sleep", lambda *_: None)
    calls = []
    def fake_request(url, data=None, timeout=30):
        calls.append(url)
        if url.endswith("/prompt"):
            return b'{"prompt_id":"job-123"}'
        if "/history/" in url:
            return json.dumps({"job-123": {"outputs": {
                "9": {"gifs": [{"filename": "final.mp4", "subfolder": "sintu", "type": "output"}]}
            }}}).encode()
        if "/view?" in url:
            return b"fake-mp4-bytes"
        raise AssertionError("Unexpected ComfyUI URL: " + url)
    monkeypatch.setattr(comfyui_client, "_request", fake_request)
    result = comfyui_client.generate_video_bytes("A moving scene", 720, 1280, 96, 24, timeout_seconds=5)
    assert result == b"fake-mp4-bytes"
    assert any("/history/job-123" in url for url in calls)
    assert any("/view?" in url and "final.mp4" in url for url in calls)


def test_comfyui_video_generation_stops_on_history_execution_error(tmp_path, monkeypatch):
    workflow = tmp_path / "video.json"
    workflow.write_text(json.dumps({
        "1": {"class_type": "TextEncode", "inputs": {"text": "__SINTU_PROMPT__"}},
        "2": {"class_type": "VideoSampler", "inputs": {
            "width": "__SINTU_WIDTH__", "height": "__SINTU_HEIGHT__",
            "length": "__SINTU_FRAMES__", "fps": "__SINTU_FPS__",
        }},
    }), encoding="utf-8")
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(workflow))
    monkeypatch.setattr(comfyui_client, "video_workflow_status", lambda: {
        "available": True, "base_url": "http://127.0.0.1:8188"
    })
    monkeypatch.setattr(comfyui_client.time, "sleep", lambda *_: None)
    def fake_request(url, data=None, timeout=30):
        if url.endswith("/prompt"):
            return b'{"prompt_id":"job-err"}'
        if "/history/" in url:
            return json.dumps({"job-err": {"status": {"messages": [
                ["execution_error", {"exception_message": "Missing video model"}]
            ]}, "outputs": {}}}).encode()
        raise AssertionError("Failed execution must not request an output file")
    monkeypatch.setattr(comfyui_client, "_request", fake_request)
    try:
        comfyui_client.generate_video_bytes("A moving scene", 720, 1280, 96, 24, timeout_seconds=5)
        assert False, "Expected workflow execution failure"
    except comfyui_client.ComfyUIUnavailable as exc:
        assert "Missing video model" in str(exc)


def test_comfyui_detects_missing_checkpoint_from_object_info():
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "missing-model.safetensors"}}
    }
    object_info = {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": ["COMBO", {"options": ["available-model.safetensors"]}]}}
        }
    }
    missing = comfyui_client._missing_model_files(workflow, object_info)
    assert missing == [{
        "node_id": "1", "node_type": "CheckpointLoaderSimple",
        "input": "ckpt_name", "configured": "missing-model.safetensors"
    }]


def test_comfyui_accepts_installed_checkpoint_from_object_info():
    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "available-model.safetensors"}}
    }
    object_info = {
        "CheckpointLoaderSimple": {
            "input": {"required": {"ckpt_name": ["COMBO", {"options": ["available-model.safetensors"]}]}}
        }
    }
    assert comfyui_client._missing_model_files(workflow, object_info) == []
