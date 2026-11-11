from app import comfyui_client

def test_comfyui_placeholder_replacement_supports_nested_workflows():
    workflow = {"6":{"inputs":{"text":"__SINTU_PROMPT__","negative":"__SINTU_NEGATIVE__","width":"__SINTU_WIDTH__","height":"__SINTU_HEIGHT__","seed":"__SINTU_SEED__"}}}
    result = comfyui_client._replace_placeholders(workflow, "A cinematic scene", "watermark", 720, 1280, 12345)
    assert result["6"]["inputs"] == {"text":"A cinematic scene","negative":"watermark","width":720,"height":1280,"seed":12345}

def test_comfyui_image_and_video_workflow_status_is_local_and_configured(tmp_path, monkeypatch):
    image_workflow = tmp_path / "image.json"
    video_workflow = tmp_path / "video.json"
    image_workflow.write_text("{}", encoding="utf-8")
    video_workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(image_workflow))
    monkeypatch.setenv("COMFYUI_VIDEO_WORKFLOW_PATH", str(video_workflow))
    assert comfyui_client.image_workflow_status()["available"] is True
    assert comfyui_client.video_workflow_status()["available"] is True

def test_comfyui_rejects_non_loopback_server(tmp_path, monkeypatch):
    workflow = tmp_path / "image.json"
    workflow.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("COMFYUI_BASE_URL", "https://example.com")
    monkeypatch.setenv("COMFYUI_IMAGE_WORKFLOW_PATH", str(workflow))
    status = comfyui_client.image_workflow_status()
    assert status["available"] is False
    assert "loopback" in status["reason"]
