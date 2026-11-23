import bpy  # type: ignore
from .source.components import preparation_settings
from bpy.props import BoolProperty as _BoolProperty  # type: ignore
from bpy.props import EnumProperty as _EnumProperty  # type: ignore
from bpy.props import FloatProperty as _FloatProperty  # type: ignore
from bpy.props import IntProperty as _IntProperty  # type: ignore
from bpy.props import StringProperty as _StringProperty  # type: ignore

try:
    from moldboxer_silicone_native.source.operator_access import (
        LITE_LOCKED_BASIC_SCENE_DEFAULTS,
        PRO_SCENE_DEFAULTS,
        has_pro_server_access,
        has_active_server_access,
        is_lite_tier,
        show_basic_membership_required,
        show_pro_membership_required,
    )
    from moldboxer_silicone_native.source.environment import get_addon_preferences
    from moldboxer_silicone_native.source.components.box_parts import (
        force_two_part_casting_box_standard,
        force_two_part_silicone_box_splits,
    )
    from moldboxer_silicone_native.source.i18n import (
        box_quality_items,
        base_pin_type_items,
        base_type_items,
        casting_input_shape_items,
        channel_adjustment_items,
        channel_end_shape_items,
        channels_type_items,
        clamp_pin_type_items,
        clamp_pin_system_items,
        direct_mold_opening_items,
        funneler_type_items,
        filler_remove_type_items,
        filler_quality_items,
        inner_cavity_core_type_items,
        inner_cavity_sensitivity_items,
        master_quality_items,
        plaster_locking_pin_type_items,
        silicone_mix_mode_items,
        slip_casting_funnel_type_items,
        slip_casting_adapted_variant_items,
        slip_casting_internal_model_type_items,
        slip_casting_rounded_count_mode_items,
        slip_casting_rounded_detection_detail_items,
        t,
        clear_undercuts_mode_items,
        undercuts_extraction_type_items,
        undercuts_quality_items,
    )
except ImportError:
    from .source.operator_access import (
        LITE_LOCKED_BASIC_SCENE_DEFAULTS,
        PRO_SCENE_DEFAULTS,
        has_pro_server_access,
        has_active_server_access,
        is_lite_tier,
        show_basic_membership_required,
        show_pro_membership_required,
    )
    from .source.environment import get_addon_preferences
    from .source.components.box_parts import (
        force_two_part_casting_box_standard,
        force_two_part_silicone_box_splits,
    )
    from .source.i18n import (
        box_quality_items,
        base_pin_type_items,
        base_type_items,
        casting_input_shape_items,
        channel_adjustment_items,
        channel_end_shape_items,
        channels_type_items,
        clamp_pin_type_items,
        clamp_pin_system_items,
        direct_mold_opening_items,
        funneler_type_items,
        filler_remove_type_items,
        filler_quality_items,
        inner_cavity_core_type_items,
        inner_cavity_sensitivity_items,
        master_quality_items,
        plaster_locking_pin_type_items,
        silicone_mix_mode_items,
        slip_casting_funnel_type_items,
        slip_casting_adapted_variant_items,
        slip_casting_internal_model_type_items,
        slip_casting_rounded_count_mode_items,
        slip_casting_rounded_detection_detail_items,
        t,
        clear_undercuts_mode_items,
        undercuts_extraction_type_items,
        undercuts_quality_items,
    )

from .source.plaster_mix import update_plaster_mix_volume

from .source.mold_types import (
    is_silicone_multipart_type,
    DEFAULT_CLAMP_DEPTH,
    DEFAULT_MOLD_TYPE,
    MOLD_TYPE_ENUM_ITEMS,
    SLIP_CASTING_DEFAULT_BASE_PIN_TYPE,
    SLIP_CASTING_DEFAULT_CLIP_TOLERANCE,
    SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS,
    SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION,
    SLIP_CASTING_DEFAULT_MOLD_THICKNESS,
    SLIP_CASTING_DEFAULT_PLASTER_DENSITY,
    SLIP_CASTING_DEFAULT_PLASTER_LOCKING_PIN_TYPE,
    SLIP_CASTING_DEFAULT_PLASTER_LOCKING_TOLERANCE,
    SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER,
    default_clamp_depth,
    get_mold_type,
    is_direct_mold_type,
    is_slip_casting_type,
)

_ACCESS_GUARD_ACTIVE = False
DEFAULT_SILICONE_DENSITY = 1.12
_DIRECT_SPLIT_PLANE_UPDATE_ACTIVE = False
_PRE_SLIP_CASTING_MOLD_THICKNESS_KEY = (
    "_moldboxer_pre_slip_casting_mold_thickness"
)
_PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY = (
    "_moldboxer_pre_slip_casting_funnel_extension"
)
_PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY = (
    "_moldboxer_pre_slip_casting_box_different_thickness"
)
_PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY = (
    "_moldboxer_pre_slip_casting_box_thickness"
)

# Remove retired scene properties immediately when this module is reloaded over
# an older add-on version.
if hasattr(bpy.types.Scene, "clear_extraction_type"):
    del bpy.types.Scene.clear_extraction_type
if hasattr(bpy.types.Scene, "casting_volume"):
    del bpy.types.Scene.casting_volume


def _translated_property(factory, **kwargs):
    translated_kwargs = dict(kwargs)
    name = translated_kwargs.get("name")
    description = translated_kwargs.get("description")
    items = translated_kwargs.get("items")
    if isinstance(name, str):
        translated_kwargs["name"] = t(name)
    if isinstance(description, str):
        translated_kwargs["description"] = t(description)
    if isinstance(items, (list, tuple)):
        translated_items = []
        for item in items:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                translated_items.append(item)
                continue
            translated_item = list(item)
            if isinstance(translated_item[1], str):
                translated_item[1] = t(translated_item[1])
            if isinstance(translated_item[2], str):
                translated_item[2] = t(translated_item[2])
            translated_items.append(tuple(translated_item))
        translated_kwargs["items"] = type(items)(translated_items)
    return factory(**translated_kwargs)


def FloatProperty(**kwargs):  # noqa: N802
    return _translated_property(_FloatProperty, **kwargs)


def IntProperty(**kwargs):  # noqa: N802
    return _translated_property(_IntProperty, **kwargs)


def BoolProperty(**kwargs):  # noqa: N802
    return _translated_property(_BoolProperty, **kwargs)


def StringProperty(**kwargs):  # noqa: N802
    return _translated_property(_StringProperty, **kwargs)


def EnumProperty(**kwargs):  # noqa: N802
    return _translated_property(_EnumProperty, **kwargs)


def _access_guard_enabled(scene) -> bool:
    return _ACCESS_GUARD_ACTIVE or bool(scene.get("_moldboxer_access_guard", False))


def _set_scene_prop_guarded(scene, prop_name, value):
    global _ACCESS_GUARD_ACTIVE
    previous_state = _ACCESS_GUARD_ACTIVE
    _ACCESS_GUARD_ACTIVE = True
    try:
        setattr(scene, prop_name, value)
    finally:
        _ACCESS_GUARD_ACTIVE = previous_state


def _sync_slip_casting_mold_thickness(scene, mold_type_identifier):
    if is_slip_casting_type(mold_type_identifier):
        if _PRE_SLIP_CASTING_MOLD_THICKNESS_KEY in scene:
            return
        scene[_PRE_SLIP_CASTING_MOLD_THICKNESS_KEY] = float(scene.box_gap)
        _set_scene_prop_guarded(
            scene,
            "box_gap",
            scene.get(
                _PRE_SLIP_CASTING_MOLD_THICKNESS_KEY + "_saved",
                SLIP_CASTING_DEFAULT_MOLD_THICKNESS,
            ),
        )
        return

    if _PRE_SLIP_CASTING_MOLD_THICKNESS_KEY in scene:
        scene[_PRE_SLIP_CASTING_MOLD_THICKNESS_KEY + "_saved"] = float(scene.box_gap)
        previous_thickness = float(
            scene[_PRE_SLIP_CASTING_MOLD_THICKNESS_KEY]
        )
        del scene[_PRE_SLIP_CASTING_MOLD_THICKNESS_KEY]
        _set_scene_prop_guarded(scene, "box_gap", previous_thickness)


def _sync_slip_casting_funnel_extension(scene, mold_type_identifier):
    if is_slip_casting_type(mold_type_identifier):
        if _PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY in scene:
            return
        scene[_PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY] = float(
            scene.funneler_offset
        )
        _set_scene_prop_guarded(
            scene,
            "funneler_offset",
            scene.get(
                _PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY + "_saved",
                SLIP_CASTING_DEFAULT_FUNNEL_EXTENSION,
            ),
        )
        return

    if _PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY in scene:
        scene[_PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY + "_saved"] = float(scene.funneler_offset)
        previous_extension = float(
            scene[_PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY]
        )
        del scene[_PRE_SLIP_CASTING_FUNNEL_EXTENSION_KEY]
        _set_scene_prop_guarded(scene, "funneler_offset", previous_extension)


