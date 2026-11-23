import bpy  # type: ignore
import contextlib
import bmesh  # type: ignore
import mathutils  # type: ignore
import blf  # type: ignore
from pathlib import Path
import logging
import math
import time
import tomllib
from mathutils import Vector, Euler  # type: ignore
import functools


logger = logging.getLogger(__name__)

MOLDBOXER_BACKGROUND = (0.012, 0.012, 0.012, 1.0)
BLENDER_DEFAULT_BACKGROUND = (0.050876, 0.050876, 0.050876, 1.0)
_BG_APPLIED_KEY = "_moldboxer_background_applied"
_BG_ORIGINAL_KEY = "_moldboxer_original_background_color"
_BG_ORIGINAL_SURFACE_NODE_KEY = "_moldboxer_original_surface_node"
_BG_ORIGINAL_SURFACE_SOCKET_KEY = "_moldboxer_original_surface_socket"
_MB_WORLD_OUTPUT = "_moldboxer_world_output"
_MB_WORLD_CAMERA_BG = "_moldboxer_camera_background"
_MB_WORLD_LIGHTING_BG = "_moldboxer_lighting_background"
_MB_WORLD_ENV = "_moldboxer_environment"
_MB_WORLD_LIGHT_PATH = "_moldboxer_light_path"
_MB_WORLD_MIX = "_moldboxer_world_mix"
_MB_WORLD_LIGHT = "studio.exr"
_VIEWPORT_LOGO_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "logo.png"
)
_VIEWPORT_LOGO_MARGIN = 16
_VIEWPORT_LOGO_TOP_OFFSET = 48
_VIEWPORT_LOGO_WIDTH = 112
_DIMENSIONS_OVERLAY_FONT_ID = 0
_DIMENSIONS_OVERLAY_FONT_SIZE = 12
_DIMENSIONS_OVERLAY_PADDING = 12
_DIMENSIONS_OVERLAY_LINE_GAP = 4
_DIMENSIONS_OVERLAY_CORNER_MARGIN = 16
_DIMENSIONS_OVERLAY_TOP_OFFSET = 16
_DIMENSIONS_OVERLAY_ROW_GAP = 10
_IDENTITY_OVERLAY_LOGO_SIZE = 38
_IDENTITY_OVERLAY_LOGO_GAP = 10
_IDENTITY_OVERLAY_FONT_SIZE = 12
_IDENTITY_OVERLAY_LINE_GAP = 4
_MOLD_METRICS_OVERLAY_FONT_SIZE = 14
_MOLD_METRICS_OVERLAY_PADDING = 12
_MOLD_METRICS_OVERLAY_LINE_GAP = 6
_MOLD_METRICS_OVERLAY_COLUMN_GAP = 12
_MOLD_METRICS_OVERLAY_BOTTOM_OFFSET = _DIMENSIONS_OVERLAY_CORNER_MARGIN
_PROGRESS_OVERLAY_TOP_OFFSET = _DIMENSIONS_OVERLAY_CORNER_MARGIN
_INSTRUCTION_OVERLAY_TITLE_FONT_SIZE = 14
_INSTRUCTION_OVERLAY_BODY_FONT_SIZE = 12
_INSTRUCTION_OVERLAY_MAX_TEXT_WIDTH = 460
_INSTRUCTION_OVERLAY_LINE_GAP = 5
_INSTRUCTION_OVERLAY_SECTION_GAP = 8
_DIMENSIONS_OVERLAY_TEXT_COLOR = (0.95, 0.95, 0.95, 1.0)
_DIMENSIONS_OVERLAY_SECONDARY_TEXT_COLOR = (0.68, 0.68, 0.68, 1.0)
_MOLD_METRICS_OVERLAY_LABEL_COLOR = (0.68, 0.68, 0.68, 1.0)
_MOLD_METRICS_OVERLAY_VALUE_COLOR = (0.95, 0.95, 0.95, 1.0)
MOLDBOXER_VIEWPORT_CARD_BACKGROUND_COLOR = (0.035, 0.035, 0.035, 0.94)
MOLDBOXER_VIEWPORT_CARD_BORDER_COLOR = (0.0, 0.0, 0.0, 0.85)
_DIMENSIONS_OVERLAY_BACKGROUND_COLOR = MOLDBOXER_VIEWPORT_CARD_BACKGROUND_COLOR
_DIMENSIONS_OVERLAY_BORDER_COLOR = MOLDBOXER_VIEWPORT_CARD_BORDER_COLOR
_DIMENSIONS_OVERLAY_BORDER_WIDTH = 1
_DIMENSIONS_OVERLAY_ACCENT_COLOR = (0.714, 0.490, 0.071, 1.0)
_DIMENSIONS_OVERLAY_ACCENT_WIDTH = 3
_DIMENSIONS_OVERLAY_CORNER_RADIUS = 6
_DIMENSIONS_OVERLAY_SUPPORTED_TYPES = {"MESH"}
_SCALE_TRANSFORM_TOOL_IDS = {"builtin.scale", "builtin.scale_cage"}
_MOLDBOXER_TRANSFORM_TOOL_IDS = {
    "builtin.move",
    "builtin.rotate",
    "builtin.scale",
    "builtin.scale_cage",
    # Measure is also backed by an active-tool gizmo. Treat it like the
    # transform tools here so later selection-sync callbacks do not undo the
    # visibility enabled when the user selects Measure.
    "builtin.measure",
}
_MOLDBOXER_TRANSFORM_GIZMO_SIZE = 110
_OBJECT_NAME_LABEL_FONT_SIZE = 11
_OBJECT_NAME_LABEL_PADDING_X = 7
_OBJECT_NAME_LABEL_PADDING_Y = 4
_OBJECT_NAME_LABEL_OFFSET_Y = 8
_OBJECT_NAME_LABEL_MIN_HEIGHT = 20
_OBJECT_NAME_LABEL_BORDER_WIDTH = 1.0
_OBJECT_NAME_LABEL_SHADOW_OFFSET = 1
_OBJECT_NAME_LABEL_CORNER_RADIUS = 4
_OBJECT_NAME_LABEL_TEXT_COLOR = (0.88, 0.90, 0.93, 0.92)
_OBJECT_NAME_LABEL_BACKGROUND_COLOR = (0.06, 0.07, 0.09, 0.70)
_OBJECT_NAME_LABEL_BORDER_COLOR = (1.0, 1.0, 1.0, 0.10)
_OBJECT_NAME_LABEL_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.15)
_GUIDE_LABEL_FONT_SIZE = 9
_GUIDE_LABEL_PADDING_X = 5
_GUIDE_LABEL_PADDING_Y = 2
_GUIDE_LABEL_MIN_HEIGHT = 16
_GUIDE_LABEL_BACKGROUND_COLOR = (0.06, 0.07, 0.09, 0.58)
_GUIDE_LABEL_BORDER_COLOR = (1.0, 1.0, 1.0, 0.08)
_GUIDE_LABEL_TEXT_COLOR = (0.82, 0.85, 0.90, 0.82)
_GUIDE_LABEL_BORDER_WIDTH = 1.0
_GUIDE_LABEL_SHADOW_OFFSET = 1
_GUIDE_LABEL_SHADOW_COLOR = (0.0, 0.0, 0.0, 0.12)
_GUIDE_LABEL_CORNER_RADIUS = 3
_GUIDE_LABEL_ACTIVE_BACKGROUND_COLOR = (0.075, 0.085, 0.11, 0.82)
_GUIDE_LABEL_ACTIVE_BORDER_COLOR = (0.714, 0.490, 0.071, 0.55)
_GUIDE_LABEL_ACTIVE_TEXT_COLOR = (0.93, 0.94, 0.96, 1.0)
_OBJECT_NAME_LABEL_ALLOWED_NAMES = {
    "patron",
    "master",
    "master_base",
    "box",
    "fixture",
    "protective_shell",
    "grip",
    "box_l",
    "box_r",
    "box_l_front",
    "box_l_back",
    "box_r_front",
    "box_r_back",
    "silicone_mold",
    "plaster_mold",
    "casting_box_r",
    "casting_box_l",
    "base_lockers",
    "skin_base_reference_height_guide",
    "fixture_height_guide",
    "funnel_reference_height_guide",
}
_OBJECT_NAME_LABEL_ALLOWED_PREFIXES = ("clamp", "plaster_mold_part_")
_OBJECT_NAME_LABEL_DISPLAY_NAMES = {
    "patron": "Original Master",
    "master": "Master",
    "master_base": "Master Base",
    "box": "Box",
    "fixture": "Fixture",
    "protective_shell": "Protective Shell",
    "box_l": "Box Left",
    "box_r": "Box Right",
    "box_l_front": "Box Left Front",
    "box_l_back": "Box Left Back",
    "box_r_front": "Box Right Front",
    "box_r_back": "Box Right Back",
    "casting_box_l": "Casting Box Left",
    "casting_box_r": "Casting Box Right",
    "clamp_l": "Clamp Left",
    "clamp_r": "Clamp Right",
    "clamp_lockers": "Clamp Locking Clips",
    "base_lockers": "Base Locking Clips",
    "silicone_mold": "Silicone Mold Preview",
    "plaster_mold": "Plaster Mold",
    "skin_base_reference_height_guide": "Base Ref Height",
    "fixture_height_guide": "Fixture Height",
    "funnel_reference_height_guide": "Funnel Start",
}
_PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY = "_moldboxer_pre_master_filler_hide_select"
MASTER_FILLER_BUILDING_KEY = "_moldboxer_master_filler_building"

viewport_logo_draw_handler = None
_viewport_metrics_modes = {}
_viewport_logo_image_name = None
_viewport_logo_image_pointer = None
_viewport_logo_texture = None
_viewport_logo_texture_image_pointer = None
_viewport_display_version = None
viewport_dimensions_draw_handler = None
_viewport_dimensions_msgbus_owner = object()
_modal_progress_overlay_active_count = 0


