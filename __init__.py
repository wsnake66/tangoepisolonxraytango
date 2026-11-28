bl_info = {
    "name": "Moldboxer Silicone",
    "author": "DRP",
    "version": (2, 3, 2),
    "blender": (4, 2, 0),
    "location": "View3D > N-panel",
    "category": "Object",
}

import logging
import importlib
import importlib.util
import site
import subprocess
import sys
from pathlib import Path

import bpy  # type: ignore
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty  # type: ignore

from .dependencies import DEPENDENCY_IMPORT_NAMES, PYTHON_DEPENDENCIES

# import importlib


def expose_user_site_packages():
    """Expose pip's user install directory in Blender's isolated Python."""

    user_site = site.getusersitepackages()
    user_site_paths = (user_site,) if isinstance(user_site, str) else user_site
    for user_site_path in user_site_paths:
        if user_site_path:
            site.addsitedir(user_site_path)


def _importable_dependency_spec(module_name):
    """Return the module spec only when the dependency can actually be loaded."""

    try:
        dependency_spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        dependency_spec = None
    if dependency_spec is None:
        return None

    try:
        importlib.import_module(module_name)
    except (ImportError, OSError):
        # Native modules from a user site can be discoverable but unusable in
        # the signed Moldboxer process. Clear the failed import so Blender can
        # retry after restoring its bundled extension wheels.
        module_prefix = module_name + "."
        for loaded_name in tuple(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(module_prefix):
                sys.modules.pop(loaded_name, None)
        return None
    return dependency_spec


def _ensure_manifest_bundled_wheels(manifest_path, wheel_paths):
    """Restore a missing manifest wheels entry from the installed wheel files."""

    if not manifest_path.is_file() or not wheel_paths:
        return False

    manifest_text = manifest_path.read_text(encoding="utf-8")
    wheel_entries = [f"./wheels/{wheel_path.name}" for wheel_path in wheel_paths]
    if all(f'"{entry}"' in manifest_text for entry in wheel_entries):
        return True

    # Do not replace a non-empty declaration: release packaging owns platform
    # wheel selection. This recovery is only for a declaration lost during an
    # older repository reload.
    if any(line.lstrip().startswith("wheels =") for line in manifest_text.splitlines()):
        return False

    wheels_line = "wheels = [" + ", ".join(
        f'"{entry}"' for entry in wheel_entries
    ) + "]"
    manifest_lines = manifest_text.splitlines()
    insertion_index = next(
        (
            index + 1
            for index, line in enumerate(manifest_lines)
            if line.lstrip().startswith("platforms =")
        ),
        None,
    )
    if insertion_index is None:
        insertion_index = next(
            (
                index + 1
                for index, line in enumerate(manifest_lines)
                if line.lstrip().startswith("blender_version_min =")
            ),
            len(manifest_lines),
        )
    manifest_lines.insert(insertion_index, wheels_line)
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    return True


def register_bundled_wheels():
    """Ensure Blender exposes native wheels shipped with this installed add-on."""

    addon_root = Path(__file__).resolve().parent
    wheel_paths = sorted((addon_root / "wheels").glob("*.whl"))
    if not _ensure_manifest_bundled_wheels(
        addon_root / "blender_manifest.toml",
        wheel_paths,
    ):
        return False

    try:
        import addon_utils  # type: ignore

        addon_utils.extensions_refresh(
            ensure_wheels=True,
            addon_modules_pending=[__package__],
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Could not register bundled Python dependency wheels"
        )
        return False
    importlib.invalidate_caches()
    return True


def install_package(package_spec):
    dependency_logger = logging.getLogger(__name__)
    distribution_name = package_spec.split("==", 1)[0]
    module_name = DEPENDENCY_IMPORT_NAMES.get(
        distribution_name, distribution_name.replace("-", "_")
    )
    existing_spec = _importable_dependency_spec(module_name)
    if existing_spec is None and register_bundled_wheels():
        existing_spec = _importable_dependency_spec(module_name)
    if existing_spec is None:
        # Production wheels are registered by Blender before this module is
        # imported. Only expose pip's user directory for source-reload/dev
        # sessions where no bundled module is available.
        expose_user_site_packages()
        existing_spec = _importable_dependency_spec(module_name)
    if existing_spec is not None:
        dependency_logger.info(
            "Python dependency already available: package=%s module=%s "
            "location=%s python=%s",
            package_spec,
            module_name,
            existing_spec.origin or "unknown",
            sys.executable,
        )
        return True

    dependency_logger.info(
        "Python dependency is missing; attempting installation: package=%s "
        "python=%s",
        package_spec,
        sys.executable,
    )
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_spec])
    except Exception:
        dependency_logger.exception(
            "Could not install Python dependency: package=%s python=%s",
            package_spec,
            sys.executable,
        )
        return False

    importlib.invalidate_caches()
    expose_user_site_packages()
    installed_spec = _importable_dependency_spec(module_name)
    if installed_spec is None:
        dependency_logger.error(
            "pip completed successfully but the Python dependency is still "
            "unavailable: package=%s module=%s python=%s",
            package_spec,
            module_name,
            sys.executable,
        )
        return False

    dependency_logger.info(
        "Python dependency installed successfully: package=%s module=%s "
        "location=%s python=%s",
        package_spec,
        module_name,
        installed_spec.origin or "unknown",
        sys.executable,
    )
    return True


for dependency_spec in PYTHON_DEPENDENCIES:
    install_package(dependency_spec)

