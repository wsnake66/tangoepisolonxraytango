import bpy  # type: ignore
import bpy.utils.previews  # type: ignore
import math
from pathlib import Path
try:
    from moldboxer_silicone_native.source.constants import ENABLE_CUSTOM_FACE_CORE
    from moldboxer_silicone_native.source.build_profile import IS_PRODUCTION_BUILD
    from moldboxer_silicone_native.source.environment import get_addon_preferences
    from moldboxer_silicone_native.source.i18n import prop_label, t
    from moldboxer_silicone_native.source.operator_access import is_core_tier, is_lite_tier
    from moldboxer_silicone_native.source.components.direct_split_planes import (
        direct_split_plane_specs,
        foundation_reference_guide_active,
        foundation_reference_guide_available,
        schedule_direct_split_plane_sync,
    )
    from moldboxer_silicone_native.source.components.direct_mold import (
        ensure_direct_patron_backup,
    )
    from moldboxer_silicone_native.source.components.funnel_reference_line import (
        schedule_funnel_reference_line_sync,
    )
    from moldboxer_silicone_native.source.components.casting_input import (
        CASTING_INPUT_NAME,
    )
    from moldboxer_silicone_native.source.components.master_air_traps import (
        scene_has_master_air_trap_pillars,
    )
    from moldboxer_silicone_native.source.components.box_parts import (
        get_effective_casting_box_type,
    )
    from moldboxer_silicone_native.source.components.slip_casting_cavity_filler import (
        slip_casting_cavities_filled,
        slip_casting_funnels_built,
        slip_casting_has_prepared_parts,
        slip_casting_initial_stage_complete,
        slip_casting_vase_prepared,
    )
    from moldboxer_silicone_native.source.bl_utils import (
        _draw_overlay_background,
        _get_overlay_ui_scale,
        _scale_overlay_value,
        MOLDBOXER_VIEWPORT_CARD_BACKGROUND_COLOR,
        MOLDBOXER_VIEWPORT_CARD_BORDER_COLOR,
        ensure_moldboxer_transform_gizmos_for_selection,
        get_viewport_info_overlay_row_layout,
        get_viewport_workflow_instruction,
        scene_has_master_filler_objects,
        set_viewport_metrics_mode,
    )
    from moldboxer_silicone_native.source.extension_updates import (
        get_extension_update_status,
    )
except ImportError:
    from .source.constants import ENABLE_CUSTOM_FACE_CORE
    from .source.build_profile import IS_PRODUCTION_BUILD
    from .source.environment import get_addon_preferences
    from .source.i18n import prop_label, t
    from .source.operator_access import is_core_tier, is_lite_tier
    from .source.components.direct_split_planes import (
        direct_split_plane_specs,
        foundation_reference_guide_active,
        foundation_reference_guide_available,
        schedule_direct_split_plane_sync,
    )
    from .source.components.direct_mold import ensure_direct_patron_backup
    from .source.components.funnel_reference_line import schedule_funnel_reference_line_sync
    from .source.components.casting_input import CASTING_INPUT_NAME
    from .source.components.master_air_traps import (
        scene_has_master_air_trap_pillars,
    )
    from .source.components.box_parts import get_effective_casting_box_type
    from .source.components.slip_casting_cavity_filler import (
        slip_casting_cavities_filled,
        slip_casting_funnels_built,
        slip_casting_has_prepared_parts,
        slip_casting_initial_stage_complete,
        slip_casting_vase_prepared,
    )
    from .source.bl_utils import (
        _draw_overlay_background,
        _get_overlay_ui_scale,
        _scale_overlay_value,
        MOLDBOXER_VIEWPORT_CARD_BACKGROUND_COLOR,
        MOLDBOXER_VIEWPORT_CARD_BORDER_COLOR,
        ensure_moldboxer_transform_gizmos_for_selection,
        get_viewport_info_overlay_row_layout,
        get_viewport_workflow_instruction,
        scene_has_master_filler_objects,
        set_viewport_metrics_mode,
    )
    from .source.extension_updates import get_extension_update_status

from .source.mold_types import (
    is_silicone_multipart_type,
    is_slip_casting_type,

    MOLD_TYPES,
    MOLD_TYPE_OPTIONS,
    MOLD_TYPE_ENUM_ITEMS,
    get_mold_type,
    is_multipart_type,
    is_slip_casting_vase_type,
    resolve_direct_mold_opening,
)
from .source.components.fixture import schedule_fixture_height_guide_sync
from .source.viewport_custom_panel import (
    draw_panel as draw_custom_viewport_panel,
    draw_utility_column as draw_viewport_utility_column,
    flatten_nodes as flatten_custom_panel_nodes,
    hitbox_at as custom_panel_hitbox_at,
    point_in_rect as point_in_custom_panel_rect,
    record_panels as record_custom_panels,
    set_preview_path_resolver as set_custom_panel_preview_path_resolver,
)

preview_collections = {}
_panel_preview_paths = {}


def _load_panel_preview(collection, key, path, preview_type="IMAGE"):
    preview = collection.load(key, str(path), preview_type)
    if Path(path).name == "slip_cast_plaster.png":
        from .source.preview_badges import load_catalog_preview_image

        image = load_catalog_preview_image(path)
        preview.image_size = image.size[:]
        preview.image_pixels_float = image.pixels[:]
    _panel_preview_paths[str(key)] = str(path)
    return preview


_mold_type_picker_items_cache = ()
_funnel_type_picker_items_cache = ()
_channel_adjustment_picker_items_cache = ()
_clamp_pin_type_picker_items_cache = ()
_master_attachment_picker_items_cache = ()
_tray_type_picker_items_cache = ()
_base_type_picker_items_cache = ()
_casting_box_type_picker_items_cache = ()
_inner_cavity_core_type_picker_items_cache = ()
_shape_type_picker_items_cache = ()
_slip_casting_funnel_picker_items_cache = ()
_slip_casting_base_picker_items_cache = ()
_slip_casting_master_base_picker_items_cache = ()
_silicone_multipart_opening_picker_items_cache = ()
SLIP_CASTING_FUNNEL_OPTIONS = (
    ("ADAPTED", "Adapted", "slip_casting_funnel_settings.png", "Follow the detected surface", 0),
    ("ROUNDED", "Rounded", "slip_casting_rounded_funnel.png", "Tapered circular funnels on top of the master", 1),
)

SLIP_CASTING_BASE_OPTIONS = (
    ("BASE", "Foot", "slip_casting_base.png", "Generate a foot together with the funnels", 1),
    ("NO_BASE", "No Foot", "slip_casting_no_base.png", "Generate funnels without a foot", 0),
)

SLIP_CASTING_MASTER_BASE_OPTIONS = (
    ("ONE_PIECE", "One Piece", "slip_casting_master_base_one_piece.png", "Join all master base sections into one piece", 0),
    ("PER_SPLIT", "Per Split", "slip_casting_master_base_per_split.png", "Keep one master base per box split section", 1),
)

SILICONE_MULTIPART_OPENING_OPTIONS = (
    (
        "ENCLOSED",
        "Open Base",
        "multipart_opening_open_base.png",
        "Keep the master seated on the base without a downward wrapper extension",
        0,
    ),
    (
        "OPEN_BASE",
        "Fully Enclosed",
        "multipart_opening_fully_enclosed.png",
        "Extend the wrappers and base downward by the mold thickness, leaving the master above the base",
        1,
    ),
)

# Remove the retired direction picker immediately on add-on reload.
if hasattr(bpy.types.WindowManager, "clear_extraction_type_picker"):
    del bpy.types.WindowManager.clear_extraction_type_picker

FUNNEL_TYPES = (
    ("optimized", "Funnel - Optimized", "optimized_funnel.png"),
    ("cylinder", "Funnel - Cylinder", "cylinder_funnel.png"),
)
FUNNEL_TYPE_IDS = {identifier for identifier, _label, _filename in FUNNEL_TYPES}
CHANNEL_ADJUSTMENTS = (
    (
        "support",
        "Channels - Support",
        "support_channels_transparent.png",
        "Maximum support, but uses more silicone and makes demolding harder.",
    ),
    (
        "balanced",
        "Channels - Balanced",
        "balanced_channels_transparent.png",
        "Balances support, silicone use, and ease of demolding.",
    ),
    (
        "adjusted",
        "Channels - Adjusted",
        "adjusted_channels_transparent.png",
        "Reduces silicone waste and makes demolding easier, but provides less support.",
    ),
)
CHANNEL_ADJUSTMENT_IDS = {
    identifier
    for identifier, _label, _filename, _description in CHANNEL_ADJUSTMENTS
}
BASE_TYPES = (
    (
        "classic",
        "Base - Winged",
        "wing_base_classic.png",
        "Build a base with supporting wings.",
    ),
    (
        "optimized",
        "Base - Optimized",
        "optimized_base.png",
        "Build an optimized compact base.",
    ),
)
BASE_TYPE_IDS = {
    identifier for identifier, _label, _filename, _description in BASE_TYPES
}
CASTING_BOX_TYPES = (
    (
        "STANDARD",
        "Standard Casting Box",
        "casting_box.png",
        "Create a full duplicate cut casting box.",
    ),
    (
        "OPTIMIZED",
        "Optimized Casting Box",
        "casting_box_optimized.png",
        (
            "Keep only bands around split planes and the selected ring to "
            "save material."
        ),
    ),
)
CASTING_BOX_TYPE_IDS = {
    identifier
    for identifier, _label, _filename, _description in CASTING_BOX_TYPES
}
INNER_CAVITY_CORE_TYPES = (
    (
        "SINGLE_PART",
        "Single Part",
        "core_single_part.png",
        "Join each core to its attacher as one printable part",
    ),
    (
        "MULTI_PART",
        "Multi-Part",
        "core_multi_part.png",
        "Keep the core and attacher separate and cut the attacher socket into the core",
    ),
)
INNER_CAVITY_CORE_TYPE_IDS = {
    identifier
    for identifier, _label, _filename, _description in INNER_CAVITY_CORE_TYPES
}
MASTER_ATTACHMENT_TYPES = (
    ("FIXED", "Fixed Master", "fixed_master.png", True),
    ("UNFIXED", "Unfixed Master", "unfixed_master.png", False),
)
MASTER_ATTACHMENT_TYPE_IDS = {
    identifier
    for identifier, _label, _filename, _is_fixed in MASTER_ATTACHMENT_TYPES
}
TRAY_TYPES = (
    (
        "OPTIMIZED",
        "Optimized",
        "tray_optimized.png",
        "Start the tray wrapper directly from the patron geometry",
    ),
    (
        "CONTOUR",
        "Contour",
        "tray_contour.png",
        "Start the tray wrapper from a sphere for a safer outer contour",
    ),
)
TRAY_TYPE_IDS = {
    identifier for identifier, _label, _filename, _description in TRAY_TYPES
}
BASE_PIN_TYPES = (
    (
        "barrier",
        "Barrier",
        "barrier_base.png",
        "Use the base barrier locking system",
    ),
    ("pin", "Pin", "pin_base.png", "Use cylindrical base pins"),
    ("none", "None", "", "Do not add a base locking system"),
)
CLAMP_PIN_TYPES = (
    (
        "barrier",
        "Barrier",
        "barrier_clamp.png",
        "Use the clamp barrier locking system",
    ),
    (
        "pin",
        "Pin",
        "pin_clamp.png",
        "Use male/female sphere pins on the clamps",
    ),
    ("none", "None", "none_clamp.png", "Do not add clamp barriers or pins"),
)
PIN_TYPE_TARGETS = {
    "BASE": ("base_pin_type", BASE_PIN_TYPES),
    "CLAMP": ("clamp_pin_type", CLAMP_PIN_TYPES),
}

# Panel summaries keep the setting family so the applied value is immediately
# clear (for example, "Channels - Balanced"). Inside a selector, that context
# is already supplied by the menu heading, so repeat only the option itself.
SELECTOR_OPTION_LABELS = {
    "Funnel - Optimized": "Optimized",
    "Funnel - Cylinder": "Cylinder",
    "Channels - Support": "Support",
    "Channels - Balanced": "Balanced",
    "Channels - Adjusted": "Adjusted",
    "Base - Winged": "Winged",
    "Base - Optimized": "Optimized",
    "Standard Casting Box": "Standard",
    "Optimized Casting Box": "Optimized",
    "Fixed Master": "Fixed",
    "Unfixed Master": "Unfixed",
}
SHAPE_TYPES = (
    (
        "cube",
        "Cube",
        "shape_cube.png",
        "Use a cube outer shape",
    ),
    (
        "cylinder",
        "Cylinder",
        "shape_cylinder.png",
        "Use a cylinder outer shape",
    ),
    (
        "adapted",
        "Adapted",
        "shape_adapted.png",
        "Adapt the outer shape to the model",
    ),
)
SHAPE_TYPE_IDS = {
    identifier for identifier, _label, _filename, _description in SHAPE_TYPES
}
_VIEW3D_HEADER_CONTROLS_REGISTERED = False
_ORIGINAL_VIEW3D_HEADER_DRAW = None
_ORIGINAL_TOPBAR_HEADER_DRAW = None
_VIEWPORT_ACTION_BAR_DRAW_HANDLER = None
_VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER = None
_VIEWPORT_TRANSFORM_PANEL_DRAW_ERROR = ""
_VIEWPORT_UTILS_LABEL_DRAW_HANDLER = None
_VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER = None
_VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER = None
_VIEWPORT_ACTION_BAR_KEYMAPS = []
_VIEW3D_HEADER_VISIBILITY = {}
_VIEW3D_TOOL_HEADER_VISIBILITY = {}
_VIEW3D_TOOLBAR_VISIBILITY = {}
_VIEW3D_SIDEBAR_VISIBILITY = {}
_VIEW3D_SIDEBAR_CATEGORIES = {}
_VIEW3D_SIDEBAR_ALIGNMENTS = {}
_VIEW3D_NAVIGATION_GIZMO_VISIBILITY = {}
_VIEW3D_OVERLAY_TEXT_VISIBILITY = {}
_NAVIGATION_CONTROLS_WERE_VISIBLE = None
_pending_detected_import_objects = []
_accepted_detected_import_pointers = set()

_ACTION_BAR_FONT_ID = 0
_ACTION_BAR_FONT_SIZE = 13
_ACTION_BAR_TITLE_FONT_SIZE = 14
_ACTION_BAR_TITLE_MIN_FONT_SIZE = 11
_ACTION_BAR_TITLE_MAX_LINES = 3
_ACTION_BAR_TITLE_LINE_GAP = 2
_ACTION_BAR_BUTTON_HEIGHT = 38
_ACTION_BAR_BUTTON_WIDTH = 190
_ACTION_BAR_BUTTON_PADDING_X = 15
_ACTION_BAR_BUTTON_GAP = 6
_ACTION_BAR_GROUP_GAP = 14
_ACTION_BAR_PANEL_PADDING = 10
_ACTION_BAR_ACCENT_WIDTH = 3
_ACTION_BAR_ACCENT_GAP = 9
_ACTION_BAR_STATUS_MAX_WIDTH = 220
_ACTION_BAR_BOTTOM_MARGIN = 12
_ACTION_BAR_CORNER_RADIUS = 8
_NAVIGATION_GIZMO_HORIZONTAL_MARGIN = 28
_NAVIGATION_GIZMO_VERTICAL_MARGIN = 40
_ACTION_BAR_PANEL_COLOR = MOLDBOXER_VIEWPORT_CARD_BACKGROUND_COLOR
_ACTION_BAR_PANEL_BORDER_COLOR = MOLDBOXER_VIEWPORT_CARD_BORDER_COLOR
_ACTION_BAR_SECONDARY_COLOR = (0.16, 0.16, 0.16, 0.98)
_ACTION_BAR_SECONDARY_BORDER_COLOR = (0.28, 0.28, 0.28, 1.0)
_ACTION_BAR_PRIMARY_COLOR = (0.541, 0.365, 0.047, 1.0)
_ACTION_BAR_PRIMARY_BORDER_COLOR = (0.714, 0.490, 0.071, 1.0)
_ACTION_BAR_WARNING_COLOR = (0.55, 0.16, 0.10, 1.0)
_ACTION_BAR_WARNING_BORDER_COLOR = (0.78, 0.25, 0.14, 1.0)
_ACTION_BAR_DISABLED_COLOR = (0.11, 0.11, 0.11, 0.90)
_ACTION_BAR_TEXT_COLOR = (0.96, 0.96, 0.96, 1.0)
_ACTION_BAR_BODY_TEXT_COLOR = (0.70, 0.70, 0.70, 1.0)
_ACTION_BAR_DISABLED_TEXT_COLOR = (0.45, 0.45, 0.45, 1.0)

_TRANSFORM_PANEL_WIDTH = 272
_TRANSFORM_PANEL_PADDING = 12
_TRANSFORM_PANEL_HEADER_HEIGHT = 36
_TRANSFORM_PANEL_ROW_HEIGHT = 32
_TRANSFORM_PANEL_ROW_GAP = 6
_TRANSFORM_PANEL_SECTION_HEIGHT = 24
_TRANSFORM_PANEL_SECTION_GAP = 8
_TRANSFORM_PANEL_TOP_MARGIN = 16
_TRANSFORM_PANEL_LEFT_MARGIN = 16
_TRANSFORM_PANEL_FIELD_COLOR = (0.075, 0.075, 0.075, 0.98)
_TRANSFORM_PANEL_FIELD_HOVER_COLOR = (0.12, 0.12, 0.12, 0.98)
_TRANSFORM_PANEL_AXIS_COLORS = {
    "X": (0.95, 0.25, 0.22, 1.0),
    "Y": (0.42, 0.78, 0.20, 1.0),
    "Z": (0.20, 0.48, 0.95, 1.0),
}
_VIEWPORT_TRANSFORM_UNIT = "MM"
_VIEWPORT_SCALE_PROPORTIONAL = True
_VIEWPORT_TRANSFORM_HOVERED = ""
_VIEWPORT_TRANSFORM_EDIT_STATE = None
_VIEWPORT_TRANSFORM_EXIT_CHECK_GENERATION = 0
_VIEWPORT_TRANSFORM_TOOL_IDS = {
    "builtin.move",
    "builtin.rotate",
    "builtin.scale",
}

_VIEWPORT_TOOLS_FIRST_OFFSET = 36
_VIEWPORT_UTILS_FIRST_OFFSET = 220
_VIEWPORT_UTILS_SPACING = 34
_VIEWPORT_UTILS_ICON_SCALE = 10
_VIEWPORT_GIZMO_REFERENCE_SIZE = 75
_VIEWPORT_UTILS_LABEL_WIDTH = 118
_VIEWPORT_UTILS_LABEL_HEIGHT = 27
_VIEWPORT_UTILS_LABEL_FONT_SIZE = 11
_VIEWPORT_UTILS_LABEL_OVERLAP = 17
_VIEWPORT_UTILS_LABEL_COLOR = (0.075, 0.075, 0.075, 0.90)
_VIEWPORT_HOVERED_TOOL_ID = ""
_VIEWPORT_HOVERED_UTIL_OPERATOR = ""
_VIEWPORT_LABEL_HOVERED_TOOL_ID = ""
_VIEWPORT_LABEL_HOVERED_UTIL_OPERATOR = ""
_VIEWPORT_CUSTOM_PANEL_STATES = {}
_VIEWPORT_CUSTOM_PANEL_HEADER_STATES = {}
_VIEWPORT_UTILITY_COLUMN_STATES = {}
_VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS = {
    "SILICONE_PT_pro_settings",
    "SILICONE_PT_utils",
}

class _SuppressedActionOperatorProperties:
    """Accept property assignments without drawing a header button."""


class _SuppressedActionLayout:
    """Discard contextual actions that are rendered in the viewport."""

    def operator(self, _operator, text="", icon="NONE"):
        del text, icon
        return _SuppressedActionOperatorProperties()


def _invoke_detected_import_processing(object_name):
    """Start import preprocessing from a live 3D-view context.

    The accepted-import callback runs from an application timer, where
    ``bpy.context.window`` can be unset.  ``ProcessDetectedImport`` starts a
    modal worker and therefore needs a real window for its event timer.
    """

    window_manager = getattr(bpy.context, "window_manager", None)
    windows = getattr(window_manager, "windows", ()) if window_manager else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            window_region = next(
                (
                    region
                    for region in getattr(area, "regions", ())
                    if getattr(region, "type", None) == "WINDOW"
                ),
                None,
            )
            if window_region is None:
                continue
            try:
                with bpy.context.temp_override(
                    window=window,
                    area=area,
                    region=window_region,
                ):
                    return bpy.ops.silicone.process_detected_import(
                        "EXEC_DEFAULT",
                        object_name=object_name,
                    )
            except (AttributeError, RuntimeError, TypeError):
                logger.debug(
                    "Could not start detected-import processing in a 3D view",
                    exc_info=True,
                )

    try:
        return bpy.ops.silicone.process_detected_import(
            "EXEC_DEFAULT",
            object_name=object_name,
        )
    except (AttributeError, RuntimeError, TypeError):
        logger.exception(
            "Could not start processing for imported object %s",
            object_name,
        )
        return {"CANCELLED"}


def _process_pending_detected_imports():
    while _pending_detected_import_objects:
        imported_object = _pending_detected_import_objects.pop(0)
        try:
            object_name = imported_object.name
        except ReferenceError:
            continue
        resolved_object = bpy.data.objects.get(object_name)
        if (
            resolved_object is None
            or resolved_object.as_pointer() != imported_object.as_pointer()
        ):
            continue
        result = _invoke_detected_import_processing(object_name)
        if "RUNNING_MODAL" not in result and "FINISHED" not in result:
            resolved_object.hide_set(False)
            logger.warning(
                "Detected import preprocessing did not start: %s",
                object_name,
            )
    return None


def _schedule_detected_import_processing(imported_object):
    if imported_object is None:
        return
    _pending_detected_import_objects.append(imported_object)
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _process_pending_detected_imports
    ):
        return
    bpy.app.timers.register(
        _process_pending_detected_imports,
        first_interval=0.0,
    )


def is_direct_mold_type(scene):
    mold_type = get_mold_type(scene.mold_type_preview)
    return mold_type.generate_operator == "silicone.automatic_mold"


def scene_has_model_object(scene):
    for obj in scene.objects:
        if getattr(obj, "type", None) != "MESH":
            continue
        try:
            if bool(obj.get("moldboxer_direct_split_plane")):
                continue
            if bool(obj.get("moldboxer_direct_split_plane_contour")):
                continue
            if bool(obj.get("moldboxer_skin_base_reference_guide")):
                continue
        except Exception:
            pass
        if str(getattr(obj, "name", "")).casefold().startswith(
            "direct_split_plane"
        ):
            continue
        return True
    return False


def scene_has_skin_core(scene):
    core = scene.objects.get("skin_core")
    return bool(
        core is not None
        and getattr(core, "type", None) == "MESH"
        and bool(getattr(core, "get", lambda *_: False)("moldboxer_skin_core"))
    )


def scene_has_casting_input(scene):
    return any(
        getattr(obj, "type", None) == "MESH"
        and str(getattr(obj, "name", "")).startswith(CASTING_INPUT_NAME)
        for obj in scene.objects
    )


def register_panel_previews():
    if "main" in preview_collections:
        return

    pcoll = bpy.utils.previews.new()
    mold_types_path = Path(__file__).resolve().parent / "assets" / "mold_types"
    for mold_type in MOLD_TYPES:
        preview_path = (
            mold_types_path / "picker" / mold_type.picker_filename
        )
        if not preview_path.is_file():
            preview_path = mold_types_path / mold_type.preview_filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll, mold_type.preview_name, preview_path)
        except Exception:
            pass

    settings_path = Path(__file__).resolve().parent / "assets" / "settings"
    for identifier, _label, filename, _description, _value in SLIP_CASTING_FUNNEL_OPTIONS:
        preview_path = settings_path / filename
        if preview_path.is_file():
            _load_panel_preview(pcoll, f"slip_casting_funnel_{identifier}", preview_path)
    for identifier, _label, filename, _description, _value in SLIP_CASTING_BASE_OPTIONS:
        preview_path = settings_path / filename
        if preview_path.is_file():
            _load_panel_preview(pcoll, f"slip_casting_base_{identifier}", preview_path)
    for identifier, _label, filename, _description, _value in SLIP_CASTING_MASTER_BASE_OPTIONS:
        preview_path = settings_path / filename
        if preview_path.is_file():
            _load_panel_preview(pcoll, f"slip_casting_master_base_{identifier}", preview_path)
    for identifier, _label, filename, _description, _value in SILICONE_MULTIPART_OPENING_OPTIONS:
        preview_path = settings_path / filename
        if preview_path.is_file():
            _load_panel_preview(pcoll, f"silicone_multipart_opening_{identifier}", preview_path)
    for identifier, _label, filename, _description in SHAPE_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"shape_type_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename in FUNNEL_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll, f"funnel_{identifier}", preview_path)
        except Exception:
            pass
    for identifier, _label, filename, _description in CHANNEL_ADJUSTMENTS:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"channel_adjustment_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename, _description in BASE_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"base_type_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename, _description in CASTING_BOX_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"casting_box_type_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename, _description in INNER_CAVITY_CORE_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"inner_cavity_core_type_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename, _is_fixed in MASTER_ATTACHMENT_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(pcoll,
                f"master_attachment_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for identifier, _label, filename, _description in TRAY_TYPES:
        preview_path = settings_path / filename
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(
                pcoll,
                f"tray_type_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass
    for target, (_prop_name, pin_types) in PIN_TYPE_TARGETS.items():
        for identifier, _label, filename, _description in pin_types:
            if not filename:
                continue
            preview_path = settings_path / filename
            if not preview_path.is_file():
                continue
            try:
                _load_panel_preview(pcoll,
                    f"{target.lower()}_pin_type_{identifier}",
                    str(preview_path),
                    "IMAGE",
                )
            except Exception:
                pass

    casting_feet_path = settings_path / "casting_feet_v2.png"
    if casting_feet_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "casting_feet",
                str(casting_feet_path),
                "IMAGE",
            )
        except Exception:
            pass

    casting_grip_path = settings_path / "casting_grip_v2.png"
    if casting_grip_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "casting_grip",
                str(casting_grip_path),
                "IMAGE",
            )
        except Exception:
            pass

    tray_grip_path = settings_path / "tray_grip.png"
    if tray_grip_path.is_file():
        try:
            _load_panel_preview(
                pcoll,
                "tray_grip",
                str(tray_grip_path),
                "IMAGE",
            )
        except Exception:
            pass

    tray_casting_volume_path = settings_path / "tray_casting_volume.png"
    if tray_casting_volume_path.is_file():
        try:
            _load_panel_preview(
                pcoll,
                "tray_casting_volume",
                str(tray_casting_volume_path),
                "IMAGE",
            )
        except Exception:
            pass

    casting_pilars_path = settings_path / "casting_pilars.png"
    if casting_pilars_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "casting_pilars",
                str(casting_pilars_path),
                "IMAGE",
            )
        except Exception:
            pass

    silicone_support_pilars_path = settings_path / "silicone_support_pilars.png"
    if silicone_support_pilars_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "silicone_support_pilars",
                str(silicone_support_pilars_path),
                "IMAGE",
            )
        except Exception:
            pass

    direct_top_funnel_settings_path = (
        settings_path / "direct_top_funnel_setting.png"
    )
    if direct_top_funnel_settings_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "direct_top_funnel_settings",
                str(direct_top_funnel_settings_path),
                "IMAGE",
            )
        except Exception:
            pass

    slip_casting_funnel_path = settings_path / "slip_casting_funnel_settings.png"
    if slip_casting_funnel_path.is_file():
        try:
            _load_panel_preview(
                pcoll, "slip_casting_funnel_settings", slip_casting_funnel_path
            )
        except Exception:
            logger.debug("Could not load slip casting funnel illustration", exc_info=True)

    grid_path = settings_path / "grid.png"
    if grid_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "grid",
                str(grid_path),
                "IMAGE",
            )
        except Exception:
            pass

    hollow_path = settings_path / "hollow.png"
    if hollow_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "hollow",
                str(hollow_path),
                "IMAGE",
            )
        except Exception:
            pass

    convert_to_planter_path = settings_path / "convert_to_planter.png"
    if convert_to_planter_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "convert_to_planter",
                str(convert_to_planter_path),
                "IMAGE",
            )
        except Exception:
            pass

    casting_sprue_path = settings_path / "casting_sprue_.png"
    if casting_sprue_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "casting_sprue",
                str(casting_sprue_path),
                "IMAGE",
            )
        except Exception:
            pass

    watermark_reference_path = settings_path / "watermark_reference_olive.png"
    if watermark_reference_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "watermark_reference",
                str(watermark_reference_path),
                "IMAGE",
            )
        except Exception:
            pass

    master_smart_sealer_path = (
        Path(__file__).resolve().parent
        / "assets"
        / "tools"
        / "master_smart_sealer_olive_cropped.png"
    )
    if master_smart_sealer_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "master_smart_sealer",
                str(master_smart_sealer_path),
                "IMAGE",
            )
        except Exception:
            pass

    master_air_trap_pillars_path = (
        Path(__file__).resolve().parent
        / "assets"
        / "tools"
        / "master_air_trap_pillars_olive.png"
    )
    if master_air_trap_pillars_path.is_file():
        try:
            _load_panel_preview(
                pcoll,
                "master_air_trap_pillars",
                str(master_air_trap_pillars_path),
                "IMAGE",
            )
        except Exception:
            pass

    utility_preview_paths = {
        "hollow": settings_path / "hollow_utility_cropped.png",
        "convert_to_planter": (
            settings_path / "convert_to_planter_utility_cropped.png"
        ),
        "grid": settings_path / "grid_utility_square.png",
        "casting_sprue": settings_path / "casting_sprue_utility_cropped.png",
        "master_smart_sealer": (
            Path(__file__).resolve().parent
            / "assets"
            / "tools"
            / "master_smart_sealer_olive_utility_cropped.png"
        ),
        "master_air_trap_pillars": (
            Path(__file__).resolve().parent
            / "assets"
            / "tools"
            / "master_air_trap_pillars_undercut_islands_olive.png"
        ),
        "foundation": (
            Path(__file__).resolve().parent
            / "assets"
            / "tools"
            / "foundation_utility_cropped.png"
        ),
        "watermark_reference": (
            settings_path / "watermark_reference_olive_utility_cropped.png"
        ),
    }
    for identifier, preview_path in utility_preview_paths.items():
        if not preview_path.is_file():
            continue
        try:
            _load_panel_preview(
                pcoll,
                f"utility_{identifier}",
                str(preview_path),
                "IMAGE",
            )
        except Exception:
            pass

    clear_undercuts_path = (
        Path(__file__).resolve().parent
        / "assets"
        / "tools"
        / "clear_undercuts_v2.png"
    )
    if clear_undercuts_path.is_file():
        try:
            _load_panel_preview(pcoll,
                "clear_undercuts",
                str(clear_undercuts_path),
                "IMAGE",
            )
        except Exception:
            pass
    preview_collections["main"] = pcoll


def unregister_panel_previews():
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _process_pending_detected_imports
    ):
        bpy.app.timers.unregister(_process_pending_detected_imports)
    _pending_detected_import_objects.clear()
    _accepted_detected_import_pointers.clear()

    pcoll = preview_collections.pop("main", None)
    if pcoll is None:
        return

    try:
        bpy.utils.previews.remove(pcoll)
    except Exception:
        pass
    _panel_preview_paths.clear()


