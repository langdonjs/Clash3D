import bpy
import math
import os
import json


import sys
print(sys.executable)

import yaml

# ============================================================================
# Configuration
# ============================================================================

BACKGROUND_IMAGE = "Clash-Royale-Detection-Dataset/images/segment/backgrounds/background07.jpg"
SCALE_FACTOR     = 3
FRAME_END        = 60

# ============================================================================
# Scene Helpers
# ============================================================================

with open("game_tracks.json", 'r') as f:
    data = json.load(f)
tracks = data["tracks"]

# Open the file and load its contents
with open('config/ClashRoyale_detection_fixed.yaml', 'r') as file:
    yaml_data = yaml.safe_load(file)
labels = yaml_data["names"]


ignore_terms = ["-tower","-bar", "-symbol"]
ignore_classes = ["elixir", "bar", "clock","bar-level","emote"]


def perception_to_ground(perception_coord):
    x,y = perception_coord
    perception_floorW = 490
    perception_floorH = 840

    blender_floorW_half = 40 //2
    blender_floorH_half = 20 //2
    
    mid_w = perception_floorW/2
    x1 = x - mid_w
    x2 = x1 / mid_w * 10

    mid_h = perception_floorH//2
    y1 = y - mid_h
    y2 = y1 / mid_h * 20
    y2*=-1

    return x2,y2


    

def remove_default_cube():
    if "Cube" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects["Cube"], do_unlink=True)


def create_floor_plane(image_path, scale):
    bpy.ops.mesh.primitive_plane_add(size=10, location=(0, 0, 0))
    plane = bpy.context.object

    mat = bpy.data.materials.new(name="FloorMaterial")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    tex       = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(image_path)
    bsdf      = nodes["Principled BSDF"]

    aspect = tex.image.size[0] / tex.image.size[1]
    plane.scale.x *= scale
    plane.scale.y *= scale / aspect

    links.new(bsdf.inputs["Base Color"], tex.outputs["Color"])
    plane.data.materials.append(mat)
    return plane


def setup_sky():
    world = bpy.context.scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    sky = nodes.new("ShaderNodeTexSky")
    bg  = nodes.new("ShaderNodeBackground")
    out = nodes.new("ShaderNodeOutputWorld")

    available    = sky.bl_rna.properties["sky_type"].enum_items.keys()
    sky.sky_type = "NISHITA" if "NISHITA" in available else "HOSEK_WILKIE"
    if sky.sky_type == "NISHITA":
        sky.air_density = 1.0
    sky.sun_elevation = 0.6
    sky.sun_rotation  = 1.0

    links.new(sky.outputs["Color"],     bg.inputs["Color"])
    links.new(bg.outputs["Background"], out.inputs["Surface"])

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.use_scene_world = True

# ============================================================================
# Model Import Helpers
# ============================================================================

