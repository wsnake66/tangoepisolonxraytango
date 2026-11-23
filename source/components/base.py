import time
import logging
import functools
from typing import Literal

from .silicone_mold import (
    DEFAULT_SILICONE_DENSITY,
    SILICONE_WEIGHT_TEXT_SIZE,
    calculate_silicone_weight,
)
from .watermark_mesh_server import request_weight_text_mesh
from ..object import *
from .mesh_envelope import *
from .geometry_adapter import (
    build_master_base_pin_target,
    clear_master_base_pin_target,
    plan_master_base_pin_with_worker,
    plan_weight_text_extension_with_worker,
)
from ..constants import WING_WIDTH
from ..bl_utils import (
    GenerationStoppedError,
    get_exception_blender_object,
    show_popup,
)
from ..materials import assign_pin_keys_material
from ..modifiers import (
    Modifier,
    build_sharp_modifier,
    build_voxel_modifier,
    diff_mod,
)
from ..operator_access import is_lite_tier
from ..mold_types import is_direct_mold_type, silicone_multipart_bottom_extension
from ..patron_lifecycle import (
    get_master_for_base_operations,
    get_patron_for_base_pin_operations,
)
from ..voxel_size import get_master_voxel_size
from ..slicer_mesh_cleanup import clean_mesh_for_slicer
from .server import _remesh_imported_barrier
from ._q7x import (
    WEIGHT_TEXT_CASTING_CUTTER_NAME,
    mirror_pending_casting_addition,
)

logger = logging.getLogger(__name__)

DEFAULT_MASTER_BASE_PIN_HEIGHT = 2.5
MASTER_BASE_PIN_FEMALE_HEIGHT_OFFSET = 0.7
MASTER_BASE_PIN_PRIMARY_CLEAN_HEIGHT = 3.0
MASTER_BASE_PIN_FALLBACK_CLEAN_HEIGHT = 0.75
MASTER_BASE_PIN_SHARP_QUALITY_LEVELS = {
    "FAST": 6,
    "MID": 7,
    "HIGH": 8,
    "EXTREME": 9,
}
DEFAULT_MASTER_BASE_PIN_TOLERANCE = 0.3
MASTER_BASE_PIN_MAX_SPLIT_RETRIES = 2
PATRON_BASE_JOIN_Z_OFFSET = -0.25
WEIGHT_TEXT_EXTENSION_REFERENCE_FONT_SIZE = 5.0
WEIGHT_TEXT_EXTENSION_SCALE = (
    SILICONE_WEIGHT_TEXT_SIZE / WEIGHT_TEXT_EXTENSION_REFERENCE_FONT_SIZE
)
WEIGHT_TEXT_EXTENSION_PADDING = 1.0 * WEIGHT_TEXT_EXTENSION_SCALE
WEIGHT_TEXT_EXTENSION_OUTWARD_SPAN = 5.0 * WEIGHT_TEXT_EXTENSION_SCALE
WEIGHT_TEXT_OUTWARD_SHIFT = 4.0 * WEIGHT_TEXT_EXTENSION_SCALE
WEIGHT_TEXT_EXTENSION_BEVEL_RADIUS = WEIGHT_TEXT_EXTENSION_PADDING
WEIGHT_TEXT_EXTENSION_BEVEL_SEGMENTS = 8
WEIGHT_TEXT_CASTING_CUTTER_OVERSIZE = 0.4
WEIGHT_TEXT_EXACT_DIFF_MOD = Modifier(
    "BOOLEAN",
    {"operation": "DIFFERENCE", "solver": "EXACT"},
)


def _weight_text_z_bounds(wing) -> tuple[float, float]:
    return wing.min_z + 0.5, wing.max_z + 0.4


def _bevel_weight_text_extension_vertical_edges(extension: Object) -> None:
    with BMeshObj(extension, repair_winding=True) as bm:
        vertical_edges = []
        for edge in bm.edges:
            direction = edge.verts[1].co - edge.verts[0].co
            if direction.length <= 1e-6:
                continue
            if abs(direction.normalized().z) > 0.999:
                vertical_edges.append(edge)

        if not vertical_edges:
            return

        bmesh.ops.bevel(
            bm,
            geom=vertical_edges,
            offset=WEIGHT_TEXT_EXTENSION_BEVEL_RADIUS,
            segments=WEIGHT_TEXT_EXTENSION_BEVEL_SEGMENTS,
            profile=0.5,
            affect="EDGES",
        )


def _remove_weight_text_casting_cutter() -> None:
    existing = bpy.data.objects.get(WEIGHT_TEXT_CASTING_CUTTER_NAME)
    if existing is not None:
        Object(existing).remove()


