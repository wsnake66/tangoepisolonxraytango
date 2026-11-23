import json
import logging
import math
from contextlib import contextmanager

import bpy  # type: ignore
import mathutils  # type: ignore
from bpy.app.handlers import persistent  # type: ignore

from ..bl_utils import ensure_moldboxer_transform_gizmos_for_selection
from ..materials import get_or_create_simple_material, assign_material
from ..mold_types import is_direct_mold_type, is_multipart_type, is_slip_casting_type
from ..object import Object, remove_objects_safely
from ..primitives import create_plane_primitive
from ..split_specs import replace_planar_specs_with_organic
from .box_parts import (
    is_fixed_two_part_split_plane,
    mold_type_uses_split_planes,
    set_split_plane_transform_lock,
)
from .direct_split_execution import (
    split_object_by_direct_plane_specs,
)

logger = logging.getLogger(__name__)

DIRECT_SPLIT_PLANE_PREFIX = "direct_split_plane"
DIRECT_SPLIT_PLANE_MARKER = "moldboxer_direct_split_plane"
DIRECT_SPLIT_PLANE_AXIS_KEY = "moldboxer_direct_split_axis"
DIRECT_SPLIT_PLANE_INDEX_KEY = "moldboxer_direct_split_index"
DIRECT_SPLIT_PLANE_CONTOUR_MARKER = "moldboxer_direct_split_plane_contour"
DIRECT_SPLIT_PLANE_CONTOUR_VERSION_KEY = "moldboxer_direct_split_plane_contour_version"
DIRECT_SPLIT_PLANE_CONTOUR_VERSION = 2
SKIN_MASTER_HALF_PREVIEW_MODIFIER_NAME = "skin_master_half_preview"
DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY = "_moldboxer_direct_split_plane_ui_hidden"
DIRECT_SPLIT_PLANES_OVERLAY_HIDDEN_KEY = (
    "_moldboxer_direct_split_planes_overlay_hidden"
)
SKIN_BASE_REFERENCE_GUIDE_NAME = "skin_base_reference_height_guide"
SKIN_BASE_REFERENCE_GUIDE_MARKER = "moldboxer_skin_base_reference_guide"
FOUNDATION_GUIDE_ACTIVE_SCENE_KEY = "_moldboxer_foundation_guide_active"
FOUNDATION_THRESHOLD_ANGLE_SCENE_KEY = (
    "moldboxer_foundation_threshold_angle_degrees"
)
FOUNDATION_TARGET_OBJECT_SCENE_KEY = "moldboxer_foundation_target_object"
SKIN_BASE_REFERENCE_MIN_Z_KEY = "moldboxer_skin_base_reference_min_z"
SKIN_BASE_REFERENCE_HEIGHT_KEY = "moldboxer_skin_base_reference_height"
SKIN_BASE_REFERENCE_GUIDE_MATERIAL = "MB_SkinBaseReference"
SKIN_BASE_REFERENCE_GUIDE_CONTOUR_MATERIAL = "MB_SkinBaseReferenceContour"
SKIN_BASE_REFERENCE_GUIDE_COLOR = "#EFCA5B66"
SKIN_BASE_REFERENCE_GUIDE_CONTOUR_COLOR = "#EFCA5BFF"
SKIN_BASE_REFERENCE_GUIDE_SEGMENTS = 64
SILICONE_SPLIT_PLANES_PAYLOAD_KEY = "_moldboxer_silicone_split_planes"
SILICONE_KEEP_SPLIT_PLANES_KEY = "_moldboxer_keep_silicone_split_planes"

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
_AXIS_SCENE_PROPERTY = {
    "x": "direct_split_y",
    "y": "direct_split_x",
    "z": "direct_split_z",
}
_AXIS_NORMALS = {
    "x": mathutils.Vector((1.0, 0.0, 0.0)),
    "y": mathutils.Vector((0.0, 1.0, 0.0)),
    "z": mathutils.Vector((0.0, 0.0, 1.0)),
}
_AXIS_COLORS = {
    "x": "#40D96B44",
    "y": "#FF1F1F44",
    "z": "#4F86FF44",
}
DIRECT_SPLIT_DEFAULTS = {
    "direct_split_x": 0,
    "direct_split_y": 1,
    "direct_split_z": 0,
}
_SYNC_PENDING = False
_PANEL_MODE_BY_REGION: dict[int, str] = {}
_DEFAULT_RESET_PENDING = False
_DEFAULT_RESET_SCENE = None
_OPTIMIZED_BASE_SPLIT_SYNC_PENDING = False
_OPTIMIZED_BASE_SPLIT_HANDLER_NAME = "_detect_optimized_base_split_rotation"
_SPLIT_PLANE_COUNT_HANDLER_NAME = "_sync_split_plane_counts_from_objects"
_SPLIT_PLANE_OBJECT_IDS_BY_SCENE: dict[int, dict[str, tuple[int, ...]]] = {}
_SPLIT_PLANE_SYNC_SUSPEND_DEPTH = 0
_SPLIT_PLANE_PREPARATION_DEPTH = 0
_SKIN_BASE_REFERENCE_HANDLER_NAME = "_sync_skin_base_reference_from_transform"
_OPTIMIZED_BASE_Y_SPLIT_PROPERTY = "direct_split_y"
_OPTIMIZED_BASE_Y_PLANE_GROUP = "x"
_SKIN_BASE_REFERENCE_UPDATING = False
_SKIN_BASE_REFERENCE_LAST_Z: dict[int, float] = {}


def _split_count_for_axis(scene, axis: str) -> int:
    # Horizontal splits are temporarily unavailable for slip casting.
    if axis == "z" and is_multipart_type(
        getattr(scene, "mold_type_preview", "")
    ):
        return 0
    return max(0, int(getattr(scene, _AXIS_SCENE_PROPERTY[axis], 0)))


def _optimized_base_split_guard_applies(scene) -> bool:
    return (
        getattr(scene, "base_type", "classic") == "optimized"
        and getattr(scene, "mold_type_preview", "") != "FIXTURE"
        and getattr(scene, "mold_type_preview", "") != "PROTECTIVE_SHELL"
        and not is_direct_mold_type(getattr(scene, "mold_type_preview", ""))
    )


def _object_name_contains_box_word(obj) -> bool:
    name_parts = [
        part
        for part in obj.name.casefold().replace(".", "_").replace("-", "_").split("_")
        if part
    ]
    return "box" in name_parts


def _box_object_exists() -> bool:
    return any(
        obj.type == "MESH"
        and (
            _object_name_contains_box_word(obj)
            or bool(
                getattr(obj, "get", lambda *_args: False)(
                    "moldboxer_protective_shell",
                    False,
                )
            )
        )
        and not _is_direct_split_plane(obj)
        for obj in bpy.data.objects
    )


def _master_object():
    for name in ("patron", "master"):
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.type == "MESH":
            return obj
    for obj in bpy.context.selected_objects:
        if (
            obj.type == "MESH"
            and not _is_direct_split_plane(obj)
            and not bool(obj.get(SKIN_BASE_REFERENCE_GUIDE_MARKER, False))
        ):
            return obj
    return None


def _object_world_bounds(obj) -> tuple[mathutils.Vector, mathutils.Vector]:
    if obj is None:
        return (
            mathutils.Vector((-10.0, -10.0, -10.0)),
            mathutils.Vector((10.0, 10.0, 10.0)),
        )
    world_corners = [
        obj.matrix_world @ mathutils.Vector(corner)
        for corner in obj.bound_box
    ]
    return (
        mathutils.Vector(
            tuple(min(corner[axis] for corner in world_corners) for axis in range(3))
        ),
        mathutils.Vector(
            tuple(max(corner[axis] for corner in world_corners) for axis in range(3))
        ),
    )


