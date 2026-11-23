# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thin Blender adapter for the external geometry worker."""

from __future__ import annotations

import logging
import time
from threading import Lock

import bpy  # type: ignore
import mathutils  # type: ignore
import numpy as np
from bpy.app.handlers import persistent  # type: ignore

from ..background_worker import (
    BackgroundTaskSequence,
    shutdown_background_worker_tasks,
    submit_worker_task,
)
from ..modifiers import build_voxel_modifier
from ..nearest_surface_worker_client import (
    NearestSurfaceWorkerError,
    TriangleBVHWorker,
)
from ..object import Object, remove_objects_safely
from ..split_specs import representative_split_specs, split_spec_point_normal
from ..patron_state import IMPORTED_VOLUME_ML_KEY


logger = logging.getLogger(__name__)


_WORKER_WATERMARK_REVISION_KEY = "_moldboxer_worker_watermark_revision"
_pending_watermark_cleanup = None


_persistent_accelerator: TriangleBVHWorker | None = None
_geometry_worker_acquire_lock = Lock()
_geometry_worker_authorize_lock = Lock()
_geometry_worker_cache_registered = False
_cached_target_signature: tuple | None = None
_cached_target_object_pointer: int | None = None
_cached_target_data_pointer: int | None = None
_cached_target_dirty = True


def _blender_id_pointer(blender_id) -> int | None:
    if blender_id is None:
        return None
    original = getattr(blender_id, "original", blender_id)
    try:
        return int(original.as_pointer())
    except (AttributeError, ReferenceError):
        return None


@persistent
def _invalidate_nearest_surface_target_on_depsgraph_update(
    _scene, depsgraph
) -> None:
    """Invalidate the retained BVH when its Blender target changes."""

    global _cached_target_dirty
    if _cached_target_dirty:
        return
    if (
        _cached_target_object_pointer is None
        and _cached_target_data_pointer is None
    ):
        return
    for update in depsgraph.updates:
        updated_pointer = _blender_id_pointer(update.id)
        target_data_changed = updated_pointer == _cached_target_data_pointer
        target_object_geometry_changed = (
            updated_pointer == _cached_target_object_pointer
            and (
                bool(getattr(update, "is_updated_geometry", False))
                or bool(getattr(update, "is_updated_transform", False))
            )
        )
        if target_data_changed or target_object_geometry_changed:
            _cached_target_dirty = True
            logger.info(
                "Nearest-surface persistent target cache invalidated: "
                "reason=depsgraph_update"
            )
            return


@persistent
def _shutdown_nearest_surface_worker_before_file_load(_unused) -> None:
    shutdown_nearest_surface_worker()


def _replace_handler(handler_list, callback) -> None:
    """Replace stale copies left by Reload from Repo, then register callback."""

    for existing in tuple(handler_list):
        if (
            getattr(existing, "__module__", None) == __name__
            and getattr(existing, "__name__", None) == callback.__name__
        ):
            handler_list.remove(existing)
    handler_list.append(callback)


def register_nearest_surface_worker_cache() -> None:
    global _geometry_worker_cache_registered

    _replace_handler(
        bpy.app.handlers.depsgraph_update_post,
        _invalidate_nearest_surface_target_on_depsgraph_update,
    )
    _replace_handler(
        bpy.app.handlers.load_pre,
        _shutdown_nearest_surface_worker_before_file_load,
    )
    with _geometry_worker_acquire_lock:
        _geometry_worker_cache_registered = True


def unregister_nearest_surface_worker_cache() -> None:
    for handler_list, callback in (
        (
            bpy.app.handlers.depsgraph_update_post,
            _invalidate_nearest_surface_target_on_depsgraph_update,
        ),
        (
            bpy.app.handlers.load_pre,
            _shutdown_nearest_surface_worker_before_file_load,
        ),
    ):
        for existing in tuple(handler_list):
            if existing is callback or (
                getattr(existing, "__module__", None) == __name__
                and getattr(existing, "__name__", None) == callback.__name__
            ):
                handler_list.remove(existing)
    shutdown_background_worker_tasks()
    shutdown_nearest_surface_worker()


def shutdown_nearest_surface_worker(*, force: bool = False) -> None:
    global _persistent_accelerator
    global _cached_target_signature
    global _cached_target_object_pointer
    global _cached_target_data_pointer
    global _cached_target_dirty
    global _geometry_worker_cache_registered

    with _geometry_worker_acquire_lock:
        _geometry_worker_cache_registered = False
        accelerator = _persistent_accelerator
        _persistent_accelerator = None
        _cached_target_signature = None
        _cached_target_object_pointer = None
        _cached_target_data_pointer = None
        _cached_target_dirty = True
    if accelerator is not None:
        pid = accelerator._process.pid
        accelerator.close(force=force)
        logger.info("Nearest-surface persistent worker stopped: pid=%d", pid)


def _target_cache_signature(target_object) -> tuple:
    target_data = target_object.data
    matrix_values = tuple(
        float(value) for row in target_object.matrix_world for value in row
    )
    return (
        _blender_id_pointer(target_object),
        _blender_id_pointer(target_data),
        len(target_data.vertices),
        len(target_data.edges),
        len(target_data.polygons),
        len(target_data.loops),
        matrix_values,
    )


def _authorize_geometry_worker(accelerator: TriangleBVHWorker) -> None:
    """Give the worker a short-lived server authorization when needed."""

    with _geometry_worker_authorize_lock:
        # Import lazily: auth uses this worker for its own HTTP transport when
        # an access token needs refreshing.
        from .auth import get_geometry_access_token
        from ..environment import is_dev_mode

        # Let authorize_worker reuse its grant only after comparing the current
        # token. A valid grant may still belong to a previous account or tier.
        _authorize_geometry_worker_with_token_refresh(
            accelerator,
            get_geometry_access_token,
            dev_requested=is_dev_mode(),
        )


def _is_worker_access_token_rejection(error: BaseException) -> bool:
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "unauthorized",
            "invalid access token",
            "access token expired",
            "log in again",
        )
    )


def _authorize_geometry_worker_with_token_refresh(
    accelerator: TriangleBVHWorker,
    token_getter,
    *,
    dev_requested: bool,
) -> None:
    """Authorize, silently replacing a stale cached access token once."""

    access_token = token_getter()
    if not access_token:
        raise NearestSurfaceWorkerError(
            "A valid Moldboxer license session is required for geometry processing"
        )

    try:
        accelerator.authorize_worker(
            access_token,
            dev_requested=dev_requested,
        )
        return
    except NearestSurfaceWorkerError as error:
        if not _is_worker_access_token_rejection(error):
            raise

    # Blender can still consider a cached access token valid after its backing
    # server session has rotated. Refresh and retry here so modal operators do
    # not turn that recoverable mismatch into a visible license dialog.
    logger.info("Refreshing a stale geometry-worker access token")
    refreshed_access_token = token_getter(force_refresh=True)
    if not refreshed_access_token:
        raise NearestSurfaceWorkerError(
            "A valid Moldboxer license session is required for geometry processing"
        )
    accelerator.authorize_worker(
        refreshed_access_token,
        dev_requested=dev_requested,
    )


def acquire_geometry_worker(
    *,
    register_cache: bool = True,
    authorize: bool = True,
) -> TriangleBVHWorker:
    """Return the shared worker without extracting or building a mesh target."""

    global _persistent_accelerator

    if register_cache:
        register_nearest_surface_worker_cache()
    created = False
    with _geometry_worker_acquire_lock:
        if not _geometry_worker_cache_registered:
            raise RuntimeError("Geometry worker cache is shutting down")
        accelerator = _persistent_accelerator
        if accelerator is None or not accelerator.is_running:
            if accelerator is not None:
                accelerator.close(force=True)
            accelerator = TriangleBVHWorker(require_native=True)
            _persistent_accelerator = accelerator
            created = True

    if created:
        logger.info(
            "Persistent geometry worker ready without target: pid=%d",
            accelerator._process.pid,
        )
    if authorize:
        _authorize_geometry_worker(accelerator)
    return accelerator


