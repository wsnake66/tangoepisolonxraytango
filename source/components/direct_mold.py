import importlib
import json
import logging
import math
import re

import bpy  # type: ignore
import mathutils  # type: ignore

from ..background_worker import BackgroundTaskSequence, finish_task_sync
from ..constants import BOX_THICKNESS, CLAMP_DEPTH, ENABLE_CUSTOM_FACE_CORE
from ..environment import get_server_base_url
from ..materials import (
    assign_foundation_material,
    assign_funnels_material,
    assign_generated_material,
    assign_moldbox_material,
    assign_skin_core_base_material,
)
from ..modifiers import (
    build_voxel_modifier,
    diff_no_material_transfer_mod,
    union_mod,
)
from ..mold_types import resolve_direct_mold_opening
from ..object import BMeshObj, DIRECT_BOOLEAN_RETRY_SCENE_KEY, Object
from ..patron_lifecycle import create_simplified_reference_for_operation
from ..split_specs import (
    representative_split_specs,
    split_spec_point_normal,
    split_specs_query_values,
)
from ..progress import breathe_viewport
from ..primitives import create_cube_primitive
from ..voxel_size import (
    get_box_voxel_size,
    get_master_voxel_size,
    get_undercuts_voxel_size,
)
from .box import iter_build_box_operator_steps
from .base import WEIGHT_TEXT_EXTENSION_PADDING, _add_weight_text_extension
from .clear_undercuts import begin_clear_undercuts, bottom_reference_plane
from .channels_deposit import remesh_channel_casting_grip
from .custom_face_core import (
    CUSTOM_FACE_CORE_BASES_DIRTY_MARKER,
    CUSTOM_FACE_CORE_MARKER,
    begin_create_custom_face_core,
    create_custom_face_core,
    custom_face_dimensions,
    center_skin_master_origin,
    validate_custom_face_head_clearance,
)
from .direct_split_planes import (
    DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY,
    SKIN_MASTER_HALF_PREVIEW_MODIFIER_NAME,
    direct_split_plane_specs,
    foundation_reference_guide_active,
    foundation_reference_target_object,
    foundation_threshold_angle_degrees,
    remove_direct_split_planes,
    remove_skin_base_reference_guide,
    set_keep_silicone_split_planes_after_build,
    skin_base_reference_guide_object,
    stored_silicone_split_plane_specs,
    sync_direct_split_planes_with_scene,
)
from .direct_split_execution import (
    begin_split_object_by_direct_plane_specs,
    split_object_by_direct_plane_specs,
)
from .geometry_adapter import plan_direct_barrier_routes
from .filler_v2 import prepare_abstracted_target
from .manual_booleans import (
    apply_clamp_booleans_after_server_import,
    subtract_base_substracter_from_box,
)
from .server import import_server_response, request_server, request_server_async
from .silicone_mold import MOLD_LABEL_TEXT_SIZE
from ..operator_access import is_lite_tier
from .watermark_mesh_server import (
    request_watermark_mesh,
    request_watermark_mesh_async,
)
from .standalone_inner_cavity_finish import create_core_cavity_exclusion
from .watermark_payload import SKIN_CASTING_VOLUME_ML_KEY, calculate_casting_volume
from .mesh_envelope import begin_mesh_envelope

logger = logging.getLogger(__name__)

DIRECT_MOLD_BOX_QUALITY = "MID"
DIRECT_CHANNELS_DEPOSIT_PATH = "/dirtect-channels-deposit/"
DIRECT_CONFIRM_MOLD_PATH = "/confirm-direct-mold/"
EXTRA_DIRECT_CONFIRM_MOLD_PATH = "/extra-confirm-direct-mold/"
SKIN_CORE_BASE_PATH = "/skin-core-bases/"
SKIN_CORE_ATTACHMENT_PATH = "/skin-core-attachment/"
BARRIER_TOLERANCE = 0.25
DIRECT_BOX_BOTTOM_CUT_OFFSET = 0.5
DIRECT_FUNNELER_OFFSET = 1.0
DIRECT_OPEN_BASE_FUNNELER_REFERENCE_HEIGHT = 90.0
DIRECT_TOP_FUNNEL_BOTTOM_EXTENSION = 4.0
DIRECT_SKIN_BARRIER_BOTTOM_OFFSET = 5.0
DIRECT_MASTER_FUNNEL_TOP_EXTENSION = 1.0
DIRECT_TOP_FUNNEL_OPENING = "top_funnel"
DIRECT_SKIN_MOLD_TYPE = "DIRECT_MOLD_SKIN"
SKIN_MASTER_HALF_PREVIEW_CUTTER_NAME = "skin_master_half_preview_cutter"
SKIN_MASTER_HALF_PREVIEW_CUTTER_MARKER = "moldboxer_skin_half_preview_cutter"
CUSTOM_FACE_MASTER_TRANSPARENT_MARKER = "moldboxer_custom_face_master_transparent"
CUSTOM_FACE_MASTER_ORIGINAL_MATERIALS_KEY = (
    "moldboxer_custom_face_master_original_materials"
)
CUSTOM_FACE_MASTER_PREVIEW_MATERIALS_KEY = (
    "moldboxer_custom_face_master_preview_materials"
)
CUSTOM_FACE_MASTER_ORIGINAL_COLOR_KEY = "moldboxer_custom_face_master_original_color"
CUSTOM_FACE_MASTER_ORIGINAL_DISPLAY_TYPE_KEY = (
    "moldboxer_custom_face_master_original_display_type"
)
CUSTOM_FACE_MASTER_ORIGINAL_TRANSPARENCY_KEY = (
    "moldboxer_custom_face_master_original_transparency"
)
CUSTOM_FACE_MASTER_PREVIEW_ALPHA = 0.28
SKIN_CORE_BASE_LEGACY_NAME = "skin_core_base_undercuts"
SKIN_CORE_BASE_NAME_PREFIX = "skin_core_base"
SKIN_CORE_BASE_MARKER = "moldboxer_skin_core_base"
SKIN_CORE_BASE_LEGACY_MARKER = "moldboxer_skin_core_base_undercuts"
SKIN_CORE_BASE_FACE_DEBUG_PREFIX = "skin_core_base_faces"
SKIN_CORE_BASE_FACE_DEBUG_MARKER = "moldboxer_skin_core_base_faces_debug"
SKIN_CORE_BASE_FACE_DEBUG_LEGACY_MARKER = (
    "moldboxer_skin_core_undercut_faces_debug"
)
SKIN_CORE_BASE_REFERENCE_POINT_KEY = "moldboxer_skin_core_base_reference_point"
SKIN_CORE_BASE_REFERENCE_NORMAL_KEY = "moldboxer_skin_core_base_reference_normal"
SKIN_CORE_VOXEL_SIZE_KEY = "moldboxer_skin_core_voxel_size"
SKIN_CORE_CONFIRMED_MARKER = "moldboxer_skin_core_confirmed"
FOUNDATION_APPLIED_MARKER = "moldboxer_foundation_applied"
SKIN_CORE_WRAPPER_NAME = "skin_wrap"
SKIN_CORE_WRAPPER_MARKER = "moldboxer_skin_core_wrapper"
SKIN_INLET_NAME = "skin_inlet"
SKIN_INLET_MARKER = "moldboxer_skin_inlet"
SKIN_INLET_SOURCE_NAME = "skin_inlet_source"
SKIN_INLET_SOURCE_MARKER = "moldboxer_skin_inlet_source"
SKIN_INLET_SOURCE_DEPTH_MARKER = "moldboxer_skin_inlet_source_depth"
SKIN_INLET_SOURCE_CENTER_Y_MARKER = "moldboxer_skin_inlet_source_center_y"
SKIN_INLET_SECTION_HEIGHT = 10.0
SKIN_INLET_Z_OFFSET = -9.5
SKIN_BOX_WRAP_TARGET_NAME = "skin_box_wrap_target"
SKIN_BOX_PATRON_DUPLICATE_NAME = "skin_box_patron_duplicate"
SKIN_BOX_WRAPPER_DUPLICATE_NAME = "skin_box_wrapper_duplicate"
SKIN_BOX_INLET_DUPLICATE_NAME = "skin_box_inlet_duplicate"
SKIN_CORE_WRAPPER_VOXEL_SIZE = 1.0
SKIN_CORE_ATTACHMENT_READY_MARKER = "moldboxer_skin_core_attachment_ready"
SKIN_CORE_ATTACHMENT_BOX_MAX_Z_MARKER = (
    "moldboxer_skin_core_attachment_box_max_z"
)
SKIN_CORE_ATTACHMENT_TYPE_MARKER = "moldboxer_skin_core_attachment_type"
SKIN_CORE_FINAL_BOX_MIN_Z_MARKER = "moldboxer_skin_core_final_box_min_z"
SKIN_CORE_ATTACHMENT_CENTER_Y_MARKER = (
    "moldboxer_skin_core_attachment_center_y"
)
SKIN_CORE_ATTACHMENT_DEPTH_MARKER = "moldboxer_skin_core_attachment_depth"
SKIN_CORE_HOLLOWED_MARKER = "moldboxer_skin_core_hollowed"
SKIN_CORE_NAME = "skin_core"
SKIN_CORE_ATTACHER_NAME = "skin_core_attacher"
SKIN_CORE_ATTACH_SOCKET_NAME = "skin_core_attach_socket"
SKIN_CORE_SOCKET_CUTTER_NAME = "skin_core_socket_cutter_to_sub"
SKIN_CORE_PIN_NAME = "skin_core_pin"
SKIN_CORE_PIN_MARKER = "moldboxer_skin_core_pin"
SKIN_CORE_HOLLOW_QUALITY = "DRAFT"
SKIN_CORE_PIN_DIAMETER = 4.0
SKIN_CORE_PIN_CLEARANCE_DIAMETER_EXTRA = 0.5
SKIN_CORE_PIN_DEPTH_OVERTRAVEL = 4.0
SKIN_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR = 2.0
SKIN_CORE_PIN_BOX_CUTTER_WIDTH = 20.0
SKIN_CORE_PIN_BOX_CUTTER_HEIGHT = 10.0
SKIN_CORE_CONFIRM_SMOOTH_FACTOR = 0.75
SKIN_CORE_CONFIRM_SMOOTH_REPEATS = 15
DIRECT_TOP_FUNNEL_NAME_MARKERS = ("funnel", "funneler", "deposit")
DIRECT_TOP_FUNNEL_UNDERCUT_OVERTRAVEL = 1.5
DIRECT_UNDERCUT_PATHS_OBJECT_KEY = "_moldboxer_direct_undercut_paths"
DIRECT_FUNNEL_REMESH_TOP_EXTENSION = 5.0
DIRECT_Z_TRIM_TOLERANCE = 1e-6
DIRECT_PATRON_BACKUP_NAME = "backup"
DIRECT_VOLUME_EXTENSION_HEIGHT = 5.0
DIRECT_VOLUME_EXTENSION_OVERLAP_FACTOR = 0.5
DIRECT_VOLUME_EXTENSION_OVERLAP_EPSILON = 1e-6
DIRECT_VOLUME_EXTENSION_PLACEMENT_TOLERANCE = 1e-4
DIRECT_BOX_COMPONENT_NAME_MARKERS = (
    "channel",
    "funnel",
    "funneler",
    "casting_feet",
    "casting feet",
    "deposit",
)
DIRECT_SHARED_SCENE_SETTINGS = (
    "base_thickness",
    "base_type",
    "box_gap",
    "box_quality",
    "box_thickness",
    "build_from_sphere",
    "casting_feet",
    "casting_feet_height",
    "casting_feet_size_factor",
    "casting_grip",
    "casting_grip_depth",
    "casting_grip_width",
    "channel_adjustment",
    "channel_back_larger",
    "channel_depth",
    "channel_width",
    "channels",
    "channels_contact_scale",
    "channels_type",
    "clamp_depth",
    "clamp_width",
    "clear_extraction",
    "funneler",
    "funneler_offset",
    "funneler_ref_height",
    "funneler_size_factor",
    "horizontal_channels_count",
    "n_splits_z",
    "pro_inner_cavity",
    "pro_two_part_silicone",
    "pro_watermark",
    "wing_width",
)
DIRECT_SHARED_ENUM_DEFAULTS = {
    "base_type": "classic",
    "box_quality": "MID",
    "channel_adjustment": "adjusted",
    "channels_type": "optimized",
    "funneler": "optimized",
}
_DIRECT_SYSTEM_OBJECT_RE = re.compile(
    r"^(?P<kind>"
    r"clamp_optimized|"
    r"clamp_stepper|"
    r"clamp_stepper_substracter|"
    r"clamp_pin_male|"
    r"clamp_pin_female|"
    r"barrier_male|"
    r"barrier_female|"
    r"barrier_vertical_reinforcement|"
    r"split_base"
    r")_(?P<system>[xyz]\d+)(?:[._-].*)?$",
    re.IGNORECASE,
)
_DIRECT_SYSTEM_SORT_AXIS = {"x": 0, "y": 1, "z": 2}


def _normalized_direct_split_plane_specs(
    split_plane_specs: list[list[list[float]]],
) -> list[list[list[float]]]:
    return representative_split_specs(split_plane_specs)


def _direct_split_plane_specs_match(
    first: list[list[list[float]]],
    second: list[list[list[float]]],
    tolerance: float = 1e-6,
) -> bool:
    if len(first) != len(second):
        return False
    try:
        return all(
            abs(float(first_value) - float(second_value)) <= tolerance
            for first_plane, second_plane in zip(first, second)
            for first_vector, second_vector in zip(first_plane, second_plane)
            for first_value, second_value in zip(first_vector, second_vector)
        )
    except (TypeError, ValueError):
        return False


def store_direct_undercut_paths(
    target_object: bpy.types.Object,
    split_plane_specs: list[list[list[float]]],
    selected_paths: dict,
    *,
    easy_extraction: bool,
    precise_cost: bool,
    restrict_bottom_extraction: bool,
) -> None:
    """Persist a Direct master's frozen paths for its later top funnels."""
    if not selected_paths:
        if DIRECT_UNDERCUT_PATHS_OBJECT_KEY in target_object:
            del target_object[DIRECT_UNDERCUT_PATHS_OBJECT_KEY]
        return

    payload = {
        "version": 4,
        "easy_extraction": bool(easy_extraction),
        "precise_cost": bool(precise_cost),
        "restrict_bottom_extraction": bool(restrict_bottom_extraction),
        "split_plane_specs": _normalized_direct_split_plane_specs(
            split_plane_specs
        ),
        "paths": [
            {
                "section": [int(side) for side in section],
                "plane_index": int(path["plane_index"]),
                "direction": [float(value) for value in path["direction"]],
                "projection_plane_indices": [
                    int(index) for index in path["projection_plane_indices"]
                ],
                "path_sections": [
                    [int(side) for side in path_section]
                    for path_section in path["path_sections"]
                ],
                "order": int(path["order"]),
            }
            for section, path in selected_paths.items()
        ],
    }
    target_object[DIRECT_UNDERCUT_PATHS_OBJECT_KEY] = json.dumps(
        payload,
        separators=(",", ":"),
    )


def load_direct_undercut_paths(
    target_object: bpy.types.Object,
    split_plane_specs: list[list[list[float]]],
    *,
    easy_extraction: bool,
    precise_cost: bool,
    restrict_bottom_extraction: bool,
) -> dict:
    """Load paths only when their planes and direction policy still match."""
    raw_payload = target_object.get(DIRECT_UNDERCUT_PATHS_OBJECT_KEY)
    if not isinstance(raw_payload, str) or not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
        if payload.get("version") != 4:
            return {}
        if (
            payload.get("easy_extraction") != bool(easy_extraction)
            or payload.get("precise_cost") != bool(precise_cost)
            or payload.get("restrict_bottom_extraction")
            != bool(restrict_bottom_extraction)
        ):
            logger.info(
                "Ignoring stored Direct undercut paths because the extraction "
                "policy changed"
            )
            return {}
        stored_plane_specs = payload.get("split_plane_specs")
        if (
            not isinstance(stored_plane_specs, list)
            or not _direct_split_plane_specs_match(
                stored_plane_specs,
                _normalized_direct_split_plane_specs(split_plane_specs),
            )
        ):
            logger.warning(
                "Ignoring stored Direct undercut paths because the split planes "
                "changed"
            )
            return {}
        paths = {}
        for record in payload["paths"]:
            section = tuple(int(side) for side in record["section"])
            paths[section] = {
                "plane_index": int(record["plane_index"]),
                "direction": tuple(float(value) for value in record["direction"]),
                "projection_plane_indices": tuple(
                    int(index) for index in record["projection_plane_indices"]
                ),
                "path_sections": tuple(
                    tuple(int(side) for side in path_section)
                    for path_section in record["path_sections"]
                ),
                "order": int(record["order"]),
            }
        return paths
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring malformed stored Direct undercut paths")
        return {}


def _plan_and_store_direct_undercut_path_steps(
    master: Object,
    split_plane_specs: list[list[list[float]]],
    *,
    restrict_bottom_extraction: bool,
) -> dict:
    """Plan master section directions without modifying the Direct master."""
    scene = bpy.context.scene
    extraction_mode = getattr(
        scene,
        "clear_undercuts_mode",
        "EASY_EXTRACTION",
    )
    easy_extraction = extraction_mode == "EASY_EXTRACTION"
    precise_cost = extraction_mode == "PRECISE"
    selected_paths = {}
    yield begin_clear_undercuts(
        target_object=master,
        bidirectional=True,
        voxel_size=get_undercuts_voxel_size(scene.undercuts_quality, master),
        target_retry_voxel_size=get_master_voxel_size(
            scene.master_quality,
            master,
        ),
        target_point=mathutils.Vector((0.0, 0.0, 0.0)),
        plane_direction=mathutils.Vector((1.0, 0.0, 0.0)),
        progress_callback=lambda _label: breathe_viewport(bpy.context),
        ui_refresh_callback=lambda: breathe_viewport(bpy.context),
        split_plane_specs=split_plane_specs,
        boundary_plane_specs=[bottom_reference_plane(master)],
        easy_extraction=easy_extraction,
        precise_cost=precise_cost,
        restrict_bottom_extraction=restrict_bottom_extraction,
        split_plane_overtravel_override=0.0,
        selected_paths_out=selected_paths,
        display_extraction_directions=False,
        planning_only=True,
    )
    if not selected_paths:
        raise RuntimeError(
            "Could not calculate Direct master extraction paths for top funnels"
        )
    store_direct_undercut_paths(
        master.object,
        split_plane_specs,
        selected_paths,
        easy_extraction=easy_extraction,
        precise_cost=precise_cost,
        restrict_bottom_extraction=restrict_bottom_extraction,
    )
    logger.info(
        "Calculated and stored %d Direct master extraction path(s) for top "
        "funnels without modifying the master",
        len(selected_paths),
    )
    return selected_paths


