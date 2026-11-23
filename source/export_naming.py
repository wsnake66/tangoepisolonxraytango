import re


SILICONE_MOLD_PREVIEW_NAMES = frozenset(
    {
        "silicone_mold",
        "left_silicone_mold",
        "right_silicone_mold",
    }
)

_EXACT_EXPORT_NAMES = {
    "patron": "original_master",
    "master": "original_master",
    "master_base": "master_base",
    "box": "mold_box",
    "box_l": "mold_box_left",
    "box_r": "mold_box_right",
    "box_l_front": "mold_box_left_front",
    "box_l_back": "mold_box_left_back",
    "box_r_front": "mold_box_right_front",
    "box_r_back": "mold_box_right_back",
    "casting_box": "casting_box",
    "casting_box_l": "casting_box_left",
    "casting_box_r": "casting_box_right",
    "left_master": "master_left",
    "right_master": "master_right",
    "left_patron": "original_master_left",
    "right_patron": "original_master_right",
    "skin_core": "skin_mold_core",
    "skin_core_attacher": "skin_core_connector",
    "skin_core_pin": "skin_core_pin",
    "fixture": "fixture_body",
    "fixture_base": "fixture_base",
    "protective_shell": "protective_shell",
    "grip": "mold_box_handle",
    "base": "mold_base",
    "base_lockers": "base_locking_clips",
    "clamp_l": "clamp_left",
    "clamp_r": "clamp_right",
    "clamp_lockers": "clamp_locking_clips",
    "master_filler": "master_cavity_filler",
    "plaster_mold": "plaster_mold",
}


def normalized_object_name(object_name: str) -> str:
    """Return a stable lower-case name without Blender's numeric suffix."""

    return re.sub(r"\.\d{3}$", "", str(object_name).strip().casefold())


def is_silicone_mold_preview(object_name: str) -> bool:
    return normalized_object_name(object_name) in SILICONE_MOLD_PREVIEW_NAMES


def export_subfolder(object_name: str) -> str:
    """Separate reference geometry from parts intended for printing."""

    name = normalized_object_name(object_name)
    if (
        name in {"patron", "master", "plaster_mold"}
        or is_silicone_mold_preview(name)
        or name.startswith(("plaster_mold_part_", "silicone_mold_part_"))
    ):
        return "reference"
    return "print"


def _two_digit(value: str) -> str:
    return f"{int(value):02d}"


def friendly_export_name(object_name: str) -> str:
    """Translate internal Blender object names into user-facing file stems."""

    name = normalized_object_name(object_name)
    exact_name = _EXACT_EXPORT_NAMES.get(name)
    if exact_name is not None:
        return exact_name

    match = re.fullmatch(r"(clamp|base)_lockers_group_(\d+)", name)
    if match:
        return f"{match.group(1)}_locking_clips_group_{_two_digit(match.group(2))}"

    match = re.fullmatch(r"box_part_(\d+)", name)
    if match:
        return f"mold_box_part_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"casting_box_(\d+)", name)
    if match:
        return f"casting_box_part_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"protective_shell_part_(\d+)", name)
    if match:
        return f"protective_shell_part_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"plaster_mold_part_(\d+)", name)
    if match:
        return f"plaster_mold_part_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"inner_cavity_standalone_core_(\d+)(?:_(\d+))?", name)
    if match:
        core_name = f"inner_core_{_two_digit(match.group(1))}"
        if match.group(2):
            return f"{core_name}_part_{_two_digit(match.group(2))}"
        return core_name

    match = re.fullmatch(r"attacher_(\d+)(?:_(\d+))?", name)
    if match:
        if match.group(2):
            return (
                f"inner_core_{_two_digit(match.group(1))}_connector_"
                f"{_two_digit(match.group(2))}"
            )
        return f"inner_core_connector_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"core_pin_(\d+)", name)
    if match:
        return f"inner_core_pin_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"skin_core_attacher_(\d+)", name)
    if match:
        return f"skin_core_connector_{_two_digit(match.group(1))}"

    match = re.fullmatch(r"base_pin_male_(\d+)", name)
    if match:
        return f"base_alignment_pin_{_two_digit(match.group(1))}"

    if name.endswith("_base_filler"):
        return "master_base_filler"

    return name
