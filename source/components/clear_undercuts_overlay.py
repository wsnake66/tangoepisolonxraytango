"""Callback-safe viewport display for Clear Undercuts extraction directions."""

from __future__ import annotations

import math

import bpy  # type: ignore
import mathutils  # type: ignore

from ..bl_utils import (
    _GUIDE_LABEL_BACKGROUND_COLOR,
    _GUIDE_LABEL_BORDER_COLOR,
    _GUIDE_LABEL_BORDER_WIDTH,
    _GUIDE_LABEL_FONT_SIZE,
    _GUIDE_LABEL_MIN_HEIGHT,
    _GUIDE_LABEL_PADDING_X,
    _GUIDE_LABEL_PADDING_Y,
    _GUIDE_LABEL_SHADOW_COLOR,
    _GUIDE_LABEL_SHADOW_OFFSET,
    _GUIDE_LABEL_TEXT_COLOR,
    _get_overlay_ui_scale,
    _scale_overlay_value,
)

_DISTANCE_EPSILON = 1e-6
_EXTRACTION_DIRECTION_COLLECTION = "Moldboxer Extraction Directions"
_EXTRACTION_DIRECTION_HANDLER_KEY = "moldboxer_extraction_direction_overlay"
_EXTRACTION_DIRECTION_ARROW_SCALE = 0.25
_EXTRACTION_DIRECTION_ARROW_MIN_SIZE = 2.0
_EXTRACTION_DIRECTION_COLOR = (1.0, 0.47, 0.035, 1.0)
_EXTRACTION_DIRECTION_DARK = (0.035, 0.028, 0.022, 0.92)

_extraction_direction_overlay_specs = []


def _remove_extraction_direction_draw_handler() -> None:
    handler = bpy.app.driver_namespace.pop(
        _EXTRACTION_DIRECTION_HANDLER_KEY,
        None,
    )
    if handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handler, "WINDOW")
        except (ReferenceError, ValueError):
            pass


