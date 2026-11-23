import logging
import time

import bpy  # type: ignore


logger = logging.getLogger(__name__)

_IMPORT_OPERATOR_IDS = {
    "IMPORT_MESH_OT_stl",
    "IMPORT_SCENE_OT_obj",
    "WM_OT_obj_import",
    "WM_OT_stl_import",
}
_PENDING_TIMEOUT_SECONDS = 1.5
_POLL_INTERVAL_SECONDS = 0.05

_known_object_pointers: set[int] = set()
_managed_object_pointers: set[int] = set()
_pending_objects: dict[int, object] = {}
_pending_deadline = 0.0
_last_import_operator_pointer = 0
_detected_import_callback = None
_timer_pending = False
_registration_pending = False


def _object_pointer(obj) -> int:
    return obj.as_pointer()


def mark_import_as_managed(obj) -> None:
    """Exclude objects imported through Moldboxer's own import operator."""
    pointer = _object_pointer(obj)
    _managed_object_pointers.add(pointer)
    _pending_objects.pop(pointer, None)


def _operator_id(operator) -> str:
    operator_id = str(getattr(operator, "bl_idname", "") or "")
    if operator_id:
        return operator_id

    bl_rna = getattr(operator, "bl_rna", None)
    return str(getattr(bl_rna, "identifier", "") or "")


def _latest_import_operator():
    window_manager = getattr(bpy.context, "window_manager", None)
    operators = getattr(window_manager, "operators", ()) if window_manager else ()
    for operator in reversed(tuple(operators)):
        if _operator_id(operator) in _IMPORT_OPERATOR_IDS:
            return operator

    active_operator = getattr(bpy.context, "active_operator", None)
    if _operator_id(active_operator) in _IMPORT_OPERATOR_IDS:
        return active_operator
    return None


def _operator_pointer(operator) -> int:
    if operator is None:
        return 0
    try:
        return operator.as_pointer()
    except Exception:
        return id(operator)


def _clear_pending() -> None:
    global _timer_pending
    _pending_objects.clear()
    _managed_object_pointers.clear()
    _timer_pending = False


def _process_pending_import():
    global _last_import_operator_pointer

    candidates = [
        obj
        for obj in tuple(bpy.data.objects)
        if (pointer := _object_pointer(obj)) in _pending_objects
        if pointer not in _managed_object_pointers
    ]
    if not candidates:
        _clear_pending()
        return None

    import_operator = _latest_import_operator()
    operator_pointer = _operator_pointer(import_operator)
    if (
        _detected_import_callback is not None
        and operator_pointer
        and operator_pointer != _last_import_operator_pointer
    ):
        _last_import_operator_pointer = operator_pointer
        active_object = getattr(bpy.context, "active_object", None)
        imported_object = (
            active_object if active_object in candidates else candidates[-1]
        )
        import_filepath = str(getattr(import_operator, "filepath", "") or "")
        _clear_pending()
        try:
            _detected_import_callback(imported_object, import_filepath)
        except Exception:
            logger.exception("Could not process detected STL/OBJ import")
        return None

    if time.monotonic() < _pending_deadline:
        return _POLL_INTERVAL_SECONDS

    _clear_pending()
    return None


def _schedule_pending_import_processing() -> None:
    global _pending_deadline, _timer_pending
    _pending_deadline = time.monotonic() + _PENDING_TIMEOUT_SECONDS
    if _timer_pending:
        return
    _timer_pending = True
    bpy.app.timers.register(
        _process_pending_import,
        first_interval=_POLL_INTERVAL_SECONDS,
    )


def _detect_new_mesh_objects(_scene, _depsgraph) -> None:
    current_objects = tuple(bpy.data.objects)
    current_pointers = {_object_pointer(obj) for obj in current_objects}
    new_objects = [
        obj
        for obj in current_objects
        if _object_pointer(obj) not in _known_object_pointers
        and getattr(obj, "type", None) == "MESH"
    ]

    _known_object_pointers.clear()
    _known_object_pointers.update(current_pointers)
    if not new_objects:
        return

    for obj in new_objects:
        pointer = _object_pointer(obj)
        if pointer not in _managed_object_pointers:
            _pending_objects[pointer] = obj
    if _pending_objects:
        _schedule_pending_import_processing()


def _remove_detection_handlers() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == "_detect_new_mesh_objects":
            handlers.remove(handler)


def _initialize_import_detection():
    global _last_import_operator_pointer, _registration_pending
    _registration_pending = False

    objects = getattr(bpy.data, "objects", None)
    if objects is None:
        _registration_pending = True
        return _POLL_INTERVAL_SECONDS

    _known_object_pointers.clear()
    _known_object_pointers.update(_object_pointer(obj) for obj in objects)
    _last_import_operator_pointer = _operator_pointer(_latest_import_operator())
    _remove_detection_handlers()
    bpy.app.handlers.depsgraph_update_post.append(_detect_new_mesh_objects)
    return None


def register_import_detection(callback) -> None:
    global _detected_import_callback, _registration_pending
    _detected_import_callback = callback
    _remove_detection_handlers()
    if _registration_pending:
        return
    _registration_pending = True
    bpy.app.timers.register(
        _initialize_import_detection,
        first_interval=0.0,
    )


def unregister_import_detection() -> None:
    global _detected_import_callback, _registration_pending
    _remove_detection_handlers()
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_initialize_import_detection):
        bpy.app.timers.unregister(_initialize_import_detection)
    if callable(is_registered) and is_registered(_process_pending_import):
        bpy.app.timers.unregister(_process_pending_import)
    _known_object_pointers.clear()
    _clear_pending()
    _detected_import_callback = None
    _registration_pending = False
