"""Blender UI and geometry creation for the Image to 3D Logo utility."""

import logging
import math
import time
from pathlib import Path
from types import SimpleNamespace

import bpy  # type: ignore
import bmesh  # type: ignore
import mathutils  # type: ignore
from bpy.props import (  # type: ignore
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper  # type: ignore
from bpy_extras import view3d_utils  # type: ignore

try:
    from moldboxer_silicone_native.source.bl_utils import (
        configure_metric_millimeter_units,
    )
    from moldboxer_silicone_native.source.i18n import t
    from moldboxer_silicone_native.source.materials import (
        MATERIAL_SPECS,
        get_or_create_simple_material,
    )
    from moldboxer_silicone_native.source.modifiers import (
        build_voxel_modifier,
        diff_mod,
    )
    from moldboxer_silicone_native.source.object import (
        DIRECT_BOOLEAN_RETRY_SCENE_KEY,
        Object,
    )
    from moldboxer_silicone_native.source.voxel_size import get_master_voxel_size
    from moldboxer_silicone_native.source.components.watermark_payload import (
        calculate_casting_volume,
    )
    from moldboxer_silicone_native.source.components.geometry_adapter import (
        begin_clear_watermark_worker_state,
        begin_conform_watermark_with_worker,
        begin_prepare_watermark_mesh_with_worker,
        begin_prepare_watermark_image_with_worker,
        begin_remesh_watermark_with_worker,
        begin_trace_watermark_image_with_worker,
        prepare_watermark_image_with_worker,
        prepare_watermark_mesh_with_worker,
        remesh_watermark_with_worker,
    )
    from moldboxer_silicone_native.source.components.watermark_mesh_server import (
        request_watermark_mesh,
    )
    from moldboxer_silicone_native.source.logo_extrusion import (
        LOGO_DEPTH_KEY,
        LOGO_OPERATION_KEY,
        LOGO_PLACED_KEY,
        LOGO_RESOLUTION_SCALE_KEY,
        LOGO_TARGET_KEY,
        LOGO_VOXEL_SIZE_KEY,
        PENDING_LOGO_KEY,
        WATERMARK_OPERATION_ADD,
        WATERMARK_OPERATION_SUBTRACT,
        choose_watermark_target_name,
        format_casting_volume,
        is_logo_box_target_name,
        normalize_watermark_operation,
    )
except ImportError:
    from .source.bl_utils import configure_metric_millimeter_units
    from .source.i18n import t
    from .source.materials import MATERIAL_SPECS, get_or_create_simple_material
    from .source.modifiers import build_voxel_modifier, diff_mod
    from .source.object import DIRECT_BOOLEAN_RETRY_SCENE_KEY, Object
    from .source.voxel_size import get_master_voxel_size
    from .source.components.watermark_payload import calculate_casting_volume
    from .source.components.geometry_adapter import (
        begin_clear_watermark_worker_state,
        begin_conform_watermark_with_worker,
        begin_prepare_watermark_mesh_with_worker,
        begin_prepare_watermark_image_with_worker,
        begin_remesh_watermark_with_worker,
        begin_trace_watermark_image_with_worker,
        prepare_watermark_image_with_worker,
        prepare_watermark_mesh_with_worker,
        remesh_watermark_with_worker,
    )
    from .source.components.watermark_mesh_server import request_watermark_mesh
    from .source.logo_extrusion import (
        LOGO_DEPTH_KEY,
        LOGO_OPERATION_KEY,
        LOGO_PLACED_KEY,
        LOGO_RESOLUTION_SCALE_KEY,
        LOGO_TARGET_KEY,
        LOGO_VOXEL_SIZE_KEY,
        PENDING_LOGO_KEY,
        WATERMARK_OPERATION_ADD,
        WATERMARK_OPERATION_SUBTRACT,
        choose_watermark_target_name,
        format_casting_volume,
        is_logo_box_target_name,
        normalize_watermark_operation,
    )


logger = logging.getLogger(__name__)
_OVERLAY_IMAGE_NAME = "Moldboxer Logo Live Mask"
_PENDING_LOGO_MATERIAL_NAME = "Moldboxer Pending Logo"
_PENDING_LOGO_INVALID_RGB = (0.8, 0.08, 0.04)
_LOGO_CREATION_RESOLUTION_SCALE = 1.5
_LOGO_TRACE_DETAIL = round(512 * _LOGO_CREATION_RESOLUTION_SCALE)
_LOGO_TRACE_DETAIL_MAX = round(_LOGO_TRACE_DETAIL * 2.0)
_TEXT_WATERMARK_CURVE_RESOLUTION = round(
    8 * _LOGO_CREATION_RESOLUTION_SCALE
)
_LOGO_CONFORM_MAX_VERTICES = round(
    12000 * _LOGO_CREATION_RESOLUTION_SCALE
)
_TRACKPAD_NAVIGATION_SETTLE_SECONDS = 0.15
_PLACEMENT_TIMER_INTERVAL_SECONDS = 0.05
_DEFAULT_SVG_VOXEL_SIZE = 0.1607142857142857
_WATERMARK_OPERATION_ITEMS = (
    (
        WATERMARK_OPERATION_ADD,
        "Raised",
        "Extrude outward and add the watermark to the target",
    ),
    (
        WATERMARK_OPERATION_SUBTRACT,
        "Engraved",
        "Cut the watermark inward into the target",
    ),
)
_WATERMARK_FONT_SPECS = {
    "INTER": ("Inter", "assets/fonts/inter/Inter-Variable.ttf"),
    "MONTSERRAT": (
        "Montserrat",
        "assets/fonts/montserrat/Montserrat-Variable.ttf",
    ),
    "ROBOTO_SLAB": (
        "Roboto Slab",
        "assets/fonts/roboto_slab/RobotoSlab-Variable.ttf",
    ),
    "BEBAS_NEUE": (
        "Bebas Neue",
        "assets/fonts/bebas_neue/BebasNeue-Regular.ttf",
    ),
    "NOTO_SANS_ARABIC": (
        "Noto Sans Arabic",
        "assets/fonts/noto_sans_arabic/NotoSansArabic-Variable.ttf",
    ),
}
_WATERMARK_FONT_ITEMS = (
    ("BFONT", "Blender Default", ""),
    *(
        (identifier, label, "")
        for identifier, (label, _relative_path) in _WATERMARK_FONT_SPECS.items()
    ),
)


def _tag_viewport_redraw():
    screen = getattr(bpy.context, "screen", None)
    if screen is not None:
        for area in screen.areas:
            area.tag_redraw()


def _refresh_logo_preview(operator, context):
    if getattr(operator, "_refreshing", False):
        return
    if _is_svg_filepath(getattr(operator, "filepath", "")):
        _tag_viewport_redraw()
        return
    ensure_preview = getattr(operator, "_ensure_live_preview", None)
    if callable(ensure_preview):
        ensure_preview(context, force=True)
    else:
        refresh = getattr(operator, "_refresh_preview", None)
        if callable(refresh):
            refresh()
    _tag_viewport_redraw()


def _draw_overlay_rectangle(x, y, width, height, color):
    import gpu  # type: ignore
    from gpu_extras.batch import batch_for_shader  # type: ignore

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {
            "pos": (
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            )
        },
    )
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _load_source_pixels(filepath, detail):
    path = Path(bpy.path.abspath(filepath)).expanduser()
    if not path.is_file():
        raise ValueError(t("Choose a valid image file"))
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    width, height = (int(image.size[0]), int(image.size[1]))
    if width < 1 or height < 1:
        raise ValueError(t("The image has no readable pixels"))
    prepared = prepare_watermark_image_with_worker(
        image.pixels[:],
        width,
        height,
        max_dimension=detail,
    )
    return (
        prepared.pixels,
        prepared.width,
        prepared.height,
        prepared.suggested_color,
        image,
    )


