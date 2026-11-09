"""Assemble portrait MP4 videos from scene cards/images, narration and optional music."""
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


def _make_frame(path: Path, title: str, scene: str, index: int, total: int,
                source_image: Path | None = None, subtitle: str | None = None):
    if source_image:
        with Image.open(source_image) as source:
            source.load()
            image = source.convert("RGB")
            image.thumbnail((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (WIDTH, HEIGHT), (16, 24, 39))
            canvas.paste(image, ((WIDTH - image.width) // 2, (HEIGHT - image.height) // 2))
            image = canvas
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        shade = ImageDraw.Draw(overlay)
        shade.rectangle((0, 0, WIDTH, 330), fill=(0, 0, 0, 150))
        shade.rectangle((0, HEIGHT - 360, WIDTH, HEIGHT), fill=(0, 0, 0, 175))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    else:
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
    if subtitle:
        caption_font = _font(30)
        caption_lines = _wrap(draw, subtitle, caption_font, WIDTH - 120)[:3]
        caption_height = len(caption_lines) * 42 + 28
        caption_top = HEIGHT - 300 - caption_height
        draw.rounded_rectangle((48, caption_top, WIDTH - 48, caption_top + caption_height),
                               radius=18, fill=(0, 0, 0))
        for line_no, line in enumerate(caption_lines):
            draw.text((68, caption_top + 14 + line_no * 42), line, font=caption_font,
                      fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
    image.save(path, format="PNG")


def render_storyboard(title: str, scenes: list[str], seconds_per_scene: int = 4,
                      image_paths: list[Path] | None = None, audio_path: Path | None = None,
                      subtitles: list[str] | None = None, music_path: Path | None = None,
                      music_volume: float = 0.18, transition: str = "fade") -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai. Video rendering filhaal unavailable hai.")
    if not scenes or len(scenes) > 25:
        raise ValueError("1 se 25 scenes required hain.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Har scene ki duration 2 se 12 seconds honi chahiye.")
    if transition not in {"cut", "fade"}:
        raise ValueError("Transition cut ya fade hona chahiye.")
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("Music volume 0 se 1 ke beech hona chahiye.")
    if music_path and not music_path.is_file():
        raise ValueError("Background music file nahi mili.")

    image_paths = image_paths or []
    subtitles = subtitles or []
    if image_paths and len(image_paths) != len(scenes):
        raise ValueError("Scene images ki sankhya scenes ke barabar honi chahiye.")
    if subtitles and len(subtitles) != len(scenes):
        raise ValueError("Subtitle lines ki sankhya scenes ke barabar honi chahiye.")
    for image_path in image_paths:
        if not image_path.is_file():
            raise ValueError("Selected scene image file nahi mili.")
        try:
            with Image.open(image_path) as check:
                check.verify()
        except Exception:
            raise ValueError("Selected scene image valid image file nahi hai.") from None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output_path = OUTPUT_DIR / f"{video_id}.mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="sintu-render-") as temp:
            work = Path(temp)
            lines = []
            for index, scene in enumerate(scenes, start=1):
                frame = work / f"frame-{index:03d}.png"
                source_image = image_paths[index - 1] if image_paths else None
                subtitle = subtitles[index - 1] if subtitles else None
                _make_frame(frame, title, scene, index, len(scenes), source_image, subtitle)
                lines.append(f"file '{frame.as_posix()}'")
                lines.append(f"duration {seconds_per_scene}")
            lines.append(f"file '{(work / f'frame-{len(scenes):03d}.png').as_posix()}'")
            concat = work / "frames.txt"
            concat.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
            duration = len(scenes) * seconds_per_scene
            filters = []
            if transition == "fade" and len(scenes) > 1:
                for boundary in range(1, len(scenes)):
                    point = boundary * seconds_per_scene
                    filters.append(f"fade=t=out:st={point - 0.35}:d=0.35")
                    filters.append(f"fade=t=in:st={point}:d=0.35")
            video_filter = ",".join(filters)
            command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                       "-f", "concat", "-safe", "0", "-i", str(concat)]
            audio_inputs = []
            if audio_path:
                command += ["-i", str(audio_path)]
                audio_inputs.append("voice")
            if music_path:
                command += ["-stream_loop", "-1", "-i", str(music_path)]
                audio_inputs.append("music")
            if audio_inputs == ["voice", "music"]:
                command += ["-filter_complex",
                    f"[1:a]volume=1[voice];[2:a]volume={music_volume},atrim=duration={duration}[music];"
                    "[voice][music]amix=inputs=2:duration=longest:dropout_transition=2,apad,atrim=duration="
                    f"{duration}[aout]", "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
            elif audio_inputs == ["voice"]:
                command += ["-map", "0:v:0", "-map", "1:a:0", "-af", f"apad,atrim=duration={duration}",
                            "-c:a", "aac", "-b:a", "192k"]
            elif audio_inputs == ["music"]:
                command += ["-map", "0:v:0", "-map", "1:a:0", "-af",
                            f"volume={music_volume},atrim=duration={duration}", "-c:a", "aac", "-b:a", "192k"]
            else:
                command += ["-map", "0:v:0", "-an"]
            if video_filter:
                command += ["-vf", video_filter]
            command += ["-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-r", "30", "-movflags", "+faststart", str(output_path)]
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
        "audio": "voiceover+music" if audio_path and music_path else "voiceover" if audio_path else "music" if music_path else "none",
        "music": bool(music_path),
        "music_volume": music_volume if music_path else None,
        "transition": transition,
        "scene_images": len(image_paths),
        "subtitles_burned_in": bool(subtitles),
        "format": "MP4 / H.264",
        "note": "Scene images, optional narration, uploaded background music and burned-in captions are combined. Fade transitions are supported; advanced motion/VFX are not included.",
    }
