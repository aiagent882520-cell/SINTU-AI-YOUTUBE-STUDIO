from app import image_generator, video_generator


def test_image_status_exposes_safe_local_diagnostics(monkeypatch):
    monkeypatch.setattr(image_generator, "image_workflow_status", lambda: {
        "available": False,
        "workflow_configured": True,
        "server_reachable": True,
        "workflow_valid": True,
        "nodes_verified": True,
        "missing_nodes": ["CustomImageNode"],
        "missing_models": [{"node_type": "CheckpointLoaderSimple",
                            "input": "ckpt_name", "configured": "missing.safetensors"}],
        "reason": "Missing local workflow dependencies",
        "base_url": "http://127.0.0.1:8188",
        "workflow_path": "C:/private/workflow.json",
    })
    status = image_generator.image_status()
    assert status["local_diagnostics"]["missing_nodes"] == ["CustomImageNode"]
    assert status["local_diagnostics"]["missing_models"][0]["configured"] == "missing.safetensors"
    assert "base_url" not in status["local_diagnostics"]
    assert "workflow_path" not in status["local_diagnostics"]


def test_video_status_exposes_safe_local_diagnostics(monkeypatch):
    monkeypatch.setattr(video_generator, "video_workflow_status", lambda: {
        "available": False,
        "workflow_configured": True,
        "server_reachable": True,
        "workflow_valid": True,
        "nodes_verified": True,
        "missing_nodes": [],
        "missing_models": [{"node_type": "VideoModelLoader",
                            "input": "model", "configured": "missing-video-model.safetensors"}],
        "reason": "Missing local model",
        "base_url": "http://127.0.0.1:8188",
        "workflow_path": "C:/private/video.json",
    })
    status = video_generator.video_status()
    assert status["local_diagnostics"]["missing_models"][0]["configured"] == "missing-video-model.safetensors"
    assert "base_url" not in status["local_diagnostics"]
    assert "workflow_path" not in status["local_diagnostics"]