def _begin_load_source_pixels(filepath, detail):
    path = Path(bpy.path.abspath(filepath)).expanduser()
    if not path.is_file():
        raise ValueError(t("Choose a valid image file"))
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    width, height = (int(image.size[0]), int(image.size[1]))
    if width < 1 or height < 1:
        raise ValueError(t("The image has no readable pixels"))
    task = begin_prepare_watermark_image_with_worker(
        image.pixels[:],
        width,
        height,
        max_dimension=detail,
    )
    return task.then(
        lambda prepared: (
            prepared.pixels,
            prepared.width,
            prepared.height,
            prepared.suggested_color,
            image,
        )
    )


def _is_svg_filepath(filepath):
    return Path(str(filepath or "")).suffix.casefold() == ".svg"


def _select_logo_object(context, logo_object):
    for selected in context.selected_objects:
        selected.select_set(False)
    logo_object.select_set(True)
    context.view_layer.objects.active = logo_object


def _create_text_watermark_object(
    context,
    text,
    width,
    depth,
    font_identifier="BFONT",
):
    del context
    font_spec = _WATERMARK_FONT_SPECS.get(font_identifier)
    font_path = (
        Path(__file__).resolve().parent / font_spec[1]
        if font_spec is not None
        else None
    )
    return request_watermark_mesh(
        {
            "kind": "text",
            "name": "Text_Watermark_3D",
            "text": text,
            "width": float(width),
            "depth": float(depth),
            "font_identifier": font_identifier,
            **({"font_path": str(font_path)} if font_path is not None else {}),
            "curve_resolution": _TEXT_WATERMARK_CURVE_RESOLUTION,
        }
    ).object


def _create_svg_logo_object(context, filepath, name, width, depth):
    del context
    path = Path(bpy.path.abspath(filepath)).expanduser()
    return request_watermark_mesh(
        {
            "kind": "svg",
            "name": name,
            "svg_path": str(path),
            "width": float(width),
            "depth": float(depth),
            "curve_resolution": _TEXT_WATERMARK_CURVE_RESOLUTION,
        }
    ).object


def _mirror_watermark_source(watermark_object, enabled):
    """Mirror a generated watermark in its local plane without flipping normals."""

    if not enabled:
        return watermark_object
    mesh = watermark_object.data
    topology = bmesh.new()
    try:
        topology.from_mesh(mesh)
        if not topology.verts:
            return watermark_object
        minimum_x = min(vertex.co.x for vertex in topology.verts)
        maximum_x = max(vertex.co.x for vertex in topology.verts)
        center_sum = minimum_x + maximum_x
        for vertex in topology.verts:
            vertex.co.x = center_sum - vertex.co.x
        bmesh.ops.reverse_faces(topology, faces=list(topology.faces))
        topology.to_mesh(mesh)
    finally:
        topology.free()
    mesh.update()
    return watermark_object


def _pending_logo_objects(context=None):
    scene = getattr(context, "scene", None) if context is not None else None
    objects = getattr(scene, "objects", None) if scene is not None else None
    if objects is None:
        objects = bpy.data.objects
    return [
        obj
        for obj in objects
        if getattr(obj, "type", None) == "MESH"
        and bool(obj.get(PENDING_LOGO_KEY, False))
    ]


def _watermark_targets(context):
    """Return one target, preferring an editable grip or selected mold part."""

    scene = getattr(context, "scene", None)
    if scene is None:
        return []

    def usable_target(name):
        target = scene.objects.get(name)
        if target is None or getattr(target, "type", None) != "MESH":
            return None
        try:
            if not target.visible_get(view_layer=context.view_layer):
                return None
        except Exception:
            if bool(getattr(target, "hide_viewport", False)):
                return None
        return target

    pending = _pending_logo_objects(context)
    if pending:
        preferred_name = str(pending[0].get(LOGO_TARGET_KEY, ""))
        preferred_target = usable_target(preferred_name)
        if preferred_target is not None:
            return [preferred_target]

    candidate_names = set(
        ("grip", "box", "left_box", "right_box", "patron")
    )
    candidate_names.update(
        obj.name
        for obj in scene.objects
        if is_logo_box_target_name(getattr(obj, "name", ""))
    )
    candidates = {
        name: target
        for name in candidate_names
        if (target := usable_target(name)) is not None
    }
    selected_names = tuple(
        getattr(obj, "name", "")
        for obj in getattr(context, "selected_objects", ())
    )
    active_object = getattr(context, "active_object", None)
    if active_object is None:
        active_object = getattr(
            getattr(context, "view_layer", None),
            "objects",
            None,
        )
        active_object = getattr(active_object, "active", None)
    target_name = choose_watermark_target_name(
        candidates,
        selected_names,
        getattr(active_object, "name", None),
    )
    return [candidates[target_name]] if target_name is not None else []


def _requested_watermark_operation(operator, target_name):
    return normalize_watermark_operation(
        getattr(operator, "watermark_operation", WATERMARK_OPERATION_ADD),
        target_name,
    )


def _draw_watermark_operation(layout, operator):
    layout.prop(operator, "watermark_operation", expand=True)


def _draw_watermark_mirroring(layout, operator):
    layout.prop(operator, "mirror_source")