def _create_weight_text_casting_cutter(
    _extension: Object,
    plan: dict,
) -> Object:
    """Retain an oversized cube for removing the label tab from casting boxes."""
    _remove_weight_text_casting_cutter()
    min_x, max_x, min_y, max_y, min_z, max_z = plan[
        "casting_cutter_bounds"
    ]
    cutter = Object(
        create_cube_primitive(1),
        WEIGHT_TEXT_CASTING_CUTTER_NAME,
    )
    cutter.scale_to(max_x - min_x, axis=0)
    cutter.scale_to(max_y - min_y, axis=1)
    cutter.scale_to(max_z - min_z, axis=2)
    cutter.translate_whole(
        mathutils.Vector(
            (
                min_x - cutter.min_x,
                min_y - cutter.min_y,
                min_z - cutter.min_z,
            )
        )
    )
    cutter.hide_during_ui_breathe = True
    cutter.object.hide_set(True)
    cutter.object.hide_viewport = True
    cutter.object.hide_render = True
    return cutter


def _replace_mesh_from_weight_text_candidate(
    target: Object,
    candidate: Object,
) -> None:
    old_mesh = target.object.data
    target.object.data = candidate.object.data
    candidate.remove()
    if old_mesh.users == 0 and old_mesh.name in bpy.data.meshes:
        bpy.data.meshes.remove(old_mesh)


def subtract_weight_text_with_validation(
    target: Object,
    vol_text: Object,
) -> bool:
    """Commit engraving when MANIFOLD or Exact applies a non-empty Boolean."""
    for solver_name, modifier in (
        ("MANIFOLD", diff_mod),
        ("EXACT", WEIGHT_TEXT_EXACT_DIFF_MOD),
    ):
        candidate = target.duplicate("_weight_text_candidate")
        attempt_start = time.perf_counter()
        try:
            candidate.apply_boolean_modifier(modifier, target=vol_text)
            if candidate.has_empty_boolean:
                raise RuntimeError("Weight-text Boolean modifier did not apply")

            _replace_mesh_from_weight_text_candidate(target, candidate)
            candidate = None
            logger.info(
                "Weight-text engraving committed on %s with solver=%s "
                "elapsed=%.3fs",
                target.name,
                solver_name,
                time.perf_counter() - attempt_start,
            )
            return True
        except Exception:
            logger.warning(
                "Weight-text %s Boolean failed on %s; elapsed=%.3fs",
                solver_name,
                target.name,
                time.perf_counter() - attempt_start,
                exc_info=True,
            )
        finally:
            if (
                candidate is not None
                and candidate.object.name in bpy.data.objects
            ):
                candidate.remove()

    logger.error(
        "Skipped weight-text engraving on %s because MANIFOLD and Exact "
        "Boolean attempts failed",
        target.name,
    )
    return False


def _validate_weight_text_extension_union(wing: Object) -> None:
    """Repair the extension union before any engraving modifies the wing."""
    if wing.is_manifold():
        return

    cleanup_start = time.perf_counter()
    clean_mesh_for_slicer(wing.object.data)
    if wing.is_manifold():
        logger.info(
            "Weight-text extension union repaired by local cleanup on %s; "
            "elapsed=%.3fs",
            wing.name,
            time.perf_counter() - cleanup_start,
        )
        return

    raise RuntimeError("Weight-text extension union could not be made manifold")


def _add_weight_text_extension(
    wing: Object,
    vol_text: Object,
    center_y: float,
    *,
    min_z: float | None = None,
    max_z: float | None = None,
    attachment_min_x: float | None = None,
    text_min_x: float | None = None,
    attachment_overlap: float | None = None,
    extension_name: str = "weight_text_extension",
    before_union_callback=None,
) -> tuple[float, float]:
    plan = plan_weight_text_extension_with_worker(
        wing.min_x,
        wing.min_z,
        wing.max_z,
        vol_text.width,
        vol_text.depth,
        center_y,
        WEIGHT_TEXT_EXTENSION_PADDING,
        WEIGHT_TEXT_EXTENSION_OUTWARD_SPAN,
        WEIGHT_TEXT_OUTWARD_SHIFT,
        WEIGHT_TEXT_CASTING_CUTTER_OVERSIZE,
        min_z=min_z,
        max_z=max_z,
        attachment_min_x=attachment_min_x,
        text_min_x=text_min_x,
        attachment_overlap=attachment_overlap,
    )
    min_x, max_x, min_y, max_y, min_z, max_z = plan[
        "extension_bounds"
    ]
    extension = Object(
        create_cube_primitive(1),
        extension_name,
    )
    try:
        extension.scale_to(max_x - min_x, axis=0)
        extension.scale_to(max_y - min_y, axis=1)
        extension.scale_to(max_z - min_z, axis=2)
        extension.translate_whole(
            mathutils.Vector(
                (
                    min_x - extension.min_x,
                    min_y - extension.min_y,
                    min_z - extension.min_z,
                )
            )
        )
        _bevel_weight_text_extension_vertical_edges(extension)
        if before_union_callback is not None:
            before_union_callback(extension, plan)
        wing += extension
        _validate_weight_text_extension_union(wing)
    finally:
        extension.remove()
    placement = plan["text_placement"]
    return placement["min_x"], placement["center_y"]