def _begin_plan_and_store_direct_undercut_paths(
    master: Object,
    split_plane_specs: list[list[list[float]]],
    *,
    restrict_bottom_extraction: bool,
):
    sequence = BackgroundTaskSequence(
        _plan_and_store_direct_undercut_path_steps(
            master,
            split_plane_specs,
            restrict_bottom_extraction=restrict_bottom_extraction,
        )
    )
    sequence.redraw_interval = 0.1
    return sequence


def _plan_and_store_direct_undercut_paths(
    master: Object,
    split_plane_specs: list[list[list[float]]],
    *,
    restrict_bottom_extraction: bool,
) -> dict:
    return finish_task_sync(
        _begin_plan_and_store_direct_undercut_paths(
            master,
            split_plane_specs,
            restrict_bottom_extraction=restrict_bottom_extraction,
        )
    )


def ensure_direct_patron_backup():
    """Keep one untouched, hidden copy of the Direct mold patron."""
    backup = bpy.data.objects.get(DIRECT_PATRON_BACKUP_NAME)
    if backup is None:
        patron = bpy.data.objects.get("patron")
        if patron is None or patron.type != "MESH":
            return None

        backup = patron.copy()
        backup.data = patron.data.copy()
        backup.name = DIRECT_PATRON_BACKUP_NAME
        backup.data.name = f"{DIRECT_PATRON_BACKUP_NAME}_mesh"
        for collection in patron.users_collection:
            collection.objects.link(backup)

    backup.hide_select = True
    backup.hide_set(True)
    backup.hide_viewport = True
    backup.hide_render = True
    backup.select_set(False)
    return backup


def _select_direct_patron_for_box_generation() -> Object:
    """Restore the active patron after deleting the selected split-plane UI."""
    patron = bpy.data.objects.get("patron")
    if patron is None or patron.type != "MESH":
        raise RuntimeError("Automatic Mold requires a patron mesh")
    selected_patron = Object(patron)
    selected_patron.select()
    return selected_patron


def _scene_settings_snapshot(scene) -> dict[str, object]:
    return {
        name: getattr(scene, name)
        for name in DIRECT_SHARED_SCENE_SETTINGS
        if hasattr(scene, name)
    }


def _set_scene_settings_to_defaults(scene) -> None:
    for name in DIRECT_SHARED_SCENE_SETTINGS:
        if name in DIRECT_SHARED_ENUM_DEFAULTS:
            setattr(scene, name, DIRECT_SHARED_ENUM_DEFAULTS[name])
            continue
        rna_property = scene.bl_rna.properties.get(name)
        if rna_property is not None and hasattr(rna_property, "default"):
            setattr(scene, name, rna_property.default)


def _restore_scene_settings(scene, settings: dict[str, object]) -> None:
    for name, value in settings.items():
        setattr(scene, name, value)


def _direct_clamps() -> list[Object]:
    excluded_name_parts = (
        "pin",
        "screw",
        "stepper",
        "substracter",
        "cutter",
        "locker",
    )
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith("clamp")
            and not any(part in obj.name.lower() for part in excluded_name_parts)
        ),
        key=lambda obj: obj.name.lower(),
    )


def _direct_system_objects() -> dict[str, dict[str, list[Object]]]:
    systems: dict[str, dict[str, list[Object]]] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        match = _DIRECT_SYSTEM_OBJECT_RE.match(obj.name.lower())
        if match is None:
            continue
        system_name = match.group("system")
        kind = match.group("kind")
        systems.setdefault(system_name, {}).setdefault(kind, []).append(Object(obj))

    for objects_by_kind in systems.values():
        for objects in objects_by_kind.values():
            objects.sort(key=lambda wrapped_obj: wrapped_obj.name.lower())
    return systems


def _direct_screw_objects(system_name: str) -> list[Object]:
    normalized_system = system_name.lower()
    screws = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.lower().startswith("screw_"):
            continue
        normalized_name = obj.name.lower().split(".", 1)[0]
        if not normalized_name.endswith(f"_{normalized_system}"):
            continue
        screws.append(Object(obj))
    return sorted(screws, key=lambda obj: obj.name.lower())


def _direct_system_sort_key(system_name: str) -> tuple[int, int, str]:
    match = re.match(r"^([xyz])(\d+)$", system_name.lower())
    if match is None:
        return (99, 0, system_name)
    return (
        _DIRECT_SYSTEM_SORT_AXIS.get(match.group(1), 99),
        int(match.group(2)),
        system_name,
    )


def _dominant_plane_axis(plane_spec: list[list[float]]) -> str:
    _point, direction = split_spec_point_normal(plane_spec)
    axis_idx = max(range(3), key=lambda idx: abs(float(direction[idx])))
    return ("x", "y", "z")[axis_idx]


def _dominant_plane_axis_coordinate(
    plane_spec: list[list[float]],
) -> float:
    """Return where a plane intersects its dominant world axis."""
    point, direction = split_spec_point_normal(plane_spec)
    axis_idx = max(range(3), key=lambda idx: abs(float(direction[idx])))
    axis_direction = float(direction[axis_idx])
    if abs(axis_direction) <= 1e-9:
        raise ValueError("Direct split plane direction cannot be zero")
    return sum(
        float(direction[idx]) * float(point[idx]) for idx in range(3)
    ) / axis_direction


def _direct_plane_system_names(
    plane_specs: list[list[list[float]]],
) -> list[str]:
    grouped_planes: dict[str, list[tuple[int, float]]] = {"x": [], "y": [], "z": []}
    for plane_index, plane_spec in enumerate(plane_specs):
        axis = _dominant_plane_axis(plane_spec)
        coordinate = _dominant_plane_axis_coordinate(plane_spec)
        grouped_planes[axis].append((plane_index, coordinate))

    system_names = [""] * len(plane_specs)
    for axis, indexed_coords in grouped_planes.items():
        for system_index, (plane_index, _coord) in enumerate(
            sorted(indexed_coords, key=lambda item: (item[1], item[0])),
            start=1,
        ):
            system_names[plane_index] = f"{axis}{system_index}"
    return system_names


def _first_system_object(
    system: dict[str, list[Object]],
    kind: str,
) -> Object | None:
    objects = system.get(kind) or []
    return objects[0] if objects else None


def _remove_system_objects(objects: list[Object]) -> None:
    for obj in objects:
        if _object_exists(obj):
            obj.remove()


def _redraw_direct_boolean_result(*visible_operands: Object) -> None:
    """Draw a completed direct-mold Boolean without its operands obscuring it."""
    visibility_states = []
    for operand in visible_operands:
        if not _object_exists(operand):
            continue
        raw_operand = operand.object
        visibility_states.append(
            (
                raw_operand,
                raw_operand.hide_get(),
                bool(getattr(raw_operand, "hide_viewport", False)),
                bool(getattr(raw_operand, "hide_render", False)),
            )
        )
        raw_operand.hide_set(True)
        raw_operand.hide_viewport = True
        raw_operand.hide_render = True

    try:
        breathe_viewport()
    finally:
        for (
            raw_operand,
            was_hidden,
            was_hide_viewport,
            was_hide_render,
        ) in visibility_states:
            try:
                raw_operand.hide_set(was_hidden)
                raw_operand.hide_viewport = was_hide_viewport
                raw_operand.hide_render = was_hide_render
            except ReferenceError:
                pass


def _remove_boolean_operand_and_redraw(operand: Object) -> None:
    _remove_system_objects([operand])
    breathe_viewport()


def _object_exists(obj: Object) -> bool:
    try:
        return obj.object.name in bpy.data.objects
    except ReferenceError:
        return False


def _plane_point_and_normal(
    plane_spec: list[list[float]],
) -> tuple[mathutils.Vector, mathutils.Vector]:
    point, normal = split_spec_point_normal(plane_spec)
    plane_point = mathutils.Vector(point)
    plane_normal = mathutils.Vector(normal)
    if plane_normal.length == 0:
        raise ValueError("Direct split plane direction cannot be zero")
    plane_normal.normalize()
    return plane_point, plane_normal


def _split_direct_barrier_into_grid(
    barrier: Object,
    split_plane_specs: list[list[list[float]]],
    *,
    skipped_plane_index: int | None = None,
) -> list[Object]:
    barrier_grid = barrier.duplicate("_direct_barrier_grid")
    barrier_pieces = [barrier_grid]
    barrier_split_plane_specs = [
        plane_spec
        for plane_index, plane_spec in enumerate(split_plane_specs)
        if plane_index != skipped_plane_index
    ]
    barrier_split_plane_indices = [
        plane_index
        for plane_index in range(len(split_plane_specs))
        if plane_index != skipped_plane_index
    ]
    try:
        barrier_pieces = split_object_by_direct_plane_specs(
            barrier_grid,
            barrier_split_plane_specs,
            preserve_isolated_meshes=True,
            section_plane_indices=barrier_split_plane_indices,
            section_plane_count=len(split_plane_specs),
        )
        return barrier_pieces
    except Exception:
        _remove_system_objects(
            [piece for piece in barrier_pieces if _object_exists(piece)]
        )
        raise


def _direct_system_plane_specs(
    split_plane_specs: list[list[list[float]]],
) -> dict[str, list[list[float]]]:
    plane_system_names = _direct_plane_system_names(split_plane_specs)
    return {
        system_name: split_plane_specs[plane_index]
        for plane_index, system_name in enumerate(plane_system_names)
        if system_name
    }


def _direct_system_plane_indices(
    split_plane_specs: list[list[list[float]]],
) -> dict[str, int]:
    plane_system_names = _direct_plane_system_names(split_plane_specs)
    return {
        system_name: plane_index
        for plane_index, system_name in enumerate(plane_system_names)
        if system_name
    }


def _cut_direct_object_to_box_z_bounds(
    obj: Object,
    *,
    box_min_z: float,
    box_max_z: float,
    cut_below: bool,
    cut_above: bool,
) -> None:
    if cut_below and obj.min_z < box_min_z - DIRECT_Z_TRIM_TOLERANCE:
        obj.cut_plane(
            mathutils.Vector((0.0, 0.0, -1.0)),
            mathutils.Vector((0.0, 0.0, box_min_z)),
        )
    if cut_above and obj.max_z > box_max_z + DIRECT_Z_TRIM_TOLERANCE:
        obj.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector((0.0, 0.0, box_max_z)),
        )


def trim_nonvertical_direct_clamp_systems_to_box(
    split_plane_specs: list[list[list[float]]],
) -> None:
    """Trim angled clamp systems where their clamps exceed the box in Z."""
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("No box object found")

    box = Object(box_raw)
    box_min_z = box.min_z
    box_max_z = box.max_z
    systems = _direct_system_objects()
    system_plane_specs = _direct_system_plane_specs(split_plane_specs)

    for system_name in sorted(systems, key=_direct_system_sort_key):
        plane_spec = system_plane_specs.get(system_name)
        if plane_spec is None:
            continue
        _plane_point, plane_normal = _plane_point_and_normal(plane_spec)
        if abs(plane_normal.z) <= DIRECT_Z_TRIM_TOLERANCE:
            continue

        system = systems[system_name]
        clamps = list(system.get("clamp_optimized") or [])
        if not clamps:
            continue
        cut_below = any(
            clamp.min_z < box_min_z - DIRECT_Z_TRIM_TOLERANCE for clamp in clamps
        )
        cut_above = any(
            clamp.max_z > box_max_z + DIRECT_Z_TRIM_TOLERANCE for clamp in clamps
        )
        if not cut_below and not cut_above:
            continue

        trim_objects = [
            *clamps,
            *(system.get("barrier_vertical_reinforcement") or []),
            *(system.get("barrier_male") or []),
            *(system.get("clamp_pin_male") or []),
        ]
        for obj in trim_objects:
            _cut_direct_object_to_box_z_bounds(
                obj,
                box_min_z=box_min_z,
                box_max_z=box_max_z,
                cut_below=cut_below,
                cut_above=cut_above,
            )

        # Slip Casting split bases continue below the box only as far as the
        # master-base floor. Clip any raw angled-clamp overrun to that exact Z.
        split_bases = list(system.get("split_base") or [])
        base_raw = bpy.data.objects.get("base")
        split_base_bottom_z = (
            Object(base_raw).min_z
            if base_raw is not None and base_raw.type == "MESH"
            else box_min_z
        )
        for split_base in split_bases:
            _cut_direct_object_to_box_z_bounds(
                split_base,
                box_min_z=split_base_bottom_z,
                box_max_z=box_max_z,
                cut_below=True,
                cut_above=cut_above,
            )

        logger.debug(
            "Trimmed direct clamp system %s to box Z bounds %.3f..%.3f "
            "(below=%s, above=%s, objects=%d)",
            system_name,
            box_min_z,
            box_max_z,
            cut_below,
            cut_above,
            len(trim_objects) + len(split_bases),
        )


def _apply_direct_clamp_system_booleans(
    system_name: str,
    system: dict[str, list[Object]],
    *,
    screw_mode: bool = False,
) -> None:
    clamp = _first_system_object(system, "clamp_optimized")
    if clamp is None:
        return

    stepper = _first_system_object(system, "clamp_stepper")
    stepper_substracter = _first_system_object(system, "clamp_stepper_substracter")
    reinforcements = list(system.get("barrier_vertical_reinforcement") or [])
    screw_cutters = _direct_screw_objects(system_name) if screw_mode else []

    try:
        if stepper is not None:
            if stepper_substracter is not None:
                stepper -= stepper_substracter
                if stepper.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
                _remove_boolean_operand_and_redraw(stepper_substracter)
                stepper_substracter = None
            clamp -= stepper
            if clamp.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
            _remove_boolean_operand_and_redraw(stepper)
            stepper = None

        for screw_cutter in screw_cutters:
            clamp -= screw_cutter
            if clamp.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
            _remove_boolean_operand_and_redraw(screw_cutter)
        screw_cutters = []

        for reinforcement in reinforcements:
            assign_generated_material(reinforcement.object)
            clamp.add_with_material_transfer(reinforcement)
            if clamp.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
            _remove_boolean_operand_and_redraw(reinforcement)
        reinforcements = []
    finally:
        if stepper_substracter is not None:
            _remove_system_objects([stepper_substracter])
        if stepper is not None:
            _remove_system_objects([stepper])
        _remove_system_objects(screw_cutters)
        _remove_system_objects(reinforcements)

    logger.debug("Applied direct clamp system booleans for %s", system_name)


def apply_direct_clamp_booleans_after_server_import(
    screw_mode: bool = False,
) -> None:
    systems = _direct_system_objects()
    has_direct_clamp_systems = any(
        bool(system.get("clamp_optimized")) for system in systems.values()
    )
    if not has_direct_clamp_systems:
        apply_clamp_booleans_after_server_import(screw_mode=screw_mode)
        return

    try:
        for system_name in sorted(systems, key=_direct_system_sort_key):
            _apply_direct_clamp_system_booleans(
                system_name,
                systems[system_name],
                screw_mode=screw_mode,
            )
    finally:
        if screw_mode:
            for system_name in systems:
                _remove_system_objects(_direct_screw_objects(system_name))


def _boolean_add(target: Object, operand: Object) -> None:
    target += operand
    if target.has_empty_boolean:
        raise Exception("Boolean modifier without target failed")


def _remove_direct_split_barriers(
    systems: dict[str, dict[str, list[Object]]],
) -> None:
    for system in systems.values():
        _remove_system_objects(
            [
                *(system.get("barrier_male") or []),
                *(system.get("barrier_female") or []),
                *(system.get("clamp_pin_male") or []),
                *(system.get("clamp_pin_female") or []),
            ]
        )


def _direct_system_lock_objects(
    system: dict[str, list[Object]],
    kind: str,
) -> list[Object]:
    return [
        *(system.get(f"barrier_{kind}") or []),
        *(system.get(f"clamp_pin_{kind}") or []),
    ]


