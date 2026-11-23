"""Debounced, non-destructive Direct and Slip Cast surface preview and extraction-plan cache.

Blender only snapshots mesh data, watches edits and draws the worker result.
Section splitting, candidate scoring and affected-face selection stay in worker.
"""
from __future__ import annotations

import json
import logging
import time

import bpy
from mathutils import Vector
from bpy.app.handlers import persistent

from ..background_worker import BackgroundTaskSequence
from ..object import Object
from ..mold_types import is_direct_mold_type, is_slip_casting_type, resolve_direct_mold_opening
from ..operator_logs import log_background_event
from .clear_undercuts import (
    begin_clear_undercuts, _mesh_from_worker_polygon_result,
    _mesh_triangle_indices,
)
from .direct_split_planes import direct_split_plane_specs, sync_direct_split_planes_with_scene
from .clear_undercuts_overlay import (
    display_worker_extraction_direction_arrows, clear_extraction_direction_arrows,
)

logger = logging.getLogger(__name__)
_cache = None
_task = None
_preview_iterator = None
_revision = 0
_observed_key = None
_changed_at = 0.0
_failed_key = None
_batch = None
_shader = None
_handler = None
_snapshot = None
_run_id = 0
_last_started_key = None
_owns_direction_overlay = False


def _log(message, *args):
    log_background_event(logger, "Mold undercut preview: " + message, *args)


def _change_reason(previous, current):
    if previous is None:
        return "initial preparation or project load"
    reasons = []
    if previous[8] != current[8]:
        reasons.append("split planes changed")
    if previous[4] != current[4]:
        reasons.append("master transform changed")
    if previous[:4] != current[:4] or previous[5:7] != current[5:7]:
        reasons.append("master geometry or project changed")
    if previous[7] != current[7]:
        reasons.append("master quality changed")
    if previous[9] != current[9]:
        reasons.append("preparation state changed")
    if previous[10:] != current[10:]:
        reasons.append("master clearance settings changed")
    return ", ".join(reasons) or "cache unavailable"


def _eligible(scene):
    master = scene.objects.get("patron")
    mold_type = getattr(scene, "mold_type_preview", "")
    slip_casting = is_slip_casting_type(mold_type)
    return bool(
        (slip_casting or is_direct_mold_type(mold_type))
        and master is not None and master.type == "MESH"
        and master.mode == "OBJECT"
        and getattr(scene, "clear_extraction", True)
        and (not slip_casting or master.get("moldboxer_slip_casting_funnels_built", False))
        and not any(scene.objects.get(name) for name in ("box", "left_box", "right_box", "master"))
        and not any(obj.name.startswith("plaster_mold_part") for obj in scene.objects)
    )


def _key(scene, specs):
    master = scene.objects.get("patron")
    if master is None:
        return None
    return (
        scene.as_pointer(), master.as_pointer(), master.data.as_pointer(), _revision,
        tuple(value for row in master.matrix_world for value in row),
        len(master.data.vertices), len(master.data.polygons),
        str(getattr(scene, "master_quality", "MID")),
        json.dumps(specs, sort_keys=True),
        bool(master.get("moldboxer_slip_casting_funnels_built", False)),
        getattr(scene, "clear_extraction", True),
        "MID_HORIZONTAL_INTERSECTION_V2",
        str(getattr(scene, "mold_type_preview", "")),
        _extraction_options(scene, specs),
    )


def _extraction_options(scene, specs):
    """Match each mold workflow's clearance policy without modifying the master."""
    mold_type = getattr(scene, "mold_type_preview", "")
    slip_casting = is_slip_casting_type(mold_type)
    mode = "EASY_EXTRACTION" if slip_casting else getattr(scene, "clear_undercuts_mode", "EASY_EXTRACTION")
    opening = resolve_direct_mold_opening(mold_type, getattr(scene, "direct_mold_opening", "base_open"))
    return {
        "easy_extraction": mode == "EASY_EXTRACTION",
        "precise_cost": mode == "PRECISE",
        "horizontal_extraction": slip_casting,
        "mid_horizontal_extraction": slip_casting,
        "restrict_bottom_extraction": (
            len(specs) != 1 if slip_casting
            else opening == "top_funnel" or mode not in {"OPTIMIZED", "PRECISE"}
        ),
    }


def _clear_display():
    global _batch, _owns_direction_overlay
    _batch = None
    if _owns_direction_overlay:
        clear_extraction_direction_arrows()
        _owns_direction_overlay = False


def _draw():
    if _batch is None or not _eligible(bpy.context.scene):
        return
    from .. import bl_utils
    if bl_utils._modal_progress_overlay_active_count:
        return
    import gpu
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    gpu.state.blend_set("ALPHA")
    try:
        _shader.bind()
        _shader.uniform_float("color", (1.0, 0.015, 0.01, 0.9))
        _batch.draw(_shader)
    finally:
        gpu.state.blend_set("NONE")
        gpu.state.depth_mask_set(True)
        gpu.state.depth_test_set("NONE")