class FemalePinCheckerFailed(Exception):
    pass


def _get_base_for_basing() -> Object:
    exact_base = bpy.data.objects.get("base")
    if exact_base is not None:
        if exact_base.type != "MESH":
            raise ValueError("Required object 'base' exists but is not a mesh")
        return Object(exact_base)

    base_candidates = sorted(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                obj.name.lower() == "base"
                or obj.name.lower().startswith("base.")
            )
        ),
        key=lambda obj: obj.name.lower(),
    )
    if not base_candidates:
        raise ValueError("Required mesh object 'base' was not found")

    base_object = base_candidates[-1]
    original_name = base_object.name
    base_object.name = "base"
    logger.warning(
        "Using suffixed base object %s and renaming it to %s",
        original_name,
        base_object.name,
    )
    return Object(base_object)


def _join_master_to_base(base: Object, master: Object) -> None:
    master_for_base = master.duplicate(name_adder="_base_join")
    local_offset = mathutils.Matrix.Translation(
        mathutils.Vector((0, 0, 0.0 if silicone_multipart_bottom_extension(bpy.context.scene)
                          else PATRON_BASE_JOIN_Z_OFFSET))
    )
    master_for_base.object.matrix_world = (
        master_for_base.object.matrix_world @ local_offset
    )
    base.join(master_for_base)


def _scale_master_base_pin(
    cube: Object,
    pin_width: float,
    pin_depth: float,
) -> None:
    cube.scale_to(pin_width, axis=0)
    cube.scale_to(pin_depth, axis=1)
    cube.apply_all_transforms()
    top_face = cube.get_limit_face_idx(axis=2, max_co=True)
    cube.scale_face(0.9, 0, top_face)
    cube.scale_face(0.9, 1, top_face)
    cube.scale_face(0.7, 0, cube.get_limit_face_idx(axis=1, max_co=True))


def _scale_pin_xy_around_center(
    pin: Object,
    scale_x: float,
    scale_y: float,
) -> None:
    center = pin.inverse_matrix_world @ pin.center_coords
    transform = (
        mathutils.Matrix.Translation(center)
        @ mathutils.Matrix.Diagonal((scale_x, scale_y, 1, 1))
        @ mathutils.Matrix.Translation(-center)
    )
    with BMeshObj(pin, repair_winding=True) as bm:
        bm.transform(transform)


def _shrink_male_pin_from_female(
    male_pin: Object,
    female_pin: Object,
    tolerance: float,
    male_height: float,
) -> bool:
    if female_pin.width <= tolerance * 2 or female_pin.depth <= tolerance * 2:
        return False

    male_pin.scale_to(male_height, axis=2)
    male_pin.translate_whole(
        mathutils.Vector((0, 0, female_pin.min_z - male_pin.min_z))
    )

    scale_x = (female_pin.width - tolerance * 2) / female_pin.width
    scale_y = (female_pin.depth - tolerance * 2) / female_pin.depth
    _scale_pin_xy_around_center(male_pin, scale_x, scale_y)
    return True


def _split_axis_normal(axis: Literal["x", "y"]) -> mathutils.Vector:
    if axis == "x":
        return mathutils.Vector((1, 0, 0))
    return mathutils.Vector((0, 1, 0))


def build_patron_base_pin_pair(
    mesh: Object,
    patron: Object,
    index: int,
    tolerance: float = DEFAULT_MASTER_BASE_PIN_TOLERANCE,
    pin_height: float = DEFAULT_MASTER_BASE_PIN_HEIGHT,
) -> tuple[Object, Object] | None:
    placement = plan_master_base_pin_with_worker(
        mesh,
        tolerance=tolerance,
        requested_male_height=pin_height,
    )
    if not placement.accepted:
        if placement.checker_failed:
            raise FemalePinCheckerFailed()
        return None

    if (
        placement.center is None
        or placement.pin_size is None
        or placement.female_bottom_z is None
        or placement.female_height is None
        or placement.male_height is None
    ):
        raise RuntimeError("worker returned an incomplete pin placement")

    cube_female = Object(
        create_cube_primitive(placement.female_height),
        f"base_pin_female_{index}",
    )
    _scale_master_base_pin(
        cube_female, placement.pin_size, placement.pin_size
    )
    cube_female.translate_whole(
        mathutils.Vector(
            (
                placement.center[0] - cube_female.center_coords.x,
                placement.center[1] - cube_female.center_coords.y,
                placement.female_bottom_z - cube_female.min_z,
            )
        )
    )

    cube_male = cube_female.duplicate(name_adder="_male")
    cube_male.name = f"base_pin_male_{index}"
    if not _shrink_male_pin_from_female(
        cube_male,
        cube_female,
        tolerance,
        placement.male_height,
    ):
        cube_female.remove()
        cube_male.remove()
        return None

    return cube_male, cube_female


