import math

import bpy  # type: ignore
import mathutils  # type: ignore

from ..background_worker import BackgroundTaskSequence
from ..bl_utils import ensure_moldboxer_transform_gizmos_for_selection
from ..materials import assign_funnels_material
from ..modifiers import build_z_projection_modifier
from ..object import Object, remove_objects_safely
from ..primitives import (
    create_cube_primitive,
    create_cylinder_primitive,
    create_plane_primitive,
)
from .geometry_adapter import (
    begin_plan_limit_face_with_worker,
    begin_project_casting_input_with_worker,
    plan_limit_face_with_worker,
    project_casting_input_with_worker,
)

CASTING_INPUT_NAME = "casting_input"
CASTING_INPUT_HEIGHT = 5.0
CASTING_INPUT_DIAMETER = 5.0
CASTING_INPUT_AXIS = "NEG_Z"
CASTING_INPUT_TOP_VERTEX_GROUP = "casting_input_top_face"
CASTING_INPUT_BOTTOM_VERTEX_GROUP = "casting_input_bottom_face"
CASTING_INPUT_BASE_PLANE_NAME = "sprue_base_projection_plane"


def get_world_limit_face_center(
    target: Object,
    axis: int = 0,
    max_co: bool = False,
) -> mathutils.Vector:
    _face_index, center = plan_limit_face_with_worker(
        target.object,
        axis=axis,
        max_co=max_co,
        average_ties=True,
        world_space=True,
    )
    return mathutils.Vector(center)