def _get_overlay_ui_scale(context=None) -> float:
    """Return Blender's DPI-aware scale for custom viewport UI."""
    if context is None:
        context = getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None)
    system_preferences = getattr(preferences, "system", None)
    try:
        ui_scale = float(getattr(system_preferences, "ui_scale", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(ui_scale) or ui_scale <= 0.0:
        return 1.0
    return ui_scale


def _scale_overlay_value(value, ui_scale: float, *, minimum: int = 1) -> int:
    return max(minimum, int(round(float(value) * ui_scale)))


@contextlib.contextmanager
def BMeshObj(blender_object, *, repair_winding=False, update_normals=True):
    """Edit mesh data; winding repair is an explicit caller decision."""
    mesh_object = blender_object.object
    mesh = bmesh.new()
    mesh.from_mesh(
        mesh_object.data,
        face_normals=update_normals or repair_winding,
        vertex_normals=update_normals or repair_winding,
    )
    mesh.faces.ensure_lookup_table()
    mesh.verts.ensure_lookup_table()
    try:
        yield mesh
    finally:
        try:
            if repair_winding:
                bmesh.ops.recalc_face_normals(mesh, faces=mesh.faces)
            elif update_normals:
                mesh.normal_update()
            mesh.to_mesh(mesh_object.data)
        finally:
            mesh.free()


def deselect_all_objects():
    for obj in bpy.data.objects:
        obj.select_set(False)


def calculate_rotation_diff_matrix(v1: mathutils.Vector, v2: mathutils.Vector):
    v1.normalize()
    v2.normalize()

    if v1 == v2:
        return mathutils.Matrix.Identity(4)

    if v1 == -v2:
        if v1.x or v1.y:
            axis = mathutils.Vector((-v1.y, v1.x, 0))
        else:
            axis = mathutils.Vector((0, -v1.z, v1.y))
    else:
        axis = v1.cross(v2)
    angle = v1.angle(v2, None)
    if angle is None:
        return mathutils.Matrix.Identity(4)

    return mathutils.Matrix.Rotation(angle, 4, axis)


def import_model(path: str):
    """Import a supported model file as one Blender mesh object."""
    from .import_detection import mark_import_as_managed

    start_time = time.perf_counter()
    before = set(bpy.context.scene.objects)
    path = bpy.path.abspath(path)
    normalized_path = path.lower()
    if normalized_path.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif normalized_path.endswith(".stl"):
        bpy.ops.wm.stl_import(filepath=path)
    elif normalized_path.endswith(".ply"):
        bpy.ops.wm.ply_import(filepath=path)
    elif normalized_path.endswith((".3mf", ".step", ".stp")):
        if normalized_path.endswith(".3mf"):
            from .three_mf import load_3mf_geometry

            geometry = load_3mf_geometry(path)
        else:
            from .step_import import load_step_geometry

            geometry = load_step_geometry(path)
        mesh = bpy.data.meshes.new(f"{geometry.name}_mesh")
        imported_object = None
        try:
            mesh.from_pydata(geometry.vertices, (), geometry.triangles)
            mesh.update(calc_edges=True)
            imported_object = bpy.data.objects.new(geometry.name, mesh)
            collection = getattr(bpy.context, "collection", None)
            if collection is None:
                collection = bpy.context.scene.collection
            collection.objects.link(imported_object)
        except Exception:
            if imported_object is not None:
                bpy.data.objects.remove(imported_object, do_unlink=True)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            raise
    else:
        raise ValueError(f"Unsupported model file type: {Path(path).suffix or 'none'}")

    after = set(bpy.context.scene.objects)
    new_objects = after - before
    for imported_object in new_objects:
        mark_import_as_managed(imported_object)
    new_object = new_objects.pop()
    logger.info(
        "Raw model import completed in %.3fs: path=%s objects=%d active=%s",
        time.perf_counter() - start_time,
        path,
        len(new_objects) + 1,
        new_object.name,
    )
    return new_object


def _get_world_background_color_input(context):
    if context is None or getattr(context, "scene", None) is None:
        return None

    scene = context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world

    world.use_nodes = True
    node_tree = world.node_tree
    if node_tree is None:
        return None

    nodes = node_tree.nodes
    background = next((node for node in nodes if node.type == "BACKGROUND"), None)
    if background is None:
        background = nodes.new(type="ShaderNodeBackground")
        output = next((node for node in nodes if node.type == "OUTPUT_WORLD"), None)
        if output is not None:
            node_tree.links.new(
                background.outputs["Background"], output.inputs["Surface"]
            )

    return background.inputs["Color"]


def _get_world_node_tree(context):
    if context is None or getattr(context, "scene", None) is None:
        return None, None

    scene = context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world

    world.use_nodes = True
    return world, world.node_tree


def _get_world_output_node(node_tree):
    if node_tree is None:
        return None

    output = next(
        (node for node in node_tree.nodes if node.type == "OUTPUT_WORLD"), None
    )
    if output is None:
        output = node_tree.nodes.new(type="ShaderNodeOutputWorld")
    output.name = _MB_WORLD_OUTPUT
    return output


def _get_or_create_plain_world_background(node_tree):
    if node_tree is None:
        return None

    moldboxer_node_names = {
        _MB_WORLD_CAMERA_BG,
        _MB_WORLD_LIGHTING_BG,
        _MB_WORLD_ENV,
        _MB_WORLD_LIGHT_PATH,
        _MB_WORLD_MIX,
    }
    background = next(
        (
            node
            for node in node_tree.nodes
            if node.type == "BACKGROUND" and node.name not in moldboxer_node_names
        ),
        None,
    )
    if background is None:
        background = node_tree.nodes.new(type="ShaderNodeBackground")
    return background


def _get_studiolight_world_path(light_name: str) -> str | None:
    preferences = getattr(bpy.context, "preferences", None)
    if preferences is None:
        return None

    for studio_light in preferences.studio_lights:
        if studio_light.name == light_name and studio_light.type == "WORLD":
            return studio_light.path
    return None


def _ensure_material_preview_world(context) -> None:
    world, node_tree = _get_world_node_tree(context)
    if world is None or node_tree is None:
        return

    scene = context.scene
    output = _get_world_output_node(node_tree)
    if output is None:
        return

    surface_input = output.inputs.get("Surface")
    if surface_input is None:
        return

    if not bool(scene.get(_BG_APPLIED_KEY, False)):
        if surface_input.is_linked:
            original_link = surface_input.links[0]
            scene[_BG_ORIGINAL_SURFACE_NODE_KEY] = original_link.from_node.name
            scene[_BG_ORIGINAL_SURFACE_SOCKET_KEY] = original_link.from_socket.name
        else:
            scene[_BG_ORIGINAL_SURFACE_NODE_KEY] = ""
            scene[_BG_ORIGINAL_SURFACE_SOCKET_KEY] = ""

    nodes = node_tree.nodes
    links = node_tree.links

    camera_background = nodes.get(_MB_WORLD_CAMERA_BG)
    if camera_background is None:
        camera_background = nodes.new(type="ShaderNodeBackground")
        camera_background.name = _MB_WORLD_CAMERA_BG
    camera_background.inputs["Color"].default_value = MOLDBOXER_BACKGROUND
    camera_background.inputs["Strength"].default_value = 1.0

    lighting_background = nodes.get(_MB_WORLD_LIGHTING_BG)
    if lighting_background is None:
        lighting_background = nodes.new(type="ShaderNodeBackground")
        lighting_background.name = _MB_WORLD_LIGHTING_BG
    lighting_background.inputs["Strength"].default_value = 1.0

    environment = nodes.get(_MB_WORLD_ENV)
    if environment is None:
        environment = nodes.new(type="ShaderNodeTexEnvironment")
        environment.name = _MB_WORLD_ENV
    environment_path = _get_studiolight_world_path(_MB_WORLD_LIGHT)
    if environment_path:
        environment.image = bpy.data.images.load(environment_path, check_existing=True)

    light_path = nodes.get(_MB_WORLD_LIGHT_PATH)
    if light_path is None:
        light_path = nodes.new(type="ShaderNodeLightPath")
        light_path.name = _MB_WORLD_LIGHT_PATH

    mix_shader = nodes.get(_MB_WORLD_MIX)
    if mix_shader is None:
        mix_shader = nodes.new(type="ShaderNodeMixShader")
        mix_shader.name = _MB_WORLD_MIX

    for link in list(lighting_background.inputs["Color"].links):
        links.remove(link)
    if environment.outputs["Color"].is_linked:
        pass
    links.new(environment.outputs["Color"], lighting_background.inputs["Color"])

    for link in list(mix_shader.inputs["Fac"].links):
        links.remove(link)
    links.new(light_path.outputs["Is Camera Ray"], mix_shader.inputs["Fac"])

    for index, source_socket in (
        (1, lighting_background.outputs["Background"]),
        (2, camera_background.outputs["Background"]),
    ):
        for link in list(mix_shader.inputs[index].links):
            links.remove(link)
        links.new(source_socket, mix_shader.inputs[index])

    for link in list(surface_input.links):
        links.remove(link)
    links.new(mix_shader.outputs["Shader"], surface_input)


def _restore_world_surface(context) -> None:
    world, node_tree = _get_world_node_tree(context)
    if world is None or node_tree is None:
        return

    scene = context.scene
    output = _get_world_output_node(node_tree)
    if output is None:
        return

    surface_input = output.inputs.get("Surface")
    if surface_input is None:
        return

    for link in list(surface_input.links):
        node_tree.links.remove(link)

    original_node_name = str(scene.get(_BG_ORIGINAL_SURFACE_NODE_KEY, ""))
    original_socket_name = str(scene.get(_BG_ORIGINAL_SURFACE_SOCKET_KEY, ""))
    if original_node_name:
        original_node = node_tree.nodes.get(original_node_name)
        if original_node is not None and original_socket_name in original_node.outputs:
            node_tree.links.new(
                original_node.outputs[original_socket_name], surface_input
            )
    else:
        background = _get_or_create_plain_world_background(node_tree)
        if background is not None:
            node_tree.links.new(background.outputs["Background"], surface_input)

    for node_name in (
        _MB_WORLD_CAMERA_BG,
        _MB_WORLD_LIGHTING_BG,
        _MB_WORLD_ENV,
        _MB_WORLD_LIGHT_PATH,
        _MB_WORLD_MIX,
    ):
        node = node_tree.nodes.get(node_name)
        if node is not None:
            node_tree.nodes.remove(node)


def _iter_view3d_spaces(context):
    if context is None:
        return

    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        return

    for window in window_manager.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    yield space


def _iter_view3d_areas(context):
    if context is None:
        return

    window_manager = getattr(context, "window_manager", None)
    if window_manager is None:
        return

    for window in window_manager.windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                yield area


def _tag_view3d_areas_for_redraw(context) -> None:
    for area in _iter_view3d_areas(context):
        try:
            area.tag_redraw()
        except Exception:
            continue


def _moldboxer_theme_enabled() -> bool:
    try:
        from .environment import get_addon_preferences

        prefs = get_addon_preferences()
    except Exception:
        prefs = None
    return bool(prefs is not None and getattr(prefs, "use_moldboxer_theme", True))


def _object_is_mold_box_part(obj) -> bool:
    object_name = str(getattr(obj, "name", "")).casefold()
    return (
        object_name in {"box_l", "box_r"}
        or object_name.startswith(
            (
                "box_l_",
                "box_r_",
                "box_l.",
                "box_r.",
                "box_l-",
                "box_r-",
            )
        )
    )


def _object_name_blocks_moldboxer_gizmos(obj) -> bool:
    object_name = str(getattr(obj, "name", "")).casefold()
    if _object_is_skin_base_reference_guide(obj):
        return False
    if _object_is_fixture_height_guide(obj):
        return False
    if "locker" in object_name:
        return False
    if _object_is_mold_box_part(obj):
        return False
    return (
        object_name in {"box", "fixture", "protective_shell"}
        or object_name.startswith("protective_shell_part_")
        or "base" in object_name
        or "silicone_mold" in object_name
        or "silicone mold" in object_name
        or "plaster_mold" in object_name
        or "plaster mold" in object_name
    )


def _object_is_casting_input(obj) -> bool:
    return str(getattr(obj, "name", "")).casefold().startswith("casting_input")


def _object_is_direct_split_plane(obj) -> bool:
    if obj is None:
        return False
    try:
        if bool(obj.get("moldboxer_direct_split_plane")):
            return True
    except Exception:
        pass
    return str(getattr(obj, "name", "")).casefold().startswith("direct_split_plane")


def _object_is_funnel_reference_line(obj) -> bool:
    if obj is None:
        return False
    try:
        if bool(obj.get("moldboxer_funnel_reference_height_guide")):
            return True
        if bool(obj.get("moldboxer_funnel_extension_height_guide")):
            return True
    except Exception:
        pass
    name = str(getattr(obj, "name", "")).casefold()
    return name.startswith("funnel_reference_height_guide") or name.startswith(
        "funnel_extension_height_guide"
    )


def _object_uses_full_transform_gizmos(obj) -> bool:
    """Return whether an editable mold component exposes move, rotate, and scale."""

    if obj is None or _object_is_funnel_reference_line(obj):
        return False

    object_name = str(getattr(obj, "name", "")).casefold()
    base_name = object_name.split(".", 1)[0]
    if base_name in {"patron", "master"}:
        return True
    if object_name.startswith("channel"):
        return True
    return "funnel" in object_name or "deposit" in object_name


def _object_is_skin_base_reference_guide(obj) -> bool:
    if obj is None:
        return False
    try:
        if bool(obj.get("moldboxer_skin_base_reference_guide")):
            return True
    except Exception:
        pass
    return str(getattr(obj, "name", "")).casefold().startswith(
        "skin_base_reference_height_guide"
    )


def _object_is_fixture_height_guide(obj) -> bool:
    if obj is None:
        return False
    try:
        if bool(obj.get("moldboxer_fixture_height_guide")):
            return True
    except Exception:
        pass
    return str(getattr(obj, "name", "")).casefold().startswith(
        "fixture_height_guide"
    )


def is_valid_utility_target(obj) -> bool:
    """Return whether an object may be modified by a Utils operator."""

    return bool(
        obj is not None
        and getattr(obj, "type", None) == "MESH"
        and not _object_is_direct_split_plane(obj)
        and not _object_is_funnel_reference_line(obj)
        and not _object_is_skin_base_reference_guide(obj)
        and not _object_is_fixture_height_guide(obj)
    )


def resolve_utility_target(context=None):
    """Use the active valid mesh, falling back to the scene patron."""

    if context is None:
        context = bpy.context
    active = getattr(context, "active_object", None) or getattr(
        context, "object", None
    )
    if is_valid_utility_target(active):
        for selected in tuple(getattr(context, "selected_objects", ())):
            if not is_valid_utility_target(selected):
                selected.select_set(False)
        return active

    scene = getattr(context, "scene", None)
    scene_objects = getattr(scene, "objects", None) if scene is not None else None
    patron = scene_objects.get("patron") if scene_objects is not None else None
    if patron is None:
        patron = bpy.data.objects.get("patron")
    if not is_valid_utility_target(patron):
        return None

    deselect_all_objects()
    patron.hide_set(False)
    patron.select_set(True)
    context.view_layer.objects.active = patron
    logger.info(
        "Utils target fallback: selected=%s fallback=%s",
        getattr(active, "name", "none"),
        patron.name,
    )
    return patron


def _iter_scene_objects(context=None):
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    return getattr(scene, "objects", None) or bpy.data.objects


def scene_has_master_filler_objects(context=None) -> bool:
    for obj in _iter_scene_objects(context):
        object_name = str(getattr(obj, "name", "")).casefold()
        if "filler" in object_name:
            return True
    return False


def sync_patron_selection_for_master_filler(
    context=None, *, deselect_patron: bool = False
) -> None:
    scene = getattr(context, "scene", None) if context is not None else None
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if scene is not None and bool(scene.get(MASTER_FILLER_BUILDING_KEY, False)):
        return

    patron = bpy.data.objects.get("patron")
    if patron is None:
        return

    has_filler = scene_has_master_filler_objects(context)
    if has_filler:
        if _PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY not in patron:
            patron[_PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY] = bool(
                getattr(patron, "hide_select", False)
            )
        patron.hide_select = True
        if deselect_patron:
            try:
                patron.select_set(False)
            except Exception:
                pass
        return

    if _PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY in patron:
        patron.hide_select = bool(patron[_PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY])
        del patron[_PATRON_PRE_MASTER_FILLER_HIDE_SELECT_KEY]


def _active_view3d_tool_uses_scale_gizmo(context) -> bool:
    workspace = getattr(context, "workspace", None)
    tools = getattr(workspace, "tools", None)
    mode = getattr(context, "mode", None)
    if tools is None or mode is None:
        return False

    try:
        active_tool = tools.from_space_view3d_mode(mode, create=False)
    except (AttributeError, TypeError, RuntimeError):
        return False

    return (
        active_tool is not None
        and getattr(active_tool, "idname", "") in _SCALE_TRANSFORM_TOOL_IDS
    )


def _active_moldboxer_transform_tool_id(context) -> str:
    workspace = getattr(context, "workspace", None)
    tools = getattr(workspace, "tools", None)
    mode = getattr(context, "mode", None)
    if tools is None or mode is None:
        return ""
    try:
        active_tool = tools.from_space_view3d_mode(mode, create=False)
    except (AttributeError, TypeError, RuntimeError):
        return ""
    tool_id = str(getattr(active_tool, "idname", "") or "")
    return tool_id if tool_id in _MOLDBOXER_TRANSFORM_TOOL_IDS else ""


def _ensure_moldboxer_transform_gizmo_size(context) -> None:
    preferences = getattr(context, "preferences", None)
    view_preferences = getattr(preferences, "view", None)
    if view_preferences is None or not hasattr(view_preferences, "gizmo_size"):
        return

    try:
        current_size = int(view_preferences.gizmo_size)
        if current_size < _MOLDBOXER_TRANSFORM_GIZMO_SIZE:
            view_preferences.gizmo_size = _MOLDBOXER_TRANSFORM_GIZMO_SIZE
    except (AttributeError, TypeError, ValueError):
        return


def set_moldboxer_transform_gizmos_enabled(
    enabled: bool,
    context=None,
    *,
    rotate_enabled: bool = False,
    scale_enabled: bool | None = None,
) -> None:
    if context is None:
        context = bpy.context
    if scale_enabled is None:
        scale_enabled = enabled
    transform_tool_id = (
        _active_moldboxer_transform_tool_id(context) if enabled else ""
    )
    transform_tool_active = bool(transform_tool_id)
    if enabled:
        _ensure_moldboxer_transform_gizmo_size(context)

    for space in _iter_view3d_spaces(context):
        try:
            if enabled and hasattr(space, "show_gizmo"):
                space.show_gizmo = True
            if enabled and hasattr(space, "show_gizmo_context"):
                space.show_gizmo_context = not transform_tool_active
            if hasattr(space, "show_gizmo_tool"):
                space.show_gizmo_tool = transform_tool_active or not (
                    enabled and rotate_enabled
                )
            if hasattr(space, "show_gizmo_object_translate"):
                space.show_gizmo_object_translate = (
                    enabled and not transform_tool_active
                )
            if hasattr(space, "show_gizmo_object_scale"):
                space.show_gizmo_object_scale = (
                    scale_enabled and not transform_tool_active
                )
            if hasattr(space, "show_gizmo_object_rotate"):
                space.show_gizmo_object_rotate = (
                    rotate_enabled and not transform_tool_active
                )
        except Exception:
            continue

    _tag_view3d_areas_for_redraw(context)


def enable_moldboxer_movement_gizmos(context=None) -> None:
    if context is None:
        context = bpy.context

    active_object = getattr(context, "active_object", None)
    if active_object is not None and _object_name_blocks_moldboxer_gizmos(
        active_object
    ):
        set_moldboxer_transform_gizmos_enabled(False, context)
        return

    uses_full_transform_gizmos = _object_uses_full_transform_gizmos(active_object)
    set_moldboxer_transform_gizmos_enabled(
        True,
        context,
        rotate_enabled=(
            uses_full_transform_gizmos
            or _object_is_direct_split_plane(active_object)
            or _object_is_skin_base_reference_guide(active_object)
            or _object_is_fixture_height_guide(active_object)
        ),
        scale_enabled=uses_full_transform_gizmos,
    )


def ensure_moldboxer_transform_gizmos_for_selection(context=None) -> None:
    if context is None:
        context = bpy.context

    active_object = getattr(context, "active_object", None)
    uses_full_transform_gizmos = _object_uses_full_transform_gizmos(active_object)
    is_casting_input = _object_is_casting_input(active_object)
    is_direct_split_plane = _object_is_direct_split_plane(active_object)
    is_funnel_reference_line = _object_is_funnel_reference_line(active_object)
    is_skin_base_reference = _object_is_skin_base_reference_guide(
        active_object
    )
    is_fixture_height_guide = _object_is_fixture_height_guide(active_object)
    is_mold_box_part = _object_is_mold_box_part(active_object)
    enabled = (
        active_object is not None
        and not _object_name_blocks_moldboxer_gizmos(active_object)
        and (
            _moldboxer_theme_enabled()
            or is_direct_split_plane
            or is_funnel_reference_line
            or is_skin_base_reference
            or is_fixture_height_guide
        )
    )
    set_moldboxer_transform_gizmos_enabled(
        enabled,
        context,
        rotate_enabled=enabled
        and (
            uses_full_transform_gizmos
            or is_casting_input
            or is_direct_split_plane
            or is_skin_base_reference
            or is_fixture_height_guide
        ),
        scale_enabled=(
            enabled
            and not is_mold_box_part
            and not is_direct_split_plane
            and not is_funnel_reference_line
            and not is_skin_base_reference
        ),
    )


def _get_active_dimensions_overlay_object(context):
    if context is None:
        return None

    obj = getattr(context, "active_object", None)
    if obj is None or getattr(obj, "type", None) not in _DIMENSIONS_OVERLAY_SUPPORTED_TYPES:
        return None
    if not is_valid_utility_target(obj):
        return None
    if not getattr(obj, "select_get", None):
        return None

    try:
        if not obj.select_get():
            return None
    except Exception:
        return None
    return obj


def _scene_length_to_millimeters(length_value: float, scene) -> float:
    unit_settings = getattr(scene, "unit_settings", None)
    scale_length = getattr(unit_settings, "scale_length", 1.0) or 1.0
    # Blender dimensions are expressed in scene units. Converting through the
    # scene unit scale keeps the overlay aligned with this addon's 1 unit = 1 mm setup.
    return float(length_value) * float(scale_length) * 1000.0


def _format_dimension_line(axis_name: str, value_mm: float) -> str:
    return f"{axis_name}: {value_mm:.2f} mm"


def _format_dimensions_overlay_object_name(name) -> str:
    raw_name = str(name or "")
    if raw_name.casefold() == "patron":
        try:
            from .i18n import t
        except Exception:
            return "Master"
        return t("Master")
    return raw_name[:1].upper() + raw_name[1:]


def _build_dimensions_overlay_lines(context):
    obj = _get_active_dimensions_overlay_object(context)
    scene = getattr(context, "scene", None)
    if obj is None or scene is None:
        return None

    dimensions = getattr(obj, "dimensions", None)
    if dimensions is None or len(dimensions) < 3:
        return None

    if scene.unit_settings.system == "IMPERIAL":
        from .scene_units import format_distance

        return [
            _format_dimensions_overlay_object_name(obj.name),
            *[f"{axis}: {format_distance(value, scene)}"
              for axis, value in zip("XYZ", dimensions)],
        ]

    return [
        _format_dimensions_overlay_object_name(obj.name),
        _format_dimension_line("X", _scene_length_to_millimeters(dimensions.x, scene)),
        _format_dimension_line("Y", _scene_length_to_millimeters(dimensions.y, scene)),
        _format_dimension_line("Z", _scene_length_to_millimeters(dimensions.z, scene)),
    ]


def _build_selected_object_dimensions_summary(context):
    obj = _get_active_dimensions_overlay_object(context)
    scene = getattr(context, "scene", None)
    if obj is None or scene is None:
        return None

    dimensions = getattr(obj, "dimensions", None)
    if dimensions is None or len(dimensions) < 3:
        return None

    width = _scene_length_to_millimeters(dimensions.x, scene)
    depth = _scene_length_to_millimeters(dimensions.y, scene)
    height = _scene_length_to_millimeters(dimensions.z, scene)
    if getattr(scene.unit_settings, "system", "METRIC") == "IMPERIAL":
        from .scene_units import format_distance

        return (
            _format_dimensions_overlay_object_name(obj.name),
            " × ".join(format_distance(value, scene) for value in dimensions),
        )
    return (
        _format_dimensions_overlay_object_name(obj.name),
        f"{width:.2f} × {depth:.2f} × {height:.2f} mm",
    )


def _build_mold_metrics_overlay_lines(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return None

    try:
        from .i18n import t
    except Exception:
        def t(value):
            return value

    area = getattr(context, "area", None)
    area_key = area.as_pointer() if area is not None else None
    metrics_mode = _viewport_metrics_modes.get(area_key, "silicone")
    if metrics_mode == "none":
        return []
    from .material_units import format_amount
    mold_volume = max(float(getattr(scene, "volume", 0.0)), 0.0)
    casting_volume = max(float(getattr(scene, "casting_volume_ml", 0.0)), 0.0)
    lines = []
    dimensions_summary = _build_selected_object_dimensions_summary(context)
    if dimensions_summary is not None:
        lines.append(dimensions_summary)
    if metrics_mode == "plaster":
        from .plaster_mix import scene_plaster_mix
        water_ml, plaster_g = scene_plaster_mix(scene)
        mix = f"P {format_amount(plaster_g, 'mass')}, W {format_amount(water_ml, 'volume')}"
        lines.append((t("Mold"), f"{format_amount(mold_volume, 'volume')} ({mix})"))
    elif metrics_mode != "direct":
        from .silicone_mix import scene_silicone_mix
        part_a, part_b = scene_silicone_mix(scene)
        mix = f"A {format_amount(part_a, 'mass')}, B {format_amount(part_b, 'mass')}"
        weight_summary = format_amount(part_a + part_b, "mass")
        if getattr(scene, "silicone_mix_mode", "TWO_PART") != "SINGLE":
            weight_summary = f"{weight_summary} ({mix})"
        lines.append((t("Mold"), weight_summary))

    casting_summary = format_amount(casting_volume, "volume")
    if hasattr(scene, "casting_material_mode"):
        from .casting_material import scene_casting_material
        ingredients = scene_casting_material(scene)
        mode = scene.casting_material_mode
        if mode == "POWDER_WATER":
            mix = f"P {format_amount(ingredients[0][1], 'mass')}, W {format_amount(ingredients[1][1], 'volume')}"
            casting_summary = f"{format_amount(casting_volume, 'volume')} ({mix})"
        elif mode == "TWO_PART":
            part_a, part_b = ingredients[0][1], ingredients[1][1]
            mix = f"A {format_amount(part_a, 'mass')}, B {format_amount(part_b, 'mass')}"
            casting_summary = f"{format_amount(part_a + part_b, 'mass')} ({mix})"
        else:
            casting_summary = format_amount(ingredients[0][1], "mass")
    lines.append((t("Casting"), casting_summary))
    return lines


def set_viewport_metrics_mode(mode: str, context=None) -> None:
    if context is None:
        context = bpy.context
    area = getattr(context, "area", None)
    if area is None or getattr(area, "type", "") != "VIEW_3D":
        return

    area_key = area.as_pointer()
    normalized_mode = mode if mode in {"direct", "none", "plaster"} else "silicone"
    if _viewport_metrics_modes.get(area_key) == normalized_mode:
        return
    _viewport_metrics_modes[area_key] = normalized_mode
    area.tag_redraw()


def _get_mold_metrics_overlay_layout(context):
    lines = _build_mold_metrics_overlay_lines(context)
    if not lines:
        return None

    ui_scale = _get_overlay_ui_scale(context)
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    font_size = _scale_overlay_value(_MOLD_METRICS_OVERLAY_FONT_SIZE, ui_scale)
    padding = _scale_overlay_value(_MOLD_METRICS_OVERLAY_PADDING, ui_scale)
    line_gap = _scale_overlay_value(_MOLD_METRICS_OVERLAY_LINE_GAP, ui_scale)
    column_gap = _scale_overlay_value(_MOLD_METRICS_OVERLAY_COLUMN_GAP, ui_scale)
    blf.size(font_id, font_size)
    text_height = int(blf.dimensions(font_id, "Ag")[1])
    line_step = text_height + line_gap
    label_width = max(int(blf.dimensions(font_id, label)[0]) for label, _ in lines)
    value_width = max(int(blf.dimensions(font_id, value)[0]) for _, value in lines)
    text_width = label_width + column_gap + value_width
    panel_width = text_width + (padding * 2)
    panel_height = (
        (text_height * len(lines))
        + (line_gap * max(0, len(lines) - 1))
        + (padding * 2)
    )
    return {
        "lines": lines,
        "font_id": font_id,
        "font_size": font_size,
        "padding": padding,
        "column_gap": column_gap,
        "text_height": text_height,
        "line_step": line_step,
        "label_width": label_width,
        "width": panel_width,
        "height": panel_height,
    }


def _draw_mold_metrics_overlay(layout, pos_x: int, pos_y: int) -> None:
    if layout is None:
        return

    _draw_styled_overlay_background(
        pos_x,
        pos_y,
        layout["width"],
        layout["height"],
    )

    font_id = layout["font_id"]
    blf.size(font_id, layout["font_size"])
    label_x = pos_x + layout["padding"]
    value_x = label_x + layout["label_width"] + layout["column_gap"]
    baseline_y = (
        pos_y
        + layout["height"]
        - layout["padding"]
        - layout["text_height"]
    )
    for index, (label, value) in enumerate(layout["lines"]):
        line_y = baseline_y - (index * layout["line_step"])
        blf.color(font_id, *_MOLD_METRICS_OVERLAY_LABEL_COLOR)
        blf.position(font_id, label_x, line_y, 0)
        blf.draw(font_id, label)
        blf.color(font_id, *_MOLD_METRICS_OVERLAY_VALUE_COLOR)
        blf.position(font_id, value_x, line_y, 0)
        blf.draw(font_id, value)


def _workflow_instruction_for_state(
    state: str,
    mold_type_identifier: str = "ADAPTED_BOX",
):
    """Return the short title and action used by the viewport coach mark."""
    instruction_type_identifier = (
        "SLIP_CASTING"
        if mold_type_identifier.startswith("SLIP_CASTING")
        else mold_type_identifier
    )
    if state == "FINISHED" and mold_type_identifier == "FIXTURE":
        return (
            "Your fixture is ready",
            (
                "Inspect the fixture and make any final checks."
            ),
        )

    if state == "FINISHED" and mold_type_identifier == "PROTECTIVE_SHELL":
        return (
            "Your Protective Shell is ready",
            (
                "Inspect the shell parts and make any final checks."
            ),
        )

    shared_states = {
        "CASTING_PREPARATION": (
            "Prepare and adjust your master",
            "Prepare and adjust your master",
        ),
        "FOUNDATION": (
            "Position the yellow circle to set the foundation base reference",
            (
                "Position and rotate the yellow circle to define the foundation "
                "base reference, then press Confirm Foundation."
            ),
        ),
        "NO_MODEL": (
            "Import your master",
            "Add your master model to begin.",
        ),
        "CASTING_INPUT": (
            "Place the casting sprue",
            "Adjust the sprue position and size.",
        ),
        "AIR_TRAPS": (
            "Review the air-trap pillars",
            "Adjust the editable pillars.",
        ),
        "MASTER_FILLER": (
            "Refine the master seal",
            (
                "Choose which sealer parts to keep, delete any you do not need "
                "(or use Bulk Remove), refine the remaining parts, then Confirm."
            ),
        ),
        "FINISHED": (
            "Your mold is ready",
            "Inspect the mold system and make any final checks.",
        ),
        "EXPORTED": (
            "Export complete",
            "Select New to start a new mold, or Restart to rebuild the current mold.",
        ),
        "SKIN_CORE": (
            "Review the skin core",
            (
                "Delete any unwanted core base (orange object), set the split "
                "planes and mold settings."
            ),
        ),
        "SKIN_CORE_CONFIRMED": (
            "Inspect the finished skin core",
            (
                "Inspect the joined and smoothed skin core and its wrapper, set "
                "the split planes and mold settings."
            ),
        ),
    }
    if state in shared_states:
        return shared_states[state]

    if state == "EDITABLE_COMPONENTS":
        editable_instructions = {
            "ADAPTED_BOX": (
                "Refine the adapted mold",
                (
                    "Adjust the box, funnel and editable components and add any "
                    "watermarks."
                ),
            ),
            "TRAY_MOLD": (
                "Refine the tray",
                (
                    "Adjust the grip and add any watermarks."
                ),
            ),
            "TWO_PART_SILICONE": (
                "Refine the two-part mold",
                (
                    "Adjust both mold halves and their editable components."
                ),
            ),
            "INNER_CAVITY": (
                "Refine the inner-core mold",
                (
                    "Adjust the box and editable components and add any "
                    "watermarks."
                ),
            ),
            "SLIP_CASTING": (
                "Refine the adapted mold",
                (
                    "Adjust the box, funnel and editable components and add any "
                    "watermarks."
                ),
            ),
            "DIRECT_MOLD_OPEN_BASE": (
                "Refine the direct mold",
                (
                    "Adjust the pillars and opening and add any watermarks."
                ),
            ),
            "DIRECT_MOLD_TOP_FUNNEL": (
                "Refine the direct mold",
                (
                    "Adjust the pillars and funnels and add any watermarks."
                ),
            ),
            "DIRECT_MOLD_SKIN": (
                "Refine the direct mold",
                (
                    "Adjust the pillars and opening and add any watermarks."
                ),
            ),
        }
        return editable_instructions.get(
            instruction_type_identifier,
            (
                "Refine the mold system",
                (
                    "Adjust the editable components and add any watermarks."
                ),
            ),
        )

    if state == "ADVANCED_READY":
        advanced_ready_instructions = {
            "ADAPTED_BOX": (
                "Build the editable mold system",
                (
                    "Orient your master and adjust the split planes and settings."
                ),
            ),
            "TRAY_MOLD": (
                "Build the editable tray",
                (
                    "Orient your master and adjust the tray settings."
                ),
            ),
            "TWO_PART_SILICONE": (
                "Build the editable two-part mold",
                (
                    "Orient your master and adjust the split planes and settings."
                ),
            ),
            "INNER_CAVITY": (
                "Build the editable inner-core mold",
                (
                    "Orient your master and adjust the split planes and settings."
                ),
            ),
            "SLIP_CASTING": (
                "Set the splits and settings.",
                "Set the splits and settings.",
            ),
            "DIRECT_MOLD_OPEN_BASE": (
                "Build the editable direct mold",
                (
                    "Orient your master and adjust the split planes and settings. "
                    "If both the mold and casting materials are solid, it's "
                    "recommended to use Clear Undercuts in the Utils panel first."
                ),
            ),
            "DIRECT_MOLD_TOP_FUNNEL": (
                "Build the editable direct mold",
                (
                    "Orient your master and adjust the split planes, funnel guides "
                    "and settings. If both the mold and casting materials are "
                    "solid, it's recommended to use Clear Undercuts in the Utils "
                    "panel first."
                ),
            ),
        }
        return advanced_ready_instructions.get(
            instruction_type_identifier,
            (
                "Build the editable mold system",
                "Adjust the master and settings.",
            ),
        )

    ready_instructions = {
        "TRAY_MOLD": (
            "Set up your tray mold",
            (
                "Orient your master and adjust the tray settings."
            ),
        ),
        "TWO_PART_SILICONE": (
            "Set up your two-part mold",
            (
                "Orient your master and adjust the split planes and settings."
            ),
        ),
        "INNER_CAVITY": (
            "Set up your inner-core mold",
            (
                "Orient your master and adjust the split planes and settings."
            ),
        ),
        "SLIP_CASTING": (
            "Set the splits and settings.",
            "Set the splits and settings.",
        ),
        "DIRECT_MOLD_OPEN_BASE": (
            "Set up your direct mold",
            (
                "Orient your master and adjust the split planes and settings. If "
                "both the mold and casting materials are solid, it's recommended "
                "to use Clear Undercuts in the Utils panel first."
            ),
        ),
        "DIRECT_MOLD_TOP_FUNNEL": (
            "Set up your direct mold",
            (
                "Orient your master and adjust the split planes, funnel guides "
                "and settings. If both the mold and casting materials are solid, "
                "it's recommended to use Clear Undercuts in the Utils panel first."
            ),
        ),
        "DIRECT_MOLD_SKIN": (
            "Set the base reference by positioning the yellow circle",
            (
                "Orient your master and set the Base Reference Height. If both "
                "the mold and casting materials are solid, it's recommended to use "
                "Clear Undercuts in the Utils panel first."
            ),
        ),
    }
    return ready_instructions.get(
        instruction_type_identifier,
        (
            "Set up your silicone mold",
            (
                "Orient your master and adjust the split planes and settings."
            ),
        ),
    )


def _object_is_workflow_helper(obj) -> bool:
    try:
        object_name = str(getattr(obj, "name", "")).casefold()
        is_helper = any(
            bool(obj.get(key))
            for key in (
                "moldboxer_direct_split_plane",
                "moldboxer_direct_split_plane_contour",
                "moldboxer_skin_base_reference_guide",
                "moldboxer_fixture_height_guide",
            )
        )
    except (AttributeError, ReferenceError, TypeError):
        return False
    return bool(
        is_helper
        or object_name.startswith("direct_split_plane")
        or "reference_height_guide" in object_name
        or object_name.startswith("fixture_height_guide")
    )


def _iter_live_scene_objects(scene):
    """Resolve names afresh; never suspend a live RNA iterator across a yield."""
    objects = getattr(scene, "objects", ())
    keys = getattr(objects, "keys", None)
    if callable(keys):
        # A consumer can join/delete objects between yields. Retain only names,
        # not an RNA iterator with a prefetched pointer to the next object.
        names = tuple(keys())
        for name in names:
            obj = objects.get(name)
            if obj is not None:
                yield obj
        return
    # Plain Python collections are used by tests and source-reload tooling.
    for obj in tuple(objects):
        try:
            getattr(obj, "name", "")
        except ReferenceError:
            continue
        yield obj


def _scene_has_workflow_model(scene) -> bool:
    return any(
        getattr(obj, "type", None) == "MESH"
        and not _object_is_workflow_helper(obj)
        for obj in _iter_live_scene_objects(scene)
    )


def _scene_has_named_object(scene, predicate) -> bool:
    return any(
        predicate(str(getattr(obj, "name", "")).casefold(), obj)
        for obj in _iter_live_scene_objects(scene)
    )


def _scene_has_finished_mold_system(scene, mold_type_identifier: str) -> bool:
    if mold_type_identifier == "FIXTURE":
        return _scene_has_named_object(
            scene,
            lambda name, _obj: name in {"fixture", "box"}
            or name.startswith("box_part_"),
        )
    if mold_type_identifier == "PROTECTIVE_SHELL":
        return _scene_has_named_object(
            scene,
            lambda name, obj: name == "protective_shell"
            or name.startswith("protective_shell_part_")
            or bool(
                getattr(obj, "get", lambda *_args: False)(
                    "moldboxer_protective_shell",
                    False,
                )
            ),
        )
    if mold_type_identifier.startswith("DIRECT_MOLD_"):
        return _scene_has_named_object(
            scene,
            lambda name, _obj: name.startswith(
                ("box_part_", "left_box", "right_box", "box_l", "box_r")
            ),
        )
    if mold_type_identifier == "TWO_PART_SILICONE":
        objects = getattr(scene, "objects", None)
        return bool(
            objects is not None
            and objects.get("left_silicone_mold") is not None
            and objects.get("right_silicone_mold") is not None
        )
    if mold_type_identifier == "SILICONE_MULTIPART":
        return _scene_has_named_object(scene, lambda name, _obj: name.startswith("silicone_mold_part_"))
    if mold_type_identifier.startswith("SLIP_CASTING"):
        return _scene_has_named_object(
            scene,
            lambda name, _obj: name == "plaster_mold"
            or name.startswith("plaster_mold_part_"),
        )
    objects = getattr(scene, "objects", None)
    return bool(objects is not None and objects.get("silicone_mold") is not None)


def _advanced_workflow_enabled(scene, mold_type_identifier: str) -> bool:
    if not bool(getattr(scene, "mold_advanced_mode", False)):
        return False
    try:
        from .operator_access import is_lite_tier

        return not is_lite_tier()
    except Exception:
        return True


def _build_workflow_instruction(context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    if bool(
        getattr(scene, "get", lambda *_args: False)(
            "_moldboxer_export_in_progress",
            False,
        )
    ):
        return None

    mold_type_identifier = str(
        getattr(scene, "mold_type_preview", "ADAPTED_BOX") or "ADAPTED_BOX"
    )
    advanced_workflow = _advanced_workflow_enabled(
        scene,
        mold_type_identifier,
    )
    if bool(
        getattr(scene, "get", lambda *_args: False)(
            "_moldboxer_foundation_guide_active",
            False,
        )
    ):
        state = "FOUNDATION"
    elif _scene_has_named_object(
        scene,
        lambda name, obj: getattr(obj, "type", None) == "MESH"
        and name.startswith("casting_input"),
    ):
        state = "CASTING_INPUT"
    elif _scene_has_named_object(
        scene,
        lambda name, obj: getattr(obj, "type", None) == "MESH"
        and name.startswith("master_air_trap_pilar"),
    ):
        state = "AIR_TRAPS"
    elif _scene_has_named_object(scene, lambda name, _obj: "filler" in name):
        state = "MASTER_FILLER"
    elif _scene_has_finished_mold_system(scene, mold_type_identifier):
        state = "FINISHED"
    elif not _scene_has_workflow_model(scene):
        state = "NO_MODEL"
    elif (
        mold_type_identifier == "DIRECT_MOLD_SKIN"
        and _scene_has_named_object(
            scene,
            lambda name, obj: name == "skin_core"
            and getattr(obj, "type", None) == "MESH"
            and bool(getattr(obj, "get", lambda *_: False)("moldboxer_skin_core")),
        )
    ):
        skin_core = getattr(scene, "objects", None).get("skin_core")
        if advanced_workflow and _scene_has_named_object(
            scene,
            lambda name, _obj: name in {"box", "left_box", "right_box"},
        ):
            state = "EDITABLE_COMPONENTS"
        else:
            state = (
                "SKIN_CORE_CONFIRMED"
                if bool(
                    getattr(skin_core, "get", lambda *_: False)(
                        "moldboxer_skin_core_confirmed",
                        False,
                    )
                )
                else "SKIN_CORE"
            )
    elif mold_type_identifier == "DIRECT_MOLD_SKIN":
        state = "READY"
    elif advanced_workflow:
        if _scene_has_named_object(
            scene,
            lambda name, _obj: name in {"box", "left_box", "right_box"},
        ):
            state = "EDITABLE_COMPONENTS"
        else:
            state = "ADVANCED_READY"
    else:
        state = "READY"

    if state == "FINISHED" and bool(
        getattr(scene, "get", lambda *_args: False)(
            "_moldboxer_export_completed",
            False,
        )
    ):
        state = "EXPORTED"

    if (
        state in {"READY", "ADVANCED_READY"}
        and mold_type_identifier.startswith("SLIP_CASTING")
        and not bool(
            getattr(scene.objects.get("patron"), "get", lambda *_: False)(
                "moldboxer_slip_casting_funnels_built", False
            )
        )
    ):
        # Preparation remains complete even when its feet and funnels are deleted.
        state = "CASTING_PREPARATION"

    if state == "READY" and mold_type_identifier == "FIXTURE":
        title, body = (
            "Set the fixture height",
            (
                "Position and rotate the fixture height plane, adjust the "
                "fixture settings."
            ),
        )
    elif state == "READY" and mold_type_identifier == "PROTECTIVE_SHELL":
        title, body = (
            "Set the Protective Shell splits",
            (
                "Position the split planes, adjust the shell and clamp "
                "settings."
            ),
        )
    else:
        title, body = _workflow_instruction_for_state(
            state,
            mold_type_identifier,
        )
    try:
        from .i18n import t

        return t(title), t(body)
    except Exception:
        return title, body


def get_viewport_workflow_instruction(context):
    """Return workflow copy only while the combined action card may be shown."""

    if _modal_progress_overlay_active_count:
        return None
    return _build_workflow_instruction(context)


def _wrap_overlay_text(text: str, font_id: int, max_width: int) -> list[str]:
    words = str(text).split()
    if not words:
        return []

    lines = []
    current_line = words[0]
    for word in words[1:]:
        candidate = f"{current_line} {word}"
        if blf.dimensions(font_id, candidate)[0] <= max_width:
            current_line = candidate
            continue
        lines.append(current_line)
        current_line = word
    lines.append(current_line)
    return lines


def _draw_workflow_instruction_overlay(context, region) -> None:
    instruction = _build_workflow_instruction(context)
    if instruction is None:
        return

    title, body = instruction
    ui_scale = _get_overlay_ui_scale(context)
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    title_font_size = _scale_overlay_value(
        _INSTRUCTION_OVERLAY_TITLE_FONT_SIZE,
        ui_scale,
    )
    body_font_size = _scale_overlay_value(
        _INSTRUCTION_OVERLAY_BODY_FONT_SIZE,
        ui_scale,
    )
    padding = _scale_overlay_value(_MOLD_METRICS_OVERLAY_PADDING, ui_scale)
    line_gap = _scale_overlay_value(_INSTRUCTION_OVERLAY_LINE_GAP, ui_scale)
    section_gap = _scale_overlay_value(_INSTRUCTION_OVERLAY_SECTION_GAP, ui_scale)
    corner_margin = _scale_overlay_value(_DIMENSIONS_OVERLAY_CORNER_MARGIN, ui_scale)
    top_offset = _scale_overlay_value(_PROGRESS_OVERLAY_TOP_OFFSET, ui_scale)
    region_width = int(getattr(region, "width", 0) or 800)
    region_height = int(getattr(region, "height", 0) or 600)
    max_text_width = max(
        1,
        min(
            _scale_overlay_value(_INSTRUCTION_OVERLAY_MAX_TEXT_WIDTH, ui_scale),
            region_width - (corner_margin * 2) - (padding * 2),
        ),
    )

    blf.size(font_id, title_font_size)
    title_width = int(blf.dimensions(font_id, title)[0])
    title_height = max(1, int(blf.dimensions(font_id, "Ag")[1]))
    blf.size(font_id, body_font_size)
    body_lines = _wrap_overlay_text(body, font_id, max_text_width)
    body_height = max(1, int(blf.dimensions(font_id, "Ag")[1]))
    body_width = max(
        (int(blf.dimensions(font_id, line)[0]) for line in body_lines),
        default=0,
    )
    panel_width = max(title_width, body_width) + (padding * 2)
    body_block_height = (
        (body_height * len(body_lines))
        + (line_gap * max(0, len(body_lines) - 1))
    )
    panel_height = (
        (padding * 2)
        + title_height
        + section_gap
        + body_block_height
    )
    pos_x = max(corner_margin, (region_width - panel_width) // 2)
    pos_y = max(corner_margin, region_height - top_offset - panel_height)

    _draw_styled_overlay_background(pos_x, pos_y, panel_width, panel_height)
    text_x = pos_x + padding
    title_y = pos_y + panel_height - padding - title_height
    blf.size(font_id, title_font_size)
    blf.color(font_id, *_DIMENSIONS_OVERLAY_TEXT_COLOR)
    blf.position(font_id, text_x, title_y, 0)
    blf.draw(font_id, title)

    blf.size(font_id, body_font_size)
    body_y = title_y - section_gap - body_height
    for index, line in enumerate(body_lines):
        blf.color(font_id, *_DIMENSIONS_OVERLAY_SECONDARY_TEXT_COLOR)
        blf.position(font_id, text_x, body_y - (index * (body_height + line_gap)), 0)
        blf.draw(font_id, line)


def set_modal_progress_overlay_active(active: bool, context=None) -> None:
    """Reserve the top-center overlay slot while modal progress is visible."""
    global _modal_progress_overlay_active_count
    if active:
        _modal_progress_overlay_active_count += 1
    else:
        _modal_progress_overlay_active_count = max(
            0,
            _modal_progress_overlay_active_count - 1,
        )
    _tag_view3d_areas_for_redraw(context or bpy.context)


def _get_viewport_display_version() -> str:
    global _viewport_display_version
    if _viewport_display_version is not None:
        return _viewport_display_version

    manifest_path = Path(__file__).resolve().parent.parent / "blender_manifest.toml"
    try:
        with manifest_path.open("rb") as manifest_file:
            _viewport_display_version = str(
                tomllib.load(manifest_file).get("version", "")
            ).strip()
    except Exception:
        _viewport_display_version = ""
    return _viewport_display_version


def _get_identity_status_text() -> str:
    try:
        from .components.auth import get_login_status_text
        from .environment import get_addon_preferences
        from .i18n import t

        prefs = get_addon_preferences()
        if prefs is None:
            return t("Account state unavailable")
        if bool(getattr(prefs, "auth_polling_active", False)):
            return t("Waiting for login confirmation...")
        if not bool(getattr(prefs, "auth_logged_in", False)):
            return t("Not logged in")
        return get_login_status_text(
            str(getattr(prefs, "auth_provider", "")),
            str(getattr(prefs, "auth_tier", "")),
            str(getattr(prefs, "auth_stripe_status", "")),
        )
    except Exception:
        return "Account state unavailable"


def _get_identity_overlay_layout(context=None):
    ui_scale = _get_overlay_ui_scale(context)
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    font_size = _scale_overlay_value(_IDENTITY_OVERLAY_FONT_SIZE, ui_scale)
    padding = _scale_overlay_value(_DIMENSIONS_OVERLAY_PADDING, ui_scale)
    line_gap = _scale_overlay_value(_IDENTITY_OVERLAY_LINE_GAP, ui_scale)
    logo_size = _scale_overlay_value(_IDENTITY_OVERLAY_LOGO_SIZE, ui_scale)
    logo_gap = _scale_overlay_value(_IDENTITY_OVERLAY_LOGO_GAP, ui_scale)
    blf.size(font_id, font_size)
    version = _get_viewport_display_version()
    title = f"Moldboxer {version}" if version else "Moldboxer"
    status = _get_identity_status_text()
    text_height = max(1, int(blf.dimensions(font_id, "Ag")[1]))
    text_width = max(
        int(blf.dimensions(font_id, title)[0]),
        int(blf.dimensions(font_id, status)[0]),
    )
    text_block_height = (text_height * 2) + line_gap
    content_height = max(logo_size, text_block_height)
    return {
        "font_id": font_id,
        "font_size": font_size,
        "padding": padding,
        "line_gap": line_gap,
        "logo_size": logo_size,
        "logo_gap": logo_gap,
        "title": title,
        "status": status,
        "text_height": text_height,
        "text_block_height": text_block_height,
        "width": (
            (padding * 2)
            + logo_size
            + logo_gap
            + text_width
        ),
        "height": content_height + (padding * 2),
    }


def _draw_identity_overlay(layout, pos_x: int, pos_y: int) -> None:
    _draw_styled_overlay_background(
        pos_x,
        pos_y,
        layout["width"],
        layout["height"],
    )

    logo_x = pos_x + layout["padding"]
    logo_y = pos_y + int((layout["height"] - layout["logo_size"]) / 2)
    texture = _get_viewport_logo_texture()
    if texture is not None:
        try:
            import gpu  # type: ignore
            from gpu_extras.presets import draw_texture_2d  # type: ignore

            gpu.state.blend_set("ALPHA")
            draw_texture_2d(
                texture,
                (logo_x, logo_y),
                layout["logo_size"],
                layout["logo_size"],
            )
            gpu.state.blend_set("NONE")
        except Exception:
            try:
                gpu.state.blend_set("NONE")
            except Exception:
                pass

    text_x = logo_x + layout["logo_size"] + layout["logo_gap"]
    text_bottom = pos_y + int((layout["height"] - layout["text_block_height"]) / 2)
    font_id = layout["font_id"]
    blf.size(font_id, layout["font_size"])
    blf.color(font_id, *_DIMENSIONS_OVERLAY_TEXT_COLOR)
    blf.position(
        font_id,
        text_x,
        text_bottom + layout["text_height"] + layout["line_gap"],
        0,
    )
    blf.draw(font_id, layout["title"])
    blf.color(font_id, *_DIMENSIONS_OVERLAY_SECONDARY_TEXT_COLOR)
    blf.position(font_id, text_x, text_bottom, 0)
    blf.draw(font_id, layout["status"])


def _draw_styled_overlay_background(x: int, y: int, width: int, height: int) -> None:
    ui_scale = _get_overlay_ui_scale()
    corner_radius = _scale_overlay_value(_DIMENSIONS_OVERLAY_CORNER_RADIUS, ui_scale)
    border_width = _scale_overlay_value(_DIMENSIONS_OVERLAY_BORDER_WIDTH, ui_scale)
    accent_width = _scale_overlay_value(_DIMENSIONS_OVERLAY_ACCENT_WIDTH, ui_scale)
    _draw_overlay_background(
        x,
        y,
        width,
        height,
        corner_radius=corner_radius,
        border_color=_DIMENSIONS_OVERLAY_BORDER_COLOR,
        border_width=border_width,
    )
    accent_y = y + corner_radius
    accent_height = height - (corner_radius * 2)
    if accent_height > 0:
        _draw_overlay_background(
            x + border_width,
            accent_y,
            accent_width,
            accent_height,
            color=_DIMENSIONS_OVERLAY_ACCENT_COLOR,
            corner_radius=_scale_overlay_value(1, ui_scale),
        )


def draw_modal_progress_overlay(
    label: str,
    elapsed_seconds: float,
    region=None,
) -> None:
    """Draw modal progress in the same styled panel as the mold metrics."""
    ui_scale = _get_overlay_ui_scale()
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    font_size = _scale_overlay_value(_MOLD_METRICS_OVERLAY_FONT_SIZE, ui_scale)
    padding = _scale_overlay_value(_MOLD_METRICS_OVERLAY_PADDING, ui_scale)
    line_gap = _scale_overlay_value(_MOLD_METRICS_OVERLAY_LINE_GAP, ui_scale)
    corner_margin = _scale_overlay_value(_DIMENSIONS_OVERLAY_CORNER_MARGIN, ui_scale)
    top_offset = _scale_overlay_value(_PROGRESS_OVERLAY_TOP_OFFSET, ui_scale)
    lines = (
        (str(label), _MOLD_METRICS_OVERLAY_VALUE_COLOR),
        (f"{elapsed_seconds:.1f}s", _MOLD_METRICS_OVERLAY_LABEL_COLOR),
    )

    blf.size(font_id, font_size)
    text_height = max(1, int(blf.dimensions(font_id, "Ag")[1]))
    text_width = max(int(blf.dimensions(font_id, text)[0]) for text, _ in lines)
    panel_width = text_width + (padding * 2)
    panel_height = (text_height * len(lines)) + line_gap + (padding * 2)

    region_width = int(getattr(region, "width", 0) or 800)
    region_height = int(getattr(region, "height", 0) or 600)
    pos_x = max(corner_margin, (region_width - panel_width) // 2)
    pos_y = max(
        corner_margin,
        region_height - top_offset - panel_height,
    )

    _draw_styled_overlay_background(pos_x, pos_y, panel_width, panel_height)

    baseline_y = pos_y + panel_height - padding - text_height
    line_step = text_height + line_gap
    for index, (text, color) in enumerate(lines):
        text_x = pos_x + padding
        if index == 1:
            line_width = int(blf.dimensions(font_id, text)[0])
            text_x = pos_x + ((panel_width - line_width) // 2)
        blf.color(font_id, *color)
        blf.position(font_id, text_x, baseline_y - (index * line_step), 0)
        blf.draw(font_id, text)


def _draw_overlay_background(
    x: int,
    y: int,
    width: int,
    height: int,
    color=None,
    corner_radius: int = 0,
    border_color=None,
    border_width: int = 0,
) -> None:
    if border_color is not None and border_width > 0:
        inset = min(int(border_width), width // 2, height // 2)
        _draw_overlay_background(
            x,
            y,
            width,
            height,
            color=border_color,
            corner_radius=corner_radius,
        )
        if inset > 0:
            _draw_overlay_background(
                x + inset,
                y + inset,
                width - (inset * 2),
                height - (inset * 2),
                color=color,
                corner_radius=max(0, corner_radius - inset),
            )
        return

    try:
        import gpu  # type: ignore
        from gpu_extras.batch import batch_for_shader  # type: ignore

        if color is None:
            color = _DIMENSIONS_OVERLAY_BACKGROUND_COLOR

        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        radius = max(0.0, min(float(corner_radius), width / 2, height / 2))
        if radius:
            perimeter = []
            corner_centers = (
                (x + radius, y + radius, math.pi, math.pi * 1.5),
                (x + width - radius, y + radius, math.pi * 1.5, math.pi * 2),
                (x + width - radius, y + height - radius, 0.0, math.pi * 0.5),
                (x + radius, y + height - radius, math.pi * 0.5, math.pi),
            )
            corner_segments = 6
            for center_x, center_y, start_angle, end_angle in corner_centers:
                for step in range(corner_segments + 1):
                    angle = start_angle + (
                        (end_angle - start_angle) * step / corner_segments
                    )
                    perimeter.append(
                        (
                            center_x + (math.cos(angle) * radius),
                            center_y + (math.sin(angle) * radius),
                        )
                    )
            center = (x + (width / 2), y + (height / 2))
            vertices = []
            for index, point in enumerate(perimeter):
                vertices.extend((center, point, perimeter[(index + 1) % len(perimeter)]))
            primitive = "TRIS"
        else:
            vertices = (
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            )
            primitive = "TRI_FAN"
        batch = batch_for_shader(
            shader,
            primitive,
            {"pos": vertices},
        )
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)
        gpu.state.blend_set("NONE")
    except Exception:
        try:
            import gpu  # type: ignore

            gpu.state.blend_set("NONE")
        except Exception:
            pass


def _object_is_visible_in_context(obj, context) -> bool:
    if obj is None:
        return False
    object_type = getattr(obj, "type", None)
    if (
        object_type not in _DIMENSIONS_OVERLAY_SUPPORTED_TYPES
        and not (
            object_type == "CURVE"
            and _object_is_funnel_reference_line(obj)
        )
    ):
        return False

    try:
        if obj.hide_get():
            return False
    except Exception:
        pass

    try:
        if not obj.visible_get(view_layer=getattr(context, "view_layer", None)):
            return False
    except TypeError:
        try:
            if not obj.visible_get():
                return False
        except Exception:
            pass
    except Exception:
        pass

    return True


def _object_name_label_base_name(name: str) -> str:
    normalized_name = name.strip().casefold()
    suffix_separator = normalized_name.rfind(".")
    if suffix_separator == -1:
        return normalized_name

    suffix = normalized_name[suffix_separator + 1 :]
    if len(suffix) == 3 and suffix.isdecimal():
        return normalized_name[:suffix_separator]
    return normalized_name


def _object_name_should_be_labeled(obj) -> bool:
    if _object_is_direct_split_plane(obj):
        return True
    base_name = _object_name_label_base_name(str(getattr(obj, "name", "")))
    if base_name in _OBJECT_NAME_LABEL_ALLOWED_NAMES:
        return True
    return base_name.startswith(_OBJECT_NAME_LABEL_ALLOWED_PREFIXES)


def _scene_has_visible_labeled_silicone_mold(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False

    for obj in _iter_live_scene_objects(scene):
        base_name = _object_name_label_base_name(str(getattr(obj, "name", "")))
        if (
            base_name == "silicone_mold"
            or base_name == "plaster_mold"
            or base_name.startswith("plaster_mold_part_")
        ) and _object_is_visible_in_context(obj, context):
            return True
    return False


def _scene_has_visible_skin_base_reference_guide(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    for obj in _iter_live_scene_objects(scene):
        if (
            _object_name_label_base_name(str(getattr(obj, "name", "")))
            == "skin_base_reference_height_guide"
            and _object_is_visible_in_context(obj, context)
        ):
            return True
    return False


def _object_is_labeled_editable_guide(obj) -> bool:
    """Return whether an editable Moldboxer guide owns a persistent label."""
    return bool(
        _object_is_direct_split_plane(obj)
        or _object_is_funnel_reference_line(obj)
        or _object_is_skin_base_reference_guide(obj)
        or _object_is_fixture_height_guide(obj)
    )


def _object_is_selected_or_active(obj, context) -> bool:
    """Return whether a label should receive the viewport's active treatment."""
    active_object = getattr(context, "active_object", None)
    if active_object is None:
        view_layer = getattr(context, "view_layer", None)
        active_object = getattr(getattr(view_layer, "objects", None), "active", None)
    if obj is active_object:
        return True
    try:
        return bool(obj.select_get())
    except Exception:
        return False


def _object_uses_compact_guide_label(obj) -> bool:
    """Use the compact quiet badge for editable Moldboxer reference objects."""
    return bool(
        _object_is_direct_split_plane(obj)
        or _object_is_funnel_reference_line(obj)
        or _object_is_skin_base_reference_guide(obj)
        or _object_is_fixture_height_guide(obj)
    )


def _scene_has_visible_labeled_editable_guide(context) -> bool:
    scene = getattr(context, "scene", None)
    if scene is None:
        return False
    return any(
        _object_is_labeled_editable_guide(obj)
        and _object_is_visible_in_context(obj, context)
        for obj in _iter_live_scene_objects(scene)
    )


def _translate_object_name_label(label: str) -> str:
    try:
        from .i18n import t

        return t(label)
    except Exception:
        return label


def _format_object_name_label(name: str) -> str:
    base_name = _object_name_label_base_name(name)
    display_name = _OBJECT_NAME_LABEL_DISPLAY_NAMES.get(base_name)
    if base_name == "skin_base_reference_height_guide":
        scene = getattr(bpy.context, "scene", None)
        if scene is not None and scene.get(
            "_moldboxer_foundation_guide_active",
            False,
        ):
            display_name = "Foundation Base Reference"
    if display_name is not None:
        return _translate_object_name_label(display_name)

    split_plane_prefix = "direct_split_plane_"
    if base_name.startswith(split_plane_prefix):
        suffix_parts = base_name[len(split_plane_prefix) :].split("_")
        axis = suffix_parts[0].upper() if suffix_parts else ""
        try:
            index = str(int(suffix_parts[1]))
        except (IndexError, TypeError, ValueError):
            index = ""
        scene = getattr(bpy.context, "scene", None)
        if axis in {"X", "Y"}:
            if axis == "Y" and index:
                index = str(int(index) + int(getattr(scene, "direct_split_y", 0)))
            axis = _translate_object_name_label("Radial")
        elif axis == "Z":
            axis = _translate_object_name_label("Horizontal")
        label = " ".join(
            part
            for part in (
                _translate_object_name_label("Split"),
                axis,
                index,
            )
            if part
        )
        return label

    label = base_name.replace("_", " ").strip()
    if not label:
        return ""
    return _translate_object_name_label(
        " ".join(word.capitalize() for word in label.split())
    )


def _get_object_bottom_label_location(obj):
    bound_box = getattr(obj, "bound_box", None)
    matrix_world = getattr(obj, "matrix_world", None)
    if bound_box is None or matrix_world is None:
        return getattr(obj, "location", None)

    try:
        corners = [matrix_world @ Vector(corner) for corner in bound_box]
    except Exception:
        return getattr(obj, "location", None)

    if not corners:
        return getattr(obj, "location", None)

    min_z = min(corner.z for corner in corners)
    center_x = sum(corner.x for corner in corners) / len(corners)
    center_y = sum(corner.y for corner in corners) / len(corners)
    return Vector((center_x, center_y, min_z))


def _get_object_name_label_screen_location(
    obj,
    region,
    region_data,
    project_world_location,
):
    if _object_is_labeled_editable_guide(obj):
        bound_box = getattr(obj, "bound_box", None)
        matrix_world = getattr(obj, "matrix_world", None)
        if bound_box is not None and matrix_world is not None:
            try:
                projected_corners = [
                    project_world_location(
                        region,
                        region_data,
                        matrix_world @ Vector(corner),
                    )
                    for corner in bound_box
                ]
            except Exception:
                projected_corners = []
            projected_corners = [
                point for point in projected_corners if point is not None
            ]
            if projected_corners:
                if _object_is_direct_split_plane(obj):
                    return max(
                        projected_corners,
                        key=lambda point: (
                            point.x - point.y,
                            point.x,
                            -point.y,
                        ),
                    )
                max_x = max(point.x for point in projected_corners)
                min_y = min(point.y for point in projected_corners)
                max_y = max(point.y for point in projected_corners)
                return Vector((max_x, (min_y + max_y) / 2.0))

    world_location = _get_object_bottom_label_location(obj)
    if world_location is None:
        return None
    try:
        return project_world_location(region, region_data, world_location)
    except Exception:
        return None


def _draw_object_name_labels(context, region, region_data) -> None:
    scene = getattr(context, "scene", None)
    if scene is None or region_data is None:
        return
    show_all_object_labels = _scene_has_visible_labeled_silicone_mold(context)
    show_editable_guide_labels = (
        _scene_has_visible_skin_base_reference_guide(context)
        or _scene_has_visible_labeled_editable_guide(context)
    )
    if not show_all_object_labels and not show_editable_guide_labels:
        return

    try:
        from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore
    except Exception:
        return

    ui_scale = _get_overlay_ui_scale(context)
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    offset_y = _scale_overlay_value(_OBJECT_NAME_LABEL_OFFSET_Y, ui_scale)
    for obj in _iter_live_scene_objects(scene):
        try:
            getattr(obj, "name", "")
        except ReferenceError:
            continue
        if not _object_is_visible_in_context(obj, context):
            continue
        if not _object_name_should_be_labeled(obj):
            continue
        if (
            not show_all_object_labels
            and not _object_is_labeled_editable_guide(obj)
        ):
            continue

        editable_guide = _object_is_labeled_editable_guide(obj)
        label_is_active = _object_is_selected_or_active(obj, context)
        if not editable_guide and not label_is_active:
            continue

        label = _format_object_name_label(str(getattr(obj, "name", "")))
        if not label:
            continue

        screen_location = _get_object_name_label_screen_location(
            obj,
            region,
            region_data,
            location_3d_to_region_2d,
        )
        if screen_location is None:
            continue

        compact_guide_label = _object_uses_compact_guide_label(obj)
        font_size = _scale_overlay_value(
            _GUIDE_LABEL_FONT_SIZE
            if compact_guide_label
            else _OBJECT_NAME_LABEL_FONT_SIZE,
            ui_scale,
        )
        padding_x = _scale_overlay_value(
            _GUIDE_LABEL_PADDING_X
            if compact_guide_label
            else _OBJECT_NAME_LABEL_PADDING_X,
            ui_scale,
        )
        padding_y = _scale_overlay_value(
            _GUIDE_LABEL_PADDING_Y
            if compact_guide_label
            else _OBJECT_NAME_LABEL_PADDING_Y,
            ui_scale,
        )
        min_height = _scale_overlay_value(
            _GUIDE_LABEL_MIN_HEIGHT
            if compact_guide_label
            else _OBJECT_NAME_LABEL_MIN_HEIGHT,
            ui_scale,
        )
        background_color = (
            _GUIDE_LABEL_BACKGROUND_COLOR
            if compact_guide_label
            else _OBJECT_NAME_LABEL_BACKGROUND_COLOR
        )
        border_color = (
            _GUIDE_LABEL_BORDER_COLOR
            if compact_guide_label
            else _OBJECT_NAME_LABEL_BORDER_COLOR
        )
        text_color = (
            _GUIDE_LABEL_TEXT_COLOR
            if compact_guide_label
            else _OBJECT_NAME_LABEL_TEXT_COLOR
        )
        if compact_guide_label and label_is_active:
            background_color = _GUIDE_LABEL_ACTIVE_BACKGROUND_COLOR
            border_color = _GUIDE_LABEL_ACTIVE_BORDER_COLOR
            text_color = _GUIDE_LABEL_ACTIVE_TEXT_COLOR
        border_width = max(
            1.0,
            (
                _GUIDE_LABEL_BORDER_WIDTH
                if compact_guide_label
                else _OBJECT_NAME_LABEL_BORDER_WIDTH
            )
            * ui_scale,
        )
        shadow_offset = _scale_overlay_value(
            _GUIDE_LABEL_SHADOW_OFFSET
            if compact_guide_label
            else _OBJECT_NAME_LABEL_SHADOW_OFFSET,
            ui_scale,
        )
        shadow_color = (
            _GUIDE_LABEL_SHADOW_COLOR
            if compact_guide_label
            else _OBJECT_NAME_LABEL_SHADOW_COLOR
        )
        corner_radius = _scale_overlay_value(
            _GUIDE_LABEL_CORNER_RADIUS
            if compact_guide_label
            else _OBJECT_NAME_LABEL_CORNER_RADIUS,
            ui_scale,
        )
        blf.size(font_id, font_size)
        text_height = max(1, int(blf.dimensions(font_id, "Ag")[1]))
        text_width = int(blf.dimensions(font_id, label)[0])
        label_width = text_width + (padding_x * 2)
        label_height = max(min_height, text_height + (padding_y * 2))
        if _object_is_direct_split_plane(obj):
            pos_x = int(screen_location.x + border_width)
            pos_y = int(screen_location.y - label_height - border_width)
        elif _object_is_labeled_editable_guide(obj):
            pos_x = int(screen_location.x + border_width)
            pos_y = int(screen_location.y - label_height / 2)
        else:
            pos_x = int(screen_location.x - (label_width / 2))
            pos_y = int(screen_location.y - label_height - offset_y)

        if (
            pos_x + label_width < 0
            or pos_x > region.width
            or pos_y + label_height < 0
            or pos_y > region.height
        ):
            continue

        border_x = pos_x - border_width
        border_y = pos_y - border_width
        border_label_width = label_width + (border_width * 2)
        border_label_height = label_height + (border_width * 2)
        _draw_overlay_background(
            border_x + shadow_offset,
            border_y - shadow_offset,
            border_label_width,
            border_label_height,
            shadow_color,
            corner_radius=corner_radius,
        )
        _draw_overlay_background(
            border_x,
            border_y,
            border_label_width,
            border_label_height,
            border_color,
            corner_radius=corner_radius,
        )
        _draw_overlay_background(
            pos_x,
            pos_y,
            label_width,
            label_height,
            background_color,
            corner_radius=max(0, corner_radius - int(math.ceil(border_width))),
        )
        blf.color(font_id, *text_color)
        blf.position(
            font_id,
            pos_x + padding_x,
            pos_y + ((label_height - text_height) / 2),
            0,
        )
        blf.draw(font_id, label)


def _get_dimensions_overlay_layout(context):
    lines = _build_dimensions_overlay_lines(context)
    if not lines:
        return None

    ui_scale = _get_overlay_ui_scale(context)
    font_id = _DIMENSIONS_OVERLAY_FONT_ID
    font_size = _scale_overlay_value(_DIMENSIONS_OVERLAY_FONT_SIZE, ui_scale)
    padding = _scale_overlay_value(_DIMENSIONS_OVERLAY_PADDING, ui_scale)
    line_gap = _scale_overlay_value(_DIMENSIONS_OVERLAY_LINE_GAP, ui_scale)
    blf.size(font_id, font_size)
    text_height = int(blf.dimensions(font_id, "Ag")[1])
    line_step = text_height + line_gap
    text_width = max(int(blf.dimensions(font_id, line)[0]) for line in lines)
    return {
        "lines": lines,
        "font_id": font_id,
        "font_size": font_size,
        "padding": padding,
        "text_height": text_height,
        "line_step": line_step,
        "width": text_width + (padding * 2),
        "height": (
            (text_height * len(lines))
            + (line_gap * max(0, len(lines) - 1))
            + (padding * 2)
        ),
    }


def get_viewport_info_overlay_row_layout(context=None):
    """Return metrics content for the combined viewport action card."""
    if context is None:
        context = bpy.context
    ui_scale = _get_overlay_ui_scale(context)
    row_gap = _scale_overlay_value(_DIMENSIONS_OVERLAY_ROW_GAP, ui_scale)
    items = []
    metrics_layout = _get_mold_metrics_overlay_layout(context)
    if metrics_layout is not None:
        items.append(("metrics", metrics_layout))
    return {
        "items": items,
        "gap": row_gap,
        "width": sum(layout["width"] for _kind, layout in items)
        + (row_gap * max(0, len(items) - 1)),
        "height": max(
            (layout["height"] for _kind, layout in items),
            default=0,
        ),
    }


def _draw_dimensions_overlay(layout, pos_x, pos_y):
    _draw_styled_overlay_background(
        pos_x,
        pos_y,
        layout["width"],
        layout["height"],
    )
    font_id = layout["font_id"]
    blf.size(font_id, layout["font_size"])
    text_x = pos_x + layout["padding"]
    baseline_y = (
        pos_y
        + layout["height"]
        - layout["padding"]
        - layout["text_height"]
    )
    for index, line in enumerate(layout["lines"]):
        color = (
            _DIMENSIONS_OVERLAY_TEXT_COLOR
            if index == 0
            else _DIMENSIONS_OVERLAY_SECONDARY_TEXT_COLOR
        )
        blf.color(font_id, *color)
        blf.position(
            font_id,
            text_x,
            baseline_y - (index * layout["line_step"]),
            0,
        )
        blf.draw(font_id, line)


def _get_viewport_action_bar_layout_for_info_row(context, region):
    try:
        from .. import panels as panels_module
    except (ImportError, ValueError):
        try:
            import moldboxer_silicone_native.panels as panels_module
        except ImportError:
            return None
    try:
        return panels_module._get_viewport_action_bar_layout(context, region)
    except (AttributeError, RuntimeError, TypeError):
        return None


def _draw_dimensions_overlay_callback():
    # Generation replaces/joins scene objects. Draw the progress overlay only
    # until the operation has finished, before touching any scene collections.
    if _modal_progress_overlay_active_count:
        return
    context = bpy.context
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    space_data = getattr(context, "space_data", None)
    region_data = getattr(context, "region_data", None)
    if region is None or area is None or space_data is None:
        return
    if getattr(region, "type", "") != "WINDOW":
        return
    if getattr(area, "type", "") != "VIEW_3D":
        return
    if getattr(space_data, "type", "") != "VIEW_3D":
        return
    overlay = getattr(space_data, "overlay", None)
    if overlay is not None and not bool(getattr(overlay, "show_overlays", True)):
        return

    _draw_object_name_labels(context, region, region_data)
    ui_scale = _get_overlay_ui_scale(context)
    corner_margin = _scale_overlay_value(_DIMENSIONS_OVERLAY_CORNER_MARGIN, ui_scale)
    info_row = get_viewport_info_overlay_row_layout(context)
    action_layout = _get_viewport_action_bar_layout_for_info_row(context, region)
    # The action bar owns and draws these metrics whenever it is available.
    # Keep this standalone path for states without a primary workflow action.
    if action_layout is not None:
        return
    row_x = max(
        corner_margin,
        (int(getattr(region, "width", 0)) - info_row["width"]) // 2,
    )
    row_y = corner_margin
    cursor_x = row_x
    for kind, layout in info_row["items"]:
        if kind == "metrics":
            _draw_mold_metrics_overlay(layout, cursor_x, row_y)
        cursor_x += layout["width"] + info_row["gap"]


def _notify_dimensions_overlay_redraw(*_args) -> None:
    ensure_moldboxer_transform_gizmos_for_selection(bpy.context)
    _tag_view3d_areas_for_redraw(bpy.context)


def _subscribe_dimensions_overlay_redraw() -> None:
    bpy.msgbus.clear_by_owner(_viewport_dimensions_msgbus_owner)
    bpy.msgbus.subscribe_rna(
        key=(bpy.types.LayerObjects, "active"),
        owner=_viewport_dimensions_msgbus_owner,
        args=(),
        notify=_notify_dimensions_overlay_redraw,
        options={"PERSISTENT"},
    )
    # Tool changes do not change the active object. Listen to the workspace so
    # selecting Scale can temporarily enable its tool gizmo, and switching away
    # restores Moldboxer's combined translate/rotate context gizmos.
    try:
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.WorkSpace, "tools"),
            owner=_viewport_dimensions_msgbus_owner,
            args=(),
            notify=_notify_dimensions_overlay_redraw,
            options={"PERSISTENT"},
        )
    except (AttributeError, TypeError, RuntimeError):
        pass
    for scene_property in (
        "volume",
        "silicone_density",
        "silicone_mix_mode",
        "silicone_mix_part_a",
        "silicone_mix_part_b",
        "plaster_mix_volume_ml",
        "plaster_mix_water_ml",
        "plaster_mix_plaster_g",
        "casting_volume_ml",
        "casting_material_mode",
        "casting_material_density",
        "casting_material_part_a",
        "casting_material_part_b",
        "casting_material_powder_g",
        "casting_material_water_ml",
        "casting_material_yield_ml",
    ):
        try:
            bpy.msgbus.subscribe_rna(
                key=(bpy.types.Scene, scene_property),
                owner=_viewport_dimensions_msgbus_owner,
                args=(),
                notify=_notify_dimensions_overlay_redraw,
                options={"PERSISTENT"},
            )
        except Exception:
            continue


def ensure_viewport_dimensions_overlay(context=None) -> None:
    global viewport_dimensions_draw_handler

    if context is None:
        context = bpy.context

    if viewport_dimensions_draw_handler is None:
        try:
            viewport_dimensions_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                _draw_dimensions_overlay_callback, (), "WINDOW", "POST_PIXEL"
            )
        except Exception:
            viewport_dimensions_draw_handler = None
            return

    _subscribe_dimensions_overlay_redraw()
    ensure_moldboxer_transform_gizmos_for_selection(context)
    _tag_view3d_areas_for_redraw(context)


def set_viewport_dimensions_overlay_enabled(enabled: bool, context=None) -> None:
    if enabled:
        ensure_viewport_dimensions_overlay(context)
        return
    remove_viewport_dimensions_overlay(context)


def remove_viewport_dimensions_overlay(context=None) -> None:
    global viewport_dimensions_draw_handler

    bpy.msgbus.clear_by_owner(_viewport_dimensions_msgbus_owner)
    _viewport_metrics_modes.clear()

    if viewport_dimensions_draw_handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                viewport_dimensions_draw_handler, "WINDOW"
            )
        except Exception:
            pass
        finally:
            viewport_dimensions_draw_handler = None

    if context is not None:
        _tag_view3d_areas_for_redraw(context)


def _load_viewport_logo_image():
    global _viewport_logo_image_name
    global _viewport_logo_image_pointer
    global _viewport_logo_texture
    global _viewport_logo_texture_image_pointer

    image = None
    if _viewport_logo_image_name:
        image = bpy.data.images.get(_viewport_logo_image_name)
        if image is not None:
            try:
                image_pointer = image.as_pointer()
            except ReferenceError:
                image = None
            else:
                if image_pointer != _viewport_logo_image_pointer:
                    _viewport_logo_image_pointer = image_pointer
                    _viewport_logo_texture = None
                    _viewport_logo_texture_image_pointer = None
                return image

        _viewport_logo_image_name = None
        _viewport_logo_image_pointer = None
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None

    if not _VIEWPORT_LOGO_PATH.is_file():
        return None

    try:
        image = bpy.data.images.load(str(_VIEWPORT_LOGO_PATH), check_existing=True)
        # Keep the overlay in the logo's authored color space with no extra fade.
        image.alpha_mode = "STRAIGHT"
        image.colorspace_settings.name = "sRGB"
        _viewport_logo_image_name = image.name
        _viewport_logo_image_pointer = image.as_pointer()
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None
    except Exception:
        _viewport_logo_image_name = None
        _viewport_logo_image_pointer = None
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None
        image = None
    return image


def _get_viewport_logo_texture():
    global _viewport_logo_texture
    global _viewport_logo_texture_image_pointer

    image = _load_viewport_logo_image()
    if image is None:
        return None

    try:
        image_pointer = image.as_pointer()
    except ReferenceError:
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None
        return None

    if (
        _viewport_logo_texture is not None
        and _viewport_logo_texture_image_pointer == image_pointer
    ):
        return _viewport_logo_texture

    try:
        import gpu  # type: ignore

        _viewport_logo_texture = gpu.texture.from_image(image)
        _viewport_logo_texture_image_pointer = image_pointer
    except Exception:
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None
    return _viewport_logo_texture


def _draw_viewport_logo_callback():
    context = bpy.context
    region = getattr(context, "region", None)
    if region is None or getattr(region, "type", "") != "WINDOW":
        return
    overlay = getattr(getattr(context, "space_data", None), "overlay", None)
    if overlay is not None and not bool(getattr(overlay, "show_overlays", True)):
        return

    texture = _get_viewport_logo_texture()
    image = _load_viewport_logo_image()
    if texture is None or image is None:
        return

    try:
        image_width, image_height = image.size[:2]
    except ReferenceError:
        return
    if image_width <= 0 or image_height <= 0:
        return

    ui_scale = _get_overlay_ui_scale(context)
    draw_width = _scale_overlay_value(_VIEWPORT_LOGO_WIDTH, ui_scale)
    draw_height = max(1, round(draw_width * (image_height / image_width)))
    margin = _scale_overlay_value(_VIEWPORT_LOGO_MARGIN, ui_scale)
    top_offset = _scale_overlay_value(_VIEWPORT_LOGO_TOP_OFFSET, ui_scale)
    pos_x = max(margin, round((region.width - draw_width) / 2))
    pos_y = max(
        margin,
        region.height - draw_height - top_offset,
    )

    try:
        import gpu  # type: ignore
        from gpu_extras.presets import draw_texture_2d  # type: ignore

        gpu.state.blend_set("ALPHA")
        draw_texture_2d(texture, (pos_x, pos_y), draw_width, draw_height)
        gpu.state.blend_set("NONE")
    except Exception:
        try:
            import gpu  # type: ignore

            gpu.state.blend_set("NONE")
        except Exception:
            pass


def ensure_viewport_logo_overlay(context) -> None:
    global viewport_logo_draw_handler

    if viewport_logo_draw_handler is not None:
        _tag_view3d_areas_for_redraw(context)
        return

    if _load_viewport_logo_image() is None:
        return

    try:
        viewport_logo_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_logo_callback, (), "WINDOW", "POST_PIXEL"
        )
    except Exception:
        viewport_logo_draw_handler = None
        return

    _tag_view3d_areas_for_redraw(context)


def remove_viewport_logo_overlay(context=None) -> None:
    global viewport_logo_draw_handler
    global _viewport_logo_image_name
    global _viewport_logo_image_pointer
    global _viewport_logo_texture
    global _viewport_logo_texture_image_pointer

    if viewport_logo_draw_handler is None:
        _viewport_logo_image_name = None
        _viewport_logo_image_pointer = None
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None
        if context is not None:
            _tag_view3d_areas_for_redraw(context)
        return

    try:
        bpy.types.SpaceView3D.draw_handler_remove(viewport_logo_draw_handler, "WINDOW")
    except Exception:
        pass
    finally:
        viewport_logo_draw_handler = None
        _viewport_logo_image_name = None
        _viewport_logo_image_pointer = None
        _viewport_logo_texture = None
        _viewport_logo_texture_image_pointer = None

    if context is not None:
        _tag_view3d_areas_for_redraw(context)


def ensure_moldboxer_background(context) -> None:
    if context is None or getattr(context, "scene", None) is None:
        return

    scene = context.scene
    color_input = _get_world_background_color_input(context)
    if not bool(scene.get(_BG_APPLIED_KEY, False)):
        if color_input is not None:
            scene[_BG_ORIGINAL_KEY] = list(color_input.default_value)
        scene[_BG_APPLIED_KEY] = True

    if color_input is not None:
        color_input.default_value = MOLDBOXER_BACKGROUND

    _ensure_material_preview_world(context)

    for space in _iter_view3d_spaces(context):
        shading = getattr(space, "shading", None)
        overlay = getattr(space, "overlay", None)
        if shading is None:
            continue
        try:
            if overlay is not None:
                overlay.show_cursor = False
                for attr in ("show_object_origins", "show_object_origins_all"):
                    if hasattr(overlay, attr):
                        setattr(overlay, attr, False)

            if shading.type == "MATERIAL":
                shading.use_scene_world = True
                continue

            if shading.type == "RENDERED":
                continue

            shading.use_scene_world = False
            shading.background_type = "VIEWPORT"
            shading.background_color = MOLDBOXER_BACKGROUND[:3]
        except Exception:
            continue

    remove_viewport_logo_overlay(context)


def ensure_solid_viewport_material_shading(context) -> None:
    if context is None:
        return

    for space in _iter_view3d_spaces(context):
        shading = getattr(space, "shading", None)
        if shading is None:
            continue
        try:
            shading.type = "SOLID"
            if hasattr(shading, "color_type"):
                shading.color_type = "MATERIAL"
            shading.use_scene_world = False
            shading.background_type = "VIEWPORT"
            shading.background_color = MOLDBOXER_BACKGROUND[:3]
        except Exception:
            continue

    _tag_view3d_areas_for_redraw(context)


def reset_background_to_default(context) -> None:
    if context is None or getattr(context, "scene", None) is None:
        return

    remove_viewport_logo_overlay(context)

    scene = context.scene
    color_input = _get_world_background_color_input(context)
    if color_input is None:
        return

    original_color = scene.get(_BG_ORIGINAL_KEY, BLENDER_DEFAULT_BACKGROUND)
    if len(original_color) == 4:
        color_input.default_value = tuple(original_color)

    _restore_world_surface(context)

    for space in _iter_view3d_spaces(context):
        shading = getattr(space, "shading", None)
        overlay = getattr(space, "overlay", None)
        if shading is None:
            continue
        try:
            if overlay is not None:
                overlay.show_cursor = True
                for attr in ("show_object_origins", "show_object_origins_all"):
                    if hasattr(overlay, attr):
                        setattr(overlay, attr, True)

            if shading.type == "MATERIAL":
                shading.use_scene_world = False
                continue

            if shading.type == "RENDERED":
                continue

            shading.use_scene_world = False
            shading.background_type = "THEME"
            shading.background_color = BLENDER_DEFAULT_BACKGROUND[:3]
        except Exception:
            continue

    scene[_BG_APPLIED_KEY] = False


def show_popup(message: str, title: str = "Moldboxer"):
    def draw(self, context):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title=title, icon="INFO")


def configure_metric_millimeter_units(context=None) -> None:
    """Keep mm geometry while preserving the selected display system.

    The historical name is retained for existing operator/native callers.
    """
    if context is None:
        context = bpy.context

    scene = getattr(context, "scene", None)
    if scene is None:
        return

    unit_settings = getattr(scene, "unit_settings", None)
    if unit_settings is not None:
        from .scene_units import configure_scene_units

        configure_scene_units(scene)

    # With a 1 mm scene unit, keep the major grid step at 1 mm so the grid
    # remains visible and aligned with the displayed units.
    clip_start = 0.1
    clip_end = 10000.0
    grid_scale = 0.01
    grid_subdivisions = 10

    for space in _iter_view3d_spaces(context):
        try:
            if hasattr(space, "clip_start"):
                space.clip_start = clip_start
            if hasattr(space, "clip_end"):
                space.clip_end = clip_end

            overlay = getattr(space, "overlay", None)
            if overlay is not None:
                if hasattr(overlay, "grid_scale"):
                    overlay.grid_scale = grid_scale
                if hasattr(overlay, "grid_subdivisions"):
                    overlay.grid_subdivisions = grid_subdivisions
        except Exception:
            continue


def cursor_to_origin(context):
    cursor = context.scene.cursor
    cursor.location = Vector((0.0, 0.0, 0.0))
    cursor.rotation_mode = "XYZ"
    cursor.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")


def heal_active_patron(context, active_bl_obj=None, quality=None):
    from .modifiers import build_voxel_modifier
    from .object import Object
    from .patron_state import DECIMATED_PATRON_KEY
    from .voxel_size import get_master_voxel_size

    active_bl_obj = (
        active_bl_obj
        or getattr(context, "active_object", None)
        or getattr(context, "object", None)
        or bpy.context.active_object
    )
    if active_bl_obj is None:
        raise RuntimeError("No active object to heal")

    active_obj = Object(active_bl_obj)
    if bool(active_obj.object.get(DECIMATED_PATRON_KEY, False)):
        logger.debug("Skipping heal for decimated patron proxy %s", active_obj.name)
        return False

    active_obj.apply_modifier(
        build_voxel_modifier(
            get_master_voxel_size(
                quality or context.scene.master_quality,
                active_obj,
            )
        )
    )
    return True


def heal_active_patron_sharp(context, active_bl_obj=None, quality=None):
    from .modifiers import build_sharp_modifier
    from .object import Object
    from .patron_state import DECIMATED_PATRON_KEY

    active_bl_obj = (
        active_bl_obj
        or getattr(context, "active_object", None)
        or getattr(context, "object", None)
        or bpy.context.active_object
    )
    if active_bl_obj is None:
        raise RuntimeError("No active object to heal")

    active_obj = Object(active_bl_obj)
    if bool(active_obj.object.get(DECIMATED_PATRON_KEY, False)):
        logger.debug(
            "Skipping sharp heal for decimated patron proxy %s",
            active_obj.name,
        )
        return False

    sharp_quality_levels = {
        "VERY_LOW": 4,
        "DRAFT": 5,
        "FAST": 6,
        "MID": 7,
        "HIGH": 8,
        "VERY HIGH": 8,
        "ULTRA": 9,
        "EXTREME": 9,
    }
    selected_quality = quality or context.scene.master_quality
    active_obj.apply_modifier(
        build_sharp_modifier(
            sharp_quality_levels.get(selected_quality, 7)
        )
    )
    return True


def get_exception_blender_object(exc):
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        bl_obj = getattr(current, "failed_object", None)
        try:
            is_blender_object = bl_obj is not None and callable(
                getattr(bl_obj, "select_set", None)
            )
        except ReferenceError:
            # Blender RNA proxies remain reachable from Python exceptions after
            # their underlying temporary object has been removed. Treat those
            # stale proxies as unavailable so recovery can use its fallback.
            is_blender_object = False
        if is_blender_object:
            return bl_obj
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return None


class GenerationStoppedError(RuntimeError):
    """Abort the active generator without entering any recovery retry."""


def retry_after_heal(func):
    def as_context(candidate):
        if hasattr(candidate, "scene") and hasattr(candidate, "view_layer"):
            return candidate
        return None

    def as_blender_object(candidate):
        if candidate is None:
            return None
        if isinstance(candidate, (list, tuple, set)):
            for item in candidate:
                bl_obj = as_blender_object(item)
                if bl_obj is not None:
                    return bl_obj
            return None
        wrapped_object = getattr(candidate, "object", None)
        if wrapped_object is not None and hasattr(wrapped_object, "select_set"):
            return wrapped_object
        if hasattr(candidate, "select_set"):
            return candidate
        return None

    def find_context(args, kwargs):
        for candidate in (*args, *kwargs.values()):
            context = as_context(candidate)
            if context is not None:
                return context
        return bpy.context

    def find_heal_target(args, kwargs):
        for candidate in (*args, *kwargs.values()):
            bl_obj = as_blender_object(candidate)
            if bl_obj is not None:
                return bl_obj
        return None

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        context = kwargs.get("context") or find_context(args, kwargs)
        active_bl_obj = (
            getattr(context, "active_object", None)
            or getattr(context, "object", None)
            or bpy.context.active_object
            or find_heal_target(args, kwargs)
        )
        try:
            return func(*args, **kwargs)
        except GenerationStoppedError:
            raise
        except Exception as exc:
            heal_target = get_exception_blender_object(exc) or active_bl_obj
            logger.debug(
                "Could not perform operation, healing %s and trying again",
                getattr(heal_target, "name", None) or "active object",
            )
            healed = heal_active_patron(context, heal_target)
            if healed:
                try:
                    from .i18n import t
                except (ImportError, KeyError):
                    def t(text, **kwargs):
                        return text.format(**kwargs) if kwargs else text

                show_popup(t("Bad mesh: healing applied. Check the master detail level."))
            if heal_target is not None:
                deselect_all_objects()
                heal_target.select_set(True)
                bpy.context.view_layer.objects.active = heal_target
            return func(*args, **kwargs)

    return wrapper
