"""Explicit clearance checkpoints on a disposable master copy."""
import bpy
import time
from mathutils import Vector
from bpy.app.handlers import persistent
from ..background_worker import BackgroundTaskSequence
from ..object import Object
from ..mesh_decimation import get_direct_undercuts_target_reduction
from ..patron_lifecycle import create_simplified_reference_for_operation
from ..voxel_size import get_master_voxel_size
from ..modifiers import build_voxel_modifier
from .clear_undercuts import begin_clear_undercuts
from .direct_split_planes import direct_split_plane_specs, sync_direct_split_planes_with_scene
from .slip_casting_undercut_preview import _extraction_options, _preview_bottom_reference
from .dev_undercut_preview import master_for_preview, begin_preview, clear_preview, log_diagnostic, log_mesh_state

_session = None
STAGES = (
    "Create Simplified Reference",
    "Build Separate Clearance",
    "Join Clearance to Debug Master",
    "Remesh Debug Master",
    "Restore Bottom Plane",
    "Measure Remaining Undercuts",
)


def next_label():
    index = _session['stage'] if _session else 0
    return f"Step {index + 1}: {STAGES[index]}" if index < len(STAGES) else "Debug Complete — Reset to Restart"


def begin_inspection(context):
    target = None
    if _session is not None:
        # At the first checkpoint the reference is the visible analysis mesh.
        target = _session.get('reference') or _session.get('working')
    return begin_preview(context, source_object=target)


def can_advance():
    return _session is None or _session['stage'] < len(STAGES)


def _remove(obj):
    if obj is None:
        return
    try:
        mesh = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    except ReferenceError:
        pass


@persistent
def reset(*_args):
    global _session
    clear_preview()
    session, _session = _session, None
    if session is None:
        return
    for key in ('clearance', 'reference', 'working'):
        _remove(session.get(key))
    try:
        source = session['source']
        source.hide_set(session['source_hidden'])
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in session['selected']:
            try:
                obj.select_set(True)
            except ReferenceError:
                pass
        bpy.context.view_layer.objects.active = session['active']
    except (ReferenceError, RuntimeError):
        pass
    log_diagnostic("step debug reset: original master restored; debug objects removed")


def _show(obj, context):
    obj.hide_viewport = False
    obj.hide_set(False)
    for selected in context.selected_objects:
        selected.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def begin_next(context):
    def steps():
        global _session
        started = time.perf_counter()
        try:
            if _session is None:
                source = master_for_preview(context.scene)
                if source is None or source.mode != 'OBJECT':
                    raise ValueError('A master mesh in Object Mode is required')
                sync_direct_split_planes_with_scene()
                specs = direct_split_plane_specs()
                if not specs:
                    raise ValueError('Add a split plane before debugging clearance')
                _session = dict(stage=0, source=source, source_hidden=source.hide_get(),
                                selected=list(context.selected_objects), active=context.view_layer.objects.active,
                                scene=context.scene, specs=specs, options=_extraction_options(context.scene, specs),
                                quality=context.scene.master_quality)
                working = source.copy()
                working.data = source.data.copy()
                working.name = 'Dev Clearance Master'
                context.collection.objects.link(working)
                _session['working'] = working
                working.hide_render = True
                source.hide_set(True)
                _session['min_z'] = float(Object(working).min_z)
                _session['voxel_size'] = get_master_voxel_size(_session['quality'], source)
            session = _session
            if context.scene != session['scene'] or direct_split_plane_specs() != session['specs']:
                raise ValueError('Scene or split planes changed; reset and restart the debug steps')
            stage = session['stage']
            if stage >= len(STAGES):
                return 'Debug complete; reset to restart'
            working = session['working']
            clear_preview()
            log_diagnostic('step %d/%d started: %s voxel_size=%.6f smoothing=False',
                           stage + 1, len(STAGES), STAGES[stage], session['voxel_size'])
            if stage == 0:
                working.data.calc_loop_triangles()
                reduction = get_direct_undercuts_target_reduction(len(working.data.loop_triangles))
                if reduction is not None and reduction > 0:
                    reference = create_simplified_reference_for_operation(
                        Object(working), context, name='Dev Clearance Reference', target_reduction=reduction).object
                    session['reference'] = reference
                    reference.hide_render = True
                    working.hide_set(True)
                    _show(reference, context)
                    log_mesh_state('step simplified reference', reference)
                else:
                    _show(working, context)
                    log_diagnostic('step simplification skipped by existing size policy')
            elif stage == 1:
                # The shared builder deletes the analysis reference after consuming it.
                reference = session.get('reference')
                boundary = [] if len(session['specs']) == 1 else [_preview_bottom_reference(working)]
                from ...operators import DIRECT_UNDERCUT_CLEARANCE_BUILD_OVERTRAVEL
                result = yield begin_clear_undercuts(
                    target_object=Object(working), bidirectional=True,
                    temporary_analysis_object=Object(reference) if reference is not None else None,
                    voxel_size=session['voxel_size'], target_retry_voxel_size=session['voxel_size'],
                    split_plane_specs=session['specs'], boundary_plane_specs=boundary,
                    **session['options'], split_plane_overtravel_override=0.0,
                    clearance_build_overtravel_override=DIRECT_UNDERCUT_CLEARANCE_BUILD_OVERTRAVEL,
                    join_target=False, smooth_target_after_remesh=False,
                )
                session['reference'] = None
                _show(working, context)
                if result is not None:
                    session['clearance'] = result.object
                    result.object.name = 'Dev Separate Clearance'
                    result.object.hide_render = True
                    _show(result.object, context)
                    log_mesh_state('step separate clearance', result.object)
                else:
                    log_diagnostic('step build: no clearance geometry detected')
            elif stage == 2:
                clearance = session.get('clearance')
                if clearance is not None:
                    Object(working).join(Object(clearance))
                    session['clearance'] = None
                _show(working, context)
            elif stage == 3:
                if session.get('has_clearance', False):
                    Object(working).apply_modifier(build_voxel_modifier(session['voxel_size']))
                _show(working, context)
            elif stage == 4:
                target = Object(working)
                if session.get('has_clearance', False) and abs(float(target.min_z) - session['min_z']) > 1e-6:
                    center = target.center_coords
                    target.cut_plane(Vector((0, 0, -1)), Vector((center.x, center.y, session['min_z'])))
                    target.recalculate_normals()
                _show(working, context)
            elif stage == 5:
                remaining = yield begin_preview(context, source_object=working)
                log_diagnostic('step post-clearance result: remaining_affected_split_faces=%d', remaining)
            if stage == 1:
                session['has_clearance'] = session.get('clearance') is not None
            log_mesh_state(f'step {stage + 1} debug master', working)
            session['stage'] += 1
            log_diagnostic('step %d/%d completed: elapsed=%.3fs', stage + 1, len(STAGES), time.perf_counter() - started)
            return f'Completed: {STAGES[stage]}'
        except Exception as exc:
            log_diagnostic('step debug failed: %r', exc)
            reset()
            raise
    return BackgroundTaskSequence(steps())


def register():
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if reset not in handlers:
            handlers.append(reset)


def unregister():
    reset()
    for handlers in (bpy.app.handlers.load_pre, bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        if reset in handlers:
            handlers.remove(reset)