def _display(mesh_result):
    global _batch, _shader, _handler
    _clear_display()
    if bpy.app.background or len(mesh_result.face_offsets) <= 1:
        return
    import gpu
    import numpy as np
    from gpu_extras.batch import batch_for_shader
    mesh = _mesh_from_worker_polygon_result("Slip Cast preview surface", mesh_result)
    try:
        triangles = _mesh_triangle_indices(mesh)
        positions = np.asarray(mesh_result.vertices).copy()
        # Tiny surface offset prevents z-fighting; it changes only the drawing.
        normals = np.empty_like(positions)
        mesh.vertices.foreach_get("normal", normals.ravel())
        positions += normals * 0.015
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        _batch = batch_for_shader(_shader, "TRIS", {"pos": positions}, indices=triangles)
        if _handler is None:
            _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    finally:
        bpy.data.meshes.remove(mesh)
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _remove_snapshot():
    global _snapshot
    if _snapshot is not None:
        raw, _snapshot = _snapshot, None
        try:
            mesh = raw.data
        except ReferenceError:
            return  # Undo or loading a file may already have removed this ID.
        bpy.data.objects.remove(raw)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def _preview_bottom_reference(master):
    """Read the eight existing bounding-box corners without selecting objects."""
    corners = [master.matrix_world @ Vector(corner) for corner in master.bound_box]
    lower = [min(corner[axis] for corner in corners) for axis in range(3)]
    upper = [max(corner[axis] for corner in corners) for axis in range(3)]
    return [[(lower[0] + upper[0]) / 2, (lower[1] + upper[1]) / 2, lower[2]],
            [0.0, 0.0, 1.0]]


def begin_preview(context):
    """Return a shared pollable task; generation may wait for an active preview."""
    global _task, _preview_iterator
    if _task is not None:
        return _task

    def steps():
        global _cache, _snapshot, _failed_key, _run_id, _last_started_key, _owns_direction_overlay
        scene = context.scene
        if not _eligible(scene):
            return None
        sync_direct_split_planes_with_scene()
        specs = direct_split_plane_specs()
        if not specs:
            return None
        signature = _key(scene, specs)
        if _cache is not None and _cache["key"] == signature:
            return _cache
        master = scene.objects.get("patron")
        _run_id += 1
        run_id = _run_id
        started = time.perf_counter()
        _log("recalculation started run=%d reason=%s split_planes=%d source_faces=%d",
             run_id, _change_reason(_last_started_key, signature), len(specs), len(master.data.polygons))
        _last_started_key = signature
        try:
            # An unlinked snapshot remains stable while the user edits the live model.
            raw = bpy.data.objects.new("Slip Cast analysis snapshot", master.data.copy())
            _snapshot = raw
            raw.matrix_world = master.matrix_world.copy()
            boundary = (
                [] if is_slip_casting_type(scene.mold_type_preview) and len(specs) == 1
                else [_preview_bottom_reference(master)]
            )
            paths, faces = {}, {}
            yield begin_clear_undercuts(
                target_object=Object(raw), bidirectional=True,
                split_plane_specs=specs, boundary_plane_specs=boundary,
                **_extraction_options(scene, specs),
                split_plane_overtravel_override=0.0,
                clearance_build_overtravel_override=0.25,
                planning_only=True, display_extraction_directions=False,
                selected_paths_out=paths, preview_faces_out=faces,
            )
            if _eligible(scene) and signature == _key(scene, direct_split_plane_specs()):
                _cache = {"key": signature, "specs": specs, "boundary": boundary, "paths": paths, "run_id": run_id}
                _failed_key = None
                _display(faces["mesh"])
                # Publish both overlays only after validating the result, so old
                # worker responses cannot display stale extraction directions.
                direction_paths = faces["selected_paths"]
                display_worker_extraction_direction_arrows(direction_paths)
                _owns_direction_overlay = True
                _log("recalculation completed run=%d split_planes=%d sections=%d affected_faces=%d extraction_arrows=%d elapsed=%.3fs display=%s",
                     run_id, len(specs), len(paths), len(faces["mesh"].face_offsets) - 1,
                     len(direction_paths),
                     time.perf_counter() - started,
                     "headless" if bpy.app.background else ("red overlay updated" if _batch is not None else "no affected faces"))
                return _cache
            _log("result discarded run=%d reason=inputs changed or preview no longer active elapsed=%.3fs",
                 run_id, time.perf_counter() - started)
            return None
        except Exception as exc:
            _cache = None
            _failed_key = signature
            _log("recalculation failed run=%d elapsed=%.3fs error=%s", run_id, time.perf_counter() - started, exc)
            logger.exception("Mold undercut preview failed; generation can calculate again")
            return None
        finally:
            _remove_snapshot()

    _preview_iterator = steps()
    _task = BackgroundTaskSequence(_preview_iterator)
    return _task


