"""Editable viewport guide for funnel reference height settings."""

from dataclasses import dataclass

import bpy  # type: ignore
import mathutils  # type: ignore
from bpy.app.handlers import persistent  # type: ignore

from ..materials import get_or_create_simple_material
from ..mold_types import mold_type_uses_reference_guides, resolve_direct_mold_opening

FUNNEL_REFERENCE_LINE_NAME = "funnel_reference_height_guide"
FUNNEL_REFERENCE_LINE_MARKER = "moldboxer_funnel_reference_height_guide"
FUNNEL_REFERENCE_LINE_MODE_KEY = "moldboxer_funnel_reference_height_mode"
FUNNEL_EXTENSION_LINE_MARKER = "moldboxer_funnel_extension_height_guide"
FUNNEL_REFERENCE_GUIDES_OVERLAY_HIDDEN_KEY = (
    "_moldboxer_funnel_reference_guides_overlay_hidden"
)
GUIDE_MATERIAL_NAME = "MB_FunnelGuides"
GUIDE_MATERIAL_HEX = "#49FF83FF"

_MODE_PROPERTY = {
    "silicone": "funneler_ref_height",
    "direct": "direct_funnel_reference_height",
}
_SYNC_PENDING = False
_REQUESTED_MODE = "silicone"
_UPDATING = False
_EPSILON = 1e-5
_LAST_GUIDE_STATE = {}
INNER_CAVITY_FUNNEL_EXTRA_EXTENSION = 5.0


def effective_silicone_funneler_offset(scene) -> float:
    extension = max(float(getattr(scene, "funneler_offset", 0.0)), 0.0)
    if bool(getattr(scene, "pro_inner_cavity", False)):
        extension += INNER_CAVITY_FUNNEL_EXTRA_EXTENSION
    return extension


@dataclass(frozen=True)
class _PatronBounds:
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def depth(self) -> float:
        return self.max_y - self.min_y

    @property
    def height(self) -> float:
        return self.max_z - self.min_z


def _patron():
    objects = getattr(bpy.data, "objects", None)
    if objects is None:
        return None
    raw = objects.get("patron") or objects.get("master")
    if raw is None or getattr(raw, "type", None) != "MESH":
        return None
    # Object.world_cords_bound_box selects its wrapped object, which is not
    # allowed while Blender is drawing a panel. Compute the same world-space
    # bounds directly without mutating selection or any other Blender state.
    world_corners = [
        raw.matrix_world @ mathutils.Vector(corner) for corner in raw.bound_box
    ]
    return _PatronBounds(
        min_x=min(corner.x for corner in world_corners),
        max_x=max(corner.x for corner in world_corners),
        min_y=min(corner.y for corner in world_corners),
        max_y=max(corner.y for corner in world_corners),
        min_z=min(corner.z for corner in world_corners),
        max_z=max(corner.z for corner in world_corners),
    )


def _guide_object(marker=FUNNEL_REFERENCE_LINE_MARKER):
    for obj in getattr(bpy.data, "objects", ()):
        if bool(getattr(obj, "get", lambda *_: False)(marker)):
            return obj
    return None


def _scene_has_box_object() -> bool:
    return any(
        "box" in str(getattr(obj, "name", "")).casefold()
        for obj in getattr(bpy.data, "objects", ())
    )