def _try_build_patron_base_pin_pair(
    mesh: Object,
    patron: Object,
    index: int,
    tolerance: float,
    pin_height: float,
) -> tuple[tuple[Object, Object] | None, bool]:
    try:
        return (
            build_patron_base_pin_pair(
                mesh,
                patron,
                index,
                tolerance,
                pin_height,
            ),
            False,
        )
    except FemalePinCheckerFailed:
        return None, True


def _try_split_axis_without_subsplitting(
    mesh: Object,
    patron: Object,
    index: int,
    tolerance: float,
    pin_height: float,
    split_axis: Literal["x", "y"],
) -> list[tuple[Object, Object]]:
    split_source = mesh.duplicate(name_adder=f"_{split_axis}_split_source")
    split_a, split_b = split_source.split_optimized(
        _split_axis_normal(split_axis), split_source.center_coords
    )
    isolated_meshes = [split_a, split_b]
    try:
        isolated_meshes = []
        for split_mesh in (split_a, split_b):
            isolated_meshes.extend(split_mesh.split_isolated_meshes())

        pin_pairs = []
        for split_index, split_mesh in enumerate(isolated_meshes):
            pin_pair, _checker_failed = _try_build_patron_base_pin_pair(
                split_mesh,
                patron,
                index * 10 + split_index,
                tolerance,
                pin_height,
            )
            if pin_pair is not None:
                pin_pairs.append(pin_pair)
        return pin_pairs
    finally:
        for split_mesh in isolated_meshes:
            split_mesh.remove()


def build_patron_base_pin_pairs_for_mesh(
    mesh: Object,
    patron: Object,
    index: int,
    tolerance: float,
    pin_height: float,
    split_retries: int = 0,
) -> list[tuple[Object, Object]]:
    pin_pair, checker_failed = _try_build_patron_base_pin_pair(
        mesh,
        patron,
        index,
        tolerance,
        pin_height,
    )
    if pin_pair is not None:
        return [pin_pair]

    if not checker_failed:
        return []

    if split_retries >= MASTER_BASE_PIN_MAX_SPLIT_RETRIES:
        return []

    for axis_index, split_axis in enumerate(("x", "y")):
        logger.debug(
            "Female pin checker failed for %s; trying direct split on %s axis "
            "(retry %s/%s)",
            mesh.name,
            split_axis,
            split_retries + 1,
            MASTER_BASE_PIN_MAX_SPLIT_RETRIES,
        )
        pin_pairs = _try_split_axis_without_subsplitting(
            mesh,
            patron,
            index * 100 + axis_index * 10,
            tolerance,
            pin_height,
            split_axis,
        )
        if pin_pairs:
            logger.debug(
                "Master-base direct split on %s axis succeeded for %s with %s pin pair%s",
                split_axis,
                mesh.name,
                len(pin_pairs),
                "" if len(pin_pairs) == 1 else "s",
            )
            return pin_pairs

    for axis_index, split_axis in enumerate(("x", "y")):
        logger.debug(
            "Master-base direct splits failed for %s; subsplitting %s axis children "
            "(retry %s/%s)",
            mesh.name,
            split_axis,
            split_retries + 1,
            MASTER_BASE_PIN_MAX_SPLIT_RETRIES,
        )
        split_source = mesh.duplicate(name_adder=f"_{split_axis}_subsplit_source")
        split_a, split_b = split_source.split_optimized(
            _split_axis_normal(split_axis), split_source.center_coords
        )
        isolated_meshes = [split_a, split_b]
        try:
            isolated_meshes = []
            for split_mesh in (split_a, split_b):
                isolated_meshes.extend(split_mesh.split_isolated_meshes())

            pin_pairs = []
            for split_index, split_mesh in enumerate(isolated_meshes):
                pin_pairs.extend(
                    build_patron_base_pin_pairs_for_mesh(
                        split_mesh,
                        patron,
                        index * 100 + axis_index * 10 + split_index,
                        tolerance,
                        pin_height,
                        split_retries + 1,
                    )
                )
            if pin_pairs:
                return pin_pairs
        finally:
            for split_mesh in isolated_meshes:
                split_mesh.remove()

    return []