def _is_mold_system_finished(scene, is_direct_mold):
    selected_type = getattr(scene, "mold_type_preview", "")
    if selected_type == "FIXTURE":
        return any(
            obj.name in {"fixture", "box"}
            or obj.name.lower().startswith("box_part_")
            for obj in scene.objects
        )
    if selected_type == "PROTECTIVE_SHELL":
        return any(
            bool(
                getattr(obj, "get", lambda *_args: False)(
                    "moldboxer_protective_shell",
                    False,
                )
            )
            for obj in scene.objects
        )
    if is_direct_mold:
        return any(
            obj.name.lower().startswith(
                ("box_part_", "left_box", "right_box", "box_l", "box_r")
            )
            for obj in scene.objects
        )

    if is_multipart_type(selected_type) or selected_type == "ADAPTED_BOX":
        if any(
            obj.name.lower() == "plaster_mold"
            or obj.name.lower().startswith("plaster_mold_part_")
            for obj in scene.objects
        ):
            return True

    if getattr(scene, "pro_two_part_silicone", False):
        return all(
            scene.objects.get(name) is not None
            for name in ("left_silicone_mold", "right_silicone_mold")
        )

    return scene.objects.get("silicone_mold") is not None or any(
        obj.name.startswith("silicone_mold_part_") for obj in scene.objects
    )


def _draw_slip_casting_primary_actions(primary, context, mold_type):
    """Draw the staged primary actions for Slip Casting."""

    scene = context.scene
    has_built_box = any(
        scene.objects.get(name) is not None
        for name in ("box", "left_box", "right_box")
    )
    if has_built_box:
        confirm_action = mold_type.advanced_actions[-1]
        primary.operator(
            confirm_action.operator,
            text=t(confirm_action.label),
            icon=confirm_action.icon,
        )
        return

    if not slip_casting_initial_stage_complete(scene):
        primary.operator(
            "silicone.detect_slip_casting_cores",
            text=t("Prepare Casting"),
            icon="VIEWZOOM",
        )
        return

    if is_silicone_multipart_type(mold_type.identifier) and scene.mold_advanced_mode:
        primary.operator("silicone.build_slip_casting_box", text=t("Build Box"), icon="MOD_LINEART")
        return

    primary.operator(
        "silicone.generate_mold",
        text=t("Generate Mold"),
        icon="LIGHT",
    )


def draw_view3d_primary_header_controls(self, context):
    layout = self.layout
    update_available, update_version = get_extension_update_status()
    if update_available:
        update = layout.row(align=True)
        update.alert = True
        update.scale_y = 1.35
        update.operator(
            "silicone.update_available_dialog",
            text=(
                f"{t('Update Required')} ({update_version})"
                if update_version
                else t("Update Required")
            ),
            icon="ERROR",
        )

    mold_type = get_mold_type(context.scene.mold_type_preview)
    is_direct_mold = is_direct_mold_type(context.scene)
    has_model_object = scene_has_model_object(context.scene)
    has_casting_input = scene_has_casting_input(context.scene)
    mold_system_finished = _is_mold_system_finished(
        context.scene,
        is_direct_mold,
    )
    foundation_active = foundation_reference_guide_active(context.scene)

    actions = layout.row(align=True)
    actions.scale_y = 1.35
    actions.operator("silicone.new_project", text=t("New"), icon="FILE_NEW")
    if has_model_object:
        actions.operator(
            "silicone.restart",
            text=t("Restart"),
            icon="FILE_REFRESH",
        )

    layout.separator_spacer()
    primary = layout.row(align=True)
    primary.scale_x = 1.25
    primary.scale_y = 1.45
    try:
        primary.emboss = "MOLDBOXER_PRIMARY"
    except (TypeError, ValueError):
        # Stock Blender does not expose the Moldboxer source-patch style.
        pass
    if not isinstance(layout, _ActionBarLayoutRecorder):
        # New, Restart, and Account stay in the native header. Only this
        # contextual workflow group moves into the viewport action bar.
        primary = _SuppressedActionLayout()
    if foundation_active:
        primary.operator(
            "silicone.confirm_foundation",
            text=t("Confirm Foundation"),
            icon="CHECKMARK",
        )
    elif has_casting_input:
        primary.operator(
            "silicone.confirm_casting_input",
            text=t("Confirm"),
            icon="CHECKMARK",
        )
    elif scene_has_master_air_trap_pillars(context):
        primary.operator(
            "silicone.confirm_master_air_trap_pillars",
            text=t("Confirm Air Trap Pillars"),
            icon="CHECKMARK",
        )
    elif scene_has_master_filler_objects(context):
        primary.operator(
            "silicone.confirm_master_filler",
            text=t("Confirm"),
            icon="CHECKMARK",
        )
        primary.operator(
            "silicone.remove_master_filler_type",
            text=t("Bulk Remove"),
            icon="TRASH",
        )
        primary.operator(
            "silicone.fill_master_base",
            text=t("Fill to Base"),
            icon="MOD_BOOLEAN",
        )
    elif mold_system_finished:
        if not is_silicone_multipart_type(context.scene.mold_type_preview) and any(
            obj.name == "plaster_mold" or obj.name.startswith("plaster_mold_part_")
            for obj in context.scene.objects
        ):
            primary.operator(
                "silicone.generate_plaster_silicone_molds",
                text=t("Generate Silicone Mold"),
                icon="MOD_CAST",
            )
        export_operator = primary.operator(
            "silicone.export_stl",
            text=t("Export"),
            icon="EXPORT",
        )
        export_operator.file_format = "STL"
    elif not has_model_object:
        primary.operator(
            "silicone.import_model",
            text=t("Import"),
            icon="IMPORT",
        )
    else:
        if is_multipart_type(mold_type.identifier):
            _draw_slip_casting_primary_actions(primary, context, mold_type)
        elif mold_type.identifier == "DIRECT_MOLD_SKIN":
            skin_core_generated = scene_has_skin_core(context.scene)
            skin_core = context.scene.objects.get("skin_core")
            skin_core_confirmed = bool(
                skin_core_generated
                and getattr(skin_core, "get", lambda *_: False)(
                    "moldboxer_skin_core_confirmed",
                    False,
                )
            )
            advanced_mode = bool(
                mold_type.advanced_actions
                and not is_lite_tier()
                and context.scene.mold_advanced_mode
            )
            has_built_box = context.scene.objects.get("box") is not None
            if advanced_mode and skin_core_generated:
                primary.operator(
                    (
                        "silicone.confirm_direct_mold"
                        if has_built_box
                        else "silicone.build_direct_mold"
                    ),
                    text=t("Confirm"),
                    icon="CHECKMARK",
                )
            else:
                primary.operator(
                    "silicone.generate_mold",
                    text=(
                        t("Generate Mold")
                        if skin_core_confirmed
                        else (
                            t("Confirm")
                            if skin_core_generated
                            else t("Generate Core")
                        )
                    ),
                    icon=(
                        "LIGHT"
                        if skin_core_confirmed or not skin_core_generated
                        else "CHECKMARK"
                    ),
                )
            if skin_core_generated:
                primary.operator(
                    "silicone.restart",
                    text=t("Undo"),
                    icon="LOOP_BACK",
                )
        else:
            advanced_mode = (
                bool(mold_type.advanced_actions)
                and not is_lite_tier()
                and context.scene.mold_advanced_mode
            )
            if advanced_mode:
                has_built_box = any(
                    context.scene.objects.get(name) is not None
                    for name in ("box", "left_box", "right_box")
                )
                action_index = 1 if has_built_box else 0
                action = mold_type.advanced_actions[action_index]
                primary.operator(
                    action.operator,
                    text=t(action.label),
                    icon=action.icon,
                )
            else:
                if mold_type.identifier == "FIXTURE":
                    primary.operator(
                        "silicone.generate_mold",
                        text=t("Generate Fixture"),
                        icon="LIGHT",
                    )
                elif mold_type.identifier == "PROTECTIVE_SHELL":
                    primary.operator(
                        "silicone.generate_mold",
                        text=t("Generate Protective Shell"),
                        icon="LIGHT",
                    )
                else:
                    primary.operator(
                        "silicone.generate_mold",
                        text=t("Generate Mold"),
                        icon="LIGHT",
                    )
    layout.separator_spacer()
    account = layout.row(align=True)
    account.alignment = "RIGHT"
    account.scale_y = 1.35
    account.operator("silicone.account_dialog", text=t("Account"), icon="USER")


def draw_moldboxer_topbar_controls(self, context):
    """Place persistent Moldboxer actions in the compact application top bar."""
    layout = self.layout
    alignment = str(getattr(getattr(context, "region", None), "alignment", ""))

    if alignment == "RIGHT":
        account = layout.row(align=True)
        overlay = next(
            (
                getattr(getattr(area, "spaces", None), "active", None).overlay
                for area in getattr(getattr(context, "screen", None), "areas", ())
                if getattr(area, "type", "") == "VIEW_3D"
                and hasattr(
                    getattr(getattr(area, "spaces", None), "active", None),
                    "overlay",
                )
            ),
            None,
        )
        if overlay is not None and hasattr(overlay, "show_overlays"):
            account.operator(
                "silicone.toggle_viewport_overlays",
                text=t("Overlay"),
                icon="OVERLAY",
            )
        account.operator(
            "silicone.account_dialog",
            text=t("Account"),
            icon="USER",
        )
        return

    layout.separator()
    actions = layout.row(align=True)
    actions.operator(
        "silicone.new_project",
        text=t("New"),
        icon="FILE_NEW",
    )
    if scene_has_model_object(context.scene):
        actions.operator(
            "silicone.restart",
            text=t("Restart"),
            icon="FILE_REFRESH",
        )
        actions.operator(
            "ed.undo",
            text=t("Undo"),
            icon="LOOP_BACK",
        )

    # Blender's top bar gives expansion to the trailing spacer only. Reserve
    # the matching lead-in explicitly so this wide command group is visually
    # centered between the persistent controls at both corners.
    layout.separator(factor=16.0)
    _draw_viewport_tool_and_util_controls(layout, context)
    layout.separator_spacer()


def draw_moldboxer_topbar(self, context):
    """Draw Blender's top bar without the workspace selector and add button."""
    alignment = str(getattr(getattr(context, "region", None), "alignment", ""))
    if alignment == "RIGHT":
        if _ORIGINAL_TOPBAR_HEADER_DRAW is not None:
            _ORIGINAL_TOPBAR_HEADER_DRAW(self, context)
        return

    layout = self.layout
    from bl_ui.space_topbar import TOPBAR_MT_editor_menus

    TOPBAR_MT_editor_menus.draw_collapsible(context, layout)
    if bool(getattr(getattr(context, "screen", None), "show_fullscreen", False)):
        layout.operator(
            "screen.back_to_previous",
            icon="SCREEN_BACK",
            text=t("Back to Previous"),
        )


def draw_moldboxer_viewport_tools_header(self, context):
    """Keep the now-unused native viewport header visually empty."""
    del self, context


def _draw_viewport_tool_and_util_controls(layout, context):
    """Draw the centered Moldboxer command strip in the application header."""
    tool_actions = build_viewport_tool_actions(context)
    utils_actions = build_viewport_utils_actions(context)
    controls = layout.grid_flow(
        row_major=True,
        columns=len(tool_actions) + len(utils_actions),
        even_columns=True,
        even_rows=True,
        align=True,
    )
    for action in tool_actions:
        operator = controls.operator(
            action["operator"],
            text=action["label"],
            icon=action["icon"],
            depress=bool(action["active"]),
        )
        operator.tool_id = action["tool_id"]

    for action in utils_actions:
        utility = controls.row(align=True)
        utility.enabled = _action_bar_operator_enabled(action)
        operator = utility.operator(
            SILICONE_OT_run_viewport_utility.bl_idname,
            text=action["label"],
            icon=action["icon"],
        )
        operator.operator_id = action["operator"]


class _ActionBarOperatorProperties:
    def __init__(self, action):
        object.__setattr__(self, "_action", action)

    def __setattr__(self, name, value):
        self._action["properties"][name] = value


class _ActionBarLayoutRecorder:
    """Small UILayout recorder that lets the overlay reuse the header workflow."""

    def __init__(self, actions=None, group=0):
        self.actions = actions if actions is not None else []
        self.group = group
        self.alert = False
        self.alignment = "EXPAND"
        self.scale_x = 1.0

    def row(self, align=False):
        del align
        return _ActionBarLayoutRecorder(self.actions, len(self.actions) + 1)

    def separator_spacer(self):
        return None

    def operator(self, operator, text="", icon="NONE"):
        del icon
        style = "secondary"
        placement = "left"
        if self.alert:
            style = "warning"
            placement = "right"
        elif self.scale_x > 1.0:
            style = "primary"
            placement = "center"
        elif self.alignment == "RIGHT":
            placement = "right"
        action = {
            "operator": operator,
            "label": text,
            "group": self.group,
            "style": style,
            "placement": placement,
            "properties": {},
        }
        self.actions.append(action)
        return _ActionBarOperatorProperties(action)


class _ActionBarHeaderProxy:
    def __init__(self, layout):
        self.layout = layout


def build_viewport_action_bar_actions(context):
    recorder = _ActionBarLayoutRecorder()
    draw_view3d_primary_header_controls(
        _ActionBarHeaderProxy(recorder),
        context,
    )
    return [
        action
        for action in recorder.actions
        if action["placement"] == "center"
    ]


def _resolve_action_bar_operator(action):
    try:
        namespace, operator_name = action["operator"].split(".", 1)
        return getattr(getattr(bpy.ops, namespace), operator_name)
    except (AttributeError, KeyError, ValueError):
        return None


def _action_bar_operator_enabled(action):
    operator = _resolve_action_bar_operator(action)
    if operator is None:
        return False
    try:
        return bool(operator.poll())
    except Exception:
        return False


def _get_action_bar_horizontal_bounds(context, region, side_margin):
    region_x = int(getattr(region, "x", 0) or 0)
    region_width = int(getattr(region, "width", 0) or 0)
    left_bound = side_margin
    right_bound = max(left_bound + 1, region_width - side_margin)
    area = getattr(context, "area", None)
    for side_region in getattr(area, "regions", ()) if area is not None else ():
        side_type = getattr(side_region, "type", "")
        side_width = int(getattr(side_region, "width", 0) or 0)
        if side_width <= 1:
            continue
        side_x = int(getattr(side_region, "x", 0) or 0)
        side_alignment = str(getattr(side_region, "alignment", ""))
        if side_alignment == "LEFT" or (
            not side_alignment and side_type == "TOOLS"
        ):
            left_bound = max(
                left_bound,
                side_x + side_width - region_x + side_margin,
            )
        elif side_alignment == "RIGHT" or (
            not side_alignment and side_type == "UI"
        ):
            right_bound = min(
                right_bound,
                side_x - region_x - side_margin,
            )
    return left_bound, max(left_bound + 1, right_bound)


def _compact_action_bar_dimension_value(value):
    """Render ``X × Y × Z mm`` compactly without needless decimal zeros."""
    rendered = str(value)
    if not rendered.endswith(" mm") or " × " not in rendered:
        return rendered
    components = rendered[:-3].split(" × ")
    try:
        compact_components = [f"{float(component):g}" for component in components]
    except ValueError:
        return rendered
    return f'{"×".join(compact_components)} mm'


def _compact_action_bar_metrics_row(metrics_row, max_width):
    """Fit estimates horizontally while preserving their metric values."""
    import blf  # type: ignore

    if not metrics_row["items"] or metrics_row["width"] <= max_width:
        return metrics_row

    compact_items = []
    for kind, metrics_layout in metrics_row["items"]:
        if kind != "metrics":
            compact_items.append((kind, metrics_layout))
            continue

        compact_layout = dict(metrics_layout)
        font_id = compact_layout["font_id"]
        blf.size(font_id, compact_layout["font_size"])
        # Imperial estimates are secondary, so remove them before taking
        # width away from the primary workflow action.
        original_lines = compact_layout["lines"]
        compact_lines = [
            (
                str(label),
                _compact_action_bar_dimension_value(
                    str(value).split("  ·  ", 1)[0]
                ),
            )
            for label, value in original_lines
        ]
        padding = compact_layout["padding"]
        column_gap = compact_layout["column_gap"]
        dimension_rows = {
            index
            for index, (_label, value) in enumerate(original_lines)
            if " × " in str(value) and str(value).endswith(" mm")
        }
        non_dimension_width = max(
            (
                int(blf.dimensions(font_id, value)[0])
                for index, (_label, value) in enumerate(compact_lines)
                if index not in dimension_rows
            ),
            default=0,
        )
        minimum_label_width = int(blf.dimensions(font_id, "…")[0])
        dimension_value_budget = max(
            non_dimension_width,
            int(max_width)
            - (padding * 2)
            - column_gap
            - minimum_label_width,
        )
        compact_lines = [
            (
                label,
                (
                    _truncate_action_bar_label(value, dimension_value_budget)
                    if index in dimension_rows
                    else value
                ),
            )
            for index, (label, value) in enumerate(compact_lines)
        ]
        value_width = max(
            int(blf.dimensions(font_id, value)[0])
            for _label, value in compact_lines
        )
        label_budget = max(
            0,
            int(max_width) - (padding * 2) - column_gap - value_width,
        )
        if label_budget <= 0:
            column_gap = 0
            compact_lines = [("", value) for _label, value in compact_lines]
        else:
            compact_lines = [
                (_truncate_action_bar_label(label, label_budget), value)
                for label, value in compact_lines
            ]
        label_width = max(
            (
                int(blf.dimensions(font_id, label)[0])
                for label, _value in compact_lines
            ),
            default=0,
        )
        compact_layout.update(
            {
                "lines": compact_lines,
                "column_gap": column_gap,
                "label_width": label_width,
                "width": (
                    (padding * 2)
                    + label_width
                    + column_gap
                    + value_width
                ),
            }
        )
        compact_items.append((kind, compact_layout))

    compact_row = dict(metrics_row)
    compact_row["items"] = compact_items
    compact_row["width"] = sum(
        layout["width"] for _kind, layout in compact_items
    ) + (metrics_row["gap"] * max(0, len(compact_items) - 1))
    return compact_row


def _fit_action_bar_button_widths(
    preferred_widths,
    full_label_widths,
    available_width,
    button_gap,
):
    """Shrink later actions first and keep the leading action readable."""
    widths = list(preferred_widths)
    usable_width = max(
        1,
        int(available_width) - (button_gap * max(0, len(widths) - 1)),
    )
    excess = max(0, sum(widths) - usable_width)
    if not excess:
        return widths

    for index in reversed(range(len(widths))):
        reducible = max(0, widths[index] - full_label_widths[index])
        reduction = min(excess, reducible)
        widths[index] -= reduction
        excess -= reduction
    for index in reversed(range(1, len(widths))):
        reducible = max(0, widths[index] - 1)
        reduction = min(excess, reducible)
        widths[index] -= reduction
        excess -= reduction
    if excess:
        widths[0] = max(1, widths[0] - excess)
    return widths


def _wrap_action_bar_instruction_text(title, max_width):
    """Wrap instruction copy at word boundaries, with character fallback."""
    import blf  # type: ignore

    remaining = " ".join(str(title).split())
    if not remaining or max_width <= 0:
        return []

    lines = []
    while remaining:
        if blf.dimensions(_ACTION_BAR_FONT_ID, remaining)[0] <= max_width:
            lines.append(remaining)
            break

        fit_length = 0
        for index in range(1, len(remaining) + 1):
            candidate = remaining[:index]
            if blf.dimensions(_ACTION_BAR_FONT_ID, candidate)[0] > max_width:
                break
            fit_length = index
        fit_length = max(1, fit_length)
        candidate = remaining[:fit_length]
        word_break = candidate.rfind(" ")
        if word_break > 0:
            lines.append(candidate[:word_break].rstrip())
            remaining = remaining[word_break + 1 :].lstrip()
        else:
            lines.append(candidate.rstrip())
            remaining = remaining[fit_length:].lstrip()
    return lines


def _fit_action_bar_instruction_text(
    title,
    max_width,
    preferred_font_size,
    minimum_font_size,
    line_gap,
):
    """Fit the instruction into at most three lines before truncating it."""
    import blf  # type: ignore

    preferred_font_size = max(1, int(preferred_font_size))
    minimum_font_size = min(
        preferred_font_size,
        max(1, int(minimum_font_size)),
    )
    lines = []
    font_size = preferred_font_size
    for candidate_size in range(
        preferred_font_size,
        minimum_font_size - 1,
        -1,
    ):
        blf.size(_ACTION_BAR_FONT_ID, candidate_size)
        candidate_lines = _wrap_action_bar_instruction_text(title, max_width)
        lines = candidate_lines
        font_size = candidate_size
        if len(candidate_lines) <= _ACTION_BAR_TITLE_MAX_LINES:
            break

    if len(lines) > _ACTION_BAR_TITLE_MAX_LINES:
        lines = lines[:_ACTION_BAR_TITLE_MAX_LINES]
        lines[-1] = _truncate_action_bar_label(
            lines[-1].rstrip() + "…",
            max_width,
        )

    blf.size(_ACTION_BAR_FONT_ID, font_size)
    line_height = max(
        1,
        int(blf.dimensions(_ACTION_BAR_FONT_ID, "Ag")[1]),
    )
    line_step = line_height + max(0, int(line_gap))
    return {
        "lines": lines,
        "font_size": font_size,
        "line_height": line_height,
        "line_step": line_step,
        "height": line_height + (line_step * max(0, len(lines) - 1)),
    }


def _get_viewport_action_bar_layout(context, region):
    import blf  # type: ignore

    region_width = int(getattr(region, "width", 0) or 0)
    region_height = int(getattr(region, "height", 0) or 0)
    instruction = get_viewport_workflow_instruction(context)
    actions = build_viewport_action_bar_actions(context)
    if (
        region_width <= 0
        or region_height <= 0
        or instruction is None
        or not actions
    ):
        return None

    title, _body = instruction
    ui_scale = _get_overlay_ui_scale(context)
    button_font_size = _scale_overlay_value(_ACTION_BAR_FONT_SIZE, ui_scale)
    title_font_size = _scale_overlay_value(
        _ACTION_BAR_TITLE_FONT_SIZE,
        ui_scale,
    )
    title_min_font_size = _scale_overlay_value(
        _ACTION_BAR_TITLE_MIN_FONT_SIZE,
        ui_scale,
    )
    title_line_gap = _scale_overlay_value(
        _ACTION_BAR_TITLE_LINE_GAP,
        ui_scale,
    )
    button_height = _scale_overlay_value(_ACTION_BAR_BUTTON_HEIGHT, ui_scale)
    button_width = _scale_overlay_value(
        _ACTION_BAR_BUTTON_WIDTH,
        ui_scale,
    )
    button_padding_x = _scale_overlay_value(
        _ACTION_BAR_BUTTON_PADDING_X,
        ui_scale,
    )
    button_gap = _scale_overlay_value(_ACTION_BAR_BUTTON_GAP, ui_scale)
    group_gap = _scale_overlay_value(_ACTION_BAR_GROUP_GAP, ui_scale)
    panel_padding = _scale_overlay_value(_ACTION_BAR_PANEL_PADDING, ui_scale)
    accent_width = _scale_overlay_value(_ACTION_BAR_ACCENT_WIDTH, ui_scale)
    accent_gap = _scale_overlay_value(_ACTION_BAR_ACCENT_GAP, ui_scale)
    bottom_margin = _scale_overlay_value(_ACTION_BAR_BOTTOM_MARGIN, ui_scale)
    corner_radius = _scale_overlay_value(_ACTION_BAR_CORNER_RADIUS, ui_scale)

    side_margin = _scale_overlay_value(12, ui_scale)
    left_bound, right_bound = _get_action_bar_horizontal_bounds(
        context,
        region,
        side_margin,
    )
    visible_width = max(1, right_bound - left_bound)
    metrics_row = get_viewport_info_overlay_row_layout(context)
    max_panel_width = min(visible_width, _scale_overlay_value(860, ui_scale))
    max_content_width = max(1, max_panel_width - (panel_padding * 2))

    blf.size(_ACTION_BAR_FONT_ID, button_font_size)
    display_labels = [
        (
            f'{action["label"]}  →'
            if action["style"] == "primary"
            else action["label"]
        )
        for action in actions
    ]
    minimum_button_width = _scale_overlay_value(54, ui_scale)
    full_label_button_widths = [
        max(
            minimum_button_width,
            int(math.ceil(blf.dimensions(_ACTION_BAR_FONT_ID, label)[0]))
            + (button_padding_x * 2),
        )
        for label in display_labels
    ]
    button_widths = [
        max(button_width, full_label_width)
        for full_label_width in full_label_button_widths
    ]
    button_group_width = sum(button_widths) + (
        button_gap * max(0, len(button_widths) - 1)
    )
    blf.size(_ACTION_BAR_FONT_ID, title_font_size)
    title_width = int(blf.dimensions(_ACTION_BAR_FONT_ID, title)[0])
    group_count = int(bool(metrics_row["items"])) + 2
    gap_width = group_gap * max(0, group_count - 1)
    minimum_button_group_width = (
        sum(full_label_button_widths)
        + button_gap * max(0, len(button_widths) - 1)
    )
    metrics_width_budget = max(
        0,
        max_content_width
        - accent_width
        - accent_gap
        - gap_width
        - minimum_button_group_width,
    )
    metrics_row = _compact_action_bar_metrics_row(
        metrics_row,
        metrics_width_budget,
    )
    metrics_items = list(metrics_row["items"])
    metrics_width = metrics_row["width"] if metrics_items else 0
    metrics_height = metrics_row["height"] if metrics_items else 0
    available_status_width = max(
        0,
        max_content_width
        - metrics_width
        - accent_width
        - accent_gap
        - gap_width
        - minimum_button_group_width,
    )
    status_width = min(
        title_width,
        _scale_overlay_value(_ACTION_BAR_STATUS_MAX_WIDTH, ui_scale),
        available_status_width,
    )
    instruction_text = _fit_action_bar_instruction_text(
        title,
        status_width,
        title_font_size,
        title_min_font_size,
        title_line_gap,
    )
    title_height = instruction_text["height"]
    fixed_width = (
        metrics_width
        + accent_width
        + accent_gap
        + status_width
        + gap_width
    )
    available_button_width = max(1, max_content_width - fixed_width)
    if button_group_width > available_button_width:
        button_widths = _fit_action_bar_button_widths(
            button_widths,
            full_label_button_widths,
            available_button_width,
            button_gap,
        )
        button_group_width = sum(button_widths) + (
            button_gap * max(0, len(button_widths) - 1)
        )

    content_width = fixed_width + button_group_width
    panel_width = min(max_panel_width, (panel_padding * 2) + content_width)
    panel_height = (panel_padding * 2) + max(
        button_height,
        metrics_height,
        title_height,
    )
    panel_x = max(left_bound, right_bound - panel_width)
    panel_y = max(
        0,
        min(bottom_margin, region_height - panel_height),
    )

    content_x = panel_x + panel_padding
    cursor_x = content_x
    metrics = []
    for kind, metrics_layout in metrics_items:
        metrics.append(
            {
                "kind": kind,
                "layout": metrics_layout,
                "x": cursor_x,
                "y": panel_y + ((panel_height - metrics_layout["height"]) / 2),
            }
        )
        cursor_x += metrics_layout["width"] + metrics_row["gap"]
    if metrics_items:
        cursor_x = content_x + metrics_width + group_gap

    status_x = cursor_x
    title_x = status_x + accent_width + accent_gap
    title_y = (
        panel_y
        + ((panel_height - title_height) / 2)
        + title_height
        - instruction_text["line_height"]
    )
    cursor_x = status_x + accent_width + accent_gap + status_width + group_gap
    button_y = panel_y + ((panel_height - button_height) / 2)
    buttons = []
    for index, action in enumerate(actions):
        if index:
            cursor_x += button_gap
        width = button_widths[index]
        buttons.append(
            {
                "action": action,
                "x": cursor_x,
                "y": button_y,
                "width": width,
                "height": button_height,
                "enabled": _action_bar_operator_enabled(action),
                "display_label": display_labels[index],
            }
        )
        cursor_x += width

    return {
        "panels": [
            {
                "x": panel_x,
                "y": panel_y,
                "width": panel_width,
                "height": panel_height,
            }
        ],
        "instruction": {
            "title": title,
            "title_lines": instruction_text["lines"],
            "x": title_x,
            "title_y": title_y,
            "title_font_size": instruction_text["font_size"],
            "title_line_step": instruction_text["line_step"],
            "max_width": status_width,
            "accent_x": status_x,
            "accent_y": panel_y + panel_padding,
            "accent_width": accent_width,
            "accent_height": panel_height - (panel_padding * 2),
        },
        "metrics": metrics,
        "font_size": button_font_size,
        "padding_x": button_padding_x,
        "corner_radius": corner_radius,
        "buttons": buttons,
    }


def _truncate_action_bar_label(label, max_width):
    import blf  # type: ignore

    if blf.dimensions(_ACTION_BAR_FONT_ID, label)[0] <= max_width:
        return label
    candidate = label
    while candidate:
        candidate = candidate[:-1]
        shortened = candidate.rstrip() + "…"
        if blf.dimensions(_ACTION_BAR_FONT_ID, shortened)[0] <= max_width:
            return shortened
    return "…"


