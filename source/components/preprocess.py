import bpy  # type: ignore
import logging
import time

from ..bl_utils import deselect_all_objects
from ..modifiers import build_voxel_modifier
from ..object import Object, remove_unused_meshes
from ..patron_state import DECIMATED_PATRON_KEY
from ..voxel_size import get_master_voxel_size

logger = logging.getLogger(__name__)


def patron_part_index(name: str):
    """Return the stable import order for patron and patron_<number> names."""
    if name == "patron":
        return 0
    prefix = "patron_"
    suffix = name[len(prefix) :] if name.startswith(prefix) else ""
    if suffix.isdigit() and int(suffix) > 0:
        return int(suffix)
    return None


def join_multi_model_patrons(context=None):
    """Join a multi-model import into the canonical patron before generation."""
    context = context or bpy.context
    scene = getattr(context, "scene", None)
    parts = []
    for obj in getattr(scene, "objects", ()):
        part_index = patron_part_index(obj.name)
        if part_index is not None and obj.type == "MESH":
            parts.append((part_index, obj))
    parts.sort(key=lambda item: item[0])
    if len(parts) < 2:
        return parts[0][1] if parts else None

    deselect_all_objects()
    for _part_index, obj in parts:
        obj.hide_set(False)
        obj.hide_viewport = False
        obj.select_set(True)
    patron = parts[0][1]
    context.view_layer.objects.active = patron
    consumed_meshes = [obj.data for _, obj in parts]
    bpy.ops.object.join()
    remove_unused_meshes(consumed_meshes)
    patron = context.view_layer.objects.active
    patron.name = "patron"
    if patron.data is not None:
        patron.data.name = "patron_mesh"
    Object(patron).select()
    logger.info("Joined %d imported patron models before generation", len(parts))
    return patron


def _join_objects(objects: list[Object], name: str) -> Object:
    if not objects:
        raise ValueError("No objects to join")

    deselect_all_objects()
    for obj in objects:
        obj.object.select_set(True)
    bpy.context.view_layer.objects.active = objects[0].object
    if len(objects) > 1:
        consumed_meshes = [obj.object.data for obj in objects]
        bpy.ops.object.join()
        remove_unused_meshes(consumed_meshes)

    joined_object = Object(bpy.context.view_layer.objects.active)
    joined_object.name = name
    return joined_object


def preprocess_patron(
    center: bool = True,
    isolate: bool = False,
    check_manifold: bool = False,
    name: str = "patron",
):
    total_start = time.perf_counter()
    phase_start = total_start
    selected_object = Object(bpy.context.active_object)
    selected_object.name = name
    rename_elapsed = time.perf_counter() - phase_start
    isolate_elapsed = 0.0
    if isolate:
        phase_start = time.perf_counter()
        isolated_meshes = selected_object.split_isolated_meshes()

        if len(isolated_meshes) == 1:
            selected_object = isolated_meshes[0]
            selected_object.name = name
            selected_object.select()
        else:
            meshes_to_keep = [obj for obj in isolated_meshes if obj.volume >= 1]
            if not meshes_to_keep:
                meshes_to_keep = [max(isolated_meshes, key=lambda obj: obj.volume)]

            for obj in isolated_meshes:
                if obj not in meshes_to_keep:
                    obj.remove()

            selected_object = _join_objects(meshes_to_keep, name)
            selected_object.apply_modifier(
                build_voxel_modifier(get_master_voxel_size(bpy.context.scene.master_quality, selected_object))
            )
        isolate_elapsed = time.perf_counter() - phase_start

    phase_start = time.perf_counter()
    selected_object.select()
    select_elapsed = time.perf_counter() - phase_start
    center_elapsed = 0.0
    if center:
        phase_start = time.perf_counter()
        if name == "patron":
            bpy.ops.silicone.center_obj()
        else:
            bpy.ops.object.origin_set(type="GEOMETRY_ORIGIN", center="BOUNDS")
            selected_object.object.location.x = 0
            selected_object.object.location.y = 0
            selected_object.object.location.z -= selected_object.min_z
        center_elapsed = time.perf_counter() - phase_start
    is_manifold = None
    manifold_check_elapsed = 0.0
    heal_elapsed = 0.0
    is_decimated_patron = bool(selected_object.object.get(DECIMATED_PATRON_KEY, False))
    transforms_elapsed = 0.0
    if not is_decimated_patron:
        phase_start = time.perf_counter()
        selected_object.apply_all_transforms()
        transforms_elapsed = time.perf_counter() - phase_start
    if check_manifold and not is_decimated_patron:
        phase_start = time.perf_counter()
        is_manifold = selected_object.is_manifold()
        manifold_check_elapsed = time.perf_counter() - phase_start
        if not is_manifold:
            phase_start = time.perf_counter()
            bpy.ops.silicone.heal_patron()
            heal_elapsed = time.perf_counter() - phase_start
    logger.info(
        "Preprocess patron completed in %.3fs: rename=%.3fs, isolate=%.3fs, "
        "select=%.3fs, center=%.3fs, transforms=%.3fs, manifold_check=%.3fs, "
        "heal=%.3fs, was_manifold=%s, decimated_patron=%s, check_manifold=%s",
        time.perf_counter() - total_start,
        rename_elapsed,
        isolate_elapsed,
        select_elapsed,
        center_elapsed,
        transforms_elapsed,
        manifold_check_elapsed,
        heal_elapsed,
        is_manifold,
        is_decimated_patron,
        check_manifold,
    )
