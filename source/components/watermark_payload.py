import bpy  # type: ignore

from ..object import Object
from ..operator_access import has_pro_server_access
from .box_parts import get_effective_box_parts

SKIN_CASTING_VOLUME_ML_KEY = "moldboxer_skin_casting_volume_ml"


def calculate_casting_volume() -> float:
    scene = getattr(bpy.context, "scene", None)
    skin_core = None
    if getattr(scene, "mold_type_preview", "") == "DIRECT_MOLD_SKIN":
        candidate = bpy.data.objects.get("skin_core")
        if (
            candidate is not None
            and candidate.type == "MESH"
            and bool(candidate.get("moldboxer_skin_core", False))
        ):
            skin_core = candidate
            cached_volume = skin_core.get(SKIN_CASTING_VOLUME_ML_KEY)
            if cached_volume is not None:
                return max(float(cached_volume), 0.0)

    patron = bpy.data.objects.get("patron")
    if patron is None:
        return 0

    # Object.volume is measured in local mesh space. Applying the world matrix
    # to a duplicate scales that volume by the matrix determinant, so calculate
    # the same result directly without copying and transforming the full mesh.
    world_volume_scale = abs(patron.matrix_world.to_3x3().determinant())
    casting_volume = Object(patron).volume * world_volume_scale

    if skin_core is not None:
        core_world_volume_scale = abs(
            skin_core.matrix_world.to_3x3().determinant()
        )
        casting_volume -= Object(skin_core).volume * core_world_volume_scale

    return max(casting_volume, 0.0)


def _watermark_disabled_for_scene(scene) -> bool:
    return (
        not has_pro_server_access()
        or getattr(scene, "pro_two_part_silicone", False)
        or get_effective_box_parts(scene) == 4
    )


def build_watermark_text(scene) -> str | None:
    if _watermark_disabled_for_scene(scene):
        return None

    return " ".join(
        str(getattr(scene, "pro_watermark", "")).strip().splitlines()
    ).strip()


def build_watermark_text_lines(scene) -> str | None:
    if _watermark_disabled_for_scene(scene):
        return None

    return " ".join(
        str(getattr(scene, "pro_watermark", "")).strip().splitlines()
    ).strip()
