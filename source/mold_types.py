import json
from typing import NamedTuple



SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS = 8.0
SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION = 1.0
SLIP_CASTING_DEFAULT_MOLD_THICKNESS = 30.0
SLIP_CASTING_DEFAULT_PLASTER_DENSITY = 1.65
SLIP_CASTING_DEFAULT_PLASTER_LOCKING_TOLERANCE = 0.35
SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER = 15.0
# Dynamic translated EnumProperty callbacks require an integer default.
# Index 0 is the CENTERED option in plaster_locking_pin_type_items().
SLIP_CASTING_DEFAULT_PLASTER_LOCKING_PIN_TYPE = 0
SLIP_CASTING_DEFAULT_BASE_PIN_TYPE = "pin"
SLIP_CASTING_DEFAULT_CLIP_TOLERANCE = 0.35
SLIP_CASTING_SETTINGS_DEFAULTS = {
    "clip_tolerance": SLIP_CASTING_DEFAULT_CLIP_TOLERANCE,
    "direct_split_x": 0,
    "direct_split_y": 2,
    "direct_split_z": 0,
    "box_gap": SLIP_CASTING_DEFAULT_MOLD_THICKNESS,
    "split_base_pin_diameter": SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER,
    "plaster_locking_tolerance": SLIP_CASTING_DEFAULT_PLASTER_LOCKING_TOLERANCE,
    "plaster_locking_pin_type": "CENTERED",
    "base_pin_type": SLIP_CASTING_DEFAULT_BASE_PIN_TYPE,
    "funneler_offset": SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION,
    "pro_casting_box_different_thickness": True,
    "casting_box_thickness": SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS,
}
SLIP_CASTING_UNDERCUTS_CLEARED_KEY = (
    "_moldboxer_slip_casting_undercuts_cleared"
)
SLIP_CASTING_LEGACY_TYPE = "SLIP_CASTING"
SLIP_CASTING_VASE_TYPE = "SLIP_CASTING_VASE"
SLIP_CASTING_TYPE_IDS = frozenset(
    {
        SLIP_CASTING_LEGACY_TYPE,
        SLIP_CASTING_VASE_TYPE,
    }
)


class MoldAdvancedAction(NamedTuple):
    operator: str
    label: str
    icon: str


class MoldTypeDefinition(NamedTuple):
    identifier: str
    label: str
    description: str
    preview_name: str
    preview_filename: str
    picker_filename: str
    generate_operator: str
    advanced_actions: tuple
    pro_two_part_silicone: bool
    pro_inner_cavity: bool
    direct_mold_opening: str
    requires_pro: bool