def _clean_patron_bottom_for_pin_placement(
    patron: Object,
    requested_clean_height: float,
) -> None:
    clean_height = min(float(requested_clean_height), patron.height)
    if clean_height <= 0:
        return

    obj = patron.object
    was_hidden = obj.hide_get()
    was_hide_viewport = obj.hide_viewport
    was_hide_render = obj.hide_render
    try:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.hide_render = False
        logger.debug(
            "Cleaning master-base pin patron bottom before placement: height=%.3f",
            clean_height,
        )
        try:
            patron.clean_bot(clean_height)
        except ModifierApplyError as exc:
            if exc.modifier_name != "BOOLEAN" or exc.failed_object != patron.object:
                raise
            if patron.is_manifold():
                raise

            master_quality = bpy.context.scene.master_quality
            sharp_level = MASTER_BASE_PIN_SHARP_QUALITY_LEVELS.get(master_quality, 7)
            logger.warning(
                "Master-base pin reference cleanup Boolean failed on non-manifold "
                "%s; sharp-remeshing with master quality=%s octree_depth=%s and "
                "retrying",
                patron.name,
                master_quality,
                sharp_level,
                exc_info=True,
            )
            patron.apply_modifier(build_sharp_modifier(sharp_level))
            patron.clean_bot(clean_height)
    finally:
        obj.hide_set(was_hidden)
        obj.hide_viewport = was_hide_viewport
        obj.hide_render = was_hide_render


def _cut_patron_base_pin_sample(
    patron_bot: Object,
    pin_patron: Object,
    sample_height: float,
) -> None:
    plane_normal = mathutils.Vector((0, 0, 1))
    plane_point = mathutils.Vector((0, 0, pin_patron.min_z + sample_height))
    try:
        patron_bot.cut_plane(plane_normal, plane_point)
    except ModifierApplyError as exc:
        if exc.modifier_name != "BOOLEAN" or exc.failed_object != patron_bot.object:
            raise
        if patron_bot.is_manifold():
            raise

        master_quality = bpy.context.scene.master_quality
        sharp_level = MASTER_BASE_PIN_SHARP_QUALITY_LEVELS.get(master_quality, 7)
        logger.warning(
            "Base pin sample Boolean failed on non-manifold %s; "
            "sharp-remeshing with master quality=%s octree_depth=%s and retrying",
            patron_bot.name,
            master_quality,
            sharp_level,
            exc_info=True,
        )
        patron_bot.apply_modifier(build_sharp_modifier(sharp_level))
        patron_bot.cut_plane(plane_normal, plane_point)


def _search_patron_base_pin_pairs(
    candidate_meshes: list[Object],
    pin_patron: Object,
    tolerance: float,
    pin_height: float,
) -> list[tuple[Object, Object]]:
    pin_pairs = []
    for index, mesh in enumerate(candidate_meshes):
        pin_pairs.extend(
            build_patron_base_pin_pairs_for_mesh(
                mesh,
                pin_patron,
                index,
                tolerance,
                pin_height,
            )
        )
    return pin_pairs


def _build_patron_base_pins_with_clean_height(
    patron: Object,
    tolerance: float,
    pin_height: float,
    clean_height: float,
) -> list[tuple[Object, Object]]:
    pin_patron = patron.duplicate(name_adder="_base_pin_reference")
    candidate_meshes: list[Object] = []
    worker_target_built = False
    try:
        _clean_patron_bottom_for_pin_placement(pin_patron, clean_height)

        sample_height = pin_height + MASTER_BASE_PIN_FEMALE_HEIGHT_OFFSET
        search_patron = pin_patron.duplicate(name_adder="_base_pin_sample")
        candidate_meshes = [search_patron]
        _cut_patron_base_pin_sample(
            search_patron,
            pin_patron,
            sample_height,
        )
        # Candidate bounds and containment queries must use the same geometry.
        # Retain the complete cut section before splitting it into candidate
        # islands; the split meshes then contribute bounds only.
        build_master_base_pin_target(search_patron)
        worker_target_built = True
        candidate_meshes = search_patron.split_isolated_meshes()

        pin_pairs = _search_patron_base_pin_pairs(
            candidate_meshes,
            pin_patron,
            tolerance,
            pin_height,
        )
        return pin_pairs
    finally:
        for mesh in candidate_meshes:
            mesh.remove()
        if worker_target_built:
            try:
                clear_master_base_pin_target()
            except Exception:
                logger.warning(
                    "Could not release the master-base pin worker target",
                    exc_info=True,
                )
        pin_patron.remove()


