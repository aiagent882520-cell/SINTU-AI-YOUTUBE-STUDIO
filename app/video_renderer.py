"""Simple, honest storyboard-to-MP4 renderer.

Creates silent portrait MP4 scene cards from text. It does not generate AI images,
voice, music, or motion; those require separate providers.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import uuid

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "generated_videos"
WIDTH, HEIGHT = 720, 1280


class RendererUnavailable(Exception):
    pass


class RenderFailed(Exception):
    pass


def _font(size: int):
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _make_frame(path: Path, title: str, scene: str, index: int, total: int):
    image = Image.new("RGB", (WIDTH, HEIGHT), (16, 24, 39))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 70, WIDTH - 42, HEIGHT - 70), radius=34, outline=(68, 89, 120), width=3)
    small = _font(26)
    heading = _font(42)
    body = _font(38)
    draw.text((82, 112), "SINTU AI STUDIO", font=small, fill=(125, 211, 252))
    draw.text((82, 190), title[:72], font=heading, fill=(255, 255, 255))
    draw.line((82, 275, WIDTH - 82, 275), fill=(68, 89, 120), width=3)
    lines = _wrap(draw, scene, body, WIDTH - 164)
    line_height = 58
    y = max(360, (HEIGHT - len(lines) * line_height) // 2)
    for line in lines[:12]:
        draw.text((82, y), line, font=body, fill=(238, 242, 255))
        y += line_height
    draw.text((82, HEIGHT - 150), f"SCENE {index} / {total}", font=small, fill=(148, 163, 184))
    image.save(path, format="PNG")


def render_storyboard(title: str, scenes: list[str], seconds_per_scene: int = 4) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai. Video rendering filhaal unavailable hai.")
    if not scenes or len(scenes) > 25:
        raise ValueError("1 se 25 scenes required hain.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Har scene ki duration 2 se 12 seconds honi chahiye.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output_path = OUTPUT_DIR / f"{video_id}.mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="sintu-render-") as temp:
            work = Path(temp)
            lines = []
            for index, scene in enumerate(scenes, start=1):
                frame = work / f"frame-{index:03d}.png"
                _make_frame(frame, title, scene, index, len(scenes))
                lines.append(f"file '{frame.as_posix()}'")
                lines.append(f"duration {seconds_per_scene}")
            lines.append(f"file '{(work / f'frame-{len(scenes):03d}.png').as_posix()}'")
            concat = work / "frames.txt"
            concat.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
            command = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-r", "30", "-movflags", "+faststart", str(output_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
            if completed.returncode != 0 or not output_path.exists():
                detail = (completed.stderr or "FFmpeg render failed")[-1200:]
                raise RenderFailed(detail)
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        raise RenderFailed("Video render timeout ho gaya. Scenes kam karke dobara try karein.") from None
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    return {
        "video_id": video_id,
        "filename": output_path.name,
        "url": f"/api/videos/{video_id}",
        "scenes": len(scenes),
        "duration_seconds": len(scenes) * seconds_per_scene,
        "resolution": f"{WIDTH}x{HEIGHT}",
        "audio": "none",
        "format": "MP4 / H.264",
        "note": "Silent text storyboard video. AI visuals, voiceover, music, and advanced motion are not included.",
    }
