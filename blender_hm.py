import bpy
import json
import math
import os

# ============================================================================
# Configuration
# ============================================================================

BACKGROUND_IMAGE = "/Users/langdonhuynh/cody-cr/clash_royacado/cr-assets-png/assets/sc/hog-mountain/hg_background.jpg"  # arena floor texture (PNG repo layout)
SCALE_FACTOR     = 3   # how big the scene is (try 3)
FRAME_END        = 60   # animation length in frames (try 60)

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
HOG_MOUNTAIN_DIR = os.path.join(_REPO_ROOT, "cr-assets-png", "assets", "sc", "hog-mountain")
# Flipbooks: each troop uses a folder of ordered .glb poses (same idea as giant_frame_0.glb…).
# Default: assets/giant_3d_model.
# - 3d_models_folder/<name>_run/models/  (your exports; name matches labels_yaml, except ice-spirit → ice_spirits_run)
# - assets/troop_flipbooks/<class_name>/
# - config/troop_flipbooks.json  class id or name -> path under repo root
GIANT_WALK_GLBS_DIR = os.path.join(_REPO_ROOT, "assets", "giant_3d_model")
MODELS3D_FOLDER = os.path.join(_REPO_ROOT, "3d_models_folder")
# labels_yaml "ice-spirit" lives in folder ice_spirits_run (underscore + plural)
_MODELS3D_RUN_OVERRIDES = {
    "ice-spirit": "ice_spirits_run",
}
TROOP_FLIPBOOKS_ROOT = os.path.join(_REPO_ROOT, "assets", "troop_flipbooks")
_TROOP_FLIPBOOK_JSON = os.path.join(_REPO_ROOT, "config", "troop_flipbooks.json")
_flipbook_json_cache: dict | None = None


def _dir_has_glbs(folder: str) -> bool:
    if not os.path.isdir(folder):
        return False
    return any(name.endswith(".glb") for name in os.listdir(folder))


def _repo_path(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(_REPO_ROOT, p))


