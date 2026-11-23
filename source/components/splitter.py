import mathutils  # type: ignore
import bpy  # type: ignore
import logging
import time
from dataclasses import dataclass

from ..background_worker import BackgroundTaskSequence
from ..object import *
from ..bl_utils import BMeshObj, show_popup
from .server import _remesh_imported_barrier
from .clamp_reinforcement import add_vertical_reinforcements_to_clamps
from .direct_mold import apply_direct_split_barrier_grid
from .direct_split_execution import (
    begin_split_object_by_direct_plane_specs,
    split_object_by_direct_plane_specs,
)
from .geometry_adapter import (
    plan_silicone_barrier_routes,
)
from ._q7x import (
    PENDING_CASTING_BOX_NAME,
    mirror_pending_casting_addition,
    pending_casting_boxes,
)

logger = logging.getLogger(__name__)

BASE_FEMALE_BARRIER_CUTTER_NAME = "base_barrier_female_clean_base_cutter"


@dataclass(frozen=True)
class _SiliconeBarrierSystem:
    """Barrier operands associated with one axis-aligned silicone-mold cut."""

    axis: str
    coordinate: float
    male_barriers: list[Object]
    female_barriers: list[Object]


def _get_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None
    return Object(obj)


def _remove_base_female_barrier_cutter_reference() -> None:
    cutter_name = BASE_FEMALE_BARRIER_CUTTER_NAME.lower()
    cutters = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (
            obj.name.lower() == cutter_name
            or obj.name.lower().startswith(f"{cutter_name}.")
        )
    ]
    for cutter in cutters:
        if cutter.object.name in bpy.data.objects:
            cutter.remove()


def _set_exact_name(obj: Object, name: str):
    raw_obj = obj.object
    existing = bpy.data.objects.get(name)
    if existing is not None and existing != raw_obj:
        backup_name = f"{name}_old"
        suffix = 1
        while backup_name in bpy.data.objects:
            suffix += 1
            backup_name = f"{name}_old{suffix}"
        existing.name = backup_name

    obj.name = name
    if bpy.data.objects.get(name) != raw_obj:
        raise RuntimeError(f"Could not rename {raw_obj.name} to {name}")


def _mesh_objects_containing(name_part: str) -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and name_part in obj.name.lower()
    ]


def _is_clamp_pin_lock_name(name: str) -> bool:
    return name.lower().startswith("clamp_pin_")


def _clamp_objects() -> list[Object]:
    return [
        clamp
        for clamp in _mesh_objects_containing("clamp")
        if not _is_clamp_pin_lock_name(clamp.name)
    ]


def _support_pilar_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in list(bpy.data.objects)
        if obj.type == "MESH" and obj.name.lower().startswith("support_pilar")
    ]


def _translate_support_pilar_bottom_to_z(
    pilar: Object,
    target_min_z: float,
    tolerance: float = 1e-4,
) -> bool:
    """Extend a support pilar downward by moving only its bottom vertices."""
    with BMeshObj(pilar, repair_winding=True) as bm:
        if not bm.verts:
            return False

        matrix_world = pilar.matrix_world
        world_coords = [(vertex, matrix_world @ vertex.co) for vertex in bm.verts]
        current_min_z = min(world_co.z for _vertex, world_co in world_coords)
        current_max_z = max(world_co.z for _vertex, world_co in world_coords)
        dynamic_tolerance = max(
            tolerance,
            (current_max_z - current_min_z) * 5e-5,
        )
        if target_min_z >= current_min_z - dynamic_tolerance:
            return False

        inverse_matrix_world = matrix_world.inverted()
        bottom_vertices = [
            (vertex, world_co)
            for vertex, world_co in world_coords
            if abs(world_co.z - current_min_z) <= dynamic_tolerance
        ]
        for vertex, world_co in bottom_vertices:
            translated_world_co = world_co.copy()
            translated_world_co.z = target_min_z
            vertex.co = inverse_matrix_world @ translated_world_co

    logger.info(
        "Extended casting support pilar %s bottom from z=%.4f to z=%.4f",
        pilar.name,
        current_min_z,
        target_min_z,
    )
    return True


def _z_clamp_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and obj.name.lower().startswith("clamp_optimized_z_")
    ]


def _screw_objects(axis: str) -> list[Object]:
    prefix = f"screw_{axis.lower()}_"
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.lower().startswith(prefix)
    ]


