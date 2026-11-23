import json
import mathutils  # type: ignore
import logging
import bpy  # type: ignore
import bmesh  # type: ignore
import math
import time
from collections.abc import Callable, Iterator
from ..silicone_mix import silicone_mix_engraving
from ..background_worker import BackgroundTaskSequence, finish_task_sync


from .server import import_server_response, request_server, request_server_async
from ..bl_utils import BMeshObj
from ..object import Object, remove_objects_safely
from ..split_specs import split_specs_query_values
from ..environment import get_server_base_url
from .silicone_mold import (
    build_silicone_mold_preview,
    hide_silicone_mold_preview,
    reveal_silicone_mold_preview,
)
from .manual_booleans import (
    iter_manual_booleans_after_server_import,
    prepare_base_substracter_after_server_import,
    subtract_base_substracter_from_box,
)
from .base_substracter_visibility import (
    is_base_substracter_object,
    set_base_substracter_hidden,
)
from .channels_deposit import (
    add_deposit,
    add_casting_feet,
    recut_channels,
    add_channels,
    set_support_pilars_hidden,
)
from .geometry_adapter import (
    locking_clamp_plan_with_worker,
    plan_casting_box_intersection_bands_with_worker,
    repeat_object_mesh_grid_with_worker,
)
from .splitter import (
    _remove_pre_split_isolated_meshes,
    _remesh_barrier_from_scene,
    _subtract_base_female_locking_geometry,
    add_clamps_to_box,
    begin_split,
)
from .inner_core import (
    create_inner_core,
    create_inner_core_async,
    subtract_inner_core_objects_from_box,
)
from .inner_cavity_clamp import barrier_male_top_extension
from .base import add_basing_to_system
from .watermark_mesh_server import request_weight_text_mesh_async
from .box_parts import (
    get_effective_box_parts,
    get_effective_casting_box_type,
    resolve_splitter_plane_specs,
)
from .direct_split_planes import (
    direct_split_plane_specs,
    remove_direct_split_planes,
    set_keep_silicone_split_planes_after_build,
    store_silicone_split_plane_specs,
    stored_silicone_split_plane_specs,
)
from .direct_split_execution import SPLIT_SECTION_SIDES_KEY
from .watermark_payload import calculate_casting_volume
from ._q7x import (
    PENDING_CASTING_BOX_NAME,
    WEIGHT_TEXT_CASTING_CUTTER_NAME,
    begin_z9f3,
    different_casting_box_thickness,
    pending_casting_boxes,
)
from ..materials import (
    assign_generated_material,
    refresh_generated_object_materials,
    refresh_viewport_material_display,
)
from ..operator_access import has_pro_or_trial_server_access, is_lite_tier
from ..patron_lifecycle import (
    finalize_master_as_patron,
    hide_working_patron,
    reveal_working_patron,
)
from ..progress import force_viewport_redraw
from ..voxel_size import get_box_boolean_retry_voxel_size, get_box_voxel_size
from ..constants import WING_BASE_HEIGHT
from ..primitives import create_cube_primitive

logger = logging.getLogger(__name__)
CLAMP_LOCKER_OBJECT_NAME = "clamp_lockers"
BASE_CLAMP_LOCKER_OBJECT_NAME = "base_lockers"
CLAMP_LOCKER_HEIGHT_SPACING_MM = 30.0
MIN_CLAMP_LOCKERS_PER_MOLD_PART = 2
DEFAULT_LOCKER_CLIP_COUNT = 6
ENABLE_OPTIMIZED_CASTING_ISLAND_CLEANUP = False
DEBUG_SKIP_OPTIMIZED_CASTING_BOX_FILTER = False
CONFIRM_SKIP_REDRAW_STEPS = {
    "Preparing channels",
    "Generating channel box",
    "Generating mold system",
    "Generating clamp details",
}
LEGACY_CLIP_OBJECT_NAMES = {
    "clamp locker",
    "base clamp locker",
    "clamp_clips",
    "base_clips",
    "clip",
}


def _mesh_object_by_name(name: str) -> Object | None:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        return None
    return Object(obj)


def _object_name_matches(obj_name: str, name: str) -> bool:
    obj_name = obj_name.lower()
    name = name.lower()
    return obj_name == name or obj_name.startswith(f"{name}.")


def _final_master_object() -> Object | None:
    return _mesh_object_by_name("master") or _mesh_object_by_name("patron")


def _object_bounds(obj: Object) -> dict[str, float]:
    coords = [
        obj.object.matrix_world @ mathutils.Vector(corner[:3])
        for corner in obj.object.bound_box
    ]
    min_x = min(coord.x for coord in coords)
    max_x = max(coord.x for coord in coords)
    min_y = min(coord.y for coord in coords)
    max_y = max(coord.y for coord in coords)
    min_z = min(coord.z for coord in coords)
    max_z = max(coord.z for coord in coords)
    return {
        "min_x": min_x,
        "max_x": max_x,
        "width": max_x - min_x,
        "min_y": min_y,
        "max_y": max_y,
        "depth": max_y - min_y,
        "center_y": min_y + (max_y - min_y) / 2,
        "min_z": min_z,
        "max_z": max_z,
        "height": max_z - min_z,
    }


def _casting_feet_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and "casting_feet" in obj.name.lower()
    ]


def casting_box_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.lower().startswith("casting_box")
    ]


def translate_object_location(obj: Object, delta: mathutils.Vector) -> None:
    obj.object.location += delta
    bpy.context.view_layer.update()


def _casting_feet_height_from_scene() -> float:
    return max((foot.height for foot in _casting_feet_objects()), default=0)


def _horizontal_channel_split_heights(scene) -> list[float]:
    if int(getattr(scene, "n_splits_z", 0)) <= 0:
        return []

    heights = [
        Object(obj).center_coords.z
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.lower().startswith("channel_horizontal")
    ]
    return sorted(float(height) for height in heights)