def _draw_viewport_action_bar():
    import blf  # type: ignore

    context = bpy.context
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    if (
        region is None
        or area is None
        or getattr(region, "type", "") != "WINDOW"
        or getattr(area, "type", "") != "VIEW_3D"
    ):
        return
    # Keep the transform editor in the same proven overlay pass as the main
    # instruction/action card. A second SpaceView3D handler can be lost during
    # extension hot reloads even though Blender still returns a valid handle.
    _draw_viewport_transform_panel()
    layout = _get_viewport_action_bar_layout(context, region)
    if layout is None:
        return

    corner_radius = layout["corner_radius"]
    for panel in layout["panels"]:
        _draw_overlay_background(
            panel["x"],
            panel["y"],
            panel["width"],
            panel["height"],
            color=_ACTION_BAR_PANEL_COLOR,
            corner_radius=corner_radius,
            border_color=_ACTION_BAR_PANEL_BORDER_COLOR,
            border_width=1,
        )
    instruction = layout["instruction"]
    _draw_overlay_background(
        instruction["accent_x"],
        instruction["accent_y"],
        instruction["accent_width"],
        instruction["accent_height"],
        color=_ACTION_BAR_PRIMARY_BORDER_COLOR,
        corner_radius=max(1, instruction["accent_width"] // 2),
    )
    for metrics in layout["metrics"]:
        metrics_layout = metrics["layout"]
        font_id = metrics_layout["font_id"]
        blf.size(font_id, metrics_layout["font_size"])
        label_x = metrics["x"] + metrics_layout["padding"]
        value_x = (
            label_x
            + metrics_layout["label_width"]
            + metrics_layout["column_gap"]
        )
        baseline_y = (
            metrics["y"]
            + metrics_layout["height"]
            - metrics_layout["padding"]
            - metrics_layout["text_height"]
        )
        for index, (label, value) in enumerate(metrics_layout["lines"]):
            line_y = baseline_y - (index * metrics_layout["line_step"])
            blf.color(font_id, *_ACTION_BAR_BODY_TEXT_COLOR)
            blf.position(font_id, label_x, line_y, 0)
            blf.draw(font_id, label)
            blf.color(font_id, *_ACTION_BAR_TEXT_COLOR)
            blf.position(font_id, value_x, line_y, 0)
            blf.draw(font_id, value)
    if instruction["max_width"] > 0:
        blf.size(_ACTION_BAR_FONT_ID, instruction["title_font_size"])
        blf.color(_ACTION_BAR_FONT_ID, *_ACTION_BAR_TEXT_COLOR)
        for index, title_line in enumerate(instruction["title_lines"]):
            blf.position(
                _ACTION_BAR_FONT_ID,
                instruction["x"],
                instruction["title_y"]
                - (index * instruction["title_line_step"]),
                0,
            )
            blf.draw(_ACTION_BAR_FONT_ID, title_line)
    blf.size(_ACTION_BAR_FONT_ID, layout["font_size"])
    text_height = max(1, int(blf.dimensions(_ACTION_BAR_FONT_ID, "Ag")[1]))
    for button in layout["buttons"]:
        action = button["action"]
        if not button["enabled"]:
            fill_color = _ACTION_BAR_DISABLED_COLOR
            border_color = _ACTION_BAR_SECONDARY_BORDER_COLOR
            text_color = _ACTION_BAR_DISABLED_TEXT_COLOR
        elif action["style"] == "primary":
            fill_color = _ACTION_BAR_PRIMARY_COLOR
            border_color = _ACTION_BAR_PRIMARY_BORDER_COLOR
            text_color = _ACTION_BAR_TEXT_COLOR
        elif action["style"] == "warning":
            fill_color = _ACTION_BAR_WARNING_COLOR
            border_color = _ACTION_BAR_WARNING_BORDER_COLOR
            text_color = _ACTION_BAR_TEXT_COLOR
        else:
            fill_color = _ACTION_BAR_SECONDARY_COLOR
            border_color = _ACTION_BAR_SECONDARY_BORDER_COLOR
            text_color = _ACTION_BAR_TEXT_COLOR
        _draw_overlay_background(
            button["x"],
            button["y"],
            button["width"],
            button["height"],
            color=fill_color,
            corner_radius=corner_radius,
            border_color=border_color,
            border_width=1,
        )
        max_text_width = max(1, button["width"] - (layout["padding_x"] * 2))
        label = _truncate_action_bar_label(
            button["display_label"],
            max_text_width,
        )
        text_width = int(blf.dimensions(_ACTION_BAR_FONT_ID, label)[0])
        blf.color(_ACTION_BAR_FONT_ID, *text_color)
        blf.position(
            _ACTION_BAR_FONT_ID,
            button["x"] + ((button["width"] - text_width) / 2),
            button["y"] + ((button["height"] - text_height) / 2),
            0,
        )
        blf.draw(_ACTION_BAR_FONT_ID, label)


def _active_viewport_tool_id(context):
    workspace = getattr(context, "workspace", None)
    tools = getattr(workspace, "tools", None)
    if tools is None:
        return ""
    try:
        active_tool = tools.from_space_view3d_mode(
            getattr(context, "mode", "OBJECT"),
            create=False,
        )
    except Exception:
        return ""
    return str(getattr(active_tool, "idname", "") or "")


def _view3d_area_and_window_region(context):
    area = getattr(context, "area", None)
    if getattr(area, "type", "") != "VIEW_3D":
        area = next(
            (
                candidate
                for candidate in getattr(
                    getattr(context, "screen", None),
                    "areas",
                    (),
                )
                if getattr(candidate, "type", "") == "VIEW_3D"
            ),
            None,
        )
    window_region = next(
        (
            region
            for region in getattr(area, "regions", ())
            if getattr(region, "type", "") == "WINDOW"
        ),
        None,
    )
    return area, window_region


def _set_active_viewport_tool(context, tool_id):
    area, window_region = _view3d_area_and_window_region(context)
    if area is None or window_region is None or not tool_id:
        return False
    try:
        with context.temp_override(area=area, region=window_region):
            result = bpy.ops.wm.tool_set_by_id(
                "EXEC_DEFAULT",
                name=tool_id,
            )
    except (AttributeError, RuntimeError, TypeError):
        return False
    if "FINISHED" not in result:
        return False
    ensure_moldboxer_transform_gizmos_for_selection(context)
    if tool_id == "builtin.measure":
        # Blender's ruler is implemented as an active-tool gizmo. Moldboxer's
        # selection sync may hide active-tool gizmos when an object uses the
        # contextual rotation controls, which makes ruler_add cancel with
        # "Gizmos hidden in this view". Measure is exposed in our custom
        # header, so keep both required viewport switches enabled here.
        space = getattr(getattr(area, "spaces", None), "active", None)
        try:
            if space is not None and hasattr(space, "show_gizmo"):
                space.show_gizmo = True
            if space is not None and hasattr(space, "show_gizmo_tool"):
                space.show_gizmo_tool = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    screen = getattr(context, "screen", None)
    redraw_areas = getattr(screen, "areas", ()) if screen is not None else ()
    for redraw_area in redraw_areas:
        if getattr(redraw_area, "type", "") in {"VIEW_3D", "TOPBAR"}:
            redraw_area.tag_redraw()
    if not redraw_areas:
        area.tag_redraw()
    return True


def _activate_default_select_tool(context):
    return _set_active_viewport_tool(context, "builtin.select_box")


def _active_transform_panel_object(context):
    obj = getattr(context, "active_object", None)
    if obj is None:
        return None
    try:
        if not obj.select_get():
            return None
    except (AttributeError, RuntimeError):
        pass
    return obj


def _schedule_transform_empty_click_check(context):
    """Restore Select after Blender has processed an empty viewport click."""
    global _VIEWPORT_TRANSFORM_EXIT_CHECK_GENERATION

    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if window is None or area is None or region is None:
        return

    _VIEWPORT_TRANSFORM_EXIT_CHECK_GENERATION += 1
    generation = _VIEWPORT_TRANSFORM_EXIT_CHECK_GENERATION
    attempt = 0
    max_attempts = 30

    def _check_selection_after_click():
        nonlocal attempt
        attempt += 1
        if generation != _VIEWPORT_TRANSFORM_EXIT_CHECK_GENERATION:
            return None
        try:
            screen = getattr(window, "screen", None)
            if screen is None:
                return None
            area_pointer = area.as_pointer()
            if not any(
                candidate.as_pointer() == area_pointer
                for candidate in screen.areas
            ):
                return None
            with bpy.context.temp_override(
                window=window,
                area=area,
                region=region,
            ):
                if (
                    _active_viewport_tool_id(bpy.context)
                    not in _VIEWPORT_TRANSFORM_TOOL_IDS
                ):
                    return None
                if getattr(bpy.context, "selected_objects", ()):
                    return 0.1 if attempt < max_attempts else None
                if not _activate_default_select_tool(bpy.context):
                    return 0.1 if attempt < max_attempts else None
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            return 0.1 if attempt < max_attempts else None
        return None

    bpy.app.timers.register(
        _check_selection_after_click,
        first_interval=0.1,
    )


def _scene_length_to_transform_mm(value, scene):
    unit_settings = getattr(scene, "unit_settings", None)
    scale_length = float(getattr(unit_settings, "scale_length", 1.0) or 1.0)
    return float(value) * scale_length * 1000.0


def _transform_panel_axis_values(context, obj, mode, unit):
    if mode in {"LOCATION", "DIMENSIONS"}:
        source = obj.location if mode == "LOCATION" else obj.dimensions
        values_mm = [
            _scene_length_to_transform_mm(value, context.scene)
            for value in source
        ]
        if unit == "IN":
            return [value / 25.4 for value in values_mm]
        return values_mm
    if mode == "ROTATION":
        return [math.degrees(float(value)) for value in obj.rotation_euler]
    return [float(value) * 100.0 for value in obj.scale]


def _format_transform_panel_value(value, mode, unit):
    if mode in {"LOCATION", "DIMENSIONS"}:
        return f"{value:.3f} in" if unit == "IN" else f"{value:.2f} mm"
    if mode == "ROTATION":
        return f"{value:.1f}°"
    return f"{value:.1f}%"


def _format_transform_panel_edit_buffer(value):
    if abs(float(value)) < 1e-9:
        return "0"
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _format_transform_panel_inline_value(buffer, mode, unit):
    suffix = {
        ("LOCATION", "MM"): " mm",
        ("LOCATION", "IN"): " in",
        ("DIMENSIONS", "MM"): " mm",
        ("DIMENSIONS", "IN"): " in",
        ("ROTATION", "DEG"): "°",
        ("SCALE", "PERCENT"): "%",
    }.get((mode, unit), "")
    return f"{buffer}{suffix}  |"


def _get_viewport_transform_panel_layout(context, region):
    tool_id = _active_viewport_tool_id(context)
    mode_info = {
        "builtin.move": ("LOCATION", t("Move")),
        "builtin.rotate": ("ROTATION", t("Rotate")),
        "builtin.scale": ("SCALE", t("Scale")),
    }.get(tool_id)
    obj = _active_transform_panel_object(context)
    if mode_info is None or obj is None:
        return None

    mode, title = mode_info
    ui_scale = _get_overlay_ui_scale(context)
    side_margin = _scale_overlay_value(_TRANSFORM_PANEL_LEFT_MARGIN, ui_scale)
    left_bound, right_bound = _get_action_bar_horizontal_bounds(
        context,
        region,
        side_margin,
    )
    panel_width = min(
        _scale_overlay_value(_TRANSFORM_PANEL_WIDTH, ui_scale),
        max(1, right_bound - left_bound),
    )
    padding = _scale_overlay_value(_TRANSFORM_PANEL_PADDING, ui_scale)
    header_height = _scale_overlay_value(
        _TRANSFORM_PANEL_HEADER_HEIGHT,
        ui_scale,
    )
    row_height = _scale_overlay_value(_TRANSFORM_PANEL_ROW_HEIGHT, ui_scale)
    row_gap = _scale_overlay_value(_TRANSFORM_PANEL_ROW_GAP, ui_scale)
    section_height = _scale_overlay_value(
        _TRANSFORM_PANEL_SECTION_HEIGHT,
        ui_scale,
    )
    section_gap = _scale_overlay_value(
        _TRANSFORM_PANEL_SECTION_GAP,
        ui_scale,
    )
    if mode == "SCALE":
        panel_height = (
            (padding * 2)
            + header_height
            + (section_height * 2)
            + (row_height * 6)
            + (row_gap * 4)
            + section_gap
        )
    else:
        panel_height = (
            (padding * 2)
            + header_height
            + (row_height * 3)
            + (row_gap * 2)
        )
    panel_x = left_bound
    panel_y = max(
        padding,
        int(getattr(region, "height", 0))
        - _scale_overlay_value(_TRANSFORM_PANEL_TOP_MARGIN, ui_scale)
        - panel_height,
    )
    field_x = panel_x + padding + _scale_overlay_value(28, ui_scale)
    field_width = panel_width - (field_x - panel_x) - padding
    rows = []
    sections = []
    top = panel_y + panel_height - padding - header_height

    def append_rows(row_mode, unit, cursor_y):
        values = _transform_panel_axis_values(context, obj, row_mode, unit)
        for index, axis in enumerate("XYZ"):
            row_y = cursor_y - row_height
            editing = bool(
                _VIEWPORT_TRANSFORM_EDIT_STATE
                and _VIEWPORT_TRANSFORM_EDIT_STATE.get("mode") == row_mode
                and _VIEWPORT_TRANSFORM_EDIT_STATE.get("axis") == index
                and _VIEWPORT_TRANSFORM_EDIT_STATE.get("unit") == unit
            )
            value = _format_transform_panel_value(
                values[index],
                row_mode,
                unit,
            )
            if editing:
                value = _format_transform_panel_inline_value(
                    _VIEWPORT_TRANSFORM_EDIT_STATE.get("buffer", ""),
                    row_mode,
                    unit,
                )
            rows.append(
                {
                    "id": f"value_{row_mode.lower()}_{index}",
                    "kind": "value",
                    "mode": row_mode,
                    "axis": index,
                    "axis_label": axis,
                    "unit": unit,
                    "value": value,
                    "editing": editing,
                    "invalid": bool(
                        editing
                        and _VIEWPORT_TRANSFORM_EDIT_STATE.get(
                            "invalid",
                            False,
                        )
                    ),
                    "x": field_x,
                    "y": row_y,
                    "width": field_width,
                    "height": row_height,
                }
            )
            cursor_y = row_y - (row_gap if index < 2 else 0)
        return cursor_y

    if mode == "SCALE":
        scale_section_y = top - section_height
        sections.append(
            {
                "label": t("Scale %"),
                "x": panel_x + padding + _scale_overlay_value(3, ui_scale),
                "y": scale_section_y,
                "height": section_height,
            }
        )
        cursor_y = append_rows("SCALE", "PERCENT", scale_section_y)
        cursor_y -= section_gap
        dimensions_section_y = cursor_y - section_height
        sections.append(
            {
                "label": t("Dimensions"),
                "x": panel_x + padding + _scale_overlay_value(3, ui_scale),
                "y": dimensions_section_y,
                "height": section_height,
            }
        )
        append_rows(
            "DIMENSIONS",
            _VIEWPORT_TRANSFORM_UNIT,
            dimensions_section_y,
        )
    else:
        unit = _VIEWPORT_TRANSFORM_UNIT if mode == "LOCATION" else "DEG"
        append_rows(mode, unit, top)

    unit_buttons = []
    if mode == "LOCATION":
        unit_width = _scale_overlay_value(38, ui_scale)
        unit_height = _scale_overlay_value(22, ui_scale)
        unit_y = panel_y + panel_height - padding - unit_height
        unit_x = panel_x + panel_width - padding - (unit_width * 2)
        for index, unit in enumerate(("MM", "IN")):
            unit_buttons.append(
                {
                    "id": f"unit_{unit}",
                    "kind": "unit",
                    "unit": unit,
                    "label": "mm" if unit == "MM" else "in",
                    "active": unit == _VIEWPORT_TRANSFORM_UNIT,
                    "x": unit_x + (index * unit_width),
                    "y": unit_y,
                    "width": unit_width,
                    "height": unit_height,
                }
            )
    elif mode == "SCALE":
        proportional_width = _scale_overlay_value(78, ui_scale)
        proportional_height = _scale_overlay_value(22, ui_scale)
        unit_buttons.append(
            {
                "id": "scale_proportional",
                "kind": "proportional",
                "label": t("Uniform"),
                "active": _VIEWPORT_SCALE_PROPORTIONAL,
                "x": panel_x + panel_width - padding - proportional_width,
                "y": (
                    panel_y
                    + panel_height
                    - padding
                    - proportional_height
                ),
                "width": proportional_width,
                "height": proportional_height,
            }
        )
        unit_width = _scale_overlay_value(38, ui_scale)
        unit_height = _scale_overlay_value(20, ui_scale)
        unit_x = panel_x + panel_width - padding - (unit_width * 2)
        unit_y = dimensions_section_y + max(
            0,
            (section_height - unit_height) // 2,
        )
        for index, unit in enumerate(("MM", "IN")):
            unit_buttons.append(
                {
                    "id": f"unit_{unit}",
                    "kind": "unit",
                    "unit": unit,
                    "label": "mm" if unit == "MM" else "in",
                    "active": unit == _VIEWPORT_TRANSFORM_UNIT,
                    "x": unit_x + (index * unit_width),
                    "y": unit_y,
                    "width": unit_width,
                    "height": unit_height,
                }
            )

    return {
        "panel": {
            "x": panel_x,
            "y": panel_y,
            "width": panel_width,
            "height": panel_height,
        },
        "title": title,
        "title_x": panel_x + padding + _scale_overlay_value(8, ui_scale),
        "title_y": panel_y + panel_height - padding - _scale_overlay_value(18, ui_scale),
        "accent_x": panel_x + padding,
        "accent_y": panel_y + panel_height - padding - header_height,
        "accent_width": _scale_overlay_value(3, ui_scale),
        "accent_height": header_height,
        "rows": rows,
        "sections": sections,
        "unit_buttons": unit_buttons,
        "font_size": _scale_overlay_value(12, ui_scale),
        "title_font_size": _scale_overlay_value(13, ui_scale),
        "corner_radius": _scale_overlay_value(7, ui_scale),
    }


def _transform_panel_hitbox_at(layout, x, y):
    if layout is None:
        return None
    for hitbox in (*layout["unit_buttons"], *layout["rows"]):
        if (
            hitbox["x"] <= x <= hitbox["x"] + hitbox["width"]
            and hitbox["y"] <= y <= hitbox["y"] + hitbox["height"]
        ):
            return hitbox
    return None


def _draw_viewport_transform_panel_impl():
    import blf  # type: ignore

    context = bpy.context
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    if (
        region is None
        or area is None
        or getattr(region, "type", "") != "WINDOW"
        or getattr(area, "type", "") != "VIEW_3D"
    ):
        return
    layout = _get_viewport_transform_panel_layout(context, region)
    if layout is None:
        return

    panel = layout["panel"]
    _draw_overlay_background(
        panel["x"],
        panel["y"],
        panel["width"],
        panel["height"],
        color=_ACTION_BAR_PANEL_COLOR,
        corner_radius=layout["corner_radius"],
        border_color=_ACTION_BAR_SECONDARY_BORDER_COLOR,
        border_width=1,
    )
    _draw_overlay_background(
        layout["accent_x"],
        layout["accent_y"],
        layout["accent_width"],
        layout["accent_height"],
        color=_ACTION_BAR_PRIMARY_BORDER_COLOR,
        corner_radius=max(1, layout["accent_width"] // 2),
    )
    blf.size(_ACTION_BAR_FONT_ID, layout["title_font_size"])
    blf.color(_ACTION_BAR_FONT_ID, *_ACTION_BAR_TEXT_COLOR)
    blf.position(
        _ACTION_BAR_FONT_ID,
        layout["title_x"],
        layout["title_y"],
        0,
    )
    blf.draw(_ACTION_BAR_FONT_ID, layout["title"])

    blf.size(_ACTION_BAR_FONT_ID, layout["font_size"])
    text_height = max(1, int(blf.dimensions(_ACTION_BAR_FONT_ID, "Ag")[1]))
    for section in layout["sections"]:
        blf.color(_ACTION_BAR_FONT_ID, *_ACTION_BAR_BODY_TEXT_COLOR)
        blf.position(
            _ACTION_BAR_FONT_ID,
            section["x"],
            section["y"] + ((section["height"] - text_height) / 2),
            0,
        )
        blf.draw(_ACTION_BAR_FONT_ID, section["label"])
    for button in layout["unit_buttons"]:
        active = bool(button["active"])
        hovered = _VIEWPORT_TRANSFORM_HOVERED == button["id"]
        fill_color = (
            _ACTION_BAR_PRIMARY_COLOR
            if active
            else _TRANSFORM_PANEL_FIELD_HOVER_COLOR
            if hovered
            else _TRANSFORM_PANEL_FIELD_COLOR
        )
        border_color = (
            _ACTION_BAR_PRIMARY_BORDER_COLOR
            if active
            else _ACTION_BAR_SECONDARY_BORDER_COLOR
        )
        _draw_overlay_background(
            button["x"],
            button["y"],
            button["width"],
            button["height"],
            color=fill_color,
            corner_radius=max(2, layout["corner_radius"] // 2),
            border_color=border_color,
            border_width=1,
        )
        label_width = int(
            blf.dimensions(_ACTION_BAR_FONT_ID, button["label"])[0]
        )
        blf.color(_ACTION_BAR_FONT_ID, *_ACTION_BAR_TEXT_COLOR)
        blf.position(
            _ACTION_BAR_FONT_ID,
            button["x"] + ((button["width"] - label_width) / 2),
            button["y"] + ((button["height"] - text_height) / 2),
            0,
        )
        blf.draw(_ACTION_BAR_FONT_ID, button["label"])

    for row in layout["rows"]:
        axis = row["axis_label"]
        blf.color(_ACTION_BAR_FONT_ID, *_TRANSFORM_PANEL_AXIS_COLORS[axis])
        blf.position(
            _ACTION_BAR_FONT_ID,
            panel["x"] + _scale_overlay_value(
                _TRANSFORM_PANEL_PADDING + 3,
                _get_overlay_ui_scale(context),
            ),
            row["y"] + ((row["height"] - text_height) / 2),
            0,
        )
        blf.draw(_ACTION_BAR_FONT_ID, axis)
        hovered = _VIEWPORT_TRANSFORM_HOVERED == row["id"]
        editing = bool(row.get("editing"))
        invalid = bool(row.get("invalid"))
        _draw_overlay_background(
            row["x"],
            row["y"],
            row["width"],
            row["height"],
            color=(
                _TRANSFORM_PANEL_FIELD_HOVER_COLOR
                if hovered or editing
                else _TRANSFORM_PANEL_FIELD_COLOR
            ),
            corner_radius=max(2, layout["corner_radius"] // 2),
            border_color=(
                _ACTION_BAR_WARNING_BORDER_COLOR
                if invalid
                else _ACTION_BAR_PRIMARY_BORDER_COLOR
                if hovered or editing
                else _ACTION_BAR_SECONDARY_BORDER_COLOR
            ),
            border_width=1,
        )
        value_width = int(blf.dimensions(_ACTION_BAR_FONT_ID, row["value"])[0])
        blf.color(_ACTION_BAR_FONT_ID, *_ACTION_BAR_TEXT_COLOR)
        blf.position(
            _ACTION_BAR_FONT_ID,
            row["x"] + row["width"] - value_width - _scale_overlay_value(
                10,
                _get_overlay_ui_scale(context),
            ),
            row["y"] + ((row["height"] - text_height) / 2),
            0,
        )
        blf.draw(_ACTION_BAR_FONT_ID, row["value"])


def _draw_viewport_transform_panel():
    global _VIEWPORT_TRANSFORM_PANEL_DRAW_ERROR
    try:
        _draw_viewport_transform_panel_impl()
        _VIEWPORT_TRANSFORM_PANEL_DRAW_ERROR = ""
    except Exception as exc:
        # Draw-handler exceptions otherwise disappear into Blender's console,
        # which makes viewport UI failures unnecessarily difficult to diagnose.
        _VIEWPORT_TRANSFORM_PANEL_DRAW_ERROR = repr(exc)


def build_viewport_tool_actions(context):
    active_tool_id = _active_viewport_tool_id(context)
    return [
        {
            "operator": "silicone.set_viewport_tool",
            "label": t(label),
            "icon": icon,
            "tool_id": tool_id,
            "active": tool_id == active_tool_id,
            "hovered": tool_id in {
                _VIEWPORT_HOVERED_TOOL_ID,
                _VIEWPORT_LABEL_HOVERED_TOOL_ID,
            },
            "style": "secondary",
            "properties": {"tool_id": tool_id},
        }
        for tool_id, label, icon in (
            ("builtin.move", "Move", "EMPTY_ARROWS"),
            ("builtin.rotate", "Rotate", "ORIENTATION_GIMBAL"),
            ("builtin.scale", "Scale", "CON_SIZELIMIT"),
            ("builtin.measure", "Measure", "DRIVER_DISTANCE"),
        )
    ]


def build_viewport_utils_actions(context):
    del context
    return [
        {
            "operator": operator,
            "label": t(label),
            "icon": icon,
            "active": False,
            "hovered": operator in {
                _VIEWPORT_HOVERED_UTIL_OPERATOR,
                _VIEWPORT_LABEL_HOVERED_UTIL_OPERATOR,
            },
            "style": "secondary",
            "properties": {},
        }
        for operator, label, icon in (
            ("silicone.center_obj", "Center", "EMPTY_AXIS"),
            ("silicone.auto_orient_model", "Auto Level", "SNAP_NORMAL"),
            (
                "silicone.orient_face_to_base",
                "Pick Base",
                "RESTRICT_SELECT_OFF",
            ),
            ("silicone.cut", "Cut", "INTERNET_OFFLINE"),
            ("silicone.clean", "Clean", "ORPHAN_DATA"),
            ("silicone.heal_patron", "Heal", "FUND"),
            ("silicone.decimate", "Decimate", "MOD_DECIM"),
            ("silicone.crop_master_filler", "Crop", "MOD_BOOLEAN"),
            ("silicone.smooth_master_seal", "Smooth", "MOD_SMOOTH"),
        )
    ]


def _viewport_utility_preview_path(preview):
    if preview is None:
        return ""
    return _custom_panel_preview_path(int(preview.icon_id), None, "")


def _preview_for_utility_card(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"utility_{identifier}")


def build_viewport_utility_card_actions(context):
    """Build the image-based utilities moved out of the native N-panel."""
    def route_locked_cards(actions):
        for action in actions:
            badge = action.get("badge")
            if badge == "CORE" and is_lite_tier():
                dialog = "silicone.basic_required_dialog"
            elif badge == "PRO" and not has_cached_pro_access(context):
                dialog = "silicone.pro_required_dialog"
            else:
                continue
            action.update(operator=dialog, properties={}, enabled=True)
        return actions

    scene = context.scene
    mold_type = get_mold_type(scene.mold_type_preview).identifier
    foundation_action = {
        "operator": "silicone.begin_foundation",
        "label": t("Foundation"),
        "badge": "PRO",
        "preview_path": _viewport_utility_preview_path(
            _preview_for_utility_card("foundation")
        ),
        "properties": {},
        "enabled": bool(
            has_cached_pro_access(context)
            and foundation_reference_guide_available(scene)
        ),
    }
    if mold_type in {"FIXTURE", "PROTECTIVE_SHELL"}:
        return route_locked_cards([
            {
                "operator": "silicone.grid",
                "label": t("Grid"),
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("grid")
                ),
                "properties": {},
                "enabled": True,
            },
            {
                "operator": "silicone.choose_watermark_type",
                "label": t("Watermark"),
                "badge": "PRO",
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("watermark_reference")
                ),
                "properties": {"include_casting_volume": False},
                "enabled": True,
            },
            foundation_action,
        ])

    actions = []
    if not is_slip_casting_type(mold_type):
        actions.append(
            {
                "operator": "silicone.new_clear_undercuts",
                "label": t("Clear Undercuts"),
                "badge": "CORE",
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_clear_undercuts()
                ),
                "properties": {},
                "enabled": True,
            }
        )
    actions.append(
        {
            "operator": "silicone.add_casting_input",
            "label": t("Add Sprue"),
            "preview_path": _viewport_utility_preview_path(
                _preview_for_utility_card("casting_sprue")
            ),
            "properties": {},
            "enabled": True,
        }
    )
    if not is_direct_mold_type(scene):
        actions.append(
            {
                "operator": "silicone.grid",
                "label": t("Grid"),
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("grid")
                ),
                "properties": {},
                "enabled": True,
            }
        )
    actions.extend(
        (
            {
                "operator": "silicone.hollow",
                "label": t("Hollow"),
                "badge": "CORE",
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("hollow")
                ),
                "properties": {},
                "enabled": True,
            },
            {
                "operator": "silicone.convert_to_planter",
                "label": t("Convert to Planter"),
                "badge": "CORE",
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("convert_to_planter")
                ),
                "properties": {},
                "enabled": True,
            },
        )
    )
    actions.append(
        {
            "operator": "silicone.choose_watermark_type",
            "label": t("Watermark"),
            "badge": "PRO",
            "preview_path": _viewport_utility_preview_path(
                _preview_for_utility_card("watermark_reference")
            ),
            "properties": {"include_casting_volume": True},
            "enabled": True,
        }
    )
    if not is_direct_mold_type(scene):
        has_air_trap_pillars = scene_has_master_air_trap_pillars(context)
        actions.append(
            {
                "operator": "silicone.build_master_air_trap_bridges",
                "label": t(
                    "Edit Pillars, Then Confirm"
                    if has_air_trap_pillars
                    else "Air Trap Pillars"
                ),
                "badge": "PRO",
                "preview_path": _viewport_utility_preview_path(
                    _preview_for_utility_card("master_air_trap_pillars")
                ),
                "properties": {},
                "enabled": bool(
                    has_cached_pro_access(context)
                    and not has_air_trap_pillars
                ),
            }
        )
    actions.append(
        {
            "operator": "silicone.build_master_filler",
            "label": t("Smart Seal"),
            "badge": "PRO",
            "preview_path": _viewport_utility_preview_path(
                _preview_for_utility_card("master_smart_sealer")
            ),
            "properties": {},
            "enabled": has_cached_pro_access(context),
        }
    )
    if mold_type != "DIRECT_MOLD_SKIN":
        actions.append(foundation_action)
    return route_locked_cards(actions)


def _draw_viewport_utility_cards():
    context = bpy.context
    area = getattr(context, "area", None)
    region = getattr(context, "region", None)
    if (
        area is None
        or region is None
        or getattr(area, "type", "") != "VIEW_3D"
        or getattr(region, "type", "") != "WINDOW"
    ):
        return
    region_key = int(region.as_pointer())
    state = _VIEWPORT_UTILITY_COLUMN_STATES.setdefault(
        region_key,
        {
            "hovered": "",
            "hitboxes": [],
            "rect": None,
            "scroll": 0.0,
            "scroll_target": 0.0,
            "max_scroll": 0,
            "context_key": "",
        },
    )
    context_key = str(getattr(context.scene, "mold_type_preview", ""))
    if state.get("context_key") != context_key:
        state["context_key"] = context_key
        state["scroll"] = 0.0
        state["scroll_target"] = 0.0
        state["hovered"] = ""
    actions = build_viewport_utility_card_actions(context)
    for action in actions:
        action["enabled"] = bool(
            action.get("enabled", True)
            and _action_bar_operator_enabled(action)
        )
    state.update(
        draw_viewport_utility_column(
            context,
            region,
            actions,
            str(state.get("hovered", "")),
            float(state.get("scroll", 0.0)),
        )
    )
    state["scroll_target"] = max(
        0.0,
        min(
            float(state.get("scroll_target", 0.0)),
            float(state.get("max_scroll", 0.0)),
        ),
    )


def _viewport_utility_column_state(region):
    if region is None:
        return None
    try:
        return _VIEWPORT_UTILITY_COLUMN_STATES.get(int(region.as_pointer()))
    except Exception:
        return None


def _tag_viewport_utility_scroll_redraw():
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()) if window_manager else ():
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", "") == "VIEW_3D":
                area.tag_redraw()


def _animate_viewport_utility_scroll():
    active = False
    changed = False
    for state in tuple(_VIEWPORT_UTILITY_COLUMN_STATES.values()):
        maximum = max(0.0, float(state.get("max_scroll", 0.0)))
        target = max(
            0.0,
            min(float(state.get("scroll_target", 0.0)), maximum),
        )
        current = max(
            0.0,
            min(float(state.get("scroll", 0.0)), maximum),
        )
        difference = target - current
        if abs(difference) <= 0.5:
            next_scroll = target
        else:
            next_scroll = current + (difference * 0.26)
            active = True
        if abs(next_scroll - current) > 1e-4:
            state["scroll"] = next_scroll
            changed = True
    if changed:
        _tag_viewport_utility_scroll_redraw()
    return (1.0 / 60.0) if active else None


def _schedule_viewport_utility_scroll_animation():
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _animate_viewport_utility_scroll
    ):
        return
    bpy.app.timers.register(
        _animate_viewport_utility_scroll,
        first_interval=0.0,
    )


def _get_viewport_column_anchor(context, region, first_offset):
    ui_scale = _get_overlay_ui_scale(context)
    toolbar_region = next(
        (
            area_region
            for area_region in getattr(context.area, "regions", ())
            if getattr(area_region, "type", "") == "TOOLS"
            and int(getattr(area_region, "width", 0) or 0) > 1
        ),
        None,
    )
    toolbar_width = int(getattr(toolbar_region, "width", 0) or 0)
    toolbar_x = int(getattr(toolbar_region, "x", 0) or 0)
    region_x = int(getattr(region, "x", 0) or 0)
    column_x = (
        toolbar_x - region_x + (toolbar_width / 2)
        if toolbar_region is not None
        else _scale_overlay_value(20, ui_scale)
    )
    first_y = region.height - _scale_overlay_value(
        first_offset,
        ui_scale,
    )
    return column_x, first_y, ui_scale


