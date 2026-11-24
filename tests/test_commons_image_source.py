import io
import json

import pytest
from PIL import Image

from app import commons_image_source as commons


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
