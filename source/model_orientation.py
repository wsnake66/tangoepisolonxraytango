# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thin Blender adapter for worker-planned model orientation."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import bmesh  # type: ignore
import bpy  # type: ignore
import mathutils  # type: ignore

from .components.geometry_adapter import (
    begin_plan_auto_orientation_with_worker,
    begin_plan_selected_face_orientation_with_worker,
    plan_auto_orientation_with_worker,
)


logger = logging.getLogger(__name__)
AUTO_ORIENT_MAX_TILT_DEGREES = 30.0


@dataclass(frozen=True)
class AutoOrientationResult:
    base_tilt_degrees: float
    z_rotation_degrees: float
    base_area: float
    source_triangle_count: int
    analysis_triangle_count: int
    target_reduction: float


def _apply_worker_orientation(obj, plan) -> AutoOrientationResult:
    """Apply the worker's complete world-space orientation transform."""

    obj.matrix_world = mathutils.Matrix(plan.world_transform) @ obj.matrix_world
    bpy.context.view_layer.update()
    return AutoOrientationResult(
        base_tilt_degrees=plan.base_tilt_degrees,
        z_rotation_degrees=plan.z_rotation_degrees,
        base_area=plan.base_area,
        source_triangle_count=plan.source_triangle_count,
        analysis_triangle_count=plan.analysis_triangle_count,
        target_reduction=plan.target_reduction,
    )


def auto_orient_imported_model(
    obj,
    *,
    max_tilt_degrees: float = AUTO_ORIENT_MAX_TILT_DEGREES,
    min_footprint_ratio: float = 0.03,
    target_reduction: float | None = None,
    place_base_on_top: bool = False,
) -> AutoOrientationResult | None:
    """Ask the worker to simplify if needed and plan the full Auto Level."""

    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None
    plan = plan_auto_orientation_with_worker(
        obj,
        target_reduction=target_reduction,
        max_tilt_degrees=max_tilt_degrees,
        min_footprint_ratio=min_footprint_ratio,
        place_base_on_top=place_base_on_top,
    )
    if plan is None:
        return None
    result = _apply_worker_orientation(obj, plan)
    logger.info(
        "Worker auto-oriented model %s: base_tilt=%.3f degrees "
        "base_area=%.3f z_alignment=%.3f degrees source_triangles=%d "
        "analysis_triangles=%d target_reduction=%.2f%% base_placement=%s",
        obj.name,
        result.base_tilt_degrees,
        result.base_area,
        result.z_rotation_degrees,
        result.source_triangle_count,
        result.analysis_triangle_count,
        result.target_reduction * 100.0,
        "top" if place_base_on_top else "bottom",
    )
    return result


def begin_auto_orient_imported_model(
    obj,
    *,
    max_tilt_degrees: float = AUTO_ORIENT_MAX_TILT_DEGREES,
    min_footprint_ratio: float = 0.03,
    target_reduction: float | None = None,
    place_base_on_top: bool = False,
):
    """Plan orientation off-thread and apply its transform on main."""

    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None
    task = begin_plan_auto_orientation_with_worker(
        obj,
        target_reduction=target_reduction,
        max_tilt_degrees=max_tilt_degrees,
        min_footprint_ratio=min_footprint_ratio,
        place_base_on_top=place_base_on_top,
    )
    if task is None:
        return None
    return task.then(
        lambda plan: None if plan is None else _apply_worker_orientation(obj, plan)
    )


def begin_orient_selected_faces_to_base(obj, polygon_indices):
    """Plan selected-face orientation off-thread and apply it on main."""

    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None
    task = begin_plan_selected_face_orientation_with_worker(obj, polygon_indices)
    if task is None:
        return None
    return task.then(lambda plan: (
        None if plan is None else _apply_worker_orientation(obj, plan)
    ))


def selected_edit_face_indices(obj) -> tuple[int, ...]:
    """Return selected edit-mode polygon IDs without doing geometry math."""

    if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
        return ()
    edit_mesh = bmesh.from_edit_mesh(obj.data)
    edit_mesh.faces.ensure_lookup_table()
    edit_mesh.faces.index_update()
    selected = tuple(int(face.index) for face in edit_mesh.faces if face.select)
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=False)
    return selected


def raycast_face(context, event, obj) -> int | None:
    """Return the clicked Blender polygon ID; orientation stays in the worker."""

    from bpy_extras import view3d_utils  # type: ignore

    region = context.region
    region_data = context.region_data
    coordinate = (event.mouse_region_x, event.mouse_region_y)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coordinate)
    ray_direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coordinate)
    inverse = obj.matrix_world.inverted()
    local_origin = inverse @ ray_origin
    local_direction = (inverse.to_3x3() @ ray_direction).normalized()
    hit, _location, _normal, face_index = obj.ray_cast(
        local_origin,
        local_direction,
        distance=1.0e12,
    )
    if not hit or face_index < 0:
        return None
    return int(face_index)