def _get_viewport_icon_scale(context, ui_scale):
    """Keep the custom buttons at Blender's normal toolbar icon size."""
    gizmo_size = _VIEWPORT_GIZMO_REFERENCE_SIZE
    try:
        gizmo_size = max(1, int(context.preferences.view.gizmo_size))
    except (AttributeError, TypeError, ValueError):
        pass
    return (
        _scale_overlay_value(_VIEWPORT_UTILS_ICON_SCALE, ui_scale)
        * _VIEWPORT_GIZMO_REFERENCE_SIZE
        / gizmo_size
    )


def _get_viewport_control_label_layout(context, region, actions, first_offset):
    region_width = int(getattr(region, "width", 0) or 0)
    region_height = int(getattr(region, "height", 0) or 0)
    if region_width <= 0 or region_height <= 0:
        return None

    column_x, first_y, ui_scale = _get_viewport_column_anchor(
        context,
        region,
        first_offset,
    )
    label_width = _scale_overlay_value(_VIEWPORT_UTILS_LABEL_WIDTH, ui_scale)
    label_height = _scale_overlay_value(_VIEWPORT_UTILS_LABEL_HEIGHT, ui_scale)
    overlap = _scale_overlay_value(_VIEWPORT_UTILS_LABEL_OVERLAP, ui_scale)
    spacing = _scale_overlay_value(_VIEWPORT_UTILS_SPACING, ui_scale)
    font_size = _scale_overlay_value(
        _VIEWPORT_UTILS_LABEL_FONT_SIZE,
        ui_scale,
    )
    label_x = column_x + overlap
    label_width = min(label_width, max(1, region_width - label_x - 8))
    buttons = []
    for index, action in enumerate(actions):
        center_y = first_y - (index * spacing)
        buttons.append(
            {
                "action": action,
                "x": label_x,
                "y": center_y - (label_height / 2),
                "width": label_width,
                "height": label_height,
                "enabled": _action_bar_operator_enabled(action),
            }
        )
    return {
        "buttons": buttons,
        "font_size": font_size,
        "padding_left": _scale_overlay_value(16, ui_scale),
        "padding_right": _scale_overlay_value(8, ui_scale),
        "corner_radius": _scale_overlay_value(5, ui_scale),
    }


def _get_viewport_tool_label_layout(context, region):
    return _get_viewport_control_label_layout(
        context,
        region,
        build_viewport_tool_actions(context),
        _VIEWPORT_TOOLS_FIRST_OFFSET,
    )


def _get_viewport_utils_label_layout(context, region):
    return _get_viewport_control_label_layout(
        context,
        region,
        build_viewport_utils_actions(context),
        _VIEWPORT_UTILS_FIRST_OFFSET,
    )


def _draw_viewport_utils_labels():
    import blf  # type: ignore

    context = bpy.context
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    if (
        region is None
        or area is None
        or getattr(region, "type", "") != "WINDOW"
        or getattr(area, "type", "") != "VIEW_3D"
    ):
        return
    layouts = (
        _get_viewport_tool_label_layout(context, region),
        _get_viewport_utils_label_layout(context, region),
    )
    for layout in layouts:
        if layout is None:
            continue
        blf.size(_ACTION_BAR_FONT_ID, layout["font_size"])
        text_height = max(
            1,
            int(blf.dimensions(_ACTION_BAR_FONT_ID, "Ag")[1]),
        )
        for button in layout["buttons"]:
            if button["action"].get("active", False) or (
                button["enabled"]
                and button["action"].get("hovered", False)
            ):
                fill_color = _ACTION_BAR_PRIMARY_COLOR
                border_color = _ACTION_BAR_PRIMARY_BORDER_COLOR
            elif button["enabled"]:
                fill_color = _VIEWPORT_UTILS_LABEL_COLOR
                border_color = _ACTION_BAR_SECONDARY_BORDER_COLOR
            else:
                fill_color = _ACTION_BAR_DISABLED_COLOR
                border_color = _ACTION_BAR_SECONDARY_BORDER_COLOR
            text_color = (
                _ACTION_BAR_TEXT_COLOR
                if button["enabled"]
                else _ACTION_BAR_DISABLED_TEXT_COLOR
            )
            _draw_overlay_background(
                button["x"],
                button["y"],
                button["width"],
                button["height"],
                color=fill_color,
                corner_radius=layout["corner_radius"],
                border_color=border_color,
                border_width=1,
            )
            max_text_width = max(
                1,
                button["width"]
                - layout["padding_left"]
                - layout["padding_right"],
            )
            label = _truncate_action_bar_label(
                button["action"]["label"],
                max_text_width,
            )
            blf.color(_ACTION_BAR_FONT_ID, *text_color)
            blf.position(
                _ACTION_BAR_FONT_ID,
                button["x"] + layout["padding_left"],
                button["y"] + ((button["height"] - text_height) / 2),
                0,
            )
            blf.draw(_ACTION_BAR_FONT_ID, label)


def _custom_panel_draw_callable(panel_class):
    def draw(layout, context):
        panel = type("ViewportPanelAdapter", (), {})()
        panel.layout = layout
        panel_class.draw(panel, context)

    return draw


def _draw_viewport_custom_panel():
    context = bpy.context
    region = getattr(context, "region", None)
    area = getattr(context, "area", None)
    if (
        region is None
        or area is None
        or getattr(region, "type", "") != "WINDOW"
        or getattr(area, "type", "") != "VIEW_3D"
    ):
        return
    space = getattr(context, "space_data", None)
    if space is not None and bool(getattr(space, "show_region_ui", False)):
        try:
            space.show_region_ui = False
            area.tag_redraw()
        except (AttributeError, TypeError):
            pass
    region_key = int(region.as_pointer())
    header_state = str(getattr(context.scene, "mold_type_preview", ""))
    if _VIEWPORT_CUSTOM_PANEL_HEADER_STATES.get(region_key) != header_state:
        try:
            MoldboxerPanel.draw_header(
                type("ViewportPanelHeaderAdapter", (), {})(),
                context,
            )
        except Exception:
            pass
        _VIEWPORT_CUSTOM_PANEL_HEADER_STATES[region_key] = header_state
    panel_specs = (
        (
            SILICONE_PT_mold.bl_idname,
            t(SILICONE_PT_mold.bl_label),
            _custom_panel_draw_callable(SILICONE_PT_mold),
        ),
        (
            SILICONE_PT_settings.bl_idname,
            t(SILICONE_PT_settings.bl_label),
            _custom_panel_draw_callable(SILICONE_PT_settings),
        ),
        (
            SILICONE_PT_pro_settings.bl_idname,
            t(SILICONE_PT_pro_settings.bl_label),
            _custom_panel_draw_callable(SILICONE_PT_pro_settings),
        ),
        (
            SILICONE_PT_utils.bl_idname,
            t(SILICONE_PT_utils.bl_label),
            _custom_panel_draw_callable(SILICONE_PT_utils),
        ),
    )
    roots = record_custom_panels(context, panel_specs)
    rows = flatten_custom_panel_nodes(
        roots,
        _VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS,
    )
    state = _VIEWPORT_CUSTOM_PANEL_STATES.setdefault(
        region_key,
        {"scroll": 0, "hovered": "", "hitboxes": [], "targets": {}},
    )
    result = draw_custom_viewport_panel(
        context,
        region,
        rows,
        int(state.get("scroll", 0)),
        str(state.get("hovered", "")),
        _VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS,
    )
    state.update(result)
    state["scroll"] = max(
        0,
        min(int(state.get("scroll", 0)), int(result["max_scroll"])),
    )


def _viewport_custom_panel_state(region):
    if region is None:
        return None
    try:
        return _VIEWPORT_CUSTOM_PANEL_STATES.get(int(region.as_pointer()))
    except Exception:
        return None


def _resolve_viewport_custom_panel_target(token):
    for state in _VIEWPORT_CUSTOM_PANEL_STATES.values():
        target = state.get("targets", {}).get(token)
        if target is not None:
            return target
    return None


def _invoke_viewport_custom_panel_operator(context, action):
    operator = _resolve_action_bar_operator({"operator": action["operator"]})
    if operator is None:
        return False
    # Custom-drawn buttons must request the same undo handling as native UI buttons.
    operator("INVOKE_DEFAULT", True, **dict(action.get("properties", {})))
    return True


class SILICONE_GGT_navigation_corner(bpy.types.GizmoGroup):
    """Add-on positioned replacement for Blender's native navigation gizmo."""

    bl_idname = "SILICONE_GGT_navigation_corner"
    bl_label = "Moldboxer Navigation Gizmo"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SCALE"}

    @classmethod
    def poll(cls, context):
        return (
            getattr(getattr(context, "area", None), "type", "") == "VIEW_3D"
            and getattr(getattr(context, "region", None), "type", "") == "WINDOW"
        )

    def setup(self, _context):
        self.navigation_gizmo = self.gizmos.new(
            "VIEW3D_GT_navigate_rotate"
        )
        self.navigation_gizmo.use_draw_modal = True
        self.navigation_gizmo.use_grab_cursor = True
        self.navigation_gizmo.color = (0.5, 0.5, 0.5)
        self.navigation_gizmo.alpha = 0.0
        self.navigation_gizmo.color_highlight = (0.5, 0.5, 0.5)
        self.navigation_gizmo.alpha_highlight = 0.5

        rotate = self.navigation_gizmo.target_set_operator(
            "view3d.rotate",
            index=0,
        )
        rotate.use_cursor_init = False
        axis_views = (
            "LEFT",
            "RIGHT",
            "FRONT",
            "BACK",
            "BOTTOM",
            "TOP",
        )
        for part_index, axis_view in enumerate(axis_views, start=1):
            view_axis = self.navigation_gizmo.target_set_operator(
                "view3d.view_axis",
                index=part_index,
            )
            view_axis.type = axis_view

    def draw_prepare(self, context):
        region = context.region
        region_data = getattr(context, "region_data", None)
        if region_data is None:
            self.navigation_gizmo.hide = True
            return
        self.navigation_gizmo.hide = False

        orientation = self.navigation_gizmo.matrix_offset.copy()
        orientation.identity()
        view_matrix = region_data.view_matrix
        for row in range(3):
            for column in range(3):
                orientation[row][column] = view_matrix[row][column]
        self.navigation_gizmo.matrix_offset = orientation

        ui_scale = _get_overlay_ui_scale(context)
        horizontal_margin = _scale_overlay_value(
            _NAVIGATION_GIZMO_HORIZONTAL_MARGIN,
            ui_scale,
        )
        vertical_margin = _scale_overlay_value(
            _NAVIGATION_GIZMO_VERTICAL_MARGIN,
            ui_scale,
        )
        navigation_size = int(
            getattr(
                getattr(getattr(context, "preferences", None), "view", None),
                "gizmo_size_navigate_v3d",
                80,
            )
            or 80
        )
        radius = max(15, navigation_size // 2)
        left_bound, _right_bound = _get_action_bar_horizontal_bounds(
            context,
            region,
            horizontal_margin,
        )
        self.navigation_gizmo.matrix_basis[0][3] = left_bound + radius
        self.navigation_gizmo.matrix_basis[1][3] = vertical_margin + radius
        self.navigation_gizmo.scale_basis = radius


class SILICONE_GGT_viewport_tools(bpy.types.GizmoGroup):
    """Retired vertical tool group; controls now live in the viewport header."""

    bl_idname = "SILICONE_GGT_viewport_tools"
    bl_label = "Moldboxer Viewport Tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SCALE"}

    @classmethod
    def poll(cls, context):
        del context
        return False

    def setup(self, context):
        self.tool_gizmos = []
        for action in build_viewport_tool_actions(context):
            gizmo = self.gizmos.new("GIZMO_GT_button_2d")
            operator = gizmo.target_set_operator(action["operator"])
            operator.name = action["tool_id"]
            gizmo.icon = action["icon"]
            gizmo.draw_options = {"BACKDROP", "OUTLINE"}
            gizmo.use_tooltip = True
            gizmo.show_drag = False
            gizmo.backdrop_fill_alpha = 0.28
            gizmo.line_width = 1.0
            self.tool_gizmos.append((gizmo, action["tool_id"]))

    def draw_prepare(self, context):
        global _VIEWPORT_HOVERED_TOOL_ID
        region = context.region
        column_x, first_y, ui_scale = _get_viewport_column_anchor(
            context, region, _VIEWPORT_TOOLS_FIRST_OFFSET,
        )
        spacing = _scale_overlay_value(_VIEWPORT_UTILS_SPACING, ui_scale)
        scale_basis = _get_viewport_icon_scale(context, ui_scale)
        active_tool_id = _active_viewport_tool_id(context)
        hovered_tool_id = ""
        for index, (gizmo, tool_id) in enumerate(self.tool_gizmos):
            if gizmo.is_highlight:
                hovered_tool_id = tool_id
            is_active = tool_id == active_tool_id
            gizmo.color = (
                (0.94, 0.64, 0.12)
                if is_active
                else (0.76, 0.76, 0.76)
            )
            gizmo.alpha = 1.0 if is_active else 0.92
            gizmo.color_highlight = (0.94, 0.64, 0.12)
            gizmo.alpha_highlight = 1.0
            gizmo.matrix_basis[0][3] = column_x
            gizmo.matrix_basis[1][3] = first_y - (index * spacing)
            gizmo.scale_basis = scale_basis
        _VIEWPORT_HOVERED_TOOL_ID = hovered_tool_id


class SILICONE_GGT_viewport_utils(bpy.types.GizmoGroup):
    """Retired vertical utility group; controls now live in the viewport header."""

    bl_idname = "SILICONE_GGT_viewport_utils"
    bl_label = "Moldboxer Viewport Utils"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT", "SCALE"}

    @classmethod
    def poll(cls, context):
        del context
        return False

    def setup(self, context):
        self.utility_gizmos = []
        for action in build_viewport_utils_actions(context):
            gizmo = self.gizmos.new("GIZMO_GT_button_2d")
            gizmo.target_set_operator(action["operator"])
            gizmo.icon = action["icon"]
            gizmo.draw_options = {"BACKDROP", "OUTLINE"}
            gizmo.use_tooltip = True
            gizmo.show_drag = False
            gizmo.color = (0.76, 0.76, 0.76)
            gizmo.alpha = 0.92
            gizmo.color_highlight = (0.94, 0.64, 0.12)
            gizmo.alpha_highlight = 1.0
            gizmo.backdrop_fill_alpha = 0.28
            gizmo.line_width = 1.0
            self.utility_gizmos.append((gizmo, action["operator"]))

    def draw_prepare(self, context):
        global _VIEWPORT_HOVERED_UTIL_OPERATOR

        region = context.region
        column_x, first_y, ui_scale = _get_viewport_column_anchor(
            context,
            region,
            _VIEWPORT_UTILS_FIRST_OFFSET,
        )
        spacing = _scale_overlay_value(_VIEWPORT_UTILS_SPACING, ui_scale)
        scale_basis = _get_viewport_icon_scale(context, ui_scale)
        hovered_operator = ""
        for index, (gizmo, operator) in enumerate(self.utility_gizmos):
            if gizmo.is_highlight:
                hovered_operator = operator
            gizmo.matrix_basis[0][3] = column_x
            gizmo.matrix_basis[1][3] = first_y - (index * spacing)
            gizmo.scale_basis = scale_basis
        _VIEWPORT_HOVERED_UTIL_OPERATOR = hovered_operator


class SILICONE_OT_set_viewport_tool(bpy.types.Operator):
    bl_idname = "silicone.set_viewport_tool"
    bl_label = "Set Viewport Tool"
    bl_options = {"INTERNAL"}

    tool_id: bpy.props.StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        area, window_region = _view3d_area_and_window_region(context)
        return area is not None and window_region is not None

    def execute(self, context):
        if not _set_active_viewport_tool(context, self.tool_id):
            return {"CANCELLED"}
        return {"FINISHED"}


class SILICONE_OT_exit_measure_tool(bpy.types.Operator):
    bl_idname = "silicone.exit_measure_tool"
    bl_label = "Exit Measure Tool"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        area, window_region = _view3d_area_and_window_region(context)
        return (
            area is not None
            and window_region is not None
            and _active_viewport_tool_id(context) == "builtin.measure"
        )

    def execute(self, context):
        if not _activate_default_select_tool(context):
            return {"CANCELLED"}
        return {"FINISHED"}


class SILICONE_OT_run_viewport_utility(bpy.types.Operator):
    bl_idname = "silicone.run_viewport_utility"
    bl_label = "Run Viewport Utility"
    bl_options = {"INTERNAL"}

    operator_id: bpy.props.StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        area, window_region = _view3d_area_and_window_region(context)
        return area is not None and window_region is not None

    def invoke(self, context, _event):
        operator = _resolve_action_bar_operator({"operator": self.operator_id})
        if operator is None:
            return {"CANCELLED"}
        area, window_region = _view3d_area_and_window_region(context)
        if area is None or window_region is None:
            return {"CANCELLED"}
        try:
            with context.temp_override(area=area, region=window_region):
                if not operator.poll():
                    return {"CANCELLED"}
                _activate_default_select_tool(context)
                return operator("INVOKE_DEFAULT", True)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class SILICONE_OT_edit_viewport_transform(bpy.types.Operator):
    bl_idname = "silicone.edit_viewport_transform"
    bl_label = "Set Transform Value"
    bl_options = {"INTERNAL", "UNDO"}

    mode: bpy.props.EnumProperty(
        items=(
            ("LOCATION", "Location", ""),
            ("ROTATION", "Rotation", ""),
            ("SCALE", "Scale", ""),
            ("DIMENSIONS", "Dimensions", ""),
        ),
        options={"HIDDEN"},
    )
    axis: bpy.props.IntProperty(min=0, max=2, options={"HIDDEN"})
    unit: bpy.props.EnumProperty(
        items=(
            ("MM", "Millimeters", ""),
            ("IN", "Inches", ""),
            ("DEG", "Degrees", ""),
            ("PERCENT", "Percent", ""),
        ),
        options={"HIDDEN"},
    )
    value: bpy.props.FloatProperty(name="Value", precision=4)

    @classmethod
    def poll(cls, context):
        return _active_transform_panel_object(context) is not None

    def _tag_redraw(self, context):
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

    def _sync_inline_state(self, invalid=False):
        global _VIEWPORT_TRANSFORM_EDIT_STATE
        _VIEWPORT_TRANSFORM_EDIT_STATE = {
            "mode": self.mode,
            "axis": self.axis,
            "unit": self.unit,
            "buffer": self._buffer,
            "invalid": bool(invalid),
        }

    def _load_axis_value(self, context):
        obj = _active_transform_panel_object(context)
        if obj is None:
            return False
        values = _transform_panel_axis_values(
            context,
            obj,
            self.mode,
            self.unit,
        )
        self.value = values[self.axis]
        self._buffer = _format_transform_panel_edit_buffer(self.value)
        self._replace_on_type = True
        self._sync_inline_state()
        self._tag_redraw(context)
        return True

    def _clear_inline_state(self, context):
        global _VIEWPORT_TRANSFORM_EDIT_STATE
        _VIEWPORT_TRANSFORM_EDIT_STATE = None
        self._tag_redraw(context)

    def _commit_inline_value(self, context):
        try:
            self.value = float(str(self._buffer).strip().replace(",", "."))
        except (TypeError, ValueError):
            self._sync_inline_state(invalid=True)
            self._tag_redraw(context)
            return False
        committed = "FINISHED" in self.execute(context)
        self._has_committed_value |= committed
        return committed

    def invoke(self, context, _event):
        self._has_committed_value = False
        if not self._load_axis_value(context):
            return {"CANCELLED"}
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        global _VIEWPORT_TRANSFORM_UNIT
        global _VIEWPORT_SCALE_PROPORTIONAL

        if _active_transform_panel_object(context) is None:
            self._clear_inline_state(context)
            return {"CANCELLED"}

        event_type = str(getattr(event, "type", ""))
        event_value = str(getattr(event, "value", ""))
        if event_type in {"ESC", "RIGHTMOUSE"}:
            self._clear_inline_state(context)
            # Tab/click may already have committed other fields. Preserve their undo step.
            return {"FINISHED"} if self._has_committed_value else {"CANCELLED"}
        if event_type in {"RET", "NUMPAD_ENTER"} and event_value == "PRESS":
            if not self._commit_inline_value(context):
                return {"RUNNING_MODAL"}
            self._clear_inline_state(context)
            return {"FINISHED"}
        if event_type == "TAB" and event_value == "PRESS":
            if not self._commit_inline_value(context):
                return {"RUNNING_MODAL"}
            direction = -1 if bool(getattr(event, "shift", False)) else 1
            if self.mode in {"SCALE", "DIMENSIONS"}:
                targets = [
                    ("SCALE", axis, "PERCENT") for axis in range(3)
                ] + [
                    ("DIMENSIONS", axis, _VIEWPORT_TRANSFORM_UNIT)
                    for axis in range(3)
                ]
                current_index = next(
                    (
                        index
                        for index, target in enumerate(targets)
                        if target[0] == self.mode and target[1] == self.axis
                    ),
                    0,
                )
                self.mode, self.axis, self.unit = targets[
                    (current_index + direction) % len(targets)
                ]
            else:
                self.axis = (self.axis + direction) % 3
            self._load_axis_value(context)
            return {"RUNNING_MODAL"}
        if event_type == "LEFTMOUSE" and event_value == "PRESS":
            region = getattr(context, "region", None)
            layout = _get_viewport_transform_panel_layout(context, region)
            hitbox = _transform_panel_hitbox_at(
                layout,
                int(getattr(event, "mouse_region_x", -1)),
                int(getattr(event, "mouse_region_y", -1)),
            )
            if hitbox is not None and hitbox["kind"] == "value":
                if (
                    hitbox["mode"] == self.mode
                    and hitbox["axis"] == self.axis
                    and hitbox["unit"] == self.unit
                ):
                    return {"RUNNING_MODAL"}
                if not self._commit_inline_value(context):
                    return {"RUNNING_MODAL"}
                self.mode = hitbox["mode"]
                self.axis = hitbox["axis"]
                self.unit = hitbox["unit"]
                self._load_axis_value(context)
                return {"RUNNING_MODAL"}
            if not self._commit_inline_value(context):
                return {"RUNNING_MODAL"}
            panel = None if layout is None else layout.get("panel")
            inside_panel = bool(
                panel
                and panel["x"]
                <= int(getattr(event, "mouse_region_x", -1))
                <= panel["x"] + panel["width"]
                and panel["y"]
                <= int(getattr(event, "mouse_region_y", -1))
                <= panel["y"] + panel["height"]
            )
            if not inside_panel:
                self._clear_inline_state(context)
                # Record this edit before the same click starts another operation.
                return {"FINISHED", "PASS_THROUGH"}
            if hitbox is not None and hitbox["kind"] == "unit":
                _VIEWPORT_TRANSFORM_UNIT = hitbox["unit"]
            elif hitbox is not None and hitbox["kind"] == "proportional":
                _VIEWPORT_SCALE_PROPORTIONAL = (
                    not _VIEWPORT_SCALE_PROPORTIONAL
                )
            self._clear_inline_state(context)
            return {"FINISHED"}

        if event_value != "PRESS":
            return {"RUNNING_MODAL"}
        command_down = bool(getattr(event, "ctrl", False)) or bool(
            getattr(event, "oskey", False)
        )
        if command_down and event_type == "A":
            self._replace_on_type = True
            return {"RUNNING_MODAL"}
        if command_down and event_type == "V":
            clipboard = str(
                getattr(context.window_manager, "clipboard", "") or ""
            ).strip()
            if clipboard:
                self._buffer = clipboard.replace(",", ".")
                self._replace_on_type = False
                self._sync_inline_state()
                self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        if event_type in {"BACK_SPACE", "DEL"}:
            if self._replace_on_type:
                self._buffer = ""
                self._replace_on_type = False
            else:
                self._buffer = self._buffer[:-1]
            self._sync_inline_state()
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}

        character = str(getattr(event, "unicode", "") or "")
        if character == ",":
            character = "."
        if character and character in "0123456789.+-eE":
            if self._replace_on_type:
                self._buffer = character
                self._replace_on_type = False
            else:
                self._buffer += character
            self._sync_inline_state()
            self._tag_redraw(context)
            return {"RUNNING_MODAL"}
        return {"PASS_THROUGH"}

    def execute(self, context):
        obj = _active_transform_panel_object(context)
        if obj is None:
            return {"CANCELLED"}
        if self.mode == "LOCATION":
            value_mm = self.value * 25.4 if self.unit == "IN" else self.value
            unit_settings = getattr(context.scene, "unit_settings", None)
            scale_length = float(
                getattr(unit_settings, "scale_length", 1.0) or 1.0
            )
            obj.location[self.axis] = value_mm / (scale_length * 1000.0)
        elif self.mode == "ROTATION":
            obj.rotation_euler[self.axis] = math.radians(self.value)
        elif self.mode == "SCALE":
            target_scale = self.value / 100.0
            current_scale = float(obj.scale[self.axis])
            if _VIEWPORT_SCALE_PROPORTIONAL and abs(current_scale) > 1e-9:
                scale_ratio = target_scale / current_scale
                for axis in range(3):
                    obj.scale[axis] = float(obj.scale[axis]) * scale_ratio
            else:
                obj.scale[self.axis] = target_scale
        else:
            value_mm = self.value * 25.4 if self.unit == "IN" else self.value
            unit_settings = getattr(context.scene, "unit_settings", None)
            scale_length = float(
                getattr(unit_settings, "scale_length", 1.0) or 1.0
            )
            target_dimension = max(
                0.0,
                value_mm / (scale_length * 1000.0),
            )
            current_dimension = float(obj.dimensions[self.axis])
            if (
                _VIEWPORT_SCALE_PROPORTIONAL
                and abs(current_dimension) > 1e-9
            ):
                dimension_ratio = target_dimension / current_dimension
                for axis in range(3):
                    obj.scale[axis] = float(obj.scale[axis]) * dimension_ratio
            else:
                obj.dimensions[self.axis] = target_dimension
        try:
            context.view_layer.update()
        except (AttributeError, RuntimeError):
            pass
        if self.mode in {"SCALE", "DIMENSIONS"}:
            from .operators import schedule_refresh_after_scale

            schedule_refresh_after_scale(obj)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}


class SILICONE_OT_viewport_action_bar_click(bpy.types.Operator):
    bl_idname = "silicone.viewport_action_bar_click"
    bl_label = "Moldboxer Viewport Action"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if (
            area is None
            or region is None
            or getattr(area, "type", "") != "VIEW_3D"
            or getattr(region, "type", "") != "WINDOW"
        ):
            return {"PASS_THROUGH"}
        mouse_x = int(getattr(event, "mouse_region_x", -1))
        mouse_y = int(getattr(event, "mouse_region_y", -1))
        transform_layout = _get_viewport_transform_panel_layout(context, region)
        transform_hitbox = _transform_panel_hitbox_at(
            transform_layout,
            mouse_x,
            mouse_y,
        )
        if transform_hitbox is not None:
            if transform_hitbox["kind"] == "unit":
                global _VIEWPORT_TRANSFORM_UNIT
                _VIEWPORT_TRANSFORM_UNIT = transform_hitbox["unit"]
                area.tag_redraw()
            elif transform_hitbox["kind"] == "proportional":
                global _VIEWPORT_SCALE_PROPORTIONAL
                _VIEWPORT_SCALE_PROPORTIONAL = (
                    not _VIEWPORT_SCALE_PROPORTIONAL
                )
                area.tag_redraw()
            else:
                bpy.ops.silicone.edit_viewport_transform(
                    "INVOKE_DEFAULT",
                    True,
                    mode=transform_hitbox["mode"],
                    axis=transform_hitbox["axis"],
                    unit=transform_hitbox["unit"],
                )
            return {"FINISHED"}
        if transform_layout is not None:
            panel = transform_layout["panel"]
            if (
                panel["x"] <= mouse_x <= panel["x"] + panel["width"]
                and panel["y"] <= mouse_y <= panel["y"] + panel["height"]
            ):
                return {"FINISHED"}
        utility_state = _viewport_utility_column_state(region)
        if utility_state is not None:
            hitbox = custom_panel_hitbox_at(
                utility_state.get("hitboxes", ()),
                mouse_x,
                mouse_y,
            )
            if hitbox is not None:
                if hitbox.get("kind") == "utility-scroll":
                    utility_state["scroll_target"] = max(
                        0.0,
                        min(
                            float(utility_state.get("max_scroll", 0.0)),
                            float(utility_state.get("scroll_target", 0.0))
                            + float(hitbox.get("delta", 0.0)),
                        ),
                    )
                    _schedule_viewport_utility_scroll_animation()
                    return {"FINISHED"}
                if not hitbox.get("enabled", True):
                    return {"CANCELLED"}
                action = hitbox["action"]
                operator = _resolve_action_bar_operator(action)
                if operator is None:
                    return {"CANCELLED"}
                try:
                    _activate_default_select_tool(context)
                    operator(
                        "INVOKE_DEFAULT",
                        True,
                        **dict(action.get("properties", {})),
                    )
                except Exception as exc:
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
                return {"FINISHED"}
        custom_state = _viewport_custom_panel_state(region)
        if custom_state is not None:
            hitbox = custom_panel_hitbox_at(
                custom_state.get("hitboxes", ()),
                mouse_x,
                mouse_y,
            )
            if hitbox is not None:
                if not hitbox.get("enabled", True):
                    return {"CANCELLED"}
                action = hitbox["action"]
                try:
                    if action["kind"] == "section":
                        section = action["section"]
                        if section in _VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS:
                            _VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS.remove(section)
                        else:
                            _VIEWPORT_CUSTOM_PANEL_COLLAPSED_SECTIONS.add(section)
                        custom_state["scroll"] = 0
                    elif action["kind"] == "property":
                        bpy.ops.silicone.viewport_overlay_edit_property(
                            "INVOKE_DEFAULT",
                            target_token=action["target"],
                            property_name=action["prop_name"],
                        )
                    elif action["kind"] == "operator":
                        _invoke_viewport_custom_panel_operator(context, action)
                    area.tag_redraw()
                except Exception as exc:
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
                return {"FINISHED"}
            rect = custom_state.get("rect")
            if rect is not None and point_in_custom_panel_rect(
                mouse_x,
                mouse_y,
                rect,
            ):
                return {"FINISHED"}
        layouts = (
            _get_viewport_action_bar_layout(context, region),
            _get_viewport_tool_label_layout(context, region),
            _get_viewport_utils_label_layout(context, region),
        )
        for layout in layouts:
            if layout is None:
                continue
            for button in layout["buttons"]:
                if not (
                    button["x"] <= mouse_x <= button["x"] + button["width"]
                    and button["y"]
                    <= mouse_y
                    <= button["y"] + button["height"]
                ):
                    continue
                if not button["enabled"]:
                    return {"CANCELLED"}
                action = button["action"]
                operator = _resolve_action_bar_operator(action)
                if operator is None:
                    return {"CANCELLED"}
                try:
                    if action["operator"] != SILICONE_OT_set_viewport_tool.bl_idname:
                        _activate_default_select_tool(context)
                    operator("INVOKE_DEFAULT", True, **action["properties"])
                except Exception as exc:
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
                return {"FINISHED"}
        if _active_viewport_tool_id(context) in _VIEWPORT_TRANSFORM_TOOL_IDS:
            _schedule_transform_empty_click_check(context)
        return {"PASS_THROUGH"}


