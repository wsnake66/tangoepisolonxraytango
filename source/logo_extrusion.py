"""Small Blender-independent watermark constants and UI policy helpers."""


ML_PER_US_FL_OZ = 29.5735295625

PENDING_LOGO_KEY = "moldboxer_pending_logo"
LOGO_PLACED_KEY = "moldboxer_logo_placed"
LOGO_TARGET_KEY = "moldboxer_logo_target"
LOGO_DEPTH_KEY = "moldboxer_logo_depth"
LOGO_RESOLUTION_SCALE_KEY = "moldboxer_logo_resolution_scale"
LOGO_VOXEL_SIZE_KEY = "moldboxer_logo_voxel_size"
LOGO_OPERATION_KEY = "moldboxer_logo_operation"
WATERMARK_OPERATION_ADD = "ADD"
WATERMARK_OPERATION_SUBTRACT = "SUBTRACT"


def normalize_watermark_operation(operation, target_name):
    del target_name
    if str(operation or "").upper() == WATERMARK_OPERATION_SUBTRACT:
        return WATERMARK_OPERATION_SUBTRACT
    return WATERMARK_OPERATION_ADD


def format_casting_volume(volume_ml, unit):
    if unit == "FL_OZ":
        return f"{float(volume_ml) / ML_PER_US_FL_OZ:.1f} fl oz"
    return f"{float(volume_ml):.0f} ml"


def choose_watermark_target_name(
    available_names,
    selected_names=(),
    active_name=None,
):
    """Choose a watermark target, honoring editable tray-grip selection."""

    available = set(available_names)
    tray_names = {"box", "grip"} & available
    if "grip" in tray_names:
        if active_name in tray_names:
            return active_name
        selected_tray_names = [
            name for name in selected_names if name in tray_names
        ]
        if len(selected_tray_names) == 1:
            return selected_tray_names[0]
        return "grip"

    if "box" in available:
        return "box"

    two_part_names = {"left_box", "right_box"} & available
    if two_part_names:
        if active_name in two_part_names:
            return active_name
        selected_two_part_names = [
            name for name in selected_names if name in two_part_names
        ]
        if len(selected_two_part_names) == 1:
            return selected_two_part_names[0]
        if "right_box" in two_part_names:
            return "right_box"
        return "left_box"

    generated_part_names = sorted(
        name
        for name in available
        if is_logo_box_target_name(name)
    )
    if generated_part_names:
        if active_name in generated_part_names:
            return active_name
        selected_part_names = [
            name for name in selected_names if name in generated_part_names
        ]
        if len(selected_part_names) == 1:
            return selected_part_names[0]
        return generated_part_names[0]

    if "patron" in available:
        return "patron"
    return None


def is_logo_box_target_name(name):
    """Return whether *name* identifies a mold box that may receive a logo."""

    normalized = str(name or "").casefold()
    return (
        normalized
        in {
            "box",
            "box_l",
            "box_r",
            "left_box",
            "right_box",
            "fixture",
            "protective_shell",
        }
        or normalized.startswith(
            (
                "box_l_",
                "box_r_",
                "box_l.",
                "box_r.",
                "box_part_",
                "protective_shell_part_",
            )
        )
    )
