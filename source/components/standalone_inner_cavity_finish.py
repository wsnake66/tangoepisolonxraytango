import importlib
import logging
import math
import os
import re
import sys

import bpy  # type: ignore
import mathutils  # type: ignore

if __package__ in (None, ""):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from source import primitives
    from source.components.clear_undercuts import clear_undercuts
    from source.components.mesh_envelope import MeshEnvelope
    from source.materials import assign_inner_core_material, assign_moldbox_material
    from source.modifiers import diff_no_material_transfer_mod
    from source.object import Object
    from source.voxel_size import get_box_voxel_size
else:
    from .. import primitives
    from .clear_undercuts import clear_undercuts
    from .mesh_envelope import MeshEnvelope
    from ..materials import assign_inner_core_material, assign_moldbox_material
    from ..modifiers import diff_no_material_transfer_mod
    from ..object import Object
    from ..voxel_size import get_box_voxel_size


def blender_process(func):
    return func

logger = logging.getLogger(__name__)

INNER_CORE_PLANTER_TOP_CUT = 3.0
INNER_CORE_PLANTER_TOP_CUT_RETRIES = 3
INNER_CORE_PLANTER_TOP_CUT_RETRY_FACTOR = 1.5
INNER_CORE_PLANTER_QUALITY = "DRAFT"
INNER_CORE_PLANTER_OVERLAP_HEIGHT = 3.0
INNER_CORE_PLANTER_REMESH_AFTER_OPENING = True
INNER_CORE_CAVITY_EXCLUSION_Z_MARGIN = 10.0
INNER_CORE_CAVITY_EXCLUSION_DEPTH = 10.0
INNER_CORE_CAVITY_EXCLUSION_WIDTH_OVERTRAVEL = 2.0
INNER_CORE_CAVITY_EXCLUSION_CYLINDER_DIAMETER = 25.0
INNER_CORE_CAVITY_EXCLUSION_CYLINDER_TOP_OFFSET = 5.0
INNER_CORE_MULTI_PART_CYLINDER_EXTRA_DROP = 5.0
INNER_CORE_CAVITY_EXCLUSION_CYLINDER_OVERTRAVEL = 2.0
INNER_CORE_PIN_DIAMETER = 4.0
INNER_CORE_PIN_CLEARANCE_DIAMETER_EXTRA = 0.5
INNER_CORE_PIN_DEPTH_OVERTRAVEL = 4.0
INNER_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR = 2.0
INNER_CORE_PIN_BOX_CUTTER_WIDTH = 20.0
INNER_CORE_PIN_BOX_CUTTER_HEIGHT = 10.0
INNER_CORE_DEBUG_KEEP_PIN_CLEARANCE = False
INNER_CORE_DEBUG_KEEP_CAVITY_OPERANDS = False
INNER_CORE_BOX_CLEARANCE_TOP_OFFSET = 10.0
SILICONE_DISPLACEMENT_CUTTER_MARKER = (
    "moldboxer_inner_core_silicone_displacement_cutter"
)

STANDALONE_CORE_RE = re.compile(
    r"^inner_cavity_standalone_core_(?P<core>\d{3})(?:_\d{3})?(?:\.\d{3})?$"
)
ATTACHER_RE = re.compile(
    r"^attacher_(?P<core>\d{3})(?:_(?P<attachment>\d{3}))?(?:\.\d{3})?$"
)
ATTACH_SOCKET_RE = re.compile(r"^attach_socket(?:_\d{3}){0,2}(?:\.\d{3})?$")
SOCKET_CUTTER_RE = re.compile(
    r"^inner_core_socket_cutter_(?P<core>\d{3})"
    r"(?:_(?P<attachment>\d{3}))?_to_sub"
    r"(?:_\d{3})?(?:\.\d{3})?$"
)


def hide_during_inner_core_refresh(obj: Object) -> Object:
    obj.hide_during_ui_breathe = True
    return obj


def get_object_by_name(name: str) -> Object | None:
    blender_object = bpy.data.objects.get(name)
    if blender_object is None:
        return None
    return hide_during_inner_core_refresh(Object(blender_object))