def _sync_slip_casting_casting_box_thickness(scene, mold_type_identifier):
    if is_slip_casting_type(mold_type_identifier):
        if _PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY in scene:
            return
        if _PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY not in scene:
            scene[_PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY] = bool(
                scene.pro_casting_box_different_thickness
            )
        if _PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY not in scene:
            scene[_PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY] = float(
                scene.casting_box_thickness
            )
        _set_scene_prop_guarded(
            scene,
            "pro_casting_box_different_thickness",
            scene.get(
                _PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY + "_saved",
                True,
            ),
        )
        _set_scene_prop_guarded(
            scene,
            "casting_box_thickness",
            scene.get(
                _PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY + "_saved",
                SLIP_CASTING_DEFAULT_CASTING_BOX_THICKNESS,
            ),
        )
        return

    if _PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY in scene:
        scene[_PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY + "_saved"] = (
            bool(scene.pro_casting_box_different_thickness)
        )
        previous_different_thickness = bool(
            scene[_PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY]
        )
        del scene[_PRE_SLIP_CASTING_CASTING_BOX_DIFFERENT_THICKNESS_KEY]
        _set_scene_prop_guarded(
            scene,
            "pro_casting_box_different_thickness",
            previous_different_thickness,
        )
    if _PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY in scene:
        scene[_PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY + "_saved"] = (
            float(scene.casting_box_thickness)
        )
        previous_thickness = float(
            scene[_PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY]
        )
        del scene[_PRE_SLIP_CASTING_CASTING_BOX_THICKNESS_KEY]
        _set_scene_prop_guarded(
            scene,
            "casting_box_thickness",
            previous_thickness,
        )


_PRE_SLIP_CASTING_BASE_PIN_TYPE_KEY = "_moldboxer_pre_slip_casting_base_pin_type"


def _sync_slip_casting_base_pin_type(scene, mold_type_identifier):
    key = _PRE_SLIP_CASTING_BASE_PIN_TYPE_KEY
    if is_slip_casting_type(mold_type_identifier):
        if key not in scene:
            scene[key] = scene.base_pin_type
            _set_scene_prop_guarded(
                scene, "base_pin_type",
                scene.get(key + "_saved", SLIP_CASTING_DEFAULT_BASE_PIN_TYPE),
            )
    elif key in scene:
        scene[key + "_saved"] = scene.base_pin_type
        previous = scene[key]
        del scene[key]
        _set_scene_prop_guarded(scene, "base_pin_type", previous)


def _sync_slip_casting_clip_tolerance(scene, identifier):
    key = "_moldboxer_pre_slip_casting_clip_tolerance"
    if is_slip_casting_type(identifier):
        if key not in scene:
            scene[key] = scene.clip_tolerance
            _set_scene_prop_guarded(scene, "clip_tolerance",
                scene.get(key + "_saved", SLIP_CASTING_DEFAULT_CLIP_TOLERANCE))
    elif key in scene:
        scene[key + "_saved"] = scene.clip_tolerance
        previous = scene[key]
        del scene[key]
        _set_scene_prop_guarded(scene, "clip_tolerance", previous)


def _sync_silicone_multipart_settings(scene, identifier):
    key = "_moldboxer_multipart_settings"
    defaults = {"box_gap": 4.5, "base_pin_type": "barrier",
                "slip_casting_master_base_mode": "ONE_PIECE", "channel_width": 8.0, "channel_end_shape": "CUBIC", "pro_casting_box": False}
    if is_silicone_multipart_type(identifier):
        if key not in scene:
            scene[key] = {name: getattr(scene, name) for name in defaults}
            saved = {**defaults, **dict(scene.get(key + "_saved", {}))}
            for name, value in saved.items():
                _set_scene_prop_guarded(scene, name, value)
    elif key in scene:
        scene[key + "_saved"] = {name: getattr(scene, name) for name in defaults}
        previous = dict(scene[key])
        del scene[key]
        for name, value in previous.items():
            _set_scene_prop_guarded(scene, name, value)


def sync_slip_casting_settings(scene):
    """Initialize missing slip-cast state without resetting a restarted mold."""
    mold_type = getattr(scene, "mold_type_preview", "")
    if not is_silicone_multipart_type(mold_type):
        _sync_silicone_multipart_settings(scene, mold_type)
    _sync_slip_casting_mold_thickness(scene, mold_type)
    _sync_slip_casting_funnel_extension(scene, mold_type)
    _sync_slip_casting_casting_box_thickness(scene, mold_type)
    _sync_slip_casting_base_pin_type(scene, mold_type)
    _sync_slip_casting_clip_tolerance(scene, mold_type)
    if is_silicone_multipart_type(mold_type):
        _sync_silicone_multipart_settings(scene, mold_type)
    _limit_slip_casting_split_base_pin_diameter(scene)


def _make_lite_basic_guard(prop_name):
    def _update(scene, context):
        if _access_guard_enabled(scene) or not is_lite_tier():
            return
        _set_scene_prop_guarded(
            scene,
            prop_name,
            LITE_LOCKED_BASIC_SCENE_DEFAULTS.get(prop_name),
        )
        show_basic_membership_required()

    return _update


_BOX_GAP_LITE_GUARD = _make_lite_basic_guard("box_gap")


def _limit_slip_casting_split_base_pin_diameter(scene) -> None:
    if not is_slip_casting_type(getattr(scene, "mold_type_preview", "")):
        return
    maximum_diameter = max(float(scene.box_gap) / 2.0, 0.0)
    if float(scene.split_base_pin_diameter) <= maximum_diameter:
        return
    _set_scene_prop_guarded(
        scene,
        "split_base_pin_diameter",
        maximum_diameter,
    )


def _update_box_gap(scene, context) -> None:
    # Internal resets and generator overrides must not overwrite the saved pin size.
    if _access_guard_enabled(scene):
        return
    _BOX_GAP_LITE_GUARD(scene, context)
    _limit_slip_casting_split_base_pin_diameter(scene)


def _update_split_base_pin_diameter(scene, _context) -> None:
    if _access_guard_enabled(scene):
        return
    _limit_slip_casting_split_base_pin_diameter(scene)


def _sync_funnel_reference_line(scene, prop_name):
    try:
        from moldboxer_silicone_native.source.components.funnel_reference_line import (
            update_funnel_reference_line_from_property,
        )
    except ImportError:
        from .source.components.funnel_reference_line import (
            update_funnel_reference_line_from_property,
        )
    update_funnel_reference_line_from_property(scene, prop_name)


def _update_direct_funnel_reference_height(scene, _context):
    _sync_funnel_reference_line(scene, "direct_funnel_reference_height")


def _update_funneler_ref_height(scene, context):
    _make_lite_basic_guard("funneler_ref_height")(scene, context)
    _sync_funnel_reference_line(scene, "funneler_ref_height")


def _update_skin_base_reference_height(scene, _context):
    try:
        from moldboxer_silicone_native.source.components.direct_split_planes import (
            update_skin_base_reference_height_from_property,
        )
    except ImportError:
        from .source.components.direct_split_planes import (
            update_skin_base_reference_height_from_property,
        )
    update_skin_base_reference_height_from_property(scene)


def _update_custom_face_core(scene, _context):
    try:
        from moldboxer_silicone_native.source.components.custom_face_core import (
            update_custom_face_core_from_scene,
        )
    except ImportError:
        from .source.components.custom_face_core import (
            update_custom_face_core_from_scene,
        )
    update_custom_face_core_from_scene(scene)


def _update_direct_split_planes(axis: str):
    def _update(scene, context):
        global _DIRECT_SPLIT_PLANE_UPDATE_ACTIVE
        if _DIRECT_SPLIT_PLANE_UPDATE_ACTIVE:
            return
        _DIRECT_SPLIT_PLANE_UPDATE_ACTIVE = True
        try:
            # Optimized bases need at least one editable Y box split. The UI's
            # Y split is represented by direct_split_y, even though its initial
            # plane is stored in the internal X plane group.
            if (
                axis == "x"
                and getattr(scene, "base_type", "classic") == "optimized"
                and not is_direct_mold_type(
                    getattr(scene, "mold_type_preview", "")
                )
                and int(getattr(scene, "direct_split_y", 0)) < 1
            ):
                scene.direct_split_y = 1

            try:
                from moldboxer_silicone_native.source.components.direct_split_planes import (
                    ensure_optimized_base_vertical_split_plane,
                    rebuild_all_direct_split_planes,
                    rebuild_direct_split_planes_for_axis,
                )
            except ImportError:
                from .source.components.direct_split_planes import (
                    ensure_optimized_base_vertical_split_plane,
                    rebuild_all_direct_split_planes,
                    rebuild_direct_split_planes_for_axis,
                )

            if force_two_part_silicone_box_splits(scene):
                rebuild_all_direct_split_planes()
            else:
                rebuild_direct_split_planes_for_axis(axis)
            ensure_optimized_base_vertical_split_plane(scene)
        finally:
            _DIRECT_SPLIT_PLANE_UPDATE_ACTIVE = False

    return _update