def confirm_mold_req(
    box_voxel_size: float = 0.8,
    channel_width: float = 6,
    n_splits: int = 2,
    box_thickness: float = 3.5,
    base_thickness: float = 5.5,
    base_type: str = "classic",
    base_pin_type: str = "pin",
    wing_width: float = 15.0,
    clamp_width: float = 5.0,
    clamp_depth: float = 7.0,
    barrier_tolerance: float = 0.25,
    clamp_pin_type: str = "barrier",
    pin_system_type: str = "PIN",
    screw_diameter: float = 4.0,
    casting_feet: bool = False,
    casting_feet_height: float = 5,
    casting_feet_size_factor: float = 1,
    splits_z: list[float] | None = None,
    split_planes: str = "[]",
    barrier_male_top_extension: float = 0.1,
    silicone_weight_text: str | None = None,
    organic_split_planes: str = "[]",
):
    total_start_time = time.perf_counter()
    params = _confirm_mold_request_params(
        box_voxel_size,
        channel_width,
        n_splits,
        box_thickness,
        base_thickness,
        base_type,
        base_pin_type,
        wing_width,
        clamp_width,
        clamp_depth,
        barrier_tolerance,
        clamp_pin_type,
        pin_system_type,
        screw_diameter,
        casting_feet,
        casting_feet_height,
        casting_feet_size_factor,
        splits_z,
        split_planes,
        barrier_male_top_extension,
        silicone_weight_text,
        organic_split_planes,
    )
    request_start_time = time.perf_counter()
    response = request_server(
        f"{get_server_base_url()}/confirm-silicone-mold/",
        ["box"],
        params=params,
    )
    logger.debug(
        "Confirm mold server request phase took %.3fs",
        time.perf_counter() - request_start_time,
    )
    _import_confirm_mold_response(
        response,
        total_start_time,
        split_planes=split_planes,
    )


def confirm_mold_req_async(
    box_voxel_size: float = 0.8,
    channel_width: float = 6,
    n_splits: int = 2,
    box_thickness: float = 3.5,
    base_thickness: float = 5.5,
    base_type: str = "classic",
    base_pin_type: str = "pin",
    wing_width: float = 15.0,
    clamp_width: float = 5.0,
    clamp_depth: float = 7.0,
    barrier_tolerance: float = 0.25,
    clamp_pin_type: str = "barrier",
    pin_system_type: str = "PIN",
    screw_diameter: float = 4.0,
    casting_feet: bool = False,
    casting_feet_height: float = 5,
    casting_feet_size_factor: float = 1,
    splits_z: list[float] | None = None,
    split_planes: str = "[]",
    barrier_male_top_extension: float = 0.1,
    silicone_weight_text: str | None = None,
    organic_split_planes: str = "[]",
):
    total_start_time = time.perf_counter()
    params = _confirm_mold_request_params(
        box_voxel_size,
        channel_width,
        n_splits,
        box_thickness,
        base_thickness,
        base_type,
        base_pin_type,
        wing_width,
        clamp_width,
        clamp_depth,
        barrier_tolerance,
        clamp_pin_type,
        pin_system_type,
        screw_diameter,
        casting_feet,
        casting_feet_height,
        casting_feet_size_factor,
        splits_z,
        split_planes,
        barrier_male_top_extension,
        silicone_weight_text,
        organic_split_planes,
    )
    request_start_time = time.perf_counter()

    def complete(response):
        logger.debug(
            "Confirm mold server request phase took %.3fs",
            time.perf_counter() - request_start_time,
        )
        return _import_confirm_mold_response(
            response,
            total_start_time,
            split_planes=split_planes,
        )

    return request_server_async(
        f"{get_server_base_url()}/confirm-silicone-mold/",
        ["box"],
        params=params,
        on_complete=complete,
    )


def _confirm_mold_request_params(
    box_voxel_size: float,
    channel_width: float,
    n_splits: int,
    box_thickness: float,
    base_thickness: float,
    base_type: str,
    base_pin_type: str,
    wing_width: float,
    clamp_width: float,
    clamp_depth: float,
    barrier_tolerance: float,
    clamp_pin_type: str,
    pin_system_type: str,
    screw_diameter: float,
    casting_feet: bool,
    casting_feet_height: float,
    casting_feet_size_factor: float,
    splits_z: list[float] | None = None,
    split_planes: str = "[]",
    barrier_male_top_extension: float = 0.1,
    silicone_weight_text: str | None = None,
    organic_split_planes: str = "[]",
) -> dict:
    params = {
        "box_voxel_size": box_voxel_size,
        "channel_width": channel_width,
        "n_splits": n_splits,
        "add_pins": clamp_pin_type != "none",
        "box_thickness": box_thickness,
        "base_thickness": base_thickness,
        "base_type": base_type,
        "base_pin_type": base_pin_type,
        "wing_width": wing_width,
        "clamp_pin_type": clamp_pin_type,
        "clamp_width": clamp_width,
        "clamp_depth": clamp_depth,
        "barrier_tolerance": barrier_tolerance,
        "casting_feet": casting_feet,
        "casting_feet_height": casting_feet_height,
        "casting_feet_size_factor": casting_feet_size_factor,
        "splits_z": list(splits_z or []),
        "split_planes": split_planes,
        "barrier_male_top_extension": barrier_male_top_extension,
    }
    if organic_split_planes != "[]":
        params["organic_split_planes"] = organic_split_planes
    if silicone_weight_text:
        params["silicone_weight_text"] = silicone_weight_text
    if pin_system_type != "NONE":
        params["pin_system_type"] = pin_system_type
        if pin_system_type == "SCREW":
            params["screw_diameter"] = screw_diameter
    return params


def _import_confirm_mold_response(
    response,
    total_start_time: float,
    *,
    split_planes: str = "[]",
):
    # original_box = Object(bpy.data.objects.get("box"))
    # original_box.remove()
    logger.debug(f"Received response from server")
    import_start_time = time.perf_counter()
    imported_objects = import_server_response(
        response,
        remesh_imported_objects=False,
    )
    try:
        split_plane_specs = json.loads(split_planes)
    except (TypeError, ValueError):
        split_plane_specs = []
    if split_plane_specs:
        from .direct_mold import trim_nonvertical_direct_clamp_systems_to_box

        trim_nonvertical_direct_clamp_systems_to_box(split_plane_specs)
    server_base_substracters = [
        obj for obj in bpy.data.objects if is_base_substracter_object(obj)
    ]
    imported_objects = [
        obj for obj in imported_objects if obj not in server_base_substracters
    ]
    for server_base_substracter in server_base_substracters:
        remove_objects_safely((server_base_substracter,))
    if server_base_substracters:
        logger.debug(
            "Discarded %d server-provided base substracter object%s",
            len(server_base_substracters),
            "" if len(server_base_substracters) == 1 else "s",
        )
    if _mesh_object_by_name("box") is None:
        raise ValueError("No box available for mold-box wrapper generation")
    logger.debug(
        "Confirm mold import phase took %.3fs",
        time.perf_counter() - import_start_time,
    )
    logger.debug(
        "Confirm mold request completed in %.3fs",
        time.perf_counter() - total_start_time,
    )
    return imported_objects


