"""Convert completed plaster previews into independent adapted-box systems."""

import math
import shutil
import tempfile
from pathlib import Path

from ..object import remove_objects_safely
from ..materials import finalize_slip_casting_foot_materials

import bpy
import mathutils

SYSTEM_KEY = "moldboxer_plaster_silicone_system"
COMPONENT_KEY = "moldboxer_plaster_silicone_component"
RESTART_MOLD_TYPE_KEY = "_moldboxer_plaster_restart_mold_type"


def plaster_sources(scene):
    parts = []
    bases = []
    funnels = []
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if obj.name == "plaster_mold" or obj.name.startswith("plaster_mold_part_"):
            parts.append(obj)
        elif obj.get("moldboxer_slip_casting_vase_base", False) and str(
            obj.get("moldboxer_slip_casting_vase_base_role", "")
        ).upper() == "MALE":
            bases.append(obj)
        elif obj.get("moldboxer_rounded_funnel_reference", False) and (
            obj.get("moldboxer_rounded_funnel_plaster_preview", False)
            or obj.name.startswith("rounded_funnel_plaster_preview_")
        ):
            # Finished, trimmed companions already have the same casting
            # orientation as feet; do not flip them like the main plaster halves.
            funnels.append(obj)
    return [(obj, True) for obj in sorted(parts, key=lambda o: o.name)] + [
        (obj, False) for obj in sorted(bases, key=lambda o: o.name)
    ] + [(obj, False) for obj in sorted(funnels, key=lambda o: o.name)]


def _properties(owner):
    return {
        key: value.to_dict() if hasattr(value, "to_dict") else
        value.to_list() if hasattr(value, "to_list") else value
        for key, value in owner.items()
    }


def _archive_objects(path, objects):
    """Write complete object relationships before removing them from bpy.data."""
    objects = list(objects)
    view_objects = bpy.context.view_layer.objects
    states = []
    for obj in objects:
        in_layer = obj.name in view_objects
        states.append(dict(
            name=obj.name, collections=[
                (collection.name, next((scene.name for scene in bpy.data.scenes
                                        if scene.collection == collection), None))
                for collection in obj.users_collection
            ],
            hidden=obj.hide_get() if in_layer else False,
            selected=obj.select_get() if in_layer else False,
            properties=_properties(obj),
            matrix_world=[list(row) for row in obj.matrix_world],
        ))
    if objects:
        bpy.data.libraries.write(str(path), set(objects))
    return states


def _remove_live_objects():
    bpy.context.view_layer.objects.active = None
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    remove_objects_safely(tuple(bpy.data.objects))
    bpy.context.view_layer.update()


def _load_objects(path, states):
    if not states:
        return []
    with bpy.data.libraries.load(str(path), link=False) as (_available, loaded):
        loaded.objects = [state["name"] for state in states]
    objects = list(loaded.objects)
    for obj, state in zip(objects, states):
        if obj is None:
            raise RuntimeError(f"Could not restore archived object {state['name']}")
        for collection_name, scene_name in state["collections"]:
            collection = (bpy.data.scenes[scene_name].collection if scene_name else
                          bpy.data.collections.get(collection_name))
            if collection is None:
                collection = bpy.data.collections.new(collection_name)
                bpy.context.scene.collection.children.link(collection)
            if obj.name not in collection.objects:
                collection.objects.link(obj)
    bpy.context.view_layer.update()
    for obj, state in zip(objects, states):
        if obj.name in bpy.context.view_layer.objects:
            obj.hide_set(state["hidden"])
            obj.select_set(state["selected"])
        if state["properties"].get("moldboxer_slip_casting_restart_master", False):
            # Hidden backups are excluded from depsgraph evaluation on load;
            # keep their world transform ready for Restart's orientation restore.
            obj.matrix_world = mathutils.Matrix(state["matrix_world"])
    return objects


def _scene_snapshot(scene):
    return _properties(scene), {
        prop.identifier: getattr(scene, prop.identifier)
        for prop in scene.bl_rna.properties
        if not prop.is_readonly and not getattr(prop, "is_array", False)
        and prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}
    }


def _restore_scene(scene, snapshot):
    properties, settings = snapshot
    if scene.mold_type_preview != settings["mold_type_preview"]:
        scene.mold_type_preview = settings["mold_type_preview"]
    for key, value in settings.items():
        if getattr(scene, key) != value:
            setattr(scene, key, value)
    for key in list(scene.keys()):
        if key not in properties:
            del scene[key]
    for key, value in properties.items():
        scene[key] = value


