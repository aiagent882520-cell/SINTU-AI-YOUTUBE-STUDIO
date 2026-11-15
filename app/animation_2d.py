"""Local procedural 2D character animation with frame-by-frame motion and camera moves."""
from pathlib import Path
import math
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw

ANIMATION_FPS = 12
MAX_SCENES = 25
MAX_TOTAL_SECONDS = 300


def _scene_palette(prompt: str):
    text = prompt.lower()
    if any(word in text for word in ("night", "mystery", "रात", "रहस्य")):
        return (18, 28, 58), (36, 50, 88), (32, 42, 55)
    if any(word in text for word in ("forest", "jungle", "जंगल", "वन")):
        return (126, 190, 210), (48, 112, 78), (34, 82, 56)
    if any(word in text for word in ("water", "river", "समुद्र", "नदी", "पानी")):
        return (110, 184, 220), (46, 132, 176), (42, 104, 120)
    return (132, 198, 236), (84, 150, 190), (62, 118, 76)


def _draw_background(prompt: str, width: int, height: int, scene_index: int) -> Image.Image:
    world_width = int(width * 1.48)
    world_height = int(height * 1.12)
    sky, hill, ground = _scene_palette(prompt)
    image = Image.new("RGB", (world_width, world_height), sky)
    draw = ImageDraw.Draw(image)
    horizon = int(world_height * 0.72)

    for band in range(36):
        y0 = int(world_height * band / 36)
        y1 = int(world_height * (band + 1) / 36)
        blend = band / 36
        color = tuple(int(sky[i] * (1 - blend * 0.2) + (220, 228, 235)[i] * blend * 0.2) for i in range(3))
        draw.rectangle((0, y0, world_width, y1), fill=color)

    sun_x = int(world_width * (0.18 + 0.12 * (scene_index % 3)))
    draw.ellipse((sun_x - 42, 85, sun_x + 42, 169), fill=(255, 222, 132))
    draw.ellipse((sun_x - 58, 69, sun_x + 58, 185), outline=(255, 238, 190), width=4)

    for index in range(6):
        x = int(world_width * index / 5)
        peak = horizon - 120 - (index % 3) * 55
        draw.polygon([(x - 180, horizon), (x, peak), (x + 180, horizon)], fill=(86, 130, 154))
    draw.rectangle((0, horizon, world_width, world_height), fill=ground)
    draw.polygon([(0, horizon + 30), (world_width, horizon - 15),
                  (world_width, horizon + 100), (0, horizon + 120)], fill=hill)

    text = prompt.lower()
    if any(word in text for word in ("fort", "castle", "किला", "महल", "गढ़")):
        wall_y = horizon - 180
        draw.rectangle((world_width * 0.28, wall_y, world_width * 0.78, horizon + 8), fill=(166, 139, 112))
        draw.rectangle((world_width * 0.24, wall_y - 28, world_width * 0.82, wall_y + 8), fill=(192, 163, 130))
        for x in (world_width * 0.30, world_width * 0.45, world_width * 0.61, world_width * 0.76):
            draw.rectangle((x, wall_y - 120, x + 65, wall_y + 18), fill=(145, 119, 98))
            draw.polygon([(x - 8, wall_y - 120), (x + 32, wall_y - 170), (x + 73, wall_y - 120)], fill=(111, 87, 76))
        for x in range(int(world_width * 0.32), int(world_width * 0.78), 48):
            draw.rectangle((x, wall_y + 45, x + 18, wall_y + 96), fill=(74, 68, 67))
    elif any(word in text for word in ("forest", "jungle", "जंगल", "वन")):
        for x in range(35, world_width, 105):
            top = horizon - 130 - (x % 3) * 22
            draw.rectangle((x + 28, top + 90, x + 48, horizon + 25), fill=(94, 70, 48))
            draw.ellipse((x - 12, top, x + 92, top + 120), fill=(36, 102, 66))
            draw.ellipse((x + 6, top + 28, x + 112, top + 145), fill=(48, 126, 74))
    elif any(word in text for word in ("city", "शहर", "नगर")):
        for x in range(20, world_width, 110):
            building_h = 110 + (x % 4) * 28
            draw.rectangle((x, horizon - building_h, x + 76, horizon), fill=(92, 112, 132))
            for wy in range(horizon - building_h + 20, horizon - 10, 32):
                for wx in range(x + 12, x + 66, 25):
                    draw.rectangle((wx, wy, wx + 10, wy + 14), fill=(246, 214, 140))
    elif any(word in text for word in ("water", "river", "समुद्र", "नदी", "पानी")):
        draw.rectangle((0, horizon + 22, world_width, horizon + 150), fill=(45, 128, 174))
        for y in range(horizon + 40, horizon + 145, 22):
            for x in range(20, world_width, 125):
                draw.line((x, y, x + 54, y - 2), fill=(180, 224, 232), width=3)

    for x in range(0, world_width, 34):
        draw.ellipse((x, world_height - 38 - (x % 4) * 3, x + 7, world_height - 22), fill=(40, 104, 58))
    return image