def space_mold_system():

    master_base = Object(bpy.data.objects.get("master_base"))
    patron = _final_master_object()
    if patron is None:
        return
    master_base_bounds = _object_bounds(master_base)
    patron_bounds = _object_bounds(patron)
    silicone_raw = bpy.data.objects.get("silicone_mold")
    if silicone_raw is not None:
        silicone_mold = Object(silicone_raw)
        silicone_bounds = _object_bounds(silicone_mold)
        target_silicone_min_x = (
            master_base_bounds["max_x"] + master_base_bounds["width"] / 2
        )
        translate_object_location(
            silicone_mold,
            mathutils.Vector(
                (
                    target_silicone_min_x - silicone_bounds["min_x"],
                    0,
                    0,
                )
            ),
        )
        silicone_bounds = _object_bounds(silicone_mold)
        casting_objects = casting_box_objects()
        if casting_objects:
            casting_bounds = [
                (casting_object, _object_bounds(casting_object))
                for casting_object in casting_objects
            ]
            casting_min_x = min(
                bounds["min_x"] for _casting_object, bounds in casting_bounds
            )
            casting_translation = mathutils.Vector(
                (
                    silicone_bounds["max_x"]
                    + silicone_bounds["width"] / 2
                    - casting_min_x,
                    0,
                    0,
                )
            )
            for casting_object, _bounds in casting_bounds:
                translate_object_location(casting_object, casting_translation)

    target_patron_max_x = master_base_bounds["min_x"] - master_base_bounds["width"] / 2
    translate_object_location(
        patron,
        mathutils.Vector((target_patron_max_x - patron_bounds["max_x"], 0, 0)),
    )
    patron_bounds = _object_bounds(patron)
    place_clips_left_of_patron(master_base_bounds, patron_bounds)


def remove_clip() -> None:
    clip_objects = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (
            obj.name in LEGACY_CLIP_OBJECT_NAMES
            or obj.name == CLAMP_LOCKER_OBJECT_NAME
            or obj.name == BASE_CLAMP_LOCKER_OBJECT_NAME
            or obj.name.startswith(
                ("clip_", "clamp_lockers_group_", "base_lockers_group_")
            )
        )
    ]
    for clip_object in clip_objects:
        Object(clip_object).remove()


def _round_vertical_edges(obj: Object, radius: float, segments: int = 8) -> None:
    with BMeshObj(obj, repair_winding=True) as bm:
        vertical_edges = []
        for edge in bm.edges:
            direction = edge.verts[1].co - edge.verts[0].co
            if direction.length <= 1e-6:
                continue
            if abs(direction.normalized().z) > 0.999:
                vertical_edges.append(edge)

        if not vertical_edges:
            return

        bmesh.ops.bevel(
            bm,
            geom=vertical_edges,
            offset=radius,
            segments=segments,
            profile=0.5,
            affect="EDGES",
        )


def _plan_dimensions(step: dict) -> tuple[float, float, float]:
    dimensions = tuple(float(value) for value in step.get("dimensions", ()))
    if len(dimensions) != 3 or min(dimensions) <= 0.0:
        raise RuntimeError("Worker returned invalid locking-clamp dimensions")
    return dimensions


def create_clip_group(name: str, plan: dict) -> Object:
    """Execute a worker-owned clamp recipe using Blender mesh operations."""

    clip_count = max(1, int(plan["layout"]["count"]))
    if clip_count > 4:
        first_group = None
        next_x = 0.0
        for start in range(0, clip_count, 4):
            group_name = name if start == 0 else f"{name}_group_{start // 4 + 1:02d}"
            group_plan = {
                **plan,
                "layout": {**plan["layout"], "count": min(4, clip_count - start)},
            }
            group = create_clip_group(group_name, group_plan)
            # Lay groups out to the left so subsequent placement keeps them
            # clear of the master while preserving separate export objects.
            bounds = _object_bounds(group)
            if first_group is None:
                first_group = group
            else:
                group.translate_whole(
                    mathutils.Vector((next_x - bounds["max_x"], 0, 0))
                )
            next_x = _object_bounds(group)["min_x"] - float(plan["layout"]["gap"])
            assign_generated_material(group.object)
        return first_group

    clip = None
    for step in plan.get("steps", ()):
        operation = str(step.get("operation", ""))
        if operation == "CREATE_CUBE":
            if clip is not None:
                raise RuntimeError("Worker locking-clamp plan creates two roots")
            dimensions = _plan_dimensions(step)
            clip = Object(create_cube_primitive(1), "clip")
            for axis, size in enumerate(dimensions):
                clip.scale_to(size, axis=axis)
            continue
        if clip is None:
            raise RuntimeError("Worker locking-clamp plan has no root mesh")
        if operation == "SUBTRACT_TAPERED_CUBE":
            dimensions = _plan_dimensions(step)
            cutter = Object(create_cube_primitive(1), "clip_cutout")
            for axis, size in enumerate(dimensions):
                cutter.scale_to(size, axis=axis)
            overtravel = float(step["min_y_overtravel"])
            cutter.translate_whole(
                mathutils.Vector((0, clip.min_y - overtravel - cutter.min_y, 0))
            )
            face_index = cutter.get_limit_face_idx(axis=1, max_co=False)
            cutter.scale_face(
                float(step["min_y_face_scale"]),
                axis=0,
                face_idx=face_index,
            )
            clip -= cutter
            cutter.remove()
            continue
        if operation == "BEVEL_VERTICAL_EDGES":
            _round_vertical_edges(
                clip,
                float(step["radius"]),
                segments=int(step["segments"]),
            )
            continue
        if operation == "SUBTRACT_MAX_Y_CUBE":
            dimensions = _plan_dimensions(step)
            cutter = Object(create_cube_primitive(1), "base_locker_slot_cutter")
            for axis, size in enumerate(dimensions):
                cutter.scale_to(size, axis=axis)
            overtravel = float(step["max_y_overtravel"])
            cutter.translate_whole(
                mathutils.Vector((0, clip.max_y - cutter.max_y + overtravel, 0))
            )
            clip -= cutter
            cutter.remove()
            continue
        raise RuntimeError(
            f"Worker returned unknown locking-clamp operation: {operation}"
        )

    if clip is None:
        raise RuntimeError("Worker returned an empty locking-clamp plan")
    layout = plan.get("layout", {})
    clip_count = max(1, int(layout["count"]))
    clip_gap = float(layout["gap"])
    if clip_count > 1:
        try:
            repeat_object_mesh_grid_with_worker(
                clip.object,
                count=clip_count,
                gap=clip_gap,
            )
            clip.name = name
            return clip
        except Exception:
            logger.warning(
                "Locking-clamp worker grid failed; using Blender copies",
                exc_info=True,
            )

    clip_rows = min(2, clip_count)
    clip_columns = math.ceil(clip_count / clip_rows)
    clip_parts = [clip]
    clip_index = 2
    for clip_number in range(1, clip_count):
        row = clip_number // clip_columns
        column = clip_number % clip_columns
        offset = (
            column * (clip.width + clip_gap),
            row * (clip.depth + clip_gap),
            0,
        )
        clip_copy = clip.duplicate(name_adder=f"_{clip_index}")
        clip_copy.translate_whole(mathutils.Vector(offset))
        clip_parts.append(clip_copy)
        clip_index += 1
    for clip_copy in clip_parts[1:]:
        clip.join(clip_copy)
    clip.name = name
    return clip


