import bpy  # type: ignore

from .components.auth import (
    get_addon_preferences,
    get_trial_exports_remaining,
    is_free_trial_status,
)
from .i18n import t
from .mold_types import (
    SLIP_CASTING_DEFAULT_BASE_PIN_TYPE,
    SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS,
    SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION,
    SLIP_CASTING_DEFAULT_MOLD_THICKNESS,
    SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER,
    is_slip_casting_type,
)

LITE_TIER = "T0"
FREE_LITE_TIER = "FL"
LITE_TIERS = {LITE_TIER, FREE_LITE_TIER}
WEBSITE_URL = "https://moldboxer.com"
UPGRADE_LICENSE_URL = "https://moldboxer.com/buy"
LITE_MASTER_QUALITY = "MID"
LITE_BOX_QUALITY = "MID"
LITE_LOCKED_BASIC_SCENE_DEFAULTS = {
    "mold_advanced_mode": False,
    "direct_skin_core_type": "MULTI_PART",
    "master_quality": LITE_MASTER_QUALITY,
    "box_gap": 4.5,
    "silicone_density": 1.12,
    "box_thickness": 3.5,
    "wing_width": 7.0,
    "base_thickness": 5.5,
    "base_type": "classic",
    "wing_join_patron": True,
    "funneler": "optimized",
    "funneler_ref_height": 80.0,
    "funneler_offset": 5.0,
    "funneler_size_factor": 1.0,
    "flat_grip": True,
    "clamp_pin_type": "barrier",
    "clamp_pin_system_type": "PIN",
    "clamp_screw_diameter": 4.0,
    "clamp_width": 5.0,
    "clamp_depth": 7.0,
    "clamp_tolerance": 0.25,
    "clip_height": 10.0,
    "clip_thickness": 4.0,
    "clip_tolerance": 0.25,
    "clip_closing_pressure": 0.25,
    "box_quality": LITE_BOX_QUALITY,
    "build_from_sphere": False,
    "clear_extraction": True,
    "master_base_pin": True,
    "master_base_pin_tolerance": 0.02,
    "master_base_pin_height": 2.5,
    "base_pin_type": "pin",
    "n_splits_xy": 1,
    "n_splits_z": 0,
    "channels": True,
    "channel_width": 6.0,
    "channel_depth": 6.0,
    "horizontal_channels_count": 0,
    "channels_type": "optimized",
    "channels_contact_scale": 1.5,
    "channel_adjustment": "adjusted",
    "channel_back_larger": True,
    "casting_feet": False,
    "casting_feet_height": 5.0,
    "casting_feet_size_factor": 1.0,
    "casting_grip": False,
    "casting_grip_width": 5.0,
    "casting_grip_depth": 7.0,
}
PRO_SCENE_DEFAULTS = {
    "pro_inner_cavity": False,
    "pro_inner_cavity_sensitivity": "3",
    "pro_inner_cavity_core_type": "SINGLE_PART",
    "pro_casting_box": False,
    "pro_casting_box_type": "OPTIMIZED",
    "pro_casting_box_different_thickness": False,
    "casting_box_thickness": 5.0,
    "optimized_casting_box_thickness": 15.0,
    "optimized_casting_box_horizontal_intersection": "TOP",
    "pro_two_part_silicone": False,
    "pro_open_base": True,
    "pro_casting_feet": True,
    "pro_key_size": 10.0,
    "pro_key_tolearnce": 0.5,
    "pro_master_filler_quality": "MID",
    "master_filler_remove_type": "ORANGE",
    "pro_master_base_offset": 0.0,
    "pro_watermark": "",
}
_ACCESS_DIALOG_LOCKS: dict[str, bool] = {}


def get_auth_tier() -> str:
    prefs = get_addon_preferences()
    if prefs is None:
        return ""
    return str(getattr(prefs, "auth_tier", "")).upper()


def is_lite_tier() -> bool:
    return False


def is_core_tier() -> bool:
    return False


def has_export_access() -> bool:
    return True


def has_pro_server_access() -> bool:
    return True


def has_pro_or_trial_server_access() -> bool:
    # Active Pro trials carry T3. A stale trial status must not enable Pro
    # tooling after the server has restored a lower tier.
    return has_pro_server_access()


def has_basic_server_access() -> bool:
    return True


def has_active_server_access() -> bool:
    return True


def show_active_membership_required(operator: bpy.types.Operator) -> None:
    operator.report({"WARNING"}, t("License required"))
    _invoke_access_dialog_once("silicone.auth_required_dialog")


def show_basic_membership_required() -> None:
    _invoke_access_dialog_once("silicone.basic_required_dialog")


def show_pro_membership_required() -> None:
    _invoke_access_dialog_once("silicone.pro_required_dialog")


def show_export_license_required() -> None:
    _invoke_access_dialog_once("silicone.export_license_required_dialog")


def _release_access_dialog_lock(dialog_idname: str):
    def _release():
        _ACCESS_DIALOG_LOCKS[dialog_idname] = False
        return None

    return _release


def _invoke_access_dialog_once(
    dialog_idname: str, cooldown_seconds: float = 0.35
) -> None:
    if _ACCESS_DIALOG_LOCKS.get(dialog_idname, False):
        return
    _ACCESS_DIALOG_LOCKS[dialog_idname] = True
    try:
        module_name, operator_name = dialog_idname.split(".", 1)
        getattr(getattr(bpy.ops, module_name), operator_name)("INVOKE_DEFAULT")
    finally:
        bpy.app.timers.register(
            _release_access_dialog_lock(dialog_idname),
            first_interval=cooldown_seconds,
        )


def apply_lite_access_defaults(scene: bpy.types.Scene | None) -> None:
    if scene is None or not is_lite_tier():
        return
    scene["_moldboxer_access_guard"] = True
    try:
        for prop_name, value in LITE_LOCKED_BASIC_SCENE_DEFAULTS.items():
            setattr(scene, prop_name, value)
        for prop_name, value in PRO_SCENE_DEFAULTS.items():
            setattr(scene, prop_name, value)
        if is_slip_casting_type(getattr(scene, "mold_type_preview", "")):
            scene.base_pin_type = SLIP_CASTING_DEFAULT_BASE_PIN_TYPE
            scene.box_gap = SLIP_CASTING_DEFAULT_MOLD_THICKNESS
            scene.split_base_pin_diameter = (
                SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER
            )
            scene.funneler_offset = SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION
            scene.pro_casting_box_different_thickness = True
            scene.casting_box_thickness = (
                SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS
            )
    finally:
        scene["_moldboxer_access_guard"] = False