try:
    from moldboxer_silicone_native.source.extensions_repo import (
        schedule_ensure_extension_repo,
        unregister_ensure_extension_repo_timer,
    )
    from moldboxer_silicone_native.source.updater_bootstrap import (
        schedule_updater_bootstrap,
        unregister_updater_bootstrap,
    )
    from moldboxer_silicone_native.source.bl_utils import (
        ensure_moldboxer_transform_gizmos_for_selection,
        ensure_viewport_dimensions_overlay,
        remove_viewport_dimensions_overlay,
        remove_viewport_logo_overlay,
        set_moldboxer_transform_gizmos_enabled,
        sync_patron_selection_for_master_filler,
    )
    from moldboxer_silicone_native.source.components.auth import initialize_auth_state_on_startup
    from moldboxer_silicone_native.source.build_profile import IS_PRODUCTION_BUILD
    from moldboxer_silicone_native.source.constants import VERSION
    from moldboxer_silicone_native.source.i18n import LANGUAGE_EN
    from moldboxer_silicone_native.source.locale_defaults import (
        detect_language_from_country,
        should_detect_default_language,
    )
    from moldboxer_silicone_native.source.import_detection import (
        register_import_detection,
        unregister_import_detection,
    )
    from moldboxer_silicone_native.source.patron_lifecycle import (
        register_orphaned_patron_cleanup,
        unregister_orphaned_patron_cleanup,
    )
    from moldboxer_silicone_native.source.components.funnel_reference_line import (
        register_funnel_reference_line,
        unregister_funnel_reference_line,
    )
    from moldboxer_silicone_native.source.components.direct_split_planes import (
        register_optimized_base_split_plane_guard,
        unregister_optimized_base_split_plane_guard,
    )
    from moldboxer_silicone_native.source.components.geometry_adapter import (
        register_nearest_surface_worker_cache,
        unregister_nearest_surface_worker_cache,
    )
    from moldboxer_silicone_native.source.window_branding import (
        schedule_window_branding,
        set_windows_app_user_model_id,
        unregister_window_branding,
    )
    from moldboxer_silicone_native.source.ui_simplification import (
        register_simplified_blender_ui,
        unregister_simplified_blender_ui,
    )
except ImportError:
    from .source.extensions_repo import (
        schedule_ensure_extension_repo,
        unregister_ensure_extension_repo_timer,
    )
    from .source.updater_bootstrap import (
        schedule_updater_bootstrap,
        unregister_updater_bootstrap,
    )
    from .source.bl_utils import (
        ensure_moldboxer_transform_gizmos_for_selection,
        ensure_viewport_dimensions_overlay,
        remove_viewport_dimensions_overlay,
        remove_viewport_logo_overlay,
        set_moldboxer_transform_gizmos_enabled,
        sync_patron_selection_for_master_filler,
    )
    from .source.components.auth import initialize_auth_state_on_startup
    from .source.build_profile import IS_PRODUCTION_BUILD
    from .source.constants import VERSION
    from .source.i18n import LANGUAGE_EN
    from .source.locale_defaults import (
        detect_language_from_country,
        should_detect_default_language,
    )
    from .source.import_detection import (
        register_import_detection,
        unregister_import_detection,
    )
    from .source.patron_lifecycle import (
        register_orphaned_patron_cleanup,
        unregister_orphaned_patron_cleanup,
    )
    from .source.components.funnel_reference_line import (
        register_funnel_reference_line,
        unregister_funnel_reference_line,
    )
    from .source.components.direct_split_planes import (
        register_optimized_base_split_plane_guard,
        unregister_optimized_base_split_plane_guard,
    )
    from .source.components.geometry_adapter import (
        register_nearest_surface_worker_cache,
        unregister_nearest_surface_worker_cache,
    )
    from .source.window_branding import (
        schedule_window_branding,
        set_windows_app_user_model_id,
        unregister_window_branding,
    )
    from .source.ui_simplification import (
        register_simplified_blender_ui,
        unregister_simplified_blender_ui,
    )
from .properties import *
from .operators import *
from .panels import *
from .hollower import (
    SILICONE_OT_convert_to_planter,
    SILICONE_OT_generate_inner_cavity,
    SILICONE_OT_hollow,
)
from .logo_extrusion import (
    SILICONE_OT_casting_volume_watermark,
    SILICONE_OT_image_to_3d_logo,
    SILICONE_OT_place_logo_on_box,
    SILICONE_OT_select_logo_image,
    SILICONE_OT_text_watermark,
)
from .source.dev_organic_plane import (
    SILICONE_OT_draw_organic_plane,
    SILICONE_OT_remove_organic_plane_thickness,
    SILICONE_OT_reshape_organic_plane,
    SILICONE_OT_set_organic_plane_thickness,
    SILICONE_OT_test_split_with_organic_plane,
)
from .source.i18n import (
    apply_language_to_registered_classes,
    initialize_language,
    language_items,
    material_units_items,
    set_language,
    t,
    tag_redraw,
)

from .source.slip_casting_base_pairs import (
    register_slip_casting_base_pairs,
    unregister_slip_casting_base_pairs,
)

logger = logging.getLogger(__name__)
_AUTO_LANGUAGE_UPDATE_ACTIVE = False
_PANEL_REFRESH_PENDING = False
_USER_PREFERENCES_SAVE_PENDING = False
_LEGACY_FILE_HANDLER_IDS = {"MOLDBOXER_FH_model_import"}


class MOLDBOXER_FH_3mf_import(bpy.types.FileHandler):
    """Route 3MF files dropped in the viewport through Moldboxer's importer."""

    bl_idname = "MOLDBOXER_FH_3mf_import"
    bl_label = "Moldboxer 3MF Import"
    bl_import_operator = "silicone.import_model"
    bl_file_extensions = ".3mf"

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return getattr(area, "type", None) == "VIEW_3D"