def create_clamp_clips(
    clamp_width: float,
    clamp_depth: float,
    height: float,
    thickness: float,
    tolerance: float,
    closing_pressure: float,
    clip_count: int,
) -> Object:
    plan = locking_clamp_plan_with_worker(
        "CLAMP",
        clamp_width,
        clamp_depth,
        height,
        thickness,
        tolerance,
        closing_pressure,
        clip_count,
    )
    return create_clip_group(CLAMP_LOCKER_OBJECT_NAME, plan)


def create_base_clips(
    base_span: float,
    base_thickness: float,
    height: float,
    thickness: float,
    tolerance: float,
    closing_pressure: float,
) -> Object:
    plan = locking_clamp_plan_with_worker(
        "BASE",
        base_span,
        base_thickness,
        height,
        thickness,
        tolerance,
        closing_pressure,
        DEFAULT_LOCKER_CLIP_COUNT,
    )
    return create_clip_group(BASE_CLAMP_LOCKER_OBJECT_NAME, plan)


def _master_height_for_clamp_clip_count() -> float:
    for object_name in ("patron", "master"):
        obj = _mesh_object_by_name(object_name)
        if obj is not None and obj.height > 0:
            return obj.height
    return 0.0


def _clamp_clip_count_from_scene(scene) -> int:
    master_height = _master_height_for_clamp_clip_count()
    clips_per_part = max(
        MIN_CLAMP_LOCKERS_PER_MOLD_PART,
        math.ceil(master_height / CLAMP_LOCKER_HEIGHT_SPACING_MM),
    )
    generated_parts = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and obj.name.lower().startswith(
            ("box_part_", "protective_shell_part_"),
        )
    ]
    mold_part_multiplier = len(generated_parts) or (
        4 if get_effective_box_parts(scene) == 4 else 2
    )
    return clips_per_part * mold_part_multiplier


def place_clips_left_of_patron(
    master_base_bounds: dict[str, float] | None = None,
    patron_bounds: dict[str, float] | None = None,
    reference_width: float | None = None,
) -> None:
    master_base = _mesh_object_by_name("master_base")
    patron = _final_master_object()
    clamp_clips = _mesh_object_by_name(CLAMP_LOCKER_OBJECT_NAME)
    base_clips = _mesh_object_by_name(BASE_CLAMP_LOCKER_OBJECT_NAME)
    if patron is None or (master_base is None and reference_width is None):
        return

    if master_base_bounds is None and master_base is not None:
        master_base_bounds = _object_bounds(master_base)
    if patron_bounds is None:
        patron_bounds = _object_bounds(patron)
    clamp_clip_bounds = _object_bounds(clamp_clips) if clamp_clips is not None else None
    base_clip_bounds = _object_bounds(base_clips) if base_clips is not None else None

    spacing_width = (
        float(reference_width)
        if reference_width is not None
        else master_base_bounds["width"]
    )
    target_max_x = patron_bounds["min_x"] - spacing_width * 0.5
    max_clip_depth = max(
        clamp_clip_bounds["depth"] if clamp_clip_bounds is not None else 0,
        base_clip_bounds["depth"] if base_clip_bounds is not None else 0,
    )
    y_gap = max_clip_depth / 2 + 2.5
    clip_positions = (
        (clamp_clips, clamp_clip_bounds, patron_bounds["center_y"] - y_gap),
        (base_clips, base_clip_bounds, patron_bounds["center_y"] + y_gap),
    )
    for clip, clip_bounds, target_center_y in clip_positions:
        if clip is None or clip_bounds is None:
            continue
        offset = mathutils.Vector(
            (
                target_max_x - clip_bounds["max_x"],
                target_center_y - clip_bounds["center_y"],
                patron_bounds["min_z"] - clip_bounds["min_z"],
            )
        )
        groups = [clip] + [
            Object(obj) for obj in bpy.data.objects
            if obj.type == "MESH" and obj.name.startswith(f"{clip.name}_group_")
        ]
        for group in groups:
            group.translate_whole(offset)
            group.origin_to_geometry()


def create_clip_from_scene(
    scene,
    *,
    include_base_clips: bool | None = None,
) -> Object:
    remove_clip()
    clamp_clips = create_clamp_clips(
        scene.clamp_width,
        scene.clamp_depth,
        scene.clip_height,
        scene.clip_thickness,
        scene.clip_tolerance,
        scene.clip_closing_pressure,
        _clamp_clip_count_from_scene(scene),
    )
    assign_generated_material(clamp_clips.object)
    if include_base_clips is None:
        include_base_clips = getattr(scene, "base_type", "classic") != "optimized"
    if include_base_clips:
        base_clips = create_base_clips(
            scene.wing_width,
            scene.base_thickness,
            scene.clip_height,
            scene.clip_thickness,
            scene.clip_tolerance,
            scene.clip_closing_pressure,
        )
        assign_generated_material(base_clips.object)
    return clamp_clips


def _create_casting_box_slab(
    name: str,
    point: mathutils.Vector,
    normal: mathutils.Vector,
    scale: tuple[float, float, float],
) -> Object:
    normalized_normal = normal.normalized()
    raw_slab = create_cube_primitive(2)
    raw_slab.name = name
    raw_slab.location = point
    raw_slab.rotation_euler = normalized_normal.to_track_quat("Z", "Y").to_euler()
    raw_slab.scale = tuple(float(value) for value in scale)
    slab = Object(raw_slab)
    slab.hide_during_ui_breathe = True
    # These intersection bands are Boolean operands only. Keep them hidden
    # between operations as well as during explicit UI refreshes.
    raw_slab.hide_set(True)
    raw_slab.hide_render = True
    bpy.context.view_layer.update()
    return slab