def _clamp_for_axis(axis: str) -> Object | None:
    optimized_clamp = _get_object(f"clamp_optimized_{axis.lower()}")
    if optimized_clamp is not None:
        return optimized_clamp

    legacy_clamp_name = "clamp_l" if axis.lower() == "x" else "clamp_r"
    return _get_object(legacy_clamp_name)


def _name_tokens(name: str) -> set[str]:
    normalized = name.lower()
    for separator in ".- ":
        normalized = normalized.replace(separator, "_")
    return {token for token in normalized.split("_") if token}


def _object_has_axis(obj: Object, axis: str) -> bool:
    return axis.lower() in _name_tokens(obj.name)


def _is_clamp_lock_object(obj: Object, kind: str) -> bool:
    normalized_name = obj.name.lower()
    if normalized_name.startswith("base_barrier_") or normalized_name.startswith(
        "base_pin_"
    ):
        return False
    name_tokens = _name_tokens(normalized_name)
    return kind.lower() in name_tokens and (
        "barrier" in name_tokens or _is_clamp_pin_lock_name(normalized_name)
    )


def _clamp_lock_objects(
    kind: str,
    axis: str | None = None,
    *,
    include_unqualified: bool = False,
) -> list[Object]:
    axis_names = {"x", "y", "z"}
    clamp_locks = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        clamp_lock = Object(obj)
        if _is_clamp_lock_object(clamp_lock, kind):
            clamp_locks.append(clamp_lock)
    if axis is None:
        return [
            clamp_lock
            for clamp_lock in clamp_locks
            if not _object_has_axis(clamp_lock, "z")
        ]

    return [
        clamp_lock
        for clamp_lock in clamp_locks
        if _object_has_axis(clamp_lock, axis)
        or (
            include_unqualified and _name_tokens(clamp_lock.name).isdisjoint(axis_names)
        )
    ]


def _remesh_barrier_from_scene(barrier: Object, *, barrier_diameter: float | None = None) -> None:
    scene = bpy.context.scene
    _remesh_imported_barrier(
        barrier.object,
        box_thickness=scene.box_thickness,
        base_thickness=scene.base_thickness,
        base_type=getattr(scene, "base_type", "classic"),
        wing_width=scene.wing_width,
        clamp_width=scene.clamp_width,
        clamp_depth=scene.clamp_depth,
        barrier_diameter=barrier_diameter,
    )


def _split_box(
    box: Object, cut_plane_normal: mathutils.Vector, point: mathutils.Vector
):
    try:
        return box.split_optimized(
            cut_plane_normal,
            point,
            preserve_isolated_meshes=True,
        )
    except Exception:
        logger.debug("Could not split box, applying sharp remesh and trying again")
        box.select()
        box.apply_modifier(build_sharp_modifier(8))
        try:
            from ..i18n import t
        except (ImportError, KeyError):
            def t(text, **kwargs):
                return text.format(**kwargs) if kwargs else text

        show_popup(t("Bad box mesh: sharp remesh applied. Check the box detail level."))
        return box.split_optimized(
            cut_plane_normal,
            point,
            preserve_isolated_meshes=True,
        )


def _mesh_size_key(part: Object) -> tuple[float, int, int]:
    data = part.object.data
    return (
        abs(float(part.volume)),
        len(data.polygons),
        len(data.vertices),
    )


def _closed_mesh_signed_volume(part: Object) -> float | None:
    """Return signed volume after a lightweight closed-surface check."""
    if not part.is_manifold():
        return None
    mesh = bmesh.new()
    try:
        mesh.from_mesh(part.object.data)
        signed_volume = float(mesh.calc_volume(signed=True))
    finally:
        mesh.free()
    transform_determinant = float(part.object.matrix_world.to_3x3().determinant())
    if abs(transform_determinant) <= 1e-12:
        return None
    orientation_sign = -1.0 if transform_determinant < 0.0 else 1.0
    return signed_volume * orientation_sign


def _is_inward_facing_closed_mesh(part: Object) -> bool:
    signed_volume = _closed_mesh_signed_volume(part)
    return signed_volume is not None and signed_volume < -1e-9