def apply_direct_split_barrier_grid(
    parts: list[Object],
    split_plane_specs: list[list[list[float]]],
    mirrored_parts: list[Object] | None = None,
    *,
    male_on_top_for_horizontal: bool = False,
) -> None:
    """Apply male barrier grid pieces and whole female barrier cutters by side."""
    if not parts or not split_plane_specs:
        return

    systems = _direct_system_objects()
    system_plane_indices = _direct_system_plane_indices(split_plane_specs)
    mirrored_parts = list(mirrored_parts or [])
    male_pieces: list[Object] = []
    male_plane_indices: list[int] = []
    female_barriers: list[Object] = []
    female_plane_indices: list[int] = []
    male_assignments: list[tuple[Object, Object, Object | None]] = []
    female_assignments: list[tuple[Object, Object]] = []

    try:
        for system_name in sorted(systems, key=_direct_system_sort_key):
            skipped_plane_index = system_plane_indices.get(system_name)
            if skipped_plane_index is None:
                continue

            system = systems[system_name]
            for barrier in _direct_system_lock_objects(system, "male"):
                split_pieces = _split_direct_barrier_into_grid(
                    barrier,
                    split_plane_specs,
                    skipped_plane_index=skipped_plane_index,
                )
                male_pieces.extend(split_pieces)
                male_plane_indices.extend(
                    [skipped_plane_index] * len(split_pieces)
                )

            for barrier in _direct_system_lock_objects(system, "female"):
                female_barriers.append(barrier)
                female_plane_indices.append(skipped_plane_index)

        route_plan = plan_direct_barrier_routes(
            plane_specs=split_plane_specs,
            parts=parts,
            mirrored_parts=mirrored_parts,
            male_pieces=male_pieces,
            male_plane_indices=male_plane_indices,
            female_barriers=female_barriers,
            female_plane_indices=female_plane_indices,
            male_on_top_for_horizontal=male_on_top_for_horizontal,
        )
        unassigned_pieces = []
        for male_index, male_piece in enumerate(male_pieces):
            target_index = int(route_plan.male_targets[male_index])
            if target_index < 0:
                unassigned_pieces.append(male_piece)
                continue
            mirrored_index = int(route_plan.mirrored_targets[male_index])
            mirrored_target = (
                mirrored_parts[mirrored_index]
                if mirrored_index >= 0
                else None
            )
            male_assignments.append(
                (parts[target_index], male_piece, mirrored_target)
            )
        _remove_system_objects(unassigned_pieces)

        combined_parts = [*parts, *mirrored_parts]
        for female_index, female_barrier in enumerate(female_barriers):
            start = int(route_plan.female_offsets[female_index])
            stop = int(route_plan.female_offsets[female_index + 1])
            for target_index in route_plan.female_targets[start:stop]:
                female_assignments.append(
                    (combined_parts[int(target_index)], female_barrier)
                )

        for target_part, male_piece, mirrored_target in male_assignments:
            target_part.add_with_material_transfer_and_geometry_fallback(male_piece)
            if mirrored_target is not None:
                mirrored_target.add_with_material_transfer_and_geometry_fallback(
                    male_piece
                )
            _remove_boolean_operand_and_redraw(male_piece)

        for target_part, female_piece in female_assignments:
            target_part.apply_boolean_modifier_with_geometry_fallback(
                diff_no_material_transfer_mod,
                female_piece,
            )
            _redraw_direct_boolean_result(female_piece)

        logger.debug(
            "Applied direct split barriers: male_grid_pieces=%d "
            "female_whole_subtractions=%d",
            len(male_assignments),
            len(female_assignments),
        )
    finally:
        _remove_system_objects(
            [
                piece for piece in male_pieces if _object_exists(piece)
            ]
        )
        _remove_direct_split_barriers(systems)


def prepare_direct_printed_mold_for_split(
    split_plane_specs: list[list[list[float]]],
) -> Object:
    """Merge direct-mold clamps into the box while retaining their materials."""
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("No box object found")

    box = Object(box_raw)
    clamps = _direct_clamps()
    if not clamps:
        if split_plane_specs:
            raise RuntimeError("No clamp objects found")
        subtract_base_substracter_from_box()
        return box

    joined_clamps = clamps[0]
    for clamp in clamps[1:]:
        joined_clamps.add_with_material_transfer_and_geometry_fallback(clamp)
        _remove_boolean_operand_and_redraw(clamp)

    box.add_with_material_transfer_and_geometry_fallback(joined_clamps)
    _remove_boolean_operand_and_redraw(joined_clamps)
    subtract_base_substracter_from_box()
    return box


def finalize_direct_printed_mold_parts(
    parts: list[Object],
    *,
    additional_cutters: list[Object] | None = None,
) -> list[Object]:
    """Cut the patron from each split part, preserving all resulting mesh islands."""
    patron_raw = bpy.data.objects.get("patron")
    if patron_raw is None or patron_raw.type != "MESH":
        raise RuntimeError("No patron object found")

    cutters = [Object(patron_raw), *(additional_cutters or [])]
    finalized_parts = []
    for part in parts:
        for cutter in cutters:
            breathe_viewport(bpy.context)
            part -= cutter
            if part.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
            breathe_viewport(bpy.context)
        finalized_parts.append(part)
    return finalized_parts


def space_direct_mold_patron(parts: list[Object]) -> None:
    patron_raw = bpy.data.objects.get("patron")
    if patron_raw is None or patron_raw.type != "MESH" or not parts:
        return

    system_min_x = min(part.min_x for part in parts)
    system_max_x = max(part.max_x for part in parts)
    system_width = system_max_x - system_min_x
    patron = Object(patron_raw)
    target_patron_max_x = system_min_x - system_width / 2
    patron.object.location.x += target_patron_max_x - patron.max_x
    bpy.context.view_layer.update()
    from .confirm_mold import place_clips_left_of_patron

    place_clips_left_of_patron(
        patron_bounds={
            "min_x": patron.min_x,
            "center_y": (patron.min_y + patron.max_y) / 2,
            "min_z": patron.min_z,
        },
        reference_width=system_width,
    )


def create_direct_mold_clips(scene) -> Object:
    """Generate the clamp clips used by an optimized-base mold system."""
    from .confirm_mold import create_clip_from_scene

    return create_clip_from_scene(scene, include_base_clips=False)


def extend_direct_top_funnel_bottom(
    extension: float = DIRECT_TOP_FUNNEL_BOTTOM_EXTENSION,
) -> None:
    """Extrude the flat box bottom down to make room for its barrier."""
    extension = max(float(extension), 0.0)
    if extension <= 1e-6:
        return

    box_object = bpy.data.objects.get("box")
    if box_object is None:
        raise RuntimeError("Cannot extend Direct mold bottom without box")
    box = Object(box_object)
    original_min_z = box.min_z
    selected_count = box.select_limit_flat_faces(max_co=False)
    if selected_count == 0:
        raise RuntimeError("Could not select Direct top-funnel mold bottom face")

    box.extrude_selected(-extension)
    box.recalculate_normals()
    actual_extension = original_min_z - box.min_z
    if abs(actual_extension - extension) > 1e-4:
        raise RuntimeError(
            "Direct top-funnel bottom extension mismatch: "
            f"expected={extension:.4f} actual={actual_extension:.4f}"
        )
    logger.info(
        "Extended Direct top-funnel mold bottom %.4f mm: "
        "min_z=%.4f->%.4f selected_faces=%s",
        extension,
        original_min_z,
        box.min_z,
        selected_count,
    )


def _insert_top_funnel_bottom_extension_step(box_steps, enabled: bool):
    """Insert the bottom extrusion immediately before channels/deposit."""
    for label, step in box_steps:
        if enabled and label == "Generating channels and funneler":
            yield "Extending mold bottom", lambda: extend_direct_top_funnel_bottom(
                DIRECT_TOP_FUNNEL_BOTTOM_EXTENSION
            )
        yield label, step


def _direct_top_funnel_cylinders() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and any(
                marker in obj.name.lower() for marker in DIRECT_TOP_FUNNEL_NAME_MARKERS
            )
            and "_direct_box_outer" not in obj.name.lower()
        ),
        key=lambda obj: obj.name.lower(),
    )


def _shape_direct_funnel_cylinder(
    funnel: Object,
    *,
    top_diameter: float,
    bottom_diameter: float,
) -> None:
    """Turn the clean server cylinder into the requested Z-axis frustum."""
    funnel.origin_to_geometry()
    funnel.apply_all_transforms()
    top_face_idx = funnel.get_limit_face_idx(axis=2, max_co=True, flat=True)
    bottom_face_idx = funnel.get_limit_face_idx(axis=2, max_co=False, flat=True)
    funnel.scale_face_to(top_diameter, axis=0, face_idx=top_face_idx)
    funnel.scale_face_to(top_diameter, axis=1, face_idx=top_face_idx)
    funnel.scale_face_to(bottom_diameter, axis=0, face_idx=bottom_face_idx)
    funnel.scale_face_to(bottom_diameter, axis=1, face_idx=bottom_face_idx)
    funnel.recalculate_normals()


def shape_direct_top_funnels_for_editing(
    top_diameter: float,
    bottom_diameter: float,
) -> None:
    """Shape generated top funnels before Advanced Build returns control."""
    funnel_cylinders = _direct_top_funnel_cylinders()
    if not funnel_cylinders:
        raise RuntimeError("No cylinder funnels were returned for the Direct mold")

    for funnel in funnel_cylinders:
        _shape_direct_funnel_cylinder(
            funnel,
            top_diameter=top_diameter,
            bottom_diameter=bottom_diameter,
        )


def _prepare_direct_funnel_pair(
    funnel: Object,
    *,
    top_diameter: float,
    bottom_diameter: float,
    thickness: float,
) -> tuple[Object, Object]:
    outer_funnel = funnel.duplicate("_direct_box_outer")
    _shape_direct_funnel_cylinder(
        funnel,
        top_diameter=top_diameter,
        bottom_diameter=bottom_diameter,
    )
    master_funnel_top_face_idx = funnel.get_limit_face_idx(
        axis=2,
        max_co=True,
        flat=True,
    )
    funnel.translate_face(
        master_funnel_top_face_idx,
        mathutils.Vector((0.0, 0.0, DIRECT_MASTER_FUNNEL_TOP_EXTENSION)),
    )
    funnel.recalculate_normals()
    _shape_direct_funnel_cylinder(
        outer_funnel,
        top_diameter=top_diameter + thickness * 2.0,
        bottom_diameter=bottom_diameter + thickness * 2.0,
    )
    outer_funnel_bottom_face_idx = outer_funnel.get_limit_face_idx(
        axis=2,
        max_co=False,
        flat=True,
    )
    outer_funnel.translate_face(
        outer_funnel_bottom_face_idx,
        mathutils.Vector((0.0, 0.0, -thickness)),
    )
    outer_funnel.recalculate_normals()
    return funnel, outer_funnel


def _direct_original_master() -> Object:
    master_raw = bpy.data.objects.get("master")
    if master_raw is None or master_raw.type != "MESH":
        master_raw = bpy.data.objects.get("patron")
    if master_raw is None or master_raw.type != "MESH":
        raise RuntimeError("No original master object found")
    return Object(master_raw)


def _raw_mesh_world_bounds(obj) -> tuple[mathutils.Vector, mathutils.Vector]:
    world_corners = [
        obj.matrix_world @ mathutils.Vector(corner)
        for corner in obj.bound_box
    ]
    return (
        mathutils.Vector(
            tuple(min(corner[axis] for corner in world_corners) for axis in range(3))
        ),
        mathutils.Vector(
            tuple(max(corner[axis] for corner in world_corners) for axis in range(3))
        ),
    )


def remove_skin_core_base_undercuts() -> None:
    for obj in tuple(bpy.data.objects):
        if (
            obj.name != SKIN_CORE_BASE_LEGACY_NAME
            and not obj.name.startswith(SKIN_CORE_BASE_NAME_PREFIX)
            and not bool(obj.get(SKIN_CORE_BASE_MARKER, False))
            and not bool(obj.get(SKIN_CORE_BASE_LEGACY_MARKER, False))
            and not bool(obj.get(SKIN_CORE_BASE_FACE_DEBUG_MARKER, False))
            and not bool(
                obj.get(SKIN_CORE_BASE_FACE_DEBUG_LEGACY_MARKER, False)
            )
        ):
            continue
        mesh = getattr(obj, "data", None)
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)


def _skin_core_base_reference_plane(
    core,
    patron_min_corner: mathutils.Vector,
    patron_max_corner: mathutils.Vector,
    scene,
) -> tuple[mathutils.Vector, mathutils.Vector]:
    guide = skin_base_reference_guide_object()
    if guide is not None:
        reference_point = guide.matrix_world.translation.copy()
        reference_normal = (
            guide.matrix_world.to_quaternion()
            @ mathutils.Vector((0.0, 0.0, 1.0))
        )
    else:
        stored_point = core.get(SKIN_CORE_BASE_REFERENCE_POINT_KEY)
        stored_normal = core.get(SKIN_CORE_BASE_REFERENCE_NORMAL_KEY)
        if stored_point is not None and stored_normal is not None:
            reference_point = mathutils.Vector(stored_point)
            reference_normal = mathutils.Vector(stored_normal)
        else:
            percentage = min(
                max(
                    float(getattr(scene, "skin_base_reference_height", 25.0)),
                    1.0,
                ),
                99.0,
            )
            reference_point = (patron_min_corner + patron_max_corner) / 2.0
            reference_point.z = float(patron_min_corner.z) + (
                float(patron_max_corner.z) - float(patron_min_corner.z)
            ) * percentage / 100.0
            reference_normal = mathutils.Vector((0.0, 0.0, 1.0))

    if reference_normal.length_squared <= 1e-12:
        reference_normal = mathutils.Vector((0.0, 0.0, 1.0))
    else:
        reference_normal.normalize()
    core[SKIN_CORE_BASE_REFERENCE_POINT_KEY] = [
        float(value) for value in reference_point
    ]
    core[SKIN_CORE_BASE_REFERENCE_NORMAL_KEY] = [
        float(value) for value in reference_normal
    ]
    return reference_point, reference_normal


def _skin_core_base_request_params(
    core,
    patron,
    scene=None,
    *,
    angle_threshold_degrees: float = 35.0,
) -> dict:
    """Capture the reference plane and server parameters for Skin bases."""
    scene = scene or bpy.context.scene
    remove_skin_core_base_undercuts()
    patron_min_corner, patron_max_corner = _raw_mesh_world_bounds(patron)
    reference_point, reference_normal = _skin_core_base_reference_plane(
        core,
        patron_min_corner,
        patron_max_corner,
        scene,
    )
    return {
        "reference_point_x": float(reference_point.x),
        "reference_point_y": float(reference_point.y),
        "reference_point_z": float(reference_point.z),
        "reference_normal_x": float(reference_normal.x),
        "reference_normal_y": float(reference_normal.y),
        "reference_normal_z": float(reference_normal.z),
        "base_z": float(patron_min_corner.z) - 10.0,
        "angle_threshold_degrees": min(
            max(float(angle_threshold_degrees), 0.0),
            90.0,
        ),
    }


def _import_skin_core_base_response(response) -> list:
    """Import and style the separate base objects returned by the server."""
    imported_objects = import_server_response(
        response,
        remesh_imported_objects=False,
    )
    results = []
    for imported_object in imported_objects:
        # Discard legacy debug-face responses from an older server deployment
        # instead of briefly showing or accidentally joining them as bases.
        if imported_object.name.startswith(SKIN_CORE_BASE_FACE_DEBUG_PREFIX):
            mesh = getattr(imported_object, "data", None)
            bpy.data.objects.remove(imported_object, do_unlink=True)
            if mesh is not None and getattr(mesh, "users", 0) == 0:
                bpy.data.meshes.remove(mesh)
            continue
        if imported_object.name.startswith(SKIN_CORE_BASE_NAME_PREFIX):
            imported_object[SKIN_CORE_BASE_MARKER] = True
            assign_skin_core_base_material(imported_object)
            results.append(imported_object)
            continue
        logger.warning(
            "Ignoring unexpected Skin core base server object %s",
            imported_object.name,
        )
    return results


def request_skin_core_bases(
    core,
    patron,
    scene=None,
    *,
    async_server=False,
    angle_threshold_degrees: float = 35.0,
):
    """Send the generated Skin core to the server for base generation."""
    params = _skin_core_base_request_params(
        core,
        patron,
        scene=scene,
        angle_threshold_degrees=angle_threshold_degrees,
    )
    url = f"{get_server_base_url()}{SKIN_CORE_BASE_PATH}"
    if async_server:
        return request_server_async(
            url,
            [core.name],
            params=params,
            on_complete=_import_skin_core_base_response,
        )
    response = request_server(url, [core.name], params=params)
    return _import_skin_core_base_response(response)


def begin_apply_foundation(context):
    """Run the Skin core basing service against the selected Foundation target."""
    if not foundation_reference_guide_active(context.scene):
        raise RuntimeError(
            "Position the Foundation base-reference circle before confirming"
        )
    target_raw = foundation_reference_target_object(context.scene)
    if target_raw is None:
        raise RuntimeError("The Foundation target object is no longer available")
    target = Object(target_raw)
    original_master = _direct_original_master()
    if target_raw == original_master.object:
        ensure_direct_patron_backup()

    simplified_target = None
    abstracted_target = None
    try:
        simplified_target = create_simplified_reference_for_operation(
            target,
            context,
            name="foundation_simplified_target",
        )
        abstracted_target, _voxel_size = prepare_abstracted_target(
            simplified_target,
            context,
            hide_during_prepare=True,
        )
        abstracted_target.name = "foundation_abstracted_target"
        request = request_skin_core_bases(
            abstracted_target.object,
            target.object,
            scene=context.scene,
            async_server=True,
            angle_threshold_degrees=foundation_threshold_angle_degrees(
                context.scene
            ),
        )
    finally:
        if (
            abstracted_target is not None
            and abstracted_target.object.name in bpy.data.objects
        ):
            abstracted_target.remove()
        if (
            simplified_target is not None
            and simplified_target.object.name in bpy.data.objects
        ):
            simplified_target.remove()
        if target.object.name in bpy.data.objects:
            target.select()

    return request.then(lambda _bases: finish_foundation(context))


def apply_foundation(context) -> Object:
    return finish_task_sync(begin_apply_foundation(context))


def finish_foundation(context) -> Object:
    """Join generated Foundation geometry into its master or sealer target."""
    target_raw = foundation_reference_target_object(context.scene)
    if target_raw is None:
        raise RuntimeError("The Foundation target object is no longer available")
    target = Object(target_raw)
    bases = _skin_core_base_objects()
    if not bases:
        raise RuntimeError("No Foundation geometry was generated at this reference")

    for base in bases:
        assign_foundation_material(base.object)
        target.join(base)
        breathe_viewport(context)
    target_raw[FOUNDATION_APPLIED_MARKER] = True
    remove_skin_core_base_undercuts()
    remove_skin_base_reference_guide()
    target.select()
    breathe_viewport(context)
    return target


def _skin_core_base_objects() -> list[Object]:
    """Return only retained orange base objects, excluding debug face copies."""
    bases = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if (
            obj.name.startswith(SKIN_CORE_BASE_FACE_DEBUG_PREFIX)
            or bool(obj.get(SKIN_CORE_BASE_FACE_DEBUG_MARKER, False))
            or bool(obj.get(SKIN_CORE_BASE_FACE_DEBUG_LEGACY_MARKER, False))
        ):
            continue
        if (
            obj.name.startswith(f"{SKIN_CORE_BASE_NAME_PREFIX}_")
            or bool(obj.get(SKIN_CORE_BASE_MARKER, False))
            or bool(obj.get(SKIN_CORE_BASE_LEGACY_MARKER, False))
        ):
            bases.append(Object(obj))
    return sorted(bases, key=lambda base: base.name)


