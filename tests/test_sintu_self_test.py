from types import SimpleNamespace

from scripts import sintu_self_test


def test_self_test_runs_readiness_tests_offline_video_and_media_audit(tmp_path, monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if "operational_readiness.py" in command:
            return SimpleNamespace(returncode=0, stdout='{"status":"PASS","checks":[{"name":"ffmpeg","status":"ok"}]}', stderr='')
        if "live_e2e.py" in command:
            return SimpleNamespace(returncode=0, stdout='{"status":"PASS","duration_seconds":32}', stderr='')
        if "project_health_audit.py" in command:
            report_path = command[command.index("--report") + 1]
            with open(report_path, "w", encoding="utf-8") as handle:
                handle.write('{"status":"PASS","checks":[{"name":"motion","motion_ratio":0.74}]}')
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout='private output should not be saved', stderr='')

    monkeypatch.setattr(sintu_self_test.subprocess, "run", fake_run)
    report = sintu_self_test.run_self_test(data_dir=tmp_path, topic="भारत के किले")

    assert report["status"] == "PASS"
    assert [step["name"] for step in report["steps"]] == [
        "operational_readiness", "pytest", "offline_video_e2e", "media_quality_audit"
    ]
    assert len(commands) == 4
    assert commands[2][-2:] == ["--topic", "भारत के किले"]
    assert report["readiness_details"]["status"] == "PASS"
    assert report["offline_video_details"]["duration_seconds"] == 32
    assert report["media_audit"]["checks"][0]["motion_ratio"] == 0.74
    saved = (tmp_path / "sintu_self_test_report.json").read_text("utf-8")
    assert "private output" not in saved
    assert report["paid_services_used"] is False
    assert report["publishing_performed"] is False


def test_self_test_continues_after_a_failed_phase_and_returns_failure(tmp_path, monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        code = 1 if "-m" in command and "pytest" in command else 0
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    monkeypatch.setattr(sintu_self_test.subprocess, "run", fake_run)
    report = sintu_self_test.run_self_test(data_dir=tmp_path)

    assert report["status"] == "FAIL"
    assert report["failed_steps"] == ["pytest"]
    assert len(commands) == 4
    assert commands[-1][1:3] == ["scripts/project_health_audit.py", "--skip-tests"]


def test_self_test_skip_options_do_not_launch_tests_or_video(tmp_path, monkeypatch):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sintu_self_test.subprocess, "run", fake_run)
    report = sintu_self_test.run_self_test(
        data_dir=tmp_path, skip_tests=True, skip_video=True
    )

    assert report["status"] == "PASS"
    assert [step["status"] for step in report["steps"]] == [
        "passed", "skipped", "skipped", "passed"
    ]
    assert len(commands) == 2
