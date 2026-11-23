import logging
import bpy  # type: ignore
import mathutils  # type: ignore

from ..constants import BOX_THICKNESS
from ..background_worker import BackgroundTaskSequence, finish_task_sync
from ..materials import assign_generated_material, prepare_material_transfer
from ..modifiers import diff_material_transfer_mod, diff_no_material_transfer_mod
from ..object import Object
from .base_substracter_visibility import set_base_substracter_hidden
from .mesh_envelope import begin_optimized_mesh_envelope
from .slip_casting_box_shape import begin_primitive_box

logger = logging.getLogger(__name__)
PENDING_CASTING_BOX_NAME = "_moldboxer_casting_box_pending"
WEIGHT_TEXT_CASTING_CUTTER_NAME = "weight_text_casting_cutter"


def different_casting_box_thickness(scene) -> float | None:
    if not getattr(scene, "pro_casting_box", False):
        return None
    if not getattr(scene, "pro_casting_box_different_thickness", False):
        return None
    return max(float(getattr(scene, "casting_box_thickness", BOX_THICKNESS)), 0.1)


def pending_casting_boxes() -> list[Object]:
    return [
        Object(raw)
        for raw in bpy.data.objects
        if raw.type == "MESH"
        and bool(raw.get("_moldboxer_different_thickness", False))
        and bool(raw.get("_moldboxer_pending_casting_box", False))
    ]


def mirror_pending_casting_addition(
    operand: Object,
    *,
    material_transfer: bool = False,
) -> bool:
    casting_boxes = pending_casting_boxes()
    if not casting_boxes:
        return False

    for casting_box in casting_boxes:
        operand_copy = operand.duplicate("_casting_mirror")
        try:
            if material_transfer:
                casting_box.add_with_material_transfer(operand_copy)
            else:
                casting_box += operand_copy
        finally:
            operand_copy.remove()
    return True


def mirror_pending_casting_subtraction(
    operand: Object,
    *,
    material_transfer: bool = True,
) -> bool:
    casting_boxes = pending_casting_boxes()
    if not casting_boxes:
        return False

    for casting_box in casting_boxes:
        operand_copy = operand.duplicate("_casting_mirror")
        try:
            if material_transfer:
                prepare_material_transfer(
                    casting_box.object,
                    operand_copy.object,
                )
            casting_box.apply_boolean_modifier(
                (
                    diff_material_transfer_mod
                    if material_transfer
                    else diff_no_material_transfer_mod
                ),
                target=operand_copy,
            )
        finally:
            operand_copy.remove()
    return True


def _open_box_object(
    source_box: Object,
    *,
    voxel_size: float,
    wall_thickness: float,
    result_name: str,
    subtract_source: bool = True,
    remove_source: bool = True,
) -> Object:
    return finish_task_sync(
        _begin_open_box_object(
            source_box,
            voxel_size=voxel_size,
            wall_thickness=wall_thickness,
            result_name=result_name,
            subtract_source=subtract_source,
            remove_source=remove_source,
        )
    )


def _begin_open_box_object(
    source_box: Object,
    *,
    voxel_size: float,
    wall_thickness: float,
    result_name: str,
    subtract_source: bool = True,
    remove_source: bool = True,
    top_z: float | None = None,
    shape_type: str = "adapted",
    vertical_faces: int = 4,
):
    """Build and plane-trim an outer wrapper around ``source_box``.

    Confirm generation can defer the interior subtraction so components are
    joined to the solid wrapper first. In that mode the source may also be
    retained and repurposed as the final opening cutter.
    """
    source_min_z = source_box.min_z
    wing_exists = bpy.data.objects.get("wing") is not None
    task = begin_primitive_box(
        source_box, distance=wall_thickness, shape_type=shape_type,
        matching_shape=True, vertical_faces=vertical_faces,
    ) if shape_type != "adapted" else begin_optimized_mesh_envelope(
        source_box,
        voxel_size=voxel_size,
        distance=wall_thickness,
        n_wraps=2,
        geometry_to_origin=False,
        cut_bot=False,
        remesh_scaled=True,
    )

    def finish(opened_box):
        if subtract_source:
            opened_box -= source_box
        cut_top_z = source_box.max_z - 0.1 if top_z is None else float(top_z)
        opened_box.cut_plane(
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, cut_top_z)),
        )
        if wing_exists:
            opened_box.clean_bot(
                0.5,
                custom_cut_point=mathutils.Vector(
                    (0, 0, source_box.min_z + 0.5)
                ),
            )
        if remove_source:
            source_box.remove()
        opened_box.name = result_name
        opened_box.object["_moldboxer_source_min_z"] = source_min_z
        assign_generated_material(opened_box.object)
        return opened_box

    return task.then(finish)