def _create_casting_box_exclusion_cutter(
    retained_bands: list[Object],
    center: mathutils.Vector,
    scale: tuple[float, float, float],
) -> Object:
    """Return an enclosing volume with the retained bands removed from it."""
    raw_cutter = create_cube_primitive(2)
    raw_cutter.name = "optimized_casting_box_exclusion_cutter"
    raw_cutter.location = center
    raw_cutter.scale = tuple(float(value) for value in scale)
    bpy.context.view_layer.update()
    exclusion_cutter = Object(raw_cutter)
    exclusion_cutter.hide_during_ui_breathe = True
    try:
        for retained_band in retained_bands:
            exclusion_cutter -= retained_band
    except Exception:
        exclusion_cutter.remove()
        raise
    return exclusion_cutter


def optimize_casting_boxes(
    casting_boxes: list[Object],
    thickness: float,
    split_plane_specs: list[list[list[float]]] | None = None,
    horizontal_intersection: str = "TOP",
) -> list[Object]:
    if not casting_boxes:
        return []

    plan = plan_casting_box_intersection_bands_with_worker(
        casting_boxes,
        thickness,
        split_plane_specs,
        horizontal_intersection,
    )
    slabs = [
        _create_casting_box_slab(
            str(band["name"]),
            mathutils.Vector(band["point"]),
            mathutils.Vector(band["normal"]),
            band["scale"],
        )
        for band in plan["bands"]
    ]

    exclusion_cutter = None
    try:
        exclusion_cutter = _create_casting_box_exclusion_cutter(
            slabs,
            mathutils.Vector(plan["exclusion_cutter"]["center"]),
            plan["exclusion_cutter"]["scale"],
        )
        for casting_box in casting_boxes:
            casting_box -= exclusion_cutter
    finally:
        if exclusion_cutter is not None:
            exclusion_cutter.remove()
        for slab in slabs:
            slab.remove()
    return casting_boxes


def _prepared_different_thickness_casting_boxes(
    scene,
) -> list[Object]:
    casting_boxes = pending_casting_boxes()
    if not casting_boxes:
        return []

    for index, casting_box in enumerate(casting_boxes, start=1):
        source_min_z = float(
            casting_box.object.get(
                "_moldboxer_source_min_z",
                casting_box.min_z,
            )
        )
        casting_box.name = (
            "casting_box"
            if len(casting_boxes) == 1
            else f"casting_box_{index:02d}"
        )
        casting_box.object["_moldboxer_source_min_z"] = source_min_z
        casting_box.object["_moldboxer_different_thickness"] = True
        casting_box.object["_moldboxer_pending_casting_box"] = False
    return casting_boxes


def _normal_box_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and "box" in obj.name.lower()
        and "casting_" not in obj.name.lower()
        and obj.name != PENDING_CASTING_BOX_NAME
        and not bool(obj.get("_moldboxer_pending_casting_box", False))
    ]


def _mesh_island_count(obj: Object) -> int:
    """Count connected mesh components without modifying or separating the object."""
    mesh = getattr(obj.object, "data", None)
    if mesh is None:
        return 0

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        remaining = set(bm.verts)
        island_count = 0
        while remaining:
            island_count += 1
            stack = [remaining.pop()]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    connected = edge.other_vert(vertex)
                    if connected in remaining:
                        remaining.remove(connected)
                        stack.append(connected)
        return island_count
    finally:
        bm.free()


def _keep_largest_casting_islands(
    casting_boxes: list[Object],
    keep_count: int,
) -> list[Object]:
    if not casting_boxes:
        return []

    isolated_meshes: list[Object] = []
    for casting_box in casting_boxes:
        isolated_meshes.extend(casting_box.split_isolated_meshes())

    target_count = max(int(keep_count), 1)
    if len(isolated_meshes) <= target_count:
        return isolated_meshes

    def size_key(mesh: Object) -> tuple[float, int, int]:
        data = mesh.object.data
        return (
            abs(float(mesh.volume)),
            len(data.polygons),
            len(data.vertices),
        )

    meshes_to_keep = sorted(
        isolated_meshes,
        key=size_key,
        reverse=True,
    )[:target_count]
    kept_object_ids = {id(mesh.object) for mesh in meshes_to_keep}
    for mesh in isolated_meshes:
        if id(mesh.object) not in kept_object_ids:
            mesh.remove()
    return meshes_to_keep


def _casting_box_overlaps_cutter(casting_box: Object, cutter: Object) -> bool:
    return (
        casting_box.min_x < cutter.max_x
        and casting_box.max_x > cutter.min_x
        and casting_box.min_y < cutter.max_y
        and casting_box.max_y > cutter.min_y
        and casting_box.min_z < cutter.max_z
        and casting_box.max_z > cutter.min_z
    )


def _subtract_weight_text_extension_from_casting_boxes(
    casting_boxes: list[Object],
) -> None:
    cutter_raw = bpy.data.objects.get(WEIGHT_TEXT_CASTING_CUTTER_NAME)
    if cutter_raw is None or cutter_raw.type != "MESH":
        return

    cutter = Object(cutter_raw)
    try:
        for casting_box in casting_boxes:
            if not _casting_box_overlaps_cutter(casting_box, cutter):
                continue
            casting_box -= cutter
            if casting_box.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
    finally:
        cutter.remove()


def duplicate_cut_casting_boxes(
    cut_vertical: bool = True,
    vertical_cut_height: float | None = None,
) -> list[Object]:
    if not has_pro_or_trial_server_access():
        _subtract_weight_text_extension_from_casting_boxes([])
        return []

    patron = Object(bpy.data.objects.get("patron"))
    cut_height = (
        vertical_cut_height
        if vertical_cut_height is not None
        else patron.min_z + WING_BASE_HEIGHT + 0.5
    )
    cut_normal = mathutils.Vector((0, 0, -1))
    cut_point = mathutils.Vector((0, 0, cut_height))
    scene = bpy.context.scene
    normal_boxes = _normal_box_objects()
    casting_boxes = _prepared_different_thickness_casting_boxes(scene)
    if not casting_boxes:
        for source_box in normal_boxes:
            scanner = source_box.duplicate(name_adder="")
            scanner.name = f"casting_{source_box.name}"
            scanner.object["_moldboxer_source_min_z"] = source_box.min_z
            casting_boxes.append(scanner)

    _subtract_weight_text_extension_from_casting_boxes(casting_boxes)

    if cut_vertical:
        for casting_box in casting_boxes:
            casting_box.cut_plane(plane_normal=cut_normal, plane_point=cut_point)
    optimized_casting_box = get_effective_casting_box_type(scene) == "OPTIMIZED"
    if optimized_casting_box:
        if DEBUG_SKIP_OPTIMIZED_CASTING_BOX_FILTER:
            return casting_boxes
        optimize_casting_boxes(
            casting_boxes,
            getattr(scene, "optimized_casting_box_thickness", 15.0),
            stored_silicone_split_plane_specs(scene),
            getattr(
                scene,
                "optimized_casting_box_horizontal_intersection",
                "TOP",
            ),
        )
        if ENABLE_OPTIMIZED_CASTING_ISLAND_CLEANUP:
            normal_island_count = sum(
                _mesh_island_count(box) for box in normal_boxes
            )
            return _keep_largest_casting_islands(
                casting_boxes,
                normal_island_count,
            )
    return casting_boxes


