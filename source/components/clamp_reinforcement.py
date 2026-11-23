import logging

import bpy  # type: ignore

from ..materials import assign_generated_material
from ..object import Object

logger = logging.getLogger(__name__)


def _object_name_matches(obj_name: str, name: str) -> bool:
    obj_name = obj_name.lower()
    name = name.lower()
    if obj_name == name:
        return True
    if not obj_name.startswith(name):
        return False
    return obj_name[len(name)] in "._-"


def _mesh_object(name: str) -> Object | None:
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "MESH":
        return Object(obj)

    for candidate in bpy.data.objects:
        if candidate.type == "MESH" and _object_name_matches(candidate.name, name):
            return Object(candidate)

    return None


def _clamp_for_axis(axis: str) -> Object | None:
    optimized = _mesh_object(f"clamp_optimized_{axis}")
    if optimized is not None:
        return optimized

    legacy_name = "clamp_l" if axis == "x" else "clamp_r"
    return _mesh_object(legacy_name)


def add_vertical_reinforcements_to_clamps() -> None:
    """Merge server-provided vertical reinforcement meshes into their clamps."""
    reinforcement_prefix = "barrier_vertical_reinforcement_"
    reinforcements_by_system: dict[str, list[Object]] = {}
    for obj in bpy.data.objects:
        normalized_name = obj.name.lower()
        if obj.type != "MESH" or not normalized_name.startswith(
            reinforcement_prefix
        ):
            continue
        system_name = normalized_name[len(reinforcement_prefix) :].split(".", 1)[0]
        reinforcements_by_system.setdefault(system_name, []).append(Object(obj))

    for system_name, reinforcements in reinforcements_by_system.items():
        clamp = _mesh_object(f"clamp_optimized_{system_name}")
        if clamp is None and system_name in {"x", "y"}:
            clamp = _clamp_for_axis(system_name)
        if clamp is None:
            logger.warning(
                "Found %s but no matching clamp for system %s",
                ", ".join(reinforcement.name for reinforcement in reinforcements),
                system_name,
            )
            continue

        for reinforcement in reinforcements:
            logger.debug("Adding %s to %s", reinforcement.name, clamp.name)
            assign_generated_material(reinforcement.object)
            clamp.add_with_material_transfer_and_geometry_fallback(reinforcement)
            reinforcement.remove()