def begin_custom_face_core_geometry(dimensions=None):
    """Authorize and request head geometry without blocking Blender's UI."""

    from .auth import begin_get_valid_access_token
    from ..environment import is_dev_mode

    worker = acquire_geometry_worker(authorize=False)
    requested_dimensions = dict(dimensions) if dimensions is not None else None

    def steps():
        started = time.perf_counter()
        access_token = yield begin_get_valid_access_token()
        token_ready = time.perf_counter()
        if not access_token:
            raise NearestSurfaceWorkerError(
                "A valid Moldboxer license session is required for geometry processing"
            )
        try:
            yield submit_worker_task(
                worker.authorize_worker,
                access_token,
                dev_requested=is_dev_mode(),
            )
        except NearestSurfaceWorkerError as error:
            if not _is_worker_access_token_rejection(error):
                raise
            logger.info("Refreshing a stale custom-face geometry access token")
            access_token = yield begin_get_valid_access_token(force_refresh=True)
            if not access_token:
                raise NearestSurfaceWorkerError(
                    "A valid Moldboxer license session is required for geometry processing"
                )
            yield submit_worker_task(
                worker.authorize_worker,
                access_token,
                dev_requested=is_dev_mode(),
            )
        authorization_ready = time.perf_counter()
        logger.info(
            "Custom-face worker authorization ready: token=%.3fs "
            "authorization=%.3fs total=%.3fs",
            token_ready - started,
            authorization_ready - token_ready,
            authorization_ready - started,
        )
        return (yield submit_worker_task(worker.custom_face_core, requested_dimensions))

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _acquire_target_accelerator(
    target_object, *, cache_identity_object=None
):
    """Return the retained worker, rebuilding only for a changed target."""

    global _persistent_accelerator
    global _cached_target_signature
    global _cached_target_object_pointer
    global _cached_target_data_pointer
    global _cached_target_dirty

    register_nearest_surface_worker_cache()
    identity_object = cache_identity_object or target_object
    signature = _target_cache_signature(identity_object)
    accelerator = acquire_geometry_worker()
    worker_running = True
    cache_hit = (
        worker_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    if cache_hit:
        logger.info(
            "Nearest-surface persistent target cache hit: pid=%d "
            "backend=%s vertices=%d triangles=%d nodes=%d "
            "target_extract=0.000s worker_build=0.000s",
            accelerator._process.pid,
            accelerator.backend,
            accelerator.vertex_count,
            accelerator.triangle_count,
            accelerator.node_count,
        )
        return accelerator, True, 0.0, 0.0

    if not worker_running:
        miss_reason = "worker_not_running"
    elif _cached_target_dirty:
        miss_reason = "target_invalidated"
    else:
        miss_reason = "different_target"
    logger.info(
        "Nearest-surface persistent target cache miss: reason=%s",
        miss_reason,
    )

    extraction_start = time.perf_counter()
    target_vertices, target_triangles = _target_surface_arrays(target_object)
    extraction_elapsed = time.perf_counter() - extraction_start

    build_start = time.perf_counter()
    if not worker_running:
        accelerator = acquire_geometry_worker()
    accelerator.build_target(target_vertices, target_triangles)
    build_elapsed = time.perf_counter() - build_start

    _cached_target_signature = signature
    _cached_target_object_pointer = _blender_id_pointer(identity_object)
    _cached_target_data_pointer = _blender_id_pointer(identity_object.data)
    _cached_target_dirty = False
    logger.info(
        "Nearest-surface persistent target cache stored: pid=%d "
        "vertices=%d triangles=%d nodes=%d process_reused=%s",
        accelerator._process.pid,
        accelerator.vertex_count,
        accelerator.triangle_count,
        accelerator.node_count,
        miss_reason != "worker_not_running",
    )
    return accelerator, False, extraction_elapsed, build_elapsed


def _build_simplified_envelope_with_cache(
    target_object,
    *,
    cache_identity_object,
    target_reduction: float,
    envelope_options: dict,
):
    """Simplify, retain the target BVH and build without a Blender round-trip."""

    global _cached_target_signature
    global _cached_target_object_pointer
    global _cached_target_data_pointer
    global _cached_target_dirty

    register_nearest_surface_worker_cache()
    identity_object = cache_identity_object or target_object
    signature = _target_cache_signature(identity_object) + (
        "simplified",
        round(float(target_reduction), 12),
    )
    accelerator = _persistent_accelerator
    worker_running = accelerator is not None and accelerator.is_running
    cache_hit = (
        worker_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    if cache_hit:
        pipeline_start = time.perf_counter()
        worker_mesh = accelerator.build_envelope(**envelope_options)
        return (
            accelerator,
            worker_mesh,
            True,
            0.0,
            0.0,
            time.perf_counter() - pipeline_start,
        )

    extraction_start = time.perf_counter()
    target_vertices, target_triangles = _target_surface_arrays(target_object)
    extraction_elapsed = time.perf_counter() - extraction_start
    if not worker_running:
        accelerator = acquire_geometry_worker()
    # The fused worker request replaces its retained BVH before completing.
    # Keep Blender's cache invalid until the complete pipeline succeeds.
    _cached_target_dirty = True
    fused_start = time.perf_counter()
    fused = accelerator.build_simplified_envelope(
        target_vertices,
        target_triangles,
        target_reduction=float(target_reduction),
        **envelope_options,
    )
    fused_elapsed = time.perf_counter() - fused_start
    _cached_target_signature = signature
    _cached_target_object_pointer = _blender_id_pointer(identity_object)
    _cached_target_data_pointer = _blender_id_pointer(identity_object.data)
    _cached_target_dirty = False
    logger.info(
        "Fused simplified target cache stored: pid=%d source_vertices=%d "
        "source_triangles=%d simplified_vertices=%d simplified_triangles=%d "
        "target_reduction=%.2f%% simplify=%.3fs bvh=%.3fs pipeline=%.3fs",
        accelerator._process.pid,
        fused.input_vertex_count,
        fused.input_triangle_count,
        fused.target_vertex_count,
        fused.target_triangle_count,
        float(target_reduction) * 100.0,
        fused.simplification_seconds,
        fused.bvh_seconds,
        fused.pipeline_seconds,
    )
    return (
        accelerator,
        fused.mesh,
        False,
        extraction_elapsed,
        fused.simplification_seconds + fused.bvh_seconds,
        fused_elapsed,
    )


def fit_pin_circle_with_worker(
    target,
    loop_source,
    *,
    offset: float,
    pass_count: int = 3,
) -> np.ndarray:
    """Fit a closed pin-placement loop using the retained target worker."""

    total_start = time.perf_counter()
    target_object = target.object if isinstance(target, Object) else target
    if hasattr(loop_source, "data"):
        points = _transform_points(
            _mesh_vertices(loop_source.data), loop_source.matrix_world
        )
        edges = _mesh_edges(loop_source.data)
    else:
        points = np.ascontiguousarray(
            [tuple(point) for point in loop_source],
            dtype=np.float32,
        )
        edges = None
    (
        accelerator,
        cache_hit,
        target_extract_elapsed,
        worker_build_elapsed,
    ) = _acquire_target_accelerator(target_object)
    phase_start = time.perf_counter()
    fitted = accelerator.fit_pin_circle(
        points,
        edges=edges,
        offset=float(offset),
        pass_count=int(pass_count),
    )
    fit_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Worker pin-circle fit complete: target=%s points=%d passes=%d "
        "offset=%.6f target_cache_hit=%s target_extract=%.3fs "
        "worker_build=%.3fs fit_roundtrip=%.3fs total=%.3fs",
        target_object.name,
        len(points),
        int(pass_count),
        float(offset),
        cache_hit,
        target_extract_elapsed,
        worker_build_elapsed,
        fit_elapsed,
        time.perf_counter() - total_start,
    )
    return fitted


def begin_fit_pin_circle_with_worker(
    target,
    loop_source,
    *,
    offset: float,
    pass_count: int = 3,
):
    global _cached_target_dirty

    target_object = target.object if isinstance(target, Object) else target
    points = _transform_points(
        _mesh_vertices(loop_source.data),
        loop_source.matrix_world,
    )
    edges = _mesh_edges(loop_source.data)
    signature = _target_cache_signature(target_object)
    worker = acquire_geometry_worker()
    cache_hit = bool(
        worker.is_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    target_vertices = target_triangles = None
    if not cache_hit:
        target_vertices, target_triangles = _target_surface_arrays(target_object)
        _cached_target_dirty = True

    def run():
        if not cache_hit:
            worker.build_target(target_vertices, target_triangles)
        return worker.fit_pin_circle(
            points,
            edges=edges,
            offset=float(offset),
            pass_count=int(pass_count),
        )

    def finish(result):
        global _cached_target_signature
        global _cached_target_object_pointer
        global _cached_target_data_pointer
        global _cached_target_dirty

        _cached_target_signature = signature
        _cached_target_object_pointer = _blender_id_pointer(target_object)
        _cached_target_data_pointer = _blender_id_pointer(target_object.data)
        _cached_target_dirty = False
        return result

    return submit_worker_task(run, on_complete=finish)


def prepare_watermark_image_with_worker(
    pixels,
    width: int,
    height: int,
    *,
    max_dimension: int,
):
    """Downsample a watermark image and choose its initial trace color."""

    _finish_pending_watermark_cleanup()
    return acquire_geometry_worker().prepare_watermark_image(
        pixels,
        width,
        height,
        max_dimension=max_dimension,
    )


def begin_prepare_watermark_image_with_worker(
    pixels,
    width: int,
    height: int,
    *,
    max_dimension: int,
):
    _finish_pending_watermark_cleanup()
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.prepare_watermark_image,
        pixels,
        width,
        height,
        max_dimension=max_dimension,
    )


def begin_trace_watermark_image_with_worker(
    pixels,
    width: int,
    height: int,
    *,
    target_color,
    color_tolerance: float,
    alpha_threshold: float,
    invert: bool,
    output_width: float,
):
    _finish_pending_watermark_cleanup()
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.trace_watermark_image,
        pixels,
        width,
        height,
        target_color=tuple(target_color),
        color_tolerance=color_tolerance,
        alpha_threshold=alpha_threshold,
        invert=invert,
        output_width=output_width,
    )


def begin_clear_watermark_worker_state():
    """Queue release of watermark-only retained data without blocking Blender."""

    global _pending_watermark_cleanup

    if _pending_watermark_cleanup is not None:
        return _pending_watermark_cleanup
    worker = acquire_geometry_worker()
    _pending_watermark_cleanup = submit_worker_task(worker.clear_watermark_state)
    return _pending_watermark_cleanup


def _finish_pending_watermark_cleanup() -> None:
    """Order a new watermark session after any asynchronous prior cleanup."""

    global _pending_watermark_cleanup

    task = _pending_watermark_cleanup
    _pending_watermark_cleanup = None
    if task is None:
        return
    try:
        task.finish()
    except Exception:
        logger.debug(
            "Could not finish prior watermark worker-state cleanup",
            exc_info=True,
        )


def prepare_watermark_mesh_with_worker(
    logo_object,
    *,
    max_vertices: int,
    resolution_scale: float,
):
    """Densify a logo in the worker and return its projection state."""

    _finish_pending_watermark_cleanup()
    vertices = _mesh_vertices(logo_object.data)
    triangles = _mesh_triangles(logo_object.data)
    prepared = acquire_geometry_worker().prepare_watermark_mesh(
        vertices,
        triangles,
        max_vertices=max_vertices,
        resolution_scale=resolution_scale,
    )
    _replace_mesh_geometry(
        logo_object,
        prepared.vertices,
        prepared.triangles,
        np.empty((0, 4), dtype=np.int32),
    )
    logo_object[_WORKER_WATERMARK_REVISION_KEY] = prepared.cache_revision
    return {
        "coordinates": prepared.vertices.copy(),
        "planar_points": prepared.planar_points,
        "vertex_point_indices": prepared.vertex_point_indices,
        "depth_fractions": prepared.depth_fractions,
        "cache_revision": prepared.cache_revision,
    }


def begin_prepare_watermark_mesh_with_worker(
    logo_object,
    *,
    max_vertices: int,
    resolution_scale: float,
):
    """Prepare watermark projection geometry off-thread and apply it on main."""

    _finish_pending_watermark_cleanup()
    vertices = _mesh_vertices(logo_object.data)
    triangles = _mesh_triangles(logo_object.data)
    worker = acquire_geometry_worker()

    def finish(prepared):
        _replace_mesh_geometry(
            logo_object,
            prepared.vertices,
            prepared.triangles,
            np.empty((0, 4), dtype=np.int32),
        )
        logo_object[_WORKER_WATERMARK_REVISION_KEY] = prepared.cache_revision
        return {
            "coordinates": prepared.vertices.copy(),
            "planar_points": prepared.planar_points,
            "vertex_point_indices": prepared.vertex_point_indices,
            "depth_fractions": prepared.depth_fractions,
            "cache_revision": prepared.cache_revision,
        }

    return submit_worker_task(
        worker.prepare_watermark_mesh,
        vertices,
        triangles,
        max_vertices=max_vertices,
        resolution_scale=resolution_scale,
        on_complete=finish,
    )


