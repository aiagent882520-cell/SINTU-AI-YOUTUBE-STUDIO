from scripts import android_device_diagnostic as diagnostic


def test_backend_health_blocks_remote_plain_http_and_embedded_credentials():
    assert diagnostic.backend_health("http://studio.example.com")["status"] == "BLOCKED"
    assert diagnostic.backend_health("https://user:pass@studio.example.com")["status"] == "BLOCKED"


def test_backend_health_allows_loopback_http_and_remote_https(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    requested = []
    monkeypatch.setattr(diagnostic.urllib.request, "urlopen",
                        lambda request, timeout: (requested.append(request.full_url) or Response()))
    assert diagnostic.backend_health("http://127.0.0.1:8000")["status"] == "PASS"
    assert diagnostic.backend_health("https://studio.example.com/sintu")["status"] == "PASS"
    assert requested == [
        "http://127.0.0.1:8000/api/health",
        "https://studio.example.com/sintu/api/health",
    ]


def test_collect_report_marks_unavailable_package_manager_as_unknown(monkeypatch):
    monkeypatch.setattr(diagnostic.shutil, "which", lambda name: None)
    monkeypatch.setattr(diagnostic, "command_output",
                        lambda command, timeout=3: {"exit_code": None, "output": "unavailable"})
    monkeypatch.setattr(diagnostic, "memory_available_mb", lambda: None)
    monkeypatch.setattr(diagnostic, "backend_health",
                        lambda url: {"status": "UNREACHABLE"})
    report = diagnostic.collect_report("http://127.0.0.1:8000")
    assert report["native_app_packages"] == {
        "com.sintu.studio": None,
        "com.sintu.studio.debug": None,
    }
    assert all(not item["available"] for item in report["binaries"].values())
    assert report["backend_health"]["status"] == "UNREACHABLE"
    assert any("Does not submit credentials" in item for item in report["limitations"])