def _draw_character(draw: ImageDraw.ImageDraw, x: float, ground_y: float,
                    t: float, scale: float = 1.0) -> None:
    """Draw one consistent cartoon character with walking arms/legs and blinking eyes."""
    s = scale
    stride = math.sin(t * math.tau * 1.15)
    arm = math.sin(t * math.tau * 1.15 + math.pi / 2)
    body_h = 170 * s
    head_r = 38 * s
    hip_y = ground_y - 70 * s
    shoulder_y = ground_y - body_h + 24 * s
    head_y = shoulder_y - head_r - 10 * s
    outline = (42, 48, 56)
    skin = (238, 182, 142)
    shirt = (232, 104, 72)
    trousers = (48, 66, 112)
    shoe = (45, 42, 44)

    # Legs are redrawn each frame; alternating knees create a visible walking cycle.
    left_knee = (x - 24 * s + stride * 20 * s, hip_y + 44 * s)
    right_knee = (x + 24 * s - stride * 20 * s, hip_y + 44 * s)
    left_foot = (x - 38 * s + stride * 34 * s, ground_y - max(0, stride) * 18 * s)
    right_foot = (x + 38 * s - stride * 34 * s, ground_y - max(0, -stride) * 18 * s)
    draw.line((x - 12 * s, hip_y, *left_knee, *left_foot), fill=outline, width=max(5, int(15 * s)))
    draw.line((x + 12 * s, hip_y, *right_knee, *right_foot), fill=outline, width=max(5, int(15 * s)))
    draw.line((left_knee, left_foot), fill=trousers, width=max(4, int(12 * s)))
    draw.line((right_knee, right_foot), fill=trousers, width=max(4, int(12 * s)))
    draw.ellipse((left_foot[0] - 19 * s, left_foot[1] - 6 * s, left_foot[0] + 12 * s, left_foot[1] + 8 * s), fill=shoe)
    draw.ellipse((right_foot[0] - 19 * s, right_foot[1] - 6 * s, right_foot[0] + 12 * s, right_foot[1] + 8 * s), fill=shoe)

    # Arms swing in opposition to the legs.
    left_hand = (x - 72 * s - arm * 24 * s, shoulder_y + 74 * s)
    right_hand = (x + 72 * s + arm * 24 * s, shoulder_y + 74 * s)
    draw.line((x - 25 * s, shoulder_y + 12 * s, left_hand[0], left_hand[1]), fill=outline, width=max(5, int(13 * s)))
    draw.line((x + 25 * s, shoulder_y + 12 * s, right_hand[0], right_hand[1]), fill=outline, width=max(5, int(13 * s)))
    draw.line((x - 25 * s, shoulder_y + 12 * s, left_hand[0], left_hand[1]), fill=skin, width=max(3, int(8 * s)))
    draw.line((x + 25 * s, shoulder_y + 12 * s, right_hand[0], right_hand[1]), fill=skin, width=max(3, int(8 * s)))

    draw.rounded_rectangle((x - 43 * s, shoulder_y, x + 43 * s, hip_y + 12 * s),
                           radius=int(22 * s), fill=shirt, outline=outline, width=max(2, int(4 * s)))
    draw.ellipse((x - head_r, head_y - head_r, x + head_r, head_y + head_r),
                 fill=skin, outline=outline, width=max(2, int(4 * s)))
    draw.arc((x - head_r - 4 * s, head_y - head_r - 12 * s,
              x + head_r + 4 * s, head_y + 12 * s), 180, 355, fill=(58, 42, 36), width=max(4, int(12 * s)))
    blink = int(t * 1.3) % 5 == 0 and (t * 1.3) % 1 < 0.12
    if blink:
        draw.line((x - 14 * s, head_y, x - 4 * s, head_y), fill=outline, width=max(2, int(3 * s)))
        draw.line((x + 6 * s, head_y, x + 16 * s, head_y), fill=outline, width=max(2, int(3 * s)))
    else:
        draw.ellipse((x - 13 * s, head_y - 5 * s, x - 6 * s, head_y + 4 * s), fill=outline)
        draw.ellipse((x + 7 * s, head_y - 5 * s, x + 14 * s, head_y + 4 * s), fill=outline)
    draw.arc((x - 11 * s, head_y + 7 * s, x + 13 * s, head_y + 22 * s), 10, 165, fill=outline, width=max(2, int(3 * s)))