def _pre_split_island_bounds(part: Object) -> str:
    """Return compact world-space bounds for pre-split cleanup diagnostics."""
    try:
        center = part.center_coords
        return (
            f"center=({center.x:.3f}, {center.y:.3f}, {center.z:.3f}) "
            f"bounds=(x:{part.min_x:.3f}..{part.max_x:.3f}, "
            f"y:{part.min_y:.3f}..{part.max_y:.3f}, "
            f"z:{part.min_z:.3f}..{part.max_z:.3f})"
        )
    except Exception:
        return "bounds=unavailable"


def _remove_pre_split_isolated_meshes(box: Object) -> Object:
    """Fast-path connected boxes; classify and filter only disconnected ones."""
    original_name = box.name
    inspection_start = time.perf_counter()
    removed_loose_vertices, has_multiple_islands = (
        box.remove_loose_vertices_and_check_islands()
    )
    inspection_elapsed = time.perf_counter() - inspection_start

    if not has_multiple_islands:
        logger.info(
            "Pre-split box cleanup for %r kept its single connected island: "
            "removed_loose_vertices=%d connectivity=%.3fs",
            original_name,
            removed_loose_vertices,
            inspection_elapsed,
        )
        return box

    isolated_meshes = box.split_isolated_meshes()
    logger.info(
        "Pre-split box cleanup for %r found %d loose island%s after "
        "connectivity=%.3fs removed_loose_vertices=%d",
        original_name,
        len(isolated_meshes),
        "" if len(isolated_meshes) == 1 else "s",
        inspection_elapsed,
        removed_loose_vertices,
    )

    island_details = []
    for index, part in enumerate(isolated_meshes, start=1):
        signed_volume = _closed_mesh_signed_volume(part)
        inward_facing = signed_volume is not None and signed_volume < -1e-9
        size_key = _mesh_size_key(part)
        if signed_volume is None:
            classification = (
                "eligible open/non-manifold/degenerate "
                "(signed volume unavailable)"
            )
            signed_volume_text = "unavailable"
        elif inward_facing:
            classification = "filtered inward-facing closed"
            signed_volume_text = f"{signed_volume:.6f}"
        else:
            classification = "eligible outward-facing closed"
            signed_volume_text = f"{signed_volume:.6f}"

        island_details.append((part, inward_facing, size_key, classification))
        logger.info(
            "Pre-split island %d/%d name=%r classification=%s "
            "signed_mesh_volume=%s rank_abs_volume=%.6f polygons=%d "
            "vertices=%d %s",
            index,
            len(isolated_meshes),
            part.name,
            classification,
            signed_volume_text,
            size_key[0],
            size_key[1],
            size_key[2],
            _pre_split_island_bounds(part),
        )

    inward_facing = [
        part for part, is_inward, _size_key, _classification in island_details
        if is_inward
    ]
    inward_facing_ids = {id(part.object) for part in inward_facing}
    eligible_meshes = [
        part for part in isolated_meshes if id(part.object) not in inward_facing_ids
    ]
    if not eligible_meshes:
        logger.warning(
            "All %d pre-split box islands have negative signed volume; "
            "falling back to the largest original island",
            len(isolated_meshes),
        )
        eligible_meshes = isolated_meshes

    largest = max(eligible_meshes, key=_mesh_size_key)
    logger.info(
        "Pre-split box cleanup for %r selected %r as the largest of %d "
        "eligible island%s",
        original_name,
        largest.name,
        len(eligible_meshes),
        "" if len(eligible_meshes) == 1 else "s",
    )
    removed_names = []
    for part in isolated_meshes:
        if part.object == largest.object:
            continue
        removal_reason = (
            "inward-facing closed island"
            if id(part.object) in inward_facing_ids
            else "smaller eligible island"
        )
        logger.info(
            "Pre-split box cleanup removing %r from %r: %s",
            part.name,
            original_name,
            removal_reason,
        )
        removed_names.append(part.name)
        if part.object.name in bpy.data.objects:
            part.remove()

    largest.name = original_name
    logger.debug(
        "Pre-split box cleanup filtered %d inward-facing closed island%s, "
        "kept the largest eligible mesh, and removed %d isolated mesh%s: %s",
        len(inward_facing),
        "" if len(inward_facing) == 1 else "s",
        len(removed_names),
        "" if len(removed_names) == 1 else "es",
        ", ".join(removed_names),
    )
    return largest


