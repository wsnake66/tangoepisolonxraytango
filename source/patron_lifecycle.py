import bpy  # type: ignore
from bpy.app.handlers import persistent  # type: ignore
import logging
import mathutils  # type: ignore
import time

from .components.preprocess import preprocess_patron
from .mesh_decimation import (
    create_fast_simplified_object,
    get_adaptive_target_reduction,
    get_adaptive_target_triangle_count,
)
from .modifiers import build_voxel_modifier
from .object import Object
from .patron_state import DECIMATED_PATRON_KEY, IMPORTED_VOLUME_ML_KEY
from .voxel_size import get_master_voxel_size
from .mold_types import is_multipart_type


MASTER_OBJECT_NAME = "master"
PATRON_OBJECT_NAME = "patron"
FALLBACK_REMESH_POLYGON_THRESHOLD = 1_000_000
FALLBACK_REMESH_VOXEL_MULTIPLIER = 2.0
logger = logging.getLogger(__name__)
SPLIT_PLANE_MARKER = "moldboxer_direct_split_plane"
_ORPHAN_CLEANUP_HANDLER_NAME = "_detect_orphaned_working_patron"
_orphan_cleanup_pending = False


def _set_hidden(obj, hidden: bool) -> None:
    obj.hide_set(hidden)
    obj.hide_viewport = hidden
    obj.hide_render = hidden


def _mark_decimated_patron(obj) -> None:
    obj[DECIMATED_PATRON_KEY] = True


def _clear_decimated_patron_mark(obj) -> None:
    if DECIMATED_PATRON_KEY in obj:
        del obj[DECIMATED_PATRON_KEY]


def _remove_object(obj) -> None:
    from .object import remove_objects_safely

    if obj is not None and obj.name in bpy.data.objects:
        remove_objects_safely((obj,))


def _mesh_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        return None
    return obj


def cleanup_orphaned_working_patron(scene=None) -> bool:
    """Remove a hidden build-time patron when it is the scene's last object."""
    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is None or not bool(patron.get(DECIMATED_PATRON_KEY, False)):
        return False

    try:
        hidden = bool(patron.hide_get())
    except (AttributeError, RuntimeError):
        hidden = False
    hidden = hidden or bool(getattr(patron, "hide_viewport", False))
    if not hidden:
        return False

    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    scene_objects = tuple(getattr(scene, "objects", ()))
    if len(scene_objects) != 1 or scene_objects[0] != patron:
        return False

    _remove_object(patron)
    logger.info("Removed orphaned hidden working patron")
    return True


def _cleanup_orphaned_working_patron_timer():
    global _orphan_cleanup_pending
    _orphan_cleanup_pending = False
    try:
        cleanup_orphaned_working_patron()
    except Exception:
        logger.exception("Could not clean up orphaned working patron")
    return None


@persistent
def _detect_orphaned_working_patron(scene, _depsgraph) -> None:
    global _orphan_cleanup_pending
    if _orphan_cleanup_pending:
        return

    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is None or not bool(patron.get(DECIMATED_PATRON_KEY, False)):
        return
    try:
        hidden = bool(patron.hide_get())
    except (AttributeError, RuntimeError):
        hidden = False
    if not hidden and not bool(getattr(patron, "hide_viewport", False)):
        return
    scene_objects = tuple(getattr(scene, "objects", ()))
    if len(scene_objects) != 1 or scene_objects[0] != patron:
        return

    _orphan_cleanup_pending = True
    bpy.app.timers.register(
        _cleanup_orphaned_working_patron_timer,
        first_interval=0.0,
    )


def _remove_orphan_cleanup_handlers() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == _ORPHAN_CLEANUP_HANDLER_NAME:
            handlers.remove(handler)


def register_orphaned_patron_cleanup() -> None:
    _remove_orphan_cleanup_handlers()
    bpy.app.handlers.depsgraph_update_post.append(_detect_orphaned_working_patron)


def unregister_orphaned_patron_cleanup() -> None:
    global _orphan_cleanup_pending
    _remove_orphan_cleanup_handlers()
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _cleanup_orphaned_working_patron_timer
    ):
        bpy.app.timers.unregister(_cleanup_orphaned_working_patron_timer)
    _orphan_cleanup_pending = False


def _create_patron_copy(master, collection):
    mesh = master.data.copy()
    mesh.name = f"{PATRON_OBJECT_NAME}_mesh"
    patron = bpy.data.objects.new(PATRON_OBJECT_NAME, mesh)
    patron.matrix_world = master.matrix_world.copy()
    collection.objects.link(patron)
    return patron


