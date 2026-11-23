"""On-demand, non-destructive inspection of the final master's undercuts."""
import bpy
import json
import logging
import time
from bpy.app.handlers import persistent

from ..background_worker import BackgroundTaskSequence
from ..object import Object
from ..operator_logs import log_background_event
from .clear_undercuts import begin_clear_undercuts, _mesh_from_worker_polygon_result, _mesh_triangle_indices
from .direct_split_planes import direct_split_plane_specs, sync_direct_split_planes_with_scene
from .slip_casting_undercut_preview import _extraction_options, _preview_bottom_reference
from ..mold_types import is_slip_casting_type

logger = logging.getLogger(__name__)


def log_diagnostic(message, *args):
    log_background_event(logger, "Dev undercuts: " + message, *args)


def log_mesh_state(label, source):
    if source is None:
        log_diagnostic("%s: no master mesh", label)
        return
    log_diagnostic(
        "%s: object=%s vertices=%d faces=%d dimensions=%s matrix_world=%s",
        label, source.name, len(source.data.vertices), len(source.data.polygons),
        tuple(float(v) for v in source.dimensions),
        [list(row) for row in source.matrix_world],
    )


def log_stored_paths(source, label):
    from .direct_mold import DIRECT_UNDERCUT_PATHS_OBJECT_KEY
    # Include the recorded plane/policy metadata: these paths may be stale and
    # are logged as evidence only, never substituted into the fresh preview.
    log_diagnostic("%s: stored_clearance_plan=%s", label,
                   source.get(DIRECT_UNDERCUT_PATHS_OBJECT_KEY, "none"))


_batch = None
_shader = None
_handler = None
_source = None
_scene = None
_specs = None


def master_for_preview(scene):
    for name in ("master", "patron"):
        obj = scene.objects.get(name)
        if obj is not None and obj.type == "MESH":
            return obj
    return None


def _redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


@persistent
def clear_preview(*_args):
    global _batch, _handler, _source, _scene, _specs
    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
    _batch = _handler = _source = _scene = _specs = None
    _redraw()


def _draw():
    if _batch is None or bpy.context.scene != _scene:
        return
    if not _source.visible_get() or direct_split_plane_specs() != _specs:
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


def _display(result, source, scene, specs):
    global _batch, _shader, _handler, _source, _scene, _specs
    clear_preview()
    if bpy.app.background or len(result.face_offsets) <= 1:
        return
    import gpu
    import numpy as np
    from gpu_extras.batch import batch_for_shader
    mesh = _mesh_from_worker_polygon_result("Dev undercut preview", result)
    try:
        positions = np.asarray(result.vertices).copy()
        normals = np.empty_like(positions)
        mesh.vertices.foreach_get("normal", normals.ravel())
        positions += normals * 0.015
        _shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        _batch = batch_for_shader(_shader, "TRIS", {"pos": positions}, indices=_mesh_triangle_indices(mesh))
        _source, _scene, _specs = source, scene, specs
        _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    finally:
        bpy.data.meshes.remove(mesh)
    _redraw()


def begin_preview(context, *, source_object=None):
    def steps():
        started = time.perf_counter()
        scene = context.scene
        source = source_object if source_object is not None else master_for_preview(scene)
        log_diagnostic("preview started: mode=%s master_quality=%s plan=fresh",
                       scene.mold_type_preview, getattr(scene, "master_quality", None))
        log_mesh_state("preview input", source)
        if source is None or source.mode != "OBJECT":
            log_diagnostic("preview rejected: no master mesh in Object Mode")
            raise ValueError("A master mesh in Object Mode is required")
        sync_direct_split_planes_with_scene()
        specs = direct_split_plane_specs()
        log_diagnostic("preview split_planes=%s", specs)
        log_stored_paths(source, "preview comparison")
        if not specs:
            log_diagnostic("preview rejected: no split planes")
            raise ValueError("Add a split plane before inspecting undercuts")
        clear_preview()
        snapshot = bpy.data.objects.new("Dev undercut snapshot", source.data.copy())
        snapshot.matrix_world = source.matrix_world.copy()
        faces = {}
        try:
            boundary = ([] if is_slip_casting_type(scene.mold_type_preview) and len(specs) == 1
                        else [_preview_bottom_reference(source)])
            options = _extraction_options(scene, specs)
            log_diagnostic("preview boundary_planes=%s options=%s", boundary, options)
            yield begin_clear_undercuts(
                target_object=Object(snapshot), bidirectional=True,
                split_plane_specs=specs, boundary_plane_specs=boundary,
                **options,
                split_plane_overtravel_override=0.0,
                planning_only=True, display_extraction_directions=False,
                preview_faces_out=faces,
            )
            count = len(faces["mesh"].face_offsets) - 1
            for path in faces.get("selected_paths", []):
                details = {key: path.get(key) for key in (
                    "section", "plane_index", "direction", "projection_plane_indices",
                    "path_sections", "affected_area", "swept_volume", "affected_faces",
                ) if key in path}
                log_diagnostic("preview selected_path=%s", json.dumps(details, default=str))
            _display(faces["mesh"], source, scene, specs)
            log_diagnostic(
                "preview completed: affected_split_faces=%d elapsed=%.3fs display=%s; "
                "face count is after plane splitting, not original mesh face count",
                count, time.perf_counter() - started,
                "headless" if bpy.app.background else ("red overlay" if count else "no undercuts"),
            )
            return count
        except Exception as exc:
            log_diagnostic("preview failed: elapsed=%.3fs error=%r", time.perf_counter() - started, exc)
            logger.exception("Dev undercuts preview traceback")
            raise
        finally:
            mesh = snapshot.data
            bpy.data.objects.remove(snapshot)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
    return BackgroundTaskSequence(steps())


@persistent
def _on_update(scene, depsgraph):
    if _source is not None:
        try:
            source_exists = scene.objects.get(_source.name) == _source
        except ReferenceError:
            source_exists = False
        if not source_exists:
            clear_preview()
            return
        for update in depsgraph.updates:
            if update.id == _source or update.id == _source.data:
                clear_preview()
                return


def register():
    for handlers, callback in _handlers():
        if callback not in handlers:
            handlers.append(callback)


def unregister():
    clear_preview()
    for handlers, callback in _handlers():
        if callback in handlers:
            handlers.remove(callback)


def _handlers():
    return ((bpy.app.handlers.load_pre, clear_preview),
            (bpy.app.handlers.undo_pre, clear_preview),
            (bpy.app.handlers.redo_pre, clear_preview),
            (bpy.app.handlers.depsgraph_update_post, _on_update))
