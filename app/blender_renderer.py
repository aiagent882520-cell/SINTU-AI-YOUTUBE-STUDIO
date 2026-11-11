"""Free local Blender scene builder and MP4 renderer.

Accepts validated JSON scene descriptions only; user input is never executed as Python.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("SINTU_DATA_DIR", str(ROOT))).expanduser().resolve()
BLENDER_DIR = DATA_DIR / "blender_renders"
ALLOWED_SHAPES = {"cube", "sphere", "cylinder", "cone", "torus", "monkey", "text"}
MAX_OBJECTS = 20

class BlenderUnavailable(Exception):
    pass

class BlenderRenderFailed(Exception):
    pass

def blender_executable():
    configured = os.getenv("BLENDER_EXECUTABLE", "blender")
    return shutil.which(configured) or (configured if Path(configured).is_file() else None)

def blender_status():
    executable = blender_executable()
    return {"available": bool(executable), "executable": executable,
            "engine": "Blender (free/open-source)", "output": "MP4 / H.264",
            "note": "Install Blender and put blender on PATH or set BLENDER_EXECUTABLE."}

def validate_scene(title, objects, duration_seconds, resolution, fps):
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError("Scene title must contain 1 to 100 characters.")
    if not isinstance(objects, list) or not 1 <= len(objects) <= MAX_OBJECTS:
        raise ValueError("A scene needs 1 to 20 objects.")
    if not isinstance(duration_seconds, int) or isinstance(duration_seconds, bool) or not 1 <= duration_seconds <= 30:
        raise ValueError("3D scene duration must be 1 to 30 seconds.")
    if resolution not in {"720x1280", "1080x1920", "1080x1080", "1280x720", "1920x1080"}:
        raise ValueError("Unsupported Blender output resolution.")
    if fps not in {24, 30, 60}:
        raise ValueError("FPS must be 24, 30 or 60.")
    cleaned=[]
    for item in objects:
        if not isinstance(item, dict):
            raise ValueError("Each 3D object must be a JSON object.")
        shape=str(item.get("shape","cube")).lower()
        if shape not in ALLOWED_SHAPES:
            raise ValueError("Unsupported 3D primitive: " + shape)
        name=str(item.get("name",shape))[:60]
        location=item.get("location",[0,0,1])
        scale=item.get("scale",[1,1,1])
        color=item.get("color",[0.2,0.45,0.8,1])
        if not isinstance(location,list) or len(location)!=3 or any(not isinstance(x,(int,float)) or abs(x)>100 for x in location):
            raise ValueError("Object location must contain 3 numbers within ±100.")
        if not isinstance(scale,list) or len(scale)!=3 or any(not isinstance(x,(int,float)) or not 0.05<=x<=20 for x in scale):
            raise ValueError("Object scale must contain 3 numbers between 0.05 and 20.")
        if not isinstance(color,list) or len(color) not in {3,4} or any(not isinstance(x,(int,float)) or not 0<=x<=1 for x in color):
            raise ValueError("Object color must contain 3 or 4 normalized values.")
        cleaned.append({"shape":shape,"name":name,"location":list(location),"scale":list(scale),"color":list(color)})
    return {"title":title.strip(),"objects":cleaned,"duration_seconds":duration_seconds,
            "resolution":resolution,"fps":fps}

BLENDER_SCRIPT = r'''
import bpy, json, math, sys
from mathutils import Vector
args = sys.argv[sys.argv.index("--")+1:]
def arg(name):
    return args[args.index(name)+1]
with open(arg("--config"), "r", encoding="utf-8") as f:
    cfg = json.load(f)
out = arg("--output")
scene = bpy.context.scene
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except Exception:
    scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = [int(x) for x in cfg["resolution"].split("x")]
scene.render.resolution_percentage = 100
scene.render.fps = cfg["fps"]
scene.frame_start = 1
scene.frame_end = cfg["duration_seconds"] * cfg["fps"]
scene.world.color = (0.025, 0.03, 0.06)
def material(name, rgba, metallic=0.15):
    m = bpy.data.materials.new(name)
    m.diffuse_color = tuple(rgba if len(rgba)==4 else rgba+[1.0])
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = m.diffuse_color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = 0.34
    return m
for index, item in enumerate(cfg["objects"]):
    shape, loc, scale = item["shape"], item["location"], item["scale"]
    if shape == "cube": bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    elif shape == "sphere": bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1, location=loc)
    elif shape == "cylinder": bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=1, depth=2, location=loc)
    elif shape == "cone": bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=1, depth=2, location=loc)
    elif shape == "torus": bpy.ops.mesh.primitive_torus_add(major_segments=48, minor_segments=12, location=loc)
    elif shape == "monkey": bpy.ops.mesh.primitive_monkey_add(location=loc)
    else:
        bpy.ops.object.text_add(location=loc)
        bpy.context.object.data.body = item["name"]
        bpy.context.object.data.extrude = 0.04
    obj = bpy.context.object
    obj.name = item["name"]
    obj.scale = scale
    if obj.type == "MESH":
        obj.data.materials.append(material("SINTU_Material_"+str(index), item["color"]))
        for polygon in obj.data.polygons: polygon.use_smooth = True
    obj.rotation_euler[2] = 0
    obj.keyframe_insert(data_path="rotation_euler", frame=1)
    obj.rotation_euler[2] = math.tau
    obj.keyframe_insert(data_path="rotation_euler", frame=scene.frame_end)
    obj.location.z = loc[2] + 0.25
    obj.keyframe_insert(data_path="location", frame=1)
    obj.location.z = loc[2]
    obj.keyframe_insert(data_path="location", frame=scene.frame_end)
bpy.ops.mesh.primitive_plane_add(size=200, location=(0,0,-0.15))
floor = bpy.context.object
floor.name = "SINTU_Background_Floor"
floor.data.materials.append(material("SINTU_Floor", [0.025,0.035,0.06,1], 0.05))
bpy.ops.object.camera_add(location=(8,-11,7))
camera = bpy.context.object
camera.data.lens = 48
camera.rotation_euler = (Vector((0,0,1.2))-camera.location).to_track_quat("-Z","Y").to_euler()
scene.camera = camera
camera.location = (8,-11,7)
camera.keyframe_insert(data_path="location", frame=1)
camera.location = (7,-10,6.3)
camera.keyframe_insert(data_path="location", frame=scene.frame_end)
for name, location, energy, size in [
    ("SINTU_Key",(4,-5,8),1800,6),("SINTU_Fill",(-5,-2,4),900,5),("SINTU_Rim",(1,5,6),1500,4)
]:
    bpy.ops.object.light_add(type="AREA", location=location)
    light=bpy.context.object; light.name=name; light.data.energy=energy; light.data.shape="DISK"; light.data.size=size
    light.rotation_euler=(Vector((0,0,1))-light.location).to_track_quat("-Z","Y").to_euler()
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.ffmpeg.ffmpeg_preset = "GOOD"
scene.render.filepath = out
scene.render.use_file_extension = True
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"
scene.frame_set(1)
bpy.ops.render.render(animation=True)
'''

def render_scene(title, objects, duration_seconds=8, resolution="1280x720", fps=24):
    cfg = validate_scene(title, objects, duration_seconds, resolution, fps)
    executable = blender_executable()
    if not executable:
        raise BlenderUnavailable("Blender not installed. Install the free Blender desktop app and add blender to PATH.")
    BLENDER_DIR.mkdir(parents=True, exist_ok=True)
    render_id = uuid.uuid4().hex
    job_dir = BLENDER_DIR / render_id
    job_dir.mkdir(parents=True, exist_ok=False)
    config_path = job_dir / "scene.json"
    script_path = job_dir / "render_scene.py"
    output_path = job_dir / (render_id + ".mp4")
    config_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    script_path.write_text(BLENDER_SCRIPT, encoding="utf-8")
    command = [str(executable), "--background", "--factory-startup", "--python", str(script_path),
               "--", "--config", str(config_path), "--output", str(output_path)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    except subprocess.TimeoutExpired:
        raise BlenderRenderFailed("Blender render timed out after 30 minutes.") from None
    except OSError:
        raise BlenderUnavailable("Blender executable could not be started.") from None
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size < 16:
        detail = (completed.stderr or completed.stdout or "")[-1200:]
        raise BlenderRenderFailed("Blender render failed. " + detail)
    return {"render_id":render_id,"video_id":render_id,"url":f"/api/blender-renders/{render_id}",
            "filename":output_path.name,"format":"MP4 / H.264","size_bytes":output_path.stat().st_size,
            "duration_seconds":duration_seconds,"resolution":resolution,"fps":fps,
            "provider":"Blender (local, free)","local":True,"note":"3D scene rendered locally. Review output and assets before publishing."}