class MOLDBOXER_FH_step_import(bpy.types.FileHandler):
    """Route STEP files dropped in the viewport through Moldboxer's importer."""

    bl_idname = "MOLDBOXER_FH_step_import"
    bl_label = "Moldboxer STEP Import"
    bl_import_operator = "silicone.import_model"
    bl_file_extensions = ".step;.stp"

    @classmethod
    def poll_drop(cls, context):
        area = getattr(context, "area", None)
        return getattr(area, "type", None) == "VIEW_3D"


def _unregister_legacy_file_handler():
    file_handler_base = getattr(bpy.types, "FileHandler", None)
    if file_handler_base is None:
        return
    for handler_class in tuple(file_handler_base.__subclasses__()):
        if (
            getattr(handler_class, "__name__", "") not in _LEGACY_FILE_HANDLER_IDS
            and getattr(handler_class, "bl_idname", "") not in _LEGACY_FILE_HANDLER_IDS
        ):
            continue
        try:
            bpy.utils.unregister_class(handler_class)
        except Exception:
            logger.debug("Could not unregister legacy import handler", exc_info=True)


def _remove_master_filler_patron_selection_handlers():
    handlers = bpy.app.handlers.depsgraph_update_post
    for handler in tuple(handlers):
        if getattr(handler, "__name__", "") == "_sync_master_filler_patron_selection_handler":
            handlers.remove(handler)


def _sync_master_filler_patron_selection_timer():
    try:
        sync_patron_selection_for_master_filler(bpy.context)
    except Exception:
        logger.debug(
            "Could not sync patron selection after add-on registration",
            exc_info=True,
        )
    return None


def _schedule_master_filler_patron_selection_sync():
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _sync_master_filler_patron_selection_timer
    ):
        return
    bpy.app.timers.register(
        _sync_master_filler_patron_selection_timer,
        first_interval=0.0,
    )


def _unregister_master_filler_patron_selection_sync():
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(
        _sync_master_filler_patron_selection_timer
    ):
        bpy.app.timers.unregister(_sync_master_filler_patron_selection_timer)


def hex_to_rgba(hex_color, alpha=1.0):
    hex_value = hex_color.lstrip("#")
    if len(hex_value) != 6:
        raise ValueError(f"Expected a 6-digit hex color, got: {hex_color}")

    return (
        int(hex_value[0:2], 16) / 255.0,
        int(hex_value[2:4], 16) / 255.0,
        int(hex_value[4:6], 16) / 255.0,
        alpha,
    )


def assign_theme_color(target, attr_name, color):
    if not hasattr(target, attr_name):
        return

    try:
        current_value = getattr(target, attr_name)
    except Exception:
        logger.debug("Could not read theme color attribute %s", attr_name, exc_info=True)
        return

    try:
        expected_size = len(current_value)
    except TypeError:
        try:
            scalar_value = color[0]
        except (TypeError, IndexError):
            scalar_value = color

        try:
            setattr(target, attr_name, scalar_value)
        except Exception:
            logger.debug(
                "Could not assign scalar theme value for %s",
                attr_name,
                exc_info=True,
            )
        return

    try:
        setattr(target, attr_name, color[:expected_size])
    except Exception:
        logger.debug(
            "Could not assign theme color for %s using %d components",
            attr_name,
            expected_size,
            exc_info=True,
        )


def clear_missing_moldboxer_font_preferences(preferences=None) -> bool:
    """Clear stale Moldboxer font paths left by an older installation."""
    if preferences is None:
        preferences = getattr(bpy.context, "preferences", None)
    view_preferences = getattr(preferences, "view", None)
    if view_preferences is None:
        return False

    changed = False
    for attr_name in ("font_path_ui", "font_path_ui_mono"):
        if not hasattr(view_preferences, attr_name):
            continue
        try:
            raw_path = str(getattr(view_preferences, attr_name, "")).strip()
        except Exception:
            continue
        if not raw_path:
            continue

        font_path = Path(raw_path).expanduser()
        normalized_parts = {part.lower() for part in font_path.parts}
        if (
            font_path.is_file()
            or "moldboxer_silicone" not in normalized_parts
            or font_path.name.lower() != "barlow-regular.ttf"
        ):
            continue

        try:
            setattr(view_preferences, attr_name, "")
            changed = True
        except Exception:
            logger.debug(
                "Could not clear missing Moldboxer font preference %s",
                attr_name,
                exc_info=True,
            )

    if changed:
        _save_user_preferences("after clearing missing Moldboxer font")
    return changed


