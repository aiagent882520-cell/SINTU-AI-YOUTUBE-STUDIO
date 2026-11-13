"""Assemble clean MP4 videos with optional audio and mandatory SINTU branding."""
from pathlib import Path
import os
import math
import shutil
import subprocess
import tempfile
import textwrap
import uuid

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
OUTPUT_DIR = DATA_DIR / "generated_videos"
WIDTH, HEIGHT = 720, 1280
OUTPUT_PROFILES = {"720x1280": (720,1280), "1080x1920": (1080,1920), "1080x1080": (1080,1080), "1280x720": (1280,720), "1920x1080": (1920,1080)}
QUALITY_PROFILES = {"standard": 23, "high": 20, "maximum": 18}
MAX_SCENE_IMAGE_BYTES = 15 * 1024 * 1024
MAX_SCENE_IMAGE_DIMENSION = 4096
MAX_SCENE_IMAGE_PIXELS = 16_777_216

MAX_SOURCE_VIDEO_BYTES = 100 * 1024 * 1024


def _validate_source_video(path: Path) -> None:
    """Bound source MP4 size before invoking FFprobe or FFmpeg."""
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("Selected AI video clip file nahi mili, safe regular file nahi hai ya MP4 nahi hai.")
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError("Selected AI video clip file read nahi ho sakti.") from None
    if size <= 0 or size > MAX_SOURCE_VIDEO_BYTES:
        raise ValueError("AI video clip empty hai ya 100 MB limit se badi hai.")



def _validate_scene_image(path: Path) -> None:
    """Reject oversized, unsupported or malformed user-supplied scene images."""
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Selected scene image file nahi mili ya safe regular file nahi hai.")
        size = path.stat().st_size
        if size <= 0 or size > MAX_SCENE_IMAGE_BYTES:
            raise ValueError("Scene image empty hai ya 15 MB limit se badi hai.")
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Scene image format PNG, JPEG ya WEBP hona chahiye.")
            width, height = image.size
            if (width < 64 or height < 64 or width > MAX_SCENE_IMAGE_DIMENSION
                    or height > MAX_SCENE_IMAGE_DIMENSION
                    or width * height > MAX_SCENE_IMAGE_PIXELS):
                raise ValueError("Scene image dimensions allowed safety limit se bahar hain.")
            image.verify()
    except ValueError:
        raise
    except Exception:
        raise ValueError("Selected scene image valid image file nahi hai.") from None


def _render_settings(resolution: str, fps: int, quality: str):
    if resolution not in OUTPUT_PROFILES:
        raise ValueError("Unsupported render resolution profile.")
    if fps not in {24, 30, 60}:
        raise ValueError("FPS 24, 30 ya 60 hona chahiye.")
    if quality not in QUALITY_PROFILES:
        raise ValueError("Quality standard, high ya maximum honi chahiye.")
    width, height = OUTPUT_PROFILES[resolution]
    return width, height, QUALITY_PROFILES[quality], "veryfast"


class RendererUnavailable(Exception):
    pass


class RenderFailed(Exception):
    pass


