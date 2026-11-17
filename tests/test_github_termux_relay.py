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


def test_relay_rejects_unbounded_or_invalid_topics():
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



def test_relay_rejects_payload_fields_for_wrong_action():
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
