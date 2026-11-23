import logging
import re
import bpy  # type: ignore
import mathutils  # type: ignore

from .server import import_server_response, request_server, request_server_async
from .base_substracter_visibility import set_object_hidden
from ..environment import get_server_base_url
from ..materials import assign_moldbox_material
from ..modifiers import build_sharp_modifier
from ..object import Object

logger = logging.getLogger(__name__)

_BLENDER_DUPLICATE_SUFFIX_RE = re.compile(r"\.\d{3}$")
CHANNEL_ADJUSTMENT_SUPPORT = "support"
CHANNEL_ADJUSTMENT_BALANCED = "balanced"
CHANNEL_ADJUSTMENT_ADJUSTED = "adjusted"
CHANNEL_ADJUSTMENT_VALUES = {
    CHANNEL_ADJUSTMENT_SUPPORT,
    CHANNEL_ADJUSTMENT_BALANCED,
    CHANNEL_ADJUSTMENT_ADJUSTED,
}
CHANNEL_CASTING_GRIP_NAME = "channel_casting_grip"
CASTING_GRIP_SHARP_REMESH_LEVEL = 7
SUPPORT_PILAR_NAME_PREFIX = "support_pilar"


def _server_object_base_name(name: str) -> str:
    return _BLENDER_DUPLICATE_SUFFIX_RE.sub("", name)


def _is_channel_casting_grip_name(name: str) -> bool:
    return _server_object_base_name(name).lower() == CHANNEL_CASTING_GRIP_NAME


def remesh_channel_casting_grip(operand: Object) -> bool:
    """Sharp-remesh only the dedicated casting grip before its box union."""
    if not _is_channel_casting_grip_name(operand.name):
        return False
    logger.info(
        "Sharp-remeshing casting grip %s at level %d before Boolean union",
        operand.name,
        CASTING_GRIP_SHARP_REMESH_LEVEL,
    )
    operand.apply_modifier(
        build_sharp_modifier(CASTING_GRIP_SHARP_REMESH_LEVEL)
    )
    return True


def _is_support_pilar_name(name: str) -> bool:
    return _server_object_base_name(name).lower().startswith(
        SUPPORT_PILAR_NAME_PREFIX
    )


def set_support_pilars_hidden(hidden: bool) -> None:
    for obj in bpy.data.objects:
        if obj.type == "MESH" and _is_support_pilar_name(obj.name):
            set_object_hidden(obj, hidden)


def is_server_funnel_object(obj: bpy.types.Object) -> bool:
    """Return whether an imported server object is funnel/deposit geometry."""
    name = getattr(obj, "name", "")
    base_name = _server_object_base_name(name).lower()
    return base_name == "deposit" or base_name.startswith("deposit_")


def _merge_watermarks_into_channels(
    imported_objs: list[bpy.types.Object],
    channels_type: str,
    channel_adjustment: str,
) -> list[bpy.types.Object]:
    if channels_type == "classic" and channel_adjustment != CHANNEL_ADJUSTMENT_ADJUSTED:
        axis_channel_names = {
            "x": "channel_x",
            "-x": "channel_-x",
        }
    else:
        axis_channel_names = {
            "x": "channel_vertical_x",
            "-x": "channel_vertical_x",
            "y": "channel_vertical_y",
            "-y": "channel_vertical_y",
        }
    imported_by_base_name = {
        _server_object_base_name(obj.name): obj
        for obj in imported_objs
        if getattr(obj, "name", None)
    }
    watermarks = [
        obj
        for obj in imported_objs
        if _server_object_base_name(obj.name).startswith("watermark_")
    ]

    merged_watermark_ids = set()
    for watermark_obj in watermarks:
        watermark_base_name = _server_object_base_name(watermark_obj.name)
        axis = watermark_base_name.removeprefix("watermark_")
        channel_name = axis_channel_names.get(axis)
        if channel_name is None:
            logger.warning("Ignoring unexpected watermark axis: %s", axis)
            continue

        channel_obj = imported_by_base_name.get(channel_name)
        if channel_obj is None:
            logger.warning(
                "Could not find %s for imported watermark %s",
                channel_name,
                watermark_obj.name,
            )
            continue

        try:
            channel = Object(channel_obj)
            watermark = Object(watermark_obj)
            channel += watermark
            watermark.remove()
            merged_watermark_ids.add(id(watermark_obj))
        except Exception:
            logger.exception(
                "Could not merge imported watermark %s into %s",
                watermark_obj.name,
                channel_obj.name,
            )
            continue

    return [
        obj
        for obj in imported_objs
        if id(obj) not in merged_watermark_ids and obj.name in bpy.data.objects
    ]