def begin_conform_watermark_with_worker(
    target_object,
    conform_state,
    *,
    location,
    center_normal,
    rotation: float,
    placement_scale: float,
    extrusion_depth: float,
    resolution_scale: float,
    voxel_size_override: float,
    operation: str,
):
    """Project a watermark off-thread from immutable placement snapshots."""

    global _cached_target_dirty

    _finish_pending_watermark_cleanup()
    signature = _target_cache_signature(target_object)
    worker = acquire_geometry_worker()
    cache_hit = bool(
        worker.is_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    target_vertices = target_triangles = None
    if not cache_hit:
        target_vertices, target_triangles = _target_surface_arrays(target_object)
        _cached_target_dirty = True

    def run():
        if not cache_hit:
            worker.build_target(target_vertices, target_triangles)
        return worker.conform_watermark(
            conform_state["planar_points"],
            conform_state["vertex_point_indices"],
            conform_state["depth_fractions"],
            location=tuple(location),
            center_normal=tuple(center_normal),
            rotation=rotation,
            placement_scale=placement_scale,
            extrusion_depth=extrusion_depth,
            resolution_scale=resolution_scale,
            voxel_size_override=voxel_size_override,
            operation=operation,
            cache_revision=conform_state.get("cache_revision"),
        )

    def finish(result):
        global _cached_target_signature
        global _cached_target_object_pointer
        global _cached_target_data_pointer
        global _cached_target_dirty

        _cached_target_signature = signature
        _cached_target_object_pointer = _blender_id_pointer(target_object)
        _cached_target_data_pointer = _blender_id_pointer(target_object.data)
        _cached_target_dirty = False
        return result

    return submit_worker_task(run, on_complete=finish)


def remesh_watermark_with_worker(
    logo_object,
    *,
    nominal_depth: float,
    resolution_scale: float,
    voxel_size_override: float,
) -> float:
    """Replace a conformed logo mesh with the worker's voxel surface."""

    _finish_pending_watermark_cleanup()
    worker = acquire_geometry_worker()
    cache_revision = logo_object.get(_WORKER_WATERMARK_REVISION_KEY)
    if worker.can_reuse_conformed_watermark(cache_revision):
        vertices = None
        triangles = None
    else:
        vertices = _mesh_vertices(logo_object.data)
        triangles = _mesh_triangles(logo_object.data)
    result, voxel_size = worker.remesh_watermark(
        vertices,
        triangles,
        nominal_depth=nominal_depth,
        resolution_scale=resolution_scale,
        voxel_size_override=voxel_size_override,
        cache_revision=cache_revision,
    )
    _replace_mesh_geometry(
        logo_object,
        result.vertices,
        result.triangles,
        result.quads,
    )
    return voxel_size


def begin_remesh_watermark_with_worker(
    logo_object,
    *,
    nominal_depth: float,
    resolution_scale: float,
    voxel_size_override: float,
):
    """Remesh a conformed watermark off-thread and replace it on main."""

    _finish_pending_watermark_cleanup()
    worker = acquire_geometry_worker()
    cache_revision = logo_object.get(_WORKER_WATERMARK_REVISION_KEY)
    vertices = _mesh_vertices(logo_object.data)
    triangles = _mesh_triangles(logo_object.data)

    def finish(payload):
        result, voxel_size = payload
        _replace_mesh_geometry(
            logo_object,
            result.vertices,
            result.triangles,
            result.quads,
        )
        return voxel_size

    return submit_worker_task(
        worker.remesh_watermark,
        vertices,
        triangles,
        nominal_depth=nominal_depth,
        resolution_scale=resolution_scale,
        voxel_size_override=voxel_size_override,
        cache_revision=cache_revision,
        on_complete=finish,
    )


def _transform_points(points: np.ndarray, matrix) -> np.ndarray:
    matrix_array = np.array(matrix, dtype=np.float32, copy=True)
    transformed = np.empty_like(points, dtype=np.float32)
    transformed[:, 0] = (
        points[:, 0] * matrix_array[0, 0]
        + points[:, 1] * matrix_array[0, 1]
        + points[:, 2] * matrix_array[0, 2]
        + matrix_array[0, 3]
    )
    transformed[:, 1] = (
        points[:, 0] * matrix_array[1, 0]
        + points[:, 1] * matrix_array[1, 1]
        + points[:, 2] * matrix_array[1, 2]
        + matrix_array[1, 3]
    )
    transformed[:, 2] = (
        points[:, 0] * matrix_array[2, 0]
        + points[:, 1] * matrix_array[2, 1]
        + points[:, 2] * matrix_array[2, 2]
        + matrix_array[2, 3]
    )
    return transformed


def _mesh_vertices(mesh) -> np.ndarray:
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", vertices.ravel())
    return vertices


def _mesh_edges(mesh) -> np.ndarray:
    edges = np.empty((len(mesh.edges), 2), dtype=np.int32)
    mesh.edges.foreach_get("vertices", edges.ravel())
    return edges


def _mesh_triangles(mesh) -> np.ndarray:
    mesh.calc_loop_triangles()
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    return triangles


def _mesh_polygon_arrays(mesh):
    """Return packed polygons plus local centers and normals."""

    polygon_count = len(mesh.polygons)
    loop_count = len(mesh.loops)
    loop_starts = np.empty(polygon_count, dtype=np.int32)
    loop_totals = np.empty(polygon_count, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", loop_starts)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    loop_vertices = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    offsets = np.empty(polygon_count + 1, dtype=np.int32)
    offsets[0] = 0
    if polygon_count:
        np.cumsum(loop_totals, out=offsets[1:])
    indices = np.empty(int(offsets[-1]), dtype=np.int32)
    output_offset = 0
    for loop_start, loop_total in zip(loop_starts, loop_totals):
        next_offset = output_offset + int(loop_total)
        indices[output_offset:next_offset] = loop_vertices[
            int(loop_start) : int(loop_start + loop_total)
        ]
        output_offset = next_offset
    centers = np.empty((polygon_count, 3), dtype=np.float32)
    normals = np.empty((polygon_count, 3), dtype=np.float32)
    if polygon_count:
        mesh.polygons.foreach_get("center", centers.ravel())
        mesh.polygons.foreach_get("normal", normals.ravel())
    return offsets, indices, centers, normals


def extract_world_polygon_arrays(source_object):
    """Extract packed polygons and their records in world space."""

    mesh = source_object.data
    mesh.update()
    vertices = _transform_points(_mesh_vertices(mesh), source_object.matrix_world)
    offsets, indices, centers, normals = _mesh_polygon_arrays(mesh)
    centers = _transform_points(centers, source_object.matrix_world)
    normal_matrix = np.asarray(
        source_object.matrix_world.to_3x3().inverted().transposed(),
        dtype=np.float32,
    )
    normals = np.ascontiguousarray(normals @ normal_matrix.T, dtype=np.float32)
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > np.finfo(np.float32).eps
    normals[valid] /= lengths[valid, None]
    normals[~valid] = 0.0
    return vertices, offsets, indices, centers, normals


def edit_object_vertices_with_worker(
    source_object,
    *,
    normal_offset: float = 0.0,
    smooth_factor: float = 0.0,
    smooth_repeat: int = 0,
) -> dict:
    """Run topology-preserving edits externally and write only coordinates."""

    started = time.perf_counter()
    mesh = source_object.data
    vertices = _mesh_vertices(mesh)
    edges = _mesh_edges(mesh)
    triangles = (
        _mesh_triangles(mesh)
        if float(normal_offset) != 0.0
        else None
    )
    result = acquire_geometry_worker().edit_mesh_vertices(
        vertices,
        edges,
        triangles,
        normal_offset=normal_offset,
        smooth_factor=smooth_factor,
        smooth_repeat=smooth_repeat,
    )
    if len(result) != len(mesh.vertices):
        raise RuntimeError("worker topology-preserving edit changed vertex count")
    mesh.vertices.foreach_set("co", result.ravel())
    mesh.update()
    elapsed = time.perf_counter() - started
    logger.info(
        "Worker Blender mesh edit apply: object=%s vertices=%d offset=%.6f "
        "smooth_repeat=%d total=%.3fs",
        source_object.name,
        len(result),
        float(normal_offset),
        int(smooth_repeat),
        elapsed,
    )
    return {"vertex_count": len(result), "total_seconds": elapsed}


def begin_edit_object_vertices_with_worker(
    source_object,
    *,
    normal_offset: float = 0.0,
    smooth_factor: float = 0.0,
    smooth_repeat: int = 0,
):
    """Run a topology-preserving edit off-thread and apply it on main."""

    started = time.perf_counter()
    mesh = source_object.data
    vertices = _mesh_vertices(mesh)
    edges = _mesh_edges(mesh)
    triangles = _mesh_triangles(mesh) if float(normal_offset) != 0.0 else None
    expected_vertex_count = len(mesh.vertices)
    worker = acquire_geometry_worker()

    def finish(result):
        if len(result) != expected_vertex_count:
            raise RuntimeError(
                "worker topology-preserving edit changed vertex count"
            )
        mesh.vertices.foreach_set("co", result.ravel())
        mesh.update()
        elapsed = time.perf_counter() - started
        logger.info(
            "Async worker Blender mesh edit apply: object=%s vertices=%d "
            "offset=%.6f smooth_repeat=%d total=%.3fs",
            source_object.name,
            len(result),
            float(normal_offset),
            int(smooth_repeat),
            elapsed,
        )
        return {"vertex_count": len(result), "total_seconds": elapsed}

    return submit_worker_task(
        worker.edit_mesh_vertices,
        vertices,
        edges,
        triangles,
        normal_offset=normal_offset,
        smooth_factor=smooth_factor,
        smooth_repeat=smooth_repeat,
        on_complete=finish,
    )


def begin_clear_mesh_faces_to_point_with_worker(
    source_object,
    *,
    target_point=None,
    target_points=None,
    voxel_size: float,
    away_from_target: bool = False,
    select_all_faces: bool = False,
    extrusion_distance: float | None = None,
    extrusion_bounds=None,
    extrusion_margin: float = 0.0,
    selection_bounds=None,
    include_source: bool = True,
):
    """Clear one mesh toward one or the nearest world-space target axis."""

    started = time.perf_counter()
    source_matrix = source_object.matrix_world.copy()
    inverse_matrix = source_matrix.inverted()
    local_vertices = _mesh_vertices(source_object.data)
    world_vertices = _transform_points(local_vertices, source_matrix)
    triangles = _mesh_triangles(source_object.data)
    worker = acquire_geometry_worker()
    if target_points is None:
        if target_point is None:
            raise ValueError("target_point or target_points is required")
        logged_targets = (target_point,)
    else:
        if target_point is not None:
            raise ValueError(
                "target_point and target_points are mutually exclusive"
            )
        logged_targets = tuple(target_points)
        if not logged_targets:
            raise ValueError("target_points must contain at least one point")

    def finish(result):
        local_result_vertices = np.ascontiguousarray(
            _transform_points(result.mesh.vertices, inverse_matrix),
            dtype=np.float32,
        )
        _replace_mesh_geometry(
            source_object,
            local_result_vertices,
            result.mesh.triangles,
            result.mesh.quads,
        )
        logger.info(
            "Applied worker point clearance to Blender object: object=%s "
            "target_count=%d target_axis_xy=%s voxel_size=%.6f "
            "away=%s all_faces=%s extrusion_distance=%s extrusion_margin=%.6f "
            "selection_bounds=%s include_source=%s selected_faces=%d components=%d "
            "total=%.3fs",
            source_object.name,
            len(logged_targets),
            (
                f"({float(logged_targets[0][0]):.6f}, "
                f"{float(logged_targets[0][1]):.6f})"
                if len(logged_targets) == 1
                else "nearest"
            ),
            float(voxel_size),
            bool(away_from_target),
            bool(select_all_faces),
            (
                "axis"
                if extrusion_distance is None and extrusion_bounds is None
                else "bounds"
                if extrusion_bounds is not None
                else f"{float(extrusion_distance):.6f}"
            ),
            float(extrusion_margin),
            "none" if selection_bounds is None else selection_bounds,
            bool(include_source),
            result.selected_face_count,
            result.component_count,
            time.perf_counter() - started,
        )
        return result

    return submit_worker_task(
        worker.clear_mesh_faces_to_point,
        world_vertices,
        triangles,
        target_point,
        target_points=(None if target_points is None else logged_targets),
        voxel_size=voxel_size,
        away_from_target=away_from_target,
        select_all_faces=select_all_faces,
        extrusion_distance=extrusion_distance,
        extrusion_bounds=extrusion_bounds,
        extrusion_margin=extrusion_margin,
        selection_bounds=selection_bounds,
        include_source=include_source,
        on_complete=finish,
    )


def match_mesh_parts_to_world_points_with_worker(
    parts: list[Object],
    world_points,
) -> tuple[np.ndarray, np.ndarray]:
    """Match one distinct mesh part to each world-space point in the worker."""

    vertex_chunks = []
    part_offsets = [0]
    for part in parts:
        raw = part.object if isinstance(part, Object) else part
        local_vertices = _mesh_vertices(raw.data)
        if not len(local_vertices):
            raise ValueError(f"Mesh part {raw.name} has no vertices")
        vertex_chunks.append(_transform_points(local_vertices, raw.matrix_world))
        part_offsets.append(part_offsets[-1] + len(local_vertices))
    if not vertex_chunks:
        raise ValueError("At least one mesh part is required")
    vertices = np.ascontiguousarray(
        np.concatenate(vertex_chunks, axis=0),
        dtype=np.float32,
    )
    return acquire_geometry_worker().match_points_to_mesh_parts(
        vertices,
        np.asarray(part_offsets, dtype=np.int32),
        world_points,
    )


def remesh_object_with_worker(source_object, *, voxel_size: float) -> dict:
    """Replace one Blender mesh with a worker OpenVDB voxel remesh."""

    total_start = time.perf_counter()
    mesh = source_object.data
    extraction_start = time.perf_counter()
    vertices = _mesh_vertices(mesh)
    triangles = _mesh_triangles(mesh)
    extraction_elapsed = time.perf_counter() - extraction_start
    worker_start = time.perf_counter()
    result = acquire_geometry_worker().voxel_remesh(
        vertices,
        triangles,
        voxel_size=float(voxel_size),
    )
    worker_elapsed = time.perf_counter() - worker_start
    write_start = time.perf_counter()
    _replace_mesh_geometry(
        source_object,
        result.vertices,
        result.triangles,
        result.quads,
    )
    write_elapsed = time.perf_counter() - write_start
    total_elapsed = time.perf_counter() - total_start
    logger.info(
        "Worker Blender voxel-remesh apply: object=%s input_vertices=%d "
        "input_triangles=%d output_vertices=%d output_triangles=%d "
        "output_quads=%d extract=%.3fs worker_roundtrip=%.3fs "
        "mesh_write=%.3fs total=%.3fs",
        source_object.name,
        len(vertices),
        len(triangles),
        len(result.vertices),
        len(result.triangles),
        len(result.quads),
        extraction_elapsed,
        worker_elapsed,
        write_elapsed,
        total_elapsed,
    )
    return {
        "input_vertices": len(vertices),
        "input_triangles": len(triangles),
        "output_vertices": len(result.vertices),
        "output_faces": len(result.triangles) + len(result.quads),
        "extract_seconds": extraction_elapsed,
        "worker_seconds": worker_elapsed,
        "write_seconds": write_elapsed,
        "total_seconds": total_elapsed,
    }


def inspect_object_mesh_connectivity_with_worker(source_object):
    """Inspect only loose vertices and edge-connected mesh islands."""

    total_start = time.perf_counter()
    phase_start = total_start
    edges = _mesh_edges(source_object.data)
    extraction_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    worker = acquire_geometry_worker()
    acquire_worker_elapsed = time.perf_counter() - phase_start

    result = worker.inspect_mesh_connectivity(
        len(source_object.data.vertices),
        edges,
    )
    logger.info(
        "Worker lightweight mesh connectivity: object=%s vertices=%d "
        "edges=%d loose_vertices=%d multiple_islands=%s "
        "extract_edges=%.3fs acquire_worker=%.3fs worker=%.3fs "
        "roundtrip=%.3fs total=%.3fs input_bytes=%d",
        source_object.name,
        len(source_object.data.vertices),
        len(edges),
        len(result.loose_vertices),
        result.multiple_components,
        extraction_elapsed,
        acquire_worker_elapsed,
        result.worker_seconds,
        result.roundtrip_seconds,
        time.perf_counter() - total_start,
        edges.nbytes,
    )
    return result


def _lightweight_manifold_edge_counts(
    loop_edge_indices: np.ndarray,
    edge_count: int,
    face_count: int,
) -> tuple[bool, int, int]:
    """Count face users per mesh edge without geometry/component analysis."""

    if face_count <= 0:
        return False, 0, 0
    if len(loop_edge_indices) == 0 or edge_count <= 0:
        return False, 0, 0
    if np.any(loop_edge_indices < 0):
        return False, int(np.count_nonzero(loop_edge_indices < 0)), 0

    edge_face_users = np.bincount(
        loop_edge_indices,
        minlength=int(edge_count),
    )
    # Preserve the former worker analysis semantics: loose edges that are not
    # referenced by any face do not make an otherwise closed surface fail.
    face_edges = edge_face_users > 0
    boundary_edges = int(np.count_nonzero(edge_face_users == 1))
    non_manifold_edges = int(
        np.count_nonzero(face_edges & (edge_face_users != 2))
    )
    return non_manifold_edges == 0, non_manifold_edges, boundary_edges


def mesh_manifold_edge_counts_lightweight(mesh) -> tuple[bool, int, int]:
    """Return manifold/bad/boundary counts from Blender loop topology only.

    Unlike ``analyze_object_mesh_with_worker``, this does not copy vertices,
    calculate polygon geometry, find components, bounds, areas, or volumes, or
    make a worker-process round trip.
    """

    loop_edge_indices = np.empty(len(mesh.loops), dtype=np.int32)
    if len(loop_edge_indices):
        mesh.loops.foreach_get("edge_index", loop_edge_indices)
    return _lightweight_manifold_edge_counts(
        loop_edge_indices,
        len(mesh.edges),
        len(mesh.polygons),
    )


def is_object_mesh_manifold_lightweight(source_object) -> bool:
    """Return only the closed two-face-per-edge status of an object mesh."""

    start_time = time.perf_counter()
    is_manifold, non_manifold_edges, boundary_edges = (
        mesh_manifold_edge_counts_lightweight(source_object.data)
    )
    logger.debug(
        "Lightweight mesh topology check: object=%s manifold=%s "
        "non_manifold_edges=%d boundary_edges=%d elapsed=%.3fs",
        source_object.name,
        is_manifold,
        non_manifold_edges,
        boundary_edges,
        time.perf_counter() - start_time,
    )
    return is_manifold


def begin_is_object_mesh_manifold_lightweight(source_object):
    """Snapshot loop topology and count edge users off the main thread."""

    mesh = source_object.data
    loop_edge_indices = np.empty(len(mesh.loops), dtype=np.int32)
    if len(loop_edge_indices):
        mesh.loops.foreach_get("edge_index", loop_edge_indices)
    return submit_worker_task(
        _lightweight_manifold_edge_counts,
        loop_edge_indices,
        len(mesh.edges),
        len(mesh.polygons),
        on_complete=lambda counts: bool(counts[0]),
    )


def analyze_object_mesh_with_worker(source_object):
    """Run generic topology/component analysis on local mesh coordinates."""

    total_start = time.perf_counter()
    phase_start = total_start
    vertices = _mesh_vertices(source_object.data)
    vertices_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    offsets, indices, _centers, _normals = _mesh_polygon_arrays(
        source_object.data
    )
    polygons_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    edges = _mesh_edges(source_object.data)
    edges_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    worker = acquire_geometry_worker()
    acquire_worker_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    result = worker.analyze_mesh(
        vertices,
        offsets,
        indices,
        edges,
    )
    worker_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Worker mesh topology analysis: object=%s vertices=%d edges=%d "
        "polygons=%d components=%d loose_vertices=%d extract_vertices=%.3fs "
        "extract_polygons=%.3fs extract_edges=%.3fs acquire_worker=%.3fs "
        "worker_roundtrip=%.3fs total=%.3fs",
        source_object.name,
        len(vertices),
        len(edges),
        len(offsets) - 1,
        len(result.components),
        len(result.loose_vertices),
        vertices_elapsed,
        polygons_elapsed,
        edges_elapsed,
        acquire_worker_elapsed,
        worker_elapsed,
        time.perf_counter() - total_start,
    )
    return result


def begin_analyze_object_mesh_with_worker(source_object):
    """Run mesh topology analysis off-thread from main-thread snapshots."""

    vertices = _mesh_vertices(source_object.data)
    offsets, indices, _centers, _normals = _mesh_polygon_arrays(
        source_object.data
    )
    edges = _mesh_edges(source_object.data)
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.analyze_mesh,
        vertices,
        offsets,
        indices,
        edges,
    )