MOLD_TYPES = (
    MoldTypeDefinition(
        identifier="ADAPTED_BOX",
        label="Silicone · Adapted Box",
        description=(
            "Creates an optimized silicone mold system that minimizes "
            "silicone waste and provides superior demolding ease."
        ),
        preview_name="adapted_box",
        preview_filename="adapted_box.png",
        picker_filename="adapted_box.png",
        generate_operator="silicone.auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_box",
                label="Build Box",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=False,
    ),
    MoldTypeDefinition(
        identifier=SLIP_CASTING_VASE_TYPE,
        label="Slip Cast",
        description=(
            "Creates a slip-casting vase mold with a prepared base and "
            "detected internal cores."
        ),
        preview_name="slip_casting_vase",
        preview_filename="slip_cast_plaster.png",
        picker_filename="slip_cast_plaster_pro.png",
        generate_operator="silicone.slip_casting_auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.clear_slip_casting_undercuts",
                label="Clear Undercuts",
                icon="TRACKING_CLEAR_BACKWARDS",
            ),
            MoldAdvancedAction(
                operator="silicone.build_slip_casting_box",
                label="Build Box",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_slip_casting",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
    # The legacy identifier follows the Vase workflow but stays out of the picker.
    MoldTypeDefinition(
        identifier=SLIP_CASTING_LEGACY_TYPE,
        label="Slip Cast",
        description=(
            "Creates a slip-casting vase mold with a prepared base and "
            "detected internal cores."
        ),
        preview_name="slip_casting_legacy",
        preview_filename="slip_cast_plaster.png",
        picker_filename="slip_cast_plaster_pro.png",
        generate_operator="silicone.slip_casting_auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.clear_slip_casting_undercuts",
                label="Clear Undercuts",
                icon="TRACKING_CLEAR_BACKWARDS",
            ),
            MoldAdvancedAction(
                operator="silicone.build_slip_casting_box",
                label="Build Box",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_slip_casting",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="TRAY_MOLD",
        label="Silicone · Tray",
        description=(
            "An open tray for simple, flat-style models, grids, "
            "and similar shapes."
        ),
        preview_name="tray_mold",
        preview_filename="tray.png",
        picker_filename="tray.png",
        generate_operator="silicone.flat_auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_tray",
                label="Build Tray",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_tray",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=False,
    ),
    MoldTypeDefinition(
        identifier="TWO_PART_SILICONE",
        label="Silicone · Two-Part Mold (Classic)",
        description="A two-part mold system for fully enclosed models.",
        preview_name="two_part_silicone",
        preview_filename="two_parts_v2.png",
        picker_filename="two_parts_v2_pro.png",
        generate_operator="silicone.auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_box",
                label="Build Box",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=True,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="INNER_CAVITY",
        label="Silicone · Inner Core",
        description=(
            "Adds an internal core to the adapted mold system for hollow "
            "models such as pots, greatly reducing silicone usage."
        ),
        preview_name="inner_cavity",
        preview_filename="inner_core.png",
        picker_filename="inner_core_pro.png",
        generate_operator="silicone.auto_box",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_box",
                label="Build Box",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=True,
        direct_mold_opening="",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="DIRECT_MOLD_OPEN_BASE",
        label="Printed Mold · Open Base",
        description="A directly printed mold with an open casting base.",
        preview_name="direct_open_base",
        preview_filename="direct_dummy.png",
        picker_filename="direct_open_base.png",
        generate_operator="silicone.automatic_mold",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_direct_mold",
                label="Build",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_direct_mold",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="base_open",
        requires_pro=False,
    ),
    MoldTypeDefinition(
        identifier="DIRECT_MOLD_TOP_FUNNEL",
        label="Printed Mold · Top Funnel",
        description="A directly printed mold cast through funnels at the top.",
        preview_name="direct_top_funnel",
        preview_filename="direct_dummy.png",
        picker_filename="direct_top_funnel.png",
        generate_operator="silicone.automatic_mold",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_direct_mold",
                label="Build",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_direct_mold",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="top_funnel",
        requires_pro=False,
    ),
    MoldTypeDefinition(
        identifier="DIRECT_MOLD_SKIN",
        label="Printed Mold · Skin",
        description="A directly printed skin mold with an open casting base.",
        preview_name="direct_skin",
        preview_filename="direct_skin.png",
        picker_filename="direct_skin_pro.png",
        generate_operator="silicone.automatic_mold",
        advanced_actions=(
            MoldAdvancedAction(
                operator="silicone.build_direct_mold",
                label="Build",
                icon="MOD_LINEART",
            ),
            MoldAdvancedAction(
                operator="silicone.confirm_direct_mold",
                label="Confirm",
                icon="CHECKMARK",
            ),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="base_open",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="FIXTURE",
        label="Fixture",
        description=(
            "Creates a fitted fixture around the model with a selectable "
            "outer shape."
        ),
        preview_name="fixture",
        preview_filename="adapted_box.png",
        picker_filename="fixture_gold_v2_pro.png",
        generate_operator="silicone.generate_fixture",
        advanced_actions=(),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="PROTECTIVE_SHELL",
        label="Protective Shell",
        description=(
            "Creates a fitted, split protective shell around the model with "
            "server-generated clamps."
        ),
        preview_name="protective_shell",
        preview_filename="adapted_box.png",
        picker_filename="protective_shell_pro.png",
        generate_operator="silicone.generate_protective_shell",
        advanced_actions=(),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
    MoldTypeDefinition(
        identifier="SILICONE_MULTIPART",
        label="Silicone · Multi-parts",
        description="Creates a multi-part silicone mold with split bases and reusable mold boxes.",
        preview_name="silicone_multipart",
        preview_filename="two_parts_v2.png",
        picker_filename="silicone_multipart_pro.png",
        generate_operator="silicone.slip_casting_auto_box",
        advanced_actions=(
            MoldAdvancedAction("silicone.build_slip_casting_box", "Build Box", "MOD_LINEART"),
            MoldAdvancedAction("silicone.confirm_slip_casting", "Confirm", "CHECKMARK"),
        ),
        pro_two_part_silicone=False,
        pro_inner_cavity=False,
        direct_mold_opening="",
        requires_pro=True,
    ),
)

HIDDEN_MOLD_TYPE_OPTION_IDS = frozenset({SLIP_CASTING_LEGACY_TYPE})
# Reorder the selector only: saved Blender enum indices follow MOLD_TYPES.
_SELECTOR_SWAP = {
    "TWO_PART_SILICONE": "SILICONE_MULTIPART",
    "SILICONE_MULTIPART": "TWO_PART_SILICONE",
}
MOLD_TYPE_OPTIONS = tuple(
    next(option for option in MOLD_TYPES
         if option.identifier == _SELECTOR_SWAP.get(mold_type.identifier, mold_type.identifier))
    for mold_type in MOLD_TYPES
    if mold_type.identifier not in HIDDEN_MOLD_TYPE_OPTION_IDS
)
DEFAULT_MOLD_TYPE = MOLD_TYPES[0].identifier
DEFAULT_CLAMP_DEPTH = 7.0
INNER_CAVITY_DEFAULT_CLAMP_DEPTH = 10.0
MOLD_TYPES_BY_ID = {mold_type.identifier: mold_type for mold_type in MOLD_TYPES}
MOLD_TYPE_ENUM_ITEMS = tuple(
    (
        mold_type.identifier,
        mold_type.label,
        mold_type.description,
    )
    for mold_type in MOLD_TYPES
)


def get_mold_type(identifier):
    if identifier in {SLIP_CASTING_LEGACY_TYPE, "SLIP_CASTING_FIGURE"}:
        identifier = SLIP_CASTING_VASE_TYPE
    return MOLD_TYPES_BY_ID.get(identifier, MOLD_TYPES_BY_ID[DEFAULT_MOLD_TYPE])


def is_slip_casting_type(identifier) -> bool:
    return get_mold_type(identifier).identifier in SLIP_CASTING_TYPE_IDS


def is_silicone_multipart_type(identifier) -> bool:
    return identifier == "SILICONE_MULTIPART"


def slip_casting_funnels_on_top(scene) -> bool:
    """Rounded and internal adapted funnels finish above the master."""
    return is_slip_casting_type(getattr(scene, "mold_type_preview", "")) and (
        getattr(scene, "slip_casting_funnel_type", "ADAPTED") == "ROUNDED"
        or (getattr(scene, "slip_casting_funnel_type", "ADAPTED") == "ADAPTED"
            and getattr(scene, "slip_casting_adapted_variant", "EXTERNAL") == "INTERNAL")
    )


def silicone_multipart_bottom_extension(scene) -> float:
    """Space below a floating master in multipart and top-funnel no-foot molds.

    OPEN_BASE is the historical saved identifier for enclosed multipart geometry.
    Companion Direct Open Base molds retain their own unextended opening.
    """
    if getattr(scene, "get", lambda *_: False)("_moldboxer_companion_open_base", False):
        return 0.0
    identifier = getattr(scene, "mold_type_preview", "")
    enclosed_multipart = (
        is_silicone_multipart_type(identifier)
        and getattr(scene, "silicone_multipart_opening", "ENCLOSED") == "OPEN_BASE"
    )
    top_funnels_without_foot = (
        is_slip_casting_type(identifier)
        and slip_casting_funnels_on_top(scene)
        and not getattr(scene, "slip_casting_generate_base", True)
    )
    if enclosed_multipart or top_funnels_without_foot:
        return max(float(scene.box_gap), 0.0)
    return 0.0


def is_multipart_type(identifier) -> bool:
    """Generators sharing the slip-casting split-base and mold-box workflow."""
    return is_slip_casting_type(identifier) or is_silicone_multipart_type(identifier)


def is_slip_casting_vase_type(identifier) -> bool:
    return get_mold_type(identifier).identifier in {
        SLIP_CASTING_LEGACY_TYPE,
        SLIP_CASTING_VASE_TYPE,
    }



def default_clamp_depth(identifier) -> float:
    if get_mold_type(identifier).identifier in {
        "INNER_CAVITY",
        "DIRECT_MOLD_SKIN",
    }:
        return INNER_CAVITY_DEFAULT_CLAMP_DEPTH
    return DEFAULT_CLAMP_DEPTH


def _slip_casting_split_plane_signature(split_plane_specs) -> str:
    normalized_specs = []
    for plane_spec in split_plane_specs:
        point, normal = (
            (plane_spec["point"], plane_spec["normal"])
            if isinstance(plane_spec, dict)
            else (plane_spec[0], plane_spec[1])
        )
        normalized_specs.append(
            [
                [float(value) for value in point],
                [float(value) for value in normal],
            ]
        )
    return "mid_horizontal_intersection_v2:" + json.dumps(normalized_specs, separators=(",", ":"))


def mark_slip_casting_undercuts_cleared(scene, split_plane_specs) -> bool:
    objects = getattr(scene, "objects", None)
    if objects is None:
        return False
    target = objects.get("master") or objects.get("patron")
    if target is None:
        return False
    target[SLIP_CASTING_UNDERCUTS_CLEARED_KEY] = (
        _slip_casting_split_plane_signature(split_plane_specs)
    )
    return True


def slip_casting_undercuts_cleared(scene, split_plane_specs) -> bool:
    objects = getattr(scene, "objects", None)
    if objects is None:
        return False
    target = objects.get("master") or objects.get("patron")
    if target is None:
        return False
    stored_signature = getattr(target, "get", lambda *_args: None)(
        SLIP_CASTING_UNDERCUTS_CLEARED_KEY,
        None,
    )
    return stored_signature == _slip_casting_split_plane_signature(
        split_plane_specs
    )


def is_direct_mold_type(identifier) -> bool:
    return (
        get_mold_type(identifier).generate_operator
        == "silicone.automatic_mold"
    )


def mold_type_uses_reference_guides(identifier) -> bool:
    mold_type = get_mold_type(identifier).identifier
    return (
        mold_type not in {"TRAY_MOLD", "FIXTURE"}
        and mold_type != "PROTECTIVE_SHELL"
        and not is_multipart_type(mold_type)
    )


def resolve_direct_mold_opening(identifier, fallback="base_open"):
    opening = get_mold_type(identifier).direct_mold_opening
    return opening or fallback