def _create_fallback_patron_object(master, collection):
    patron = _create_patron_copy(master, collection)
    polygon_count = len(patron.data.polygons)
    if polygon_count <= FALLBACK_REMESH_POLYGON_THRESHOLD:
        logger.info(
            "Prepared build-time patron copy from %s without fast simplification: "
            "polygons=%d",
            master.name,
            polygon_count,
        )
        return patron

    voxel_size = (
        get_master_voxel_size("FAST", Object(master))
        * FALLBACK_REMESH_VOXEL_MULTIPLIER
    )
    logger.info(
        "fast-simplification unavailable; remeshing fallback patron from %s: "
        "polygons=%d voxel_size=%.6f",
        master.name,
        polygon_count,
        voxel_size,
    )
    patron_obj = Object(patron)
    patron_obj.apply_modifier(build_voxel_modifier(voxel_size))
    patron_obj.cut_plane(
        mathutils.Vector((0, 0, -1)),
        mathutils.Vector((0, 0, Object(master).min_z + 0.3)),
    )
    patron.data.name = f"{PATRON_OBJECT_NAME}_mesh"
    return patron


def _create_adaptive_patron_object(
    master,
    collection,
    *,
    target_reduction=None,
):
    master.data.calc_loop_triangles()
    triangle_count = len(master.data.loop_triangles)
    if target_reduction is None:
        target_triangles = get_adaptive_target_triangle_count(triangle_count)
        target_reduction = get_adaptive_target_reduction(triangle_count)
    else:
        target_triangles = round(triangle_count * (1.0 - target_reduction))

    if (
        target_triangles is None
        or target_reduction is None
        or target_reduction <= 0.0
    ):
        patron = _create_patron_copy(master, collection)
        logger.info(
            "Prepared build-time patron copy from %s without fast simplification: "
            "triangles=%d",
            master.name,
            triangle_count,
        )
        return patron, False

    logger.info(
        "Preparing build-time simplified patron from %s: triangles=%d "
        "target_triangles=%d target_reduction=%.2f%%",
        master.name,
        triangle_count,
        target_triangles,
        target_reduction * 100.0,
    )
    patron = create_fast_simplified_object(
        master,
        collection,
        name=PATRON_OBJECT_NAME,
        target_reduction=target_reduction,
    )
    return patron, True


def remove_existing_master_patron(keep=None) -> None:
    # A Direct-mold project may contain an untouched hidden patron named
    # ``backup``. It must not survive a new import: Restart deliberately prefers
    # that object, which would otherwise replace the newly imported and oriented
    # patron at the end of finalization.
    for name in (PATRON_OBJECT_NAME, MASTER_OBJECT_NAME, "backup", "_slip_casting_restart_master"):
        obj = bpy.data.objects.get(name)
        if obj is not None and obj is not keep:
            _remove_object(obj)


def prepare_imported_patron(
    context,
    model: Object,
    *,
    name: str = PATRON_OBJECT_NAME,
    replace_existing: bool = True,
    center: bool = True,
):
    total_start = time.perf_counter()
    phase_start = total_start
    if replace_existing:
        remove_existing_master_patron(keep=model.object)
    cleanup_elapsed = time.perf_counter() - phase_start

    preprocess_start = time.perf_counter()
    phase_start = preprocess_start
    model.select()
    select_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    removed_loose_vertices = model.remove_loose_vertices()
    topology_inspection_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Imported model topology inspection completed: object=%s "
        "vertices=%d edges=%d polygons=%d removed_loose_vertices=%d "
        "select=%.3fs loose_vertex_cleanup=%.3fs",
        model.name,
        len(model.object.data.vertices),
        len(model.object.data.edges),
        len(model.object.data.polygons),
        removed_loose_vertices,
        select_elapsed,
        topology_inspection_elapsed,
    )

    phase_start = time.perf_counter()
    preprocess_patron(
        center=center,
        isolate=False,
        check_manifold=False,
        name=name,
    )
    final_preprocess_elapsed = time.perf_counter() - phase_start
    preprocess_elapsed = time.perf_counter() - preprocess_start

    phase_start = time.perf_counter()
    patron = bpy.context.view_layer.objects.active
    patron.name = name
    patron.data.name = f"{name}_mesh"
    _clear_decimated_patron_mark(patron)
    _set_hidden(patron, False)
    Object(patron).select()
    setup_elapsed = time.perf_counter() - phase_start

    logger.info(
        "Import patron setup completed: elapsed=%.3fs, cleanup=%.3fs, "
        "preprocess=%.3fs, setup=%.3fs; preprocess_detail: select=%.3fs, "
        "loose_vertex_cleanup=%.3fs, final_preprocess=%.3fs",
        time.perf_counter() - total_start,
        cleanup_elapsed,
        preprocess_elapsed,
        setup_elapsed,
        select_elapsed,
        topology_inspection_elapsed,
        final_preprocess_elapsed,
    )
    return patron