def build_patron_base_pins(
    patron: Object,
    tolerance: float = DEFAULT_MASTER_BASE_PIN_TOLERANCE,
    pin_height: float = DEFAULT_MASTER_BASE_PIN_HEIGHT,
) -> list[tuple[Object, Object]]:
    pin_pairs = _build_patron_base_pins_with_clean_height(
        patron,
        tolerance,
        pin_height,
        MASTER_BASE_PIN_PRIMARY_CLEAN_HEIGHT,
    )
    if pin_pairs:
        return pin_pairs

    logger.debug(
        "No master-base pin location found after cleaning the patron bottom at "
        "%.3f; retrying from the original patron with clean height %.3f",
        MASTER_BASE_PIN_PRIMARY_CLEAN_HEIGHT,
        MASTER_BASE_PIN_FALLBACK_CLEAN_HEIGHT,
    )
    return _build_patron_base_pins_with_clean_height(
        patron,
        tolerance,
        pin_height,
        MASTER_BASE_PIN_FALLBACK_CLEAN_HEIGHT,
    )


MASTER_BASE_PIN_PREVIEW_KEY = "moldboxer_master_base_pin_preview"
MASTER_BASE_PINS_PREPARED_KEY = "moldboxer_master_base_pins_prepared"


def clear_prepared_master_base_pins() -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.get(MASTER_BASE_PIN_PREVIEW_KEY):
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.pop(MASTER_BASE_PINS_PREPARED_KEY, None)


def prepare_master_base_pins(context) -> None:
    """Build editable key/cutter pairs without applying either to the mold."""
    clear_prepared_master_base_pins()
    scene = context.scene
    if is_direct_mold_type(getattr(scene, "mold_type_preview", "")):
        return
    if not (
        getattr(scene, "mold_advanced_mode", False)
        and not scene.wing_join_patron
        and scene.master_base_pin
    ):
        return
    pairs = build_patron_base_pins(
        get_patron_for_base_pin_operations(),
        scene.master_base_pin_tolerance,
        scene.master_base_pin_height,
    )
    for male, female in pairs:
        male.object[MASTER_BASE_PIN_PREVIEW_KEY] = "male"
        female.object[MASTER_BASE_PIN_PREVIEW_KEY] = "female"
        assign_pin_keys_material(male.object)
        # Object-mode moves, rotations and scales must keep the socket aligned.
        world_matrix = female.object.matrix_world.copy()
        female.object.parent = male.object
        female.object.matrix_parent_inverse = male.object.matrix_world.inverted()
        female.object.matrix_world = world_matrix
        female.object.display_type = "WIRE"
        female.object.hide_select = True
        female.object.hide_render = True
    scene[MASTER_BASE_PINS_PREPARED_KEY] = True


def _take_prepared_master_base_pins():
    scene = bpy.context.scene
    if not scene.get(MASTER_BASE_PINS_PREPARED_KEY):
        return None
    pairs = []
    for female in list(scene.objects):
        if female.get(MASTER_BASE_PIN_PREVIEW_KEY) != "female":
            continue
        male = female.parent
        if male is None or male.get(MASTER_BASE_PIN_PREVIEW_KEY) != "male":
            continue
        # Apply copies so a failed confirmation leaves the editable pair intact.
        copies = []
        for obj in (male, female):
            duplicate = Object(obj).duplicate(name_adder="_apply")
            world_matrix = obj.matrix_world.copy()
            duplicate.object.parent = None
            duplicate.object.matrix_world = world_matrix
            duplicate.object.hide_select = False
            duplicate.object.hide_render = False
            duplicate.object.pop(MASTER_BASE_PIN_PREVIEW_KEY, None)
            copies.append(duplicate)
        pairs.append(tuple(copies))
    return pairs


def _join_pin_objects(objects: list[Object], name: str) -> Object:
    if not objects:
        raise ValueError("No pin objects to join")

    joined = objects[0]
    joined.name = name
    for obj in objects[1:]:
        joined.join(obj)
    joined.name = name
    return joined


def _is_base_barrier_male_name(name: str) -> bool:
    name = name.lower()
    prefix = "base_barrier_male"
    return name == prefix or (
        name.startswith(prefix) and name[len(prefix)] in "._-"
    )


def _is_base_pin_male_name(name: str) -> bool:
    name = name.lower()
    return name == "base_pin_male" or name.startswith("base_pin_male.")


def _add_base_male_locking_geometry(base: Object) -> None:
    locking_objects = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (_is_base_barrier_male_name(obj.name) or _is_base_pin_male_name(obj.name))
    ]
    locking_objects.sort(key=lambda locking_obj: locking_obj.name)
    scene = bpy.context.scene
    for locking_obj in locking_objects:
        if _is_base_barrier_male_name(locking_obj.name):
            _remesh_imported_barrier(
                locking_obj.object,
                box_thickness=scene.box_thickness,
                base_thickness=scene.base_thickness,
                base_type=getattr(scene, "base_type", "classic"),
                wing_width=scene.wing_width,
                clamp_width=scene.clamp_width,
                clamp_depth=scene.clamp_depth,
            )
        logger.debug("Adding base male locking geometry %s to base", locking_obj.name)
        base.add_with_material_transfer(locking_obj)
        if base.has_empty_boolean:
            raise Exception("Boolean modifier without target failed")
        locking_obj.remove()


