from ..slip_casting_base_pairs import slip_casting_uses_base
import mathutils  # type: ignore
import bpy  # type: ignore
from ..object import *
from ..materials import assign_generated_material
from .funnel_reference_line import effective_silicone_funneler_offset
from ..mold_types import is_multipart_type, is_slip_casting_vase_type, is_silicone_multipart_type
from ..mold_types import silicone_multipart_bottom_extension
from .watermark_mesh_server import request_watermark_mesh

DEFAULT_SILICONE_DENSITY = 1.12
MOLD_LABEL_TEXT_SIZE = 8.0
SILICONE_WEIGHT_TEXT_SIZE = MOLD_LABEL_TEXT_SIZE


def _silicone_mold_top_cut_z(box: Object, is_tray_mold: bool = False) -> float:
    if is_tray_mold:
        return box.max_z - 0.5
    if is_slip_casting_vase_type(
        getattr(bpy.context.scene, "mold_type_preview", "")
    ):
        if not slip_casting_uses_base(bpy.context.scene):
            # No-base funnels are merged into the box with a 1 mm extension.
            # Follow that envelope instead of truncating at the master top.
            return box.max_z - 1.0
        patron = bpy.data.objects.get("patron")
        if patron is not None and patron.type == "MESH":
            return Object(patron).max_z - 1.0
    return box.max_z - effective_silicone_funneler_offset(bpy.context.scene)


def _set_silicone_mold_visible(visible: bool) -> None:
    silicone_mold = bpy.data.objects.get("silicone_mold")
    if silicone_mold is None:
        return
    hidden = not visible
    silicone_mold.hide_set(hidden)
    silicone_mold.hide_viewport = hidden
    silicone_mold.hide_render = hidden


def hide_silicone_mold_preview() -> None:
    _set_silicone_mold_visible(False)


def reveal_silicone_mold_preview() -> None:
    _set_silicone_mold_visible(True)


def _subtract_voxelized_patron(
    silicone_mold: Object,
    patron: Object,
    voxel_size: float,
    retry_voxel_size: float | None = None,
    use_temporary_patron_cutter: bool = False,
) -> None:
    patron_copy = None
    patron_target = patron
    if use_temporary_patron_cutter:
        patron_copy = patron.duplicate(name_adder="_silicone_mold_cutter")
        patron_target = patron_copy
    try:
        retry_voxel_size = (
            retry_voxel_size if retry_voxel_size is not None else voxel_size
        )
        silicone_mold.apply_boolean_modifier(
            diff_mod,
            target=patron_target,
            retry_remesh=build_voxel_modifier(retry_voxel_size),
            retry_remesh_on="both",
            clean_before_remesh_retry=False,
        )
    finally:
        if patron_copy is not None:
            patron_copy.remove()


def build_silicone_mold_preview(
    voxel_size: float = 0.8,
    retry_voxel_size: float | None = None,
    is_tray_mold: bool = False,
) -> float:
    silicone_mold = bpy.data.objects.get("silicone_mold")
    if silicone_mold is not None:
        assign_generated_material(silicone_mold)
        hide_silicone_mold_preview()
        return Object(silicone_mold).volume
    box = Object(bpy.data.objects.get("box"))
    patron = Object(bpy.data.objects.get("patron"))
    silicone_mold = box.duplicate(name_adder="_silicone_mold")
    silicone_mold.name = "silicone_mold"
    if not silicone_multipart_bottom_extension(bpy.context.scene):
        silicone_mold.cut_plane(
            mathutils.Vector((0, 0, -1)),
            mathutils.Vector((0, 0, silicone_mold.min_z + 0.3)),
        )
    if not is_silicone_multipart_type(
        getattr(bpy.context.scene, "mold_type_preview", "")
    ):
        silicone_mold.cut_plane(
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, _silicone_mold_top_cut_z(box, is_tray_mold))),
        )
    _subtract_voxelized_patron(
        silicone_mold,
        patron,
        voxel_size,
        retry_voxel_size,
        use_temporary_patron_cutter=is_tray_mold or is_multipart_type(
            getattr(bpy.context.scene, "mold_type_preview", "")
        ),
    )

    assign_generated_material(silicone_mold.object)
    hide_silicone_mold_preview()
    return silicone_mold.volume


def calculate_silicone_weight(
    volume: float, density: float = DEFAULT_SILICONE_DENSITY
) -> float:
    return volume * max(density, 0)


def create_weight_text(
    volume: float,
    density: float = DEFAULT_SILICONE_DENSITY,
    size: float = SILICONE_WEIGHT_TEXT_SIZE,
):
    weight = calculate_silicone_weight(volume, density)
    return create_mold_text(f"{weight:.0f} g", size=size)


def create_mold_text(text: str, size: float = 5):
    return request_watermark_mesh(
        {
            "kind": "text",
            "name": "Text1",
            "text": text,
            "size": float(size),
            "depth": 2.0,
            "font_identifier": "BFONT",
            "sharp_remesh_level": 8,
        }
    )


def create_volume_text(volume):
    return create_weight_text(volume)


def sub_patron(box_voxel_size: float = 0.8, retry_voxel_size: float | None = None):
    box = Object(bpy.data.objects.get("box"))
    silicone_mold = Object(bpy.data.objects.get("silicone_mold"))
    patron = Object(bpy.data.objects.get("patron"))
    _subtract_voxelized_patron(silicone_mold, patron, box_voxel_size, retry_voxel_size)
    if not silicone_multipart_bottom_extension(bpy.context.scene):
        silicone_mold.cut_plane(
            mathutils.Vector((0, 0, -1)),
            mathutils.Vector((0, 0, silicone_mold.min_z + 0.2)),
        )
    if not is_silicone_multipart_type(
        getattr(bpy.context.scene, "mold_type_preview", "")
    ):
        silicone_mold.cut_plane(
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, _silicone_mold_top_cut_z(box))),
        )