def prepare_decimated_patron_for_operation(context=None, target=None) -> bool:
    source = target.object if isinstance(target, Object) else target
    if source is None:
        source = bpy.context.view_layer.objects.active or bpy.context.object
    if source is not None and bool(source.get(SPLIT_PLANE_MARKER, False)):
        logger.warning(
            "Ignoring split-plane UI object %s as patron preprocessing target",
            source.name,
        )
        source = _mesh_object(PATRON_OBJECT_NAME) or _mesh_object(MASTER_OBJECT_NAME)
    if source is None or source.type != "MESH":
        source = _mesh_object(MASTER_OBJECT_NAME) or _mesh_object(PATRON_OBJECT_NAME)
    if source is None or source.type != "MESH":
        return False

    scene = context.scene if context is not None else bpy.context.scene
    if is_multipart_type(getattr(scene, "mold_type_preview", "")):
        # Box wrapping, prepared-part unions, plaster subtraction and base
        # assembly must all use the same full-resolution model. Undercut
        # analysis creates its own temporary simplified reference separately.
        patron = _mesh_object(PATRON_OBJECT_NAME)
        if patron is not None and bool(patron.get(DECIMATED_PATRON_KEY, False)):
            raise RuntimeError(
                "Rebuild the Slip Casting mold from the original model; "
                "this scene contains a legacy simplified working patron."
            )
        source = patron or source
        source.name = PATRON_OBJECT_NAME
        _clear_decimated_patron_mark(source)
        _set_hidden(source, False)
        Object(source).select()
        return True

    if source.name == PATRON_OBJECT_NAME and bool(source.get(DECIMATED_PATRON_KEY, False)):
        _set_hidden(source, False)
        Object(source).select()
        return True

    existing_patron = _mesh_object(PATRON_OBJECT_NAME)
    if existing_patron is not None and existing_patron is not source:
        _remove_object(existing_patron)

    if source.name == PATRON_OBJECT_NAME:
        source.name = MASTER_OBJECT_NAME
        source.data.name = f"{MASTER_OBJECT_NAME}_mesh"
        _clear_decimated_patron_mark(source)

    master = source
    if master.name != MASTER_OBJECT_NAME:
        master.name = MASTER_OBJECT_NAME
        master.data.name = f"{MASTER_OBJECT_NAME}_mesh"
        _clear_decimated_patron_mark(master)

    collection = (
        context.collection
        if context is not None and getattr(context, "collection", None) is not None
        else bpy.context.collection
    )
    start_time = time.perf_counter()
    simplified = False
    try:
        patron, simplified = _create_adaptive_patron_object(master, collection)
        _mark_decimated_patron(patron)
    except RuntimeError as exc:
        if "fast-simplification is not available" not in str(exc):
            raise
        patron = _create_fallback_patron_object(master, collection)
        _mark_decimated_patron(patron)
        if len(master.data.polygons) > FALLBACK_REMESH_POLYGON_THRESHOLD:
            simplified = True
    _set_hidden(master, False)
    _set_hidden(patron, False)
    Object(patron).select()
    logger.info(
        "Prepared build-time patron from %s in %.3fs: simplified=%s",
        master.name,
        time.perf_counter() - start_time,
        simplified,
    )
    return True


def create_simplified_reference_for_operation(
    source,
    context=None,
    name: str = "reference",
    *,
    target_reduction=None,
):
    """Create a temporary reference using the patron simplification path."""
    raw_source = source.object if isinstance(source, Object) else source
    if raw_source is None or raw_source.type != "MESH":
        raise ValueError("No mesh object available for reference simplification")

    collection = (
        context.collection
        if context is not None and getattr(context, "collection", None) is not None
        else bpy.context.collection
    )
    start_time = time.perf_counter()
    simplified = False
    try:
        reference, simplified = _create_adaptive_patron_object(
            raw_source,
            collection,
            target_reduction=target_reduction,
        )
        reference.name = name
        reference.data.name = f"{name}_mesh"
    except RuntimeError as exc:
        if "fast-simplification is not available" not in str(exc):
            raise
        reference = _create_fallback_patron_object(raw_source, collection)
        reference.name = name
        reference.data.name = f"{name}_mesh"
        if len(raw_source.data.polygons) > FALLBACK_REMESH_POLYGON_THRESHOLD:
            simplified = True

    _set_hidden(reference, False)
    logger.info(
        "Prepared temporary simplified reference from %s in %.3fs: "
        "reference=%s simplified=%s",
        raw_source.name,
        time.perf_counter() - start_time,
        reference.name,
        simplified,
    )
    return Object(reference)


def reveal_working_patron() -> None:
    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is not None:
        _set_hidden(patron, False)
        Object(patron).select()


def hide_working_patron() -> None:
    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is not None and bool(patron.get(DECIMATED_PATRON_KEY, False)):
        _set_hidden(patron, True)


def get_master_for_base_operations() -> Object:
    master = _mesh_object(MASTER_OBJECT_NAME)
    if master is not None:
        return Object(master)
    return Object(bpy.data.objects.get(PATRON_OBJECT_NAME))


def get_patron_for_base_pin_operations() -> Object:
    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is not None:
        return Object(patron)
    return get_master_for_base_operations()


def finalize_master_as_patron() -> None:
    master = _mesh_object(MASTER_OBJECT_NAME)
    patron = _mesh_object(PATRON_OBJECT_NAME)
    if patron is not None and bool(patron.get(DECIMATED_PATRON_KEY, False)):
        _remove_object(patron)
        patron = None
    if master is not None:
        _set_hidden(master, False)
        Object(master).select()
    elif patron is not None:
        _set_hidden(patron, False)
        Object(patron).select()
