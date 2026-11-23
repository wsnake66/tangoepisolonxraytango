# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender-side orchestration for the slip-casting confirmation stage.

Geometry payload transport is delegated to ``components.server``, which sends
data through the external Moldboxer Worker. This module must remain free of
direct HTTP clients and in-process imports of Worker implementation modules.
"""

import json
import re
import mathutils  # type: ignore
import logging

from ..slip_casting_base_pairs import slip_casting_uses_base
import bpy  # type: ignore
import bmesh  # type: ignore
import math
import time
from collections.abc import Callable, Iterator
from ..background_worker import BackgroundTaskSequence, finish_task_sync


from .server import import_server_response, request_server, request_server_async
from .box import SLIP_CASTING_HALF_BOX_WRAPPER_NAME, generate_slip_casting_half_box_wrapper
from ..plaster_mix import plaster_mix_engraving
from ..silicone_mix import silicone_mix_engraving
from ..mold_types import is_silicone_multipart_type, is_slip_casting_type, slip_casting_funnels_on_top


from ..bl_utils import BMeshObj
from ..object import Object, SPLIT_PLANE_CUT_HALF_THICKNESS, remove_unused_meshes
from ..split_specs import split_spec_point_normal, split_specs_query_values
from ..environment import get_server_base_url
from .silicone_mold import (
    build_silicone_mold_preview,
    hide_silicone_mold_preview,
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
    add_channels,
    recut_channels,
    set_support_pilars_hidden,
)
from .geometry_adapter import (
    locking_clamp_plan_with_worker,
    plan_casting_box_intersection_bands_with_worker,
    repeat_object_mesh_grid_with_worker,
)
from .slip_casting_multipart_server import (
    request_multipart_plan,
    plan_slip_casting_movements,
    plan_slip_casting_split_base_subtractions_with_server,
    plan_slip_casting_split_base_locking_geometry_with_server,
)
from .splitter import (
    _remove_pre_split_isolated_meshes,
    _remesh_barrier_from_scene,
    _subtract_base_female_locking_geometry,
    add_clamps_to_box,
)
from .direct_mold import (
    _direct_plane_system_names,
    apply_direct_split_barrier_grid,
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
from .direct_split_execution import (
    SPLIT_SECTION_SIDES_KEY,
    begin_split_object_by_direct_plane_specs,
)
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
    assign_split_base_keys_material,
    assign_plaster_mold_material,
    refresh_generated_object_materials,
    refresh_viewport_material_display,
)
from ..operator_access import has_pro_or_trial_server_access, is_lite_tier
from ..patron_lifecycle import (
    finalize_master_as_patron,
    get_master_for_base_operations,
    hide_working_patron,
    reveal_working_patron,
)
from ..progress import force_viewport_redraw
from ..voxel_size import get_box_boolean_retry_voxel_size, get_box_voxel_size
from ..constants import WING_BASE_HEIGHT
from ..modifiers import (
    build_sharp_modifier,
    diff_no_material_transfer_mod,
    intersect_mod,
    union_no_material_transfer_mod,
)
from ..primitives import (
    create_cube_primitive,
    create_cylinder_primitive,
    create_uv_sphere_primitive,
)

logger = logging.getLogger(__name__)
DEBUG_STOP_BEFORE_GAP_SUBTRACTION = False
SLIP_CASTING_CONFIRM_ENDPOINT = "/slip-casting/confirm-silicone-mold/"
CLAMP_LOCKER_OBJECT_NAME = "clamp_lockers"
BASE_CLAMP_LOCKER_OBJECT_NAME = "base_lockers"
CLAMP_LOCKER_HEIGHT_SPACING_MM = 30.0
MIN_CLAMP_LOCKERS_PER_MOLD_PART = 2
DEFAULT_LOCKER_CLIP_COUNT = 6
ENABLE_OPTIMIZED_CASTING_COMPONENT_CLEANUP = False
DEBUG_SKIP_OPTIMIZED_CASTING_BOX_FILTER = False
CONFIRM_SKIP_REDRAW_STEPS = {
    "Preparing mold box",
    "Generating mold box",
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
SLIP_CASTING_SPLIT_OFFSET_APPLIED_KEY = (
    "_moldboxer_slip_casting_split_offset_applied"
)
SLIP_CASTING_SPLIT_BASE_GAP_PREFIX = "split_base_gap_cube_"
SLIP_CASTING_PLASTER_MOLD_NAME = "plaster_mold"
SLIP_CASTING_PLASTER_MOLD_PART_PREFIX = "plaster_mold_part_"
SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX = "slip_casting_preview_male_pin_"
SLIP_CASTING_EDGE_PIN_PREFIX = "slip_casting_edge_pin_"
SLIP_CASTING_EDGE_PIN_MALE_PREFIX = f"{SLIP_CASTING_EDGE_PIN_PREFIX}male_"
SLIP_CASTING_EDGE_PIN_FEMALE_PREFIX = f"{SLIP_CASTING_EDGE_PIN_PREFIX}female_"
SLIP_CASTING_EDGE_PIN_CLIPPER_NAME = "_slip_casting_edge_pin_original_box_clipper"
SLIP_CASTING_PREVIEW_MALE_PIN_ALIGNED_KEY = (
    "_moldboxer_slip_casting_preview_male_pin_aligned"
)
SLIP_CASTING_EDGE_PIN_ALIGNED_KEY = "_moldboxer_slip_casting_edge_pin_aligned"
SLIP_CASTING_VASE_BASE_KEY = "moldboxer_slip_casting_vase_base"
SLIP_CASTING_VASE_BASE_ROLE_KEY = "moldboxer_slip_casting_vase_base_role"
SLIP_CASTING_VASE_BASE_FLIPPED_KEY = (
    "moldboxer_slip_casting_vase_base_flipped"
)
SLIP_CASTING_MALE_VASE_BASE_TOP_CUT_MM = 0.5


def _mold_mix_engraving(scene):
    return (silicone_mix_engraving(scene) if is_silicone_multipart_type(scene.mold_type_preview)
            else plaster_mix_engraving(scene))


def _silicone_key_operand_diameter(barrier):
    """Measure tube thickness along its plane normal after server fitting."""
    import numpy as np
    raw = barrier.object
    points = np.array([tuple(raw.matrix_world @ v.co) for v in raw.data.vertices])
    if len(points) < 3:
        return 0.1
    centered = points - points.mean(axis=0)
    _, axes = np.linalg.eigh(np.einsum("ni,nj->ij", centered, centered))
    projected = np.einsum("ni,i->n", centered, axes[:, 0])
    return max(float(projected.max() - projected.min()), 0.1)


def _split_base_key_settings(scene):
    if is_silicone_multipart_type(scene.mold_type_preview):
        thickness = max(float(scene.box_gap), 0.0)
        if scene.channels:
            # The centerline sits halfway through thickness + channel depth.
            # Leave 1 mm to each radial side and each channel sidewall.
            limit = min(thickness,
                        thickness + max(float(scene.channel_depth), 0.0) - 2.0,
                        max(float(scene.channel_width), 0.0) - 2.0)
        else:
            # Without channels leave 0.5 mm on each side of the mold wall.
            limit = thickness - 1.0
        diameter = min(max(float(scene.silicone_split_base_key_diameter), 0.0),
                       max(limit, 0.0))
        return (diameter, scene.silicone_split_base_key_tolerance, "CENTERED")
    return (scene.split_base_pin_diameter, scene.plaster_locking_tolerance,
            getattr(scene, "plaster_locking_pin_type", "CENTERED"))


def limited_split_base_pin_diameter(
    requested_diameter: float,
    mold_thickness: float,
) -> float:
    return min(
        max(float(requested_diameter), 0.0),
        max(float(mold_thickness) / 2.0, 0.0),
    )


def _mesh_object_by_name(name: str) -> Object | None:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        return None
    return Object(obj)


def _slip_casting_plaster_mold_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                obj.name.lower() == SLIP_CASTING_PLASTER_MOLD_NAME
                or obj.name.lower().startswith(
                    SLIP_CASTING_PLASTER_MOLD_PART_PREFIX
                )
            )
        ),
        key=lambda obj: obj.name.lower(),
    )


def _slip_casting_male_vase_base_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and bool(obj.get(SLIP_CASTING_VASE_BASE_KEY, False))
            and str(obj.get(SLIP_CASTING_VASE_BASE_ROLE_KEY, "")).upper()
            == "MALE"
        ),
        key=lambda part: part.name.lower(),
    )


def _rename_slip_casting_mold_preview() -> Object | None:
    plaster_mold = _mesh_object_by_name(SLIP_CASTING_PLASTER_MOLD_NAME)
    if plaster_mold is not None:
        assign_plaster_mold_material(plaster_mold.object)
        return plaster_mold
    silicone_mold = _mesh_object_by_name("silicone_mold")
    if silicone_mold is None:
        return None
    silicone_mold.name = SLIP_CASTING_PLASTER_MOLD_NAME
    assign_plaster_mold_material(silicone_mold.object)
    return silicone_mold


def _set_slip_casting_plaster_molds_visible(visible: bool) -> None:
    hidden = not bool(visible)
    for plaster_mold in _slip_casting_plaster_mold_objects():
        if visible:
            # Boolean and split stages can preserve stale/default material
            # slots. Reassign the dedicated plaster material at the point the
            # final pieces become visible so Solid/Material viewport shading
            # cannot fall back to Blender grey.
            assign_plaster_mold_material(plaster_mold.object)
        plaster_mold.object.hide_set(hidden)
        plaster_mold.object.hide_viewport = hidden
        plaster_mold.object.hide_render = hidden


def begin_slip_casting_split_system(
    split_plane_specs: list[list[list[float]]],
    split_base_gap_thickness: float,
):
    """Execute local mesh splits with server-planned crossing-gap cutters."""
    box = _mesh_object_by_name("box")
    if box is None:
        raise RuntimeError("No box object found for Slip Casting split")
    box = _remove_pre_split_isolated_meshes(box)

    casting_sources = pending_casting_boxes()
    casting_box = casting_sources[0] if len(casting_sources) == 1 else None
    if casting_box is not None:
        casting_box = _remove_pre_split_isolated_meshes(casting_box)

    master_base_sources = _master_base_objects()
    if len(master_base_sources) != 1:
        raise RuntimeError(
            "Slip Casting split requires exactly one unsplit master base"
        )
    master_base = master_base_sources[0]
    split_base_sources = _slip_casting_split_base_objects()
    preview_male_pin_sources = _slip_casting_preview_male_pin_objects()
    edge_pin_sources = _slip_casting_edge_pin_objects()
    plaster_mold = _rename_slip_casting_mold_preview()
    if plaster_mold is None:
        raise RuntimeError("No plaster mold found for Slip Casting split")
    # The preview is hidden during the early confirm stages. Blender's split
    # implementation enters Edit Mode to separate the Boolean result into
    # loose parts, which is forbidden for a hidden active object.
    _set_slip_casting_plaster_molds_visible(True)

    def steps():
        gap_cutter_plan = request_multipart_plan(
            "gap_candidates", plane_specs=split_plane_specs,
            distance=float(split_base_gap_thickness),
        )["cutters"] if split_base_sources else []
        boxes = yield begin_split_object_by_direct_plane_specs(
            box,
            split_plane_specs,
            preserve_isolated_meshes=True,
            output_name_prefix="box_part",
        )
        casting_boxes: list[Object] = []
        if casting_box is not None:
            casting_boxes = yield begin_split_object_by_direct_plane_specs(
                casting_box,
                split_plane_specs,
                preserve_isolated_meshes=True,
                output_name_prefix=PENDING_CASTING_BOX_NAME,
            )

        master_base_parts = yield begin_split_object_by_direct_plane_specs(
            master_base,
            split_plane_specs,
            preserve_isolated_meshes=True,
            output_name_prefix="master_base_part",
            plan_from_cuts=True,
        )

        plaster_mold_parts = yield begin_split_object_by_direct_plane_specs(
            plaster_mold,
            split_plane_specs,
            preserve_isolated_meshes=True,
            output_name_prefix="plaster_mold_part",
            plan_from_cuts=True,
        )

        split_base_parts: list[Object] = []
        split_base_gap_parts: list[Object] = []
        for split_base in split_base_sources:
            name_prefix = split_base.name.lower().split(".", 1)[0]
            gap_candidates = _create_split_base_gap_candidates(
                split_base,
                split_plane_specs,
                split_base_gap_thickness,
                cutter_plan=gap_cutter_plan,
            )
            try:
                parts = yield begin_split_object_by_direct_plane_specs(
                    split_base,
                    split_plane_specs,
                    preserve_isolated_meshes=True,
                    output_name_prefix=f"{name_prefix}_part",
                )
            except Exception:
                for _plane_index, gap_candidate in gap_candidates:
                    gap_candidate.remove()
                raise
            split_base_parts.extend(parts)
            kept_gaps = _keep_crossing_split_base_gap_candidates(gap_candidates, parts)
            own_plane = _split_base_own_plane_index(name_prefix, split_plane_specs)
            for gap_plane, gap in gap_candidates:
                if gap not in kept_gaps:
                    continue
                split_base_gap_parts.extend(
                    (yield from _prepare_split_base_gap_placements(
                        gap, own_plane, gap_plane, split_plane_specs))
                )

        preview_male_pin_parts: list[Object] = []
        for preview_male_pin in preview_male_pin_sources:
            own_plane_index = _preview_male_pin_own_plane_index(
                preview_male_pin.name,
                split_plane_specs,
            )
            if own_plane_index is None:
                raise RuntimeError(
                    "Could not resolve the source split plane for preview male "
                    f"pin {preview_male_pin.name}"
                )
            other_plane_indices = [
                plane_index
                for plane_index in range(len(split_plane_specs))
                if plane_index != own_plane_index
            ]
            if not other_plane_indices:
                preview_male_pin.object[SPLIT_SECTION_SIDES_KEY] = [
                    0
                ] * len(split_plane_specs)
                preview_male_pin.name = f"{preview_male_pin.name}_part_01"
                preview_male_pin_parts.append(preview_male_pin)
                continue
            preview_male_pin_parts.extend(
                (
                    yield begin_split_object_by_direct_plane_specs(
                        preview_male_pin,
                        [
                            split_plane_specs[plane_index]
                            for plane_index in other_plane_indices
                        ],
                        preserve_isolated_meshes=True,
                        section_plane_indices=other_plane_indices,
                        section_plane_count=len(split_plane_specs),
                        output_name_prefix=preview_male_pin.name,
                        # Small key fragments can lose a whole side to the cut
                        # gap. Route the surviving geometry instead of requiring
                        # both sides predicted by the zero-width plane planner.
                        plan_from_cuts=True,
                    )
                )
            )

        edge_pin_parts: list[Object] = []
        for edge_pin in edge_pin_sources:
            role_and_plane = _edge_pin_role_and_plane_index(
                edge_pin.name,
                split_plane_specs,
            )
            if role_and_plane is None:
                raise RuntimeError(
                    "Could not resolve the role/source plane for Edge pin "
                    f"{edge_pin.name}"
                )
            _pin_role, own_plane_index = role_and_plane
            other_plane_indices = [
                plane_index
                for plane_index in range(len(split_plane_specs))
                if plane_index != own_plane_index
            ]
            if not other_plane_indices:
                edge_pin.object[SPLIT_SECTION_SIDES_KEY] = [
                    0
                ] * len(split_plane_specs)
                edge_pin.name = f"{edge_pin.name}_part_01"
                edge_pin_parts.append(edge_pin)
                continue
            edge_pin_parts.extend(
                (
                    yield begin_split_object_by_direct_plane_specs(
                        edge_pin,
                        [
                            split_plane_specs[plane_index]
                            for plane_index in other_plane_indices
                        ],
                        preserve_isolated_meshes=True,
                        section_plane_indices=other_plane_indices,
                        section_plane_count=len(split_plane_specs),
                        output_name_prefix=edge_pin.name,
                    )
                )
            )

        _subtract_matching_female_barriers_from_edge_male_pins(
            edge_pin_parts,
            split_plane_specs,
        )

        apply_direct_split_barrier_grid(
            boxes,
            split_plane_specs,
            mirrored_parts=casting_boxes,
        )
        _subtract_base_female_locking_geometry(boxes, casting_boxes)

        logger.info(
            "Slip Casting split output: boxes=%d casting_boxes=%d "
            "split_bases=%d split_base_gap_cubes=%d master_base_parts=%d "
            "plaster_mold_parts=%d preview_male_pin_parts=%d "
            "edge_pin_parts=%d",
            len(boxes),
            len(casting_boxes),
            len(split_base_parts),
            len(split_base_gap_parts),
            len(master_base_parts),
            len(plaster_mold_parts),
            len(preview_male_pin_parts),
            len(edge_pin_parts),
        )
        return boxes

    return BackgroundTaskSequence(steps())


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


def _combined_object_bounds(objects: list[Object]) -> dict[str, float]:
    if not objects:
        raise ValueError("Cannot calculate bounds for an empty object collection")
    object_bounds = [_object_bounds(obj) for obj in objects]
    min_x = min(bounds["min_x"] for bounds in object_bounds)
    max_x = max(bounds["max_x"] for bounds in object_bounds)
    min_y = min(bounds["min_y"] for bounds in object_bounds)
    max_y = max(bounds["max_y"] for bounds in object_bounds)
    min_z = min(bounds["min_z"] for bounds in object_bounds)
    max_z = max(bounds["max_z"] for bounds in object_bounds)
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


def _master_base_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                obj.name.lower() in {"base", "master_base"}
                or obj.name.lower().startswith("master_base_part_")
            )
        ),
        key=lambda obj: obj.name.lower(),
    )


def _slip_casting_split_base_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith("split_base_")
            and not obj.name.lower().startswith(
                SLIP_CASTING_SPLIT_BASE_GAP_PREFIX
            )
        ),
        key=lambda obj: obj.name.lower(),
    )


def _slip_casting_split_base_gap_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith(
                SLIP_CASTING_SPLIT_BASE_GAP_PREFIX
            )
        ),
        key=lambda obj: obj.name.lower(),
    )


def _slip_casting_preview_male_pin_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith(
                SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX
            )
        ),
        key=lambda obj: obj.name.lower(),
    )


def _slip_casting_edge_pin_objects() -> list[Object]:
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith(SLIP_CASTING_EDGE_PIN_PREFIX)
        ),
        key=lambda obj: obj.name.lower(),
    )


def _split_master_base_plan_arguments(scene) -> dict:
    if is_silicone_multipart_type(getattr(scene, "mold_type_preview", "")):
        return {"silicone_multipart": True,
                "master_base_mode": getattr(scene, "slip_casting_master_base_mode", "ONE_PIECE")}
    # Preserve compatibility with existing servers for the default mode.
    if getattr(scene, "slip_casting_master_base_mode", "ONE_PIECE") == "PER_SPLIT":
        return {"master_base_mode": "PER_SPLIT"}
    return {}


def slip_casting_split_base_thickness(scene) -> float:
    """Match the server's pin-safe split-base extrusion length exactly."""
    plan = plan_slip_casting_split_base_locking_geometry_with_server(
        box_wall_thickness=scene.box_thickness,
        requested_pin_diameter=_split_base_key_settings(scene)[0],
        mold_thickness=scene.box_gap,
        **_split_master_base_plan_arguments(scene),
        plaster_locking_pin_type=getattr(
            scene,
            "plaster_locking_pin_type",
            "CENTERED",
        ),
    )
    return float(plan["split_base_thickness"])