def normalize_channel_adjustment(
    channel_adjustment: str | None,
    channels_type: str,
) -> str:
    if channel_adjustment not in CHANNEL_ADJUSTMENT_VALUES:
        channel_adjustment = CHANNEL_ADJUSTMENT_SUPPORT
    if channels_type == "classic" and channel_adjustment == CHANNEL_ADJUSTMENT_BALANCED:
        return CHANNEL_ADJUSTMENT_SUPPORT
    return channel_adjustment


def scene_channel_adjustment(scene) -> str:
    channels_type = getattr(scene, "channels_type", "classic")
    if hasattr(scene, "get") and scene.get("channel_adjustment") is None:
        legacy_adjust_to_contour = scene.get("channel_adjust_to_contour")
        if legacy_adjust_to_contour is not None:
            old_adjust_to_contour = bool(legacy_adjust_to_contour)
            if not getattr(scene, "pro_two_part_silicone", False):
                old_adjust_to_contour = not old_adjust_to_contour
            channel_adjustment = (
                CHANNEL_ADJUSTMENT_BALANCED
                if old_adjust_to_contour
                else CHANNEL_ADJUSTMENT_SUPPORT
            )
            return normalize_channel_adjustment(channel_adjustment, channels_type)
    return normalize_channel_adjustment(
        getattr(scene, "channel_adjustment", CHANNEL_ADJUSTMENT_BALANCED),
        channels_type,
    )


def scene_channels_deposit_extraction(scene) -> str:
    """Return the legacy server value; smart extraction is plane-driven."""
    return "lateral"


def request_channels_deposit(
    channel_width: float = 6,
    channel_depth: float = 10,
    channel_adjustment: str = CHANNEL_ADJUSTMENT_SUPPORT,
    larger_back: bool = True,
    add_funneler: bool = True,
    generate_funneler: bool = True,
    channels: bool = True,
    support_pilars: bool = True,
    extraction: str = "lateral",
    progressive_channels: bool = True,
    channels_contact_scale: float = 1.3,
    n_horizontal_channels: int = 0,
    channels_type: str = "classic",
    funneler_ref_height: float = 0.8,
    funneler_offset: float = 5.0,
    funnel_size_factor: float = 1,
    casting_feet: bool = False,
    casting_feet_height: float = 5,
    casting_feet_size_factor: float = 1,
    casting_grip: bool = True,
    casting_grip_width: float = 5,
    casting_grip_depth: float = 7,
    watermark_text: str | None = None,
    n_splits: int = 2,
    n_splits_z: int = 0,
    split_planes: str = "[]",
    endpoint_path: str = "/channels-deposit/",
    *,
    organic_split_planes: str = "[]",
    channel_end_shape: str = "V",
    funnel_depth: float | None = None,
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
):
    channel_adjustment = normalize_channel_adjustment(
        channel_adjustment,
        channels_type,
    )
    response = request_server(
        f"{get_server_base_url()}{endpoint_path}",
        ["box"],
        params=_channels_deposit_params(
            channel_width,
            channel_depth,
            channel_adjustment,
            larger_back,
            add_funneler,
            generate_funneler,
            channels,
            support_pilars,
            extraction,
            progressive_channels,
            channels_contact_scale,
            n_horizontal_channels,
            channels_type,
            funneler_ref_height,
            funneler_offset,
            funnel_size_factor,
            funnel_depth,
            casting_feet,
            casting_feet_height,
            casting_feet_size_factor,
            casting_grip,
            casting_grip_width,
            casting_grip_depth,
            watermark_text,
            n_splits,
            n_splits_z,
            split_planes,
            include_x_channel,
            include_y_channel,
            organic_split_planes=organic_split_planes,
            channel_end_shape=channel_end_shape,
        ),
    )
    return _import_channels_deposit_response(
        response,
        channels_type,
        channel_adjustment,
    )