def confirm_skin_core(context) -> Object:
    """Fuse retained bases into the Skin core and finish its flat bottom."""
    core_raw = bpy.data.objects.get("skin_core")
    if (
        core_raw is None
        or core_raw.type != "MESH"
        or not bool(core_raw.get("moldboxer_skin_core", False))
    ):
        raise RuntimeError("No generated Skin core found to confirm")

    core = Object(core_raw)
    if bool(core_raw.get(SKIN_CORE_CONFIRMED_MARKER, False)):
        remove_skin_core_base_undercuts()
        core.select()
        return core

    patron = _direct_original_master()
    if bool(core_raw.get(CUSTOM_FACE_CORE_MARKER, False)):
        validate_custom_face_head_clearance(context.scene, core_raw, patron.object)
    patron_min_corner, patron_max_corner = _raw_mesh_world_bounds(patron.object)
    patron_center = (patron_min_corner + patron_max_corner) / 2.0
    patron_min_z = float(patron_min_corner.z)

    if bool(core_raw.get(CUSTOM_FACE_CORE_MARKER, False)) and bool(
        core_raw.get(CUSTOM_FACE_CORE_BASES_DIRTY_MARKER, True)
    ):
        request_skin_core_bases(
            core_raw,
            patron.object,
            scene=context.scene,
        )
        core_raw[CUSTOM_FACE_CORE_BASES_DIRTY_MARKER] = False

    breathe_viewport(context)
    for base in _skin_core_base_objects():
        core.join(base)
        breathe_viewport(context)
    core.apply_all_transforms()
    breathe_viewport(context)

    fallback_voxel_size = max(float(context.scene.skin_thickness) / 4.0, 0.025)
    voxel_size = float(core_raw.get(SKIN_CORE_VOXEL_SIZE_KEY, fallback_voxel_size))
    if voxel_size <= 0.0:
        voxel_size = fallback_voxel_size
    core.apply_modifier(build_voxel_modifier(voxel_size))
    breathe_viewport(context)
    remaining_smooth_repeats = SKIN_CORE_CONFIRM_SMOOTH_REPEATS
    while remaining_smooth_repeats > 0:
        smooth_repeats = min(5, remaining_smooth_repeats)
        core.smooth_geometry(
            factor=SKIN_CORE_CONFIRM_SMOOTH_FACTOR,
            repeat=smooth_repeats,
        )
        remaining_smooth_repeats -= smooth_repeats
        breathe_viewport(context)
    core.cut_plane(
        mathutils.Vector((0.0, 0.0, -1.0)),
        mathutils.Vector((patron_center.x, patron_center.y, patron_min_z)),
    )
    core.recalculate_normals()
    breathe_viewport(context)
    core_raw[SKIN_CORE_CONFIRMED_MARKER] = True
    assign_generated_material(core_raw)
    remove_skin_core_base_undercuts()
    core.select()
    return core


def begin_generate_skin_core_wrapper(context):
    """Create the first Skin mold wrapper around the confirmed final core."""
    core_raw = bpy.data.objects.get("skin_core")
    if (
        core_raw is None
        or core_raw.type != "MESH"
        or not bool(core_raw.get(SKIN_CORE_CONFIRMED_MARKER, False))
    ):
        raise RuntimeError("The Skin core must be confirmed before wrapping it")

    existing_wrapper = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    if existing_wrapper is not None:
        if bool(existing_wrapper.get(SKIN_CORE_WRAPPER_MARKER, False)):
            wrapper = Object(existing_wrapper)
            wrapper.select()
            return wrapper
        raise RuntimeError(f'A different object named "{SKIN_CORE_WRAPPER_NAME}" exists')

    skin_thickness = max(float(context.scene.skin_thickness), 1.0)
    wrap_distance = skin_thickness - 1.0
    if wrap_distance <= 1e-6:
        wrapper = Object(core_raw).duplicate(name_adder="_skin_wrap")
        wrapper.apply_all_transforms()
        wrapper.apply_modifier(
            build_voxel_modifier(SKIN_CORE_WRAPPER_VOXEL_SIZE)
        )
    else:
        task = begin_mesh_envelope(
            Object(core_raw),
            distance=wrap_distance,
            n_wraps=1,
            build_from_sphere=False,
        )

        def finish(wrapper):
            wrapper.name = SKIN_CORE_WRAPPER_NAME
            wrapper.object[SKIN_CORE_WRAPPER_MARKER] = True
            assign_moldbox_material(wrapper.object)
            wrapper.object.hide_set(False)
            wrapper.object.hide_viewport = False
            wrapper.object.hide_render = False
            core_raw.hide_set(False)
            core_raw.hide_viewport = False
            wrapper.select()
            return wrapper

        return task.then(finish)

    wrapper.name = SKIN_CORE_WRAPPER_NAME
    wrapper.object[SKIN_CORE_WRAPPER_MARKER] = True
    assign_moldbox_material(wrapper.object)
    wrapper.object.hide_set(False)
    wrapper.object.hide_viewport = False
    wrapper.object.hide_render = False
    core_raw.hide_set(False)
    core_raw.hide_viewport = False
    wrapper.select()
    return wrapper


def generate_skin_core_wrapper(context) -> Object:
    return finish_task_sync(begin_generate_skin_core_wrapper(context))


def begin_generate_skin_inlet(context):
    """Wrap a trimmed copy of skin_wrap to form the lowered Skin inlet."""
    wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    if (
        wrapper_raw is None
        or wrapper_raw.type != "MESH"
        or not bool(wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False))
    ):
        raise RuntimeError("Skin inlet generation requires skin_wrap")

    existing_inlet = bpy.data.objects.get(SKIN_INLET_NAME)
    if existing_inlet is not None:
        if bool(existing_inlet.get(SKIN_INLET_MARKER, False)):
            inlet = Object(existing_inlet)
            inlet.select()
            return inlet
        raise RuntimeError(f'A different object named "{SKIN_INLET_NAME}" exists')

    stale_source = bpy.data.objects.get(SKIN_INLET_SOURCE_NAME)
    if stale_source is not None:
        _remove_mesh_object(stale_source)

    source = Object(wrapper_raw)
    original_min_z = float(source.min_z)
    original_max_z = float(source.max_z)
    source_center = source.center_coords.copy()
    inlet_source = source.duplicate(name_adder="_skin_inlet_source")
    inlet_source.name = SKIN_INLET_SOURCE_NAME
    inlet_source_depth = None
    inlet_source_center_y = None
    try:
        inlet_source.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector(
                (
                    source_center.x,
                    source_center.y,
                    original_min_z + SKIN_INLET_SECTION_HEIGHT,
                )
            ),
        )
        breathe_viewport(context)
        inlet_source_depth = float(inlet_source.depth)
        inlet_source_center_y = float(inlet_source.center_coords.y)
        task = begin_mesh_envelope(
            inlet_source,
            voxel_size=SKIN_CORE_WRAPPER_VOXEL_SIZE,
            distance=max(4.0, float(context.scene.skin_thickness)),
            n_wraps=1,
            build_from_sphere=False,
            cut_bot=False,
        )

        def finish(inlet):
            inlet.cut_plane(
                mathutils.Vector((0.0, 0.0, -1.0)),
                mathutils.Vector((source_center.x, source_center.y, original_min_z)),
            )
            breathe_viewport(context)
            inlet.cut_plane(
                mathutils.Vector((0.0, 0.0, 1.0)),
                mathutils.Vector((source_center.x, source_center.y, original_max_z)),
            )
            breathe_viewport(context)
            inlet.translate_whole(
                mathutils.Vector((0.0, 0.0, SKIN_INLET_Z_OFFSET))
            )
            inlet.name = SKIN_INLET_NAME
            if SKIN_CORE_WRAPPER_MARKER in inlet.object:
                del inlet.object[SKIN_CORE_WRAPPER_MARKER]
            inlet.object[SKIN_INLET_MARKER] = True
            if inlet_source_depth is None or inlet_source_depth <= 0.0:
                inlet.remove()
                _remove_mesh_object(inlet_source.object)
                raise RuntimeError(
                    "Skin inlet bottom section has no measurable depth"
                )
            inlet.object[SKIN_INLET_SOURCE_DEPTH_MARKER] = inlet_source_depth
            inlet.object[SKIN_INLET_SOURCE_CENTER_Y_MARKER] = (
                inlet_source_center_y
            )
            inlet_source.object[SKIN_INLET_SOURCE_MARKER] = True
            inlet_source.object.hide_set(True)
            inlet_source.object.hide_viewport = True
            inlet_source.object.hide_render = True
            assign_moldbox_material(inlet.object)
            inlet.object.hide_set(False)
            inlet.object.hide_viewport = False
            inlet.object.hide_render = False
            inlet.select()
            breathe_viewport(context)
            return inlet

        return task.then(finish)
    except Exception:
        _remove_mesh_object(inlet_source.object)
        raise


def generate_skin_inlet(context) -> Object:
    return finish_task_sync(begin_generate_skin_inlet(context))


def ensure_skin_inlet_source_reference(context) -> Object:
    """Restore the retained trimmed skin-wrap reference when resuming old files."""

    existing = bpy.data.objects.get(SKIN_INLET_SOURCE_NAME)
    if (
        existing is not None
        and existing.type == "MESH"
        and bool(existing.get(SKIN_INLET_SOURCE_MARKER, False))
    ):
        return Object(existing)
    if existing is not None:
        raise RuntimeError(
            f'A different object named "{SKIN_INLET_SOURCE_NAME}" exists'
        )

    wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    if (
        wrapper_raw is None
        or wrapper_raw.type != "MESH"
        or not bool(wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False))
    ):
        raise RuntimeError(
            "Skin attachment reference reconstruction requires skin_wrap"
        )
    wrapper = Object(wrapper_raw)
    source_center = wrapper.center_coords.copy()
    reference = wrapper.duplicate(name_adder="_skin_inlet_source")
    reference.name = SKIN_INLET_SOURCE_NAME
    try:
        reference.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector(
                (
                    source_center.x,
                    source_center.y,
                    float(wrapper.min_z) + SKIN_INLET_SECTION_HEIGHT,
                )
            ),
        )
    except Exception:
        reference.remove()
        raise
    reference.object[SKIN_INLET_SOURCE_MARKER] = True
    reference.object.hide_set(True)
    reference.object.hide_viewport = True
    reference.object.hide_render = True
    breathe_viewport(context or bpy.context)
    return reference


def _remove_mesh_object(raw_object) -> None:
    if raw_object is None:
        return
    try:
        object_name = raw_object.name
    except ReferenceError:
        return
    if object_name not in bpy.data.objects:
        return
    mesh = getattr(raw_object, "data", None)
    bpy.data.objects.remove(raw_object, do_unlink=True)
    if mesh is not None and getattr(mesh, "users", 0) == 0:
        bpy.data.meshes.remove(mesh)


def remove_skin_box_wrap_target() -> None:
    """Remove stale temporary geometry used only to size the Skin mold box."""
    targets = [
        obj
        for obj in tuple(bpy.data.objects)
        if obj.name in {
            SKIN_BOX_WRAP_TARGET_NAME,
            SKIN_BOX_PATRON_DUPLICATE_NAME,
            SKIN_BOX_WRAPPER_DUPLICATE_NAME,
            SKIN_BOX_INLET_DUPLICATE_NAME,
        }
    ]
    for target in targets:
        _remove_mesh_object(target)


def create_skin_box_wrap_target() -> Object:
    """Join disposable patron, wrapper, and inlet copies for the box envelope."""
    remove_skin_box_wrap_target()
    patron_raw = bpy.data.objects.get("patron")
    wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    inlet_raw = bpy.data.objects.get(SKIN_INLET_NAME)
    if patron_raw is None or patron_raw.type != "MESH":
        raise RuntimeError("Skin mold box generation requires the patron mesh")
    if (
        wrapper_raw is None
        or wrapper_raw.type != "MESH"
        or not bool(wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False))
    ):
        raise RuntimeError("Skin mold box generation requires skin_wrap")
    if (
        inlet_raw is None
        or inlet_raw.type != "MESH"
        or not bool(inlet_raw.get(SKIN_INLET_MARKER, False))
    ):
        raise RuntimeError("Skin mold box generation requires skin_inlet")

    patron_duplicate = Object(patron_raw).duplicate(name_adder="_skin_box_target")
    patron_duplicate.name = SKIN_BOX_PATRON_DUPLICATE_NAME
    breathe_viewport(bpy.context)
    wrapper_duplicate = Object(wrapper_raw).duplicate(name_adder="_skin_box_target")
    wrapper_duplicate.name = SKIN_BOX_WRAPPER_DUPLICATE_NAME
    breathe_viewport(bpy.context)
    inlet_duplicate = Object(inlet_raw).duplicate(name_adder="_skin_box_target")
    inlet_duplicate.name = SKIN_BOX_INLET_DUPLICATE_NAME
    breathe_viewport(bpy.context)
    patron_duplicate.join(wrapper_duplicate)
    patron_duplicate.join(inlet_duplicate)
    patron_duplicate.name = SKIN_BOX_WRAP_TARGET_NAME
    patron_duplicate.object.data.name = f"{SKIN_BOX_WRAP_TARGET_NAME}_mesh"
    patron_duplicate.select()
    breathe_viewport(bpy.context)
    return patron_duplicate


def remove_skin_box_wrap_sources() -> None:
    """Remove the disposable target and consumed Skin wrapping geometry."""
    remove_skin_box_wrap_target()
    wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    if wrapper_raw is not None and bool(
        wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False)
    ):
        _remove_mesh_object(wrapper_raw)
    inlet_raw = bpy.data.objects.get(SKIN_INLET_NAME)
    if inlet_raw is not None and bool(inlet_raw.get(SKIN_INLET_MARKER, False)):
        _remove_mesh_object(inlet_raw)
    inlet_source_raw = bpy.data.objects.get(SKIN_INLET_SOURCE_NAME)
    if inlet_source_raw is not None and bool(
        inlet_source_raw.get(SKIN_INLET_SOURCE_MARKER, False)
    ):
        _remove_mesh_object(inlet_source_raw)


def _load_hollower_module():
    package_name = __package__ or ""
    package_suffix = ".source.components"
    if package_name == "source.components":
        addon_package = ""
    elif package_name.endswith(package_suffix):
        addon_package = package_name[: -len(package_suffix)]
    else:
        addon_package = ""
    return importlib.import_module(
        f"{addon_package}.hollower" if addon_package else "hollower"
    )


def _remove_skin_core_attachment_objects(*, include_finished: bool = False) -> None:
    names = {
        SKIN_CORE_ATTACH_SOCKET_NAME,
        SKIN_CORE_SOCKET_CUTTER_NAME,
        "skin_core_pin_clearance",
        "skin_core_pin_box_cutter",
    }
    if include_finished:
        names.update({SKIN_CORE_ATTACHER_NAME, SKIN_CORE_PIN_NAME})
    for raw_object in tuple(bpy.data.objects):
        if raw_object.name in names or any(
            raw_object.name.startswith(f"{name}_") for name in names
        ):
            _remove_mesh_object(raw_object)


def resolve_direct_skin_core_type(scene, core_type: str | None = None) -> str:
    """Normalize the selected Direct Skin core construction type."""
    selected = str(
        core_type
        if core_type is not None
        else getattr(scene, "direct_skin_core_type", "MULTI_PART")
    ).upper()
    return selected if selected in {"SINGLE_PART", "MULTI_PART"} else "MULTI_PART"


def hollow_skin_core_for_attachment(
    context,
    *,
    core: Object | None = None,
    is_multi_part: bool = True,
    attachment_center_ys: list[float] | None = None,
) -> Object:
    """Hollow the Skin core locally, opening it through its bottom."""
    core_raw = (
        bpy.data.objects.get(SKIN_CORE_NAME)
        if core is None
        else core.object
    )
    if (
        core_raw is None
        or core_raw.type != "MESH"
        or (
            core is None
            and not bool(core_raw.get("moldboxer_skin_core", False))
        )
    ):
        raise RuntimeError("Skin attachment hollowing requires skin_core")
    core = Object(core_raw) if core is None else core
    if bool(core_raw.get(SKIN_CORE_HOLLOWED_MARKER, False)):
        return core

    if not attachment_center_ys:
        stored_center_y = core_raw.get(SKIN_CORE_ATTACHMENT_CENTER_Y_MARKER)
        attachment_center_ys = [
            skin_inlet_bottom_section_center_y(context)
            if stored_center_y is None
            else float(stored_center_y)
        ]
    hollower_module = _load_hollower_module()
    cavity_exclusion = None
    try:
        for reference_index, center_y in enumerate(attachment_center_ys, start=1):
            exclusion = create_core_cavity_exclusion(
                core,
                reference_index=reference_index,
                is_multi_part=is_multi_part,
                attachment_at_bottom=True,
                center_y=float(center_y),
            )
            if cavity_exclusion is None:
                cavity_exclusion = exclusion
            else:
                cavity_exclusion.join(exclusion)
        if cavity_exclusion is None:
            raise RuntimeError("Skin attachment hollowing has no Y positions")
        solid_mesh_name = core_raw.data.name
        solid_mesh_backup = core_raw.data.copy()
        solid_matrix_world = core_raw.matrix_world.copy()
        try:
            hollower_module.hollow_object(
                context,
                core_raw,
                cavity_inset=max(float(context.scene.direct_mold_thickness), 0.1),
                quality=SKIN_CORE_HOLLOW_QUALITY,
                open_bottom=True,
                open_top=False,
                cavity_exclusion=cavity_exclusion.object,
                use_manifold_hollow_difference=True,
            )
        except RuntimeError as exc:
            cavity_was_removed = isinstance(
                exc,
                hollower_module.EmptyCavityError,
            )
            opening_was_removed = (
                "completely removes the cavity opening" in str(exc)
            )
            if not cavity_was_removed and not opening_was_removed:
                raise
            failed_mesh = core_raw.data
            core_raw.data = solid_mesh_backup
            core_raw.matrix_world = solid_matrix_world
            if (
                failed_mesh is not solid_mesh_backup
                and failed_mesh.users == 0
                and bpy.data.meshes.get(failed_mesh.name) is failed_mesh
            ):
                bpy.data.meshes.remove(failed_mesh)
            solid_mesh_backup.name = solid_mesh_name
            solid_mesh_backup = None
            logger.warning(
                "Skin core is too narrow for the requested hollow wall; "
                "keeping the core solid"
            )
        finally:
            if (
                solid_mesh_backup is not None
                and solid_mesh_backup.users == 0
                and bpy.data.meshes.get(solid_mesh_backup.name)
                is solid_mesh_backup
            ):
                bpy.data.meshes.remove(solid_mesh_backup)
    finally:
        if cavity_exclusion is not None:
            cavity_exclusion.remove()
    core_raw[SKIN_CORE_HOLLOWED_MARKER] = True
    assign_generated_material(core_raw)
    breathe_viewport(context)
    return core