def _split_four_parts_geometry(box_l: Object, box_r: Object) -> list[Object]:
    """Finish the four-part cut before applying any locking barriers."""
    secondary_cut_plane_normal = mathutils.Vector((0, -1, 0))
    point = mathutils.Vector((0, 0, 0))
    split_parts: list[Object] = []

    for parent in (box_l, box_r):
        parent_name = parent.name
        part_a, part_b = _split_box(parent, secondary_cut_plane_normal, point)
        low_part, high_part = sorted(
            (part_a, part_b),
            key=lambda obj: obj.center_coords.y,
        )
        _set_exact_name(low_part, f"{parent_name}_front")
        _set_exact_name(high_part, f"{parent_name}_back")
        split_parts.extend([low_part, high_part])

    return split_parts


def _z_split_name_suffix(height: float) -> str:
    return str(int(round(float(height) * 100)))


def _z_split_lock_objects(kind: str, height: float) -> list[Object]:
    base_name = f"barrier_{kind.lower()}_z_{_z_split_name_suffix(height)}"
    normalized_base_name = base_name.lower()
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (
            obj.name.lower() == normalized_base_name
            or obj.name.lower().startswith(f"{normalized_base_name}.")
        )
    ]


def _apply_z_split(
    boxes: list[Object],
    *,
    height: float,
) -> list[Object]:
    split_height = float(height)
    height_suffix = _z_split_name_suffix(split_height)
    split_pairs: list[tuple[Object, Object]] = []
    unchanged_boxes: list[Object] = []

    for box in list(boxes):
        if not (
            box.min_z + SPLIT_PLANE_CUT_HALF_THICKNESS < split_height
            < box.max_z - SPLIT_PLANE_CUT_HALF_THICKNESS
        ):
            unchanged_boxes.append(box)
            continue

        parent_name = box.name
        split_a, split_b = _split_box(
            box,
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, split_height)),
        )
        lower_box, upper_box = sorted(
            (split_a, split_b),
            key=lambda part: part.center_coords.z,
        )
        _set_exact_name(lower_box, f"{parent_name}_z_{height_suffix}_bottom")
        _set_exact_name(upper_box, f"{parent_name}_z_{height_suffix}_top")
        split_pairs.append((lower_box, upper_box))

    if not split_pairs:
        logger.warning(
            "Ignoring Z split %.3f because it is outside the mold box",
            split_height,
        )

    split_boxes = list(unchanged_boxes)
    for lower_part, upper_part in split_pairs:
        split_boxes.extend((lower_part, upper_part))
    return split_boxes


def _apply_z_splits(
    boxes: list[Object],
    splits_z: list[float],
) -> list[Object]:
    split_boxes = boxes
    for height in sorted(set(float(value) for value in splits_z)):
        split_boxes = _apply_z_split(
            split_boxes,
            height=height,
        )
    return split_boxes


def _barrier_systems(
    n_splits: int,
    splits_z: list[float],
) -> list[_SiliconeBarrierSystem]:
    if n_splits == 4:
        systems = [
            _SiliconeBarrierSystem(
                axis="x",
                coordinate=0.0,
                male_barriers=_clamp_lock_objects(
                    "male", "y", include_unqualified=True
                ),
                female_barriers=_clamp_lock_objects(
                    "female", "y", include_unqualified=True
                ),
            ),
            _SiliconeBarrierSystem(
                axis="y",
                coordinate=0.0,
                male_barriers=_clamp_lock_objects("male", "x"),
                female_barriers=_clamp_lock_objects("female", "x"),
            ),
        ]
    else:
        systems = [
            _SiliconeBarrierSystem(
                axis="x",
                coordinate=0.0,
                male_barriers=_clamp_lock_objects("male"),
                female_barriers=_clamp_lock_objects("female"),
            )
        ]

    systems.extend(
        _SiliconeBarrierSystem(
            axis="z",
            coordinate=height,
            male_barriers=_z_split_lock_objects("male", height),
            female_barriers=_z_split_lock_objects("female", height),
        )
        for height in sorted(set(float(value) for value in splits_z))
    )
    return systems


