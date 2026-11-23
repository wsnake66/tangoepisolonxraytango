"""Interactive freehand organic-plane tools used by the development panel."""

from __future__ import annotations

import json
import math

import bpy  # type: ignore
import mathutils  # type: ignore
from bpy.props import FloatProperty  # type: ignore

from .environment import get_addon_preferences
from .i18n import t
from .materials import assign_material, get_or_create_simple_material
from .modifiers import diff_mod
from .object import Object
from .components.geometry_adapter import acquire_geometry_worker
from .components.organic_plane_server import request_organic_plane


ORGANIC_PLANE_NAME = "organic_plane"
# Release gate: keep the unfinished drawing tool unavailable in every entry point.
ORGANIC_SPLIT_AVAILABLE = False
ORGANIC_PLANE_MARKER = "moldboxer_organic_plane"
ORGANIC_PLANE_DATA_KEY = "moldboxer_organic_plane_control_surface"
ORGANIC_PLANE_THICKNESS_KEY = "moldboxer_organic_plane_thickness"
DIRECT_SPLIT_PLANE_MARKER = "moldboxer_direct_split_plane"
DIRECT_SPLIT_PLANE_AXIS_KEY = "moldboxer_direct_split_axis"
DIRECT_SPLIT_PLANE_INDEX_KEY = "moldboxer_direct_split_index"
ORGANIC_SPLIT_TEST_RESULT_KEY = "moldboxer_organic_split_test_result"
ORGANIC_SPLIT_TEST_SOURCE_KEY = "moldboxer_organic_split_test_source"
_MIN_SAMPLE_DISTANCE_PIXELS = 4.0
_SIMPLIFY_TOLERANCE_PIXELS = 2.0
_BOUNDS_CLEARANCE_RATIO = 0.05
_MIN_BOUNDS_CLEARANCE = 1.0e-3
_CONTROL_DEPTH_COUNT = 12
_CONTROL_HEIGHT_COUNT = 16
_HOVER_LIMIT_PIXELS = 64.0
_DEFAULT_CUTTER_THICKNESS = 0.1


def _organic_worker(operation: str, **arguments) -> dict:
    return acquire_geometry_worker().organic_plane(operation, **arguments)


def _organic_server(operation: str, **arguments) -> dict:
    return request_organic_plane(operation, **arguments)


def simplify_polyline(points, tolerance):
    return _organic_worker(
        "simplify_polyline", points=points, tolerance=float(tolerance)
    )["points"]


def proportional_radius_from_drag(
    start_radius, horizontal_pixels, *, minimum, maximum, pixels_per_doubling=140.0
):
    return float(
        _organic_worker(
            "proportional_radius",
            start_radius=float(start_radius),
            horizontal_pixels=float(horizontal_pixels),
            minimum=float(minimum),
            maximum=float(maximum),
            pixels_per_doubling=float(pixels_per_doubling),
        )["value"]
    )


def create_organic_surface_data(stroke_points, depth_axis, **options):
    return _organic_server(
        "create_surface",
        stroke_points=stroke_points,
        depth_axis=depth_axis,
        **options,
    )["surface"]


def top_profile_from_stroke(stroke_points, surface_data):
    return _organic_server(
        "top_profile",
        stroke_points=stroke_points,
        surface_data=surface_data,
    )["profile"]


def organic_surface_mesh(surface_data):
    result = _organic_worker("surface_mesh", surface_data=surface_data)
    return result["vertices"], result["faces"]


def organic_cutter_mesh(surface_data, thickness):
    result = _organic_server(
        "cutter_mesh", surface_data=surface_data, thickness=float(thickness)
    )
    return result["vertices"], result["faces"]


def organic_cutter_preview_mesh(surface_data, thickness):
    result = _organic_worker(
        "cutter_mesh", surface_data=surface_data, thickness=float(thickness)
    )
    return result["vertices"], result["faces"]


def _dev_mode_enabled() -> bool:
    prefs = get_addon_preferences()
    return bool(prefs and getattr(prefs, "dev_mode", False))


def _patron(context):
    scene = getattr(context, "scene", None)
    scene_objects = getattr(scene, "objects", None) if scene is not None else None
    target = scene_objects.get("patron") if scene_objects is not None else None
    if target is None:
        target = bpy.data.objects.get("patron")
    if target is None or getattr(target, "type", None) != "MESH":
        return None
    return target


def _world_bounds(obj):
    return [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]


def _encode_surface_data(surface_data: dict) -> str:
    return json.dumps(surface_data, separators=(",", ":"))


def _decode_surface_data(obj, *, validate: bool = True) -> dict:
    raw_data = obj.get(ORGANIC_PLANE_DATA_KEY, "")
    if not isinstance(raw_data, str) or not raw_data:
        raise ValueError("The selected organic plane has no editable control data")
    data = json.loads(raw_data)
    if validate:
        organic_surface_mesh(data)
    return data


def _apply_surface_mesh(obj, surface_data: dict, vertices, faces) -> None:
    thickness = max(0.0, float(surface_data.get("thickness", 0.0)))
    mesh = obj.data
    mesh.clear_geometry()
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj[ORGANIC_PLANE_DATA_KEY] = _encode_surface_data(surface_data)
    obj[ORGANIC_PLANE_THICKNESS_KEY] = thickness