def _skin_attachment_part_index(
    attacher: Object,
    part_count: int,
) -> int | None:
    match = re.search(r"_part_(\d{3})_\d{3}(?:\.\d{3})?$", attacher.name)
    if match is None:
        return None
    part_index = int(match.group(1)) - 1
    return part_index if 0 <= part_index < part_count else None


def _skin_attachment_distance_to_part(
    attacher: Object,
    core_part: Object,
) -> float:
    center = attacher.center_coords
    delta_x = max(core_part.min_x - center.x, 0.0, center.x - core_part.max_x)
    delta_y = max(core_part.min_y - center.y, 0.0, center.y - core_part.max_y)
    return delta_x * delta_x + delta_y * delta_y


def build_skin_core_attachments_from_reference_islands(
    context,
    core: Object,
    attachers: list[Object],
    box: Object,
    *,
    is_multi_part: bool,
) -> tuple[Object, Object | None]:
    """Use each bottom-section reference island, then rejoin the reference."""

    reference_raw = bpy.data.objects.get(SKIN_INLET_SOURCE_NAME)
    if (
        reference_raw is None
        or reference_raw.type != "MESH"
        or not bool(reference_raw.get(SKIN_INLET_SOURCE_MARKER, False))
    ):
        raise RuntimeError(
            "Skin attachment finishing requires the bottom-section reference"
        )
    reference = Object(reference_raw)
    reference.object.hide_set(False)
    reference.object.hide_viewport = False
    reference_parts = sorted(
        reference.split_isolated_meshes(),
        key=lambda part: (
            part.min_x,
            part.min_y,
            part.max_x,
            part.max_y,
            part.volume,
        ),
    )
    grouped_attachers: list[list[Object]] = [[] for _part in reference_parts]
    for attacher in attachers:
        part_index = _skin_attachment_part_index(attacher, len(reference_parts))
        if part_index is None:
            part_index = min(
                range(len(reference_parts)),
                key=lambda index: _skin_attachment_distance_to_part(
                    attacher,
                    reference_parts[index],
                ),
            )
        grouped_attachers[part_index].append(attacher)

    pins: list[Object] = []
    try:
        hollow_skin_core_for_attachment(
            context,
            core=core,
            is_multi_part=is_multi_part,
            attachment_center_ys=[
                attacher.center_coords.y for attacher in attachers
            ],
        )
        for part_index, (reference_part, part_attachers) in enumerate(
            zip(reference_parts, grouped_attachers),
            start=1,
        ):
            if not part_attachers:
                logger.warning(
                    "Skin bottom-section island %s has no attachment",
                    part_index,
                )
                continue
            if is_multi_part:
                pins.append(
                    create_skin_core_attachment_pin(
                        context,
                        core,
                        part_attachers,
                        box,
                        source_depth=float(reference_part.depth),
                        source_center_y=float(reference_part.center_coords.y),
                        reference_center_x=float(reference_part.center_coords.x),
                        part_index=part_index,
                        part_count=len(reference_parts),
                    )
                )
    finally:
        for reference_part in reference_parts:
            if reference_part.object != reference.object:
                reference.join(reference_part)
        reference.name = SKIN_INLET_SOURCE_NAME
        reference.object[SKIN_INLET_SOURCE_MARKER] = True
        reference.object.hide_set(True)
        reference.object.hide_viewport = True
        reference.object.hide_render = True

    joined_pin = pins[0] if pins else None
    if joined_pin is not None:
        for pin in pins[1:]:
            joined_pin.join(pin)
        joined_pin.name = SKIN_CORE_PIN_NAME
    return core, joined_pin


def skin_inlet_bottom_section_metrics(context=None) -> tuple[float, float]:
    """Return Y depth and center of the source used to build skin_inlet."""
    inlet_raw = bpy.data.objects.get(SKIN_INLET_NAME)
    if (
        inlet_raw is None
        or inlet_raw.type != "MESH"
        or not bool(inlet_raw.get(SKIN_INLET_MARKER, False))
    ):
        raise RuntimeError("Skin core pin generation requires skin_inlet")

    stored_depth = inlet_raw.get(SKIN_INLET_SOURCE_DEPTH_MARKER)
    stored_center_y = inlet_raw.get(SKIN_INLET_SOURCE_CENTER_Y_MARKER)
    if (
        stored_depth is not None
        and float(stored_depth) > 0.0
        and stored_center_y is not None
    ):
        return float(stored_depth), float(stored_center_y)

    wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    if (
        wrapper_raw is None
        or wrapper_raw.type != "MESH"
        or not bool(wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False))
    ):
        raise RuntimeError(
            "Skin inlet source depth is missing and skin_wrap is unavailable"
        )

    wrapper = Object(wrapper_raw)
    source_center = wrapper.center_coords.copy()
    source_min_z = float(wrapper.min_z)
    inlet_source = wrapper.duplicate(name_adder="_skin_pin_depth_source")
    try:
        inlet_source.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector(
                (
                    source_center.x,
                    source_center.y,
                    source_min_z + SKIN_INLET_SECTION_HEIGHT,
                )
            ),
        )
        source_depth = float(inlet_source.depth)
        source_center_y = float(inlet_source.center_coords.y)
    finally:
        inlet_source.remove()
    if source_depth <= 0.0:
        raise RuntimeError("Skin inlet bottom section has no measurable depth")
    inlet_raw[SKIN_INLET_SOURCE_DEPTH_MARKER] = source_depth
    inlet_raw[SKIN_INLET_SOURCE_CENTER_Y_MARKER] = source_center_y
    breathe_viewport(context or bpy.context)
    return source_depth, source_center_y


def skin_inlet_bottom_section_depth(context=None) -> float:
    """Return the Y depth of the trimmed source used to build skin_inlet."""
    return skin_inlet_bottom_section_metrics(context)[0]


def skin_inlet_bottom_section_center_y(context=None) -> float:
    """Return the Y center of the trimmed source used to build skin_inlet."""
    return skin_inlet_bottom_section_metrics(context)[1]


def create_skin_core_attachment_pin(
    context,
    core: Object,
    attachers: list[Object],
    box: Object,
    *,
    source_depth: float | None = None,
    source_center_y: float | None = None,
    reference_center_x: float | None = None,
    part_index: int = 1,
    part_count: int = 1,
) -> Object:
    """Keep a transverse core pin and cut its reversed attachment clearances."""
    if not attachers:
        raise RuntimeError("Skin core pin generation requires an attacher")
    reference_attacher = attachers[0]
    pin_name = (
        SKIN_CORE_PIN_NAME
        if part_count == 1
        else f"{SKIN_CORE_PIN_NAME}_part_{part_index:03d}"
    )
    existing_pin = bpy.data.objects.get(pin_name)
    if existing_pin is not None:
        _remove_mesh_object(existing_pin)

    has_explicit_reference = (
        source_depth is not None and source_center_y is not None
    )
    if not has_explicit_reference:
        source_depth, source_center_y = skin_inlet_bottom_section_metrics(context)
    pin_depth = source_depth + SKIN_CORE_PIN_DEPTH_OVERTRAVEL
    core_center_y = float(
        source_center_y
        if has_explicit_reference
        else core.object.get(
            SKIN_CORE_ATTACHMENT_CENTER_Y_MARKER, source_center_y
        )
    )
    pin = Object(
        create_cube_primitive(1.0),
        pin_name,
    )
    pin_profile_side = SKIN_CORE_PIN_DIAMETER / math.sqrt(2.0)
    pin.scale_to(pin_profile_side, 0)
    pin.scale_to(pin_depth, 1)
    pin.scale_to(pin_profile_side, 2)
    pin.rotate_whole(mathutils.Matrix.Rotation(math.radians(45), 4, "Y"))
    pin.translate_whole(
        mathutils.Vector(
            (
                (
                    core.center_coords.x
                    if reference_center_x is None
                    else float(reference_center_x)
                )
                - pin.center_coords.x,
                core_center_y - pin.center_coords.y,
                reference_attacher.center_coords.z - pin.center_coords.z,
            )
        )
    )
    pin.object[SKIN_CORE_PIN_MARKER] = True
    assign_generated_material(pin.object)

    clearance = pin.duplicate(name_adder="_clearance")
    clearance.name = (
        "skin_core_pin_clearance"
        if part_count == 1
        else f"skin_core_pin_clearance_part_{part_index:03d}"
    )
    clearance_profile_size = (
        SKIN_CORE_PIN_DIAMETER + SKIN_CORE_PIN_CLEARANCE_DIAMETER_EXTRA
    )
    clearance_profile_scale = clearance_profile_size / SKIN_CORE_PIN_DIAMETER
    clearance.scale(clearance_profile_scale, 0)
    clearance.scale_to(
        box.depth * SKIN_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR,
        1,
    )
    clearance.scale(clearance_profile_scale, 2)
    clearance.translate_whole(pin.center_coords - clearance.center_coords)

    box_cutter = Object(
        create_cube_primitive(1.0),
        (
            "skin_core_pin_box_cutter"
            if part_count == 1
            else f"skin_core_pin_box_cutter_part_{part_index:03d}"
        ),
    )
    box_cutter.scale_to(SKIN_CORE_PIN_BOX_CUTTER_WIDTH, 0)
    box_cutter.scale_to(
        box.depth * SKIN_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR,
        1,
    )
    box_cutter.scale_to(SKIN_CORE_PIN_BOX_CUTTER_HEIGHT, 2)
    box_cutter.translate_whole(
        mathutils.Vector(
            (
                pin.center_coords.x - box_cutter.center_coords.x,
                pin.center_coords.y - box_cutter.center_coords.y,
                reference_attacher.max_z - box_cutter.max_z,
            )
        )
    )
    try:
        core.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=clearance,
        )
        for attacher in attachers:
            attacher.apply_boolean_modifier(
                diff_no_material_transfer_mod,
                target=clearance,
            )
    except Exception:
        box_cutter.remove()
        raise
    finally:
        clearance.remove()

    # Keep this operand until clamps have been unioned into the box. Applying
    # it now would allow the later clamp union to refill the clearance.
    box_cutter.hide_during_ui_breathe = True
    box_cutter.object.hide_set(True)
    box_cutter.object.hide_viewport = True
    box_cutter.object.hide_render = True

    pin.select()
    breathe_viewport(context)
    return pin


def apply_skin_core_pin_box_clearance(context=None) -> Object | None:
    """Cut the retained pin clearance after every clamp has joined the box."""
    cutter_objects = [
        raw_object
        for raw_object in tuple(bpy.data.objects)
        if raw_object.type == "MESH"
        and (
            raw_object.name == "skin_core_pin_box_cutter"
            or raw_object.name.startswith("skin_core_pin_box_cutter_")
        )
    ]
    if not cutter_objects:
        return None
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("Skin pin clearance requires the joined mold box")

    box = Object(box_raw)
    for cutter_raw in cutter_objects:
        cutter = Object(cutter_raw)
        try:
            box.apply_boolean_modifier(
                diff_no_material_transfer_mod,
                target=cutter,
            )
            if box.has_empty_boolean:
                raise Exception("Skin core pin box clearance Boolean failed")
            breathe_viewport(context or bpy.context)
        finally:
            cutter.remove()
    return box


def fit_skin_attachment_socket_to_box_top(
    socket: Object,
    box: Object,
    tolerance: float = 1e-3,
) -> None:
    """Defensively fit an imported Skin socket to the current finished box."""
    target_max_z = float(box.max_z)
    extension = target_max_z - float(socket.max_z)
    if extension > tolerance:
        selected_count = socket.select_limit_flat_faces(max_co=True)
        if selected_count == 0:
            raise RuntimeError("Could not select the Skin attach socket top")
        socket.extrude_selected(extension)
    elif extension < -tolerance:
        socket.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector((0.0, 0.0, target_max_z)),
        )
    if abs(float(socket.max_z) - target_max_z) > tolerance:
        raise RuntimeError(
            "Skin attach socket does not reach the finished box top: "
            f"socket_max_z={socket.max_z} box_max_z={target_max_z}"
        )


def finish_skin_core_attachment(
    context,
    response,
    *,
    core_type: str | None = None,
) -> Object:
    """Import the reversed server attachment and finish its client geometry."""
    _remove_skin_core_attachment_objects(include_finished=True)
    imported_objects = import_server_response(
        response,
        remesh_imported_objects=False,
    )
    def matching_objects(base_name: str) -> list[Object]:
        matches = [
            Object(obj)
            for obj in imported_objects
            if obj.name == base_name or obj.name.startswith(f"{base_name}_")
        ]
        return sorted(matches, key=lambda item: item.name)

    attachers = matching_objects(SKIN_CORE_ATTACHER_NAME)
    sockets = matching_objects(SKIN_CORE_ATTACH_SOCKET_NAME)
    socket_cutters = matching_objects(SKIN_CORE_SOCKET_CUTTER_NAME)
    if not attachers or not (
        len(attachers) == len(sockets) == len(socket_cutters)
    ):
        raise RuntimeError(
            "Skin attachment server response has mismatched attachment parts: "
            f"attachers={len(attachers)} sockets={len(sockets)} "
            f"cutters={len(socket_cutters)}"
        )

    for attacher in attachers:
        assign_generated_material(attacher.object)
    for socket in sockets:
        assign_moldbox_material(socket.object)
    for socket_cutter in socket_cutters:
        assign_moldbox_material(socket_cutter.object)
    core_type = resolve_direct_skin_core_type(context.scene, core_type)
    is_multi_part = core_type == "MULTI_PART"
    core_raw = bpy.data.objects.get(SKIN_CORE_NAME)
    if core_raw is None or core_raw.type != "MESH":
        raise RuntimeError("Skin attachment finishing requires skin_core")
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("Skin attachment finishing requires the mold box")
    box = Object(box_raw)
    core, skin_pin = build_skin_core_attachments_from_reference_islands(
        context,
        Object(core_raw),
        attachers,
        box,
        is_multi_part=is_multi_part,
    )
    for socket in sockets:
        fit_skin_attachment_socket_to_box_top(socket, box)

    if is_multi_part:
        for socket_cutter in socket_cutters:
            core_cutter = socket_cutter.duplicate(name_adder="_core")
            try:
                core.apply_boolean_modifier(
                    diff_no_material_transfer_mod,
                    target=core_cutter,
                )
            finally:
                core_cutter.remove()
            breathe_viewport(context)

    for socket, socket_cutter in zip(sockets, socket_cutters):
        box.apply_boolean_modifier(union_mod, target=socket)
        box.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=socket_cutter,
        )
        breathe_viewport(context)

    if is_multi_part:
        if skin_pin is None:
            raise RuntimeError("Skin core islands produced no attachment pins")
        result = skin_pin
        for attacher in attachers:
            attacher.object[SKIN_CORE_ATTACHMENT_READY_MARKER] = True
            attacher.object.hide_set(False)
            attacher.object.hide_viewport = False
            attacher.object.hide_render = False
    else:
        for attacher in attachers:
            core.join(attacher)
        assign_generated_material(core.object)
        result = core

    for socket in sockets:
        socket.remove()
    for socket_cutter in socket_cutters:
        socket_cutter.remove()
    core.object[SKIN_CORE_ATTACHMENT_READY_MARKER] = True
    core.object[SKIN_CORE_ATTACHMENT_BOX_MAX_Z_MARKER] = float(box.max_z)
    core.object[SKIN_CORE_ATTACHMENT_TYPE_MARKER] = core_type
    result.select()
    return result


def skin_core_attachment_matches_box_top(
    core_type: str | None = None,
    center_y: float | None = None,
    depth: float | None = None,
    tolerance: float = 1e-3,
) -> bool:
    """Return whether the current Skin attachment used the finished box top."""
    core_raw = bpy.data.objects.get("skin_core")
    box_raw = bpy.data.objects.get("box")
    if (
        core_raw is None
        or core_raw.type != "MESH"
        or box_raw is None
        or box_raw.type != "MESH"
        or not bool(core_raw.get(SKIN_CORE_ATTACHMENT_READY_MARKER, False))
    ):
        return False
    stored_max_z = core_raw.get(SKIN_CORE_ATTACHMENT_BOX_MAX_Z_MARKER)
    stored_center_y = core_raw.get(SKIN_CORE_ATTACHMENT_CENTER_Y_MARKER)
    stored_depth = core_raw.get(SKIN_CORE_ATTACHMENT_DEPTH_MARKER)
    selected_core_type = resolve_direct_skin_core_type(
        bpy.context.scene,
        core_type,
    )
    if (
        stored_max_z is None
        or stored_center_y is None
        or stored_depth is None
        or core_raw.get(SKIN_CORE_ATTACHMENT_TYPE_MARKER) != selected_core_type
    ):
        return False
    if center_y is not None and abs(float(stored_center_y) - center_y) > tolerance:
        return False
    if depth is not None and abs(float(stored_depth) - depth) > tolerance:
        return False
    return abs(float(stored_max_z) - float(Object(box_raw).max_z)) <= tolerance


