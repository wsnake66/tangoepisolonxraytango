import logging

import bpy  # type: ignore


logger = logging.getLogger(__name__)

_TOPBAR_ORIGINAL_DRAW_ATTR = "_moldboxer_original_draw_right"
_TOOLBAR_ORIGINAL_OBJECT_TOOLS_ATTR = "_moldboxer_original_object_tools"
_REMOVED_OBJECT_TOOL_IDS = {
    "builtin.cursor",
    "builtin.transform",
    "builtin.annotate",
    "builtin.annotate_line",
    "builtin.annotate_polygon",
    "builtin.annotate_eraser",
    "builtin.primitive_cube_add",
    "builtin.primitive_cone_add",
    "builtin.primitive_cylinder_add",
    "builtin.primitive_uv_sphere_add",
    "builtin.primitive_ico_sphere_add",
}


def _draw_moldboxer_topbar_right(self, context) -> None:
    """Draw only operational status items on the right side of the top bar."""

    if not context.screen.show_statusbar:
        self.layout.template_reports_banner()
        self.layout.template_running_jobs()


def _moldboxer_object_tools(toolbar_module, toolbar_class):
    transform = toolbar_module._defs_transform
    view3d_generic = toolbar_module._defs_view3d_generic
    return [
        *toolbar_class._tools_select,
        None,
        transform.translate,
        transform.rotate,
        (
            transform.scale,
            transform.scale_cage,
        ),
        None,
        view3d_generic.ruler,
    ]


def _activate_select_tool_if_removed(context) -> None:
    window_manager = getattr(context, "window_manager", None)
    windows = getattr(window_manager, "windows", ()) if window_manager else ()
    updated_workspaces = set()

    for window in windows:
        workspace = getattr(window, "workspace", None)
        workspace_key = id(workspace)
        if workspace is None or workspace_key in updated_workspaces:
            continue

        try:
            active_tool = workspace.tools.from_space_view3d_mode(
                "OBJECT",
                create=False,
            )
        except (AttributeError, TypeError, RuntimeError):
            continue
        if getattr(active_tool, "idname", "") not in _REMOVED_OBJECT_TOOL_IDS:
            continue

        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            if getattr(area, "type", None) != "VIEW_3D":
                continue
            region = next(
                (
                    candidate
                    for candidate in getattr(area, "regions", ())
                    if getattr(candidate, "type", None) == "WINDOW"
                ),
                None,
            )
            if region is None:
                continue
            try:
                with context.temp_override(
                    window=window,
                    area=area,
                    region=region,
                ):
                    bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
                updated_workspaces.add(workspace_key)
            except (AttributeError, RuntimeError):
                logger.debug(
                    "Could not switch away from a hidden object tool",
                    exc_info=True,
                )
            break


def _tag_ui_for_redraw(context) -> None:
    window_manager = getattr(context, "window_manager", None)
    windows = getattr(window_manager, "windows", ()) if window_manager else ()
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()) if screen else ():
            try:
                area.tag_redraw()
            except Exception:
                continue


def register_simplified_blender_ui(context=None) -> None:
    if context is None:
        context = bpy.context

    try:
        from bl_ui.space_topbar import TOPBAR_HT_upper_bar

        if not hasattr(TOPBAR_HT_upper_bar, _TOPBAR_ORIGINAL_DRAW_ATTR):
            setattr(
                TOPBAR_HT_upper_bar,
                _TOPBAR_ORIGINAL_DRAW_ATTR,
                TOPBAR_HT_upper_bar.draw_right,
            )
        TOPBAR_HT_upper_bar.draw_right = _draw_moldboxer_topbar_right
    except (AttributeError, ImportError):
        logger.debug("Could not simplify the Blender top bar", exc_info=True)

    try:
        from bl_ui import space_toolsystem_toolbar as toolbar_module

        toolbar_class = toolbar_module.VIEW3D_PT_tools_active
        if not hasattr(toolbar_class, _TOOLBAR_ORIGINAL_OBJECT_TOOLS_ATTR):
            setattr(
                toolbar_class,
                _TOOLBAR_ORIGINAL_OBJECT_TOOLS_ATTR,
                toolbar_class._tools["OBJECT"],
            )
        toolbar_class._tools["OBJECT"] = _moldboxer_object_tools(
            toolbar_module,
            toolbar_class,
        )
        _activate_select_tool_if_removed(context)
    except (AttributeError, ImportError, KeyError):
        logger.debug("Could not simplify the Blender object toolbar", exc_info=True)

    _tag_ui_for_redraw(context)


def unregister_simplified_blender_ui(context=None) -> None:
    if context is None:
        context = bpy.context

    try:
        from bl_ui.space_topbar import TOPBAR_HT_upper_bar

        original_draw = getattr(
            TOPBAR_HT_upper_bar,
            _TOPBAR_ORIGINAL_DRAW_ATTR,
            None,
        )
        if original_draw is not None:
            TOPBAR_HT_upper_bar.draw_right = original_draw
            delattr(TOPBAR_HT_upper_bar, _TOPBAR_ORIGINAL_DRAW_ATTR)
    except (AttributeError, ImportError):
        logger.debug("Could not restore the Blender top bar", exc_info=True)

    try:
        from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active

        original_tools = getattr(
            VIEW3D_PT_tools_active,
            _TOOLBAR_ORIGINAL_OBJECT_TOOLS_ATTR,
            None,
        )
        if original_tools is not None:
            VIEW3D_PT_tools_active._tools["OBJECT"] = original_tools
            delattr(
                VIEW3D_PT_tools_active,
                _TOOLBAR_ORIGINAL_OBJECT_TOOLS_ATTR,
            )
    except (AttributeError, ImportError, KeyError):
        logger.debug("Could not restore the Blender object toolbar", exc_info=True)

    _tag_ui_for_redraw(context)