def find_standalone_inner_cavity_core_objects() -> list[Object]:
    cores_by_index: dict[str, Object] = {}

    for blender_object in bpy.context.scene.objects:
        core_match = STANDALONE_CORE_RE.match(blender_object.name)
        if core_match:
            cores_by_index[core_match.group("core")] = (
                hide_during_inner_core_refresh(Object(blender_object))
            )

    return [cores_by_index[index] for index in sorted(cores_by_index)]


def find_attacher_objects() -> dict[str, list[Object]]:
    attachers_by_index: dict[str, list[Object]] = {}

    for blender_object in sorted(bpy.context.scene.objects, key=lambda obj: obj.name):
        core_match = ATTACHER_RE.match(blender_object.name)
        if core_match:
            attachers_by_index.setdefault(core_match.group("core"), []).append(
                hide_during_inner_core_refresh(Object(blender_object))
            )

    return attachers_by_index


def find_attach_socket_objects() -> list[Object]:
    return [
        hide_during_inner_core_refresh(Object(blender_object))
        for blender_object in sorted(
            bpy.context.scene.objects,
            key=lambda obj: obj.name,
        )
        if ATTACH_SOCKET_RE.match(blender_object.name)
    ]


def find_inner_core_socket_cutters() -> dict[str, list[Object]]:
    cutters_by_index: dict[str, list[Object]] = {}
    for blender_object in sorted(bpy.context.scene.objects, key=lambda obj: obj.name):
        cutter_match = SOCKET_CUTTER_RE.match(blender_object.name)
        if cutter_match:
            cutters_by_index.setdefault(cutter_match.group("core"), []).append(
                hide_during_inner_core_refresh(Object(blender_object))
            )
    return cutters_by_index


def subtract_socket_cutter_from_core(core: Object, cutter: Object) -> None:
    """Cut a core-side socket while retaining the original box cutter."""

    core_cutter = cutter.duplicate(name_adder="_core_socket")
    core_cutter.hide_during_ui_breathe = True
    try:
        core.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=core_cutter,
        )
    finally:
        core_cutter.remove()


def create_multi_part_core_pin(
    core: Object,
    attachers: list[Object],
    box: Object,
    reference_index: int,
) -> Object:
    """Create a printable pin and cut its clearances from the assembled parts."""

    if not attachers:
        raise ValueError("Multi-Part inner-core pin requires an attacher")
    reference_attacher = attachers[0]

    pin = Object(
        primitives.create_cube_primitive(size=1),
        f"core_pin_{reference_index:03d}",
    )
    pin.hide_during_ui_breathe = True
    pin_profile_side = INNER_CORE_PIN_DIAMETER / math.sqrt(2.0)
    pin.scale_to(pin_profile_side, 0)
    pin.scale_to(core.depth + INNER_CORE_PIN_DEPTH_OVERTRAVEL, 1)
    pin.scale_to(pin_profile_side, 2)
    pin.rotate_whole(mathutils.Matrix.Rotation(math.radians(45), 4, "Y"))
    pin.translate_whole(
        mathutils.Vector(
            (
                core.center_coords.x - pin.center_coords.x,
                core.center_coords.y - pin.center_coords.y,
                reference_attacher.center_coords.z - pin.center_coords.z,
            )
        )
    )
    assign_inner_core_material(pin.object)

    clearance = pin.duplicate(name_adder="_clearance")
    clearance.name = f"temp_core_pin_clearance_{reference_index:03d}"
    clearance.hide_during_ui_breathe = True
    clearance_diameter = (
        INNER_CORE_PIN_DIAMETER + INNER_CORE_PIN_CLEARANCE_DIAMETER_EXTRA
    )
    clearance_profile_scale = clearance_diameter / INNER_CORE_PIN_DIAMETER
    clearance.scale(clearance_profile_scale, 0)
    clearance.scale_to(
        box.depth * INNER_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR,
        1,
    )
    clearance.scale(clearance_profile_scale, 2)
    clearance.translate_whole(pin.center_coords - clearance.center_coords)

    box_cutter = Object(
        primitives.create_cube_primitive(size=1),
        f"temp_core_pin_box_cutter_{reference_index:03d}",
    )
    box_cutter.hide_during_ui_breathe = True
    box_cutter.scale_to(INNER_CORE_PIN_BOX_CUTTER_WIDTH, 0)
    box_cutter.scale_to(
        box.depth * INNER_CORE_PIN_CLEARANCE_BOX_DEPTH_FACTOR,
        1,
    )
    box_cutter.scale_to(INNER_CORE_PIN_BOX_CUTTER_HEIGHT, 2)
    box_cutter.translate_whole(
        mathutils.Vector(
            (
                pin.center_coords.x - box_cutter.center_coords.x,
                pin.center_coords.y - box_cutter.center_coords.y,
                reference_attacher.min_z - box_cutter.min_z,
            )
        )
    )
    try:
        core.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=clearance,
        )
        for attacher in attachers:
            attacher.apply_boolean_modifier(
                diff_no_material_transfer_mod,
                target=clearance,
            )
        box.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=box_cutter,
        )
    finally:
        if not INNER_CORE_DEBUG_KEEP_PIN_CLEARANCE:
            clearance.remove()
        box_cutter.remove()

    return pin