def apply_moldboxer_theme(save=True):
    preferences = getattr(bpy.context, "preferences", None)
    themes = getattr(preferences, "themes", None)
    if not themes:
        return False

    try:
        ui = themes[0].user_interface
    except Exception:
        logger.debug("Could not access Blender UI theme", exc_info=True)
        return False

    panel_bg = hex_to_rgba("#2F2F2F")
    section_bg = hex_to_rgba("#242424")
    control_bg = hex_to_rgba("#343434")
    control_hover = hex_to_rgba("#404040")
    header_bg = hex_to_rgba("#202020")
    viewport_header_bg = hex_to_rgba("#242424")
    outline = hex_to_rgba("#3A3A3A")
    divider = hex_to_rgba("#303030")
    accent = hex_to_rgba("#8A5D0C")
    accent_active = hex_to_rgba("#A06B12")
    accent_light = hex_to_rgba("#B67D12")
    text = hex_to_rgba("#E8E8E8")
    text_muted = hex_to_rgba("#A8A8A8")
    text_disabled = hex_to_rgba("#666666")
    text_on_accent = hex_to_rgba("#FFFFFF")

    try:
        viewport_space = themes[0].view_3d.space
    except Exception:
        logger.debug("Could not access the 3D View theme", exc_info=True)
    else:
        assign_theme_color(viewport_space, "header", viewport_header_bg)
        assign_theme_color(viewport_space, "header_text", text)
        assign_theme_color(viewport_space, "header_text_hi", text_on_accent)

    def style_widget(
        widget_colors,
        *,
        base_color,
        selected_color=None,
        text_color=None,
        selected_text_color=None,
        item_color=None,
        key_color=None,
    ):
        selected_color = selected_color or accent
        text_color = text_color or text
        selected_text_color = selected_text_color or text_on_accent
        item_color = item_color or accent_active
        key_color = key_color or accent

        assign_theme_color(widget_colors, "inner", base_color)
        assign_theme_color(widget_colors, "inner_sel", selected_color)
        assign_theme_color(widget_colors, "outline", outline)
        assign_theme_color(widget_colors, "text", text_color)
        assign_theme_color(widget_colors, "text_sel", selected_text_color)
        assign_theme_color(widget_colors, "item", item_color)

        # These are optional across Blender versions, so keep them best-effort.
        assign_theme_color(widget_colors, "inner_key", key_color)
        assign_theme_color(widget_colors, "inner_key_sel", accent_active)
        assign_theme_color(widget_colors, "text_hi", text_muted)
        assign_theme_color(widget_colors, "text_disabled", text_disabled)
        assign_theme_color(widget_colors, "show_shaded", (1,))
        assign_theme_color(widget_colors, "shadetop", (0,))
        assign_theme_color(widget_colors, "shadedown", (-12,))
        assign_theme_color(widget_colors, "roundness", (0.35,))

    widget_ids = (
        "wcol_regular",
        "wcol_tool",
        "wcol_box",
        "wcol_menu",
        "wcol_menu_back",
        "wcol_tab",
        "wcol_num",
        "wcol_numslider",
        "wcol_option",
        "wcol_progress",
        "wcol_toggle",
        "wcol_radio",
    )

    for widget_id in widget_ids:
        if not hasattr(ui, widget_id):
            continue

        widget_colors = getattr(ui, widget_id)
        style_widget(widget_colors, base_color=control_bg)

    if hasattr(ui, "wcol_tool"):
        tool_colors = ui.wcol_tool
        style_widget(
            tool_colors,
            base_color=control_bg,
            selected_color=accent,
            selected_text_color=text_on_accent,
            item_color=accent_light,
            key_color=accent,
        )
        assign_theme_color(tool_colors, "inner", control_bg)
        assign_theme_color(tool_colors, "inner_sel", accent)

    if hasattr(ui, "wcol_box"):
        box_colors = ui.wcol_box
        style_widget(
            box_colors,
            base_color=section_bg,
            selected_color=accent,
            text_color=text,
            selected_text_color=text,
            item_color=divider,
            key_color=divider,
        )

    if hasattr(ui, "wcol_menu_back"):
        menu_back_colors = ui.wcol_menu_back
        assign_theme_color(menu_back_colors, "inner", panel_bg)
        assign_theme_color(menu_back_colors, "outline", divider)
        assign_theme_color(menu_back_colors, "text", text)
        assign_theme_color(menu_back_colors, "text_sel", text)

    # Icon-view popups use list-item colors for the selected thumbnail.
    # Change only the selected state so normal lists keep their native
    # transparent background.
    for widget_id in ("wcol_list_item", "wcol_menu_item"):
        if not hasattr(ui, widget_id):
            continue
        widget_colors = getattr(ui, widget_id)
        assign_theme_color(widget_colors, "inner_sel", accent)
        assign_theme_color(widget_colors, "text_sel", text_on_accent)
        assign_theme_color(widget_colors, "item", accent_active)

    if hasattr(ui, "wcol_tab"):
        tab_colors = ui.wcol_tab
        style_widget(
            tab_colors,
            base_color=header_bg,
            selected_color=accent,
            text_color=text,
            selected_text_color=text,
            item_color=accent_light,
            key_color=accent,
        )

    if hasattr(ui, "wcol_num"):
        style_widget(
            ui.wcol_num,
            base_color=control_bg,
            selected_color=accent_active,
            selected_text_color=text_on_accent,
            item_color=accent_light,
            key_color=accent,
        )

    if hasattr(ui, "wcol_numslider"):
        style_widget(
            ui.wcol_numslider,
            base_color=control_bg,
            selected_color=control_hover,
            selected_text_color=text,
            item_color=accent_active,
            key_color=accent,
        )

    if hasattr(ui, "wcol_progress"):
        style_widget(
            ui.wcol_progress,
            base_color=control_bg,
            selected_color=control_hover,
            selected_text_color=text,
            item_color=accent_active,
            key_color=accent,
        )

    if hasattr(ui, "wcol_option"):
        style_widget(
            ui.wcol_option,
            base_color=control_bg,
            selected_color=accent,
            selected_text_color=text_on_accent,
            item_color=accent_light,
            key_color=accent,
        )

    if hasattr(ui, "wcol_toggle"):
        style_widget(
            ui.wcol_toggle,
            base_color=control_bg,
            selected_color=accent,
            selected_text_color=text_on_accent,
            item_color=accent_active,
            key_color=accent,
        )

    if hasattr(ui, "wcol_radio"):
        style_widget(
            ui.wcol_radio,
            base_color=control_bg,
            selected_color=accent,
            selected_text_color=text_on_accent,
            item_color=accent_active,
            key_color=accent,
        )

    if save:
        _save_user_preferences("after theme update")

    return True


def reset_blender_default_theme(save=True):
    reset_theme_op = getattr(bpy.ops.preferences, "reset_default_theme", None)
    if reset_theme_op is None:
        return False

    try:
        reset_theme_op()
    except Exception:
        logger.debug("Could not reset Blender theme to default", exc_info=True)
        return False

    if save:
        _save_user_preferences("after theme reset")

    return True


