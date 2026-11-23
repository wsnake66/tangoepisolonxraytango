# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Prepare the Slip Casting ``w`` and ``extr`` reference objects."""

import logging
import math
import time

import bmesh  # type: ignore
import bpy  # type: ignore
import mathutils  # type: ignore

from ..background_worker import BackgroundTaskSequence, submit_worker_task
from ..bl_utils import calculate_rotation_diff_matrix
from ..environment import get_server_base_url
from ..cast_plan import read_cast_plan
from ..clearance_proxy_cache import (
    clearance_proxy_key, get_clearance_proxy, store_clearance_proxy,
)

from ..materials import (
    assign_funnels_material,
    assign_moldbox_material,
    assign_slip_casting_funnel_span_material,
)
from ..mesh_decimation import (
    begin_create_fast_simplified_object,
    begin_direct_undercuts_target_reduction,
    create_mesh_from_triangles,
    extract_mesh_triangles,
)
from ..mold_types import (
    is_slip_casting_vase_type,
    slip_casting_funnels_on_top,
)
from ..modifiers import build_voxel_modifier, diff_mod, intersect_mod, union_mod
from ..object import Object, remove_objects_safely, remove_unused_meshes, suppress_ui_breathe
from ..slicer_mesh_cleanup import clean_mesh_for_manifold_boolean
from ..progress import force_viewport_redraw
from ..slip_casting_base_pairs import (
    cleanup_slip_casting_base_pairs,
    pair_slip_casting_bases,
)
from ..split_specs import split_spec_point_normal
from ..voxel_size import get_box_voxel_size, get_master_voxel_size
from .clear_undercuts import begin_clear_undercuts
from .direct_split_planes import (
    direct_split_plane_specs,
    stored_silicone_split_plane_specs,
)
from .geometry_adapter import (
    acquire_geometry_worker,
    begin_apply_nearest_surface_shrinkwrap,
    begin_clear_mesh_faces_to_point_with_worker,
    match_mesh_parts_to_world_points_with_worker,
)
from .mesh_envelope import begin_mesh_envelope, begin_optimized_mesh_envelope
from .server import import_server_response, request_server_async


logger = logging.getLogger(__name__)

SLIP_CASTING_PREPARE_REFERENCE_KEY = "moldboxer_slip_casting_prepare_reference"
SLIP_CASTING_RAW_CORE_KEY = "moldboxer_slip_casting_raw_core"
SLIP_CASTING_FUNNELS_BUILT_KEY = "moldboxer_slip_casting_funnels_built"
SLIP_CASTING_CORE_TOP_CLEAN_MM = 5.0
SLIP_CASTING_CORE_WRAPPER_KEY = "moldboxer_slip_casting_core_wrapper"
SLIP_CASTING_CORE_WRAPPER_EXTRA_WRAP_MM = 0.25
SLIP_CASTING_CORE_WRAPPER_TOP_CUT_MM = 1.0
SLIP_CASTING_CORE_WRAPPER_TOP_TOLERANCE_MM = 1e-3
SLIP_CASTING_BOTTOM_EXTENSION_KEY = "moldboxer_slip_casting_bottom_extension"
SLIP_CASTING_BOTTOM_EXTENSION_NAME = "slip_casting_bottom_extension"
SLIP_CASTING_BOTTOM_KEY = "moldboxer_slip_casting_bottom"
SLIP_CASTING_BOTTOM_NAME = "slip_casting_bottom"
SLIP_CASTING_BOTTOM_PART_FACES_NAME = "slip_casting_bottom_reference_faces"
SLIP_CASTING_BOTTOM_LOOP_MAX_HEIGHT_FACTOR = 0.90
SLIP_CASTING_BOTTOM_LOOP_NAME = "slip_casting_bottom_loop"
SLIP_CASTING_BOTTOM_LOOP_KEY = "moldboxer_slip_casting_bottom_loop"
SLIP_CASTING_VASE_BASE_KEY = "moldboxer_slip_casting_vase_base"
SLIP_CASTING_VASE_BASE_NAME = "foot"
SLIP_CASTING_FEMALE_BASE_KEY = "moldboxer_slip_casting_female_base"
SLIP_CASTING_FEMALE_BASE_NAME = "female_base"
SLIP_CASTING_VASE_BASE_ROLE_KEY = "moldboxer_slip_casting_vase_base_role"
SLIP_CASTING_VASE_BASE_WRAP_COUNT = 3
SLIP_CASTING_BOTTOM_FACE_BAND_MM = 1.0
SLIP_CASTING_BOTTOM_NORMAL_Z_MAX = -0.99
SLIP_CASTING_BOTTOM_PART_Z_TOLERANCE_MM = 0.1
SLIP_CASTING_VASE_TOP_PART_Z_TOLERANCE_MM = 0.1
SLIP_CASTING_VASE_BASE_MIN_TOP_VOLUME_ML = 0.2
SLIP_CASTING_VASE_BASE_LOWER_UNION_OVERLAP_MM = 0.05
SLIP_CASTING_FINISHED_BASE_Z_OFFSET_MM = -0.15
SLIP_CASTING_VASE_BASE_PIN_FLAT_TIP_HEIGHT_FACTOR = 0.8
SLIP_CASTING_VASE_BASE_PIN_PREFIX = "_cast_item_09_"
SLIP_CASTING_DEFAULT_PIN_DIAMETER_MM = 15.0
SLIP_CASTING_DEFAULT_LOCKING_TOLERANCE_MM = 0.35
SLIP_CASTING_VASE_BASE_PIN_RAY_MARGIN_MM = 1.0
SLIP_CASTING_VASE_BASE_PIN_MIN_HORIZONTAL_NORMAL = 1.0e-6
SLIP_CASTING_W_WRAP_COUNT = 3
SLIP_CASTING_W_TOP_CLEAN_VOXEL_FACTOR = 2.0
SLIP_CASTING_W_TOP_TARGET_OFFSET_MM = 2.0
SLIP_CASTING_W_BOTTOM_SPHERE_SIZE_FACTOR = 0.6
SLIP_CASTING_W_BOTTOM_BASE_EXTENSION_APPROACH = "BASE_EXTENSION"
SLIP_CASTING_W_BOTTOM_SPHERE_RELATIVE_CUT_APPROACH = "SPHERE_RELATIVE_CUT"
SLIP_CASTING_W_BOTTOM_APPROACH = (
    SLIP_CASTING_W_BOTTOM_BASE_EXTENSION_APPROACH
)
SLIP_CASTING_W_BOTTOM_SPHERE_CUT_HEIGHT_FACTOR = 0.05
SLIP_CASTING_PREPARE_DEBUG_STOP_AFTER_EXTR_BOTTOM = False
SLIP_CASTING_PREPARE_DEBUG_STOP_BEFORE_BOTTOM_EXTENSION_REMOVAL = False
SLIP_CASTING_PREPARE_DEBUG_KEEP_BOTTOM_EXTR = False
SLIP_CASTING_BOTTOM_EXTR_WRAP_DISTANCE_FACTOR = 0.5
SLIP_CASTING_TOP_PREPARE_OBJECT_NAMES = ("w", "extr")
SLIP_CASTING_BOTTOM_PREPARE_OBJECT_NAMES = ("w_bottom", "extr_bottom")
SLIP_CASTING_PREPARE_OBJECT_NAMES = (
    *SLIP_CASTING_TOP_PREPARE_OBJECT_NAMES,
    *SLIP_CASTING_BOTTOM_PREPARE_OBJECT_NAMES,
)
SLIP_CASTING_RAW_CORE_PREFIX = "slip_casting_raw_core"
SLIP_CASTING_BOTTOM_RAW_CORE_PREFIX = "slip_casting_bottom_raw_core"
SLIP_CASTING_CORE_MASTER_CLEARANCE_PREFIX = "cast_item_01"
SLIP_CASTING_CORE_MASTER_CLEARANCE_KEY = (
    "moldboxer_slip_casting_core_master_clearance"
)
SLIP_CASTING_CORE_MASTER_EXTERIOR_PREFIX = (
    "cast_item_02"
)
SLIP_CASTING_CORE_MASTER_EXTERIOR_KEY = (
    "moldboxer_slip_casting_core_master_exterior_clearance"
)
SLIP_CASTING_CORE_MASTER_SOURCE_KEY = "moldboxer_slip_casting_core_source"
SLIP_CASTING_FUNNEL_CLEARANCE_PROXY_NAME = (
    "cast_item_03"
)
SLIP_CASTING_FUNNEL_SPAN_WRAPPER_NAME = "cast_item_04"
SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY = (
    "moldboxer_slip_casting_funnel_span_wrapper"
)
SLIP_CASTING_FUNNEL_SPAN_EXTR_TARGET_NAME = (
    "cast_item_05"
)
SLIP_CASTING_FUNNEL_SPAN_EXTR_TARGET_KEY = (
    "moldboxer_slip_casting_funnel_span_extr_target"
)
SLIP_CASTING_FUNNEL_SPAN_WRAPPER_WRAP_COUNT = 3
SLIP_CASTING_FUNNEL_SPAN_CORE_PREFIX = "cast_part"
SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX = "_final"
SLIP_CASTING_FUNNEL_PART_WRAPPER_DISTANCE_MM = 0.25
SLIP_CASTING_FUNNEL_PART_WRAPPER_WRAP_COUNT = 3
SLIP_CASTING_FUNNEL_FINAL_CLEAR_VOXEL_FACTOR = 0.8
SLIP_CASTING_FUNNEL_FINAL_REMESH_VOXEL_FACTOR = 0.5
SLIP_CASTING_VASE_BASE_PART_WRAPPER_DISTANCE_MM = 0.25
SLIP_CASTING_VASE_BASE_PART_WRAPPER_WRAP_COUNT = 3
SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_NAME = (
    "cast_item_06"
)
SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_DISTANCE_MM = 0.5
SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_HEIGHT_FACTOR = 0.20
SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_Z_MARGIN_MM = 0.5
SLIP_CASTING_VASE_FUNNEL_PART_PREFIX = "cast_item_07"
SLIP_CASTING_VASE_FUNNEL_PART_KEY = (
    "moldboxer_slip_casting_vase_funnel_reference"
)
SLIP_CASTING_VASE_BASE_PART_PREFIX = "cast_item_08"
SLIP_CASTING_VASE_BASE_PART_KEY = "moldboxer_slip_casting_vase_base_reference"
SLIP_CASTING_VASE_FUNNEL_PART_CENTER_KEYS = (
    "moldboxer_slip_casting_vase_funnel_reference_center_x",
    "moldboxer_slip_casting_vase_funnel_reference_center_y",
    "moldboxer_slip_casting_vase_funnel_reference_center_z",
)
SLIP_CASTING_VASE_FUNNEL_PART_CENTER_MARKER_KEY = (
    "moldboxer_slip_casting_vase_funnel_reference_center_marker"
)
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_CLEARANCE_GENERATION = False
SLIP_CASTING_INTERNAL_DEBUG_STOP_AFTER_CLEARANCE = False
SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_CLEARANCE_SUBTRACTION = False
SLIP_CASTING_INTERNAL_DEBUG_SKIP_OUTWARD_CLEARANCE = False
SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_ANY_CLEARANCE = False
SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_REGION_CROPS = False
SLIP_CASTING_INTERNAL_DEBUG_STOP_AFTER_REGION_CROPS = False
# Extra radius and half-height for a 100 mm master; scaled by overall model size.
SLIP_CASTING_INTERNAL_CROP_MARGIN_MM = 10.0
SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION = False
# Keep the base construction geometry visible after a complete build.
SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_BASE_INSPECTION = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_FUNNEL_SUBTRACTIONS = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_CLEARANCE_GENERATION = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_BEFORE_BASE_CLEARANCE_SUBTRACTION = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_CLEARANCE_SUBTRACTION = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_PART_MATCHING = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_PART_MATCHING = False
SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_PER_PART_MASTER_WRAPS = False
SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_DETECTED_PARTS = False
SLIP_CASTING_PENDING_MASTER_UNION_KEY = "moldboxer_slip_casting_pending_master_union"
def _slip_casting_master(scene=None) -> Object | None:
    objects = getattr(scene, "objects", None) if scene is not None else None
    master_raw = objects.get("patron") if objects is not None else None
    if master_raw is None:
        master_raw = bpy.data.objects.get("patron")
    if master_raw is None or master_raw.type != "MESH":
        return None
    return Object(master_raw)


def slip_casting_funnels_built(scene=None) -> bool:
    """Return whether the funnel-generation stage completed."""

    objects = getattr(scene, "objects", None) if scene is not None else None
    objects = objects or bpy.data.objects
    master = objects.get("patron")
    return bool(
        master is not None
        and master.get(SLIP_CASTING_FUNNELS_BUILT_KEY, False)
    )


def slip_casting_has_prepared_parts(scene) -> bool:
    """Keep preparation unavailable until every generated funnel/base is removed."""

    for raw in scene.objects:
        if raw.type != "MESH":
            continue
        if (
            SLIP_CASTING_PENDING_MASTER_UNION_KEY in raw
            or raw.get("moldboxer_rounded_funnel_mold", False)
            or raw.get(SLIP_CASTING_VASE_BASE_KEY, False)
            or raw.get(SLIP_CASTING_FEMALE_BASE_KEY, False)
            or raw.get(SLIP_CASTING_VASE_BASE_ROLE_KEY) in {"MALE", "FEMALE"}
        ):
            return True
        name = raw.name.split(".", 1)[0]
        if (
            name == SLIP_CASTING_VASE_BASE_NAME
            or name.startswith(SLIP_CASTING_VASE_BASE_NAME + "_")
            or name == SLIP_CASTING_FEMALE_BASE_NAME
            or name.startswith(SLIP_CASTING_FEMALE_BASE_NAME + "_")
            or (
                name.startswith(SLIP_CASTING_FUNNEL_SPAN_CORE_PREFIX)
                and name.endswith(SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX)
            )
            or (name.startswith("slip_casting_funnel_span_core") and name.endswith("_wrapper"))
        ):
            return True
    return False


def slip_casting_vase_prepared(scene=None) -> bool:
    """Return whether the current Prepare Vase workflow produced its base."""

    objects = getattr(scene, "objects", None) if scene is not None else None
    objects = objects or bpy.data.objects
    vase_base = objects.get(SLIP_CASTING_VASE_BASE_NAME)
    if vase_base is None:
        vase_base = objects.get("vase_base")
    return bool(
        vase_base is not None
        and vase_base.type == "MESH"
        and vase_base.get(SLIP_CASTING_VASE_BASE_KEY, False)
    )


def slip_casting_initial_stage_complete(scene) -> bool:
    """Return whether the selected Slip Casting mode may generate its mold."""

    identifier = getattr(scene, "mold_type_preview", "")
    if identifier == "SILICONE_MULTIPART":
        return True
    if is_slip_casting_vase_type(identifier):
        # This records completed preparation, not the presence of its outputs.
        # Deleting all feet and funnels keeps generation available; Restart
        # clears the marker and a new project starts with a new master.
        return slip_casting_funnels_built(scene)
    return False


def slip_casting_cavities_filled(scene=None) -> bool:
    objects = getattr(scene, "objects", None) if scene is not None else None
    objects = objects or bpy.data.objects
    if any(
        obj.type == "MESH" and bool(obj.get(SLIP_CASTING_RAW_CORE_KEY, False))
        for obj in objects
    ):
        return True
    if slip_casting_vase_prepared(scene):
        return True
    return all(
        (reference := objects.get(object_name)) is not None
        and reference.get(SLIP_CASTING_PREPARE_REFERENCE_KEY) == object_name
        for object_name in SLIP_CASTING_PREPARE_OBJECT_NAMES
    )


def _set_reference_hidden(reference: Object, hidden: bool) -> None:
    reference.object.hide_set(hidden)
    reference.object.hide_viewport = hidden
    reference.object.hide_render = hidden


def _set_funnel_intermediate_hidden(reference: Object, hidden: bool) -> None:
    """Hide funnel construction geometry whenever the viewport can redraw."""

    reference.hide_during_ui_breathe = True
    _set_reference_hidden(reference, hidden)


def _ensure_prepare_names_available(object_names=None) -> None:
    required_names = object_names or (
        *SLIP_CASTING_PREPARE_OBJECT_NAMES,
        SLIP_CASTING_VASE_BASE_NAME,
    )
    for object_name in required_names:
        existing = bpy.data.objects.get(object_name)
        if existing is not None:
            raise RuntimeError(
                f'Prepare Vase requires the object name "{object_name}" to be free'
            )


def _remove_prepare_references(
    object_names=SLIP_CASTING_PREPARE_OBJECT_NAMES,
) -> None:
    for object_name in object_names:
        reference = bpy.data.objects.get(object_name)
        if (
            reference is not None
            and reference.get(SLIP_CASTING_PREPARE_REFERENCE_KEY) == object_name
        ):
            remove_objects_safely((reference,))


def _import_slip_casting_raw_cores(
    response,
    *,
    voxel_size: float,
    expected_prefix: str,
    bottom: bool,
    finish_geometry: bool = True,
) -> list[Object]:
    imported_objects = import_server_response(
        response,
        remesh_imported_objects=finish_geometry,
        decorate_imported_objects=finish_geometry,
    )
    imported_cores = [Object(imported_object) for imported_object in imported_objects]
    try:
        invalid_cores = [
            core
            for core in imported_cores
            if core.object.type != "MESH"
            or not core.name.lower().startswith(expected_prefix)
        ]
        if invalid_cores:
            imported_names = ", ".join(core.name for core in imported_cores)
            raise ValueError(
                "Slip Casting core response included unexpected objects: "
                f"{imported_names or 'none'}"
            )

        for core in imported_cores:
            if finish_geometry:
                core.apply_modifier(build_voxel_modifier(voxel_size))
                if not bottom:
                    core.clean_top(SLIP_CASTING_CORE_TOP_CLEAN_MM)
            else:
                core.hide_during_ui_breathe = True
                _set_reference_hidden(core, True)
                core.object.hide_select = True
            core.object[SLIP_CASTING_RAW_CORE_KEY] = True
    except BaseException:
        for core in imported_cores:
            if core.object.name in bpy.data.objects:
                core.remove()
        raise
    logger.info(
        "Imported %s Slip Casting raw core%s from server",
        len(imported_cores),
        "" if len(imported_cores) == 1 else "s",
    )
    return imported_cores


def _finish_slip_casting_core_wrapper(
    core: Object,
    wrapper: Object,
    *,
    core_limit_z: float | None,
    bottom: bool,
) -> Object:
    """Keep a generated core wrapper and finish its oriented Z limit."""
    core_name = core.name
    wrapper.name = f"{core_name}_wrapper"
    if not bottom:
        if core_limit_z is None:
            raise ValueError("Top Slip Casting core requires a maximum-Z limit")
        wrapper -= core
        wrapper_cut_z = core_limit_z - SLIP_CASTING_CORE_WRAPPER_TOP_CUT_MM
        core_center = core.center_coords
        wrapper.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector((core_center.x, core_center.y, wrapper_cut_z)),
        )
        selected_count = wrapper.select_limit_flat_faces(max_co=True)
        if selected_count <= 0:
            raise RuntimeError(
                f"Could not select the top face of Slip Casting wrapper {wrapper.name}"
            )
        wrapper_limit_z = float(wrapper.max_z)
        wrapper.move_selected(core_limit_z - wrapper_limit_z)
        wrapper.recalculate_normals()
        finished_limit_z = float(wrapper.max_z)
        if (
            abs(finished_limit_z - core_limit_z)
            > SLIP_CASTING_CORE_WRAPPER_TOP_TOLERANCE_MM
        ):
            raise RuntimeError(
                f"Slip Casting wrapper {wrapper.name} did not reach its core limit: "
                f"wrapper_limit_z={finished_limit_z} core_limit_z={core_limit_z}"
            )
    wrapper.object[SLIP_CASTING_CORE_WRAPPER_KEY] = True
    assign_moldbox_material(wrapper.object)
    wrapper.hide_during_ui_breathe = False
    wrapper.object.hide_set(False)
    wrapper.object.hide_viewport = False
    wrapper.object.hide_render = False
    wrapper.object.display_type = "SOLID"
    logger.info(
        "Generated retained Slip Casting wrapper %s for core %s",
        wrapper.name,
        core_name,
    )
    return wrapper


def _build_slip_casting_vase_base(
    bottom_extension: Object,
    bottom_cores: list[Object],
    *,
    voxel_size: float,
):
    """Wrap the bottom extension, joined with any returned bottom cores."""
    joined_target = bottom_extension.duplicate("_vase_base_target")
    joined_target.hide_during_ui_breathe = True
    _set_reference_hidden(joined_target, False)
    try:
        for core in bottom_cores:
            joined_core = core.duplicate("_vase_base_target")
            joined_core.hide_during_ui_breathe = True
            _set_reference_hidden(joined_core, False)
            joined_target.join(joined_core)

        with suppress_ui_breathe():
            vase_base = yield begin_mesh_envelope(
                joined_target,
                voxel_size=voxel_size,
                distance=0.0,
                n_wraps=SLIP_CASTING_VASE_BASE_WRAP_COUNT,
                name_adder="_vase_base",
                cut_bot=False,
                build_from_sphere=True,
            )
    finally:
        if joined_target.object.name in bpy.data.objects:
            joined_target.remove()

    vase_base.name = SLIP_CASTING_VASE_BASE_NAME
    vase_base.object[SLIP_CASTING_VASE_BASE_KEY] = True
    assign_moldbox_material(vase_base.object)
    vase_base.hide_during_ui_breathe = False
    _set_reference_hidden(vase_base, False)
    vase_base.object.display_type = "SOLID"
    logger.info(
        "Generated Slip Casting vase base from the bottom extension and %s "
        "bottom core%s using %s zero-distance wraps",
        len(bottom_cores),
        "" if len(bottom_cores) == 1 else "s",
        SLIP_CASTING_VASE_BASE_WRAP_COUNT,
    )
    return vase_base


