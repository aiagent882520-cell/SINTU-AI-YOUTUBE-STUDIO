import io
import json

import pytest
from PIL import Image

from app import commons_image_source as commons, image_generator


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (128, 128), "slateblue").save(output, format="JPEG")
    return output.getvalue()


def test_commons_image_requires_explicit_reusable_licence_and_records_attribution(monkeypatch):
    metadata = {
        "LicenseShortName": {"value": "CC BY-SA 4.0"},
        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
        "Artist": {"value": "<a>Photographer</a>"},
        "Credit": {"value": "Wikimedia Commons"},
        "AttributionRequired": {"value": "true"},
    }
    payload = {
        "query": {"pages": [
            {"title": "File:Unlicensed.jpg", "imageinfo": [{"url": "https://upload.wikimedia.org/unlicensed.jpg", "extmetadata": {}}]},
            {"title": "File:Fort.jpg", "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/fort-thumb.jpg",
                "extmetadata": metadata,
            }]},
        ]}
    }
    calls = []
    def fake_request(url, **kwargs):
        calls.append(url)
        return json.dumps(payload).encode() if len(calls) == 1 else image_bytes()
    monkeypatch.setattr(commons, "_request", fake_request)

    raw, source = commons.fetch_documentary_image("Historic Indian fort sandstone walls")

    assert raw.startswith(b"\xff\xd8\xff")
    assert source["provider"] == "Wikimedia Commons"
    assert source["license"] == "CC BY-SA 4.0"
    assert source["artist"] == "Photographer"
    assert source["attribution_required"] is True
    assert "Fort.jpg" in source["source_url"]
    assert len(calls) == 2


def test_commons_rejects_non_commons_image_hosts(monkeypatch):
    payload = {"query": {"pages": [{
        "title": "File:Fort.jpg",
        "imageinfo": [{
            "url": "https://example.invalid/fort.jpg",
            "extmetadata": {"LicenseShortName": {"value": "Public domain"}},
        }],
    }]}}
    monkeypatch.setattr(commons, "_request", lambda url, **kwargs: json.dumps(payload).encode())
    with pytest.raises(commons.CommonsImageUnavailable, match="No matching Commons image"):
        commons.fetch_documentary_image("historic fort")


def test_commons_rejects_empty_search_query():
    with pytest.raises(commons.CommonsImageUnavailable, match="too short"):
        commons.fetch_documentary_image("  ")


def test_commons_request_rejects_redirect_to_untrusted_host(monkeypatch):
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def geturl(self):
            return "https://example.invalid/image.jpg"
        def read(self, limit):
            return b"image"
    monkeypatch.setattr(commons.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(commons.CommonsImageUnavailable, match="untrusted host"):
        commons._request("https://upload.wikimedia.org/image.jpg")



def test_documentary_scene_uses_commons_photo_and_writes_provenance(tmp_path, monkeypatch):
    source = {
        "provider": "Wikimedia Commons",
        "title": "File:Historic Fort.jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Historic_Fort.jpg",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "artist": "Photographer",
        "credit": "Wikimedia Commons",
        "attribution_required": True,
        "search_query": "historic Indian fort",
    }
    monkeypatch.setenv("SINTU_DOCUMENTARY_IMAGE_SOURCE", "wikimedia")
    monkeypatch.setattr(image_generator, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(image_generator, "image_workflow_status", lambda: {
        "available": False, "workflow_configured": False, "server_reachable": False,
        "workflow_valid": False, "nodes_verified": False, "missing_nodes": [],
        "missing_models": [], "reason": "ComfyUI not configured",
    })
    monkeypatch.setattr(image_generator, "fetch_documentary_image", lambda prompt: (image_bytes(), source))

    result = image_generator.generate_image("Historic Indian fort with sandstone ramparts", kind="scene")

    assert result["provider"] == "Wikimedia Commons (licensed real photograph)"
    assert result["source"]["license"] == "CC BY-SA 4.0"
    saved = tmp_path / (result["image_id"] + ".source.json")
    assert saved.is_file()
    assert json.loads(saved.read_text(encoding="utf-8"))["source"]["artist"] == "Photographer"


@pytest.mark.parametrize("licence", [
    "CC BY 4.0", "CC BY-SA 4.0", "CC0 1.0", "Public domain", "PD-US",
])
def test_commons_accepts_commercially_reusable_adaptable_licences(licence):
    assert commons._is_reusable_license(licence)


@pytest.mark.parametrize("licence", [
    "CC BY-NC 4.0", "CC BY-NC-SA 4.0", "CC BY-ND 4.0",
    "CC BY-NC-ND 4.0", "All rights reserved", "GPL",
])
def test_commons_rejects_noncommercial_no_derivatives_and_unknown_licences(licence):
    assert not commons._is_reusable_license(licence)