def _two_part_casting_box_target(
    casting_boxes: list[Object],
    side: str,
) -> Object | None:
    """Find the outer casting-box half for one rotated two-part mold side."""
    legacy_name = "casting_box_r" if side == "left" else "casting_box_l"
    legacy_target = next(
        (
            casting_box
            for casting_box in casting_boxes
            if casting_box.name == legacy_name
        ),
        None,
    )
    if legacy_target is not None:
        return legacy_target

    target_split_side = 1 if side == "left" else -1
    metadata_targets = []
    for casting_box in casting_boxes:
        split_sides = casting_box.object.get(SPLIT_SECTION_SIDES_KEY)
        if (
            split_sides is not None
            and len(split_sides) > 0
            and int(split_sides[0]) == target_split_side
        ):
            metadata_targets.append(casting_box)
    if metadata_targets:
        return max(
            metadata_targets,
            key=lambda casting_box: target_split_side * casting_box.center_coords.x,
        )

    if not casting_boxes:
        return None
    return max(
        casting_boxes,
        key=lambda casting_box: target_split_side * casting_box.center_coords.x,
    )


def cut_two_part_casting_boxes(
    side: str,
    wing_span: float,
    cut_open_base_side: bool = False,
) -> None:
    patron = Object(bpy.data.objects.get("patron"))
    if side == "left":
        open_base_normal = mathutils.Vector((-1, 0, 0))
        open_base_point = mathutils.Vector((patron.min_x + 1, 0, 0))
        opposite_normal = mathutils.Vector((1, 0, 0))
        target_name = "casting_box_r"
    elif side == "right":
        open_base_normal = mathutils.Vector((1, 0, 0))
        open_base_point = mathutils.Vector((patron.max_x - 1, 0, 0))
        opposite_normal = mathutils.Vector((-1, 0, 0))
        target_name = "casting_box_l"
    else:
        return

    casting_boxes = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.lower().startswith("casting_box")
    ]
    if not casting_boxes:
        return

    target = _two_part_casting_box_target(casting_boxes, side)
    if target is None:
        return
    opposite_point = mathutils.Vector(
        (
            (
                target.max_x - wing_span - 1
                if side == "left"
                else target.min_x + wing_span + 1
            ),
            0,
            0,
        )
    )
    for casting_box in casting_boxes:
        if cut_open_base_side:
            casting_box.cut_plane(
                plane_normal=open_base_normal,
                plane_point=open_base_point,
            )
        casting_box.cut_plane(
            plane_normal=opposite_normal,
            plane_point=opposite_point,
        )

    if cut_open_base_side:
        cube = Object(create_cube_primitive(1), f"{target_name}_open_base_wing")
        cube.scale_to(5, axis=0)
        cube.scale_to(
            max(casting_box.depth * 0.75 for casting_box in casting_boxes), axis=1
        )
        cube.scale_to(max(casting_box.height for casting_box in casting_boxes), axis=2)
        target_x = (
            target.max_x - 1 - cube.min_x
            if side == "left"
            else target.min_x + 1 - cube.max_x
        )
        cube.translate_whole(
            mathutils.Vector(
                (
                    target_x,
                    target.center_coords.y - cube.center_coords.y,
                    target.min_z - cube.min_z,
                )
            )
        )
        target += cube
        cube.remove()

    scene = bpy.context.scene
    if (
        ENABLE_OPTIMIZED_CASTING_ISLAND_CLEANUP
        and get_effective_casting_box_type(scene) == "OPTIMIZED"
    ):
        normal_island_count = sum(
            _mesh_island_count(box) for box in _normal_box_objects()
        )
        _keep_largest_casting_islands(casting_boxes, normal_island_count)


ConfirmStep = tuple[str, Callable[[], None]]


