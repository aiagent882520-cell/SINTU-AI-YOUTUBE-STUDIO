"""Independent QA for Hindi documentary MP4 renders and subtitle pixel boundaries."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

from .video_renderer import (
    OUTPUT_DIR,
    _create_subtitle_track,
    verify_publishable_mp4,
)


def audit_subtitle_pixel_bounds(
    subtitles: list[str],
    durations: list[float],
    width: int,
    height: int,
    *,
    safe_margin_ratio: float = 0.06,
) -> dict:
    """Burn each exact subtitle onto black via libass and inspect rendered glyph pixels.

    This is intentionally a pixel test, not a character-count or text-width heuristic.
    A black background isolates subtitle glyphs from scene art and the SINTU watermark.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Subtitle pixel audit requires FFmpeg.")
    if not subtitles or len(subtitles) != len(durations):
        raise ValueError("Subtitle and duration counts must match and be non-empty.")
    if not 0 < safe_margin_ratio < 0.25:
        raise ValueError("Subtitle safe margin ratio is invalid.")

    minimum_x = round(width * safe_margin_ratio)
    maximum_x = width - minimum_x - 1
    cues = []
    with tempfile.TemporaryDirectory(prefix="sintu-subtitle-pixel-audit-") as temporary:
        work = Path(temporary)
        for index, (subtitle, duration) in enumerate(zip(subtitles, durations), start=1):
            if not isinstance(subtitle, str) or not subtitle.strip():
                raise ValueError(f"Subtitle {index} is empty.")
            subtitle_file, subtitle_filter = _create_subtitle_track(
                work / f"cue-{index:02d}", [subtitle], [float(duration)],
                width, height, ffmpeg,
            )
            if subtitle_file is None or not subtitle_filter:
                raise RuntimeError(f"Subtitle {index} could not be prepared for pixel audit.")
            frame_path = work / f"cue-{index:02d}.png"
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1:d=1",
                "-vf", subtitle_filter, "-frames:v", "1", str(frame_path),
            ]
            rendered = subprocess.run(
                command, capture_output=True, text=True, timeout=45, check=False,
            )
            if rendered.returncode or not frame_path.is_file():
                raise RuntimeError(
                    f"Subtitle {index} pixel render failed: {(rendered.stderr or '')[-500:]}"
                )
            with Image.open(frame_path) as frame:
                gray = frame.convert("L")
                glyph_mask = gray.point(lambda value: 255 if value >= 24 else 0)
                bounds = glyph_mask.getbbox()
            if bounds is None:
                raise AssertionError(f"Subtitle {index} produced no visible glyph pixels.")
            left, top, right, bottom = bounds
            passed = left >= minimum_x and right - 1 <= maximum_x
            cues.append({
                "index": index,
                "text": subtitle,
                "pixel_bounds": [left, top, right, bottom],
                "safe_x_bounds": [minimum_x, maximum_x],
                "passed": passed,
            })
            if not passed:
                raise AssertionError(
                    f"Subtitle {index} clips the safe horizontal area: "
                    f"pixels x={left}..{right - 1}, allowed={minimum_x}..{maximum_x}."
                )
    return {
        "passed": all(cue["passed"] for cue in cues),
        "method": "FFmpeg libass burn on black + Pillow glyph-pixel bounding box",
        "resolution": f"{width}x{height}",
        "safe_margin_ratio": safe_margin_ratio,
        "cue_count": len(cues),
        "cues": cues,
    }


def audit_documentary_mp4(
    video_path: Path,
    subtitles: list[str],
    durations: list[float],
    width: int,
    height: int,
) -> dict:
    """Run publish-grade MP4 checks plus an independent rendered subtitle pixel audit."""
    video_path = Path(video_path)
    media = verify_publishable_mp4(video_path)
    if media["resolution"] != f"{width}x{height}":
        raise AssertionError("Final documentary MP4 resolution differs from the requested profile.")
    subtitle_pixels = audit_subtitle_pixel_bounds(
        subtitles, durations, width, height,
    )
    report = {
        "passed": bool(media["verified"] and subtitle_pixels["passed"]),
        "video": media,
        "subtitle_pixel_audit": subtitle_pixels,
    }
    report_path = video_path.with_name(f"{video_path.stem}-qa.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    return report