class SILICONE_OT_viewport_action_bar_hover(bpy.types.Operator):
    """Track hover over the GPU-drawn text portions of viewport controls."""

    bl_idname = "silicone.viewport_action_bar_hover"
    bl_label = "Moldboxer Viewport Action Hover"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        global _VIEWPORT_LABEL_HOVERED_TOOL_ID
        global _VIEWPORT_LABEL_HOVERED_UTIL_OPERATOR
        global _VIEWPORT_TRANSFORM_HOVERED

        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if (
            area is None
            or region is None
            or getattr(area, "type", "") != "VIEW_3D"
            or getattr(region, "type", "") != "WINDOW"
        ):
            return {"PASS_THROUGH"}

        mouse_x = int(getattr(event, "mouse_region_x", -1))
        mouse_y = int(getattr(event, "mouse_region_y", -1))
        transform_layout = _get_viewport_transform_panel_layout(context, region)
        transform_hitbox = _transform_panel_hitbox_at(
            transform_layout,
            mouse_x,
            mouse_y,
        )
        transform_hovered = (
            "" if transform_hitbox is None else transform_hitbox["id"]
        )
        if transform_hovered != _VIEWPORT_TRANSFORM_HOVERED:
            _VIEWPORT_TRANSFORM_HOVERED = transform_hovered
            area.tag_redraw()
        utility_state = _viewport_utility_column_state(region)
        if utility_state is not None:
            hitbox = custom_panel_hitbox_at(
                utility_state.get("hitboxes", ()),
                mouse_x,
                mouse_y,
            )
            hovered = "" if hitbox is None else hitbox["id"]
            if hovered != utility_state.get("hovered", ""):
                utility_state["hovered"] = hovered
                area.tag_redraw()
        custom_state = _viewport_custom_panel_state(region)
        if custom_state is not None:
            hitbox = custom_panel_hitbox_at(
                custom_state.get("hitboxes", ()),
                mouse_x,
                mouse_y,
            )
            hovered = "" if hitbox is None else hitbox["id"]
            if hovered != custom_state.get("hovered", ""):
                custom_state["hovered"] = hovered
                area.tag_redraw()
        hovered_tool_id = ""
        hovered_util_operator = ""
        layouts = (
            ("tool", _get_viewport_tool_label_layout(context, region)),
            ("util", _get_viewport_utils_label_layout(context, region)),
        )
        for control_type, layout in layouts:
            if layout is None:
                continue
            for button in layout["buttons"]:
                if not (
                    button["x"] <= mouse_x <= button["x"] + button["width"]
                    and button["y"]
                    <= mouse_y
                    <= button["y"] + button["height"]
                ):
                    continue
                action = button["action"]
                if control_type == "tool":
                    hovered_tool_id = action["tool_id"]
                else:
                    hovered_util_operator = action["operator"]
                break

        changed = (
            hovered_tool_id != _VIEWPORT_LABEL_HOVERED_TOOL_ID
            or hovered_util_operator != _VIEWPORT_LABEL_HOVERED_UTIL_OPERATOR
        )
        _VIEWPORT_LABEL_HOVERED_TOOL_ID = hovered_tool_id
        _VIEWPORT_LABEL_HOVERED_UTIL_OPERATOR = hovered_util_operator
        if changed:
            area.tag_redraw()
        return {"PASS_THROUGH"}


def _viewport_overlay_property_enum_items(self, _context):
    target = _resolve_viewport_custom_panel_target(self.target_token)
    if target is None:
        return [("NONE", "Unavailable", "")]
    try:
        metadata = target.bl_rna.properties[self.property_name]
        return [
            (
                str(item.identifier),
                str(item.name),
                str(item.description or ""),
                int(getattr(item, "value", index)),
            )
            for index, item in enumerate(metadata.enum_items)
        ]
    except Exception:
        return [("NONE", "Unavailable", "")]


class SILICONE_OT_viewport_overlay_edit_property(bpy.types.Operator):
    bl_idname = "silicone.viewport_overlay_edit_property"
    bl_label = "Edit Moldboxer Setting"
    bl_options = {"INTERNAL"}

    target_token: bpy.props.StringProperty(options={"HIDDEN"})
    property_name: bpy.props.StringProperty(options={"HIDDEN"})
    value_text: bpy.props.StringProperty(name="Value")
    distance_value: bpy.props.FloatProperty(
        name="Value", subtype="DISTANCE", unit="LENGTH",
    )
    enum_value: bpy.props.EnumProperty(
        name="Value",
        items=_viewport_overlay_property_enum_items,
    )

    def _target_and_metadata(self):
        target = _resolve_viewport_custom_panel_target(self.target_token)
        if target is None:
            return None, None
        try:
            return target, target.bl_rna.properties[self.property_name]
        except Exception:
            return target, None

    def invoke(self, context, _event):
        target, metadata = self._target_and_metadata()
        if target is None or metadata is None:
            return {"CANCELLED"}
        value = getattr(target, self.property_name)
        if metadata.type == "BOOLEAN":
            setattr(target, self.property_name, not bool(value))
            context.area.tag_redraw()
            return {"FINISHED"}
        if metadata.type == "ENUM":
            self.enum_value = str(value)
        elif metadata.type == "FLOAT" and metadata.subtype == "DISTANCE":
            self.distance_value = value
        elif getattr(metadata, "is_array", False):
            self.value_text = ", ".join(str(item) for item in value)
        else:
            self.value_text = str(value)
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        _target, metadata = self._target_and_metadata()
        if metadata is not None and metadata.type == "ENUM":
            self.layout.prop(self, "enum_value", text=str(metadata.name))
        elif metadata is not None and metadata.type == "FLOAT" and metadata.subtype == "DISTANCE":
            self.layout.prop(self, "distance_value", text=str(metadata.name))
        else:
            label = str(getattr(metadata, "name", "Value"))
            self.layout.prop(self, "value_text", text=label)

    def execute(self, context):
        target, metadata = self._target_and_metadata()
        if target is None or metadata is None:
            return {"CANCELLED"}
        try:
            if metadata.type == "ENUM":
                value = self.enum_value
            elif metadata.type == "FLOAT" and metadata.subtype == "DISTANCE":
                value = self.distance_value
            elif getattr(metadata, "is_array", False):
                parts = [part.strip() for part in self.value_text.split(",")]
                value = tuple(float(part) for part in parts if part)
            elif metadata.type == "FLOAT":
                value = float(self.value_text)
            elif metadata.type == "INT":
                value = int(float(self.value_text))
            else:
                value = self.value_text
            setattr(target, self.property_name, value)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        context.area.tag_redraw()
        return {"FINISHED"}


class SILICONE_OT_viewport_overlay_scroll(bpy.types.Operator):
    bl_idname = "silicone.viewport_overlay_scroll"
    bl_label = "Scroll Moldboxer Panel"
    bl_options = {"INTERNAL"}

    direction: bpy.props.IntProperty(default=1, options={"HIDDEN"})

    @staticmethod
    def _event_direction(event, fallback):
        direction = int(fallback)
        if str(getattr(event, "type", "")) != "TRACKPADPAN":
            return direction
        delta = int(getattr(event, "mouse_y", 0)) - int(
            getattr(event, "mouse_prev_y", 0)
        )
        if delta == 0:
            return 0
        return -1 if delta > 0 else 1

    def invoke(self, context, event):
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if (
            area is None
            or region is None
            or getattr(area, "type", "") != "VIEW_3D"
            or getattr(region, "type", "") != "WINDOW"
        ):
            return {"PASS_THROUGH"}
        mouse_x = int(getattr(event, "mouse_region_x", -1))
        mouse_y = int(getattr(event, "mouse_region_y", -1))
        utility_state = _viewport_utility_column_state(region)
        utility_rect = (
            utility_state.get("rect") if utility_state is not None else None
        )
        if (
            utility_rect
            and int(utility_state.get("max_scroll", 0)) > 0
            and point_in_custom_panel_rect(
                mouse_x,
                mouse_y,
                utility_rect,
            )
        ):
            direction = self._event_direction(event, self.direction)
            if direction:
                if str(getattr(event, "type", "")) == "TRACKPADPAN":
                    raw_delta = abs(
                        int(getattr(event, "mouse_y", 0))
                        - int(getattr(event, "mouse_prev_y", 0))
                    )
                    distance = max(
                        _scale_overlay_value(
                            8,
                            _get_overlay_ui_scale(context),
                        ),
                        min(
                            _scale_overlay_value(
                                96,
                                _get_overlay_ui_scale(context),
                            ),
                            raw_delta * 3,
                        ),
                    )
                else:
                    distance = min(
                        float(utility_state.get("scroll_step", 72.0)),
                        float(
                            _scale_overlay_value(
                                72,
                                _get_overlay_ui_scale(context),
                            )
                        ),
                    )
                utility_state["scroll_target"] = max(
                    0.0,
                    min(
                        float(utility_state.get("max_scroll", 0.0)),
                        float(utility_state.get("scroll_target", 0.0))
                        + (direction * distance),
                    ),
                )
                _schedule_viewport_utility_scroll_animation()
            return {"FINISHED"}
        state = _viewport_custom_panel_state(region)
        if state is None or not point_in_custom_panel_rect(
            mouse_x,
            mouse_y,
            state.get("rect", {}),
        ):
            return {"PASS_THROUGH"}
        direction = self._event_direction(event, self.direction)
        if direction == 0:
            return {"PASS_THROUGH"}
        step = _scale_overlay_value(72, _get_overlay_ui_scale(context))
        if str(getattr(event, "type", "")) == "TRACKPADPAN":
            delta = int(getattr(event, "mouse_y", 0)) - int(
                getattr(event, "mouse_prev_y", 0)
            )
            if delta == 0:
                return {"PASS_THROUGH"}
            direction = -1 if delta > 0 else 1
            step = max(
                _scale_overlay_value(18, _get_overlay_ui_scale(context)),
                min(
                    _scale_overlay_value(120, _get_overlay_ui_scale(context)),
                    abs(delta) * 3,
                ),
            )
        state["scroll"] = max(
            0,
            min(
                int(state.get("max_scroll", 0)),
                int(state.get("scroll", 0)) + (direction * step),
            ),
        )
        area.tag_redraw()
        return {"FINISHED"}


class SILICONE_OT_keep_native_sidebar_hidden(bpy.types.Operator):
    bl_idname = "silicone.keep_native_sidebar_hidden"
    bl_label = "Moldboxer Panel"
    bl_options = {"INTERNAL"}

    def invoke(self, context, _event):
        space = getattr(context, "space_data", None)
        area = getattr(context, "area", None)
        if (
            space is None
            or area is None
            or getattr(area, "type", "") != "VIEW_3D"
        ):
            return {"PASS_THROUGH"}
        if hasattr(space, "show_region_ui"):
            space.show_region_ui = False
        area.tag_redraw()
        return {"FINISHED"}


def _set_view3d_sidebar_alignment(window, area, region, target_alignment):
    current_alignment = str(getattr(region, "alignment", ""))
    if current_alignment == target_alignment:
        return True
    if {current_alignment, target_alignment} != {"LEFT", "RIGHT"}:
        return False
    try:
        with bpy.context.temp_override(
            window=window,
            area=area,
            region=region,
        ):
            result = bpy.ops.screen.region_flip()
    except (AttributeError, RuntimeError, TypeError):
        return False
    return "FINISHED" in result and str(
        getattr(region, "alignment", "")
    ) == target_alignment


def configure_view3d_ui(space, area=None, window=None):
    if space is None or getattr(space, "type", "") != "VIEW_3D":
        return

    space_key = space.as_pointer()
    overlay = getattr(space, "overlay", None)
    if overlay is not None and hasattr(overlay, "show_text"):
        if space_key not in _VIEW3D_OVERLAY_TEXT_VISIBILITY:
            _VIEW3D_OVERLAY_TEXT_VISIBILITY[space_key] = bool(
                overlay.show_text
            )
        if overlay.show_text:
            overlay.show_text = False

    if hasattr(space, "show_region_header"):
        if space_key not in _VIEW3D_HEADER_VISIBILITY:
            _VIEW3D_HEADER_VISIBILITY[space_key] = bool(
                space.show_region_header
            )
        if space.show_region_header:
            space.show_region_header = False

    if hasattr(space, "show_region_tool_header"):
        if space_key not in _VIEW3D_TOOL_HEADER_VISIBILITY:
            _VIEW3D_TOOL_HEADER_VISIBILITY[space_key] = bool(
                space.show_region_tool_header
            )
        if space.show_region_tool_header:
            space.show_region_tool_header = False

    if hasattr(space, "show_region_toolbar"):
        if space_key not in _VIEW3D_TOOLBAR_VISIBILITY:
            _VIEW3D_TOOLBAR_VISIBILITY[space_key] = bool(
                space.show_region_toolbar
            )
        if space.show_region_toolbar:
            space.show_region_toolbar = False

    if hasattr(space, "show_region_ui"):
        if space_key not in _VIEW3D_SIDEBAR_VISIBILITY:
            _VIEW3D_SIDEBAR_VISIBILITY[space_key] = bool(
                space.show_region_ui
            )
        if not space.show_region_ui:
            space.show_region_ui = True

    if hasattr(space, "show_gizmo_navigate"):
        if space_key not in _VIEW3D_NAVIGATION_GIZMO_VISIBILITY:
            _VIEW3D_NAVIGATION_GIZMO_VISIBILITY[space_key] = bool(
                space.show_gizmo_navigate
            )
        if space.show_gizmo_navigate:
            space.show_gizmo_navigate = False

    for region in getattr(area, "regions", ()) if area is not None else ():
        if getattr(region, "type", "") != "UI":
            continue
        region_key = region.as_pointer()
        if region_key not in _VIEW3D_SIDEBAR_ALIGNMENTS:
            _VIEW3D_SIDEBAR_ALIGNMENTS[region_key] = str(
                getattr(region, "alignment", "")
            )
        if window is not None:
            _set_view3d_sidebar_alignment(
                window,
                area,
                region,
                "LEFT",
            )
        if not hasattr(region, "active_panel_category"):
            continue
        if region_key not in _VIEW3D_SIDEBAR_CATEGORIES:
            _VIEW3D_SIDEBAR_CATEGORIES[region_key] = str(
                getattr(region, "active_panel_category", "")
            )
        try:
            region.active_panel_category = "Moldboxer"
        except (AttributeError, TypeError):
            pass
        region.tag_redraw()


def _deferred_configure_view3d_ui():
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()) if window_manager else ():
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            configure_view3d_ui(
                getattr(getattr(area, "spaces", None), "active", None),
                area,
                window,
            )
            area.tag_redraw()
    # Configure once at startup; preserve subsequent sidebar choices.
    return None


def register_view3d_header_controls():
    global _VIEW3D_HEADER_CONTROLS_REGISTERED
    global _ORIGINAL_VIEW3D_HEADER_DRAW
    global _ORIGINAL_TOPBAR_HEADER_DRAW
    global _VIEWPORT_ACTION_BAR_DRAW_HANDLER
    global _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER
    global _VIEWPORT_UTILS_LABEL_DRAW_HANDLER
    global _VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER
    global _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER
    global _NAVIGATION_CONTROLS_WERE_VISIBLE
    if _VIEW3D_HEADER_CONTROLS_REGISTERED:
        return

    primary_header = getattr(bpy.types, "VIEW3D_HT_header", None)
    if primary_header is None:
        return
    _ORIGINAL_VIEW3D_HEADER_DRAW = primary_header.draw
    primary_header.draw = draw_moldboxer_viewport_tools_header
    topbar_header = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if topbar_header is not None:
        _ORIGINAL_TOPBAR_HEADER_DRAW = topbar_header.draw
        topbar_header.draw = draw_moldboxer_topbar
        topbar_header.append(draw_moldboxer_topbar_controls)
    view_preferences = getattr(
        getattr(bpy.context, "preferences", None),
        "view",
        None,
    )
    if (
        view_preferences is not None
        and hasattr(view_preferences, "show_navigate_ui")
    ):
        if _NAVIGATION_CONTROLS_WERE_VISIBLE is None:
            _NAVIGATION_CONTROLS_WERE_VISIBLE = bool(
                view_preferences.show_navigate_ui
            )
        view_preferences.show_navigate_ui = False
    _VIEWPORT_ACTION_BAR_DRAW_HANDLER = bpy.types.SpaceView3D.draw_handler_add(
        _draw_viewport_action_bar,
        (),
        "WINDOW",
        "POST_PIXEL",
    )
    _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER = (
        bpy.types.SpaceView3D.draw_handler_add(
            _draw_viewport_utility_cards,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
    )
    _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER = None
    window_manager = getattr(bpy.context, "window_manager", None)
    addon_keyconfig = getattr(
        getattr(window_manager, "keyconfigs", None),
        "addon",
        None,
    )
    if addon_keyconfig is not None:
        window_keymap = addon_keyconfig.keymaps.new(
            name="3D View",
            space_type="VIEW_3D",
        )
        # The main viewport has no "User Interface" keymap handler. Its
        # active/fallback tool maps run before "3D View", and selection there
        # can deselect the target before the overlay gets a chance to hit-test.
        # Cover both tool orders (Blender swaps them with visible gizmos).
        click_keymaps = [window_keymap]
        for tool_name in (
            "Move", "Rotate", "Scale", "Tweak", "Select Box",
            "Select Circle", "Select Lasso", "Tweak (fallback)",
            "Select Box (fallback)", "Select Circle (fallback)",
            "Select Lasso (fallback)",
        ):
            click_keymaps.append(addon_keyconfig.keymaps.new(
                name=f"3D View Tool: {tool_name}",
                space_type="VIEW_3D",
                region_type="WINDOW",
                tool=True,
            ))
        for click_keymap in click_keymaps:
            keymap_item = click_keymap.keymap_items.new(
                SILICONE_OT_viewport_action_bar_click.bl_idname,
                type="LEFTMOUSE",
                value="PRESS",
                any=True,
                head=True,
            )
            _VIEWPORT_ACTION_BAR_KEYMAPS.append((click_keymap, keymap_item))
        for event_type, direction, event_value in (
            ("WHEELUPMOUSE", -1, "PRESS"),
            ("WHEELDOWNMOUSE", 1, "PRESS"),
            ("TRACKPADPAN", 0, "ANY"),
        ):
            scroll_keymap_item = window_keymap.keymap_items.new(
                SILICONE_OT_viewport_overlay_scroll.bl_idname,
                type=event_type,
                value=event_value,
                head=True,
            )
            scroll_keymap_item.properties.direction = direction
            _VIEWPORT_ACTION_BAR_KEYMAPS.append(
                (window_keymap, scroll_keymap_item)
            )
        escape_keymap_item = window_keymap.keymap_items.new(
            SILICONE_OT_exit_measure_tool.bl_idname,
            type="ESC",
            value="PRESS",
            head=True,
        )
        _VIEWPORT_ACTION_BAR_KEYMAPS.append(
            (window_keymap, escape_keymap_item)
        )

        hover_keymap_item = window_keymap.keymap_items.new(
            SILICONE_OT_viewport_action_bar_hover.bl_idname,
            type="MOUSEMOVE",
            value="ANY",
            head=True,
        )
        _VIEWPORT_ACTION_BAR_KEYMAPS.append(
            (window_keymap, hover_keymap_item)
        )
    _VIEW3D_HEADER_CONTROLS_REGISTERED = True

    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if not callable(is_registered) or not is_registered(
        _deferred_configure_view3d_ui
    ):
        bpy.app.timers.register(
            _deferred_configure_view3d_ui,
            first_interval=0.1,
        )


def unregister_view3d_header_controls():
    global _VIEW3D_HEADER_CONTROLS_REGISTERED
    global _ORIGINAL_VIEW3D_HEADER_DRAW
    global _ORIGINAL_TOPBAR_HEADER_DRAW
    global _VIEWPORT_ACTION_BAR_DRAW_HANDLER
    global _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER
    global _VIEWPORT_UTILS_LABEL_DRAW_HANDLER
    global _VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER
    global _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER
    global _NAVIGATION_CONTROLS_WERE_VISIBLE
    if not _VIEW3D_HEADER_CONTROLS_REGISTERED:
        return

    for keymap, keymap_item in reversed(_VIEWPORT_ACTION_BAR_KEYMAPS):
        try:
            keymap.keymap_items.remove(keymap_item)
        except Exception:
            pass
    _VIEWPORT_ACTION_BAR_KEYMAPS.clear()
    if _VIEWPORT_ACTION_BAR_DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _VIEWPORT_ACTION_BAR_DRAW_HANDLER,
                "WINDOW",
            )
        except Exception:
            pass
        _VIEWPORT_ACTION_BAR_DRAW_HANDLER = None
    if _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER,
                "WINDOW",
            )
        except Exception:
            pass
        _VIEWPORT_UTILITY_COLUMN_DRAW_HANDLER = None
    if _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER,
                "WINDOW",
            )
        except Exception:
            pass
        _VIEWPORT_TRANSFORM_PANEL_DRAW_HANDLER = None
    if _VIEWPORT_UTILS_LABEL_DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _VIEWPORT_UTILS_LABEL_DRAW_HANDLER,
                "WINDOW",
            )
        except Exception:
            pass
        _VIEWPORT_UTILS_LABEL_DRAW_HANDLER = None
    if _VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(
                _VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER,
                "WINDOW",
            )
        except Exception:
            pass
        _VIEWPORT_CUSTOM_PANEL_DRAW_HANDLER = None
    primary_header = getattr(bpy.types, "VIEW3D_HT_header", None)
    topbar_header = getattr(bpy.types, "TOPBAR_HT_upper_bar", None)
    if topbar_header is not None:
        try:
            topbar_header.remove(draw_moldboxer_topbar_controls)
        except Exception:
            pass
        try:
            if _ORIGINAL_TOPBAR_HEADER_DRAW is not None:
                topbar_header.draw = _ORIGINAL_TOPBAR_HEADER_DRAW
        except Exception:
            pass
    try:
        if primary_header is not None and _ORIGINAL_VIEW3D_HEADER_DRAW is not None:
            primary_header.draw = _ORIGINAL_VIEW3D_HEADER_DRAW
    except Exception:
        pass
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _deferred_configure_view3d_ui
    ):
        bpy.app.timers.unregister(_deferred_configure_view3d_ui)
    view_preferences = getattr(
        getattr(bpy.context, "preferences", None),
        "view",
        None,
    )
    if (
        _NAVIGATION_CONTROLS_WERE_VISIBLE is not None
        and view_preferences is not None
        and hasattr(view_preferences, "show_navigate_ui")
    ):
        view_preferences.show_navigate_ui = _NAVIGATION_CONTROLS_WERE_VISIBLE
    _NAVIGATION_CONTROLS_WERE_VISIBLE = None
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()) if window_manager else ():
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", "") != "VIEW_3D":
                continue
            space = getattr(getattr(area, "spaces", None), "active", None)
            if space is None:
                continue
            space_key = space.as_pointer()
            header_was_visible = _VIEW3D_HEADER_VISIBILITY.get(space_key)
            tool_header_was_visible = _VIEW3D_TOOL_HEADER_VISIBILITY.get(
                space_key
            )
            toolbar_was_visible = _VIEW3D_TOOLBAR_VISIBILITY.get(space_key)
            sidebar_was_visible = _VIEW3D_SIDEBAR_VISIBILITY.get(space_key)
            navigation_gizmo_was_visible = (
                _VIEW3D_NAVIGATION_GIZMO_VISIBILITY.get(space_key)
            )
            overlay_text_was_visible = _VIEW3D_OVERLAY_TEXT_VISIBILITY.get(
                space_key
            )
            sidebar_alignment_was_changed = any(
                _VIEW3D_SIDEBAR_ALIGNMENTS.get(region.as_pointer()) is not None
                for region in getattr(area, "regions", ())
                if getattr(region, "type", "") == "UI"
            )
            if (
                header_was_visible is None
                and tool_header_was_visible is None
                and toolbar_was_visible is None
                and sidebar_was_visible is None
                and navigation_gizmo_was_visible is None
                and overlay_text_was_visible is None
                and not sidebar_alignment_was_changed
            ):
                continue
            try:
                if (
                    header_was_visible is not None
                    and hasattr(space, "show_region_header")
                ):
                    space.show_region_header = header_was_visible
                if (
                    tool_header_was_visible is not None
                    and hasattr(space, "show_region_tool_header")
                ):
                    space.show_region_tool_header = tool_header_was_visible
                if (
                    toolbar_was_visible is not None
                    and hasattr(space, "show_region_toolbar")
                ):
                    space.show_region_toolbar = toolbar_was_visible
                if (
                    sidebar_was_visible is not None
                    and hasattr(space, "show_region_ui")
                ):
                    space.show_region_ui = sidebar_was_visible
                if (
                    navigation_gizmo_was_visible is not None
                    and hasattr(space, "show_gizmo_navigate")
                ):
                    space.show_gizmo_navigate = navigation_gizmo_was_visible
                overlay = getattr(space, "overlay", None)
                if (
                    overlay_text_was_visible is not None
                    and overlay is not None
                    and hasattr(overlay, "show_text")
                ):
                    overlay.show_text = overlay_text_was_visible
                for region in getattr(area, "regions", ()):
                    if getattr(region, "type", "") != "UI":
                        continue
                    category = _VIEW3D_SIDEBAR_CATEGORIES.get(
                        region.as_pointer()
                    )
                    if category is not None and hasattr(
                        region, "active_panel_category"
                    ):
                        region.active_panel_category = category
                    original_alignment = _VIEW3D_SIDEBAR_ALIGNMENTS.get(
                        region.as_pointer()
                    )
                    if original_alignment in {"LEFT", "RIGHT"}:
                        _set_view3d_sidebar_alignment(
                            window,
                            area,
                            region,
                            original_alignment,
                        )
                    region.tag_redraw()
                area.tag_redraw()
            except Exception:
                pass
    _VIEW3D_HEADER_VISIBILITY.clear()
    _VIEW3D_TOOL_HEADER_VISIBILITY.clear()
    _VIEW3D_TOOLBAR_VISIBILITY.clear()
    _VIEW3D_SIDEBAR_VISIBILITY.clear()
    _VIEW3D_SIDEBAR_CATEGORIES.clear()
    _VIEW3D_SIDEBAR_ALIGNMENTS.clear()
    _VIEW3D_NAVIGATION_GIZMO_VISIBILITY.clear()
    _VIEW3D_OVERLAY_TEXT_VISIBILITY.clear()
    _VIEWPORT_CUSTOM_PANEL_STATES.clear()
    _VIEWPORT_UTILITY_COLUMN_STATES.clear()
    _VIEWPORT_CUSTOM_PANEL_HEADER_STATES.clear()
    _ORIGINAL_VIEW3D_HEADER_DRAW = None
    _ORIGINAL_TOPBAR_HEADER_DRAW = None
    _VIEW3D_HEADER_CONTROLS_REGISTERED = False


def _custom_panel_preview_path(icon_value, data=None, prop_name=""):
    previews = preview_collections.get("main")
    if previews is None:
        return ""

    key = ""
    if data is not None and prop_name:
        try:
            identifier = str(getattr(data, prop_name))
        except Exception:
            identifier = ""
        if prop_name == "mold_type_picker" and identifier:
            key = get_mold_type(identifier).preview_name
        else:
            prefix_by_picker = {
                "shape_type_picker": "shape_type_",
                "slip_casting_funnel_picker": "slip_casting_funnel_",
                "slip_casting_base_picker": "slip_casting_base_",
                "slip_casting_master_base_picker": "slip_casting_master_base_",
                "silicone_multipart_opening_picker": "silicone_multipart_opening_",
                "funnel_type_picker": "funnel_",
                "channel_adjustment_picker": "channel_adjustment_",
                "clamp_pin_type_picker": "clamp_pin_type_",
                "master_attachment_picker": "master_attachment_",
                "tray_type_picker": "tray_type_",
                "base_type_picker": "base_type_",
                "casting_box_type_picker": "casting_box_type_",
                "inner_cavity_core_type_picker": "inner_cavity_core_type_",
            }
            prefix = prefix_by_picker.get(prop_name, "")
            if prefix and identifier:
                key = f"{prefix}{identifier}"
        if key and key in _panel_preview_paths:
            return _panel_preview_paths[key]

    if icon_value:
        for preview_key, path in _panel_preview_paths.items():
            try:
                preview = previews.get(preview_key)
                if preview is not None and int(preview.icon_id) == int(icon_value):
                    return path
            except (ReferenceError, TypeError, ValueError):
                continue
    return ""


set_custom_panel_preview_path_resolver(_custom_panel_preview_path)


def _preview_for_mold_type(mold_type):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(mold_type.preview_name)


def _preview_for_funnel_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"funnel_{identifier}")


def _preview_for_channel_adjustment(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"channel_adjustment_{identifier}")


def _preview_for_master_smart_sealer():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("master_smart_sealer")


def _preview_for_master_air_trap_pillars():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("master_air_trap_pillars")


def _preview_for_clear_undercuts():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("clear_undercuts")


def _preview_for_casting_feet():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("casting_feet")


def _preview_for_casting_grip():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("casting_grip")


def _preview_for_tray_grip():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("tray_grip")


def _preview_for_tray_casting_volume():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("tray_casting_volume")


def _preview_for_casting_pilars():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("casting_pilars")


def _preview_for_silicone_support_pilars():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("silicone_support_pilars")


def _preview_for_direct_top_funnel_settings():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("direct_top_funnel_settings")


def _preview_for_grid():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("grid")


def _preview_for_hollow():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("hollow")


def _preview_for_convert_to_planter():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("convert_to_planter")


def _preview_for_casting_sprue():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("casting_sprue")


def _preview_for_watermark_reference():
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get("watermark_reference")


def _preview_for_base_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"base_type_{identifier}")


def _preview_for_casting_box_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"casting_box_type_{identifier}")


def _preview_for_inner_cavity_core_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"inner_cavity_core_type_{identifier}")


def _preview_for_master_attachment(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"master_attachment_{identifier}")


def _preview_for_tray_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"tray_type_{identifier}")


def _preview_for_pin_type(target, identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"{target.lower()}_pin_type_{identifier}")


def _preview_for_shape_type(identifier):
    previews = preview_collections.get("main")
    if previews is None:
        return None
    return previews.get(f"shape_type_{identifier}")


def _selector_option_label(label):
    return SELECTOR_OPTION_LABELS.get(label, label)