def _update_surface_mesh(
    obj,
    surface_data: dict,
    *,
    authoritative: bool = False,
) -> None:
    thickness = max(0.0, float(surface_data.get("thickness", 0.0)))
    if thickness > 0.0:
        mesh_builder = (
            organic_cutter_mesh if authoritative else organic_cutter_preview_mesh
        )
        vertices, faces = mesh_builder(surface_data, thickness)
    else:
        vertices, faces = organic_surface_mesh(surface_data)
    _apply_surface_mesh(obj, surface_data, vertices, faces)


def organic_split_spec_from_object(obj) -> dict:
    """Serialize an organic cutter so later workflows do not need its object."""
    surface_data = _decode_surface_data(obj, validate=False)
    thickness = max(
        float(surface_data.get("thickness", 0.0)),
        float(obj.get(ORGANIC_PLANE_THICKNESS_KEY, 0.0)),
    )
    if thickness <= 0.0:
        raise ValueError("Confirm the organic split before using it")

    surface_vertices, surface_faces = organic_surface_mesh(surface_data)
    cutter_vertices = [
        [float(value) for value in obj.matrix_world @ vertex.co]
        for vertex in obj.data.vertices
    ]
    surface_world_vertices = [
        [float(value) for value in obj.matrix_world @ mathutils.Vector(vertex)]
        for vertex in surface_vertices
    ]
    point = sum(
        (mathutils.Vector(vertex) for vertex in surface_world_vertices),
        mathutils.Vector((0.0, 0.0, 0.0)),
    ) / len(surface_world_vertices)
    normal = obj.matrix_world.to_3x3() @ mathutils.Vector(
        surface_data["lateral_axis"]
    )
    if normal.length <= 1.0e-9:
        raise ValueError("Organic split has an invalid direction")
    normal.normalize()
    return {
        "type": "organic",
        "version": 1,
        "point": [float(value) for value in point],
        "normal": [float(value) for value in normal],
        "thickness": thickness,
        "surface": {
            "vertices": surface_world_vertices,
            "faces": [list(map(int, face)) for face in surface_faces],
        },
        "cutter": {
            "vertices": cutter_vertices,
            "faces": [
                [int(index) for index in polygon.vertices]
                for polygon in obj.data.polygons
            ],
        },
    }


def _has_mesh_geometry(obj) -> bool:
    data = getattr(obj, "data", None)
    return bool(
        data is not None
        and len(getattr(data, "vertices", ())) > 0
        and len(getattr(data, "polygons", ())) > 0
    )


def _remove_objects_created_after(existing_pointers: set[int]) -> None:
    for obj in tuple(bpy.data.objects):
        try:
            pointer = int(obj.as_pointer())
        except ReferenceError:
            continue
        if pointer not in existing_pointers:
            from .object import remove_objects_safely

            remove_objects_safely((obj,))


def split_object_with_organic_plane(target_obj, cutter_obj) -> list:
    """Test-split a duplicate using one Difference Boolean and keep all sides."""

    if target_obj is cutter_obj:
        raise ValueError("The organic cutter cannot split itself")
    if getattr(target_obj, "type", None) != "MESH":
        raise ValueError("The split target must be a mesh")
    if getattr(cutter_obj, "type", None) != "MESH":
        raise ValueError("The organic cutter must be a mesh")
    if float(cutter_obj.get(ORGANIC_PLANE_THICKNESS_KEY, 0.0)) <= 0.0:
        raise ValueError("Confirm the organic plane before testing the split")
    surface_data = _decode_surface_data(cutter_obj, validate=False)
    existing_pointers = {int(obj.as_pointer()) for obj in bpy.data.objects}
    temporary_cutter = None
    try:
        working = Object(target_obj).duplicate(name_adder="_organic_split_test")
        temporary_cutter = Object(cutter_obj).duplicate(
            name_adder="_organic_split_boolean"
        )
        temporary_cutter.hide_during_ui_breathe = True
        working.apply_boolean_modifier_with_geometry_fallback(
            diff_mod,
            temporary_cutter,
        )
        if working.has_empty_boolean:
            raise RuntimeError("The organic split Boolean did not apply")

        valid_parts = []
        for part in working.split_isolated_meshes():
            if _has_mesh_geometry(part.object):
                valid_parts.append(part)
            elif part.object.name in bpy.data.objects:
                part.remove()
        parts = valid_parts
        if len(parts) < 2:
            raise ValueError(
                "The organic cutter did not separate the target into two components"
            )

        local_axis = mathutils.Vector(surface_data["lateral_axis"])
        world_axis = cutter_obj.matrix_world.to_3x3() @ local_axis
        if world_axis.length <= 1.0e-9:
            raise ValueError("The organic cutter has an invalid split direction")
        world_axis.normalize()
        cutter_origin = cutter_obj.matrix_world.translation

        def split_position(part):
            bounds = _world_bounds(part.object)
            center = sum(bounds, mathutils.Vector()) / len(bounds)
            return (center - cutter_origin).dot(world_axis)

        parts.sort(key=split_position)
        source_name = target_obj.name
        for index, part in enumerate(parts, start=1):
            suffix = (
                "negative"
                if len(parts) == 2 and index == 1
                else "positive"
                if len(parts) == 2
                else f"part_{index:02d}"
            )
            part.name = f"{source_name}_organic_{suffix}"
            part.object[ORGANIC_SPLIT_TEST_RESULT_KEY] = True
            part.object[ORGANIC_SPLIT_TEST_SOURCE_KEY] = source_name
        return [part.object for part in parts]
    except Exception:
        _remove_objects_created_after(existing_pointers)
        temporary_cutter = None
        raise
    finally:
        if (
            temporary_cutter is not None
            and temporary_cutter.object.name in bpy.data.objects
        ):
            temporary_cutter.remove()


