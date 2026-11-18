#!/usr/bin/env python3
"""Read-only Android/Termux engine and hardware audit. Never downloads models or starts renders."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def _read_meminfo() -> dict[str, int]:
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return values


def _disk_free(path: Path) -> int | None:
    try:
        result = subprocess.run(["df", "-Pk", str(path)], capture_output=True,
                                text=True, timeout=5, check=True)
        fields = result.stdout.strip().splitlines()[-1].split()
        return int(fields[3]) * 1024
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _http_probe(url: str) -> dict:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "SINTU-Engine-Probe/1.0"})
        with urllib.request.urlopen(request, timeout=2) as response:
            return {"reachable": response.status == 200, "detail": f"HTTP {response.status}"}
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"reachable": False, "detail": type(exc).__name__}


def _binary(name: str) -> str | None:
    return shutil.which(name)


def _model_inventory() -> list[dict]:
    root = Path.home() / ".sintu" / "models"
    items = []
    if root.is_dir():
        for path in sorted(root.glob("*")):
            if path.is_file() and path.suffix.lower() in {".gguf", ".safetensors", ".ckpt", ".pth"}:
                try:
                    items.append({"name": path.name, "bytes": path.stat().st_size})
                except OSError:
                    continue
    return items


def _comfyui_setup_gate(termux: bool, available_ram_bytes: int, free_disk_bytes: int | None) -> dict:
    """Conservative host suitability check; this probe never installs ComfyUI or models."""
    minimum_ram = 8 * 1024**3
    minimum_disk = 20 * 1024**3
    reasons = []
    if termux:
        reasons.append("Android/Termux is not an approved local ComfyUI host in this setup.")
    if available_ram_bytes < minimum_ram:
        reasons.append("At least 8 GiB currently available RAM is required for manual host review.")
    if free_disk_bytes is None or free_disk_bytes < minimum_disk:
        reasons.append("At least 20 GiB free disk space is required for manual host review.")
    eligible = not reasons
    return {
        "status": "eligible_for_manual_review" if eligible else "blocked",
        "eligible_for_manual_review": eligible,
        "auto_install_allowed": False,
        "install_performed": False,
        "minimum_available_ram_bytes": minimum_ram,
        "minimum_free_disk_bytes": minimum_disk,
        "reasons": reasons,
        "recommendation": (
            "Use a separately managed Linux desktop/server and review its GPU, driver, model-license and workflow requirements."
            if eligible else
            "Do not install ComfyUI or download diffusion models on this device; use the procedural offline fallback until a suitable separate host is configured."
        ),
    }


def build_report() -> dict:
    mem = _read_meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    free_bytes = _disk_free(Path.home())
    arch = platform.machine()
    termux = bool(os.getenv("PREFIX", "").startswith("/data/data/com.termux"))
    llama = _binary("llama-server")
    sd_bins = {name: _binary(name) for name in ("sd-server", "sd-cli", "stable-diffusion.cpp")}
    models = _model_inventory()
    llama_probe = _http_probe("http://127.0.0.1:8080/v1/models")
    comfy_probe = _http_probe("http://127.0.0.1:8188/system_stats")
    sd_probe = _http_probe("http://127.0.0.1:8081/v1/models")
    # These are conservative eligibility hints, not guarantees of model performance.
    if available >= 3 * 1024**3 and (free_bytes or 0) >= 2 * 1024**3:
        llama_tier = "small_1b_to_3b_candidate"
    elif available >= 1500 * 1024**2 and (free_bytes or 0) >= 900 * 1024**2:
        llama_tier = "tiny_0.5b_candidate"
    else:
        llama_tier = "no_safe_automatic_model_download"
    if available >= 6 * 1024**3 and (free_bytes or 0) >= 5 * 1024**3:
        image_tier = "sd15_cpu_or_gpu_candidate"
    else:
        image_tier = "no_safe_automatic_diffusion_model_download"
    return {
        "device": {"termux": termux, "architecture": arch, "platform": platform.platform(),
                   "cpu_cores": os.cpu_count(), "ram_total_bytes": total,
                   "ram_available_bytes": available, "home_free_bytes": free_bytes},
        "engines": {
            "llama_cpp": {"binary": llama, "server": llama_probe,
                          "model_files": [m for m in models if m["name"].endswith(".gguf")]},
            "stable_diffusion_cpp": {"binaries": sd_bins, "server": sd_probe},
            "comfyui": {"server": comfy_probe,
                        "workflow_configured": bool(os.getenv("COMFYUI_IMAGE_WORKFLOW_PATH", "").strip()),
                        "setup_gate": _comfyui_setup_gate(termux, available, free_bytes)},
        },
        "recommendation": {"llama_model_tier": llama_tier, "image_model_tier": image_tier,
                           "install_policy": "No model downloads or engine builds performed by this probe."},
        "model_inventory": models,
        "render_started": False,
    }


def main() -> int:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
