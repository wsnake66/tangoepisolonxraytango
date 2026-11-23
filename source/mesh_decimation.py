from __future__ import annotations

import time
import logging
from functools import lru_cache

import bpy  # type: ignore

from .background_worker import submit_worker_task
from .components.geometry_adapter import (
    acquire_geometry_worker,
    mesh_manifold_edge_counts_lightweight,
)
from .nearest_surface_worker_client import NearestSurfaceWorkerError

logger = logging.getLogger(__name__)

try:
    import numpy as np
except ImportError:
    np = None


def begin_fast_simplification_available():
    worker = acquire_geometry_worker()
    return submit_worker_task(worker.simplification_available)


def _simplify_arrays(vertices, faces, target_reduction: float):
    try:
        return acquire_geometry_worker().simplify_mesh(
            vertices,
            faces,
            target_reduction=target_reduction,
        )
    except NearestSurfaceWorkerError as error:
        if "fast-simplification" in str(error):
            raise RuntimeError("fast-simplification is not available") from error
        raise


def mesh_manifold_edge_counts(mesh):
    """Return manifold state, all bad edges, and boundary/open edges."""
    return mesh_manifold_edge_counts_lightweight(mesh)


def mesh_manifold_state(mesh):
    is_manifold, non_manifold_edges, _open_edges = mesh_manifold_edge_counts(mesh)
    return is_manifold, non_manifold_edges


@lru_cache(maxsize=64)
def _simplification_policy(triangle_count: int, mode: str) -> dict:
    return acquire_geometry_worker().geometry_policy(
        "simplification_target",
        triangle_count=int(triangle_count),
        mode=mode,
    )


def get_adaptive_target_triangle_count(triangle_count: int) -> int | None:
    result = _simplification_policy(int(triangle_count), "adaptive")
    target = result["target_triangles"]
    return None if target is None else int(target)


def get_adaptive_target_reduction(triangle_count: int) -> float | None:
    result = _simplification_policy(int(triangle_count), "adaptive")
    reduction = result["target_reduction"]
    return None if reduction is None else float(reduction)


def get_direct_undercuts_target_triangle_count(
    triangle_count: int,
) -> int | None:
    """Return the aggressive analysis target used by Direct undercuts."""
    result = _simplification_policy(int(triangle_count), "direct_undercuts")
    target = result["target_triangles"]
    return None if target is None else int(target)


def get_direct_undercuts_target_reduction(
    triangle_count: int,
) -> float | None:
    result = _simplification_policy(int(triangle_count), "direct_undercuts")
    reduction = result["target_reduction"]
    return None if reduction is None else float(reduction)


def begin_direct_undercuts_target_reduction(triangle_count: int):
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.geometry_policy,
        "simplification_target",
        triangle_count=int(triangle_count),
        mode="direct_undercuts",
        on_complete=lambda result: (
            None
            if result["target_reduction"] is None
            else float(result["target_reduction"])
        ),
    )


def extract_mesh_triangles(mesh):
    if np is None:
        vertices = [tuple(vertex.co) for vertex in mesh.vertices]
        faces = [tuple(loop_triangle.vertices) for loop_triangle in mesh.loop_triangles]
        return vertices, faces

    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    faces = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.vertices.foreach_get("co", vertices.ravel())
    mesh.loop_triangles.foreach_get("vertices", faces.ravel())
    return vertices, faces


def create_mesh_from_triangles(name, vertices, faces):
    if np is None:
        new_mesh = bpy.data.meshes.new(name)
        new_mesh.from_pydata(vertices, [], faces)
        new_mesh.update()
        return new_mesh

    vertices = np.ascontiguousarray(vertices, dtype=np.float32)
    faces = np.ascontiguousarray(faces, dtype=np.int32)
    face_count = len(faces)
    loop_count = face_count * 3

    new_mesh = bpy.data.meshes.new(name)
    new_mesh.vertices.add(len(vertices))
    new_mesh.vertices.foreach_set("co", vertices.ravel())
    new_mesh.loops.add(loop_count)
    new_mesh.loops.foreach_set("vertex_index", faces.ravel())
    new_mesh.polygons.add(face_count)
    new_mesh.polygons.foreach_set(
        "loop_start", np.arange(0, loop_count, 3, dtype=np.int32)
    )
    new_mesh.polygons.foreach_set("loop_total", np.full(face_count, 3, dtype=np.int32))
    new_mesh.update()
    return new_mesh


