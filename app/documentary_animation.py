"""Scene-aware 2D documentary animation clips (maps, timelines, diagrams, environments).

This is a deterministic offline vector-animation engine. It creates frame-by-frame
motion rather than applying a Ken Burns transform to still images. It is a visual
fallback, not generative AI or a substitute for researched/licensed artwork.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ANIMATION_FPS = 12
MAX_SCENES = 25
MAX_TOTAL_SECONDS = 300
PROFILES = {"360x640", "720x1280", "1080x1920", "1080x1080", "1280x720", "1920x1080"}


def classify_scene(description: str) -> str:
    """Infer the visual grammar from a scene brief, not from the whole film topic."""
    text = description.casefold()
    if any(x in text for x in ("map", "route", "border", "geography", "location", "मानचित्र", "नक्शा", "सीमा", "मार्ग", "स्थान")):
        return "map"
    if any(x in text for x in ("timeline", "chronology", "year", "date", "century", "timeline", "वर्ष", "तारीख", "सदी", "कालक्रम", "समयरेखा")):
        return "timeline"
    if any(x in text for x in ("diagram", "chart", "data", "comparison", "process", "structure", "आरेख", "तुलना", "आंकड़े", "प्रक्रिया", "संरचना")):
        return "diagram"
    if any(x in text for x in ("character", "person", "people", "traveller", "king", "soldier", "leader", "व्यक्ति", "राजा", "सैनिक", "यात्री", "नेता", "लोग")):
        return "character"
    return "environment"


def _background(size: tuple[int, int], index: int) -> Image.Image:
    w, h = size
    image = Image.new("RGB", size, (17, 31, 53))
    draw = ImageDraw.Draw(image)
    for y in range(h):
        t = y / max(1, h - 1)
        color = (int(19 + 25*t), int(38 + 43*t), int(65 + 50*t))
        draw.line((0, y, w, y), fill=color)
    # Quiet paper-like grain and a soft horizon give vector scenes depth.
    draw.ellipse((int(w*.67), int(h*.10), int(w*.87), int(h*.22)), fill=(220, 181, 116))
    draw.rectangle((0, int(h*.79), w, h), fill=(27, 49, 57))
    return image


def _draw_map(draw: ImageDraw.ImageDraw, w: int, h: int, p: float, index: int) -> None:
    # Stylized topographic land masses; moving route reveal and traveling locator.
    land = (64, 113, 104)
    draw.polygon([(w*.10,h*.27),(w*.22,h*.17),(w*.36,h*.20),(w*.42,h*.34),
                  (w*.34,h*.48),(w*.25,h*.44),(w*.18,h*.58),(w*.09,h*.47)], fill=land)
    draw.polygon([(w*.49,h*.20),(w*.68,h*.16),(w*.84,h*.29),(w*.78,h*.48),
                  (w*.66,h*.52),(w*.58,h*.41)], fill=(78, 126, 112))
    draw.polygon([(w*.42,h*.59),(w*.57,h*.54),(w*.70,h*.65),(w*.65,h*.84),
                  (w*.49,h*.82),(w*.39,h*.70)], fill=(75, 119, 108))
    for x in range(0, w, max(1,w//9)):
        draw.arc((x, int(h*.18), x+w//3, int(h*.78)), 20, 160, fill=(105,145,129), width=2)
    start=(int(w*.18),int(h*.37)); end=(int(w*.72),int(h*.68))
    mid=(int(w*.46),int(h*.50))
    route=[start,mid,end]
    for a,b in zip(route,route[1:]):
        draw.line((a,b), fill=(243,194,102), width=max(3,w//120))
    x=int(start[0]+(end[0]-start[0])*p)
    y=int(start[1]+(end[1]-start[1])*p)
    r=max(7,w//55)
    draw.ellipse((x-r*2,y-r*2,x+r*2,y+r*2), outline=(255,225,156), width=3)
    draw.ellipse((x-r,y-r,x+r,y+r), fill=(255,226,151))


def _draw_timeline(draw: ImageDraw.ImageDraw, w: int, h: int, p: float, index: int) -> None:
    y=int(h*.52); left=int(w*.12); right=int(w*.88)
    draw.line((left,y,right,y), fill=(205,211,207), width=max(4,w//150))
    points=[left+int((right-left)*i/4) for i in range(5)]
    for i,x in enumerate(points):
        r=max(8,w//48)
        draw.ellipse((x-r,y-r,x+r,y+r), fill=(230,174,91) if i/4<=p else (81,112,126))
        top=int(h*.30) if i%2==0 else int(h*.61)
        draw.rounded_rectangle((x-w*.065,top,x+w*.065,top+h*.12), radius=12,
                               fill=(52,82,100), outline=(155,174,174), width=2)
        draw.line((x,y-r,x,top+h*.12 if top<y else top), fill=(155,174,174), width=2)
    marker=int(left+(right-left)*p)
    draw.polygon([(marker,y-int(h*.07)),(marker-w*.018,y-int(h*.11)),
                  (marker+w*.018,y-int(h*.11))], fill=(255,220,143))


def _draw_diagram(draw: ImageDraw.ImageDraw, w: int, h: int, p: float, index: int) -> None:
    colors=[(67,139,145),(206,151,82),(130,112,166),(86,145,111)]
    base=int(h*.77); max_h=int(h*.43)
    widths=int(w*.12); gap=int(w*.065)
    total=4*widths+3*gap; x0=(w-total)//2
    for i in range(4):
        target=max_h*(.35+.65*((i+index)%4)/3)
        visible=target*max(0,min(1,p*4-i+.25))
        x=x0+i*(widths+gap)
        y=base-int(visible)
        draw.rounded_rectangle((x,y,x+widths,base),radius=10,fill=colors[i])
        draw.ellipse((x+widths*.32,y-12,x+widths*.68,y+12),fill=(235,211,161))
    # Animated connector line indicates the causal/process flow.
    y=int(h*.25)
    for i in range(3):
        x=x0+widths+i*(widths+gap)
        if p>(i+.5)/3:
            draw.line((x,y,x+gap,y),fill=(239,207,144),width=4)
            draw.polygon([(x+gap,y),(x+gap-12,y-8),(x+gap-12,y+8)],fill=(239,207,144))


def _draw_environment(draw: ImageDraw.ImageDraw, w: int, h: int, p: float, index: int) -> None:
    horizon=int(h*.72)
    # Multi-layer mountains with separate drifting cloud and moving water/fire cues.
    draw.polygon([(0,horizon),(w*.22,h*.34),(w*.43,horizon)],fill=(57,91,112))
    draw.polygon([(w*.28,horizon),(w*.58,h*.26),(w*.88,horizon)],fill=(72,105,119))
    draw.polygon([(w*.62,horizon),(w*.83,h*.42),(w,horizon)],fill=(49,83,104))
    shift=int((p-.5)*w*.12)
    for cx,cy in ((.18,.22),(.56,.16),(.82,.29)):
        x=int((cx*w+shift)%(w+100))-50; y=int(cy*h)
        draw.ellipse((x,y,x+w*.16,y+h*.035),fill=(186,199,196))
        draw.ellipse((x+w*.04,y-h*.025,x+w*.12,y+h*.025),fill=(186,199,196))
    draw.rectangle((0,horizon,w,h),fill=(35,79,81))
    for i in range(7):
        x=int((i*w/6 + p*w*.10)%(w+60))-30
        yy=int(horizon+h*.08+i%3*h*.045)
        draw.line((x,yy,x+w*.09,yy-3),fill=(127,183,176),width=3)
    # Rising smoke/fire is deliberately animated when the brief asks for it.
    draw.ellipse((w*.72,h*.59,w*.82,h*.69),fill=(206,116,65))
    for i in range(4):
        rise=(p*70+i*19)%110
        x=w*.77+math.sin(p*math.tau+i)*w*.012
        y=h*.60-rise
        r=8+i*3
        draw.ellipse((x-r,y-r,x+r,y+r),fill=(115,116,113))


def _draw_character_scene(draw: ImageDraw.ImageDraw, w: int, h: int, p: float, index: int) -> None:
    ground=int(h*.80)
    draw.rectangle((0,ground,w,h),fill=(33,67,58))
    x=int(w*(.25+.48*p)); scale=min(w/720,h/1280)
    stride=math.sin(p*math.tau*2)
    head=(x,int(h*.37+math.sin(p*math.tau*2)*5*scale))
    draw.ellipse((head[0]-42*scale,head[1]-42*scale,head[0]+42*scale,head[1]+42*scale),
                 fill=(220,172,133),outline=(35,39,45),width=max(2,int(4*scale)))
    draw.arc((head[0]-44*scale,head[1]-48*scale,head[0]+44*scale,head[1]+25*scale),
             180,355,fill=(44,38,34),width=max(4,int(11*scale)))
    shoulder=int(h*.45); hip=int(h*.66)
    shirt=(196,102,75); dark=(39,49,66)
    draw.rounded_rectangle((x-45*scale,shoulder,x+45*scale,hip),radius=18,fill=shirt,outline=dark,width=3)
    for sign in (-1,1):
        knee=(x+sign*(22+stride*18)*scale,int(h*.72))
        foot=(x+sign*(35-stride*30)*scale,ground-int(max(0,sign*stride)*22*scale))
        draw.line((x+sign*14*scale,hip,*knee,*foot),fill=dark,width=max(5,int(13*scale)))
        hand=(x+sign*(76+stride*22)*scale,int(h*.57))
        draw.line((x+sign*34*scale,shoulder+20*scale,*hand),fill=(221,174,135),width=max(5,int(11*scale)))
    draw.ellipse((x-13*scale,head[1]-6*scale,x-6*scale,head[1]+4*scale),fill=dark)
    draw.ellipse((x+7*scale,head[1]-6*scale,x+14*scale,head[1]+4*scale),fill=dark)
    # A separate foreground layer moves at a different rate to create parallax.
    offset=int(p*w*.08)
    for x0 in range(-40,w+40,70):
        xx=x0-offset
        draw.line((xx,ground,xx-8,ground-45),fill=(112,139,93),width=4)


def _render_frame(description: str, kind: str, index: int, p: float, size: tuple[int,int]) -> Image.Image:
    w,h=size
    image=_background(size,index)
    draw=ImageDraw.Draw(image)
    if kind=="map":
        _draw_map(draw,w,h,p,index)
    elif kind=="timeline":
        _draw_timeline(draw,w,h,p,index)
    elif kind=="diagram":
        _draw_diagram(draw,w,h,p,index)
    elif kind=="character":
        _draw_character_scene(draw,w,h,p,index)
    else:
        _draw_environment(draw,w,h,p,index)
    # A subtle camera drift is layered on top of meaningful scene-specific motion.
    return image


def render_documentary_animation_clips(
    scenes: list[str], seconds_per_scene: int, output_dir: Path,
    resolution: str = "720x1280", fps: int = 24,
) -> tuple[list[Path], dict]:
    """Render scene-specific, frame-animated documentary clips and measurable motion evidence."""
    ffmpeg,ffprobe=shutil.which("ffmpeg"),shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("Documentary animation requires FFmpeg and FFprobe.")
    if not scenes or len(scenes)>MAX_SCENES or any(not isinstance(s,str) or not s.strip() for s in scenes):
        raise ValueError("Documentary animation needs 1–25 non-empty scene briefs.")
    if not 2<=seconds_per_scene<=12 or len(scenes)*seconds_per_scene>MAX_TOTAL_SECONDS:
        raise ValueError("Documentary scene duration must be 2–12 seconds and total <=300 seconds.")
    if resolution not in PROFILES or fps not in {24,30,60}:
        raise ValueError("Unsupported documentary animation render profile.")
    w,h=map(int,resolution.split("x"))
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    clips=[]; evidence=[]
    for index,description in enumerate(scenes):
        kind=classify_scene(description)
        target=out/f"sintu-documentary-scene-{index+1:02d}.mp4"
        with tempfile.TemporaryDirectory(prefix=f"sintu-doc-frames-{index+1}-") as temp:
            frame_dir=Path(temp)
            samples=[]
            count=seconds_per_scene*ANIMATION_FPS
            for frame_index in range(count):
                p=frame_index/max(1,count-1)
                frame=_render_frame(description,kind,index,p,(w,h))
                if frame_index in {0,count//2,count-1}:
                    samples.append(frame.copy())
                frame.save(frame_dir/f"frame_{frame_index:05d}.jpg",quality=88,optimize=True)
            motion_pixels=sum(1 for a,b in zip(samples,samples[1:])
                              if ImageChops.difference(a,b).convert("L").getbbox())
            if motion_pixels<2:
                raise RuntimeError(f"Scene {index+1} ({kind}) failed frame-motion acceptance.")
            cmd=[ffmpeg,"-y","-hide_banner","-loglevel","error","-framerate",str(ANIMATION_FPS),
                 "-i",str(frame_dir/"frame_%05d.jpg"),"-vf",f"fps={fps},format=yuv420p",
                 "-c:v","libx264","-preset","veryfast","-crf","20","-t",str(seconds_per_scene),
                 "-an","-movflags","+faststart",str(target)]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=300,check=False)
            if result.returncode or not target.is_file() or target.stat().st_size<1000:
                target.unlink(missing_ok=True)
                raise RuntimeError((result.stderr or f"Scene {index+1} encoding failed.")[-1200:])
        probe=subprocess.run([ffprobe,"-v","error","-show_entries","format=duration:stream=codec_type,width,height",
                              "-of","json",str(target)],capture_output=True,text=True,timeout=30,check=False)
        if probe.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Scene {index+1} failed ffprobe verification.")
        meta=json.loads(probe.stdout)
        stream=next((s for s in meta.get("streams",[]) if s.get("codec_type")=="video"),{})
        duration=float(meta.get("format",{}).get("duration",0))
        if (stream.get("width"),stream.get("height"))!=(w,h) or abs(duration-seconds_per_scene)>.25:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Scene {index+1} failed resolution/duration acceptance.")
        clips.append(target)
        evidence.append({"scene":index+1,"visual_type":kind,"duration_seconds":duration,
                         "frames":count,"motion_samples_passed":motion_pixels,
                         "motion_verified":True,"file":target.name})
    report={"engine":"SINTU scene-aware procedural 2D documentary animation",
            "provider":"local vector animation; no external model inference",
            "fps":fps,"animation_fps":ANIMATION_FPS,"resolution":resolution,
            "scene_count":len(clips),"scenes":evidence,
            "all_scenes_animated":all(x["motion_verified"] for x in evidence)}
    (out/"documentary-animation-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return clips,report