def update_moldboxer_theme_preference(self, context):
    if getattr(self, "use_moldboxer_theme", True):
        apply_moldboxer_theme(save=True)
        ensure_moldboxer_transform_gizmos_for_selection(context)
    else:
        reset_blender_default_theme(save=True)
        set_moldboxer_transform_gizmos_enabled(False, context)


def update_language_preference(self, context):
    if not _AUTO_LANGUAGE_UPDATE_ACTIVE:
        try:
            self.language_user_selected = True
        except Exception:
            logger.debug("Could not mark language as user selected", exc_info=True)

    set_language(getattr(self, "language", "EN"))
    try:
        from . import properties as properties_module

        importlib.reload(properties_module)
    except Exception:
        logger.debug("Could not refresh scene property translations", exc_info=True)
    apply_language_to_registered_classes()
    schedule_registered_panel_refresh()
    tag_redraw()
    _save_user_preferences("after language update")


def sync_account_unit_display(prefs=None):
    from . import panels
    from .source.scene_units import apply_account_units

    if prefs is None:
        prefs = get_theme_preferences()
    units = getattr(prefs, "material_units", "METRIC")
    # Initial preference callbacks may run in Blender's restricted context.
    # The registered startup timer applies the selection once scenes exist.
    if hasattr(bpy.data, "scenes"):
        apply_account_units(units)
    panels._VIEWPORT_TRANSFORM_UNIT = "IN" if units == "US" else "MM"
    tag_redraw()


def update_material_units_preference(self, context):
    self.material_units_initialized = True
    sync_account_unit_display(self)
    _save_user_preferences("after units update")


def initialize_default_material_units(prefs):
    if prefs is None or getattr(prefs, "material_units_initialized", False):
        return
    from .source.material_units import units_for_country
    country = getattr(prefs, "language_auto_detected_country", "")
    if not country:
        _, country = detect_language_from_country()
    if not country or country == "XX":
        return  # Keep metric and retry next startup if geolocation was unavailable.
    prefs.material_units = units_for_country(country)
    prefs.material_units_initialized = True
    _save_user_preferences("after country-based units initialization")


def update_silicone_density_preference(self, context):
    _save_user_preferences()


def get_theme_preferences():
    addons = getattr(getattr(bpy.context, "preferences", None), "addons", None)
    if addons is None:
        return None

    for addon_key in (__package__, __name__):
        addon = addons.get(addon_key)
        prefs = getattr(addon, "preferences", None) if addon else None
        if prefs is not None:
            return prefs

    for addon in addons.values():
        prefs = getattr(addon, "preferences", None)
        if type(prefs).__name__ == "MoldboxerAddonPreferences":
            return prefs

    return None


def _can_save_user_preferences_now() -> bool:
    return getattr(bpy.context, "view_layer", None) is not None


def _deferred_save_user_preferences_timer():
    global _USER_PREFERENCES_SAVE_PENDING
    _USER_PREFERENCES_SAVE_PENDING = False
    if not _can_save_user_preferences_now():
        _schedule_save_user_preferences()
        return None
    _save_user_preferences()
    return None


def _schedule_save_user_preferences() -> None:
    global _USER_PREFERENCES_SAVE_PENDING
    if _USER_PREFERENCES_SAVE_PENDING:
        return
    _USER_PREFERENCES_SAVE_PENDING = True
    try:
        bpy.app.timers.register(_deferred_save_user_preferences_timer, first_interval=0.1)
    except Exception:
        _USER_PREFERENCES_SAVE_PENDING = False


def _save_user_preferences(reason: str = "") -> None:
    save_pref_op = getattr(bpy.ops.wm, "save_userpref", None)
    if save_pref_op is None:
        return
    if not _can_save_user_preferences_now():
        _schedule_save_user_preferences()
        return

    try:
        save_pref_op()
    except Exception:
        logger.debug(
            "Could not save Blender preferences%s",
            f" {reason}" if reason else "",
            exc_info=True,
        )


def initialize_default_language_from_country(
    prefs,
    *,
    redetect_auto_language: bool = False,
):
    global _AUTO_LANGUAGE_UPDATE_ACTIVE

    if prefs is None:
        return

    try:
        current_language = str(getattr(prefs, "language", LANGUAGE_EN)).upper()
        inferred_user_selection = False
        if (
            not bool(getattr(prefs, "language_user_selected", False))
            and current_language != LANGUAGE_EN
            and not str(getattr(prefs, "language_auto_detected_version", "")).strip()
        ):
            prefs.language_user_selected = True
            inferred_user_selection = True

        if not should_detect_default_language(
            prefs,
            redetect_auto_language=redetect_auto_language,
        ):
            if inferred_user_selection:
                _save_user_preferences()
            return

        detected_language, country_code = detect_language_from_country()
        prefs.language_auto_detected_version = VERSION
        prefs.language_auto_detected_country = country_code

        if detected_language and detected_language != current_language:
            _AUTO_LANGUAGE_UPDATE_ACTIVE = True
            try:
                prefs.language = detected_language
            finally:
                _AUTO_LANGUAGE_UPDATE_ACTIVE = False

        _save_user_preferences()
    except Exception:
        logger.debug("Could not initialize country-based language default", exc_info=True)
        try:
            prefs.language_auto_detected_version = VERSION
            _save_user_preferences()
        except Exception:
            logger.debug("Could not store language detection attempt", exc_info=True)


def update_offline_mode_preference(self, context):
    from .source import network_guard

    network_guard.set_enabled(bool(getattr(self, "offline_mode", True)))


class MoldboxerAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    language: EnumProperty(  # type: ignore
        name="Language",
        description=t("Language used by the Moldboxer panel"),
        items=language_items,
        default=0,
        update=update_language_preference,
    )
    material_units: EnumProperty(
        name="Unit System",
        description="Display units for dimensions, mold settings and material quantities",
        items=material_units_items,
        default=0,
        update=update_material_units_preference,
    )
    material_units_initialized: BoolProperty(default=False, options={"HIDDEN"})
    language_user_selected: BoolProperty(  # type: ignore
        name="Language User Selected",
        default=False,
        options={"HIDDEN"},
    )
    language_auto_detected_version: StringProperty(  # type: ignore
        name="Language Auto Detected Version",
        default="",
        options={"HIDDEN"},
    )
    language_auto_detected_country: StringProperty(  # type: ignore
        name="Language Auto Detected Country",
        default="",
        options={"HIDDEN"},
    )
    silicone_density: FloatProperty(  # type: ignore
        name="Silicone Density (g/cm3)",
        description=t("Density used to calculate silicone weight from mold volume"),
        default=DEFAULT_SILICONE_DENSITY,
        min=0,
        update=update_silicone_density_preference,
    )
    use_moldboxer_theme: BoolProperty(  # type: ignore
        name="Moldboxer Theme",
        description=t(
            "Apply the Moldboxer UI theme. Disable to restore Blender's default theme "
            "and prevent Moldboxer from applying its theme automatically"
        ),
        default=True,
        update=update_moldboxer_theme_preference,
    )
    offline_mode: BoolProperty(  # type: ignore
        name="Offline Mode",
        description=t(
            "Block all outbound Moldboxer network connections (local connections stay allowed)"
        ),
        default=True,
        update=update_offline_mode_preference,
    )
    dev_mode: BoolProperty(  # type: ignore
        name="Dev Mode",
        description=t("Show development tools in the UI"),
        default=False,
    )
    test_mode: BoolProperty(  # type: ignore
        name="Test Mode",
        description=t("Show test-only tools in the development UI"),
        default=False,
    )
    dev_repo_path: StringProperty(  # type: ignore
        name="Dev Repo Path",
        description=t("Path to the local extension repository"),
        subtype="DIR_PATH",
        default="",
    )
    auth_logged_in: BoolProperty(  # type: ignore
        name="Logged In",
        default=False,
        options={"HIDDEN"},
    )
    auth_provider: StringProperty(  # type: ignore
        name="Auth Provider",
        default="",
        options={"HIDDEN"},
    )
    auth_pending_provider: StringProperty(  # type: ignore
        name="Pending Auth Provider",
        default="",
        options={"HIDDEN"},
    )
    auth_polling_active: BoolProperty(  # type: ignore
        name="Polling Active",
        default=False,
        options={"HIDDEN"},
    )
    auth_device_code: StringProperty(  # type: ignore
        name="Device Code",
        default="",
        options={"HIDDEN"},
    )
    auth_device_expires_at: FloatProperty(  # type: ignore
        name="Device Expires At",
        default=0.0,
        options={"HIDDEN"},
    )
    auth_refresh_token: StringProperty(  # type: ignore
        name="Refresh Token",
        default="",
        subtype="PASSWORD",
        options={"HIDDEN"},
    )
    auth_access_token: StringProperty(  # type: ignore
        name="Access Token",
        default="",
        subtype="PASSWORD",
        options={"HIDDEN"},
    )
    auth_access_expires_at: FloatProperty(  # type: ignore
        name="Access Expires At",
        default=0.0,
        options={"HIDDEN"},
    )
    auth_user_email: StringProperty(  # type: ignore
        name="User Email",
        default="",
        options={"HIDDEN"},
    )
    analytics_installation_id: StringProperty(  # type: ignore
        name="Analytics Installation ID",
        default="",
        options={"HIDDEN"},
    )
    auth_tier: StringProperty(  # type: ignore
        name="Membership Tier",
        default="",
        options={"HIDDEN"},
    )
    auth_stripe_status: StringProperty(  # type: ignore
        name="Stripe Status",
        default="",
        options={"HIDDEN"},
    )
    auth_pro_trial_available: BoolProperty(  # type: ignore
        name="Pro Trial Available",
        default=False,
        options={"HIDDEN"},
    )
    auth_trial_exports_remaining: IntProperty(  # type: ignore
        name="Free Trial Exports Remaining",
        default=2,
        min=0,
        options={"HIDDEN"},
    )
    auth_trial_export_email: StringProperty(  # type: ignore
        name="Free Trial Export Email",
        default="",
        options={"HIDDEN"},
    )
    auth_last_error: StringProperty(  # type: ignore
        name="Last Auth Error",
        default="",
        options={"HIDDEN"},
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "language", text=t("Language"))
        col.prop(self, "material_units", text=t("Unit System"))
        col.prop(self, "use_moldboxer_theme", text=t("Moldboxer Theme"))
        col.prop(self, "dev_mode", text=t("Dev Mode"))
        col.prop(self, "test_mode", text=t("Test Mode"))
        col.prop(self, "dev_repo_path", text=t("Dev Repo Path"))
        if (
            getattr(self, "auth_logged_in", False)
            and str(getattr(self, "auth_stripe_status", "")).upper() == "FREE_BASIC_GOOGLE"
        ):
            col.label(
                text=t(
                    "Free Trial Exports Remaining: {remaining}",
                    remaining=int(getattr(self, "auth_trial_exports_remaining", 0)),
                )
            )


_OPERATOR_LOG_CLASSES = () if IS_PRODUCTION_BUILD else (CopyLastOperatorLogs,)

