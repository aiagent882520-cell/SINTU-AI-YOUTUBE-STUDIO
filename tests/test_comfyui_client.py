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