def set_extraction_direction_overlay_visible(visible: bool) -> None:
    """Show or hide the direction labels without discarding their data."""
    handler = bpy.app.driver_namespace.get(_EXTRACTION_DIRECTION_HANDLER_KEY)
    if visible:
        if handler is None and _extraction_direction_overlay_specs:
            handler = bpy.types.SpaceView3D.draw_handler_add(
                _draw_extraction_direction_overlay,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
            bpy.app.driver_namespace[_EXTRACTION_DIRECTION_HANDLER_KEY] = handler
    elif handler is not None:
        _remove_extraction_direction_draw_handler()

    _redraw_extraction_direction_viewports()


def clear_extraction_direction_arrows() -> None:
    """Remove the direction overlay and any arrows made by older versions."""
    global _extraction_direction_overlay_specs
    _remove_extraction_direction_draw_handler()
    _extraction_direction_overlay_specs = []

    # Clean up scene objects left by the original Empty-based implementation.
    collection = bpy.data.collections.get(_EXTRACTION_DIRECTION_COLLECTION)
    if collection is not None:
        for arrow in list(collection.objects):
            bpy.data.objects.remove(arrow, do_unlink=True)
        bpy.data.collections.remove(collection)

    _redraw_extraction_direction_viewports()


def _redraw_extraction_direction_viewports() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _direction_overlay_label(section_index: int) -> str:
    return f"B{section_index:02d} Extraction"


def _overlay_rectangles_intersect(first, second, margin: float = 4.0) -> bool:
    return not (
        first[2] + margin < second[0]
        or second[2] + margin < first[0]
        or first[3] + margin < second[1]
        or second[3] + margin < first[1]
    )


def _draw_extraction_direction_overlay() -> None:
    """Draw Moldboxer-styled section arrows in the active 3D viewport."""
    if not _extraction_direction_overlay_specs:
        return
    overlay = getattr(getattr(bpy.context, "space_data", None), "overlay", None)
    if overlay is not None and not bool(getattr(overlay, "show_overlays", True)):
        return
    region = getattr(bpy.context, "region", None)
    region_data = getattr(bpy.context, "region_data", None)
    if region is None or region_data is None:
        return

    import blf  # type: ignore
    import gpu  # type: ignore
    from bpy_extras.view3d_utils import location_3d_to_region_2d  # type: ignore
    from gpu_extras.batch import batch_for_shader  # type: ignore

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")

    def draw_shape(vertices, indices, color):
        shader.bind()
        shader.uniform_float("color", color)
        batch_for_shader(
            shader,
            "TRIS",
            {"pos": vertices},
            indices=indices,
        ).draw(shader)

    def draw_line(start, end, color, width):
        gpu.state.line_width_set(width)
        shader.bind()
        shader.uniform_float("color", color)
        batch_for_shader(shader, "LINES", {"pos": (start, end)}).draw(shader)

    def draw_circle(center, radius, color, segments=16):
        vertices = [center]
        vertices.extend(
            (
                center[0] + math.cos(angle) * radius,
                center[1] + math.sin(angle) * radius,
            )
            for angle in (
                index * math.tau / segments
                for index in range(segments)
            )
        )
        indices = [
            (0, index + 1, (index + 1) % segments + 1)
            for index in range(segments)
        ]
        draw_shape(vertices, indices, color)

    def draw_rectangle(bounds, color):
        left, bottom, right, top = bounds
        vertices = (
            (left, bottom),
            (right, bottom),
            (right, top),
            (left, top),
        )
        draw_shape(vertices, ((0, 1, 2), (0, 2, 3)), color)

    projected_specs = []
    for spec in _extraction_direction_overlay_specs:
        start = location_3d_to_region_2d(region, region_data, spec["origin"])
        end = location_3d_to_region_2d(region, region_data, spec["endpoint"])
        if start is None or end is None:
            continue
        delta = end - start
        if delta.length < 8.0:
            continue
        direction_2d = delta.normalized()
        perpendicular = mathutils.Vector((-direction_2d.y, direction_2d.x))
        projected_specs.append((spec, start, end, direction_2d, perpendicular))

    gpu.state.blend_set("ALPHA")
    try:
        # Draw every arrow first so labels remain clean and readable on top.
        for _spec, start, end, direction_2d, perpendicular in projected_specs:
            draw_line(start, end, _EXTRACTION_DIRECTION_DARK, 7.0)
            draw_line(start, end, _EXTRACTION_DIRECTION_COLOR, 3.0)
            draw_circle(start, 6.0, _EXTRACTION_DIRECTION_DARK)
            draw_circle(start, 3.5, _EXTRACTION_DIRECTION_COLOR)

            outer_base = end - direction_2d * 17.0
            inner_base = end - direction_2d * 14.0
            draw_shape(
                (
                    end,
                    outer_base + perpendicular * 9.0,
                    outer_base - perpendicular * 9.0,
                ),
                ((0, 1, 2),),
                _EXTRACTION_DIRECTION_DARK,
            )
            draw_shape(
                (
                    end,
                    inner_base + perpendicular * 6.5,
                    inner_base - perpendicular * 6.5,
                ),
                ((0, 1, 2),),
                _EXTRACTION_DIRECTION_COLOR,
            )

        ui_scale = _get_overlay_ui_scale(bpy.context)
        font_id = 0
        font_size = _scale_overlay_value(_GUIDE_LABEL_FONT_SIZE, ui_scale)
        padding_x = float(
            _scale_overlay_value(_GUIDE_LABEL_PADDING_X, ui_scale)
        )
        padding_y = float(
            _scale_overlay_value(_GUIDE_LABEL_PADDING_Y, ui_scale)
        )
        min_height = float(
            _scale_overlay_value(_GUIDE_LABEL_MIN_HEIGHT, ui_scale)
        )
        border_width = max(1.0, _GUIDE_LABEL_BORDER_WIDTH * ui_scale)
        shadow_offset = float(
            _scale_overlay_value(_GUIDE_LABEL_SHADOW_OFFSET, ui_scale)
        )
        blf.size(font_id, font_size)
        occupied_bounds = []
        for spec, _start, end, direction_2d, perpendicular in projected_specs:
            label = spec["label"]
            text_width, text_height = blf.dimensions(font_id, label)
            box_width = text_width + (padding_x * 2.0)
            box_height = max(min_height, text_height + (padding_y * 2.0))
            label_center = end + direction_2d * 13.0 + perpendicular * 12.0
            if label_center.x + box_width > region.width - 8.0:
                label_center.x = end.x - box_width - 13.0

            bounds = (
                label_center.x,
                label_center.y - box_height * 0.5,
                label_center.x + box_width,
                label_center.y + box_height * 0.5,
            )
            for shift_index in range(8):
                if not any(
                    _overlay_rectangles_intersect(bounds, occupied)
                    for occupied in occupied_bounds
                ):
                    break
                shift = box_height + 5.0
                direction = 1.0 if shift_index % 2 == 0 else -1.0
                distance = (shift_index // 2 + 1) * shift * direction
                bounds = (
                    bounds[0],
                    label_center.y - box_height * 0.5 + distance,
                    bounds[2],
                    label_center.y + box_height * 0.5 + distance,
                )
            horizontal_shift = 0.0
            vertical_shift = 0.0
            if bounds[0] < 8.0:
                horizontal_shift = 8.0 - bounds[0]
            elif bounds[2] > region.width - 8.0:
                horizontal_shift = region.width - 8.0 - bounds[2]
            if bounds[1] < 8.0:
                vertical_shift = 8.0 - bounds[1]
            elif bounds[3] > region.height - 8.0:
                vertical_shift = region.height - 8.0 - bounds[3]
            bounds = (
                bounds[0] + horizontal_shift,
                bounds[1] + vertical_shift,
                bounds[2] + horizontal_shift,
                bounds[3] + vertical_shift,
            )
            occupied_bounds.append(bounds)

            border = (
                bounds[0] - border_width,
                bounds[1] - border_width,
                bounds[2] + border_width,
                bounds[3] + border_width,
            )
            shadow = (
                border[0] + shadow_offset,
                border[1] - shadow_offset,
                border[2] + shadow_offset,
                border[3] - shadow_offset,
            )
            draw_rectangle(shadow, _GUIDE_LABEL_SHADOW_COLOR)
            draw_rectangle(border, _GUIDE_LABEL_BORDER_COLOR)
            draw_rectangle(bounds, _GUIDE_LABEL_BACKGROUND_COLOR)
            blf.color(font_id, *_GUIDE_LABEL_TEXT_COLOR)
            blf.position(
                font_id,
                bounds[0] + padding_x,
                bounds[1] + (box_height - text_height) * 0.5,
                0.0,
            )
            blf.draw(font_id, label)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.blend_set("NONE")


def display_worker_extraction_direction_arrows(selected_paths) -> None:
    """Display arrows from compact bounds returned by the fused worker."""

    global _extraction_direction_overlay_specs
    clear_extraction_direction_arrows()
    overlay_specs = []
    for section_index, path in enumerate(selected_paths, start=1):
        try:
            minimum = mathutils.Vector(path["display_bounds_min"])
            maximum = mathutils.Vector(path["display_bounds_max"])
            extraction_direction = mathutils.Vector(path["direction"])
            section = tuple(int(value) for value in path["section"])
        except (KeyError, TypeError, ValueError):
            continue
        if extraction_direction.length_squared <= _DISTANCE_EPSILON**2:
            continue
        extraction_direction.normalize()
        center = (
            mathutils.Vector(path["display_origin"])
            if path.get("display_origin") is not None
            else (minimum + maximum) * 0.5
        )
        arrow_size = max(
            _EXTRACTION_DIRECTION_ARROW_MIN_SIZE,
            (maximum - minimum).length * _EXTRACTION_DIRECTION_ARROW_SCALE,
        )
        overlay_specs.append(
            {
                "origin": center,
                "endpoint": center + extraction_direction * arrow_size,
                "direction": extraction_direction,
                "section": section,
                "label": _direction_overlay_label(section_index),
            }
        )

    if not overlay_specs:
        return
    _extraction_direction_overlay_specs = overlay_specs
    set_extraction_direction_overlay_visible(True)