def _center_master(context, model):
    """Use world bounds, independent of the imported origin and prior layout."""
    context.view_layer.update()
    points = [model.matrix_world @ mathutils.Vector(corner) for corner in model.bound_box]
    offset = mathutils.Vector((
        -(min(p.x for p in points) + max(p.x for p in points)) / 2.0,
        -(min(p.y for p in points) + max(p.y for p in points)) / 2.0,
        -min(p.z for p in points),
    ))
    model.matrix_world.translation += offset
    for obj in context.selected_objects:
        obj.select_set(False)
    model.select_set(True)
    context.view_layer.objects.active = model
    context.view_layer.update()


def _slip_component(state):
    name = state["name"].lower()
    return name in {"patron", "master", "backup", "box", "base", "grip", "wing", "silicone_mold"} or name.startswith((
        "plaster_mold", "master_base", "box_", "casting_box", "clamp", "clip",
        "base_", "female_base", "split_base", "slip_casting_", "vase_base", "foot",
        "funnel", "rounded_funnel", "_rounded_funnel",
        "direct_split_plane", "silicone_split_plane",
    )) or any("slip_casting" in key or key.startswith("moldboxer_rounded_funnel_")
              for key in state["properties"])



def enable_plaster_silicone_settings(context):
    """Expose adapted-box settings only after the complete slip-cast workflow."""
    scene = context.scene
    if not str(scene.mold_type_preview).startswith("SLIP_CASTING"):
        return
    if not any(flip for _obj, flip in plaster_sources(scene)):
        return
    from .export import _export_cleanup_is_excluded, object_export_y_rotation

    # Future silicone settings must not change direct export of the existing mold.
    for obj in scene.objects:
        if obj.type != "MESH" or not _slip_component({
            "name": obj.name, "properties": _properties(obj),
        }):
            continue
        obj["moldboxer_source_export_cleanup_excluded"] = _export_cleanup_is_excluded(obj)
        obj["moldboxer_source_export_y_rotation"] = object_export_y_rotation(scene, obj.name)
    finalize_slip_casting_foot_materials(scene)
    scene[RESTART_MOLD_TYPE_KEY] = scene.mold_type_preview
    scene.mold_type_preview = "ADAPTED_BOX"


def restore_slip_casting_panel_on_restart(scene):
    """Return from the automatic silicone-settings panel to the source workflow."""
    source_type = scene.get(RESTART_MOLD_TYPE_KEY)
    has_plaster = any(flip for _obj, flip in plaster_sources(scene))
    has_converted_system = any(obj.get(SYSTEM_KEY) for obj in scene.objects)
    if (scene.mold_type_preview == "ADAPTED_BOX"
            and (has_plaster or (source_type and has_converted_system))):
        # Existing projects made before this marker was added still have their
        # completed plaster previews, which identify the originating workflow.
        scene.mold_type_preview = (source_type if source_type in
            {"SLIP_CASTING", "SLIP_CASTING_VASE"} else "SLIP_CASTING_VASE")
    if RESTART_MOLD_TYPE_KEY in scene:
        del scene[RESTART_MOLD_TYPE_KEY]


def _place_row(objects, minimum_y, clearance):
    visible = [obj for obj in objects if obj.type == "MESH" and not obj.hide_get()
               and not obj.hide_viewport]
    if not visible:
        raise RuntimeError("Adapted-box generation produced no visible mesh")
    points = [obj.matrix_world @ mathutils.Vector(corner)
              for obj in visible for corner in obj.bound_box]
    offset = minimum_y - min(point.y for point in points)
    translation = mathutils.Matrix.Translation((0.0, offset, 0.0))
    placements = [(obj, translation @ obj.matrix_world) for obj in objects]
    for obj, matrix in placements:
        obj.matrix_world = matrix
    bpy.context.view_layer.update()
    return max(point.y for point in points) + offset + clearance