def fit_skin_core_bottom_to_finished_box(
    core: Object,
    box: Object,
    tolerance: float = 1e-3,
) -> bool:
    """Fit the still-solid Skin core bottom to the finished box minimum Z."""
    target_min_z = float(box.min_z)
    original_min_z = float(core.min_z)
    distance_to_extend = original_min_z - target_min_z
    changed = False
    if distance_to_extend > tolerance:
        selected_count = core.select_limit_flat_faces(max_co=False)
        if selected_count == 0:
            raise RuntimeError("Could not select the Skin core bottom faces")
        core.extrude_selected(-distance_to_extend)
        changed = True
    elif distance_to_extend < -tolerance:
        core.cut_plane(
            mathutils.Vector((0.0, 0.0, -1.0)),
            mathutils.Vector((0.0, 0.0, target_min_z)),
        )
        changed = True

    if abs(float(core.min_z) - target_min_z) > tolerance:
        raise RuntimeError(
            "Skin core bottom does not reach the finished box bottom: "
            f"core_min_z={core.min_z} box_min_z={target_min_z}"
        )

    core.object[SKIN_CORE_FINAL_BOX_MIN_Z_MARKER] = target_min_z
    if changed:
        core.object[SKIN_CORE_ATTACHMENT_READY_MARKER] = False
        if SKIN_CORE_ATTACHMENT_BOX_MAX_Z_MARKER in core.object:
            del core.object[SKIN_CORE_ATTACHMENT_BOX_MAX_Z_MARKER]
        logger.info(
            "Fitted solid Skin core bottom to finished box: %.4f -> %.4f",
            original_min_z,
            target_min_z,
        )
    return changed


def request_skin_core_attachment(
    context,
    *,
    async_server: bool = False,
    core_type: str | None = None,
):
    """Ask the server for the reversed Skin attacher/socket geometry."""
    core_raw = bpy.data.objects.get("skin_core")
    box_raw = bpy.data.objects.get("box")
    inlet_source_raw = ensure_skin_inlet_source_reference(context).object
    if core_raw is None or core_raw.type != "MESH":
        raise RuntimeError("Skin attachment generation requires skin_core")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("Skin attachment generation requires the mold box")
    if (
        inlet_source_raw is None
        or inlet_source_raw.type != "MESH"
        or not bool(inlet_source_raw.get(SKIN_INLET_SOURCE_MARKER, False))
    ):
        raise RuntimeError(
            "Skin attachment generation requires the bottom-section reference"
        )
    core = Object(core_raw)
    box = Object(box_raw)
    core_type = resolve_direct_skin_core_type(context.scene, core_type)
    fit_skin_core_bottom_to_finished_box(core, box)
    attachment_depth, attachment_center_y = skin_inlet_bottom_section_metrics(
        context
    )
    if skin_core_attachment_matches_box_top(
        core_type,
        attachment_center_y,
        attachment_depth,
    ):
        return core

    _remove_skin_core_attachment_objects(include_finished=True)
    core_raw[SKIN_CORE_ATTACHMENT_CENTER_Y_MARKER] = attachment_center_y
    core_raw[SKIN_CORE_ATTACHMENT_DEPTH_MARKER] = attachment_depth
    params = {
        "min_box_z": float(box.min_z),
        "max_box_z": float(box.max_z),
        "core_center_y": attachment_center_y,
        "core_depth": attachment_depth,
        "clamp_width": float(context.scene.clamp_width),
        "core_type": core_type,
        "box_thickness": float(context.scene.direct_mold_thickness),
        "mold_thickness": float(context.scene.direct_mold_thickness),
        "box_intersection_voxel_size": get_box_voxel_size(
            context.scene.box_quality,
            box_raw,
        ),
    }
    endpoint = f"{get_server_base_url()}{SKIN_CORE_ATTACHMENT_PATH}"
    if async_server:
        return request_server_async(
            endpoint,
            [core_raw.name, box_raw.name, inlet_source_raw.name],
            params=params,
            on_complete=lambda response: finish_skin_core_attachment(
                context,
                response,
                core_type=core_type,
            ),
        )
    response = request_server(
        endpoint,
        [core_raw.name, box_raw.name, inlet_source_raw.name],
        params=params,
    )
    return finish_skin_core_attachment(
        context,
        response,
        core_type=core_type,
    )


def _configure_custom_face_transparent_material(material) -> None:
    material.use_nodes = True
    rgba = tuple(material.diffuse_color)
    material.diffuse_color = (*rgba[:3], CUSTOM_FACE_MASTER_PREVIEW_ALPHA)
    node_tree = getattr(material, "node_tree", None)
    if node_tree is not None:
        for node in node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            alpha_input = node.inputs.get("Alpha")
            if alpha_input is not None:
                alpha_input.default_value = CUSTOM_FACE_MASTER_PREVIEW_ALPHA
            break
    for attr_name, value in (
        ("blend_method", "BLEND"),
        ("surface_render_method", "BLENDED"),
        ("show_transparent_back", True),
        ("use_screen_refraction", False),
    ):
        if hasattr(material, attr_name):
            try:
                setattr(material, attr_name, value)
            except Exception:
                pass


def remove_custom_face_master_transparency() -> None:
    """Restore material slots changed only for the custom-head preview."""

    for master in tuple(bpy.data.objects):
        if not bool(master.get(CUSTOM_FACE_MASTER_TRANSPARENT_MARKER, False)):
            continue
        original_material_names = tuple(
            master.get(CUSTOM_FACE_MASTER_ORIGINAL_MATERIALS_KEY, ())
        )
        preview_material_names = tuple(
            master.get(CUSTOM_FACE_MASTER_PREVIEW_MATERIALS_KEY, ())
        )
        materials = getattr(getattr(master, "data", None), "materials", None)
        if materials is not None:
            materials.clear()
            for material_name in original_material_names:
                material = bpy.data.materials.get(str(material_name))
                if material is not None:
                    materials.append(material)

        original_color = master.get(CUSTOM_FACE_MASTER_ORIGINAL_COLOR_KEY)
        if original_color is not None and len(original_color) == 4:
            master.color = tuple(float(value) for value in original_color)
        original_display_type = master.get(
            CUSTOM_FACE_MASTER_ORIGINAL_DISPLAY_TYPE_KEY
        )
        if original_display_type:
            master.display_type = str(original_display_type)
        if hasattr(master, "show_transparent"):
            master.show_transparent = bool(
                master.get(CUSTOM_FACE_MASTER_ORIGINAL_TRANSPARENCY_KEY, False)
            )

        for key in (
            CUSTOM_FACE_MASTER_TRANSPARENT_MARKER,
            CUSTOM_FACE_MASTER_ORIGINAL_MATERIALS_KEY,
            CUSTOM_FACE_MASTER_PREVIEW_MATERIALS_KEY,
            CUSTOM_FACE_MASTER_ORIGINAL_COLOR_KEY,
            CUSTOM_FACE_MASTER_ORIGINAL_DISPLAY_TYPE_KEY,
            CUSTOM_FACE_MASTER_ORIGINAL_TRANSPARENCY_KEY,
        ):
            if key in master:
                del master[key]
        for material_name in preview_material_names:
            material = bpy.data.materials.get(str(material_name))
            if material is not None and material.users == 0:
                bpy.data.materials.remove(material)


def remove_skin_master_half_preview() -> None:
    """Remove either temporary Skin master preview and restore the master."""

    remove_custom_face_master_transparency()
    cutters = [
        obj
        for obj in bpy.data.objects
        if obj.name == SKIN_MASTER_HALF_PREVIEW_CUTTER_NAME
        or bool(obj.get(SKIN_MASTER_HALF_PREVIEW_CUTTER_MARKER, False))
    ]
    for obj in bpy.data.objects:
        for modifier in tuple(getattr(obj, "modifiers", ())):
            target = getattr(modifier, "object", None)
            target_is_preview_cutter = bool(
                target is not None
                and (
                    target.name == SKIN_MASTER_HALF_PREVIEW_CUTTER_NAME
                    or target.get(SKIN_MASTER_HALF_PREVIEW_CUTTER_MARKER, False)
                )
            )
            if (
                modifier.name == SKIN_MASTER_HALF_PREVIEW_MODIFIER_NAME
                or target_is_preview_cutter
            ):
                obj.modifiers.remove(modifier)
    for cutter in cutters:
        mesh = getattr(cutter, "data", None)
        bpy.data.objects.remove(cutter, do_unlink=True)
        if mesh is not None and getattr(mesh, "users", 0) == 0:
            bpy.data.meshes.remove(mesh)


def show_custom_face_master_transparent(master) -> None:
    """Show the whole custom-face master translucently without a Boolean."""

    remove_skin_master_half_preview()
    materials = getattr(getattr(master, "data", None), "materials", None)
    if materials is None:
        return

    original_materials = tuple(materials)
    master[CUSTOM_FACE_MASTER_ORIGINAL_MATERIALS_KEY] = [
        material.name for material in original_materials if material is not None
    ]
    master[CUSTOM_FACE_MASTER_ORIGINAL_COLOR_KEY] = [
        float(value) for value in master.color
    ]
    master[CUSTOM_FACE_MASTER_ORIGINAL_DISPLAY_TYPE_KEY] = str(master.display_type)
    master[CUSTOM_FACE_MASTER_ORIGINAL_TRANSPARENCY_KEY] = bool(
        getattr(master, "show_transparent", False)
    )

    preview_materials = []
    material_sources = original_materials or (None,)
    for index, original_material in enumerate(material_sources):
        if original_material is None:
            preview_material = bpy.data.materials.new(
                name=f"MB_CustomFaceMasterPreview_{master.name}_{index}"
            )
            preview_material.diffuse_color = (0.82, 0.9, 0.62, 1.0)
        else:
            preview_material = original_material.copy()
            preview_material.name = (
                f"MB_CustomFaceMasterPreview_{master.name}_{index}"
            )
        _configure_custom_face_transparent_material(preview_material)
        preview_materials.append(preview_material)

    materials.clear()
    for preview_material in preview_materials:
        materials.append(preview_material)
    master[CUSTOM_FACE_MASTER_PREVIEW_MATERIALS_KEY] = [
        material.name for material in preview_materials
    ]
    master[CUSTOM_FACE_MASTER_TRANSPARENT_MARKER] = True
    master.display_type = "TEXTURED"
    master.color = (*tuple(master.color)[:3], CUSTOM_FACE_MASTER_PREVIEW_ALPHA)
    if hasattr(master, "show_transparent"):
        master.show_transparent = True
    master.hide_set(False)
    bpy.context.view_layer.update()


def create_skin_master_half_preview(patron) -> None:
    """Show the negative-X half of the patron using an unapplied Boolean."""
    remove_skin_master_half_preview()
    min_corner, max_corner = _raw_mesh_world_bounds(patron)
    center = (min_corner + max_corner) / 2.0
    dimensions = max_corner - min_corner
    if min(dimensions) <= 1e-9:
        return

    cutter = create_cube_primitive(1.0)
    if cutter is None:
        raise RuntimeError("Could not create the Skin half-master preview cutter")
    cutter.name = SKIN_MASTER_HALF_PREVIEW_CUTTER_NAME
    cutter.data.name = f"{SKIN_MASTER_HALF_PREVIEW_CUTTER_NAME}_mesh"
    cutter[SKIN_MASTER_HALF_PREVIEW_CUTTER_MARKER] = True
    cutter.dimensions = dimensions * 2.0
    cutter.location = (
        center.x + dimensions.x,
        center.y,
        center.z,
    )
    bpy.context.view_layer.update()

    modifier = patron.modifiers.new(
        SKIN_MASTER_HALF_PREVIEW_MODIFIER_NAME,
        type="BOOLEAN",
    )
    modifier.operation = "DIFFERENCE"
    modifier.solver = "MANIFOLD"
    modifier.object = cutter
    modifier.show_viewport = True
    modifier.show_render = False
    cutter.hide_select = True
    cutter.hide_render = True
    cutter.hide_set(True)


def _finish_direct_skin_core_generation(
    context,
    source,
    core,
    voxel_size,
    base_request,
    *,
    custom_face_mode,
    async_server,
):
    """Finalize a generated core on Blender's main thread."""

    center_skin_master_origin(source)
    core[SKIN_CORE_VOXEL_SIZE_KEY] = float(voxel_size)
    assign_generated_material(core)
    casting_volume = calculate_casting_volume()
    core[SKIN_CASTING_VOLUME_ML_KEY] = casting_volume
    context.scene.casting_volume_ml = casting_volume
    remove_skin_base_reference_guide()
    if custom_face_mode:
        show_custom_face_master_transparent(source)
    else:
        create_skin_master_half_preview(source)
    selected_core = Object(core)
    if custom_face_mode:
        Object(source).select()
    else:
        selected_core.select()
    if async_server and base_request is not None:
        return base_request
    return selected_core


def generate_direct_skin_core(context, *, async_server=False):
    """Create the selected automatic or adjustable Skin core artifact."""

    source = _direct_original_master().object
    custom_face_mode = (
        ENABLE_CUSTOM_FACE_CORE
        and getattr(
            context.scene,
            "direct_skin_core_generation_mode",
            "AUTOMATIC",
        )
        == "CUSTOM_FACE"
    )
    if custom_face_mode:
        dimensions = custom_face_dimensions(context.scene)
        voxel_size = min(
            dimensions["custom_face_head_height"],
            dimensions["custom_face_head_width"],
            dimensions["custom_face_head_depth"],
        ) / 240.0
        voxel_size = min(max(voxel_size, 0.25), 1.0)
        if async_server:
            return begin_create_custom_face_core(context, source).then(
                lambda core: _finish_direct_skin_core_generation(
                    context,
                    source,
                    core,
                    voxel_size,
                    None,
                    custom_face_mode=True,
                    async_server=True,
                )
            )
        core = create_custom_face_core(context, source)
        base_request = None
    else:
        hollower_module = _load_hollower_module()
        core, voxel_size, _requested_voxel_size, _estimate = (
            hollower_module.generate_skin_core(
                context,
                source,
                float(context.scene.skin_thickness),
            )
        )
        base_request = request_skin_core_bases(
            core,
            source,
            scene=context.scene,
            async_server=async_server,
        )
    return _finish_direct_skin_core_generation(
        context,
        source,
        core,
        voxel_size,
        base_request,
        custom_face_mode=custom_face_mode,
        async_server=async_server,
    )


def _add_direct_funnel_to_master(master: Object, funnel: Object) -> None:
    """Union a green funnel into the master while retaining both materials."""
    # Do this immediately before the Boolean rather than recoloring the master
    # afterward: TRANSFER preserves the green funnel faces in the joined mesh.
    assign_funnels_material(funnel.object)
    scene = bpy.context.scene
    had_retry_setting = DIRECT_BOOLEAN_RETRY_SCENE_KEY in scene
    original_retry_setting = scene.get(DIRECT_BOOLEAN_RETRY_SCENE_KEY, False)
    scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = False
    try:
        try:
            master.add_with_material_transfer(funnel)
            if master.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
        except Exception:
            voxel_size = get_master_voxel_size(scene.master_quality, master)
            logger.warning(
                "Could not add Direct top funnel %s to original master %s; "
                "voxel-remeshing only the master with quality=%s "
                "voxel_size=%.6f and trying again",
                funnel.name,
                master.name,
                scene.master_quality,
                voxel_size,
                exc_info=True,
            )
            master.apply_modifier(build_voxel_modifier(voxel_size))
            master.add_with_material_transfer(funnel)
            if master.has_empty_boolean:
                raise Exception("Boolean modifier without target failed")
    finally:
        if had_retry_setting:
            scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = original_retry_setting
        elif DIRECT_BOOLEAN_RETRY_SCENE_KEY in scene:
            del scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY]


def _boolean_union_direct_funnel_batch(
    funnels: list[Object],
    name: str,
) -> Object:
    """Boolean-union funnels before applying the batch to its destination."""
    if not funnels:
        raise ValueError("Cannot union an empty Direct funnel batch")

    combined = funnels[0]
    combined.name = name
    for funnel in funnels[1:]:
        _boolean_add(combined, funnel)
        funnel.remove()
    return combined


def _extend_direct_funnel_top_for_remesh(funnel: Object) -> None:
    top_faces = funnel.select_limit_flat_faces(max_co=True)
    if top_faces <= 0:
        raise RuntimeError(
            f"Could not find the top face of Direct funnel {funnel.name}"
        )
    funnel.move_selected(DIRECT_FUNNEL_REMESH_TOP_EXTENSION)


def _restore_direct_funnel_max_z(
    funnel: Object,
    *,
    max_z: float,
) -> None:
    center = funnel.center_coords
    funnel.cut_plane(
        mathutils.Vector((0.0, 0.0, 1.0)),
        mathutils.Vector((center.x, center.y, max_z)),
    )
    funnel.recalculate_normals()


def _remesh_direct_top_funnel_before_clearance(
    funnel: Object,
    voxel_size: float,
) -> float:
    """Remesh with an extended top and return its untouched maximum Z."""
    funnel.apply_all_transforms()
    original_max_z = float(funnel.max_z)
    _extend_direct_funnel_top_for_remesh(funnel)
    funnel.apply_modifier(build_voxel_modifier(voxel_size))
    funnel.smooth_geometry(factor=0.5, repeat=5)
    logger.info(
        "Pre-remeshed Direct top funnel %s with its top extended before "
        "undercut clearance: voxel_size=%.6f original_max_z=%.6f",
        funnel.name,
        voxel_size,
        original_max_z,
    )
    return original_max_z


def _clear_direct_top_funnel_undercuts(
    funnel: Object,
    *,
    split_plane_specs: list[list[list[float]]],
    target_retry_voxel_size: float,
    original_max_z: float,
    split_plane_overtravel: float,
    locked_extraction_paths: dict,
):
    """Clear one Direct funnel batch and restore only its original maximum Z."""
    scene = bpy.context.scene
    funnel.apply_all_transforms()

    extraction_mode = getattr(
        scene,
        "clear_undercuts_mode",
        "EASY_EXTRACTION",
    )
    task = begin_clear_undercuts(
        target_object=funnel,
        bidirectional=True,
        voxel_size=get_undercuts_voxel_size(scene.undercuts_quality, funnel),
        target_retry_voxel_size=target_retry_voxel_size,
        target_point=mathutils.Vector((0.0, 0.0, 0.0)),
        plane_direction=mathutils.Vector((1.0, 0.0, 0.0)),
        progress_callback=lambda _label: breathe_viewport(bpy.context),
        ui_refresh_callback=lambda: breathe_viewport(bpy.context),
        split_plane_specs=split_plane_specs,
        boundary_plane_specs=[bottom_reference_plane(funnel)],
        easy_extraction=extraction_mode == "EASY_EXTRACTION",
        precise_cost=extraction_mode == "PRECISE",
        restrict_bottom_extraction=True,
        split_plane_overtravel_override=split_plane_overtravel,
        locked_extraction_paths=locked_extraction_paths,
        display_extraction_directions=False,
    )
    return task.then(
        lambda result: (
            _restore_direct_funnel_max_z(
                funnel,
                max_z=original_max_z,
            )
            or result
        )
    )


