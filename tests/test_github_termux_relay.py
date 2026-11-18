import importlib.util
from pathlib import Path

import pytest
from datetime import datetime, timedelta, timezone


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "github_termux_relay", ROOT / "scripts" / "github_termux_relay.py"
)
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)


def test_relay_accepts_only_allowlisted_fixed_commands(monkeypatch):
    monkeypatch.setattr(relay, "AUTOMATION_ONLY", False)
    assert relay.command_for("git_status", []) == ["git", "status", "--short", "--branch"]
    assert relay.command_for("engine_probe", {})[-1:] == ["scripts/engine_probe.py"]
    assert relay.command_for("safe_optional_install", {}) == ["bash", "scripts/termux_safe_optional_install.sh"]
    assert relay.command_for("operational_readiness", {})[-2:] == [
        "scripts/operational_readiness.py", "--json"
    ]
    assert relay.command_for("full_self_test", {"topic": "नमस्ते"})[-2:] == [
        "--topic", "नमस्ते"
    ]
    assert relay.command_for("full_studio_e2e", {"topic": "भारत"})[-2:] == [
        "--topic", "भारत"
    ]
    assert relay.command_for("full_studio_e2e", {})[-2:] == [
        "--topic", "भारत के प्राचीन किले में सुबह का सिनेमाई दृश्य"
    ]


@pytest.mark.parametrize("action", ["shell", "exec", "bash", "python -c", ""])
def test_relay_rejects_arbitrary_actions(action):
    with pytest.raises(ValueError, match="allowlist"):
        relay.command_for(action, {})


@pytest.mark.parametrize("test_path", [
    "/tmp/evil.py", "../evil.py", "tests/../evil.py",
    "app/main.py", "tests/subdir/test.py", "tests/not-real.py",
])
def test_relay_rejects_unapproved_test_paths(test_path):
    with pytest.raises(ValueError, match="test_path"):
        relay.command_for("run_tests", {"test_path": test_path})


def test_relay_rejects_unbounded_or_invalid_topics(monkeypatch):
    monkeypatch.setattr(relay, "AUTOMATION_ONLY", False)
    with pytest.raises(ValueError, match="topic"):
        relay.command_for("offline_video_e2e", {"topic": "x" * 301})
    with pytest.raises(ValueError, match="topic"):
        relay.command_for("full_self_test", {"topic": "   "})
    with pytest.raises(ValueError, match="topic"):
        relay.command_for("full_studio_e2e", {"topic": "x" * 301})



def test_relay_rejects_extra_payload_fields():
    issue_body = {"action": "git_status", "command": "rm -rf /"}
    assert set(issue_body) - {"action", "topic", "test_path"} == {"command"}


def test_relay_repository_and_actor_are_scoped_to_project_owner():
    assert relay.REPOSITORY == "aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO"
    assert relay.ALLOWED_ACTOR == "aiagent882520-cell"



def test_relay_requeues_stale_claim_after_worker_crash():
    class FakeGitHub(relay.GitHub):
        def __init__(self):
            self.updates = []
            self.comments = []

        def request(self, method, path, payload=None):
            if method == "GET" and "labels=sintu-command-running" in path:
                stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                return [{
                    "number": 42,
                    "title": "SINTU-CMD: full_self_test",
                    "updated_at": stale,
                    "user": {"login": relay.ALLOWED_ACTOR},
                }]
            if method == "GET" and "labels=sintu-command-queued" in path:
                return [{
                    "number": 42,
                    "title": "SINTU-CMD: full_self_test",
                    "user": {"login": relay.ALLOWED_ACTOR},
                }]
            raise AssertionError(f"Unexpected GitHub API request: {method} {path}")

        def update_issue(self, number, **fields):
            self.updates.append((number, fields))

        def comment(self, number, body):
            self.comments.append((number, body))

    github = FakeGitHub()
    pending = github.pending()
    assert [issue["number"] for issue in pending] == [42]
    assert github.updates == [(42, {"labels": [relay.QUEUED_LABEL]})]
    assert "Recovered stale claim" in github.comments[0][1]



def test_relay_rejects_payload_fields_for_wrong_action(monkeypatch):
    monkeypatch.setattr(relay, "AUTOMATION_ONLY", False)
    with pytest.raises(ValueError, match="Payload fields"):
        relay.command_for("git_status", {"topic": "ignored"})
    with pytest.raises(ValueError, match="Payload fields"):
        relay.command_for("run_tests", {"topic": "wrong-field"})
    with pytest.raises(ValueError, match="Payload fields"):
        relay.command_for("offline_video_e2e", {"test_path": "tests/test_ai_brain.py"})