def reference_guides_overlay_hidden(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(
        scene is not None
        and scene.get(FUNNEL_REFERENCE_GUIDES_OVERLAY_HIDDEN_KEY, False)
    )


def _reference_guides_should_be_hidden(scene=None) -> bool:
    return _scene_has_box_object() or reference_guides_overlay_hidden(scene)


def _set_guide_hidden(obj, hidden: bool) -> None:
    try:
        if bool(obj.hide_get()) != hidden:
            obj.hide_set(hidden)
    except Exception:
        pass
    if bool(getattr(obj, "hide_viewport", False)) != hidden:
        obj.hide_viewport = hidden


def set_reference_guides_overlay_visible(visible: bool, scene=None) -> None:
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return
    scene[FUNNEL_REFERENCE_GUIDES_OVERLAY_HIDDEN_KEY] = not bool(visible)
    _remove_guide(FUNNEL_EXTENSION_LINE_MARKER)
    hidden = _reference_guides_should_be_hidden(scene)
    obj = _guide_object(FUNNEL_REFERENCE_LINE_MARKER)
    if obj is not None:
        _set_guide_hidden(obj, hidden)


def _object_pointer(obj):
    try:
        return obj.as_pointer()
    except Exception:
        return id(obj)


def _remember_guide_z(obj) -> None:
    _LAST_GUIDE_STATE[_object_pointer(obj)] = float(obj.location.z)


def _cached_guide_z(obj):
    return _LAST_GUIDE_STATE.get(_object_pointer(obj))


def _remove_guide(marker=FUNNEL_REFERENCE_LINE_MARKER) -> None:
    obj = _guide_object(marker)
    if obj is None:
        return
    pointer = _object_pointer(obj)
    curve = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if curve is not None and getattr(curve, "users", 0) == 0:
        bpy.data.curves.remove(curve)
    _LAST_GUIDE_STATE.pop(pointer, None)


def _remove_guides() -> None:
    _remove_guide()
    _remove_guide(FUNNEL_EXTENSION_LINE_MARKER)


def _mode_is_visible(scene, mode: str) -> bool:
    if not mold_type_uses_reference_guides(
        getattr(scene, "mold_type_preview", "")
    ):
        return False
    if mode == "direct":
        return (
            resolve_direct_mold_opening(
                getattr(scene, "mold_type_preview", ""),
                getattr(scene, "direct_mold_opening", "base_open"),
            )
            == "top_funnel"
        )
    return mode == "silicone"


def _reference_z(scene, patron, mode: str) -> float:
    prop_name = _MODE_PROPERTY[mode]
    percentage = min(max(float(getattr(scene, prop_name)), 1.0), 99.0)
    return patron.min_z + percentage * patron.height / 100.0


def _line_dimensions(patron) -> tuple[float, float, float]:
    size = max(patron.width, patron.depth, patron.height, 1.0)
    padding = size * 0.08
    return patron.min_y - padding, patron.max_y + padding, size * 0.002


def _close(left: float, right: float) -> bool:
    left = float(left)
    right = float(right)
    tolerance = max(_EPSILON, max(abs(left), abs(right)) * 1e-6)
    return abs(left - right) <= tolerance


def _vector_close(vector, values) -> bool:
    return all(_close(vector[index], value) for index, value in enumerate(values))


def _set_line_points(obj, patron) -> None:
    min_y, max_y, bevel_depth = _line_dimensions(patron)
    spline = obj.data.splines[0]
    first_point = (0.0, min_y, 0.0, 1.0)
    second_point = (0.0, max_y, 0.0, 1.0)
    if not _vector_close(spline.points[0].co, first_point):
        spline.points[0].co = first_point
    if not _vector_close(spline.points[1].co, second_point):
        spline.points[1].co = second_point
    if not _close(obj.data.bevel_depth, bevel_depth):
        obj.data.bevel_depth = bevel_depth


def _apply_guide_style(obj) -> None:
    material = get_or_create_simple_material(
        GUIDE_MATERIAL_NAME,
        GUIDE_MATERIAL_HEX,
        metallic=0.0,
        roughness=0.5,
    )
    obj.color = material.diffuse_color
    materials = obj.data.materials
    if len(materials) != 1 or materials[0] != material:
        materials.clear()
        materials.append(material)


def _guide_has_material(obj) -> bool:
    materials = getattr(getattr(obj, "data", None), "materials", ())
    return len(materials) == 1 and materials[0].name == GUIDE_MATERIAL_NAME


def _guide_needs_panel_sync(scene, patron, mode: str) -> bool:
    obj = _guide_object()
    extension_obj = _guide_object(FUNNEL_EXTENSION_LINE_MARKER)
    should_exist = patron is not None and _mode_is_visible(scene, mode)
    if not should_exist:
        return obj is not None or extension_obj is not None
    if obj is None or str(obj.get(FUNNEL_REFERENCE_LINE_MODE_KEY, "")) != mode:
        return True
    # Old files may still contain the retired funnel-extension guide. Schedule
    # a sync so it is removed as soon as the settings panel is drawn.
    if extension_obj is not None:
        return True
    if not _guide_has_material(obj):
        return True
    expected_hidden = _reference_guides_should_be_hidden(scene)
    if bool(getattr(obj, "hide_viewport", False)) != expected_hidden:
        return True
    if len(obj.data.splines) != 1 or len(obj.data.splines[0].points) != 2:
        return True
    min_y, max_y, bevel_depth = _line_dimensions(patron)
    return (
        not _vector_close(obj.data.splines[0].points[0].co, (0.0, min_y, 0.0, 1.0))
        or not _vector_close(
            obj.data.splines[0].points[1].co, (0.0, max_y, 0.0, 1.0)
        )
        or not _close(obj.data.bevel_depth, bevel_depth)
    )


def _create_guide(
    patron,
    mode: str,
    *,
    name=FUNNEL_REFERENCE_LINE_NAME,
    marker=FUNNEL_REFERENCE_LINE_MARKER,
):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_resolution = 0
    spline = curve.splines.new("POLY")
    spline.points.add(1)

    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj[marker] = True
    obj[FUNNEL_REFERENCE_LINE_MODE_KEY] = mode
    _apply_guide_style(obj)
    obj.show_in_front = True
    obj.hide_render = True
    obj.lock_location = (True, True, False)
    obj.lock_rotation = (True, True, True)
    obj.lock_scale = (True, True, True)
    _set_line_points(obj, patron)
    return obj


def sync_funnel_reference_line(mode: str | None = None) -> None:
    """Create/update the guide for the requested product settings panel."""
    global _REQUESTED_MODE, _UPDATING
    if mode in _MODE_PROPERTY:
        _REQUESTED_MODE = mode
    mode = _REQUESTED_MODE
    scene = getattr(bpy.context, "scene", None)
    patron = _patron()
    if scene is None or patron is None or not _mode_is_visible(scene, mode):
        _remove_guides()
        return

    # The extension value remains editable in the panel, but its separate
    # viewport reference line is intentionally no longer displayed.
    _remove_guide(FUNNEL_EXTENSION_LINE_MARKER)

    _UPDATING = True
    try:
        obj = _guide_object()
        if obj is None:
            obj = _create_guide(patron, mode)
        if obj.name != FUNNEL_REFERENCE_LINE_NAME:
            obj.name = FUNNEL_REFERENCE_LINE_NAME
        if obj.data.name != FUNNEL_REFERENCE_LINE_NAME:
            obj.data.name = FUNNEL_REFERENCE_LINE_NAME
        if str(obj.get(FUNNEL_REFERENCE_LINE_MODE_KEY, "")) != mode:
            obj[FUNNEL_REFERENCE_LINE_MODE_KEY] = mode
        _apply_guide_style(obj)
        _set_line_points(obj, patron)
        target_location = (0.0, 0.0, _reference_z(scene, patron, mode))
        if not _vector_close(obj.location, target_location):
            obj.location = target_location
        if not _vector_close(obj.rotation_euler, (0.0, 0.0, 0.0)):
            obj.rotation_euler = (0.0, 0.0, 0.0)
        if not _vector_close(obj.scale, (1.0, 1.0, 1.0)):
            obj.scale = (1.0, 1.0, 1.0)
        _set_guide_hidden(obj, _reference_guides_should_be_hidden(scene))
        _remember_guide_z(obj)
    finally:
        _UPDATING = False


def update_funnel_reference_line_from_property(scene, prop_name: str) -> None:
    """Move the existing guide when its corresponding percentage changes."""
    if _UPDATING:
        return
    if not _mode_is_visible(scene, "silicone"):
        _remove_guides()
        return
    obj = _guide_object()
    if obj is None:
        return
    _set_guide_hidden(obj, _reference_guides_should_be_hidden(scene))
    mode = str(obj.get(FUNNEL_REFERENCE_LINE_MODE_KEY, ""))
    if _MODE_PROPERTY.get(mode) != prop_name:
        return
    patron = _patron()
    if patron is None:
        return
    target_z = _reference_z(scene, patron, mode)
    if not _close(obj.location.z, target_z):
        obj.location.z = target_z
    _remember_guide_z(obj)


def _sync_timer():
    global _SYNC_PENDING
    try:
        sync_funnel_reference_line()
    finally:
        _SYNC_PENDING = False
    return None


def schedule_funnel_reference_line_sync(mode: str) -> None:
    global _REQUESTED_MODE, _SYNC_PENDING
    if mode not in _MODE_PROPERTY:
        return
    _REQUESTED_MODE = mode
    scene = getattr(bpy.context, "scene", None)
    patron = _patron()
    if scene is None or _SYNC_PENDING:
        return
    if not _guide_needs_panel_sync(scene, patron, mode):
        return
    _SYNC_PENDING = True
    try:
        bpy.app.timers.register(_sync_timer, first_interval=0.0)
    except Exception:
        _SYNC_PENDING = False
        sync_funnel_reference_line()


@persistent
def _sync_property_from_moved_line(scene, _depsgraph) -> None:
    """Convert user-edited guide Z positions back into their scene settings."""
    global _UPDATING
    if _UPDATING:
        return
    # Retire the extension guide globally, including in mold modes that do not
    # draw or schedule the remaining funnel-start reference guide.
    _remove_guide(FUNNEL_EXTENSION_LINE_MARKER)
    obj = _guide_object()
    if obj is None:
        return
    mode = str(obj.get(FUNNEL_REFERENCE_LINE_MODE_KEY, ""))
    if not _mode_is_visible(scene, mode):
        _remove_guides()
        return
    guides_hidden = _reference_guides_should_be_hidden(scene)
    _set_guide_hidden(obj, guides_hidden)
    if guides_hidden:
        _remember_guide_z(obj)
        return
    prop_name = _MODE_PROPERTY.get(mode)
    patron = _patron()
    if prop_name is None or patron is None or scene is None or patron.height <= 1e-9:
        return
    cached_z = _cached_guide_z(obj)
    if cached_z is None:
        _remember_guide_z(obj)
        return
    if _close(obj.location.z, cached_z):
        # The guide did not move. If the patron bounds changed, keep the scene
        # percentage stable and move the guide to its new derived world Z.
        target_z = _reference_z(scene, patron, mode)
        if not _close(obj.location.z, target_z):
            _UPDATING = True
            try:
                obj.location.z = target_z
                _remember_guide_z(obj)
            finally:
                _UPDATING = False
        return

    _UPDATING = True
    try:
        percentage = (float(obj.location.z) - patron.min_z) * 100.0 / patron.height
        percentage = min(max(percentage, 1.0), 99.0)
        target_location = (
            0.0,
            0.0,
            patron.min_z + percentage * patron.height / 100.0,
        )
        if not _vector_close(obj.location, target_location):
            obj.location = target_location
        if not _vector_close(obj.rotation_euler, (0.0, 0.0, 0.0)):
            obj.rotation_euler = (0.0, 0.0, 0.0)
        if not _vector_close(obj.scale, (1.0, 1.0, 1.0)):
            obj.scale = (1.0, 1.0, 1.0)
        if abs(float(getattr(scene, prop_name)) - percentage) > 1e-5:
            setattr(scene, prop_name, percentage)
        # A property guard may reject the requested percentage (for example on
        # the Lite tier), so always finish at the value the scene accepted.
        effective_percentage = float(getattr(scene, prop_name))
        effective_z = patron.min_z + effective_percentage * patron.height / 100.0
        if not _close(obj.location.z, effective_z):
            obj.location.z = effective_z
        _remember_guide_z(obj)
    finally:
        _UPDATING = False


def _remove_sync_handlers() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == "_sync_property_from_moved_line":
            handlers.remove(handler)


def register_funnel_reference_line() -> None:
    _remove_sync_handlers()
    bpy.app.handlers.depsgraph_update_post.append(_sync_property_from_moved_line)
    # Blender exposes bpy.data as _RestrictData while add-ons register, so do
    # not inspect scene objects here. The first panel/depsgraph sync initializes
    # the guide cache after normal data access has been restored.


def unregister_funnel_reference_line() -> None:
    _remove_sync_handlers()
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_sync_timer):
        bpy.app.timers.unregister(_sync_timer)
    _remove_guides()