def iter_convert_plaster(context, *, orient, prepare, generate):
    """Generate with only the current system in Blender's object database."""
    sources = plaster_sources(context.scene)
    if not sources or not any(flip for _, flip in sources):
        raise RuntimeError("No finished plaster mold previews available")
    scene_snapshot = _scene_snapshot(context.scene)
    original_active_name = getattr(context.view_layer.objects.active, "name", None)
    original_scene_names = set(context.scene.objects.keys())
    cameras = [(scene, scene.camera.name) for scene in bpy.data.scenes if scene.camera]
    archive_dir = Path(tempfile.mkdtemp(prefix="moldboxer-plaster-"))
    original_path = archive_dir / "original.blend"
    templates = []
    completed = []
    original_states = []
    originals_removed = False
    recovered = False
    committed = False
    try:
        # Evaluated mesh copies retain the plaster geometry but no parents,
        # modifiers, constraints, object tags, or references to other systems.
        depsgraph = context.evaluated_depsgraph_get()
        for obj, flip in sources:
            mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(depsgraph), depsgraph=depsgraph)
            templates.append((obj.name, mesh, obj.matrix_world.copy(), flip))
        original_states = _archive_objects(original_path, bpy.data.objects)
        originals_removed = True
        _remove_live_objects()
        if context.scene.mold_type_preview != "ADAPTED_BOX":
            context.scene.mold_type_preview = "ADAPTED_BOX"
        generation_settings = _scene_snapshot(context.scene)
        total_volume = 0.0
        clearance = max(10.0, float(context.scene.clamp_depth))
        for index, (source_name, mesh, matrix, flip) in enumerate(templates, 1):
            if len(bpy.data.objects):
                raise RuntimeError("Previous mold objects remain before independent generation")
            _restore_scene(context.scene, generation_settings)
            # Rebuild split guides and their payload against this master only.
            for key in ("_moldboxer_silicone_split_planes", "_moldboxer_keep_silicone_split_planes"):
                if key in context.scene:
                    del context.scene[key]
            model = bpy.data.objects.new("patron", mesh.copy())
            context.collection.objects.link(model)
            model.matrix_world = matrix
            if flip:
                model.matrix_world = mathutils.Matrix.Rotation(math.pi, 4, "X") @ model.matrix_world
            _center_master(context, model)
            label = f"Silicone mold {index}/{len(templates)}"
            yield f"{label}: Aligning master", lambda model=model: orient(model)
            # Auto-orientation can move the bounds. Recenter before preparation
            # builds any reference planes, wings, or pins.
            _center_master(context, model)
            yield f"{label}: Preparing master", lambda model=model: prepare(model)
            result = yield from generate()
            if result != {"FINISHED"}:
                raise RuntimeError(f"Could not generate silicone mold for {source_name}")
            outputs = list(bpy.data.objects)
            if not any(obj.name == "silicone_mold" for obj in outputs):
                raise RuntimeError("Adapted-box generation did not finish its silicone preview")
            total_volume += float(getattr(context.scene, "volume", 0.0))
            for obj in outputs:
                obj[SYSTEM_KEY] = source_name
                obj[COMPONENT_KEY] = obj.name
            path = archive_dir / f"system_{index:03d}.blend"
            completed.append((path, _archive_objects(path, outputs)))
            _remove_live_objects()

        _restore_scene(context.scene, generation_settings)
        for key in ("_moldboxer_silicone_split_planes", "_moldboxer_keep_silicone_split_planes"):
            if key in context.scene:
                del context.scene[key]
        # No prior system participates in another build. Only now load and lay
        # out the finished systems, preserving each system's relative positions.
        original_objects = _load_objects(original_path, original_states)
        rows = [_load_objects(path, states) for path, states in completed]
        next_y = 0.0
        for row in rows:
            next_y = _place_row(row, next_y, clearance)
        for obj, state in zip(original_objects, original_states):
            if (state["name"] in original_scene_names and _slip_component(state)
                    and not state["properties"].get("moldboxer_slip_casting_restart_master", False)):
                remove_objects_safely((obj,))
        # Release names occupied by the old slip-cast objects during restoration.
        for row, (_path, states) in zip(rows, completed):
            for obj, state in zip(row, states):
                obj.name = state["name"]
        for scene, camera_name in cameras:
            scene.camera = bpy.data.objects.get(camera_name)
        if hasattr(context.scene, "volume"):
            context.scene.volume = total_volume
        if "_moldboxer_export_completed" in context.scene:
            del context.scene["_moldboxer_export_completed"]
        context.view_layer.objects.active = context.scene.objects.get("patron")
        committed = True
    finally:
        if originals_removed and not committed:
            try:
                _remove_live_objects()
                _load_objects(original_path, original_states)
                _restore_scene(context.scene, scene_snapshot)
                for scene, camera_name in cameras:
                    scene.camera = bpy.data.objects.get(camera_name)
                context.view_layer.objects.active = bpy.data.objects.get(original_active_name) if original_active_name else None
                recovered = True
            except Exception as error:
                raise RuntimeError(
                    f"Could not restore the original scene; recovery objects are saved in {original_path}"
                ) from error
        for _name, mesh, _matrix, _flip in templates:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        # Retain the recovery archive if restoration itself fails.
        if committed or recovered or not originals_removed:
            shutil.rmtree(archive_dir)
        context.view_layer.update()
