# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thin Blender bridge for protected worker-side mesh cleanup."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np


SLICER_WELD_DISTANCE = 1.0e-4
GENERATED_BOX_PREFIXES = ("box_part_", "casting_box_", "protective_shell")
GENERATED_BOX_SIDE_PREFIXES = ("left_", "right_")
UI_CLEANUP_REDRAW_MIN_FACETS = 50_000
BOOLEAN_CLEANUP_UI_REFRESH_INTERVAL = 0.1


@dataclass(frozen=True)
class SlicerCleanupStats:
    triangulated_faces: int
    welded_vertices: int
    dissolved_micro_edges: int
    degenerate_faces_removed: int
    duplicate_faces_removed: int
    boundary_loops_filled: int = 0
    flat_boundary_loops_stitched: int = 0

    @property
    def changed(self) -> bool:
        return any(self.__dict__.values())


@dataclass(frozen=True)
class SlicerCleanupPreflight:
    cleanup_required: bool
    reason: str
    vertex_count: int
    edge_count: int
    face_count: int


def is_generated_box_name(object_name: str) -> bool:
    normalized = str(object_name).casefold()
    for side_prefix in GENERATED_BOX_SIDE_PREFIXES:
        if normalized.startswith(side_prefix):
            normalized = normalized[len(side_prefix) :]
            break
    return normalized.startswith(GENERATED_BOX_PREFIXES)


def cleanup_ui_refresh_callback(mesh, callback: Callable[[], None] | None):
    if callback is None:
        return None
    mesh.calc_loop_triangles()
    return callback if len(mesh.loop_triangles) >= UI_CLEANUP_REDRAW_MIN_FACETS else None


def _mesh_arrays(mesh):
    mesh.calc_loop_triangles()
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.vertices.foreach_get("co", vertices.ravel())
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    materials = np.ascontiguousarray(
        [mesh.polygons[triangle.polygon_index].material_index for triangle in mesh.loop_triangles],
        dtype=np.int32,
    )
    return vertices, triangles, materials


def _worker_cleanup(
    mesh,
    *,
    matrix_world=None,
    generated_box: bool,
    max_passes: int,
    weld_distance: float | None,
    apply_result: bool,
    ui_refresh_callback: Callable[[], None] | None = None,
    ui_refresh_interval: float = BOOLEAN_CLEANUP_UI_REFRESH_INTERVAL,
):
    from .background_worker import submit_worker_task
    from .components.geometry_adapter import acquire_geometry_worker

    vertices, triangles, materials = _mesh_arrays(mesh)
    matrix = np.eye(4, dtype=np.float32) if matrix_world is None else np.ascontiguousarray(matrix_world, dtype=np.float32)
    worker = acquire_geometry_worker()
    worker_arguments = {
        "generated_box": generated_box,
        "max_passes": max_passes,
        "source_polygon_count": len(mesh.polygons),
        "weld_distance": weld_distance,
    }
    if ui_refresh_callback is None:
        result = worker.clean_slicer_mesh(
            vertices,
            triangles,
            matrix,
            **worker_arguments,
        )
    else:
        # Keep Blender API work on the caller thread while the protected
        # geometry request runs in the shared background queue. This polling
        # loop lets the modal progress overlay repaint during long repairs.
        task = submit_worker_task(
            worker.clean_slicer_mesh,
            vertices,
            triangles,
            matrix,
            **worker_arguments,
        )
        refresh_interval = max(float(ui_refresh_interval), 0.01)
        while not task.done():
            ui_refresh_callback()
            time.sleep(refresh_interval)
        result = task.finish()
        ui_refresh_callback()
    if apply_result and result.changed:
        mesh.clear_geometry()
        mesh.vertices.add(len(result.vertices))
        mesh.vertices.foreach_set("co", result.vertices.ravel())
        mesh.loops.add(len(result.triangles) * 3)
        mesh.loops.foreach_set("vertex_index", result.triangles.ravel())
        mesh.polygons.add(len(result.triangles))
        if len(result.triangles):
            mesh.polygons.foreach_set("loop_start", np.arange(0, len(result.triangles) * 3, 3, dtype=np.int32))
            mesh.polygons.foreach_set("loop_total", np.full(len(result.triangles), 3, dtype=np.int32))
            material_indices = np.zeros(len(result.triangles), dtype=np.int32)
            valid = (result.face_sources >= 0) & (result.face_sources < len(materials))
            material_indices[valid] = materials[result.face_sources[valid]]
            mesh.polygons.foreach_set("material_index", material_indices)
        mesh.validate(verbose=False, clean_customdata=False)
        mesh.update(calc_edges=True)
    return result