def get_casting_input_axis_settings(
    axis_name: str,
) -> tuple[int, bool, mathutils.Matrix]:
    axis_map = {
        "NEG_X": (0, False, mathutils.Matrix.Rotation(math.radians(90), 4, "Y")),
        "POS_X": (0, True, mathutils.Matrix.Rotation(math.radians(90), 4, "Y")),
        "NEG_Y": (1, False, mathutils.Matrix.Rotation(math.radians(90), 4, "X")),
        "POS_Y": (1, True, mathutils.Matrix.Rotation(math.radians(90), 4, "X")),
        "NEG_Z": (2, False, mathutils.Matrix.Identity(4)),
        "POS_Z": (2, True, mathutils.Matrix.Identity(4)),
    }
    try:
        return axis_map[axis_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported casting input axis '{axis_name}'") from exc


def _get_casting_input_target(context) -> Object:
    target_raw = bpy.data.objects.get("patron")
    if target_raw is None:
        target_raw = context.active_object or bpy.context.active_object
    if target_raw is None:
        raise ValueError("No active object selected")
    if target_raw.type != "MESH":
        raise ValueError("Selected object must be a mesh")
    return Object(target_raw)


def _create_casting_input_base_plane(target: Object, base_offset: float) -> Object:
    plane = Object(create_plane_primitive(), CASTING_INPUT_BASE_PLANE_NAME)
    plane.scale_to(target.width * 10, axis=0)
    plane.scale_to(target.depth * 10, axis=1)
    plane.translate_whole(
        mathutils.Vector(
            (
                target.center_coords.x - plane.center_coords.x,
                target.center_coords.y - plane.center_coords.y,
                target.min_z - base_offset - plane.center_coords.z,
            )
        )
    )
    plane.object.hide_render = True
    plane.object.hide_select = True
    plane.object.display_type = "WIRE"
    plane.object.hide_set(True)
    return plane


def _add_casting_input_projection(
    casting_input: Object,
    target: Object,
    base_offset: float,
) -> None:
    top_face_idx = casting_input.get_limit_face_idx(axis=2, max_co=True, flat=True)
    bottom_face_idx = casting_input.get_limit_face_idx(axis=2, max_co=False, flat=True)
    base_plane = _create_casting_input_base_plane(target, base_offset)
    casting_input.create_vertex_group(
        CASTING_INPUT_TOP_VERTEX_GROUP,
        casting_input.get_face_verts_idxs(top_face_idx),
    )
    casting_input.create_vertex_group(
        CASTING_INPUT_BOTTOM_VERTEX_GROUP,
        casting_input.get_face_verts_idxs(bottom_face_idx),
    )
    casting_input.add_modifier(
        build_z_projection_modifier(CASTING_INPUT_TOP_VERTEX_GROUP),
        target=target,
    )
    casting_input.add_modifier(
        build_z_projection_modifier(
            CASTING_INPUT_BOTTOM_VERTEX_GROUP,
            offset=0,
            wrap_mode="ON_SURFACE",
            use_positive_direction=False,
            use_negative_direction=True,
        ),
        target=base_plane,
    )


def create_casting_input(
    context,
    *,
    shape: str | None = None,
    project_top: bool | None = None,
    base_offset: float | None = None,
) -> Object:
    target = _get_casting_input_target(context)
    axis, max_co, rotation_matrix = get_casting_input_axis_settings(CASTING_INPUT_AXIS)
    input_center = get_world_limit_face_center(target, axis=axis, max_co=max_co)
    input_radius = CASTING_INPUT_DIAMETER / 2
    selected_shape = shape or str(context.scene.casting_input_shape)

    if selected_shape == "CUBE":
        casting_input = Object(create_cube_primitive(1), CASTING_INPUT_NAME)
        casting_input.scale_to(CASTING_INPUT_DIAMETER, axis=0)
        casting_input.scale_to(CASTING_INPUT_DIAMETER, axis=1)
        casting_input.scale_to(CASTING_INPUT_HEIGHT, axis=2)
    else:
        casting_input = Object(
            create_cylinder_primitive(input_radius, CASTING_INPUT_HEIGHT),
            CASTING_INPUT_NAME,
        )
    assign_funnels_material(casting_input.object)
    casting_input.rotate_whole(rotation_matrix)
    casting_input.translate_whole(input_center - casting_input.center_coords)
    should_project_top = (
        bool(getattr(context.scene, "casting_input_project_top", True))
        if project_top is None
        else project_top
    )
    if should_project_top:
        selected_base_offset = (
            float(getattr(context.scene, "casting_input_base_offset", 0.0))
            if base_offset is None
            else base_offset
        )
        _add_casting_input_projection(casting_input, target, selected_base_offset)
    casting_input.origin_to_geometry()
    casting_input.select()
    ensure_moldboxer_transform_gizmos_for_selection(context)
    return casting_input


def begin_create_casting_input(
    context,
    *,
    shape: str | None = None,
    project_top: bool | None = None,
    base_offset: float | None = None,
):
    target = _get_casting_input_target(context)
    axis, max_co, rotation_matrix = get_casting_input_axis_settings(
        CASTING_INPUT_AXIS
    )
    task = begin_plan_limit_face_with_worker(
        target.object,
        axis=axis,
        max_co=max_co,
        average_ties=True,
        world_space=True,
    )

    def finish(plan):
        _face_index, center = plan
        input_center = mathutils.Vector(center)
        input_radius = CASTING_INPUT_DIAMETER / 2
        selected_shape = shape or str(context.scene.casting_input_shape)
        if selected_shape == "CUBE":
            casting_input = Object(create_cube_primitive(1), CASTING_INPUT_NAME)
            casting_input.scale_to(CASTING_INPUT_DIAMETER, axis=0)
            casting_input.scale_to(CASTING_INPUT_DIAMETER, axis=1)
            casting_input.scale_to(CASTING_INPUT_HEIGHT, axis=2)
        else:
            casting_input = Object(
                create_cylinder_primitive(input_radius, CASTING_INPUT_HEIGHT),
                CASTING_INPUT_NAME,
            )
        assign_funnels_material(casting_input.object)
        casting_input.rotate_whole(rotation_matrix)
        casting_input.translate_whole(input_center - casting_input.center_coords)
        should_project_top = (
            bool(getattr(context.scene, "casting_input_project_top", True))
            if project_top is None
            else project_top
        )
        if should_project_top:
            selected_base_offset = (
                float(getattr(context.scene, "casting_input_base_offset", 0.0))
                if base_offset is None
                else base_offset
            )
            _add_casting_input_projection(
                casting_input,
                target,
                selected_base_offset,
            )
        casting_input.origin_to_geometry()
        casting_input.select()
        ensure_moldboxer_transform_gizmos_for_selection(context)
        return casting_input

    return task.then(finish)


def confirm_casting_input(context) -> Object:
    target_raw = bpy.data.objects.get("patron")
    if target_raw is None:
        raise ValueError("No patron object found")
    if target_raw.type != "MESH":
        raise ValueError("Patron object must be a mesh")

    casting_inputs = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.startswith(CASTING_INPUT_NAME)
    ]
    if not casting_inputs:
        raise ValueError("No casting input to confirm")

    target = Object(target_raw)
    for casting_input in casting_inputs:
        projection_active = _casting_input_projection_active(casting_input)
        if projection_active:
            base_plane_raw = None
            for modifier in tuple(casting_input.object.modifiers):
                if (
                    modifier.type == "SHRINKWRAP"
                    and modifier.vertex_group
                    in {
                        CASTING_INPUT_TOP_VERTEX_GROUP,
                        CASTING_INPUT_BOTTOM_VERTEX_GROUP,
                    }
                ):
                    if modifier.vertex_group == CASTING_INPUT_BOTTOM_VERTEX_GROUP:
                        base_plane_raw = modifier.target
                    casting_input.object.modifiers.remove(modifier)
            if base_plane_raw is None:
                raise RuntimeError("Casting input projection base plane is missing")
            project_casting_input_with_worker(
                casting_input,
                target,
                Object(base_plane_raw),
                top_vertex_group=CASTING_INPUT_TOP_VERTEX_GROUP,
                bottom_vertex_group=CASTING_INPUT_BOTTOM_VERTEX_GROUP,
            )
        casting_input.apply_all_modifiers()
        if not projection_active:
            casting_input.cut_plane(
                mathutils.Vector((0, 0, -1)),
                mathutils.Vector((0, 0, target.min_z)),
            )
        target.join(casting_input)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(CASTING_INPUT_BASE_PLANE_NAME):
            remove_objects_safely((obj,))
    target.select()
    return target