def _update_base_type(scene, context):
    _make_lite_basic_guard("base_type")(scene, context)
    if (
        _access_guard_enabled(scene)
        or getattr(scene, "base_type", "classic") != "optimized"
    ):
        return

    try:
        from moldboxer_silicone_native.source.components.direct_split_planes import (
            ensure_optimized_base_vertical_split_plane,
        )
    except ImportError:
        from .source.components.direct_split_planes import (
            ensure_optimized_base_vertical_split_plane,
        )
    ensure_optimized_base_vertical_split_plane(scene)


def _update_fixture_base_span(scene, _context):
    if not bool(getattr(scene, "fixture_base_screw_holes", False)):
        return
    required_span = max(
        float(getattr(scene, "fixture_base_screw_body_diameter", 0.0)),
        float(getattr(scene, "fixture_base_screw_head_diameter", 0.0)),
    ) + 0.25
    if float(getattr(scene, "fixture_base_span", 0.0)) < required_span:
        scene.fixture_base_span = required_span


def _make_pro_guard(prop_name):
    def _update(scene, context):
        if _access_guard_enabled(scene) or has_pro_server_access():
            return
        _set_scene_prop_guarded(scene, prop_name, PRO_SCENE_DEFAULTS.get(prop_name))
        show_pro_membership_required()

    return _update


def _update_casting_feet(scene, context):
    _make_lite_basic_guard("casting_feet")(scene, context)
    if _access_guard_enabled(scene):
        return
    if getattr(scene, "pro_two_part_silicone", False) and scene.casting_feet:
        _set_scene_prop_guarded(scene, "casting_feet", False)
        return
    if not scene.casting_feet:
        return
    _set_scene_prop_guarded(scene, "channel_adjustment", "support")
    _set_scene_prop_guarded(scene, "channel_back_larger", False)


def _update_channels_type(scene, context):
    _make_lite_basic_guard("channels_type")(scene, context)
    if _access_guard_enabled(scene):
        return
    if (
        scene.channels_type == "classic"
        and getattr(scene, "channel_adjustment", "") == "balanced"
    ):
        _set_scene_prop_guarded(scene, "channel_adjustment", "support")


def _update_pro_two_part_silicone(scene, context):
    _make_pro_guard("pro_two_part_silicone")(scene, context)
    if _access_guard_enabled(scene):
        return
    if scene.pro_two_part_silicone:
        _set_scene_prop_guarded(scene, "casting_feet", False)
        force_two_part_casting_box_standard(scene)
        force_two_part_silicone_box_splits(scene)

    try:
        from moldboxer_silicone_native.source.components.direct_split_planes import (
            rebuild_all_direct_split_planes,
        )
    except ImportError:
        from .source.components.direct_split_planes import (
            rebuild_all_direct_split_planes,
        )
    rebuild_all_direct_split_planes()


def _update_pro_casting_box_type(scene, context):
    _make_pro_guard("pro_casting_box_type")(scene, context)
    if _access_guard_enabled(scene):
        return
    force_two_part_casting_box_standard(scene)


def _get_silicone_density(scene):
    prefs = get_addon_preferences()
    if prefs is None:
        return DEFAULT_SILICONE_DENSITY
    return float(getattr(prefs, "silicone_density", DEFAULT_SILICONE_DENSITY))


def _set_silicone_density(scene, value):
    prefs = get_addon_preferences()
    if prefs is None:
        return
    prefs.silicone_density = max(float(value), 0.0)


def _get_clamp_screws(scene):
    return getattr(scene, "clamp_pin_system_type", "PIN") == "SCREW"


def _set_clamp_screws(scene, value):
    scene.clamp_pin_system_type = "SCREW" if value else "PIN"


def _get_pro_inner_cavity(scene):
    return bool(scene.get("_moldboxer_pro_inner_cavity", False))


def _set_pro_inner_cavity(scene, value):
    if _access_guard_enabled(scene):
        scene["_moldboxer_pro_inner_cavity"] = bool(value)
        return
    enabled = bool(value)
    if enabled and not has_pro_server_access():
        scene["_moldboxer_pro_inner_cavity"] = False
        show_pro_membership_required()
        return
    scene["_moldboxer_pro_inner_cavity"] = enabled


def _has_cached_pro_access() -> bool:
    return has_pro_server_access()


def _get_pro_casting_box(scene):
    if not _has_cached_pro_access():
        return False
    return bool(scene.get("_moldboxer_pro_casting_box", False))


def _set_pro_casting_box(scene, value):
    enabled = bool(value)
    if _access_guard_enabled(scene):
        scene["_moldboxer_pro_casting_box"] = enabled
        return
    if enabled and not _has_cached_pro_access():
        scene["_moldboxer_pro_casting_box"] = False
        show_pro_membership_required()
        return
    scene["_moldboxer_pro_casting_box"] = enabled


def _update_mold_type_preview(scene, _context):
    if _access_guard_enabled(scene):
        return

    mold_type = get_mold_type(scene.mold_type_preview)
    if (mold_type.requires_pro and has_active_server_access()
            and not has_pro_server_access()):
        show_pro_membership_required()
        _set_scene_prop_guarded(scene, "mold_type_preview", DEFAULT_MOLD_TYPE)
        return
    if not mold_type.advanced_actions and getattr(
        scene,
        "mold_advanced_mode",
        False,
    ):
        scene.mold_advanced_mode = False
    if scene.pro_two_part_silicone:
        scene.pro_two_part_silicone = False
    if scene.pro_inner_cavity:
        scene.pro_inner_cavity = False

    if mold_type.pro_two_part_silicone:
        if has_active_server_access():
            scene.pro_two_part_silicone = True
        else:
            _set_scene_prop_guarded(scene, "pro_two_part_silicone", True)
    elif mold_type.pro_inner_cavity:
        if has_active_server_access():
            scene.pro_inner_cavity = True
        else:
            _set_scene_prop_guarded(scene, "pro_inner_cavity", True)

    flags_were_applied = (
        bool(scene.pro_two_part_silicone)
        == mold_type.pro_two_part_silicone
        and bool(scene.pro_inner_cavity) == mold_type.pro_inner_cavity
    )
    if not flags_were_applied:
        _set_scene_prop_guarded(scene, "mold_type_preview", DEFAULT_MOLD_TYPE)
        return

    if not is_silicone_multipart_type(mold_type.identifier):
        _sync_silicone_multipart_settings(scene, mold_type.identifier)
    _sync_slip_casting_mold_thickness(scene, mold_type.identifier)
    _sync_slip_casting_funnel_extension(scene, mold_type.identifier)
    _sync_slip_casting_casting_box_thickness(scene, mold_type.identifier)
    _sync_slip_casting_base_pin_type(scene, mold_type.identifier)
    _sync_slip_casting_clip_tolerance(scene, mold_type.identifier)
    if is_silicone_multipart_type(mold_type.identifier):
        _sync_silicone_multipart_settings(scene, mold_type.identifier)
    _limit_slip_casting_split_base_pin_diameter(scene)
    _set_scene_prop_guarded(
        scene,
        "clamp_depth",
        default_clamp_depth(mold_type.identifier),
    )

    if mold_type.direct_mold_opening:
        scene.wing_join_patron = True
        scene.direct_mold_opening = mold_type.direct_mold_opening
        scene.undercuts_quality = "FAST"
    elif mold_type.identifier == "FIXTURE":
        scene.direct_split_x = 0
        scene.direct_split_y = 0
        scene.direct_split_z = 0


bpy.types.Scene.master_voxel_size = FloatProperty(
    name="Master Detail",
    description="Master voxel detail size. Lower values will make the master more detailed but it will take more time (0.05 to 1)",
    default=0.15,
    min=0.05,
    max=1,
    subtype="DISTANCE",
)

bpy.types.Scene.master_quality = EnumProperty(
    name="Master",
    description="Master heal speed/quality. Only applies if the master mesh needs to be healed",
    items=master_quality_items,
    default=1,
    update=_make_lite_basic_guard("master_quality"),
)