def import_gltf(filepath):
    """Import a GLB file and return all newly created objects."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=filepath)
    return list(set(bpy.data.objects) - before)


def apply_rotation(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(rotation=True)


def import_prop(filepath, name, location, rotation, scale):
    """Import a GLB prop and place it in the scene."""
    import_gltf(filepath)
    obj = bpy.data.objects[name]
    obj.rotation_mode  = "XYZ"
    obj.rotation_euler = rotation
    apply_rotation(obj)
    obj.location = location
    obj.scale    = scale
    return obj

# ============================================================================
# Walking Animation
# ============================================================================

#def perception_to_ground(x,y):


def create_walking_animation(
    models_folder,
    start_pos,
    end_pos,
    start_frame,
    total_frames,
    pos_list,
    frames_per_model=2,
    scale=3,
    orientation=math.pi,
):
    """
    Animate a character walking from start_pos to end_pos using a flipbook
    of GLB pose files stored in models_folder.
    """
    model_files = sorted(f for f in os.listdir(models_folder) if f.endswith(".glb"))
    if not model_files:
        print(f"No .glb files found in '{models_folder}'")
        return []

    print(f"Found {len(model_files)} models — animation starts at frame {start_frame}")

    dx = (end_pos[0] - start_pos[0]) / total_frames
    dy = (end_pos[1] - start_pos[1]) / total_frames
    dz = (end_pos[2] - start_pos[2]) / total_frames

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

        obj.name           = f"Walker_{start_frame}_{i:03d}"
        obj.rotation_mode  = "XYZ"
        obj.rotation_euler = (0, 0, orientation)
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

    # --- Keyframe visibility and position ---
    n = len(imported)
    frame_ix = 0
    orientation = None
    for frame in range(start_frame, start_frame + len(pos_list)):
        offset     = frame - start_frame
        frame_ix+=1
        active_idx = (offset // frames_per_model) % n
        print(len(pos_list), total_frames, frame_ix, offset)
        ground_x, ground_y = perception_to_ground(pos_list[offset])
        position = [ground_x, ground_y, start_pos[2]]
        #print(position)
        #position   = (
        #    start_pos[0] + offset * dx,
        #    start_pos[1] + offset * dy,
        #    start_pos[2] + offset * dz,
        #)

        if offset + 4 < len(pos_list):
            next_x, next_y = perception_to_ground(pos_list[offset + 4])
            dx = next_x - ground_x
            dy = next_y - ground_y
        elif offset > 0:
            # Last frame: reuse previous delta
            prev_x, prev_y = perception_to_ground(pos_list[offset - 1])
            dx = ground_x - prev_x
            dy = ground_y - prev_y
        else:
            dx, dy = 0, 1  # fallback if only one position
        still = False
        if abs(dx) > 0.001 or abs(dy) > 0.001:  # avoid jitter when stationary
            if orientation is None:
                orientation = math.atan2(dy, dx) - math.pi / 2
            else:
                ori_new = math.atan2(dy, dx) - math.pi / 2
                orientation = 0.7 * orientation + 0.3 * ori_new 
        else:
            #if orientation is None:
            still = True
            orientation = math.pi  # fallback to default

        bpy.context.scene.frame_set(frame)

        for i, obj in enumerate(imported):
            visible           = (i == active_idx)
            obj.hide_viewport = not visible
            obj.hide_render   = not visible
            obj.keyframe_insert(data_path="hide_viewport")
            obj.keyframe_insert(data_path="hide_render")
            if visible:
                obj.location = position
                obj.rotation_euler = (0, 0, orientation)
                obj.keyframe_insert(data_path="location")
                if still:
                    orientation = None
    bpy.context.scene.frame_set(frame+1)
    for obj in imported:
        obj.hide_viewport = True
        obj.hide_render   = True
        obj.keyframe_insert(data_path="hide_viewport")
        obj.keyframe_insert(data_path="hide_render")
    

    end_frame = start_frame + len(pos_list)
    if end_frame > bpy.context.scene.frame_end:
        bpy.context.scene.frame_end = end_frame

    bpy.context.scene.frame_set(1)
    print(f"Animation complete: {n} models over {total_frames} frames\n")
    return imported

# ============================================================================
# Main
# ============================================================================

def main():
    remove_default_cube()
    create_floor_plane(BACKGROUND_IMAGE, SCALE_FACTOR)

    s  = SCALE_FACTOR
    pt = 1.8  # princess/king tower scale multiplier
    ph = 2.2  # tower height (z)
    bs = 5    # bleacher scale multiplier

    # Blender auto-numbers duplicate geometry names (geometry_0, geometry_0.001, ...)
    # glb_num tracks which import we're on so names stay in sync.
    glb_num = 0

    def next_geo():
        nonlocal glb_num
        name = "geometry_0" if glb_num == 0 else (
               f"geometry_0.00{glb_num}" if glb_num < 10 else f"geometry_0.0{glb_num}")
        glb_num += 1
        return name

    # --- Arena structure ---
    import_prop("arena/royal_arena/royal_bridge.glb", next_geo(),
                location=( 9.25, -0.5, 0.5), rotation=(0, 0,  math.pi / 2),
                scale=(s * 1.75, s * 2, s * 1.5))

    import_prop("arena/royal_arena/royal_bridge.glb", next_geo(),
                location=(-9.25, -0.5, 0.5), rotation=(0, 0,  math.pi / 2),
                scale=(s * 1.75, s * 2, s * 1.5))

    import_prop("arena/royal_arena/royalar_0.glb", next_geo(),
                location=( 19,  -0.5, 5), rotation=(-math.pi / 2, 0, math.pi / 2),
                scale=(s * 4.5, s * 4.5, s * 4.5))

    import_prop("arena/royal_arena/royalar_2.glb", next_geo(),
                location=(-19,  -1,   5), rotation=(0, 0, math.pi / 2),
                scale=(s * 4.5, s * 4.5, s * 4.5))

    # --- Princess towers ---
    for loc, rot in [
        (( 9,  15, ph), (0, 0, 0)),
        ((-9,  15, ph), (0, 0, 0)),
        (( 9, -18, ph), (0, 0, math.pi)),
        ((-9, -18, ph), (0, 0, math.pi)),
    ]:
        import_prop("princess_tower.glb", next_geo(),
                    location=loc, rotation=rot, scale=(s * pt, s * pt, s * pt))

    # --- King towers ---
    import_prop("king_tower.glb", next_geo(),
                location=( 0,  20, ph), rotation=(0, 0, 0),
                scale=(s * pt, s * pt, s * pt))

    import_prop("king_tower.glb", next_geo(),
                location=( 0, -20, ph), rotation=(0, 0, math.pi),
                scale=(s * pt, s * pt, s * pt))

    # --- Bleachers ---
    for loc, rot in [
        (( 18,  12, 2), (0, 0, -math.pi / 2)),
        ((-18,  12, 2), (0, 0,  math.pi / 2)),
        (( 18, -12, 2), (0, 0, -math.pi / 2)),
        ((-18, -12, 2), (0, 0,  math.pi / 2)),
    ]:
        import_prop("arena/royal_arena/bleacher.glb", next_geo(),
                    location=loc, rotation=rot, scale=(s * bs, s * bs, s * bs))

    # --- Gate ---
    import_prop("gate.glb", "Cube",
                location=(0, 0, 40), rotation=(0, 0, math.pi / 2),
                scale=(s, s, s))

    setup_sky()
    bpy.context.scene.frame_end = FRAME_END

    print("Scene setup complete!")
    print(f"Objects: {[o.name for o in bpy.data.objects]}\n")

    for track in tracks:
        class_id = track["class_id"]
        class_name = labels[class_id]
        skip = False
        if class_name in ignore_classes:
            skip = True
        for ig in ignore_terms:
            if ig in class_name:
                skip = True
        if skip:
            continue
        print(class_name)
        start_frame = track["start_frame"]
        total_frames = track["end_frame"] - track["start_frame"]

        # --- Walking animations ---
        create_walking_animation(
            models_folder="assets/giant_3d_model",
            start_pos=(-9,  0,  1.7), end_pos=(-9, 12,  1.7), pos_list=track["positions"],
            start_frame=start_frame,  total_frames=total_frames,
            scale=2.5, orientation=math.pi,
        )
    


main()