def test_relay_pauses_video_production_in_automation_only_mode(monkeypatch):
    monkeypatch.setattr(relay, "AUTOMATION_ONLY", True)
    for action in ("offline_video_e2e", "full_self_test", "full_studio_e2e"):
        with pytest.raises(ValueError, match="paused"):
            relay.command_for(action, {})


def test_relay_maps_device_maintenance_actions_to_fixed_commands(monkeypatch):
    monkeypatch.setattr(relay, "AUTOMATION_ONLY", True)
    assert relay.command_for("restart_services", {}) == ["bash", "scripts/start_services.sh"]
    assert relay.command_for("media_repair", {}) == [
        relay.PYTHON, "scripts/repair_media.py", "--apply", "--json"
    ]


def test_relay_does_not_expose_public_youtube_publish_as_a_worker_action():
    import pytest
    with pytest.raises(ValueError, match="allowlist"):
        relay.command_for("youtube_publish", {})


def test_relay_maps_read_only_media_forensics_to_fixed_script():
    assert relay.command_for("media_forensics", {}) == [
        relay.PYTHON, "scripts/media_forensics.py", "--json"
    ]


def test_relay_maps_watchdog_recovery_test_to_fixed_script():
    assert relay.command_for("watchdog_recovery_test", {}) == [
        relay.PYTHON, "scripts/watchdog_recovery_test.py", "--json"
    ]


def test_relay_defers_restart_until_other_queued_jobs_are_drained(monkeypatch):
    processed = []

    def fake_process_issue(github, issue):
        processed.append(issue["number"])
        return issue["number"] == 1

    monkeypatch.setattr(relay, "process_issue", fake_process_issue)
    issues = [
        {"number": 1, "body": '{"action":"restart_services"}'},
        {"number": 2, "body": '{"action":"run_tests"}'},
        {"number": 3, "body": '{"action":"media_forensics"}'},
    ]

    assert relay.process_pending(None, issues) is True
    assert processed == [2, 3, 1]


def test_relay_exits_after_scheduled_restart_when_result_ack_fails(monkeypatch):
    import subprocess

    class BrokenGitHub:
        def update_issue(self, number, **fields):
            if fields.get("labels") == [relay.RUNNING_LABEL]:
                return
            raise RuntimeError("temporary GitHub outage")

        def comment(self, number, body):
            if body.startswith("🤖"):
                return
            raise RuntimeError("temporary GitHub outage")

    monkeypatch.setattr(
        relay.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "restart scheduled", ""),
    )
    issue = {"number": 77, "body": '{"action":"restart_services"}'}

    assert relay.process_issue(BrokenGitHub(), issue) is True


def test_relay_returns_queued_jobs_in_oldest_first_order():
    class FakeGitHub(relay.GitHub):
        def __init__(self):
            self.urls = []

        def request(self, method, path, payload=None):
            self.urls.append(path)
            if "labels=sintu-command-running" in path:
                return []
            if "labels=sintu-command-queued" in path:
                # Simulate GitHub's default newest-first API response.
                return [
                    {"number": 140, "created_at": "2026-11-18T09:54:20Z",
                     "title": "SINTU-CMD: media_forensics",
                     "user": {"login": relay.ALLOWED_ACTOR}},
                    {"number": 139, "created_at": "2026-11-18T09:53:35Z",
                     "title": "SINTU-CMD: run_tests",
                     "user": {"login": relay.ALLOWED_ACTOR}},
                    {"number": 137, "created_at": "2026-11-18T09:53:26Z",
                     "title": "SINTU-CMD: git_pull_ff_only",
                     "user": {"login": relay.ALLOWED_ACTOR}},
                ]
            raise AssertionError(f"Unexpected request: {method} {path}")

    github = FakeGitHub()
    pending = github.pending()
    assert [issue["number"] for issue in pending] == [137, 139, 140]
    queued_url = next(url for url in github.urls if "labels=sintu-command-queued" in url)
    assert "sort=created" in queued_url
    assert "direction=asc" in queued_url


def test_relay_preserves_compact_forensic_footer_with_20k_output_limit(monkeypatch):
    import subprocess

    class FakeGitHub:
        def __init__(self):
            self.comments = []
            self.updates = []

        def update_issue(self, number, **fields):
            self.updates.append((number, fields))

        def comment(self, number, body):
            self.comments.append(body)

    footer = "SINTU_FORENSICS_SUMMARY={\"status\":\"READ_ONLY_FORENSICS\"}"
    stdout = ("x" * 9000) + footer
    monkeypatch.setattr(
        relay.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout, ""),
    )
    github = FakeGitHub()
    issue = {"number": 145, "body": '{"action":"git_status"}'}
    assert relay.process_issue(github, issue) is False
    assert footer in github.comments[-1]
    assert len(github.comments[-1]) > 9000