def plan_limit_face_with_worker(
    source_object,
    *,
    axis: int,
    max_co: bool,
    flat: bool = False,
    average_ties: bool = False,
    world_space: bool = False,
):
    _offsets, _indices, centers, normals = _mesh_polygon_arrays(
        source_object.data
    )
    if world_space:
        centers = _transform_points(centers, source_object.matrix_world)
        normal_matrix = np.asarray(
            source_object.matrix_world.to_3x3().inverted().transposed(),
            dtype=np.float32,
        )
        normals = np.ascontiguousarray(normals @ normal_matrix.T, dtype=np.float32)
        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > np.finfo(np.float32).eps
        normals[valid] /= lengths[valid, None]
    return acquire_geometry_worker().plan_limit_face(
        centers,
        normals,
        axis=axis,
        max_co=max_co,
        flat=flat,
        average_ties=average_ties,
    )


def begin_plan_limit_face_with_worker(
    source_object,
    *,
    axis: int,
    max_co: bool,
    flat: bool = False,
    average_ties: bool = False,
    world_space: bool = False,
):
    _offsets, _indices, centers, normals = _mesh_polygon_arrays(
        source_object.data
    )
    if world_space:
        centers = _transform_points(centers, source_object.matrix_world)
        normal_matrix = np.asarray(
            source_object.matrix_world.to_3x3().inverted().transposed(),
            dtype=np.float32,
        )
        normals = np.ascontiguousarray(normals @ normal_matrix.T, dtype=np.float32)
        lengths = np.linalg.norm(normals, axis=1)
        valid = lengths > np.finfo(np.float32).eps
        normals[valid] /= lengths[valid, None]
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.plan_limit_face,
        centers,
        normals,
        axis=axis,
        max_co=max_co,
        flat=flat,
        average_ties=average_ties,
    )


def select_limit_flat_faces_with_worker(
    source_object,
    *,
    max_co: bool,
    tolerance: float,
) -> np.ndarray:
    _offsets, _indices, centers, normals = _mesh_polygon_arrays(
        source_object.data
    )
    vertices = _mesh_vertices(source_object.data)
    z_range = float(np.ptp(vertices[:, 2])) if len(vertices) else 0.0
    return acquire_geometry_worker().select_limit_flat_faces(
        centers,
        normals,
        max_co=max_co,
        tolerance=tolerance,
        z_range=z_range,
    )


def begin_analyze_top_surface_flatness_with_worker(
    source_object,
    *,
    top_band_depth: float,
    flat_normal_z: float,
    min_flat_projected_area_ratio: float,
):
    """Analyze a world-space top cap without blocking Blender's UI thread."""

    vertices, offsets, indices, centers, normals = (
        extract_world_polygon_arrays(source_object)
    )
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.analyze_top_surface_flatness,
        vertices,
        offsets,
        indices,
        centers,
        normals,
        top_band_depth=top_band_depth,
        flat_normal_z=flat_normal_z,
        min_flat_projected_area_ratio=min_flat_projected_area_ratio,
    )


def find_master_air_traps_with_worker(
    source_object,
    *,
    base_z: float,
    min_projected_area: float,
    contact_tolerance: float,
    minima_merge_height: float = 0.0,
):
    vertices, offsets, indices, centers, normals = (
        extract_world_polygon_arrays(source_object)
    )
    return acquire_geometry_worker().find_master_air_traps(
        vertices,
        offsets,
        indices,
        normals,
        centers,
        _mesh_edges(source_object.data),
        base_z=base_z,
        min_projected_area=min_projected_area,
        contact_tolerance=contact_tolerance,
        minima_merge_height=minima_merge_height,
    )


def begin_find_master_air_traps_with_worker(
    source_object,
    *,
    base_z: float,
    min_projected_area: float,
    contact_tolerance: float,
    minima_merge_height: float = 0.0,
):
    vertices, offsets, indices, centers, normals = (
        extract_world_polygon_arrays(source_object)
    )
    edges = _mesh_edges(source_object.data)
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.find_master_air_traps,
        vertices,
        offsets,
        indices,
        normals,
        centers,
        edges,
        base_z=base_z,
        min_projected_area=min_projected_area,
        contact_tolerance=contact_tolerance,
        minima_merge_height=minima_merge_height,
    )


def build_extraction_prisms_with_worker(
    source_object,
    *,
    selection_mode: str,
    face_normal,
    split_plane_normal,
    split_plane_point,
    side: int,
    normal_tolerance: float,
    distance_tolerance: float,
    extra_extrusion_distance: float,
    extrusion_target_point,
):
    vertices, offsets, indices, centers, normals = extract_world_polygon_arrays(
        source_object
    )
    return acquire_geometry_worker().build_extraction_prisms(
        vertices,
        offsets,
        indices,
        centers,
        normals,
        selection_mode=selection_mode,
        face_normal=face_normal,
        split_plane_normal=split_plane_normal,
        split_plane_point=split_plane_point,
        side=side,
        normal_tolerance=normal_tolerance,
        distance_tolerance=distance_tolerance,
        extra_extrusion_distance=extra_extrusion_distance,
        extrusion_target_point=extrusion_target_point,
    )


def order_closed_loop_with_worker(
    source_object,
    *,
    min_z: float | None = None,
) -> np.ndarray:
    vertices = _transform_points(
        _mesh_vertices(source_object.data), source_object.matrix_world
    )
    edges = _mesh_edges(source_object.data)
    return acquire_geometry_worker().order_closed_loop(
        vertices,
        edges,
        min_z=min_z,
    )


def resample_closed_loop_with_worker(
    source_object,
    *,
    spacing: float | None = None,
    point_count: int | None = None,
    min_z: float | None = None,
) -> np.ndarray:
    vertices = _transform_points(
        _mesh_vertices(source_object.data), source_object.matrix_world
    )
    edges = _mesh_edges(source_object.data)
    return acquire_geometry_worker().resample_closed_loop(
        vertices,
        edges,
        spacing=spacing,
        point_count=point_count,
        min_z=min_z,
    )


def begin_resample_closed_loop_with_worker(
    source_object,
    *,
    spacing: float | None = None,
    point_count: int | None = None,
    min_z: float | None = None,
):
    vertices = _transform_points(
        _mesh_vertices(source_object.data), source_object.matrix_world
    )
    edges = _mesh_edges(source_object.data)
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.resample_closed_loop,
        vertices,
        edges,
        spacing=spacing,
        point_count=point_count,
        min_z=min_z,
    )


def extend_funnel_to_plane_with_worker(
    source_object,
    *,
    plane_point,
    plane_normal,
    tolerance: float,
):
    vertices, offsets, indices, centers, normals = extract_world_polygon_arrays(
        source_object
    )
    result = acquire_geometry_worker().extend_funnel_to_plane(
        vertices,
        offsets,
        indices,
        centers,
        normals,
        object_center=source_object.matrix_world.translation,
        plane_point=plane_point,
        plane_normal=plane_normal,
        tolerance=tolerance,
    )
    inverse_world = np.asarray(source_object.matrix_world.inverted(), dtype=np.float32)
    local_vertices = _transform_points(result.vertices, inverse_world)
    source_object.data.vertices.foreach_set("co", local_vertices.ravel())
    source_object.data.update()
    return result


def plan_auto_orientation_with_worker(
    source_object,
    *,
    target_reduction: float | None,
    max_tilt_degrees: float,
    min_footprint_ratio: float,
    place_base_on_top: bool = False,
):
    """Extract once and run optional simplification plus Auto Level planning."""

    mesh = source_object.data
    vertices = _mesh_vertices(mesh)
    triangles = _mesh_triangles(mesh)
    if not len(triangles):
        return None
    analysis = acquire_geometry_worker().analyze_model_orientation(
        vertices,
        triangles,
        np.asarray(source_object.matrix_world, dtype=np.float32),
        target_reduction=target_reduction,
        max_tilt_degrees=max_tilt_degrees,
        min_footprint_ratio=min_footprint_ratio,
        place_base_on_top=place_base_on_top,
    )
    _cache_imported_volume(source_object, analysis.source_volume)
    return analysis.plan


def _cache_imported_volume(source_object, local_volume: float):
    """Cache import volume while the already-extracted worker mesh is available."""

    world_scale = abs(source_object.matrix_world.to_3x3().determinant())
    volume_ml = max(float(local_volume) * float(world_scale) / 1000.0, 0.0)
    source_object[IMPORTED_VOLUME_ML_KEY] = volume_ml
    return volume_ml


def begin_plan_auto_orientation_with_worker(
    source_object,
    *,
    target_reduction: float | None,
    max_tilt_degrees: float,
    min_footprint_ratio: float,
    place_base_on_top: bool = False,
):
    """Start Auto Level planning after extracting Blender data on main."""

    mesh = source_object.data
    vertices = _mesh_vertices(mesh)
    triangles = _mesh_triangles(mesh)
    if not len(triangles):
        return None
    worker = acquire_geometry_worker()

    def finish(analysis):
        _cache_imported_volume(source_object, analysis.source_volume)
        return analysis.plan

    return submit_worker_task(
        worker.analyze_model_orientation,
        vertices,
        triangles,
        np.asarray(source_object.matrix_world, dtype=np.float32),
        target_reduction=target_reduction,
        max_tilt_degrees=max_tilt_degrees,
        min_footprint_ratio=min_footprint_ratio,
        place_base_on_top=place_base_on_top,
        on_complete=finish,
    )


def begin_plan_selected_face_orientation_with_worker(
    source_object,
    polygon_indices,
):
    """Start selected-face planning after main-thread mesh extraction."""

    selected_polygons = {int(index) for index in polygon_indices}
    if not selected_polygons:
        return None
    mesh = source_object.data
    vertices = _mesh_vertices(mesh)
    triangles = _mesh_triangles(mesh)
    if not len(triangles):
        return None
    selected_triangles = np.ascontiguousarray(
        [
            index
            for index, triangle in enumerate(mesh.loop_triangles)
            if int(triangle.polygon_index) in selected_polygons
        ],
        dtype=np.int32,
    )
    if not len(selected_triangles):
        return None
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.plan_model_orientation,
        vertices,
        triangles,
        np.asarray(source_object.matrix_world, dtype=np.float32),
        selected_triangle_indices=selected_triangles,
    )


