"""Verify the explicit ComfyUI CPU fallback launcher without requiring a GPU host."""
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "start_comfyui_cpu.sh"


def _fake_comfy_host(tmp_path, torch_info):
    comfy_root = tmp_path / "ComfyUI"
    comfy_root.mkdir()
    (comfy_root / "main.py").write_text("# fake host entrypoint\n", encoding="utf-8")
    fake_python = tmp_path / "fake-python"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"-c\" ]]; then\n"
        "  printf '%s\\n' \"$FAKE_TORCH_INFO\"\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' \"$@\" > \"$COMFY_ARGS_FILE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    args_file = tmp_path / "comfy-args.txt"
    env = {
        **os.environ,
        "COMFYUI_ROOT": str(comfy_root),
        "COMFYUI_PYTHON": str(fake_python),
        "COMFYUI_DEVICE": "cpu",
        "COMFYUI_LISTEN": "127.0.0.1",
        "COMFYUI_PORT": "8188",
        "FAKE_TORCH_INFO": torch_info,
        "COMFY_ARGS_FILE": str(args_file),
    }
    return env, args_file


def test_cpu_launcher_starts_existing_checkout_with_explicit_cpu_flag(tmp_path):
    env, args_file = _fake_comfy_host(
        tmp_path, "torch=2.6.0\\ncuda=True\\nmps=False"
    )
    result = subprocess.run(
        ["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "main.py", "--listen", "127.0.0.1", "--port", "8188", "--cpu"
    ]
    assert "cuda=True" in result.stdout


@pytest.mark.parametrize(
    "torch_info,expected_cpu",
    [
        ("torch=2.6.0\\ncuda=False\\nmps=False", True),
        ("torch=2.6.0\\ncuda=True\\nmps=False", False),
        ("torch=2.6.0\\ncuda=False\\nmps=True", False),
    ],
)
def test_auto_mode_selects_cpu_only_when_cuda_is_unavailable(tmp_path, torch_info, expected_cpu):
    env, args_file = _fake_comfy_host(tmp_path, torch_info)
    env["COMFYUI_DEVICE"] = "auto"
    result = subprocess.run(
        ["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert ("--cpu" in args) is expected_cpu


def test_launcher_rejects_unknown_device_mode(tmp_path):
    env, args_file = _fake_comfy_host(tmp_path, "torch=unavailable")
    env["COMFYUI_DEVICE"] = "cuda"
    result = subprocess.run(
        ["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2
    assert "must be cpu or auto" in result.stderr
    assert not args_file.exists()


def test_launcher_rejects_invalid_port_before_starting_server(tmp_path):
    env, args_file = _fake_comfy_host(tmp_path, "torch=unavailable")
    env["COMFYUI_PORT"] = "70000"
    result = subprocess.run(
        ["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2
    assert not args_file.exists()


def test_launcher_does_not_install_or_download_any_dependencies():
    source = LAUNCHER.read_text(encoding="utf-8")
    for forbidden in ("pip install", "curl ", "wget ", "git clone", "conda install"):
        assert forbidden not in source
    assert 'COMFYUI_LISTEN="${COMFYUI_LISTEN:-127.0.0.1}"' in source