def _split_barrier_across_other_cuts(
    barrier: Object,
    own_system: _SiliconeBarrierSystem,
    systems: list[_SiliconeBarrierSystem],
) -> list[Object]:
    """Cut a male barrier into the same grid as the final mold parts."""
    _remesh_barrier_from_scene(barrier)
    pieces = [barrier.duplicate("_silicone_barrier_grid")]
    for system in systems:
        if system is own_system:
            continue
        next_pieces: list[Object] = []
        for piece in pieces:
            min_coord = getattr(piece, f"min_{system.axis}")
            max_coord = getattr(piece, f"max_{system.axis}")
            if (
                min_coord
                >= system.coordinate - SPLIT_PLANE_CUT_HALF_THICKNESS
                or max_coord
                <= system.coordinate + SPLIT_PLANE_CUT_HALF_THICKNESS
            ):
                next_pieces.append(piece)
                continue
            normal = {
                "x": mathutils.Vector((1, 0, 0)),
                "y": mathutils.Vector((0, 1, 0)),
                "z": mathutils.Vector((0, 0, 1)),
            }[system.axis]
            point = normal * system.coordinate
            split_a, split_b = _split_box(piece, normal, point)
            next_pieces.extend((split_a, split_b))
        pieces = next_pieces
    return pieces


def _apply_barriers_after_all_cuts(
    boxes: list[Object],
    systems: list[_SiliconeBarrierSystem],
    mirrored_boxes: list[Object] | None = None,
) -> None:
    """Apply silicone barriers using the same cut-first workflow as direct molds."""
    generated_male_pieces: list[Object] = []
    mirrored_boxes = list(mirrored_boxes or [])
    male_pieces: list[Object] = []
    male_system_indices: list[int] = []
    female_barriers: list[Object] = []
    female_system_indices: list[int] = []
    all_source_barriers = [
        barrier
        for system in systems
        for barrier in [*system.male_barriers, *system.female_barriers]
    ]
    try:
        for system_index, system in enumerate(systems):
            for male_barrier in system.male_barriers:
                split_pieces = _split_barrier_across_other_cuts(
                    male_barrier,
                    system,
                    systems,
                )
                generated_male_pieces.extend(split_pieces)
                male_pieces.extend(split_pieces)
                male_system_indices.extend([system_index] * len(split_pieces))

            for female_barrier in system.female_barriers:
                _remesh_barrier_from_scene(female_barrier)
                female_barriers.append(female_barrier)
                female_system_indices.append(system_index)

        routes = plan_silicone_barrier_routes(
            axes=[system.axis for system in systems],
            coordinates=[system.coordinate for system in systems],
            parts=boxes,
            mirrored_parts=mirrored_boxes,
            male_pieces=male_pieces,
            male_system_indices=male_system_indices,
            female_barriers=female_barriers,
            female_system_indices=female_system_indices,
        )

        applied_male_count = 0
        for piece_index, male_piece in enumerate(male_pieces):
            target_index = int(routes.male_targets[piece_index])
            mirrored_index = int(routes.mirrored_targets[piece_index])
            if target_index >= 0:
                boxes[target_index].add_with_material_transfer(male_piece)
                if boxes[target_index].has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
                applied_male_count += 1
            if mirrored_index >= 0:
                mirrored_boxes[mirrored_index].add_with_material_transfer(male_piece)
                if mirrored_boxes[mirrored_index].has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")
            male_piece.remove()
            generated_male_pieces.remove(male_piece)

        all_targets = [*boxes, *mirrored_boxes]
        for barrier_index, female_barrier in enumerate(female_barriers):
            start = int(routes.female_offsets[barrier_index])
            end = int(routes.female_offsets[barrier_index + 1])
            for target_index in routes.female_targets[start:end]:
                target = all_targets[int(target_index)]
                target -= female_barrier
                if target.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")

        logger.debug(
            "Applied silicone split barriers after all cuts: "
            "male_grid_pieces=%d female_whole_subtractions=%d",
            applied_male_count,
            len(routes.female_targets),
        )
    finally:
        for piece in generated_male_pieces:
            if piece.object.name in bpy.data.objects:
                piece.remove()
        seen_names: set[str] = set()
        for barrier in all_source_barriers:
            if barrier.name in seen_names:
                continue
            seen_names.add(barrier.name)
            if barrier.object.name in bpy.data.objects:
                barrier.remove()


def _is_base_pin_female_name(name: str) -> bool:
    name = name.lower()
    return name == "base_pin_female" or name.startswith("base_pin_female.")


def _base_female_locking_objects() -> list[Object]:
    locking_objects = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and (
            _is_base_pin_female_name(obj.name)
            or obj.name.lower() == "base_barrier_female"
            or obj.name.lower().startswith("base_barrier_female.")
        )
    ]
    locking_objects.sort(key=lambda locking_obj: locking_obj.name)
    return locking_objects


