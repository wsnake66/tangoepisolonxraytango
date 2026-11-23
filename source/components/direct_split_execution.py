"""GPL Blender adapter for worker-planned direct mold splits."""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import Future

import bpy  # type: ignore
import mathutils  # type: ignore

from ..object import Object
from ..modifiers import diff_mod
from ..background_worker import BackgroundWorkerTask, finish_task_sync
from ..progress import breathe_viewport
from .geometry_adapter import acquire_geometry_worker, begin_plan_object_split_cells

SPLIT_SECTION_SIDES_KEY = "_moldboxer_split_section_sides"
logger = logging.getLogger(__name__)


def _split_plane_spec_point_and_normal(
    plane_spec,
) -> tuple[mathutils.Vector, mathutils.Vector]:
    if isinstance(plane_spec, dict):
        point = mathutils.Vector(plane_spec["point"])
        normal = mathutils.Vector(plane_spec["normal"])
    else:
        point = mathutils.Vector(plane_spec[0])
        normal = mathutils.Vector(plane_spec[1])
    if normal.length <= 1e-9:
        normal = mathutils.Vector((0.0, 0.0, 1.0))
    return point, normal.normalized()


def _is_organic_split_spec(plane_spec) -> bool:
    return isinstance(plane_spec, dict) and plane_spec.get("type") == "organic"


def _mesh_object_from_spec(mesh_spec: dict, name: str) -> Object:
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(mesh_spec["vertices"], [], mesh_spec["faces"])
    mesh.update()
    raw_object = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(raw_object)
    return Object(raw_object)


def _extend_organic_mesh_spec_to_target(
    mesh_spec: dict,
    target: Object,
    normal: mathutils.Vector,
) -> dict:
    """Pass mesh data and Blender bounds to the protected geometry worker."""
    return acquire_geometry_worker().organic_plane(
        "extend_split_mesh",
        mesh_spec=mesh_spec,
        target_bounds=[
            list(target.object.matrix_world @ mathutils.Vector(corner))
            for corner in target.object.bound_box
        ],
        target_span=max(target.width, target.depth, target.height),
        normal=list(normal),
    )