def create_vertical_core_clearance_for_box(
    context,
    box: Object,
    core: Object,
) -> Object:
    """Create an upward-swept core cutter for the assembled box."""

    voxel_size = get_box_voxel_size(context.scene.box_quality, core)
    clearance = MeshEnvelope(
        core,
        voxel_size=voxel_size,
        distance=0.7,
        n_wraps=1,
        name_adder="_box_vertical_clearance",
        build_from_sphere=False,
        normal_offset=2.0,
    )
    clearance.name = f"temp_clear_{core.name}"
    assign_moldbox_material(clearance.object)
    clearance.hide_during_ui_breathe = True
    target_max_z = box.max_z + INNER_CORE_BOX_CLEARANCE_TOP_OFFSET
    clear_undercuts(
        target_object=clearance,
        bidirectional=False,
        voxel_size=voxel_size,
        target_retry_voxel_size=voxel_size,
        target_point=mathutils.Vector((0.0, 0.0, target_max_z)),
        plane_direction=mathutils.Vector((0.0, 0.0, -1.0)),
        clearance_build_overtravel_override=0.0,
        display_extraction_directions=False,
        smooth_target_after_remesh=False,
    )
    return clearance


def create_core_cavity_exclusion(
    core: Object,
    reference_index: int,
    is_multi_part: bool = False,
    attachment_at_bottom: bool = False,
    center_y: float | None = None,
) -> Object:
    exclusion = Object(
        primitives.create_cube_primitive(size=1),
        f"temp_cavity_exclusion_{reference_index:03d}",
    )
    exclusion.hide_during_ui_breathe = True
    exclusion.scale_to(
        core.width + INNER_CORE_CAVITY_EXCLUSION_WIDTH_OVERTRAVEL,
        0,
    )
    exclusion.scale_to(INNER_CORE_CAVITY_EXCLUSION_DEPTH, 1)

    min_z = core.min_z - INNER_CORE_CAVITY_EXCLUSION_Z_MARGIN
    max_z = core.max_z + INNER_CORE_CAVITY_EXCLUSION_Z_MARGIN
    placement_center_y = (
        core.center_coords.y if center_y is None else float(center_y)
    )
    exclusion.scale_to(max_z - min_z, 2)
    exclusion.translate_whole(
        mathutils.Vector(
            (
                core.center_coords.x - exclusion.center_coords.x,
                placement_center_y - exclusion.center_coords.y,
                (min_z + max_z) * 0.5 - exclusion.center_coords.z,
            )
        )
    )
    exclusion_cylinder = Object(
        primitives.create_cylinder_primitive(
            INNER_CORE_CAVITY_EXCLUSION_CYLINDER_DIAMETER / 2,
            INNER_CORE_CAVITY_EXCLUSION_DEPTH
            + INNER_CORE_CAVITY_EXCLUSION_CYLINDER_OVERTRAVEL,
        ),
        f"temp_cavity_exclusion_cylinder_{reference_index:03d}",
    )
    exclusion_cylinder.hide_during_ui_breathe = True
    exclusion_cylinder.rotate_whole(
        mathutils.Matrix.Rotation(math.radians(90), 4, "X")
    )
    cylinder_top_offset = INNER_CORE_CAVITY_EXCLUSION_CYLINDER_TOP_OFFSET
    if is_multi_part:
        cylinder_top_offset += INNER_CORE_MULTI_PART_CYLINDER_EXTRA_DROP
    if attachment_at_bottom:
        cylinder_z_translation = (
            core.min_z
            + cylinder_top_offset
            - exclusion_cylinder.min_z
        )
    else:
        cylinder_z_translation = (
            core.max_z
            - cylinder_top_offset
            - exclusion_cylinder.max_z
        )
    exclusion_cylinder.translate_whole(
        mathutils.Vector(
            (
                exclusion.center_coords.x - exclusion_cylinder.center_coords.x,
                exclusion.center_coords.y - exclusion_cylinder.center_coords.y,
                cylinder_z_translation,
            )
        )
    )
    try:
        exclusion -= exclusion_cylinder
    finally:
        exclusion_cylinder.remove()
    return exclusion