def request_channels_deposit_async(
    channel_width: float = 6,
    channel_depth: float = 10,
    channel_adjustment: str = CHANNEL_ADJUSTMENT_SUPPORT,
    larger_back: bool = True,
    add_funneler: bool = True,
    generate_funneler: bool = True,
    channels: bool = True,
    support_pilars: bool = True,
    extraction: str = "lateral",
    progressive_channels: bool = True,
    channels_contact_scale: float = 1.3,
    n_horizontal_channels: int = 0,
    channels_type: str = "classic",
    funneler_ref_height: float = 0.8,
    funneler_offset: float = 5.0,
    funnel_size_factor: float = 1,
    casting_feet: bool = False,
    casting_feet_height: float = 5,
    casting_feet_size_factor: float = 1,
    casting_grip: bool = True,
    casting_grip_width: float = 5,
    casting_grip_depth: float = 7,
    watermark_text: str | None = None,
    n_splits: int = 2,
    n_splits_z: int = 0,
    split_planes: str = "[]",
    endpoint_path: str = "/channels-deposit/",
    *,
    organic_split_planes: str = "[]",
    channel_end_shape: str = "V",
    funnel_depth: float | None = None,
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
    on_complete=None,
):
    channel_adjustment = normalize_channel_adjustment(
        channel_adjustment,
        channels_type,
    )

    def complete(response):
        imported_objs = _import_channels_deposit_response(
            response,
            channels_type,
            channel_adjustment,
        )
        if on_complete is not None:
            on_complete(imported_objs)
        return imported_objs

    return request_server_async(
        f"{get_server_base_url()}{endpoint_path}",
        ["box"],
        params=_channels_deposit_params(
            channel_width,
            channel_depth,
            channel_adjustment,
            larger_back,
            add_funneler,
            generate_funneler,
            channels,
            support_pilars,
            extraction,
            progressive_channels,
            channels_contact_scale,
            n_horizontal_channels,
            channels_type,
            funneler_ref_height,
            funneler_offset,
            funnel_size_factor,
            funnel_depth,
            casting_feet,
            casting_feet_height,
            casting_feet_size_factor,
            casting_grip,
            casting_grip_width,
            casting_grip_depth,
            watermark_text,
            n_splits,
            n_splits_z,
            split_planes,
            include_x_channel,
            include_y_channel,
            organic_split_planes=organic_split_planes,
            channel_end_shape=channel_end_shape,
        ),
        on_complete=complete,
    )


def _channels_deposit_params(
    channel_width: float,
    channel_depth: float,
    channel_adjustment: str,
    larger_back: bool,
    add_funneler: bool,
    generate_funneler: bool,
    channels: bool,
    support_pilars: bool,
    extraction: str,
    progressive_channels: bool,
    channels_contact_scale: float,
    n_horizontal_channels: int,
    channels_type: str,
    funneler_ref_height: float,
    funneler_offset: float,
    funnel_size_factor: float,
    funnel_depth: float | None,
    casting_feet: bool,
    casting_feet_height: float,
    casting_feet_size_factor: float,
    casting_grip: bool,
    casting_grip_width: float,
    casting_grip_depth: float,
    watermark_text: str | None,
    n_splits: int,
    n_splits_z: int = 0,
    split_planes: str = "[]",
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
    *,
    organic_split_planes: str = "[]",
    channel_end_shape: str = "V",
) -> dict:
    params = {
        "channel_width": channel_width,
        "channel_depth": channel_depth,
        "channel_end_shape": channel_end_shape,
        "channel_adjustment": channel_adjustment,
        "larger_back": larger_back,
        "add_funneler": add_funneler,
        "generate_funneler": generate_funneler,
        "channels": channels,
        "support_pilars": support_pilars,
        "extraction": extraction,
        "progressive_channels": progressive_channels,
        "channels_contact_scale": channels_contact_scale,
        "n_horizontal_channels": n_horizontal_channels,
        "n_splits_z": n_splits_z,
        "channels_type": channels_type,
        "funneler_ref_height": funneler_ref_height,
        "funneler_offset": funneler_offset,
        "funnel_size_factor": funnel_size_factor,
        "casting_feet": casting_feet,
        "casting_feet_height": casting_feet_height,
        "casting_feet_size_factor": casting_feet_size_factor,
        "casting_grip": casting_grip,
        "casting_grip_width": casting_grip_width,
        "casting_grip_depth": casting_grip_depth,
        "watermark_text": watermark_text,
        "n_splits": n_splits,
        "split_planes": split_planes,
    }
    if organic_split_planes != "[]":
        params["organic_split_planes"] = organic_split_planes
    if funnel_depth is not None:
        params["funnel_depth"] = funnel_depth
    if include_x_channel is not None:
        params["include_x_channel"] = include_x_channel
    if include_y_channel is not None:
        params["include_y_channel"] = include_y_channel
    return params