def retry_after_sharp_box_remesh(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GenerationStoppedError:
            raise
        except Exception as exc:
            failed_bl_obj = get_exception_blender_object(exc)
            remesh_target = (
                Object(failed_bl_obj)
                if failed_bl_obj is not None
                else Object(bpy.data.objects.get("box"))
            )
            logger.debug(
                "Could not perform operation; applying sharp remesh to %s and "
                "retrying generation",
                remesh_target.name,
            )
            remesh_target.select()
            remesh_target.apply_modifier(build_sharp_modifier(8))
            try:
                from ..i18n import t
            except (ImportError, KeyError):
                def t(text, **kwargs):
                    return text.format(**kwargs) if kwargs else text

            show_popup(
                t("Bad box mesh: sharp remesh applied. Check the box detail level.")
            )
            return func(*args, **kwargs)

    return wrapper


@retry_after_heal
def pin_patron(
    base: Object,
    patron: Object,
    tolerance: float = DEFAULT_MASTER_BASE_PIN_TOLERANCE,
    pin_height: float = DEFAULT_MASTER_BASE_PIN_HEIGHT,
    pin_target: Object | None = None,
):
    start_time = time.perf_counter()
    pin_pairs = _take_prepared_master_base_pins()
    if pin_pairs is None:
        pin_pairs = build_patron_base_pins(patron, tolerance, pin_height)
    if not pin_pairs:
        clear_prepared_master_base_pins()
        logger.debug(
            "No valid master-base pin position found after fallback; "
            "skipping pin placement"
        )
        return

    male_pins = [male_pin for male_pin, _female_pin in pin_pairs]
    female_pins = [female_pin for _male_pin, female_pin in pin_pairs]
    joined_male_pins = None
    joined_female_pins = None

    try:
        join_start = time.perf_counter()
        joined_female_pins = _join_pin_objects(female_pins, "base_pin_females")
        joined_male_pins = _join_pin_objects(male_pins, "base_pin_males")
        logger.debug(
            "Master-base pin objects joined in %.3fs (%s pin pair%s)",
            time.perf_counter() - join_start,
            len(pin_pairs),
            "" if len(pin_pairs) == 1 else "s",
        )

        subtract_start = time.perf_counter()
        target = pin_target or patron
        target.apply_boolean_modifier(
            diff_mod,
            target=joined_female_pins,
            retry_remesh=build_voxel_modifier(
                get_master_voxel_size(bpy.context.scene.master_quality, target)
            ),
            retry_remesh_on="self",
        )
        logger.debug(
            "Master-base joined female pins subtracted in %.3fs",
            time.perf_counter() - subtract_start,
        )
        if target.has_empty_boolean:
            raise Exception("Boolean modifier without target failed")

        join_start = time.perf_counter()
        assign_pin_keys_material(joined_male_pins.object)
        joined_male_pins.object.pop(MASTER_BASE_PIN_PREVIEW_KEY, None)
        base.join(joined_male_pins)
        joined_male_pins = None
        clear_prepared_master_base_pins()
        logger.debug(
            "Master-base male pins joined in %.3fs",
            time.perf_counter() - join_start,
        )
    finally:
        if joined_female_pins is not None:
            joined_female_pins.remove()
        if joined_male_pins is not None:
            joined_male_pins.remove()
        logger.debug(
            "Master-base pin keys built and applied in %.3fs (%s pin pair%s)",
            time.perf_counter() - start_time,
            len(pin_pairs),
            "" if len(pin_pairs) == 1 else "s",
        )


@retry_after_sharp_box_remesh
def add_basing_to_system(
    volume: float,
    join_patron: bool = True,
    master_base_pin: bool = True,
    wing_width: float = WING_WIDTH,
    master_base_pin_tolerance: float = DEFAULT_MASTER_BASE_PIN_TOLERANCE,
    master_base_pin_height: float = DEFAULT_MASTER_BASE_PIN_HEIGHT,
    silicone_density: float = DEFAULT_SILICONE_DENSITY,
    base_thickness: float = 5.5,
    base_type: str = "classic",
    pre_join_base_callback=None,
    weight_text: str | None = None,
):
    total_start_time = time.perf_counter()
    box = Object(bpy.data.objects.get("box"))
    wing = Object(bpy.data.objects.get("wing"))
    master = get_master_for_base_operations()
    patron = (
        get_patron_for_base_pin_operations()
        if not join_patron and master_base_pin
        else master
    )
    base = _get_base_for_basing()

    phase_start = time.perf_counter()
    _add_base_male_locking_geometry(base)
    base_locking_elapsed = time.perf_counter() - phase_start

    if pre_join_base_callback is not None:
        phase_start = time.perf_counter()
        pre_join_base_callback(base, patron)
        logger.debug(
            "Pre-join base callback completed in %.3fs",
            time.perf_counter() - phase_start,
        )

    phase_start = time.perf_counter()
    base_height = base.height
    box_wall_thickness = float(getattr(bpy.context.scene, "box_thickness", base_thickness))
    is_optimized_base = base_type == "optimized"

    # Alignment mark
    wing_min_x_co = wing.get_limit_face_co(axis=0, max_co=False)
    alignment_cube = Object(create_cube_primitive(3), "alignment_cube")
    alignment_cube.scale_to(6, axis=0)
    alignment_cube.scale_to(wing.height * 2 + base_height * 2 + 1, axis=2)
    alignment_inset = box_wall_thickness - 1 if is_optimized_base else 5
    alignment_cube.translate_whole(
        mathutils.Vector(
            (
                wing.max_x - alignment_inset - alignment_cube.min_x,
                wing_min_x_co.y - alignment_cube.min_y,
                base.min_z - 0.2 - alignment_cube.min_z,
            )
        )
    )

    wing -= alignment_cube
    base -= alignment_cube
    alignment_cube.remove()
    alignment_elapsed = time.perf_counter() - phase_start

    pin_or_join_start = time.perf_counter()
    if not join_patron:
        if master_base_pin:
            pin_patron(
                base,
                patron,
                master_base_pin_tolerance,
                master_base_pin_height,
                pin_target=master,
            )
    else:
        _join_master_to_base(base, master)
    clear_prepared_master_base_pins()
    pin_or_join_elapsed = time.perf_counter() - pin_or_join_start

    text_start = time.perf_counter()
    _remove_weight_text_casting_cutter()
    if not is_lite_tier():
        weight_text_object = bpy.data.objects.get("Text1")
        if weight_text_object is not None and weight_text_object.type == "MESH":
            vol_text = Object(weight_text_object)
            vol_text.apply_modifier(build_sharp_modifier(8))
        else:
            vol_text = request_weight_text_mesh(
                weight_text
                if weight_text is not None
                else f"{calculate_silicone_weight(volume, silicone_density):.0f} g"
            )
        weight_text_min_z, weight_text_max_z = _weight_text_z_bounds(wing)
        vol_text.scale_to(weight_text_max_z - weight_text_min_z, axis=2)
        vol_text.rotate_whole(mathutils.Matrix.Rotation(math.radians(270), 4, "Z"))
        weight_text_min_x, weight_text_center_y = _add_weight_text_extension(
            wing,
            vol_text,
            wing_min_x_co.y,
            before_union_callback=(
                _create_weight_text_casting_cutter
                if getattr(bpy.context.scene, "pro_casting_box", False)
                else None
            ),
        )

        vol_text.translate_whole(
            mathutils.Vector(
                (
                    weight_text_min_x - vol_text.min_x,
                    weight_text_center_y - vol_text.min_y - vol_text.depth / 2,
                    weight_text_min_z - vol_text.min_z,
                )
            )
        )
        if getattr(bpy.context.scene, "pro_inner_cavity", False):
            vol_text.object["_moldboxer_weight_text_min_x"] = weight_text_min_x
            vol_text.object["_moldboxer_weight_text_center_y"] = weight_text_center_y
            vol_text.object["_moldboxer_weight_text_min_z"] = weight_text_min_z
            vol_text.object["_moldboxer_weight_text_height"] = vol_text.height
            vol_text.object.hide_set(True)
            vol_text.object.hide_viewport = True
            vol_text.object.hide_render = True
        else:
            subtract_weight_text_with_validation(wing, vol_text)
            vol_text.remove()
    text_elapsed = time.perf_counter() - text_start

    merge_start = time.perf_counter()
    mirror_pending_casting_addition(wing, material_transfer=True)
    box.add_with_material_transfer(wing)
    merge_elapsed = time.perf_counter() - merge_start
    logger.debug(
        "Basing system completed in %.3fs: base_locking=%.3fs, "
        "alignment=%.3fs, pin_or_join=%.3fs, text=%.3fs, merge_wing=%.3fs",
        time.perf_counter() - total_start_time,
        base_locking_elapsed,
        alignment_elapsed,
        pin_or_join_elapsed,
        text_elapsed,
        merge_elapsed,
    )
    wing.remove()