def _selected_organic_split_target(context, cutter_obj):
    selected_targets = [
        obj
        for obj in getattr(context, "selected_objects", ())
        if obj is not cutter_obj and getattr(obj, "type", None) == "MESH"
    ]
    if len(selected_targets) > 1:
        raise ValueError("Select only one mesh target together with the organic plane")
    if selected_targets:
        return selected_targets[0]
    patron = _patron(context)
    if patron is not None and patron is not cutter_obj:
        return patron
    raise ValueError("Select a mesh target or add a patron object")


def _screen_to_plane(context, screen_point, plane_point, plane_normal):
    from bpy_extras import view3d_utils  # type: ignore

    ray_origin = view3d_utils.region_2d_to_origin_3d(
        context.region,
        context.region_data,
        screen_point,
    )
    ray_direction = view3d_utils.region_2d_to_vector_3d(
        context.region,
        context.region_data,
        screen_point,
    )
    denominator = ray_direction.dot(plane_normal)
    if abs(denominator) <= 1.0e-9:
        return None
    distance = (plane_point - ray_origin).dot(plane_normal) / denominator
    return ray_origin + ray_direction * distance


def _append_screen_point(points, event, *, force=False) -> bool:
    point = (float(event.mouse_region_x), float(event.mouse_region_y))
    if points and not force:
        delta_x = point[0] - points[-1][0]
        delta_y = point[1] - points[-1][1]
        if delta_x * delta_x + delta_y * delta_y < _MIN_SAMPLE_DISTANCE_PIXELS**2:
            return False
    if points and point == points[-1]:
        return False
    points.append(point)
    return True