def _pending_logo_material(*, valid):
    if valid:
        material_name, hex_color, metallic, roughness = MATERIAL_SPECS["funnels"]
        return get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        )

    material = bpy.data.materials.get(_PENDING_LOGO_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(_PENDING_LOGO_MATERIAL_NAME)
    material.diffuse_color = (*_PENDING_LOGO_INVALID_RGB, 1.0)
    return material


def _set_pending_logo_color(logo_object, *, valid):
    material = _pending_logo_material(valid=valid)
    materials = logo_object.data.materials
    if len(materials) != 1 or materials[0] != material:
        materials.clear()
        materials.append(material)
        if logo_object.data.polygons:
            logo_object.data.polygons.foreach_set(
                "material_index",
                [0] * len(logo_object.data.polygons),
            )
    logo_object.color = tuple(material.diffuse_color)


def _remove_logo_object(logo_object):
    if logo_object is None or logo_object.name not in bpy.data.objects:
        return
    mesh = logo_object.data
    bpy.data.objects.remove(logo_object, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)
    material = bpy.data.materials.get(_PENDING_LOGO_MATERIAL_NAME)
    if material is not None and material.users == 0:
        bpy.data.materials.remove(material)


def _view3d_region(context):
    area = getattr(context, "area", None)
    if area is None or getattr(area, "type", None) != "VIEW_3D":
        return None, None
    region = next(
        (item for item in area.regions if getattr(item, "type", None) == "WINDOW"),
        None,
    )
    region_data = getattr(getattr(context, "space_data", None), "region_3d", None)
    return region, region_data


def _raycast_box_target(target, origin_world, direction_world, depsgraph):
    evaluated = target.evaluated_get(depsgraph)
    world_matrix = evaluated.matrix_world
    inverse = world_matrix.inverted_safe()
    origin_local = inverse @ origin_world
    direction_local = inverse.to_3x3() @ direction_world
    if direction_local.length_squared <= 1e-12:
        return None
    direction_local.normalize()
    hit, location_local, normal_local, _face_index = evaluated.ray_cast(
        origin_local,
        direction_local,
    )
    if not hit:
        return None
    location_world = world_matrix @ location_local
    normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
    normal_world = normal_matrix @ normal_local
    if normal_world.length_squared <= 1e-12:
        return None
    normal_world.normalize()
    if normal_world.dot(direction_world) > 0.0:
        normal_world.negate()
    return location_world, normal_world


def _raycast_watermark_targets(context, event, targets):
    region, region_data = _view3d_region(context)
    if region is None or region_data is None:
        return None
    coordinate = (
        event.mouse_x - region.x,
        event.mouse_y - region.y,
    )
    origin = view3d_utils.region_2d_to_origin_3d(region, region_data, coordinate)
    direction = view3d_utils.region_2d_to_vector_3d(region, region_data, coordinate)
    depsgraph = context.evaluated_depsgraph_get()
    closest = None
    closest_distance = math.inf
    for target in targets:
        result = _raycast_box_target(target, origin, direction, depsgraph)
        if result is None:
            continue
        location, normal = result
        distance = (location - origin).length
        if distance < closest_distance:
            closest = (target, location, normal)
            closest_distance = distance
    return closest


def _prepare_logo_conform_state(
    logo_object,
    *,
    max_vertices=_LOGO_CONFORM_MAX_VERTICES,
):
    """Densify the welded solid and cache its projection state in the worker."""

    return prepare_watermark_mesh_with_worker(
        logo_object,
        max_vertices=max_vertices,
        resolution_scale=_LOGO_CREATION_RESOLUTION_SCALE,
    )


def _begin_prepare_logo_conform_state(
    logo_object,
    *,
    max_vertices=_LOGO_CONFORM_MAX_VERTICES,
):
    return begin_prepare_watermark_mesh_with_worker(
        logo_object,
        max_vertices=max_vertices,
        resolution_scale=_LOGO_CREATION_RESOLUTION_SCALE,
    )


def _restore_logo_conform_source(logo_object, conform_state):
    coordinates = conform_state["coordinates"]
    logo_object.data.vertices.foreach_set("co", coordinates.reshape(-1))
    logo_object.data.update()


def _ensure_logo_mesh_is_manifold(logo_object):
    mesh = logo_object.data
    topology = bmesh.new()
    try:
        topology.from_mesh(mesh)
        bmesh.ops.recalc_face_normals(topology, faces=topology.faces)
        if any(not edge.is_manifold for edge in topology.edges):
            raise RuntimeError("The conformed logo is not manifold")
        topology.to_mesh(mesh)
    finally:
        topology.free()
    mesh.update()


def _logo_resolution_scale(logo_object):
    return max(
        1.0,
        float(logo_object.get(LOGO_RESOLUTION_SCALE_KEY, 1.0)),
    )


def _logo_voxel_size_override(logo_object):
    return max(
        0.0,
        float(logo_object.get(LOGO_VOXEL_SIZE_KEY, 0.0)),
    )


def _logo_operation(logo_object):
    operation = str(
        logo_object.get(LOGO_OPERATION_KEY, WATERMARK_OPERATION_ADD)
    ).upper()
    if operation == WATERMARK_OPERATION_SUBTRACT:
        return WATERMARK_OPERATION_SUBTRACT
    return WATERMARK_OPERATION_ADD


def _remesh_conformed_logo(logo_object):
    """Worker-remesh projected geometry before its MANIFOLD Boolean union."""

    nominal_depth = max(0.1, float(logo_object.get(LOGO_DEPTH_KEY, 1.0)))
    voxel_size = remesh_watermark_with_worker(
        logo_object,
        nominal_depth=nominal_depth,
        resolution_scale=_logo_resolution_scale(logo_object),
        voxel_size_override=_logo_voxel_size_override(logo_object),
    )
    _ensure_logo_mesh_is_manifold(logo_object)
    # Remeshing may rebuild material assignments. Restore the shared green
    # deposit material so MANIFOLD TRANSFER keeps the watermark faces green.
    _set_pending_logo_color(logo_object, valid=True)
    return voxel_size


def _begin_remesh_conformed_logo(logo_object):
    nominal_depth = max(0.1, float(logo_object.get(LOGO_DEPTH_KEY, 1.0)))
    task = begin_remesh_watermark_with_worker(
        logo_object,
        nominal_depth=nominal_depth,
        resolution_scale=_logo_resolution_scale(logo_object),
        voxel_size_override=_logo_voxel_size_override(logo_object),
    )

    def finish(voxel_size):
        _ensure_logo_mesh_is_manifold(logo_object)
        _set_pending_logo_color(logo_object, valid=True)
        return voxel_size

    return task.then(finish)


def _mark_logo_pending(
    logo_object,
    depth,
    target_name="",
    resolution_scale=1.0,
    voxel_size=0.0,
    operation=WATERMARK_OPERATION_ADD,
):
    logo_object[PENDING_LOGO_KEY] = True
    logo_object[LOGO_PLACED_KEY] = False
    logo_object[LOGO_TARGET_KEY] = str(target_name or "")
    logo_object[LOGO_DEPTH_KEY] = float(depth)
    logo_object[LOGO_RESOLUTION_SCALE_KEY] = max(
        1.0,
        float(resolution_scale),
    )
    logo_object[LOGO_VOXEL_SIZE_KEY] = max(0.0, float(voxel_size))
    logo_object[LOGO_OPERATION_KEY] = normalize_watermark_operation(
        operation,
        target_name,
    )
    _set_pending_logo_color(logo_object, valid=True)


def _finish_manifold_add_logo_to_box(context, logo_object, target):
    """Apply the watermark with a MANIFOLD union or subtraction."""

    original_hide_select = bool(target.hide_select)
    logo_materials = list(logo_object.data.materials)
    target_wrapper = Object(target)
    logo_wrapper = Object(logo_object)
    scene = context.scene
    is_patron_target = target == scene.objects.get("patron")
    operation = normalize_watermark_operation(
        _logo_operation(logo_object),
        target.name,
    )
    subtract_watermark = operation == WATERMARK_OPERATION_SUBTRACT
    had_retry_setting = DIRECT_BOOLEAN_RETRY_SCENE_KEY in scene
    original_retry_setting = scene.get(DIRECT_BOOLEAN_RETRY_SCENE_KEY, False)

    def apply_watermark_boolean():
        if subtract_watermark:
            target_wrapper.apply_modifier(diff_mod, target=logo_wrapper)
            failure_message = (
                "The manifold watermark subtraction did not produce geometry"
            )
        else:
            target_wrapper.add_with_material_transfer(logo_wrapper)
            failure_message = "The manifold logo union did not produce geometry"
        if target_wrapper.has_empty_boolean:
            raise RuntimeError(failure_message)

    try:
        target.hide_set(False)
        target.hide_select = False
        if is_patron_target:
            scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = False
        try:
            apply_watermark_boolean()
        except Exception:
            if not is_patron_target:
                raise
            master_voxel_size = get_master_voxel_size(
                scene.master_quality,
                target_wrapper,
            )
            logger.warning(
                "Could not apply watermark %s to patron %s; voxel-remeshing "
                "the patron with master quality=%s voxel_size=%.6f and retrying",
                logo_wrapper.name,
                target_wrapper.name,
                scene.master_quality,
                master_voxel_size,
                exc_info=True,
            )
            target_wrapper.apply_modifier(
                build_voxel_modifier(master_voxel_size),
            )
            apply_watermark_boolean()
        logo_name = logo_object.name
        target_name = target.name
        _remove_logo_object(logo_object)
        target.hide_select = original_hide_select
        _select_logo_object(context, target)
        return logo_name, target_name, operation
    except Exception:
        target.hide_select = original_hide_select
        if logo_object.name in bpy.data.objects:
            logo_object.data.materials.clear()
            for material in logo_materials:
                logo_object.data.materials.append(material)
            _select_logo_object(context, logo_object)
        raise
    finally:
        if is_patron_target:
            if had_retry_setting:
                scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY] = original_retry_setting
            elif DIRECT_BOOLEAN_RETRY_SCENE_KEY in scene:
                del scene[DIRECT_BOOLEAN_RETRY_SCENE_KEY]


def _manifold_add_logo_to_box(context, logo_object, target):
    _remesh_conformed_logo(logo_object)
    return _finish_manifold_add_logo_to_box(context, logo_object, target)


def _begin_manifold_add_logo_to_box(context, logo_object, target):
    return _begin_remesh_conformed_logo(logo_object).then(
        lambda _voxel_size: _finish_manifold_add_logo_to_box(
            context,
            logo_object,
            target,
        )
    )