def iter_confirm_steps(
    context,
    two_part_casting_side: str | None = None,
    cut_casting_open_base_side: bool = False,
    cut_casting_vertical: bool = True,
    pre_join_base_callback=None,
    async_server: bool = False,
) -> Iterator[ConfirmStep]:
    total_start_time = time.perf_counter()
    state: dict[str, object] = {
        "basing_elapsed": 0.0,
        "split_elapsed": 0.0,
        "casting_box_elapsed": 0.0,
        "finalize_elapsed": 0.0,
        "clips_elapsed": 0.0,
        "spacing_elapsed": 0.0,
        "metrics_elapsed": 0.0,
        "viewport_elapsed": 0.0,
    }

    def prepare_channels() -> None:
        set_support_pilars_hidden(False)
        reveal_working_patron()
        state["box_voxel_size"] = get_box_voxel_size(context.scene.box_quality)
        state["box_boolean_retry_voxel_size"] = get_box_boolean_retry_voxel_size(
            context.scene.box_quality
        )
        casting_feet_height = _casting_feet_height_from_scene()
        state["casting_feet_height"] = casting_feet_height
        state["casting_feet"] = (
            casting_feet_height > 0 and not context.scene.pro_two_part_silicone
        )
        state["pin_system_type"] = (
            "SCREW"
            if context.scene.clamp_screws
            else context.scene.clamp_pin_system_type
        )
        state["clamp_pin_type"] = getattr(context.scene, "clamp_pin_type", "barrier")
        state["n_splits"] = get_effective_box_parts(context.scene)
        live_split_plane_specs = direct_split_plane_specs(
            log_context="Silicone confirm capture"
        )
        captured_split_plane_specs = (
            live_split_plane_specs
            or stored_silicone_split_plane_specs(context.scene)
        )
        state["split_plane_specs"] = resolve_splitter_plane_specs(
            context.scene,
            captured_split_plane_specs,
        )
        store_silicone_split_plane_specs(
            state["split_plane_specs"],
            context.scene,
        )
        set_keep_silicone_split_planes_after_build(False, context.scene)
        remove_direct_split_planes()
        (
            state["split_planes"],
            state["organic_split_planes"],
        ) = split_specs_query_values(
            state["split_plane_specs"]
        )
        state["splitter_plane_specs"] = state["split_plane_specs"]
        state["has_splits"] = bool(state["splitter_plane_specs"])
        add_deposit()
        if bool(state["casting_feet"]):
            add_casting_feet()
        recut_channels()
        state["splits_z"] = _horizontal_channel_split_heights(context.scene)
        logger.info(
            "Confirm split configuration: plane_count=%d has_splits=%s "
            "requested_box_parts=%d horizontal_split_heights=%s",
            len(state["splitter_plane_specs"]),
            state["has_splits"],
            state["n_splits"],
            state["splits_z"],
        )
        hide_working_patron()

    def build_channel_box() -> None:
        add_channels(
            float(state["casting_feet_height"]),
            include_casting_feet=bool(state["casting_feet"]),
        )
        volume = build_silicone_mold_preview(
            float(state["box_voxel_size"]),
            retry_voxel_size=float(state["box_boolean_retry_voxel_size"]),
        )
        context.scene.volume = volume
        context.scene.casting_volume_ml = calculate_casting_volume()
        hide_silicone_mold_preview()
        hide_working_patron()

    def request_and_import_server_response():
        logger.debug(f"Executing confirm_mold_req")
        request_fn = confirm_mold_req_async if async_server else confirm_mold_req
        result = request_fn(
            float(state["box_voxel_size"]),
            context.scene.channel_width,
            int(state["n_splits"]),
            box_thickness=context.scene.box_thickness,
            base_thickness=context.scene.base_thickness,
            base_type=context.scene.base_type,
            base_pin_type=context.scene.base_pin_type,
            wing_width=context.scene.wing_width,
            clamp_width=context.scene.clamp_width,
            clamp_depth=context.scene.clamp_depth,
            barrier_tolerance=context.scene.clamp_tolerance,
            clamp_pin_type=str(state["clamp_pin_type"]),
            pin_system_type=str(state["pin_system_type"]),
            screw_diameter=context.scene.clamp_screw_diameter,
            casting_feet=bool(state["casting_feet"]),
            casting_feet_height=float(state["casting_feet_height"]),
            casting_feet_size_factor=context.scene.casting_feet_size_factor,
            splits_z=list(state["splits_z"]),
            split_planes=str(state["split_planes"]),
            organic_split_planes=str(state["organic_split_planes"]),
            barrier_male_top_extension=barrier_male_top_extension(context.scene),
            silicone_weight_text=(
                silicone_mix_engraving(context.scene)
                if not is_lite_tier()
                else None
            ),
        )
        set_base_substracter_hidden(True)
        return result

    def iter_imported_boolean_steps():
        manual_boolean_start_time = time.perf_counter()
        screw_mode = str(state["pin_system_type"]) == "SCREW"
        boolean_steps = list(
            iter_manual_booleans_after_server_import(
                screw_mode,
                include_clamps=bool(state["has_splits"]),
            )
        )

        def wrap_boolean_step(step, *, is_last: bool):
            def wrapped_step() -> None:
                set_base_substracter_hidden(True)
                try:
                    step()
                finally:
                    set_base_substracter_hidden(True)
                    if is_last:
                        logger.debug(
                            "Confirm mold manual boolean phase took %.3fs",
                            time.perf_counter() - manual_boolean_start_time,
                        )

            return wrapped_step

        for index, (label, step) in enumerate(boolean_steps):
            yield label, wrap_boolean_step(
                step,
                is_last=index == len(boolean_steps) - 1,
            )

    def prepare_imported_base_substracter() -> None:
        if getattr(context.scene, "mold_box_shape_type", "adapted") != "cube":
            prepare_base_substracter_after_server_import()

    def remesh_imported_barriers() -> None:
        barriers = [
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and any(
                marker in obj.name.lower()
                for marker in (
                    "barrier_male",
                    "barrier_female",
                    "barrier_vertical_reinforcement",
                )
            )
        ]
        for barrier in barriers:
            _remesh_barrier_from_scene(barrier)
        logger.debug(
            "Debug checkpoint remeshed %d imported barrier/reinforcement%s",
            len(barriers),
            "" if len(barriers) == 1 else "s",
        )

    def postprocess_imported_box():
        casting_feet_height = float(state["casting_feet_height"])
        clean_top_height = (
            min(3.2, casting_feet_height) if state["casting_feet"] else 3.2
        )
        logger.debug(f"Cleaning imported box with clean_top_height={clean_top_height}")

        postprocess_start_time = time.perf_counter()
        task = begin_z9f3(
            float(state["box_voxel_size"]),
            _b4=context.scene.box_thickness,
            _c2=clean_top_height,
            _casting_b4=different_casting_box_thickness(context.scene),
            reuse_source_as_base_substracter=True,
            # Offset the channel/funnel surface instead of fitting a new
            # primitive around protrusions and adding their depth to every wall.
            shape_type=(
                "adapted" if context.scene.mold_type_preview == "ADAPTED_BOX"
                else getattr(context.scene, "mold_box_shape_type", "adapted")
            ),
            vertical_faces=getattr(context.scene, "mold_box_faces", 4),
        )

        def finish(opened_box):
            logger.debug(
                "Confirm mold postprocess phase took %.3fs",
                time.perf_counter() - postprocess_start_time,
            )
            assign_generated_material(bpy.data.objects.get("box"))
            return opened_box

        return task.then(finish)

    def add_basing():
        def steps():
            if not is_lite_tier() and bpy.data.objects.get("Text1") is None:
                weight_text = silicone_mix_engraving(context.scene)
                yield request_weight_text_mesh_async(weight_text)

            basing_start_time = time.perf_counter()
            add_basing_to_system(
                context.scene.volume,
                context.scene.wing_join_patron,
                context.scene.master_base_pin,
                context.scene.wing_width,
                context.scene.master_base_pin_tolerance,
                context.scene.master_base_pin_height,
                context.scene.silicone_density,
                context.scene.base_thickness,
                context.scene.base_type,
                pre_join_base_callback,
                weight_text=silicone_mix_engraving(context.scene),
            )
            state["basing_elapsed"] = time.perf_counter() - basing_start_time

        sequence = BackgroundTaskSequence(steps())
        sequence.redraw_interval = 0.1
        return sequence

    def generate_inner_cores():
        if context.scene.pro_inner_cavity:
            if async_server:
                return create_inner_core_async(context)
            create_inner_core(context)

    def add_clamps() -> None:
        add_clamps_to_box()

    def split_system():
        split_start_time = time.perf_counter()
        if bool(state["has_splits"]):
            logger.info(
                "Running mold-box split and pre-split island cleanup with %d "
                "split plane%s",
                len(state["splitter_plane_specs"]),
                "" if len(state["splitter_plane_specs"]) == 1 else "s",
            )
            task = begin_split(
                int(state["n_splits"]),
                splits_z=list(state["splits_z"]),
                split_plane_specs=state["splitter_plane_specs"],
            )
            return task.then(
                lambda parts: (
                    state.__setitem__(
                        "split_elapsed",
                        time.perf_counter() - split_start_time,
                    )
                    or parts
                )
            )
        else:
            logger.info(
                "No splitter planes were captured; cleaning isolated box "
                "islands without splitting"
            )
            box = _mesh_object_by_name("box")
            if box is None:
                raise RuntimeError("No box object found for base locking geometry")
            box = _remove_pre_split_isolated_meshes(box)
            casting_boxes = pending_casting_boxes()
            if len(casting_boxes) == 1:
                casting_boxes = [
                    _remove_pre_split_isolated_meshes(casting_boxes[0])
                ]
            _subtract_base_female_locking_geometry(
                [box],
                casting_boxes,
            )
            base = bpy.data.objects.get("base")
            if base is not None:
                Object(base).name = "master_base"
        state["split_elapsed"] = time.perf_counter() - split_start_time
        return None

    def subtract_inner_cores() -> None:
        if context.scene.pro_inner_cavity:
            subtract_inner_core_objects_from_box(context)

    def finish_casting_boxes() -> None:
        casting_box_elapsed = 0.0
        if context.scene.pro_casting_box:
            casting_box_start_time = time.perf_counter()
            duplicate_cut_casting_boxes(cut_vertical=cut_casting_vertical)
            casting_box_elapsed += time.perf_counter() - casting_box_start_time
        if context.scene.pro_casting_box and two_part_casting_side is not None:
            casting_box_start_time = time.perf_counter()
            cut_two_part_casting_boxes(
                two_part_casting_side,
                context.scene.wing_width,
                cut_open_base_side=cut_casting_open_base_side,
            )
            casting_box_elapsed += time.perf_counter() - casting_box_start_time
        state["casting_box_elapsed"] = casting_box_elapsed

    def finalize_patron() -> None:
        finalize_start_time = time.perf_counter()
        finalize_master_as_patron()
        state["finalize_elapsed"] = time.perf_counter() - finalize_start_time

    def create_clips() -> None:
        if not bool(state["has_splits"]):
            return
        clips_start_time = time.perf_counter()
        create_clip_from_scene(context.scene)
        state["clips_elapsed"] = time.perf_counter() - clips_start_time

    def space_system() -> None:
        spacing_start_time = time.perf_counter()
        reveal_silicone_mold_preview()
        space_mold_system()
        state["spacing_elapsed"] = time.perf_counter() - spacing_start_time

    def refresh_final_mold_metrics() -> None:
        metrics_start_time = time.perf_counter()
        silicone_raw = bpy.data.objects.get("silicone_mold")
        if silicone_raw is not None:
            context.scene.volume = Object(silicone_raw).volume
        state["metrics_elapsed"] = time.perf_counter() - metrics_start_time

    def refresh_display() -> None:
        viewport_start_time = time.perf_counter()
        refresh_viewport_material_display(context)
        state["viewport_elapsed"] = time.perf_counter() - viewport_start_time
        logger.debug(
            "Confirm finalization phases: basing=%.3fs, split=%.3fs, "
            "casting_boxes=%.3fs, finalize_master=%.3fs, clips=%.3fs, "
            "spacing=%.3fs, metrics=%.3fs, viewport=%.3fs",
            float(state["basing_elapsed"]),
            float(state["split_elapsed"]),
            float(state["casting_box_elapsed"]),
            float(state["finalize_elapsed"]),
            float(state["clips_elapsed"]),
            float(state["spacing_elapsed"]),
            float(state["metrics_elapsed"]),
            float(state["viewport_elapsed"]),
        )
        logger.debug(
            "Confirm mold completed in %.3fs",
            time.perf_counter() - total_start_time,
        )

    yield "Preparing channels", prepare_channels
    yield "Generating channel box", build_channel_box
    yield "Generating mold system", request_and_import_server_response
    yield "Remeshing imported barriers and reinforcements", remesh_imported_barriers
    yield "Refining mold box", postprocess_imported_box
    yield "Preparing base cutter", prepare_imported_base_substracter
    for label, step in iter_imported_boolean_steps():
        yield label, step
    yield "Generating base", add_basing
    yield "Adding clamps and support pilars to mold box", add_clamps
    yield "Trimming assembled mold box", lambda: subtract_base_substracter_from_box(
        extend_opening=getattr(context.scene, "mold_box_shape_type", "adapted") != "adapted",
        extrude_caps=getattr(context.scene, "mold_box_shape_type", "adapted") == "cube",
    )
    if context.scene.pro_inner_cavity:
        yield "Generating inner cores", generate_inner_cores
    if context.scene.pro_inner_cavity:
        yield "Subtracting inner cores", subtract_inner_cores
    yield "Splitting mold system", split_system
    yield "Preparing casting boxes", finish_casting_boxes
    yield "Finalizing patron", finalize_patron
    yield "Generating clips", create_clips
    yield "Spacing mold system", space_system
    yield "Updating mold metrics", refresh_final_mold_metrics
    yield "Refreshing display", refresh_display


def confirm(
    context,
    two_part_casting_side: str | None = None,
    cut_casting_open_base_side: bool = False,
    cut_casting_vertical: bool = True,
    pre_join_base_callback=None,
):
    for label, step in iter_confirm_steps(
        context,
        two_part_casting_side=two_part_casting_side,
        cut_casting_open_base_side=cut_casting_open_base_side,
        cut_casting_vertical=cut_casting_vertical,
        pre_join_base_callback=pre_join_base_callback,
    ):
        finish_task_sync(step())
        if label not in CONFIRM_SKIP_REDRAW_STEPS:
            refresh_generated_object_materials()
            refresh_viewport_material_display(context)
            force_viewport_redraw(context)
