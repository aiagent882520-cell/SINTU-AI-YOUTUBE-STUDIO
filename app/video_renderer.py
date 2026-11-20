"""Assemble clean MP4 videos with optional audio and mandatory SINTU branding."""
from pathlib import Path
from functools import lru_cache
import os
import re
import math
import shutil
import subprocess
import tempfile
import textwrap
import uuid

from PIL import Image, ImageDraw, ImageFont
from . import render_process

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

def _ffmpeg_thread_count() -> int:
    """Bound encoder threads to protect low-memory phones and shared CI runners."""
    try:
        return max(1, min(8, int(os.getenv("SINTU_FFMPEG_THREADS", "2"))))
    except ValueError:
        return 2

# Mobile Termux devices need more time for portrait H.264 encoding with two audio tracks.
try:
    RENDER_TIMEOUT_SECONDS = max(60, min(900, int(os.getenv("SINTU_RENDER_TIMEOUT_SECONDS", "600"))))
except ValueError:
    RENDER_TIMEOUT_SECONDS = 600


def _validate_source_video(path: Path) -> None:
    """Bound and decode sampled source pixels; metadata/extension alone cannot reject black MP4s."""
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".mp4":
        raise ValueError("Selected AI video clip file nahi mili, safe regular file nahi hai ya MP4 nahi hai.")
    try:
        size = path.stat().st_size
    except OSError:
        raise ValueError("Selected AI video clip file read nahi ho sakti.") from None
    if size <= 0 or size > MAX_SOURCE_VIDEO_BYTES:
        raise ValueError("AI video clip empty hai ya 100 MB limit se badi hai.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("AI source clip ke actual pixels verify karne ke liye FFmpeg required hai.")
    try:
        pixels = render_process.run_render_process(
            [ffmpeg, "-v", "error", "-i", str(path), "-vf", "fps=1,scale=32:32",
             "-frames:v", "600", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, text=False, check=False, timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("AI source video ke visual frames verify nahi ho sake.") from None
    frame_bytes = 32 * 32 * 3
    if pixels.returncode != 0 or len(pixels.stdout) < frame_bytes or len(pixels.stdout) % frame_bytes:
        raise ValueError("AI source MP4 mein decodable visual frames nahi hain.")
    frames = [pixels.stdout[i:i + frame_bytes] for i in range(0, len(pixels.stdout), frame_bytes)]
    visible = sum(1 for frame in frames if sum(frame) / len(frame) > 5.0 and max(frame) > 24)
    if visible < max(1, math.ceil(len(frames) * 0.70)):
        raise ValueError(f"AI source MP4 visual check failed: {visible}/{len(frames)} sampled frames contain visible content.")



def _validate_audio_file(path: Path, label: str) -> None:
    """Reject missing, empty, or symlinked narration/music inputs before FFmpeg opens them."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} file nahi mili ya safe regular file nahi hai.")
    try:
        if path.stat().st_size <= 0:
            raise ValueError(f"{label} file empty hai.")
    except OSError:
        raise ValueError(f"{label} file read nahi ho sakti.") from None


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
        # A valid PNG/JPEG can still be a completely black placeholder.
        with Image.open(path) as image:
            rgb = image.convert("RGB").resize((32, 32))
            extrema = rgb.getextrema()
            # Reject genuinely near-black placeholders without rejecting
            # valid low-texture/illustrative scenes (including flat-color art).
            if max(channel[1] for channel in extrema) < 24:
                raise ValueError("Scene image blank ya almost-black hai; real visual scene required hai.")
    except ValueError:
        raise
    except Exception:
        raise ValueError("Selected scene image valid image file nahi hai.") from None


def _storyboard_motion_filter(motion: str, width: int, height: int,
                              fps: int, seconds_per_scene: int) -> str | None:
    """Build repeatable per-scene camera motion; never let a zoom hit a global cap and freeze."""
    if motion == "none":
        return None
    scene_frames = max(1, int(round(seconds_per_scene * fps)))
    phase = f"mod(on,{scene_frames})/{max(1, scene_frames - 1)}"
    zoom_strength = min(0.24, max(0.16, seconds_per_scene * 0.02))
    if motion == "slow-zoom-in":
        zoom = f"1+{zoom_strength:.3f}*({phase})"
    elif motion == "slow-zoom-out":
        zoom = f"{1 + zoom_strength:.3f}-{zoom_strength:.3f}*({phase})"
    else:
        raise ValueError("Unsupported storyboard motion.")
    # Drift within the available crop margin, so pan remains in-bounds even at zoom=1.
    x = f"(iw-iw/zoom)/2+sin(2*PI*({phase}))*((iw-iw/zoom)*0.22)"
    y = f"(ih-ih/zoom)/2+cos(2*PI*({phase}))*((ih-ih/zoom)*0.12)"
    return (
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:"
        f"s={width}x{height}:fps={fps}"
    )


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



@lru_cache(maxsize=8)
def _ffmpeg_supports_subtitles(ffmpeg: str) -> bool:
    try:
        result = render_process.run_render_process(
            [ffmpeg, "-hide_banner", "-filters"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(re.search(r"\bsubtitles\b", result.stdout + result.stderr))


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def _create_subtitle_track(work: Path, subtitles: list[str] | None,
                           durations: list[float], height: int,
                           ffmpeg: str) -> tuple[Path | None, str | None]:
    """Create a timed SRT track and an FFmpeg libass filter for explicit user captions."""
    subtitles = subtitles or []
    if not subtitles or not any(isinstance(line, str) and line.strip() for line in subtitles):
        return None, None
    if len(subtitles) != len(durations):
        raise ValueError("Subtitle lines ki sankhya timeline scenes/clips ke barabar honi chahiye.")
    if any(not isinstance(line, str) or len(line) > 1000 for line in subtitles):
        raise ValueError("Har subtitle line text hona chahiye aur 1000 characters se chhoti honi chahiye.")
    if not _ffmpeg_supports_subtitles(ffmpeg):
        raise RendererUnavailable(
            "Burned-in subtitles ke liye FFmpeg ka libass subtitles filter chahiye. "
            "Termux mein libass aur fontconfig install karke FFmpeg support check karein."
        )
    cues = []
    cursor = 0.0
    cue_index = 1
    for line, duration in zip(subtitles, durations):
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Subtitle timing duration positive aur finite honi chahiye.")
        clean = line.replace("\r", " ").replace("{", "(").replace("}", ")")
        clean = clean.replace("<", "‹").replace(">", "›").strip()
        if clean:
            wrapped = textwrap.fill(clean, width=42, break_long_words=False, break_on_hyphens=False)
            cues.append(
                f"{cue_index}\n{_srt_timestamp(cursor)} --> {_srt_timestamp(cursor + duration)}\n{wrapped}\n"
            )
            cue_index += 1
        cursor += duration
    if not cues:
        return None, None
    subtitle_path = work / "sintu-subtitles.srt"
    subtitle_path.write_text("\n".join(cues), encoding="utf-8")
    raw_path = subtitle_path.as_posix().replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
    font = re.sub(r"[^A-Za-z0-9 _-]", "", os.getenv("SINTU_SUBTITLE_FONT", "Noto Sans Devanagari")).strip()
    if not font:
        font = "Noto Sans Devanagari"
    font_size = max(22, round(height * 0.027))
    margin = max(28, round(height * 0.055))
    style = (
        f"FontName={font},FontSize={font_size},PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H80000000,BackColour=&H50000000,BorderStyle=1,"
        f"Outline=2,Shadow=1,Alignment=2,MarginV={margin},WrapStyle=2"
    )
    return subtitle_path, f"subtitles=filename='{raw_path}':force_style='{style}'"


def validate_sampled_motion(frames: bytes, *, frame_bytes: int = 32 * 32 * 3,
                            minimum_ratio: float = 0.20, minimum_delta: float = 1.5) -> dict:
    """Measure frame-to-frame visual movement and reject frozen/slideshow-like long renders."""
    if frame_bytes <= 0 or len(frames) % frame_bytes:
        raise RenderFailed("Sampled video frames are incomplete.")
    if not 0.0 <= minimum_ratio <= 1.0:
        raise ValueError("Minimum motion ratio must be between 0 and 1.")
    sampled = [frames[index:index + frame_bytes]
               for index in range(0, len(frames), frame_bytes)]
    if len(sampled) < 8:
        raise RenderFailed("Long video has too few decoded frames for a motion quality audit.")
    deltas = [
        sum(abs(a - b) for a, b in zip(previous, current)) / frame_bytes
        for previous, current in zip(sampled, sampled[1:])
    ]
    moving = sum(delta >= minimum_delta for delta in deltas)
    transitions = len(deltas)
    ratio = moving / transitions if transitions else 0.0
    if ratio < minimum_ratio:
        raise RenderFailed(
            f"Video appears frozen or slideshow-like: {moving}/{transitions} sampled transitions show motion "
            f"({ratio:.1%}; minimum {minimum_ratio:.0%})."
        )
    return {
        "sampled_frames": len(sampled),
        "moving_transitions": moving,
        "sampled_transitions": transitions,
        "motion_ratio": round(ratio, 3),
        "mean_frame_delta": round(sum(deltas) / len(deltas), 3),
    }


def _verify_rendered_output(path: Path, expected_width: int, expected_height: int,
                            expected_duration: float, require_audio: bool | None = None,
                            expected_fps: int = 30,
                            minimum_motion_ratio: float = 0.40) -> dict:
    """Verify real video frames and video-stream duration, not just container/audio duration."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RendererUnavailable("Final video verification ke liye FFprobe installed hona chahiye.")
    try:
        result = render_process.run_render_process(
            [ffprobe, "-v", "error", "-count_frames",
             "-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name,width,height,pix_fmt,duration,nb_read_frames,avg_frame_rate,sample_rate,channels",
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
        video_duration = float(video.get("duration", 0))
        frame_count = int(video.get("nb_read_frames", 0))
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        codec = str(video.get("codec_name", "")).lower()
        pixel_format = str(video.get("pix_fmt", "")).lower()
        audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
        audio_codec = str(audio_stream.get("codec_name", "")).lower() if audio_stream else ""
        audio_sample_rate = int(audio_stream.get("sample_rate", 0)) if audio_stream else 0
        audio_channels = int(audio_stream.get("channels", 0)) if audio_stream else 0
        audio_duration = float(audio_stream.get("duration", 0)) if audio_stream else 0.0
        names = str(fmt.get("format_name", "")).lower().split(",")
        has_audio = any(item.get("codec_type") == "audio" for item in metadata.get("streams", []))
        frame_rate_num, frame_rate_den = (int(part) for part in str(video.get("avg_frame_rate", "0/1")).split("/", 1))
        actual_fps = frame_rate_num / frame_rate_den if frame_rate_den else 0
    except (AttributeError, TypeError, ValueError, StopIteration, json.JSONDecodeError, ZeroDivisionError):
        raise RenderFailed("Final MP4 mein valid video stream/frame metadata nahi hai.") from None
    if not any(name in {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"} for name in names):
        raise RenderFailed("Final output MP4 container nahi hai.")
    if codec != "h264" or (width, height) != (expected_width, expected_height):
        raise RenderFailed("Final video codec ya resolution expected profile se match nahi karta.")
    if pixel_format != "yuv420p":
        raise RenderFailed("Final MP4 Android-compatible yuv420p pixel format mein encode nahi hua.")
    if has_audio and (audio_codec != "aac" or audio_sample_rate != 48000 or audio_channels != 2):
        raise RenderFailed("Final MP4 audio Android-compatible AAC, 48 kHz stereo profile mein nahi hai.")
    if not math.isfinite(duration) or duration <= 0 or abs(duration - expected_duration) > max(1.0, expected_duration * 0.03):
        raise RenderFailed("Final MP4 container duration expected timeline se match nahi karti.")
    minimum_frames = max(1, math.floor(expected_duration * expected_fps * 0.95))
    if frame_count < minimum_frames or not math.isfinite(video_duration) or video_duration < expected_duration - (2 / expected_fps):
        raise RenderFailed("Final video mein actual frames ya video-stream duration expected timeline se kam hai.")
    if not math.isfinite(actual_fps) or abs(actual_fps - expected_fps) > 0.1:
        raise RenderFailed("Final video frame rate expected FPS se match nahi karta.")
    if require_audio is not None and has_audio != require_audio:
        raise RenderFailed("Final video audio stream expected setting se match nahi karti.")
    if has_audio:
        sync_tolerance = max(0.5, 2.0 / expected_fps)
        if (not math.isfinite(audio_duration) or audio_duration <= 0
                or abs(audio_duration - video_duration) > sync_tolerance):
            raise RenderFailed(
                "Audio/video stream durations are not synchronized "
                f"(audio={audio_duration:.3f}s, video={video_duration:.3f}s, "
                f"tolerance={sync_tolerance:.3f}s)."
            )

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("Visual quality verification ke liye FFmpeg required hai.")

    # Reject full-black and long black segments at render time too, not
    # only when a later upload is attempted.
    try:
        black = render_process.run_render_process(
            [ffmpeg, "-hide_banner", "-i", str(path), "-vf",
             "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Final MP4 black-frame verification fail ya timeout ho gaya.") from None
    if black.returncode != 0:
        raise RenderFailed("Final MP4 black-frame scan decode nahi ho saka.")
    black_intervals = [
        (float(start), float(end)) for start, end in re.findall(
            r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", black.stderr
        )
    ]
    longest_black_seconds = max((end - start for start, end in black_intervals), default=0.0)
    if any(start <= 0.1 and end >= duration * 0.95 for start, end in black_intervals):
        raise RenderFailed("Final video mein full-duration black frames hain.")
    if longest_black_seconds >= max(2.5, duration * 0.25):
        raise RenderFailed(
            f"Final video mein lamba black segment hai ({longest_black_seconds:.2f}s)."
        )

    # Decode real pixels at one frame per second. Metadata-only checks let an
    # all-black H.264 file pass as a successful video; reject that failure mode.
    try:
        pixels = render_process.run_render_process(
            [ffmpeg, "-v", "error", "-i", str(path), "-vf", "fps=1,scale=32:32",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, text=False, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Final video ke actual visual frames decode nahi ho sake.") from None
    frame_bytes = 32 * 32 * 3
    if pixels.returncode != 0 or len(pixels.stdout) < frame_bytes:
        raise RenderFailed("Final video mein decodable visual frames nahi hain.")
    sampled = [pixels.stdout[i:i + frame_bytes]
               for i in range(0, len(pixels.stdout) - frame_bytes + 1, frame_bytes)]
    visible = 0
    for frame in sampled:
        mean_luma = sum(frame) / len(frame)
        if mean_luma > 5.0 and max(frame) > 24:
            visible += 1
    if visible < max(1, math.ceil(len(sampled) * 0.70)):
        raise RenderFailed(
            f"Visual quality check failed: {visible}/{len(sampled)} sampled frames contain visible image content."
        )
    verified = {"verified": True, "duration_seconds": duration, "video_duration_seconds": video_duration,
                "frame_count": frame_count, "fps": actual_fps,
                "audio_duration_seconds": audio_duration if has_audio else None,
                "resolution": f"{width}x{height}", "video_codec": codec, "audio": has_audio,
                "black_intervals": black_intervals,
                "longest_black_segment_seconds": round(longest_black_seconds, 3),
                "visible_frame_count": visible, "sampled_frame_count": len(sampled)}
    if duration > 8:
        verified["motion_audit"] = validate_sampled_motion(
            pixels.stdout, minimum_ratio=minimum_motion_ratio
        )
    return verified


def verify_publishable_mp4(path: Path, max_bytes: int = 512 * 1024 * 1024) -> dict:
    """Fail closed before upload if an MP4 is corrupt, truncated, or not a supported render."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RenderFailed("Upload ke liye MP4 missing hai ya unsafe file hai.")
    try:
        size = path.stat().st_size
    except OSError:
        raise RenderFailed("Upload MP4 file read nahi ho sakti.") from None
    if size <= 0 or size > max_bytes:
        raise RenderFailed("Upload MP4 empty hai ya 512 MB safety limit se badi hai.")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RendererUnavailable("Upload se pehle MP4 verify karne ke liye FFprobe required hai.")
    try:
        result = render_process.run_render_process(
            [ffprobe, "-v", "error", "-count_frames", "-show_entries",
             "format=format_name,duration:stream=codec_type,codec_name,width,height,duration,nb_read_frames,avg_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Upload MP4 verification fail ya timeout ho gaya.") from None
    if result.returncode != 0:
        raise RenderFailed("Upload MP4 corrupt hai; FFprobe verify nahi kar saka.")
    try:
        import json
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        fmt = metadata.get("format", {})
        duration = float(fmt.get("duration", 0))
        video_duration = float(video.get("duration", 0))
        frame_count = int(video.get("nb_read_frames", 0))
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        codec = str(video.get("codec_name", "")).lower()
        names = str(fmt.get("format_name", "")).lower().split(",")
        numerator, denominator = (int(part) for part in str(video.get("avg_frame_rate", "0/1")).split("/", 1))
        fps = numerator / denominator if denominator else 0
        audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
        audio_duration = float(audio_stream.get("duration", 0)) if audio_stream else None
    except (AttributeError, TypeError, ValueError, StopIteration, json.JSONDecodeError, ZeroDivisionError):
        raise RenderFailed("Upload MP4 mein valid video stream/frame metadata nahi hai.") from None
    if not any(name in {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"} for name in names):
        raise RenderFailed("Upload file MP4 container nahi hai.")
    if codec != "h264" or (width, height) not in set(OUTPUT_PROFILES.values()):
        raise RenderFailed("Upload MP4 H.264 ya supported SINTU resolution mein nahi hai.")
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(video_duration) or video_duration <= 0:
        raise RenderFailed("Upload MP4 ki duration invalid hai.")
    if not math.isfinite(fps) or fps not in {24, 30, 60}:
        raise RenderFailed("Upload MP4 ka frame rate supported profile se match nahi karta.")
    minimum_frames = max(1, math.floor(duration * fps * 0.95))
    if frame_count < minimum_frames or abs(duration - video_duration) > max(0.5, 2 / fps):
        raise RenderFailed("Upload MP4 truncated hai: actual frames aur video duration match nahi karte.")
    if audio_stream is not None:
        if (audio_duration is None or not math.isfinite(audio_duration) or audio_duration <= 0
                or abs(audio_duration - video_duration) > max(0.5, 2 / fps)):
            raise RenderFailed(
                "Upload MP4 audio/video streams are not synchronized "
                f"(audio={audio_duration}, video={video_duration:.3f}s)."
            )

    # Metadata alone does not prove that the encoded picture contains visible
    # content. Reject full-duration black exports and sample short clips too;
    # otherwise a 4–8 second black MP4 could pass the upload gate.
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("Upload se pehle visual MP4 verification ke liye FFmpeg required hai.")
    try:
        black = render_process.run_render_process(
            [ffmpeg, "-hide_banner", "-i", str(path), "-vf",
             "blackdetect=d=0.5:pix_th=0.10", "-an", "-f", "null", "-"],
            capture_output=True, text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Upload MP4 black-frame verification fail ya timeout ho gaya.") from None
    if black.returncode != 0:
        raise RenderFailed("Upload MP4 black-frame scan decode nahi ho saka.")
    black_intervals = [
        (float(start), float(end)) for start, end in re.findall(
            r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", black.stderr
        )
    ]
    longest_black_seconds = max((end - start for start, end in black_intervals), default=0.0)
    if any(start <= 0.1 and end >= duration * 0.95 for start, end in black_intervals):
        raise RenderFailed("Upload MP4 mein full-duration black video frames hain; publishing blocked.")
    maximum_black_segment = max(2.5, duration * 0.25)
    if longest_black_seconds >= maximum_black_segment:
        raise RenderFailed(
            f"Upload MP4 mein lamba black segment hai ({longest_black_seconds:.2f}s); publishing blocked."
        )

    # Uniformly distribute up to 600 frame samples across the entire duration.
    # This avoids inspecting only the opening 10 minutes of a longer render.
    sample_rate = min(2.0, 600.0 / duration)
    try:
        pixels = render_process.run_render_process(
            [ffmpeg, "-v", "error", "-i", str(path), "-vf",
             f"fps={sample_rate:.8f},scale=32:32",
             "-frames:v", "600", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
            capture_output=True, text=False, timeout=45, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RenderFailed("Upload MP4 visible-frame verification fail ya timeout ho gaya.") from None
    frame_bytes = 32 * 32 * 3
    if pixels.returncode != 0 or len(pixels.stdout) < frame_bytes or len(pixels.stdout) % frame_bytes:
        raise RenderFailed("Upload MP4 ke visible frames decode nahi ho sake.")
    sampled_frames = [
        pixels.stdout[index:index + frame_bytes]
        for index in range(0, len(pixels.stdout), frame_bytes)
    ]
    visible_frames = sum(
        1 for frame in sampled_frames
        if (sum(frame) / len(frame)) > 5.0 and max(frame) > 24
    )
    required_visible = max(1, math.ceil(len(sampled_frames) * 0.70))
    if visible_frames < required_visible:
        raise RenderFailed(
            f"Upload MP4 visual quality failed: {visible_frames}/{len(sampled_frames)} sampled frames contain visible content."
        )

    motion_audit = None
    if duration > 8:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RendererUnavailable("Long MP4 motion verification ke liye FFmpeg required hai.")
        try:
            pixels = render_process.run_render_process(
                [ffmpeg, "-v", "error", "-i", str(path), "-vf", "fps=1,scale=32:32",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                capture_output=True, text=False, timeout=45, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RenderFailed("Upload MP4 motion verification fail ya timeout ho gaya.") from None
        if pixels.returncode != 0:
            raise RenderFailed("Upload MP4 ke motion frames decode nahi ho sake.")
        motion_audit = validate_sampled_motion(pixels.stdout, minimum_ratio=0.40)
    return {
        "verified": True, "size_bytes": size, "duration_seconds": duration,
        "video_duration_seconds": video_duration, "audio_duration_seconds": audio_duration, "frame_count": frame_count,
        "fps": fps, "resolution": f"{width}x{height}", "video_codec": codec,
        "black_intervals": black_intervals,
        "longest_black_segment_seconds": round(longest_black_seconds, 3),
        "sampled_frame_count": len(sampled_frames),
        "visible_frame_count": visible_frames,
        "motion_audit": motion_audit,
    }


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
                      music_volume: float = 0.18, transition: str = "fade", motion: str = "slow-zoom-in",
                      resolution: str = "720x1280", fps: int = 30, quality: str = "high",
                      sound_effects_enabled: bool = False, sound_effects_volume: float = 0.18) -> dict:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai. Video rendering filhaal unavailable hai.")
    width, height, crf, preset = _render_settings(resolution, fps, quality)
    if not scenes or len(scenes) > 25:
        raise ValueError("1 se 25 scenes required hain.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Har scene ki duration 2 se 12 seconds honi chahiye.")
    if len(scenes) * seconds_per_scene > 8 and motion == "none":
        raise ValueError("8 seconds se lambi storyboard video mein cinematic camera motion zaroori hai; static slideshow disabled hai.")
    if transition not in {"cut", "fade"}:
        raise ValueError("Transition cut ya fade hona chahiye.")
    if motion not in {"none", "slow-zoom-in", "slow-zoom-out"}:
        raise ValueError("Motion none, slow-zoom-in ya slow-zoom-out hona chahiye.")
    if not 0.0 <= music_volume <= 1.0:
        raise ValueError("Music volume 0 se 1 ke beech hona chahiye.")
    if not isinstance(sound_effects_enabled, bool) or not 0.0 <= sound_effects_volume <= 1.0:
        raise ValueError("Sound effects enable flag ya volume invalid hai.")
    if music_path:
        _validate_audio_file(music_path, "Background music")

    if image_paths is None or len(image_paths) != len(scenes):
        raise ValueError("Har scene ke liye real scene image required hai; blank placeholder render disabled hai.")
    subtitles = subtitles or []
    if subtitles and len(subtitles) != len(scenes):
        raise ValueError("Subtitle lines ki sankhya scenes ke barabar honi chahiye.")
    if any(not isinstance(line, str) or len(line) > 1000 for line in subtitles):
        raise ValueError("Har subtitle line text hona chahiye aur 1000 characters se chhoti honi chahiye.")
    if image_paths and len(image_paths) != len(scenes):
        raise ValueError("Scene images ki sankhya scenes ke barabar honi chahiye.")
    for image_path in image_paths:
        _validate_scene_image(image_path)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output_path = OUTPUT_DIR / f"{video_id}.mp4"
    temporary_output_path = None
    try:
        # Render privately; publish only after FFprobe verification.
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".sintu-render-", suffix=".mp4",
            dir=OUTPUT_DIR, delete=False,
        ) as temporary_output:
            temporary_output_path = Path(temporary_output.name)
        with tempfile.TemporaryDirectory(prefix="sintu-render-") as temp:
            work = Path(temp)
            lines = []
            for index, scene in enumerate(scenes, start=1):
                frame = work / f"frame-{index:03d}.png"
                source_image = image_paths[index - 1] if image_paths else None
                _make_frame(frame, title, scene, index, len(scenes), source_image, None, width, height)
                lines.append(f"file '{frame.as_posix()}'")
                lines.append(f"duration {seconds_per_scene}")
            lines.append(f"file '{(work / f'frame-{len(scenes):03d}.png').as_posix()}'")
            concat = work / "frames.txt"
            concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
            duration = len(scenes) * seconds_per_scene
            sfx_result = None
            if sound_effects_enabled and sound_effects_volume > 0:
                from .sound_effects import generate_scene_sound_effects
                sfx_result = generate_scene_sound_effects(
                    scenes, [seconds_per_scene] * len(scenes),
                    work / "sintu-sound-effects.wav", 1.0,
                )
            sfx_path = sfx_result["path"] if sfx_result else None
            filters = []
            if transition == "fade":
                # Chaining multiple timestamped fade filters after the concat
                # demuxer resets timestamps on some FFmpeg builds and can turn
                # the entire output black. Use one deterministic opening fade
                # and one closing fade; scene changes remain clean hard cuts.
                filters.extend([
                    "fade=t=in:st=0:d=0.35",
                    f"fade=t=out:st={max(0, duration - 0.35)}:d=0.35",
                ])
            motion_filter = _storyboard_motion_filter(
                motion, width, height, fps, seconds_per_scene
            )
            if motion_filter:
                filters.insert(0, motion_filter)
            # The concat demuxer emits one timestamped packet per still image. Without an fps filter,
            # FFmpeg writes only one frame per scene while audio/container duration spans the full timeline.
            # Expand the still-image timestamps into a continuous CFR stream before motion/fade filters.
            video_filter_parts = [f"fps={fps}", *filters]
            subtitle_file, subtitle_filter = _create_subtitle_track(
                work, subtitles, [seconds_per_scene] * len(scenes), height, ffmpeg
            )
            if subtitle_filter:
                video_filter_parts.append(subtitle_filter)
            video_filter = ",".join(video_filter_parts)
            command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                       "-f", "concat", "-safe", "0", "-i", str(concat)]
            audio_tracks = []
            next_audio_index = 1
            if audio_path:
                command += ["-i", str(audio_path)]
                audio_tracks.append(("voice", next_audio_index))
                next_audio_index += 1
            if music_path:
                command += ["-stream_loop", "-1", "-i", str(music_path)]
                audio_tracks.append(("music", next_audio_index))
                next_audio_index += 1
            if sfx_path:
                command += ["-i", str(sfx_path)]
                audio_tracks.append(("sfx", next_audio_index))
                next_audio_index += 1
            if audio_tracks:
                audio_filters, mix_labels = [], []
                for kind, input_index in audio_tracks:
                    label = kind
                    if kind == "music":
                        audio_filters.append(
                            f"[{input_index}:a]aresample=48000,volume={music_volume},"
                            f"afade=t=in:st=0:d=1.5,afade=t=out:st={max(0, duration - 2)}:d=2,"
                            f"atrim=duration={duration}[{label}]"
                        )
                    else:
                        track_volume = 1.0 if kind == "voice" else sound_effects_volume
                        audio_filters.append(
                            f"[{input_index}:a]aresample=48000,volume={track_volume},"
                            f"apad,atrim=duration={duration}[{label}]"
                        )
                    mix_labels.append(f"[{label}]")
                audio_filters.append(
                    "".join(mix_labels) +
                    f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=2,"
                    f"apad,atrim=duration={duration}[aout]"
                )
                command += ["-filter_complex", ";".join(audio_filters),
                            "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
            else:
                command += ["-map", "0:v:0", "-an"]
            if video_filter:
                command += ["-vf", video_filter]
            # The concat demuxer needs the duplicated final still to establish the last
            # frame duration. Include one frame interval; otherwise -t cuts that
            # duplicate at exactly the timeline boundary and can leave only one frame.
            command += ["-t", f"{duration + (1 / fps):.6f}", "-c:v", "libx264", "-preset", preset,
                        "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", str(fps),
                        "-movflags", "+faststart", "-threads", "2", str(temporary_output_path)]
            completed = render_process.run_render_process(command, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False)
            if completed.returncode != 0 or not temporary_output_path.is_file():
                detail = (completed.stderr or "FFmpeg render failed")[-1200:]
                raise RenderFailed(detail)
            verified = _verify_rendered_output(
                temporary_output_path, width, height, duration,
                require_audio=bool(audio_path or music_path or sfx_path),
                expected_fps=fps, minimum_motion_ratio=0.60,
            )
            os.replace(temporary_output_path, output_path)
            temporary_output_path = None
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        if temporary_output_path is not None:
            temporary_output_path.unlink(missing_ok=True)
        raise RenderFailed(f"Video render {RENDER_TIMEOUT_SECONDS}s timeout par ruk gaya. Phone par background apps band karke ya kam scenes/resolution ke saath dobara try karein.") from None
    except Exception:
        output_path.unlink(missing_ok=True)
        if temporary_output_path is not None:
            temporary_output_path.unlink(missing_ok=True)
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
        "audio": "+".join([label for label, enabled in (("voiceover", audio_path), ("music", music_path), ("sound-effects", sfx_path)) if enabled]) or "none",
        "music": bool(music_path),
        "music_volume": music_volume if music_path else None,
        "sound_effects": bool(sfx_path),
        "sound_effect_cue_count": sfx_result["cue_count"] if sfx_result else 0,
        "transition": transition,
        "motion": motion,
        "scene_images": len(image_paths),
        "motion_audit": (verified or {}).get("motion_audit"),
        "quality_report": verified,
        "subtitles_burned_in": bool(subtitle_file),
        "brand_watermark": "SINTU AI YOUTUBE STUDIO",
        "format": "MP4 / H.264",
        "note": "Clean generated scene imagery with mandatory SINTU branding, optional narration/music and a separate timed subtitle track burned in only when supplied.",
    }


def render_ai_clips(video_paths: list[Path], audio_path: Path | None = None,
                    music_path: Path | None = None, music_volume: float = 0.18,
                    subtitles: list[str] | None = None, transition: str = "cut", transitions: list[str] | None = None,
                    clip_audio_volumes: list[float] | None = None, resolution: str = "720x1280",
                    fps: int = 30, quality: str = "high",
                    scene_descriptions: list[str] | None = None,
                    sound_effects_enabled: bool = False, sound_effects_volume: float = 0.18) -> dict:
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
    if not isinstance(sound_effects_enabled, bool) or not 0.0 <= sound_effects_volume <= 1.0:
        raise ValueError("Sound effects enable flag ya volume invalid hai.")
    if scene_descriptions is not None and len(scene_descriptions) != len(video_paths):
        raise ValueError("Scene descriptions ki sankhya AI clips ke barabar honi chahiye.")
    if transition not in {"cut", "fade"}:
        raise ValueError("Transition cut ya fade hona chahiye.")
    transitions = transitions or [transition] * len(video_paths)
    if len(transitions) != len(video_paths) or any(x not in {"cut", "fade"} for x in transitions):
        raise ValueError("Har clip ke liye cut ya fade transition required hai.")
    clip_audio_volumes = clip_audio_volumes or [0.25] * len(video_paths)
    if len(clip_audio_volumes) != len(video_paths) or any(not isinstance(v, (int, float)) or not 0 <= v <= 2 for v in clip_audio_volumes):
        raise ValueError("Har clip ka source audio volume 0 se 2 (0–200%) hona chahiye.")
    subtitles = subtitles or []
    if subtitles and len(subtitles) != len(video_paths):
        raise ValueError("Subtitle lines ki sankhya AI clips ke barabar honi chahiye.")
    if any(not isinstance(line, str) or len(line) > 1000 for line in subtitles):
        raise ValueError("Har subtitle line text hona chahiye aur 1000 characters se chhoti honi chahiye.")
    for path in video_paths:
        _validate_source_video(path)
    if audio_path:
        _validate_audio_file(audio_path, "Voiceover audio")
    if music_path:
        _validate_audio_file(music_path, "Background music")

    clip_info = []
    total_duration = 0.0
    for path in video_paths:
        probe = render_process.run_render_process(
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
    sfx_result = None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    video_id = uuid.uuid4().hex
    output_path = OUTPUT_DIR / f"{video_id}.mp4"
    temporary_output_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".sintu-ai-join-", suffix=".mp4",
            dir=OUTPUT_DIR, delete=False,
        ) as temporary_output:
            temporary_output_path = Path(temporary_output.name)
        with tempfile.TemporaryDirectory(prefix="sintu-ai-join-") as temp:
            work = Path(temp)
            if sound_effects_enabled and sound_effects_volume > 0:
                from .sound_effects import generate_scene_sound_effects
                sfx_result = generate_scene_sound_effects(
                    scene_descriptions or ["" for _ in video_paths],
                    [item["duration"] for item in clip_info],
                    work / "sintu-sound-effects.wav",
                    1.0,
                )
            command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-filter_complex_threads", "1"]
            brand_path = work / "sintu-watermark.png"
            _make_watermark_image(width=max(180, int(width * 0.22)), height=max(44, int(width * 0.05))).save(brand_path, format="PNG")
            subtitle_file, subtitle_filter = _create_subtitle_track(
                work, subtitles, [item["duration"] for item in clip_info], height, ffmpeg
            )
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
            next_index += 1
            sound_effect_index = None
            if sfx_result:
                command += ["-i", str(sfx_result["path"])]
                sound_effect_index = next_index

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
            video_map = "[vbrand]"
            if subtitle_filter:
                filters.append(f"[vbrand]{subtitle_filter}[vsub]")
                video_map = "[vsub]"
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
            if sound_effect_index is not None:
                filters.append(
                    f"[{sound_effect_index}:a:0]volume={sound_effects_volume},aresample=48000,"
                    f"apad,atrim=duration={total_duration:.3f}[sfx]"
                )
                mix_labels.append("[sfx]")
            filters.append("".join(mix_labels) + f"amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=2,apad,atrim=duration={total_duration:.3f}[aout]")

            command += ["-filter_complex", ";".join(filters), "-map", video_map, "-map", "[aout]",
                        "-c:v", "libx264", "-threads", str(_ffmpeg_thread_count()), "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{total_duration:.3f}",
                        "-movflags", "+faststart", str(temporary_output_path)]
            completed = render_process.run_render_process(command, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS, check=False)
            if completed.returncode != 0 or not temporary_output_path.is_file():
                detail = (completed.stderr or "FFmpeg AI clip assembly failed")[-1600:]
                raise RenderFailed(detail)
            verified = _verify_rendered_output(
                temporary_output_path, width, height, total_duration,
                require_audio=True, expected_fps=fps, minimum_motion_ratio=0.40,
            )
            os.replace(temporary_output_path, output_path)
            temporary_output_path = None
    except subprocess.TimeoutExpired:
        output_path.unlink(missing_ok=True)
        if temporary_output_path is not None:
            temporary_output_path.unlink(missing_ok=True)
        raise RenderFailed("AI clips assemble karne mein timeout ho gaya.") from None
    except Exception:
        output_path.unlink(missing_ok=True)
        if temporary_output_path is not None:
            temporary_output_path.unlink(missing_ok=True)
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
        "audio": "source" + ("+voiceover" if audio_path else "") + ("+music" if music_path else "") + ("+sound-effects" if sfx_result else ""),
        "music": bool(music_path),
        "music_volume": music_volume if music_path else None,
        "sound_effects": bool(sfx_result),
        "sound_effect_cue_count": sfx_result["cue_count"] if sfx_result else 0,
        "transition": transition,
        "motion": "source AI clip motion",
        "motion_audit": (verified or {}).get("motion_audit"),
        "scene_images": 0,
        "subtitles_burned_in": bool(subtitle_file),
        "brand_watermark": "SINTU AI YOUTUBE STUDIO",
        "format": "MP4 / H.264",
        "note": "Original clip audio is retained at reduced ambient level and mixed with optional voiceover/music. SINTU branding and any supplied timed subtitle track are burned into the final output. Fade mode fades each clip at its boundaries; it is not a cross-dissolve."
    }


def render_mixed_timeline(items: list[dict], title: str, scenes: list[str],
                          seconds_per_scene: int = 4, audio_path: Path | None = None,
                          music_path: Path | None = None, music_volume: float = 0.18,
                          subtitles: list[str] | None = None, transition: str = "cut",
                          transitions: list[str] | None = None, resolution: str = "720x1280",
                          fps: int = 30, quality: str = "high",
                          sound_effects_enabled: bool = False,
                          sound_effects_volume: float = 0.18) -> dict:
    """Create one ordered timeline from generated still images and AI video clips."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RendererUnavailable("FFmpeg server par installed nahi hai.")
    width, height, _, _ = _render_settings(resolution, fps, quality)
    if not items or len(items) > 25 or len(items) != len(scenes):
        raise ValueError("Timeline mein 1 se 25 items hon aur har item ka scene text ho.")
    if not 2 <= seconds_per_scene <= 12:
        raise ValueError("Still image duration 2 se 12 seconds honi chahiye.")
    if not isinstance(sound_effects_enabled, bool) or not 0.0 <= sound_effects_volume <= 1.0:
        raise ValueError("Sound effects enable flag ya volume invalid hai.")
    subtitles = subtitles or []
    if subtitles and len(subtitles) != len(items):
        raise ValueError("Mixed timeline subtitle lines ki sankhya timeline items ke barabar honi chahiye.")
    if any(not isinstance(line, str) or len(line) > 1000 for line in subtitles):
        raise ValueError("Har subtitle line text hona chahiye aur 1000 characters se chhoti honi chahiye.")
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
                probe=render_process.run_render_process([ffprobe,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,timeout=30,check=False)
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
                command=[ffmpeg,"-y","-hide_banner","-loglevel","error","-ss",f"{trim_start:.3f}","-i",str(path),"-t",f"{segment_duration:.3f}","-map","0:v:0","-map","0:a?","-c:v","libx264","-preset","veryfast","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-ar","48000","-ac","2","-movflags","+faststart",str(segment)]
                completed=render_process.run_render_process(command,capture_output=True,text=True,timeout=min(RENDER_TIMEOUT_SECONDS, 180),check=False)
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
                completed = render_process.run_render_process(
                    [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-loop", "1", "-framerate", "30", "-i", str(frame),
                     "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                     "-t", str(image_duration), "-shortest",
                     "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(segment)],
                    capture_output=True, text=True, timeout=min(RENDER_TIMEOUT_SECONDS, 90), check=False
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
            scene_descriptions=scenes, sound_effects_enabled=sound_effects_enabled,
            sound_effects_volume=sound_effects_volume,
            resolution=resolution, fps=fps, quality=quality
        )
        result["timeline_items"] = len(items)
        result["timeline_order"] = [item["kind"] for item in items]
        result["scene_transitions"] = transitions
        result["clip_audio_volumes"] = [item.get("audio_volume", 0.25) if item["kind"] == "video" else 0.0 for item in items]
        result["scene_durations"] = [item.get("duration") if item["kind"] == "image" else (round(float(item["trim_end"])-float(item.get("trim_start",0)),2) if item.get("trim_end") is not None else None) for item in items]
        result["note"] = "Still images and AI video clips are joined in order. Still-image duration is configurable; video clips can be trimmed by start/end seconds without modifying original source files. Source audio, optional voiceover/music, mandatory SINTU branding, timed subtitles and cut/fade transitions are supported."
        return result