def _render_scene_frames(scene: str, scene_index: int, duration: int, width: int,
                         height: int, output_dir: Path, animation_fps: int = ANIMATION_FPS) -> int:
    background = _draw_background(scene, width, height, scene_index)
    world_width, world_height = background.size
    ground_y = int(world_height * 0.76)
    character_x = int(world_width * 0.66)
    frames = max(2, duration * animation_fps)

    for frame_index in range(frames):
        t = frame_index / animation_fps
        progress = frame_index / max(1, frames - 1)
        frame = background.copy()
        draw = ImageDraw.Draw(frame)
        # A consistent 2D character walks and gestures while the camera slowly pans and zooms.
        _draw_character(draw, character_x + math.sin(t * 0.7) * 10, ground_y, t, scale=1.0)
        zoom = 1.0 + 0.045 * progress
        crop_w = int(width / zoom)
        crop_h = int(height / zoom)
        max_x = max(0, world_width - crop_w)
        pan = progress if scene_index % 2 == 0 else 1.0 - progress
        left = int(max_x * pan)
        top = max(0, min(world_height - crop_h, int((world_height - crop_h) * 0.45)))
        crop = frame.crop((left, top, left + crop_w, top + crop_h))
        crop = crop.resize((width, height), Image.Resampling.LANCZOS)
        crop.save(output_dir / f"frame_{frame_index:05d}.jpg", quality=88, optimize=True)
    return frames


def render_2d_animation_clips(scenes: list[str], seconds_per_scene: int,
                              output_dir: Path, resolution: str = "720x1280",
                              fps: int = 30) -> list[Path]:
    """Render each scene as a short animated 2D cartoon clip with a moving camera."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("2D animation ke liye FFmpeg aur FFprobe required hain.")
    if not scenes or len(scenes) > MAX_SCENES or any(not str(scene).strip() for scene in scenes):
        raise ValueError("2D animation ke liye 1 se 25 non-empty scenes chahiye.")
    if not 2 <= seconds_per_scene <= 12 or len(scenes) * seconds_per_scene > MAX_TOTAL_SECONDS:
        raise ValueError("2D animation duration 2–12 seconds per scene aur 5 minutes total tak supported hai.")
    if resolution not in {"720x1280", "1080x1920", "1080x1080", "1280x720", "1920x1080"}:
        raise ValueError("Unsupported 2D animation resolution.")
    if fps not in {24, 30, 60}:
        raise ValueError("2D animation FPS 24, 30 ya 60 hona chahiye.")
    width, height = (int(part) for part in resolution.split("x"))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clips = []

    for scene_index, scene in enumerate(scenes):
        output_path = output_dir / f"sintu-2d-scene-{scene_index + 1:02d}.mp4"
        with tempfile.TemporaryDirectory(prefix=f"sintu-2d-frames-{scene_index + 1}-") as temp:
            frame_dir = Path(temp)
            _render_scene_frames(str(scene), scene_index, seconds_per_scene, width, height, frame_dir)
            command = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", str(ANIMATION_FPS), "-i", str(frame_dir / "frame_%05d.jpg"),
                "-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "22", "-t", str(seconds_per_scene),
                "-an", "-movflags", "+faststart", str(output_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
            if completed.returncode != 0 or not output_path.is_file():
                output_path.unlink(missing_ok=True)
                detail = (completed.stderr or "2D animation render failed")[-1200:]
                raise RuntimeError(detail)
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if probe.returncode != 0 or not probe.stdout.strip():
            output_path.unlink(missing_ok=True)
            raise RuntimeError("2D animation MP4 verification failed.")
        clips.append(output_path)
    return clips