def _extract_slip_casting_bottom_faces(
    master: Object,
    *,
    object_name: str,
    marker_key: str,
) -> Object | None:
    """Copy the master's lowest downward-facing polygons in world coordinates."""

    if bpy.data.objects.get(object_name) is not None:
        raise RuntimeError(
            f'Prepare Vase requires the object name "{object_name}" '
            "to be free"
        )

    matrix_world = master.matrix_world
    normal_matrix = master.inverse_transpose_matrix_world.to_3x3()
    maximum_bottom_z = master.min_z + SLIP_CASTING_BOTTOM_FACE_BAND_MM
    selected_polygons = []
    for polygon in master.object.data.polygons:
        world_center = matrix_world @ polygon.center
        world_normal = (normal_matrix @ polygon.normal).normalized()
        if (
            world_center.z <= maximum_bottom_z
            and world_normal.z <= SLIP_CASTING_BOTTOM_NORMAL_Z_MAX
        ):
            selected_polygons.append(polygon)

    if not selected_polygons:
        logger.warning(
            "Prepare Vase found no downward bottom faces below z=%.6f on %s",
            maximum_bottom_z,
            master.name,
        )
        return None

    source_vertex_indices = sorted(
        {
            int(vertex_index)
            for polygon in selected_polygons
            for vertex_index in polygon.vertices
        }
    )
    output_index_by_source = {
        source_index: output_index
        for output_index, source_index in enumerate(source_vertex_indices)
    }
    vertices = [
        tuple(matrix_world @ master.object.data.vertices[source_index].co)
        for source_index in source_vertex_indices
    ]
    faces = [
        [output_index_by_source[int(index)] for index in polygon.vertices]
        for polygon in selected_polygons
    ]

    mesh = bpy.data.meshes.new(f"{object_name}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    bottom_raw = bpy.data.objects.new(object_name, mesh)
    if master.object.users_collection:
        master.object.users_collection[0].objects.link(bottom_raw)
    else:
        bpy.context.collection.objects.link(bottom_raw)

    bottom = Object(bottom_raw)
    bottom.object[marker_key] = True
    assign_moldbox_material(bottom.object)
    logger.info(
        "Extracted Slip Casting bottom faces: object=%s faces=%s "
        "threshold_z=%.6f normal_z<=%.3f",
        object_name,
        len(selected_polygons),
        maximum_bottom_z,
        SLIP_CASTING_BOTTOM_NORMAL_Z_MAX,
    )
    return bottom




def _existing_slip_casting_vase_funnel_reference_center_markers(
    scene=None,
) -> list[Object]:
    objects = getattr(scene, "objects", None) if scene is not None else None
    objects = objects or bpy.data.objects
    return [
        Object(raw)
        for raw in objects
        if raw.type == "MESH"
        and bool(
            raw.get(
                SLIP_CASTING_VASE_FUNNEL_PART_CENTER_MARKER_KEY,
                False,
            )
        )
    ]


def _show_slip_casting_reference_centers(references, master):
    """Mark the stored analysis centers used to position clearance regions."""
    radius = max(master.width, master.depth, master.height) * 0.006
    vertices = [
        (radius, 0, 0), (-radius, 0, 0),
        (0, radius, 0), (0, -radius, 0),
        (0, 0, radius), (0, 0, -radius),
    ]
    faces = [
        (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
        (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
    ]
    for reference in references:
        name = f"{reference.name}_item_15"
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        raw = bpy.data.objects.new(name, mesh)
        collection = (
            reference.object.users_collection[0]
            if reference.object.users_collection else bpy.context.collection
        )
        collection.objects.link(raw)
        raw.location = _slip_casting_clearance_region_center(reference)
        raw[SLIP_CASTING_VASE_FUNNEL_PART_CENTER_MARKER_KEY] = True
        raw.show_in_front = True
        raw.show_name = True
        raw.hide_render = True
        raw.display_type = "SOLID"
        assign_funnels_material(raw)


def _create_slip_casting_vase_funnel_reference_objects(
    master,
    results,
    *,
    name_prefix: str = SLIP_CASTING_VASE_FUNNEL_PART_PREFIX,
    marker_key: str = SLIP_CASTING_VASE_FUNNEL_PART_KEY,
):
    collection = (
        master.object.users_collection[0]
        if master.object.users_collection else bpy.context.collection
    )
    outputs = []
    try:
        for index, spec in enumerate(results, start=1):
            name = f"{name_prefix}_{index:03d}"
            mesh = bpy.data.meshes.new(f"{name}_mesh")
            mesh.from_pydata([spec["minimum"], spec["maximum"]], [], [])
            mesh.update(calc_edges=True)
            raw = bpy.data.objects.new(name, mesh)
            collection.objects.link(raw)
            raw[marker_key] = True
            for key, value in zip(
                SLIP_CASTING_VASE_FUNNEL_PART_CENTER_KEYS,
                spec["reference"],
            ):
                raw[key] = value
            output = Object(raw)
            output.hide_during_ui_breathe = True
            _set_reference_hidden(output, True)
            raw.hide_select = True
            raw.show_in_front = False
            raw.display_type = "SOLID"
            outputs.append(output)
    except BaseException:
        for output in outputs:
            if output.object.name in bpy.data.objects:
                output.remove()
        raise
    return outputs


def _preparation_settings(master):
    return acquire_geometry_worker().geometry_policy('q17', p0=max(master.width, master.depth, master.height))


def _slip_casting_analysis_wrap_distance(master):
    return _preparation_settings(master)['analysis_distance']


def _crop_preparation_surface(surface, crop, index):
    """Keep the server's closed cylindrical crop, including radial and end caps.

    A height-only face selection cannot enforce this radial boundary or make
    the watertight object consumed by subsequent subtraction operations.
    """
    geometry = acquire_geometry_worker().geometry_policy('q42', p0={'p0': crop['center'], 'p1': crop['radius'], 'p2': crop['half_height'], 'p3': crop['segments']})
    mesh = bpy.data.meshes.new('_cast_item_10')
    mesh.from_pydata(geometry['vertices'], [], geometry['faces'])
    mesh.update()
    raw = bpy.data.objects.new('_cast_item_10', mesh)
    bpy.context.collection.objects.link(raw)
    cutter = Object(raw)
    output = None
    try:
        output = surface.duplicate(f'_item_{index:03d}')
        output.apply_modifier(intersect_mod, target=cutter)
        if not output.object.data.polygons:
            output.remove()
            return None
        return output
    except BaseException:
        if output is not None and output.object.name in bpy.data.objects:
            output.remove()
        raise
    finally:
        cutter.remove()


def _begin_local_preparation_surfaces(source, specs, *, voxel_size, funnel_span, envelope_settings, stop_before_crops=False, crop_margin=0.0, optimized=False):
    if not specs and not stop_before_crops:
        return [], []
    started = time.perf_counter()
    build_envelope = begin_optimized_mesh_envelope if optimized else begin_mesh_envelope
    surface = yield build_envelope(
        source, voxel_size=voxel_size, distance=funnel_span,
        name_adder='_cast_item_11', **envelope_settings,
    )
    logger.info('Local preparation shared envelope: algorithm=%s elapsed=%.3fs',
                'OPTIMIZED' if optimized else 'BASE', time.perf_counter() - started)
    if stop_before_crops:
        surface.object["moldboxer_internal_wrapper_debug"] = True
        return [], [surface]
    retained, outputs = [], []
    try:
        for index, spec in enumerate(specs, 1):
            crop_started = time.perf_counter()
            crop = {**spec['crop'],
                    'radius': spec['crop']['radius'] + crop_margin,
                    'half_height': spec['crop']['half_height'] + crop_margin}
            output = _crop_preparation_surface(surface, crop, index)
            if output is not None:
                retained.append(spec)
                outputs.append(output)
            logger.info('Local preparation crop: region=%d margin_mm=%.3f retained=%s elapsed=%.3fs',
                        index, crop_margin, output is not None, time.perf_counter() - crop_started)
    except BaseException:
        for output in outputs:
            output.remove()
        raise
    finally:
        surface.remove()
    return retained, outputs


def _internal_adapted_funnel(scene):
    return (getattr(scene, "slip_casting_funnel_type", "ADAPTED") == "ADAPTED"
            and getattr(scene, "slip_casting_adapted_variant", "EXTERNAL") == "INTERNAL")


def _slip_casting_master_target_flipped(scene):
    """Choose the finished assembly orientation for the funnel and foot style."""
    foot = bool(getattr(scene, "slip_casting_generate_base", True))
    external = (getattr(scene, "slip_casting_funnel_type", "ADAPTED") == "ADAPTED"
                and getattr(scene, "slip_casting_adapted_variant", "EXTERNAL") == "EXTERNAL")
    hollow_internal = (_internal_adapted_funnel(scene)
                       and getattr(scene, "slip_casting_internal_model_type", "CAVITY") != "FILLED")
    return (foot and external) or (not foot and not hollow_internal
                                   and slip_casting_funnels_on_top(scene))


def _slip_casting_master_build_flipped(scene):
    """Put the original top at the service's lower funnel scan."""
    foot = bool(getattr(scene, "slip_casting_generate_base", True))
    style = getattr(scene, "slip_casting_funnel_type", "ADAPTED")
    return ((foot and style == "ADAPTED")
            or (not foot and (style == "ROUNDED"
                or (_internal_adapted_funnel(scene)
                    and getattr(scene, "slip_casting_internal_model_type", "CAVITY") != "FILLED"))))


def _slip_casting_master_target_lift(scene):
    """Leave mold-thickness clearance below internal no-foot masters."""
    if (not bool(getattr(scene, "slip_casting_generate_base", True))
            and _internal_adapted_funnel(scene)):
        return max(0.0, float(getattr(scene, "box_gap", 0.0)))
    return 0.0


def _solid_flat_regions(scene):
    return (_internal_adapted_funnel(scene)
            and getattr(scene, "slip_casting_internal_model_type", "CAVITY") == "FILLED")


def _build_solid_flat_regions(master, context, *, voxel_size, funnel_extension):
    mesh = master.object.data
    mesh.calc_loop_triangles()
    vertices = [tuple(master.object.matrix_world @ v.co) for v in mesh.vertices]
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    worker = acquire_geometry_worker()
    plan = yield submit_worker_task(lambda: worker.geometry_policy(
        'q74', p0=vertices, p1=triangles, p2=funnel_extension,
        p3=float(getattr(context.scene, 'slip_casting_flat_region_inset', 3.0))))
    results = []
    try:
        for index, record in enumerate(plan['p0'], 1):
            data = bpy.data.meshes.new('_internal_flat_region')
            data.from_pydata(record[0], [], record[1])
            data.update()
            raw = bpy.data.objects.new(f'Internal Flat Funnel {index}', data)
            bpy.context.collection.objects.link(raw)
            part = Object(raw)
            results.append(part)
            part.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
            part.apply_modifier(build_voxel_modifier(voxel_size))
            bm = bmesh.new()
            try:
                bm.from_mesh(part.object.data)
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                if bm.calc_volume(signed=True) < 0.0:
                    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
                bm.to_mesh(part.object.data)
                part.object.data.update()
            finally:
                bm.free()
            # The opening is at the build-frame bottom; clean its final top.
            original_matrix = part.object.matrix_world.copy()
            try:
                part.object.matrix_world = mathutils.Matrix.Diagonal((-1., 1., -1., 1.)) @ original_matrix
                context.view_layer.update()
                cleaned = part.clean_top(2.0, strict_top=True)
            finally:
                part.object.matrix_world = original_matrix
                context.view_layer.update()
            if not cleaned:
                logger.warning('Skipping flat region %s: final Clean Top 2 mm failed', part.name)
                results.pop()
                part.remove()
                continue
            part.object.location.z += .25
            _set_funnel_intermediate_hidden(part, True)
        logger.info('Solid flat regions: selected_faces=%d regions=%d angle=%.1f '
                    'minimum_area=%.6f target_z=%.6f remesh_voxel=%.6f inset=%.6f collapsed=%d clean_top=2',
                    plan['p1'], len(results), plan['p2'],
                    plan['p3'], plan['p4'], voxel_size, plan['p5'], plan['p6'])
        return results
    except BaseException:
        for part in results:
            part.remove()
        raise


def _begin_cast_preparation(master, context, *, voxel_size, funnel_span, build_base):
    if _solid_flat_regions(context.scene) and not build_base:
        return [], [], []
    if bpy.data.objects.get("input_mesh") is not None:
        raise RuntimeError("Preparation input name is already in use")
    source = None
    created = []
    before = {raw.as_pointer() for raw in bpy.data.objects}
    try:
        settings = _preparation_settings(master)
        internal = _internal_adapted_funnel(context.scene)
        effective_span = 0.0 if internal else funnel_span
        logger.info("Adapted funnel preparation: variant=%s surface=%s span=%.6f",
                    "INTERNAL" if internal else "EXTERNAL",
                    "master" if internal else "analysis envelope", effective_span)
        source = yield begin_mesh_envelope(
            master, voxel_size=voxel_size, name_adder="_input_mesh",
            **settings['analysis_envelope'],
        )
        source.name = "input_mesh"
        _set_reference_hidden(source, True)
        response = yield request_server_async(
            f"{get_server_base_url()}/v1/g/", [source.name],
            params={"p0": max(master.width, master.depth, master.height),
                    "p1": voxel_size, "p2": effective_span,
                    "p3": build_base, "p4": 2, "p5": "AGGRESSIVE"},
        )
        plan = read_cast_plan(response)
        if internal and plan['version'] != 2:
            raise RuntimeError('Internal adapted funnels require preparation contract 2')
        if _solid_flat_regions(context.scene):
            # Solid funnels are built from worker-produced regions. This service
            # request is only needed for the foot references.
            plan['records'] = []
            surfaces = []
        elif plan['version'] == 2:
            plan['records'], created = yield from _begin_local_preparation_surfaces(
                master if internal else source, plan['records'],
                voxel_size=voxel_size, funnel_span=effective_span,
                envelope_settings=({**settings['shared_envelope'], 'final_wrap_distance': 0.0,
                                    'build_from_sphere': True, 'cut_top_bf_wrap': True,
                                    'cut_top_before_each_wrap': True}
                                   if internal else settings['shared_envelope']),
                optimized=internal,
                stop_before_crops=(internal and SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_REGION_CROPS),
                crop_margin=(SLIP_CASTING_INTERNAL_CROP_MARGIN_MM
                             * max(master.width, master.depth, master.height) / 100.0
                             if internal else 0.0),
            )
            if internal and SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_REGION_CROPS:
                return [], [], created
            surfaces = list(created)
        else:
            # Older services ignore the requested contract and return finished crops.
            created = [Object(raw) for raw in import_server_response(response, remesh_imported_objects=False)]
            by_name = {part.name: part for part in created}
            if set(by_name) != {spec['surface'] for spec in plan['records']}:
                raise RuntimeError('Preparation returned invalid surfaces')
            surfaces = [by_name[spec['surface']] for spec in plan['records']]
        groups = []
        for key, prefix, marker in (
            ("records", SLIP_CASTING_VASE_FUNNEL_PART_PREFIX, SLIP_CASTING_VASE_FUNNEL_PART_KEY),
            ("secondary", SLIP_CASTING_VASE_BASE_PART_PREFIX, SLIP_CASTING_VASE_BASE_PART_KEY),
        ):
            # Only bounds and reference points are needed by local finishing.
            references = _create_slip_casting_vase_funnel_reference_objects(
                master,
                plan[key],
                name_prefix=prefix, marker_key=marker,
            )
            created.extend(references)
            groups.append(references)
        wrappers = []
        for surface, reference in zip(surfaces, groups[0]):
            surface.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
            surface.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = reference.name
            _set_funnel_intermediate_hidden(surface, True)
            wrappers.append(surface)
        return groups[0], groups[1], wrappers
    except BaseException:
        # Import can fail after creating a partial scene object. Roll back all
        # objects belonging to this operation, including incomplete imports.
        remove_objects_safely([raw for raw in bpy.data.objects if raw.as_pointer() not in before])
        source = None
        raise
    finally:
        if source is not None and source.object.name in bpy.data.objects:
            source.remove()




def _create_slip_casting_bottom_extension(
    master: Object,
    *,
    mold_thickness: float,
) -> Object | None:
    """Extrude the master's downward bottom faces by the mold thickness."""

    if mold_thickness <= 0.0:
        raise ValueError("Slip Casting mold thickness must be greater than zero")
    extension = _extract_slip_casting_bottom_faces(
        master,
        object_name=SLIP_CASTING_BOTTOM_EXTENSION_NAME,
        marker_key=SLIP_CASTING_BOTTOM_EXTENSION_KEY,
    )
    if extension is None:
        return None

    mesh = extension.object.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        extruded = bmesh.ops.extrude_face_region(
            bm,
            geom=list(bm.faces),
        )["geom"]
        extruded_vertices = [
            element
            for element in extruded
            if isinstance(element, bmesh.types.BMVert)
        ]
        bmesh.ops.translate(
            bm,
            vec=mathutils.Vector((0.0, 0.0, -float(mold_thickness))),
            verts=extruded_vertices,
        )
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        mesh.update(calc_edges=True)
    except BaseException:
        if extension.object.name in bpy.data.objects:
            extension.remove()
        if mesh.users == 0 and mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        bm.free()

    mesh.update(calc_edges=True)
    logger.info(
        "Generated Slip Casting bottom extension: faces=%s threshold_z=%.6f "
        "normal_z<=%.3f extension=%.6f",
        len(extension.object.data.polygons),
        master.min_z + SLIP_CASTING_BOTTOM_FACE_BAND_MM,
        SLIP_CASTING_BOTTOM_NORMAL_Z_MAX,
        mold_thickness,
    )
    return extension


def _remove_bottom_extension_from_master(
    master: Object,
    master_mesh_without_extension,
) -> None:
    """Restore the master mesh and discard the temporary joined base."""
    if master_mesh_without_extension is None:
        return
    extended_master_mesh = master.object.data
    master.object.data = master_mesh_without_extension
    if SLIP_CASTING_BOTTOM_EXTENSION_KEY in master.object:
        del master.object[SLIP_CASTING_BOTTOM_EXTENSION_KEY]
    master.object.data.update()
    if extended_master_mesh.users == 0 and extended_master_mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(extended_master_mesh)
    logger.info(
        "Separated and removed the temporary Slip Casting bottom extension "
        "from the master"
    )


def _build_slip_casting_w_bottom_base(
    master: Object,
    *,
    voxel_size: float,
    w_name: str,
):
    """Mirror the top ``w`` pipeline in the bottom direction."""
    with suppress_ui_breathe():
        w = yield begin_mesh_envelope(
            master,
            voxel_size=voxel_size,
            distance=0,
            n_wraps=SLIP_CASTING_W_WRAP_COUNT,
            name_adder=f"_{w_name}",
            cut_bot=False,
            build_from_sphere=True,
            sphere_size_factor=SLIP_CASTING_W_BOTTOM_SPHERE_SIZE_FACTOR,
            cut_top_bf_wrap=False,
            cut_bottom_bf_wrap=True,
            pre_wrap_cut_offset=1.0,
            finish_top_after_intermediate_remesh=False,
            finish_bottom_after_intermediate_remesh=True,
            remesh_between_wraps=True,
            apply_final_remesh=True,
            intermediate_top_clean_voxel_factor=(
                SLIP_CASTING_W_TOP_CLEAN_VOXEL_FACTOR
            ),
            intermediate_top_target_offset=(
                SLIP_CASTING_W_TOP_TARGET_OFFSET_MM
            ),
        )
    return w


def _build_slip_casting_w_bottom_sphere_relative_cut(
    master: Object,
    *,
    voxel_size: float,
    w_name: str,
):
    """Cut the remeshed seed sphere at five percent of its own height."""
    with suppress_ui_breathe():
        w = yield begin_mesh_envelope(
            master,
            voxel_size=voxel_size,
            distance=0.0,
            n_wraps=0,
            name_adder=f"_{w_name}",
            cut_bot=False,
            build_from_sphere=True,
            sphere_size_factor=SLIP_CASTING_W_BOTTOM_SPHERE_SIZE_FACTOR,
            cut_top_bf_wrap=False,
            cut_bottom_bf_wrap=False,
            remesh_between_wraps=False,
            apply_final_remesh=False,
        )
        sphere_cut_z = (
            w.min_z + w.height * SLIP_CASTING_W_BOTTOM_SPHERE_CUT_HEIGHT_FACTOR
        )
        w.cut_plane(
            mathutils.Vector((0.0, 0.0, -1.0)),
            mathutils.Vector((0.0, 0.0, sphere_cut_z)),
        )
        if abs(w.min_z - sphere_cut_z) > 1e-3:
            raise RuntimeError(
                "Slip Casting w_bottom sphere-relative cut missed its "
                f"requested height: requested={sphere_cut_z:.6f} "
                f"actual={w.min_z:.6f}"
            )
    yield begin_apply_nearest_surface_shrinkwrap(
        w,
        master,
        offset=0.0,
    )
    return w


def _build_slip_casting_prepare_pair(
    master: Object,
    *,
    voxel_size: float,
    extr_wrap_distance: float,
    bottom: bool,
    clear_extr_undercuts: bool = True,
    reverse_z: bool = False,
    preserve_extr_before_clearance: bool = False,
):
    """Build one top- or bottom-oriented ``w``/``extr`` reference pair."""

    w_name, extr_name = (
        SLIP_CASTING_BOTTOM_PREPARE_OBJECT_NAMES
        if bottom
        else SLIP_CASTING_TOP_PREPARE_OBJECT_NAMES
    )
    if bottom:
        if (
            SLIP_CASTING_W_BOTTOM_APPROACH
            == SLIP_CASTING_W_BOTTOM_BASE_EXTENSION_APPROACH
        ):
            w = yield from _build_slip_casting_w_bottom_base(
                master,
                voxel_size=voxel_size,
                w_name=w_name,
            )
        elif (
            SLIP_CASTING_W_BOTTOM_APPROACH
            == SLIP_CASTING_W_BOTTOM_SPHERE_RELATIVE_CUT_APPROACH
        ):
            w = yield from _build_slip_casting_w_bottom_sphere_relative_cut(
                master,
                voxel_size=voxel_size,
                w_name=w_name,
            )
        else:
            raise ValueError(
                "Unsupported Slip Casting w_bottom approach: "
                f"{SLIP_CASTING_W_BOTTOM_APPROACH}"
            )
    else:
        with suppress_ui_breathe():
            w = yield begin_mesh_envelope(
                master,
                voxel_size=voxel_size,
                distance=0,
                n_wraps=SLIP_CASTING_W_WRAP_COUNT,
                name_adder=f"_{w_name}",
                cut_bot=False,
                build_from_sphere=True,
                cut_top_bf_wrap=not reverse_z,
                cut_bottom_bf_wrap=reverse_z,
                pre_wrap_cut_offset=1.0,
                finish_top_after_intermediate_remesh=not reverse_z,
                finish_bottom_after_intermediate_remesh=reverse_z,
                remesh_between_wraps=True,
                apply_final_remesh=True,
                intermediate_top_clean_voxel_factor=(
                    SLIP_CASTING_W_TOP_CLEAN_VOXEL_FACTOR
                ),
                intermediate_top_target_offset=(
                    SLIP_CASTING_W_TOP_TARGET_OFFSET_MM
                ),
            )
    w.name = w_name
    w.hide_during_ui_breathe = True
    w.object[SLIP_CASTING_PREPARE_REFERENCE_KEY] = w_name
    _set_reference_hidden(w, True)

    with suppress_ui_breathe():
        extr = yield begin_optimized_mesh_envelope(
            master,
            voxel_size=voxel_size,
            distance=extr_wrap_distance,
            n_wraps=2,
            name_adder=f"_{extr_name}",
            cut_bot=False,
            remesh_scaled=True,
        )
    raw_extr_target = None
    if preserve_extr_before_clearance:
        for existing in tuple(bpy.data.objects):
            if bool(
                existing.get(SLIP_CASTING_FUNNEL_SPAN_EXTR_TARGET_KEY, False)
            ):
                Object(existing).remove()
        raw_extr_target = extr.duplicate("_funnel_span_target")
        raw_extr_target.name = SLIP_CASTING_FUNNEL_SPAN_EXTR_TARGET_NAME
        raw_extr_target.object[SLIP_CASTING_FUNNEL_SPAN_EXTR_TARGET_KEY] = True
        raw_extr_target.hide_during_ui_breathe = True
        _set_reference_hidden(raw_extr_target, True)
        logger.info(
            "Preserved raw Slip Casting extr wrapper before undercut "
            "clearance: object=%s distance=%.6f",
            raw_extr_target.name,
            float(extr_wrap_distance),
        )
    extr.hide_during_ui_breathe = True
    if clear_extr_undercuts:
        effective_bottom = bottom or reverse_z
        yield begin_clear_undercuts(
            target_object=extr,
            bidirectional=False,
            voxel_size=voxel_size * 0.9,
            target_retry_voxel_size=voxel_size * 0.9,
            target_point=mathutils.Vector(
                (0.0, 0.0, w.max_z if effective_bottom else w.min_z)
            ),
            plane_direction=mathutils.Vector(
                (0.0, 0.0, -1.0 if effective_bottom else 1.0)
            ),
            clearance_build_overtravel_override=1.0,
            display_extraction_directions=False,
        )
    with suppress_ui_breathe():
        effective_bottom = bottom or reverse_z
        extr.cut_plane(
            mathutils.Vector(
                (0.0, 0.0, 1.0 if effective_bottom else -1.0)
            ),
            mathutils.Vector(
                (
                    0.0,
                    0.0,
                    w.max_z + 1.0 if effective_bottom else w.min_z - 1.0,
                )
            ),
        )
    extr.name = extr_name
    extr.object[SLIP_CASTING_PREPARE_REFERENCE_KEY] = extr_name
    _set_reference_hidden(extr, True)
    return w, extr, raw_extr_target


def begin_prepare_slip_casting_vase_with_cores(context):
    """Run the preserved Prepare Vase workflow that requests server cores."""
    master = _slip_casting_master(context.scene)
    if master is None:
        raise ValueError("No master model found")
    _ensure_prepare_names_available()

    voxel_size = get_box_voxel_size(context.scene.box_quality, master)
    extr_wrap_distance = float(context.scene.box_thickness)
    mold_thickness = float(context.scene.box_gap)

    def steps():
        imported_cores: list[Object] = []
        transient_bottom_cores: list[Object] = []
        core_wrappers: list[Object] = []
        vase_bases: list[Object] = []
        bottom_extension = None
        master_mesh_without_bottom_extension = None
        if (
            SLIP_CASTING_W_BOTTOM_APPROACH
            == SLIP_CASTING_W_BOTTOM_BASE_EXTENSION_APPROACH
        ):
            bottom_extension = _create_slip_casting_bottom_extension(
                master,
                mold_thickness=mold_thickness,
        )
        w, extr, _raw_extr_target = yield from _build_slip_casting_prepare_pair(
            master,
            voxel_size=voxel_size,
            extr_wrap_distance=extr_wrap_distance,
            bottom=False,
        )
        if bottom_extension is not None:
            master_mesh_without_bottom_extension = master.object.data.copy()
            joined_bottom_extension = bottom_extension.duplicate("_joined_target")
            _set_reference_hidden(bottom_extension, True)
            master.join(joined_bottom_extension)
            master.object[SLIP_CASTING_BOTTOM_EXTENSION_KEY] = True
            logger.info(
                "Joined the unremeshed full-thickness Slip Casting bottom-"
                "extension duplicate into the master before building w_bottom; "
                "retained the original for final separation"
            )
        try:
            w_bottom, extr_bottom, _raw_extr_bottom_target = yield from (
                _build_slip_casting_prepare_pair(
                    master,
                    voxel_size=voxel_size,
                    extr_wrap_distance=(
                        extr_wrap_distance
                        * SLIP_CASTING_BOTTOM_EXTR_WRAP_DISTANCE_FACTOR
                    ),
                    bottom=True,
                )
            )
        except BaseException:
            _remove_bottom_extension_from_master(
                master,
                master_mesh_without_bottom_extension,
            )
            raise

        if SLIP_CASTING_PREPARE_DEBUG_STOP_AFTER_EXTR_BOTTOM:
            if (
                master_mesh_without_bottom_extension is not None
                and master_mesh_without_bottom_extension.users == 0
            ):
                bpy.data.meshes.remove(master_mesh_without_bottom_extension)
                master_mesh_without_bottom_extension = None
            debug_references = (w_bottom, extr_bottom)
            for reference in debug_references:
                reference.hide_during_ui_breathe = False
                reference.object.display_type = "SOLID"
            for scene_object in list(bpy.context.view_layer.objects):
                scene_object.select_set(False)
                is_debug_visible = scene_object in {
                    master.object,
                    *(reference.object for reference in debug_references),
                }
                scene_object.hide_render = not is_debug_visible
                scene_object.hide_viewport = not is_debug_visible
                scene_object.hide_set(not is_debug_visible)
            for reference in debug_references:
                reference.object.select_set(True)
            bpy.context.view_layer.objects.active = extr_bottom.object
            bpy.context.view_layer.update()
            logger.info(
                "Prepare Vase debug stop reached after extr_bottom generation; "
                "the extended master, w_bottom, and extr_bottom remain visible"
            )
            return list(debug_references)

        try:
            for bottom, object_names, expected_prefix in (
                (
                    False,
                    SLIP_CASTING_TOP_PREPARE_OBJECT_NAMES,
                    SLIP_CASTING_RAW_CORE_PREFIX,
                ),
                (
                    True,
                    SLIP_CASTING_BOTTOM_PREPARE_OBJECT_NAMES,
                    SLIP_CASTING_BOTTOM_RAW_CORE_PREFIX,
                ),
            ):
                orientation = "BOTTOM" if bottom else "TOP"
                logger.info(
                    "Requesting cleaned Slip Casting %s raw cores from server: "
                    "objects=%s voxel_size=%.6f",
                    orientation.lower(),
                    ", ".join(object_names),
                    voxel_size,
                )
                request = request_server_async(
                    f"{get_server_base_url()}/slip-casting-inner-cores/",
                    list(object_names),
                    params={
                        "box_voxel_size": voxel_size,
                        "orientation": orientation,
                        "w_name": object_names[0],
                        "extr_name": object_names[1],
                    },
                )
                if bottom and SLIP_CASTING_PREPARE_DEBUG_KEEP_BOTTOM_EXTR:
                    _remove_prepare_references((object_names[0],))
                    extr_bottom.hide_during_ui_breathe = False
                    _set_reference_hidden(extr_bottom, False)
                else:
                    _remove_prepare_references(object_names)
                response = yield request
                pair_cores = _import_slip_casting_raw_cores(
                    response,
                    voxel_size=voxel_size,
                    expected_prefix=expected_prefix,
                    bottom=bottom,
                )
                if bottom:
                    transient_bottom_cores.extend(pair_cores)
                    if bottom_extension is None:
                        raise RuntimeError(
                            "Prepare Vase could not build vase_base because no "
                            "bottom base was generated"
                        )
                    vase_base = yield from _build_slip_casting_vase_base(
                        bottom_extension,
                        pair_cores,
                        voxel_size=voxel_size,
                    )
                    vase_bases.append(vase_base)
                else:
                    imported_cores.extend(pair_cores)
                for core in pair_cores:
                    core_limit_z = None if bottom else float(core.max_z)
                    with suppress_ui_breathe():
                        wrapper = yield begin_optimized_mesh_envelope(
                            core,
                            voxel_size=voxel_size,
                            distance=(
                                extr_wrap_distance
                                + SLIP_CASTING_CORE_WRAPPER_EXTRA_WRAP_MM
                            ),
                            n_wraps=2,
                            name_adder="_wrapper",
                            cut_bot=False,
                            build_from_sphere=False,
                            remesh_scaled=True,
                        )
                    core_wrappers.append(wrapper)
                    _finish_slip_casting_core_wrapper(
                        core,
                        wrapper,
                        core_limit_z=core_limit_z,
                        bottom=bottom,
                    )
                    if bottom:
                        transient_core_name = core.name
                        core.remove()
                        transient_bottom_cores.remove(core)
                        logger.info(
                            "Deleted transient Slip Casting bottom core %s after "
                            "generating its unmodified wrapper",
                            transient_core_name,
                        )
        except BaseException:
            _remove_prepare_references()
            for wrapper in core_wrappers:
                if wrapper.object.name in bpy.data.objects:
                    wrapper.remove()
            for vase_base in vase_bases:
                if vase_base.object.name in bpy.data.objects:
                    vase_base.remove()
            for core in imported_cores:
                if core.object.name in bpy.data.objects:
                    core.remove()
            for core in transient_bottom_cores:
                if core.object.name in bpy.data.objects:
                    core.remove()
            if (
                bottom_extension is not None
                and bottom_extension.object.name in bpy.data.objects
            ):
                bottom_extension.remove()
            _remove_bottom_extension_from_master(
                master,
                master_mesh_without_bottom_extension,
            )
            raise

        _remove_bottom_extension_from_master(
            master,
            master_mesh_without_bottom_extension,
        )
        if SLIP_CASTING_PREPARE_DEBUG_STOP_BEFORE_BOTTOM_EXTENSION_REMOVAL:
            master.hide_during_ui_breathe = False
            master.object.hide_set(False)
            master.object.hide_viewport = False
            master.object.hide_render = False
            if bottom_extension is not None:
                bottom_extension.hide_during_ui_breathe = False
                bottom_extension.object.hide_set(False)
                bottom_extension.object.hide_viewport = False
                bottom_extension.object.hide_render = False
                bottom_extension.select()
            bpy.context.view_layer.update()
            logger.info(
                "Prepare Vase debug stop reached after separating the bottom "
                "extension and before deleting it"
            )
            return imported_cores
        if (
            bottom_extension is not None
            and bottom_extension.object.name in bpy.data.objects
        ):
            bottom_extension.remove()
            bottom_extension = None
        if core_wrappers:
            core_wrappers[0].select()
            for wrapper in core_wrappers[1:]:
                wrapper.object.select_set(True)
            for vase_base in vase_bases:
                vase_base.object.select_set(True)
        elif vase_bases:
            vase_bases[0].select()
            for vase_base in vase_bases[1:]:
                vase_base.object.select_set(True)
        else:
            master.select()
        return imported_cores

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _slip_casting_clearance_region_center(core: Object) -> mathutils.Vector:
    stored_center = tuple(
        core.object.get(key)
        for key in SLIP_CASTING_VASE_FUNNEL_PART_CENTER_KEYS
    )
    if all(value is not None for value in stored_center):
        return mathutils.Vector(tuple(float(value) for value in stored_center))
    return core.center_coords.copy()


def _preparation_object_bounds(value):
    return {
        "p0": [float(value.min_x), float(value.min_y), float(value.min_z)],
        "p1": [float(value.max_x), float(value.max_y), float(value.max_z)],
    }


def _slip_casting_per_reference_span_target_bounds(
    target: Object,
    references: list[Object],
    *,
    voxel_size: float,
    reference_z_offset: float = 0.0,
    xy_wrap_margin: float = 0.0,
    minimum_half_height: float = 0.0,
):
    return acquire_geometry_worker().geometry_policy('q08', p0=_preparation_object_bounds(target), p1=[_preparation_object_bounds(value) for value in references], p2=voxel_size, p3=reference_z_offset, p4=xy_wrap_margin, p5=minimum_half_height)["bounds"]


def _slip_casting_clearance_bounds_for_reference_wrappers(
    wrappers: list[Object],
    references: list[Object],
    *,
    voxel_size: float,
):
    return acquire_geometry_worker().geometry_policy('q63', p0=[_preparation_object_bounds(value) for value in wrappers], p1=len(references), p2=voxel_size)["bounds"]


def _merged_slip_casting_clearance_region_bounds(region_bounds):
    return acquire_geometry_worker().geometry_policy('q25', p0=region_bounds)["bounds"]


def _expanded_slip_casting_clearance_region_bounds(
    region_bounds,
    *,
    z_margin: float,
):
    return acquire_geometry_worker().geometry_policy('q91', p0=region_bounds, p1=z_margin)["bounds"]


def _create_slip_casting_clearance_region_cutter(
    region_bounds,
    *,
    name: str,
) -> Object:
    geometry = acquire_geometry_worker().geometry_policy('q36', p0=region_bounds)
    vertices, faces = geometry["vertices"], geometry["faces"]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    raw = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(raw)
    cutter = Object(raw)
    cutter.hide_during_ui_breathe = True
    _set_reference_hidden(cutter, True)
    return cutter


def _ensure_preparation_source_manifold(source: Object, *, role: str, voxel_size: float) -> None:
    """Repair a shared source before duplication, committing only valid geometry."""
    started = time.perf_counter()
    if source.is_manifold():
        logger.info("Preparation source validation: role=%s object=%s repaired=False elapsed=%.3fs",
                    role, source.name, time.perf_counter() - started)
        return
    original = source.object.data
    repaired = original.copy()
    stats = None
    remeshed = False
    try:
        try:
            stats = clean_mesh_for_manifold_boolean(repaired)
        except Exception:
            logger.warning("Preparation source cleanup failed: role=%s object=%s; remeshing",
                           role, source.name, exc_info=True)
            remove_unused_meshes([repaired])
            repaired = original.copy()
        source.object.data = repaired
        if stats is None or not source.is_manifold():
            logger.info("Remeshing preparation source: role=%s object=%s voxel_size=%.6f",
                        role, source.name, voxel_size)
            source.apply_modifier(build_voxel_modifier(voxel_size))
            remeshed = True
            if not source.object.data.polygons or not source.is_manifold():
                raise RuntimeError(f"Preparation {role} is empty or remains non-manifold after source remesh")
    except BaseException:
        failed = source.object.data
        source.object.data = original
        remove_unused_meshes([repaired, failed])
        raise
    remove_unused_meshes([original, repaired])
    logger.info(
        "Preparation source validation: role=%s object=%s repaired=True "
        "remeshed=%s duplicate_faces=%d elapsed=%.3fs",
        role, source.name, remeshed,
        stats.duplicate_faces_removed if stats is not None else 0,
        time.perf_counter() - started,
    )


def _intersect_with_slip_casting_clearance_regions(target: Object, region_bounds, *, label: str, allow_empty: bool=False) -> bool:
    """Keep a closed region crop; face filtering would discard its cap surfaces."""
    if not region_bounds:
        raise RuntimeError('Optimized Slip Casting clearance requires an region')
    merged = _merged_slip_casting_clearance_region_bounds(region_bounds)
    # Use local object bounds here, not the worker's encoded p0/p1 payload.
    minimum = (float(target.min_x), float(target.min_y), float(target.min_z))
    maximum = (float(target.max_x), float(target.max_y), float(target.max_z))
    if target.object.data.polygons and any(
        all(lo[axis] < minimum[axis] - 1e-6 and hi[axis] > maximum[axis] + 1e-6
            for axis in range(3)) for lo, hi in merged
    ):
        logger.info('Skipped contained Slip Casting region intersection: label=%s object=%s', label, target.name)
        return True
    if not target.object.data.polygons or all(
        any(maximum[axis] < lo[axis] - 1e-6 or minimum[axis] > hi[axis] + 1e-6
            for axis in range(3)) for lo, hi in merged
    ):
        if not allow_empty:
            raise RuntimeError(f'Optimized Slip Casting {label} region intersection is empty')
        logger.info('Skipped disjoint Slip Casting region intersection: label=%s object=%s', label, target.name)
        return False
    cutter = _create_slip_casting_clearance_region_cutter(region_bounds, name=f'_{target.name}_item_12')
    started = time.perf_counter()
    try:
        with suppress_ui_breathe():
            _set_reference_hidden(target, False)
            _set_reference_hidden(cutter, False)
            try:
                target.apply_modifier(intersect_mod, target=cutter)
            finally:
                _set_reference_hidden(target, True)
    finally:
        if cutter.object.name in bpy.data.objects:
            cutter.remove()
    target.object.data.calc_loop_triangles()
    triangle_count = len(target.object.data.loop_triangles)
    if not triangle_count:
        if allow_empty:
            logger.warning('Skipped empty optimized Slip Casting %s region intersection: regions=%d elapsed=%.3fs', label, len(_merged_slip_casting_clearance_region_bounds(region_bounds)), time.perf_counter() - started)
            return False
        raise RuntimeError(f'Optimized Slip Casting {label} region intersection is empty')
    logger.info('Intersected Slip Casting %s with optimized clearance regions: regions=%d triangles=%d elapsed=%.3fs', label, len(_merged_slip_casting_clearance_region_bounds(region_bounds)), triangle_count, time.perf_counter() - started)
    return True


def _build_slip_casting_clearance_proxy(master: Object, context):
    """Build the simplified master shared by funnel and vase-base clearance."""

    master.object.data.calc_loop_triangles()
    source_triangle_count = len(master.object.data.loop_triangles)
    collection = (
        context.collection
        if getattr(context, "collection", None) is not None
        else bpy.context.collection
    )
    master_voxel_size = get_master_voxel_size(
        context.scene.master_quality, master,
    ) * 1.2
    cache_key = clearance_proxy_key(
        master.object.data, master.object.matrix_world,
        context.scene.master_quality, master_voxel_size,
    )
    cached = get_clearance_proxy(cache_key)
    if cached is not None:
        vertices, triangles = cached
        mesh = create_mesh_from_triangles(
            f"{SLIP_CASTING_FUNNEL_CLEARANCE_PROXY_NAME}_mesh", vertices, triangles,
        )
        raw = bpy.data.objects.new(SLIP_CASTING_FUNNEL_CLEARANCE_PROXY_NAME, mesh)
        raw.matrix_world = master.object.matrix_world.copy()
        collection.objects.link(raw)
        clearance_source = Object(raw)
        clearance_source.hide_during_ui_breathe = True
        _set_reference_hidden(clearance_source, True)
        logger.info(
            "Reused cached Slip Casting clearance proxy: source=%s "
            "proxy_triangles=%d voxel_size=%.6f",
            master.name, len(triangles), master_voxel_size,
        )
        return clearance_source
    # Only the remeshed proxy is used for clearance; simplify it afterward.
    clearance_source = master.duplicate("_cast_item_03")
    proxy_face_count = len(clearance_source.object.data.polygons)
    try:
        clearance_source.apply_modifier(build_voxel_modifier(master_voxel_size))
        clearance_source.object.data.calc_loop_triangles()
        remeshed_triangle_count = len(clearance_source.object.data.loop_triangles)
        target_reduction = yield begin_direct_undercuts_target_reduction(
            remeshed_triangle_count
        )
        # Still run fast decimation for small remeshes, using its default
        # reduction when the adaptive policy would otherwise skip it.
        if target_reduction is None or target_reduction <= 0.0:
            target_reduction = 0.8
        simplified_raw = yield begin_create_fast_simplified_object(
            clearance_source.object,
            collection,
            name=SLIP_CASTING_FUNNEL_CLEARANCE_PROXY_NAME,
            target_reduction=target_reduction,
        )
    except BaseException:
        clearance_source.remove()
        raise
    clearance_source.remove()
    clearance_source = Object(simplified_raw)
    logger.info(
        "Remeshed Slip Casting clearance proxy: initial_faces=%d "
        "master_voxel_size=%.6f remeshed_triangles=%d",
        proxy_face_count, master_voxel_size, remeshed_triangle_count,
    )
    clearance_source.name = SLIP_CASTING_FUNNEL_CLEARANCE_PROXY_NAME
    clearance_source.hide_during_ui_breathe = True
    _set_reference_hidden(clearance_source, True)
    # This proxy supplies clearance geometry, which is remeshed downstream.
    # Simplification need not preserve manifold topology on this reference.
    clearance_source.object.data.calc_loop_triangles()
    logger.info(
        "Prepared shared Slip Casting clearance proxy: source=%s "
        "source_triangles=%d proxy_triangles=%d target_reduction=%s",
        master.name,
        source_triangle_count,
        len(clearance_source.object.data.loop_triangles),
        (
            "none"
            if target_reduction is None
            else f"{float(target_reduction):.6f}"
        ),
    )
    vertices, triangles = extract_mesh_triangles(clearance_source.object.data)
    store_clearance_proxy(cache_key, vertices, triangles)
    return clearance_source


def _build_slip_casting_core_master_clearances(
    master: Object,
    cores: list[Object],
    context,
    *,
    voxel_size: float,
    funnel_wrappers: list[Object],
    clearance_region_bounds,
    clearance_source: Object | None = None,
    include_inward: bool = True,
    include_outward: bool = True,
    include_source_geometry: bool = True,
    stop_after_join_before_remesh: bool = False,
):
    """Build localized clearance cutters, separately when requested."""

    if not (len(cores) == len(clearance_region_bounds) == len(funnel_wrappers)):
        raise RuntimeError(
            "Per-region clearance requires one region and wrapper per region"
        )
    if not cores:
        return []
    core_targets = [(tuple(core.center_coords),) for core in cores]

    owns_clearance_source = clearance_source is None
    if clearance_source is None:
        clearance_source = yield from _build_slip_casting_clearance_proxy(
            master,
            context,
        )

    exterior_margin = float(voxel_size)
    clearance_jobs = tuple(
        (
            f"{core_index:03d}",
            core_targets[core_index - 1],
            (clearance_region_bounds[core_index - 1],),
            core.name,
            funnel_wrappers[core_index - 1],
        )
        for core_index, core in enumerate(cores, start=1)
    )
    cutters: list[Object | None] = []
    try:
        for (
            job_suffix,
            target_centers,
            job_region_bounds,
            source_names,
            funnel_wrapper,
        ) in clearance_jobs:
            cutter = clearance_source.duplicate(
                f"_item_{job_suffix}"
            )
            cutter.name = (
                f"{SLIP_CASTING_CORE_MASTER_CLEARANCE_PREFIX}_{job_suffix}"
            )
            cutter.object[SLIP_CASTING_CORE_MASTER_CLEARANCE_KEY] = True
            cutter.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = source_names
            cutter.hide_during_ui_breathe = True
            _set_reference_hidden(cutter, True)
            intersection_has_geometry = (
                # This source volume is joined with the face-selected sweeps
                # below. Retain its closed crop so voxel remeshing fills it.
                _intersect_with_slip_casting_clearance_regions(
                    cutter,
                    job_region_bounds,
                    label=f"base clearance cutter {job_suffix}",
                    allow_empty=True,
                )
            )
            if not intersection_has_geometry:
                cutter.remove()
                cutters.append(None)
                logger.info(
                    "Continuing Slip Casting funnel generation without "
                    "clearance subtraction: region=%s wrapper=%s",
                    job_suffix,
                    funnel_wrapper.name,
                )
                continue
            cutters.append(cutter)
            if not include_source_geometry:
                # Optional sweep-only mode discards the cropped source solid.
                cutter.object.data.clear_geometry()
            wrapper_bounds = (
                (
                    float(funnel_wrapper.min_x),
                    float(funnel_wrapper.min_y),
                    float(funnel_wrapper.min_z),
                ),
                (
                    float(funnel_wrapper.max_x),
                    float(funnel_wrapper.max_y),
                    float(funnel_wrapper.max_z),
                ),
            )
            clearance_specs = []
            if include_inward:
                clearance_specs.append(
                    (
                        "inward",
                        SLIP_CASTING_CORE_MASTER_CLEARANCE_PREFIX,
                        SLIP_CASTING_CORE_MASTER_CLEARANCE_KEY,
                        {},
                    )
                )
            if include_outward:
                clearance_specs.append(
                    (
                        "exterior",
                        SLIP_CASTING_CORE_MASTER_EXTERIOR_PREFIX,
                        SLIP_CASTING_CORE_MASTER_EXTERIOR_KEY,
                        {
                            "away_from_target": True,
                            "extrusion_bounds": wrapper_bounds,
                            "extrusion_margin": exterior_margin,
                        },
                    )
                )
            if not clearance_specs:
                raise ValueError(
                    "At least one Slip Casting clearance direction is required"
                )
            sweep_solid_count = 0
            selection_bounds = (
                job_region_bounds[0]
            )
            for (
                clearance_label,
                name_prefix,
                marker_key,
                options,
            ) in clearance_specs:
                clearance = clearance_source.duplicate(
                    f"_item_{job_suffix}"
                )
                clearance.name = f"{name_prefix}_{job_suffix}"
                clearance.object[marker_key] = True
                clearance.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = (
                    source_names
                )
                clearance.hide_during_ui_breathe = True
                _set_reference_hidden(clearance, True)
                target_arguments = (
                    {'target_point': target_centers[0]}
                )
                result = yield begin_clear_mesh_faces_to_point_with_worker(
                    clearance.object,
                    voxel_size=voxel_size,
                    include_source=False,
                    selection_bounds=selection_bounds,
                    **target_arguments,
                    **options,
                )
                selected_face_count = int(result.selected_face_count)
                component_count = int(result.component_count)
                clearance_name = clearance.name
                if selected_face_count:
                    with suppress_ui_breathe():
                        _set_reference_hidden(cutter, False)
                        _set_reference_hidden(clearance, False)
                        cutter.join(clearance)
                        _set_reference_hidden(cutter, True)
                    sweep_solid_count += 1
                elif clearance.object.name in bpy.data.objects:
                    clearance.remove()
                force_viewport_redraw(context)
                logger.info(
                    "Generated Slip Casting %s sweep-only clearance: "
                    "object=%s generation=%s targets=%d "
                    "direction_z=0 distance=%s selected_faces=%d "
                    "components=%d",
                    clearance_label,
                    clearance_name,
                    "per_reference",
                    len(target_centers),
                    (
                        f"wrapper_bounds+{exterior_margin:.6f}"
                        if clearance_label == "exterior"
                        else "axis"
                    ),
                    selected_face_count,
                    component_count,
                )

            if not include_source_geometry and not sweep_solid_count:
                cutter.remove()
                cutters[-1] = None
                continue
            if stop_after_join_before_remesh:
                logger.info(
                    "Retained joined Slip Casting vase-base clearance for "
                    "debugging before remesh: object=%s sweep_solids=%s "
                    "join=True remeshes=0",
                    cutter.name,
                    sweep_solid_count,
                )
                continue

            remesh_voxel_size = float(voxel_size) * 1.2
            with suppress_ui_breathe():
                _set_reference_hidden(cutter, False)
                cutter.apply_modifier(build_voxel_modifier(remesh_voxel_size))
                _set_reference_hidden(cutter, True)
            logger.info(
                "Built Slip Casting funnel clearance cutter: object=%s "
                "approach=optimized generation=%s targets=%d sweep_solids=%d "
                "box_voxel_size=%.6f voxel_size=%.6f remeshes=1",
                cutter.name,
                "per_reference",
                len(target_centers),
                sweep_solid_count,
                float(voxel_size),
                remesh_voxel_size,
            )
    except BaseException:
        for cutter in cutters:
            if cutter is not None and cutter.object.name in bpy.data.objects:
                cutter.remove()
        raise
    finally:
        if (
            owns_clearance_source
            and clearance_source.object.name in bpy.data.objects
        ):
            clearance_source.remove()
    return cutters


def _build_slip_casting_funnel_span_wrapper(
    target: Object,
    context,
    *,
    voxel_size: float,
    funnel_span: float,
    target_wrap_distance: float,
    distance_override: float | None = None,
    remesh_between_wraps: bool = False,
    wrap_count: int = SLIP_CASTING_FUNNEL_SPAN_WRAPPER_WRAP_COUNT,
    build_from_sphere: bool = True,
):
    """Wrap the raw extr target at the compensated master-relative span."""

    compensated_distance = float(funnel_span) - float(target_wrap_distance)
    effective_distance = (
        compensated_distance
        if distance_override is None
        else float(distance_override)
    )

    wrapper = yield begin_mesh_envelope(
        target,
        voxel_size=voxel_size,
        distance=effective_distance,
        n_wraps=wrap_count,
        name_adder="_cast_item_04",
        cut_bot=False,
        build_from_sphere=build_from_sphere,
        cut_top_bf_wrap=False,
        cut_bottom_bf_wrap=False,
        remesh_between_wraps=remesh_between_wraps,
    )
    wrapper.name = SLIP_CASTING_FUNNEL_SPAN_WRAPPER_NAME
    wrapper.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
    _set_funnel_intermediate_hidden(wrapper, True)
    wrapper.object.display_type = "SOLID"
    force_viewport_redraw(context)
    logger.info(
        "Generated Slip Casting funnel-span wrapper: object=%s "
        "target=%s requested_span=%.6f target_wrap_distance=%.6f "
        "compensated_distance=%.6f effective_distance=%.6f "
        "distance_override=%s wraps=%d remesh_between_wraps=%s "
        "intermediate_remeshes=%d "
        "build_from_sphere=%s cuts=False",
        wrapper.name,
        target.name,
        float(funnel_span),
        float(target_wrap_distance),
        compensated_distance,
        effective_distance,
        (
            "none"
            if distance_override is None
            else f"{float(distance_override):.6f}"
        ),
        wrap_count,
        remesh_between_wraps,
        (
            wrap_count - 1
            if remesh_between_wraps
            else 0
        ),
        build_from_sphere,
    )
    return wrapper


def _build_slip_casting_funnel_span_wrappers_per_reference(target: Object, references: list[Object], context, *, voxel_size: float, funnel_span: float, target_wrap_distance: float, name_prefix: str=SLIP_CASTING_FUNNEL_SPAN_WRAPPER_NAME, distance_override: float | None=None, remesh_between_wraps: bool=False, reference_z_offset: float=0.0, xy_wrap_margin: float=0.0, minimum_half_height: float=0.0):
    """Build an independent envelope from a local target around each region."""
    target_bounds = _slip_casting_per_reference_span_target_bounds(target, references, voxel_size=voxel_size, reference_z_offset=reference_z_offset, xy_wrap_margin=xy_wrap_margin, minimum_half_height=minimum_half_height)
    wrappers: list[Object] = []
    local_targets: list[Object | None] = []
    successful_references: list[Object] = []
    local_target: Object | None = None
    try:
        for (reference_index, (reference, reference_bounds)) in enumerate(zip(references, target_bounds), start=1):
            local_target = target.duplicate(f'_item_{reference_index:03d}')
            local_target.name = f'_{name_prefix}_item_{reference_index:03d}'
            _set_funnel_intermediate_hidden(local_target, True)
            # The envelope queries this solid's cut caps as well as its side
            # faces. Selecting only original faces changes the target surface.
            has_geometry = _intersect_with_slip_casting_clearance_regions(local_target, (reference_bounds,), label=f'local span target region {reference_index:03d}', allow_empty=True)
            if not has_geometry:
                local_target.remove()
                local_target = None
                local_targets.append(None)
                continue
            local_target.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = reference.name
            local_targets.append(local_target)
            local_target = None
        for (reference_index, (reference, local_target)) in enumerate(zip(references, local_targets), start=1):
            if local_target is None:
                continue
            wrapper = (yield from _build_slip_casting_funnel_span_wrapper(local_target, context, voxel_size=voxel_size, funnel_span=funnel_span, target_wrap_distance=target_wrap_distance, distance_override=distance_override, build_from_sphere=True, remesh_between_wraps=remesh_between_wraps, wrap_count=SLIP_CASTING_FUNNEL_SPAN_WRAPPER_WRAP_COUNT))
            wrapper.name = f'{name_prefix}_{reference_index:03d}'
            wrapper.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
            wrapper.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = reference.name
            _set_funnel_intermediate_hidden(wrapper, True)
            wrappers.append(wrapper)
            minimum_z = target_bounds[reference_index - 1][0][2]
            maximum_z = target_bounds[reference_index - 1][1][2]
            xy_margin = max(float(voxel_size), 0.001)
            crop_bounds = ((wrapper.min_x - xy_margin, wrapper.min_y - xy_margin, minimum_z), (wrapper.max_x + xy_margin, wrapper.max_y + xy_margin, maximum_z))
            has_geometry = _intersect_with_slip_casting_clearance_regions(wrapper, (crop_bounds,), label=f'final span Z band region {reference_index:03d}', allow_empty=True)
            local_target.remove()
            local_targets[reference_index - 1] = None
            local_target = None
            if not has_geometry:
                wrapper.remove()
                wrappers.pop()
                continue
            successful_references.append(reference)
            logger.info('Generated localized Slip Casting funnel-span wrapper: region=%d/%d wrapper=%s source=%s z_band=(%.6f, %.6f) target=master', reference_index, len(references), wrapper.name, reference.name, minimum_z, maximum_z)
    except BaseException:
        if local_target is not None and local_target.object.name in bpy.data.objects:
            local_target.remove()
        for target in local_targets:
            if target is not None and target.object.name in bpy.data.objects:
                target.remove()
        for wrapper in wrappers:
            if wrapper.object.name in bpy.data.objects:
                wrapper.remove()
        raise
    for reference in references:
        if reference not in successful_references:
            logger.warning('Skipped empty preparation part: source=%s', reference.name)
            reference.remove()
    references[:] = successful_references
    logger.info('Built localized Slip Casting funnel-span wrappers: wrappers=%d regions=%d approach=per_reference', len(wrappers), len(references))
    return wrappers


def _subtract_core_clearances_from_funnel_span_wrappers(
    wrappers: list[Object],
    cleared_masters: list[Object | None],
    context,
) -> None:
    """Subtract each clearance cutter only from its corresponding wrapper."""

    if not cleared_masters:
        return
    if len(wrappers) != len(cleared_masters):
        raise RuntimeError(
            "Slip Casting funnel clearance requires one cutter per wrapper"
        )
    for reference_index, (wrapper, cutter) in enumerate(
        zip(wrappers, cleared_masters),
        start=1,
    ):
        if cutter is None:
            logger.info(
                "Skipped Slip Casting clearance subtraction for wrapper "
                "without intersecting clearance geometry: region=%d/%d "
                "wrapper=%s",
                reference_index,
                len(wrappers),
                wrapper.name,
            )
            continue
        cutter_name = cutter.name
        _set_reference_hidden(cutter, False)
        _set_funnel_intermediate_hidden(wrapper, False)
        try:
            with suppress_ui_breathe():
                wrapper.apply_boolean_modifier_with_geometry_fallback(
                    diff_mod,
                    cutter,
                )
        except BaseException:
            _set_reference_hidden(cutter, True)
            raise
        finally:
            if wrapper.object.name in bpy.data.objects:
                _set_funnel_intermediate_hidden(wrapper, True)
        cutter.remove()
        logger.info(
            "Subtracted Slip Casting clearance from corresponding "
            "funnel-span wrapper: region=%d/%d wrapper=%s cutter=%s",
            reference_index,
            len(wrappers),
            wrapper.name,
            cutter_name,
        )
    cleared_masters.clear()
    force_viewport_redraw(context)


def _subtract_final_internal_funnel_clearances(wrappers, cutters, context):
    """Apply internal outward clearance once, before top finishing."""
    by_source = {
        str(cutter.object.get(SLIP_CASTING_CORE_MASTER_SOURCE_KEY, "")): cutter
        for cutter in cutters
    }
    for wrapper in wrappers:
        source = str(wrapper.object.get(SLIP_CASTING_CORE_MASTER_SOURCE_KEY, ""))
        cutter = by_source.get(source)
        if cutter is None:
            continue  # This region had no sweep geometry.
        operand = cutter.duplicate("_final_cut")
        try:
            _subtract_core_clearances_from_funnel_span_wrappers(
                [wrapper], [operand], context)
        except BaseException:
            try:
                if operand.object.name in bpy.data.objects:
                    operand.remove()
            except ReferenceError:
                pass
            raise
        logger.info("Applied final internal funnel outward clearance: wrapper=%s source=%s",
                    wrapper.name, source)


def _show_slip_casting_vase_base_wrappers_before_clearance_subtraction(
    wrappers: list[Object],
    clearances: list[Object | None],
    context,
) -> None:
    """Expose untouched vase-base wrappers for debug inspection."""

    for wrapper in wrappers:
        wrapper.hide_during_ui_breathe = False
        _set_reference_hidden(wrapper, False)
        wrapper.object.hide_select = False
        wrapper.object.display_type = "SOLID"
        assign_slip_casting_funnel_span_material(wrapper.object)
    for clearance in clearances:
        if clearance is not None:
            _set_reference_hidden(clearance, True)
    if wrappers:
        wrappers[0].select()
        for wrapper in wrappers[1:]:
            wrapper.object.select_set(True)
    force_viewport_redraw(context)
    logger.info(
        "Build Funnels debug stop before vase-base undercut clearance "
        "subtraction: wrappers=%d clearances=%d wrapper_distance=%.3fmm "
        "build_from_sphere=True clearance_target=base_reference_center",
        len(wrappers),
        sum(clearance is not None for clearance in clearances),
        SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_DISTANCE_MM,
    )


def _show_slip_casting_vase_base_clearances_after_generation(
    clearances: list[Object | None],
    context,
) -> list[Object]:
    """Expose generated vase-base clearance cutters for debug inspection."""

    visible_clearances = [
        clearance for clearance in clearances if clearance is not None
    ]
    for clearance in visible_clearances:
        clearance.hide_during_ui_breathe = False
        _set_reference_hidden(clearance, False)
        clearance.object.hide_select = False
        clearance.object.display_type = "SOLID"
        clearance.object.show_in_front = False
        clearance.object.select_set(False)
    force_viewport_redraw(context)
    logger.info(
        "Build Funnels debug stop after vase-base clearance generation: "
        "requested=%d generated=%d empty=%d normal_display=True selected=False; "
        "join=True remeshes=1; no clearances subtracted",
        len(clearances),
        len(visible_clearances),
        len(clearances) - len(visible_clearances),
    )
    return visible_clearances


def _show_slip_casting_vase_base_wrappers_after_clearance_subtraction(
    wrappers: list[Object],
    context,
) -> None:
    """Expose vase-base wrappers after their clearance subtraction."""

    for wrapper in wrappers:
        wrapper.hide_during_ui_breathe = False
        _set_reference_hidden(wrapper, False)
        wrapper.object.hide_select = False
        wrapper.object.display_type = "SOLID"
        wrapper.object.show_in_front = False
        wrapper.object.select_set(False)
    force_viewport_redraw(context)
    logger.info(
        "Build Funnels debug stop after vase-base clearance subtraction: "
        "wrappers=%d normal_display=True selected=False",
        len(wrappers),
    )


def _show_slip_casting_vase_base_parts_after_reference_matching(
    parts: list[Object],
    context,
) -> None:
    """Expose vase-base wrapper parts retained for their matched regions."""

    for part in parts:
        part.hide_during_ui_breathe = False
        _set_reference_hidden(part, False)
        part.object.hide_select = False
        part.object.display_type = "SOLID"
        part.object.show_in_front = False
        part.object.select_set(False)
    force_viewport_redraw(context)
    logger.info(
        "Build Funnels debug stop after vase-base region matching: "
        "parts=%d normal_display=True selected=False",
        len(parts),
    )


def _keep_funnel_span_wrapper_parts_for_cores(
    wrapper: Object,
    cores: list[Object],
    context,
    *,
    use_max_z: bool = False,
) -> list[Object]:
    """Keep the wrapper region closest to each core's selected Z limit."""

    assign_slip_casting_funnel_span_material(wrapper.object)
    if not cores:
        logger.info(
            "Kept Slip Casting funnel-span wrapper without isolated "
            "matches because no cores were detected"
        )
        return []

    with suppress_ui_breathe():
        _set_funnel_intermediate_hidden(wrapper, False)
        isolated_parts = wrapper.split_isolated_meshes()
        for part in isolated_parts:
            _set_funnel_intermediate_hidden(part, True)
    force_viewport_redraw(context)
    if len(isolated_parts) < len(cores):
        for part in isolated_parts:
            if part.object != wrapper.object:
                part.remove()
        raise RuntimeError(
            "Funnel-span wrapper produced fewer isolated parts than detected "
            f"cores ({len(isolated_parts)} parts for {len(cores)} cores)"
        )

    core_limit_centers = [
        (
            float(core.center_coords.x),
            float(core.center_coords.y),
            float(core.max_z if use_max_z else core.min_z),
        )
        for core in cores
    ]
    try:
        part_indices, distances = (
            match_mesh_parts_to_world_points_with_worker(
                isolated_parts,
                core_limit_centers,
            )
        )
    except BaseException:
        for part in isolated_parts:
            if part.object != wrapper.object:
                part.remove()
        raise

    retained: list[Object] = []
    retained_object_pointers: set[int] = set()
    for core_index, (core, part_index, distance) in enumerate(
        zip(cores, part_indices, distances),
        start=1,
    ):
        part = isolated_parts[int(part_index)]
        part.name = f"{SLIP_CASTING_FUNNEL_SPAN_CORE_PREFIX}_{core_index:03d}"
        part.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
        part.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = core.name
        _set_funnel_intermediate_hidden(part, True)
        part.object.display_type = "SOLID"
        assign_slip_casting_funnel_span_material(part.object)
        retained.append(part)
        retained_object_pointers.add(int(part.object.as_pointer()))
        limit_label = "maximum-Z" if use_max_z else "minimum-Z"
        logger.info(
            "Matched Slip Casting funnel-span part to core %s center: "
            "part=%s core=%s limit_center=(%.6f, %.6f, %.6f) "
            "nearest_vertex_distance=%.6f",
            limit_label,
            part.name,
            core.name,
            core_limit_centers[core_index - 1][0],
            core_limit_centers[core_index - 1][1],
            core_limit_centers[core_index - 1][2],
            float(distance),
        )

    unmatched_count = 0
    for part in isolated_parts:
        if int(part.object.as_pointer()) in retained_object_pointers:
            continue
        part.remove()
        unmatched_count += 1
    logger.info(
        "Filtered Slip Casting funnel-span regions after %s core matching: "
        "regions=%d matched=%d removed_unmatched=%d",
        "maximum-Z" if use_max_z else "minimum-Z",
        len(isolated_parts),
        len(retained),
        unmatched_count,
    )
    force_viewport_redraw(context)
    return retained


def _clean_mostly_flat_funnel_top(wrapper: Object, voxel_size: float) -> bool:
    """Restore a near-horizontal cap without flattening a shaped funnel top."""
    height = 2.0 * float(voxel_size)
    if height <= 0.0 or height >= float(wrapper.height):
        return False
    mesh = wrapper.object.data
    matrix = wrapper.object.matrix_world
    linear = matrix.to_3x3()
    determinant = abs(linear.determinant())
    if determinant <= 1e-12:
        return False
    normal_matrix = linear.inverted().transposed()
    top_z = float(wrapper.max_z)
    flat_normal_z = math.cos(math.radians(8.0))
    upward_area = 0.0
    flat_top_area = 0.0
    for face in mesh.polygons:
        normal = normal_matrix @ face.normal
        normal_length = normal.length
        if normal_length <= 1e-12 or normal.z <= 0.0:
            continue
        # Compare area as seen from above, so almost-vertical walls do not
        # outweigh the cap. This also accounts for nonuniform object scale.
        area = float(face.area) * determinant * normal.z
        upward_area += area
        if normal.z / normal_length >= flat_normal_z and all(
            (matrix @ mesh.vertices[index].co).z >= top_z - height
            for index in face.vertices
        ):
            flat_top_area += area
    if upward_area <= 0.0 or flat_top_area / upward_area < 0.8:
        return False
    if not wrapper.clean_top(height, strict_top=True):
        logger.warning(
            "Skipped mostly flat funnel top cleanup: object=%s flat_area_fraction=%.3f "
            "height=%.6f original_geometry_preserved=True",
            wrapper.name, flat_top_area / upward_area, height,
        )
        return False
    logger.info(
        "Cleaned mostly flat Slip Casting funnel top: object=%s "
        "flat_area_fraction=%.3f height=%.6f",
        wrapper.name, flat_top_area / upward_area, height,
    )
    return True


def _internal_debug_before_clearance(scene):
    return (_internal_adapted_funnel(scene)
            and not _solid_flat_regions(scene)
            and SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_CLEARANCE_SUBTRACTION)


def _internal_debug_after_clearance(scene):
    return (_internal_adapted_funnel(scene)
            and not _solid_flat_regions(scene)
            and SLIP_CASTING_INTERNAL_DEBUG_STOP_AFTER_CLEARANCE)


def _clear_internal_funnel_vertical_extraction(parts, master, context, *, voxel_size, debug_outputs=None, subtract=True, clearance_source=None):
    """Sweep the simplified master for hollow internal-adapted funnels."""
    if not parts:
        return
    source = clearance_source if clearance_source is not None else master
    cutter = source.duplicate("_internal_vertical_clearance")
    cutter_name = cutter.name
    try:
        # The internal funnel exits downwards in this inverted build frame.
        # Sweep the master upwards to remove material obstructing that exit.
        target_z = max(float(master.max_z), *(float(p.max_z) for p in parts)) + 1.0
        center = master.center_coords
        with suppress_ui_breathe():
            _set_funnel_intermediate_hidden(cutter, False)
            yield begin_clear_undercuts(
                target_object=cutter,
                bidirectional=False,
                voxel_size=voxel_size * 0.9,
                target_retry_voxel_size=voxel_size * 0.9,
                target_point=mathutils.Vector((center.x, center.y, target_z)),
                plane_direction=mathutils.Vector((0.0, 0.0, -1.0)),
                clearance_build_overtravel_override=1.0,
                display_extraction_directions=False,
            )
        _set_funnel_intermediate_hidden(cutter, True)
        if not subtract:
            if debug_outputs is None:
                raise ValueError("Unsubtracted vertical clearance requires debug_outputs")
            debug_outputs.append(cutter)
            cutter_name = None
            return
        for part in parts:
            operand = cutter.duplicate("_cut")
            operand_name = operand.name
            try:
                _subtract_core_clearances_from_funnel_span_wrappers(
                    [part], [operand], context)
            finally:
                if bpy.data.objects.get(operand_name) is not None:
                    operand.remove()
        logger.info("Applied internal funnel vertical extraction: parts=%d build_direction=-Z "
                    "source=%s simplified=%s wrapper=False",
                    len(parts), source.name, clearance_source is not None)
        if debug_outputs is not None:
            debug_outputs.append(cutter)
            cutter_name = None
    finally:
        if cutter_name is not None and bpy.data.objects.get(cutter_name) is not None:
            cutter.remove()


def _remove_internal_funnel_volume_artifacts(parts, volume_fraction=0.01):
    """Remove tiny closed positive-volume fragments; preserve cavity shells."""
    for part in parts:
        bm = bmesh.new()
        try:
            bm.from_mesh(part.object.data)
            pending = set(bm.verts)
            components = []
            membership = {}
            while pending:
                first = pending.pop()
                vertices = [first]
                stack = [first]
                while stack:
                    vertex = stack.pop()
                    for edge in vertex.link_edges:
                        other = edge.other_vert(vertex)
                        if other in pending:
                            pending.remove(other)
                            vertices.append(other)
                            stack.append(other)
                index = len(components)
                for vertex in vertices:
                    membership[vertex] = index
                components.append(vertices)
            if len(components) < 2:
                continue
            origins = [vertices[0].co.copy() for vertices in components]
            volumes = [0.0] * len(components)
            for triangle in bm.calc_loop_triangles():
                index = membership[triangle[0].vert]
                origin = origins[index]
                a, b, c = (loop.vert.co - origin for loop in triangle)
                volumes[index] += a.dot(b.cross(c)) / 6.0
            world_scale = abs(part.object.matrix_world.to_3x3().determinant())
            volumes = [volume * world_scale for volume in volumes]
            eligible = [
                i for i, vertices in enumerate(components)
                if volumes[i] > 0.0 and all(
                    vertex.link_faces and all(edge.is_manifold for edge in vertex.link_edges)
                    for vertex in vertices)
            ]
            if not eligible:
                continue
            largest = max(eligible, key=lambda i: volumes[i])
            threshold = volumes[largest] * volume_fraction
            removed = [i for i in eligible if i != largest and volumes[i] < threshold]
            if removed:
                bmesh.ops.delete(bm, geom=[vertex for i in removed for vertex in components[i]],
                                 context="VERTS")
                bm.to_mesh(part.object.data)
                part.object.data.update()
            logger.info(
                "Internal funnel artifact cleanup: object=%s fragments=%d removed=%d "
                "threshold_volume=%.6f removed_volume=%.6f fraction=%.6f",
                part.name, len(components), len(removed), threshold,
                sum(volumes[i] for i in removed), volume_fraction,
            )
        finally:
            bm.free()


def _expand_internal_funnel_top(part, fraction=0.10):
    """Flare only the planar cap, with an even outline offset when safe."""
    if fraction == 0.0:
        return
    mesh = part.object.data
    matrix = part.object.matrix_world
    points = [matrix @ v.co for v in mesh.vertices]
    top = max(p.z for p in points)
    tolerance = max(1e-5, (top - min(p.z for p in points)) * 1e-6)
    caps = [p for p in mesh.polygons
            if all(abs(points[i].z - top) <= tolerance for i in p.vertices)]
    if not caps:
        raise RuntimeError(f"No planar top cap to expand on {part.name}")
    indices = {i for p in caps for i in p.vertices}
    edges = {}
    area = 0.0
    for face in caps:
        ids = list(face.vertices)
        for a, b in zip(ids, ids[1:] + ids[:1]):
            key = tuple(sorted((a, b)))
            edges.setdefault(key, []).append((a, b))
            area += (points[a].x * points[b].y - points[b].x * points[a].y) / 2
    boundary = [uses[0] for uses in edges.values() if len(uses) == 1]
    perimeter = sum((points[b] - points[a]).length for a, b in boundary)
    if perimeter <= tolerance or abs(area) <= tolerance * tolerance:
        raise RuntimeError(f"Degenerate top cap on {part.name}")
    # Expand by a fraction of the equivalent radius, using a constant
    # outline offset for irregular shapes.
    distance = fraction * 2.0 * abs(area) / perimeter
    center = sum((points[i] for i in indices), mathutils.Vector()) / len(indices)
    scaled = {i: center + (points[i] - center) * (1.0 + fraction) for i in indices}
    normals = {}
    for a, b in boundary:
        edge = points[b] - points[a]
        normal = mathutils.Vector((edge.y, -edge.x, 0.0)).normalized()
        if area < 0:
            normal.negate()
        normals.setdefault(a, []).append(normal)
        normals.setdefault(b, []).append(normal)
    expanded = {i: p.copy() for i, p in scaled.items()}
    safe = True
    for i, adjacent in normals.items():
        if len(adjacent) != 2:
            safe = False
            break
        direction = adjacent[0] + adjacent[1]
        divisor = direction.dot(adjacent[0])
        if divisor <= 1e-8:
            safe = False
            break
        offset = direction * (distance / divisor)
        # Avoid long spikes at very acute corners.
        if offset.length > 4.0 * distance:
            safe = False
            break
        expanded[i] = points[i] + offset
    mesh.calc_loop_triangles()
    cap_faces = {p.index for p in caps}
    if safe:
        for triangle in mesh.loop_triangles:
            if triangle.polygon_index not in cap_faces:
                continue
            a, b, c = triangle.vertices
            before = (points[b] - points[a]).cross(points[c] - points[a]).z
            after = (expanded[b] - expanded[a]).cross(expanded[c] - expanded[a]).z
            if before * after <= 0:
                safe = False
                break
    # Check nonadjacent boundary segments, pruning disjoint X/Y ranges.
    segments = sorted((min(expanded[a].x, expanded[b].x),
                       max(expanded[a].x, expanded[b].x), a, b) for a, b in boundary)
    if safe:
        for n, (_, xmax, a, b) in enumerate(segments):
            for xmin, _, c, d in segments[n + 1:]:
                if xmin > xmax:
                    break
                if {a, b} & {c, d}:
                    continue
                if max(expanded[a].y, expanded[b].y) < min(expanded[c].y, expanded[d].y) or max(expanded[c].y, expanded[d].y) < min(expanded[a].y, expanded[b].y):
                    continue
                if mathutils.geometry.intersect_line_line_2d(
                        expanded[a].xy, expanded[b].xy, expanded[c].xy, expanded[d].xy) is not None:
                    safe = False
                    break
            if not safe:
                break
    result = expanded if safe else scaled
    inverse = matrix.inverted()
    for i, point in result.items():
        point.z = points[i].z
        mesh.vertices[i].co = inverse @ point
    mesh.update()
    logger.info("Expanded internal funnel top: object=%s amount=%.3f%% method=%s offset=%.6f",
                part.name, fraction * 100.0, "outline offset" if safe else "scale fallback", distance)


class _InternalFunnelFinishError(RuntimeError):
    """An individual funnel cannot be completed; other parts may continue."""


def _finish_internal_funnel_surfaces(parts, master, context, *, funnel_extension, voxel_size):
    """Extend and finish the funnel, then sphere-wrap at zero and clean its top."""
    if funnel_extension <= 0:
        raise ValueError("Slip Casting funnel extension must be greater than zero")
    # The build-frame bottom becomes the top after preparation is restored.
    turn_up = mathutils.Matrix.Diagonal((-1., 1., -1., 1.))
    target_top = -float(master.min_z) + float(funnel_extension)
    finished_parts = []
    for part in parts:
        failure = None
        original = part.object.matrix_world.copy()
        try:
            part.object.matrix_world = turn_up @ original
            context.view_layer.update()
            # Clearance subtraction hides this construction object. Keep it
            # editable through cap extrusion, including Boolean redraw points.
            with suppress_ui_breathe():
                _set_funnel_intermediate_hidden(part, False)
                center = part.center_coords
                extension = yield begin_clear_undercuts(
                    target_object=part,
                    bidirectional=False,
                    voxel_size=voxel_size * 0.9,
                    target_retry_voxel_size=voxel_size * 0.9,
                    target_point=mathutils.Vector((center.x, center.y, target_top)),
                    plane_direction=mathutils.Vector((0.0, 0.0, -1.0)),
                    clearance_build_overtravel_override=0.0,
                    display_extraction_directions=False,
                    join_target=False,
                    remesh_target_after_join=False,
                    smooth_target_after_remesh=False,
                )
                if extension is None:
                    raise _InternalFunnelFinishError(f"Could not extend internal funnel {part.name}")
                try:
                    _set_funnel_intermediate_hidden(extension, False)
                    part.apply_boolean_modifier_with_geometry_fallback(union_mod, extension)
                finally:
                    extension.remove()
                context.view_layer.update()
                actual_top = max((part.object.matrix_world @ v.co).z
                                 for v in part.object.data.vertices)
                if abs(actual_top - target_top) > max(0.001, voxel_size * 0.01):
                    raise _InternalFunnelFinishError(f"Internal funnel extension missed target height: {part.name}")
                _expand_internal_funnel_top(
                    part, fraction=float(getattr(context.scene, "slip_casting_internal_top_expansion", 10.0)) / 100.0)
                final_voxel = float(voxel_size)
                part.apply_modifier(build_voxel_modifier(final_voxel))
                part.smooth_geometry(factor=0.5, repeat=5)
                # Remeshing can leave inward winding. Clean Top selects an
                # upward cap, so normalize the closed solid before cutting.
                bm = bmesh.new()
                try:
                    bm.from_mesh(part.object.data)
                    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                    if bm.calc_volume(signed=True) < 0.0:
                        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
                    bm.to_mesh(part.object.data)
                    part.object.data.update()
                finally:
                    bm.free()
                context.view_layer.update()
                smoothed_top = max((part.object.matrix_world @ v.co).z
                                   for v in part.object.data.vertices)
                if not part.clean_top(3.0, extra_extrussion=target_top - smoothed_top,
                                      strict_top=True):
                    raise _InternalFunnelFinishError(f"Could not apply final Clean Top 3 mm to {part.name}")
                context.view_layer.update()
                wrapper = yield begin_mesh_envelope(
                    part, voxel_size=voxel_size, distance=0.0, n_wraps=3,
                    name_adder="_internal_final_wrapper", build_from_sphere=True,
                    cut_bot=False, cut_top_bf_wrap=False, cut_bottom_bf_wrap=False,
                )
                try:
                    _set_funnel_intermediate_hidden(wrapper, False)
                    wrapper.smooth_geometry(factor=0.5, repeat=5)
                    context.view_layer.update()
                    if not wrapper.clean_top(3.0, strict_top=True):
                        raise _InternalFunnelFinishError(f"Could not clean final wrapper top by 3 mm: {part.name}")
                    if not wrapper.object.data.polygons:
                        raise _InternalFunnelFinishError(f"Final wrapper top cleanup emptied {part.name}")
                    # Preserve the funnel identity and metadata when replacing
                    # its geometry; the temporary wrapper may have its own frame.
                    mesh = wrapper.object.data.copy()
                    mesh.transform(part.object.matrix_world.inverted() @ wrapper.object.matrix_world)
                    old_mesh = part.object.data
                    part.object.data = mesh
                    if old_mesh.users == 0:
                        bpy.data.meshes.remove(old_mesh)
                finally:
                    wrapper.remove()
                context.view_layer.update()
        except _InternalFunnelFinishError as error:
            failure = str(error)
        finally:
            part.object.matrix_world = original
            _set_funnel_intermediate_hidden(part, True)
            context.view_layer.update()
        if failure is not None:
            logger.warning("Skipping internal funnel %s: %s; continuing preparation",
                           part.name, failure)
            part.remove()
            continue
        # Internal funnels point down in the build frame. Moving toward the
        # master here becomes a downward shift after the final assembly flip.
        shifted = part.object.matrix_world.copy()
        shifted.translation.z += 0.25
        part.object.matrix_world = shifted
        context.view_layer.update()
        finished_parts.append(part)
        logger.info("Foundation-like extension of internal funnel wrapper two: "
                    "object=%s extension=%.6f build_end_z=%.6f "
                    "remesh_voxel=%.6f smooth_factor=0.5 smooth_repeats=5 clean_top=3.000 "
                    "final_wrapper_distance=0 wraps=3 build_from_sphere=True "
                    "final_wrapper_smooth_factor=0.5 final_wrapper_smooth_repeats=5 final_clean_top=3 "
                    "master_overlap_shift=0.25",
                    part.name, funnel_extension, -target_top, final_voxel)
    return finished_parts


def _build_cleared_funnel_span_part_wrappers(
    parts: list[Object],
    master: Object,
    context,
    *,
    voxel_size: float,
    funnel_extension: float,
    reverse_z: bool = False,
    debug_stop_after_wrapper_generation: bool = False,
):
    """Wrap retained funnel parts and clear them before their final remesh."""

    if funnel_extension <= 0.0:
        raise ValueError("Slip Casting funnel extension must be greater than zero")
    # Leave 0.5 mm of the original wrapper offset beyond the cleaned end.
    cleanup_distance = max(0.0, (
        _slip_casting_analysis_wrap_distance(master)
        if reverse_z
        else (0.0 if _internal_adapted_funnel(context.scene) else float(context.scene.slip_casting_funnel_span))
    ) - 0.5)
    target_z = float(master.min_z) - float(funnel_extension)
    if reverse_z:
        target_z = float(master.max_z) + float(funnel_extension)
    clearance_voxel_size = (
        float(voxel_size) * SLIP_CASTING_FUNNEL_FINAL_CLEAR_VOXEL_FACTOR
    )
    final_remesh_voxel_size = (
        float(voxel_size) * SLIP_CASTING_FUNNEL_FINAL_REMESH_VOXEL_FACTOR
    )
    wrapper_distance = 0.0 if _internal_adapted_funnel(context.scene) else SLIP_CASTING_FUNNEL_PART_WRAPPER_DISTANCE_MM
    master_center = master.center_coords
    wrappers: list[Object] = []
    wrapper_parts: list[tuple[int, Object, Object]] = []
    try:
        for part_index, part in enumerate(parts, start=1):
            wrapper = yield begin_mesh_envelope(
                part,
                voxel_size=voxel_size,
                distance=wrapper_distance,
                n_wraps=SLIP_CASTING_FUNNEL_PART_WRAPPER_WRAP_COUNT,
                name_adder=(
                    f"_{part.name}{SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX}"
                ),
                cut_bot=False,
                build_from_sphere=True,
                cut_top_bf_wrap=False,
                cut_bottom_bf_wrap=False,
                apply_final_remesh=False,
                remesh_between_wraps=True,
            )
            wrapper.name = (
                f"{part.name}{SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX}"
            )
            wrapper.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
            wrapper.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = str(
                part.object.get(SLIP_CASTING_CORE_MASTER_SOURCE_KEY, "")
            )
            _set_funnel_intermediate_hidden(wrapper, True)
            wrapper.object.display_type = "SOLID"
            assign_slip_casting_funnel_span_material(wrapper.object)
            wrappers.append(wrapper)
            wrapper_parts.append((part_index, part, wrapper))
            force_viewport_redraw(context)

        if debug_stop_after_wrapper_generation:
            for part in parts:
                _set_reference_hidden(part, True)
            for wrapper in wrappers:
                wrapper.hide_during_ui_breathe = False
                _set_reference_hidden(wrapper, False)
                wrapper.object.display_type = "SOLID"
                wrapper.object.hide_select = False
                assign_funnels_material(wrapper.object)
                wrapper.object.select_set(False)
            if wrappers:
                wrappers[0].select()
                for wrapper in wrappers[1:]:
                    wrapper.object.select_set(True)
            force_viewport_redraw(context)
            logger.info(
                "Build Funnels debug stop reached after final per-part "
                "wrapper generation and before undercut clearance: "
                "wrappers=%d distance=%.6f wraps=%d "
                "intermediate_remeshes=%d",
                len(wrappers),
                wrapper_distance,
                SLIP_CASTING_FUNNEL_PART_WRAPPER_WRAP_COUNT,
                SLIP_CASTING_FUNNEL_PART_WRAPPER_WRAP_COUNT - 1,
            )
            return wrappers

        for part_index, part, wrapper in wrapper_parts:
            _set_funnel_intermediate_hidden(wrapper, False)
            yield begin_clear_undercuts(
                target_object=wrapper,
                bidirectional=False,
                voxel_size=clearance_voxel_size,
                target_retry_voxel_size=clearance_voxel_size,
                target_point=mathutils.Vector(
                    (
                        float(master_center.x),
                        float(master_center.y),
                        target_z,
                    )
                ),
                plane_direction=mathutils.Vector(
                    (0.0, 0.0, -1.0 if reverse_z else 1.0)
                ),
                clearance_build_overtravel_override=0.0,
                display_extraction_directions=False,
                before_target_join=lambda target: (
                    assign_slip_casting_funnel_span_material(target.object)
                ),
                remesh_target_after_join=False,
                smooth_target_after_remesh=False,
            )
            with suppress_ui_breathe():
                wrapper.apply_modifier(
                    build_voxel_modifier(final_remesh_voxel_size)
                )
                wrapper.smooth_geometry(factor=0.5, repeat=5)
                if cleanup_distance > 0.0:
                    if reverse_z:
                        wrapper.clean_top(cleanup_distance)
                    else:
                        wrapper.clean_bot(cleanup_distance)
                if not reverse_z:
                    _clean_mostly_flat_funnel_top(wrapper, voxel_size)
                _set_funnel_intermediate_hidden(wrapper, True)
            force_viewport_redraw(context)
            assign_slip_casting_funnel_span_material(wrapper.object)
            force_viewport_redraw(context)
            logger.info(
                "Finished Slip Casting funnel-span part wrapper: "
                "wrapper=%s source=%s distance=%.6f wraps=%d "
                "target_z=%.6f funnel_extension=%.6f "
                "clearance_voxel_size=%.6f final_voxel_size=%.6f "
                "smooth_factor=0.5 smooth_repeats=5 reverse_z=%s "
                "limit_clean=%.6f "
                "index=%d/%d",
                wrapper.name,
                part.name,
                wrapper_distance,
                SLIP_CASTING_FUNNEL_PART_WRAPPER_WRAP_COUNT,
                target_z,
                float(funnel_extension),
                clearance_voxel_size,
                final_remesh_voxel_size,
                reverse_z,
                cleanup_distance,
                part_index,
                len(parts),
            )
    except BaseException:
        for wrapper in wrappers:
            if wrapper.object.name in bpy.data.objects:
                wrapper.remove()
        raise

    for part in parts:
        if part.object.name in bpy.data.objects:
            part.remove()
    return wrappers


def _keep_highest_vase_base_piece(wrapper: Object) -> Object:
    """Keep one highest connected piece from an already region-matched base."""
    name = wrapper.name
    source = wrapper.object.get(SLIP_CASTING_CORE_MASTER_SOURCE_KEY, "")
    pieces = wrapper.split_isolated_meshes()
    retained = max(
        pieces,
        key=lambda piece: (float(piece.max_z), float(piece.center_coords.z), piece.name),
    )
    for piece in pieces:
        if piece.object != retained.object:
            piece.remove()
    retained.name = name
    retained.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = source
    logger.info(
        "Kept highest final vase-base piece: region=%s pieces=%d retained=%s max_z=%.6f",
        source, len(pieces), retained.name, float(retained.max_z),
    )
    return retained


def _build_final_slip_casting_vase_base_parts(
    parts: list[Object],
    master: Object,
    context,
    *,
    voxel_size: float,
    mold_thickness: float,
):
    """Clear, wrap, and trim matched vase-base parts against the master."""

    if mold_thickness <= 0.0:
        raise ValueError("Slip Casting mold thickness must be greater than zero")
    cleanup_distance = 2.0 * float(voxel_size)
    target_z = float(master.max_z) + float(mold_thickness)
    clearance_voxel_size = (
        float(voxel_size) * SLIP_CASTING_FUNNEL_FINAL_CLEAR_VOXEL_FACTOR
    )
    def skip_empty_wrapper(wrapper: Object, stage: str) -> bool:
        if Object._has_mesh_geometry(wrapper):
            return False
        logger.warning(
            "Skipped empty Slip Casting vase-base part: wrapper=%s stage=%s",
            wrapper.name, stage,
        )
        wrapper.remove()
        return True

    wrappers: list[Object] = []
    try:
        for part_index, part in enumerate(parts, start=1):
            part_center = part.center_coords.copy()
            _set_funnel_intermediate_hidden(part, False)
            yield begin_clear_undercuts(
                target_object=part,
                bidirectional=False,
                voxel_size=clearance_voxel_size,
                target_retry_voxel_size=clearance_voxel_size,
                target_point=mathutils.Vector(
                    (float(part_center.x), float(part_center.y), target_z)
                ),
                plane_direction=mathutils.Vector((0.0, 0.0, -1.0)),
                clearance_build_overtravel_override=0.0,
                display_extraction_directions=False,
                before_target_join=lambda target: (
                    assign_slip_casting_funnel_span_material(target.object)
                ),
                remesh_target_after_join=True,
                smooth_target_after_remesh=True,
            )
            _set_funnel_intermediate_hidden(part, True)
            force_viewport_redraw(context)
            if not Object._has_mesh_geometry(part):
                logger.warning(
                    "Skipped empty Slip Casting vase-base part: source=%s "
                    "stage=undercut_clearance", part.name,
                )
                continue

            wrapper = yield begin_mesh_envelope(
                part,
                voxel_size=voxel_size,
                distance=SLIP_CASTING_VASE_BASE_PART_WRAPPER_DISTANCE_MM,
                n_wraps=SLIP_CASTING_VASE_BASE_PART_WRAPPER_WRAP_COUNT,
                name_adder=(
                    f"_{part.name}{SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX}"
                ),
                cut_bot=False,
                build_from_sphere=True,
                cut_top_bf_wrap=False,
                cut_bottom_bf_wrap=False,
                apply_final_remesh=False,
                remesh_between_wraps=True,
            )
            wrapper.name = (
                f"{part.name}{SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX}"
            )
            wrapper.object[SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY] = True
            wrapper.object[SLIP_CASTING_CORE_MASTER_SOURCE_KEY] = str(
                part.object.get(SLIP_CASTING_CORE_MASTER_SOURCE_KEY, "")
            )
            _set_funnel_intermediate_hidden(wrapper, False)
            wrapper.object.display_type = "SOLID"
            assign_slip_casting_funnel_span_material(wrapper.object)
            with suppress_ui_breathe():
                wrapper.apply_modifier(build_voxel_modifier(clearance_voxel_size))
                if skip_empty_wrapper(wrapper, "final_remesh"):
                    continue
                wrapper.smooth_geometry(factor=0.5, repeat=5)
                if cleanup_distance > 0.0:
                    wrapper.clean_top(cleanup_distance, strict_top=True)
                if skip_empty_wrapper(wrapper, "top_cleanup"):
                    continue
                wrapper.apply_modifier(diff_mod, target=master)
                if skip_empty_wrapper(wrapper, "master_subtraction"):
                    continue
                wrapper = _keep_highest_vase_base_piece(wrapper)
            _set_funnel_intermediate_hidden(wrapper, True)
            wrappers.append(wrapper)
            force_viewport_redraw(context)
            logger.info(
                "Finished Slip Casting vase-base part geometry: wrapper=%s "
                "source=%s clearance_target=(%.6f, %.6f, %.6f) "
                "clearance_voxel_size=%.6f clearance_remesh=True "
                "clearance_smooth=True wrapper_distance=%.6f "
                "wrapper_voxel_size=%.6f wraps=%d intermediate_remeshes=%d "
                "final_remesh=True final_remesh_voxel_size=%.6f "
                "final_smooth_factor=0.5 final_smooth_repeats=5 "
                "top_clean_height=%.6f top_clean_before_master_subtraction=True "
                "master_subtracted=True index=%d/%d",
                wrapper.name,
                part.name,
                float(part_center.x),
                float(part_center.y),
                target_z,
                clearance_voxel_size,
                SLIP_CASTING_VASE_BASE_PART_WRAPPER_DISTANCE_MM,
                float(voxel_size),
                SLIP_CASTING_VASE_BASE_PART_WRAPPER_WRAP_COUNT,
                SLIP_CASTING_VASE_BASE_PART_WRAPPER_WRAP_COUNT - 1,
                clearance_voxel_size,
                cleanup_distance,
                part_index,
                len(parts),
            )
    except BaseException:
        for wrapper in wrappers:
            if wrapper.object.name in bpy.data.objects:
                wrapper.remove()
        raise

    for part in parts:
        if part.object.name in bpy.data.objects:
            part.remove()
    return wrappers


def _remove_detected_cores_and_clearance_masters(
    cores: list[Object],
    cleared_masters: list[Object | None],
    context,
    *,
    keep_references_for_debug: bool = False,
) -> None:
    """Finish region-detection intermediates after funnel-part matching."""

    core_count = len(cores)
    clearance_count = sum(
        cleared_master is not None for cleared_master in cleared_masters
    )
    for core in cores:
        if core.object.name not in bpy.data.objects:
            continue
        if keep_references_for_debug:
            core.hide_during_ui_breathe = False
            _set_reference_hidden(core, False)
            core.object.hide_render = True
            core.object.hide_select = False
            core.object.show_in_front = True
            core.object.display_type = "SOLID"
            assign_funnels_material(core.object)
        else:
            core.remove()
        force_viewport_redraw(context)
    for cleared_master in cleared_masters:
        if (
            cleared_master is not None
            and cleared_master.object.name in bpy.data.objects
        ):
            cleared_master.remove()
            force_viewport_redraw(context)
    logger.info(
        "%s Slip Casting Build Funnels detected regions: regions=%d "
        "removed_clearance_master_duplicates=%d",
        "Retained visible green debug"
        if keep_references_for_debug
        else "Removed",
        core_count,
        clearance_count,
    )


def _manifold_union_parts_into_master(
    master: Object,
    parts: list[Object],
    context,
    *,
    component_label: str,
    consume_parts: bool = True,
) -> int:
    """Commit generated parts to the master, optionally retaining the operands."""

    total_count = len(parts)
    unioned_count = 0
    part_index = 0
    while part_index < len(parts):
        part = parts[part_index]
        part.hide_during_ui_breathe = False
        part.object.hide_set(False)
        part.object.hide_viewport = False
        part.object.hide_render = False
        master.apply_modifier(union_mod, target=part)
        if consume_parts:
            part.remove()
            parts.pop(part_index)
        else:
            part.object.hide_set(False)
            part.object.hide_viewport = False
            part.object.hide_render = False
            part_index += 1
        unioned_count += 1
        force_viewport_redraw(context)
        logger.info(
            "MANIFOLD-unioned Slip Casting %s into master: "
            "index=%d/%d master=%s",
            component_label,
            unioned_count,
            total_count,
            master.name,
        )
    return unioned_count


def _slip_casting_part_needs_master_union(raw) -> bool:
    """Recognize finished parts in both current and older generated scenes."""
    if raw.type != "MESH":
        return False
    if SLIP_CASTING_PENDING_MASTER_UNION_KEY in raw:
        return bool(raw[SLIP_CASTING_PENDING_MASTER_UNION_KEY])
    # A stored False means already committed. Only fall back for old parts
    # without the flag, and exclude construction wrappers and male bases.
    if raw.get(SLIP_CASTING_VASE_BASE_ROLE_KEY) == "MALE":
        return False
    if raw.get(SLIP_CASTING_FEMALE_BASE_KEY, False):
        return True
    name = raw.name.split(".", 1)[0]
    return bool(
        raw.get(SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY, False)
        and name.startswith(SLIP_CASTING_FUNNEL_SPAN_CORE_PREFIX)
        and name.endswith(SLIP_CASTING_FUNNEL_PART_WRAPPER_SUFFIX)
    ) or (
        bool(raw.get(SLIP_CASTING_FUNNEL_SPAN_WRAPPER_KEY, False))
        and name.startswith("slip_casting_funnel_span_core") and name.endswith("_wrapper")
    )


def ensure_slip_casting_restart_master(context, master=None):
    """Retain the clean full-resolution master before the first destructive step."""
    from ..mold_types import is_slip_casting_type
    if not is_slip_casting_type(getattr(context.scene, "mold_type_preview", "")):
        return None
    name = "_slip_casting_restart_master"
    existing = context.scene.objects.get(name)
    if existing is not None:
        return existing
    master = master or _slip_casting_master(context.scene)
    if master is None:
        raise ValueError("No master model found")
    raw = master.object.copy()
    raw.data = master.object.data.copy()
    raw.name = name
    raw["moldboxer_slip_casting_restart_master"] = True
    collection = master.object.users_collection[0] if master.object.users_collection else context.collection
    collection.objects.link(raw)
    raw.matrix_world = master.object.matrix_world.copy()
    raw.hide_set(True)
    raw.hide_viewport = True
    raw.hide_render = True
    raw.hide_select = True
    logger.info("Saved clean Slip Casting master for Restart: source=%s", master.name)
    return raw


def commit_slip_casting_parts_to_master(context, *, master=None, include_rounded_funnels=True):
    """Union pending parts; defer rounded funnels until after master clearance."""
    if master is None:
        master = _slip_casting_master(context.scene)
    if master is None:
        raise ValueError("No master model found")
    ensure_slip_casting_restart_master(context, master)
    cleanup_slip_casting_base_pairs(context.scene)
    parts = [
        Object(raw) for raw in context.scene.objects
        if raw != master.object and _slip_casting_part_needs_master_union(raw)
        and (include_rounded_funnels or not (
            "moldboxer_rounded_funnel_dimensions" in raw
            or raw.name.startswith("rounded_funnel_")
        ))
    ]
    for part in parts:
        _manifold_union_parts_into_master(
            master, [part], context,
            component_label="prepared funnel/base", consume_parts=False,
        )
        part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
        part.hide_during_ui_breathe = True
        _set_reference_hidden(part, True)
    master.select()
    return len(parts)


def _cleanup_finished_slip_funnel_build(previous_objects, previous_meshes, outputs):
    """Discard build intermediates while preserving the scene and final parts."""

    retained = previous_objects | {part.object.as_pointer() for part in outputs}
    leftovers = [
        raw for raw in bpy.data.objects if raw.as_pointer() not in retained
    ]
    remove_objects_safely(leftovers)
    # Helpers removed earlier in the pipeline can also leave unused mesh data.
    for mesh in list(bpy.data.meshes):
        if mesh.as_pointer() not in previous_meshes and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _lower_finished_casting_bases(bases, context, previous_objects):
    """Move finished base assemblies in world Z, including surviving loose locks."""
    if not bases:
        return []
    base_objects = {base.object for base in bases}
    accessories = []
    for raw in context.scene.objects:
        if (raw.type != "MESH" or raw in base_objects
                or raw.as_pointer() in previous_objects):
            continue
        name = raw.name.lower()
        named_lock = (
            ("vase_base" in name or "foot" in name or "female_base" in name)
            and ("pin" in name or "key" in name)
        )
        parent = raw.parent
        attached = False
        while parent is not None:
            if parent in base_objects:
                attached = True
                break
            parent = parent.parent
        operand = any(
            modifier.type == "BOOLEAN" and modifier.object == raw
            for base in base_objects for modifier in base.modifiers
        )
        if named_lock or attached or operand:
            accessories.append(Object(raw))

    # Capture every world transform first; parented keys must move only once.
    targets = [*base_objects, *(part.object for part in accessories)]
    def parent_depth(raw):
        depth = 0
        while raw.parent is not None:
            depth += 1
            raw = raw.parent
        return depth
    transforms = [(raw, raw.matrix_world.copy())
                  for raw in sorted(targets, key=parent_depth)]
    for raw, matrix in transforms:
        matrix.translation.z += SLIP_CASTING_FINISHED_BASE_Z_OFFSET_MM
        raw.matrix_world = matrix
        context.view_layer.update()
    logger.info("Lowered %d finished casting bases and %d separate locks by %.3f mm",
                len(base_objects), len(accessories), -SLIP_CASTING_FINISHED_BASE_Z_OFFSET_MM)
    return accessories


def restore_slip_casting_preparation_orientation(raw) -> None:
    """Undo the preparation orientation and lift, including on a backup."""
    from mathutils import Matrix, Vector

    key = "moldboxer_slip_casting_prepared_flipped"
    if raw.get(key, False):
        # Use world geometry bounds: generation may have applied the object's
        # transform or moved its origin since preparation.
        matrix = raw.matrix_world.copy()
        corners = [matrix @ Vector(point) for point in raw.bound_box]
        center = Vector(tuple(
            (min(point[axis] for point in corners) + max(point[axis] for point in corners)) / 2
            for axis in range(3)
        ))
        transform = (Matrix.Translation(center)
                     @ Matrix.Diagonal((-1., 1., -1., 1.))
                     @ Matrix.Translation(-center))
        raw.matrix_world = transform @ matrix
    if key in raw:
        del raw[key]
    lift_key = "moldboxer_slip_casting_prepared_lift"
    lift = float(raw.get(lift_key, 0.0))
    if lift:
        matrix = raw.matrix_world.copy()
        matrix.translation.z -= lift
        raw.matrix_world = matrix
    if lift_key in raw:
        del raw[lift_key]


def begin_detect_slip_casting_cores(context):
    """Prepare from base-down input and commit the final casting orientation."""
    from ..mold_types import is_slip_casting_type
    if not is_slip_casting_type(context.scene.mold_type_preview):
        return _begin_detect_slip_casting_cores_in_build_frame(context)

    def steps():
        from mathutils import Matrix, Vector
        from .direct_split_planes import iter_direct_split_plane_objects
        master = _slip_casting_master(context.scene)
        if master is None:
            raise ValueError("No master model found")
        original_matrix = master.object.matrix_world.copy()
        # Adapted funnels with a foot use an inverted build frame:
        # the service's lower funnel scan then sees the original top, while
        # its upper foot scan sees the original bottom. Internal funnels
        # return upright; internal no-foot masters also gain floor clearance.
        orientation_key = "moldboxer_slip_casting_prepared_flipped"
        lift_key = "moldboxer_slip_casting_prepared_lift"
        target_flipped = _slip_casting_master_target_flipped(context.scene)
        build_flipped = _slip_casting_master_build_flipped(context.scene)
        previous_lift = float(master.object.get(lift_key, 0.0))
        target_lift = _slip_casting_master_target_lift(context.scene)
        flip = build_flipped != bool(master.object.get(orientation_key, False))
        previous_built = master.object.get(SLIP_CASTING_FUNNELS_BUILT_KEY)
        if SLIP_CASTING_FUNNELS_BUILT_KEY in master.object:
            del master.object[SLIP_CASTING_FUNNELS_BUILT_KEY]
        # Preserve edited planes, including organic cutters. Their contour
        # children inherit the same transform automatically.
        # Preparation may replace guide objects. Keep names for rollback rather
        # than retaining RNA handles that become invalid when a guide is removed.
        split_matrices = [(plane.name, plane.matrix_world.copy())
                          for plane in iter_direct_split_plane_objects()]
        original_objects = {(raw.as_pointer(), raw.name) for raw in context.scene.objects}
        build_matrix = original_matrix.copy()
        build_matrix.translation.z -= previous_lift
        build_split_matrices = []
        for name, matrix in split_matrices:
            unlifted = matrix.copy()
            unlifted.translation.z -= previous_lift
            build_split_matrices.append((name, unlifted))
        corners = [build_matrix @ Vector(p) for p in master.object.bound_box]
        center = Vector(tuple((min(p[a] for p in corners)+max(p[a] for p in corners))/2 for a in range(3)))
        transform = Matrix.Translation(center) @ Matrix.Diagonal((-1.,1.,-1.,1.)) @ Matrix.Translation(-center)
        success = False
        try:
            if previous_lift:
                master.object.matrix_world = build_matrix
                for name, matrix in build_split_matrices:
                    plane = bpy.data.objects.get(name)
                    if plane is not None:
                        plane.matrix_world = matrix
                context.view_layer.update()
            if flip:
                master.object.matrix_world = transform @ build_matrix
                for name, matrix in build_split_matrices:
                    plane = bpy.data.objects.get(name)
                    if plane is not None:
                        plane.matrix_world = transform @ matrix
                context.view_layer.update()
            result = yield _begin_detect_slip_casting_cores_in_build_frame(context)
            clearance_debug_stop = (
                _internal_adapted_funnel(context.scene)
                and (_internal_debug_before_clearance(context.scene)
                     or _internal_debug_after_clearance(context.scene))
                and not master.object.get(SLIP_CASTING_FUNNELS_BUILT_KEY, False)
            )
            new_objects = {raw for raw in context.scene.objects
                           if (raw.as_pointer(), raw.name) not in original_objects}
            def depth(raw):
                count = 0
                while raw.parent is not None:
                    count += 1
                    raw = raw.parent
                return count
            finish_flipped = (
                _internal_adapted_funnel(context.scene)
                and build_flipped != target_flipped
                and not clearance_debug_stop
            )
            if finish_flipped:
                # Adapted geometry is built downward. Turn the entire finished
                # assembly over, preserving edited splits and attached keys.
                targets = {master.object, *iter_direct_split_plane_objects()}
                targets.update(new_objects)
                matrices = [(raw, transform @ raw.matrix_world.copy())
                            for raw in sorted(targets, key=depth)]
                for raw, matrix in matrices:
                    raw.matrix_world = matrix
                    if raw.get(SLIP_CASTING_VASE_BASE_KEY, False):
                        raw["moldboxer_slip_casting_lower_foot"] = True
                    context.view_layer.update()
            lift = 0.0 if clearance_debug_stop else target_lift
            if lift:
                targets = {master.object, *iter_direct_split_plane_objects()}
                targets.update(new_objects)
                matrices = [(raw, raw.matrix_world.copy())
                            for raw in sorted(targets, key=depth)]
                for raw, matrix in matrices:
                    matrix.translation.z += lift
                    raw.matrix_world = matrix
                context.view_layer.update()
            # A redraw or preparation helper may have reconciled/replaced a
            # guide in the build frame. Commit from the pre-build snapshot,
            # not that guide's possibly reset transform. Apply only the same
            # flips and floor lift used for the master and finished assembly.
            for name, matrix in build_split_matrices:
                plane = bpy.data.objects.get(name)
                if plane is None:
                    continue
                final_matrix = matrix.copy()
                if flip != finish_flipped:
                    final_matrix = transform @ final_matrix
                final_matrix.translation.z += lift
                plane.matrix_world = final_matrix
            context.view_layer.update()
            # Keep the clearance inspection in its build frame. Record the
            # actual orientation so retry and Restart can restore it correctly.
            master.object[orientation_key] = build_flipped if clearance_debug_stop else target_flipped
            master.object[lift_key] = lift
            success = True
            return result
        finally:
            if not success:
                master.object.matrix_world = original_matrix
                for name, matrix in split_matrices:
                    plane = bpy.data.objects.get(name)
                    if plane is not None:
                        plane.matrix_world = matrix
                if previous_built is None:
                    if SLIP_CASTING_FUNNELS_BUILT_KEY in master.object:
                        del master.object[SLIP_CASTING_FUNNELS_BUILT_KEY]
                else:
                    master.object[SLIP_CASTING_FUNNELS_BUILT_KEY] = previous_built
                context.view_layer.update()
    def guarded_steps():
        from .direct_split_planes import preserve_direct_split_planes_during_preparation
        with preserve_direct_split_planes_during_preparation(context.scene):
            return (yield from steps())

    return BackgroundTaskSequence(guarded_steps())


def _begin_detect_slip_casting_cores_in_build_frame(context):
    """Finish the service-provided casting parts against the local master."""

    if getattr(context.scene, "slip_casting_funnel_type", "ADAPTED") == "ROUNDED":
        from .slip_casting_rounded import begin_rounded_funnels
        return begin_rounded_funnels(context)
    master = _slip_casting_master(context.scene)
    if master is None:
        raise ValueError("No master model found")
    voxel_size = get_box_voxel_size(context.scene.box_quality, master)
    funnel_span = max(0.0, float(context.scene.slip_casting_funnel_span))
    funnel_extension = max(
        0.1,
        float(context.scene.slip_casting_funnel_extension),
    )
    build_vase_base = bool(getattr(context.scene, "slip_casting_generate_base", True))
    inspect_finished_base = (
        build_vase_base
        and SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_BASE_INSPECTION
        and not SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION
    )
    mold_thickness = float(context.scene.box_gap)
    if build_vase_base:
        if mold_thickness <= 0.0:
            raise ValueError(
                "Slip Casting mold thickness must be greater than zero"
            )
        for required_name in (
            SLIP_CASTING_VASE_BASE_NAME,
            SLIP_CASTING_FEMALE_BASE_NAME,
        ):
            if bpy.data.objects.get(required_name) is not None:
                raise RuntimeError(
                    "Funnel-style Prepare Vase requires the object name "
                    f'"{required_name}" to be free'
                )

    def steps():
        previous_objects = {raw.as_pointer() for raw in bpy.data.objects}
        previous_meshes = {mesh.as_pointer() for mesh in bpy.data.meshes}
        workflow_started = time.perf_counter()
        stage_started = workflow_started
        stage_timings: dict[str, float] = {}

        def finish_stage(stage_name: str) -> None:
            nonlocal stage_started
            now = time.perf_counter()
            stage_timings[stage_name] = now - stage_started
            stage_started = now
            logger.info(
                "Build Funnels stage completed: stage=%s elapsed=%.3fs",
                stage_name,
                stage_timings[stage_name],
            )

        imported_cores: list[Object] = []
        base_references: list[Object] = []
        cleared_masters: list[Object | None] = []
        base_clearances: list[Object | None] = []
        clearance_source: Object | None = None
        clearance_source_name = None
        funnel_span_target: Object | None = None
        funnel_wrappers: list[Object] = []
        base_wrappers: list[Object] = []
        funnel_parts: list[Object] = []
        base_parts: list[Object] = []
        female_bases: list[Object] = []
        base_accessories: list[Object] = []
        debug_wrappers: list[Object] = []
        debug_clearances: list[Object] = []
        final_internal_clearances: list[Object] = []
        detected_core_count = 0
        try:
            # All envelopes, local targets and simplified proxies must derive
            # from this validated master, not independent unrepaired copies.
            _ensure_preparation_source_manifold(
                master,
                role="master",
                voxel_size=get_master_voxel_size(context.scene.master_quality, master),
            )
            finish_stage("source_validation")
            imported_cores, base_references, funnel_wrappers = yield from _begin_cast_preparation(
                master, context, voxel_size=voxel_size, funnel_span=funnel_span,
                build_base=build_vase_base,
            )
            if (_internal_adapted_funnel(context.scene)
                    and (SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_REGION_CROPS
                         or SLIP_CASTING_INTERNAL_DEBUG_STOP_AFTER_REGION_CROPS)):
                for wrapper in funnel_wrappers:
                    wrapper.hide_during_ui_breathe = False
                    _set_reference_hidden(wrapper, False)
                    wrapper.object.hide_select = False
                    wrapper.object.display_type = "SOLID"
                    wrapper.object.show_name = True
                    wrapper.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                    assign_funnels_material(wrapper.object)
                _cleanup_finished_slip_funnel_build(previous_objects, previous_meshes, funnel_wrappers)
                master.object.pop(SLIP_CASTING_FUNNELS_BUILT_KEY, None)
                if funnel_wrappers:
                    funnel_wrappers[0].select()
                force_viewport_redraw(context)
                logger.info("Internal adapted debug stop: %s; wrappers=%d; "
                            "distance=0 final_wrap_distance=0; no clearance generated",
                            "before region cropping" if SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_REGION_CROPS
                            else "after region cropping",
                            len(funnel_wrappers))
                return funnel_wrappers
            if build_vase_base and not base_references:
                raise RuntimeError("Preparation returned no base references")
            target_wrap_distance = _slip_casting_analysis_wrap_distance(master)
            finish_stage("preparation")
            intersection_region_bounds = (
                _slip_casting_clearance_bounds_for_reference_wrappers(
                    funnel_wrappers,
                    imported_cores,
                    voxel_size=voxel_size,
                )
            )
            if build_vase_base:
                base_wrappers = yield from (
                    _build_slip_casting_funnel_span_wrappers_per_reference(
                        master,
                        base_references,
                        context,
                        voxel_size=voxel_size,
                        funnel_span=funnel_span,
                        target_wrap_distance=target_wrap_distance,
                        name_prefix=(
                            SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_NAME
                        ),
                        distance_override=(
                            SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_DISTANCE_MM
                        ),
                        remesh_between_wraps=True,
                        # Top references lie on the expanded analysis wrapper;
                        # move their crop back down onto the original master.
                        reference_z_offset=-target_wrap_distance,
                        minimum_half_height=target_wrap_distance,
                    )
                )
                base_intersection_region_bounds = (
                    _slip_casting_clearance_bounds_for_reference_wrappers(
                        base_wrappers,
                        base_references,
                        voxel_size=voxel_size,
                    )
                )
            base_clearance_region_bounds = []
            if build_vase_base:
                base_clearance_region_bounds = (
                    _expanded_slip_casting_clearance_region_bounds(
                        base_intersection_region_bounds,
                        z_margin=(
                            SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_Z_MARGIN_MM
                        ),
                    )
                )
            clearance_region_bounds = (
                _expanded_slip_casting_clearance_region_bounds(
                    intersection_region_bounds,
                    z_margin=(
                        SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_Z_MARGIN_MM
                    ),
                )
            )
            logger.info(
                "Expanded Slip Casting clearance regions by "
                "%.3fmm above and below the wrapper intersections",
                SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_Z_MARGIN_MM,
            )
            finish_stage("funnel_span_wrapper")
            force_viewport_redraw(context)
            if (
                SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_PER_PART_MASTER_WRAPS
                or (_internal_adapted_funnel(context.scene)
                    and SLIP_CASTING_INTERNAL_DEBUG_STOP_BEFORE_ANY_CLEARANCE)
            ):
                for part in [*base_references, *base_wrappers]:
                    _set_reference_hidden(part, True)
                for part in [*funnel_wrappers, *imported_cores]:
                    part.hide_during_ui_breathe = False
                    _set_reference_hidden(part, False)
                    part.object.display_type = "SOLID"
                    part.object.hide_select = False
                    part.object.show_in_front = False
                    part.object.select_set(False)
                    part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                    assign_funnels_material(part.object)
                master.object.pop(SLIP_CASTING_FUNNELS_BUILT_KEY, None)
                force_viewport_redraw(context)
                logger.info(
                    "Build Funnels debug stop after Per Region Master wraps: "
                    "wrappers=%d original_references=%d; Z intersection cubes "
                    "retained, clearance not generated",
                    len(funnel_wrappers), len(imported_cores),
                )
                return [*funnel_wrappers, *imported_cores]
            if not _solid_flat_regions(context.scene) or build_vase_base:
                clearance_source = yield from _build_slip_casting_clearance_proxy(master, context)
                clearance_source_name = clearance_source.name
            cleared_masters = yield from (
                _build_slip_casting_core_master_clearances(
                    master,
                    imported_cores,
                    context,
                    voxel_size=voxel_size,
                    funnel_wrappers=funnel_wrappers,
                    clearance_region_bounds=clearance_region_bounds,
                    clearance_source=clearance_source,
                    include_inward=not _internal_adapted_funnel(context.scene),
                    include_outward=True,
                    include_source_geometry=True,
                )
            )
            if build_vase_base:
                base_clearances = yield from (
                    _build_slip_casting_core_master_clearances(
                        master,
                        base_references,
                        context,
                        voxel_size=voxel_size,
                        funnel_wrappers=base_wrappers,
                        clearance_region_bounds=base_clearance_region_bounds,
                        clearance_source=clearance_source,
                        include_inward=False,
                        include_outward=True,
                    )
                )
            if not _internal_adapted_funnel(context.scene):
                clearance_source.remove()
                clearance_source = None
                clearance_source_name = None
            finish_stage("clearance_cutters")
            if inspect_finished_base:
                # Preserve the inputs before subtraction and reference matching
                # mutate or consume them. Reveal them only once the build ends.
                for source_parts, debug_parts, suffix in (
                    (base_wrappers, debug_wrappers, "_item_13"),
                    (base_clearances, debug_clearances, "_item_14"),
                ):
                    for part in source_parts:
                        if part is None:
                            continue
                        copy = part.duplicate(suffix)
                        copy.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                        _set_reference_hidden(copy, True)
                        copy.hide_during_ui_breathe = True
                        debug_parts.append(copy)
            if (
                SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_CLEARANCE_GENERATION
                or SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION
            ):
                wrappers = [*funnel_wrappers, *base_wrappers]
                if SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION:
                    for wrapper in wrappers:
                        copy = wrapper.duplicate("_item_13")
                        copy.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                        debug_wrappers.append(copy)
                    wrappers = debug_wrappers
                clearances = [
                    part for part in [*cleared_masters, *base_clearances]
                    if part is not None
                ]
                if SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION:
                    for clearance in clearances:
                        copy = clearance.duplicate("_item_14")
                        copy.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                        debug_clearances.append(copy)
                    clearances = debug_clearances
                references = [*imported_cores, *base_references]
                for part in references:
                    part.hide_during_ui_breathe = False
                    _set_reference_hidden(part, False)
                    part.object.hide_select = False
                    part.object.display_type = "SOLID"
                    part.object.show_in_front = True
                _show_slip_casting_reference_centers(references, master)
                for part in [*wrappers, *clearances]:
                    part.hide_during_ui_breathe = False
                    _set_reference_hidden(part, False)
                    part.object.hide_select = False
                    part.object.show_in_front = False
                    part.object.select_set(False)
                for part in wrappers:
                    part.object.display_type = "SOLID"
                for part in clearances:
                    part.object.display_type = "WIRE"
                    part.object.hide_render = True
                if wrappers:
                    wrappers[0].select()
                force_viewport_redraw(context)
                logger.info(
                    "Prepare Casting clearance inspection retained: "
                    "wrappers=%d clearances=%d",
                    len(wrappers), len(clearances),
                )
                if SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_CLEARANCE_GENERATION:
                    return [*wrappers, *clearances]
            force_viewport_redraw(context)
            if (
                build_vase_base
                and (
                    SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_CLEARANCE_GENERATION
                )
            ):
                return _show_slip_casting_vase_base_clearances_after_generation(
                    base_clearances,
                    context,
                )
            if _internal_adapted_funnel(context.scene):
                # Keep the original cutters for subtraction from matched regions before extension.
                final_internal_clearances.extend(
                    cutter for cutter in cleared_masters if cutter is not None)
                cleared_masters.clear()
            else:
                _subtract_core_clearances_from_funnel_span_wrappers(
                    funnel_wrappers,
                    cleared_masters,
                    context,
                )
            if (
                build_vase_base
                and (
                    SLIP_CASTING_DETECT_CORES_DEBUG_STOP_BEFORE_BASE_CLEARANCE_SUBTRACTION
                )
            ):
                _show_slip_casting_vase_base_wrappers_before_clearance_subtraction(
                    base_wrappers,
                    base_clearances,
                    context,
                )
                return base_wrappers
            if build_vase_base:
                _subtract_core_clearances_from_funnel_span_wrappers(
                    base_wrappers,
                    base_clearances,
                    context,
                )
            if (
                build_vase_base
                and (
                    SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_CLEARANCE_SUBTRACTION
                )
            ):
                _show_slip_casting_vase_base_wrappers_after_clearance_subtraction(
                    base_wrappers,
                    context,
                )
                return base_wrappers
            finish_stage("clearance_subtractions")
            force_viewport_redraw(context)
            if SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_FUNNEL_SUBTRACTIONS:
                for wrapper in funnel_wrappers:
                    wrapper.hide_during_ui_breathe = False
                    wrapper.object.hide_set(False)
                    wrapper.object.hide_viewport = False
                    wrapper.object.hide_render = False
                    wrapper.object.display_type = "SOLID"
                if funnel_wrappers:
                    funnel_wrappers[0].select()
                for wrapper in funnel_wrappers[1:]:
                    wrapper.object.select_set(True)
                force_viewport_redraw(context)
                logger.info(
                    "Build Funnels debug stop reached after funnel-span "
                    "clearance subtractions and before region splitting: "
                    "wrappers=%d cores=%d clearance_masters=%d",
                    len(funnel_wrappers),
                    len(imported_cores),
                    len(cleared_masters),
                )
                return funnel_wrappers
            for wrapper, core in zip(funnel_wrappers, imported_cores):
                funnel_parts.extend(
                    _keep_funnel_span_wrapper_parts_for_cores(
                        wrapper,
                        [core],
                        context,
                    )
                )
            if build_vase_base:
                for wrapper, reference in zip(base_wrappers, base_references):
                    base_parts.extend(
                        _keep_funnel_span_wrapper_parts_for_cores(
                            wrapper,
                            [reference],
                            context,
                            use_max_z=True,
                        )
                    )
            funnel_wrappers = []
            base_wrappers = []
            finish_stage("reference_matching")
            if (
                build_vase_base
                and SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_BASE_PART_MATCHING
            ):
                _show_slip_casting_vase_base_parts_after_reference_matching(
                    base_parts,
                    context,
                )
                return base_parts
            if SLIP_CASTING_DETECT_CORES_DEBUG_STOP_AFTER_PART_MATCHING:
                for funnel_part in funnel_parts:
                    assign_slip_casting_funnel_span_material(
                        funnel_part.object
                    )
                    funnel_part.object.hide_set(False)
                    funnel_part.object.hide_viewport = False
                    funnel_part.object.hide_render = False
                    funnel_part.object.display_type = "SOLID"
                for imported_core in imported_cores:
                    _set_reference_hidden(imported_core, True)
                for cleared_master in cleared_masters:
                    if cleared_master is not None:
                        _set_reference_hidden(cleared_master, True)
                if funnel_parts:
                    funnel_parts[0].select()
                    for funnel_part in funnel_parts[1:]:
                        funnel_part.object.select_set(True)
                force_viewport_redraw(context)
                logger.info(
                    "Build Funnels debug stop reached after funnel-span region "
                    "splitting and minimum-Z core matching: matched=%d; "
                    "unmatched regions removed",
                    len(funnel_parts),
                )
                return funnel_parts
            force_viewport_redraw(context)
            if _solid_flat_regions(context.scene):
                funnel_parts = yield from _build_solid_flat_regions(
                    master, context, voxel_size=voxel_size, funnel_extension=funnel_extension)
                detected_core_count = len(funnel_parts)
            else:
                detected_core_count = len(imported_cores)
                if _internal_debug_before_clearance(context.scene):
                    yield from _clear_internal_funnel_vertical_extraction(
                        funnel_parts, master, context, voxel_size=voxel_size,
                        debug_outputs=debug_clearances, subtract=False,
                        clearance_source=clearance_source)
                    clearance_source.remove()
                    clearance_source = None
                    clearance_source_name = None
                    retained = [*funnel_parts, *final_internal_clearances, *debug_clearances]
                    from ..materials import assign_material, get_or_create_simple_material
                    clearance_material = get_or_create_simple_material(
                        "Internal Clearance Debug Red", "E53935", roughness=0.5)
                    for part in retained:
                        part.hide_during_ui_breathe = False
                        _set_reference_hidden(part, False)
                        part.object.hide_select = False
                        part.object.hide_render = True
                        part.object.show_name = True
                        part.object.display_type = "SOLID"
                        part.object.show_wire = False
                        part.object.show_all_edges = False
                        part.object.show_in_front = False
                        if part not in funnel_parts:
                            part.object.hide_render = False
                            assign_material(part.object, clearance_material)
                            part.object.color = clearance_material.diffuse_color
                        part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                        part.object["moldboxer_internal_clearance_debug"] = True
                    _cleanup_finished_slip_funnel_build(previous_objects, previous_meshes, retained)
                    master.object.pop(SLIP_CASTING_FUNNELS_BUILT_KEY, None)
                    if funnel_parts:
                        funnel_parts[0].select()
                        for part in funnel_parts[1:]:
                            part.object.select_set(True)
                    finish_stage("internal_before_clearance_subtraction_debug_stop")
                    force_viewport_redraw(context)
                    logger.info("Internal adapted debug stop: after clearance generation, before subtraction; "
                                "vertical_source=simplified_master wrapper=False "
                                "parts=%d outward_cutters=%d vertical_cutters=%d",
                                len(funnel_parts), len(final_internal_clearances), len(debug_clearances))
                    return retained
                if final_internal_clearances:
                    if (_internal_adapted_funnel(context.scene)
                            and SLIP_CASTING_INTERNAL_DEBUG_SKIP_OUTWARD_CLEARANCE):
                        logger.info("Internal adapted debug: skipping outward clearance subtraction; vertical only")
                    else:
                        _subtract_final_internal_funnel_clearances(
                            funnel_parts, final_internal_clearances, context)
                    for cutter in final_internal_clearances:
                        cutter.remove()
                    final_internal_clearances.clear()
                if _internal_adapted_funnel(context.scene):
                    yield from _clear_internal_funnel_vertical_extraction(
                        funnel_parts, master, context, voxel_size=voxel_size,
                        clearance_source=clearance_source)
                    clearance_source.remove()
                    clearance_source = None
                    clearance_source_name = None
                    if _internal_debug_after_clearance(context.scene):
                        for cutter in debug_clearances:
                            cutter.remove()
                        debug_clearances.clear()
                        retained = list(funnel_parts)
                        for part in retained:
                            part.hide_during_ui_breathe = False
                            _set_reference_hidden(part, False)
                            part.object.hide_select = False
                            part.object.hide_render = True
                            part.object.show_name = True
                            part.object.display_type = "SOLID"
                            part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = False
                            part.object["moldboxer_internal_clearance_debug"] = True
                        _cleanup_finished_slip_funnel_build(previous_objects, previous_meshes, retained)
                        master.object.pop(SLIP_CASTING_FUNNELS_BUILT_KEY, None)
                        if funnel_parts:
                            funnel_parts[0].select()
                            for part in funnel_parts[1:]:
                                part.object.select_set(True)
                        finish_stage("internal_clearance_debug_stop")
                        force_viewport_redraw(context)
                        logger.info("Internal adapted debug stop: after %s clearance subtraction "
                                    "and cutter removal; parts=%d; "
                                    "before artifact removal, extension, remesh and smoothing",
                                    "vertical only" if SLIP_CASTING_INTERNAL_DEBUG_SKIP_OUTWARD_CLEARANCE else "outward and vertical",
                                    len(funnel_parts))
                        return retained
                    _remove_internal_funnel_volume_artifacts(funnel_parts)
                    funnel_parts = yield from _finish_internal_funnel_surfaces(
                        funnel_parts, master, context, funnel_extension=funnel_extension,
                        voxel_size=voxel_size)
                else:
                    funnel_parts = yield from _build_cleared_funnel_span_part_wrappers(
                        funnel_parts,
                        master,
                        context,
                        voxel_size=voxel_size,
                        funnel_extension=funnel_extension,
                        debug_stop_after_wrapper_generation=False,
                    )
            if build_vase_base:
                base_parts = yield from (
                    _build_final_slip_casting_vase_base_parts(
                        base_parts,
                        master,
                        context,
                        voxel_size=voxel_size,
                        mold_thickness=mold_thickness,
                    )
                )
                base_parts, female_bases = (
                    _finish_funnel_generated_vase_bases(
                        base_parts,
                        master,
                        context,
                        mold_thickness=mold_thickness,
                    )
                )
                base_accessories = _lower_finished_casting_bases(
                    [*base_parts, *female_bases], context, previous_objects,
                )
            finish_stage("final_funnel_wrappers")
            force_viewport_redraw(context)
            for funnel_part in funnel_parts:
                assign_funnels_material(funnel_part.object)
                funnel_part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = True
            if funnel_parts:
                finished_funnel_count = len(funnel_parts)
                for funnel_part in funnel_parts:
                    funnel_part.hide_during_ui_breathe = False
                    funnel_part.object.hide_set(False)
                    funnel_part.object.hide_viewport = False
                    funnel_part.object.hide_render = False
                    funnel_part.object.display_type = "SOLID"
                logger.info(
                    "Build Funnels: retained %d finished funnel-span "
                    "part%s separately from master=%s",
                    finished_funnel_count,
                    "" if finished_funnel_count == 1 else "s",
                    master.name,
                )
            else:
                finished_funnel_count = 0
            if inspect_finished_base:
                for part in [*base_references, *debug_wrappers, *debug_clearances]:
                    part.hide_during_ui_breathe = False
                    _set_reference_hidden(part, False)
                    part.object.hide_select = False
                    part.object.hide_render = True
                    part.object.show_name = True
                    part.object.show_in_front = part in base_references
                    part.object.display_type = (
                        "SOLID" if part in base_references else "WIRE"
                    )
                _show_slip_casting_reference_centers(base_references, master)
                retained_parts = [
                    *funnel_parts, *base_parts, *female_bases, *base_accessories,
                    *base_references, *debug_wrappers, *debug_clearances,
                    *_existing_slip_casting_vase_funnel_reference_center_markers(
                        context.scene
                    ),
                ]
                _cleanup_finished_slip_funnel_build(
                    previous_objects, previous_meshes, retained_parts,
                )
                master.object[SLIP_CASTING_FUNNELS_BUILT_KEY] = True
                if base_references:
                    base_references[0].select()
                finish_stage("final_union_and_cleanup")
                force_viewport_redraw(context)
                logger.info(
                    "Prepare Casting final base inspection: regions=%d "
                    "wrappers=%d clearances=%d; region centers retained",
                    len(base_references), len(debug_wrappers), len(debug_clearances),
                )
                return retained_parts
            if SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_FINAL_FUNNEL_INSPECTION:
                for wrapper in debug_wrappers:
                    wrapper.object.display_type = "WIRE"
                    wrapper.object.hide_render = True
                if funnel_parts:
                    funnel_parts[0].select()
                    for part in funnel_parts[1:]:
                        part.object.select_set(True)
                master.object[SLIP_CASTING_FUNNELS_BUILT_KEY] = True
                force_viewport_redraw(context)
                logger.info(
                    "Prepare Casting final funnel inspection: funnels=%d; "
                    "original wrappers, clearances, regions and centers retained",
                    len(funnel_parts),
                )
                return [
                    *funnel_parts, *base_parts, *female_bases, *base_accessories,
                    *debug_wrappers, *debug_clearances,
                ]
            _remove_detected_cores_and_clearance_masters(
                [*imported_cores, *base_references],
                cleared_masters,
                context,
                keep_references_for_debug=(
                    SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_DETECTED_PARTS
                ),
            )
            retained_parts = [*funnel_parts, *base_parts, *female_bases, *base_accessories]
            if SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_DETECTED_PARTS:
                retained_parts.extend([*imported_cores, *base_references])
            _cleanup_finished_slip_funnel_build(
                previous_objects, previous_meshes, retained_parts,
            )
            imported_cores = []
            cleared_masters = []
            base_references = []
            base_clearances = []
            finish_stage("final_union_and_cleanup")
            # Completion records a successful stage, even when optional parts
            # were all skipped because their geometry became empty.
            master.object[SLIP_CASTING_FUNNELS_BUILT_KEY] = True
            force_viewport_redraw(context)
        except BaseException:
            for wrapper in [*debug_wrappers, *debug_clearances, *final_internal_clearances]:
                if wrapper.object.name in bpy.data.objects:
                    wrapper.remove()
            if (
                funnel_span_target is not None
                and funnel_span_target.object.name in bpy.data.objects
            ):
                funnel_span_target.remove()
            if SLIP_CASTING_DETECT_CORES_DEBUG_KEEP_DETECTED_PARTS:
                _remove_detected_cores_and_clearance_masters(
                    [*imported_cores, *base_references],
                    [],
                    context,
                    keep_references_for_debug=True,
                )
                imported_cores = []
                base_references = []
            else:
                for core in imported_cores:
                    if core.object.name in bpy.data.objects:
                        core.remove()
                for base_reference in base_references:
                    if base_reference.object.name in bpy.data.objects:
                        base_reference.remove()
            for cleared_master in cleared_masters:
                if (
                    cleared_master is not None
                    and cleared_master.object.name in bpy.data.objects
                ):
                    cleared_master.remove()
            for base_clearance in base_clearances:
                if (
                    base_clearance is not None
                    and base_clearance.object.name in bpy.data.objects
                ):
                    base_clearance.remove()
            if (
                clearance_source is not None
                and clearance_source.object.name in bpy.data.objects
            ):
                clearance_source.remove()
            for funnel_part in funnel_parts:
                if funnel_part.object.name in bpy.data.objects:
                    funnel_part.remove()
            for wrapper in funnel_wrappers:
                if wrapper.object.name in bpy.data.objects:
                    wrapper.remove()
            for base_part in base_parts:
                if base_part.object.name in bpy.data.objects:
                    base_part.remove()
            for wrapper in base_wrappers:
                if wrapper.object.name in bpy.data.objects:
                    wrapper.remove()
            raise
        finally:
            if clearance_source_name is not None:
                raw = bpy.data.objects.get(clearance_source_name)
                if raw is not None:
                    Object(raw).remove()

        if funnel_parts:
            funnel_parts[0].select()
            for funnel_part in funnel_parts[1:]:
                funnel_part.object.select_set(True)
        else:
            master.select()
        logger.info(
            "Detected %d Slip Casting region%s and retained %d "
            "finished funnel-span part%s %s",
            detected_core_count,
            "" if detected_core_count == 1 else "s",
            finished_funnel_count,
            "" if finished_funnel_count == 1 else "s",
            "separately until Generate Mold",
        )
        logger.info(
            "Build Funnels timing summary: total=%.3fs %s",
            time.perf_counter() - workflow_started,
            " ".join(
                f"{stage_name}={elapsed:.3f}s"
                for stage_name, elapsed in stage_timings.items()
            ),
        )
        return []

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _keep_bottom_isolated_meshes(result: Object) -> list[Object]:
    """Keep only isolated mesh regions that reach the generated bottom plane."""

    isolated_parts = result.split_isolated_meshes()
    lowest_z = min(float(part.min_z) for part in isolated_parts)
    retained = [
        part
        for part in isolated_parts
        if float(part.min_z)
        <= lowest_z + SLIP_CASTING_BOTTOM_PART_Z_TOLERANCE_MM
    ]
    retained.sort(
        key=lambda part: (
            float(part.min_z),
            float(part.center_coords.x),
            float(part.center_coords.y),
        ),
    )
    for part in isolated_parts:
        if any(part.object == bottom_part.object for bottom_part in retained):
            continue
        part.remove()
    removed_count = len(isolated_parts) - len(retained)
    logger.info(
        "Kept %s bottom Slip Casting vase-base region%s within %.3f mm of "
        "min_z=%.6f; removed %s higher region%s",
        len(retained),
        "" if len(retained) == 1 else "s",
        SLIP_CASTING_BOTTOM_PART_Z_TOLERANCE_MM,
        lowest_z,
        removed_count,
        "" if removed_count == 1 else "s",
    )
    return retained


def _keep_top_isolated_meshes(result: Object) -> list[Object]:
    """Keep all isolated vase-base regions reaching the reversed top plane."""

    force_viewport_redraw()
    isolated_parts = result.split_isolated_meshes()
    force_viewport_redraw()
    highest_z = max(float(part.max_z) for part in isolated_parts)
    retained = [
        part
        for part in isolated_parts
        if float(part.max_z)
        >= highest_z - SLIP_CASTING_VASE_TOP_PART_Z_TOLERANCE_MM
    ]
    retained.sort(
        key=lambda part: (
            -float(part.max_z),
            float(part.center_coords.x),
            float(part.center_coords.y),
        ),
    )
    for part in isolated_parts:
        if any(part.object == top_part.object for top_part in retained):
            continue
        logger.warning(
            "Prepare Vase removing pre-split region %s: reason=max_z below "
            "highest-region tolerance volume=%.6fml min_z=%.6f max_z=%.6f "
            "center=(%.6f, %.6f, %.6f) highest_z=%.6f tolerance=%.6f",
            part.name,
            abs(float(part.volume)),
            float(part.min_z),
            float(part.max_z),
            float(part.center_coords.x),
            float(part.center_coords.y),
            float(part.center_coords.z),
            highest_z,
            SLIP_CASTING_VASE_TOP_PART_Z_TOLERANCE_MM,
        )
        part.remove()
    removed_count = len(isolated_parts) - len(retained)
    logger.info(
        "Kept %s top Slip Casting vase-base region%s within %.3f mm of "
        "max_z=%.6f; removed %s lower region%s",
        len(retained),
        "" if len(retained) == 1 else "s",
        SLIP_CASTING_VASE_TOP_PART_Z_TOLERANCE_MM,
        highest_z,
        removed_count,
        "" if removed_count == 1 else "s",
    )
    force_viewport_redraw()
    return retained


def _split_and_filter_vase_base_top_sections(
    result: Object,
    *,
    target_max_z: float,
    minimum_volume_ml: float = SLIP_CASTING_VASE_BASE_MIN_TOP_VOLUME_ML,
) -> list[Object]:
    """Keep the top and Boolean-union retained lower sections with overlap."""

    split_z = float(target_max_z)
    volume_limit = max(float(minimum_volume_ml), 0.0)
    original_name = result.name

    if float(result.min_z) >= split_z:
        logger.info(
            "Slip Casting vase base %s is entirely above target_max_z=%.6f; "
            "no lower sections required filtering",
            original_name,
            split_z,
        )
        return [result]

    if float(result.max_z) <= split_z:
        lower_parts = result.split_isolated_meshes()
        top_parts: list[Object] = []
    else:
        lower_side, top_side = result.split(
            plane_normal=mathutils.Vector((0.0, 0.0, 1.0)),
            plane_point=mathutils.Vector((0.0, 0.0, split_z)),
        )
        result.remove()
        force_viewport_redraw()
        lower_parts = lower_side.split_isolated_meshes()
        top_parts = top_side.split_isolated_meshes()

    retained_lower: list[Object] = []
    removed: list[tuple[str, float, float]] = []
    for lower_part in lower_parts:
        volume_ml = abs(float(lower_part.volume))
        maximum_z = float(lower_part.max_z)
        if volume_ml >= volume_limit:
            retained_lower.append(lower_part)
            continue
        removed.append((lower_part.name, volume_ml, maximum_z))
        logger.warning(
            "Prepare Vase removing lower split section %s: reason=volume below "
            "minimum volume=%.6fml min_z=%.6f max_z=%.6f center=(%.6f, "
            "%.6f, %.6f) split_z=%.6f minimum_volume=%.6fml",
            lower_part.name,
            volume_ml,
            float(lower_part.min_z),
            maximum_z,
            float(lower_part.center_coords.x),
            float(lower_part.center_coords.y),
            float(lower_part.center_coords.z),
            split_z,
            volume_limit,
        )
        if lower_part.object.name in bpy.data.objects:
            lower_part.remove()

    for lower_part in retained_lower:
        lower_part.translate_whole(
            mathutils.Vector(
                (0.0, 0.0, SLIP_CASTING_VASE_BASE_LOWER_UNION_OVERLAP_MM)
            )
        )

    survivors = [*top_parts, *retained_lower]
    if not survivors:
        logger.info(
            "Split Slip Casting vase base %s at target_max_z=%.6f and "
            "removed every lower section below %.3f ml",
            original_name,
            split_z,
            volume_limit,
        )
        force_viewport_redraw()
        return []

    top_parts.sort(
        key=lambda part: (
            -abs(float(part.volume)),
            float(part.center_coords.x),
            float(part.center_coords.y),
        )
    )
    retained_lower.sort(
        key=lambda part: (
            -abs(float(part.volume)),
            float(part.center_coords.x),
            float(part.center_coords.y),
        )
    )
    joined = top_parts[0] if top_parts else retained_lower[0]
    for survivor in survivors:
        if survivor.object == joined.object:
            continue
        joined.apply_modifier(union_mod, target=survivor)
        survivor.remove()
    joined.name = original_name
    logger.info(
        "Split Slip Casting vase base at target_max_z=%.6f, kept %s top "
        "section%s, translated %s retained lower section%s upward by %.3f mm "
        "and MANIFOLD-unioned the survivors at or above %.3f ml, and removed "
        "%s: %s",
        split_z,
        len(top_parts),
        "" if len(top_parts) == 1 else "s",
        len(retained_lower),
        "" if len(retained_lower) == 1 else "s",
        SLIP_CASTING_VASE_BASE_LOWER_UNION_OVERLAP_MM,
        volume_limit,
        len(removed),
        ", ".join(
            f"{name}(volume={volume_ml:.3f}ml,max_z={maximum_z:.3f})"
            for name, volume_ml, maximum_z in removed
        )
        or "none",
    )
    force_viewport_redraw()
    return [joined]


def _vase_base_pin_diameter(
    requested_diameter: float,
    mold_thickness: float,
    locking_tolerance: float,
    *,
    pin_role: str,
) -> float:
    return acquire_geometry_worker().geometry_policy('q54', p0=requested_diameter, p1=mold_thickness, p2=locking_tolerance, p3=pin_role)["value"]


def _vase_base_pin_cap_height(pin_diameter: float) -> float:
    return acquire_geometry_worker().geometry_policy('q79', p0=pin_diameter)["value"]


def _create_vase_base_pin_cap(
    pin_diameter: float,
    name: str,
) -> Object | None:
    geometry = acquire_geometry_worker().geometry_policy('q12', p0=pin_diameter)
    if not geometry:
        return None
    vertices, faces = geometry['vertices'], geometry['faces']
    radius, height = geometry['radius'], geometry['height']
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    raw_object = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(raw_object)
    cap = Object(raw_object)
    cap.recalculate_normals()
    _flatten_vase_base_pin_tip(
        cap,
        radius=radius,
        cap_height=height,
    )
    return cap


def _flatten_vase_base_pin_tip(
    cap: Object,
    *,
    radius: float,
    cap_height: float,
) -> None:
    """Clip and cap the local +X tip directly, without a Boolean operand."""

    cut_x = float(cap_height) * SLIP_CASTING_VASE_BASE_PIN_FLAT_TIP_HEIGHT_FACTOR
    bm = bmesh.new()
    try:
        bm.from_mesh(cap.object.data)
        result = bmesh.ops.bisect_plane(
            bm,
            geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            dist=1e-7,
            plane_co=(cut_x, 0.0, 0.0),
            plane_no=(1.0, 0.0, 0.0),
            clear_outer=True,
            clear_inner=False,
        )
        boundary = [edge for edge in result["geom_cut"]
                    if isinstance(edge, bmesh.types.BMEdge) and edge.is_boundary]
        bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(cap.object.data)
        cap.object.data.update(calc_edges=True)
    finally:
        bm.free()


def _union_disjoint_vase_base_pins(vase_base: Object, pins: list[Object]) -> int:
    """Union separated pin shells together; keep touching pins sequential."""
    batches = []
    batch, bounds = [], []
    for pin in pins:
        points = [pin.object.matrix_world @ vertex.co for vertex in pin.object.data.vertices]
        current = ([min(point[axis] for point in points) for axis in range(3)],
                   [max(point[axis] for point in points) for axis in range(3)])
        if any(not any(current[1][axis] < previous[0][axis] - 1e-5
                       or previous[1][axis] < current[0][axis] - 1e-5
                       for axis in range(3)) for previous in bounds):
            batches.append(batch)
            batch, bounds = [], []
        batch.append(pin)
        bounds.append(current)
    if batch:
        batches.append(batch)
    for batch in batches:
        if len(batch) == 1:
            vase_base.apply_modifier(union_mod, target=batch[0])
            continue
        vertices, faces = [], []
        for pin in batch:
            offset = len(vertices)
            vertices.extend(tuple(pin.object.matrix_world @ vertex.co)
                            for vertex in pin.object.data.vertices)
            faces.extend(tuple(offset + index for index in face.vertices)
                         for face in pin.object.data.polygons)
        mesh = bpy.data.meshes.new("_vase_base_pin_union_batch")
        operand = None
        try:
            mesh.from_pydata(vertices, [], faces)
            mesh.update(calc_edges=True)
            raw = bpy.data.objects.new("_vase_base_pin_union_batch", mesh)
            operand = Object(raw)
            bpy.context.collection.objects.link(raw)
            vase_base.apply_modifier(union_mod, target=operand)
        finally:
            if operand is not None:
                operand.remove()
            remove_unused_meshes([mesh])
    return len(batches)


def _raycast_vase_base_boundary(
    vase_bases: list[Object],
    horizontal_normal: mathutils.Vector,
    pin_z: float,
    side: float,
) -> tuple[Object, mathutils.Vector] | None:
    """Find an outermost hit along a line through the base's XY center."""

    outward = horizontal_normal * float(side)
    corners = [
        corner
        for vase_base in vase_bases
        for corner in vase_base.world_cords_bound_box
    ]
    if not corners:
        return None
    axis_point = mathutils.Vector((
        (min(corner.x for corner in corners) + max(corner.x for corner in corners)) / 2.0,
        (min(corner.y for corner in corners) + max(corner.y for corner in corners)) / 2.0,
        pin_z,
    ))
    support_values = [corner.dot(outward) for corner in corners]
    start_distance = (
        max(support_values)
        - axis_point.dot(outward)
        + SLIP_CASTING_VASE_BASE_PIN_RAY_MARGIN_MM
    )
    ray_origin = axis_point + outward * start_distance
    ray_direction = -outward
    nearest: tuple[float, Object, mathutils.Vector] | None = None

    for vase_base in vase_bases:
        if not float(vase_base.min_z) <= pin_z <= float(vase_base.max_z):
            continue
        raw = vase_base.object
        was_hidden = raw.hide_get()
        was_hide_viewport = bool(raw.hide_viewport)
        try:
            # Blender does not retain evaluated mesh data for viewport-disabled
            # objects, and Object.ray_cast raises in that state. These generated
            # bases normally remain hidden between construction stages.
            raw.hide_set(False)
            raw.hide_viewport = False
            bpy.context.view_layer.update()
            inverse = raw.matrix_world.inverted()
            local_origin = inverse @ ray_origin
            local_direction = (
                inverse.to_3x3() @ ray_direction
            ).normalized()
            hit, local_location, _normal, _face_index = raw.ray_cast(
                local_origin,
                local_direction,
                distance=1.0e12,
            )
        finally:
            raw.hide_set(was_hidden)
            raw.hide_viewport = was_hide_viewport
            bpy.context.view_layer.update()
        if not hit:
            continue
        world_location = raw.matrix_world @ local_location
        distance = (world_location - ray_origin).dot(ray_direction)
        if distance < -1.0e-5:
            continue
        if nearest is None or distance < nearest[0]:
            nearest = (distance, vase_base, world_location)

    if nearest is None:
        return None
    return nearest[1], nearest[2]


def _add_split_plane_pins_to_vase_bases(
    vase_bases: list[Object],
    split_plane_specs: list[object],
    *,
    pin_z: float,
    mold_thickness: float,
    requested_pin_diameter: float,
    locking_tolerance: float,
    pin_role: str,
) -> int:
    """Add two outward locking pins per split plane with MANIFOLD unions."""

    normalized_role = str(pin_role).upper()
    pin_diameter = _vase_base_pin_diameter(
        requested_pin_diameter,
        mold_thickness,
        locking_tolerance,
        pin_role=normalized_role,
    )
    if pin_diameter <= 0.0 or not vase_bases:
        return 0

    # Ray hits and pin meshes are expressed in world millimetres. Applying the
    # imported base transforms prevents a deeply embedded pin from being
    # rescaled again by Blender's Boolean operand transform.
    for vase_base in vase_bases:
        vase_base.apply_all_transforms()
        force_viewport_redraw()

    pin_z = float(pin_z)
    placements: list[
        tuple[int, str, Object, mathutils.Vector, mathutils.Vector]
    ] = []
    for plane_index, plane_spec in enumerate(split_plane_specs, start=1):
        _point_values, normal_values = split_spec_point_normal(plane_spec)
        plane_normal = mathutils.Vector(normal_values)
        if plane_normal.length <= 1.0e-9:
            logger.warning(
                "Skipping vase-base pins for split plane %s because its "
                "normal is zero",
                plane_index,
            )
            continue
        plane_normal.normalize()
        horizontal_normal = mathutils.Vector(
            (plane_normal.x, plane_normal.y, 0.0)
        )
        if (
            horizontal_normal.length
            <= SLIP_CASTING_VASE_BASE_PIN_MIN_HORIZONTAL_NORMAL
        ):
            logger.warning(
                "Skipping vase-base pins for split plane %s because its "
                "normal has no horizontal direction",
                plane_index,
            )
            continue
        horizontal_normal.normalize()

        for side, side_name in ((1.0, "positive"), (-1.0, "negative")):
            boundary = _raycast_vase_base_boundary(
                vase_bases,
                horizontal_normal,
                pin_z,
                side,
            )
            if boundary is None:
                logger.warning(
                    "Could not place the %s vase-base pin for split plane %s "
                    "at z=%.3f because its normal line missed the vase base",
                    side_name,
                    plane_index,
                    pin_z,
                )
                continue
            vase_base, boundary_point = boundary
            placements.append(
                (
                    plane_index,
                    side_name,
                    vase_base,
                    boundary_point,
                    plane_normal * side,
                )
            )

    added_count = 0
    union_count = 0
    generated_pins = []
    grouped_pins = {}
    try:
        for plane_index, side_name, vase_base, boundary_point, outward in placements:
            pin = _create_vase_base_pin_cap(
                pin_diameter,
                (
                    f"{SLIP_CASTING_VASE_BASE_PIN_PREFIX}"
                    f"{normalized_role.lower()}_sp{plane_index:02d}_{side_name}"
                ),
            )
            if pin is None:
                continue
            generated_pins.append(pin)
            pin.rotate_whole(
                calculate_rotation_diff_matrix(
                    mathutils.Vector((1.0, 0.0, 0.0)),
                    outward.copy(),
                )
            )
            pin.translate_whole(boundary_point)
            grouped_pins.setdefault(vase_base.object, (vase_base, []))[1].append(pin)
        bpy.context.view_layer.update()
        for vase_base, pins in grouped_pins.values():
            union_count += _union_disjoint_vase_base_pins(vase_base, pins)
            added_count += len(pins)
            force_viewport_redraw()
    finally:
        for pin in generated_pins:
            if pin.object.name in bpy.data.objects:
                pin.remove()

    logger.info(
        "Added %s outward Slip Casting %s vase-base pin%s with MANIFOLD "
        "unions at z=%.3f: split_planes=%s diameter=%.3f "
        "requested_diameter=%.3f locking_tolerance=%.3f boolean_unions=%d",
        added_count,
        normalized_role.lower(),
        "" if added_count == 1 else "s",
        pin_z,
        len(split_plane_specs),
        pin_diameter,
        requested_pin_diameter,
        locking_tolerance,
        union_count,
    )
    return added_count


def _vase_base_pin_split_plane_specs(context, *, log_context: str) -> list[object]:
    """Use live split planes, falling back to the last captured plane specs."""

    split_planes = direct_split_plane_specs(log_context=log_context)
    if split_planes:
        return split_planes
    scene = getattr(context, "scene", None)
    if not callable(getattr(scene, "get", None)):
        scene = bpy.context.scene
    split_planes = stored_silicone_split_plane_specs(scene)
    if split_planes:
        logger.info(
            "%s: using %d stored split plane%s because no live split-plane "
            "objects were available",
            log_context,
            len(split_planes),
            "" if len(split_planes) == 1 else "s",
        )
    else:
        logger.warning(
            "%s: no live or stored split planes; vase-base pins cannot be "
            "generated",
            log_context,
        )
    return split_planes




def _finish_funnel_generated_vase_bases(
    vase_bases: list[Object],
    master: Object,
    context,
    *,
    mold_thickness: float,
    split_planes_override=None,
) -> tuple[list[Object], list[Object]]:
    """Create and commit the male/female bases from reversed funnel parts."""

    if not vase_bases:
        logger.warning("No valid base parts remain; continuing without a base")
        return [], []
    split_planes = (split_planes_override if split_planes_override is not None
                    else _vase_base_pin_split_plane_specs(
                        context, log_context="Slip Casting funnel-style vase-base pin capture"))
    requested_pin_diameter = float(
        getattr(
            context.scene,
            "split_base_pin_diameter",
            SLIP_CASTING_DEFAULT_PIN_DIAMETER_MM,
        )
    )
    locking_tolerance = float(
        getattr(
            context.scene,
            "plaster_locking_tolerance",
            SLIP_CASTING_DEFAULT_LOCKING_TOLERANCE_MM,
        )
    )
    pin_z = float(master.max_z) + float(mold_thickness) / 2.0
    female_bases = [part.duplicate("_female_base") for part in vase_bases]
    force_viewport_redraw(context)
    _add_split_plane_pins_to_vase_bases(
        vase_bases,
        split_planes,
        pin_z=pin_z,
        mold_thickness=mold_thickness,
        requested_pin_diameter=requested_pin_diameter,
        locking_tolerance=locking_tolerance,
        pin_role="MALE",
    )
    force_viewport_redraw(context)
    _add_split_plane_pins_to_vase_bases(
        female_bases,
        split_planes,
        pin_z=pin_z,
        mold_thickness=mold_thickness,
        requested_pin_diameter=requested_pin_diameter,
        locking_tolerance=locking_tolerance,
        pin_role="FEMALE",
    )
    force_viewport_redraw(context)

    for part_index, part in enumerate(vase_bases):
        part.name = (
            SLIP_CASTING_VASE_BASE_NAME
            if part_index == 0
            else f"{SLIP_CASTING_VASE_BASE_NAME}_{part_index + 1:03d}"
        )
        part.object[SLIP_CASTING_VASE_BASE_KEY] = True
        part.object[SLIP_CASTING_VASE_BASE_ROLE_KEY] = "MALE"
        assign_moldbox_material(part.object)
        part.hide_during_ui_breathe = False
        _set_reference_hidden(part, False)
        part.object.display_type = "SOLID"
        part.object.select_set(False)
        part.object.hide_select = False
    for part_index, part in enumerate(female_bases):
        part.name = (
            SLIP_CASTING_FEMALE_BASE_NAME
            if part_index == 0
            else f"{SLIP_CASTING_FEMALE_BASE_NAME}_{part_index + 1:03d}"
        )
        part.object[SLIP_CASTING_VASE_BASE_KEY] = True
        part.object[SLIP_CASTING_FEMALE_BASE_KEY] = True
        part.object[SLIP_CASTING_VASE_BASE_ROLE_KEY] = "FEMALE"
        assign_moldbox_material(part.object)
        part.hide_during_ui_breathe = False
        _set_reference_hidden(part, False)
        part.object.display_type = "SOLID"
        part.object.hide_select = False

    pair_slip_casting_bases(vase_bases, female_bases)
    female_count = len(female_bases)
    for part in female_bases:
        part.object[SLIP_CASTING_PENDING_MASTER_UNION_KEY] = True
    for part in (*vase_bases, *female_bases):
        part.shade_flat()
        part.object.select_set(False)
        assign_moldbox_material(part.object)
        part.hide_during_ui_breathe = False
        _set_reference_hidden(part, False)
        part.object.display_type = "SOLID"
        part.object.hide_select = False
    force_viewport_redraw(context)
    logger.info(
        "Finished reversed funnel-style Slip Casting vase base: "
        "male_parts=%d female_parts=%d split_planes=%d pin_z=%.3f "
        "mold_thickness=%.3f",
        len(vase_bases),
        female_count,
        len(split_planes),
        pin_z,
        mold_thickness,
    )
    return vase_bases, female_bases