def _import_channels_deposit_response(
    response,
    channels_type: str,
    channel_adjustment: str,
):
    logger.debug(f"Received response from server")
    imported_objs = import_server_response(response)
    imported_objs = _merge_watermarks_into_channels(
        imported_objs,
        channels_type,
        channel_adjustment,
    )
    for obj in imported_objs:
        bl_obj = Object(obj)
        bl_obj.origin_to_geometry()
        # bl_obj.recalculate_normals()
    set_support_pilars_hidden(True)
    return imported_objs


def clean_channels_bot_to_box_height():
    box = Object(bpy.data.objects.get("box"))
    clean_height = min(5, box.height - 0.1)
    if clean_height <= 0:
        return

    channels = [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and "channel" in obj.name.lower()
        and not obj.name.lower().startswith("channel_horizontal")
        and not _is_channel_casting_grip_name(obj.name)
    ]
    for channel in channels:
        channel.clean_bot(clean_height)
        channel.clean_top(clean_height)


def add_channels(casting_feet_height: float, include_casting_feet: bool = True):
    box = Object(bpy.data.objects.get("box"))
    box.select()
    box.apply_all_transforms()
    clean_top_height = min(2, casting_feet_height - 0.2)
    channels = []
    for i in range(len(bpy.data.objects)):
        obj_ = bpy.data.objects[i]
        if "channel" in obj_.name:
            channels.append(Object(obj_))
    if channels:
        for channel in channels:
            channel.apply_all_transforms()
            remesh_channel_casting_grip(channel)

        combined_channel = channels[0]
        for channel in channels[1:]:
            combined_channel += channel
            channel.remove()

        box += combined_channel
        combined_channel.remove()
        # box.clean_bot(1)
        if clean_top_height > 0:
            box.clean_top(clean_top_height)
    else:
        add_deposit()
        if include_casting_feet:
            add_casting_feet()
        # box.clean_bot(1)
        if clean_top_height > 0:
            box.clean_top(clean_top_height)
    return box


def add_deposit():
    box = Object(bpy.data.objects.get("box"))
    box.select()
    box.apply_all_transforms()
    deposits = []
    for i in range(len(bpy.data.objects)):
        obj_ = bpy.data.objects[i]
        if "deposit" in obj_.name:
            deposits.append(Object(obj_))
    for deposit_ in deposits:
        deposit_.apply_all_transforms()
        assign_moldbox_material(deposit_.object)
        box.add_without_material_transfer(deposit_)
        deposit_.remove()


def add_casting_feet():
    box = Object(bpy.data.objects.get("box"))
    box.select()
    box.apply_all_transforms()
    casting_feet: list[Object] = []
    for i in range(len(bpy.data.objects)):
        obj_ = bpy.data.objects[i]
        if "casting_feet" in obj_.name.lower():
            casting_feet.append(Object(obj_))
    for foot in casting_feet:
        # foot.apply_modifier(build_sharp_modifier(7))
        foot.apply_all_transforms()
        box += foot
        foot.remove()


def recut_channels():
    channels: list[Object] = []
    target = Object(bpy.data.objects.get("box"))
    for i in range(len(bpy.data.objects)):
        obj_ = bpy.data.objects[i]
        if "channel" in obj_.name:
            channels.append(Object(obj_))
    if channels:
        for channel in channels:
            target_coos = target.center_coords
            if channel.min_z < target.min_z - 0.01:
                logger.debug(f"Recutting channel min z{channel.name}")
                channel.cut_plane(
                    mathutils.Vector((0, 0, -1)),
                    mathutils.Vector((target_coos.x, target_coos.y, target.min_z)),
                )
            if channel.max_z > target.max_z + 0.01:
                logger.debug(f"Recutting channel {channel.name}")
                channel.cut_plane(
                    mathutils.Vector((0, 0, 1)),
                    mathutils.Vector((target_coos.x, target_coos.y, target.max_z)),
                )