def begin_confirm_casting_input(context):
    target_raw = bpy.data.objects.get("patron")
    if target_raw is None or target_raw.type != "MESH":
        raise ValueError("No valid patron object found")
    casting_inputs = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.startswith(CASTING_INPUT_NAME)
    ]
    if not casting_inputs:
        raise ValueError("No casting input to confirm")
    target = Object(target_raw)

    def steps():
        for casting_input in casting_inputs:
            projection_active = _casting_input_projection_active(casting_input)
            if projection_active:
                base_plane_raw = None
                for modifier in tuple(casting_input.object.modifiers):
                    if (
                        modifier.type == "SHRINKWRAP"
                        and modifier.vertex_group
                        in {
                            CASTING_INPUT_TOP_VERTEX_GROUP,
                            CASTING_INPUT_BOTTOM_VERTEX_GROUP,
                        }
                    ):
                        if modifier.vertex_group == CASTING_INPUT_BOTTOM_VERTEX_GROUP:
                            base_plane_raw = modifier.target
                        casting_input.object.modifiers.remove(modifier)
                if base_plane_raw is None:
                    raise RuntimeError(
                        "Casting input projection base plane is missing"
                    )
                yield begin_project_casting_input_with_worker(
                    casting_input,
                    target,
                    Object(base_plane_raw),
                    top_vertex_group=CASTING_INPUT_TOP_VERTEX_GROUP,
                    bottom_vertex_group=CASTING_INPUT_BOTTOM_VERTEX_GROUP,
                )
            casting_input.apply_all_modifiers()
            if not projection_active:
                casting_input.cut_plane(
                    mathutils.Vector((0, 0, -1)),
                    mathutils.Vector((0, 0, target.min_z)),
                )
            target.join(casting_input)
        for obj in list(bpy.data.objects):
            if obj.name.startswith(CASTING_INPUT_BASE_PLANE_NAME):
                remove_objects_safely((obj,))
        target.select()
        return target

    return BackgroundTaskSequence(steps())


def add_casting_input(context) -> Object:
    create_casting_input(context)
    return confirm_casting_input(context)


def _casting_input_projection_active(casting_input: Object) -> bool:
    projected_groups = {
        CASTING_INPUT_TOP_VERTEX_GROUP,
        CASTING_INPUT_BOTTOM_VERTEX_GROUP,
    }
    for modifier in casting_input.object.modifiers:
        if (
            modifier.type == "SHRINKWRAP"
            and bool(getattr(modifier, "show_viewport", True))
            and getattr(modifier, "vertex_group", "") in projected_groups
        ):
            return True
    return False
