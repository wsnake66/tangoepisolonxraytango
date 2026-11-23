"""Keep editable slip-casting male/female bases together when deleted."""

from uuid import uuid4

import bpy
from bpy.app.handlers import persistent

PAIR_KEY = "moldboxer_slip_casting_base_pair"
ROLE_KEY = "moldboxer_slip_casting_vase_base_role"
BUILT_KEY = "moldboxer_slip_casting_funnels_built"


def slip_casting_uses_base(scene):
    """Resolve generation mode from the preparation setting and surviving bases."""
    if not getattr(scene, "slip_casting_generate_base", True):
        return False
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if (
            obj.get(ROLE_KEY) in {"MALE", "FEMALE"}
            or obj.get("moldboxer_slip_casting_vase_base", False)
            or obj.get("moldboxer_slip_casting_female_base", False)
        ):
            return True
        # Support older preparations and Blender's duplicate-name suffixes.
        name = obj.name.split(".", 1)[0]
        if any(name == prefix or name.startswith(prefix + "_")
               for prefix in ("foot", "vase_base", "female_base")):
            return True
    return False


def pair_slip_casting_bases(males, females):
    for male, female in zip(males, females):
        pair_id = uuid4().hex
        male.object[PAIR_KEY] = pair_id
        female.object[PAIR_KEY] = pair_id


def _base_pairs(scene):
    pairs = {}
    master = scene.objects.get("patron")
    prepared = master is not None and master.get(BUILT_KEY, False)
    for obj in scene.objects:
        role = obj.get(ROLE_KEY)
        if role not in {"MALE", "FEMALE"}:
            continue
        pair_id = obj.get(PAIR_KEY)
        # Older saved preparations used matching suffixes for each base pair.
        if not pair_id and prepared:
            prefix = ("foot" if obj.name == "foot" or obj.name.startswith("foot_")
                      else "vase_base") if role == "MALE" else "female_base"
            if obj.name == prefix or obj.name.startswith(prefix + "_"):
                pair_id = "legacy:" + obj.name[len(prefix):]
        if pair_id:
            pairs.setdefault(pair_id, []).append(obj)
    return pairs


def cleanup_slip_casting_base_pairs(scene):
    from .object import remove_objects_safely

    orphaned = [
        obj
        for parts in _base_pairs(scene).values()
        if {obj.get(ROLE_KEY) for obj in parts} != {"MALE", "FEMALE"}
        for obj in parts
    ]
    remove_objects_safely(orphaned)


def _cleanup_slip_casting_base_pairs_timer():
    for scene in bpy.data.scenes:
        cleanup_slip_casting_base_pairs(scene)
    return None


@persistent
def _detect_deleted_slip_casting_base(scene, _depsgraph):
    pairs = _base_pairs(scene)
    if not any(
        {obj.get(ROLE_KEY) for obj in parts} != {"MALE", "FEMALE"}
        for parts in pairs.values()
    ):
        return
    if not bpy.app.timers.is_registered(_cleanup_slip_casting_base_pairs_timer):
        bpy.app.timers.register(_cleanup_slip_casting_base_pairs_timer, first_interval=0.0)


def register_slip_casting_base_pairs():
    unregister_slip_casting_base_pairs()
    bpy.app.handlers.depsgraph_update_post.append(_detect_deleted_slip_casting_base)


def unregister_slip_casting_base_pairs():
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == "_detect_deleted_slip_casting_base":
            handlers.remove(handler)
    if bpy.app.timers.is_registered(_cleanup_slip_casting_base_pairs_timer):
        bpy.app.timers.unregister(_cleanup_slip_casting_base_pairs_timer)