def _split_base_own_plane_index(
    part_name: str,
    split_plane_specs: list[list[list[float]]],
) -> int | None:
    """Resolve a split-base part's source plane from its server system name."""
    normalized_name = part_name.lower().split(".", 1)[0]
    if not normalized_name.startswith("split_base_"):
        return None
    for plane_index, system_name in enumerate(
        _direct_plane_system_names(split_plane_specs)
    ):
        prefix = f"split_base_{system_name.lower()}"
        if normalized_name == prefix or normalized_name.startswith(
            (f"{prefix}_", f"{prefix}-")
        ):
            return plane_index
    return None


def _preview_male_pin_own_plane_index(
    part_name: str,
    split_plane_specs: list[list[list[float]]],
) -> int | None:
    match = re.match(
        rf"^{re.escape(SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX)}sp(\d+)_",
        part_name.lower(),
    )
    if match is None:
        return None
    plane_index = int(match.group(1)) - 1
    if plane_index < 0 or plane_index >= len(split_plane_specs):
        return None
    return plane_index


def _edge_pin_role_and_plane_index(
    part_name: str,
    split_plane_specs: list[list[list[float]]],
) -> tuple[str, int] | None:
    match = re.match(
        rf"^{re.escape(SLIP_CASTING_EDGE_PIN_PREFIX)}(male|female)_sp(\d+)_",
        part_name.lower(),
    )
    if match is None:
        return None
    plane_index = int(match.group(2)) - 1
    if plane_index < 0 or plane_index >= len(split_plane_specs):
        return None
    return match.group(1), plane_index