def run_fast_simplification_benchmark(obj, collection):
    total_start = time.time()
    phase_start = total_start

    mesh = obj.data
    mesh.calc_loop_triangles()
    triangulation_elapsed = time.time() - phase_start
    original_triangle_count = len(mesh.loop_triangles)
    target_triangles = get_adaptive_target_triangle_count(original_triangle_count)
    if target_triangles is None:
        return {
            "skipped": True,
            "message": "Mesh has fewer than 1M triangles. Skipping fast decimation.",
        }

    phase_start = time.time()
    vertices, faces = extract_mesh_triangles(mesh)
    extraction_elapsed = time.time() - phase_start

    if len(vertices) == 0 or original_triangle_count == 0:
        raise ValueError("Active mesh has no triangles to simplify")

    adaptive_target_reduction = get_adaptive_target_reduction(
        original_triangle_count
    )
    if adaptive_target_reduction is None or adaptive_target_reduction <= 0.0:
        return {
            "skipped": True,
            "message": "Mesh is below the adaptive decimation threshold.",
        }
    target_reduction = adaptive_target_reduction

    phase_start = time.time()
    worker_result = _simplify_arrays(
        vertices,
        faces,
        target_reduction=target_reduction,
    )
    simplification_roundtrip_elapsed = time.time() - phase_start
    simplification_elapsed = worker_result.simplification_seconds
    new_vertices = worker_result.vertices
    new_faces = worker_result.triangles

    phase_start = time.time()
    if np is None:
        simplified_vertices = [
            tuple(float(coordinate) for coordinate in vertex) for vertex in new_vertices
        ]
        simplified_faces = [tuple(int(index) for index in face) for face in new_faces]
    else:
        simplified_vertices = np.ascontiguousarray(new_vertices, dtype=np.float32)
        simplified_faces = np.ascontiguousarray(new_faces, dtype=np.int32)
    conversion_elapsed = time.time() - phase_start

    phase_start = time.time()
    new_mesh = create_mesh_from_triangles(
        f"{obj.name}_fast_simplified_mesh",
        simplified_vertices,
        simplified_faces,
    )
    mesh_creation_elapsed = time.time() - phase_start

    phase_start = time.time()
    simplified_is_manifold, simplified_non_manifold_edges = mesh_manifold_state(
        new_mesh
    )
    simplified_manifold_elapsed = time.time() - phase_start

    phase_start = time.time()
    new_obj = bpy.data.objects.new(f"{obj.name}_fast_simplified", new_mesh)
    new_obj.matrix_world = obj.matrix_world.copy()
    collection.objects.link(new_obj)
    link_elapsed = time.time() - phase_start

    resulting_triangle_count = len(simplified_faces)
    reduction = (1.0 - (resulting_triangle_count / original_triangle_count)) * 100.0
    total_elapsed = time.time() - total_start

    return {
        "skipped": False,
        "original_triangle_count": original_triangle_count,
        "target_triangles": target_triangles,
        "target_reduction": target_reduction,
        "adaptive_target_reduction": adaptive_target_reduction,
        "resulting_triangle_count": resulting_triangle_count,
        "reduction": reduction,
        "simplification_elapsed": simplification_elapsed,
        "simplification_roundtrip_elapsed": simplification_roundtrip_elapsed,
        "total_elapsed": total_elapsed,
        "triangulation_elapsed": triangulation_elapsed,
        "extraction_elapsed": extraction_elapsed,
        "conversion_elapsed": conversion_elapsed,
        "mesh_creation_elapsed": mesh_creation_elapsed,
        "simplified_manifold_elapsed": simplified_manifold_elapsed,
        "link_elapsed": link_elapsed,
        "simplified_is_manifold": simplified_is_manifold,
        "simplified_non_manifold_edges": simplified_non_manifold_edges,
    }


