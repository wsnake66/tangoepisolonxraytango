TWO_PART_SILICONE_BOX_SPLITS = {
    "direct_split_x": 0,
    "direct_split_y": 1,
    "direct_split_z": 0,
}
TWO_PART_CASTING_BOX_TYPE = "STANDARD"
TWO_PART_SPLIT_PLANE_SPECS = (
    ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
)


def mold_type_uses_split_planes(scene) -> bool:
    """Return whether the selected mold type supports editable split planes."""
    mold_type = str(getattr(scene, "mold_type_preview", ""))
    if mold_type == "TRAY_MOLD":
        return False
    if mold_type != "DIRECT_MOLD_SKIN":
        return True
    objects = getattr(scene, "objects", None)
    core = objects.get("skin_core") if objects is not None else None
    return bool(
        core is not None
        and getattr(core, "type", None) == "MESH"
        and bool(getattr(core, "get", lambda *_: False)("moldboxer_skin_core"))
    )


def is_fixed_two_part_split_plane(scene, axis: str, index: int) -> bool:
    """Return whether this is the single centered plane required by two-part molds."""
    # The UI's Y split count creates an X-normal plane internally.
    return bool(
        getattr(scene, "pro_two_part_silicone", False)
        and axis == "x"
        and index == 1
    )


def set_split_plane_transform_lock(obj, locked: bool) -> None:
    locked = bool(locked)
    transform_lock = (locked, locked, locked)
    obj.hide_select = locked
    obj.lock_location = transform_lock
    obj.lock_rotation = transform_lock
    obj.lock_scale = transform_lock


def force_two_part_silicone_box_splits(scene) -> bool:
    if not getattr(scene, "pro_two_part_silicone", False):
        return False

    changed = False
    for prop_name, value in TWO_PART_SILICONE_BOX_SPLITS.items():
        if getattr(scene, prop_name, None) == value:
            continue
        setattr(scene, prop_name, value)
        changed = True
    return changed


def force_two_part_casting_box_standard(scene) -> bool:
    if not getattr(scene, "pro_two_part_silicone", False):
        return False
    if getattr(scene, "pro_casting_box_type", None) == TWO_PART_CASTING_BOX_TYPE:
        return False
    scene.pro_casting_box_type = TWO_PART_CASTING_BOX_TYPE
    return True


def get_effective_casting_box_type(scene) -> str:
    if getattr(scene, "pro_two_part_silicone", False):
        return TWO_PART_CASTING_BOX_TYPE
    return str(getattr(scene, "pro_casting_box_type", "OPTIMIZED"))


def get_effective_box_parts(scene) -> int:
    if getattr(scene, "pro_two_part_silicone", False):
        return 2
    n_splits_xy = min(max(int(getattr(scene, "n_splits_xy", 1)), 0), 2)
    return n_splits_xy * 2


def resolve_splitter_plane_specs(
    scene,
    plane_specs: list[list[list[float]]],
) -> list[list[list[float]]]:
    """Resolve two-part defaults without replacing an explicit organic split."""
    plane_specs = list(plane_specs or [])
    organic_specs = [
        spec
        for spec in plane_specs
        if isinstance(spec, dict) and spec.get("type") == "organic"
    ]
    if organic_specs and getattr(scene, "pro_two_part_silicone", False):
        # The locked centered plane remains visible as the two-part UI guide,
        # but a drawn organic split replaces it in the actual workflow.
        return organic_specs
    if getattr(scene, "pro_two_part_silicone", False):
        return [
            [list(point), list(normal)]
            for point, normal in TWO_PART_SPLIT_PLANE_SPECS
        ]
    return plane_specs


def has_xy_splits(scene) -> bool:
    return get_effective_box_parts(scene) > 1