bpy.types.Scene.box_gap = FloatProperty(
    name="Mold Thickness",
    description="Mold Thickness",
    default=4.5,
    min=0,
    subtype="DISTANCE",
    update=_update_box_gap,
)

bpy.types.Scene.fixture_fit_tolerance = FloatProperty(
    name="Fit Tolerance",
    description="Clearance between the model and the generated fixture",
    default=0.4,
    min=0.0,
    soft_max=5.0,
    subtype="DISTANCE",
)

bpy.types.Scene.fixture_thickness = FloatProperty(
    name="Thickness",
    description="Wall thickness around the fixture clearance wrapper",
    default=3.0,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
)

bpy.types.Scene.slip_casting_box_faces = IntProperty(
    name="Vertical Faces",
    description="Number of main vertical sides of the box, before beveling",
    default=4,
    min=3,
    max=64,
)

bpy.types.Scene.slip_casting_shape_type = EnumProperty(
    name="Mold Shape",
    description="Outer shape used for the Slip Casting box",
    items=(
        ("adapted", "Adapted", "Adapt the box shape to the model"),
        ("cube", "Cube", "Build a cubic box"),
        ("cylinder", "Cylinder", "Build a cylindrical box"),
    ),
    default="adapted",
)

# Keep non-slip molds independent from saved Slip Casting shape settings.
bpy.types.Scene.mold_box_shape_type = EnumProperty(
    name="Mold Shape",
    description="Outer shape used for silicone and direct mold boxes",
    items=(
        ("adapted", "Adapted", "Adapt the box shape to the model"),
        ("cube", "Cube", "Build a cubic box"),
        ("cylinder", "Cylinder", "Build a cylindrical box"),
    ),
    default="adapted",
)

bpy.types.Scene.mold_box_faces = IntProperty(
    name="Vertical Faces",
    description="Number of main vertical sides of the box, before beveling",
    default=4,
    min=3,
    max=64,
)

bpy.types.Scene.fixture_shape_type = EnumProperty(
    name="Shape Type",
    description="Outer shape used for the generated fixture",
    items=(
        ("cube", "Cube", "Build the fixture with a cube outer shape"),
        ("cylinder", "Cylinder", "Build the fixture with a cylinder outer shape"),
        ("adapted", "Adapted", "Adapt the fixture shape to the model"),
    ),
    default="adapted",
)

bpy.types.Scene.fixture_box_quality = EnumProperty(
    name="Detail",
    description="Fixture wrapper voxel size, speed, and surface detail",
    items=box_quality_items,
    default=1,
)

bpy.types.Scene.protective_shell_fit_tolerance = FloatProperty(
    name="Fit Tolerance",
    description="Clearance between the model and the generated Protective Shell",
    default=0.4,
    min=0.0,
    soft_max=5.0,
    subtype="DISTANCE",
)

bpy.types.Scene.protective_shell_thickness = FloatProperty(
    name="Thickness",
    description="Wall thickness around the Protective Shell clearance wrapper",
    default=3.0,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
)

bpy.types.Scene.protective_shell_shape_type = EnumProperty(
    name="Shape Type",
    description="Outer shape used for the generated Protective Shell",
    items=(
        ("cube", "Cube", "Build the Protective Shell with a cube outer shape"),
        (
            "cylinder",
            "Cylinder",
            "Build the Protective Shell with a cylinder outer shape",
        ),
        ("adapted", "Adapted", "Adapt the Protective Shell shape to the model"),
    ),
    default="adapted",
)

bpy.types.Scene.protective_shell_box_quality = EnumProperty(
    name="Detail",
    description="Protective Shell wrapper voxel size, speed, and surface detail",
    items=box_quality_items,
    default=1,
)

bpy.types.Scene.fixture_base = BoolProperty(
    name="Base",
    description="Add a base below the generated fixture",
    default=True,
)

bpy.types.Scene.fixture_base_thickness = FloatProperty(
    name="Thickness",
    description="Height of the fixture base",
    default=5.0,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
)

bpy.types.Scene.fixture_base_span = FloatProperty(
    name="Span",
    description="Base extension added independently on every X and Y side",
    default=8.0,
    min=0.0,
    soft_max=30.0,
    subtype="DISTANCE",
    update=_update_fixture_base_span,
)

bpy.types.Scene.fixture_base_screw_holes = BoolProperty(
    name="Screw Holes",
    description="Add counterbored screw holes at the fixture base corners",
    default=True,
    update=_update_fixture_base_span,
)

bpy.types.Scene.fixture_base_screw_body_diameter = FloatProperty(
    name="Body Diameter",
    description="Diameter of the screw body holes before tolerance",
    default=3.0,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_update_fixture_base_span,
)

bpy.types.Scene.fixture_base_screw_head_diameter = FloatProperty(
    name="Head Diameter",
    description="Diameter of the screw head recesses before tolerance",
    default=6.0,
    min=0.1,
    soft_max=30.0,
    subtype="DISTANCE",
    update=_update_fixture_base_span,
)

bpy.types.Scene.fixture_base_screw_head_height = FloatProperty(
    name="Head Height",
    description="Depth of the screw head recesses from the top of the base",
    default=2.0,
    min=0.1,
    soft_max=10.0,
    subtype="DISTANCE",
)

bpy.types.Scene.direct_mold_thickness = FloatProperty(
    name="Thickness",
    description="Distance used to build the Direct automatic mold wrapper",
    default=3.5,
    min=0,
    soft_max=20.0,
    subtype="DISTANCE",
)

bpy.types.Scene.skin_thickness = FloatProperty(
    name="Skin Thickness",
    description=(
        "Distance from the master surface to the retained Skin mold core"
    ),
    default=4.0,
    min=1.0,
    soft_min=1.0,
    soft_max=20.0,
    subtype="DISTANCE",
)

bpy.types.Scene.skin_base_reference_height = FloatProperty(
    name="Base Reference Height",
    description="Height of the Skin mold base reference circle on the master",
    default=25.0,
    min=1.0,
    max=99.0,
    subtype="PERCENTAGE",
    update=_update_skin_base_reference_height,
)

bpy.types.Scene.direct_skin_core_generation_mode = EnumProperty(
    name="Core Generation",
    description="Choose how the editable Skin mold core is generated",
    items=(
        (
            "AUTOMATIC",
            "Automatic",
            "Generate the core automatically from an inward offset of the master",
        ),
        (
            "CUSTOM_FACE",
            "Custom Face Core",
            "Generate an adjustable proportional human head as the core",
        ),
    ),
    default="AUTOMATIC",
)