def _shape_type_picker_items(self, context):
    global _shape_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        SHAPE_TYPES
    ):
        preview = _preview_for_shape_type(identifier)
        items.append(
            (
                identifier,
                t(label),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _shape_type_picker_items_cache = tuple(items)
    return _shape_type_picker_items_cache


def _active_shape_type_property(scene):
    mold_type = get_mold_type(scene.mold_type_preview).identifier
    if is_multipart_type(scene.mold_type_preview):
        return "slip_casting_shape_type"
    if mold_type == "FIXTURE":
        return "fixture_shape_type"
    if mold_type == "PROTECTIVE_SHELL":
        return "protective_shell_shape_type"
    return "mold_box_shape_type"


def _update_shape_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    scene_property = _active_shape_type_property(scene)
    selected_identifier = window_manager.shape_type_picker
    if (
        scene_property is not None
        and selected_identifier in SHAPE_TYPE_IDS
        and getattr(scene, scene_property) != selected_identifier
    ):
        setattr(scene, scene_property, selected_identifier)


bpy.types.WindowManager.shape_type_picker = bpy.props.EnumProperty(
    name=t("Shape Type"),
    description="",
    items=_shape_type_picker_items,
    update=_update_shape_type_picker,
)


def _sync_shape_type_picker(context, scene_property):
    selected_identifier = getattr(context.scene, scene_property)
    if selected_identifier not in SHAPE_TYPE_IDS:
        selected_identifier = "adapted"
    try:
        picker_identifier = context.window_manager.shape_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.shape_type_picker = selected_identifier


def _funnel_type_picker_items(self, context):
    global _funnel_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename) in enumerate(FUNNEL_TYPES):
        preview = _preview_for_funnel_type(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                "",
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _funnel_type_picker_items_cache = tuple(items)
    return _funnel_type_picker_items_cache


def _update_funnel_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.funnel_type_picker
    if (
        selected_identifier in FUNNEL_TYPE_IDS
        and scene.funneler != selected_identifier
    ):
        scene.funneler = selected_identifier


bpy.types.WindowManager.funnel_type_picker = bpy.props.EnumProperty(
    name=t("Funnel Type"),
    description="",
    items=_funnel_type_picker_items,
    update=_update_funnel_type_picker,
)


def _sync_funnel_type_picker(context):
    selected_identifier = context.scene.funneler
    if selected_identifier not in FUNNEL_TYPE_IDS:
        selected_identifier = FUNNEL_TYPES[0][0]
    try:
        picker_identifier = context.window_manager.funnel_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.funnel_type_picker = selected_identifier


def _channel_adjustment_picker_items(self, context):
    global _channel_adjustment_picker_items_cache

    items = []
    for index, (
        identifier,
        label,
        _filename,
        description,
    ) in enumerate(CHANNEL_ADJUSTMENTS):
        preview = _preview_for_channel_adjustment(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _channel_adjustment_picker_items_cache = tuple(items)
    return _channel_adjustment_picker_items_cache


def _update_channel_adjustment_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.channel_adjustment_picker
    if (
        selected_identifier in CHANNEL_ADJUSTMENT_IDS
        and scene.channel_adjustment != selected_identifier
    ):
        scene.channel_adjustment = selected_identifier


bpy.types.WindowManager.channel_adjustment_picker = bpy.props.EnumProperty(
    name=t("Channel Adjustment"),
    description="",
    items=_channel_adjustment_picker_items,
    update=_update_channel_adjustment_picker,
)


def _sync_channel_adjustment_picker(context):
    selected_identifier = context.scene.channel_adjustment
    if selected_identifier not in CHANNEL_ADJUSTMENT_IDS:
        selected_identifier = CHANNEL_ADJUSTMENTS[0][0]
    try:
        picker_identifier = context.window_manager.channel_adjustment_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.channel_adjustment_picker = selected_identifier


def _clamp_pin_type_picker_items(self, context):
    global _clamp_pin_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        CLAMP_PIN_TYPES
    ):
        preview = _preview_for_pin_type("CLAMP", identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _clamp_pin_type_picker_items_cache = tuple(items)
    return _clamp_pin_type_picker_items_cache


def _update_clamp_pin_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.clamp_pin_type_picker
    valid_identifiers = {
        identifier
        for identifier, _label, _filename, _description in CLAMP_PIN_TYPES
    }
    if (
        selected_identifier in valid_identifiers
        and scene.clamp_pin_type != selected_identifier
    ):
        scene.clamp_pin_type = selected_identifier


bpy.types.WindowManager.clamp_pin_type_picker = bpy.props.EnumProperty(
    name=t("Clamp Lock"),
    description="",
    items=_clamp_pin_type_picker_items,
    update=_update_clamp_pin_type_picker,
)


def _sync_clamp_pin_type_picker(context):
    selected_identifier = context.scene.clamp_pin_type
    valid_identifiers = {
        identifier
        for identifier, _label, _filename, _description in CLAMP_PIN_TYPES
    }
    if selected_identifier not in valid_identifiers:
        selected_identifier = CLAMP_PIN_TYPES[0][0]
    try:
        picker_identifier = context.window_manager.clamp_pin_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.clamp_pin_type_picker = selected_identifier


def _master_attachment_picker_items(self, context):
    global _master_attachment_picker_items_cache

    items = []
    for index, (
        identifier,
        label,
        _filename,
        _is_fixed,
    ) in enumerate(MASTER_ATTACHMENT_TYPES):
        preview = _preview_for_master_attachment(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                "",
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _master_attachment_picker_items_cache = tuple(items)
    return _master_attachment_picker_items_cache


def _tray_type_picker_items(self, context):
    global _tray_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        TRAY_TYPES
    ):
        preview = _preview_for_tray_type(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _tray_type_picker_items_cache = tuple(items)
    return _tray_type_picker_items_cache


def _update_tray_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.tray_type_picker
    if (
        selected_identifier in TRAY_TYPE_IDS
        and scene.tray_type != selected_identifier
    ):
        scene.tray_type = selected_identifier


bpy.types.WindowManager.tray_type_picker = bpy.props.EnumProperty(
    name=t("Tray Type"),
    description="",
    items=_tray_type_picker_items,
    update=_update_tray_type_picker,
)


def _sync_tray_type_picker(context):
    selected_identifier = context.scene.tray_type
    if selected_identifier not in TRAY_TYPE_IDS:
        selected_identifier = "OPTIMIZED"
    try:
        picker_identifier = context.window_manager.tray_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.tray_type_picker = selected_identifier


def _ensure_unfixed_master_backup(scene):
    if (
        not is_multipart_type(scene.mold_type_preview)
        and not bool(scene.wing_join_patron)
    ):
        ensure_direct_patron_backup()


def _update_master_attachment_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.master_attachment_picker
    if selected_identifier not in MASTER_ATTACHMENT_TYPE_IDS:
        return
    is_fixed = selected_identifier == "FIXED"
    if bool(scene.wing_join_patron) != is_fixed:
        scene.wing_join_patron = is_fixed
    _ensure_unfixed_master_backup(scene)


bpy.types.WindowManager.master_attachment_picker = bpy.props.EnumProperty(
    name=t("Fixed Master"),
    description="",
    items=_master_attachment_picker_items,
    update=_update_master_attachment_picker,
)


def _sync_master_attachment_picker(context):
    selected_identifier = (
        "FIXED" if context.scene.wing_join_patron else "UNFIXED"
    )
    try:
        picker_identifier = context.window_manager.master_attachment_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.master_attachment_picker = selected_identifier


def _base_type_picker_items(self, context):
    global _base_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        BASE_TYPES
    ):
        preview = _preview_for_base_type(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _base_type_picker_items_cache = tuple(items)
    return _base_type_picker_items_cache


def _update_base_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.base_type_picker
    if (
        selected_identifier in BASE_TYPE_IDS
        and scene.base_type != selected_identifier
    ):
        scene.base_type = selected_identifier


bpy.types.WindowManager.base_type_picker = bpy.props.EnumProperty(
    name=t("Base Type"),
    description="",
    items=_base_type_picker_items,
    update=_update_base_type_picker,
)


def _sync_base_type_picker(context):
    selected_identifier = context.scene.base_type
    if selected_identifier not in BASE_TYPE_IDS:
        selected_identifier = BASE_TYPES[0][0]
    try:
        picker_identifier = context.window_manager.base_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.base_type_picker = selected_identifier


def _casting_box_type_picker_items(self, context):
    global _casting_box_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        CASTING_BOX_TYPES
    ):
        preview = _preview_for_casting_box_type(identifier)
        items.append(
            (
                identifier,
                t(_selector_option_label(label)),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _casting_box_type_picker_items_cache = tuple(items)
    return _casting_box_type_picker_items_cache


def _update_casting_box_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.casting_box_type_picker
    if (
        selected_identifier in CASTING_BOX_TYPE_IDS
        and scene.pro_casting_box_type != selected_identifier
    ):
        scene.pro_casting_box_type = selected_identifier


bpy.types.WindowManager.casting_box_type_picker = bpy.props.EnumProperty(
    name=t("Casting Box Type"),
    description="",
    items=_casting_box_type_picker_items,
    update=_update_casting_box_type_picker,
)


def _sync_casting_box_type_picker(context):
    selected_identifier = get_effective_casting_box_type(context.scene)
    if selected_identifier not in CASTING_BOX_TYPE_IDS:
        selected_identifier = CASTING_BOX_TYPES[0][0]
    try:
        picker_identifier = context.window_manager.casting_box_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.casting_box_type_picker = selected_identifier


def _inner_cavity_core_type_picker_items(self, context):
    global _inner_cavity_core_type_picker_items_cache

    items = []
    for index, (identifier, label, _filename, description) in enumerate(
        INNER_CAVITY_CORE_TYPES
    ):
        preview = _preview_for_inner_cavity_core_type(identifier)
        items.append(
            (
                identifier,
                t(label),
                t(description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _inner_cavity_core_type_picker_items_cache = tuple(items)
    return _inner_cavity_core_type_picker_items_cache


def _update_inner_cavity_core_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    selected_identifier = window_manager.inner_cavity_core_type_picker
    scene_property = (
        "direct_skin_core_type"
        if get_mold_type(scene.mold_type_preview).identifier == "DIRECT_MOLD_SKIN"
        else "pro_inner_cavity_core_type"
    )
    if (
        selected_identifier in INNER_CAVITY_CORE_TYPE_IDS
        and getattr(scene, scene_property) != selected_identifier
    ):
        setattr(scene, scene_property, selected_identifier)


bpy.types.WindowManager.inner_cavity_core_type_picker = bpy.props.EnumProperty(
    name=t("Core Type"),
    description="",
    items=_inner_cavity_core_type_picker_items,
    update=_update_inner_cavity_core_type_picker,
)


def _sync_inner_cavity_core_type_picker(context):
    scene_property = (
        "direct_skin_core_type"
        if get_mold_type(context.scene.mold_type_preview).identifier
        == "DIRECT_MOLD_SKIN"
        else "pro_inner_cavity_core_type"
    )
    selected_identifier = getattr(context.scene, scene_property)
    if selected_identifier not in INNER_CAVITY_CORE_TYPE_IDS:
        selected_identifier = INNER_CAVITY_CORE_TYPES[0][0]
    try:
        picker_identifier = context.window_manager.inner_cavity_core_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        context.window_manager.inner_cavity_core_type_picker = selected_identifier


def _mold_type_picker_items(self, context):
    global _mold_type_picker_items_cache

    items = []
    for index, mold_type in enumerate(MOLD_TYPE_OPTIONS):
        preview = _preview_for_mold_type(mold_type)
        items.append(
            (
                mold_type.identifier,
                t(mold_type.label),
                t(mold_type.description),
                preview.icon_id if preview is not None else 0,
                index,
            )
        )
    _mold_type_picker_items_cache = tuple(items)
    return _mold_type_picker_items_cache


def _update_mold_type_picker(window_manager, context):
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    previous_identifier = get_mold_type(scene.mold_type_preview).identifier
    selected_type = get_mold_type(window_manager.mold_type_picker)
    if previous_identifier != selected_type.identifier:
        scene.mold_type_preview = selected_type.identifier
        current_identifier = get_mold_type(scene.mold_type_preview).identifier
        if current_identifier != previous_identifier:
            bpy.ops.silicone.restart(
                reload_dev_addon=False,
                preserve_slip_casting_vase_bases=False,
            )


bpy.types.WindowManager.mold_type_picker = bpy.props.EnumProperty(
    name=t("Mold Type"),
    description="",
    items=_mold_type_picker_items,
    update=_update_mold_type_picker,
)


def _sync_mold_type_picker(context):
    window_manager = context.window_manager
    selected_identifier = get_mold_type(
        context.scene.mold_type_preview
    ).identifier
    visible_identifiers = {
        mold_type.identifier for mold_type in MOLD_TYPE_OPTIONS
    }
    if selected_identifier not in visible_identifiers:
        # Preserve hidden legacy/work-in-progress mold identifiers in the
        # scene without trying to assign an unavailable picker enum item.
        return
    try:
        picker_identifier = window_manager.mold_type_picker
    except Exception:
        picker_identifier = ""
    if picker_identifier != selected_identifier:
        window_manager.mold_type_picker = selected_identifier


def _draw_mold_type_icon_view(layout, context, *, scale):
    _sync_mold_type_picker(context)
    window = getattr(context, "window", None)
    preferences = getattr(context, "preferences", None)
    system_preferences = getattr(preferences, "system", None)
    window_width = max(int(getattr(window, "width", 0) or 0), 640)
    ui_scale = max(
        float(getattr(system_preferences, "ui_scale", 1.0) or 1.0),
        0.5,
    )
    mold_count = max(len(MOLD_TYPE_OPTIONS), 1)
    popup_margin = 96.0 * ui_scale
    item_gaps = max(mold_count - 1, 0) * 8.0 * ui_scale
    usable_width = max(window_width - popup_margin - item_gaps, 320.0)
    preview_pixels_per_scale = 24.0 * ui_scale
    popup_scale = usable_width / (mold_count * preview_pixels_per_scale)
    popup_scale = max(3.0, min(popup_scale, 12.0))

    layout.template_icon_view(
        context.window_manager,
        "mold_type_picker",
        show_labels=True,
        scale=scale,
        scale_popup=popup_scale,
    )


class SILICONE_OT_select_mold_type(bpy.types.Operator):
    bl_idname = "silicone.select_mold_type"
    bl_label = "Select Mold Type"
    bl_description = "Use this mold type for generation"
    bl_options = {"INTERNAL"}

    mold_type: bpy.props.EnumProperty(  # type: ignore
        name="Mold Type",
        items=MOLD_TYPE_ENUM_ITEMS,
    )
    continue_to_import: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    reset_direct_planes: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    clear_project_before_import: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    import_filepath: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN"},
    )
    detected_import_object: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN"},
    )

    @classmethod
    def description(cls, context, properties):
        mold_type = get_mold_type(getattr(properties, "mold_type", ""))
        return t(mold_type.description)

    def execute(self, context):
        detected_imported_object = bpy.data.objects.get(
            self.detected_import_object
        )
        if detected_imported_object is not None:
            live_object_pointers = {
                obj.as_pointer() for obj in bpy.data.objects
            }
            _accepted_detected_import_pointers.intersection_update(
                live_object_pointers
            )
            _accepted_detected_import_pointers.add(
                detected_imported_object.as_pointer()
            )
        previous_identifier = get_mold_type(
            context.scene.mold_type_preview
        ).identifier
        selected_type = get_mold_type(self.mold_type)
        context.scene.mold_type_preview = selected_type.identifier
        current_identifier = get_mold_type(
            context.scene.mold_type_preview
        ).identifier
        context.window_manager.mold_type_picker = current_identifier
        if current_identifier != previous_identifier:
            bpy.ops.silicone.restart(
                reload_dev_addon=False,
                keep_object_name=self.detected_import_object,
                preserve_slip_casting_vase_bases=False,
            )
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        # The mold cards run as child operators, so finishing this operator does
        # not finish the popup that owns them. Reassigning the current screen
        # refreshes Blender's UI and dismisses its active popup without relying
        # on event_simulate, which is disabled in normal Blender sessions.
        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen

        if detected_imported_object is not None:
            _schedule_detected_import_processing(detected_imported_object)
        elif self.continue_to_import:
            import_args = {
                "mold_type_confirmed": True,
                "reset_direct_planes": self.reset_direct_planes,
                "clear_project_before_import": self.clear_project_before_import,
            }
            if self.import_filepath:
                import_args["filepath"] = self.import_filepath
                bpy.ops.silicone.import_model("EXEC_DEFAULT", **import_args)
            else:
                bpy.ops.silicone.import_model("INVOKE_DEFAULT", **import_args)
        return {"FINISHED"}


class SILICONE_OT_change_mold_type(bpy.types.Operator):
    bl_idname = "silicone.change_mold_type"
    bl_label = "Change Mold Type"
    bl_description = "Choose the mold workflow to use"
    bl_options = {"INTERNAL"}

    continue_to_import: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    reset_direct_planes: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    clear_project_before_import: bpy.props.BoolProperty(  # type: ignore
        default=False,
        options={"HIDDEN"},
    )
    import_filepath: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN"},
    )
    detected_import_object: bpy.props.StringProperty(  # type: ignore
        default="",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=560)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Choose Generator"), icon="MOD_BOOLEAN")
        selected_identifier = get_mold_type(
            context.scene.mold_type_preview
        ).identifier
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for mold_type in MOLD_TYPE_OPTIONS:
            card = grid.box().column(align=True)
            preview = _preview_for_mold_type(mold_type)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="MOD_BOOLEAN")

            is_selected = mold_type.identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = (
                self.continue_to_import
                or bool(self.detected_import_object)
                or not is_selected
            )
            select = action.operator(
                "silicone.select_mold_type",
                text=t(mold_type.label),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.mold_type = mold_type.identifier
            select.continue_to_import = self.continue_to_import
            select.reset_direct_planes = self.reset_direct_planes
            select.clear_project_before_import = self.clear_project_before_import
            select.import_filepath = self.import_filepath
            select.detected_import_object = self.detected_import_object

    def execute(self, context):
        return {"FINISHED"}

    def cancel(self, context):
        if not self.detected_import_object:
            return
        imported_object = bpy.data.objects.get(self.detected_import_object)
        if imported_object is not None:
            if (
                imported_object.as_pointer()
                in _accepted_detected_import_pointers
            ):
                return
            # Cancelling the workflow picker must not destroy a model that was
            # already imported successfully.  Leave it visible so a dismissed
            # or context-cancelled popup never looks like a failed file drop.
            imported_object.hide_set(False)


class SILICONE_OT_select_master_attachment(bpy.types.Operator):
    bl_idname = "silicone.select_master_attachment"
    bl_label = "Select Master Attachment"
    bl_description = "Choose whether the master is joined to the base"
    bl_options = {"INTERNAL"}

    master_attachment: bpy.props.EnumProperty(  # type: ignore
        name="Master Attachment",
        items=tuple(
            (identifier, _selector_option_label(label), "")
            for identifier, label, _filename, _is_fixed
            in MASTER_ATTACHMENT_TYPES
        ),
    )

    def execute(self, context):
        if self.master_attachment not in MASTER_ATTACHMENT_TYPE_IDS:
            return {"CANCELLED"}

        context.scene.wing_join_patron = self.master_attachment == "FIXED"
        _ensure_unfixed_master_backup(context.scene)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_master_attachment(bpy.types.Operator):
    bl_idname = "silicone.change_master_attachment"
    bl_label = "Change Master Attachment"
    bl_description = "Choose whether the master is joined to the base"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Fixed Master"), icon="DECORATE_LOCKED")
        selected_identifier = (
            "FIXED" if context.scene.wing_join_patron else "UNFIXED"
        )
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for (
            identifier,
            label,
            _filename,
            _is_fixed,
        ) in MASTER_ATTACHMENT_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_master_attachment(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(
                    text="",
                    icon=(
                        "DECORATE_LOCKED"
                        if identifier == "FIXED"
                        else "DECORATE_UNLOCKED"
                    ),
                )

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_master_attachment",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.master_attachment = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_tray_type(bpy.types.Operator):
    bl_idname = "silicone.select_tray_type"
    bl_label = "Select Tray Type"
    bl_description = "Choose how the initial tray wrapper is generated"
    bl_options = {"INTERNAL"}

    tray_type: bpy.props.EnumProperty(  # type: ignore
        name="Tray Type",
        items=tuple(
            (identifier, _selector_option_label(label), description)
            for identifier, label, _filename, description in TRAY_TYPES
        ),
    )

    def execute(self, context):
        if self.tray_type not in TRAY_TYPE_IDS:
            return {"CANCELLED"}

        context.scene.tray_type = self.tray_type
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_tray_type(bpy.types.Operator):
    bl_idname = "silicone.change_tray_type"
    bl_label = "Change Tray Type"
    bl_description = "Choose how the initial tray wrapper is generated"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Tray Type"), icon="MOD_SMOOTH")
        selected_identifier = context.scene.tray_type
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename, _description in TRAY_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_tray_type(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="MOD_SMOOTH")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_tray_type",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.tray_type = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_pin_type(bpy.types.Operator):
    bl_idname = "silicone.select_pin_type"
    bl_label = "Select Pin Type"
    bl_description = "Use this locking system"
    bl_options = {"INTERNAL"}

    target: bpy.props.EnumProperty(  # type: ignore
        name="Target",
        items=(
            ("BASE", "Base Lock", ""),
            ("CLAMP", "Clamp Lock", ""),
        ),
    )
    pin_type: bpy.props.StringProperty(  # type: ignore
        name="Pin Type",
    )

    @classmethod
    def description(cls, context, properties):
        target = getattr(properties, "target", "")
        pin_type = getattr(properties, "pin_type", "")
        _prop_name, pin_types = PIN_TYPE_TARGETS.get(
            target,
            ("", ()),
        )
        for identifier, _label, _filename, description in pin_types:
            if identifier == pin_type:
                return t(description)
        return t(cls.bl_description)

    def execute(self, context):
        target_config = PIN_TYPE_TARGETS.get(self.target)
        if target_config is None:
            return {"CANCELLED"}
        prop_name, pin_types = target_config
        valid_identifiers = {
            identifier
            for identifier, _label, _filename, _description in pin_types
        }
        if self.pin_type not in valid_identifiers:
            return {"CANCELLED"}

        setattr(context.scene, prop_name, self.pin_type)
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_pin_type(bpy.types.Operator):
    bl_idname = "silicone.change_pin_type"
    bl_label = "Change Pin Type"
    bl_description = "Choose the locking system to use"
    bl_options = {"INTERNAL"}

    target: bpy.props.EnumProperty(  # type: ignore
        name="Target",
        items=(
            ("BASE", "Base Lock", ""),
            ("CLAMP", "Clamp Lock", ""),
        ),
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=720)

    def draw(self, context):
        target_config = PIN_TYPE_TARGETS.get(self.target)
        if target_config is None:
            return
        prop_name, pin_types = target_config
        selected_identifier = getattr(context.scene, prop_name)

        layout = self.layout
        layout.label(text=prop_label(prop_name), icon="PINNED")
        grid = layout.grid_flow(
            row_major=True,
            columns=len(pin_types),
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename, _description in pin_types:
            card = grid.box().column(align=True)
            preview = _preview_for_pin_type(self.target, identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=5.5)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 5.5
                empty_preview.label(
                    text="",
                    icon="X" if identifier == "none" else "PINNED",
                )

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_pin_type",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.target = self.target
            select.pin_type = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_funnel_type(bpy.types.Operator):
    bl_idname = "silicone.select_funnel_type"
    bl_label = "Select Funnel Type"
    bl_description = "Use this funnel type"
    bl_options = {"INTERNAL"}

    funnel_type: bpy.props.EnumProperty(  # type: ignore
        name="Funnel Type",
        items=tuple(
            (identifier, _selector_option_label(label), "")
            for identifier, label, _filename in FUNNEL_TYPES
        ),
    )

    def execute(self, context):
        if self.funnel_type not in FUNNEL_TYPE_IDS:
            return {"CANCELLED"}

        context.scene.funneler = self.funnel_type
        context.window_manager.funnel_type_picker = self.funnel_type
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_funnel_type(bpy.types.Operator):
    bl_idname = "silicone.change_funnel_type"
    bl_label = "Change Funnel Type"
    bl_description = "Choose the funnel shape to use"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Choose a Funnel Type"), icon="MESH_CYLINDER")
        selected_identifier = context.scene.funneler
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename in FUNNEL_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_funnel_type(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="MESH_CYLINDER")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_funnel_type",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.funnel_type = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_channel_adjustment(bpy.types.Operator):
    bl_idname = "silicone.select_channel_adjustment"
    bl_label = "Select Channel Adjustment"
    bl_description = "Use this channel adjustment"
    bl_options = {"INTERNAL"}

    channel_adjustment: bpy.props.EnumProperty(  # type: ignore
        name="Channel Adjustment",
        items=tuple(
            (identifier, _selector_option_label(label), description)
            for identifier, label, _filename, description in CHANNEL_ADJUSTMENTS
        ),
    )

    @classmethod
    def description(cls, context, properties):
        selected_identifier = getattr(properties, "channel_adjustment", "")
        for identifier, _label, _filename, description in CHANNEL_ADJUSTMENTS:
            if identifier == selected_identifier:
                return t(description)
        return t(cls.bl_description)

    def execute(self, context):
        if self.channel_adjustment not in CHANNEL_ADJUSTMENT_IDS:
            return {"CANCELLED"}

        context.scene.channel_adjustment = self.channel_adjustment
        context.window_manager.channel_adjustment_picker = (
            self.channel_adjustment
        )
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_channel_adjustment(bpy.types.Operator):
    bl_idname = "silicone.change_channel_adjustment"
    bl_label = "Change Channel Adjustment"
    bl_description = "Choose the channel adjustment to use"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=720)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text=t("Choose a Channel Adjustment"),
            icon="MOD_SMOOTH",
        )
        selected_identifier = context.scene.channel_adjustment
        grid = layout.grid_flow(
            row_major=True,
            columns=3,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename, _description in CHANNEL_ADJUSTMENTS:
            card = grid.box().column(align=True)
            preview = _preview_for_channel_adjustment(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=5.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 5.0
                empty_preview.label(text="", icon="MOD_SMOOTH")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_channel_adjustment",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.channel_adjustment = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_base_type(bpy.types.Operator):
    bl_idname = "silicone.select_base_type"
    bl_label = "Select Base Type"
    bl_description = "Use this base type"
    bl_options = {"INTERNAL"}

    base_type: bpy.props.EnumProperty(  # type: ignore
        name="Base Type",
        items=tuple(
            (identifier, _selector_option_label(label), description)
            for identifier, label, _filename, description in BASE_TYPES
        ),
    )

    @classmethod
    def description(cls, context, properties):
        selected_identifier = getattr(properties, "base_type", "")
        for identifier, _label, _filename, description in BASE_TYPES:
            if identifier == selected_identifier:
                return t(description)
        return t(cls.bl_description)

    def execute(self, context):
        if self.base_type not in BASE_TYPE_IDS:
            return {"CANCELLED"}

        context.scene.base_type = self.base_type
        context.window_manager.base_type_picker = self.base_type
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()

        window = getattr(context, "window", None)
        screen = getattr(window, "screen", None)
        if screen is not None:
            window.screen = screen
        return {"FINISHED"}


class SILICONE_OT_change_base_type(bpy.types.Operator):
    bl_idname = "silicone.change_base_type"
    bl_label = "Change Base Type"
    bl_description = "Choose the base style to use"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Choose a Base Type"), icon="AXIS_TOP")
        selected_identifier = context.scene.base_type
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename, _description in BASE_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_base_type(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="AXIS_TOP")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_base_type",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.base_type = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_casting_box_type(bpy.types.Operator):
    bl_idname = "silicone.select_casting_box_type"
    bl_label = "Select Casting Box Type"
    bl_description = "Use this casting box type"
    bl_options = {"INTERNAL"}

    casting_box_type: bpy.props.EnumProperty(  # type: ignore
        name="Casting Box Type",
        items=tuple(
            (identifier, _selector_option_label(label), description)
            for identifier, label, _filename, description in CASTING_BOX_TYPES
        ),
    )

    @classmethod
    def description(cls, context, properties):
        selected_identifier = getattr(properties, "casting_box_type", "")
        for identifier, _label, _filename, description in CASTING_BOX_TYPES:
            if identifier == selected_identifier:
                return t(description)
        return t(cls.bl_description)

    def execute(self, context):
        if self.casting_box_type not in CASTING_BOX_TYPE_IDS:
            return {"CANCELLED"}

        context.scene.pro_casting_box_type = self.casting_box_type
        context.window_manager.casting_box_type_picker = self.casting_box_type
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}


class SILICONE_OT_change_casting_box_type(bpy.types.Operator):
    bl_idname = "silicone.change_casting_box_type"
    bl_label = "Change Casting Box Type"
    bl_description = "Choose the casting box style to use"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Choose a Casting Box Type"), icon="MESH_CUBE")
        selected_identifier = get_effective_casting_box_type(context.scene)
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for identifier, label, _filename, _description in CASTING_BOX_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_casting_box_type(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="MESH_CUBE")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_casting_box_type",
                text=t(_selector_option_label(label)),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.casting_box_type = identifier

    def execute(self, context):
        return {"FINISHED"}


class SILICONE_OT_select_inner_cavity_core_type(bpy.types.Operator):
    bl_idname = "silicone.select_inner_cavity_core_type"
    bl_label = "Select Inner Core Type"
    bl_description = "Use this inner-core construction type"
    bl_options = {"INTERNAL"}

    core_type: bpy.props.EnumProperty(  # type: ignore
        name="Core Type",
        items=tuple(
            (identifier, label, description)
            for identifier, label, _filename, description
            in INNER_CAVITY_CORE_TYPES
        ),
    )

    @classmethod
    def description(cls, context, properties):
        selected_identifier = getattr(properties, "core_type", "")
        for (
            identifier,
            _label,
            _filename,
            description,
        ) in INNER_CAVITY_CORE_TYPES:
            if identifier == selected_identifier:
                return t(description)
        return t(cls.bl_description)

    def execute(self, context):
        if self.core_type not in INNER_CAVITY_CORE_TYPE_IDS:
            return {"CANCELLED"}

        scene_property = (
            "direct_skin_core_type"
            if get_mold_type(context.scene.mold_type_preview).identifier
            == "DIRECT_MOLD_SKIN"
            else "pro_inner_cavity_core_type"
        )
        setattr(context.scene, scene_property, self.core_type)
        context.window_manager.inner_cavity_core_type_picker = self.core_type
        area = getattr(context, "area", None)
        if area is not None:
            area.tag_redraw()
        return {"FINISHED"}


class SILICONE_OT_change_inner_cavity_core_type(bpy.types.Operator):
    bl_idname = "silicone.change_inner_cavity_core_type"
    bl_label = "Change Inner Core Type"
    bl_description = "Choose whether the inner core prints as one or multiple parts"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.label(text=t("Choose a Core Type"), icon="MOD_BOOLEAN")
        scene_property = (
            "direct_skin_core_type"
            if get_mold_type(context.scene.mold_type_preview).identifier
            == "DIRECT_MOLD_SKIN"
            else "pro_inner_cavity_core_type"
        )
        selected_identifier = getattr(context.scene, scene_property)
        grid = layout.grid_flow(
            row_major=True,
            columns=2,
            even_columns=True,
            even_rows=True,
            align=True,
        )

        for (
            identifier,
            label,
            _filename,
            _description,
        ) in INNER_CAVITY_CORE_TYPES:
            card = grid.box().column(align=True)
            preview = _preview_for_inner_cavity_core_type(identifier)
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            else:
                empty_preview = card.row(align=True)
                empty_preview.scale_y = 6.0
                empty_preview.label(text="", icon="MOD_BOOLEAN")

            is_selected = identifier == selected_identifier
            action = card.row(align=True)
            action.enabled = not is_selected
            select = action.operator(
                "silicone.select_inner_cavity_core_type",
                text=t(label),
                icon="CHECKMARK" if is_selected else "RESTRICT_SELECT_OFF",
            )
            select.core_type = identifier

    def execute(self, context):
        return {"FINISHED"}


def draw_mold_type_selector(layout, context):
    box = layout.box()
    mold_type = get_mold_type(context.scene.mold_type_preview)

    header = box.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(mold_type.label), icon="MOD_BOOLEAN")
    split.operator(
        "silicone.change_mold_type",
        text=t("Change"),
        icon="FILE_REFRESH",
    )

    _draw_mold_type_icon_view(box, context, scale=5.0)


def draw_shape_type_selector(layout, context, scene_property):
    label = "Mold Shape" if scene_property in {"slip_casting_shape_type", "mold_box_shape_type"} else "Shape Type"
    layout.label(text=t(label), icon="MESH_CUBE")
    _sync_shape_type_picker(context, scene_property)
    layout.template_icon_view(
        context.window_manager,
        "shape_type_picker",
        show_labels=True,
        scale=4.0,
        scale_popup=5.0,
    )


def _slip_casting_base_picker_items(self, context):
    global _slip_casting_base_picker_items_cache
    previews = preview_collections.get("main")
    items = []
    for identifier, label, _filename, description, value in SLIP_CASTING_BASE_OPTIONS:
        preview = previews.get(f"slip_casting_base_{identifier}") if previews else None
        items.append((identifier, t(label), t(description),
                      preview.icon_id if preview is not None else 0, value))
    _slip_casting_base_picker_items_cache = tuple(items)
    return _slip_casting_base_picker_items_cache


def _get_slip_casting_base_picker(scene):
    return int(scene.slip_casting_generate_base)


def _set_slip_casting_base_picker(scene, value):
    generate_base = bool(value)
    if scene.slip_casting_generate_base == generate_base:
        return
    if (is_multipart_type(scene.mold_type_preview)
            and not is_slip_casting_type(scene.mold_type_preview)):
        master = scene.objects.get("patron")
        if master is not None and master.type == "MESH":
            from mathutils import Matrix

            # Flip around world Y at the master's origin; switching back to
            # Foot restores its orientation without moving the model.
            transform = master.matrix_world.copy()
            flipped = Matrix.Rotation(math.pi, 4, "Y") @ transform
            flipped.translation = transform.translation
            master.matrix_world = flipped
    scene.slip_casting_generate_base = generate_base


# Keep the saved boolean as the single source of truth, including undo and scripts.
bpy.types.Scene.slip_casting_base_picker = bpy.props.EnumProperty(
    name=t("Foot"),
    items=_slip_casting_base_picker_items,
    get=_get_slip_casting_base_picker,
    set=_set_slip_casting_base_picker,
)


class SILICONE_OT_change_slip_casting_base(bpy.types.Operator):
    bl_idname = "silicone.change_slip_casting_base"
    bl_label = "Choose a Foot"
    bl_description = "Choose whether to generate a foot with the funnels"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, row_major=True,
                                     even_columns=True, even_rows=True, align=True)
        previews = preview_collections.get("main")
        for identifier, label, _filename, _description, value in SLIP_CASTING_BASE_OPTIONS:
            card = grid.box().column(align=True)
            preview = previews.get(f"slip_casting_base_{identifier}") if previews else None
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            selected = context.scene.slip_casting_generate_base == bool(value)
            action = card.row(align=True)
            action.enabled = not selected
            choice = action.operator("wm.context_set_enum", text=t(label),
                                     icon="CHECKMARK" if selected else "RESTRICT_SELECT_OFF")
            choice.data_path = "scene.slip_casting_base_picker"
            choice.value = identifier

    def execute(self, context):
        return {"FINISHED"}


def draw_slip_casting_base_selector(layout, context):
    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t("Foot" if context.scene.slip_casting_generate_base else "No Foot"))
    split.operator("silicone.change_slip_casting_base", text=t("Change"), icon="FILE_REFRESH")
    layout.template_icon_view(
        context.scene,
        "slip_casting_base_picker",
        show_labels=True,
        scale=5.0,
        scale_popup=6.0,
    )


def _slip_casting_funnel_picker_items(self, context):
    global _slip_casting_funnel_picker_items_cache
    previews = preview_collections.get("main")
    items = []
    for identifier, label, _filename, description, value in SLIP_CASTING_FUNNEL_OPTIONS:
        preview = previews.get(f"slip_casting_funnel_{identifier}") if previews else None
        items.append((identifier, t(label), t(description),
                      preview.icon_id if preview is not None else 0, value))
    _slip_casting_funnel_picker_items_cache = tuple(items)
    return _slip_casting_funnel_picker_items_cache


def _get_slip_casting_funnel_picker(scene):
    return int(scene.slip_casting_funnel_type == "ROUNDED")


def _set_slip_casting_funnel_picker(scene, value):
    scene.slip_casting_funnel_type = "ROUNDED" if value else "ADAPTED"


# The saved geometry setting remains the source of truth for both selectors.
bpy.types.Scene.slip_casting_funnel_picker = bpy.props.EnumProperty(
    name=t("Funnel Style"),
    items=_slip_casting_funnel_picker_items,
    get=_get_slip_casting_funnel_picker,
    set=_set_slip_casting_funnel_picker,
)


class SILICONE_OT_change_slip_casting_funnel(bpy.types.Operator):
    bl_idname = "silicone.change_slip_casting_funnel"
    bl_label = "Choose a Funnel Style"
    bl_description = "Choose adapted or rounded slip-casting funnels"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, row_major=True,
                                     even_columns=True, even_rows=True, align=True)
        previews = preview_collections.get("main")
        for identifier, label, _filename, _description, _value in SLIP_CASTING_FUNNEL_OPTIONS:
            card = grid.box().column(align=True)
            preview = previews.get(f"slip_casting_funnel_{identifier}") if previews else None
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            selected = context.scene.slip_casting_funnel_type == identifier
            action = card.row(align=True)
            action.enabled = not selected
            choice = action.operator("wm.context_set_enum", text=t(label),
                                     icon="CHECKMARK" if selected else "RESTRICT_SELECT_OFF")
            choice.data_path = "scene.slip_casting_funnel_picker"
            choice.value = identifier

    def execute(self, context):
        return {"FINISHED"}


def draw_slip_casting_funnel_selector(layout, context):
    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    selected_label = next(
        label
        for identifier, label, _filename, _description, _value in SLIP_CASTING_FUNNEL_OPTIONS
        if identifier == context.scene.slip_casting_funnel_type
    )
    split.label(text=t(selected_label))
    split.operator("silicone.change_slip_casting_funnel", text=t("Change"), icon="FILE_REFRESH")
    layout.template_icon_view(
        context.scene,
        "slip_casting_funnel_picker",
        show_labels=True,
        scale=5.0,
        scale_popup=6.0,
    )


def _slip_casting_master_base_picker_items(self, context):
    global _slip_casting_master_base_picker_items_cache
    previews = preview_collections.get("main")
    items = []
    for identifier, label, _filename, description, value in SLIP_CASTING_MASTER_BASE_OPTIONS:
        preview = previews.get(f"slip_casting_master_base_{identifier}") if previews else None
        items.append((identifier, t(label), t(description),
                      preview.icon_id if preview is not None else 0, value))
    _slip_casting_master_base_picker_items_cache = tuple(items)
    return _slip_casting_master_base_picker_items_cache


def _get_slip_casting_master_base_picker(scene):
    return int(scene.slip_casting_master_base_mode == "PER_SPLIT")


def _set_slip_casting_master_base_picker(scene, value):
    scene.slip_casting_master_base_mode = "PER_SPLIT" if value else "ONE_PIECE"


# The saved geometry setting remains the source of truth for both selectors.
bpy.types.Scene.slip_casting_master_base_picker = bpy.props.EnumProperty(
    name=t("Master Base"),
    items=_slip_casting_master_base_picker_items,
    get=_get_slip_casting_master_base_picker,
    set=_set_slip_casting_master_base_picker,
)


class SILICONE_OT_change_slip_casting_master_base(bpy.types.Operator):
    bl_idname = "silicone.change_slip_casting_master_base"
    bl_label = "Choose a Master Base"
    bl_description = "Choose one piece or an independent master base per split section"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, row_major=True,
                                     even_columns=True, even_rows=True, align=True)
        previews = preview_collections.get("main")
        for identifier, label, _filename, _description, _value in SLIP_CASTING_MASTER_BASE_OPTIONS:
            card = grid.box().column(align=True)
            preview = previews.get(f"slip_casting_master_base_{identifier}") if previews else None
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            selected = context.scene.slip_casting_master_base_mode == identifier
            action = card.row(align=True)
            action.enabled = not selected
            choice = action.operator("wm.context_set_enum", text=t(label),
                                     icon="CHECKMARK" if selected else "RESTRICT_SELECT_OFF")
            choice.data_path = "scene.slip_casting_master_base_picker"
            choice.value = identifier

    def execute(self, context):
        return {"FINISHED"}


def draw_slip_casting_master_base_selector(layout, context):
    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    selected_label = next(
        label
        for identifier, label, _filename, _description, _value in SLIP_CASTING_MASTER_BASE_OPTIONS
        if identifier == context.scene.slip_casting_master_base_mode
    )
    split.label(text=t(selected_label))
    split.operator("silicone.change_slip_casting_master_base", text=t("Change"), icon="FILE_REFRESH")
    layout.template_icon_view(
        context.scene,
        "slip_casting_master_base_picker",
        show_labels=True,
        scale=5.0,
        scale_popup=6.0,
    )


def _silicone_multipart_opening_picker_items(self, context):
    global _silicone_multipart_opening_picker_items_cache
    previews = preview_collections.get("main")
    items = []
    for identifier, label, _filename, description, value in SILICONE_MULTIPART_OPENING_OPTIONS:
        preview = (
            previews.get(f"silicone_multipart_opening_{identifier}")
            if previews else None
        )
        items.append((identifier, t(label), t(description),
                      preview.icon_id if preview is not None else 0, value))
    _silicone_multipart_opening_picker_items_cache = tuple(items)
    return _silicone_multipart_opening_picker_items_cache


def _get_silicone_multipart_opening_picker(scene):
    return int(scene.silicone_multipart_opening == "OPEN_BASE")


def _set_silicone_multipart_opening_picker(scene, value):
    scene.silicone_multipart_opening = "OPEN_BASE" if value else "ENCLOSED"


# Keep the historical saved enum as the geometry source of truth.
bpy.types.Scene.silicone_multipart_opening_picker = bpy.props.EnumProperty(
    name=t("Opening"),
    items=_silicone_multipart_opening_picker_items,
    get=_get_silicone_multipart_opening_picker,
    set=_set_silicone_multipart_opening_picker,
)


class SILICONE_OT_change_silicone_multipart_opening(bpy.types.Operator):
    bl_idname = "silicone.change_silicone_multipart_opening"
    bl_label = "Choose a Multipart Opening"
    bl_description = "Choose an open-base or fully enclosed multipart mold"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, row_major=True,
                                     even_columns=True, even_rows=True, align=True)
        previews = preview_collections.get("main")
        for identifier, label, _filename, _description, _value in SILICONE_MULTIPART_OPENING_OPTIONS:
            card = grid.box().column(align=True)
            preview = (
                previews.get(f"silicone_multipart_opening_{identifier}")
                if previews else None
            )
            if preview is not None:
                card.template_icon(icon_value=preview.icon_id, scale=6.0)
            selected = context.scene.silicone_multipart_opening == identifier
            action = card.row(align=True)
            action.enabled = not selected
            choice = action.operator(
                "wm.context_set_enum",
                text=t(label),
                icon="CHECKMARK" if selected else "RESTRICT_SELECT_OFF",
            )
            choice.data_path = "scene.silicone_multipart_opening_picker"
            choice.value = identifier

    def execute(self, context):
        return {"FINISHED"}