def _verify_rendered_output(path: Path, expected_width: int, expected_height: int,
                            expected_duration: float, require_audio: bool | None = None) -> dict:
    """Verify the finished MP4 on disk before exposing it to the user."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RendererUnavailable("Final video verification ke liye FFprobe installed hona chahiye.")
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name,width,height",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Final MP4 quality verification fail ya timeout ho gaya.") from None
    if result.returncode != 0:
        raise RenderFailed("Final MP4 corrupt hai; FFprobe verify nahi kar saka.")
    try:
        import json
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        fmt = metadata.get("format", {})
        duration = float(fmt.get("duration", 0))
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        codec = str(video.get("codec_name", "")).lower()
        names = str(fmt.get("format_name", "")).lower().split(",")
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
    except (AttributeError, TypeError, ValueError, StopIteration, json.JSONDecodeError):
        raise RenderFailed("Final MP4 mein valid video stream/duration metadata nahi hai.") from None
    if not any(name in {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"} for name in names):
        raise RenderFailed("Final output MP4 container nahi hai.")
    if codec != "h264" or (width, height) != (expected_width, expected_height):
        raise RenderFailed("Final video codec ya resolution expected profile se match nahi karta.")
    if not math.isfinite(duration) or duration <= 0 or abs(duration - expected_duration) > max(1.0, expected_duration * 0.03):
        raise RenderFailed("Final video duration expected timeline se match nahi karti.")
    if require_audio is not None and has_audio != require_audio:
        raise RenderFailed("Final video audio stream expected setting se match nahi karti.")
    return {"duration_seconds": duration, "resolution": f"{width}x{height}",
            "video_codec": codec, "audio": has_audio}

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


def _make_watermark_image(width: int = 320, height: int = 76) -> Image.Image:
    """Create a compact SINTU mark: blue-violet S, red play tile and wordmark."""
    logo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logo)
    draw.rounded_rectangle((1, 1, width - 2, height - 2), radius=max(10, int(height * .22)),
                           fill=(8, 15, 28, 178), outline=(90, 170, 255, 190), width=max(1, int(height * .025)))
    icon_size = height - 12
    left, top = 7, 6
    draw.rounded_rectangle((left, top, left + icon_size, top + icon_size), radius=max(8, int(icon_size * .22)),
                           fill=(14, 24, 48, 255), outline=(72, 170, 255, 255), width=max(1, int(height * .035)))
    # A clean, high-contrast play tile keeps the mark legible at watermark scale.
    tile_w, tile_h = int(icon_size * .72), int(icon_size * .50)
    tx = left + (icon_size - tile_w) // 2
    ty = top + (icon_size - tile_h) // 2
    draw.rounded_rectangle((tx, ty, tx + tile_w, ty + tile_h), radius=max(4, int(tile_h * .25)),
                           fill=(222, 25, 58, 255))
    cy = ty + tile_h // 2
    draw.polygon([(tx + tile_w * .42, cy - tile_h * .25),
                  (tx + tile_w * .42, cy + tile_h * .25),
                  (tx + tile_w * .68, cy)], fill=(255, 255, 255, 255))
    text_x = left + icon_size + 10
    draw.text((text_x, int(height * .12)), "SINTU AI", font=_font(max(10, int(height * .34))), fill=(255, 255, 255, 255))
    draw.text((text_x, int(height * .56)), "YOUTUBE STUDIO", font=_font(max(7, int(height * .18))), fill=(145, 205, 255, 255))
    return logo


def _make_frame(path: Path, title: str, scene: str, index: int, total: int,
                source_image: Path | None = None, subtitle: str | None = None,
                width: int = WIDTH, height: int = HEIGHT, include_watermark: bool = True):
    """Create a clean visual frame; only the required brand watermark is drawn."""
    if subtitle:
        raise ValueError("Burned-in subtitles are disabled; SINTU exports clean video frames.")
    if source_image:
        with Image.open(source_image) as source:
            source.load()
            image = source.convert("RGB")
            image.thumbnail((width, height), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (width, height), (16, 24, 39))
            canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
            image = canvas.convert("RGBA")
    else:
        image = Image.new("RGBA", (width, height), (16, 24, 39, 255))
    if include_watermark:
        watermark = _make_watermark_image(width=max(180, int(width * 0.22)), height=max(44, int(width * 0.05)))
        margin = max(18, int(width * 0.025))
        image.alpha_composite(watermark, (width - watermark.width - margin, height - watermark.height - margin))
    image.convert("RGB").save(path, format="PNG")

def render_storyboard(title: str, scenes: list[str], seconds_per_scene: int = 4,
                      image_paths: list[Path] | None = None, audio_path: Path | None = None,
                      subtitles: list[str] | None = None, music_path: Path | None = None,
                      music_volume: float = 0.18, transition: str = "fade", motion: str = "none",
                      resolution: str = "720x1280", fps: int = 30, quality: str = "high") -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai. Video rendering filhaal unavailable hai.")
    width, height, crf, preset = _render_settings(resolution, fps, quality)
    if not scenes or len(scenes) > 25:
        raise ValueError("1 se 25 scenes required hain.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Har scene ki duration 2 se 12 seconds honi chahiye.")
    if transition not in {"cut", "fade"}:
        raise ValueError("Transition cut ya fade hona chahiye.")
    if motion not in {"none", "slow-zoom-in", "slow-zoom-out"}:
        raise ValueError("Motion none, slow-zoom-in ya slow-zoom-out hona chahiye.")
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("Music volume 0 se 1 ke beech hona chahiye.")
    if music_path and not music_path.is_file():
        raise ValueError("Background music file nahi mili.")

    image_paths = image_paths or []
    subtitles = subtitles or []
    if subtitles:
        raise ValueError("Subtitles/captions are disabled. Exported videos contain no spoken-word text overlays.")
    if image_paths and len(image_paths) != len(scenes):
        raise ValueError("Scene images ki sankhya scenes ke barabar honi chahiye.")
    if subtitles and len(subtitles) != len(scenes):
        raise ValueError("Subtitle lines ki sankhya scenes ke barabar honi chahiye.")
    for image_path in image_paths:
        _validate_scene_image(image_path)

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
                _make_frame(frame, title, scene, index, len(scenes), source_image, subtitle, width, height)
                lines.append(f"file '{frame.as_posix()}'")
                lines.append(f"duration {seconds_per_scene}")
            lines.append(f"file '{(work / f'frame-{len(scenes):03d}.png').as_posix()}'")
            concat = work / "frames.txt"
            concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
            duration = len(scenes) * seconds_per_scene
            filters = []
            if transition == "fade" and len(scenes) > 1:
                for boundary in range(1, len(scenes)):
                    point = boundary * seconds_per_scene
                    filters.append(f"fade=t=out:st={point - 0.35}:d=0.35")
                    filters.append(f"fade=t=in:st={point}:d=0.35")
            if motion == "slow-zoom-in":
                filters.insert(0, f"zoompan=z='min(zoom+0.0008,1.12)':d=1:s={width}x{height}:fps={fps}")
            elif motion == "slow-zoom-out":
                filters.insert(0, f"zoompan=z='max(zoom-0.0008,1.0)':d=1:s={width}x{height}:fps={fps}")
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
                    f"[1:a]volume=1[voice];[2:a]volume={music_volume},afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, duration - 2)}:d=2,atrim=duration={duration}[music];"
                    "[voice][music]amix=inputs=2:duration=longest:dropout_transition=2,apad,atrim=duration="
                    f"{duration}[aout]", "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
            elif audio_inputs == ["voice"]:
                command += ["-map", "0:v:0", "-map", "1:a:0", "-af", f"apad,atrim=duration={duration}",
                            "-c:a", "aac", "-b:a", "192k"]
            elif audio_inputs == ["music"]:
                command += ["-map", "0:v:0", "-map", "1:a:0", "-af",
                            f"volume={music_volume},afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, duration - 2)}:d=2,atrim=duration={duration}", "-c:a", "aac", "-b:a", "192k"]
            else:
                command += ["-map", "0:v:0", "-an"]
            if video_filter:
                command += ["-vf", video_filter]
            # The concat demuxer needs the duplicated final still to establish the last
            # frame duration. Include one frame interval; otherwise -t cuts that
            # duplicate at exactly the timeline boundary and can leave only one frame.
            command += ["-t", f"{duration + (1 / fps):.6f}", "-c:v", "libx264", "-preset", preset,
                        "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
                        "-movflags", "+faststart", str(output_path)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
            if completed.returncode != 0 or not output_path.exists():
                detail = (completed.stderr or "FFmpeg render failed")[-1200:]
                raise RenderFailed(detail)
            _verify_rendered_output(output_path, width, height, duration, require_audio=bool(audio_path or music_path))
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
        "resolution": f"{width}x{height}",
        "fps": fps,
        "quality": quality,
        "video_codec": "H.264 / libx264",
        "audio": "voiceover+music" if audio_path and music_path else "voiceover" if audio_path else "music" if music_path else "none",
        "music": bool(music_path),
        "music_volume": music_volume if music_path else None,
        "transition": transition,
        "motion": motion,
        "scene_images": len(image_paths),
        "subtitles_burned_in": False,
        "brand_watermark": "SINTU AI YOUTUBE STUDIO",
        "format": "MP4 / H.264",
        "note": "Clean scene imagery with the mandatory SINTU AI YOUTUBE STUDIO watermark, optional narration and background music. Spoken words and scene descriptions are never burned into the frames.",
    }


def render_ai_clips(video_paths: list[Path], audio_path: Path | None = None,
                    music_path: Path | None = None, music_volume: float = 0.18,
                    subtitles: list[str] | None = None, transition: str = "cut", transitions: list[str] | None = None,
                    clip_audio_volumes: list[float] | None = None, resolution: str = "720x1280",
                    fps: int = 30, quality: str = "high") -> dict:
    """Join AI MP4 clips, preserve audio, mix optional narration/music and add SINTU branding."""
    import json

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RendererUnavailable("FFmpeg aur FFprobe server par installed hone chahiye.")
    width, height, crf, preset = _render_settings(resolution, fps, quality)
    if not video_paths or len(video_paths) > 25:
        raise ValueError("1 se 25 AI video clips required hain.")
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("Music volume 0 se 1 ke beech hona chahiye.")
    if transition not in {"cut", "fade"}:
        raise ValueError("Transition cut ya fade hona chahiye.")
    transitions = transitions or [transition] * len(video_paths)
    if len(transitions) != len(video_paths) or any(x not in {"cut", "fade"} for x in transitions):
        raise ValueError("Har clip ke liye cut ya fade transition required hai.")
    clip_audio_volumes = clip_audio_volumes or [0.25] * len(video_paths)
    if len(clip_audio_volumes) != len(video_paths) or any(not isinstance(v, (int, float)) or not 0 <= v <= 2 for v in clip_audio_volumes):
        raise ValueError("Har clip ka source audio volume 0 se 2 (0–200%) hona chahiye.")
    subtitles = subtitles or []
    if subtitles:
        raise ValueError("Subtitles/captions are disabled. Exported videos contain no spoken-word text overlays.")
    if subtitles and len(subtitles) != len(video_paths):
        raise ValueError("Subtitle lines ki sankhya AI clips ke barabar honi chahiye.")
    if any(len(line) > 1000 for line in subtitles):
        raise ValueError("Subtitle line 1000 characters se chhoti honi chahiye.")
    for path in video_paths:
        _validate_source_video(path)
    if audio_path and not audio_path.is_file():
        raise ValueError("Voiceover audio file nahi mili.")
    if music_path and not music_path.is_file():
        raise ValueError("Background music file nahi mili.")

    clip_info = []
    total_duration = 0.0
    for path in video_paths:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
             "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=False
        )
        if probe.returncode != 0:
            raise RenderFailed("AI clip metadata read nahi ho saka.")
        try:
            metadata = json.loads(probe.stdout)
            duration = float(metadata["format"]["duration"])
            has_audio = any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", []))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise RenderFailed("AI clip duration ya audio metadata invalid hai.") from None
        if not math.isfinite(duration) or duration <= 0 or duration > 600:
            raise ValueError("AI clip duration finite aur 0 se 600 seconds ke beech honi chahiye.")
        clip_info.append({"duration": duration, "has_audio": has_audio})
        total_duration += duration
    if total_duration > 1800:
        raise ValueError("Combined AI video 30 minutes se lambi nahi ho sakti.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output_path = OUTPUT_DIR / f"{video_id}.mp4"
    try:
        with tempfile.TemporaryDirectory(prefix="sintu-ai-join-") as temp:
            work = Path(temp)
            command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
            brand_path = work / "sintu-watermark.png"
            _make_watermark_image(width=max(180, int(width * 0.22)), height=max(44, int(width * 0.05))).save(brand_path, format="PNG")
            for path in video_paths:
                command += ["-i", str(path)]

            audio_input_indexes = []
            next_index = len(video_paths)
            for index, info in enumerate(clip_info):
                if info["has_audio"]:
                    audio_input_indexes.append(index)
                else:
                    command += ["-f", "lavfi", "-t", f'{info["duration"]:.3f}',
                                "-i", "anullsrc=r=48000:cl=stereo"]
                    audio_input_indexes.append(next_index)
                    next_index += 1

            voice_index = None
            if audio_path:
                command += ["-i", str(audio_path)]
                voice_index = next_index
                next_index += 1
            music_index = None
            if music_path:
                command += ["-stream_loop", "-1", "-i", str(music_path)]
                music_index = next_index
                next_index += 1
            brand_index = next_index
            command += ["-loop", "1", "-i", str(brand_path)]

            filters = []
            video_labels = []
            audio_labels = []
            for index, info in enumerate(clip_info):
                vlabel = f"v{index}"
                alabel = f"clipa{index}"
                video_labels.append(f"[{vlabel}]")
                audio_labels.append(f"[{alabel}]")
                vfilters = (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},fps={fps},setsar=1,format=yuv420p,setpts=PTS-STARTPTS"
                )
                if len(clip_info) > 1:
                    fade_duration = min(0.35, info["duration"] / 4)
                    if index > 0 and transitions[index - 1] == "fade":
                        vfilters += f",fade=t=in:st=0:d={fade_duration:.3f}"
                    if index < len(clip_info) - 1 and transitions[index] == "fade":
                        vfilters += f",fade=t=out:st={max(0, info['duration']-fade_duration):.3f}:d={fade_duration:.3f}"
                filters.append(f"[{index}:v:0]{vfilters}[{vlabel}]")
                audio_filters = (
                    f"aresample=48000,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"atrim=duration={info['duration']:.3f},asetpts=PTS-STARTPTS"
                )
                filters.append(f"[{audio_input_indexes[index]}:a:0]{audio_filters},volume={float(clip_audio_volumes[index]):.3f}[{alabel}]")

            filters.append("".join(video_labels) + f"concat=n={len(video_paths)}:v=1:a=0[vout]")
            filters.append(f"[vout][{brand_index}:v]overlay=x=W-w-28:y=H-h-28:format=auto[vbrand]")
            filters.append("".join(audio_labels) + f"concat=n={len(video_paths)}:v=0:a=1[clipaudio]")

            mix_labels = []
            filters.append("[clipaudio]anull[ambient]")
            mix_labels.append("[ambient]")
            if voice_index is not None:
                filters.append(f"[{voice_index}:a:0]volume=1,aresample=48000,apad,atrim=duration={total_duration:.3f}[voice]")
                mix_labels.append("[voice]")
            if music_index is not None:
                filters.append(
                    f"[{music_index}:a:0]volume={music_volume},aresample=48000,"
                    f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0,total_duration-2):.3f}:d=2,"
                    f"atrim=duration={total_duration:.3f}[music]"
                )
                mix_labels.append("[music]")
            filters.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=2,atrim=duration={total_duration:.3f}[aout]")

            video_map = "[vbrand]"

            command += ["-filter_complex", ";".join(filters), "-map", video_map, "-map", "[aout]",
                        "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-t", f"{total_duration:.3f}",
                        "-movflags", "+faststart", str(output_path)]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=900, check=False)
            if completed.returncode != 0 or not output_path.exists():
                detail = (completed.stderr or "FFmpeg AI clip assembly failed")[-1600:]
                raise RenderFailed(detail)
            _verify_rendered_output(output_path, width, height, total_duration, require_audio=True)
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        raise RenderFailed("AI clips assemble karne mein timeout ho gaya.") from None
    except Exception:
        output_path.unlink(missing_ok=True)
        raise

    return {
        "video_id": video_id,
        "filename": output_path.name,
        "url": f"/api/videos/{video_id}",
        "scenes": len(video_paths),
        "duration_seconds": round(total_duration, 2),
        "resolution": f"{width}x{height}",
        "fps": fps,
        "quality": quality,
        "video_codec": "H.264 / libx264",
        "audio": "source+voiceover+music" if audio_path and music_path else "source+voiceover" if audio_path else "source+music" if music_path else "source-audio",
        "music": bool(music_path),
        "music_volume": music_volume if music_path else None,
        "transition": transition,
        "motion": "source AI clip motion",
        "scene_images": 0,
        "subtitles_burned_in": False,
        "brand_watermark": "SINTU AI YOUTUBE STUDIO",
        "format": "MP4 / H.264",
        "note": "Original clip audio is retained at reduced ambient level and mixed with optional voiceover/music. The SINTU AI YOUTUBE STUDIO watermark is added to the final output; no subtitle or spoken-word overlay is burned in. Fade mode fades each clip at its boundaries; it is not a cross-dissolve."
    }


def render_mixed_timeline(items: list[dict], title: str, scenes: list[str],
                          seconds_per_scene: int = 4, audio_path: Path | None = None,
                          music_path: Path | None = None, music_volume: float = 0.18,
                          subtitles: list[str] | None = None, transition: str = "cut",
                          transitions: list[str] | None = None, resolution: str = "720x1280",
                          fps: int = 30, quality: str = "high") -> dict:
    """Create one ordered timeline from generated still images and AI video clips."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai.")
    width, height, _, _ = _render_settings(resolution, fps, quality)
    if not items or len(items) > 25 or len(items) != len(scenes):
        raise ValueError("Timeline mein 1 se 25 items hon aur har item ka scene text ho.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Still image duration 2 se 12 seconds honi chahiye.")
    if subtitles:
        raise ValueError("Subtitles/captions are disabled. Exported videos contain no spoken-word text overlays.")
    subtitles = []
    transitions = transitions or [transition] * len(items)
    if len(transitions) != len(items) or any(x not in {"cut", "fade"} for x in transitions):
        raise ValueError("Har timeline scene ke liye cut ya fade transition chahiye.")
    with tempfile.TemporaryDirectory(prefix="sintu-mixed-timeline-") as temp:
        work = Path(temp)
        clip_paths = []
        for index, item in enumerate(items, start=1):
            kind = item.get("kind")
            path = item.get("path")
            if kind == "video":
                if not isinstance(path, Path):
                    raise ValueError("Timeline AI video clip nahi mili.")
                _validate_source_video(path)
                try:
                    trim_start = float(item.get("trim_start", 0) or 0)
                    trim_end = float(item["trim_end"]) if item.get("trim_end") is not None else None
                except (TypeError, ValueError):
                    raise ValueError("Video trim start/end valid numbers hone chahiye.") from None
                if (not math.isfinite(trim_start) or trim_start < 0
                        or (trim_end is not None and (not math.isfinite(trim_end) or trim_end <= trim_start))):
                    raise ValueError("Video trim start/end finite hone chahiye aur end, start se bada hona chahiye.")
                ffprobe=shutil.which("ffprobe")
                if not ffprobe: raise RendererUnavailable("Video trimming ke liye FFprobe installed hona chahiye.")
                probe=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,timeout=30,check=False)
                if probe.returncode!=0: raise RenderFailed("Source video duration read nahi ho saki.")
                try:
                    source_duration = float(probe.stdout.strip())
                except ValueError:
                    raise RenderFailed("Source video duration invalid hai.") from None
                if not math.isfinite(source_duration) or source_duration <= 0:
                    raise RenderFailed("Source video duration finite aur positive honi chahiye.")
                effective_end = source_duration if trim_end is None else trim_end
                if trim_start>=source_duration or effective_end>source_duration+0.05:
                    raise ValueError("Video trim range source clip ki duration ke andar hona chahiye.")
                segment_duration=effective_end-trim_start
                if segment_duration<0.25: raise ValueError("Trimmed video kam se kam 0.25 seconds ka hona chahiye.")
                segment=work/f"trimmed-{index:03d}.mp4"
                command=[ffmpeg,"-y","-hide_banner","-loglevel","error","-ss",f"{trim_start:.3f}","-i",str(path),"-t",f"{segment_duration:.3f}","-map","0:v:0","-map","0:a?","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-movflags","+faststart",str(segment)]
                completed=subprocess.run(command,capture_output=True,text=True,timeout=180,check=False)
                if completed.returncode!=0 or not segment.is_file():
                    raise RenderFailed((completed.stderr or "Video trim failed")[-1200:])
                clip_paths.append(segment)
            elif kind == "image":
                if not isinstance(path, Path):
                    raise ValueError("Timeline scene image nahi mili.")
                _validate_scene_image(path)
                image_duration = item.get("duration", seconds_per_scene)
                if not isinstance(image_duration, int) or not 2 <= image_duration <= 12:
                    raise ValueError("Har still image ki duration 2 se 12 seconds honi chahiye.")
                frame = work / f"still-{index:03d}.png"
                _make_frame(frame, title, scenes[index - 1], index, len(items), path, width=width, height=height, include_watermark=False)
                segment = work / f"still-{index:03d}.mp4"
                completed = subprocess.run(
                    [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-loop", "1", "-framerate", "30", "-i", str(frame),
                     "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                     "-t", str(image_duration), "-shortest",
                     "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(segment)],
                    capture_output=True, text=True, timeout=90, check=False
                )
                if completed.returncode != 0 or not segment.is_file():
                    raise RenderFailed((completed.stderr or "Still image clip creation failed")[-1200:])
                clip_paths.append(segment)
            else:
                raise ValueError("Timeline item kind image ya video hona chahiye.")
        result = render_ai_clips(
            clip_paths, audio_path=audio_path, music_path=music_path,
            music_volume=music_volume, subtitles=subtitles, transition=transition, transitions=transitions,
            clip_audio_volumes=[float(item.get("audio_volume", 0.25)) if item["kind"] == "video" else 0.0 for item in items],
            resolution=resolution, fps=fps, quality=quality
        )
        result["timeline_items"] = len(items)
        result["timeline_order"] = [item["kind"] for item in items]
        result["scene_transitions"] = transitions
        result["clip_audio_volumes"] = [item.get("audio_volume", 0.25) if item["kind"] == "video" else 0.0 for item in items]
        result["scene_durations"] = [item.get("duration") if item["kind"] == "image" else (round(float(item["trim_end"])-float(item.get("trim_start",0)),2) if item.get("trim_end") is not None else None) for item in items]
        result["note"] = "Still images and AI video clips are joined in order. Still-image duration is configurable; video clips can be trimmed by start/end seconds without modifying original source files. Source audio, optional voiceover/music, mandatory SINTU branding and cut/fade transitions are supported. No text overlays are burned in."
        return result
