"""Detect downward master islands and bridge them to the mold base."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import bpy  # type: ignore
import mathutils  # type: ignore

from ..materials import assign_funnels_material
from ..modifiers import build_voxel_modifier, union_mod
from ..object import Object, remove_objects_safely
from ..primitives import create_cylinder_primitive
from ..voxel_size import get_master_voxel_size


logger = logging.getLogger(__name__)

DEFAULT_MASTER_AIR_TRAP_MIN_AREA = 4.0
DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT = 0.25
DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS = 1.0
DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP = 0.25
MASTER_AIR_TRAP_PILLAR_PREFIX = "master_air_trap_pilar"
MASTER_AIR_TRAP_TARGET_KEY = "_moldboxer_air_trap_target"
_HEIGHT_EPSILON = 1.0e-6
_NORMAL_EPSILON = 1.0e-9


@dataclass(frozen=True)
class MasterAirTrapIsland:
    """A downward-facing surface basin ending above the master base."""

    projected_area: float
    tip: mathutils.Vector


def is_master_air_trap_pillar(obj) -> bool:
    try:
        target_name = str(obj.get(MASTER_AIR_TRAP_TARGET_KEY, "")).strip()
    except (AttributeError, ReferenceError, TypeError):
        target_name = ""
    return bool(getattr(obj, "type", None) == "MESH" and target_name)


def get_master_air_trap_pillars(context=None) -> list:
    """Return editable air-trap pillar objects in deterministic name order."""
    scene = getattr(context, "scene", None) if context is not None else None
    objects = getattr(scene, "objects", None) if scene is not None else None
    if objects is None:
        objects = bpy.data.objects
    return sorted(
        (obj for obj in objects if is_master_air_trap_pillar(obj)),
        key=lambda obj: obj.name.casefold(),
    )


def scene_has_master_air_trap_pillars(context=None) -> bool:
    return bool(get_master_air_trap_pillars(context))


def find_master_air_trap_islands(
    master: Object,
    base_z: float,
    *,
    min_projected_area: float = DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
    contact_tolerance: float = _HEIGHT_EPSILON,
    minima_merge_height: float = DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
) -> list[MasterAirTrapIsland]:
    """Delegate unsupported underside-basin detection to the geometry worker."""

    from .geometry_adapter import find_master_air_traps_with_worker

    result = find_master_air_traps_with_worker(
        master.object,
        base_z=float(base_z),
        min_projected_area=float(min_projected_area),
        contact_tolerance=float(contact_tolerance),
        minima_merge_height=float(minima_merge_height),
    )
    islands = [
        MasterAirTrapIsland(float(area), mathutils.Vector(tuple(tip)))
        for tip, area in zip(result.tips, result.projected_areas)
    ]
    logger.info(
        "Master air-trap worker result: object=%s accepted=%d "
        "supported_base_z=%.4f minima_merge_height=%.4f backend=%s "
        "worker=%.3fs roundtrip=%.3fs",
        master.name,
        len(islands),
        result.supported_base_z,
        minima_merge_height,
        result.backend,
        result.worker_seconds,
        result.roundtrip_seconds,
    )
    return islands


def _set_pillar_bottom_origin(cylinder: Object) -> None:
    """Rebase a finished pillar without changing its world-space vertices."""
    raw = cylinder.object
    world = raw.matrix_world.copy()
    points = [world @ vertex.co for vertex in raw.data.vertices]
    if not points:
        return
    origin = mathutils.Vector((
        sum(point.x for point in points) / len(points),
        sum(point.y for point in points) / len(points),
        min(point.z for point in points),
    ))
    local_origin = world.inverted() @ origin
    raw.data.transform(mathutils.Matrix.Translation(-local_origin))
    raw.matrix_world = world @ mathutils.Matrix.Translation(local_origin)
    raw.data.update()


def build_master_air_trap_cylinders(
    master: Object,
    base_z: float,
    *,
    radius: float = DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS,
    overlap: float = DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP,
    min_projected_area: float = DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
    minima_merge_height: float = DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
) -> list[Object]:
    """Place one vertical cylinder from every island tip to ``base_z``.

    ``overlap`` embeds each cylinder into the master at the island tip. The
    cylinder bottom is clamped to the model minimum Z and never extends below
    the model base.
    """
    if radius <= 0.0:
        raise ValueError("Master air-trap bridge radius must be positive")
    if overlap < 0.0:
        raise ValueError("Master air-trap bridge overlap must be non-negative")

    pillar_base_z = max(float(base_z), float(master.min_z))
    islands = find_master_air_trap_islands(
        master,
        pillar_base_z,
        min_projected_area=min_projected_area,
        minima_merge_height=minima_merge_height,
    )
    cylinders: list[Object] = []
    try:
        for island in islands:
            bottom_z = pillar_base_z
            top_z = island.tip.z + overlap
            height = top_z - bottom_z
            if height <= _HEIGHT_EPSILON:
                continue

            index = len(cylinders) + 1
            cylinder = Object(
                create_cylinder_primitive(radius, height),
                f"{MASTER_AIR_TRAP_PILLAR_PREFIX}_{index}",
            )
            assign_funnels_material(cylinder.object)
            cylinder.object[MASTER_AIR_TRAP_TARGET_KEY] = master.name
            target_center = mathutils.Vector(
                (island.tip.x, island.tip.y, (bottom_z + top_z) / 2.0)
            )
            cylinder.translate_whole(target_center - cylinder.center_coords)
            cylinders.append(cylinder)
            _set_pillar_bottom_origin(cylinder)
    except Exception:
        for cylinder in cylinders:
            try:
                cylinder.remove()
            except ReferenceError:
                pass
        raise

    return cylinders


def begin_build_master_air_trap_cylinders(
    master: Object,
    base_z: float,
    *,
    radius: float = DEFAULT_MASTER_AIR_TRAP_BRIDGE_RADIUS,
    overlap: float = DEFAULT_MASTER_AIR_TRAP_BRIDGE_OVERLAP,
    min_projected_area: float = DEFAULT_MASTER_AIR_TRAP_MIN_AREA,
    minima_merge_height: float = DEFAULT_MASTER_AIR_TRAP_MINIMA_MERGE_HEIGHT,
):
    """Detect islands off-thread, then build editable pillars on main."""

    if radius <= 0.0:
        raise ValueError("Master air-trap bridge radius must be positive")
    if overlap < 0.0:
        raise ValueError("Master air-trap bridge overlap must be non-negative")

    from .geometry_adapter import begin_find_master_air_traps_with_worker

    pillar_base_z = max(float(base_z), float(master.min_z))
    task = begin_find_master_air_traps_with_worker(
        master.object,
        base_z=pillar_base_z,
        min_projected_area=float(min_projected_area),
        contact_tolerance=float(_HEIGHT_EPSILON),
        minima_merge_height=float(minima_merge_height),
    )

    def finish(result):
        islands = [
            MasterAirTrapIsland(float(area), mathutils.Vector(tuple(tip)))
            for tip, area in zip(result.tips, result.projected_areas)
        ]
        cylinders: list[Object] = []
        try:
            for island in islands:
                bottom_z = pillar_base_z
                top_z = island.tip.z + overlap
                height = top_z - bottom_z
                if height <= _HEIGHT_EPSILON:
                    continue
                index = len(cylinders) + 1
                cylinder = Object(
                    create_cylinder_primitive(radius, height),
                    f"{MASTER_AIR_TRAP_PILLAR_PREFIX}_{index}",
                )
                assign_funnels_material(cylinder.object)
                cylinder.object[MASTER_AIR_TRAP_TARGET_KEY] = master.name
                target_center = mathutils.Vector(
                    (island.tip.x, island.tip.y, (bottom_z + top_z) / 2.0)
                )
                cylinder.translate_whole(target_center - cylinder.center_coords)
                cylinders.append(cylinder)
                _set_pillar_bottom_origin(cylinder)
        except Exception:
            for cylinder in cylinders:
                try:
                    cylinder.remove()
                except ReferenceError:
                    pass
            raise
        return cylinders

    return task.then(finish)


def _pillar_target(pillars: list) -> Object:
    target_names = {
        str(pillar.get(MASTER_AIR_TRAP_TARGET_KEY, "")).strip()
        for pillar in pillars
        if str(pillar.get(MASTER_AIR_TRAP_TARGET_KEY, "")).strip()
    }
    if len(target_names) != 1:
        raise ValueError("Air-trap pillars do not reference one master object")

    target_name = next(iter(target_names))
    target_raw = bpy.data.objects.get(target_name)
    if target_raw is None or target_raw.type != "MESH":
        raise ValueError(f"Air-trap pillar master '{target_name}' was not found")
    return Object(target_raw)


def _remove_raw_objects(raw_objects: list) -> None:
    remove_objects_safely(raw_objects)


def confirm_master_air_trap_pillars(context=None) -> Object:
    """Boolean-union editable air-trap pillars into their source master.

    Confirmation is transactional: the Boolean runs on a duplicate master.
    The source master and editable pillars are only changed after that
    candidate succeeds. Final non-manifold cleanup is deferred to export.
    """
    pillars = get_master_air_trap_pillars(context)
    if not pillars:
        raise ValueError("No master air-trap pillars found")

    master = _pillar_target(pillars)
    temporary_raw_objects = []
    old_master_mesh = None
    try:
        operand = None
        for pillar_raw in pillars:
            pillar_copy = Object(pillar_raw).duplicate(
                name_adder="_air_trap_confirm"
            )
            temporary_raw_objects.append(pillar_copy.object)
            if operand is None:
                operand = pillar_copy
            else:
                operand.join(pillar_copy)

        if operand is None:
            raise ValueError("No master air-trap pillars found")
        operand.name = "master_air_trap_pilars_confirm_operand"

        def build_candidate(retry_voxel_size: float | None = None) -> Object:
            candidate = master.duplicate(name_adder="_air_trap_confirm")
            temporary_raw_objects.append(candidate.object)
            if retry_voxel_size is not None:
                candidate.apply_modifier(build_voxel_modifier(retry_voxel_size))
            candidate.apply_boolean_modifier(union_mod, target=operand)
            if candidate.has_empty_boolean:
                raise RuntimeError("Air-trap pillar Boolean union did not apply")
            return candidate

        try:
            candidate = build_candidate()
        except Exception:
            scene = getattr(context, "scene", None)
            if scene is None:
                scene = bpy.context.scene
            master_quality = str(getattr(scene, "master_quality", "MID"))
            retry_voxel_size = get_master_voxel_size(master_quality, master)
            logger.warning(
                "Air-trap pillar Boolean failed; retrying after adaptive master "
                "voxel remesh: master=%s quality=%s voxel_size=%.6f",
                master.name,
                master_quality,
                retry_voxel_size,
                exc_info=True,
            )
            candidate = build_candidate(retry_voxel_size)

        old_master_mesh = master.object.data
        master.object.data = candidate.object.data
        _remove_raw_objects(list(pillars))
    finally:
        _remove_raw_objects(temporary_raw_objects)

    if (
        old_master_mesh is not None
        and old_master_mesh.users == 0
        and old_master_mesh.name in bpy.data.meshes
    ):
        bpy.data.meshes.remove(old_master_mesh)

    master.select()
    return master