def _subtract_matching_female_barriers_from_edge_male_pins(
    edge_pin_parts: list[Object],
    split_plane_specs: list[list[list[float]]],
) -> int:
    """Trim Edge males with their source plane's female clamp barriers."""
    system_names = _direct_plane_system_names(split_plane_specs)
    female_barriers_by_plane: dict[int, list[Object]] = {}
    for plane_index, system_name in enumerate(system_names):
        expected_name = f"barrier_female_{system_name}".lower()
        female_barriers_by_plane[plane_index] = [
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                obj.name.lower() == expected_name
                or obj.name.lower().startswith(f"{expected_name}.")
            )
        ]

    subtraction_count = 0
    for pin in edge_pin_parts:
        role_and_plane = _edge_pin_role_and_plane_index(
            pin.name,
            split_plane_specs,
        )
        if role_and_plane is None or role_and_plane[0] != "male":
            continue
        for female_barrier in female_barriers_by_plane.get(
            role_and_plane[1],
            (),
        ):
            visibility = (
                female_barrier.object.hide_get(),
                female_barrier.object.hide_viewport,
                female_barrier.object.hide_render,
            )
            try:
                female_barrier.object.hide_set(False)
                female_barrier.object.hide_viewport = False
                female_barrier.object.hide_render = False
                pin.apply_boolean_modifier(
                    diff_no_material_transfer_mod,
                    target=female_barrier,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                subtraction_count += 1
                force_viewport_redraw()
            finally:
                hidden, hide_viewport, hide_render = visibility
                female_barrier.object.hide_set(hidden)
                female_barrier.object.hide_viewport = hide_viewport
                female_barrier.object.hide_render = hide_render
    logger.info(
        "Subtracted %d matching female barrier(s) from Edge male pin parts",
        subtraction_count,
    )
    return subtraction_count


def _split_base_geometry_own_plane_index(
    part_name: str,
    split_plane_specs: list[list[list[float]]],
) -> int | None:
    """Resolve regular and gap-fill split bases to their source plane."""
    own_plane_index = _split_base_own_plane_index(
        part_name,
        split_plane_specs,
    )
    if own_plane_index is not None:
        return own_plane_index

    normalized_name = part_name.lower().split(".", 1)[0]
    if not normalized_name.startswith(SLIP_CASTING_SPLIT_BASE_GAP_PREFIX):
        return None
    source_system_name = normalized_name[
        len(SLIP_CASTING_SPLIT_BASE_GAP_PREFIX) :
    ].split("_by_", 1)[0]
    for plane_index, system_name in enumerate(
        _direct_plane_system_names(split_plane_specs)
    ):
        if source_system_name == system_name.lower():
            return plane_index
    return None


def _prepare_slip_casting_edge_pin_clipper(original_box: Object) -> Object:
    existing = bpy.data.objects.get(SLIP_CASTING_EDGE_PIN_CLIPPER_NAME)
    if existing is not None:
        Object(existing).remove()
    clipper = original_box.duplicate("_edge_pin_original_box_clipper")
    clipper.name = SLIP_CASTING_EDGE_PIN_CLIPPER_NAME
    return clipper


def _clip_slip_casting_edge_pins_to_original_box_wrapper() -> int:
    """Restrict Edge pins to the untouched box wrapper before it is opened."""
    edge_pins = _slip_casting_edge_pin_objects()
    clipper_raw = bpy.data.objects.get(SLIP_CASTING_EDGE_PIN_CLIPPER_NAME)
    if not edge_pins:
        if clipper_raw is not None:
            Object(clipper_raw).remove()
        return 0
    if clipper_raw is None:
        raise RuntimeError("Slip Casting Edge pins require the original box wrapper")

    clipper = Object(clipper_raw)
    kept_count = 0
    try:
        for edge_pin in edge_pins:
            edge_pin.apply_boolean_modifier(
                intersect_mod,
                target=clipper,
                retry_remesh=build_sharp_modifier(8),
                retry_remesh_on="self",
            )
            force_viewport_redraw()
            if not edge_pin.object.data.polygons or edge_pin.volume <= 1e-6:
                edge_pin.remove()
                continue
            kept_count += 1
    finally:
        if clipper.object.name in bpy.data.objects:
            clipper.remove()

    logger.info(
        "Clipped %d Slip Casting Edge pin(s) to the original box wrapper",
        kept_count,
    )
    return kept_count


def _create_split_base_gap_candidates(
    split_base: Object,
    split_plane_specs: list[list[list[float]]],
    distance: float,
    *,
    cutter_plan: list[dict] | None = None,
) -> list[tuple[int, Object]]:
    """Keep the original base slices that can occupy translated split gaps."""
    own_plane_index = _split_base_own_plane_index(
        split_base.name,
        split_plane_specs,
    )
    if own_plane_index is None:
        logger.warning(
            "Skipping gap cubes for unrecognized Slip Casting split base %s",
            split_base.name,
        )
        return []

    thickness = float(distance)
    if thickness <= 0.0:
        return []

    system_names = _direct_plane_system_names(split_plane_specs)
    if cutter_plan is None:
        cutter_plan = request_multipart_plan(
            "gap_candidates", plane_specs=split_plane_specs, distance=thickness,
        )["cutters"]
    candidates: list[tuple[int, Object]] = []
    for plane_index, plan in enumerate(cutter_plan):
        if plane_index == own_plane_index:
            continue
        normal = mathutils.Vector(plan["normal"])
        gap_center = mathutils.Vector(plan["center"])
        gap_cube = split_base.duplicate(
            name_adder=f"_gap_cube_{plane_index + 1:02d}"
        )
        cutter = None
        try:
            # Object owns only the Blender execution here. Its slab dimensions
            # and orientation are planned by the external geometry worker.
            cutter = gap_cube._create_split_plane_cutter(
                normal,
                gap_center,
                float(plan["thickness"]),
            )
            gap_cube &= cutter
        except Exception:
            gap_cube.remove()
            raise
        finally:
            if cutter is not None:
                cutter.remove()

        mesh = getattr(gap_cube.object, "data", None)
        if (
            mesh is None
            or len(mesh.vertices) == 0
            or len(mesh.polygons) == 0
        ):
            gap_cube.remove()
            continue

        gap_cube.name = (
            f"{SLIP_CASTING_SPLIT_BASE_GAP_PREFIX}"
            f"{system_names[own_plane_index]}_by_{system_names[plane_index]}"
        )
        candidates.append((plane_index, gap_cube))
    return candidates


def _keep_crossing_split_base_gap_candidates(
    candidates: list[tuple[int, Object]],
    split_base_parts: list[Object],
) -> list[Object]:
    """Discard cubes for planes that did not actually split this base."""
    kept: list[Object] = []
    for plane_index, gap_cube in candidates:
        sides = {
            int(part.object[SPLIT_SECTION_SIDES_KEY][plane_index])
            for part in split_base_parts
            if part.object.get(SPLIT_SECTION_SIDES_KEY) is not None
        }
        if -1 in sides and 1 in sides:
            kept.append(gap_cube)
        else:
            gap_cube.remove()
    return kept


def _prepare_split_base_gap_placements(gap, own_plane, gap_plane, split_plane_specs):
    """Let a crossing filler follow translations from all other planes."""
    other_indices = [i for i in range(len(split_plane_specs))
                     if i not in (own_plane, gap_plane)]
    if not other_indices:
        gap.object[SPLIT_SECTION_SIDES_KEY] = [0] * len(split_plane_specs)
        return [gap]
    # The source-base and bridged planes stay zero: the filler already occupies
    # their thickness. Remaining planes must move it with the adjoining bases,
    # including cumulative offsets from additional parallel planes.
    return (yield begin_split_object_by_direct_plane_specs(
        gap,
        [split_plane_specs[i] for i in other_indices],
        preserve_isolated_meshes=True,
        section_plane_indices=other_indices,
        section_plane_count=len(split_plane_specs),
        output_name_prefix=gap.name,
        plan_from_cuts=True,
    ))


def _split_section_sides(obj: Object, plane_count: int) -> list[int]:
    values = obj.object.get(SPLIT_SECTION_SIDES_KEY)
    if values is None or len(values) != plane_count:
        return [0] * plane_count
    return [int(value) for value in values]


def _routing_bounds(obj: Object) -> list[float]:
    return [
        float(obj.min_x),
        float(obj.min_y),
        float(obj.min_z),
        float(obj.max_x),
        float(obj.max_y),
        float(obj.max_z),
    ]


def _subtract_touching_split_bases_from_plaster_molds(
    split_plane_specs: list[list[list[float]]],
) -> int:
    """Cut each translated plaster section with only its touching base pieces."""
    plaster_parts = _slip_casting_plaster_mold_objects()
    regular_split_bases = _slip_casting_split_base_objects()
    gap_split_bases = _slip_casting_split_base_gap_objects()
    split_bases = [*regular_split_bases, *gap_split_bases]
    if not plaster_parts or not split_bases:
        return 0

    plane_count = len(split_plane_specs)
    split_base_plane_indices = []
    for split_base in split_bases:
        resolved_index = _split_base_own_plane_index(
            split_base.name,
            split_plane_specs,
        )
        split_base_plane_indices.append(
            resolved_index if resolved_index is not None else -1
        )
    routes = plan_slip_casting_split_base_subtractions_with_server(
        plaster_bounds=[_routing_bounds(part) for part in plaster_parts],
        plaster_sides=[
            _split_section_sides(part, plane_count) for part in plaster_parts
        ],
        split_base_bounds=[_routing_bounds(base) for base in split_bases],
        split_base_sides=[
            _split_section_sides(base, plane_count) for base in split_bases
        ],
        split_base_plane_indices=split_base_plane_indices,
    )
    if len(routes) != len(plaster_parts):
        raise RuntimeError(
            "Server returned incomplete plaster-mold subtraction routes"
        )

    # Validate the whole response before changing any section.
    for indices in routes:
        if any(index < 0 or index >= len(split_bases) for index in indices):
            raise RuntimeError("Server returned an invalid split-base route")
    started = time.perf_counter()
    subtraction_count = 0
    boolean_count = 0
    for plaster_part, split_base_indices in zip(plaster_parts, routes):
        cutters = [split_bases[index] for index in split_base_indices]
        boolean_count += _apply_disjoint_difference_batches(
            plaster_part, cutters,
            retry_remesh=build_sharp_modifier(8), retry_remesh_on="self",
        )
        subtraction_count += len(cutters)
        force_viewport_redraw()
    logger.info(
        "Applied %d touching split-base subtraction(s) with %d Boolean(s) "
        "across %d plaster-mold section(s) in %.3fs",
        subtraction_count,
        boolean_count,
        len(plaster_parts),
        time.perf_counter() - started,
    )
    return subtraction_count


def _apply_disjoint_difference_batches(
    target: Object, cutters: list[Object], **retry_options,
) -> int:
    """Join only separated cutters; preserve order across touching bounds.

    Joining intersecting shells is not a Boolean union. Flush the current
    batch on any overlap (including contact), so such cutters retain their
    sequential difference semantics. Source operands are never consumed.
    """
    batches = []
    batch = []
    bounds = []
    for cutter in cutters:
        current = _routing_bounds(cutter)
        if any(not any(
            current[axis + 3] < previous[axis] - 1e-5
            or previous[axis + 3] < current[axis] - 1e-5
            for axis in range(3)
        ) for previous in bounds):
            batches.append(batch)
            batch, bounds = [], []
        batch.append(cutter)
        bounds.append(current)
    if batch:
        batches.append(batch)
    for batch in batches:
        operand = batch[0] if len(batch) == 1 else _joined_duplicate_pin_operand(
            batch, name=f"_{target.name}_difference_batch",
        )
        try:
            target.apply_modifier(
                diff_no_material_transfer_mod, target=operand, **retry_options,
            )
        finally:
            if len(batch) > 1:
                operand.remove()
    return len(batches)


def _joined_duplicate_pin_operand(
    pins: list[Object],
    *,
    name: str,
) -> Object | None:
    """Copy and join disjoint pins without consuming routed source objects."""
    if not pins:
        return None
    duplicates = []
    try:
        # Preserve independent mesh data and routing properties, but defer
        # selection/depsgraph evaluation until the single join operation.
        for index, pin in enumerate(pins, start=1):
            source = pin.object
            raw = source.copy()
            duplicate = Object(raw)
            duplicates.append(duplicate)
            raw.data = source.data.copy()
            collection = source.users_collection[0] if source.users_collection else bpy.context.collection
            collection.objects.link(raw)
            raw.select_set(False)
            raw.matrix_world = source.matrix_world.copy()
            raw.hide_set(False)
            raw.hide_viewport = False
            raw.hide_render = False
            raw.name = f"{source.name}_batch_{index:03d}"
        joined = duplicates[0]
        joined.name = name
        if len(duplicates) > 1:
            bpy.ops.object.mode_set(mode="OBJECT")
            bpy.ops.object.select_all(action="DESELECT")
            for duplicate in duplicates:
                duplicate.object.select_set(True)
            bpy.context.view_layer.objects.active = joined.object
            consumed_meshes = [duplicate.object.data for duplicate in duplicates]
            bpy.ops.object.join()
            remove_unused_meshes(consumed_meshes)
    except Exception:
        for duplicate in duplicates:
            try:
                if duplicate.object.name in bpy.data.objects:
                    mesh = duplicate.object.data
                    bpy.data.objects.remove(duplicate.object, do_unlink=True)
                    if mesh is not None and mesh.users == 0:
                        bpy.data.meshes.remove(mesh)
            except ReferenceError:
                continue
        raise
    return joined


def _add_touching_preview_male_pins_to_plaster_molds(
    split_plane_specs: list[list[list[float]]],
) -> int:
    """Union returned male caps into their server-routed plaster sections."""
    plaster_parts = _slip_casting_plaster_mold_objects()
    male_pins = _slip_casting_preview_male_pin_objects()
    if not plaster_parts or not male_pins:
        return 0

    plane_count = len(split_plane_specs)
    pin_plane_indices = []
    alignment_pins = []
    alignment_records = []
    for male_pin in male_pins:
        own = _preview_male_pin_own_plane_index(male_pin.name, split_plane_specs)
        if own is None:
            raise RuntimeError(f"Could not resolve source plane for {male_pin.name}")
        pin_plane_indices.append(own)
        if not bool(male_pin.object.get(SLIP_CASTING_PREVIEW_MALE_PIN_ALIGNED_KEY, False)):
            alignment_pins.append(male_pin)
            alignment_records.append({"own_plane": own, "sides": _split_section_sides(male_pin, plane_count)})
    if alignment_pins:
        movements = plan_slip_casting_movements(
            split_plane_specs, alignment_records, 0.0, mode="preview_align",
            cut_half_thickness=SPLIT_PLANE_CUT_HALF_THICKNESS,
        )
        for male_pin, movement in zip(alignment_pins, movements):
            male_pin.translate_whole(mathutils.Vector(movement))
            male_pin.object[SLIP_CASTING_PREVIEW_MALE_PIN_ALIGNED_KEY] = True

    routes = plan_slip_casting_split_base_subtractions_with_server(
        plaster_bounds=[_routing_bounds(part) for part in plaster_parts],
        plaster_sides=[
            _split_section_sides(part, plane_count) for part in plaster_parts
        ],
        split_base_bounds=[_routing_bounds(pin) for pin in male_pins],
        split_base_sides=[
            _split_section_sides(pin, plane_count) for pin in male_pins
        ],
        split_base_plane_indices=pin_plane_indices,
        kind="preview_male",
    )
    if len(routes) != len(plaster_parts):
        raise RuntimeError(
            "Server returned incomplete plaster-mold male-pin routes"
        )

    addition_count = 0
    boolean_count = 0
    try:
        for plaster_part, male_pin_indices in zip(plaster_parts, routes):
            routed_pins: list[Object] = []
            for male_pin_index in male_pin_indices:
                if male_pin_index < 0 or male_pin_index >= len(male_pins):
                    raise RuntimeError(
                        "Server returned an invalid preview male-pin route"
                    )
                routed_pins.append(male_pins[male_pin_index])
            male_operand = _joined_duplicate_pin_operand(
                routed_pins,
                name=f"_{plaster_part.name}_preview_male_pins_batch",
            )
            if male_operand is None:
                continue
            try:
                plaster_part.apply_boolean_modifier(
                    union_no_material_transfer_mod,
                    target=male_operand,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                assign_plaster_mold_material(plaster_part.object)
                addition_count += len(routed_pins)
                boolean_count += 1
                force_viewport_redraw()
                logger.debug(
                    "Added %d joined Slip Casting preview male pins to %s",
                    len(routed_pins),
                    plaster_part.name,
                )
            finally:
                male_operand.remove()
    finally:
        for male_pin in male_pins:
            if male_pin.object.name in bpy.data.objects:
                male_pin.remove()

    logger.info(
        "Added %d server-routed male pin(s) with %d batched Boolean(s) "
        "across %d plaster-mold section(s)",
        addition_count,
        boolean_count,
        len(plaster_parts),
    )
    return addition_count


def _subtract_slip_casting_edge_female_pins_from_split_bases(
    split_plane_specs: list[list[list[float]]],
) -> int:
    """Subtract Edge females before separation and retain them as keep-outs."""
    split_bases = [
        *_slip_casting_split_base_objects(),
        *_slip_casting_split_base_gap_objects(),
    ]
    edge_pins = _slip_casting_edge_pin_objects()
    if not edge_pins:
        return 0

    plane_count = len(split_plane_specs)
    female_pins: list[Object] = []
    female_plane_indices: list[int] = []
    for edge_pin in edge_pins:
        role_and_plane = _edge_pin_role_and_plane_index(
            edge_pin.name,
            split_plane_specs,
        )
        if role_and_plane is None:
            raise RuntimeError(
                "Could not resolve the role/source plane for Edge pin "
                f"{edge_pin.name}"
            )
        pin_role, own_plane_index = role_and_plane
        if pin_role == "female":
            female_pins.append(edge_pin)
            female_plane_indices.append(own_plane_index)

    female_routes = plan_slip_casting_split_base_subtractions_with_server(
        plaster_bounds=[_routing_bounds(base) for base in split_bases],
        plaster_sides=[
            _split_section_sides(base, plane_count) for base in split_bases
        ],
        split_base_bounds=[_routing_bounds(pin) for pin in female_pins],
        split_base_sides=[
            _split_section_sides(pin, plane_count) for pin in female_pins
        ],
        split_base_plane_indices=female_plane_indices,
        kind="same_plane",
        target_plane_indices=[
            index if (index := _split_base_geometry_own_plane_index(base.name, split_plane_specs)) is not None else -1
            for base in split_bases
        ],
    )
    if len(female_routes) != len(split_bases):
        raise RuntimeError("Server returned incomplete Edge female routes")

    operation_count = 0
    boolean_count = 0
    for split_base, female_pin_indices in zip(split_bases, female_routes):
        routed_female_pins: list[Object] = []
        for female_pin_index in female_pin_indices:
            if female_pin_index < 0 or female_pin_index >= len(female_pins):
                raise RuntimeError(
                    "Server returned an invalid Edge female route"
                )
            routed_female_pins.append(female_pins[female_pin_index])
        female_operand = _joined_duplicate_pin_operand(
            routed_female_pins,
            name=f"_{split_base.name}_edge_female_pins_batch",
        )
        if female_operand is None:
            continue
        try:
            split_base.apply_boolean_modifier(
                diff_no_material_transfer_mod,
                target=female_operand,
                retry_remesh=build_sharp_modifier(8),
                retry_remesh_on="self",
            )
            operation_count += len(routed_female_pins)
            boolean_count += 1
            force_viewport_redraw()
        finally:
            female_operand.remove()

    logger.info(
        "Subtracted %d server-routed Edge female pin(s) with %d batched "
        "Boolean(s) across %d split-base piece(s)",
        operation_count,
        boolean_count,
        len(split_bases),
    )
    return operation_count


def _translate_and_add_slip_casting_edge_male_pins_to_box_parts(
    split_plane_specs: list[list[list[float]]],
    split_base_thickness: float,
) -> int:
    """Translate Edge males with split cells, then add to positive box parts."""
    box_parts = sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.name.lower().startswith("box_part_")
        ),
        key=lambda obj: obj.name.lower(),
    )
    plane_count = len(split_plane_specs)
    male_pins = []
    male_plane_indices = []
    records = []
    for pin in _slip_casting_edge_pin_objects():
        role_and_plane = _edge_pin_role_and_plane_index(pin.name, split_plane_specs)
        if role_and_plane is None or role_and_plane[0] != "male":
            continue
        own = role_and_plane[1]
        male_pins.append(pin)
        male_plane_indices.append(own)
        records.append({"own_plane": own, "sides": _split_section_sides(pin, plane_count)})
    if male_pins:
        movements = plan_slip_casting_movements(
            split_plane_specs, records, split_base_thickness, mode="edge_male",
        )
        for pin, movement in zip(male_pins, movements):
            pin.translate_whole(mathutils.Vector(movement))
        force_viewport_redraw()
    routes = plan_slip_casting_split_base_subtractions_with_server(
        plaster_bounds=[_routing_bounds(part) for part in box_parts],
        plaster_sides=[_split_section_sides(part, plane_count) for part in box_parts],
        split_base_bounds=[_routing_bounds(pin) for pin in male_pins],
        split_base_sides=[_split_section_sides(pin, plane_count) for pin in male_pins],
        split_base_plane_indices=male_plane_indices,
        kind="edge_male",
    )
    if len(routes) != len(box_parts):
        raise RuntimeError("Server returned incomplete Edge male routes")
    operation_count = 0
    boolean_count = 0
    try:
        for box_part, pin_indices in zip(box_parts, routes):
            routed_male_pins: list[Object] = []
            for pin_index in pin_indices:
                if pin_index < 0 or pin_index >= len(male_pins):
                    raise RuntimeError(
                        "Server returned an invalid Edge male route"
                    )
                routed_male_pins.append(male_pins[pin_index])
            male_operand = _joined_duplicate_pin_operand(
                routed_male_pins,
                name=f"_{box_part.name}_edge_male_pins_batch",
            )
            if male_operand is None:
                continue
            try:
                box_part.apply_boolean_modifier(
                    union_no_material_transfer_mod,
                    target=male_operand,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                assign_generated_material(box_part.object)
                operation_count += len(routed_male_pins)
                boolean_count += 1
                force_viewport_redraw()
            finally:
                male_operand.remove()
    finally:
        for pin in male_pins:
            if pin.object.name in bpy.data.objects:
                pin.remove()
    logger.info(
        "Added %d server-routed Edge male pin(s) with %d batched Boolean(s) "
        "across %d box part(s)",
        operation_count,
        boolean_count,
        len(box_parts),
    )
    return operation_count


def _retain_split_base_debug_cutter(cutter: Object, role: str, source_name: str) -> None:
    """Retain hidden Boolean operands for optional later inspection."""
    cutter.name = f"debug_{role}_{source_name}"
    cutter.object.display_type = "WIRE"
    cutter.object.show_in_front = False
    cutter.object.hide_render = True
    cutter.object.hide_set(True)
    cutter.object.select_set(False)


def _cut_slip_casting_split_base_locking_gaps(
    split_plane_specs: list[list[list[float]]],
    locking_plan: dict,
    *,
    create_only: bool = False,
) -> int:
    """Cut a 1 mm gap, preserving a center cylinder and pin keepout spheres."""
    gap_thickness = float(locking_plan["gap_thickness"])
    gap_center_offset = float(locking_plan["gap_center_offset"])
    if gap_thickness <= 0.0:
        return 0

    split_bases = [
        *_slip_casting_split_base_objects(),
        *_slip_casting_split_base_gap_objects(),
    ]
    locking_pins: list[Object] = []
    locking_pin_plane_indices: list[int] = []
    for pin in _slip_casting_preview_male_pin_objects():
        plane_index = _preview_male_pin_own_plane_index(
            pin.name,
            split_plane_specs,
        )
        if plane_index is not None:
            locking_pins.append(pin)
            locking_pin_plane_indices.append(plane_index)
    edge_female_pins: list[Object] = []
    for pin in _slip_casting_edge_pin_objects():
        role_and_plane = _edge_pin_role_and_plane_index(
            pin.name,
            split_plane_specs,
        )
        if role_and_plane is None or role_and_plane[0] != "female":
            continue
        edge_female_pins.append(pin)
        locking_pins.append(pin)
        locking_pin_plane_indices.append(role_and_plane[1])

    plane_count = len(split_plane_specs)
    pin_routes = plan_slip_casting_split_base_subtractions_with_server(
        plaster_bounds=[_routing_bounds(base) for base in split_bases],
        plaster_sides=[
            _split_section_sides(base, plane_count) for base in split_bases
        ],
        split_base_bounds=[_routing_bounds(pin) for pin in locking_pins],
        split_base_sides=[
            _split_section_sides(pin, plane_count) for pin in locking_pins
        ],
        split_base_plane_indices=locking_pin_plane_indices,
        kind="same_plane",
        target_plane_indices=[
            index if (index := _split_base_geometry_own_plane_index(base.name, split_plane_specs)) is not None else -1
            for base in split_bases
        ],
    )
    if len(pin_routes) != len(split_bases):
        raise RuntimeError(
            "Server returned incomplete split-base gap pin routes"
        )

    gap_plans = request_multipart_plan(
        "gaps", plane_specs=split_plane_specs, locking_plan=locking_plan,
        parts=[{
            "own_plane": index if (index := _split_base_geometry_own_plane_index(base.name, split_plane_specs)) is not None else -1,
            "center": [float(v) for v in base.center_coords], "height": float(base.height),
        } for base in split_bases],
    )["gaps"]
    cut_count = 0
    try:
        for split_base, routed_pin_indices, gap_plan in zip(split_bases, pin_routes, gap_plans):
            if gap_plan is None:
                continue
            normal = mathutils.Vector(gap_plan["normal"])
            gap_center = mathutils.Vector(gap_plan["center"])
            base_center = mathutils.Vector(gap_plan["bridge_center"])
            keepout_radius = float(gap_plan["pin_radius"])
            cutter = split_base._create_split_plane_cutter(
                normal,
                gap_center,
                float(gap_plan["thickness"]),
            )
            try:
                center_radius = float(gap_plan["bridge_radius"])
                if center_radius > 0.0:
                    # Keep the cylinder vertical and centered on the base;
                    # its caps match the base's world Z bounds.
                    center_keepout = Object(
                        create_cylinder_primitive(
                            center_radius,
                            float(gap_plan["bridge_height"]),
                            vertices=64,
                        ),
                        "_split_base_center_keepout",
                    )
                    try:
                        center_keepout.object.rotation_euler = (0.0, 0.0, 0.0)
                        center_keepout.object.location = base_center
                        center_keepout.apply_all_transforms()
                        if not create_only:
                            cutter.apply_boolean_modifier(
                                diff_no_material_transfer_mod,
                                target=center_keepout,
                                retry_remesh=build_sharp_modifier(8),
                                retry_remesh_on="self",
                            )
                    finally:
                        if create_only:
                            _retain_split_base_debug_cutter(
                                center_keepout, "gap_cylinder", split_base.name
                            )
                        else:
                            center_keepout.remove()
                if create_only:
                    cut_count += 1
                    continue
                for pin_index in routed_pin_indices:
                    if pin_index < 0 or pin_index >= len(locking_pins):
                        raise RuntimeError(
                            "Server returned an invalid gap pin route"
                        )
                    pin = locking_pins[pin_index]
                    keepout = Object(
                        create_uv_sphere_primitive(keepout_radius),
                        f"_split_base_pin_keepout_{pin_index + 1:03d}",
                    )
                    try:
                        keepout.translate_whole(
                            pin.center_coords - keepout.center_coords
                        )
                        cutter.apply_boolean_modifier(
                            diff_no_material_transfer_mod,
                            target=keepout,
                            retry_remesh=build_sharp_modifier(8),
                            retry_remesh_on="self",
                        )
                        # Boolean application already refreshes the viewport.
                        # Avoid an extra draw for each temporary keepout.
                    finally:
                        keepout.remove()
                split_base.apply_boolean_modifier(
                    diff_no_material_transfer_mod,
                    target=cutter,
                    retry_remesh=build_sharp_modifier(8),
                    retry_remesh_on="self",
                )
                cut_count += 1
                force_viewport_redraw()
            finally:
                if create_only:
                    _retain_split_base_debug_cutter(cutter, "gap_cutter", split_base.name)
                else:
                    cutter.remove()
    finally:
        for pin in (() if create_only else edge_female_pins):
            if pin.object.name in bpy.data.objects:
                pin.remove()

    logger.info(
        "Prepared %d Slip Casting split-base locking gap(s): thickness=%.4f "
        "center_offset=%.4f pin_keepout_diameter=%.4f",
        cut_count,
        gap_thickness,
        gap_center_offset,
        float(locking_plan["pin_keepout_diameter"]),
    )
    return cut_count


def _translate_positive_split_parts(
    parts: list[Object],
    split_plane_specs: list[list[list[float]]],
    distance: float,
) -> None:
    """Apply a fully validated server placement batch once."""
    pending = []
    records = []
    for part in parts:
        if bool(part.object.get(SLIP_CASTING_SPLIT_OFFSET_APPLIED_KEY, False)):
            continue
        split_sides = part.object.get(SPLIT_SECTION_SIDES_KEY)
        if split_sides is None or len(split_sides) != len(split_plane_specs):
            raise RuntimeError(f"Invalid split-side metadata for {part.name}")
        own = _split_base_own_plane_index(part.name, split_plane_specs)
        if own is None:
            own = _preview_male_pin_own_plane_index(part.name, split_plane_specs)
        pending.append(part)
        records.append({"own_plane": own if own is not None else -1,
                        "sides": [int(value) for value in split_sides]})
    if not pending:
        return
    movements = plan_slip_casting_movements(split_plane_specs, records, distance)
    for part, movement in zip(pending, movements):
        part.object.location += mathutils.Vector(movement)
        part.object[SLIP_CASTING_SPLIT_OFFSET_APPLIED_KEY] = True
    bpy.context.view_layer.update()
    force_viewport_redraw()
    logger.info("Applied server placement batch to %d split components", len(pending))


def _slip_casting_parts_to_separate() -> list[Object]:
    name_prefixes = (
        "box_part_",
        "split_base_",
        "master_base_part_",
        SLIP_CASTING_PLASTER_MOLD_PART_PREFIX,
        SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX,
    )
    return sorted(
        (
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and obj.get(SPLIT_SECTION_SIDES_KEY) is not None
            and obj.name.lower().startswith(name_prefixes)
        ),
        key=lambda obj: obj.name.lower(),
    )


def _join_slip_casting_bases_by_section(split_plane_specs, distance) -> list[Object]:
    """Duplicate and trim split-base pieces into their corresponding master bases."""
    masters = _master_base_objects()
    if not masters:
        raise RuntimeError("No master-base sections found")
    sources = [*_slip_casting_split_base_objects(), *_slip_casting_split_base_gap_objects()]
    plane_count = len(split_plane_specs)
    sections = [_split_section_sides(master, plane_count) for master in masters]
    # A horizontal/angled box section may have no piece of the original floor.
    # Its split bases still form an independent master-base output.
    owners = list(masters)
    for box in _normal_box_objects():
        if not box.name.lower().startswith("box_part_"):
            continue
        cell = _split_section_sides(box, plane_count)
        if cell not in sections:
            sections.append(cell)
            owners.append(None)
    records = []
    for source in sources:
        own = _split_base_geometry_own_plane_index(source.name, split_plane_specs)
        if own is None:
            raise RuntimeError(f"Unknown split-base source plane: {source.name}")
        records.append({"own_plane": own, "sides": _split_section_sides(source, plane_count)})
    routes = request_multipart_plan(
        "base_sections", plane_specs=split_plane_specs, parts=records,
        sections=sections, distance=float(distance),
    )["sections"]
    pending = []
    try:
        for source, source_routes in zip(sources, routes):
            for route in source_routes:
                piece = source.duplicate(name_adder="_section")
                pending.append((route["section_index"], piece))
                for cut in route["cuts"]:
                    piece.cut_plane(mathutils.Vector(cut["normal"]), mathutils.Vector(cut["center"]))
                    if not piece.object.data.polygons:
                        break
        # Keep originals intact until every section has been cut successfully.
        for section_index, piece in pending:
            if not piece.object.data.polygons:
                piece.remove()
            elif owners[section_index] is None:
                piece.name = f"master_base_part_section_{section_index + 1:02d}"
                piece.object[SPLIT_SECTION_SIDES_KEY] = sections[section_index]
                piece.object[SLIP_CASTING_SPLIT_OFFSET_APPLIED_KEY] = True
                owners[section_index] = piece
            else:
                owners[section_index].join(piece)
            force_viewport_redraw()
        pending.clear()
        for source in sources:
            source.remove()
    finally:
        for _master, piece in pending:
            try:
                piece.remove()
            except ReferenceError:
                pass
    return [owner for owner in owners if owner is not None]


def _join_slip_casting_bases_into_master_base() -> Object | None:
    """Join all translated base components into one final master-base object."""
    master_base_parts = _master_base_objects()
    split_base_parts = _slip_casting_split_base_objects()
    split_base_gap_parts = _slip_casting_split_base_gap_objects()
    if not master_base_parts:
        logger.warning(
            "Skipping Slip Casting base join because no master-base part exists"
        )
        return None

    master_base = master_base_parts[0]
    sources = [
        *master_base_parts[1:],
        *split_base_parts,
        *split_base_gap_parts,
    ]
    for source in sources:
        master_base.join(source)
        force_viewport_redraw()

    master_base.name = "master_base"
    for metadata_key in (
        SPLIT_SECTION_SIDES_KEY,
        SLIP_CASTING_SPLIT_OFFSET_APPLIED_KEY,
    ):
        if metadata_key in master_base.object:
            del master_base.object[metadata_key]
    logger.info(
        "Joined %d master-base part(s), %d split-base part(s), and %d "
        "split-base gap cube(s) into %s",
        len(master_base_parts),
        len(split_base_parts),
        len(split_base_gap_parts),
        master_base.name,
    )
    return master_base


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


def _finish_slip_casting_male_vase_base_preview(
    male_vase_bases: list[Object],
) -> None:
    """Trim and turn over only the prepared male Vase base assembly."""
    pending = [
        male_vase_base
        for male_vase_base in male_vase_bases
        if not male_vase_base.object.get("moldboxer_rounded_lower_foot", False)
        and not male_vase_base.object.get("moldboxer_slip_casting_lower_foot", False)
        and not bool(
            male_vase_base.object.get(
                SLIP_CASTING_VASE_BASE_FLIPPED_KEY,
                False,
            )
        )
    ]
    if not pending:
        return

    for male_vase_base in pending:
        male_vase_base.cut_plane(
            mathutils.Vector((0.0, 0.0, 1.0)),
            mathutils.Vector(
                (
                    male_vase_base.center_coords.x,
                    male_vase_base.center_coords.y,
                    male_vase_base.max_z
                    - SLIP_CASTING_MALE_VASE_BASE_TOP_CUT_MM,
                )
            ),
        )
        force_viewport_redraw()

    bounds = _combined_object_bounds(pending)
    pivot = mathutils.Vector(
        (
            (bounds["min_x"] + bounds["max_x"]) / 2.0,
            (bounds["min_y"] + bounds["max_y"]) / 2.0,
            (bounds["min_z"] + bounds["max_z"]) / 2.0,
        )
    )
    assembly_rotation = (
        mathutils.Matrix.Translation(pivot)
        @ mathutils.Matrix.Rotation(math.radians(180.0), 4, "X")
        @ mathutils.Matrix.Translation(-pivot)
    )
    for male_vase_base in pending:
        male_vase_base.object.matrix_world = (
            assembly_rotation @ male_vase_base.object.matrix_world
        )
        male_vase_base.object[SLIP_CASTING_VASE_BASE_FLIPPED_KEY] = True
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
    mold_thickness: float = 30.0,
    plaster_locking_tolerance: float = 0.35,
    split_base_pin_diameter: float = 15.0,
    plaster_locking_pin_type: str = "CENTERED",
    organic_split_planes: str = "[]",
    master_base_mode: str = "ONE_PIECE",
    silicone_multipart: bool = False,
    split_base_key_type: str = "BARRIER",
    allow_bottom_split_base_keys: bool = False,
    bottom_pin_master_size: float = 0.0,
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
        mold_thickness,
        plaster_locking_tolerance,
        split_base_pin_diameter,
        plaster_locking_pin_type,
        organic_split_planes,
        master_base_mode,
        silicone_multipart,
        split_base_key_type,
        allow_bottom_split_base_keys,
        bottom_pin_master_size,
    )
    request_start_time = time.perf_counter()
    response = request_server(
        f"{get_server_base_url()}{SLIP_CASTING_CONFIRM_ENDPOINT}",
        ["box", SLIP_CASTING_HALF_BOX_WRAPPER_NAME],
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
    mold_thickness: float = 30.0,
    plaster_locking_tolerance: float = 0.35,
    split_base_pin_diameter: float = 15.0,
    plaster_locking_pin_type: str = "CENTERED",
    organic_split_planes: str = "[]",
    master_base_mode: str = "ONE_PIECE",
    silicone_multipart: bool = False,
    split_base_key_type: str = "BARRIER",
    allow_bottom_split_base_keys: bool = False,
    bottom_pin_master_size: float = 0.0,
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
        mold_thickness,
        plaster_locking_tolerance,
        split_base_pin_diameter,
        plaster_locking_pin_type,
        organic_split_planes,
        master_base_mode,
        silicone_multipart,
        split_base_key_type,
        allow_bottom_split_base_keys,
        bottom_pin_master_size,
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
        f"{get_server_base_url()}{SLIP_CASTING_CONFIRM_ENDPOINT}",
        ["box", SLIP_CASTING_HALF_BOX_WRAPPER_NAME],
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
    mold_thickness: float = 30.0,
    plaster_locking_tolerance: float = 0.35,
    split_base_pin_diameter: float = 15.0,
    plaster_locking_pin_type: str = "CENTERED",
    organic_split_planes: str = "[]",
    master_base_mode: str = "ONE_PIECE",
    silicone_multipart: bool = False,
    split_base_key_type: str = "BARRIER",
    allow_bottom_split_base_keys: bool = False,
    bottom_pin_master_size: float = 0.0,
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
        "mold_thickness": mold_thickness,
        "plaster_locking_tolerance": plaster_locking_tolerance,
        "plaster_locking_pin_type": str(plaster_locking_pin_type).upper(),
        "split_base_pin_diameter": (
            min(max(split_base_pin_diameter, 0.0), max(mold_thickness, 0.0))
            if silicone_multipart else limited_split_base_pin_diameter(split_base_pin_diameter, mold_thickness)
        ),
    }
    if allow_bottom_split_base_keys:
        params["allow_bottom_split_base_keys"] = True
        params["bottom_pin_master_size"] = bottom_pin_master_size
    if silicone_multipart:
        params["silicone_multipart"] = True
        params["split_base_key_type"] = split_base_key_type
    if master_base_mode != "ONE_PIECE":
        params["master_base_mode"] = master_base_mode
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
    helper_wrappers = [
        obj
        for obj in bpy.data.objects
        if obj.name.startswith(SLIP_CASTING_HALF_BOX_WRAPPER_NAME)
    ]
    imported_objects = [obj for obj in imported_objects if obj not in helper_wrappers]
    for helper_wrapper in helper_wrappers:
        bpy.data.objects.remove(helper_wrapper, do_unlink=True)
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
        bpy.data.objects.remove(server_base_substracter, do_unlink=True)
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
    master_base_objects = _master_base_objects()
    patron = _final_master_object()
    if patron is None or not master_base_objects:
        return
    master_base_bounds = _combined_object_bounds(master_base_objects)
    patron_bounds = _object_bounds(patron)
    male_vase_bases = _slip_casting_male_vase_base_objects()
    _finish_slip_casting_male_vase_base_preview(male_vase_bases)
    plaster_molds = _slip_casting_plaster_mold_objects()
    if plaster_molds:
        plaster_bounds = _combined_object_bounds(plaster_molds)
        target_plaster_min_x = (
            master_base_bounds["max_x"] + master_base_bounds["width"] / 2
        )
        plaster_translation = mathutils.Vector(
            (target_plaster_min_x - plaster_bounds["min_x"], 0, 0)
        )
        for plaster_mold in plaster_molds:
            translate_object_location(plaster_mold, plaster_translation)
        # Keep the flipped male base in casting coordinates until its companion
        # mold has been generated with the original slip-cast split planes.
        plaster_bounds = _combined_object_bounds(plaster_molds)
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
                    plaster_bounds["max_x"]
                    + plaster_bounds["width"] / 2
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
    if patron is None or (
        master_base is None
        and master_base_bounds is None
        and reference_width is None
    ):
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
    # One Piece clips span both clamp halves plus the solid base slab.
    # Use the same planned slab thickness as generation and part separation,
    # including the Edge dome allowance; do not add a cutter-gap allowance.
    clamp_locking_span = (
        float(scene.clamp_width) + slip_casting_split_base_thickness(scene)
    )
    if getattr(scene, "slip_casting_master_base_mode", "ONE_PIECE") == "PER_SPLIT":
        # Each clip grips one clamp half and one split-base half. The latter
        # is normally the box wall thickness, with any dome allowance retained.
        clamp_locking_span /= 2.0
    clamp_clips = create_clamp_clips(
        clamp_locking_span,
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


def _mesh_component_count(obj: Object) -> int:
    """Count connected mesh components without modifying or separating the object."""
    mesh = getattr(obj.object, "data", None)
    if mesh is None:
        return 0

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        remaining = set(bm.verts)
        component_count = 0
        while remaining:
            component_count += 1
            stack = [remaining.pop()]
            while stack:
                vertex = stack.pop()
                for edge in vertex.link_edges:
                    connected = edge.other_vert(vertex)
                    if connected in remaining:
                        remaining.remove(connected)
                        stack.append(connected)
        return component_count
    finally:
        bm.free()


def _keep_largest_casting_components(
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
        if ENABLE_OPTIMIZED_CASTING_COMPONENT_CLEANUP:
            normal_component_count = sum(
                _mesh_component_count(box) for box in normal_boxes
            )
            return _keep_largest_casting_components(
                casting_boxes,
                normal_component_count,
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
        ENABLE_OPTIMIZED_CASTING_COMPONENT_CLEANUP
        and get_effective_casting_box_type(scene) == "OPTIMIZED"
    ):
        normal_component_count = sum(
            _mesh_component_count(box) for box in _normal_box_objects()
        )
        _keep_largest_casting_components(casting_boxes, normal_component_count)


def _apply_imported_split_base_barriers() -> None:
    """Apply remeshed server-positioned clamp locks to the raw split bases."""
    routes = []
    for prefix, modifier in (
        ("slip_clamp_barrier_male__", union_no_material_transfer_mod),
        ("slip_clamp_barrier_female__", diff_no_material_transfer_mod),
    ):
        for raw in sorted(bpy.data.objects, key=lambda obj: obj.name):
            if not raw.name.startswith(prefix):
                continue
            target_name = raw.name[len(prefix):]
            target = bpy.data.objects.get(target_name)
            if target is None or target.type != "MESH" or raw.type != "MESH":
                raise RuntimeError(
                    f"Invalid split-base barrier route: {raw.name} -> {target_name}"
                )
            routes.append((Object(target), Object(raw), modifier))
    # Validate all routes before mutation; males precede females, then pins.
    for target, operand, modifier in routes:
        if operand.name.startswith("slip_clamp_barrier_male__"):
            assign_generated_material(target.object)
            assign_split_base_keys_material(operand.object)
            target.add_with_material_transfer(operand)
        else:
            target.apply_modifier(modifier, target=operand)
        operand.remove()
        force_viewport_redraw()


def _trim_reversed_silicone_key_intersections(scene, split_plane_specs, split_base_thickness):
    """Trim preview males at sockets while keeping base groove cutters intact."""
    if (not is_silicone_multipart_type(scene.mold_type_preview)
            or scene.silicone_split_base_key_type != "BARRIER"
            or len(split_plane_specs) < 2):
        return 0
    protrusions = []
    for raw in bpy.data.objects:
        if raw.type != "MESH":
            continue
        if raw.name.startswith("slip_base_male__"):
            target_name = raw.name.removeprefix("slip_base_male__")
            plane = _split_base_own_plane_index(target_name, split_plane_specs)
            if plane is None:
                raise RuntimeError(f"Could not resolve silicone socket plane: {raw.name}")
            protrusions.append((plane, Object(raw)))
    aligned = []
    count = 0
    try:
        for plane, protrusion in protrusions:
            # The mold preview is at the split plane; the physical raised key
            # is on the opposite face of the split base.
            cutter = protrusion.duplicate(name_adder="_silicone_socket_crossing")
            aligned.append((plane, cutter))
            _, normal = split_spec_point_normal(split_plane_specs[plane])
            cutter.translate_whole(-mathutils.Vector(normal).normalized() * float(split_base_thickness))
        # Keep the base's recess cutters whole. Trimming a subtractive operand
        # leaves positive red material in the groove, even when correctly aligned.
        # Only the cast preview needs the crossing socket subtraction here.
        for preview in _slip_casting_preview_male_pin_objects():
            plane = _preview_male_pin_own_plane_index(preview.name, split_plane_specs)
            if plane is None:
                raise RuntimeError(f"Could not resolve silicone preview key plane: {preview.name}")
            cutters = [obj for own, obj in aligned if own != plane]
            count += _apply_disjoint_difference_batches(preview, cutters)
            if not preview.object.data.polygons:
                preview.remove()
    finally:
        for _, cutter in aligned:
            cutter.remove()
    logger.info("Trimmed reversed silicone key crossings with %d Boolean(s)", count)
    return count


def _apply_imported_split_base_pins() -> None:
    """Apply transported pin operands before top trimming and splitting."""
    routes = []
    for prefix, modifier, role in (
        ("slip_base_male__", union_no_material_transfer_mod, "male_union"),
        ("slip_base_female__", diff_no_material_transfer_mod, "female_difference"),
    ):
        for raw in sorted(bpy.data.objects, key=lambda obj: obj.name):
            if not raw.name.startswith(prefix):
                continue
            target_name = raw.name[len(prefix):]
            if role == "female_difference":
                pin_index, separator, target_name = target_name.partition("__")
                if not separator or not pin_index.isdigit():
                    raise RuntimeError(f"Invalid individual female pin route: {raw.name}")
            target = bpy.data.objects.get(target_name)
            if target is None or target.type != "MESH" or raw.type != "MESH":
                raise RuntimeError(f"Invalid split-base pin route: {raw.name} -> {target_name}")
            routes.append((Object(target), Object(raw), modifier, role))
    # Validate every route first; apply all male unions before female cuts.
    started = time.perf_counter()
    female_routes = {}
    boolean_count = 0
    for target, operand, modifier, role in routes:
        if role == "female_difference":
            female_routes.setdefault(target.name, (target, []))[1].append(operand)
            continue
        assign_generated_material(target.object)
        assign_split_base_keys_material(operand.object)
        target.add_with_material_transfer(operand)
        boolean_count += 1
        operand.remove()
        force_viewport_redraw()
    for target, cutters in female_routes.values():
        boolean_count += _apply_disjoint_difference_batches(target, cutters)
        for cutter in cutters:
            cutter.remove()
        force_viewport_redraw()
    logger.info(
        "Applied %d split-base pin operands with %d Boolean(s) in %.3fs",
        len(routes), boolean_count, time.perf_counter() - started,
    )


def _trim_slip_casting_system_at_top(top_z: float | None) -> None:
    """Keep assembled parts at the prepared master's top before display spacing."""
    if top_z is None:
        return
    names = {"box", "silicone_mold", SLIP_CASTING_HALF_BOX_WRAPPER_NAME}
    parts = [
        Object(raw)
        for raw in bpy.data.objects
        if raw.type == "MESH"
        and (raw.name in names or raw.name.startswith("box_part_"))
    ]
    parts.extend(pending_casting_boxes())
    parts.extend(casting_box_objects())
    parts.extend(_master_base_objects())
    parts.extend(_slip_casting_split_base_objects())
    parts.extend(_slip_casting_split_base_gap_objects())
    parts.extend(_slip_casting_plaster_mold_objects())
    parts.extend(_slip_casting_preview_male_pin_objects())
    parts.extend(_slip_casting_edge_pin_objects())
    seen = set()
    for part in parts:
        if part.name in seen:
            continue
        seen.add(part.name)
        if float(part.max_z) <= top_z:
            continue
        part.cut_plane(
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, top_z)),
        )
        force_viewport_redraw()


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
        # The prepared female base/funnels have already been unioned by Build Box.
        # Capture this before basing or part separation changes any bounds.
        if is_silicone_multipart_type(context.scene.mold_type_preview):
            # Silicone has its own top padding and channels. Saved slip-casting
            # preparation settings must not trim it back to the master height.
            state["system_top_z"] = None
        elif slip_casting_funnels_on_top(context.scene):
            state["system_top_z"] = float(get_master_for_base_operations().max_z)
        else:
            state["system_top_z"] = (
                float(get_master_for_base_operations().max_z) - 0.5
                if slip_casting_uses_base(context.scene)
                else None
            )
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
        state["plaster_locking_pin_type"] = str(_split_base_key_settings(context.scene)[2]).upper()
        state["split_base_locking_plan"] = (
            plan_slip_casting_split_base_locking_geometry_with_server(
                box_wall_thickness=context.scene.box_thickness,
                requested_pin_diameter=_split_base_key_settings(context.scene)[0],
                mold_thickness=context.scene.box_gap,
                **_split_master_base_plan_arguments(context.scene),
                plaster_locking_pin_type=state["plaster_locking_pin_type"],
            )
        )
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
        ) = split_specs_query_values(state["split_plane_specs"])
        state["splitter_plane_specs"] = state["split_plane_specs"]
        state["has_splits"] = bool(state["splitter_plane_specs"])
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
        box = Object(bpy.data.objects.get("box"))
        box.select()
        box.apply_all_transforms()
        clean_top_height = min(2, box.height - 0.1)
        preserve_bevels = getattr(context.scene, "slip_casting_shape_type", "adapted") == "cube"
        if clean_top_height > 0 and not preserve_bevels:
            box.clean_top(clean_top_height)
        # Clamp generation uses these uploaded meshes as its reference bounds.
        # Cut them before the request, including boxes built before this offset.
        top_z = state["system_top_z"]
        if top_z is not None and not preserve_bevels:
            for name in ("box", SLIP_CASTING_HALF_BOX_WRAPPER_NAME):
                raw = bpy.data.objects.get(name)
                if raw is None or raw.type != "MESH":
                    continue
                part = Object(raw)
                if float(part.max_z) > float(top_z):
                    part.cut_plane(
                        mathutils.Vector((0, 0, 1)),
                        mathutils.Vector((0, 0, float(top_z))),
                    )
        if is_silicone_multipart_type(context.scene.mold_type_preview):
            add_deposit()
            if state["casting_feet"]:
                add_casting_feet()
            recut_channels()
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
                _mold_mix_engraving(context.scene)
                if not is_lite_tier()
                else None
            ),
            mold_thickness=context.scene.box_gap,
            plaster_locking_tolerance=_split_base_key_settings(context.scene)[1],
            plaster_locking_pin_type=(
                state["plaster_locking_pin_type"]
            ),
            split_base_pin_diameter=_split_base_key_settings(context.scene)[0],
            bottom_pin_master_size=(
                max(Object(bpy.data.objects.get("_slip_casting_restart_master")
                           or bpy.data.objects["patron"]).object.dimensions)
                if is_slip_casting_type(context.scene.mold_type_preview)
                and slip_casting_funnels_on_top(context.scene)
                and not context.scene.slip_casting_generate_base else 0.0
            ),
            allow_bottom_split_base_keys=(
                is_slip_casting_type(context.scene.mold_type_preview)
                and slip_casting_funnels_on_top(context.scene)
                and not context.scene.slip_casting_generate_base
            ),
            silicone_multipart=is_silicone_multipart_type(context.scene.mold_type_preview),
            split_base_key_type=getattr(context.scene, "silicone_split_base_key_type", "BARRIER"),
            master_base_mode=getattr(context.scene, "slip_casting_master_base_mode", "ONE_PIECE"),
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
        if getattr(context.scene, "slip_casting_shape_type", "adapted") != "cube":
            prepare_base_substracter_after_server_import()

    def clip_edge_pins_to_original_box_wrapper() -> None:
        if str(state["plaster_locking_pin_type"]) != "EDGE":
            return
        _clip_slip_casting_edge_pins_to_original_box_wrapper()

    def remesh_imported_barriers() -> None:
        silicone_barrier_keys = (
            is_silicone_multipart_type(context.scene.mold_type_preview)
            and context.scene.silicone_split_base_key_type == "BARRIER"
        )
        barriers = [
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            # Base locks are remeshed at their point of use in base/splitter.
            # Doing them here as well applies the same voxel pass twice.
            and not obj.name.lower().startswith("base_barrier_")
            and (any(
                marker in obj.name.lower()
                for marker in (
                    "barrier_male",
                    "barrier_female",
                    "barrier_vertical_reinforcement",
                )
            ) or (silicone_barrier_keys and obj.name.startswith((
                "slip_base_male__",
                "slip_base_female__",
                SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX,
            ))))
        ]
        for barrier in barriers:
            if silicone_barrier_keys and barrier.name.startswith((
                "slip_base_male__", "slip_base_female__", SLIP_CASTING_PREVIEW_MALE_PIN_PREFIX,
            )):
                diameter = float(context.scene.silicone_split_base_key_diameter)
                # Base recesses and silicone preview males use the smaller
                # profile; base protrusions form the larger silicone sockets.
                if not barrier.name.startswith("slip_base_male__"):
                    diameter -= float(context.scene.silicone_split_base_key_tolerance)
                _remesh_barrier_from_scene(barrier, barrier_diameter=min(max(diameter, 0.001), _silicone_key_operand_diameter(barrier)))
            else:
                _remesh_barrier_from_scene(barrier)
            force_viewport_redraw(context)
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
            top_z=(
                float(Object(bpy.data.objects.get("box")).max_z)
                if is_silicone_multipart_type(context.scene.mold_type_preview)
                else state["system_top_z"]
            ),
            # Silicone channels/funnels are already part of the source mesh.
            # Re-fitting a primitive around their bounds thickens every wall by
            # their protrusion as well as the requested box thickness. Offset
            # the actual surface instead; the initial mold keeps its chosen shape.
            shape_type=(
                "adapted" if is_silicone_multipart_type(context.scene.mold_type_preview)
                else getattr(context.scene, "slip_casting_shape_type", "adapted")
            ),
            vertical_faces=getattr(context.scene, "slip_casting_box_faces", 4),
        )

        def finish(opened_box):
            logger.debug(
                "Confirm mold postprocess phase took %.3fs",
                time.perf_counter() - postprocess_start_time,
            )
            assign_generated_material(bpy.data.objects.get("box"))
            if str(state["plaster_locking_pin_type"]) == "EDGE":
                # Despite the historical variable name, this is the solid
                # outer wrapper. It is opened later by the assembled-box trim.
                _prepare_slip_casting_edge_pin_clipper(opened_box)
            return opened_box

        return task.then(finish)

    def add_basing():
        def steps():
            if not is_lite_tier() and bpy.data.objects.get("Text1") is None:
                weight_text = _mold_mix_engraving(context.scene)
                yield request_weight_text_mesh_async(weight_text)

            basing_start_time = time.perf_counter()
            add_basing_to_system(
                context.scene.volume,
                True,  # Slip casting uses a fixed master until unfixed support is implemented.
                context.scene.master_base_pin,
                context.scene.wing_width,
                context.scene.master_base_pin_tolerance,
                context.scene.master_base_pin_height,
                base_thickness=context.scene.base_thickness,
                base_type=context.scene.base_type,
                pre_join_base_callback=pre_join_base_callback,
                weight_text=_mold_mix_engraving(context.scene),
            )
            state["basing_elapsed"] = time.perf_counter() - basing_start_time

        sequence = BackgroundTaskSequence(steps())
        sequence.redraw_interval = 0.1
        return sequence

    def add_clamps() -> None:
        add_clamps_to_box()

    def split_system():
        split_start_time = time.perf_counter()
        if bool(state["has_splits"]):
            logger.info(
                "Running mold-box split and pre-split component cleanup with %d "
                "split plane%s",
                len(state["splitter_plane_specs"]),
                "" if len(state["splitter_plane_specs"]) == 1 else "s",
            )
            task = begin_slip_casting_split_system(
                state["splitter_plane_specs"],
                float(
                    state["split_base_locking_plan"][
                        "split_base_thickness"
                    ]
                ),
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
                "components without splitting"
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
            if _rename_slip_casting_mold_preview() is None:
                raise RuntimeError("No plaster mold found for Slip Casting")
        state["split_elapsed"] = time.perf_counter() - split_start_time
        return None

    def finish_casting_boxes() -> None:
        casting_box_elapsed = 0.0
        if context.scene.pro_casting_box:
            casting_box_start_time = time.perf_counter()
            duplicate_cut_casting_boxes(cut_vertical=cut_casting_vertical)
            casting_box_elapsed += time.perf_counter() - casting_box_start_time
            force_viewport_redraw(context)
        if context.scene.pro_casting_box and two_part_casting_side is not None:
            casting_box_start_time = time.perf_counter()
            cut_two_part_casting_boxes(
                two_part_casting_side,
                context.scene.wing_width,
                cut_open_base_side=cut_casting_open_base_side,
            )
            casting_box_elapsed += time.perf_counter() - casting_box_start_time
            force_viewport_redraw(context)
        state["casting_box_elapsed"] = casting_box_elapsed

    def separate_split_parts() -> None:
        if not bool(state["has_splits"]):
            return
        _translate_positive_split_parts(
            _slip_casting_parts_to_separate(),
            state["splitter_plane_specs"],
            float(
                state["split_base_locking_plan"]["split_base_thickness"]
            ),
        )

    def subtract_edge_female_pins() -> None:
        if (
            not bool(state["has_splits"])
            or str(state["plaster_locking_pin_type"]) != "EDGE"
        ):
            return
        _subtract_slip_casting_edge_female_pins_from_split_bases(
            state["splitter_plane_specs"]
        )

    def translate_and_add_edge_male_pins() -> None:
        if (
            not bool(state["has_splits"])
            or str(state["plaster_locking_pin_type"]) != "EDGE"
        ):
            return
        _translate_and_add_slip_casting_edge_male_pins_to_box_parts(
            state["splitter_plane_specs"],
            float(state["split_base_locking_plan"]["split_base_thickness"]),
        )

    def cut_split_base_locking_gaps() -> None:
        if not bool(state["has_splits"]):
            return
        _cut_slip_casting_split_base_locking_gaps(
            state["splitter_plane_specs"],
            state["split_base_locking_plan"],
        )

    def preview_gap_cutters() -> None:
        _cut_slip_casting_split_base_locking_gaps(
            state["splitter_plane_specs"],
            state["split_base_locking_plan"],
            create_only=True,
        )
        force_viewport_redraw(context)
        logger.info("Debug stop: gap cutters and cylinders created; no gap subtraction applied")

    def subtract_split_bases_from_plaster_molds() -> None:
        if not bool(state["has_splits"]):
            return
        _subtract_touching_split_bases_from_plaster_molds(
            state["splitter_plane_specs"]
        )

    def add_preview_male_pins_to_plaster_molds() -> None:
        if not bool(state["has_splits"]):
            return
        _add_touching_preview_male_pins_to_plaster_molds(
            state["splitter_plane_specs"]
        )

    def join_split_bases_to_master_base() -> None:
        if not bool(state["has_splits"]):
            return
        if getattr(context.scene, "slip_casting_master_base_mode", "ONE_PIECE") == "PER_SPLIT":
            _join_slip_casting_bases_by_section(
                state["splitter_plane_specs"],
                float(state["split_base_locking_plan"]["split_base_thickness"]),
            )
        else:
            _join_slip_casting_bases_into_master_base()

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
        _set_slip_casting_plaster_molds_visible(True)
        space_mold_system()
        state["spacing_elapsed"] = time.perf_counter() - spacing_start_time

    def refresh_final_mold_metrics() -> None:
        metrics_start_time = time.perf_counter()
        plaster_molds = _slip_casting_plaster_mold_objects()
        if plaster_molds:
            context.scene.volume = sum(
                plaster_mold.volume for plaster_mold in plaster_molds
            )
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

    yield "Preparing mold box", prepare_channels
    yield "Generating mold box", build_channel_box
    yield "Generating mold system", request_and_import_server_response
    if (DEBUG_STOP_BEFORE_GAP_SUBTRACTION and bool(state["has_splits"])
            and not _split_master_base_plan_arguments(context.scene)):
        yield "Debug: preview gap cutters and cylinders before subtraction", preview_gap_cutters
        return "DEBUG_GAP_PREVIEW"
    yield "Remeshing imported barriers and reinforcements", remesh_imported_barriers
    yield "Applying split base barriers", _apply_imported_split_base_barriers
    yield "Trimming silicone key intersections", lambda: _trim_reversed_silicone_key_intersections(
        context.scene, state["split_plane_specs"],
        float(state["split_base_locking_plan"]["split_base_thickness"]),
    )
    yield "Applying split base pins", _apply_imported_split_base_pins
    yield "Refining mold box", postprocess_imported_box
    yield "Preparing base cutter", prepare_imported_base_substracter
    yield "Clipping edge locking pins", clip_edge_pins_to_original_box_wrapper
    for label, step in iter_imported_boolean_steps():
        yield label, step
    yield "Generating base", add_basing
    yield "Adding clamps and support pilars to mold box", add_clamps
    yield "Trimming assembled mold box", lambda: subtract_base_substracter_from_box(
        extend_opening=getattr(context.scene, "slip_casting_shape_type", "adapted") != "adapted",
        extrude_caps=getattr(context.scene, "slip_casting_shape_type", "adapted") == "cube",
    )
    # Shape each original base's gap before deriving split parts or crossing
    # gap pieces, so they inherit the same centered cylinder cutout.
    yield "Subtracting edge female pins", subtract_edge_female_pins
    yield "Cutting split base locking gaps", cut_split_base_locking_gaps
    yield "Splitting mold system", split_system
    yield "Preparing casting boxes", finish_casting_boxes
    yield "Separating split parts", separate_split_parts
    yield "Adding translated edge male pins", translate_and_add_edge_male_pins
    yield (
        "Fitting split bases to mold",
        subtract_split_bases_from_plaster_molds,
    )
    yield "Adding registration keys to mold", add_preview_male_pins_to_plaster_molds
    yield "Joining split bases to master base", join_split_bases_to_master_base
    yield "Finalizing patron", finalize_patron
    yield "Generating clips", create_clips
    yield "Spacing mold system", space_system
    yield "Updating mold metrics", refresh_final_mold_metrics
    if is_silicone_multipart_type(context.scene.mold_type_preview):
        def finish_silicone_outputs():
            for part in _slip_casting_plaster_mold_objects():
                part.name = ("silicone_mold_part_01" if part.name == "plaster_mold"
                             else part.name.replace("plaster_mold", "silicone_mold", 1))
                assign_generated_material(part.object)
        yield "Finishing silicone mold", finish_silicone_outputs
    yield "Refreshing display", refresh_display


def confirm(
    context,
    two_part_casting_side: str | None = None,
    cut_casting_open_base_side: bool = False,
    cut_casting_vertical: bool = True,
    pre_join_base_callback=None,
):
    steps = iter_confirm_steps(
        context,
        two_part_casting_side=two_part_casting_side,
        cut_casting_open_base_side=cut_casting_open_base_side,
        cut_casting_vertical=cut_casting_vertical,
        pre_join_base_callback=pre_join_base_callback,
    )
    while True:
        try:
            label, step = next(steps)
        except StopIteration as finished:
            return finished.value
        finish_task_sync(step())
        if label not in CONFIRM_SKIP_REDRAW_STEPS:
            refresh_generated_object_materials()
            refresh_viewport_material_display(context)
            force_viewport_redraw(context)