def draw_silicone_multipart_opening_selector(layout, context):
    selected_label = next(
        label
        for identifier, label, _filename, _description, _value
        in SILICONE_MULTIPART_OPENING_OPTIONS
        if identifier == context.scene.silicone_multipart_opening
    )
    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label))
    split.operator(
        "silicone.change_silicone_multipart_opening",
        text=t("Change"),
        icon="FILE_REFRESH",
    )
    layout.template_icon_view(
        context.scene,
        "silicone_multipart_opening_picker",
        show_labels=True,
        scale=5.0,
        scale_popup=6.0,
    )


def draw_funnel_type_selector(layout, context):
    selected_identifier = context.scene.funneler
    if selected_identifier not in FUNNEL_TYPE_IDS:
        selected_identifier = FUNNEL_TYPES[0][0]
    selected_label = next(
        label
        for identifier, label, _filename in FUNNEL_TYPES
        if identifier == selected_identifier
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon="MESH_CYLINDER")
    split.operator(
        "silicone.change_funnel_type",
        text=t("Type"),
        icon="FILE_REFRESH",
    )

    preview = _preview_for_funnel_type(selected_identifier)
    if preview is not None:
        _sync_funnel_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "funnel_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_channel_adjustment_selector(layout, context):
    selected_identifier = context.scene.channel_adjustment
    if selected_identifier not in CHANNEL_ADJUSTMENT_IDS:
        selected_identifier = CHANNEL_ADJUSTMENTS[0][0]
    selected_label = next(
        label
        for identifier, label, _filename, _description in CHANNEL_ADJUSTMENTS
        if identifier == selected_identifier
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon="MOD_SMOOTH")
    split.operator(
        "silicone.change_channel_adjustment",
        text=t("Adjustment"),
        icon="FILE_REFRESH",
    )

    preview = _preview_for_channel_adjustment(selected_identifier)
    if preview is not None:
        _sync_channel_adjustment_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "channel_adjustment_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=5.0,
        )


def draw_base_type_selector(layout, context):
    selected_identifier = context.scene.base_type
    if selected_identifier not in BASE_TYPE_IDS:
        selected_identifier = BASE_TYPES[0][0]
    selected_label = (
        "Winged" if selected_identifier == "classic" else "Optimized"
    )
    selected_icon = (
        "MOD_MIRROR" if selected_identifier == "classic" else "MOD_DECIM"
    )

    layout.label(text=t("Base"), icon="AXIS_TOP")
    option = layout.row(align=True)
    split = option.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon=selected_icon)
    split.operator(
        "silicone.change_base_type",
        text="",
        icon="FILE_REFRESH",
    )

    preview = _preview_for_base_type(selected_identifier)
    if preview is not None:
        _sync_base_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "base_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_casting_box_type_selector(layout, context):
    selected_identifier = get_effective_casting_box_type(context.scene)
    if selected_identifier not in CASTING_BOX_TYPE_IDS:
        selected_identifier = CASTING_BOX_TYPES[0][0]
    selected_label = next(
        label
        for identifier, label, _filename, _description in CASTING_BOX_TYPES
        if identifier == selected_identifier
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon="MESH_CUBE")
    split.operator(
        "silicone.change_casting_box_type",
        text=t("Type"),
        icon="FILE_REFRESH",
    )

    preview = _preview_for_casting_box_type(selected_identifier)
    if preview is not None:
        _sync_casting_box_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "casting_box_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_inner_cavity_core_type_selector(layout, context):
    scene_property = (
        "direct_skin_core_type"
        if get_mold_type(context.scene.mold_type_preview).identifier
        == "DIRECT_MOLD_SKIN"
        else "pro_inner_cavity_core_type"
    )
    selected_identifier = getattr(context.scene, scene_property)
    if selected_identifier not in INNER_CAVITY_CORE_TYPE_IDS:
        selected_identifier = INNER_CAVITY_CORE_TYPES[0][0]
    selected_label = next(
        label
        for identifier, label, _filename, _description
        in INNER_CAVITY_CORE_TYPES
        if identifier == selected_identifier
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon="MOD_BOOLEAN")
    split.operator(
        "silicone.change_inner_cavity_core_type",
        text=t("Change"),
        icon="FILE_REFRESH",
    )

    preview = _preview_for_inner_cavity_core_type(selected_identifier)
    if preview is not None:
        _sync_inner_cavity_core_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "inner_cavity_core_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_master_attachment_selector(layout, context, *, compact=False):
    is_fixed = bool(context.scene.wing_join_patron)
    selected_identifier = "FIXED" if is_fixed else "UNFIXED"
    selected_label = "Fixed" if is_fixed else "Unfixed"
    icon = "DECORATE_LOCKED" if is_fixed else "DECORATE_UNLOCKED"

    if compact:
        layout.label(text="")
    else:
        header = layout.row(align=True)
        split = header.split(factor=0.62, align=True)
        split.label(
            text=t("Fixed Master" if is_fixed else "Unfixed Master"),
            icon=icon,
        )
        split.operator(
            "silicone.change_master_attachment",
            text=t("Type"),
            icon="FILE_REFRESH",
        )
    if compact:
        option = layout.row(align=True)
        split = option.split(factor=0.62, align=True)
        split.label(text=t(selected_label), icon=icon)
        split.operator(
            "silicone.change_master_attachment",
            text="",
            icon="FILE_REFRESH",
        )

    preview = _preview_for_master_attachment(selected_identifier)
    if preview is not None:
        _sync_master_attachment_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "master_attachment_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_tray_type_selector(layout, context):
    selected_identifier = context.scene.tray_type
    selected_label = next(
        (
            label
            for identifier, label, _filename, _description in TRAY_TYPES
            if identifier == selected_identifier
        ),
        "Optimized",
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(text=t(selected_label), icon="MOD_SMOOTH")
    split.operator(
        "silicone.change_tray_type",
        text=t("Type"),
        icon="FILE_REFRESH",
    )

    preview = _preview_for_tray_type(selected_identifier)
    if preview is not None:
        _sync_tray_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "tray_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=6.0,
        )


def draw_pin_type_selector(layout, context, target):
    prop_name, pin_types = PIN_TYPE_TARGETS[target]
    selected_identifier = getattr(context.scene, prop_name)
    selected_label = next(
        (
            label
            for identifier, label, _filename, _description in pin_types
            if identifier == selected_identifier
        ),
        pin_types[0][1],
    )

    select = layout.operator(
        "silicone.change_pin_type",
        text=t(selected_label),
        icon="PINNED",
    )
    select.target = target


def draw_clamp_pin_type_selector(layout, context):
    selected_identifier = context.scene.clamp_pin_type
    selected_label = next(
        (
            label
            for identifier, label, _filename, _description
            in CLAMP_PIN_TYPES
            if identifier == selected_identifier
        ),
        CLAMP_PIN_TYPES[0][1],
    )

    header = layout.row(align=True)
    split = header.split(factor=0.62, align=True)
    split.label(
        text=f"{t('Clamps')} - {t(selected_label)}",
        icon="PIVOT_MEDIAN",
    )
    change = split.operator(
        "silicone.change_pin_type",
        text=t("Type"),
        icon="FILE_REFRESH",
    )
    change.target = "CLAMP"

    preview = _preview_for_pin_type("CLAMP", selected_identifier)
    if preview is not None:
        _sync_clamp_pin_type_picker(context)
        layout.template_icon_view(
            context.window_manager,
            "clamp_pin_type_picker",
            show_labels=True,
            scale=5.0,
            scale_popup=5.0,
        )


def draw_enum_with_split_label(layout, data, prop_name, label, *, factor=0.42):
    row = layout.row(align=True)
    split = row.split(factor=factor, align=True)
    split.label(text=t(label))
    split.prop(data, prop_name, text="")


def draw_translated_prop(layout, data, prop_name, *, icon=None, text=None):
    kwargs = {"text": t(text) if text is not None else prop_label(prop_name)}
    if icon is not None:
        kwargs["icon"] = icon
    layout.prop(data, prop_name, **kwargs)


def has_cached_pro_access(context):
    return True


class MoldboxerPanel(bpy.types.Panel):
    bl_category = "MoldboxerPATCHED"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw_header(self, context):
        mold_type = get_mold_type(context.scene.mold_type_preview).identifier
        metrics_mode = (
            "none"
            if mold_type in {"FIXTURE", "PROTECTIVE_SHELL"}
            else (
                "direct"
                if is_direct_mold_type(context.scene)
                else "plaster" if is_slip_casting_type(mold_type) else "silicone"
            )
        )
        split_plane_mode = "fixture" if mold_type == "FIXTURE" else metrics_mode
        set_viewport_metrics_mode(metrics_mode, context)
        schedule_direct_split_plane_sync(
            "silicone" if split_plane_mode == "none" else split_plane_mode,
            context,
        )
        schedule_fixture_height_guide_sync(context)


class SILICONE_PT_mold(MoldboxerPanel):
    bl_idname = "SILICONE_PT_mold"
    bl_label = "Generator"

    def draw(self, context):
        layout = self.layout

        draw_mold_type_selector(layout, context)


def draw_direct_clamp_settings(
    layout,
    context,
    *,
    include_locking_clips=False,
    pin_only=False,
):
    box = layout.box()
    box.label(text=t("Clamps"), icon="MOD_BOOLEAN")
    col = box.column(align=True)
    if not pin_only:
        draw_clamp_pin_type_selector(col, context)
    row = col.row(align=True)
    draw_translated_prop(
        row,
        context.scene,
        "clamp_width",
        icon="FIXED_SIZE",
    )
    draw_translated_prop(
        row,
        context.scene,
        "clamp_depth",
        icon="FACE_CORNER",
    )
    if not pin_only:
        draw_translated_prop(
            col,
            context.scene,
            "clamp_tolerance",
            icon="ARROW_LEFTRIGHT",
        )
        draw_translated_prop(
            col,
            context.scene,
            "clamp_screws",
            icon="MOD_SCREW",
        )
        if context.scene.clamp_screws:
            draw_translated_prop(
                col,
                context.scene,
                "clamp_screw_diameter",
                icon="DRIVER_DISTANCE",
            )
    if include_locking_clips:
        col.label(text=t("Locking Clamps"), icon="NOCURVE")
        row = col.row(align=True)
        draw_translated_prop(
            row,
            context.scene,
            "clip_height",
            icon="EMPTY_SINGLE_ARROW",
        )
        draw_translated_prop(
            row,
            context.scene,
            "clip_thickness",
            icon="MOD_SOLIDIFY",
        )
        row = col.row(align=True)
        draw_translated_prop(
            row,
            context.scene,
            "clip_tolerance",
            icon="ARROW_LEFTRIGHT",
        )
        draw_translated_prop(
            row,
            context.scene,
            "clip_closing_pressure",
            icon="FORCE_HARMONIC",
        )


def draw_radial_split_controls(layout, scene):
    row = layout.row(align=True)
    draw_translated_prop(
        row, scene, "direct_radial_splits",
        text="Vertical", icon="DRIVER_ROTATIONAL_DIFFERENCE",
    )
    horizontal_row = row.row(align=True)
    horizontal_splits_available = not is_multipart_type(
        getattr(scene, "mold_type_preview", "")
    )
    horizontal_row.enabled = horizontal_splits_available
    horizontal_label = t("Horizontal")
    if not horizontal_splits_available:
        horizontal_label += " (" + t("Soon") + ")"
    draw_translated_prop(
        horizontal_row, scene, "direct_split_z",
        text=horizontal_label, icon="AXIS_TOP",
    )


def draw_center_split_planes_button(layout):
    layout.operator(
        "silicone.center_split_planes",
        text=t("Center Split Planes"),
        icon="PIVOT_MEDIAN",
    )


def draw_organic_split_button(layout):
    row = layout.row()
    row.enabled = False
    row.operator(
        "silicone.draw_organic_plane",
        text=t("Draw Organic Split") + " (" + t("Soon") + ")",
        icon="LOCKED",
    )


def draw_direct_settings(layout, context):
    schedule_funnel_reference_line_sync("direct")

    lite_tier = is_lite_tier()
    mold_type = get_mold_type(context.scene.mold_type_preview)
    if lite_tier:
        upgrade_box = layout.box()
        upgrade = upgrade_box.operator(
            "silicone.open_upgrade_license",
            text=t("Unlock with Core"),
            icon="LOCKED",
        )
        upgrade.license_target = "CORE"

    box = layout.box()
    box.label(text=t("General"), icon="TOOL_SETTINGS")
    advanced_col = box.column(align=True)
    advanced_col.enabled = not lite_tier
    advanced_col.prop(
        context.scene,
        "mold_advanced_mode",
        text=t("Advanced Mode"),
        icon="MODIFIER",
        toggle=True,
    )

    draw_shape_type_selector(advanced_col, context, "mold_box_shape_type")
    if context.scene.mold_box_shape_type == "cube":
        draw_translated_prop(advanced_col, context.scene, "mold_box_faces")

    if mold_type.identifier == "DIRECT_MOLD_SKIN":
        skin_core_generated = scene_has_skin_core(context.scene)
        if ENABLE_CUSTOM_FACE_CORE:
            generation_mode_row = advanced_col.row(align=True)
            generation_mode_row.enabled = not skin_core_generated
            draw_translated_prop(
                generation_mode_row,
                context.scene,
                "direct_skin_core_generation_mode",
                icon="OUTLINER_OB_META",
            )
        draw_translated_prop(
            advanced_col,
            context.scene,
            "skin_thickness",
            icon="MOD_SOLIDIFY",
        )
        draw_translated_prop(
            advanced_col,
            context.scene,
            "direct_mold_thickness",
            text="Box Wall Thickness",
            icon="MOD_SOLIDIFY",
        )
        draw_inner_cavity_core_type_selector(advanced_col, context)
        if (
            ENABLE_CUSTOM_FACE_CORE
            and context.scene.direct_skin_core_generation_mode == "CUSTOM_FACE"
        ):
            face_box = layout.box()
            face_box.label(text=t("Wearable Face Core Fit"), icon="USER")
            face_box.label(
                text=t("Edit the measurements below to update the core."),
                icon="INFO",
            )
            skin_core = context.scene.objects.get("skin_core")
            skin_core_confirmed = bool(
                skin_core_generated
                and getattr(skin_core, "get", lambda *_: False)(
                    "moldboxer_skin_core_confirmed",
                    False,
                )
            )
            face_col = face_box.column(align=True)
            face_col.enabled = not skin_core_confirmed
            parameter_sections = (
                (
                    "Head Measurements",
                    (
                        ("custom_face_head_height", "custom_face_head_width"),
                        ("custom_face_head_depth",),
                    ),
                ),
                (
                    "Face Measurements",
                    (
                        ("custom_face_cheek_width", "custom_face_jaw_width"),
                        ("custom_face_forehead_width", "custom_face_chin_length"),
                        ("custom_face_nose_length", "custom_face_nose_width"),
                        ("custom_face_nose_height",),
                    ),
                ),
                (
                    "Neck Measurements",
                    (
                        ("custom_face_neck_circumference", "custom_face_neck_width"),
                        ("custom_face_neck_length", "custom_face_neck_offset"),
                        ("custom_face_neck_flare",),
                    ),
                ),
                (
                    "Fit and Clearance",
                    (
                        ("custom_face_comfort_clearance",),
                        (
                            "custom_face_ear_clearance",
                            "custom_face_hair_allowance",
                        ),
                    ),
                ),
            )
            for section_index, (section_label, parameter_rows) in enumerate(
                parameter_sections
            ):
                if section_index:
                    face_col.separator(factor=0.5)
                face_col.label(text=t(section_label))
                for property_names in parameter_rows:
                    parameter_row = face_col.row(align=True)
                    for property_name in property_names:
                        draw_translated_prop(
                            parameter_row,
                            context.scene,
                            property_name,
                        )
        if not skin_core_generated:
            draw_translated_prop(
                advanced_col,
                context.scene,
                "skin_base_reference_height",
                icon="EMPTY_SINGLE_ARROW",
            )
        else:
            split_box = layout.box()
            split_box.label(text=t("Box Splits"), icon="MOD_BOOLEAN")
            split_row = split_box.row(align=True)
            draw_radial_split_controls(split_row, context.scene)
            draw_center_split_planes_button(split_box)
            draw_organic_split_button(split_box)
            draw_direct_clamp_settings(layout, context)

        box = layout.box()
        box.operator(
            "silicone.reset_settings_to_default",
            text=t("Reset settings"),
            icon="LOOP_BACK",
        )
        return

    editable_components_built = (
        not is_silicone_multipart_type(mold_type.identifier)
        and bool(mold_type.advanced_actions)
        and context.scene.mold_advanced_mode
        and context.scene.objects.get("box") is not None
    )
    if editable_components_built:
        edit_box = layout.box()
        edit_box.label(text=t("Editable Components"), icon="EDITMODE_HLT")
        edit_box.label(
            text=t(
                "Adjust the pillars and funnel, add watermarks, then confirm in the header."
            ),
            icon="INFO",
        )

    direct_mold_opening = resolve_direct_mold_opening(
        context.scene.mold_type_preview,
        context.scene.direct_mold_opening,
    )
    if direct_mold_opening == "top_funnel":
        box = layout.box()
        direct_top_funnel_preview = _preview_for_direct_top_funnel_settings()
        if direct_top_funnel_preview is not None:
            box.template_icon(
                icon_value=direct_top_funnel_preview.icon_id,
                scale=6.5,
            )
        col = box.column(align=True)
        row = col.row(align=True)
        draw_translated_prop(
            row,
            context.scene,
            "direct_funnel_top_diameter",
            icon="MESH_CIRCLE",
        )
        draw_translated_prop(
            row,
            context.scene,
            "direct_funnel_bottom_diameter",
            icon="MESH_CIRCLE",
        )
        draw_translated_prop(
            col,
            context.scene,
            "direct_funnel_reference_height",
            icon="EMPTY_SINGLE_ARROW",
        )
        draw_translated_prop(
            col,
            context.scene,
            "direct_funnel_depth",
            icon="EMPTY_SINGLE_ARROW",
        )

    box = layout.box()
    box.label(text=t("Mold Thickness"), icon="MOD_SOLIDIFY")
    col = box.column(align=True)
    draw_translated_prop(
        col,
        context.scene,
        "direct_mold_thickness",
        icon="MOD_SOLIDIFY",
    )

    box = layout.box()
    box.label(text=t("Box Splits"), icon="MOD_BOOLEAN")
    col = box.column(align=True)
    row = col.row(align=True)
    draw_radial_split_controls(row, context.scene)
    draw_center_split_planes_button(col)
    draw_organic_split_button(col)

    draw_direct_clamp_settings(layout, context)

    box = layout.box()
    col = box.column(align=True)
    draw_translated_prop(
        col,
        context.scene,
        "direct_support_pilars",
        icon="OUTLINER_OB_ARMATURE",
    )
    support_pilars_enabled = bool(context.scene.direct_support_pilars)
    casting_pilars_preview = _preview_for_casting_pilars()
    if casting_pilars_preview is not None:
        preview_row = box.row(align=True)
        preview_row.enabled = support_pilars_enabled
        preview_row.template_icon(
            icon_value=casting_pilars_preview.icon_id,
            scale=6.5,
        )

    col = box.column(align=True)
    col.enabled = support_pilars_enabled
    row = col.row(align=True)
    draw_translated_prop(
        row,
        context.scene,
        "direct_support_pilar_width",
        icon="FIXED_SIZE",
    )
    draw_translated_prop(
        row,
        context.scene,
        "direct_support_pilar_depth",
        icon="FACE_CORNER",
    )

    box = layout.box()
    box.operator(
        "silicone.reset_settings_to_default",
        text=t("Reset settings"),
        icon="LOOP_BACK",
    )


class SILICONE_OT_choose_watermark_type(bpy.types.Operator):
    bl_idname = "silicone.choose_watermark_type"
    bl_label = "Watermark"
    bl_description = "Watermark"

    include_casting_volume: bpy.props.BoolProperty(  # type: ignore
        default=True,
        options={"HIDDEN", "SKIP_SAVE"},
    )

    def invoke(self, context, _event):
        return context.window_manager.invoke_popup(self, width=260)

    def draw(self, _context):
        layout = self.layout
        layout.label(text=t("Choose a Watermark Type"), icon="IMAGE_DATA")
        choices = layout.column(align=True)
        choices.operator(
            "silicone.text_watermark",
            text=t("Text"),
            icon="FONT_DATA",
        )
        choices.operator(
            "silicone.select_logo_image",
            text=t("Image"),
            icon="FILE_IMAGE",
        )
        if self.include_casting_volume:
            choices.operator(
                "silicone.casting_volume_watermark",
                text=t("Casting Volume"),
                icon="DRIVER_DISTANCE",
            )

    def execute(self, _context):
        return {"CANCELLED"}