def _prepare_direct_top_funnel_steps(
    top_diameter: float,
    bottom_diameter: float,
    thickness: float,
    split_plane_specs: list[list[list[float]]],
) -> None:
    """Create the inner master funnels and thicker box-side duplicates."""
    funnel_cylinders = _direct_top_funnel_cylinders()
    if not funnel_cylinders:
        raise RuntimeError("No cylinder funnels were returned for the Direct mold")

    master = _direct_original_master()
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        raise RuntimeError("No box object found")
    box = Object(box_raw)
    inner_funnels = []
    outer_funnels = []
    for funnel in funnel_cylinders:
        inner_funnel, outer_funnel = _prepare_direct_funnel_pair(
            funnel,
            thickness=thickness,
            top_diameter=top_diameter,
            bottom_diameter=bottom_diameter,
        )
        inner_funnels.append(inner_funnel)
        outer_funnels.append(outer_funnel)

    combined_inner_funnels = _boolean_union_direct_funnel_batch(
        inner_funnels,
        "direct_top_funnels",
    )
    combined_outer_funnels = _boolean_union_direct_funnel_batch(
        outer_funnels,
        "direct_top_funnels_direct_box_outer",
    )

    extraction_mode = getattr(
        bpy.context.scene,
        "clear_undercuts_mode",
        "EASY_EXTRACTION",
    )
    easy_extraction = extraction_mode == "EASY_EXTRACTION"
    precise_cost = extraction_mode == "PRECISE"
    master_paths = load_direct_undercut_paths(
        master.object,
        split_plane_specs,
        easy_extraction=easy_extraction,
        precise_cost=precise_cost,
        restrict_bottom_extraction=True,
    )
    if not master_paths:
        logger.info(
            "Direct master has no matching stored extraction paths; calculating "
            "them from the master before clearing top funnels"
        )
        master_paths = yield _begin_plan_and_store_direct_undercut_paths(
            master,
            split_plane_specs,
            restrict_bottom_extraction=True,
        )

    funnel_voxel_size = get_box_voxel_size(
        bpy.context.scene.box_quality,
        box,
    )
    outer_original_max_z = _remesh_direct_top_funnel_before_clearance(
        combined_outer_funnels,
        funnel_voxel_size,
    )
    inner_original_max_z = _remesh_direct_top_funnel_before_clearance(
        combined_inner_funnels,
        funnel_voxel_size,
    )

    yield _clear_direct_top_funnel_undercuts(
        combined_outer_funnels,
        split_plane_specs=split_plane_specs,
        target_retry_voxel_size=funnel_voxel_size,
        original_max_z=outer_original_max_z,
        split_plane_overtravel=(
            DIRECT_TOP_FUNNEL_UNDERCUT_OVERTRAVEL + thickness
        ),
        locked_extraction_paths=master_paths,
    )
    yield _clear_direct_top_funnel_undercuts(
        combined_inner_funnels,
        split_plane_specs=split_plane_specs,
        target_retry_voxel_size=funnel_voxel_size,
        original_max_z=inner_original_max_z,
        split_plane_overtravel=DIRECT_TOP_FUNNEL_UNDERCUT_OVERTRAVEL,
        locked_extraction_paths=master_paths,
    )
    _add_direct_funnel_to_master(master, combined_inner_funnels)
    combined_inner_funnels.remove()


def begin_prepare_direct_top_funnels(
    top_diameter: float,
    bottom_diameter: float,
    thickness: float,
    split_plane_specs: list[list[list[float]]],
):
    sequence = BackgroundTaskSequence(
        _prepare_direct_top_funnel_steps(
            top_diameter,
            bottom_diameter,
            thickness,
            split_plane_specs,
        )
    )
    sequence.redraw_interval = 0.1
    return sequence


def prepare_direct_top_funnels(
    top_diameter: float,
    bottom_diameter: float,
    thickness: float,
    split_plane_specs: list[list[list[float]]],
) -> None:
    finish_task_sync(
        begin_prepare_direct_top_funnels(
            top_diameter,
            bottom_diameter,
            thickness,
            split_plane_specs,
        )
    )


def _direct_volume_extension_attachment(
    box: Object,
    min_z: float,
    max_z: float,
    *,
    attachment_z: float | None = None,
) -> mathutils.Vector:
    section_points = []
    matrix_world = box.matrix_world
    normal_matrix = box.inverse_transpose_matrix_world.to_3x3()
    with BMeshObj(box, repair_winding=True) as bm:
        for face in bm.faces:
            world_coords = [matrix_world @ vert.co for vert in face.verts]
            face_min_z = min(co.z for co in world_coords)
            face_max_z = max(co.z for co in world_coords)
            if (
                face_max_z < min_z + DIRECT_Z_TRIM_TOLERANCE
                or face_min_z > max_z - DIRECT_Z_TRIM_TOLERANCE
            ):
                continue
            world_normal = (normal_matrix @ face.normal).normalized()
            if abs(world_normal.z) > 0.9:
                continue
            section_zs = (
                (attachment_z,) if attachment_z is not None else (min_z, max_z)
            )
            section_points.extend(
                co
                for co in world_coords
                if any(
                    abs(co.z - section_z) <= DIRECT_Z_TRIM_TOLERANCE
                    for section_z in section_zs
                )
            )
            for edge in face.edges:
                start = matrix_world @ edge.verts[0].co
                end = matrix_world @ edge.verts[1].co
                delta_z = end.z - start.z
                if abs(delta_z) <= DIRECT_Z_TRIM_TOLERANCE:
                    continue
                for section_z in section_zs:
                    factor = (section_z - start.z) / delta_z
                    if -DIRECT_Z_TRIM_TOLERANCE <= factor <= (
                        1 + DIRECT_Z_TRIM_TOLERANCE
                    ):
                        section_points.append(start.lerp(end, factor))

    if not section_points:
        raise RuntimeError(
            "Could not find a Direct mold side face touching the volume "
            "extension section"
        )
    min_x = min(point.x for point in section_points)
    outer_points = [
        point
        for point in section_points
        if abs(point.x - min_x) <= DIRECT_Z_TRIM_TOLERANCE
    ]
    return mathutils.Vector(
        (
            min_x,
            (min(point.y for point in outer_points) + max(point.y for point in outer_points))
            / 2,
            (min(point.z for point in outer_points) + max(point.z for point in outer_points))
            / 2,
        )
    )


def _verify_direct_volume_extension_overlap(box: Object, extension: Object) -> None:
    overlap = extension.duplicate("_overlap_check")
    try:
        overlap &= box
        overlap_volume = overlap.volume
    finally:
        overlap.remove()
    if overlap_volume <= DIRECT_VOLUME_EXTENSION_OVERLAP_EPSILON:
        raise RuntimeError(
            "Direct mold volume extension does not overlap the mold box"
        )


def _verify_direct_volume_extension_placement(
    box: Object,
    extension: Object,
    *,
    attachment_x: float,
    attachment_overlap: float,
    expected_min_z: float,
    expected_max_z: float,
) -> None:
    tolerance = DIRECT_VOLUME_EXTENSION_PLACEMENT_TOLERANCE
    expected_max_x = attachment_x + attachment_overlap
    if abs(extension.max_x - expected_max_x) > tolerance:
        raise RuntimeError(
            "Direct mold volume extension overlap does not match half the "
            "mold thickness"
        )
    if (
        abs(extension.min_z - expected_min_z) > tolerance
        or abs(extension.max_z - expected_max_z) > tolerance
    ):
        raise RuntimeError(
            "Direct mold volume extension does not match its target Z section"
        )
    _verify_direct_volume_extension_overlap(box, extension)


def _direct_casting_volume_text_item(casting_volume: float) -> dict:
    return {
        "kind": "text",
        "name": "direct_casting_volume_text",
        "text": f"{casting_volume:.0f} ml",
        "size": MOLD_LABEL_TEXT_SIZE,
        "depth": 2.0,
        "font_identifier": "BFONT",
        "sharp_remesh_level": 8,
    }


def add_direct_casting_volume_extension(
    volume_text=None,
    *,
    casting_volume: float | None = None,
) -> Object | None:
    if is_lite_tier():
        return None
    box_raw = bpy.data.objects.get("box")
    if box_raw is None or box_raw.type != "MESH":
        logger.debug("Skipping Direct mold volume extension because box is missing")
        if volume_text is not None and _object_exists(volume_text):
            volume_text.remove()
        return None

    box = Object(box_raw)
    try:
        box.apply_all_transforms()
        original_box_min_x = box.min_x
        scene = bpy.context.scene
        direct_mold_opening = resolve_direct_mold_opening(
            getattr(scene, "mold_type_preview", ""),
            getattr(scene, "direct_mold_opening", "base_open"),
        )
        open_base_mode = direct_mold_opening == "base_open"
        if open_base_mode:
            extension_max_z = box.max_z
            extension_min_z = extension_max_z - DIRECT_VOLUME_EXTENSION_HEIGHT
            attachment_z = extension_max_z
        else:
            extension_min_z = box.min_z
            extension_max_z = extension_min_z + DIRECT_VOLUME_EXTENSION_HEIGHT
            attachment_z = extension_min_z
        attachment = _direct_volume_extension_attachment(
            box,
            extension_min_z,
            extension_max_z,
            attachment_z=attachment_z,
        )
        direct_mold_thickness = max(
            float(getattr(bpy.context.scene, "direct_mold_thickness", 3.5)),
            0.0,
        )
        attachment_overlap = (
            direct_mold_thickness * DIRECT_VOLUME_EXTENSION_OVERLAP_FACTOR
        )
        if attachment_overlap <= DIRECT_VOLUME_EXTENSION_OVERLAP_EPSILON:
            raise RuntimeError("Direct mold thickness is zero")
        if casting_volume is None:
            casting_volume = calculate_casting_volume()
        bpy.context.scene.casting_volume_ml = casting_volume
        if volume_text is None:
            volume_text = request_watermark_mesh(
                _direct_casting_volume_text_item(casting_volume)
            )
        if open_base_mode:
            # Enter from below and retain a 0.5 mm roof so the label is
            # engraved into the top extension's bottom face.
            text_min_z = extension_min_z - 0.4
            text_max_z = extension_max_z - 0.5
        else:
            text_min_z = extension_min_z + 0.5
            text_max_z = extension_max_z + 0.4
        volume_text.scale_to(text_max_z - text_min_z, axis=2)
        volume_text.rotate_whole(
            mathutils.Matrix.Rotation(math.radians(270), 4, "Z")
        )
        if open_base_mode:
            volume_text.rotate_whole(
                mathutils.Matrix.Rotation(math.radians(180), 4, "X")
            )
        direct_text_min_x = (
            attachment.x - WEIGHT_TEXT_EXTENSION_PADDING - volume_text.width
        )
        text_min_x, text_center_y = _add_weight_text_extension(
            box,
            volume_text,
            attachment.y,
            min_z=extension_min_z,
            max_z=extension_max_z,
            attachment_min_x=attachment.x,
            text_min_x=direct_text_min_x,
            attachment_overlap=attachment_overlap,
            extension_name="direct_volume_text_extension",
            before_union_callback=lambda extension, _plan: (
                _verify_direct_volume_extension_placement(
                    box,
                    extension,
                    attachment_x=attachment.x,
                    attachment_overlap=attachment_overlap,
                    expected_min_z=extension_min_z,
                    expected_max_z=extension_max_z,
                )
            ),
        )
        volume_text.translate_whole(
            mathutils.Vector(
                (
                    text_min_x - volume_text.min_x,
                    text_center_y - volume_text.min_y - volume_text.depth / 2,
                    text_min_z - volume_text.min_z,
                )
            )
        )
        box -= volume_text
        if box.has_empty_boolean:
            raise Exception("Direct mold volume text Boolean failed")
        logger.info(
            "Added Direct mold casting-volume extension: volume=%.0f ml "
            "placement=%s height=%.2f overlap=%.2f min_x=%.2f->%.2f",
            casting_volume,
            "top" if open_base_mode else "bottom",
            DIRECT_VOLUME_EXTENSION_HEIGHT,
            attachment_overlap,
            original_box_min_x,
            box.min_x,
        )
    except Exception:
        logger.debug(
            "Skipping Direct mold casting-volume extension after a best-effort "
            "placement failure",
            exc_info=True,
        )
    finally:
        if volume_text is not None and _object_exists(volume_text):
            volume_text.remove()
    return box


def add_components_to_box(volume_text=None, *, casting_volume=None):
    box_raw = bpy.data.objects.get("box")
    if box_raw is None:
        if volume_text is not None and _object_exists(volume_text):
            volume_text.remove()
        return None

    box = Object(box_raw)
    box.select()
    box.apply_all_transforms()

    components = []
    for obj in tuple(bpy.data.objects):
        if obj == box_raw or obj.type != "MESH":
            continue
        object_name = obj.name.lower()
        if any(marker in object_name for marker in DIRECT_BOX_COMPONENT_NAME_MARKERS):
            components.append(Object(obj))

    funnel_components = []
    other_components = []
    for component in components:
        component.apply_all_transforms()
        component_name = component.name.lower()
        if any(
            marker in component_name for marker in ("funnel", "funneler", "deposit")
        ):
            funnel_components.append(component)
        else:
            other_components.append(component)

    # Add the box-side funnel shells individually while the box is still whole.
    # The patron is subtracted later, after the box has been split into parts.
    for funnel_component in funnel_components:
        assign_moldbox_material(funnel_component.object)
        box.add_without_material_transfer(funnel_component)
        funnel_component.remove()

    for component in other_components:
        remesh_channel_casting_grip(component)
        box += component
        component.remove()

    if volume_text is None and casting_volume is None:
        return add_direct_casting_volume_extension() or box
    return add_direct_casting_volume_extension(
        volume_text,
        casting_volume=casting_volume,
    ) or box


def begin_add_components_to_box():
    def steps():
        if is_lite_tier():
            return add_components_to_box()
        casting_volume = calculate_casting_volume()
        volume_text = yield request_watermark_mesh_async(
            _direct_casting_volume_text_item(casting_volume)
        )
        try:
            return add_components_to_box(
                volume_text,
                casting_volume=casting_volume,
            )
        finally:
            if _object_exists(volume_text):
                volume_text.remove()

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def confirm_direct_mold_req(
    box_voxel_size: float = 1,
    box_thickness: float = BOX_THICKNESS,
    channel_width: float = 6,
    clamp_width: float = 5,
    clamp_depth: float = CLAMP_DEPTH,
    barrier_tolerance: float = BARRIER_TOLERANCE,
    n_splits: int = 2,
    pin_system_type: str = "PIN",
    clamp_pin_type: str = "barrier",
    screw_diameter: float | None = None,
):
    params = {
        "box_voxel_size": box_voxel_size,
        "box_thickness": box_thickness,
        "channel_width": channel_width,
        "clamp_width": clamp_width,
        "clamp_depth": clamp_depth,
        "barrier_tolerance": barrier_tolerance,
        "n_splits": n_splits,
        "pin_system_type": pin_system_type,
        "clamp_pin_type": clamp_pin_type,
    }
    if pin_system_type.upper() == "SCREW" and screw_diameter is not None:
        params["screw_diameter"] = screw_diameter
    response = request_server(
        f"{get_server_base_url()}{DIRECT_CONFIRM_MOLD_PATH}",
        ["box"],
        params=params,
    )
    imported_objects = import_server_response(response)
    return imported_objects


def confirm_direct_mold_req_async(
    box_voxel_size: float = 1,
    box_thickness: float = BOX_THICKNESS,
    channel_width: float = 6,
    clamp_width: float = 5,
    clamp_depth: float = CLAMP_DEPTH,
    barrier_tolerance: float = BARRIER_TOLERANCE,
    n_splits: int = 2,
    pin_system_type: str = "PIN",
    clamp_pin_type: str = "barrier",
    screw_diameter: float | None = None,
):
    params = {
        "box_voxel_size": box_voxel_size,
        "box_thickness": box_thickness,
        "channel_width": channel_width,
        "clamp_width": clamp_width,
        "clamp_depth": clamp_depth,
        "barrier_tolerance": barrier_tolerance,
        "n_splits": n_splits,
        "pin_system_type": pin_system_type,
        "clamp_pin_type": clamp_pin_type,
    }
    if pin_system_type.upper() == "SCREW" and screw_diameter is not None:
        params["screw_diameter"] = screw_diameter
    return request_server_async(
        f"{get_server_base_url()}{DIRECT_CONFIRM_MOLD_PATH}",
        ["box"],
        params=params,
        on_complete=import_server_response,
    )


def extra_confirm_direct_mold_req(
    box_voxel_size: float = 1,
    box_thickness: float = BOX_THICKNESS,
    channel_width: float = 6,
    clamp_width: float = 5,
    clamp_depth: float = CLAMP_DEPTH,
    barrier_tolerance: float = BARRIER_TOLERANCE,
    split_planes: str = "[]",
    horizontal_barrier_top_offset: float | None = None,
    horizontal_barrier_bottom_offset: float | None = None,
    barrier_bottom_trim_offset: float | None = None,
    barrier_reinforcement_reach_box_top: bool = False,
    pin_system_type: str = "PIN",
    clamp_pin_type: str = "barrier",
    screw_diameter: float | None = None,
    after_import=None,
    organic_split_planes: str = "[]",
):
    params = {
        "box_voxel_size": box_voxel_size,
        "box_thickness": box_thickness,
        "channel_width": channel_width,
        "clamp_width": clamp_width,
        "clamp_depth": clamp_depth,
        "barrier_tolerance": barrier_tolerance,
        "split_planes": split_planes,
        "pin_system_type": pin_system_type,
        "clamp_pin_type": clamp_pin_type,
    }
    if organic_split_planes != "[]":
        params["organic_split_planes"] = organic_split_planes
    if pin_system_type.upper() == "SCREW" and screw_diameter is not None:
        params["screw_diameter"] = screw_diameter
    if horizontal_barrier_top_offset is not None:
        params["horizontal_barrier_top_offset"] = horizontal_barrier_top_offset
    if horizontal_barrier_bottom_offset is not None:
        params["horizontal_barrier_bottom_offset"] = horizontal_barrier_bottom_offset
    if barrier_bottom_trim_offset is not None:
        params["barrier_bottom_trim_offset"] = barrier_bottom_trim_offset
    if barrier_reinforcement_reach_box_top:
        params["barrier_reinforcement_reach_box_top"] = True
    response = request_server(
        f"{get_server_base_url()}{EXTRA_DIRECT_CONFIRM_MOLD_PATH}",
        ["box"],
        params=params,
    )
    imported_objects = import_server_response(response)
    if after_import is not None:
        after_import()
    return imported_objects