def _stats(result) -> SlicerCleanupStats:
    values = result.stats
    return SlicerCleanupStats(
        triangulated_faces=int(values.get("triangulated_faces", 0)),
        welded_vertices=int(values.get("welded_vertices", 0)),
        dissolved_micro_edges=int(values.get("dissolved_micro_edges", 0)),
        degenerate_faces_removed=int(values.get("degenerate_faces_removed", 0)),
        duplicate_faces_removed=int(values.get("duplicate_faces_removed", 0)),
        boundary_loops_filled=int(values.get("boundary_loops_filled", 0)),
        flat_boundary_loops_stitched=int(values.get("flat_boundary_loops_stitched", 0)),
    )


def inspect_mesh_for_slicer_cleanup(mesh, matrix_world=None) -> SlicerCleanupPreflight:
    result = _worker_cleanup(mesh, matrix_world=matrix_world, generated_box=False, max_passes=1, weld_distance=None, apply_result=False)
    initial = result.initial
    return SlicerCleanupPreflight(
        cleanup_required=bool(initial["cleanup_required"]),
        reason=str(initial["reason"]),
        vertex_count=int(initial["vertex_count"]),
        edge_count=int(initial["edge_count"]),
        face_count=int(initial["face_count"]),
    )


def generated_box_weld_distance(mesh) -> float:
    result = _worker_cleanup(mesh, generated_box=True, max_passes=1, weld_distance=None, apply_result=False)
    return float(result.weld_distance)


def clean_mesh_for_manifold_boolean(mesh, *, weld_distance: float = SLICER_WELD_DISTANCE) -> SlicerCleanupStats:
    from .progress import breathe_viewport

    return _stats(
        _worker_cleanup(
            mesh,
            generated_box=False,
            max_passes=1,
            weld_distance=float(weld_distance),
            apply_result=True,
            ui_refresh_callback=breathe_viewport,
            ui_refresh_interval=BOOLEAN_CLEANUP_UI_REFRESH_INTERVAL,
        )
    )


def clean_mesh_for_slicer(
    mesh,
    *,
    weld_distance: float = SLICER_WELD_DISTANCE,
    dissolve_coplanar: bool = False,
    stl_matrix_world=None,
    ui_refresh_callback: Callable[[], None] | None = None,
) -> SlicerCleanupStats:
    del dissolve_coplanar
    if ui_refresh_callback is not None:
        ui_refresh_callback()
    result = _worker_cleanup(mesh, matrix_world=stl_matrix_world, generated_box=False, max_passes=2, weld_distance=float(weld_distance), apply_result=True)
    if ui_refresh_callback is not None:
        ui_refresh_callback()
    return _stats(result)


def clean_generated_box_mesh(
    mesh,
    *,
    stl_matrix_world=None,
    ui_refresh_callback: Callable[[], None] | None = None,
) -> tuple[SlicerCleanupStats, float]:
    if ui_refresh_callback is not None:
        ui_refresh_callback()
    result = _worker_cleanup(mesh, matrix_world=stl_matrix_world, generated_box=True, max_passes=2, weld_distance=None, apply_result=True)
    if ui_refresh_callback is not None:
        ui_refresh_callback()
    return _stats(result), float(result.weld_distance)