def _replace_mesh_geometry(
    source_object,
    vertices: np.ndarray,
    triangles: np.ndarray,
    quads: np.ndarray,
    polygon_material_indices: np.ndarray | None = None,
    polygon_use_smooth: np.ndarray | None = None,
) -> None:
    old_mesh = source_object.data
    old_name = old_mesh.name
    new_mesh = bpy.data.meshes.new(f"{old_name}_worker_voxel")
    try:
        vertex_count = len(vertices)
        triangle_count = len(triangles)
        quad_count = len(quads)
        loop_count = triangle_count * 3 + quad_count * 4
        polygon_count = triangle_count + quad_count

        new_mesh.vertices.add(vertex_count)
        new_mesh.vertices.foreach_set("co", vertices.ravel())
        new_mesh.loops.add(loop_count)
        if loop_count:
            loop_vertices = np.concatenate(
                (triangles.ravel(), quads.ravel())
            ).astype(np.int32, copy=False)
            new_mesh.loops.foreach_set("vertex_index", loop_vertices)
        new_mesh.polygons.add(polygon_count)
        if polygon_count:
            loop_totals = np.concatenate(
                (
                    np.full(triangle_count, 3, dtype=np.int32),
                    np.full(quad_count, 4, dtype=np.int32),
                )
            )
            loop_starts = np.empty(polygon_count, dtype=np.int32)
            loop_starts[0] = 0
            if polygon_count > 1:
                np.cumsum(loop_totals[:-1], out=loop_starts[1:])
            new_mesh.polygons.foreach_set("loop_start", loop_starts)
            new_mesh.polygons.foreach_set("loop_total", loop_totals)
            if polygon_material_indices is not None:
                material_indices = np.ascontiguousarray(
                    polygon_material_indices, dtype=np.int32
                )
                if material_indices.shape != (polygon_count,):
                    raise ValueError(
                        "polygon material indices do not match the mesh"
                    )
                new_mesh.polygons.foreach_set(
                    "material_index", material_indices
                )
            if polygon_use_smooth is not None:
                smooth_flags = np.ascontiguousarray(
                    polygon_use_smooth, dtype=np.bool_
                )
                if smooth_flags.shape != (polygon_count,):
                    raise ValueError(
                        "polygon smooth flags do not match the mesh"
                    )
                new_mesh.polygons.foreach_set("use_smooth", smooth_flags)
        for material in old_mesh.materials:
            new_mesh.materials.append(material)
        new_mesh.update(calc_edges=True)
        source_object.data = new_mesh
    except Exception:
        bpy.data.meshes.remove(new_mesh)
        raise

    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    new_mesh.name = old_name


def plan_weight_text_extension_with_worker(
    wing_min_x: float,
    wing_min_z: float,
    wing_max_z: float,
    text_width: float,
    text_depth: float,
    center_y: float,
    padding: float,
    outward_span: float,
    outward_shift: float,
    cutter_oversize: float,
    *,
    min_z: float | None = None,
    max_z: float | None = None,
    attachment_min_x: float | None = None,
    text_min_x: float | None = None,
    attachment_overlap: float | None = None,
) -> dict:
    """Fetch the protected label-tab placement plan as scalar data."""

    return acquire_geometry_worker().weight_text_extension_plan(
        wing_min_x,
        wing_min_z,
        wing_max_z,
        text_width,
        text_depth,
        center_y,
        padding,
        outward_span,
        outward_shift,
        cutter_oversize,
        min_z=min_z,
        max_z=max_z,
        attachment_min_x=attachment_min_x,
        text_min_x=text_min_x,
        attachment_overlap=attachment_overlap,
    )


def locking_clamp_plan_with_worker(
    kind: str,
    primary_size: float,
    secondary_size: float,
    height: float,
    thickness: float,
    tolerance: float,
    closing_pressure: float,
    clip_count: int,
) -> dict:
    """Fetch the protected construction recipe without touching Blender data."""

    return acquire_geometry_worker().locking_clamp_plan(
        kind,
        primary_size,
        secondary_size,
        height,
        thickness,
        tolerance,
        closing_pressure,
        clip_count,
    )


def repeat_object_mesh_grid_with_worker(
    source_object,
    *,
    count: int,
    gap: float,
) -> None:
    """Replace one Blender mesh with worker-packed copies in a two-row grid."""

    count = int(count)
    if count <= 1:
        return
    old_mesh = source_object.data
    vertices = _mesh_vertices(old_mesh)
    face_offsets, face_indices, _centers, _normals = _mesh_polygon_arrays(
        old_mesh
    )
    source_face_count = len(old_mesh.polygons)
    source_use_smooth = np.empty(source_face_count, dtype=np.bool_)
    source_material_indices = np.empty(source_face_count, dtype=np.int32)
    if source_face_count:
        old_mesh.polygons.foreach_get("use_smooth", source_use_smooth)
        old_mesh.polygons.foreach_get(
            "material_index", source_material_indices
        )
    result = acquire_geometry_worker().repeat_polygon_mesh_grid(
        vertices,
        face_offsets,
        face_indices,
        count=count,
        gap=float(gap),
    )

    old_name = old_mesh.name
    new_mesh = bpy.data.meshes.new(f"{old_name}_worker_grid")
    try:
        new_mesh.vertices.add(len(result.vertices))
        if len(result.vertices):
            new_mesh.vertices.foreach_set("co", result.vertices.ravel())
        new_mesh.loops.add(len(result.face_indices))
        if len(result.face_indices):
            new_mesh.loops.foreach_set(
                "vertex_index", result.face_indices
            )
        face_count = len(result.face_offsets) - 1
        new_mesh.polygons.add(face_count)
        if face_count:
            if face_count != source_face_count * count:
                raise RuntimeError(
                    "Worker locking-clamp grid returned the wrong face count"
                )
            new_mesh.polygons.foreach_set(
                "loop_start", result.face_offsets[:-1]
            )
            new_mesh.polygons.foreach_set(
                "loop_total",
                np.diff(result.face_offsets).astype(np.int32),
            )
            new_mesh.polygons.foreach_set(
                "use_smooth", np.tile(source_use_smooth, count)
            )
            new_mesh.polygons.foreach_set(
                "material_index", np.tile(source_material_indices, count)
            )
        for material in old_mesh.materials:
            new_mesh.materials.append(material)
        new_mesh.update(calc_edges=True)
        source_object.data = new_mesh
    except Exception:
        bpy.data.meshes.remove(new_mesh)
        raise

    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    new_mesh.name = old_name


def extract_world_triangle_arrays(
    target_object,
    *,
    operation: str = "Geometry worker",
) -> tuple[np.ndarray, np.ndarray]:
    """Extract an evaluated mesh once for an array-only worker command."""

    total_start = time.perf_counter()
    phase_start = total_start
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = target_object.evaluated_get(depsgraph)
    evaluated_mesh = evaluated_object.to_mesh(
        preserve_all_data_layers=False,
        depsgraph=depsgraph,
    )
    evaluation_elapsed = time.perf_counter() - phase_start
    try:
        phase_start = time.perf_counter()
        evaluated_mesh.calc_loop_triangles()
        triangulation_elapsed = time.perf_counter() - phase_start

        phase_start = time.perf_counter()
        vertices = _mesh_vertices(evaluated_mesh)
        triangles = np.empty(
            (len(evaluated_mesh.loop_triangles), 3), dtype=np.int32
        )
        evaluated_mesh.loop_triangles.foreach_get(
            "vertices", triangles.ravel()
        )
        extraction_elapsed = time.perf_counter() - phase_start

        phase_start = time.perf_counter()
        world_vertices = _transform_points(
            vertices, evaluated_object.matrix_world
        )
        transform_elapsed = time.perf_counter() - phase_start
        logger.info(
            "%s extraction: object=%s vertices=%d "
            "triangles=%d evaluation=%.3fs triangulation=%.3fs "
            "array_extract=%.3fs world_transform=%.3fs total=%.3fs",
            operation,
            target_object.name,
            len(vertices),
            len(triangles),
            evaluation_elapsed,
            triangulation_elapsed,
            extraction_elapsed,
            transform_elapsed,
            time.perf_counter() - total_start,
        )
        return world_vertices, triangles
    finally:
        evaluated_object.to_mesh_clear()


def _target_surface_arrays(target_object) -> tuple[np.ndarray, np.ndarray]:
    return extract_world_triangle_arrays(
        target_object,
        operation="Nearest-surface target",
    )


def build_master_base_pin_target(target) -> None:
    """Extract the cleaned patron once and retain its private worker BVH."""

    target_object = target.object if isinstance(target, Object) else target
    vertices, triangles = extract_world_triangle_arrays(
        target_object,
        operation="Master-base pin target",
    )
    acquire_geometry_worker().build_master_base_pin_target(
        vertices, triangles
    )


def plan_master_base_pin_with_worker(
    mesh: Object,
    *,
    tolerance: float,
    requested_male_height: float,
):
    """Calculate pin dimensions, location and fitted height outside Blender."""

    bounds = np.ascontiguousarray(
        (
            mesh.min_x,
            mesh.min_y,
            mesh.min_z,
            mesh.max_x,
            mesh.max_y,
            mesh.max_z,
        ),
        dtype=np.float32,
    )
    return acquire_geometry_worker().plan_master_base_pin(
        bounds,
        tolerance=float(tolerance),
        requested_male_height=float(requested_male_height),
    )


def clear_master_base_pin_target() -> None:
    """Release the temporary pin-placement BVH without stopping the worker."""

    acquire_geometry_worker().clear_master_base_pin_target()


class BackgroundExportMeshCleanup:
    """Worker-only background cleanup finalized against Blender on main."""

    def __init__(
        self,
        source_object,
        worker_task,
        triangle_materials,
        triangle_use_smooth,
    ) -> None:
        self._source_object = source_object
        self._worker_task = worker_task
        self._triangle_materials = triangle_materials
        self._triangle_use_smooth = triangle_use_smooth
        self._result = None

    def done(self) -> bool:
        return self._worker_task.done()

    def finish(self):
        if self._result is not None:
            return self._result

        result = self._worker_task.finish()
        triangle_materials = self._triangle_materials
        triangle_use_smooth = self._triangle_use_smooth
        if result.changed:
            material_indices = np.zeros(len(result.triangles), dtype=np.int32)
            default_use_smooth = bool(
                len(triangle_use_smooth)
                and np.count_nonzero(triangle_use_smooth) * 2
                >= len(triangle_use_smooth)
            )
            use_smooth = np.full(
                len(result.triangles), default_use_smooth, dtype=np.bool_
            )
            valid_sources = (
                (result.face_sources >= 0)
                & (result.face_sources < len(triangle_materials))
            )
            material_indices[valid_sources] = triangle_materials[
                result.face_sources[valid_sources]
            ]
            use_smooth[valid_sources] = triangle_use_smooth[
                result.face_sources[valid_sources]
            ]
            _replace_mesh_geometry(
                self._source_object,
                result.vertices,
                result.triangles,
                np.empty((0, 4), dtype=np.int32),
                polygon_material_indices=material_indices,
                polygon_use_smooth=use_smooth,
            )
        self._result = result
        return result