CLASSES = (
    MoldboxerAddonPreferences,
    GenerateMold,
    AutoBox,
    SlipCastingAutoBox,
    GeneratePlasterSiliconeMolds,
    Fixture,
    ProtectiveShell,
    LoginWithGoogle,
    LoginWithPatreon,
    StartProTrial,
    LogoutAccount,
    OpenExtensionUpdates,
    OpenUpgradeLicense,
    UpdateAvailableDialog,
    ConnectionErrorDialog,
    *_OPERATOR_LOG_CLASSES,
    ResetBackgroundColor,
    ResetSettingsToDefault,
    AccountDialog,
    AuthRequiredDialog,
    BasicRequiredDialog,
    ProRequiredDialog,
    ExportLicenseRequiredDialog,
    ImportScaleWarningDialog,
    ProcessDetectedImport,
    AutoOrientModel,
    OrientFaceToBase,
    CenterObj,
    SILICONE_OT_select_logo_image,
    SILICONE_OT_image_to_3d_logo,
    SILICONE_OT_place_logo_on_box,
    SILICONE_OT_text_watermark,
    SILICONE_OT_casting_volume_watermark,
    SILICONE_OT_choose_watermark_type,
    BuildBox,
    BuildSlipCastingBox,
    BuildTray,
    Confirm,
    ConfirmSlipCasting,
    ConfirmTray,
    SmoothMasterSeal,
    DetectSlipCastingCores,
    EnableSlipCastingCavityFillerWithCores,
    BuildMasterFiller,
    ConfirmMasterFiller,
    CropMasterFillerGesture,
    CropMasterFiller,
    FillMasterBase,
    RemoveMasterFillerType,
    SplitFillerMeshes,
    AddCastingInput,
    ConfirmCastingInput,
    Clean,
    Cut,
    BuildGrip,
    AddGrip,
    Grid,
    ExportSTL,
    SILICONE_OT_select_mold_type,
    SILICONE_OT_change_mold_type,
    SILICONE_OT_select_master_attachment,
    SILICONE_OT_change_master_attachment,
    SILICONE_OT_select_tray_type,
    SILICONE_OT_change_tray_type,
    SILICONE_OT_select_pin_type,
    SILICONE_OT_change_pin_type,
    SILICONE_OT_select_funnel_type,
    SILICONE_OT_change_funnel_type,
    SILICONE_OT_change_slip_casting_funnel,
    SILICONE_OT_change_slip_casting_base,
    SILICONE_OT_change_slip_casting_master_base,
    SILICONE_OT_change_silicone_multipart_opening,
    SILICONE_OT_select_channel_adjustment,
    SILICONE_OT_change_channel_adjustment,
    SILICONE_OT_select_base_type,
    SILICONE_OT_change_base_type,
    SILICONE_OT_select_casting_box_type,
    SILICONE_OT_change_casting_box_type,
    SILICONE_OT_select_inner_cavity_core_type,
    SILICONE_OT_change_inner_cavity_core_type,
    SILICONE_OT_set_viewport_tool,
    SILICONE_OT_exit_measure_tool,
    SILICONE_OT_run_viewport_utility,
    SILICONE_OT_edit_viewport_transform,
    SILICONE_OT_viewport_action_bar_click,
    SILICONE_OT_viewport_action_bar_hover,
    SILICONE_OT_viewport_overlay_edit_property,
    SILICONE_OT_viewport_overlay_scroll,
    SILICONE_OT_keep_native_sidebar_hidden,
    SILICONE_GGT_navigation_corner,
    SILICONE_GGT_viewport_tools,
    SILICONE_GGT_viewport_utils,
    SILICONE_PT_mold,
    SILICONE_PT_settings,
    SILICONE_PT_pro_settings,
    SILICONE_PT_utils,
    ReloadFromRepo,
    RestoreRecordingWindowLayout,
    ClampLockersGenerator,
    ImportModel,
    MOLDBOXER_FH_3mf_import,
    MOLDBOXER_FH_step_import,
    Decimate,
    HealPatron,
    ScaleHeight,
    SplitWithConnector,
    FlatAutoBox,
    AutomaticMold,
    BuildDirectMold,
    ConfirmDirectMold,
    NewProject,
    Restart,
    NewClearUndercuts,
    ClearSlipCastingUndercuts,
    DevClearSlipCastingUndercuts,
    StepDevSlipCastingUndercuts,
    ResetDevSlipCastingUndercuts,
    BeginFoundation,
    ConfirmFoundation,
    BuildMasterAirTrapBridges,
    ConfirmMasterAirTrapPillars,
    TestOperator,
    BatchTestsOperator,
    FixManifold,
    CheckManifoldStatus,
    ToggleViewportOverlays,
    CenterSplitPlanes,
    ToggleDevMeshOverlays,
    PreviewMasterUndercuts,
    HideMasterUndercuts,
    SILICONE_OT_draw_organic_plane,
    SILICONE_OT_reshape_organic_plane,
    SILICONE_OT_set_organic_plane_thickness,
    SILICONE_OT_remove_organic_plane_thickness,
    SILICONE_OT_test_split_with_organic_plane,
    TestAllFillersOperator,
    TestAddFillerToPatron,
    SILICONE_OT_generate_inner_cavity,
    SILICONE_OT_hollow,
    SILICONE_OT_convert_to_planter,
)

PANEL_CLASSES = (
    SILICONE_PT_mold,
    SILICONE_PT_settings,
    SILICONE_PT_pro_settings,
    SILICONE_PT_utils,
)

addon_keymaps = []


def _unregister_addon_keymaps():
    while addon_keymaps:
        km, kmi = addon_keymaps.pop()
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            logger.debug("Could not remove stale Moldboxer keymap", exc_info=True)


def _register_reload_keymap():
    _unregister_addon_keymaps()
    wm = getattr(bpy.context, "window_manager", None)
    keyconfigs = getattr(wm, "keyconfigs", None)
    addon_keyconfig = getattr(keyconfigs, "addon", None)
    if addon_keyconfig is None:
        return
    km = addon_keyconfig.keymaps.new(name="Window", space_type="EMPTY")
    kmi = km.keymap_items.new(
        ReloadFromRepo.bl_idname,
        type="R",
        value="PRESS",
        ctrl=True,
        alt=True,
    )
    addon_keymaps.append((km, kmi))