class SILICONE_OT_select_logo_image(ImportHelper, bpy.types.Operator):
    bl_idname = "silicone.select_logo_image"
    bl_label = "Choose Logo Image"
    bl_description = "Choose a PNG, JPEG, BMP, TIFF, or SVG image to turn into 3D"

    filepath: StringProperty(subtype="FILE_PATH", options={"SKIP_SAVE"})  # type: ignore
    filter_glob: StringProperty(  # type: ignore
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff;*.svg",
        options={"HIDDEN"},
    )

    def execute(self, _context):
        result = bpy.ops.silicone.image_to_3d_logo(
            "INVOKE_DEFAULT",
            filepath=self.filepath,
        )
        if "CANCELLED" in result:
            return {"CANCELLED"}
        return {"FINISHED"}


class SILICONE_OT_place_logo_on_box(bpy.types.Operator):
    bl_idname = "silicone.place_logo_on_box"
    bl_label = "Place Logo"
    bl_description = "Snap the generated watermark to the target surface"
    bl_options = {"REGISTER", "UNDO"}

    logo_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})  # type: ignore

    _targets = None
    _logo_object = None
    _rotation = 0.0
    _scale = 1.0
    _valid = False
    _target = None
    _last_valid_matrix = None
    _last_valid_target = None
    _last_valid_mouse = None
    _last_valid_coordinates = None
    _conform_state = None
    _modal_timer = None
    _trackpad_navigation_until = 0.0
    _pending_pointer = None
    _prepare_task = None
    _conform_task = None
    _conform_target = None
    _conform_mouse = None
    _placement_task = None
    _watermark_state_release_queued = False

    def _set_status(self, context, text=None):
        workspace = getattr(context, "workspace", None)
        if workspace is not None:
            try:
                workspace.status_text_set(text)
            except Exception:
                pass

    def _finish(self, context):
        if not self._watermark_state_release_queued:
            self._watermark_state_release_queued = True
            try:
                begin_clear_watermark_worker_state()
            except Exception:
                logger.debug(
                    "Could not queue watermark worker-state cleanup",
                    exc_info=True,
                )
        if self._modal_timer is not None:
            try:
                context.window_manager.event_timer_remove(self._modal_timer)
            except Exception:
                pass
            self._modal_timer = None
        self._set_status(context, None)
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        _tag_viewport_redraw()

    def _cancel_placement(self, context):
        logo_object = self._logo_object
        if logo_object is None:
            self._finish(context)
            return
        self._logo_object = None
        self._finish(context)
        _remove_logo_object(logo_object)
        self.report({"INFO"}, t("Logo placement cancelled"))

    def _update_placement(self, context, event):
        if self._conform_state is None or self._conform_task is not None:
            self._pending_pointer = (event.mouse_x, event.mouse_y)
            return False
        hit = _raycast_watermark_targets(context, event, self._targets)
        if hit is None:
            self._valid = False
            self._target = None
            _set_pending_logo_color(self._logo_object, valid=False)
            _tag_viewport_redraw()
            return False

        target, location, normal = hit
        depth = float(self._logo_object.get(LOGO_DEPTH_KEY, 1.0))
        try:
            self._conform_task = begin_conform_watermark_with_worker(
                target,
                self._conform_state,
                location=location,
                center_normal=normal,
                rotation=self._rotation,
                placement_scale=self._scale,
                extrusion_depth=depth,
                resolution_scale=_logo_resolution_scale(self._logo_object),
                voxel_size_override=_logo_voxel_size_override(self._logo_object),
                operation=_logo_operation(self._logo_object),
            )
            self._conform_target = target
            self._conform_mouse = (event.mouse_x, event.mouse_y)
        except Exception:
            logger.debug("Could not conform watermark to target surface", exc_info=True)
            self._conform_task = None
            self._conform_target = None
            return False
        return False

    def _apply_conform_result(self, result, target, mouse):
        valid = result.valid
        self._logo_object.matrix_world = mathutils.Matrix(result.matrix.tolist())
        if valid:
            self._logo_object.data.vertices.foreach_set(
                "co",
                result.vertices.ravel(),
            )
            self._logo_object.data.update()
        else:
            _restore_logo_conform_source(
                self._logo_object,
                self._conform_state,
            )
        self._valid = valid
        self._target = target if valid else None
        self._logo_object[LOGO_TARGET_KEY] = target.name if valid else ""
        _set_pending_logo_color(self._logo_object, valid=valid)
        if valid:
            self._last_valid_matrix = self._logo_object.matrix_world.copy()
            self._last_valid_target = target
            self._last_valid_mouse = mouse
            self._last_valid_coordinates = tuple(
                vertex.co.copy() for vertex in self._logo_object.data.vertices
            )
        _tag_viewport_redraw()
        return valid

    def _poll_worker_tasks(self, context):
        if self._prepare_task is not None:
            if not self._prepare_task.done():
                _tag_viewport_redraw()
                return {"RUNNING_MODAL"}
            try:
                self._conform_state = self._prepare_task.finish()
            except Exception as exc:
                logger.exception("Could not prepare logo surface conformation")
                self.report(
                    {"ERROR"},
                    t("Could not create 3D logo: {error}", error=exc),
                )
                self._cancel_placement(context)
                return {"CANCELLED"}
            self._prepare_task = None
            self._set_status(
                context,
                t(
                    "Move over the target surface · Wheel rotates · Shift+wheel scales · MMB orbits · Click or tap places · Esc cancels"
                ),
            )

        if self._conform_task is not None:
            if not self._conform_task.done():
                _tag_viewport_redraw()
                return {"RUNNING_MODAL"}
            task = self._conform_task
            target = self._conform_target
            mouse = self._conform_mouse
            self._conform_task = None
            self._conform_target = None
            self._conform_mouse = None
            try:
                self._apply_conform_result(task.finish(), target, mouse)
            except Exception:
                logger.debug(
                    "Could not conform watermark to target surface",
                    exc_info=True,
                )

        if self._placement_task is not None:
            if not self._placement_task.done():
                _tag_viewport_redraw()
                return {"RUNNING_MODAL"}
            task = self._placement_task
            self._placement_task = None
            try:
                logo_name, target_name, operation = task.finish()
            except Exception as exc:
                logger.exception("Could not add watermark to target")
                self._set_status(
                    context,
                    t("Could not add watermark to target: {error}", error=exc),
                )
                self.report(
                    {"ERROR"},
                    t("Could not add watermark to target: {error}", error=exc),
                )
                return {"RUNNING_MODAL"}
            self._logo_object = None
            self._finish(context)
            message = (
                t("Engraved {name} into {target}", name=logo_name, target=target_name)
                if operation == WATERMARK_OPERATION_SUBTRACT
                else t("Added {name} to {target}", name=logo_name, target=target_name)
            )
            self.report({"INFO"}, message)
            return {"FINISHED"}
        return None

    @classmethod
    def poll(cls, context):
        return bool(_pending_logo_objects(context) and _watermark_targets(context))

    def invoke(self, context, event):
        region, region_data = _view3d_region(context)
        if region is None or region_data is None:
            self.report({"ERROR"}, t("Logo placement requires a 3D viewport"))
            return {"CANCELLED"}
        logo_object = bpy.data.objects.get(self.logo_name)
        if logo_object is None or not bool(logo_object.get(PENDING_LOGO_KEY, False)):
            pending = _pending_logo_objects(context)
            logo_object = pending[0] if pending else None
        targets = _watermark_targets(context)
        if logo_object is None or not targets:
            self.report(
                {"ERROR"},
                t("No patron or built box is available for watermark placement"),
            )
            return {"CANCELLED"}

        try:
            prepare_task = _begin_prepare_logo_conform_state(logo_object)
        except Exception as exc:
            logger.exception("Could not prepare logo surface conformation")
            self.report(
                {"ERROR"},
                t("Could not create 3D logo: {error}", error=exc),
            )
            return {"CANCELLED"}

        self._logo_object = logo_object
        self._targets = targets
        self._conform_state = None
        self._prepare_task = prepare_task
        self._conform_task = None
        self._conform_target = None
        self._conform_mouse = None
        self._placement_task = None
        self._watermark_state_release_queued = False
        self._rotation = 0.0
        self._scale = 1.0
        self._valid = False
        self._target = None
        self._last_valid_matrix = None
        self._last_valid_target = None
        self._last_valid_mouse = None
        self._last_valid_coordinates = None
        self._trackpad_navigation_until = 0.0
        self._pending_pointer = None
        logo_object[LOGO_PLACED_KEY] = False
        logo_object[LOGO_TARGET_KEY] = ""
        _select_logo_object(context, logo_object)
        _set_pending_logo_color(logo_object, valid=True)
        self._set_status(
            context,
            t("Preparing watermark surface..."),
        )
        try:
            context.window.cursor_modal_set("EYEDROPPER")
        except Exception:
            pass
        self._modal_timer = context.window_manager.event_timer_add(
            _PLACEMENT_TIMER_INTERVAL_SECONDS,
            window=context.window,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if self._logo_object is None or self._logo_object.name not in bpy.data.objects:
            self._finish(context)
            return {"CANCELLED"}
        if self._placement_task is not None and event.type != "TIMER":
            return {"RUNNING_MODAL"}
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cancel_placement(context)
            return {"CANCELLED"}
        if event.type == "MIDDLEMOUSE":
            return {"PASS_THROUGH"}
        if event.alt and event.type in {"LEFTMOUSE", "MOUSEMOVE"}:
            return {"PASS_THROUGH"}
        if event.type in {"TRACKPADPAN", "TRACKPADZOOM"}:
            self._pending_pointer = (event.mouse_x, event.mouse_y)
            self._trackpad_navigation_until = (
                time.monotonic() + _TRACKPAD_NAVIGATION_SETTLE_SECONDS
            )
            return {"PASS_THROUGH"}
        if event.type in {"NDOF_MOTION", "MOUSEROTATE", "MOUSESMARTZOOM"}:
            return {"PASS_THROUGH"}
        if event.type == "TIMER":
            worker_result = self._poll_worker_tasks(context)
            if worker_result is not None:
                return worker_result
            if (
                self._pending_pointer is not None
                and time.monotonic() >= self._trackpad_navigation_until
            ):
                mouse_x, mouse_y = self._pending_pointer
                self._pending_pointer = None
                self._update_placement(
                    context,
                    SimpleNamespace(mouse_x=mouse_x, mouse_y=mouse_y),
                )
            return {"RUNNING_MODAL"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            direction = 1.0 if event.type == "WHEELUPMOUSE" else -1.0
            if event.shift:
                scale_step = 1.05 if direction > 0.0 else 1.0 / 1.05
                self._scale = max(0.2, min(5.0, self._scale * scale_step))
            else:
                self._rotation += math.radians(5.0) * direction
            self._update_placement(context, event)
            return {"RUNNING_MODAL"}
        if (
            event.type in {"EQUAL", "NUMPAD_PLUS", "MINUS", "NUMPAD_MINUS"}
            and event.value == "PRESS"
        ):
            scale_step = (
                1.05
                if event.type in {"EQUAL", "NUMPAD_PLUS"}
                else 1.0 / 1.05
            )
            self._scale = max(0.2, min(5.0, self._scale * scale_step))
            self._update_placement(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE":
            self._pending_pointer = (event.mouse_x, event.mouse_y)
            if time.monotonic() < self._trackpad_navigation_until:
                return {"PASS_THROUGH"}
            self._pending_pointer = None
            self._update_placement(context, event)
            return {"RUNNING_MODAL"}
        if event.type in {
            "LEFTMOUSE",
            "SELECTMOUSE",
            "ACTIONMOUSE",
            "EVT_TWEAK_L",
        } and event.value in {"PRESS", "RELEASE", "CLICK", "DOUBLE_CLICK"}:
            target = self._target
            if (
                target is None
                and self._last_valid_target is not None
                and self._last_valid_mouse is not None
                and abs(event.mouse_x - self._last_valid_mouse[0]) <= 20
                and abs(event.mouse_y - self._last_valid_mouse[1]) <= 20
            ):
                target = self._last_valid_target
                self._logo_object.matrix_world = self._last_valid_matrix.copy()
                if self._last_valid_coordinates is not None:
                    for vertex, coordinate in zip(
                        self._logo_object.data.vertices,
                        self._last_valid_coordinates,
                    ):
                        vertex.co = coordinate
                    self._logo_object.data.update()
            if target is None:
                self._set_status(
                    context,
                    t("The watermark must fit completely on the target surface"),
                )
                return {"RUNNING_MODAL"}
            logo_object = self._logo_object
            try:
                self._placement_task = _begin_manifold_add_logo_to_box(
                    context,
                    logo_object,
                    target,
                )
            except Exception as exc:
                logger.exception("Could not add watermark to target")
                self._set_status(
                    context,
                    t("Could not add watermark to target: {error}", error=exc),
                )
                self.report(
                    {"ERROR"},
                    t("Could not add watermark to target: {error}", error=exc),
                )
                return {"RUNNING_MODAL"}
            self._set_status(context, t("Applying watermark..."))
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self._cancel_placement(context)


class SILICONE_OT_text_watermark(bpy.types.Operator):
    bl_idname = "silicone.text_watermark"
    bl_label = "Text Watermark"
    bl_description = "Type text and turn it into a 3D watermark"
    bl_options = {"REGISTER", "UNDO"}

    watermark_text: StringProperty(  # type: ignore
        name="Watermark Text",
        description="Text to place on the target surface",
        default="",
    )
    font_choice: EnumProperty(  # type: ignore
        name="Font",
        description="Typeface used to create the 3D watermark",
        items=_WATERMARK_FONT_ITEMS,
        default="BFONT",
    )
    watermark_operation: EnumProperty(  # type: ignore
        name="Effect",
        description="Choose whether the watermark is raised or engraved",
        items=_WATERMARK_OPERATION_ITEMS,
        default=WATERMARK_OPERATION_ADD,
    )
    mirror_source: BoolProperty(  # type: ignore
        name="Mirror Source",
        description="Mirror the source horizontally so the molded result reads correctly",
        default=False,
    )
    output_width: FloatProperty(  # type: ignore
        name="Logo Width",
        description="Width of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=500.0,
        default=30.0,
    )
    extrusion_depth: FloatProperty(  # type: ignore
        name="Extrusion",
        description="Depth of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=50.0,
        default=3.0,
    )

    def invoke(self, context, _event):
        configure_metric_millimeter_units(context)
        return context.window_manager.invoke_props_dialog(
            self,
            width=400,
            title=t("Text Watermark"),
            confirm_text=t("Create Text Watermark"),
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "watermark_text")
        layout.prop(self, "font_choice")
        geometry_box = layout.box()
        geometry_box.label(text=t("3D size"), icon="MESH_CUBE")
        _draw_watermark_operation(geometry_box, self)
        _draw_watermark_mirroring(geometry_box, self)
        row = geometry_box.row(align=True)
        row.prop(self, "output_width")
        row.prop(self, "extrusion_depth")

    def execute(self, context):
        text = " ".join(str(self.watermark_text).strip().splitlines()).strip()
        if not text:
            self.report({"ERROR"}, t("Enter watermark text"))
            return {"CANCELLED"}
        return _create_and_place_text_watermark(
            self,
            context,
            text,
            "Text_Watermark_3D",
        )


def _create_and_place_text_watermark(
    operator,
    context,
    text,
    object_name,
):
    watermark_object = None
    targets = _watermark_targets(context)
    target_name = targets[0].name if targets else ""
    try:
        watermark_object = _create_text_watermark_object(
            context,
            text,
            operator.output_width,
            operator.extrusion_depth,
            operator.font_choice,
        )
        _mirror_watermark_source(watermark_object, operator.mirror_source)
        watermark_object.name = object_name
        # Text and casting-volume watermarks share the green deposit material
        # even when there is no placement target yet. Raised placement later
        # transfers this material through the MANIFOLD union.
        _set_pending_logo_color(watermark_object, valid=True)
        if target_name:
            _mark_logo_pending(
                watermark_object,
                operator.extrusion_depth,
                target_name,
                operation=_requested_watermark_operation(operator, target_name),
            )
    except Exception as exc:
        logger.exception("Could not create text watermark")
        if watermark_object is not None and watermark_object.name in bpy.data.objects:
            data = watermark_object.data
            bpy.data.objects.remove(watermark_object, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.batch_remove(ids=[data])
        operator.report(
            {"ERROR"},
            t("Could not create text watermark: {error}", error=exc),
        )
        return {"CANCELLED"}

    operator.report(
        {"INFO"},
        t("Created {name} from text", name=watermark_object.name),
    )
    if not bool(watermark_object.get(PENDING_LOGO_KEY, False)):
        return {"FINISHED"}
    placement_result = bpy.ops.silicone.place_logo_on_box(
        "INVOKE_DEFAULT",
        logo_name=watermark_object.name,
    )
    if "CANCELLED" in placement_result:
        for key in (
            PENDING_LOGO_KEY,
            LOGO_PLACED_KEY,
            LOGO_TARGET_KEY,
            LOGO_DEPTH_KEY,
            LOGO_RESOLUTION_SCALE_KEY,
            LOGO_VOXEL_SIZE_KEY,
            LOGO_OPERATION_KEY,
        ):
            if key in watermark_object:
                del watermark_object[key]
        operator.report(
            {"WARNING"},
            t("Could not start logo placement; the 3D logo was kept"),
        )
    return {"FINISHED"}


class SILICONE_OT_casting_volume_watermark(bpy.types.Operator):
    bl_idname = "silicone.casting_volume_watermark"
    bl_label = "Casting Volume"
    bl_description = "Use the casting volume as a 3D watermark"
    bl_options = {"REGISTER", "UNDO"}

    volume_unit: EnumProperty(  # type: ignore
        name="Unit",
        description="Unit shown in the casting volume watermark",
        items=(
            ("ML", "ml", "Milliliters"),
            ("FL_OZ", "fl oz", "US fluid ounces"),
        ),
        default="ML",
    )
    font_choice: EnumProperty(  # type: ignore
        name="Font",
        description="Typeface used to create the 3D watermark",
        items=_WATERMARK_FONT_ITEMS,
        default="BFONT",
    )
    watermark_operation: EnumProperty(  # type: ignore
        name="Effect",
        description="Choose whether the watermark is raised or engraved",
        items=_WATERMARK_OPERATION_ITEMS,
        default=WATERMARK_OPERATION_ADD,
    )
    mirror_source: BoolProperty(  # type: ignore
        name="Mirror Source",
        description="Mirror the source horizontally so the molded result reads correctly",
        default=False,
    )

    output_width: FloatProperty(  # type: ignore
        name="Logo Width",
        description="Width of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=500.0,
        default=30.0,
    )
    extrusion_depth: FloatProperty(  # type: ignore
        name="Extrusion",
        description="Depth of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=50.0,
        default=3.0,
    )

    def _text(self):
        return format_casting_volume(
            calculate_casting_volume(),
            self.volume_unit,
        )

    def invoke(self, context, _event):
        configure_metric_millimeter_units(context)
        return context.window_manager.invoke_props_dialog(
            self,
            width=400,
            title=t("Casting Volume"),
            confirm_text=t("Create Text Watermark"),
        )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "volume_unit", expand=True)
        layout.prop(self, "font_choice")
        layout.label(text=self._text(), icon="DRIVER_DISTANCE")
        geometry_box = layout.box()
        geometry_box.label(text=t("3D size"), icon="MESH_CUBE")
        _draw_watermark_operation(geometry_box, self)
        _draw_watermark_mirroring(geometry_box, self)
        row = geometry_box.row(align=True)
        row.prop(self, "output_width")
        row.prop(self, "extrusion_depth")

    def execute(self, context):
        return _create_and_place_text_watermark(
            self,
            context,
            self._text(),
            "Casting_Volume_Watermark_3D",
        )


class SILICONE_OT_image_to_3d_logo(bpy.types.Operator):
    bl_idname = "silicone.image_to_3d_logo"
    bl_label = "Image to 3D Logo"
    bl_description = "Trace pixels close to a color and extrude them into a 3D mesh"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})  # type: ignore
    watermark_operation: EnumProperty(  # type: ignore
        name="Effect",
        description="Choose whether the watermark is raised or engraved",
        items=_WATERMARK_OPERATION_ITEMS,
        default=WATERMARK_OPERATION_ADD,
    )
    mirror_source: BoolProperty(  # type: ignore
        name="Mirror Source",
        description="Mirror the source horizontally so the molded result reads correctly",
        default=False,
        update=_refresh_logo_preview,
    )
    target_color: FloatVectorProperty(  # type: ignore
        name="Detected Color",
        description="Pixels close to this color become 3D geometry",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0),
        update=_refresh_logo_preview,
    )
    svg_voxel_size: FloatProperty(  # type: ignore
        name="Voxel Size",
        description="Voxel size used to remesh SVG artwork; lower values preserve more detail",
        unit="LENGTH",
        min=0.01,
        soft_max=0.5,
        default=_DEFAULT_SVG_VOXEL_SIZE,
        update=_refresh_logo_preview,
    )
    color_tolerance: FloatProperty(  # type: ignore
        name="Color Threshold",
        description="How far a pixel color may be from the detected color",
        subtype="PERCENTAGE",
        min=0.0,
        max=100.0,
        default=12.0,
        update=_refresh_logo_preview,
    )
    alpha_threshold: FloatProperty(  # type: ignore
        name="Opacity Threshold",
        description="Ignore pixels more transparent than this value",
        subtype="PERCENTAGE",
        min=0.0,
        max=100.0,
        default=5.0,
        update=_refresh_logo_preview,
    )
    invert: BoolProperty(  # type: ignore
        name="Invert Selection",
        description="Extrude colors outside the selected color range",
        default=False,
        update=_refresh_logo_preview,
    )
    detail: IntProperty(  # type: ignore
        name="Trace Detail",
        description="Maximum image dimension used for tracing",
        min=32,
        max=_LOGO_TRACE_DETAIL_MAX,
        default=_LOGO_TRACE_DETAIL,
        update=_refresh_logo_preview,
    )
    output_width: FloatProperty(  # type: ignore
        name="Logo Width",
        description="Width of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=500.0,
        default=30.0,
        update=_refresh_logo_preview,
    )
    extrusion_depth: FloatProperty(  # type: ignore
        name="Extrusion",
        description="Depth of the generated logo in millimeters",
        unit="LENGTH",
        min=0.1,
        soft_max=50.0,
        default=3.0,
        update=_refresh_logo_preview,
    )

    _source_pixels = None
    _source_width = 0
    _source_height = 0
    _source_image = None
    _source_signature = None
    _suggested_target_color = (0.0, 0.0, 0.0)
    _overlay_draw_handler = None
    _overlay_image_name = ""
    _overlay_texture = None
    _last_preview_signature = None
    _mask = None
    _preview_pixels = None
    _contours = None
    _selected_pixels = 0
    _islands = 0
    _preview_error = ""
    _refreshing = False
    _preview_task = None
    _preview_reschedule = False
    _source_task = None
    _source_reschedule = False

    def _apply_source_result(self, result, signature):
        pixels, width, height, color, image = result
        self._source_pixels = pixels
        self._source_width = width
        self._source_height = height
        self._suggested_target_color = color
        self._source_image = image
        self._source_signature = signature
        self._refreshing = True
        try:
            self.target_color = color
        finally:
            self._refreshing = False

    def _apply_preview_result(self, result):
        self._preview_error = ""
        self._mask = result.mask
        self._preview_pixels = result.preview
        self._contours = result.contours
        self._selected_pixels = result.selected_pixels
        self._islands = result.islands
        self._refresh_overlay_image()

    def _read_source(self):
        signature = (self.filepath, int(self.detail))
        if self._source_pixels is not None and self._source_signature == signature:
            return
        pixels, width, height, suggested_color, image = _load_source_pixels(
            self.filepath,
            self.detail,
        )
        self._source_pixels = pixels
        self._source_width = width
        self._source_height = height
        self._suggested_target_color = suggested_color
        self._source_image = image
        self._source_signature = signature

    def _start_source_read(self):
        signature = (self.filepath, int(self.detail))
        if self._source_task is not None:
            self._source_reschedule = True
            return
        try:
            task = _begin_load_source_pixels(self.filepath, self.detail)
        except Exception as exc:
            self.report({"ERROR"}, t("Could not read image: {error}", error=exc))
            return
        self._source_task = task

        def poll_source():
            if self._source_task is not task:
                return None
            if not task.done():
                _tag_viewport_redraw()
                return 0.25
            try:
                self._apply_source_result(task.finish(), signature)
            except Exception as exc:
                logger.exception("Could not read logo image")
                self.report(
                    {"ERROR"},
                    t("Could not read image: {error}", error=exc),
                )
            finally:
                self._source_task = None
            desired_signature = (self.filepath, int(self.detail))
            if self._source_reschedule or desired_signature != signature:
                self._source_reschedule = False
                self._start_source_read()
            else:
                self._ensure_live_preview(bpy.context, force=True)
            _tag_viewport_redraw()
            return None

        bpy.app.timers.register(poll_source, first_interval=0.0)

    def _refresh_preview(self):
        if not self.filepath:
            return
        if self._preview_task is not None:
            self._preview_reschedule = True
            return
        self._refreshing = True
        try:
            task = begin_trace_watermark_image_with_worker(
                self._source_pixels,
                self._source_width,
                self._source_height,
                target_color=self.target_color,
                color_tolerance=self.color_tolerance / 100.0,
                alpha_threshold=self.alpha_threshold / 100.0,
                invert=self.invert,
                output_width=self.output_width,
            )
            self._preview_task = task

            def poll_preview():
                if self._preview_task is not task:
                    return None
                if not task.done():
                    _tag_viewport_redraw()
                    return 0.25
                try:
                    self._apply_preview_result(task.finish())
                except Exception as exc:
                    logger.exception(
                        "Could not refresh logo threshold preview",
                    )
                    self._preview_error = str(exc).strip() or type(exc).__name__
                    self._mask = None
                    self._preview_pixels = None
                    self._contours = None
                    self._selected_pixels = 0
                    self._islands = 0
                finally:
                    self._preview_task = None
                    self._refreshing = False
                if self._preview_reschedule:
                    self._preview_reschedule = False
                    self._ensure_live_preview(bpy.context, force=True)
                _tag_viewport_redraw()
                return None

            bpy.app.timers.register(poll_preview, first_interval=0.0)
        except Exception as exc:
            logger.exception("Could not refresh logo threshold preview")
            self._preview_error = str(exc).strip() or type(exc).__name__
            self._mask = None
            self._preview_pixels = None
            self._contours = None
            self._selected_pixels = 0
            self._islands = 0
            self._refreshing = False

    def _wait_for_live_preview(self, context):
        """Finish the current image and preview jobs before confirming."""

        for _attempt in range(4):
            self._ensure_live_preview(context)
            source_task = self._source_task
            if source_task is not None:
                signature = (self.filepath, int(self.detail))
                self._apply_source_result(source_task.wait(), signature)
                if self._source_task is source_task:
                    self._source_task = None
                self._source_reschedule = False
                self._last_preview_signature = None
                continue

            preview_task = self._preview_task
            if preview_task is not None:
                self._apply_preview_result(preview_task.wait())
                if self._preview_task is preview_task:
                    self._preview_task = None
                if self._preview_reschedule:
                    self._preview_reschedule = False
                    self._last_preview_signature = None
                    continue
                return

            if (
                self._source_signature == (self.filepath, int(self.detail))
                and self._last_preview_signature == self._preview_signature()
                and self._mask is not None
            ):
                return
            self._last_preview_signature = None

        raise RuntimeError(t("The logo preview could not finish"))

    def _preview_signature(self):
        return (
            self.filepath,
            tuple(round(float(channel), 6) for channel in self.target_color),
            round(float(self.color_tolerance), 6),
            round(float(self.alpha_threshold), 6),
            bool(self.invert),
            int(self.detail),
            round(float(self.output_width), 6),
            round(float(self.extrusion_depth), 6),
            bool(self.mirror_source),
        )

    def _overlay_image(self):
        if not self._overlay_image_name:
            return None
        return bpy.data.images.get(self._overlay_image_name)

    def _refresh_overlay_image(self):
        if self._mask is None or self._preview_pixels is None:
            return
        overlay_image = self._overlay_image()
        if overlay_image is not None and tuple(overlay_image.size) != (
            self._source_width,
            self._source_height,
        ):
            self._overlay_texture = None
            bpy.data.images.remove(overlay_image)
            overlay_image = None
        if overlay_image is None:
            overlay_image = bpy.data.images.new(
                _OVERLAY_IMAGE_NAME,
                width=self._source_width,
                height=self._source_height,
                alpha=True,
            )
            self._overlay_image_name = overlay_image.name
        preview_pixels = self._preview_pixels
        if self.mirror_source:
            preview_pixels = (
                preview_pixels.reshape(self._source_height, self._source_width, 4)
                [:, ::-1, :]
                .reshape(-1)
            )
        overlay_image.pixels.foreach_set(preview_pixels)
        overlay_image.update()
        try:
            overlay_image.gl_free()
        except Exception:
            pass
        self._overlay_texture = None

    def _ensure_live_preview(self, _context, *, force=False):
        desired_source_signature = (self.filepath, int(self.detail))
        if self._source_signature != desired_source_signature:
            self._start_source_read()
            return
        signature = self._preview_signature()
        if not force and signature == self._last_preview_signature:
            return
        # Set the signature first so the image update's redraw cannot recursively
        # trigger another rebuild from draw().
        self._last_preview_signature = signature
        self._refresh_preview()
        try:
            self._refresh_overlay_image()
        except Exception:
            logger.debug("Could not refresh logo mask overlay", exc_info=True)
        _tag_viewport_redraw()

    def _start_overlay(self):
        if self._overlay_draw_handler is not None:
            return
        try:
            self._overlay_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_mask_overlay,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
        except Exception:
            self._overlay_draw_handler = None
            logger.debug("Could not start logo mask overlay", exc_info=True)

    def _stop_overlay(self):
        draw_handler = self._overlay_draw_handler
        self._overlay_draw_handler = None
        if draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(draw_handler, "WINDOW")
            except Exception:
                logger.debug("Could not remove logo mask overlay", exc_info=True)
        self._overlay_texture = None
        overlay_image = self._overlay_image()
        self._overlay_image_name = ""
        if overlay_image is not None:
            bpy.data.images.remove(overlay_image)
        _tag_viewport_redraw()

    def _draw_mask_overlay(self):
        region = getattr(bpy.context, "region", None)
        overlay_image = self._overlay_image()
        if region is None or overlay_image is None:
            return
        try:
            import blf  # type: ignore
            import gpu  # type: ignore
            from gpu_extras.presets import draw_texture_2d  # type: ignore

            if self._overlay_texture is None:
                self._overlay_texture = gpu.texture.from_image(overlay_image)
            image_width, image_height = overlay_image.size[:2]
            max_width = min(320, max(180, int(region.width * 0.28)))
            max_height = min(320, max(180, int(region.height * 0.38)))
            scale = min(
                max_width / max(1, image_width),
                max_height / max(1, image_height),
            )
            draw_width = max(1, int(image_width * scale))
            draw_height = max(1, int(image_height * scale))
            padding = 10
            label_height = 42
            pos_x = max(24, int((region.width - draw_width) * 0.5))
            pos_y = max(24, region.height - draw_height - label_height - 54)

            gpu.state.blend_set("ALPHA")
            _draw_overlay_rectangle(
                pos_x - padding,
                pos_y - padding - label_height,
                draw_width + padding * 2,
                draw_height + padding * 2 + label_height,
                (0.025, 0.025, 0.025, 0.92),
            )
            draw_texture_2d(
                self._overlay_texture,
                (pos_x, pos_y),
                draw_width,
                draw_height,
            )
            font_id = 0
            blf.size(font_id, 13)
            blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
            blf.position(font_id, pos_x, pos_y - 24, 0)
            blf.draw(font_id, t("Live logo mask — gold becomes 3D"))
            blf.size(font_id, 11)
            blf.color(font_id, 0.72, 0.72, 0.72, 1.0)
            blf.position(font_id, pos_x, pos_y - 40, 0)
            blf.draw(
                font_id,
                t(
                    "{width:g} mm wide × {depth:g} mm deep",
                    width=self.output_width,
                    depth=self.extrusion_depth,
                ),
            )
        except Exception:
            logger.debug("Could not draw logo mask overlay", exc_info=True)
        finally:
            try:
                import gpu  # type: ignore

                gpu.state.blend_set("NONE")
            except Exception:
                pass

    def invoke(self, context, _event):
        configure_metric_millimeter_units(context)
        self._overlay_draw_handler = None
        self._overlay_image_name = ""
        self._overlay_texture = None
        self._last_preview_signature = None
        self._source_signature = None
        self._source_task = None
        self._source_reschedule = False
        self._preview_task = None
        self._preview_reschedule = False
        self._preview_error = ""
        if _is_svg_filepath(self.filepath):
            return context.window_manager.invoke_props_dialog(
                self,
                width=440,
                title=t("Image to 3D Logo"),
                confirm_text=t("Create 3D Logo"),
            )
        self._start_source_read()
        self._start_overlay()
        _tag_viewport_redraw()
        return context.window_manager.invoke_props_dialog(
            self,
            width=440,
            title=t("Image to 3D Logo"),
            confirm_text=t("Create 3D Logo"),
        )

    def draw(self, context):
        # Operator RNA update callbacks can be coalesced while a popup is open.
        # Comparing settings during draw provides a reliable second path for
        # refreshing the live mask after any visible control changes.
        is_svg = _is_svg_filepath(self.filepath)
        if not is_svg:
            self._ensure_live_preview(context)
        layout = self.layout
        header = layout.column(align=True)
        header.label(text=Path(self.filepath).name, icon="IMAGE_DATA")

        if not is_svg:
            selection_box = layout.box()
            column = selection_box.column(align=True)
            column.prop(self, "target_color")
            column.prop(self, "color_tolerance", slider=True)
            row = column.row(align=True)
            row.prop(self, "alpha_threshold", slider=True)
            row.prop(self, "invert")
            column.prop(self, "detail")

        geometry_box = layout.box()
        geometry_box.label(text=t("3D size"), icon="MESH_CUBE")
        _draw_watermark_operation(geometry_box, self)
        _draw_watermark_mirroring(geometry_box, self)
        row = geometry_box.row(align=True)
        row.prop(self, "output_width")
        row.prop(self, "extrusion_depth")
        if is_svg:
            geometry_box.prop(self, "svg_voxel_size")

    def execute(self, context):
        if _is_svg_filepath(self.filepath):
            return self._execute_svg(context)
        try:
            self._wait_for_live_preview(context)
        except Exception as exc:
            logger.exception("Could not finish logo preview before creation")
            self.report(
                {"ERROR"},
                t("Could not read image: {error}", error=exc),
            )
            return {"CANCELLED"}
        self._stop_overlay()
        if self._preview_error:
            self.report(
                {"ERROR"},
                t("Could not read image: {error}", error=self._preview_error),
            )
            return {"CANCELLED"}
        if self._mask is None or self._selected_pixels < 1:
            self.report(
                {"ERROR"},
                t("The current threshold does not select any pixels"),
            )
            return {"CANCELLED"}
        contours = [
            [tuple(float(value) for value in point) for point in contour]
            for contour in (self._contours or ())
        ]
        if not contours:
            self.report(
                {"ERROR"},
                t("The selected pixels did not produce a closed shape"),
            )
            return {"CANCELLED"}
        targets = _watermark_targets(context)
        target_name = targets[0].name if targets else ""
        resolution_scale = max(
            1.0,
            float(self.detail) / float(_LOGO_TRACE_DETAIL),
        )
        name = f"{Path(self.filepath).stem}_3D"
        logo_object = None
        try:
            logo_object = request_watermark_mesh(
                {
                    "kind": "contours",
                    "name": name,
                    "contours": contours,
                    "depth": float(self.extrusion_depth),
                }
            ).object
            _mirror_watermark_source(logo_object, self.mirror_source)
            logo_object.name = name
            if target_name:
                _mark_logo_pending(
                    logo_object,
                    self.extrusion_depth,
                    target_name,
                    resolution_scale,
                    operation=_requested_watermark_operation(self, target_name),
                )
        except Exception as exc:
            logger.exception("Could not create 3D logo")
            if logo_object is not None and logo_object.name in bpy.data.objects:
                bpy.data.objects.remove(logo_object, do_unlink=True)
            self.report(
                {"ERROR"},
                t("Could not create 3D logo: {error}", error=exc),
            )
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            t(
                "Created {name} from {count} selected pixels",
                name=logo_object.name,
                count=self._selected_pixels,
            ),
        )
        if bool(logo_object.get(PENDING_LOGO_KEY, False)):
            placement_result = bpy.ops.silicone.place_logo_on_box(
                "INVOKE_DEFAULT",
                logo_name=logo_object.name,
            )
            if "CANCELLED" in placement_result:
                for key in (
                    PENDING_LOGO_KEY,
                    LOGO_PLACED_KEY,
                    LOGO_TARGET_KEY,
                    LOGO_DEPTH_KEY,
                    LOGO_RESOLUTION_SCALE_KEY,
                    LOGO_VOXEL_SIZE_KEY,
                    LOGO_OPERATION_KEY,
                ):
                    if key in logo_object:
                        del logo_object[key]
                self.report(
                    {"WARNING"},
                    t("Could not start logo placement; the 3D logo was kept"),
                )
        return {"FINISHED"}

    def _execute_svg(self, context):
        self._stop_overlay()
        targets = _watermark_targets(context)
        target_name = targets[0].name if targets else ""
        name = f"{Path(self.filepath).stem}_3D"
        logo_object = None
        try:
            logo_object = _create_svg_logo_object(
                context,
                self.filepath,
                name,
                self.output_width,
                self.extrusion_depth,
            )
            _mirror_watermark_source(logo_object, self.mirror_source)
            if target_name:
                _mark_logo_pending(
                    logo_object,
                    self.extrusion_depth,
                    target_name,
                    voxel_size=self.svg_voxel_size,
                    operation=_requested_watermark_operation(self, target_name),
                )
        except Exception as exc:
            logger.exception("Could not create 3D logo from SVG")
            self.report(
                {"ERROR"},
                t("Could not create 3D logo: {error}", error=exc),
            )
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            t("Created {name} from SVG", name=logo_object.name),
        )
        if bool(logo_object.get(PENDING_LOGO_KEY, False)):
            placement_result = bpy.ops.silicone.place_logo_on_box(
                "INVOKE_DEFAULT",
                logo_name=logo_object.name,
            )
            if "CANCELLED" in placement_result:
                for key in (
                    PENDING_LOGO_KEY,
                    LOGO_PLACED_KEY,
                    LOGO_TARGET_KEY,
                    LOGO_DEPTH_KEY,
                    LOGO_RESOLUTION_SCALE_KEY,
                    LOGO_VOXEL_SIZE_KEY,
                    LOGO_OPERATION_KEY,
                ):
                    if key in logo_object:
                        del logo_object[key]
                self.report(
                    {"WARNING"},
                    t("Could not start logo placement; the 3D logo was kept"),
                )
        return {"FINISHED"}

    def cancel(self, _context):
        self._stop_overlay()
