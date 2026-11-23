import bpy  # type: ignore
import mathutils  # type: ignore
from mathutils import Euler  # type: ignore
import logging
import time

from ..object import *
from .mesh_envelope import *
from ..constants import *

logger = logging.getLogger(__name__)


def _set_extraction_object_hidden(obj: Object, hidden: bool) -> None:
    blender_obj = getattr(obj, "object", None)
    if blender_obj is None or blender_obj.name not in bpy.data.objects:
        return
    blender_obj.hide_set(hidden)
    blender_obj.hide_viewport = hidden
    blender_obj.hide_render = hidden


def clear_horizontal_extraction_path(
    extra_extrussion_dist: float = 10,
    voxel_size: float = 0.8,
):
    start = time.time()
    box = Object(bpy.data.objects.get("box"))
    patron = Object(bpy.data.objects.get("patron"))
    box.name = "box_original"
    box.select()
    closest_face_normal = mathutils.Vector((-1, 0, 0))
    closest_face_normal.rotate(Euler((0.0, 0.0, math.radians(90.0)), "XYZ"))
    closest_face_normal.normalize()
    mold_box_left = cut_and_extrude(
        box,
        mathutils.Vector((0, extra_extrussion_dist, 0)),
        closest_face_normal,
        cut_rotation=90,
        extra_extrussion_dist=extra_extrussion_dist,
        voxel_size=voxel_size,
    )
    mold_box_right = cut_and_extrude(
        box,
        mathutils.Vector((0, -extra_extrussion_dist, 0)),
        closest_face_normal,
        cut_rotation=-90,
        extra_extrussion_dist=extra_extrussion_dist,
        voxel_size=voxel_size,
    )
    mold_box_left += mold_box_right

    mold_box_right.remove()
    # mold_box_left.clean_bot(2)
    # mold_box_left.clean_top(3)
    mold_box_left.apply_modifier(build_voxel_modifier(voxel_size * 0.75))
    mold_box_left.cut_plane(
        mathutils.Vector((0, 0, -1)), mathutils.Vector((0, 0, patron.min_z))
    )
    # mold_box_left.cut_plane(
    #     mathutils.Vector((0, 0, 1)), mathutils.Vector((0, 0, original_max_z))
    # )
    # mold_box_left.clean_bot(0.4)
    mold_box_left.clean_top(1)
    mold_box_left.name = "box"
    box.remove()

    logger.info("Classic clear horizontal extraction took %.3fs", time.time() - start)
    return mold_box_left


def clear_vertical_extraction_path(
    voxel_size: float = 0.8,
):
    box = Object(bpy.data.objects.get("box"))
    box.name = "box_original"
    box.hide_during_ui_breathe = True
    box.select()
    original_max_z = box.max_z
    array_box = create_extraction_path(
        box,
        mathutils.Vector((0, 0, 1)),
        voxel_size=voxel_size,
        hide_construction=True,
    )
    array_box.cut_plane(
        mathutils.Vector((0, 0, 1)), mathutils.Vector((0, 0, original_max_z))
    )
    # array_box.clean_bot(2)
    # array_box.apply_modifier(build_voxel_modifier(voxel_size))
    # array_box.clean_bot(1)
    # array_box.clean_top(1)
    array_box.name = "box"
    box.remove()
    _set_extraction_object_hidden(array_box, False)

    return array_box


def cut_and_extrude(
    mold_box: Object,
    point: mathutils.Vector,
    plane_flat_normal: mathutils.Vector,
    cut_rotation: Literal[90, -90],
    extra_extrussion_dist: float = 10,
    voxel_size: float = 0.8,
    copies_per_array: int = 5,
):
    mold_box_copy = mold_box.duplicate(name_adder=f"_cut_{cut_rotation}")
    angle = math.radians(cut_rotation)
    rot_matrix = mathutils.Matrix.Rotation(angle, 4, "Z")
    cut_plane = rot_matrix @ plane_flat_normal
    mold_box_copy.cut_plane(cut_plane, point)
    cut_resolution = 1
    cut_vector = cut_plane * cut_resolution
    if 0.99 < cut_plane[1] < 1.01:
        target_extrussion_distance = mold_box_copy.depth
    else:
        target_extrussion_distance = max(mold_box_copy.width, mold_box_copy.depth)
    target_extrussion_distance += extra_extrussion_dist

    # cut res == extruded dist
    start = time.time()
    while cut_resolution < target_extrussion_distance:
        logger.debug(
            f"Cutting with resolution {cut_resolution}m, {cut_vector=}m, {target_extrussion_distance=}m"
        )
        mold_box_copy.apply_modifier(
            build_array_modifier(copies_per_array, [cut_vector[0], cut_vector[1], 0])
        )
        cut_resolution *= copies_per_array
        cut_vector *= copies_per_array
        mold_box_copy.apply_modifier(build_voxel_modifier(voxel_size))

    mold_box_copy.cut_plane(cut_plane, point + cut_plane.normalized())
    logger.debug(f"Cutting took {time.time() - start}s")
    return mold_box_copy


def create_extraction_path(
    target: Object,
    array_dir: mathutils.Vector,
    extra_array_dist: float = 0,
    voxel_size: float = 0.8,
    copies_per_array: int = 5,
    extrusion_distance: Optional[float] = None,
    hide_construction: bool = False,
):
    target_copy = target.duplicate(name_adder=f"array")
    if hide_construction:
        target_copy.hide_during_ui_breathe = True
    cut_resolution = 0.6
    cut_vector = array_dir * cut_resolution
    if extrusion_distance is None:
        if array_dir == mathutils.Vector((0, 0, 1)):
            target_extrussion_distance = target_copy.height
        else:
            target_extrussion_distance = max(target_copy.width, target_copy.height)

        target_extrussion_distance += extra_array_dist
    else:
        target_extrussion_distance = extrusion_distance

    while cut_resolution < target_extrussion_distance:
        logger.debug(
            f"Cutting with resolution {cut_resolution}m, {cut_vector=}m, {target_extrussion_distance=}m"
        )
        target_copy.apply_modifier(
            build_array_modifier(
                copies_per_array, [cut_vector[0], cut_vector[1], cut_vector[2]]
            )
        )
        cut_resolution *= copies_per_array
        cut_vector *= copies_per_array
        target_copy.apply_modifier(build_voxel_modifier(voxel_size))

    return target_copy