def begin_clean_export_mesh_with_worker(
    source_object,
    *,
    generated_box: bool,
    max_passes: int = 2,
):
    """Start array-only cleanup without accessing Blender off main thread."""

    mesh = source_object.data
    mesh.calc_loop_triangles()
    vertices = _mesh_vertices(mesh)
    triangles = np.empty((len(mesh.loop_triangles), 3), dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    triangle_materials = np.ascontiguousarray(
        [
            mesh.polygons[triangle.polygon_index].material_index
            for triangle in mesh.loop_triangles
        ],
        dtype=np.int32,
    )
    triangle_use_smooth = np.ascontiguousarray(
        [
            mesh.polygons[triangle.polygon_index].use_smooth
            for triangle in mesh.loop_triangles
        ],
        dtype=np.bool_,
    )
    worker = acquire_geometry_worker()
    worker_task = submit_worker_task(
        worker.clean_slicer_mesh,
        vertices,
        triangles,
        np.asarray(source_object.matrix_world, dtype=np.float32),
        generated_box=generated_box,
        max_passes=max_passes,
        source_polygon_count=len(mesh.polygons),
    )
    return BackgroundExportMeshCleanup(
        source_object,
        worker_task,
        triangle_materials,
        triangle_use_smooth,
    )


def clean_export_mesh_with_worker(
    source_object,
    *,
    generated_box: bool,
    max_passes: int = 2,
):
    """Run fused export cleanup synchronously for non-modal callers."""

    return begin_clean_export_mesh_with_worker(
        source_object,
        generated_box=generated_box,
        max_passes=max_passes,
    ).finish()


def plan_casting_box_intersection_bands_with_worker(
    casting_boxes: list[Object],
    thickness: float,
    split_plane_specs: list[list[list[float]]] | None = None,
    horizontal_intersection: str = "TOP",
) -> dict:
    """Return protected placement and dimensions for casting-box bands."""

    bounds = [
        [
            float(box.min_x),
            float(box.max_x),
            float(box.min_y),
            float(box.max_y),
            float(box.min_z),
            float(box.max_z),
        ]
        for box in casting_boxes
    ]
    result = acquire_geometry_worker().geometry_policy(
        "casting_box_intersection_bands",
        bounds=bounds,
        thickness=float(thickness),
        split_plane_specs=split_plane_specs or [],
        horizontal_intersection=str(horizontal_intersection),
    )
    ignored_count = int(result["requested_split_plane_count"]) - int(
        result["accepted_split_plane_count"]
    )
    if ignored_count:
        logger.warning(
            "Geometry worker ignored %d invalid casting-box split plane%s",
            ignored_count,
            "" if ignored_count == 1 else "s",
        )
    return result


def plan_reference_object_cutter_with_worker(
    source_object: Object,
    operation: str,
    **arguments,
) -> dict:
    """Return worker-owned cutter transforms derived from object bounds."""

    bound_box = [
        [float(value) for value in point]
        for point in source_object.world_cords_bound_box
    ]
    return acquire_geometry_worker().geometry_policy(
        "reference_object_cutter",
        bound_box=bound_box,
        mode=str(operation),
        **arguments,
    )


def plan_clean_bottom_cutter_with_worker(
    source_object: Object,
    height: float,
) -> dict:
    """Return worker-owned placement and dimensions for bottom cleaning."""

    result = plan_reference_object_cutter_with_worker(
        source_object,
        "CLEAN_BOTTOM",
        height=float(height),
    )
    cutter = result["cutters"][0]
    return {
        "cut_z": result["cut_z"],
        "cutter_center": cutter["center"],
        "cutter_dimensions": cutter["dimensions"],
        "extrusion_distance": result["extrusion_distance"],
    }


def plan_object_split_cells(
    source_object,
    plane_specs: list[list[list[float]]],
) -> np.ndarray:
    """Send one mesh once and receive its complete split-plane cell plan."""

    if not plane_specs:
        return np.empty((1, 0), dtype=np.int8)
    representative_specs = representative_split_specs(plane_specs)
    points = np.ascontiguousarray(
        [plane_spec[0] for plane_spec in representative_specs], dtype=np.float32
    )
    normals = np.ascontiguousarray(
        [plane_spec[1] for plane_spec in representative_specs], dtype=np.float32
    )
    vertices, triangles = extract_world_triangle_arrays(
        source_object,
        operation="Direct split source",
    )
    worker = acquire_geometry_worker()
    return worker.plan_split_cells(
        vertices,
        triangles,
        plane_points=points,
        plane_normals=normals,
    ).cells


def begin_plan_object_split_cells(
    source_object,
    plane_specs: list[list[list[float]]],
):
    if not plane_specs:
        return submit_worker_task(
            lambda: np.empty((1, 0), dtype=np.int8)
        )
    representative_specs = representative_split_specs(plane_specs)
    points = np.ascontiguousarray(
        [plane_spec[0] for plane_spec in representative_specs], dtype=np.float32
    )
    normals = np.ascontiguousarray(
        [plane_spec[1] for plane_spec in representative_specs], dtype=np.float32
    )
    vertices, triangles = extract_world_triangle_arrays(
        source_object,
        operation="Direct split source",
    )
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.plan_split_cells,
        vertices,
        triangles,
        plane_points=points,
        plane_normals=normals,
        on_complete=lambda result: result.cells,
    )


def _direct_object_bounds(objects: list[Object]) -> np.ndarray:
    if not objects:
        return np.empty((0, 6), dtype=np.float32)
    return np.ascontiguousarray(
        [
            (
                obj.min_x,
                obj.min_y,
                obj.min_z,
                obj.max_x,
                obj.max_y,
                obj.max_z,
            )
            for obj in objects
        ],
        dtype=np.float32,
    )


def _direct_object_cell_sides(
    objects: list[Object],
    plane_count: int,
) -> np.ndarray:
    if not objects:
        return np.empty((0, plane_count), dtype=np.int8)
    rows = []
    for obj in objects:
        values = obj.object.get("_moldboxer_split_section_sides")
        if values is None or len(values) != plane_count:
            raise RuntimeError(
                f"{obj.name} is missing its worker split-cell metadata"
            )
        rows.append([int(value) for value in values])
    return np.ascontiguousarray(rows, dtype=np.int8)


def plan_direct_barrier_routes(
    *,
    plane_specs: list[list[list[float]]],
    parts: list[Object],
    mirrored_parts: list[Object],
    male_pieces: list[Object],
    male_plane_indices: list[int],
    female_barriers: list[Object],
    female_plane_indices: list[int],
    male_on_top_for_horizontal: bool,
):
    """Route all split barriers through one metadata-only worker request."""

    plane_count = len(plane_specs)
    normals = np.ascontiguousarray(
        [split_spec_point_normal(plane_spec)[1] for plane_spec in plane_specs],
        dtype=np.float32,
    )
    return acquire_geometry_worker().plan_barrier_routes(
        plane_normals=normals,
        part_bounds=_direct_object_bounds(parts),
        part_sides=_direct_object_cell_sides(parts, plane_count),
        mirrored_bounds=_direct_object_bounds(mirrored_parts),
        mirrored_sides=_direct_object_cell_sides(
            mirrored_parts, plane_count
        ),
        male_bounds=_direct_object_bounds(male_pieces),
        male_sides=_direct_object_cell_sides(male_pieces, plane_count),
        male_plane_indices=np.ascontiguousarray(
            male_plane_indices, dtype=np.int32
        ),
        female_bounds=_direct_object_bounds(female_barriers),
        female_plane_indices=np.ascontiguousarray(
            female_plane_indices, dtype=np.int32
        ),
        male_on_top_for_horizontal=male_on_top_for_horizontal,
    )


def begin_plan_direct_barrier_routes(
    *,
    plane_specs: list[list[list[float]]],
    parts: list[Object],
    mirrored_parts: list[Object],
    male_pieces: list[Object],
    male_plane_indices: list[int],
    female_barriers: list[Object],
    female_plane_indices: list[int],
    male_on_top_for_horizontal: bool,
):
    plane_count = len(plane_specs)
    kwargs = dict(
        plane_normals=np.ascontiguousarray(
            [split_spec_point_normal(plane_spec)[1] for plane_spec in plane_specs],
            dtype=np.float32,
        ),
        part_bounds=_direct_object_bounds(parts),
        part_sides=_direct_object_cell_sides(parts, plane_count),
        mirrored_bounds=_direct_object_bounds(mirrored_parts),
        mirrored_sides=_direct_object_cell_sides(
            mirrored_parts,
            plane_count,
        ),
        male_bounds=_direct_object_bounds(male_pieces),
        male_sides=_direct_object_cell_sides(male_pieces, plane_count),
        male_plane_indices=np.ascontiguousarray(
            male_plane_indices,
            dtype=np.int32,
        ),
        female_bounds=_direct_object_bounds(female_barriers),
        female_plane_indices=np.ascontiguousarray(
            female_plane_indices,
            dtype=np.int32,
        ),
        male_on_top_for_horizontal=male_on_top_for_horizontal,
    )
    worker = acquire_geometry_worker()
    return submit_worker_task(worker.plan_barrier_routes, **kwargs)


def plan_silicone_barrier_routes(
    *,
    axes: list[str],
    coordinates: list[float],
    parts: list[Object],
    mirrored_parts: list[Object],
    male_pieces: list[Object],
    male_system_indices: list[int],
    female_barriers: list[Object],
    female_system_indices: list[int],
):
    """Extract bounds only; all silicone barrier routing stays in the worker."""

    axis_indices = {"x": 0, "y": 1, "z": 2}
    return acquire_geometry_worker().plan_axis_barrier_routes(
        plane_axes=np.ascontiguousarray(
            [axis_indices[axis] for axis in axes], dtype=np.int8
        ),
        plane_coordinates=np.ascontiguousarray(coordinates, dtype=np.float32),
        part_bounds=_direct_object_bounds(parts),
        mirrored_bounds=_direct_object_bounds(mirrored_parts),
        male_bounds=_direct_object_bounds(male_pieces),
        male_plane_indices=np.ascontiguousarray(male_system_indices, dtype=np.int32),
        female_bounds=_direct_object_bounds(female_barriers),
        female_plane_indices=np.ascontiguousarray(female_system_indices, dtype=np.int32),
    )


def begin_plan_silicone_barrier_routes(
    *,
    axes: list[str],
    coordinates: list[float],
    parts: list[Object],
    mirrored_parts: list[Object],
    male_pieces: list[Object],
    male_system_indices: list[int],
    female_barriers: list[Object],
    female_system_indices: list[int],
):
    axis_indices = {"x": 0, "y": 1, "z": 2}
    worker = acquire_geometry_worker()
    return submit_worker_task(
        worker.plan_axis_barrier_routes,
        plane_axes=np.ascontiguousarray(
            [axis_indices[axis] for axis in axes], dtype=np.int8
        ),
        plane_coordinates=np.ascontiguousarray(
            coordinates,
            dtype=np.float32,
        ),
        part_bounds=_direct_object_bounds(parts),
        mirrored_bounds=_direct_object_bounds(mirrored_parts),
        male_bounds=_direct_object_bounds(male_pieces),
        male_plane_indices=np.ascontiguousarray(
            male_system_indices,
            dtype=np.int32,
        ),
        female_bounds=_direct_object_bounds(female_barriers),
        female_plane_indices=np.ascontiguousarray(
            female_system_indices,
            dtype=np.int32,
        ),
    )


def _casting_input_base_plane_z(base_raw) -> float:
    local_vertices = _mesh_vertices(base_raw.data)
    if not len(local_vertices):
        raise RuntimeError("casting input base plane has no vertices")
    world_vertices = _transform_points(local_vertices, base_raw.matrix_world)
    return float(np.mean(world_vertices[:, 2]))


def project_casting_input_with_worker(
    casting_input,
    target,
    base_plane,
    *,
    top_vertex_group: str,
    bottom_vertex_group: str,
) -> int:
    """Bake both casting-input cap projections through the retained worker BVH."""

    raw = getattr(casting_input, "object", casting_input)
    target_raw = getattr(target, "object", target)
    base_raw = getattr(base_plane, "object", base_plane)
    mesh = raw.data

    def group_indices(name: str) -> np.ndarray:
        group = raw.vertex_groups.get(name)
        if group is None:
            raise RuntimeError(f"casting input is missing vertex group {name!r}")
        return np.ascontiguousarray(
            [
                vertex.index
                for vertex in mesh.vertices
                if any(link.group == group.index for link in vertex.groups)
            ],
            dtype=np.int32,
        )

    top_indices = group_indices(top_vertex_group)
    bottom_indices = group_indices(bottom_vertex_group)
    if not len(top_indices) or not len(bottom_indices):
        raise RuntimeError("casting input projection groups cannot be empty")
    local_vertices = _mesh_vertices(mesh)
    world_vertices = _transform_points(local_vertices, raw.matrix_world)
    accelerator, _cache_hit, _extract, _build = _acquire_target_accelerator(
        target_raw
    )
    max_distance = max(
        1.0,
        float(np.max(world_vertices[:, 2]) - np.min(world_vertices[:, 2]))
        + float(target_raw.dimensions.z)
        + 10.0,
    )
    top, bottom, hits = accelerator.project_casting_input(
        world_vertices[top_indices],
        world_vertices[bottom_indices],
        bottom_z=_casting_input_base_plane_z(base_raw),
        max_distance=max_distance,
    )
    world_vertices[top_indices] = top
    world_vertices[bottom_indices] = bottom
    local_result = _transform_points(world_vertices, raw.matrix_world.inverted())
    mesh.vertices.foreach_set(
        "co", np.ascontiguousarray(local_result, dtype=np.float32).ravel()
    )
    mesh.update()
    logger.info(
        "Worker casting input applied: object=%s top_vertices=%d bottom_vertices=%d hits=%d",
        raw.name,
        len(top_indices),
        len(bottom_indices),
        int(np.count_nonzero(hits)),
    )
    return int(np.count_nonzero(hits))