def _classify_organic_split_parts(
    parts: list[Object],
    plane_spec: dict,
    point: mathutils.Vector,
    normal: mathutils.Vector,
) -> tuple[list[Object], list[Object]]:
    # Preserve Blender's polygon tessellation and normals at the data boundary.
    mesh = bpy.data.meshes.new("_organic_classification_surface")
    try:
        surface = plane_spec["surface"]
        mesh.from_pydata(surface["vertices"], [], surface["faces"])
        mesh.update()
        mesh.calc_loop_triangles()
        surface_data = {
            "vertices": [list(vertex.co) for vertex in mesh.vertices],
            "triangles": [list(triangle.vertices) for triangle in mesh.loop_triangles],
            "normals": [
                list(mesh.polygons[triangle.polygon_index].normal)
                for triangle in mesh.loop_triangles
            ],
        }
    finally:
        bpy.data.meshes.remove(mesh)

    # Transport only the same vertex samples previously used by the local BVH.
    part_data = []
    for part in parts:
        vertices = part.object.data.vertices
        stride = max(1, len(vertices) // 512)
        part_data.append({
            "points": [
                list(part.object.matrix_world @ vertices[index].co)
                for index in range(0, len(vertices), stride)
            ],
            "center": list(part.center_coords),
        })
    result = acquire_geometry_worker().organic_plane(
        "classify_split_parts",
        surface=surface_data,
        parts=part_data,
        reference_point=list(point),
        reference_normal=list(normal),
    )
    return (
        [parts[index] for index in result["negative"]],
        [parts[index] for index in result["positive"]],
    )


def _split_with_organic_spec(
    piece: Object,
    plane_spec: dict,
    *,
    preserve_isolated_meshes: bool,
) -> tuple[Object, Object]:
    point, normal = _split_plane_spec_point_and_normal(plane_spec)
    cutter_spec = _extend_organic_mesh_spec_to_target(
        plane_spec["cutter"],
        piece,
        normal,
    )
    surface_spec = _extend_organic_mesh_spec_to_target(
        plane_spec["surface"],
        piece,
        normal,
    )
    cutter = _mesh_object_from_spec(
        cutter_spec,
        f"{piece.name}_organic_split_cutter",
    )
    original_name = piece.name
    try:
        piece.apply_boolean_modifier_with_geometry_fallback(diff_mod, cutter)
        usable_parts = []
        for part in piece.split_isolated_meshes():
            data = getattr(part.object, "data", None)
            if data is None or not data.vertices or not data.polygons:
                part.remove()
                continue
            usable_parts.append(part)
        if len(usable_parts) < 2:
            raise ValueError(
                "Organic cutter did not fully cross the target; no two-sided "
                f"split was produced for {original_name}"
            )
        classification_spec = dict(plane_spec)
        classification_spec["surface"] = surface_spec
        negative_side, positive_side = _classify_organic_split_parts(
            usable_parts,
            classification_spec,
            point,
            normal,
        )
        finish_side = (
            Object._join_split_side
            if preserve_isolated_meshes
            else Object._keep_largest_split_side
        )
        return (
            finish_side(negative_side, f"{original_name}_l"),
            finish_side(positive_side, f"{original_name}_r"),
        )
    finally:
        if cutter.object.name in bpy.data.objects:
            cutter.remove()


def split_object_by_direct_plane_specs(
    box: Object,
    plane_specs: list[list[list[float]]],
    after_split_callback=None,
    *,
    preserve_isolated_meshes: bool = False,
    section_plane_indices: list[int] | None = None,
    section_plane_count: int | None = None,
    output_name_prefix: str = "box_part",
    plan_from_cuts: bool = False,
) -> list[Object]:
    return finish_task_sync(
        begin_split_object_by_direct_plane_specs(
            box,
            plane_specs,
            after_split_callback,
            preserve_isolated_meshes=preserve_isolated_meshes,
            section_plane_indices=section_plane_indices,
            section_plane_count=section_plane_count,
            output_name_prefix=output_name_prefix,
            plan_from_cuts=plan_from_cuts,
        )
    )


def begin_split_object_by_direct_plane_specs(
    box: Object,
    plane_specs: list[list[list[float]]],
    after_split_callback=None,
    *,
    preserve_isolated_meshes: bool = False,
    section_plane_indices: list[int] | None = None,
    section_plane_count: int | None = None,
    output_name_prefix: str = "box_part",
    plan_from_cuts: bool = False,
):
    """Split on main, optionally deriving flat-plane cells from surviving cuts.

    Organic surfaces and two-sided callbacks retain worker planning.
    """

    total_start = time.perf_counter()
    source_name = box.name
    plane_indices = (
        list(range(len(plane_specs)))
        if section_plane_indices is None
        else [int(value) for value in section_plane_indices]
    )
    if len(plane_indices) != len(plane_specs):
        raise ValueError("section_plane_indices must match plane_specs")
    stored_plane_count = (
        len(plane_specs)
        if section_plane_count is None
        else int(section_plane_count)
    )
    if any(index < 0 or index >= stored_plane_count for index in plane_indices):
        raise ValueError("section plane index is outside the stored side vector")

    plan_start = time.perf_counter()
    planning_specs = []
    for spec in plane_specs:
        planning_point, planning_normal = _split_plane_spec_point_and_normal(spec)
        if not all(math.isfinite(value) for value in (*planning_point, *planning_normal)):
            raise ValueError("Split plane coordinates and normal must be finite")
        planning_specs.append(
            [list(planning_point), list(planning_normal)]
        )
    derive_from_cuts = (
        plan_from_cuts
        and after_split_callback is None
        and not any(_is_organic_split_spec(spec) for spec in plane_specs)
    )
    if derive_from_cuts:
        # Preserve the pollable task API and main-thread finalization without
        # uploading the mesh or dispatching a geometry-planning worker call.
        ready = Future()
        ready.set_result(())
        task = BackgroundWorkerTask(ready)
    else:
        task = begin_plan_object_split_cells(box.object, planning_specs)

    def finish(planned_rows):
        planned_cells = [
            tuple(int(value) for value in row) for row in planned_rows
        ]
        plan_seconds = 0.0 if derive_from_cuts else time.perf_counter() - plan_start
        pieces: list[tuple[Object, tuple[int, ...]]] = [(box, ())]
        split_count = 0
        blender_split_start = time.perf_counter()
        for plane_index, plane_spec in enumerate(plane_specs):
            point, normal = _split_plane_spec_point_and_normal(plane_spec)
            next_pieces: list[tuple[Object, tuple[int, ...]]] = []
            for piece, path in pieces:
                child_sides = {-1, 1} if derive_from_cuts else {
                    cell[plane_index]
                    for cell in planned_cells
                    if cell[:plane_index] == path
                }
                if not child_sides:
                    raise RuntimeError(
                        "worker split plan does not contain a Blender piece"
                    )
                if len(child_sides) == 1:
                    next_pieces.append(
                        (piece, path + (next(iter(child_sides)),))
                    )
                    continue

                if _is_organic_split_spec(plane_spec):
                    split_a, split_b = _split_with_organic_spec(
                        piece,
                        plane_spec,
                        preserve_isolated_meshes=preserve_isolated_meshes,
                    )
                else:
                    split_options = {
                        "preserve_isolated_meshes": preserve_isolated_meshes,
                    }
                    if derive_from_cuts:
                        split_options["allow_empty_sides"] = True
                    split_a, split_b = piece.split_optimized(
                        normal, point, **split_options,
                    )
                split_count += 1
                if after_split_callback is not None:
                    after_split_callback(plane_index, split_a, split_b)
                for split_piece, side in ((split_a, -1), (split_b, 1)):
                    if (
                        split_piece is not None
                        and split_piece.object.name in bpy.data.objects
                    ):
                        next_pieces.append((split_piece, path + (side,)))
                breathe_viewport()
            pieces = next_pieces

        output = []
        for index, (piece, path) in enumerate(pieces, start=1):
            stored_sides = [0] * stored_plane_count
            for local_index, side in enumerate(path):
                stored_sides[plane_indices[local_index]] = side
            piece.object[SPLIT_SECTION_SIDES_KEY] = stored_sides
            piece.name = f"{output_name_prefix}_{index:02d}"
            output.append(piece)
        logger.info(
            "Direct split complete: object=%s planes=%d planned_cells=%d "
            "split_calls=%d output_parts=%d worker_plan=%.3fs "
            "blender_split=%.3fs total=%.3fs planning=%s",
            source_name,
            len(plane_specs),
            len(planned_cells),
            split_count,
            len(output),
            plan_seconds,
            time.perf_counter() - blender_split_start,
            time.perf_counter() - total_start,
            "actual_cuts" if derive_from_cuts else "worker",
        )
        return output

    return task.then(finish)