def _load_flipbook_json_map() -> dict:
    global _flipbook_json_cache
    if _flipbook_json_cache is not None:
        return _flipbook_json_cache
    if not os.path.isfile(_TROOP_FLIPBOOK_JSON):
        _flipbook_json_cache = {}
        return _flipbook_json_cache
    with open(_TROOP_FLIPBOOK_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raw = {}
    _flipbook_json_cache = {str(k): str(v) for k, v in raw.items()}
    return _flipbook_json_cache


def _try_3d_models_run_folder(class_name: str) -> str | None:
    """3d_models_folder/hog-rider_run/models, ice-wizard_run, ice_spirits_run (ice-spirit), skeleton_run, giant_run, …"""
    run_name = _MODELS3D_RUN_OVERRIDES.get(class_name, f"{class_name}_run")
    cand = os.path.join(MODELS3D_FOLDER, run_name, "models")
    if _dir_has_glbs(cand):
        return cand
    return None


def resolve_troop_flipbook_dir(class_name: str, class_id: int) -> str:
    """
    Pick GLB folder: troop_flipbooks.json (id or name), then 3d_models_folder/*_run/models,
    then assets/troop_flipbooks/<class_name>/, else assets/giant_3d_model.
    """
    jmap = _load_flipbook_json_map()
    for key in (str(class_id), class_name):
        if key in jmap:
            cand = _repo_path(jmap[key])
            if _dir_has_glbs(cand):
                return cand
            print(
                f"[troop_flipbook] config key {key!r} -> {jmap[key]!r} has no .glb; trying defaults."
            )

    cand3 = _try_3d_models_run_folder(class_name)
    if cand3:
        return cand3

    conventional = os.path.join(TROOP_FLIPBOOKS_ROOT, class_name)
    if _dir_has_glbs(conventional):
        return conventional

    return GIANT_WALK_GLBS_DIR

# Keyframe time base (see create_walking_animation docstring):
#   video  — default: JSON frame idx is same as processed video (0-based); Blender is 1-based:
#            bl_frame = start_frame + offset + 1 (keeps sync with footage; empty lead-in if spawn is late)
#   track  — each track’s first pose is Blender frame 1 (all tracks overlap; use for hero-only clips)
_CR_BLENDER_TIME_BASE = os.environ.get("CR_BLENDER_TIME_BASE", "video").strip().lower()


def _track_to_blender_frame(start_frame: int, offset: int) -> int:
    """Map inference track sample index → Blender frame (1-based timeline)."""
    if _CR_BLENDER_TIME_BASE == "track":
        return offset + 1
    return int(start_frame) + int(offset) + 1


def _last_motion_blender_frame(start_frame: int, pos_len: int) -> int:
    if _CR_BLENDER_TIME_BASE == "track":
        return pos_len
    return int(start_frame) + int(pos_len)


def _resolve_tracks_json_path() -> str:
    """Override with env CR_TRACKS_JSON (absolute or relative to repo)."""
    env = os.environ.get("CR_TRACKS_JSON", "").strip()
    if env:
        return env if os.path.isabs(env) else os.path.join(_REPO_ROOT, env)
    candidates = [
        os.path.join(_REPO_ROOT, "hog_2_6_med_tracks.json"),
        os.path.join(_REPO_ROOT, "outputs", "tracks", "hog_2_6_start_tracks.json"),
        os.path.join(_REPO_ROOT, "outputs", "tracks", "hog_2_6_start.json"),
        os.path.join(_REPO_ROOT, "outputs", "tracks", "clash_royale_tracking.json"),
        os.path.join(_REPO_ROOT, "clash_royale_tracking.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[1]


TRACKS_JSON_PATH = _resolve_tracks_json_path()


def perception_to_ground(perception_coord):
    """Map inference pixel coords (576×896 crop) onto the textured floor plane."""
    x, y = perception_coord
    perception_floor_w = 576
    perception_floor_h = 896
    mid_w = perception_floor_w / 2
    x1 = x - mid_w
    x2 = x1 / mid_w * 10
    mid_h = perception_floor_h // 2
    y1 = y - mid_h
    y2 = y1 / mid_h * 20
    y2 *= -1
    return x2, y2


# ============================================================================
# Step 1 — Remove the Default Cube
# ============================================================================

def remove_default_cube():
    # Check if the cube exists before trying to remove it
    if 'Cube' in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects['Cube'], do_unlink=True)


# ============================================================================
# Step 2 — Create a Textured Floor
# ============================================================================

def create_floor_plane(image_path, scale):
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Floor texture missing: {image_path}")
    # Create a flat plane at the origin
    bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, 0))
    plane = bpy.context.object   # the new plane is automatically set as active

    # Create a new material and enable node-based editing
    mat = bpy.data.materials.new(name="FloorMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Get the Principled BSDF node (auto-created when use_nodes=True)
    bsdf = nodes["Principled BSDF"]

    # Add an image texture node and load the background image
    tex       = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(image_path)

    # Fix the aspect ratio so the image isn't stretched
    aspect = tex.image.size[0] / tex.image.size[1]
    plane.scale.x *= scale
    plane.scale.y *= scale / aspect

    # Wire the texture into the material: Texture Color → BSDF Base Color
    links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])

    # Attach the material to the plane
    plane.data.materials.append(mat)

    return plane


# ============================================================================
# Step 3 — Import Helpers
# ============================================================================

def import_gltf(filepath):
    # Snapshot existing objects so we can find what the import adds
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    return list(set(bpy.data.objects) - before)


def apply_rotation(obj):
    # You MUST set the active object before calling transform_apply
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(rotation=True)


def import_prop(filepath, name, location, rotation, scale):
    import_gltf(filepath)
    obj = bpy.data.objects[name]   # look up by name Blender assigned

    obj.rotation_mode  = 'XYZ'
    obj.rotation_euler = rotation
    apply_rotation(obj)

    obj.location = location
    obj.scale    = scale
    return obj