def cached_plan(scene, specs):
    if _cache is not None and _cache["key"] == _key(scene, specs):
        return _cache
    return None


def begin_generation_plan(context):
    """Finish an in-flight calculation before consuming its matching paths."""
    def steps():
        global _task
        if _task is not None:
            _log("Generate Mold waiting for pending preview task")
            pending = _task
            yield pending
            if _task is pending:
                _task = None
        sync_direct_split_planes_with_scene()
        specs = direct_split_plane_specs()
        plan = cached_plan(context.scene, specs)
        if plan is None:
            _log("Generate Mold has no matching cached plan; requesting calculation")
            pending = begin_preview(context)
            yield pending
            if _task is pending:
                _task = None
            plan = cached_plan(context.scene, direct_split_plane_specs())
        if plan is not None:
            _log("Generate Mold reusing cached plan run=%d split_planes=%d sections=%d",
                 plan["run_id"], len(plan["specs"]), len(plan["paths"]))
        else:
            _log("Generate Mold has no preview plan; full clearance will calculate paths")
        _clear_display()
        return plan
    return BackgroundTaskSequence(steps())


@persistent
def _on_update(scene, depsgraph):
    global _revision
    master = scene.objects.get("patron")
    if master is None:
        return
    for update in depsgraph.updates:
        if update.id == master.data or (update.id == master and update.is_updated_geometry):
            _revision += 1
            _clear_display()
            break


def _tick():
    global _task, _cache, _observed_key, _changed_at
    try:
        from .. import bl_utils
        # Modal generation owns its tasks; never advance its shared task twice.
        if bl_utils._modal_progress_overlay_active_count:
            return 0.2
        scene = bpy.context.scene
        if not _eligible(scene):
            _cache = None
            _clear_display()
            # Drain any snapshot already in flight, rejecting its stale result.
            if _task is not None and _task.done():
                _task.finish()
                _task = None
            return 0.2
        specs = direct_split_plane_specs()
        if not specs:
            _cache = None
            _clear_display()
            if _task is not None and _task.done():
                _task.finish()
                _task = None
            return 0.2
        signature = _key(scene, specs)
        if signature != _observed_key:
            _observed_key, _changed_at = signature, time.monotonic()
            if _cache is None or _cache["key"] != signature:
                if _cache is not None:
                    _log("cached preview invalidated reason=%s; waiting for edits to settle",
                         _change_reason(_cache["key"], signature))
                _cache = None
                _clear_display()
        if _task is not None:
            if _task.done():
                _task.finish()
                _task = None
        elif _cache is None and signature != _failed_key and time.monotonic() - _changed_at >= 0.5:
            begin_preview(bpy.context)
    except Exception:
        logger.exception("Could not update mold undercut preview")
        _task = None
        _remove_snapshot()
    return 0.2


@persistent
def _before_history_change(_unused):
    """Detach pending work before Blender replaces the scene's mesh IDs."""
    global _task, _preview_iterator, _cache, _revision, _failed_key, _observed_key
    _revision += 1
    _cache = _failed_key = _observed_key = None
    _clear_display()
    if _preview_iterator is not None:
        _preview_iterator.close()
        _preview_iterator = None
    _task = None
    _remove_snapshot()


def _after_history_change(action):
    global _revision, _cache, _failed_key, _observed_key, _changed_at
    _revision += 1
    _cache = _failed_key = _observed_key = None
    _changed_at = time.monotonic()
    _clear_display()
    _log("%s completed; faces and extraction arrows reset; recalculation scheduled for restored preparation", action)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


@persistent
def _after_undo(_unused):
    _after_history_change("Undo")


@persistent
def _after_redo(_unused):
    _after_history_change("Redo")


@persistent
def _on_load(_unused):
    global _cache, _task, _snapshot, _observed_key, _failed_key, _last_started_key, _preview_iterator
    _cache = _task = _snapshot = _observed_key = _failed_key = None
    _preview_iterator = None
    _last_started_key = None
    _clear_display()


def register():
    for handlers, callback in _history_handlers():
        if callback not in handlers:
            handlers.append(callback)
    if _on_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_on_update)
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


def unregister():
    global _handler
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for handlers, callback in (*_history_handlers(), (bpy.app.handlers.depsgraph_update_post, _on_update), (bpy.app.handlers.load_post, _on_load)):
        if callback in handlers:
            handlers.remove(callback)
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
        _handler = None
    _remove_snapshot()
    _on_load(None)


def _history_handlers():
    return (
        (bpy.app.handlers.undo_pre, _before_history_change),
        (bpy.app.handlers.redo_pre, _before_history_change),
        (bpy.app.handlers.undo_post, _after_undo),
        (bpy.app.handlers.redo_post, _after_redo),
    )