def _add_optimized_base_to_female_barrier(locking_obj: Object) -> None:
    scene = bpy.context.scene
    if getattr(scene, "base_type", "classic") != "optimized":
        return
    if locking_obj.name.lower() != "base_barrier_female":
        return

    cutter = _get_object(BASE_FEMALE_BARRIER_CUTTER_NAME)
    if cutter is None:
        return

    cutter.object.hide_set(False)
    cutter.object.hide_viewport = False
    selected_count = cutter.select_limit_flat_faces(max_co=False)
    if selected_count > 0:
        cutter.extrude_selected(-2 * scene.base_thickness)
        cutter.recalculate_normals()
    locking_obj += cutter
    if locking_obj.has_empty_boolean:
        raise Exception("Boolean modifier without target failed")


def _subtract_base_female_locking_geometry(
    boxes: list[Object],
    mirrored_boxes: list[Object] | None = None,
) -> None:
    locking_objects = _base_female_locking_objects()
    if not locking_objects:
        _remove_base_female_barrier_cutter_reference()
        return

    try:
        for locking_obj in locking_objects:
            if not len(locking_obj.object.data.polygons):
                logger.warning("Discarding empty base locking helper %s", locking_obj.name)
                continue
            _remesh_barrier_from_scene(locking_obj)
            _add_optimized_base_to_female_barrier(locking_obj)
            for box in [*boxes, *(mirrored_boxes or [])]:
                box -= locking_obj

                if box.has_empty_boolean:
                    raise Exception("Boolean modifier without target failed")

    finally:
        _remove_base_female_barrier_cutter_reference()
        for locking_obj in locking_objects:
            if locking_obj.object.name in bpy.data.objects:
                locking_obj.remove()


def _subtract_screw_holes_from_clamps():
    screw_objects_by_axis = {
        "x": _screw_objects("x"),
        "y": _screw_objects("y"),
    }

    try:
        for axis, screw_objects in screw_objects_by_axis.items():
            clamp = _clamp_for_axis(axis)
            if clamp is None:
                continue
            for screw in screw_objects:
                clamp -= screw
    finally:
        for screw_objects in screw_objects_by_axis.values():
            for screw in screw_objects:
                screw.remove()


def add_clamps_to_box() -> None:
    """Merge prepared clamp and support-pilar meshes into the mold box."""
    box = Object(bpy.data.objects.get("box"))
    box.select()
    optimized_wing_min_z = (
        box.min_z
        if getattr(bpy.context.scene, "base_type", "classic") == "optimized"
        else None
    )
    clamps = _clamp_objects()
    add_vertical_reinforcements_to_clamps()
    _subtract_screw_holes_from_clamps()

    for clamp in clamps:
        mirror_pending_casting_addition(clamp, material_transfer=True)
        box.add_with_material_transfer(clamp)
        if box.has_empty_boolean:
            raise Exception("Boolean modifier without target failed")
        clamp.remove()

    for pilar in _support_pilar_objects():
        if optimized_wing_min_z is not None:
            _translate_support_pilar_bottom_to_z(pilar, optimized_wing_min_z)
        mirror_pending_casting_addition(pilar, material_transfer=True)
        box.add_with_material_transfer(pilar)
        if box.has_empty_boolean:
            raise Exception("Boolean modifier without target failed")
        pilar.remove()