def import_prop_at(filepath, location, rotation, scale):
    """Import a GLB and place it without knowing Blender’s internal object name."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"GLB missing: {filepath}")
    new_objects  = import_gltf(filepath)
    mesh_objects = [o for o in new_objects if o.type == "MESH"]
    for o in new_objects:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    if not mesh_objects:
        print(f"No mesh in {filepath}")
        return None
    if len(mesh_objects) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in mesh_objects:
            o.select_set(True)
        bpy.context.view_layer.objects.active = mesh_objects[0]
        bpy.ops.object.join()
        obj = bpy.context.active_object
    else:
        obj = mesh_objects[0]

    obj.rotation_mode  = "XYZ"
    obj.rotation_euler = rotation
    apply_rotation(obj)
    obj.location = location
    obj.scale    = scale
    return obj


# ============================================================================
# Step 4 — Sky
# ============================================================================

def setup_sky():
    world = bpy.context.scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()   # remove default nodes before building our own

    # Create the three nodes we need
    sky = nodes.new("ShaderNodeTexSky")
    bg  = nodes.new("ShaderNodeBackground")
    out = nodes.new("ShaderNodeOutputWorld")

    # Use NISHITA if available, fall back to HOSEK_WILKIE on older Blender
    available    = sky.bl_rna.properties["sky_type"].enum_items.keys()
    sky.sky_type = 'NISHITA' if 'NISHITA' in available else 'HOSEK_WILKIE'
    if sky.sky_type == 'NISHITA':
        sky.air_density = 1.0
    sky.sun_elevation = 0.6   # radians (~0.6 = afternoon sun)
    sky.sun_rotation  = 1.0

    # Wire: Sky Color → Background → World Output Surface
    links.new(sky.outputs["Color"],      bg.inputs["Color"])
    links.new(bg.outputs["Background"], out.inputs["Surface"])
    # Background only exposes Color + Strength (no "String" / placeholder socket names)
    bg.inputs["Strength"].default_value = 3.0

    # Make the sky visible while working in the viewport
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.use_scene_world = True


# ============================================================================
# Step 5 — Walking Animation (Flipbook System)
# ============================================================================

def create_walking_animation(
    models_folder,
    start_pos,
    end_pos,
    start_frame,
    total_frames,
    pos_list,
    frames_per_model=2,
    scale=3,
    facing_default=math.pi,
    track_id=None,
):
    """
    Animate a character walking from start_pos to end_pos using a flipbook
    of GLB pose files stored in models_folder.

    Inference JSON uses 0-based frame indices (first video frame = 0). Blender uses a
    1-based timeline (first frame = 1), so each sample maps as:
      video time base (default):  bl_frame = start_frame + offset + 1
      so pos_list[0] lines up with source frame start_frame on the processed clip.

    If motion looks 'late' with empty Blender time at the start, the unit simply was not
    detected until start_frame — that is not dropped frames. To make every track begin at
    Blender frame 1 instead, set env CR_BLENDER_TIME_BASE=track (multiple units will overlap).

    Unrelated: preprocess crop (crop_and_resize) literally trims top/bottom pixels; that
    can look like the picture is cropped, which is separate from frame indexing.
    """
    model_files = sorted(f for f in os.listdir(models_folder) if f.endswith(".glb"))
    if not model_files:
        print(f"No .glb files found in '{models_folder}'")
        return []

    print(f"Found {len(model_files)} models — animation starts at frame {start_frame}")

    n_seg = max(1, int(total_frames))
    dx = (end_pos[0] - start_pos[0]) / n_seg
    dy = (end_pos[1] - start_pos[1]) / n_seg
    dz = (end_pos[2] - start_pos[2]) / n_seg

    # --- Import all pose models ---
    imported = []
    for i, filename in enumerate(model_files):
        new_objects  = import_gltf(os.path.join(models_folder, filename))
        mesh_objects = [o for o in new_objects if o.type == "MESH"]

        for o in new_objects:
            if o.type != "MESH":
                bpy.data.objects.remove(o, do_unlink=True)

        if not mesh_objects:
            continue

        if len(mesh_objects) > 1:
            bpy.ops.object.select_all(action="DESELECT")
            for o in mesh_objects:
                o.select_set(True)
            bpy.context.view_layer.objects.active = mesh_objects[0]
            bpy.ops.object.join()
            obj = bpy.context.active_object
        else:
            obj = mesh_objects[0]

        tid = track_id if track_id is not None else start_frame
        obj.name = f"Walker_tid{tid}_f{start_frame}_{i:03d}"
        obj.rotation_mode  = "XYZ"
        obj.rotation_euler = (0, 0, facing_default)
        obj.scale          = (scale, scale, scale)
        apply_rotation(obj)
        obj.location      = start_pos
        obj.hide_viewport = True
        obj.hide_render   = True

        imported.append(obj)
        print(f"  Imported: {filename}")
    bpy.context.scene.frame_set(1)
    for obj in imported:
        obj.hide_viewport = True
        obj.hide_render   = True
        obj.keyframe_insert(data_path="hide_viewport")
        obj.keyframe_insert(data_path="hide_render")

    # --- Keyframe visibility and position (Blender frames: 1-based) ---
    n = len(imported)
    heading_z = None
    for offset in range(len(pos_list)):
        bl_frame = _track_to_blender_frame(start_frame, offset)
        active_idx = (offset // frames_per_model) % n
        ground_x, ground_y = perception_to_ground(pos_list[offset])
        position = [ground_x, ground_y, start_pos[2]]

        if offset + 4 < len(pos_list):
            next_x, next_y = perception_to_ground(pos_list[offset + 4])
            dvx = next_x - ground_x
            dvy = next_y - ground_y
        elif offset > 0:
            # Last frame: reuse previous delta
            prev_x, prev_y = perception_to_ground(pos_list[offset - 1])
            dvx = ground_x - prev_x
            dvy = ground_y - prev_y
        else:
            dvx, dvy = 0, 1
        still = False
        if abs(dvx) > 0.001 or abs(dvy) > 0.001:
            if heading_z is None:
                heading_z = math.atan2(dvy, dvx) - math.pi / 2
            else:
                ori_new = math.atan2(dvy, dvx) - math.pi / 2
                heading_z = 0.7 * heading_z + 0.3 * ori_new
        else:
            still = True
            heading_z = facing_default

        bpy.context.scene.frame_set(bl_frame)

        for i, obj in enumerate(imported):
            visible           = (i == active_idx)
            obj.hide_viewport = not visible
            obj.hide_render   = not visible
            obj.keyframe_insert(data_path="hide_viewport")
            obj.keyframe_insert(data_path="hide_render")
            if visible:
                obj.location = position
                obj.rotation_euler = (0, 0, heading_z)
                obj.keyframe_insert(data_path="location")
                obj.keyframe_insert(data_path="rotation_euler")
                if still:
                    heading_z = None
    last_bl_frame = _last_motion_blender_frame(start_frame, len(pos_list))
    bpy.context.scene.frame_set(last_bl_frame + 1)
    for obj in imported:
        obj.hide_viewport = True
        obj.hide_render   = True
        obj.keyframe_insert(data_path="hide_viewport")
        obj.keyframe_insert(data_path="hide_render")
    

    if last_bl_frame > bpy.context.scene.frame_end:
        bpy.context.scene.frame_end = last_bl_frame

    bpy.context.scene.frame_set(1)
    first_bf = _track_to_blender_frame(start_frame, 0) if pos_list else 1
    print(
        f"Animation complete: track_id={track_id} "
        f"{n} pose meshes, Blender frames {first_bf}..{last_bl_frame} "
        f"(inference start_frame={start_frame}, time_base={_CR_BLENDER_TIME_BASE})\n"
    )
    return imported

# ============================================================================
# Main — Run Everything
# ============================================================================

remove_default_cube()
create_floor_plane(BACKGROUND_IMAGE, SCALE_FACTOR)

s = SCALE_FACTOR

# --- Hog Mountain GLBs (paths under cr-assets-png/assets/sc/hog-mountain/) ---
hm = lambda *parts: os.path.join(HOG_MOUNTAIN_DIR, *parts)

# Stadium foundation — below arena floor (matches viewport geometry_0)
import_prop_at(
    hm("stadium_rock.glb"),
    (0, 0, -3.96),
    (0, 0, 0),
    (53.0, 60.0, 24.0),
)

# Bridges — bridge 1 / bridge 2 from viewport
import_prop_at(hm("bridge.glb"), (9, -0.64, 0.28), (0, 0, 0), (4, 4, 4))
import_prop_at(hm("bridge.glb"), (-9.3579, 0.003898, 0.29), (0, 0, 0), (4, 4, 4))

# Towers & buildings
pt = 1.8
ph = 2.0
for loc, rot in [
    ((8, 14, ph), (0, 0, 0)),
    ((-8, 14, ph), (0, 0, 0)),
    ((8, -16, ph), (0, 0, math.pi)),
    ((-8, -16, ph), (0, 0, math.pi)),
]:
    import_prop_at(hm("archer_tower.glb"), loc, rot, (s * pt, s * pt, s * pt))

# Princess / king tower GLBs (same corner layout as archer slots; remove archer imports if you only want these)
pk = pt  # king/princess mesh scale (match archer or tweak)
kh = ph + 0.5  # king sits slightly higher on back row
import_prop_at(hm("blue_princess.glb"), (8, 14, ph), (0, 0, 0), (s * pk, s * pk, s * pk))
import_prop_at(hm("blue_princess.glb"), (-8, 14, ph), (0, 0, 0), (s * pk, s * pk, s * pk))
import_prop_at(hm("red_princess.glb"), (8, -16, ph), (0, 0, math.pi), (s * pk, s * pk, s * pk))
import_prop_at(hm("red_princess.glb"), (-8, -16, ph), (0, 0, math.pi), (s * pk, s * pk, s * pk))
import_prop_at(hm("blue_king_tower.glb"), (0, 19.5, kh), (0, 0, 0), (s * pk, s * pk, s * pk))
import_prop_at(hm("red_king_tower.glb"), (0, -19.5, kh), (0, 0, math.pi), (s * pk, s * pk, s * pk))

# Red buildings — north (+Y); rotation Z from viewport (degrees → radians)
_red_z_L = math.radians(-302)
_red_z_R = math.radians(-416)
import_prop_at(hm("red_building.glb"), (-23, 15, 2), (0, 0, _red_z_L), (16, 16, 16))
import_prop_at(hm("red_building.glb"), (22, 15, 2), (0, 0, _red_z_R), (16, 16, 16))
# Mirrored south (−Y): flip Y; reflect yaw across arena (XZ plane) as π − θ
import_prop_at(
    hm("red_building.glb"),
    (-23, -15, 2),
    (0, 0, math.pi - _red_z_L),
    (16, 16, 16),
)
import_prop_at(
    hm("red_building.glb"),
    (22, -15, 2),
    (0, 0, math.pi - _red_z_R),
    (16, 16, 16),
)

# Rocks / props
import_prop_at(hm("rock_mountain.glb"), (-18, 0, 1), (0, 0, math.pi / 2), (s, s, s))
import_prop_at(hm("gong.glb"), (-15.82, 0, 5.26), (math.radians(0), math.radians(270), math.radians(-178)), (13, 13, 13))

# Hog statues — north row (toward +Y king side)
import_prop_at(hm("hog_statue.glb"), (7.177, 22.5, 6.9006), (0, 0, 0), (-15.0, 15.0, 15.0))
import_prop_at(hm("hog_statue.glb"), (-7.177, 22.5, 6.9006), (0, 0, 0), (15.0, 15.0, 15.0))
# Mirrored south row (−Y); rotate π so statues face into the arena like other south props
import_prop_at(hm("hog_statue.glb"), (-7.177, -22.5, 6.9006), (0, 0, math.pi), (15.0, 15.0, 15.0))
import_prop_at(hm("hog_statue.glb"), (7.177, -22.5, 6.9006), (0, 0, math.pi), (-15.0, 15.0, 15.0))

setup_sky()
bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end = FRAME_END

# --- Walking animations (needs a folder of pose .glb files) ---
# create_walking_animation(
#     models_folder=GIANT_WALK_GLBS_DIR,
#     start_pos=(0, -5, 1),
#     end_pos=(0, 5, 1),
#     start_frame=1,
#     total_frames=60,
#     pos_list=None,
#     scale=s,
#     orientation=math.pi,
# )

print("Scene setup complete!")
print(f"Objects: {[o.name for o in bpy.data.objects]}")


if not os.path.isfile(TRACKS_JSON_PATH):
    raise FileNotFoundError(
        f"Tracks JSON not found: {TRACKS_JSON_PATH}\n"
        "Run inference (e.g. python3 run_inference_simple.py) or set CR_TRACKS_JSON "
        "to your *_tracks.json path."
    )
print(f"Loading tracks from {TRACKS_JSON_PATH}")
with open(TRACKS_JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)
tracks = data["tracks"]

with open(os.path.join(_REPO_ROOT, "config", "labels_yaml.json"), encoding="utf-8") as file:
    labels = json.load(file)


ignore_terms = ["-tower","-bar", "-symbol"]
ignore_classes = ["elixir", "bar", "clock","bar-level","emote"]

for track in tracks:
    class_id = track["class_id"]
    class_name = labels[str(class_id)]
    if class_name in ignore_classes:
        continue
    if any(term in class_name for term in ignore_terms):
        continue

    position_list = track["positions"]
    if not position_list:
        continue

    scale = 3.5
    if class_name == "skeleton":
        scale = 1

    start_f = int(track["start_frame"])
    end_f = int(track["end_frame"])
    span = max(1, end_f - start_f)

    models_folder = resolve_troop_flipbook_dir(class_name, class_id)
    if models_folder != GIANT_WALK_GLBS_DIR:
        print(f"  troop_model {class_name!r} id={class_id} -> {models_folder}")

    create_walking_animation(
        models_folder=models_folder,
        start_pos=[-9, 0, 1.7],
        end_pos=[-9, 12, 1.7],
        start_frame=start_f,
        total_frames=span,
        pos_list=position_list,
        frames_per_model=2,
        scale=scale,
        facing_default=math.pi,
        track_id=int(track.get("track_id", start_f)),
    )