def _master_bounds() -> tuple[mathutils.Vector, mathutils.Vector]:
    master = _master_object()
    if master is None:
        return _object_world_bounds(None)
    bounds_source = master
    scene = getattr(bpy.context, "scene", None)
    preview_modifier = getattr(master, "modifiers", None)
    preview_modifier = (
        preview_modifier.get(SKIN_MASTER_HALF_PREVIEW_MODIFIER_NAME)
        if preview_modifier is not None
        else None
    )
    if (
        scene is not None
        and getattr(scene, "mold_type_preview", "") == "DIRECT_MOLD_SKIN"
        and preview_modifier is not None
    ):
        full_patron = bpy.data.objects.get("backup")
        if full_patron is not None and full_patron.type == "MESH":
            bounds_source = full_patron

    return _object_world_bounds(bounds_source)


def _is_direct_split_plane(obj) -> bool:
    return bool(getattr(obj, "get", lambda *_: False)(DIRECT_SPLIT_PLANE_MARKER))


def _is_direct_split_plane_contour(obj) -> bool:
    return bool(
        getattr(obj, "get", lambda *_: False)(DIRECT_SPLIT_PLANE_CONTOUR_MARKER)
    )


def direct_split_plane_ui_hidden(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(
        scene is not None and scene.get(DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY, False)
    )


def keep_silicone_split_planes_after_build(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(
        scene is not None and scene.get(SILICONE_KEEP_SPLIT_PLANES_KEY, False)
    )


def set_keep_silicone_split_planes_after_build(
    keep: bool,
    scene=None,
) -> None:
    scene = scene or bpy.context.scene
    scene[SILICONE_KEEP_SPLIT_PLANES_KEY] = bool(keep)


def _box_blocks_split_plane_ui() -> bool:
    return _box_object_exists() and not keep_silicone_split_planes_after_build()


def _mold_type_blocks_split_plane_ui(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return scene is not None and not mold_type_uses_split_planes(scene)


def _split_plane_ui_blocked(scene=None) -> bool:
    return (
        direct_split_plane_ui_hidden(scene)
        or _box_blocks_split_plane_ui()
        or _mold_type_blocks_split_plane_ui(scene)
    )


def iter_direct_split_plane_objects(axis: str | None = None):
    normalized_axis = axis.lower() if axis else None
    planes = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and _is_direct_split_plane(obj)
        and (
            normalized_axis is None
            or obj.get(DIRECT_SPLIT_PLANE_AXIS_KEY) == normalized_axis
        )
    ]
    return sorted(
        planes,
        key=lambda obj: (
            str(obj.get(DIRECT_SPLIT_PLANE_AXIS_KEY, "")),
            int(obj.get(DIRECT_SPLIT_PLANE_INDEX_KEY, 0)),
            obj.name,
        ),
    )


def _scene_pointer(scene) -> int:
    try:
        return int(scene.as_pointer())
    except Exception:
        return id(scene)


def _object_pointer(obj) -> int:
    try:
        return int(obj.as_pointer())
    except Exception:
        return id(obj)


def _scene_direct_split_plane_objects(scene, axis: str):
    return [
        obj
        for obj in iter_direct_split_plane_objects(axis)
        if obj.name in scene.objects
    ]


def _direct_split_plane_object_ids(scene) -> dict[str, tuple[int, ...]]:
    return {
        axis: tuple(
            _object_pointer(obj)
            for obj in _scene_direct_split_plane_objects(scene, axis)
        )
        for axis in ("x", "y", "z")
    }


def _remember_direct_split_plane_objects(scene=None) -> None:
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return
    _SPLIT_PLANE_OBJECT_IDS_BY_SCENE[_scene_pointer(scene)] = (
        _direct_split_plane_object_ids(scene)
    )


@contextmanager
def preserve_direct_split_counts(scene=None):
    """Do not interpret programmatic plane cleanup as a viewport deletion."""
    global _SPLIT_PLANE_SYNC_SUSPEND_DEPTH
    scene = scene or bpy.context.scene
    _SPLIT_PLANE_SYNC_SUSPEND_DEPTH += 1
    try:
        yield
    finally:
        _SPLIT_PLANE_SYNC_SUSPEND_DEPTH -= 1
        _remember_direct_split_plane_objects(scene)


@contextmanager
def preserve_direct_split_planes_during_preparation(scene=None):
    """Keep UI sync from deleting guides when temporary box meshes appear."""
    global _SPLIT_PLANE_PREPARATION_DEPTH
    _SPLIT_PLANE_PREPARATION_DEPTH += 1
    try:
        with preserve_direct_split_counts(scene):
            yield
    finally:
        _SPLIT_PLANE_PREPARATION_DEPTH -= 1


def _remove_orphaned_direct_split_plane_contours(scene) -> None:
    stale_contours = [
        obj
        for obj in tuple(scene.objects)
        if _is_direct_split_plane_contour(obj)
        and not _is_direct_split_plane(getattr(obj, "parent", None))
    ]
    if stale_contours:
        remove_objects_safely(stale_contours)


def direct_split_planes_overlay_hidden(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(
        scene is not None
        and scene.get(DIRECT_SPLIT_PLANES_OVERLAY_HIDDEN_KEY, False)
    )


def _set_direct_split_plane_hidden(obj, hidden: bool) -> None:
    try:
        if bool(obj.hide_get()) != hidden:
            obj.hide_set(hidden)
    except Exception:
        pass
    if bool(getattr(obj, "hide_viewport", False)) != hidden:
        obj.hide_viewport = hidden
    for child in getattr(obj, "children", ()):
        if _is_direct_split_plane_contour(child):
            _set_direct_split_plane_hidden(child, hidden)


def set_direct_split_planes_overlay_visible(visible: bool, scene=None) -> None:
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return
    hidden = not bool(visible)
    scene[DIRECT_SPLIT_PLANES_OVERLAY_HIDDEN_KEY] = hidden
    for plane in iter_direct_split_plane_objects():
        _set_direct_split_plane_hidden(plane, hidden)
    guide = skin_base_reference_guide_object()
    if guide is not None:
        _set_direct_split_plane_hidden(guide, hidden)


@preserve_direct_split_counts()
def remove_direct_split_planes(axis: str | None = None) -> None:
    for obj in list(iter_direct_split_plane_objects(axis)):
        _remove_direct_split_plane_object(obj)


def _remove_direct_split_plane_object(obj) -> None:
    children = [child for child in getattr(obj, "children", ())
                if _is_direct_split_plane_contour(child)]
    remove_objects_safely((*children, obj))


def _plane_material(axis: str):
    material = get_or_create_simple_material(
        f"MB_DirectSplitPlane_{axis.upper()}",
        _AXIS_COLORS[axis],
        0.0,
        0.35,
    )
    node_tree = getattr(material, "node_tree", None)
    if node_tree is not None:
        for node in node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            alpha_input = node.inputs.get("Alpha")
            if alpha_input is not None:
                alpha_input.default_value = material.diffuse_color[3]
            break

    for attr_name, value in (
        ("blend_method", "BLEND"),
        ("surface_render_method", "BLENDED"),
        ("show_transparent_back", True),
        ("use_screen_refraction", False),
    ):
        if hasattr(material, attr_name):
            try:
                setattr(material, attr_name, value)
            except Exception:
                pass
    return material


def _contour_material(axis: str):
    material = get_or_create_simple_material(
        f"MB_DirectSplitPlaneContour_{axis.upper()}",
        _AXIS_COLORS[axis][:7] + "FF",
        0.0,
        0.2,
    )
    if hasattr(material, "blend_method"):
        try:
            material.blend_method = "OPAQUE"
        except Exception:
            pass
    return material


def skin_base_reference_guide_object():
    for obj in getattr(bpy.data, "objects", ()):
        if bool(
            getattr(obj, "get", lambda *_: False)(
                SKIN_BASE_REFERENCE_GUIDE_MARKER
            )
        ):
            return obj
    return None


def _skin_base_reference_pointer(obj) -> int:
    try:
        return int(obj.as_pointer())
    except Exception:
        return id(obj)


def _remember_skin_base_reference_z(obj) -> None:
    _SKIN_BASE_REFERENCE_LAST_Z[_skin_base_reference_pointer(obj)] = float(
        obj.location.z
    )


def _cached_skin_base_reference_z(obj):
    return _SKIN_BASE_REFERENCE_LAST_Z.get(_skin_base_reference_pointer(obj))


def _store_skin_base_reference_frame(obj, min_corner, max_corner) -> None:
    """Keep the patron height used when this guide was first created."""
    obj[SKIN_BASE_REFERENCE_MIN_Z_KEY] = float(min_corner.z)
    obj[SKIN_BASE_REFERENCE_HEIGHT_KEY] = float(max_corner.z - min_corner.z)


def _skin_base_reference_frame(obj):
    try:
        min_z = float(obj[SKIN_BASE_REFERENCE_MIN_Z_KEY])
        height = float(obj[SKIN_BASE_REFERENCE_HEIGHT_KEY])
    except (KeyError, TypeError, ValueError):
        return None
    if height <= 1e-9:
        return None
    return min_z, height


def remove_skin_base_reference_guide() -> None:
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and FOUNDATION_GUIDE_ACTIVE_SCENE_KEY in scene:
        del scene[FOUNDATION_GUIDE_ACTIVE_SCENE_KEY]
    if scene is not None and FOUNDATION_TARGET_OBJECT_SCENE_KEY in scene:
        del scene[FOUNDATION_TARGET_OBJECT_SCENE_KEY]
    guide = skin_base_reference_guide_object()
    if guide is None:
        return
    pointer = _skin_base_reference_pointer(guide)
    mesh = getattr(guide, "data", None)
    bpy.data.objects.remove(guide, do_unlink=True)
    if mesh is not None and getattr(mesh, "users", 0) == 0:
        bpy.data.meshes.remove(mesh)
    _SKIN_BASE_REFERENCE_LAST_Z.pop(pointer, None)


def _skin_base_reference_should_exist(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    foundation_active = bool(
        scene is not None
        and scene.get(FOUNDATION_GUIDE_ACTIVE_SCENE_KEY, False)
    )
    target = (
        foundation_reference_target_object(scene)
        if foundation_active
        else _master_object()
    )
    return bool(
        scene is not None
        and (
            foundation_active
            or (
                getattr(scene, "mold_type_preview", "") == "DIRECT_MOLD_SKIN"
                and not mold_type_uses_split_planes(scene)
            )
        )
        and target is not None
        and not direct_split_plane_ui_hidden(scene)
        and not _box_object_exists()
    )


def foundation_reference_guide_active(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    return bool(
        scene is not None
        and scene.get(FOUNDATION_GUIDE_ACTIVE_SCENE_KEY, False)
        and foundation_reference_target_object(scene) is not None
        and skin_base_reference_guide_object() is not None
    )


def foundation_reference_target_object(scene=None):
    """Return the master or selected sealer targeted by Foundation."""
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is not None and scene.get(FOUNDATION_GUIDE_ACTIVE_SCENE_KEY, False):
        target_name = str(scene.get(FOUNDATION_TARGET_OBJECT_SCENE_KEY, ""))
        target = bpy.data.objects.get(target_name) if target_name else None
        if target is not None and target.type == "MESH":
            return target
        return None
    return _master_object()


def foundation_reference_guide_available(scene=None, *, target=None) -> bool:
    """Return whether Foundation can start in the current generator state."""
    scene = scene or getattr(bpy.context, "scene", None)
    target = target or _master_object()
    return bool(
        scene is not None
        and getattr(scene, "mold_type_preview", "") != "DIRECT_MOLD_SKIN"
        and target is not None
        and getattr(target, "type", None) == "MESH"
        and not _box_object_exists()
        and not direct_split_plane_ui_hidden(scene)
        and not foundation_reference_guide_active(scene)
    )


def foundation_threshold_angle_degrees(scene=None) -> float:
    scene = scene or getattr(bpy.context, "scene", None)
    if scene is None:
        return 35.0
    return min(
        max(
            float(scene.get(FOUNDATION_THRESHOLD_ANGLE_SCENE_KEY, 35.0)),
            0.0,
        ),
        90.0,
    )


def begin_foundation_reference_guide(
    scene=None,
    *,
    target=None,
    angle_threshold_degrees: float = 35.0,
):
    """Create and select the movable base-reference circle for Foundation."""
    scene = scene or getattr(bpy.context, "scene", None)
    target = target or _master_object()
    if not foundation_reference_guide_available(scene, target=target):
        raise RuntimeError(
            "Foundation is not available in the current generator state"
        )
    scene[FOUNDATION_THRESHOLD_ANGLE_SCENE_KEY] = min(
        max(float(angle_threshold_degrees), 0.0),
        90.0,
    )
    scene[FOUNDATION_TARGET_OBJECT_SCENE_KEY] = target.name
    scene[FOUNDATION_GUIDE_ACTIVE_SCENE_KEY] = True
    sync_skin_base_reference_guide(scene)
    guide = skin_base_reference_guide_object()
    if guide is None:
        del scene[FOUNDATION_GUIDE_ACTIVE_SCENE_KEY]
        del scene[FOUNDATION_TARGET_OBJECT_SCENE_KEY]
        raise RuntimeError("Could not create the Foundation base-reference guide")
    for obj in tuple(getattr(bpy.context, "selected_objects", ())):
        obj.select_set(False)
    guide.hide_set(False)
    guide.hide_viewport = False
    guide.select_set(True)
    bpy.context.view_layer.objects.active = guide
    return guide


def _skin_base_reference_location(scene, min_corner, max_corner):
    percentage = min(
        max(float(getattr(scene, "skin_base_reference_height", 25.0)), 1.0),
        99.0,
    )
    center = (min_corner + max_corner) / 2.0
    return mathutils.Vector(
        (
            center.x,
            center.y,
            min_corner.z + (max_corner.z - min_corner.z) * percentage / 100.0,
        )
    )


def _skin_base_reference_radius(
    min_corner: mathutils.Vector,
    max_corner: mathutils.Vector,
) -> float:
    return max(max(max_corner - min_corner), 1.0) * 1.35 / 2.0


def _configure_transparent_material(material) -> None:
    node_tree = getattr(material, "node_tree", None)
    if node_tree is not None:
        for node in node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            alpha_input = node.inputs.get("Alpha")
            if alpha_input is not None:
                alpha_input.default_value = material.diffuse_color[3]
            break
    for attr_name, value in (
        ("blend_method", "BLEND"),
        ("surface_render_method", "BLENDED"),
        ("show_transparent_back", True),
        ("use_screen_refraction", False),
    ):
        if hasattr(material, attr_name):
            try:
                setattr(material, attr_name, value)
            except Exception:
                pass


def _skin_base_reference_materials():
    fill = get_or_create_simple_material(
        SKIN_BASE_REFERENCE_GUIDE_MATERIAL,
        SKIN_BASE_REFERENCE_GUIDE_COLOR,
        0.0,
        0.35,
    )
    _configure_transparent_material(fill)
    contour = get_or_create_simple_material(
        SKIN_BASE_REFERENCE_GUIDE_CONTOUR_MATERIAL,
        SKIN_BASE_REFERENCE_GUIDE_CONTOUR_COLOR,
        0.0,
        0.2,
    )
    if hasattr(contour, "blend_method"):
        try:
            contour.blend_method = "OPAQUE"
        except Exception:
            pass
    return fill, contour


def _create_skin_base_reference_mesh():
    segment_count = SKIN_BASE_REFERENCE_GUIDE_SEGMENTS
    inner_radius = 0.96
    vertices = [(0.0, 0.0, 0.0)]
    vertices.extend(
        (
            inner_radius * math.cos(math.tau * index / segment_count),
            inner_radius * math.sin(math.tau * index / segment_count),
            0.0,
        )
        for index in range(segment_count)
    )
    vertices.extend(
        (
            math.cos(math.tau * index / segment_count),
            math.sin(math.tau * index / segment_count),
            0.002,
        )
        for index in range(segment_count)
    )
    fill_faces = []
    contour_faces = []
    inner_start = 1
    outer_start = inner_start + segment_count
    for index in range(segment_count):
        next_index = (index + 1) % segment_count
        inner = inner_start + index
        next_inner = inner_start + next_index
        outer = outer_start + index
        next_outer = outer_start + next_index
        fill_faces.append((0, inner, next_inner))
        contour_faces.append((inner, outer, next_outer, next_inner))

    mesh = bpy.data.meshes.new(SKIN_BASE_REFERENCE_GUIDE_NAME)
    mesh.from_pydata(vertices, [], [*fill_faces, *contour_faces])
    mesh.update()
    for polygon in mesh.polygons[segment_count:]:
        polygon.material_index = 1
    return mesh


def _apply_skin_base_reference_style(obj) -> None:
    fill, contour = _skin_base_reference_materials()
    materials = obj.data.materials
    if (
        len(materials) != 2
        or materials[0] != fill
        or materials[1] != contour
    ):
        materials.clear()
        materials.append(fill)
        materials.append(contour)
    obj.color = fill.diffuse_color
    obj.display_type = "TEXTURED"
    obj.show_in_front = False
    obj.hide_render = True


def _create_skin_base_reference_guide():
    guide = bpy.data.objects.new(
        SKIN_BASE_REFERENCE_GUIDE_NAME,
        _create_skin_base_reference_mesh(),
    )
    bpy.context.collection.objects.link(guide)
    guide[SKIN_BASE_REFERENCE_GUIDE_MARKER] = True
    guide.lock_location = (True, True, False)
    guide.lock_rotation = (True, True, True)
    guide.lock_scale = (True, True, True)
    _apply_skin_base_reference_style(guide)
    return guide


def _skin_base_reference_has_materials(obj) -> bool:
    materials = getattr(getattr(obj, "data", None), "materials", ())
    return bool(
        len(materials) == 2
        and materials[0].name == SKIN_BASE_REFERENCE_GUIDE_MATERIAL
        and materials[1].name == SKIN_BASE_REFERENCE_GUIDE_CONTOUR_MATERIAL
    )


def _skin_base_reference_needs_sync(scene=None) -> bool:
    scene = scene or getattr(bpy.context, "scene", None)
    guide = skin_base_reference_guide_object()
    should_exist = _skin_base_reference_should_exist(scene)
    if not should_exist:
        return guide is not None
    if guide is None or not _skin_base_reference_has_materials(guide):
        return True
    if _skin_base_reference_frame(guide) is None:
        return True
    expected_hidden = direct_split_planes_overlay_hidden(scene)
    return bool(getattr(guide, "hide_viewport", False)) != expected_hidden


def _close_float(left: float, right: float) -> bool:
    left = float(left)
    right = float(right)
    tolerance = max(1e-5, max(abs(left), abs(right)) * 1e-6)
    return abs(left - right) <= tolerance


def _sync_skin_base_reference_property_from_guide(scene, guide) -> None:
    global _SKIN_BASE_REFERENCE_UPDATING
    if _SKIN_BASE_REFERENCE_UPDATING:
        return
    cached_z = _cached_skin_base_reference_z(guide)
    if cached_z is None:
        _remember_skin_base_reference_z(guide)
        return
    if _close_float(guide.location.z, cached_z):
        return
    frame = _skin_base_reference_frame(guide)
    if frame is None:
        return
    min_z, height = frame

    _SKIN_BASE_REFERENCE_UPDATING = True
    try:
        percentage = (float(guide.location.z) - min_z) * 100.0 / height
        percentage = min(max(percentage, 1.0), 99.0)
        if not _close_float(
            getattr(scene, "skin_base_reference_height", 25.0),
            percentage,
        ):
            scene.skin_base_reference_height = percentage
        effective_percentage = min(
            max(float(getattr(scene, "skin_base_reference_height", 25.0)), 1.0),
            99.0,
        )
        guide.location.z = min_z + height * effective_percentage / 100.0
        _remember_skin_base_reference_z(guide)
    finally:
        _SKIN_BASE_REFERENCE_UPDATING = False


def sync_skin_base_reference_guide(scene=None) -> None:
    global _SKIN_BASE_REFERENCE_UPDATING
    scene = scene or getattr(bpy.context, "scene", None)
    if not _skin_base_reference_should_exist(scene):
        remove_skin_base_reference_guide()
        return
    guide = skin_base_reference_guide_object()
    needs_initial_frame = guide is None
    if guide is None:
        guide = _create_skin_base_reference_guide()
    elif _skin_base_reference_frame(guide) is None:
        needs_initial_frame = True
    else:
        _sync_skin_base_reference_property_from_guide(scene, guide)

    _SKIN_BASE_REFERENCE_UPDATING = True
    try:
        guide.name = SKIN_BASE_REFERENCE_GUIDE_NAME
        guide.data.name = SKIN_BASE_REFERENCE_GUIDE_NAME
        guide[SKIN_BASE_REFERENCE_GUIDE_MARKER] = True
        _apply_skin_base_reference_style(guide)
        if needs_initial_frame:
            if scene.get(FOUNDATION_GUIDE_ACTIVE_SCENE_KEY, False):
                min_corner, max_corner = _object_world_bounds(
                    foundation_reference_target_object(scene)
                )
            else:
                min_corner, max_corner = _master_bounds()
            radius = _skin_base_reference_radius(min_corner, max_corner)
            _store_skin_base_reference_frame(guide, min_corner, max_corner)
            guide.location = _skin_base_reference_location(
                scene,
                min_corner,
                max_corner,
            )
            guide.rotation_euler = (0.0, 0.0, 0.0)
            guide.scale = (radius, radius, 1.0)
        guide.lock_location = (True, True, False)
        guide.lock_rotation = (False, False, False)
        guide.lock_scale = (True, True, True)
        _set_direct_split_plane_hidden(
            guide,
            direct_split_planes_overlay_hidden(scene),
        )
        _remember_skin_base_reference_z(guide)
    finally:
        _SKIN_BASE_REFERENCE_UPDATING = False


def update_skin_base_reference_height_from_property(scene) -> None:
    if _SKIN_BASE_REFERENCE_UPDATING:
        return
    guide = skin_base_reference_guide_object()
    if guide is None:
        return
    frame = _skin_base_reference_frame(guide)
    if frame is None:
        return
    min_z, height = frame
    percentage = min(
        max(float(getattr(scene, "skin_base_reference_height", 25.0)), 1.0),
        99.0,
    )
    guide.location.z = min_z + height * percentage / 100.0
    _remember_skin_base_reference_z(guide)


def _plane_size(min_corner: mathutils.Vector, max_corner: mathutils.Vector) -> float:
    dimensions = max_corner - min_corner
    return max(max(dimensions), 1.0) * 1.35


def _is_verticalish_plane(obj) -> bool:
    """Treat a plane as verticalish while its normal is more horizontal than Z."""
    normal = _plane_normal(obj)
    horizontal_length_squared = normal.x * normal.x + normal.y * normal.y
    return horizontal_length_squared >= normal.z * normal.z


def _configure_plane_object(
    obj,
    *,
    axis: str,
    index: int,
    count: int,
    min_corner: mathutils.Vector,
    max_corner: mathutils.Vector,
) -> None:
    obj.name = f"{DIRECT_SPLIT_PLANE_PREFIX}_{axis}_{index:02d}"
    obj.data.name = obj.name
    obj[DIRECT_SPLIT_PLANE_MARKER] = True
    obj[DIRECT_SPLIT_PLANE_AXIS_KEY] = axis
    obj[DIRECT_SPLIT_PLANE_INDEX_KEY] = index
    _apply_plane_visual_style(obj, axis)
    _ensure_plane_contour(obj, axis)
    _apply_plane_editability(obj, axis, index)
    _set_direct_split_plane_hidden(obj, direct_split_planes_overlay_hidden())
    _reset_direct_split_plane_transform(
        obj,
        axis=axis,
        index=index,
        count=count,
        min_corner=min_corner,
        max_corner=max_corner,
    )


def _radial_split_planes():
    return [
        plane for plane in iter_direct_split_plane_objects()
        if plane.name in bpy.context.scene.objects
        and plane.get(DIRECT_SPLIT_PLANE_AXIS_KEY) in {"x", "y"}
        and not plane.get("moldboxer_organic_plane", False)
    ]


def _redistribute_radial_split_planes():
    """Evenly space radial rotations when their count changes."""
    bpy.context.view_layer.update()
    planes = _radial_split_planes()
    if not planes:
        return
    normal = _plane_normal(planes[0])
    start = math.atan2(normal.y, normal.x)
    step = math.pi / len(planes)
    for index, plane in enumerate(planes):
        if is_fixed_two_part_split_plane(
            bpy.context.scene,
            plane.get(DIRECT_SPLIT_PLANE_AXIS_KEY),
            plane.get(DIRECT_SPLIT_PLANE_INDEX_KEY),
        ):
            continue
        angle = start + index * step
        normal = mathutils.Vector((math.cos(angle), math.sin(angle), 0.0))
        plane.rotation_euler = normal.to_track_quat("Z", "Y").to_euler()
    bpy.context.view_layer.update()


def _reset_direct_split_plane_transform(
    obj,
    *,
    axis: str,
    index: int,
    count: int,
    min_corner: mathutils.Vector,
    max_corner: mathutils.Vector,
) -> None:
    """Initialize a radial or horizontal split plane."""
    axis_idx = _AXIS_INDEX[axis]
    fraction = index / (count + 1)
    location = (min_corner + max_corner) / 2.0
    location[axis_idx] = (
        min_corner[axis_idx]
        + (max_corner[axis_idx] - min_corner[axis_idx]) * fraction
    )
    normal = _AXIS_NORMALS[axis]
    if axis in {"x", "y"}:
        location = (min_corner + max_corner) / 2.0
        normal = _AXIS_NORMALS["x"]
        bpy.context.view_layer.update()
        existing = [plane for plane in _radial_split_planes() if plane != obj]
        if existing:
            location = existing[0].matrix_world.translation.copy()
            normal = _plane_normal(existing[0])
    size = _plane_size(min_corner, max_corner)
    obj.location = location
    obj.rotation_euler = normal.to_track_quat(
        "Z",
        "Y",
    ).to_euler()
    obj.scale = (size / 2.0, size / 2.0, 1.0)


def _apply_plane_visual_style(obj, axis: str) -> None:
    obj.display_type = "TEXTURED"
    obj.show_in_front = False
    material = _plane_material(axis)
    obj.color = material.diffuse_color
    assign_material(obj, material)


def _apply_plane_editability(obj, axis: str, index: int, scene=None) -> None:
    scene = scene or bpy.context.scene
    locked = is_fixed_two_part_split_plane(scene, axis, index)
    if locked:
        min_corner, max_corner = _master_bounds()
        center = (min_corner + max_corner) / 2.0
        size = _plane_size(min_corner, max_corner)
        obj.location = center
        obj.rotation_euler = _AXIS_NORMALS[axis].to_track_quat(
            "Z",
            "Y",
        ).to_euler()
        obj.scale = (size / 2.0, size / 2.0, 1.0)

    set_split_plane_transform_lock(obj, locked)


def _plane_editability_needs_sync(
    obj,
    axis: str,
    index: int,
    scene=None,
) -> bool:
    scene = scene or bpy.context.scene
    locked = is_fixed_two_part_split_plane(scene, axis, index)
    expected = (locked, locked, locked)
    return bool(
        bool(obj.hide_select) != locked
        or tuple(obj.lock_location) != expected
        or tuple(obj.lock_rotation) != expected
        or tuple(obj.lock_scale) != expected
    )


def _plane_contour_name(obj) -> str:
    return f"{obj.name}_contour"


def _create_plane_contour_curve(obj, axis: str):
    mesh = bpy.data.meshes.new(_plane_contour_name(obj))
    thickness = 0.04
    z_offset = 0.035
    verts = (
        (-1.0, -1.0, z_offset),
        (1.0, -1.0, z_offset),
        (1.0, -1.0 + thickness, z_offset),
        (-1.0, -1.0 + thickness, z_offset),
        (1.0 - thickness, -1.0, z_offset),
        (1.0, -1.0, z_offset),
        (1.0, 1.0, z_offset),
        (1.0 - thickness, 1.0, z_offset),
        (-1.0, 1.0 - thickness, z_offset),
        (1.0, 1.0 - thickness, z_offset),
        (1.0, 1.0, z_offset),
        (-1.0, 1.0, z_offset),
        (-1.0, -1.0, z_offset),
        (-1.0 + thickness, -1.0, z_offset),
        (-1.0 + thickness, 1.0, z_offset),
        (-1.0, 1.0, z_offset),
    )
    faces = ((0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11), (12, 13, 14, 15))
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    contour = bpy.data.objects.new(_plane_contour_name(obj), mesh)
    bpy.context.collection.objects.link(contour)
    contour[DIRECT_SPLIT_PLANE_CONTOUR_MARKER] = True
    contour[DIRECT_SPLIT_PLANE_CONTOUR_VERSION_KEY] = DIRECT_SPLIT_PLANE_CONTOUR_VERSION
    contour.hide_select = True
    contour.display_type = "TEXTURED"
    contour.parent = obj
    contour.matrix_parent_inverse.identity()
    contour.location = (0.0, 0.0, 0.0)
    contour.rotation_euler = (0.0, 0.0, 0.0)
    contour.scale = (1.0, 1.0, 1.0)
    contour.show_in_front = False
    material = _contour_material(axis)
    contour.color = material.diffuse_color
    contour.data.materials.append(material)
    return contour


def _ensure_plane_contour(obj, axis: str) -> None:
    contour = None
    for child in getattr(obj, "children", ()):
        if _is_direct_split_plane_contour(child):
            contour = child
            break
    if contour is None:
        _create_plane_contour_curve(obj, axis)
        return
    if (
        not getattr(getattr(contour, "data", None), "polygons", None)
        or int(contour.get(DIRECT_SPLIT_PLANE_CONTOUR_VERSION_KEY, 0))
        != DIRECT_SPLIT_PLANE_CONTOUR_VERSION
    ):
        remove_objects_safely((contour,))
        _create_plane_contour_curve(obj, axis)
        return

    contour.name = _plane_contour_name(obj)
    contour.data.name = contour.name
    contour.hide_select = True
    contour.display_type = "TEXTURED"
    contour.parent = obj
    contour.location = (0.0, 0.0, 0.0)
    contour.rotation_euler = (0.0, 0.0, 0.0)
    contour.scale = (1.0, 1.0, 1.0)
    material = _contour_material(axis)
    contour.color = material.diffuse_color
    contour.data.materials.clear()
    contour.data.materials.append(material)


@preserve_direct_split_counts()
def rebuild_direct_split_planes_for_axis(axis: str) -> None:
    axis = axis.lower()
    if axis not in _AXIS_INDEX:
        return
    if _split_plane_ui_blocked():
        remove_direct_split_planes(axis)
        return

    scene = bpy.context.scene
    count = _split_count_for_axis(scene, axis)
    existing_planes = list(iter_direct_split_plane_objects(axis))
    count_changed = len(existing_planes) != count

    # Preserve user-edited objects during reconciliation. Radial rotations are
    # redistributed only when the count changes, never during routine UI sync.
    for plane in reversed(existing_planes[count:]):
        _remove_direct_split_plane_object(plane)
    existing_planes = existing_planes[:count]

    for index, plane in enumerate(existing_planes, start=1):
        plane[DIRECT_SPLIT_PLANE_AXIS_KEY] = axis
        plane[DIRECT_SPLIT_PLANE_INDEX_KEY] = index
        _apply_plane_visual_style(plane, axis)
        _ensure_plane_contour(plane, axis)
        _apply_plane_editability(plane, axis, index, scene)
        _set_direct_split_plane_hidden(
            plane,
            direct_split_planes_overlay_hidden(scene),
        )

    if len(existing_planes) >= count:
        if count_changed and axis in {"x", "y"}:
            _redistribute_radial_split_planes()
        ensure_moldboxer_transform_gizmos_for_selection(bpy.context)
        return

    min_corner, max_corner = _master_bounds()

    for index in range(len(existing_planes) + 1, count + 1):
        plane = create_plane_primitive()
        if plane is None:
            continue
        _configure_plane_object(
            plane,
            axis=axis,
            index=index,
            count=count,
            min_corner=min_corner,
            max_corner=max_corner,
        )

    if count_changed and axis in {"x", "y"}:
        _redistribute_radial_split_planes()

    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    ensure_moldboxer_transform_gizmos_for_selection(bpy.context)


def rebuild_all_direct_split_planes() -> None:
    for axis in ("x", "y", "z"):
        rebuild_direct_split_planes_for_axis(axis)


def ensure_optimized_base_vertical_split_plane(scene=None) -> bool:
    """Keep the optimized base backed by a real, editable vertical split plane."""
    scene = scene or getattr(bpy.context, "scene", None)
    if (
        scene is None
        or not _optimized_base_split_guard_applies(scene)
        or _split_plane_ui_blocked(scene)
    ):
        return False

    requested_count = max(
        0,
        int(getattr(scene, _OPTIMIZED_BASE_Y_SPLIT_PROPERTY, 0)),
    )
    if requested_count < 1:
        setattr(scene, _OPTIMIZED_BASE_Y_SPLIT_PROPERTY, 1)
        return True

    if (
        len(iter_direct_split_plane_objects(_OPTIMIZED_BASE_Y_PLANE_GROUP))
        != requested_count
    ):
        rebuild_direct_split_planes_for_axis(_OPTIMIZED_BASE_Y_PLANE_GROUP)

    # Newly created or interactively rotated objects may not have their latest
    # Euler transform reflected in matrix_world until the view layer updates.
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    planes = list(iter_direct_split_plane_objects())
    if any(_is_verticalish_plane(plane) for plane in planes):
        return False

    # Preserve the plane the user rotated. Add a new Y box split and then
    # explicitly make that new plane centered and Y-normal; ordinary count
    # reconciliation distributes new planes across the master bounds.
    existing_group_planes = list(
        iter_direct_split_plane_objects(_OPTIMIZED_BASE_Y_PLANE_GROUP)
    )
    setattr(scene, _OPTIMIZED_BASE_Y_SPLIT_PROPERTY, requested_count + 1)
    updated_group_planes = list(
        iter_direct_split_plane_objects(_OPTIMIZED_BASE_Y_PLANE_GROUP)
    )
    new_planes = [
        plane for plane in updated_group_planes if plane not in existing_group_planes
    ]
    if not new_planes:
        rebuild_direct_split_planes_for_axis(_OPTIMIZED_BASE_Y_PLANE_GROUP)
        updated_group_planes = list(
            iter_direct_split_plane_objects(_OPTIMIZED_BASE_Y_PLANE_GROUP)
        )
        new_planes = [
            plane
            for plane in updated_group_planes
            if plane not in existing_group_planes
        ]
    if not new_planes:
        return True

    min_corner, max_corner = _master_bounds()
    center = (min_corner + max_corner) / 2.0
    size = _plane_size(min_corner, max_corner)
    new_plane = new_planes[-1]
    new_plane.location = center
    new_plane.rotation_euler = _AXIS_NORMALS["y"].to_track_quat(
        "Z",
        "Y",
    ).to_euler()
    new_plane.scale = (size / 2.0, size / 2.0, 1.0)
    _ensure_plane_contour(new_plane, _OPTIMIZED_BASE_Y_PLANE_GROUP)
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    logger.info(
        "Added centered Y-normal split plane %s required by optimized base",
        new_plane.name,
    )
    return True


def center_direct_split_planes(context) -> int:
    """Give editable planar splits a common pivot at the master bounds center."""
    min_corner, max_corner = _master_bounds()
    center = (min_corner + max_corner) / 2.0
    planes = [
        obj for obj in iter_direct_split_plane_objects()
        if obj.name in context.scene.objects
        and not obj.get("moldboxer_organic_plane", False)
        and not all(obj.lock_location)
    ]
    for obj in planes:
        transform = obj.matrix_world.copy()
        transform.translation = center
        obj.matrix_world = transform
    context.view_layer.update()
    return len(planes)


@preserve_direct_split_counts()
def reset_direct_split_planes() -> None:
    """Recreate every Direct split plane from the current master bounds."""
    remove_direct_split_planes()
    rebuild_all_direct_split_planes()


@preserve_direct_split_counts()
def reset_direct_split_planes_to_defaults(scene=None) -> None:
    """Restore the default split counts and recreate their editable planes."""
    scene = scene or bpy.context.scene
    defaults = dict(DIRECT_SPLIT_DEFAULTS)
    if is_slip_casting_type(getattr(scene, "mold_type_preview", "")):
        defaults["direct_split_y"] = 2
    for prop_name, value in defaults.items():
        setattr(scene, prop_name, value)
    reset_direct_split_planes()


def _direct_split_planes_need_sync() -> bool:
    if _SPLIT_PLANE_PREPARATION_DEPTH:
        return False
    if _skin_base_reference_needs_sync():
        return True
    planes = iter_direct_split_plane_objects()
    if _split_plane_ui_blocked():
        return bool(planes)

    scene = bpy.context.scene
    if (
        _optimized_base_split_guard_applies(scene)
        and not _split_plane_ui_blocked(scene)
        and (
            int(getattr(scene, _OPTIMIZED_BASE_Y_SPLIT_PROPERTY, 0)) < 1
            or not any(
                _is_verticalish_plane(plane)
                for plane in iter_direct_split_plane_objects()
            )
        )
    ):
        return True

    for axis in ("x", "y", "z"):
        expected_count = _split_count_for_axis(scene, axis)
        axis_planes = iter_direct_split_plane_objects(axis)
        if len(axis_planes) != expected_count:
            return True
        for index, plane in enumerate(axis_planes, start=1):
            if _plane_editability_needs_sync(plane, axis, index, scene):
                return True
            contours = [
                child
                for child in getattr(plane, "children", ())
                if _is_direct_split_plane_contour(child)
            ]
            if len(contours) != 1:
                return True
            contour = contours[0]
            if (
                not getattr(getattr(contour, "data", None), "polygons", None)
                or int(contour.get(DIRECT_SPLIT_PLANE_CONTOUR_VERSION_KEY, 0))
                != DIRECT_SPLIT_PLANE_CONTOUR_VERSION
            ):
                return True
    return False


def sync_direct_split_planes_with_scene() -> None:
    if _SPLIT_PLANE_PREPARATION_DEPTH:
        return
    sync_skin_base_reference_guide()
    if _split_plane_ui_blocked():
        remove_direct_split_planes()
        return

    scene = bpy.context.scene
    for axis in ("x", "y", "z"):
        expected_count = _split_count_for_axis(scene, axis)
        current_count = len(iter_direct_split_plane_objects(axis))
        if current_count != expected_count:
            rebuild_direct_split_planes_for_axis(axis)
        else:
            for index, plane in enumerate(
                iter_direct_split_plane_objects(axis),
                start=1,
            ):
                _apply_plane_visual_style(plane, axis)
                _ensure_plane_contour(plane, axis)
                _apply_plane_editability(plane, axis, index, scene)
                _set_direct_split_plane_hidden(
                    plane,
                    direct_split_planes_overlay_hidden(scene),
                )
    ensure_optimized_base_vertical_split_plane(scene)
    ensure_moldboxer_transform_gizmos_for_selection(bpy.context)


def _selection_snapshot():
    view_layer = getattr(bpy.context, "view_layer", None)
    active = getattr(getattr(view_layer, "objects", None), "active", None)
    selected = tuple(getattr(bpy.context, "selected_objects", ()))
    return active, selected


def _restore_selection(snapshot) -> None:
    active, selected = snapshot
    scene_objects = getattr(getattr(bpy.context, "scene", None), "objects", ())
    live_objects = set(scene_objects)
    selected = tuple(obj for obj in selected if obj in live_objects)
    if active not in live_objects:
        active = bpy.data.objects.get("patron")
    if active is not None and active not in selected:
        selected = (*selected, active)

    for obj in tuple(getattr(bpy.context, "selected_objects", ())):
        try:
            obj.select_set(False)
        except (ReferenceError, RuntimeError):
            pass
    for obj in selected:
        if not getattr(obj, "hide_select", False):
            obj.select_set(True)
    if active is not None:
        bpy.context.view_layer.objects.active = active


def _sync_direct_split_planes_timer():
    global _SYNC_PENDING, _DEFAULT_RESET_PENDING, _DEFAULT_RESET_SCENE
    if _SPLIT_PLANE_PREPARATION_DEPTH:
        return 0.1
    selection = _selection_snapshot()
    try:
        if _DEFAULT_RESET_PENDING:
            scene = _DEFAULT_RESET_SCENE
            _DEFAULT_RESET_PENDING = False
            _DEFAULT_RESET_SCENE = None
            reset_direct_split_planes_to_defaults(scene)
            sync_skin_base_reference_guide(scene)
        else:
            sync_direct_split_planes_with_scene()
    finally:
        _restore_selection(selection)
        _SYNC_PENDING = False
    return None


def _optimized_base_split_sync_timer():
    global _OPTIMIZED_BASE_SPLIT_SYNC_PENDING
    selection = _selection_snapshot()
    try:
        ensure_optimized_base_vertical_split_plane()
    except Exception:
        logger.exception("Could not enforce optimized-base split-plane orientation")
    finally:
        _restore_selection(selection)
        _OPTIMIZED_BASE_SPLIT_SYNC_PENDING = False
    return None


@persistent
def _detect_optimized_base_split_rotation(scene, depsgraph) -> None:
    global _OPTIMIZED_BASE_SPLIT_SYNC_PENDING
    if (
        _OPTIMIZED_BASE_SPLIT_SYNC_PENDING
        or not _optimized_base_split_guard_applies(scene)
        or _split_plane_ui_blocked(scene)
    ):
        return

    split_plane_transform_changed = False
    for update in getattr(depsgraph, "updates", ()):
        updated_id = getattr(update, "id", None)
        if (
            getattr(updated_id, "type", None) == "MESH"
            and _is_direct_split_plane(updated_id)
            and bool(getattr(update, "is_updated_transform", True))
        ):
            split_plane_transform_changed = True
            break
    if not split_plane_transform_changed:
        return
    if any(
        _is_verticalish_plane(plane)
        for plane in iter_direct_split_plane_objects()
    ):
        return

    _OPTIMIZED_BASE_SPLIT_SYNC_PENDING = True
    try:
        bpy.app.timers.register(
            _optimized_base_split_sync_timer,
            first_interval=0.0,
        )
    except Exception:
        _optimized_base_split_sync_timer()


def _remove_optimized_base_split_handlers() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") in {
            _OPTIMIZED_BASE_SPLIT_HANDLER_NAME,
            _SPLIT_PLANE_COUNT_HANDLER_NAME,
        }:
            handlers.remove(handler)


@persistent
def _sync_split_plane_counts_from_objects(scene, _depsgraph) -> None:
    """Adopt split planes duplicated directly in the viewport."""
    if scene is None or _SPLIT_PLANE_SYNC_SUSPEND_DEPTH:
        return

    _remove_orphaned_direct_split_plane_contours(scene)
    scene_key = _scene_pointer(scene)
    current_ids = _direct_split_plane_object_ids(scene)
    _SPLIT_PLANE_OBJECT_IDS_BY_SCENE[scene_key] = current_ids

    if _split_plane_ui_blocked(scene):
        return

    # A native Blender duplicate retains its source plane index. Only adopt an
    # excess plane with that duplicate signature. Never lower a configured
    # count from the live objects: mold generation and batch tests temporarily
    # remove those objects after capturing their split specifications.
    for axis in ("x", "y", "z"):
        if axis == "z" and is_multipart_type(
            getattr(scene, "mold_type_preview", "")
        ):
            continue
        planes = _scene_direct_split_plane_objects(scene, axis)
        property_name = _AXIS_SCENE_PROPERTY[axis]
        configured = int(getattr(scene, property_name, 0))
        if len(planes) <= configured:
            continue
        indices = [
            int(plane.get(DIRECT_SPLIT_PLANE_INDEX_KEY, 0))
            for plane in planes
        ]
        if len(indices) != len(set(indices)):
            setattr(scene, property_name, len(planes))

    # Property update callbacks reindex and restyle the surviving objects.
    _SPLIT_PLANE_OBJECT_IDS_BY_SCENE[scene_key] = (
        _direct_split_plane_object_ids(scene)
    )


@persistent
def _sync_skin_base_reference_from_transform(scene, depsgraph) -> None:
    if _SKIN_BASE_REFERENCE_UPDATING:
        return
    guide = skin_base_reference_guide_object()
    if (
        getattr(scene, "mold_type_preview", "") != "DIRECT_MOLD_SKIN"
        and not scene.get(FOUNDATION_GUIDE_ACTIVE_SCENE_KEY, False)
    ):
        if guide is not None:
            remove_skin_base_reference_guide()
        return
    if guide is None:
        return
    guide_transform_changed = any(
        (
            getattr(update, "id", None) == guide
            or getattr(getattr(update, "id", None), "original", None) == guide
        )
        and bool(getattr(update, "is_updated_transform", True))
        for update in getattr(depsgraph, "updates", ())
    )
    if not guide_transform_changed:
        return
    _set_direct_split_plane_hidden(
        guide,
        direct_split_planes_overlay_hidden(scene),
    )
    _sync_skin_base_reference_property_from_guide(scene, guide)


def _remove_skin_base_reference_handlers() -> None:
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == _SKIN_BASE_REFERENCE_HANDLER_NAME:
            handlers.remove(handler)


def register_optimized_base_split_plane_guard() -> None:
    _remove_optimized_base_split_handlers()
    _remove_skin_base_reference_handlers()
    bpy.app.handlers.depsgraph_update_post.append(
        _detect_optimized_base_split_rotation
    )
    bpy.app.handlers.depsgraph_update_post.append(
        _sync_split_plane_counts_from_objects
    )
    bpy.app.handlers.depsgraph_update_post.append(
        _sync_skin_base_reference_from_transform
    )
    _remember_direct_split_plane_objects()


def unregister_optimized_base_split_plane_guard() -> None:
    global _OPTIMIZED_BASE_SPLIT_SYNC_PENDING
    _remove_optimized_base_split_handlers()
    _remove_skin_base_reference_handlers()
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _optimized_base_split_sync_timer
    ):
        bpy.app.timers.unregister(_optimized_base_split_sync_timer)
    _OPTIMIZED_BASE_SPLIT_SYNC_PENDING = False
    _SPLIT_PLANE_OBJECT_IDS_BY_SCENE.clear()
    remove_skin_base_reference_guide()


def _panel_region_key(context) -> int:
    region = getattr(context, "region", None)
    as_pointer = getattr(region, "as_pointer", None)
    if callable(as_pointer):
        return int(as_pointer())
    return id(region)


def schedule_direct_split_plane_sync(panel_mode=None, context=None) -> None:
    global _SYNC_PENDING, _DEFAULT_RESET_PENDING, _DEFAULT_RESET_SCENE
    context = context or bpy.context
    normalized_mode = str(panel_mode or "").lower()
    if normalized_mode in {"direct", "silicone", "fixture"}:
        region_key = _panel_region_key(context)
        previous_mode = _PANEL_MODE_BY_REGION.get(region_key)
        _PANEL_MODE_BY_REGION[region_key] = normalized_mode
        if (
            previous_mode == "direct" and normalized_mode == "silicone"
        ) or (
            previous_mode == "fixture" and normalized_mode in {"direct", "silicone"}
        ):
            _DEFAULT_RESET_PENDING = True
            _DEFAULT_RESET_SCENE = context.scene

    if _SYNC_PENDING or (
        not _DEFAULT_RESET_PENDING and not _direct_split_planes_need_sync()
    ):
        return
    _SYNC_PENDING = True
    try:
        bpy.app.timers.register(_sync_direct_split_planes_timer, first_interval=0.0)
    except Exception:
        _sync_direct_split_planes_timer()


def _plane_normal(obj) -> mathutils.Vector:
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    normal = normal_matrix @ mathutils.Vector((0.0, 0.0, 1.0))
    if normal.length <= 1e-9:
        return mathutils.Vector((0.0, 0.0, 1.0))
    return normal.normalized()


def _plane_center_point(obj) -> mathutils.Vector:
    vertices = getattr(getattr(obj, "data", None), "vertices", None)
    if not vertices:
        return obj.matrix_world.translation.copy()

    center = mathutils.Vector((0.0, 0.0, 0.0))
    for vertex in vertices:
        center += obj.matrix_world @ vertex.co
    return center / len(vertices)


def direct_split_plane_specs(
    *, log_context: str | None = None,
) -> list[object]:
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass

    planes = []
    slip_casting = is_multipart_type(
        getattr(bpy.context.scene, "mold_type_preview", "")
    )
    for obj in iter_direct_split_plane_objects():
        if slip_casting and obj.get(DIRECT_SPLIT_PLANE_AXIS_KEY) == "z":
            continue
        if bool(obj.get("moldboxer_organic_plane", False)):
            from ..dev_organic_plane import organic_split_spec_from_object

            organic_spec = organic_split_spec_from_object(obj)
            if log_context is not None:
                logger.info(
                    "%s organic split: name=%s point=%s direction=%s",
                    log_context,
                    obj.name,
                    organic_spec["point"],
                    organic_spec["normal"],
                )
            planes.append(organic_spec)
            continue
        normal = _plane_normal(obj)
        point = _plane_center_point(obj)
        point_values = [float(value) for value in point]
        normal_values = [float(value) for value in normal]
        if log_context is not None:
            logger.info(
                "%s split plane: name=%s point=%s direction=%s",
                log_context,
                obj.name,
                point_values,
                normal_values,
            )
        planes.append(
            [
                point_values,
                normal_values,
            ]
        )
    return replace_planar_specs_with_organic(planes)


def direct_split_planes_payload() -> str:
    return json.dumps(direct_split_plane_specs(), separators=(",", ":"))


def store_silicone_split_plane_specs(
    plane_specs: list[object],
    scene=None,
) -> None:
    scene = scene or bpy.context.scene
    plane_specs = replace_planar_specs_with_organic(plane_specs)
    scene[SILICONE_SPLIT_PLANES_PAYLOAD_KEY] = json.dumps(
        plane_specs,
        separators=(",", ":"),
    )


def stored_silicone_split_plane_specs(scene=None) -> list[object]:
    scene = scene or bpy.context.scene
    payload = scene.get(SILICONE_SPLIT_PLANES_PAYLOAD_KEY, "[]")
    try:
        plane_specs = json.loads(str(payload))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid stored silicone split-plane payload")
        return []
    if not isinstance(plane_specs, list):
        return []
    return replace_planar_specs_with_organic(plane_specs)


def capture_silicone_split_plane_specs(scene=None) -> list[object]:
    """Capture editable planes before box generation hides their UI objects."""
    scene = scene or bpy.context.scene
    sync_direct_split_planes_with_scene()
    plane_specs = direct_split_plane_specs(log_context="Silicone mold capture")
    store_silicone_split_plane_specs(plane_specs, scene)
    return plane_specs


def split_object_by_direct_planes(box: Object) -> list[Object]:
    return split_object_by_direct_plane_specs(box, direct_split_plane_specs())
