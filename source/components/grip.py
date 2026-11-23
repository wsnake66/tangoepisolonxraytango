import bpy  # type: ignore
import mathutils  # type: ignore

from ..object import *


def build_grip(
    height: float = 10, grip_span: float = 20, grip_depth: float = 10
) -> Object:
    grip = Object(create_cube_primitive(height), "grip")
    box = Object(bpy.data.objects.get("box"))
    grip.scale_to(box.width / 2 + grip_span, axis=0)
    grip.scale_to(grip_depth, axis=1)
    grip.translate_whole(
        mathutils.Vector(
            (box.max_x + grip_span - grip.max_x, 0, box.max_z - grip.max_z)
        )
    )
    # grip.origin_to_cursor()
    grip.apply_all_transforms()
    if grip.min_z < box.min_z:
        grip.cut_plane(
            mathutils.Vector((0, 0, -1)), mathutils.Vector((0, 0, box.min_z + 0.1))
        )
    return grip


def add_grip(box_voxel_size: float = 0.8):
    box = Object(bpy.data.objects.get("box"))
    grip = Object(bpy.data.objects.get("grip"))
    grip.apply_modifier(build_sharp_modifier(7))
    box += grip
    # box.apply_modifier(build_voxel_modifier(box_voxel_size))
    grip.remove()
    # box.clean_top(3)
    # box.clean_bot(2)