def draw_watermark_settings(
    layout,
    context,
    *,
    include_casting_volume=True,
):
    box = layout.box()
    box.label(text=t("Watermark"), icon="IMAGE_DATA")
    watermark_reference_preview = _preview_for_watermark_reference()
    if watermark_reference_preview is not None:
        box.template_icon(
            icon_value=watermark_reference_preview.icon_id,
            scale=6.5,
        )
    col = box.column(align=True)
    box_built = any(
        context.scene.objects.get(name) is not None
        for name in ("box", "left_box", "right_box")
    )
    is_standalone_generator = (
        get_mold_type(context.scene.mold_type_preview).identifier
        in {"FIXTURE", "PROTECTIVE_SHELL"}
    )
    if not is_standalone_generator and not box_built:
        col.label(
            text=t(
                "Build the box in Advanced Mode first to add watermarks to the box."
            ),
            icon="INFO",
        )
    choose_watermark = col.operator(
        "silicone.choose_watermark_type",
        text=t("Add Watermark"),
        icon="ADD",
    )
    choose_watermark.include_casting_volume = include_casting_volume


from .source.material_ui import draw_casting_material_settings, draw_material_field, draw_powder_recipe


class SILICONE_PT_settings(MoldboxerPanel):
    bl_idname = "SILICONE_PT_settings"
    bl_label = "Settings"

    def draw(self, context):
        layout = self.layout
        if is_direct_mold_type(context.scene):
            draw_direct_settings(layout, context)
            draw_casting_material_settings(layout, context)
            return

        lite_tier = is_lite_tier()
        pro_access = has_cached_pro_access(context)
        mold_type = get_mold_type(
            context.scene.mold_type_preview
        )
        selected_mold_type = mold_type.identifier
        schedule_funnel_reference_line_sync("silicone")

        if selected_mold_type == "PROTECTIVE_SHELL":
            box = layout.box()
            box.label(text=t("Protective Shell"), icon="MOD_BOOLEAN")
            col = box.column(align=True)
            draw_translated_prop(
                col,
                context.scene,
                "protective_shell_fit_tolerance",
                icon="ARROW_LEFTRIGHT",
            )
            draw_translated_prop(
                col,
                context.scene,
                "protective_shell_thickness",
                icon="MOD_SOLIDIFY",
            )
            draw_shape_type_selector(
                col,
                context,
                "protective_shell_shape_type",
            )
            draw_enum_with_split_label(
                col,
                context.scene,
                "protective_shell_box_quality",
                "Detail",
            )

            split_box = layout.box()
            split_box.label(text=t("Box Splits"), icon="MOD_BOOLEAN")
            split_row = split_box.row(align=True)
            draw_radial_split_controls(split_row, context.scene)
            draw_center_split_planes_button(split_box)
            draw_organic_split_button(split_box)
            draw_direct_clamp_settings(
                layout,
                context,
                include_locking_clips=True,
                pin_only=True,
            )
            return

        if selected_mold_type == "FIXTURE":
            box = layout.box()
            box.label(text=t("Fixture"), icon="MOD_BOOLEAN")
            col = box.column(align=True)
            draw_translated_prop(
                col,
                context.scene,
                "fixture_fit_tolerance",
                icon="ARROW_LEFTRIGHT",
            )
            draw_translated_prop(
                col,
                context.scene,
                "fixture_thickness",
                icon="MOD_SOLIDIFY",
            )
            draw_shape_type_selector(
                col,
                context,
                "fixture_shape_type",
            )
            draw_enum_with_split_label(
                col,
                context.scene,
                "fixture_box_quality",
                "Detail",
            )

            base_box = layout.box()
            draw_translated_prop(
                base_box,
                context.scene,
                "fixture_base",
                icon="MESH_CUBE",
            )
            if context.scene.fixture_base:
                base_col = base_box.column(align=True)
                draw_translated_prop(
                    base_col,
                    context.scene,
                    "fixture_base_thickness",
                    icon="MOD_SOLIDIFY",
                )
                draw_translated_prop(
                    base_col,
                    context.scene,
                    "fixture_base_span",
                    icon="ARROW_LEFTRIGHT",
                )
                draw_translated_prop(
                    base_col,
                    context.scene,
                    "fixture_base_screw_holes",
                    icon="MOD_SCREW",
                )
                if context.scene.fixture_base_screw_holes:
                    screw_col = base_col.column(align=True)
                    draw_translated_prop(
                        screw_col,
                        context.scene,
                        "fixture_base_screw_body_diameter",
                        icon="DRIVER_DISTANCE",
                    )
                    draw_translated_prop(
                        screw_col,
                        context.scene,
                        "fixture_base_screw_head_diameter",
                        icon="DRIVER_DISTANCE",
                    )
                    draw_translated_prop(
                        screw_col,
                        context.scene,
                        "fixture_base_screw_head_height",
                        icon="DRIVER_DISTANCE",
                    )

            return

        if lite_tier:
            upgrade_box = layout.box()
            upgrade = upgrade_box.operator(
                "silicone.open_upgrade_license",
                text=t("Unlock with Core"),
                icon="LOCKED",
            )
            upgrade.license_target = "CORE"

        if selected_mold_type == "TRAY_MOLD":
            box = layout.box()
            box.label(text=t("Tray"), icon="REMOVE")
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_tray_type_selector(col, context)
            draw_translated_prop(
                col,
                context.scene,
                "flat_grip",
                icon="NORMALS_FACE",
            )
            tray_grip_preview = _preview_for_tray_grip()
            if tray_grip_preview is not None:
                preview_row = col.row(align=True)
                preview_row.enabled = bool(context.scene.flat_grip)
                preview_row.template_icon(
                    icon_value=tray_grip_preview.icon_id,
                    scale=6.5,
                )
            engraving_col = col.column(align=True)
            engraving_col.enabled = bool(context.scene.flat_grip)
            draw_translated_prop(
                engraving_col,
                context.scene,
                "tray_casting_volume",
                text="Casting Volume",
                icon="VOLUME_DATA",
            )
            tray_casting_volume_preview = _preview_for_tray_casting_volume()
            if tray_casting_volume_preview is not None:
                preview_row = engraving_col.row(align=True)
                preview_row.enabled = bool(context.scene.tray_casting_volume)
                preview_row.template_icon(
                    icon_value=tray_casting_volume_preview.icon_id,
                    scale=6.5,
                )
            if (
                context.scene.mold_advanced_mode
                and context.scene.objects.get("box") is not None
                and context.scene.objects.get("grip") is not None
            ):
                col.label(
                    text=t("Edit the grip, then confirm in the header"),
                    icon="EDITMODE_HLT",
                )

        if context.scene.pro_inner_cavity:
            box = layout.box()
            box.label(text=t("Silicone · Inner Core"), icon="PROP_PROJECTED")
            col = box.column(align=True)
            col.enabled = pro_access
            draw_translated_prop(
                col,
                context.scene,
                "pro_inner_cavity_sensitivity",
            )
            draw_inner_cavity_core_type_selector(col, context)

        if context.scene.pro_two_part_silicone:
            box = layout.box()
            box.label(text=t("Silicone · Two-Part Mold"), icon="SPLIT_VERTICAL")
            col = box.column(align=True)
            col.enabled = pro_access
            draw_translated_prop(
                col,
                context.scene,
                "pro_open_base",
                icon="PLAYHEAD_SNAP_ON",
            )
            draw_translated_prop(
                col,
                context.scene,
                "pro_casting_feet",
                icon="OUTLINER_OB_ARMATURE",
            )
            draw_translated_prop(
                col,
                context.scene,
                "pro_key_size",
                icon="MESH_CUBE",
            )
            draw_translated_prop(
                col,
                context.scene,
                "pro_key_tolearnce",
                icon="ARROW_LEFTRIGHT",
            )

        box = layout.box()
        box.label(text=t("General"), icon="TOOL_SETTINGS")
        if (
            mold_type.advanced_actions
            and not is_slip_casting_type(selected_mold_type)
        ):
            advanced_col = box.column(align=True)
            advanced_col.enabled = not lite_tier
            advanced_col.prop(
                context.scene,
                "mold_advanced_mode",
                text=t("Advanced Mode"),
                icon="MODIFIER",
                toggle=True,
            )
        col = box.column(align=True)
        col.enabled = not lite_tier

        draw_translated_prop(col, context.scene, "box_gap", icon="OUTLINER_DATA_CURVES")
        draw_translated_prop(col, context.scene, "box_thickness", icon="MESH_CUBE")
        draw_enum_with_split_label(col, context.scene, "box_quality", "Box Detail")
        draw_enum_with_split_label(
            col,
            context.scene,
            "master_quality",
            "Master Detail",
        )
        if (
            selected_mold_type != "TRAY_MOLD"
            and not is_multipart_type(selected_mold_type)
        ):
            draw_translated_prop(
                col,
                context.scene,
                "build_from_sphere",
                icon="FAKE_USER_ON",
            )
        if is_slip_casting_vase_type(selected_mold_type):
            draw_slip_casting_base_selector(col, context)
        if is_multipart_type(selected_mold_type):
            draw_slip_casting_master_base_selector(col, context)

        if is_multipart_type(selected_mold_type):
            if is_slip_casting_type(selected_mold_type):
                draw_translated_prop(
                    col, context.scene, "clear_extraction", icon="TRACKING_CLEAR_BACKWARDS",
                )
            draw_shape_type_selector(col, context, "slip_casting_shape_type")
            if context.scene.slip_casting_shape_type == "cube":
                draw_translated_prop(col, context.scene, "slip_casting_box_faces")

        if not is_multipart_type(selected_mold_type):
            draw_shape_type_selector(col, context, "mold_box_shape_type")
            if context.scene.mold_box_shape_type == "cube":
                draw_translated_prop(col, context.scene, "mold_box_faces")

        if is_silicone_multipart_type(selected_mold_type):
            draw_silicone_multipart_opening_selector(col, context)

        if is_slip_casting_vase_type(selected_mold_type):
            box = layout.box()
            box.label(text=t("Funnel"), icon="MESH_CONE")
            funnel_col = box.column(align=True)
            funnel_col.enabled = not lite_tier and not slip_casting_has_prepared_parts(context.scene)
            draw_slip_casting_funnel_selector(funnel_col, context)
            if context.scene.slip_casting_funnel_type == "ROUNDED":
                for property_name in ("slip_casting_rounded_bottom_diameter",
                                      "slip_casting_rounded_top_diameter",
                                      "slip_casting_rounded_extension",
                                      "slip_casting_rounded_detection_detail",
                                      "slip_casting_rounded_count_mode"):
                    draw_translated_prop(funnel_col, context.scene, property_name)
                if context.scene.slip_casting_rounded_count_mode == "MANUAL":
                    draw_translated_prop(funnel_col, context.scene, "slip_casting_rounded_count")
                if context.scene.slip_casting_rounded_top_diameter <= context.scene.slip_casting_rounded_bottom_diameter:
                    funnel_col.label(text=t("Opening diameter must exceed contact diameter"), icon="ERROR")
            else:
                draw_translated_prop(funnel_col, context.scene, "slip_casting_adapted_variant")
                if context.scene.slip_casting_adapted_variant == "EXTERNAL":
                    draw_translated_prop(funnel_col, context.scene, "slip_casting_funnel_span")
                else:
                    draw_translated_prop(funnel_col, context.scene, "slip_casting_internal_model_type")
                    if context.scene.slip_casting_internal_model_type == "FILLED":
                        draw_translated_prop(funnel_col, context.scene, "slip_casting_flat_region_inset")
                    else:
                        draw_translated_prop(funnel_col, context.scene, "slip_casting_internal_top_expansion")
                draw_translated_prop(funnel_col, context.scene, "slip_casting_funnel_extension")

        if not is_slip_casting_type(selected_mold_type):
            recipe_box = layout.box()
            recipe_box.label(text=t("Silicone Mix"), icon="EXPERIMENTAL")
            mix_col = recipe_box.column(align=True)
            mix_col.enabled = not lite_tier
            draw_translated_prop(mix_col, context.scene, "silicone_mix_mode", text="Silicone Type")
            single_component = context.scene.silicone_mix_mode == "SINGLE"
            if not single_component:
                ingredients = mix_col.split(factor=0.5, align=True)
                draw_translated_prop(ingredients, context.scene, "silicone_mix_part_a")
                draw_translated_prop(ingredients, context.scene, "silicone_mix_part_b")
            draw_material_field(mix_col, context.scene, "silicone_density",
                                "Density" if single_component else "Mixed Density", "density")

        if is_slip_casting_type(selected_mold_type):
            recipe_box = layout.box()
            recipe_box.label(text=t("Plaster Recipe"), icon="EXPERIMENTAL")
            mix_col = recipe_box.column(align=True)
            mix_col.enabled = not lite_tier
            draw_powder_recipe(mix_col, context.scene, "plaster_mix_water_ml",
                               "plaster_mix_plaster_g", "plaster_mix_volume_ml")

        if is_multipart_type(selected_mold_type):
            box = layout.box()
            box.label(text=t("Splits"), icon="MOD_BOOLEAN")
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_radial_split_controls(col, context.scene)
            draw_center_split_planes_button(col)
            draw_organic_split_button(col)


        if is_slip_casting_type(selected_mold_type):
            box = layout.box()
            box.label(text=t("Plaster Locking System"), icon="LOCKED")
            col = box.column(align=True)
            col.enabled = not lite_tier
            pin_placement = col.row(align=True).split(factor=0.42, align=True)
            pin_placement.label(text=t("Pin Placement"))
            pin_options = pin_placement.column(align=True)
            pin_options.prop_enum(
                context.scene,
                "plaster_locking_pin_type",
                "CENTERED",
                text=t("Centered Pins"),
            )
            edge_pin_option = pin_options.row(align=True)
            edge_pin_option.enabled = False
            edge_pin_option.prop_enum(
                context.scene,
                "plaster_locking_pin_type",
                "EDGE",
                text=t("Edge Pins") + " (" + t("Soon") + ")",
            )
            draw_translated_prop(
                col,
                context.scene,
                "split_base_pin_diameter",
                icon="SPHERE",
            )
            draw_translated_prop(
                col,
                context.scene,
                "plaster_locking_tolerance",
                icon="ARROW_LEFTRIGHT",
            )

        if is_silicone_multipart_type(selected_mold_type):
            box = layout.box()
            box.label(text=t("Silicone Keys"), icon="MOD_BOOLEAN")
            col = box.column(align=True)
            draw_translated_prop(col, context.scene, "silicone_split_base_key_type")
            draw_translated_prop(col, context.scene, "silicone_split_base_key_diameter")
            draw_translated_prop(col, context.scene, "silicone_split_base_key_tolerance")

        # -----------------
        # Clear Undercuts
        # -----------------
        if selected_mold_type != "TRAY_MOLD" and not is_slip_casting_type(selected_mold_type):
            box = layout.box()
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_translated_prop(
                col,
                context.scene,
                "clear_extraction",
                icon="TRACKING_CLEAR_BACKWARDS",
            )
            if context.scene.clear_extraction:
                if getattr(
                    context.scene,
                    "clear_undercuts_mode",
                    "OPTIMIZED",
                ) not in {"OPTIMIZED", "EASY_EXTRACTION"}:
                    # Migrate scenes saved while the experimental Precise item was
                    # visible to the closest supported policy.
                    context.scene.clear_undercuts_mode = "OPTIMIZED"
                draw_enum_with_split_label(
                    col,
                    context.scene,
                    "clear_undercuts_mode",
                    "Type",
                )
        # -----------------
        # Box Splits
        # -----------------
        if (
            selected_mold_type not in {"TRAY_MOLD", "TWO_PART_SILICONE"}
            and not is_multipart_type(selected_mold_type)
        ):
            box = layout.box()
            box.label(
                text=t("Box Splits"),
                icon="MOD_BOOLEAN",
            )
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_radial_split_controls(col, context.scene)
            draw_center_split_planes_button(col)
            draw_organic_split_button(col)

        # -----------------
        # Channels
        # -----------------
        if (
            selected_mold_type != "TRAY_MOLD"
            and not is_slip_casting_type(selected_mold_type)
        ):
            box = layout.box()
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_translated_prop(col, context.scene, "channels", icon="CURVE_PATH")
            settings_col = col.column(align=True)
            settings_col.enabled = context.scene.channels
            draw_channel_adjustment_selector(settings_col, context)
            draw_translated_prop(settings_col, context.scene, "channel_end_shape")
            row = settings_col.row(align=True)
            draw_translated_prop(
                row,
                context.scene,
                "channel_width",
                icon="FIXED_SIZE",
            )
            draw_translated_prop(
                row,
                context.scene,
                "channel_depth",
                icon="FACE_CORNER",
            )
            draw_translated_prop(
                settings_col,
                context.scene,
                "horizontal_channels_count",
                icon="LINENUMBERS_ON",
            )

        # -----------------
        # Base
        # -----------------
        box = layout.box()
        if selected_mold_type == "TRAY_MOLD":
            box.label(text=t("Base"), icon="AXIS_TOP")
        col = box.column(align=True)
        col.enabled = not lite_tier
        if selected_mold_type != "TRAY_MOLD":
            selector_row = col.grid_flow(
                row_major=True,
                columns=2,
                even_columns=True,
                even_rows=False,
                align=True,
            )
            draw_base_type_selector(
                selector_row.column(align=True),
                context,
            )
            draw_master_attachment_selector(
                selector_row.column(align=True),
                context,
                compact=True,
            )
        else:
            draw_master_attachment_selector(col, context)
        if selected_mold_type != "TRAY_MOLD":
            if context.scene.base_type == "classic":
                draw_pin_type_selector(col, context, "BASE")
                draw_translated_prop(
                    col,
                    context.scene,
                    "wing_width",
                    icon="ARROW_LEFTRIGHT",
                )
            draw_translated_prop(col, context.scene, "base_thickness", icon="MOD_SOLIDIFY")
        if (
            not is_multipart_type(selected_mold_type)
            and not context.scene.wing_join_patron
        ):
            draw_translated_prop(col, context.scene, "master_base_pin", icon="PINNED")
            draw_translated_prop(col, context.scene, "master_base_pin_tolerance", icon="ARROW_LEFTRIGHT")
            draw_translated_prop(col, context.scene, "master_base_pin_height", icon="EMPTY_SINGLE_ARROW")

        # -----------------
        # Funnel
        # -----------------
        if (
            selected_mold_type != "TRAY_MOLD"
            and not is_slip_casting_type(selected_mold_type)
        ):
            box = layout.box()
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_funnel_type_selector(col, context)
            draw_translated_prop(col, context.scene, "funneler_ref_height", icon="EMPTY_SINGLE_ARROW")
            draw_translated_prop(col, context.scene, "funneler_offset", icon="EMPTY_SINGLE_ARROW")
            draw_translated_prop(col, context.scene, "funneler_size_factor", icon="FULLSCREEN_ENTER")

        # -----------------
        # Clamps
        # -----------------
        if selected_mold_type != "TRAY_MOLD":
            box = layout.box()
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_clamp_pin_type_selector(col, context)
            row = col.row(align=True)
            draw_translated_prop(row, context.scene, "clamp_width", icon="FIXED_SIZE")
            draw_translated_prop(row, context.scene, "clamp_depth", icon="FACE_CORNER")
            draw_translated_prop(col, context.scene, "clamp_tolerance", icon="ARROW_LEFTRIGHT")
            draw_translated_prop(col, context.scene, "clamp_screws", icon="MOD_SCREW")
            if context.scene.clamp_screws:
                draw_translated_prop(col, context.scene, "clamp_screw_diameter", icon="DRIVER_DISTANCE")
            col.label(text=t("Locking Clamps"), icon="NOCURVE")
            row = col.row(align=True)
            draw_translated_prop(row, context.scene, "clip_height", icon="EMPTY_SINGLE_ARROW")
            draw_translated_prop(row, context.scene, "clip_thickness", icon="MOD_SOLIDIFY")
            row = col.row(align=True)
            draw_translated_prop(row, context.scene, "clip_tolerance", icon="ARROW_LEFTRIGHT")
            draw_translated_prop(row, context.scene, "clip_closing_pressure", icon="FORCE_HARMONIC")
            col.operator("silicone.generate_clamp_lockers", text=t("Regenerate"), icon="FILE_REFRESH")

        # -----------------
        # Casting Feet
        # -----------------
        if (
            selected_mold_type != "TRAY_MOLD"
            and not is_slip_casting_type(selected_mold_type)
        ):
            casting_row = layout.row(align=True)
            box = casting_row.box()
            header = box.column(align=True)
            header.enabled = not lite_tier
            draw_translated_prop(
                header,
                context.scene,
                "casting_feet",
                icon="OUTLINER_OB_ARMATURE",
            )
            preview_content = box.column(align=True)
            preview_content.enabled = (
                not lite_tier and context.scene.casting_feet
            )
            casting_feet_preview = _preview_for_casting_feet()
            if casting_feet_preview is not None:
                preview_content.template_icon(
                    icon_value=casting_feet_preview.icon_id,
                    scale=6.5,
                )
            if context.scene.casting_feet:
                settings = box.column(align=True)
                settings.enabled = not lite_tier
                draw_translated_prop(
                    settings,
                    context.scene,
                    "casting_feet_height",
                    icon="EMPTY_SINGLE_ARROW",
                )
                draw_translated_prop(
                    settings,
                    context.scene,
                    "casting_feet_size_factor",
                    icon="FULLSCREEN_ENTER",
                )

            box = casting_row.box()
            header = box.column(align=True)
            header.enabled = not lite_tier
            draw_translated_prop(
                header,
                context.scene,
                "casting_grip",
                icon="MOD_SOLIDIFY",
            )
            preview_content = box.column(align=True)
            preview_content.enabled = (
                not lite_tier and context.scene.casting_grip
            )
            casting_grip_preview = _preview_for_casting_grip()
            if casting_grip_preview is not None:
                preview_content.template_icon(
                    icon_value=casting_grip_preview.icon_id,
                    scale=6.5,
                )
            if context.scene.casting_grip:
                settings = box.column(align=True)
                settings.enabled = not lite_tier
                draw_translated_prop(
                    settings,
                    context.scene,
                    "casting_grip_width",
                    icon="ARROW_LEFTRIGHT",
                )
                draw_translated_prop(
                    settings,
                    context.scene,
                    "casting_grip_depth",
                    icon="EMPTY_SINGLE_ARROW",
                )

        # -----------------
        # Support Pilars
        # -----------------
        if selected_mold_type != "TRAY_MOLD":
            box = layout.box()
            col = box.column(align=True)
            col.enabled = not lite_tier
            draw_translated_prop(
                col,
                context.scene,
                "silicone_support_pilars",
                icon="OUTLINER_OB_ARMATURE",
            )
            support_pilars_enabled = bool(context.scene.silicone_support_pilars)
            casting_pilars_preview = _preview_for_silicone_support_pilars()
            if casting_pilars_preview is not None:
                preview_row = box.row(align=True)
                preview_row.enabled = not lite_tier and support_pilars_enabled
                preview_row.template_icon(
                    icon_value=casting_pilars_preview.icon_id,
                    scale=6.5,
                )

            support_col = box.column(align=True)
            support_col.enabled = not lite_tier and support_pilars_enabled
            draw_translated_prop(
                support_col,
                context.scene,
                "channel_width",
                icon="FIXED_SIZE",
            )

        box = layout.box()
        box.operator(
            "silicone.reset_settings_to_default",
            text=t("Reset settings"),
            icon="LOOP_BACK",
        )

        draw_casting_material_settings(layout, context)


def draw_utils_panel(layout, context, *, include_grid=True):
    prefs = get_addon_preferences()
    # Image utilities are rendered as cards in the viewport's right column.
    del include_grid

    # box = layout.box()
    # box.label(text="Split Connector", icon="MOD_BOOLEAN")
    # col = box.column(align=True)
    # row = col.row(align=True)
    # row.operator("silicone.split_with_connector", icon="MOD_BOOLEAN")
    # row.prop(context.scene, "split_connector_tolerance")

    # -----------------
    # Grip
    # -----------------
    # box = layout.box()
    # box.label(text="Grip", icon="MOD_SOLIDIFY")
    # col = box.column(align=True)

    # row = col.row(align=True)
    # row.operator("silicone.build_grip", icon="MESH_CUBE")
    # row.prop(context.scene, "grip_height")

    # col.operator("silicone.add_grip", icon="ADD")

    draw_dev_tools_panel(layout, context, prefs)


def draw_dev_tools_panel(layout, context, prefs=None):
    if prefs is None:
        prefs = get_addon_preferences()

    if prefs and getattr(prefs, "dev_mode", False):
        box = layout.box()
        box.label(text=t("Dev"), icon="TOOL_SETTINGS")
        col = box.column(align=True)
        draw_translated_prop(col, prefs, "dev_repo_path")
        overlay = getattr(getattr(context, "space_data", None), "overlay", None)
        if (
            overlay is not None
            and hasattr(overlay, "show_face_orientation")
            and hasattr(overlay, "show_stats")
        ):
            col.operator(
                "silicone.toggle_dev_mesh_overlays",
                text=t("Face Orientation & Statistics"),
                icon="INFO",
                depress=bool(overlay.show_face_orientation and overlay.show_stats),
            )
        col.operator(
            "silicone.fix_manifold",
            text=t("Fix Manifold"),
            icon="MODIFIER",
        )
        col.operator(
            "silicone.check_manifold_status",
            text=t("Check Manifold Status"),
            icon="MESH_DATA",
        )
        undercuts = col.row(align=True)
        undercuts.operator("silicone.preview_master_undercuts", text=t("Show Master Undercuts"), icon="VIEWZOOM")
        undercuts.operator("silicone.hide_master_undercuts", text="", icon="HIDE_ON")
        col.operator(
            "silicone.dev_clear_slip_casting_undercuts",
            text=t("Clear Undercuts (Slip Cast)"),
            icon="MOD_BOOLEAN",
        )
        from .source.components.dev_undercut_steps import next_label
        col.label(text=t("Clearance Debug — Temporary Copy"))
        col.operator("silicone.step_dev_slip_casting_undercuts", text=next_label(), icon="PLAY")
        col.operator("silicone.reset_dev_slip_casting_undercuts", text=t("Reset Clearance Debug"), icon="LOOP_BACK")
        draw_organic_split_button(col)
        reshape = col.row(align=True)
        active_object = getattr(context, "active_object", None)
        reshape.enabled = bool(
            active_object is not None
            and active_object.get("moldboxer_organic_plane", False)
        )
        reshape.operator(
            "silicone.reshape_organic_plane",
            text=t("Reshape Organic Plane"),
            icon="PROP_ON",
        )
        reshape.operator(
            "silicone.test_split_with_organic_plane",
            text=t("Test Split"),
            icon="MOD_BOOLEAN",
        )
        col.operator(
            "silicone.restore_recording_window_layout",
            text=t("Restore OBS Window"),
            icon="WINDOW",
        )
        col.operator("silicone.reload_from_repo", text=t("Reload From Repo"), icon="FILE_REFRESH")
        export_glb = col.operator("silicone.export_stl", text=t("Export GLB"), icon="EXPORT")
        export_glb.file_format = "GLB"
        if getattr(prefs, "test_mode", False):
            col.operator(
                "silicone.test_operator",
                text=t("Test Operator"),
                icon="MOD_SMOOTH",
            )
    if not IS_PRODUCTION_BUILD:
        box = layout.box()
        col = box.column(align=True)
        col.operator(
            "silicone.copy_last_operator_logs",
            text=t("Copy Last Operator Logs"),
            icon="COPYDOWN",
        )

    if prefs and getattr(prefs, "dev_mode", False):
        box = layout.box()
        box.label(text=t("Batch Tests"), icon="FILE_TICK")
        col = box.column(align=True)
        draw_translated_prop(col, context.scene, "dev_batch_tests_path")
        batch = col.operator(
            "silicone.batch_tests_operator",
            text=t("Run Batch Tests"),
            icon="PLAY",
        )
        batch.slip_casting_all_options = False
        batch.multipart_all_shapes = False
        batch.all_generators = False
        all_generators = col.operator(
            "silicone.batch_tests_operator",
            text=t("Run All Generators (Defaults)"),
            icon="PLAY",
        )
        all_generators.slip_casting_all_options = False
        all_generators.multipart_all_shapes = False
        all_generators.all_generators = True
        if is_slip_casting_type(context.scene.mold_type_preview):
            matrix = col.operator(
                "silicone.batch_tests_operator",
                text=t("Run All Slip Cast Options (24 per Model)"),
                icon="PLAY",
            )
            matrix.slip_casting_all_options = True
            matrix.multipart_all_shapes = False
        if is_silicone_multipart_type(context.scene.mold_type_preview):
            matrix = col.operator(
                "silicone.batch_tests_operator",
                text=t("Run All Multipart Options (6 per Model)"),
                icon="PLAY",
            )
            matrix.slip_casting_all_options = False
            matrix.multipart_all_shapes = True



def draw_fixture_utils_panel(layout, context):
    draw_dev_tools_panel(layout, context)


class SILICONE_PT_utils(MoldboxerPanel):
    bl_idname = "SILICONE_PT_utils"
    bl_label = "Utils"

    @classmethod
    def poll(cls, context):
        del cls, context
        prefs = get_addon_preferences()
        return bool(
            (prefs and getattr(prefs, "dev_mode", False))
            or not IS_PRODUCTION_BUILD
        )

    def draw(self, context):
        if get_mold_type(context.scene.mold_type_preview).identifier in {
            "FIXTURE",
            "PROTECTIVE_SHELL",
        }:
            draw_fixture_utils_panel(self.layout, context)
            return
        draw_utils_panel(
            self.layout,
            context,
            include_grid=not is_direct_mold_type(context.scene),
        )


class SILICONE_PT_pro_settings(MoldboxerPanel):
    bl_idname = "SILICONE_PT_pro_settings"
    bl_label = "Pro Tools & Features"

    @classmethod
    def poll(cls, context):
        mold_type = get_mold_type(context.scene.mold_type_preview).identifier
        if mold_type in {"FIXTURE", "PROTECTIVE_SHELL"}:
            return False
        return True

    def draw(self, context):
        layout = self.layout
        selected_mold_type = get_mold_type(
            context.scene.mold_type_preview
        ).identifier
        if selected_mold_type in {"FIXTURE", "PROTECTIVE_SHELL"}:
            return

        lite_tier = is_lite_tier()
        core_tier = is_core_tier()
        pro_access = has_cached_pro_access(context)

        if lite_tier or core_tier:
            upgrade_box = layout.box()
            upgrade = upgrade_box.operator(
                "silicone.open_upgrade_license",
                text=t("Unlock with Pro"),
                icon="LOCKED",
            )
            upgrade.license_target = "PRO"

        if is_direct_mold_type(context.scene):
            return

        box = layout.box()
        col = box.column(align=True)
        col.enabled = pro_access
        draw_translated_prop(col, context.scene, "pro_casting_box", icon="MESH_CUBE")
        casting_options = col.column(align=True)
        casting_options.enabled = context.scene.pro_casting_box
        casting_box_type_options = casting_options.column(align=True)
        casting_box_type_options.enabled = (
            not context.scene.pro_two_part_silicone
        )
        draw_casting_box_type_selector(casting_box_type_options, context)
        if context.scene.pro_casting_box:
            draw_translated_prop(
                casting_options,
                context.scene,
                "pro_casting_box_different_thickness",
            )
            thickness_options = casting_options.column(align=True)
            thickness_options.enabled = (
                context.scene.pro_casting_box_different_thickness
            )
            draw_translated_prop(
                thickness_options,
                context.scene,
                "casting_box_thickness",
            )
            if context.scene.pro_casting_box_type == "OPTIMIZED":
                draw_translated_prop(
                    casting_options,
                    context.scene,
                    "optimized_casting_box_horizontal_intersection",
                )
                draw_translated_prop(
                    casting_options,
                    context.scene,
                    "optimized_casting_box_thickness",
                )