def _unregister_class_if_registered(cls) -> bool:
    """Unregister a Blender RNA class only when registration completed."""

    if getattr(cls, "bl_rna", None) is None:
        logger.debug("Skipping unregistered class %s", cls.__name__)
        return False
    try:
        bpy.utils.unregister_class(cls)
    except Exception:
        logger.debug(
            "Could not unregister class %s",
            cls.__name__,
            exc_info=True,
        )
        return False
    return True


def refresh_registered_panels():
    translated_classes = tuple(
        cls for cls in CLASSES if cls is not MoldboxerAddonPreferences
    )

    # Never unregister operators during a language change. The language picker is
    # available inside operator popups, and unregistering their classes leaves the
    # live popup instances with invalid RNA property pointers. Blender may then
    # fail in draw() with path_resolve("properties") or crash while closing them.
    for cls in reversed(PANEL_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            logger.debug(
                "Could not unregister translated panel class %s",
                cls.__name__,
                exc_info=True,
            )

    apply_language_to_registered_classes(translated_classes)

    for cls in PANEL_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            logger.debug(
                "Could not register translated panel class %s",
                cls.__name__,
                exc_info=True,
            )

    tag_redraw()


def _refresh_registered_panels_timer():
    global _PANEL_REFRESH_PENDING
    _PANEL_REFRESH_PENDING = False
    refresh_registered_panels()
    return None


def schedule_registered_panel_refresh():
    global _PANEL_REFRESH_PENDING
    if _PANEL_REFRESH_PENDING:
        return

    _PANEL_REFRESH_PENDING = True
    try:
        bpy.app.timers.register(_refresh_registered_panels_timer, first_interval=0.0)
    except Exception:
        _PANEL_REFRESH_PENDING = False
        refresh_registered_panels()


def register():
    from .source.scene_units import register_scene_units
    from .source import network_guard

    network_guard.install()
    network_guard.set_enabled(
        bool(getattr(get_theme_preferences(), "offline_mode", True))
    )
    register_scene_units(sync_account_unit_display)
    _unregister_legacy_file_handler()
    set_windows_app_user_model_id()
    clear_missing_moldboxer_font_preferences()
    register_panel_previews()
    try:
        bpy.utils.register_class(MoldboxerAddonPreferences)
    except Exception:
        logger.debug("Could not register class %s", MoldboxerAddonPreferences.__name__)

    prefs = get_theme_preferences()
    initialize_auth_state_on_startup()
    initialize_default_language_from_country(
        prefs,
        redetect_auto_language=not bool(
            getattr(prefs, "auth_logged_in", False)
        ),
    )
    initialize_default_material_units(prefs)
    initialize_language(prefs)
    apply_language_to_registered_classes(CLASSES)

    for cls in CLASSES:
        if cls is MoldboxerAddonPreferences:
            continue
        try:
            bpy.utils.register_class(cls)
        except Exception:
            logger.debug("Could not register class %s", cls.__name__)
    try:
        from . import properties as properties_module

        importlib.reload(properties_module)
    except Exception:
        logger.debug("Could not refresh scene property translations", exc_info=True)
    apply_language_to_registered_classes(CLASSES)
    register_view3d_header_controls()
    register_simplified_blender_ui(bpy.context)
    if getattr(prefs, "use_moldboxer_theme", True):
        # Add-on registration can run with Blender's restricted context, where
        # UI operators such as wm.save_userpref cannot access a view layer.
        apply_moldboxer_theme(save=False)
    schedule_ensure_extension_repo()
    schedule_updater_bootstrap()
    schedule_window_branding()
    ensure_viewport_dimensions_overlay(bpy.context)
    register_import_detection(process_detected_import)
    register_orphaned_patron_cleanup()
    register_funnel_reference_line()
    register_optimized_base_split_plane_guard()
    register_scale_refresh_handler()
    register_slip_casting_base_pairs()
    from .source.components import slip_casting_undercut_preview
    slip_casting_undercut_preview.register()
    from .source.components import dev_undercut_preview
    dev_undercut_preview.register()
    from .source.components import dev_undercut_steps
    dev_undercut_steps.register()
    register_nearest_surface_worker_cache()
    _remove_master_filler_patron_selection_handlers()
    _schedule_master_filler_patron_selection_sync()
    _register_reload_keymap()


def unregister():
    from .source.login_resume import clear_pending_generation

    clear_pending_generation()
    from .source import network_guard

    network_guard.uninstall()
    from .source.scene_units import unregister_scene_units

    unregister_scene_units()
    from .source.components import slip_casting_undercut_preview
    slip_casting_undercut_preview.unregister()
    from .source.components import dev_undercut_preview
    dev_undercut_preview.unregister()
    from .source.components import dev_undercut_steps
    dev_undercut_steps.unregister()
    _unregister_addon_keymaps()
    unregister_simplified_blender_ui(bpy.context)
    unregister_updater_bootstrap()
    unregister_nearest_surface_worker_cache()
    unregister_scale_refresh_handler()
    unregister_slip_casting_base_pairs()
    unregister_optimized_base_split_plane_guard()
    unregister_funnel_reference_line()
    unregister_orphaned_patron_cleanup()
    unregister_import_detection()
    _unregister_legacy_file_handler()
    _unregister_master_filler_patron_selection_sync()
    _remove_master_filler_patron_selection_handlers()
    unregister_window_branding()
    unregister_ensure_extension_repo_timer()
    remove_viewport_dimensions_overlay(bpy.context)
    remove_viewport_logo_overlay(bpy.context)
    unregister_view3d_header_controls()
    for cls in reversed(CLASSES):
        _unregister_class_if_registered(cls)
    unregister_panel_previews()
