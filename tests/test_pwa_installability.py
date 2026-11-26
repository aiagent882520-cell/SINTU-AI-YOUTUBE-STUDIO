"""PWA installability and offline shell asset contract."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"


def test_manifest_declares_sintu_install_identity_and_scalable_icons():
    manifest = json.loads((STATIC / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "SINTU AI YOUTUBE STUDIO"
    assert manifest["short_name"] == "SINTU AI"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["theme_color"] == "#101827"
    icons = manifest["icons"]
    assert any(icon["src"] == "/static/icon.svg" and icon["sizes"] == "any" for icon in icons)
    assert any(icon["src"] == "/static/icon.svg" and "maskable" in icon["purpose"] for icon in icons)
    assert (STATIC / "icon.svg").is_file()


def test_service_worker_precaches_brand_and_login_shell_without_private_dashboard():
    worker = (STATIC / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"const APP_SHELL = \[(.*?)\];", worker, re.S)
    assert shell, "Service worker must declare a deterministic app shell."
    assets = re.findall(r'"([^"]+)"', shell.group(1))
    assert "/login" in assets
    assert "/static/manifest.json" in assets
    assert "/static/icon.svg" in assets
    assert "/static/brand-logo.svg" in assets
    assert "/static/login.js" in assets
    assert "/" not in assets, "Authenticated dashboard HTML must not be precached."
    assert "if (url.pathname.startsWith(\"/api/\")) return;" in worker
    assert "caches.delete(key)" in worker


def test_offline_fallback_explains_private_dashboard_is_not_cached():
    offline = (STATIC / "offline.html").read_text(encoding="utf-8")
    assert "private dashboard" in offline
    assert "internet connection" in offline