def align_core_top_to_attacher(
    core: Object,
    attacher: Object,
) -> None:
    """Move the core's trimmed top-face group to the attacher top plane."""

    selected_count = core.select_limit_flat_faces(max_co=True)
    if selected_count == 0:
        raise RuntimeError(
            f"Could not select the trimmed top faces of inner cavity core {core.name}"
        )

    movement = attacher.max_z - core.max_z
    if abs(movement) <= 1e-6:
        return
    core.move_selected(movement)
    logger.debug(
        "Aligned inner cavity core top to attacher: core=%s movement=%.6g "
        "target_z=%.6g result_z=%.6g",
        core.name,
        movement,
        attacher.max_z,
        core.max_z,
    )


def convert_inner_cavity_core_to_planter(
    context,
    core: Object,
    attacher: Object,
    reference_index: int,
) -> Object:
    package_name = __package__ or ""
    package_suffix = ".source.components"
    if package_name == "source.components":
        addon_package = ""
    elif package_name.endswith(package_suffix):
        addon_package = package_name[: -len(package_suffix)]
    else:
        addon_package = ""
    hollower_module = importlib.import_module(
        f"{addon_package}.hollower" if addon_package else "hollower"
    )
    logger.debug("Converting inner cavity core %s to planter", core.name)
    is_multi_part = (
        str(getattr(context.scene, "pro_inner_cavity_core_type", "SINGLE_PART"))
        == "MULTI_PART"
    )
    cavity_exclusion = create_core_cavity_exclusion(
        core,
        reference_index,
        is_multi_part=is_multi_part,
    )
    original_name = core.name
    last_error: Exception | None = None
    try:
        for attempt_index in range(INNER_CORE_PLANTER_TOP_CUT_RETRIES + 1):
            top_cut_amount = INNER_CORE_PLANTER_TOP_CUT * (
                INNER_CORE_PLANTER_TOP_CUT_RETRY_FACTOR**attempt_index
            )
            candidate: Object | None = None
            try:
                candidate = core.duplicate(
                    name_adder=f"_planter_attempt_{attempt_index + 1}"
                )
                candidate.hide_during_ui_breathe = True
                hollower_module.convert_inner_core_to_planter(
                    context,
                    candidate.object,
                    cavity_exclusion.object,
                    cavity_inset=float(context.scene.box_thickness),
                    quality=INNER_CORE_PLANTER_QUALITY,
                    top_cut_amount=top_cut_amount,
                    top_overlap_height=INNER_CORE_PLANTER_OVERLAP_HEIGHT,
                    remesh_after_top_opening=INNER_CORE_PLANTER_REMESH_AFTER_OPENING,
                    keep_cavity=INNER_CORE_DEBUG_KEEP_CAVITY_OPERANDS,
                    kept_cavity_name=(
                        f"temp_cavity_cutter_{reference_index:03d}_"
                        f"attempt_{attempt_index + 1}"
                    ),
                )
                align_core_top_to_attacher(candidate, attacher)
                candidate.clean_top(2)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Inner cavity core %s planter attempt %d/%d failed at "
                    "top cut %.6g mm",
                    original_name,
                    attempt_index + 1,
                    INNER_CORE_PLANTER_TOP_CUT_RETRIES + 1,
                    top_cut_amount,
                    exc_info=True,
                )
                if candidate is not None:
                    candidate.remove()
                continue

            core.remove()
            candidate.name = original_name
            return candidate

        logger.error(
            "Skipping hollowing for inner cavity core %s after %d failed "
            "attempts; keeping the original solid core. Last error: %s",
            original_name,
            INNER_CORE_PLANTER_TOP_CUT_RETRIES + 1,
            last_error,
        )
        return core
    finally:
        if not INNER_CORE_DEBUG_KEEP_CAVITY_OPERANDS:
            cavity_exclusion.remove()