def split(
    n_splits: int,
    pre_split_callback=None,
    post_barrier_callback=None,
    *,
    splits_z: list[float] | None = None,
    add_clamps: bool = True,
    rename_master_base: bool = True,
    split_plane_specs: list[list[list[float]]] | None = None,
):
    """Split solidified mold box."""
    if add_clamps:
        add_clamps_to_box()
    box = Object(bpy.data.objects.get("box"))
    casting_sources = pending_casting_boxes()
    casting_box = casting_sources[0] if len(casting_sources) == 1 else None

    if pre_split_callback is not None:
        pre_split_callback()
        box = Object(bpy.data.objects.get("box"))

    box = _remove_pre_split_isolated_meshes(box)
    if casting_box is not None:
        casting_box = _remove_pre_split_isolated_meshes(casting_box)

    if split_plane_specs is not None:
        boxes = split_object_by_direct_plane_specs(
            box,
            split_plane_specs,
            preserve_isolated_meshes=True,
        )
        casting_boxes = (
            split_object_by_direct_plane_specs(
                casting_box,
                split_plane_specs,
                preserve_isolated_meshes=True,
            )
            if casting_box is not None
            else []
        )
        for index, casting_part in enumerate(casting_boxes, start=1):
            casting_part.name = f"{PENDING_CASTING_BOX_NAME}_{index:02d}"
        apply_direct_split_barrier_grid(
            boxes,
            split_plane_specs,
            mirrored_parts=casting_boxes,
        )
        _subtract_base_female_locking_geometry(boxes, casting_boxes)
        if post_barrier_callback is not None:
            post_barrier_callback()
        if rename_master_base:
            master_base = _get_object("base")
            if master_base is not None:
                master_base.name = "master_base"
        return boxes

    split_heights = list(splits_z or [])
    barrier_systems = _barrier_systems(n_splits, split_heights)

    cut_plane_normal = mathutils.Vector((-1, 0, 0))
    point = mathutils.Vector((0, 0, 0))
    box_r, box_l = _split_box(box, cut_plane_normal, point)
    if casting_box is not None:
        casting_r, casting_l = _split_box(
            casting_box,
            cut_plane_normal,
            point,
        )
        casting_l.name = f"{PENDING_CASTING_BOX_NAME}_l"
        casting_r.name = f"{PENDING_CASTING_BOX_NAME}_r"
    else:
        casting_l = casting_r = None

    if n_splits == 4:
        boxes = _split_four_parts_geometry(box_l, box_r)
        casting_boxes = (
            _split_four_parts_geometry(casting_l, casting_r)
            if casting_l is not None and casting_r is not None
            else []
        )
    else:
        _set_exact_name(box_l, "box_l")
        _set_exact_name(box_r, "box_r")
        boxes = [box_l, box_r]
        casting_boxes = (
            [casting_l, casting_r]
            if casting_l is not None and casting_r is not None
            else []
        )

    boxes = _apply_z_splits(boxes, split_heights)
    if casting_boxes:
        casting_boxes = _apply_z_splits(casting_boxes, split_heights)
    _apply_barriers_after_all_cuts(
        boxes,
        barrier_systems,
        mirrored_boxes=casting_boxes,
    )

    _subtract_base_female_locking_geometry(boxes, casting_boxes)

    if post_barrier_callback is not None:
        post_barrier_callback()

    if rename_master_base:
        master_base = Object(bpy.data.objects.get("base"))
        master_base.name = "master_base"
    return boxes


def begin_split(
    n_splits: int,
    pre_split_callback=None,
    post_barrier_callback=None,
    *,
    splits_z: list[float] | None = None,
    add_clamps: bool = True,
    rename_master_base: bool = True,
    split_plane_specs: list[list[list[float]]] | None = None,
):
    """Use asynchronous cell planning for arbitrary direct split planes."""

    if split_plane_specs is None:
        return split(
            n_splits,
            pre_split_callback,
            post_barrier_callback,
            splits_z=splits_z,
            add_clamps=add_clamps,
            rename_master_base=rename_master_base,
        )

    if add_clamps:
        add_clamps_to_box()
    box = Object(bpy.data.objects.get("box"))
    casting_sources = pending_casting_boxes()
    casting_box = casting_sources[0] if len(casting_sources) == 1 else None
    if pre_split_callback is not None:
        pre_split_callback()
        box = Object(bpy.data.objects.get("box"))
    box = _remove_pre_split_isolated_meshes(box)
    if casting_box is not None:
        casting_box = _remove_pre_split_isolated_meshes(casting_box)

    def steps():
        boxes = yield begin_split_object_by_direct_plane_specs(
            box,
            split_plane_specs,
            preserve_isolated_meshes=True,
        )
        casting_boxes = []
        if casting_box is not None:
            casting_boxes = yield begin_split_object_by_direct_plane_specs(
                casting_box,
                split_plane_specs,
                preserve_isolated_meshes=True,
            )
        for index, casting_part in enumerate(casting_boxes, start=1):
            casting_part.name = f"{PENDING_CASTING_BOX_NAME}_{index:02d}"
        apply_direct_split_barrier_grid(
            boxes,
            split_plane_specs,
            mirrored_parts=casting_boxes,
        )
        _subtract_base_female_locking_geometry(boxes, casting_boxes)
        if post_barrier_callback is not None:
            post_barrier_callback()
        if rename_master_base:
            master_base = _get_object("base")
            if master_base is not None:
                master_base.name = "master_base"
        return boxes

    return BackgroundTaskSequence(steps())
