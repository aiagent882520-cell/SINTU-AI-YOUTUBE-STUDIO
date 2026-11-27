"""Bounded 360-degree projection conversion for compatible source footage.

This is an intermediate projection-export stage only. It deliberately does not
claim spherical MP4 metadata, headset/platform compatibility, or publishability.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from . import render_process

MAX_INPUT_BYTES = 512 * 1024 * 1024
OUTPUT_PROFILES = {
    "1920x960": (1920, 960),
    "3840x1920": (3840, 1920),
}
# Expected source width/height ratios for FFmpeg's supported projection names.
_SOURCE_ASPECTS = {
    "e": 2.0,
    "c3x2": 1.5,
    "c6x1": 6.0,
    "eac": 1.5,
    "dfisheye": 2.0,
    "c1x6": 1.0 / 6.0,
}
_PROBE_TIMEOUT = 30
_RENDER_TIMEOUT = 900


class ImmersiveRenderError(RuntimeError):
    """A 360 projection conversion could not be completed safely."""


def _probe(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ImmersiveRenderError("360 conversion requires FFprobe.")
    try:
        result = render_process.run_render_process(
            [
                ffprobe, "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,width,height,codec_name",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=_PROBE_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ImmersiveRenderError("Could not inspect the source/output media.") from None
    if result.returncode != 0:
        raise ImmersiveRenderError("FFprobe rejected the source/output media.")
    try:
        metadata = json.loads(result.stdout)
        video = next(s for s in metadata.get("streams", []) if s.get("codec_type") == "video")
        width, height = int(video["width"]), int(video["height"])
        duration = float(metadata.get("format", {}).get("duration", 0))
        codec = str(video.get("codec_name", "")).lower()
    except (TypeError, ValueError, KeyError, StopIteration, json.JSONDecodeError):
        raise ImmersiveRenderError("Media has incomplete video metadata.") from None
    if width <= 0 or height <= 0 or not math.isfinite(duration) or duration <= 0:
        raise ImmersiveRenderError("Media dimensions and duration must be positive and finite.")
    return {"width": width, "height": height, "duration": duration, "codec": codec}


def render_360_projection(
    source: str | Path,
    destination: str | Path,
    *,
    input_projection: str,
    resolution: str = "1920x960",
    fps: int = 30,
    quality: int = 20,
) -> dict:
    """Convert explicitly identified compatible projection footage to equirectangular MP4.

    Supported source projections are equirectangular, cubemap 3x2/6x1/1x6,
    equi-angular cubemap, and dual-fisheye. The caller must identify the source
    projection correctly; this function does not infer it from pixels.
    """
    source_path = Path(source)
    destination_path = Path(destination)
    if input_projection not in _SOURCE_ASPECTS:
        raise ValueError("Unsupported input projection; choose a documented FFmpeg v360 projection.")
    if resolution not in OUTPUT_PROFILES:
        raise ValueError("360 output resolution must be 1920x960 or 3840x1920.")
    if isinstance(fps, bool) or fps not in {24, 25, 30, 50, 60}:
        raise ValueError("FPS must be 24, 25, 30, 50, or 60.")
    if isinstance(quality, bool) or not isinstance(quality, int) or not 18 <= quality <= 28:
        raise ValueError("CRF quality must be an integer from 18 to 28.")

    if source_path.is_symlink() or not source_path.is_file() or source_path.suffix.lower() != ".mp4":
        raise ImmersiveRenderError("Source must be a regular, non-symlink MP4 file.")
    try:
        source_size = source_path.stat().st_size
    except OSError:
        raise ImmersiveRenderError("Source MP4 cannot be read.") from None
    if source_size <= 0 or source_size > MAX_INPUT_BYTES:
        raise ImmersiveRenderError("Source MP4 is empty or exceeds the 512 MB safety limit.")

    source_resolved = source_path.resolve()
    destination_resolved = destination_path.resolve()
    if source_resolved == destination_resolved:
        raise ImmersiveRenderError("Source and destination must be different files.")
    if not destination_path.parent.is_dir():
        raise ImmersiveRenderError("Destination directory must already exist.")
    if destination_path.exists() or destination_path.is_symlink():
        raise ImmersiveRenderError("Destination already exists; refusing to overwrite any file.")

    source_info = _probe(source_path)
    actual_aspect = source_info["width"] / source_info["height"]
    expected_aspect = _SOURCE_ASPECTS[input_projection]
    if abs(actual_aspect - expected_aspect) > max(0.02, expected_aspect * 0.03):
        raise ImmersiveRenderError(
            f"Source dimensions do not match declared {input_projection} projection."
        )

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ImmersiveRenderError("360 conversion requires FFmpeg with the v360 filter.")
    width, height = OUTPUT_PROFILES[resolution]
    command = [
        ffmpeg, "-hide_banner", "-nostdin", "-n", "-i", str(source_path),
        "-map", "0:v:0", "-map", "0:a?", "-vf",
        f"v360=input={input_projection}:output=e:w={width}:h={height}:interp=lanc",
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
        "-crf", str(quality), "-pix_fmt", "yuv420p", "-threads", "2",
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(destination_path),
    ]
    try:
        rendered = render_process.run_render_process(
            command, capture_output=True, text=True,
            timeout=_RENDER_TIMEOUT, check=False,
        )
        if rendered.returncode != 0:
            raise ImmersiveRenderError("FFmpeg v360 projection conversion failed.")
        if destination_path.is_symlink() or not destination_path.is_file() or destination_path.stat().st_size <= 0:
            raise ImmersiveRenderError("FFmpeg did not produce a safe, non-empty output file.")
        output_info = _probe(destination_path)
        if (output_info["width"], output_info["height"]) != (width, height):
            raise ImmersiveRenderError("Converted output dimensions do not match the requested 2:1 profile.")
        if output_info["codec"] != "h264":
            raise ImmersiveRenderError("Converted output is not H.264.")
        if abs(output_info["duration"] - source_info["duration"]) > max(1.0, source_info["duration"] * 0.03):
            raise ImmersiveRenderError("Converted output duration differs materially from the source.")
    except (OSError, subprocess.TimeoutExpired):
        raise ImmersiveRenderError("360 projection conversion failed or timed out.") from None
    except ImmersiveRenderError:
        # Only remove the new destination created by this invocation. Never touch the source.
        if destination_path.exists() and not destination_path.is_symlink():
            destination_path.unlink()
        raise

    return {
        "success": True,
        "stage": "projection_conversion_only",
        "source_projection": input_projection,
        "output_projection": "equirectangular",
        "resolution": resolution,
        "fps": fps,
        "duration_seconds": output_info["duration"],
        "codec": output_info["codec"],
        "output": str(destination_path),
        "spherical_metadata_embedded": False,
        "platform_ready": False,
        "limitations": [
            "Spherical MP4 metadata has not been embedded or validated.",
            "No headset, YouTube, or other platform playback certification has been performed.",
            "This stage converts compatible supplied footage; it does not generate a real 360-degree scene.",
            "The declared input projection must match the actual source footage.",
        ],
    }