class SILICONE_OT_draw_organic_plane(bpy.types.Operator):
    bl_idname = "silicone.draw_organic_plane"
    bl_label = "Draw Organic Split (Soon)"
    bl_description = (
        "Draw a freehand vertical profile, extend it beyond the patron, then "
        "reshape it with a proportional control surface"
    )
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    _draw_handler = None
    _drawing = False
    _screen_points = None
    _plane_point = None
    _depth_axis = None
    _depth_min = 0.0
    _depth_max = 0.0
    _height_min = 0.0
    _height_max = 0.0

    @classmethod
    def poll(cls, context):
        if not ORGANIC_SPLIT_AVAILABLE:
            cls.poll_message_set("Organic split drawing is coming soon")
            return False
        return bool(
            getattr(getattr(context, "area", None), "type", None) == "VIEW_3D"
        )

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _finish(self, context):
        if self._draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, "WINDOW")
            except Exception:
                pass
            self._draw_handler = None
        area = getattr(context, "area", None)
        if area is not None:
            try:
                area.header_text_set(None)
            except Exception:
                pass
        window = getattr(context, "window", None)
        if window is not None:
            try:
                window.cursor_modal_restore()
            except Exception:
                pass
        self._tag_redraw(context)

    def _draw_overlay(self):
        if not self._screen_points:
            return
        try:
            import gpu  # type: ignore
            from gpu_extras.batch import batch_for_shader  # type: ignore

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            batch = batch_for_shader(shader, "LINE_STRIP", {"pos": self._screen_points})
            gpu.state.blend_set("ALPHA")
            gpu.state.line_width_set(3.0)
            shader.bind()
            shader.uniform_float("color", (1.0, 0.45, 0.08, 1.0))
            batch.draw(shader)
        except Exception:
            pass
        finally:
            try:
                import gpu  # type: ignore

                gpu.state.line_width_set(1.0)
                gpu.state.blend_set("NONE")
            except Exception:
                pass

    def _create_plane(self, context):
        simplified = simplify_polyline(self._screen_points, _SIMPLIFY_TOLERANCE_PIXELS)
        stroke_points = []
        for screen_point in simplified:
            world_point = _screen_to_plane(
                context,
                screen_point,
                self._plane_point,
                self._depth_axis,
            )
            if world_point is not None:
                stroke_points.append(tuple(world_point))

        surface_data = create_organic_surface_data(
            stroke_points,
            tuple(self._depth_axis),
            depth_min=self._depth_min,
            depth_max=self._depth_max,
            height_min=self._height_min,
            height_max=self._height_max,
            depth_count=_CONTROL_DEPTH_COUNT,
            height_count=_CONTROL_HEIGHT_COUNT,
        )
        mesh = bpy.data.meshes.new(f"{ORGANIC_PLANE_NAME}_mesh")
        organic_plane = bpy.data.objects.new(ORGANIC_PLANE_NAME, mesh)
        context.collection.objects.link(organic_plane)
        organic_plane[ORGANIC_PLANE_MARKER] = True
        organic_plane[DIRECT_SPLIT_PLANE_MARKER] = True
        organic_plane[DIRECT_SPLIT_PLANE_AXIS_KEY] = "organic"
        organic_plane[DIRECT_SPLIT_PLANE_INDEX_KEY] = sum(
            bool(obj.get(ORGANIC_PLANE_MARKER, False)) for obj in bpy.data.objects
        )
        organic_plane.show_in_front = True
        _update_surface_mesh(organic_plane, surface_data)
        assign_material(
            organic_plane,
            get_or_create_simple_material(
                "MB_OrganicPlane",
                "#F28C28CC",
                metallic=0.0,
                roughness=0.65,
            ),
        )
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        organic_plane.select_set(True)
        context.view_layer.objects.active = organic_plane
        return organic_plane

    def invoke(self, context, _event):
        if not ORGANIC_SPLIT_AVAILABLE:
            self.report({"WARNING"}, t("Organic split drawing is coming soon"))
            return {"CANCELLED"}
        patron = _patron(context)
        if patron is None:
            self.report({"ERROR"}, t("A patron mesh is required"))
            return {"CANCELLED"}
        if context.region_data is None:
            self.report({"ERROR"}, t("Run this tool from a 3D viewport"))
            return {"CANCELLED"}

        from bpy_extras import view3d_utils  # type: ignore

        viewport_center = (context.region.width * 0.5, context.region.height * 0.5)
        view_direction = view3d_utils.region_2d_to_vector_3d(
            context.region,
            context.region_data,
            viewport_center,
        ).normalized()
        horizontal_direction = mathutils.Vector(
            (view_direction.x, view_direction.y, 0.0)
        )
        if horizontal_direction.length <= 0.15:
            self.report(
                {"ERROR"},
                t("Use a front, back, or side view to draw a vertical profile"),
            )
            return {"CANCELLED"}
        self._depth_axis = horizontal_direction.normalized()

        corners = _world_bounds(patron)
        self._plane_point = mathutils.Vector(
            tuple(
                sum(float(corner[axis]) for corner in corners) / len(corners)
                for axis in range(3)
            )
        )
        depths = [corner.dot(self._depth_axis) for corner in corners]
        min_depth = min(depths)
        max_depth = max(depths)
        min_height = min(corner.z for corner in corners)
        max_height = max(corner.z for corner in corners)
        depth_clearance = max(
            (max_depth - min_depth) * _BOUNDS_CLEARANCE_RATIO,
            _MIN_BOUNDS_CLEARANCE,
        )
        height_clearance = max(
            (max_height - min_height) * _BOUNDS_CLEARANCE_RATIO,
            _MIN_BOUNDS_CLEARANCE,
        )
        self._depth_min = min_depth - depth_clearance
        self._depth_max = max_depth + depth_clearance
        self._height_min = min_height - height_clearance
        self._height_max = max_height + height_clearance
        self._screen_points = []
        self._drawing = False
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_overlay,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        try:
            context.window.cursor_modal_set("CROSSHAIR")
        except Exception:
            pass
        context.area.header_text_set(
            t("Draw Organic Plane: drag LMB vertically over the patron; Esc or RMB cancels")
        )
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._finish(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._screen_points = []
            self._drawing = True
            _append_screen_point(self._screen_points, event, force=True)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self._drawing:
            if _append_screen_point(self._screen_points, event):
                self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._drawing:
            _append_screen_point(self._screen_points, event, force=True)
            self._drawing = False
            try:
                organic_plane = self._create_plane(context)
            except ValueError as exc:
                self.report({"WARNING"}, str(exc))
                self._screen_points = []
                context.area.header_text_set(
                    t("Draw vertically with LMB to define the organic profile; Esc cancels")
                )
                self._tag_redraw(context)
                return {"RUNNING_MODAL"}
            except Exception as exc:
                self.report({"ERROR"}, t("Could not create organic plane: {error}", error=exc))
                self._finish(context)
                return {"CANCELLED"}

            self._finish(context)
            self.report(
                {"INFO"},
                t("Created {name}; reshape mode started", name=organic_plane.name),
            )
            try:
                bpy.ops.silicone.reshape_organic_plane("INVOKE_DEFAULT")
            except Exception:
                self.report(
                    {"WARNING"},
                    t("Plane created; use Reshape Organic Plane in the Dev panel to edit it"),
                )
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class SILICONE_OT_reshape_organic_plane(bpy.types.Operator):
    bl_idname = "silicone.reshape_organic_plane"
    bl_label = "Reshape Organic Plane"
    bl_description = (
        "Proportionally push, smooth, restore, or draw a top profile on the "
        "selected organic plane"
    )
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    _draw_handler = None
    _object = None
    _surface_data = None
    _original_data = ""
    _radius = 1.0
    _hover = None
    _dragging = False
    _drag_operation = "PUSH"
    _drag_start_mouse = None
    _drag_start_offsets = None
    _drag_center = None
    _mode = "EDIT"
    _top_drawing = False
    _top_screen_points = None
    _radius_adjusting = False
    _radius_adjust_start = 1.0
    _radius_adjust_start_mouse = None

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return bool(
            getattr(getattr(context, "area", None), "type", None) == "VIEW_3D"
            and obj is not None
            and getattr(obj, "type", None) == "MESH"
            and bool(obj.get(ORGANIC_PLANE_MARKER, False))
            and bool(obj.get(ORGANIC_PLANE_DATA_KEY, ""))
        )

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _set_edit_header(self, context):
        context.area.header_text_set(
            t(
                "Reshape: LMB push/pull · F/Wheel radius · Shift smooth · Ctrl restore · "
                "T top profile · R reset · MMB orbit · Enter confirm · Esc revert"
            )
        )

    def _set_radius_header(self, context):
        context.area.header_text_set(
            t("Radius: move horizontally · LMB/Enter confirms · Esc restores radius")
        )

    def _set_top_header(self, context):
        context.area.header_text_set(
            t("Top Profile: drag LMB across the plane depth · Esc/RMB returns to reshape")
        )

    def _finish(self, context):
        if self._draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._draw_handler, "WINDOW")
            except Exception:
                pass
            self._draw_handler = None
        try:
            context.area.header_text_set(None)
        except Exception:
            pass
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        self._tag_redraw(context)

    def _surface_parameters(self):
        data = self._surface_data
        depth_count = int(data["depth_count"])
        height_count = int(data["height_count"])
        depths = [
            float(data["depth_min"])
            + (float(data["depth_max"]) - float(data["depth_min"]))
            * index
            / (depth_count - 1)
            for index in range(depth_count)
        ]
        heights = [
            float(data["height_min"])
            + (float(data["height_max"]) - float(data["height_min"]))
            * index
            / (height_count - 1)
            for index in range(height_count)
        ]
        return depths, heights

    def _local_vertices(self):
        expected_count = int(self._surface_data["depth_count"]) * int(
            self._surface_data["height_count"]
        )
        mesh_vertices = self._object.data.vertices
        if len(mesh_vertices) >= expected_count:
            return [
                tuple(mesh_vertices[index].co) for index in range(expected_count)
            ]
        return organic_surface_mesh(self._surface_data)[0]

    def _raycast_local(self, context, event):
        from bpy_extras import view3d_utils  # type: ignore

        coordinate = (event.mouse_region_x, event.mouse_region_y)
        ray_origin = view3d_utils.region_2d_to_origin_3d(
            context.region,
            context.region_data,
            coordinate,
        )
        ray_direction = view3d_utils.region_2d_to_vector_3d(
            context.region,
            context.region_data,
            coordinate,
        )
        inverse = self._object.matrix_world.inverted()
        local_origin = inverse @ ray_origin
        local_direction = (inverse.to_3x3() @ ray_direction).normalized()
        hit, location, _normal, _face_index = self._object.ray_cast(
            local_origin,
            local_direction,
            distance=1.0e12,
        )
        return mathutils.Vector(location) if hit else None

    def _hover_from_event(self, context, event):
        from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore

        depth_axis = mathutils.Vector(self._surface_data["depth_axis"])
        local_hit = self._raycast_local(context, event)
        if local_hit is not None:
            return (local_hit.dot(depth_axis), local_hit.z, local_hit)

        mouse = mathutils.Vector((event.mouse_region_x, event.mouse_region_y))
        depths, heights = self._surface_parameters()
        local_vertices = self._local_vertices()
        depth_count = len(depths)
        depth_center = (
            float(self._surface_data["depth_min"])
            + float(self._surface_data["depth_max"])
        ) * 0.5
        best = None
        for height_index, height in enumerate(heights):
            for depth_index, depth in enumerate(depths):
                index = height_index * depth_count + depth_index
                local_point = mathutils.Vector(local_vertices[index])
                screen = location_3d_to_region_2d(
                    context.region,
                    context.region_data,
                    self._object.matrix_world @ local_point,
                )
                if screen is None:
                    continue
                screen_distance = (mathutils.Vector(screen) - mouse).length
                score = screen_distance + abs(depth - depth_center) * 1.0e-7
                if best is None or score < best[0]:
                    best = (score, screen_distance, depth, height, local_point)
        if best is None or best[1] > _HOVER_LIMIT_PIXELS:
            return None
        return (best[2], best[3], best[4])

    def _lateral_mouse_delta(self, context, event):
        from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore

        if self._hover is None:
            return 0.0
        local_point = mathutils.Vector(self._hover[2])
        lateral_axis = mathutils.Vector(self._surface_data["lateral_axis"])
        screen_origin = location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._object.matrix_world @ local_point,
        )
        screen_lateral = location_3d_to_region_2d(
            context.region,
            context.region_data,
            self._object.matrix_world @ (local_point + lateral_axis),
        )
        if screen_origin is None or screen_lateral is None:
            return 0.0
        screen_axis = mathutils.Vector(screen_lateral) - mathutils.Vector(screen_origin)
        pixels_per_unit = screen_axis.length
        if pixels_per_unit <= 1.0e-6:
            return 0.0
        screen_axis.normalize()
        mouse_delta = mathutils.Vector(
            (
                event.mouse_region_x - self._drag_start_mouse[0],
                event.mouse_region_y - self._drag_start_mouse[1],
            )
        )
        return mouse_delta.dot(screen_axis) / pixels_per_unit

    def _apply_drag(self, context, event):
        center_depth, center_height = self._drag_center
        mouse_distance = math.hypot(
            event.mouse_region_x - self._drag_start_mouse[0],
            event.mouse_region_y - self._drag_start_mouse[1],
        )
        strength = min(1.0, mouse_distance / 60.0)
        result = _organic_worker(
            "sculpt_surface",
            surface_data=self._surface_data,
            original_offsets=self._drag_start_offsets,
            center_depth=center_depth,
            center_height=center_height,
            radius=self._radius,
            brush_operation=self._drag_operation,
            displacement=(
                self._lateral_mouse_delta(context, event)
                if self._drag_operation == "PUSH"
                else 0.0
            ),
            strength=strength,
        )
        self._surface_data = result["surface"]
        _apply_surface_mesh(
            self._object,
            self._surface_data,
            result["vertices"],
            result["faces"],
        )
        self._tag_redraw(context)

    def _reset(self, context):
        self._surface_data["top_profile"] = [0.0] * int(
            self._surface_data["depth_count"]
        )
        self._surface_data["sculpt_offsets"] = [0.0] * (
            int(self._surface_data["depth_count"])
            * int(self._surface_data["height_count"])
        )
        _update_surface_mesh(self._object, self._surface_data)
        self._tag_redraw(context)

    def _radius_limits(self):
        depth_span = float(self._surface_data["depth_max"]) - float(
            self._surface_data["depth_min"]
        )
        height_span = float(self._surface_data["height_max"]) - float(
            self._surface_data["height_min"]
        )
        minimum = max(min(depth_span, height_span) / 60.0, 1.0e-4)
        maximum = max(depth_span, height_span) * 2.0
        return minimum, maximum

    def _begin_radius_adjustment(self, context, event):
        self._hover = self._hover_from_event(context, event)
        if self._hover is None:
            self.report({"WARNING"}, t("Hover over the organic plane before pressing F"))
            return False
        self._radius_adjusting = True
        self._radius_adjust_start = self._radius
        self._radius_adjust_start_mouse = (
            event.mouse_region_x,
            event.mouse_region_y,
        )
        self._set_radius_header(context)
        self._tag_redraw(context)
        return True

    def _adjust_radius_from_event(self, context, event):
        horizontal_delta = event.mouse_region_x - self._radius_adjust_start_mouse[0]
        minimum, maximum = self._radius_limits()
        self._radius = proportional_radius_from_drag(
            self._radius_adjust_start,
            horizontal_delta,
            minimum=minimum,
            maximum=maximum,
        )
        self._tag_redraw(context)

    def _end_radius_adjustment(self, context, *, restore=False):
        if restore:
            self._radius = self._radius_adjust_start
        self._radius_adjusting = False
        self._set_edit_header(context)
        self._tag_redraw(context)

    def _enter_top_profile(self, context):
        self._mode = "TOP_PROFILE"
        self._top_drawing = False
        self._top_screen_points = []
        self._set_top_header(context)
        try:
            bpy.ops.view3d.view_axis(type="TOP", align_active=False)
        except Exception:
            pass
        self._tag_redraw(context)

    def _leave_top_profile(self, context):
        self._mode = "EDIT"
        self._top_drawing = False
        self._top_screen_points = []
        self._radius_adjusting = False
        self._set_edit_header(context)
        self._tag_redraw(context)

    def _apply_top_profile(self, context):
        simplified = simplify_polyline(
            self._top_screen_points,
            _SIMPLIFY_TOLERANCE_PIXELS,
        )
        local_points = []
        inverse = self._object.matrix_world.inverted()
        center_height = (
            float(self._surface_data["height_min"])
            + float(self._surface_data["height_max"])
        ) * 0.5
        local_plane_point = mathutils.Vector((0.0, 0.0, center_height))
        world_plane_point = self._object.matrix_world @ local_plane_point
        world_normal = (
            self._object.matrix_world.to_3x3() @ mathutils.Vector((0.0, 0.0, 1.0))
        ).normalized()
        for screen_point in simplified:
            world_point = _screen_to_plane(
                context,
                screen_point,
                world_plane_point,
                world_normal,
            )
            if world_point is not None:
                local_points.append(tuple(inverse @ world_point))
        self._surface_data["top_profile"] = top_profile_from_stroke(
            local_points,
            self._surface_data,
        )
        _update_surface_mesh(self._object, self._surface_data)

    def _screen_radius(self):
        from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore

        if self._hover is None:
            return 0.0
        local_point = mathutils.Vector(self._hover[2])
        candidates = []
        for axis in (
            mathutils.Vector(self._surface_data["depth_axis"]),
            mathutils.Vector((0.0, 0.0, 1.0)),
        ):
            first = location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.region_data,
                self._object.matrix_world @ local_point,
            )
            second = location_3d_to_region_2d(
                bpy.context.region,
                bpy.context.region_data,
                self._object.matrix_world @ (local_point + axis * self._radius),
            )
            if first is not None and second is not None:
                candidates.append(
                    (mathutils.Vector(second) - mathutils.Vector(first)).length
                )
        return sum(candidates) / len(candidates) if candidates else 48.0

    def _draw_batch(self, shader, primitive, coordinates, color):
        if not coordinates:
            return
        from gpu_extras.batch import batch_for_shader  # type: ignore

        batch = batch_for_shader(shader, primitive, {"pos": coordinates})
        shader.bind()
        shader.uniform_float("color", color)
        batch.draw(shader)

    def _draw_overlay(self):
        try:
            import gpu  # type: ignore
            from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore

            shader = gpu.shader.from_builtin("UNIFORM_COLOR")
            gpu.state.blend_set("ALPHA")
            screen_vertices = [
                location_3d_to_region_2d(
                    bpy.context.region,
                    bpy.context.region_data,
                    self._object.matrix_world @ mathutils.Vector(vertex),
                )
                for vertex in self._local_vertices()
            ]
            depth_count = int(self._surface_data["depth_count"])
            height_count = int(self._surface_data["height_count"])
            lines = []
            for height_index in range(height_count):
                for depth_index in range(depth_count):
                    index = height_index * depth_count + depth_index
                    if depth_index + 1 < depth_count:
                        following = index + 1
                        if (
                            screen_vertices[index] is not None
                            and screen_vertices[following] is not None
                        ):
                            lines.extend(
                                (screen_vertices[index], screen_vertices[following])
                            )
                    if height_index + 1 < height_count:
                        following = index + depth_count
                        if (
                            screen_vertices[index] is not None
                            and screen_vertices[following] is not None
                        ):
                            lines.extend(
                                (screen_vertices[index], screen_vertices[following])
                            )
            gpu.state.line_width_set(1.0)
            self._draw_batch(shader, "LINES", lines, (0.2, 0.65, 1.0, 0.35))
            points = [point for point in screen_vertices if point is not None]
            gpu.state.point_size_set(4.0)
            self._draw_batch(shader, "POINTS", points, (0.35, 0.75, 1.0, 0.75))

            if self._hover is not None and self._mode == "EDIT":
                screen_hover = location_3d_to_region_2d(
                    bpy.context.region,
                    bpy.context.region_data,
                    self._object.matrix_world @ mathutils.Vector(self._hover[2]),
                )
                if screen_hover is not None:
                    radius = max(8.0, self._screen_radius())
                    circle = [
                        (
                            screen_hover.x + math.cos(step * math.tau / 48) * radius,
                            screen_hover.y + math.sin(step * math.tau / 48) * radius,
                        )
                        for step in range(48)
                    ]
                    circle.append(circle[0])
                    gpu.state.line_width_set(2.0)
                    self._draw_batch(
                        shader,
                        "LINE_STRIP",
                        circle,
                        (1.0, 0.45, 0.08, 0.95),
                    )
            if self._mode == "TOP_PROFILE" and self._top_screen_points:
                gpu.state.line_width_set(3.0)
                self._draw_batch(
                    shader,
                    "LINE_STRIP",
                    self._top_screen_points,
                    (1.0, 0.25, 0.1, 1.0),
                )
        except Exception:
            pass
        finally:
            try:
                import gpu  # type: ignore

                gpu.state.line_width_set(1.0)
                gpu.state.point_size_set(1.0)
                gpu.state.blend_set("NONE")
            except Exception:
                pass

    def invoke(self, context, _event):
        self._object = context.active_object
        try:
            self._surface_data = _decode_surface_data(self._object)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self._original_data = _encode_surface_data(self._surface_data)
        depth_span = float(self._surface_data["depth_max"]) - float(
            self._surface_data["depth_min"]
        )
        height_span = float(self._surface_data["height_max"]) - float(
            self._surface_data["height_min"]
        )
        self._radius = max(min(depth_span, height_span) * 0.22, 1.0e-3)
        self._hover = None
        self._dragging = False
        self._mode = "EDIT"
        self._top_drawing = False
        self._top_screen_points = []
        self._radius_adjusting = False
        self._draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_overlay,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        try:
            context.window.cursor_modal_set("CROSSHAIR")
        except Exception:
            pass
        self._set_edit_header(context)
        context.window_manager.modal_handler_add(self)
        self._tag_redraw(context)
        return {"RUNNING_MODAL"}


    def modal(self, context, event):
        if self._object is None or self._object.name not in bpy.data.objects:
            self._finish(context)
            return {"CANCELLED"}

        if self._mode == "TOP_PROFILE":
            if event.type in {"ESC", "RIGHTMOUSE", "T"} and event.value == "PRESS":
                self._leave_top_profile(context)
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self._top_screen_points = []
                self._top_drawing = True
                _append_screen_point(self._top_screen_points, event, force=True)
                self._tag_redraw(context)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE" and self._top_drawing:
                if _append_screen_point(self._top_screen_points, event):
                    self._tag_redraw(context)
                return {"RUNNING_MODAL"}
            if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._top_drawing:
                _append_screen_point(self._top_screen_points, event, force=True)
                self._top_drawing = False
                try:
                    self._apply_top_profile(context)
                except ValueError as exc:
                    self.report({"WARNING"}, str(exc))
                    self._top_screen_points = []
                    return {"RUNNING_MODAL"}
                except Exception as exc:
                    self.report({"ERROR"}, t("Could not apply top profile: {error}", error=exc))
                    self._top_screen_points = []
                    return {"RUNNING_MODAL"}
                self._leave_top_profile(context)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if self._radius_adjusting:
            if event.type == "MOUSEMOVE":
                self._adjust_radius_from_event(context, event)
                return {"RUNNING_MODAL"}
            if (
                event.type in {"LEFTMOUSE", "RET", "NUMPAD_ENTER", "F"}
                and event.value == "PRESS"
            ):
                self._end_radius_adjustment(context)
                return {"RUNNING_MODAL"}
            if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
                self._end_radius_adjustment(context, restore=True)
                return {"RUNNING_MODAL"}
            return {"RUNNING_MODAL"}

        if event.type == "ESC" and event.value == "PRESS":
            self._surface_data = json.loads(self._original_data)
            _update_surface_mesh(self._object, self._surface_data)
            self._finish(context)
            self.report({"INFO"}, t("Organic plane edits reverted"))
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            if float(self._surface_data.get("thickness", 0.0)) <= 0.0:
                self._surface_data["thickness"] = _DEFAULT_CUTTER_THICKNESS
            try:
                _update_surface_mesh(
                    self._object,
                    self._surface_data,
                    authoritative=True,
                )
            except Exception as exc:
                self.report({"ERROR"}, t("Could not finalize organic cutter: {error}", error=exc))
                return {"RUNNING_MODAL"}
            self._finish(context)
            self.report({"INFO"}, t("Organic plane confirmed as a thick cutter"))
            return {"FINISHED"}
        if event.type == "T" and event.value == "PRESS" and not self._dragging:
            self._enter_top_profile(context)
            return {"RUNNING_MODAL"}
        if event.type == "F" and event.value == "PRESS" and not self._dragging:
            self._begin_radius_adjustment(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "R" and event.value == "PRESS" and not self._dragging:
            self._reset(context)
            return {"RUNNING_MODAL"}
        if event.type in {"MIDDLEMOUSE", "NDOF_MOTION", "TRACKPADPAN", "TRACKPADZOOM"}:
            return {"PASS_THROUGH"}
        if event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"} and event.value == "PRESS":
            multiplier = 1.15 if event.type == "WHEELUPMOUSE" else 1.0 / 1.15
            minimum, maximum = self._radius_limits()
            self._radius = min(maximum, max(minimum, self._radius * multiplier))
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and not self._dragging:
            self._hover = self._hover_from_event(context, event)
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._hover = self._hover_from_event(context, event)
            if self._hover is None:
                return {"RUNNING_MODAL"}
            self._dragging = True
            self._drag_operation = (
                "SMOOTH" if event.shift else "RESTORE" if event.ctrl else "PUSH"
            )
            self._drag_start_mouse = (event.mouse_region_x, event.mouse_region_y)
            self._drag_start_offsets = list(self._surface_data["sculpt_offsets"])
            self._drag_center = (self._hover[0], self._hover[1])
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self._dragging:
            self._apply_drag(context, event)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._dragging:
            self._apply_drag(context, event)
            self._dragging = False
            self._hover = self._hover_from_event(context, event)
            return {"RUNNING_MODAL"}
        return {"RUNNING_MODAL"}


class SILICONE_OT_set_organic_plane_thickness(bpy.types.Operator):
    bl_idname = "silicone.set_organic_plane_thickness"
    bl_label = "Make Thick Cutter"
    bl_description = (
        "Convert the selected organic plane into a centered, capped watertight cutter"
    )
    bl_options = {"REGISTER", "UNDO"}

    thickness: FloatProperty(  # type: ignore
        name="Thickness",
        description="Total centered cutter thickness and resulting split kerf",
        default=0.1,
        min=0.001,
        soft_max=5.0,
        subtype="DISTANCE",
        unit="LENGTH",
    )

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return bool(
            _dev_mode_enabled()
            and obj is not None
            and getattr(obj, "type", None) == "MESH"
            and bool(obj.get(ORGANIC_PLANE_MARKER, False))
            and bool(obj.get(ORGANIC_PLANE_DATA_KEY, ""))
        )

    def draw(self, _context):
        self.layout.prop(self, "thickness")
        self.layout.label(text=t("The cutter expands equally on both sides"))

    def invoke(self, context, _event):
        obj = context.active_object
        existing = float(obj.get(ORGANIC_PLANE_THICKNESS_KEY, 0.0))
        self.thickness = existing if existing > 0.0 else 0.1
        return context.window_manager.invoke_props_dialog(self, width=320)

    def execute(self, context):
        obj = context.active_object
        try:
            surface_data = _decode_surface_data(obj, validate=False)
            surface_data["thickness"] = float(self.thickness)
            _update_surface_mesh(obj, surface_data, authoritative=True)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        obj.show_in_front = True
        self.report(
            {"INFO"},
            t(
                "Organic cutter thickness set to {thickness:.3f} mm",
                thickness=float(self.thickness),
            ),
        )
        return {"FINISHED"}


class SILICONE_OT_remove_organic_plane_thickness(bpy.types.Operator):
    bl_idname = "silicone.remove_organic_plane_thickness"
    bl_label = "Remove Cutter Thickness"
    bl_description = "Return the selected cutter to its zero-thickness editable surface"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = getattr(context, "active_object", None)
        return bool(
            _dev_mode_enabled()
            and obj is not None
            and getattr(obj, "type", None) == "MESH"
            and bool(obj.get(ORGANIC_PLANE_MARKER, False))
            and float(obj.get(ORGANIC_PLANE_THICKNESS_KEY, 0.0)) > 0.0
        )

    def execute(self, context):
        obj = context.active_object
        try:
            surface_data = _decode_surface_data(obj, validate=False)
            surface_data["thickness"] = 0.0
            _update_surface_mesh(obj, surface_data)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, t("Organic cutter returned to an editable surface"))
        return {"FINISHED"}


class SILICONE_OT_test_split_with_organic_plane(bpy.types.Operator):
    bl_idname = "silicone.test_split_with_organic_plane"
    bl_label = "Test Organic Split"
    bl_description = (
        "Subtract the selected thick organic plane from a duplicate target and "
        "separate the resulting components"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        cutter = getattr(context, "active_object", None)
        return bool(
            _dev_mode_enabled()
            and cutter is not None
            and getattr(cutter, "type", None) == "MESH"
            and bool(cutter.get(ORGANIC_PLANE_MARKER, False))
            and float(cutter.get(ORGANIC_PLANE_THICKNESS_KEY, 0.0)) > 0.0
        )

    def execute(self, context):
        cutter = context.active_object
        try:
            target = _selected_organic_split_target(context, cutter)
            parts = split_object_with_organic_plane(target, cutter)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        target.hide_set(True)
        target.hide_render = True
        cutter.hide_set(True)
        cutter.hide_render = True
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        for part in parts:
            part.hide_set(False)
            part.select_set(True)
        context.view_layer.objects.active = parts[0]
        self.report(
            {"INFO"},
            t(
                "Organic split test created {count} parts with one Difference Boolean",
                count=len(parts),
            ),
        )
        return {"FINISHED"}