def create_silicone_displacement_cutter(
    core: Object,
    reference_index: int,
) -> Object:
    """Preserve the solid core volume used to calculate silicone usage."""

    cutter = core.duplicate(name_adder="_silicone_displacement")
    cutter.name = f"temp_silicone_displacement_core_{reference_index:03d}"
    cutter.hide_during_ui_breathe = True
    cutter.object[SILICONE_DISPLACEMENT_CUTTER_MARKER] = True
    cutter.object.hide_set(True)
    cutter.object.hide_viewport = True
    cutter.object.hide_render = True
    return cutter


@blender_process
def main(
    context=None,
):
    context = context or bpy.context
    box = get_object_by_name("box")
    attach_sockets = find_attach_socket_objects()
    cores = find_standalone_inner_cavity_core_objects()
    attachers = find_attacher_objects()
    socket_cutters = find_inner_core_socket_cutters()
    core_type = str(
        getattr(context.scene, "pro_inner_cavity_core_type", "SINGLE_PART")
    )
    is_multi_part = core_type == "MULTI_PART"

    if not cores:
        logger.debug("No inner cavity cores found, skipping planter conversion")
        for core_attachers in attachers.values():
            for attacher in core_attachers:
                attacher.remove()
        for socket in attach_sockets:
            socket.remove()
        return

    if box is None:
        raise ValueError("Object named 'box' was not found in this Blender scene")

    pairs: list[tuple[Object, list[Object]]] = []
    for core in cores:
        core_match = STANDALONE_CORE_RE.match(core.name)
        if core_match is None:
            raise ValueError(
                f"Could not determine inner cavity core index from {core.name}"
            )
        core_index = core_match.group("core")
        core_attachers = attachers.get(core_index, [])
        if not core_attachers:
            raise ValueError(
                f"Object named 'attacher_{core_index}' was not found in this Blender scene"
            )
        pairs.append((core, core_attachers))

    for core in cores:
        create_vertical_core_clearance_for_box(
            context,
            box,
            core,
        )

    finished_multi_part_cores: list[tuple[Object, list[Object], int]] = []
    for reference_index, (core, core_attachers) in enumerate(pairs, start=1):
        reference_attacher = core_attachers[0]
        create_silicone_displacement_cutter(core, reference_index)
        core = convert_inner_cavity_core_to_planter(
            context,
            core,
            reference_attacher,
            reference_index,
        )
        if is_multi_part:
            core_match = STANDALONE_CORE_RE.match(core.name)
            core_index = core_match.group("core") if core_match else None
            core_socket_cutters = socket_cutters.get(core_index or "", [])
            if len(core_socket_cutters) != len(core_attachers):
                raise ValueError(
                    "Inner-core attachment response has mismatched parts for "
                    f"{core.name}: attachers={len(core_attachers)} "
                    f"socket_cutters={len(core_socket_cutters)}"
                )
            for socket_cutter in core_socket_cutters:
                subtract_socket_cutter_from_core(core, socket_cutter)
            finished_multi_part_cores.append(
                (core, core_attachers, reference_index)
            )
        else:
            reference_attacher.join(core)
            for extra_attacher in core_attachers[1:]:
                reference_attacher.join(extra_attacher)
            assign_inner_core_material(reference_attacher.object)

    # Pin clearances alter both finished Multi-Part pieces, so defer them until
    # every other inner-core construction step has completed.
    for core, core_attachers, reference_index in finished_multi_part_cores:
        create_multi_part_core_pin(core, core_attachers, box, reference_index)


def finish_inner_cavity_from_scene(
    context=None,
):
    main(context=context)


if __name__ == "__main__":
    main()