def create_fast_simplified_object(
    obj,
    collection,
    name="patron",
    target_reduction=0.8,
):
    total_start = time.perf_counter()
    phase_start = total_start
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangulation_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    vertices, faces = extract_mesh_triangles(mesh)
    extraction_elapsed = time.perf_counter() - phase_start
    if len(vertices) == 0 or len(faces) == 0:
        raise ValueError("Mesh has no triangles to simplify")

    phase_start = time.perf_counter()
    worker_result = _simplify_arrays(
        vertices,
        faces,
        target_reduction=target_reduction,
    )
    simplification_roundtrip_elapsed = time.perf_counter() - phase_start
    simplification_elapsed = worker_result.simplification_seconds
    new_vertices = worker_result.vertices
    new_faces = worker_result.triangles

    phase_start = time.perf_counter()
    if np is None:
        simplified_vertices = [
            tuple(float(coordinate) for coordinate in vertex)
            for vertex in new_vertices
        ]
        simplified_faces = [tuple(int(index) for index in face) for face in new_faces]
    else:
        simplified_vertices = np.ascontiguousarray(new_vertices, dtype=np.float32)
        simplified_faces = np.ascontiguousarray(new_faces, dtype=np.int32)
    conversion_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    new_mesh = create_mesh_from_triangles(
        f"{name}_mesh",
        simplified_vertices,
        simplified_faces,
    )
    mesh_creation_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    new_obj = bpy.data.objects.new(name, new_mesh)
    object_creation_elapsed = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    new_obj.matrix_world = obj.matrix_world.copy()
    transform_elapsed = time.perf_counter() - phase_start
    phase_start = time.perf_counter()
    collection.objects.link(new_obj)
    link_elapsed = time.perf_counter() - phase_start
    original_triangle_count = len(faces)
    resulting_triangle_count = len(simplified_faces)
    actual_reduction = (
        1.0 - (resulting_triangle_count / original_triangle_count)
    ) * 100.0
    logger.info(
        "Fast simplified object created in %.3fs: source=%s name=%s "
        "triangles=%d target_reduction=%.2f%% resulting_triangles=%d "
        "actual_reduction=%.2f%% triangulate=%.3fs, "
        "extract=%.3fs, simplify=%.3fs, worker_roundtrip=%.3fs, "
        "convert=%.3fs, mesh_create=%.3fs, "
        "object_create=%.3fs, transform=%.3fs, link=%.3fs",
        time.perf_counter() - total_start,
        obj.name,
        name,
        original_triangle_count,
        target_reduction * 100.0,
        resulting_triangle_count,
        actual_reduction,
        triangulation_elapsed,
        extraction_elapsed,
        simplification_elapsed,
        simplification_roundtrip_elapsed,
        conversion_elapsed,
        mesh_creation_elapsed,
        object_creation_elapsed,
        transform_elapsed,
        link_elapsed,
    )
    return new_obj


def begin_create_fast_simplified_object(
    obj,
    collection,
    name="patron",
    target_reduction=0.8,
):
    """Simplify arrays off-thread and create the Blender object on main."""

    mesh = obj.data
    mesh.calc_loop_triangles()
    vertices, faces = extract_mesh_triangles(mesh)
    if len(vertices) == 0 or len(faces) == 0:
        raise ValueError("Mesh has no triangles to simplify")
    matrix_world = obj.matrix_world.copy()
    original_triangle_count = len(faces)
    worker = acquire_geometry_worker()

    def finish(worker_result):
        new_mesh = create_mesh_from_triangles(
            f"{name}_mesh",
            worker_result.vertices,
            worker_result.triangles,
        )
        new_obj = bpy.data.objects.new(name, new_mesh)
        new_obj.matrix_world = matrix_world
        collection.objects.link(new_obj)
        logger.info(
            "Async fast simplified object created: source=%s name=%s "
            "triangles=%d resulting_triangles=%d target_reduction=%.2f%% "
            "worker=%.3fs",
            obj.name,
            name,
            original_triangle_count,
            len(worker_result.triangles),
            target_reduction * 100.0,
            worker_result.simplification_seconds,
        )
        return new_obj

    return submit_worker_task(
        worker.simplify_mesh,
        vertices,
        faces,
        target_reduction=target_reduction,
        on_complete=finish,
    )


def print_fast_simplification_benchmark(result):
    print(f"Original triangle count: {result['original_triangle_count']}")
    print(f"Target triangle count: {result['target_triangles']}")
    print(f"Adaptive target reduction: {result['adaptive_target_reduction'] * 100.0:.2f}%")
    print(f"Applied target reduction: {result['target_reduction'] * 100.0:.2f}%")
    print(f"Resulting triangle count: {result['resulting_triangle_count']}")
    print(f"Percentage reduction: {result['reduction']:.2f}%")
    print(f"Simplification execution time: {result['simplification_elapsed']:.3f}s")
    print(
        "Simplification worker round-trip time: "
        f"{result['simplification_roundtrip_elapsed']:.3f}s"
    )
    print(f"Total operator execution time: {result['total_elapsed']:.3f}s")
    print(f"Triangulation time: {result['triangulation_elapsed']:.3f}s")
    print(f"Geometry extraction time: {result['extraction_elapsed']:.3f}s")
    print(f"Result conversion time: {result['conversion_elapsed']:.3f}s")
    print(f"Mesh creation/update time: {result['mesh_creation_elapsed']:.3f}s")
    print(
        f"Resulting manifold check time: "
        f"{result['simplified_manifold_elapsed']:.3f}s"
    )
    print(f"Object link/transform time: {result['link_elapsed']:.3f}s")
    print(
        "Resulting manifold: "
        f"{result['simplified_is_manifold']} "
        f"({result['simplified_non_manifold_edges']} non-manifold edges)"
    )