bpy.types.Scene.custom_face_head_height = FloatProperty(
    name="Crown-to-Chin",
    description="Vertical distance from the top of the crown to the bottom of the chin",
    default=230.0,
    min=40.0,
    soft_max=350.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_head_width = FloatProperty(
    name="Head Width",
    description="Maximum skull breadth above the ears, excluding the ears",
    default=155.0,
    min=30.0,
    soft_max=260.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_head_depth = FloatProperty(
    name="Head Length",
    description="Front-to-back length from the forehead to the back of the skull, excluding the nose",
    default=195.0,
    min=30.0,
    soft_max=300.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_cheek_width = FloatProperty(
    name="Cheek Width",
    description="Maximum side-to-side width across the cheekbones",
    default=135.0,
    min=40.0,
    soft_max=240.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_neck_circumference = FloatProperty(
    name="Neck Circumference",
    description="Measured neck circumference before comfort clearance and opening flare; must exceed twice Neck Width",
    default=305.0,
    min=150.0,
    soft_max=550.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_neck_width = FloatProperty(
    name="Neck Width", description="Side-to-side neck width; circumference determines front-to-back depth",
    default=100.0, min=40.0, soft_max=160.0, subtype="DISTANCE", update=_update_custom_face_core,
)
bpy.types.Scene.custom_face_neck_length = FloatProperty(
    name="Neck Length", description="Vertical distance from the front chin/neck boundary to the flat opening",
    default=50.0, min=20.0, soft_max=120.0, subtype="DISTANCE", update=_update_custom_face_core,
)
bpy.types.Scene.custom_face_neck_offset = FloatProperty(
    name="Forward / Back", description="Move the lower neck forward with positive values or backward with negative values",
    default=0.0, min=-30.0, max=30.0, subtype="DISTANCE", update=_update_custom_face_core,
)
bpy.types.Scene.custom_face_neck_flare = FloatProperty(
    name="Opening Flare", description="Additional radial widening at the lower opening, blended into the neck",
    default=5.0, min=0.0, soft_max=20.0, subtype="DISTANCE", update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_comfort_clearance = FloatProperty(
    name="Comfort Clearance",
    description="Radial clearance added around the measured head dimensions",
    default=2.0,
    min=0.0,
    soft_max=8.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_ear_clearance = FloatProperty(
    name="Ear Clearance",
    description="Extra lateral clearance around the simplified solid ears",
    default=2.0,
    min=0.0,
    soft_max=10.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_hair_allowance = FloatProperty(
    name="Hair Allowance",
    description="Extra clearance over the crown and back for hair or a liner",
    default=0.0,
    min=0.0,
    soft_max=12.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_forehead_width = FloatProperty(
    name="Forehead Width",
    description="Side-to-side width across the forehead",
    default=142.0,
    min=25.0,
    soft_max=240.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_jaw_width = FloatProperty(
    name="Jaw Width",
    description="Side-to-side width at the jaw",
    default=116.0,
    min=20.0,
    soft_max=220.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_chin_length = FloatProperty(
    name="Chin Length",
    description="Vertical length and prominence of the chin",
    default=32.0,
    min=8.0,
    soft_max=70.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_nose_length = FloatProperty(
    name="Nose Projection",
    description="Forward projection of the nose from the face",
    default=22.0,
    min=0.0,
    soft_max=55.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_nose_width = FloatProperty(
    name="Nose Width",
    description="Side-to-side width of the nose",
    default=38.0,
    min=8.0,
    soft_max=80.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.custom_face_nose_height = FloatProperty(
    name="Nose Height",
    description="Vertical height of the nose from bridge to base",
    default=52.0,
    min=12.0,
    soft_max=100.0,
    subtype="DISTANCE",
    update=_update_custom_face_core,
)

bpy.types.Scene.direct_skin_core_type = EnumProperty(
    name="Core Type",
    description=(
        "Choose whether the Direct Skin core and its attacher form one part "
        "or separate parts"
    ),
    items=inner_cavity_core_type_items,
    # Callback enum values are one-based here, so 2 selects MULTI_PART.
    default=2,
)

bpy.types.Scene.direct_mold_opening = EnumProperty(
    name="Casting Opening",
    description="Location of the casting-material opening for Direct molds",
    items=direct_mold_opening_items,
    default=0,
)

bpy.types.Scene.direct_funnel_top_diameter = FloatProperty(
    name="Funnel Top Diameter",
    description="Diameter of the top face of Direct mold funnels",
    default=10.0,
    min=0.1,
    subtype="DISTANCE",
)

bpy.types.Scene.direct_funnel_bottom_diameter = FloatProperty(
    name="Funnel Bottom Diameter",
    description="Diameter of the bottom face of Direct mold funnels",
    default=5.0,
    min=0.1,
    subtype="DISTANCE",
)

bpy.types.Scene.direct_funnel_reference_height = FloatProperty(
    name="Funnel Start Height",
    description="Percentage from the top of the Direct mold where funnels are created",
    default=80.0,
    min=1.0,
    max=99.0,
    subtype="PERCENTAGE",
    update=_update_direct_funnel_reference_height,
)

bpy.types.Scene.direct_funnel_depth = FloatProperty(
    name="Funnel Depth",
    description="Depth that Direct mold funnels extend inside the master model",
    default=5.0,
    min=0.0,
    subtype="DISTANCE",
)

bpy.types.Scene.direct_split_x = IntProperty(
    name="X",
    description="Number of editable mold split planes along the X axis",
    default=0,
    min=0,
    update=_update_direct_split_planes("y"),
)

bpy.types.Scene.direct_split_y = IntProperty(
    name="Y",
    description="Number of editable mold split planes along the Y axis",
    default=1,
    min=0,
    update=_update_direct_split_planes("x"),
)

def _get_direct_radial_splits(scene):
    # Keep the existing saved counts and server payload compatible.
    return scene.direct_split_x + scene.direct_split_y


def _set_direct_radial_splits(scene, value):
    current = _get_direct_radial_splits(scene)
    if value >= current:
        scene.direct_split_y += value - current
    else:
        # Remove the legacy X group first, retaining the original Y plane.
        remove_x = min(scene.direct_split_x, current - value)
        if remove_x:
            scene.direct_split_x -= remove_x
        remaining = current - value - remove_x
        if remaining:
            scene.direct_split_y = max(0, scene.direct_split_y - remaining)


bpy.types.Scene.direct_radial_splits = IntProperty(
    name="Vertical",
    description="Number of vertical split planes sharing a center; rotations are evenly spaced whenever the count changes",
    min=0,
    get=_get_direct_radial_splits,
    set=_set_direct_radial_splits,
)

# Compatibility alias for scenes and scripts using the slip-casting control.
bpy.types.Scene.slip_radial_splits = IntProperty(
    name="Vertical",
    description="Number of vertical split planes sharing a center; rotations are evenly spaced whenever the count changes",
    min=0,
    get=_get_direct_radial_splits,
    set=_set_direct_radial_splits,
)


bpy.types.Scene.direct_split_z = IntProperty(
    name="Z",
    description="Number of editable mold split planes along the Z axis",
    default=0,
    min=0,
    update=_update_direct_split_planes("z"),
)

bpy.types.Scene.undercuts_quality = EnumProperty(
    name="Detail",
    description="Voxel detail used when clearing undercuts",
    items=undercuts_quality_items,
    default=1,
)

bpy.types.Scene.undercuts_extraction_type = EnumProperty(
    name="Extraction",
    description="Direction used to clear undercuts",
    items=undercuts_extraction_type_items,
    default=0,
)

bpy.types.Scene.direct_support_pilar_width = FloatProperty(
    name="Width",
    description="Width of the Direct support pillars",
    default=5.0,
    min=0,
    subtype="DISTANCE",
)

bpy.types.Scene.direct_support_pilars = BoolProperty(
    name="Casting Support Pillars",
    description="Generate support pillars for the Direct mold",
    default=True,
)

bpy.types.Scene.direct_support_pilar_depth = FloatProperty(
    name="Depth",
    description="Depth of the Direct support pillars",
    default=-8,
    subtype="DISTANCE",
)

bpy.types.Scene.silicone_support_pilars = BoolProperty(
    name="Casting Support Pillars",
    description="Generate support pillars for the silicone mold",
    default=False,
    update=_make_lite_basic_guard("silicone_support_pilars"),
)

bpy.types.Scene.silicone_density = FloatProperty(
    name="Silicone Density (g/cm3)",
    description="Density used to calculate silicone weight from mold volume",
    default=DEFAULT_SILICONE_DENSITY,
    min=0,
    get=_get_silicone_density,
    set=_set_silicone_density,
    update=_make_lite_basic_guard("silicone_density"),
)

bpy.types.Scene.silicone_mix_mode = EnumProperty(
    name="Silicone Type",
    description="Calculate a single silicone weight or split it into components A and B",
    items=silicone_mix_mode_items,
    default=0,
)

bpy.types.Scene.silicone_mix_part_a = FloatProperty(
    name="Part A",
    description="Part A in the manufacturer's A:B mix ratio by weight (for example 100:10). Use the specified ratio for your silicone",
    default=1.0,
    min=0.001,
    max=10000.0,
    precision=3,
)

bpy.types.Scene.silicone_mix_part_b = FloatProperty(
    name="Part B",
    description="Part B in the manufacturer's A:B mix ratio by weight; 1:1 means equal weights, not equal volumes",
    default=1.0,
    min=0.001,
    max=10000.0,
    precision=3,
)

bpy.types.Scene.plaster_density = FloatProperty(
    name="Mixed Slurry Density (g/ml)",
    description="Density of the wet plaster-water mix, not loose powder or cured plaster; adjust for your mix ratio",
    default=SLIP_CASTING_DEFAULT_PLASTER_DENSITY,
    min=0,
)

bpy.types.Scene.plaster_mix_water_ml = FloatProperty(
    name="Water",
    description="Water in this recipe; automatically updates the estimated resulting volume",
    default=70.0,
    min=0.0,
    precision=1,
    update=update_plaster_mix_volume,
)

bpy.types.Scene.plaster_mix_plaster_g = FloatProperty(
    name="Plaster",
    description="Plaster in this recipe; automatically updates the estimated resulting volume",
    default=100.0,
    min=0.1,
    precision=1,
    update=update_plaster_mix_volume,
)

bpy.types.Scene.plaster_mix_volume_ml = FloatProperty(
    name="Makes",
    description=(
        "Volume produced by the water and plaster amounts above, measured freshly mixed before setting. "
        "Default estimate: 70 ml water + 100 g plaster produces about 102 ml (USG mixing guidance). "
        "Automatically estimated when Water or Plaster changes; override with a measured fresh mix volume if needed"
    ),
    default=102.0,
    min=0.1,
    precision=1,
)

preparation_settings.register(FloatProperty)

def _update_slip_casting_funnel_type(scene, context):
    # Orientation is finalized by Prepare Casting, never by a settings edit.
    scene['_moldboxer_previous_funnel_type'] = scene.slip_casting_funnel_type


bpy.types.Scene.slip_casting_funnel_type = EnumProperty(
    name="Funnel Style",
    description="Choose adapted or rounded slip-casting funnels",
    items=slip_casting_funnel_type_items,
    default=0, update=_update_slip_casting_funnel_type,
)
bpy.types.Scene.slip_casting_rounded_bottom_diameter = FloatProperty(
    name="Contact Diameter", description="Diameter of the lower face where the funnel meets the model",
    default=10.0, min=0.1, subtype="DISTANCE",
)
bpy.types.Scene.slip_casting_rounded_top_diameter = FloatProperty(
    name="Opening Diameter", description="Upper opening diameter; must exceed the contact diameter",
    default=20.0, min=0.1, subtype="DISTANCE",
)
bpy.types.Scene.slip_casting_rounded_extension = FloatProperty(
    name="Height Above Model", description="Height above the highest point of the model",
    default=20.0, min=0.1, subtype="DISTANCE",
)
bpy.types.Scene.slip_casting_rounded_detection_detail = EnumProperty(
    name="Detection Detail", description="Controls how much surface detail is retained",
    items=slip_casting_rounded_detection_detail_items, default=0,
)
bpy.types.Scene.slip_casting_rounded_count_mode = EnumProperty(
    name="Placement", description="Automatic placement or a custom total",
    items=slip_casting_rounded_count_mode_items,
    default=0,
)
bpy.types.Scene.slip_casting_rounded_count = IntProperty(
    name="Number of Funnels", description="Total number of funnels to place", default=1, min=1, max=128,
)


bpy.types.Scene.slip_casting_adapted_variant = EnumProperty(
    name="Placement", items=slip_casting_adapted_variant_items, default=0,
)


bpy.types.Scene.slip_casting_internal_model_type = EnumProperty(
    name="Model Type", items=slip_casting_internal_model_type_items, default=0,
)


bpy.types.Scene.slip_casting_flat_region_inset = FloatProperty(
    name="Surface Inset", description="Adjust the detected surface boundary",
    default=3.0, min=0.0, soft_max=5.0, precision=2, subtype="DISTANCE",
)


bpy.types.Scene.slip_casting_internal_top_expansion = FloatProperty(
    name="Funnel Taper",
    description="Expand the top of internal adapted funnels by this percentage; zero disables expansion",
    default=10.0, min=0.0, soft_max=100.0, precision=1, subtype="PERCENTAGE",
)


bpy.types.Scene.slip_casting_funnel_span = FloatProperty(
    name="Span",
    description="Controls the funnel span",
    default=12.0,
    min=0.1,
    soft_max=30.0,
    precision=2,
    subtype="DISTANCE",
)

bpy.types.Scene.slip_casting_funnel_extension = FloatProperty(
    name="Extension",
    description="Distance the finished funnel clearance extends below the master",
    default=20.0,
    min=0.1,
    soft_max=100.0,
    precision=2,
    subtype="DISTANCE",
)




bpy.types.Scene.slip_casting_generate_base = BoolProperty(
    name="Generate Foot",
    description="Generate a foot together with the funnels",
    default=True,
)

bpy.types.Scene.slip_casting_master_base_mode = EnumProperty(
    name="Master Base",
    description="Build one master base or an independent base for each box split section",
    items=(
        ("ONE_PIECE", "One Piece", "Join all master base sections into one piece"),
        ("PER_SPLIT", "Per Split", "Keep one master base per box split, with its own side locks and no locking gap"),
    ),
    default="PER_SPLIT",
)

bpy.types.Scene.silicone_multipart_opening = EnumProperty(
    name="Opening",
    description="Choose the multipart base layout",
    items=(
        # Keep stored identifiers/numbers so existing scenes retain their geometry.
        ("ENCLOSED", "Open Base", "Keep the master seated on the base without a downward wrapper extension", 0),
        ("OPEN_BASE", "Fully Enclosed", "Extend the wrappers and base downward by the mold thickness, leaving the master above the base", 1),
    ),
    default="ENCLOSED",
)

bpy.types.Scene.silicone_split_base_key_type = EnumProperty(
    name="Silicone Keys",
    description="Shape of the silicone split-base registration keys",
    items=(("BARRIER", "Barriers", "Continuous rounded keys like the clamp barriers"),
           ("PIN", "Pins", "Spherical registration pins")),
    default="BARRIER",
)
bpy.types.Scene.silicone_split_base_key_diameter = FloatProperty(
    name="Key Diameter", description="Maximum diameter of silicone keys. Reduced per split at confirmation to keep clearance from the master and outer mold surface: 0.5 mm per side without a usable channel, 1 mm with a channel",
    default=4.0, min=0.1, soft_max=10.0, subtype="DISTANCE",
)
bpy.types.Scene.silicone_split_base_key_tolerance = FloatProperty(
    name="Key Tolerance", description="Diameter reduction for male split-base keys",
    default=0.25, min=0.0, soft_max=1.0, subtype="DISTANCE",
)

bpy.types.Scene.plaster_locking_tolerance = FloatProperty(
    name="Plaster Locking Tolerance",
    description="Diameter reduction applied to male Slip Casting locking pins",
    default=SLIP_CASTING_DEFAULT_PLASTER_LOCKING_TOLERANCE,
    min=0,
    soft_max=5.0,
    subtype="DISTANCE",
)

bpy.types.Scene.plaster_locking_pin_type = EnumProperty(
    name="Pin Placement",
    description="Placement mode for Slip Casting plaster locking pins",
    items=plaster_locking_pin_type_items,
    default=SLIP_CASTING_DEFAULT_PLASTER_LOCKING_PIN_TYPE,
)

bpy.types.Scene.split_base_pin_diameter = FloatProperty(
    name="Plaster Locking Pin Diameter",
    description=(
        "Diameter of Slip Casting plaster locking pins, limited to half "
        "the mold thickness"
    ),
    default=SLIP_CASTING_DEFAULT_SPLIT_BASE_PIN_DIAMETER,
    min=0.0,
    soft_max=30.0,
    subtype="DISTANCE",
    update=_update_split_base_pin_diameter,
)

bpy.types.Scene.box_thickness = FloatProperty(
    name="Box Wall Thickness",
    description="Wall thickness of the generated mold box",
    default=3.5,
    min=2,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("box_thickness"),
)

bpy.types.Scene.wing_width = FloatProperty(
    name="Span",
    description="Span of the mold base wing",
    default=7,
    min=7,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("wing_width"),
)

bpy.types.Scene.base_thickness = FloatProperty(
    name="Thickness",
    description="Base thickness",
    default=5.5,
    min=2.0,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("base_thickness"),
)

bpy.types.Scene.base_type = EnumProperty(
    name="",
    description="Base generation type",
    items=base_type_items,
    default=0,
    update=_update_base_type,
)

bpy.types.Scene.base_pin_type = EnumProperty(
    name="",
    description="Type of base-to-wing locking system",
    items=base_pin_type_items,
    default=1,
    update=_make_lite_basic_guard("base_pin_type"),
)


bpy.types.Scene.box_quality = EnumProperty(
    name="Box",
    description="Box generation speed and quality",
    items=box_quality_items,
    default=1,
    update=_make_lite_basic_guard("box_quality"),
)

bpy.types.Scene.tray_type = EnumProperty(
    name="Type",
    description="Starting geometry used to generate the tray wrapper",
    items=(
        (
            "CONTOUR",
            "Contour",
            "Start the tray wrapper from a sphere for a safer outer contour",
        ),
        (
            "OPTIMIZED",
            "Optimized",
            "Start the tray wrapper directly from the patron geometry",
        ),
    ),
    default="OPTIMIZED",
)

bpy.types.Scene.funneler = EnumProperty(
    name="",
    items=funneler_type_items,
    default=0,
    update=_make_lite_basic_guard("funneler"),
)

bpy.types.Scene.funneler_ref_height = FloatProperty(
    name="Funnel Start Height",
    description="Percentage from the top of the mold where the funnel is created",
    default=80.0,
    min=1.0,
    max=99.0,
    subtype="PERCENTAGE",
    update=_update_funneler_ref_height,
)

bpy.types.Scene.funneler_offset = FloatProperty(
    name="Extension",
    description="Controls how far the funnel extends above the top of the mold.",
    default=5.0,
    min=0.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("funneler_offset"),
)

bpy.types.Scene.funneler_size_factor = FloatProperty(
    name="Size Factor",
    description="Scale factor applied to the generated funnel",
    default=1.0,
    min=0.1,
    max=3.0,
    update=_make_lite_basic_guard("funneler_size_factor"),
)


bpy.types.Scene.flat_grip = BoolProperty(
    name="Grip",
    description="Add a grip and flat mold text markings to flat automatic molds",
    default=True,
    update=_make_lite_basic_guard("flat_grip"),
)

bpy.types.Scene.tray_casting_volume = BoolProperty(
    name="Casting Volume",
    description="Engrave the casting volume on the underside of the tray grip",
    default=True,
)


bpy.types.Scene.clamp_pin_type = EnumProperty(
    name="",
    description="Type of clamp barrier or pin locking system",
    items=clamp_pin_type_items,
    default=0,
    update=_make_lite_basic_guard("clamp_pin_type"),
)

bpy.types.Scene.clamp_pin_system_type = EnumProperty(
    name="Pin System",
    description="Type of clamp alignment system",
    items=clamp_pin_system_items,
    default=1,
    update=_make_lite_basic_guard("clamp_pin_system_type"),
)

bpy.types.Scene.clamp_screws = BoolProperty(
    name="Screw Holes",
    description="Add screw pass-through holes in the clamps",
    get=_get_clamp_screws,
    set=_set_clamp_screws,
)

bpy.types.Scene.clamp_screw_diameter = FloatProperty(
    name="Screw Diameter",
    description="Diameter of screw pass-through holes in the clamps",
    default=4.0,
    min=0.1,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clamp_screw_diameter"),
)

bpy.types.Scene.clamp_width = FloatProperty(
    name="Width",
    description="Width of the clamps",
    default=5.0,
    min=3.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clamp_width"),
)

bpy.types.Scene.clamp_depth = FloatProperty(
    name="Depth",
    description="Depth of the clamps",
    default=DEFAULT_CLAMP_DEPTH,
    min=4,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clamp_depth"),
)

bpy.types.Scene.clamp_tolerance = FloatProperty(
    name="Tolerance",
    description="Tolerance for the clamps",
    default=0.25,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clamp_tolerance"),
)

bpy.types.Scene.clip_height = FloatProperty(
    name="Height",
    description="Height of the generated clamp clip",
    default=10.0,
    min=0.1,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clip_height"),
)

bpy.types.Scene.clip_thickness = FloatProperty(
    name="Thickness",
    description="Wall thickness of the generated clamp clip",
    default=4.0,
    min=0.1,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clip_thickness"),
)

bpy.types.Scene.clip_tolerance = FloatProperty(
    name="Tolerance",
    description="Clearance between the clamp and generated clip",
    default=0.25,
    min=0.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("clip_tolerance"),
)

bpy.types.Scene.clip_closing_pressure = FloatProperty(
    name="Closing Pressure",
    description="Closing pressure for the locking clamp",
    default=0.25,
    min=0.0,
    max=0.9,
    update=_make_lite_basic_guard("clip_closing_pressure"),
)


bpy.types.Scene.build_from_sphere = BoolProperty(
    name="Safe Mode Box",
    description="Enable if you see any not clean result box to ensure a clean moldbox, but it will take more time to create the mold",
    default=False,
    update=_make_lite_basic_guard("build_from_sphere"),
)


bpy.types.Scene.channel_width = FloatProperty(
    name="Width",
    description="Width of the channel",
    default=6,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("channel_width"),
)

bpy.types.Scene.channel_depth = FloatProperty(
    name="Depth",
    description="Depth of the channel",
    default=6,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("channel_depth"),
)

bpy.types.Scene.channels = BoolProperty(
    name="Channels",
    description="Generate channels",
    default=True,
    update=_make_lite_basic_guard("channels"),
)

bpy.types.Scene.horizontal_channels_count = IntProperty(
    name="Horizontal Channels",
    description="Number of horizontal channels to build",
    default=0,
    min=0,
    max=20,
    update=_make_lite_basic_guard("horizontal_channels_count"),
)

bpy.types.Scene.channel_end_shape = EnumProperty(
    name="Channel End Shape",
    description="Use tapered V-shaped channel ends or square cubic ends",
    items=channel_end_shape_items,
    default=0,
)

bpy.types.Scene.channels_type = EnumProperty(
    name="",
    description="Channel generation type",
    items=channels_type_items,
    default=0,
    update=_update_channels_type,
)

bpy.types.Scene.channels_contact_scale = FloatProperty(
    name="Contact Scale",
    description="Scale factor applied to the channel contact area",
    default=1.5,
    min=1.0,
    max=3.0,
    update=_make_lite_basic_guard("channels_contact_scale"),
)


bpy.types.Scene.channel_adjustment = EnumProperty(
    name="Adjustment",
    description="Channel support and adjustment mode",
    items=channel_adjustment_items,
    default=2,
    update=_make_lite_basic_guard("channel_adjustment"),
)
bpy.types.Scene.channel_back_larger = BoolProperty(
    name="Larger Back",
    description="Make the back channel larger",
    default=True,
    update=_make_lite_basic_guard("channel_back_larger"),
)

bpy.types.Scene.casting_feet = BoolProperty(
    name="Casting Feet",
    description="Add casting feet to the generated mold box",
    default=False,
    update=_update_casting_feet,
)

bpy.types.Scene.casting_feet_height = FloatProperty(
    name="Height",
    description="Height of the generated casting feet",
    default=5.0,
    min=0.5,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("casting_feet_height"),
)

bpy.types.Scene.casting_feet_size_factor = FloatProperty(
    name="Size Factor",
    description="Size factor applied to the generated casting feet",
    default=1.0,
    min=0.1,
    max=2.0,
    update=_make_lite_basic_guard("casting_feet_size_factor"),
)

bpy.types.Scene.casting_grip = BoolProperty(
    name="Casting Grip",
    description="Add a casting grip to the generated channels deposit",
    default=False,
    update=_make_lite_basic_guard("casting_grip"),
)

bpy.types.Scene.casting_grip_width = FloatProperty(
    name="Thickness",
    description="Width of the generated casting grip",
    default=5.0,
    min=0.1,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("casting_grip_width"),
)

bpy.types.Scene.casting_grip_depth = FloatProperty(
    name="Span",
    description="Depth of the generated casting grip",
    default=7.0,
    min=0.1,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("casting_grip_depth"),
)

bpy.types.Scene.wing_join_patron = BoolProperty(
    name="Fixed Master",
    description=(
        "When enabled, the generated mold system includes the master joined "
        "to the base. When disabled, the master is split from the base"
    ),
    default=True,
    update=_make_lite_basic_guard("wing_join_patron"),
)


bpy.types.Scene.n_splits_xy = IntProperty(
    name="X/Y Splits",
    description="Number of splits along the X/Y plane",
    default=1,
    min=0,
    max=2,
    update=_make_lite_basic_guard("n_splits_xy"),
)

bpy.types.Scene.n_splits_z = IntProperty(
    name="Z",
    description="Number of horizontal splits of the box",
    default=0,
    min=0,
    max=20,
    update=_make_lite_basic_guard("n_splits_z"),
)

bpy.types.Scene.split_connector_tolerance = FloatProperty(
    name="Connector Tol",
    description="Clearance added to the negative side of the split connector",
    default=0.2,
    min=0.0,
    soft_max=2.0,
    subtype="DISTANCE",
)


# Grip

bpy.types.Scene.grip_height = FloatProperty(
    name="H",
    description="Height of the grip",
    default=10,
    subtype="DISTANCE",
)

# Clean
bpy.types.Scene.cut_clean_height = FloatProperty(
    name="Height",
    description="Height to clean or cut",
    default=1,
    min=0.1,
    subtype="DISTANCE",
)

## Master Holes

bpy.types.Scene.master_holes_depth = FloatProperty(
    name="D",
    description="Depth of the master holes",
    default=3,
    subtype="DISTANCE",
)


## Volume
bpy.types.Scene.volume = FloatProperty(
    name="Volume",
    description="Volume of the mold",
    default=0,
)
bpy.types.Scene.casting_volume_ml = FloatProperty(
    name="Casting Volume",
    description="Calculated casting volume",
    default=0,
)

## Grid
bpy.types.Scene.grid_distance = FloatProperty(
    name="Distance",
    description="Distance between the grid",
    default=4,
    subtype="DISTANCE",
)
bpy.types.Scene.grid_rows = IntProperty(
    name="Rows",
    description="Number of rows of the grid",
    default=3,
)
bpy.types.Scene.grid_columns = IntProperty(
    name="Columns",
    description="Number of columns of the grid",
    default=3,
)

## Import
bpy.types.Scene.import_model = StringProperty(
    name="Master",
    description="Import Master Model",
    default="//",
    subtype="FILE_PATH",
)

## EXPORT

bpy.types.Scene.export_stl_folder = StringProperty(
    name="Folder",
    description="Folder to export the mold system",
    default="//",
    subtype="DIR_PATH",
)

## Utils
bpy.types.Scene.clear_extraction = BoolProperty(
    name="Clear undercuts",
    description=(
        "For Slip Cast, clear the master when generating the mold; the box "
        "always has its undercuts cleared. For other molds, the box is generated with undercuts cleared "
        "relative to the split direction, making the mold easier to remove "
        "from the system. This improves demolding but makes the mold box less "
        "adjusted to the contour"
    ),
    default=True,
    update=_make_lite_basic_guard("clear_extraction"),
)

bpy.types.Scene.clear_undercuts_mode = EnumProperty(
    name="Type",
    description=(
        "Choose the extraction-direction policy and whether candidate cost "
        "uses precise model intersection checks"
    ),
    items=clear_undercuts_mode_items,
    default=1,
)

bpy.types.Scene.master_base_pin = BoolProperty(
    name="Master Pin Keys",
    description="Add master-base pin when Fixed Master is disabled",
    default=True,
    update=_make_lite_basic_guard("master_base_pin"),
)

bpy.types.Scene.master_base_pin_tolerance = FloatProperty(
    name="Pin Tolerance",
    description="Clearance between the master-base male and female pin keys",
    default=0.02,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("master_base_pin_tolerance"),
)

bpy.types.Scene.master_base_pin_height = FloatProperty(
    name="Pin Height",
    description="Height of the master-base male pin key",
    default=2.5,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_make_lite_basic_guard("master_base_pin_height"),
)

bpy.types.Scene.pro_inner_cavity = BoolProperty(
    name="Inner cavity",
    description="Create inner pot-style cavity filler geometry to reduce silicone usage",
    default=False,
    get=_get_pro_inner_cavity,
    set=_set_pro_inner_cavity,
)

bpy.types.Scene.pro_inner_cavity_sensitivity = EnumProperty(
    name="Power",
    description="Controls cavity detection power",
    items=inner_cavity_sensitivity_items,
    default=1,
    update=_make_pro_guard("pro_inner_cavity_sensitivity"),
)

bpy.types.Scene.pro_inner_cavity_core_type = EnumProperty(
    name="Core Type",
    description=(
        "Choose whether each inner core and its attacher form one part or separate parts"
    ),
    items=inner_cavity_core_type_items,
    # Blender requires an integer default when EnumProperty items use a callback.
    # Callback enum values are one-based here, so 1 selects SINGLE_PART.
    default=1,
    update=_make_pro_guard("pro_inner_cavity_core_type"),
)

bpy.types.Scene.pro_casting_box = BoolProperty(
    name="Casting Box",
    description="Create duplicate cut casting boxes for the generated mold",
    default=False,
    get=_get_pro_casting_box,
    set=_set_pro_casting_box,
)

bpy.types.Scene.pro_casting_box_type = EnumProperty(
    name="Casting Box Type",
    description="Choose how much of the generated casting box is retained",
    items=[
        (
            "STANDARD",
            "Standard",
            "Create a full duplicate cut casting box",
        ),
        (
            "OPTIMIZED",
            "Optimized",
            (
                "Keep only bands around split planes and the selected "
                "ring"
            ),
        ),
    ],
    default="OPTIMIZED",
    update=_update_pro_casting_box_type,
)

bpy.types.Scene.pro_casting_box_different_thickness = BoolProperty(
    name="Different Thickness",
    description="Use a wall thickness for the casting box that is different from the mold box",
    default=False,
    update=_make_pro_guard("pro_casting_box_different_thickness"),
)

bpy.types.Scene.casting_box_thickness = FloatProperty(
    name="Casting Box Wall Thickness",
    description="Wall thickness of the separately opened casting box",
    default=5.0,
    min=2.0,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_make_pro_guard("casting_box_thickness"),
)

bpy.types.Scene.optimized_casting_box_thickness = FloatProperty(
    name="Width",
    description=(
        "Width of optimized casting-box bands around split planes and the "
        "ring"
    ),
    default=15.0,
    min=0.1,
    soft_max=50.0,
    subtype="DISTANCE",
    update=_make_pro_guard("optimized_casting_box_thickness"),
)

bpy.types.Scene.optimized_casting_box_horizontal_intersection = EnumProperty(
    name="Ring",
    description=(
        "Place the optimized casting-box ring at the top or bottom"
    ),
    items=[
        (
            "TOP",
            "Top",
            "Keep the casting-box ring at the top",
        ),
        (
            "BOTTOM",
            "Bottom",
            "Keep the casting-box ring at the bottom",
        ),
    ],
    default="TOP",
    update=_make_pro_guard("optimized_casting_box_horizontal_intersection"),
)

bpy.types.Scene.pro_two_part_silicone = BoolProperty(
    name="Silicone · Two-Part Mold",
    description="Create a mold system for producing separate 2-part silicone molds",
    default=False,
    update=_update_pro_two_part_silicone,
)

bpy.types.Scene.pro_open_base = BoolProperty(
    name="Open base",
    description="Keep the two-parts mold base open below the selected object's minimum Z",
    default=True,
    update=_make_pro_guard("pro_open_base"),
)

bpy.types.Scene.pro_casting_feet = BoolProperty(
    name="Casting Feet",
    description="Enable casting feet for two-parts molds",
    default=False,
    update=_make_pro_guard("pro_casting_feet"),
)

bpy.types.Scene.pro_key_size = FloatProperty(
    name="Key Size",
    description="Cube size used to build one key at each two-parts circle vertex",
    default=10.0,
    min=0.1,
    soft_max=20.0,
    subtype="DISTANCE",
    update=_make_pro_guard("pro_key_size"),
)

bpy.types.Scene.pro_key_tolearnce = FloatProperty(
    name="Key Tolerance",
    description="Size reduction applied to the male keys on each axis",
    default=0.5,
    min=0.0,
    soft_max=5.0,
    subtype="DISTANCE",
    update=_make_pro_guard("pro_key_tolearnce"),
)

bpy.types.Scene.pro_master_filler_quality = EnumProperty(
    name="Detail",
    description="Master filler generation speed and detail",
    items=filler_quality_items,
    default=2,
    update=_make_pro_guard("pro_master_filler_quality"),
)

bpy.types.Scene.master_filler_remove_type = EnumProperty(
    name="Filler Type",
    description="Filler type to remove",
    items=filler_remove_type_items,
    default=2,
    update=_make_pro_guard("master_filler_remove_type"),
)

bpy.types.Scene.pro_master_base_offset = FloatProperty(
    name="Offset",
    description="Distance subtracted from the base silhouette Z position",
    default=0.0,
    subtype="DISTANCE",
    update=_make_pro_guard("pro_master_base_offset"),
)

bpy.types.Scene.pro_watermark = StringProperty(
    name="Watermark",
    description="Text to send to server-side watermark generation",
    default="",
    update=_make_pro_guard("pro_watermark"),
)

bpy.types.Scene.casting_input_shape = EnumProperty(
    name="Shape",
    description="Shape used to create the casting input",
    items=casting_input_shape_items,
    default=0,
)

bpy.types.Scene.casting_input_project_top = BoolProperty(
    name="Project",
    description="Project the casting sprue top face to the patron along Z",
    default=True,
)

bpy.types.Scene.casting_input_base_offset = FloatProperty(
    name="Base Offset",
    description="Offset from the patron base for the casting sprue base projection plane",
    default=0.0,
    min=0.0,
    subtype="DISTANCE",
)

bpy.types.Scene.scale_height = FloatProperty(
    name="H (cm)",
    description="Height to scale the object to in centimeters",
    default=10,
)

bpy.types.Scene.mold_type_preview = EnumProperty(
    name="Mold Type",
    description="Mold workflow used by Generate Mold",
    items=MOLD_TYPE_ENUM_ITEMS,
    default=DEFAULT_MOLD_TYPE,
    update=_update_mold_type_preview,
)

bpy.types.Scene.mold_advanced_mode = BoolProperty(
    name="Advanced Mode",
    description=(
        "Create your mold system in two steps so you can fully customize "
        "its components before confirming"
    ),
    default=False,
    update=_make_lite_basic_guard("mold_advanced_mode"),
)

bpy.types.Scene.dev_batch_tests_path = StringProperty(
    name="Batch Tests Path",
    description="Folder containing models to batch import, mold, save, and export",
    default="",
    subtype="DIR_PATH",
)

bpy.types.Scene.bottom_scale_factor = FloatProperty(
    name="Bottom XY",
    description="Scale factor applied to the bottom of the object with a smooth falloff toward the top",
    default=0.8,
    min=0.01,
    soft_max=3.0,
)


from .source.casting_material import register_properties as register_material_properties
register_material_properties(FloatProperty, EnumProperty)
