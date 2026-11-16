from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "operational_readiness", Path(__file__).resolve().parents[1] / "scripts" / "operational_readiness.py"
)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(doctor)


def test_env_parser_ignores_comments_and_splits_only_first_equals(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# ignored\nTOKEN=a=b=c\nEMPTY=\n", encoding="utf-8")
    assert doctor.read_env(path) == {"TOKEN": "a=b=c", "EMPTY": ""}


def test_report_never_exposes_secret_values(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/" + name)
    (tmp_path / "app" / "static").mkdir(parents=True)
    (tmp_path / "app" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "app" / "static" / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "app" / "static" / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "SINTU_ADMIN_PASSWORD=SUPER_SECRET_PASSWORD_VALUE\n"
        "SINTU_SESSION_SECRET=SUPER_SECRET_SESSION_VALUE_12345678901234567890\n"
        "SINTU_BRIDGE_TOKEN=SUPER_SECRET_BRIDGE_TOKEN_VALUE_12345678901234567890\n"
        "SINTU_BRIDGE_WORKER_TOKEN=SUPER_SECRET_WORKER_TOKEN_VALUE_12345678901234567890\n",
        encoding="utf-8",
    )
    report = doctor.build_report(tmp_path, env={}, check_network=False)
    rendered = __import__("json").dumps(report)
    assert "SUPER_SECRET" not in rendered
    assert report["ready"] is True
    assert report["summary"]["warnings"] >= 1


def test_missing_required_configuration_fails_closed(tmp_path):
    report = doctor.build_report(tmp_path, env={}, check_network=False)
    assert report["ready"] is False
    assert "repository" in report["failed_checks"]
    assert "private_environment" in report["failed_checks"]