def begin_project_casting_input_with_worker(
    casting_input,
    target,
    base_plane,
    *,
    top_vertex_group: str,
    bottom_vertex_group: str,
):
    global _cached_target_dirty

    raw = getattr(casting_input, "object", casting_input)
    target_raw = getattr(target, "object", target)
    base_raw = getattr(base_plane, "object", base_plane)
    mesh = raw.data

    def group_indices(name: str) -> np.ndarray:
        group = raw.vertex_groups.get(name)
        if group is None:
            raise RuntimeError(f"casting input is missing vertex group {name!r}")
        return np.ascontiguousarray(
            [
                vertex.index
                for vertex in mesh.vertices
                if any(link.group == group.index for link in vertex.groups)
            ],
            dtype=np.int32,
        )

    top_indices = group_indices(top_vertex_group)
    bottom_indices = group_indices(bottom_vertex_group)
    if not len(top_indices) or not len(bottom_indices):
        raise RuntimeError("casting input projection groups cannot be empty")
    world_vertices = _transform_points(_mesh_vertices(mesh), raw.matrix_world)
    inverse_world = np.asarray(raw.matrix_world.inverted(), dtype=np.float32)
    bottom_z = _casting_input_base_plane_z(base_raw)
    max_distance = max(
        1.0,
        float(np.max(world_vertices[:, 2]) - np.min(world_vertices[:, 2]))
        + float(target_raw.dimensions.z)
        + 10.0,
    )
    signature = _target_cache_signature(target_raw)
    worker = acquire_geometry_worker()
    cache_hit = bool(
        worker.is_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    target_vertices = target_triangles = None
    if not cache_hit:
        target_vertices, target_triangles = _target_surface_arrays(target_raw)
        _cached_target_dirty = True

    def run():
        if not cache_hit:
            worker.build_target(target_vertices, target_triangles)
        return worker.project_casting_input(
            world_vertices[top_indices],
            world_vertices[bottom_indices],
            bottom_z=bottom_z,
            max_distance=max_distance,
        )

    def finish(payload):
        global _cached_target_signature
        global _cached_target_object_pointer
        global _cached_target_data_pointer
        global _cached_target_dirty

        top, bottom, hits = payload
        _cached_target_signature = signature
        _cached_target_object_pointer = _blender_id_pointer(target_raw)
        _cached_target_data_pointer = _blender_id_pointer(target_raw.data)
        _cached_target_dirty = False
        world_vertices[top_indices] = top
        world_vertices[bottom_indices] = bottom
        local_result = _transform_points(world_vertices, inverse_world)
        mesh.vertices.foreach_set(
            "co",
            np.ascontiguousarray(local_result, dtype=np.float32).ravel(),
        )
        mesh.update()
        return int(np.count_nonzero(hits))

    return submit_worker_task(run, on_complete=finish)


def apply_nearest_surface_shrinkwrap(
    source_object,
    accelerator: TriangleBVHWorker,
    *,
    offset: float,
    seed_triangle_indices=None,
) -> np.ndarray:
    """Update only vertex coordinates; topology and Blender data stay local."""

    total_start = time.perf_counter()
    mesh = source_object.data
    phase_start = time.perf_counter()
    local_vertices = _mesh_vertices(mesh)
    extraction_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    world_vertices = _transform_points(local_vertices, source_object.matrix_world)
    to_world_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    wrapped_world_vertices, nearest_result = accelerator.shrinkwrap_with_result(
        world_vertices,
        offset=offset,
        seed_triangle_indices=seed_triangle_indices,
    )
    projection_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    inverse_world = source_object.matrix_world.inverted()
    wrapped_local_vertices = np.ascontiguousarray(
        _transform_points(wrapped_world_vertices, inverse_world),
        dtype=np.float32,
    )
    to_local_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    mesh.vertices.foreach_set("co", wrapped_local_vertices.ravel())
    mesh.update()
    write_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Nearest-surface Blender apply: object=%s vertices=%d "
        "array_extract=%.3fs to_world=%.3fs projection=%.3fs "
        "to_local=%.3fs mesh_write=%.3fs total=%.3fs",
        source_object.name,
        len(local_vertices),
        extraction_elapsed,
        to_world_elapsed,
        projection_elapsed,
        to_local_elapsed,
        write_elapsed,
        time.perf_counter() - total_start,
    )
    return nearest_result.triangle_indices


def begin_apply_nearest_surface_shrinkwrap(
    source_object,
    target_object,
    *,
    offset: float,
    vertex_indices=None,
):
    """Apply one worker nearest-surface wrap without changing mesh topology."""

    source_raw = getattr(source_object, "object", source_object)
    target_raw = getattr(target_object, "object", target_object)
    mesh = source_raw.data
    local_vertices = _mesh_vertices(mesh)
    world_vertices = _transform_points(local_vertices, source_raw.matrix_world)
    if vertex_indices is None:
        wrapped_indices = np.arange(len(local_vertices), dtype=np.int32)
    else:
        wrapped_indices = np.unique(
            np.asarray(tuple(vertex_indices), dtype=np.int32)
        )
        if len(wrapped_indices) and (
            int(wrapped_indices[0]) < 0
            or int(wrapped_indices[-1]) >= len(local_vertices)
        ):
            raise ValueError("vertex_indices contains an out-of-range index")
    selected_world_vertices = np.ascontiguousarray(
        world_vertices[wrapped_indices],
        dtype=np.float32,
    )
    inverse_world = source_raw.matrix_world.inverted().copy()
    accelerator, _cache_hit, _extract, _build = _acquire_target_accelerator(
        target_raw
    )

    def run():
        return accelerator.shrinkwrap_with_result(
            selected_world_vertices,
            offset=float(offset),
        )

    def finish(payload):
        wrapped_world_vertices, nearest_result = payload
        wrapped_local_subset = np.ascontiguousarray(
            _transform_points(wrapped_world_vertices, inverse_world),
            dtype=np.float32,
        )
        local_vertices[wrapped_indices] = wrapped_local_subset
        mesh.vertices.foreach_set("co", local_vertices.ravel())
        mesh.update()
        logger.info(
            "Async worker nearest-surface wrap applied: object=%s vertices=%d "
            "offset=%.6f hits=%d",
            source_raw.name,
            len(wrapped_local_subset),
            float(offset),
            int(np.count_nonzero(nearest_result.hit_mask)),
        )
        return nearest_result.triangle_indices

    return submit_worker_task(run, on_complete=finish)


def apply_nearest_surface_wrap_sequence(
    source_object,
    accelerator: TriangleBVHWorker,
    *,
    normal_offset: float,
    offset: float,
    wrap_count: int,
    smooth_factor: float,
    smooth_repeat: int,
) -> None:
    """Run every projection and between-pass smooth in one worker request."""

    total_start = time.perf_counter()
    mesh = source_object.data
    phase_start = time.perf_counter()
    local_vertices = _mesh_vertices(mesh)
    source_edges = _mesh_edges(mesh)
    source_triangles = (
        _mesh_triangles(mesh)
        if normal_offset != 0.0
        else None
    )
    extraction_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    world_vertices = _transform_points(local_vertices, source_object.matrix_world)
    to_world_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    wrapped_world_vertices = accelerator.shrinkwrap_sequence(
        world_vertices,
        source_edges,
        wrap_count=wrap_count,
        source_triangles=source_triangles,
        normal_offset=normal_offset,
        offset=offset,
        smooth_factor=smooth_factor,
        smooth_repeat=smooth_repeat,
    )
    worker_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    inverse_world = source_object.matrix_world.inverted()
    wrapped_local_vertices = np.ascontiguousarray(
        _transform_points(wrapped_world_vertices, inverse_world),
        dtype=np.float32,
    )
    to_local_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    mesh.vertices.foreach_set("co", wrapped_local_vertices.ravel())
    mesh.update()
    write_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Nearest-surface Blender sequence apply: object=%s vertices=%d "
        "edges=%d triangles=%d wraps=%d normal_offset=%.6f "
        "array_extract=%.3fs to_world=%.3fs "
        "worker_roundtrip=%.3fs to_local=%.3fs mesh_write=%.3fs total=%.3fs",
        source_object.name,
        len(local_vertices),
        len(source_edges),
        len(source_triangles) if source_triangles is not None else 0,
        wrap_count,
        normal_offset,
        extraction_elapsed,
        to_world_elapsed,
        worker_elapsed,
        to_local_elapsed,
        write_elapsed,
        time.perf_counter() - total_start,
    )


def apply_worker_voxel_remesh_wrap_sequence(
    source_object,
    accelerator: TriangleBVHWorker,
    *,
    voxel_size: float,
    normal_offset: float,
    offset: float,
    wrap_count: int,
    smooth_factor: float,
    smooth_repeat: int,
) -> None:
    """Run the first voxel remesh and all wrap passes in one worker request."""

    total_start = time.perf_counter()
    mesh = source_object.data
    phase_start = time.perf_counter()
    local_vertices = _mesh_vertices(mesh)
    source_triangles = _mesh_triangles(mesh)
    extraction_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    world_vertices = _transform_points(local_vertices, source_object.matrix_world)
    to_world_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    worker_mesh = accelerator.voxel_remesh_wrap_sequence(
        world_vertices,
        source_triangles,
        voxel_size=voxel_size,
        wrap_count=wrap_count,
        normal_offset=normal_offset,
        offset=offset,
        smooth_factor=smooth_factor,
        smooth_repeat=smooth_repeat,
    )
    worker_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    inverse_world = source_object.matrix_world.inverted()
    wrapped_local_vertices = np.ascontiguousarray(
        _transform_points(worker_mesh.vertices, inverse_world),
        dtype=np.float32,
    )
    to_local_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    _replace_mesh_geometry(
        source_object,
        wrapped_local_vertices,
        worker_mesh.triangles,
        worker_mesh.quads,
    )
    write_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Nearest-surface Blender worker-remesh apply: object=%s "
        "input_vertices=%d input_triangles=%d output_vertices=%d "
        "output_triangles=%d output_quads=%d wraps=%d normal_offset=%.6f "
        "array_extract=%.3fs to_world=%.3fs worker_roundtrip=%.3fs "
        "to_local=%.3fs mesh_replace=%.3fs total=%.3fs",
        source_object.name,
        len(local_vertices),
        len(source_triangles),
        len(worker_mesh.vertices),
        len(worker_mesh.triangles),
        len(worker_mesh.quads),
        wrap_count,
        normal_offset,
        extraction_elapsed,
        to_world_elapsed,
        worker_elapsed,
        to_local_elapsed,
        write_elapsed,
        time.perf_counter() - total_start,
    )


def _create_worker_envelope_object(
    name: str,
    target_object,
    worker_mesh,
):
    mesh = bpy.data.meshes.new(f"{name}_worker_input")
    blender_object = bpy.data.objects.new(f"{name}_worker_input", mesh)
    bpy.context.collection.objects.link(blender_object)
    try:
        _replace_mesh_geometry(
            blender_object,
            worker_mesh.vertices,
            worker_mesh.triangles,
            worker_mesh.quads,
        )
        for material in target_object.data.materials:
            blender_object.data.materials.append(material)
        return blender_object
    except Exception:
        if blender_object.name in bpy.data.objects:
            remove_objects_safely((blender_object,))
        raise