def _z9f3(
    _a7: float = 1.2,
    _b4: float = BOX_THICKNESS,
    _c2: float = 3.2,
    *,
    _casting_b4=None,
    reuse_source_as_base_substracter: bool = False,
):
    logger.info(
        f"_z9f3 {_a7=} {_b4=} {_c2=} {_casting_b4=} "
        f"{reuse_source_as_base_substracter=}"
    )
    solid_box = Object(bpy.data.objects.get("box"))
    if _casting_b4 is not None:
        pending_casting_box = bpy.data.objects.get(PENDING_CASTING_BOX_NAME)
        if pending_casting_box is not None:
            Object(pending_casting_box).remove()
        casting_source = solid_box.duplicate("_casting_source")
        casting_box = _open_box_object(
            casting_source,
            voxel_size=_a7,
            wall_thickness=_casting_b4,
            result_name=PENDING_CASTING_BOX_NAME,
            subtract_source=not reuse_source_as_base_substracter,
        )
        casting_box.object["_moldboxer_different_thickness"] = True
        casting_box.object["_moldboxer_wall_thickness"] = float(_casting_b4)
        casting_box.object["_moldboxer_pending_casting_box"] = True
    opened_box = _open_box_object(
        solid_box,
        voxel_size=_a7,
        wall_thickness=_b4,
        result_name="box",
        subtract_source=not reuse_source_as_base_substracter,
        remove_source=not reuse_source_as_base_substracter,
    )
    if reuse_source_as_base_substracter:
        solid_box.name = "base_substracter"
        opened_box.name = "box"
        set_base_substracter_hidden(True)
    return opened_box


def begin_z9f3(
    _a7: float = 1.2,
    _b4: float = BOX_THICKNESS,
    _c2: float = 3.2,
    *,
    _casting_b4: float | None = None,
    reuse_source_as_base_substracter: bool = False,
    top_z: float | None = None,
    shape_type: str = "adapted",
    vertical_faces: int = 4,
):
    """Build the primary box wrapper and optional casting-box wrapper.

    When ``reuse_source_as_base_substracter`` is true, every wrapper is built
    from the untouched source before the source becomes ``base_substracter``.
    The returned wrappers remain solid until the confirm pipeline assembles
    their components and performs its single opening subtraction.
    """
    logger.info(
        f"_z9f3 {_a7=} {_b4=} {_c2=} {_casting_b4=} "
        f"{reuse_source_as_base_substracter=}"
    )

    def steps():
        solid_box = Object(bpy.data.objects.get("box"))
        if _casting_b4 is not None:
            pending_casting_box = bpy.data.objects.get(PENDING_CASTING_BOX_NAME)
            if pending_casting_box is not None:
                Object(pending_casting_box).remove()
            casting_source = solid_box.duplicate("_casting_source")
            casting_box = yield _begin_open_box_object(
                casting_source,
                voxel_size=_a7,
                wall_thickness=_casting_b4,
                result_name=PENDING_CASTING_BOX_NAME,
                top_z=top_z,
                shape_type=shape_type,
                vertical_faces=vertical_faces,
                subtract_source=not reuse_source_as_base_substracter,
            )
            casting_box.object["_moldboxer_different_thickness"] = True
            casting_box.object["_moldboxer_wall_thickness"] = float(_casting_b4)
            casting_box.object["_moldboxer_pending_casting_box"] = True
        opened_box = yield _begin_open_box_object(
            solid_box,
            voxel_size=_a7,
            wall_thickness=_b4,
            result_name="box",
            top_z=top_z,
            shape_type=shape_type,
            vertical_faces=vertical_faces,
            subtract_source=not reuse_source_as_base_substracter,
            remove_source=not reuse_source_as_base_substracter,
        )
        if reuse_source_as_base_substracter:
            solid_box.name = "base_substracter"
            opened_box.name = "box"
            set_base_substracter_hidden(True)
        return opened_box

    return BackgroundTaskSequence(steps())