def extra_confirm_direct_mold_req_async(
    box_voxel_size: float = 1,
    box_thickness: float = BOX_THICKNESS,
    channel_width: float = 6,
    clamp_width: float = 5,
    clamp_depth: float = CLAMP_DEPTH,
    barrier_tolerance: float = BARRIER_TOLERANCE,
    split_planes: str = "[]",
    horizontal_barrier_top_offset: float | None = None,
    horizontal_barrier_bottom_offset: float | None = None,
    barrier_bottom_trim_offset: float | None = None,
    barrier_reinforcement_reach_box_top: bool = False,
    pin_system_type: str = "PIN",
    clamp_pin_type: str = "barrier",
    screw_diameter: float | None = None,
    after_import=None,
    organic_split_planes: str = "[]",
):
    def import_and_finalize(response):
        imported_objects = import_server_response(response)
        if after_import is not None:
            after_import()
        return imported_objects

    params = {
        "box_voxel_size": box_voxel_size,
        "box_thickness": box_thickness,
        "channel_width": channel_width,
        "clamp_width": clamp_width,
        "clamp_depth": clamp_depth,
        "barrier_tolerance": barrier_tolerance,
        "split_planes": split_planes,
        "pin_system_type": pin_system_type,
        "clamp_pin_type": clamp_pin_type,
    }
    if organic_split_planes != "[]":
        params["organic_split_planes"] = organic_split_planes
    if pin_system_type.upper() == "SCREW" and screw_diameter is not None:
        params["screw_diameter"] = screw_diameter
    if horizontal_barrier_top_offset is not None:
        params["horizontal_barrier_top_offset"] = horizontal_barrier_top_offset
    if horizontal_barrier_bottom_offset is not None:
        params["horizontal_barrier_bottom_offset"] = horizontal_barrier_bottom_offset
    if barrier_bottom_trim_offset is not None:
        params["barrier_bottom_trim_offset"] = barrier_bottom_trim_offset
    if barrier_reinforcement_reach_box_top:
        params["barrier_reinforcement_reach_box_top"] = True

    return request_server_async(
        f"{get_server_base_url()}{EXTRA_DIRECT_CONFIRM_MOLD_PATH}",
        ["box"],
        params=params,
        on_complete=import_and_finalize,
    )


def _clear_companion_box_undercuts(
    context, *, split_plane_specs, boundary_plane_specs, locked_extraction_paths,
):
    """Clear the companion shell using the male base's frozen master paths."""
    if not locked_extraction_paths:
        raise RuntimeError("No master extraction paths available for the companion mold")
    raw = bpy.data.objects.get("box")
    if raw is None or raw.type != "MESH":
        raise RuntimeError("No companion mold box found for undercut clearance")
    box = Object(raw)
    voxel_size = get_undercuts_voxel_size(context.scene.master_quality, box)
    return begin_clear_undercuts(
        target_object=box, bidirectional=True,
        voxel_size=voxel_size, target_retry_voxel_size=voxel_size,
        split_plane_specs=split_plane_specs,
        boundary_plane_specs=boundary_plane_specs,
        locked_extraction_paths=locked_extraction_paths,
        horizontal_extraction=True,
        restrict_bottom_extraction=False,
        split_plane_overtravel_override=0.0,
        clearance_build_overtravel_override=0.25,
        display_extraction_directions=False,
        ui_refresh_callback=lambda: breathe_viewport(context),
    )


def iter_build_direct_automatic_mold_steps(
    context,
    *,
    async_server: bool = False,
    stage: str = "all",
    split_plane_specs_override: list[object] | None = None,
    locked_extraction_paths_override: dict | None = None,
    undercut_boundary_specs_override: list | None = None,
):
    if stage not in {"all", "build", "confirm"}:
        raise ValueError(f"Unsupported Direct mold stage: {stage}")

    ensure_direct_patron_backup()
    scene = context.scene
    # Saved scenes can retain the unfixed setting from another mold mode.
    scene.wing_join_patron = True
    from .base import clear_prepared_master_base_pins

    clear_prepared_master_base_pins()
    skin_core = bpy.data.objects.get("skin_core")
    skin_mode = getattr(scene, "mold_type_preview", "") == DIRECT_SKIN_MOLD_TYPE
    skin_core_ready = bool(
        skin_core is not None
        and skin_core.type == "MESH"
        and skin_core.get("moldboxer_skin_core", False)
    )
    skin_core_confirmed = bool(
        skin_core_ready
        and skin_core.get(SKIN_CORE_CONFIRMED_MARKER, False)
    )
    skin_core_wrapper = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
    skin_core_wrapper_ready = bool(
        skin_core_confirmed
        and skin_core_wrapper is not None
        and skin_core_wrapper.type == "MESH"
        and skin_core_wrapper.get(SKIN_CORE_WRAPPER_MARKER, False)
    )
    skin_inlet = bpy.data.objects.get(SKIN_INLET_NAME)
    skin_inlet_ready = bool(
        skin_core_wrapper_ready
        and skin_inlet is not None
        and skin_inlet.type == "MESH"
        and skin_inlet.get(SKIN_INLET_MARKER, False)
    )
    if (
        skin_mode
        and not skin_core_ready
    ):
        yield "Generating skin core", lambda: generate_direct_skin_core(
            context,
            async_server=async_server,
        )
        return True
    if skin_mode:
        remove_skin_master_half_preview()
    direct_mold_opening = (
        "base_open"
        if skin_mode
        else resolve_direct_mold_opening(
            getattr(scene, "mold_type_preview", ""),
            scene.direct_mold_opening,
        )
    )
    top_funnel_opening = direct_mold_opening == DIRECT_TOP_FUNNEL_OPENING
    direct_mold_thickness = float(scene.direct_mold_thickness)
    skin_core_type = resolve_direct_skin_core_type(scene)
    skin_core_is_multi_part = skin_core_type == "MULTI_PART"
    funnel_top_diameter = float(scene.direct_funnel_top_diameter)
    funnel_bottom_diameter = float(scene.direct_funnel_bottom_diameter)
    funnel_reference_height = float(scene.direct_funnel_reference_height)
    funnel_depth = float(scene.direct_funnel_depth)
    support_pilars = bool(scene.direct_support_pilars)
    clamp_pin_type = str(scene.clamp_pin_type).lower()
    clamp_width = float(scene.clamp_width)
    clamp_depth = float(scene.clamp_depth)
    clamp_tolerance = float(scene.clamp_tolerance)
    clamp_pin_system_type = "SCREW" if scene.clamp_screws else "PIN"
    clamp_screw_diameter = float(scene.clamp_screw_diameter)
    set_keep_silicone_split_planes_after_build(False, scene)
    state = {}
    original_settings = _scene_settings_snapshot(scene)
    original_access_guard = bool(scene.get("_moldboxer_access_guard", False))
    had_boolean_retry_setting = DIRECT_BOOLEAN_RETRY_SCENE_KEY in scene
    original_boolean_retry_setting = scene.get(DIRECT_BOOLEAN_RETRY_SCENE_KEY, False)
    had_split_plane_ui_hidden_setting = DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY in scene
    original_split_plane_ui_hidden_setting = scene.get(
        DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY,
        False,
    )

    try:
        scene["_moldboxer_access_guard"] = True
        scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = True
        if skin_mode and not skin_core_wrapper_ready:
            if not skin_core_confirmed:
                yield "Confirming skin core", lambda: confirm_skin_core(context)
            yield "Generating skin core wrapper", lambda: (
                begin_generate_skin_core_wrapper(context)
            )
        if skin_mode and not skin_inlet_ready:
            yield "Generating skin inlet", lambda: begin_generate_skin_inlet(
                context
            )
        _set_scene_settings_to_defaults(scene)
        scene.box_gap = scene.direct_mold_thickness
        scene.box_quality = DIRECT_MOLD_BOX_QUALITY
        scene.casting_feet = False
        scene.channels = support_pilars
        scene.channel_adjustment = "support"
        scene.channel_width = scene.direct_support_pilar_width
        scene.channel_depth = scene.direct_support_pilar_depth
        scene.clamp_pin_type = clamp_pin_type
        scene.clamp_width = clamp_width
        scene.clamp_depth = clamp_depth
        scene.clamp_tolerance = clamp_tolerance
        scene.funneler_offset = (
            DIRECT_FUNNELER_OFFSET
            if top_funnel_opening
            else clamp_depth
        )
        if top_funnel_opening:
            scene.funneler = "cylinder"
            scene.funneler_ref_height = funnel_reference_height
        else:
            scene.funneler_ref_height = DIRECT_OPEN_BASE_FUNNELER_REFERENCE_HEIGHT
        # Direct-printed mold boxes must retain their extraction geometry.
        scene.clear_extraction = False
        if split_plane_specs_override is not None:
            # Companion molds must use the original casting coordinate system.
            split_plane_specs = split_plane_specs_override
        elif stage == "confirm":
            split_plane_specs = stored_silicone_split_plane_specs(scene)
        else:
            direct_split_plane_specs(log_context="Automatic Mold before sync")
            sync_direct_split_planes_with_scene()
            split_plane_specs = direct_split_plane_specs(
                log_context="Automatic Mold server capture",
            )
        split_planes, organic_split_planes = split_specs_query_values(
            split_plane_specs
        )
        logger.info(
            "Automatic Mold captured %d direct split plane(s): split_planes=%s",
            len(split_plane_specs),
            split_planes,
        )
        # No modal or panel redraw may expose the editable plane geometry once
        # mold generation starts.  The guard also prevents panel draw timers
        # from recreating the planes after they are removed here.
        scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY] = True
        remove_direct_split_planes()
        remove_skin_base_reference_guide()
        if stage != "confirm":
            if skin_mode:
                yield "Preparing skin box target", lambda: state.__setitem__(
                    "skin_box_target",
                    create_skin_box_wrap_target(),
                )
                state["skin_box_target"].select()
            else:
                _select_direct_patron_for_box_generation()
            box_steps = iter_build_box_operator_steps(
                context,
                async_server=async_server,
                refresh_materials=False,
                channels_deposit_path=DIRECT_CHANNELS_DEPOSIT_PATH,
                defer_extraction_clearance=locked_extraction_paths_override is not None,
                bottom_cut_offset=DIRECT_BOX_BOTTOM_CUT_OFFSET,
                bottom_clean_height=(
                    direct_mold_thickness if top_funnel_opening else None
                ),
                funnel_depth=funnel_depth if top_funnel_opening else None,
                split_plane_specs=split_plane_specs,
                target_object=(
                    state.get("skin_box_target") if skin_mode else None
                ),
            )
            yield from _insert_top_funnel_bottom_extension_step(
                box_steps,
                top_funnel_opening,
            )
            if top_funnel_opening:
                yield "Shaping top funnels", lambda: (
                    shape_direct_top_funnels_for_editing(
                        funnel_top_diameter,
                        funnel_bottom_diameter,
                    )
                )
        if stage == "build":
            return
        if top_funnel_opening:
            yield "Preparing top funnels", lambda: begin_prepare_direct_top_funnels(
                funnel_top_diameter,
                funnel_bottom_diameter,
                direct_mold_thickness,
                split_plane_specs,
            )
        yield "Joining channels and supports", (
            begin_add_components_to_box if async_server else add_components_to_box
        )
        if locked_extraction_paths_override is not None:
            yield "Clearing base mold undercuts", lambda: _clear_companion_box_undercuts(
                context,
                split_plane_specs=split_plane_specs,
                boundary_plane_specs=undercut_boundary_specs_override or [],
                locked_extraction_paths=locked_extraction_paths_override,
            )
        yield "Generating clamps and barriers", lambda: (
            extra_confirm_direct_mold_req_async(
                channel_width=scene.direct_support_pilar_width,
                clamp_width=clamp_width,
                clamp_depth=clamp_depth,
                barrier_tolerance=clamp_tolerance,
                split_planes=split_planes,
                organic_split_planes=organic_split_planes,
                horizontal_barrier_top_offset=(
                    None if top_funnel_opening else clamp_depth
                ),
                horizontal_barrier_bottom_offset=(
                    DIRECT_TOP_FUNNEL_BOTTOM_EXTENSION
                    if top_funnel_opening
                    else None
                ),
                barrier_bottom_trim_offset=(
                    DIRECT_SKIN_BARRIER_BOTTOM_OFFSET if skin_mode else None
                ),
                barrier_reinforcement_reach_box_top=skin_mode,
                pin_system_type=clamp_pin_system_type,
                clamp_pin_type=clamp_pin_type,
                screw_diameter=clamp_screw_diameter,
                after_import=lambda: trim_nonvertical_direct_clamp_systems_to_box(
                    split_plane_specs
                ),
            )
            if async_server
            else extra_confirm_direct_mold_req(
                channel_width=scene.direct_support_pilar_width,
                clamp_width=clamp_width,
                clamp_depth=clamp_depth,
                barrier_tolerance=clamp_tolerance,
                split_planes=split_planes,
                organic_split_planes=organic_split_planes,
                horizontal_barrier_top_offset=(
                    None if top_funnel_opening else clamp_depth
                ),
                horizontal_barrier_bottom_offset=(
                    DIRECT_TOP_FUNNEL_BOTTOM_EXTENSION
                    if top_funnel_opening
                    else None
                ),
                barrier_bottom_trim_offset=(
                    DIRECT_SKIN_BARRIER_BOTTOM_OFFSET if skin_mode else None
                ),
                barrier_reinforcement_reach_box_top=skin_mode,
                pin_system_type=clamp_pin_system_type,
                clamp_pin_type=clamp_pin_type,
                screw_diameter=clamp_screw_diameter,
                after_import=lambda: trim_nonvertical_direct_clamp_systems_to_box(
                    split_plane_specs
                ),
            )
        )
        yield "Applying clamp booleans", lambda: (
            apply_direct_clamp_booleans_after_server_import(
                screw_mode=clamp_pin_system_type == "SCREW"
            )
        )
        yield "Joining clamps to box", lambda: prepare_direct_printed_mold_for_split(
            split_plane_specs
        )
        if skin_mode and not skin_core_attachment_matches_box_top(skin_core_type):
            yield "Generating skin core attachment", lambda: (
                request_skin_core_attachment(
                    context,
                    async_server=async_server,
                    core_type=skin_core_type,
                )
            )
        if skin_mode and skin_core_is_multi_part:
            yield "Applying skin core pin clearance", lambda: (
                apply_skin_core_pin_box_clearance(context)
            )

        def split_mold_system():
            box = Object(bpy.data.objects.get("box"))
            task = begin_split_object_by_direct_plane_specs(
                box,
                split_plane_specs,
                preserve_isolated_meshes=True,
            )

            def finish(parts):
                state["parts"] = parts
                apply_direct_split_barrier_grid(
                    parts,
                    split_plane_specs,
                    male_on_top_for_horizontal=(
                        direct_mold_opening == "base_open"
                    ),
                )
                return parts

            return task.then(finish)

        yield "Splitting mold system", split_mold_system

        def finalize_mold_parts():
            additional_cutters = None
            if skin_mode:
                wrapper_raw = bpy.data.objects.get(SKIN_CORE_WRAPPER_NAME)
                inlet_raw = bpy.data.objects.get(SKIN_INLET_NAME)
                if (
                    wrapper_raw is None
                    or wrapper_raw.type != "MESH"
                    or not bool(
                        wrapper_raw.get(SKIN_CORE_WRAPPER_MARKER, False)
                    )
                ):
                    raise RuntimeError(
                        "Skin mold finalization requires skin_wrap"
                    )
                if (
                    inlet_raw is None
                    or inlet_raw.type != "MESH"
                    or not bool(inlet_raw.get(SKIN_INLET_MARKER, False))
                ):
                    raise RuntimeError(
                        "Skin mold finalization requires skin_inlet"
                    )
                additional_cutters = [Object(wrapper_raw), Object(inlet_raw)]
            state["parts"] = finalize_direct_printed_mold_parts(
                state["parts"],
                additional_cutters=additional_cutters,
            )
            if skin_mode:
                remove_skin_box_wrap_sources()
                state.pop("skin_box_target", None)

        yield "Finalizing mold parts", finalize_mold_parts
        yield "Generating clips", lambda: create_direct_mold_clips(scene)
        yield "Spacing patron", lambda: space_direct_mold_patron(state["parts"])
    finally:
        _restore_scene_settings(scene, original_settings)
        scene["_moldboxer_access_guard"] = original_access_guard
        if had_boolean_retry_setting:
            scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = original_boolean_retry_setting
        else:
            del scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY]
        if had_split_plane_ui_hidden_setting:
            scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY] = (
                original_split_plane_ui_hidden_setting
            )
        elif DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY in scene:
            del scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY]
    return False


def build_direct_automatic_mold(context):
    steps = iter_build_direct_automatic_mold_steps(context)
    while True:
        try:
            _label, step = next(steps)
        except StopIteration as completed:
            return bool(completed.value)
        finish_task_sync(step())


def iter_build_direct_mold_steps(context, *, async_server: bool = False):
    """Build editable Direct mold components without merging them into the box."""
    yield from iter_build_direct_automatic_mold_steps(
        context,
        async_server=async_server,
        stage="build",
    )


def build_direct_mold(context):
    for _label, step in iter_build_direct_mold_steps(context):
        finish_task_sync(step())


def iter_confirm_direct_mold_steps(context, *, async_server: bool = False):
    """Finish a Direct mold from its user-edited box, pillars, and funnels."""
    yield from iter_build_direct_automatic_mold_steps(
        context,
        async_server=async_server,
        stage="confirm",
    )


def confirm_direct_mold(context):
    for _label, step in iter_confirm_direct_mold_steps(context):
        step()