class WorkerMeshEnvelope(Object):
    """Thin Blender facade for the retained-target geometry pipeline."""

    def __init__(
        self,
        target: Object,
        voxel_size: float = 1.0,
        distance: float = 6.0,
        n_wraps: int = 2,
        *,
        algorithm: str,
        final_wrap_distance: float | None = None,
        cut_top_before_each_wrap: bool = False,
        name_adder: str = "",
        geometry_to_origin: bool = False,
        cut_bot: bool = True,
        build_from_sphere: bool = False,
        normal_offset: float = 2.0,
        remesh_scaled: bool = True,
        sphere_voxel_factor: float = 2.0,
        sphere_size_factor: float = 1.0,
        sphere_height_factor: float | None = None,
        cut_top_bf_wrap: bool = False,
        cut_bottom_bf_wrap: bool = False,
        pre_wrap_cut_offset: float = 1.0,
        smooth_after_wrap: bool = True,
        finish_top_after_intermediate_remesh: bool = False,
        finish_bottom_after_intermediate_remesh: bool = False,
        remesh_between_wraps: bool = True,
        apply_final_remesh: bool = True,
        intermediate_top_clean_voxel_factor: float = 2.0,
        intermediate_top_target_offset: float = 2.0,
        target_cache_object=None,
        simplify_target_reduction: float | None = None,
    ) -> None:
        total_start = time.perf_counter()
        algorithm = str(algorithm).upper()
        if isinstance(target_cache_object, Object):
            target_cache_object = target_cache_object.object
        if target_cache_object is None:
            target_cache_object = target.object
        if geometry_to_origin:
            target.geometry_to_origin()
        target_min_z = target.min_z
        envelope_options = dict(
            algorithm=algorithm,
            voxel_size=float(voxel_size),
            distance=float(distance),
            final_wrap_distance=final_wrap_distance,
            cut_top_before_each_wrap=bool(cut_top_before_each_wrap),
            wrap_count=int(n_wraps),
            build_from_sphere=bool(build_from_sphere),
            normal_offset=(
                0.0 if build_from_sphere else float(normal_offset)
            ),
            remesh_scaled=bool(remesh_scaled),
            sphere_voxel_factor=float(sphere_voxel_factor),
            sphere_size_factor=float(sphere_size_factor),
            sphere_height_factor=(
                float(sphere_size_factor)
                if sphere_height_factor is None
                else float(sphere_height_factor)
            ),
            cut_top_before_wrap=bool(cut_top_bf_wrap),
            cut_bottom_before_wrap=bool(cut_bottom_bf_wrap),
            pre_wrap_cut_offset=float(pre_wrap_cut_offset),
            smooth_after_wrap=bool(smooth_after_wrap),
            finish_top_after_intermediate_remesh=bool(
                finish_top_after_intermediate_remesh
            ),
            finish_bottom_after_intermediate_remesh=bool(
                finish_bottom_after_intermediate_remesh
            ),
            remesh_between_wraps=bool(remesh_between_wraps),
            intermediate_top_clean_voxel_factor=float(
                intermediate_top_clean_voxel_factor
            ),
            intermediate_top_target_offset=float(intermediate_top_target_offset),
        )
        if simplify_target_reduction is None:
            (
                accelerator,
                worker_cache_hit,
                target_extraction_elapsed,
                worker_build_elapsed,
            ) = _acquire_target_accelerator(
                target.object,
                cache_identity_object=target_cache_object,
            )
            phase_start = time.perf_counter()
            worker_mesh = accelerator.build_envelope(**envelope_options)
            worker_elapsed = time.perf_counter() - phase_start
        else:
            (
                accelerator,
                worker_mesh,
                worker_cache_hit,
                target_extraction_elapsed,
                worker_build_elapsed,
                worker_elapsed,
            ) = _build_simplified_envelope_with_cache(
                target.object,
                cache_identity_object=target_cache_object,
                target_reduction=float(simplify_target_reduction),
                envelope_options=envelope_options,
            )

        phase_start = time.perf_counter()
        blender_object = _create_worker_envelope_object(
            "box" + name_adder,
            target.object,
            worker_mesh,
        )
        super().__init__(blender_object, "box" + name_adder)
        self.hide_during_ui_breathe = True
        self.smooth_after_wrap = bool(smooth_after_wrap)
        self.build_from_sphere = bool(build_from_sphere)
        self.voxel_size = float(voxel_size)
        self.distance = float(distance)
        self.n_wraps = int(n_wraps)
        self.cut_bot = bool(cut_bot)
        self.remesh_scaled = bool(remesh_scaled)
        self.sphere_voxel_factor = float(sphere_voxel_factor)
        self.sphere_size_factor = float(sphere_size_factor)
        self.sphere_height_factor = (
            float(sphere_size_factor)
            if sphere_height_factor is None
            else float(sphere_height_factor)
        )
        self.cut_top_bf_wrap = bool(cut_top_bf_wrap)
        self.cut_bottom_bf_wrap = bool(cut_bottom_bf_wrap)
        self.pre_wrap_cut_offset = float(pre_wrap_cut_offset)
        self.finish_top_after_intermediate_remesh = bool(
            finish_top_after_intermediate_remesh
        )
        self.finish_bottom_after_intermediate_remesh = bool(
            finish_bottom_after_intermediate_remesh
        )
        self.remesh_between_wraps = bool(remesh_between_wraps)
        self.apply_final_remesh = bool(apply_final_remesh)
        self.simplify_target_reduction = simplify_target_reduction
        self.worker_target_cache_hit = worker_cache_hit
        self.worker_target_extraction_seconds = target_extraction_elapsed
        self.worker_target_build_seconds = worker_build_elapsed
        self.worker_pipeline_seconds = worker_elapsed
        self.worker_target_vertex_count = accelerator.vertex_count
        self.worker_target_triangle_count = accelerator.triangle_count
        mesh_create_elapsed = time.perf_counter() - phase_start

        final_remesh_elapsed = 0.0
        if apply_final_remesh:
            phase_start = time.perf_counter()
            self.apply_modifier(build_voxel_modifier(float(voxel_size)))
            final_remesh_elapsed = time.perf_counter() - phase_start
        bottom_cut_elapsed = 0.0
        if cut_bot:
            phase_start = time.perf_counter()
            self.cut_plane(
                plane_normal=mathutils.Vector((0, 0, -1)),
                plane_point=mathutils.Vector((0, 0, target_min_z)),
            )
            bottom_cut_elapsed = time.perf_counter() - phase_start
        logger.info(
            "Worker-backed envelope complete: algorithm=%s object=%s target=%s "
            "target_vertices=%d target_triangles=%d target_cache_hit=%s "
            "target_reduction=%s "
            "target_extract=%.3fs worker_build=%.3fs worker_pipeline=%.3fs "
            "mesh_create=%.3fs final_remesh=%.3fs bottom_cut=%.3fs "
            "total=%.3fs",
            algorithm,
            self.name,
            target.name,
            accelerator.vertex_count,
            accelerator.triangle_count,
            worker_cache_hit,
            (
                "none"
                if simplify_target_reduction is None
                else f"{float(simplify_target_reduction) * 100.0:.2f}%"
            ),
            target_extraction_elapsed,
            worker_build_elapsed,
            worker_elapsed,
            mesh_create_elapsed,
            final_remesh_elapsed,
            bottom_cut_elapsed,
            time.perf_counter() - total_start,
        )

class WorkerEnvelopeTest(WorkerMeshEnvelope):
    """Worker-envelope configuration used by the geometry test operator."""

    def __init__(self, target: Object, voxel_size=1.0, distance=6.0, n_wraps=2, **kwargs):
        kwargs.setdefault("name_adder", "_nearest_surface")
        kwargs.setdefault("cut_bot", False)
        kwargs["sphere_voxel_factor"] = 2.0
        super().__init__(
            target,
            voxel_size,
            distance,
            n_wraps,
            algorithm="OPTIMIZED",
            **kwargs,
        )


def begin_worker_mesh_envelope(
    target: Object,
    voxel_size: float = 1.0,
    distance: float = 6.0,
    n_wraps: int = 2,
    *,
    algorithm: str,
    final_wrap_distance: float | None = None,
    cut_top_before_each_wrap: bool = False,
    name_adder: str = "",
    geometry_to_origin: bool = False,
    cut_bot: bool = True,
    build_from_sphere: bool = False,
    normal_offset: float = 2.0,
    remesh_scaled: bool = True,
    sphere_voxel_factor: float = 2.0,
    sphere_size_factor: float = 1.0,
    sphere_height_factor: float | None = None,
    cut_top_bf_wrap: bool = False,
    cut_bottom_bf_wrap: bool = False,
    pre_wrap_cut_offset: float = 1.0,
    smooth_after_wrap: bool = True,
    finish_top_after_intermediate_remesh: bool = False,
    finish_bottom_after_intermediate_remesh: bool = False,
    remesh_between_wraps: bool = True,
    apply_final_remesh: bool = True,
    intermediate_top_clean_voxel_factor: float = 2.0,
    intermediate_top_target_offset: float = 2.0,
    target_cache_object=None,
    simplify_target_reduction: float | None = None,
):
    """Build the retained-target envelope off-thread and finalize on main."""

    global _cached_target_dirty

    algorithm = str(algorithm).upper()
    if isinstance(target_cache_object, Object):
        target_cache_object = target_cache_object.object
    if target_cache_object is None:
        target_cache_object = target.object
    if geometry_to_origin:
        target.geometry_to_origin()
    target_min_z = target.min_z
    target_object = target.object
    identity_object = target_cache_object
    signature = _target_cache_signature(identity_object)
    if simplify_target_reduction is not None:
        signature += (
            "simplified",
            round(float(simplify_target_reduction), 12),
        )

    envelope_options = dict(
        algorithm=algorithm,
        voxel_size=float(voxel_size),
        distance=float(distance),
        final_wrap_distance=final_wrap_distance,
        cut_top_before_each_wrap=bool(cut_top_before_each_wrap),
        wrap_count=int(n_wraps),
        build_from_sphere=bool(build_from_sphere),
        normal_offset=0.0 if build_from_sphere else float(normal_offset),
        remesh_scaled=bool(remesh_scaled),
        sphere_voxel_factor=float(sphere_voxel_factor),
        sphere_size_factor=float(sphere_size_factor),
        sphere_height_factor=(
            float(sphere_size_factor)
            if sphere_height_factor is None
            else float(sphere_height_factor)
        ),
        cut_top_before_wrap=bool(cut_top_bf_wrap),
        cut_bottom_before_wrap=bool(cut_bottom_bf_wrap),
        pre_wrap_cut_offset=float(pre_wrap_cut_offset),
        smooth_after_wrap=bool(smooth_after_wrap),
        finish_top_after_intermediate_remesh=bool(
            finish_top_after_intermediate_remesh
        ),
        finish_bottom_after_intermediate_remesh=bool(
            finish_bottom_after_intermediate_remesh
        ),
        remesh_between_wraps=bool(remesh_between_wraps),
        intermediate_top_clean_voxel_factor=float(
            intermediate_top_clean_voxel_factor
        ),
        intermediate_top_target_offset=float(intermediate_top_target_offset),
    )
    worker = acquire_geometry_worker()
    cache_hit = bool(
        worker.is_running
        and not _cached_target_dirty
        and signature == _cached_target_signature
    )
    target_extract_start = time.perf_counter()
    target_vertices = target_triangles = None
    if not cache_hit:
        target_vertices, target_triangles = _target_surface_arrays(target_object)
        _cached_target_dirty = True
    target_extraction_elapsed = time.perf_counter() - target_extract_start

    def run_worker_pipeline():
        worker_build_elapsed = 0.0
        if simplify_target_reduction is not None and not cache_hit:
            started = time.perf_counter()
            fused = worker.build_simplified_envelope(
                target_vertices,
                target_triangles,
                target_reduction=float(simplify_target_reduction),
                **envelope_options,
            )
            return (
                fused.mesh,
                fused.simplification_seconds + fused.bvh_seconds,
                time.perf_counter() - started,
            )
        if not cache_hit:
            started = time.perf_counter()
            worker.build_target(target_vertices, target_triangles)
            worker_build_elapsed = time.perf_counter() - started
        started = time.perf_counter()
        worker_mesh = worker.build_envelope(**envelope_options)
        return (
            worker_mesh,
            worker_build_elapsed,
            time.perf_counter() - started,
        )

    def finish_worker_pipeline(payload):
        global _cached_target_signature
        global _cached_target_object_pointer
        global _cached_target_data_pointer
        global _cached_target_dirty

        worker_mesh, worker_build_elapsed, worker_elapsed = payload
        _cached_target_signature = signature
        _cached_target_object_pointer = _blender_id_pointer(identity_object)
        _cached_target_data_pointer = _blender_id_pointer(identity_object.data)
        _cached_target_dirty = False
        name = "box" + name_adder
        blender_object = _create_worker_envelope_object(
            name,
            target_object,
            worker_mesh,
        )
        envelope = Object(blender_object, name)
        envelope.hide_during_ui_breathe = True
        envelope.smooth_after_wrap = bool(smooth_after_wrap)
        envelope.build_from_sphere = bool(build_from_sphere)
        envelope.voxel_size = float(voxel_size)
        envelope.distance = float(distance)
        envelope.n_wraps = int(n_wraps)
        envelope.cut_bot = bool(cut_bot)
        envelope.remesh_scaled = bool(remesh_scaled)
        envelope.sphere_voxel_factor = float(sphere_voxel_factor)
        envelope.sphere_size_factor = float(sphere_size_factor)
        envelope.sphere_height_factor = (
            float(sphere_size_factor)
            if sphere_height_factor is None
            else float(sphere_height_factor)
        )
        envelope.cut_top_bf_wrap = bool(cut_top_bf_wrap)
        envelope.cut_bottom_bf_wrap = bool(cut_bottom_bf_wrap)
        envelope.pre_wrap_cut_offset = float(pre_wrap_cut_offset)
        envelope.finish_top_after_intermediate_remesh = bool(
            finish_top_after_intermediate_remesh
        )
        envelope.finish_bottom_after_intermediate_remesh = bool(
            finish_bottom_after_intermediate_remesh
        )
        envelope.remesh_between_wraps = bool(remesh_between_wraps)
        envelope.apply_final_remesh = bool(apply_final_remesh)
        envelope.simplify_target_reduction = simplify_target_reduction
        envelope.worker_target_cache_hit = cache_hit
        envelope.worker_target_extraction_seconds = target_extraction_elapsed
        envelope.worker_target_build_seconds = worker_build_elapsed
        envelope.worker_pipeline_seconds = worker_elapsed
        envelope.worker_target_vertex_count = worker.vertex_count
        envelope.worker_target_triangle_count = worker.triangle_count
        if apply_final_remesh:
            envelope.apply_modifier(build_voxel_modifier(float(voxel_size)))
        if cut_bot:
            envelope.cut_plane(
                plane_normal=mathutils.Vector((0, 0, -1)),
                plane_point=mathutils.Vector((0, 0, target_min_z)),
            )
        logger.info(
            "Async worker-backed envelope complete: algorithm=%s object=%s "
            "target=%s cache_hit=%s worker_build=%.3fs worker_pipeline=%.3fs",
            algorithm,
            envelope.name,
            target.name,
            cache_hit,
            worker_build_elapsed,
            worker_elapsed,
        )
        return envelope

    return submit_worker_task(
        run_worker_pipeline,
        on_complete=finish_worker_pipeline,
    )
