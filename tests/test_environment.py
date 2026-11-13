from app.main import _load_project_environment


def test_project_environment_loads_local_env_without_overriding_process_values(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SINTU_TEST_LOCAL_ENV=loaded-from-file\nSINTU_TEST_PRECEDENCE=file-value\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("SINTU_TEST_LOCAL_ENV", raising=False)
    monkeypatch.setenv("SINTU_TEST_PRECEDENCE", "process-value")

    assert _load_project_environment(env_file) is True
    assert __import__("os").environ["SINTU_TEST_LOCAL_ENV"] == "loaded-from-file"
    assert __import__("os").environ["SINTU_TEST_PRECEDENCE"] == "process-value"
