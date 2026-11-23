"""Record Blender panel layouts and render them as a viewport overlay.

Blender does not expose persistent ``UILayout`` widgets outside editor regions.
This adapter records the add-on's existing panel draw calls and turns their
labels, properties and operators into a compact, scrollable viewport panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import blf  # type: ignore
import bpy  # type: ignore
import gpu  # type: ignore
from gpu_extras.batch import batch_for_shader  # type: ignore
from gpu_extras.presets import draw_texture_2d  # type: ignore

from .bl_utils import _draw_overlay_background, _get_overlay_ui_scale, _scale_overlay_value
from .i18n import t
from .preview_badges import load_catalog_preview_image
from .scene_units import format_distance


PANEL_WIDTH = 318
PANEL_RIGHT_MARGIN = 0
PANEL_VERTICAL_MARGIN = 12
PANEL_HEADER_HEIGHT = 40
ROW_HEIGHT = 28
ROW_GAP = 4
SECTION_GAP = 8
CONTENT_PADDING = 10

PANEL_COLOR = (0.105, 0.105, 0.105, 0.985)
PANEL_BORDER = (0.22, 0.22, 0.22, 1.0)
HEADER_COLOR = (0.075, 0.075, 0.075, 1.0)
SECTION_COLOR = (0.145, 0.145, 0.145, 1.0)
CONTROL_COLOR = (0.125, 0.125, 0.125, 0.98)
CONTROL_HOVER_COLOR = (0.541, 0.365, 0.047, 1.0)
CONTROL_BORDER = (0.22, 0.22, 0.22, 1.0)
ACCENT_BORDER = (0.714, 0.490, 0.071, 1.0)
TEXT_COLOR = (0.94, 0.94, 0.94, 1.0)
MUTED_TEXT_COLOR = (0.67, 0.67, 0.67, 1.0)
DISABLED_TEXT_COLOR = (0.38, 0.38, 0.38, 1.0)
PRO_BADGE_COLOR = (116 / 255, 48 / 255, 181 / 255, 1.0)
PRO_BADGE_BOTTOM_COLOR = (79 / 255, 29 / 255, 139 / 255, 1.0)
PRO_BADGE_BORDER = (151 / 255, 91 / 255, 210 / 255, 1.0)
PRO_BADGE_TEXT_COLOR = (1.0, 252 / 255, 1.0, 1.0)
CORE_BADGE_COLOR = (0.541, 0.365, 0.047, 0.96)
CORE_BADGE_BORDER = (0.714, 0.490, 0.071, 1.0)
CORE_BADGE_TEXT_COLOR = (1.0, 0.945, 0.780, 1.0)
PREVIEW_HEIGHT = 112

UTILITY_COLUMN_WIDTH = 108
UTILITY_COLUMN_RIGHT_MARGIN = 12
UTILITY_COLUMN_TOP_MARGIN = 16
UTILITY_COLUMN_BOTTOM_MARGIN = 150
UTILITY_CARD_HEIGHT = 112
UTILITY_CARD_MIN_HEIGHT = 54
UTILITY_CARD_GAP = 8
UTILITY_CARD_LABEL_HEIGHT = 30
UTILITY_CARD_IMAGE_LABEL_OVERLAP = 8

_preview_path_resolver = None
_preview_texture_cache: dict[str, tuple[Any, Any]] = {}

ENUM_FALLBACK_LABELS = {
    "FAST": "Fast",
    "MID": "Balanced",
    "HIGH": "High Detail",
    "VERY HIGH": "Very High Detail",
    "ULTRA": "Ultra Detail",
    "EXTREME": "Extreme Detail",
    "OPTIMIZED": "Optimized (Beta)",
    "EASY_EXTRACTION": "Easy Extraction",
}


@dataclass
class RecordedNode:
    kind: str
    children: list["RecordedNode"] = field(default_factory=list)
    data: Any = None
    prop_name: str = ""
    text: str = ""
    icon: str = ""
    operator: str = ""
    operator_properties: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    active: bool = True
    depress: bool = False
    factor: float = 0.5
    icon_value: int = 0


class OperatorPropertyRecorder:
    def __init__(self, node: RecordedNode):
        object.__setattr__(self, "_node", node)

    def __setattr__(self, name: str, value: Any) -> None:
        self._node.operator_properties[name] = value

    def __getattr__(self, name: str) -> Any:
        return self._node.operator_properties.get(name)


class LayoutRecorder:
    """Small UILayout-compatible recorder for Moldboxer's panel draw code."""

    _LOCAL_ATTRIBUTES = {
        "node",
        "enabled",
        "active",
        "alert",
        "alignment",
        "operator_context",
        "scale_x",
        "scale_y",
        "use_property_split",
        "use_property_decorate",
    }

    def __init__(self, node: RecordedNode | None = None):
        object.__setattr__(self, "node", node or RecordedNode("column"))
        object.__setattr__(self, "enabled", True)
        object.__setattr__(self, "active", True)
        object.__setattr__(self, "alert", False)
        object.__setattr__(self, "alignment", "EXPAND")
        object.__setattr__(self, "operator_context", "INVOKE_DEFAULT")
        object.__setattr__(self, "scale_x", 1.0)
        object.__setattr__(self, "scale_y", 1.0)
        object.__setattr__(self, "use_property_split", False)
        object.__setattr__(self, "use_property_decorate", False)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name == "enabled":
            self.node.enabled = bool(value)
        elif name == "active":
            self.node.active = bool(value)

    def _container(self, kind: str, *, factor: float = 0.5, **_kwargs):
        child = RecordedNode(kind=kind, factor=factor)
        self.node.children.append(child)
        return LayoutRecorder(child)

    def row(self, **kwargs):
        return self._container("row", **kwargs)

    def column(self, **kwargs):
        return self._container("column", **kwargs)

    def box(self):
        return self._container("box")

    def split(self, factor=0.5, **kwargs):
        return self._container("row", factor=float(factor), **kwargs)

    def grid_flow(self, **kwargs):
        return self._container("grid", **kwargs)

    def label(self, text="", icon="NONE", **_kwargs):
        self.node.children.append(
            RecordedNode(kind="label", text=str(text), icon=str(icon or ""))
        )

    def prop(self, data, prop_name, text=None, icon="NONE", **kwargs):
        label = text
        if label is None:
            try:
                label = data.bl_rna.properties[prop_name].name
            except Exception:
                label = prop_name.replace("_", " ").title()
        self.node.children.append(
            RecordedNode(
                kind="property",
                data=data,
                prop_name=str(prop_name),
                text=str(label or ""),
                icon=str(icon or ""),
                depress=bool(kwargs.get("toggle", False)),
            )
        )

    def prop_search(self, data, prop_name, *_args, text=None, icon="NONE", **kwargs):
        self.prop(data, prop_name, text=text, icon=icon, **kwargs)

    def operator(self, operator, text="", icon="NONE", depress=False, **_kwargs):
        node = RecordedNode(
            kind="operator",
            operator=str(operator),
            text=str(text or operator.rsplit(".", 1)[-1].replace("_", " ").title()),
            icon=str(icon or ""),
            depress=bool(depress),
        )
        self.node.children.append(node)
        return OperatorPropertyRecorder(node)

    def operator_menu_enum(self, operator, _property, text="", icon="NONE", **kwargs):
        return self.operator(operator, text=text, icon=icon, **kwargs)

    def menu(self, menu, text="", icon="NONE", **_kwargs):
        self.node.children.append(
            RecordedNode(kind="menu", operator=str(menu), text=str(text or menu), icon=str(icon or ""))
        )

    def popover(self, panel, text="", icon="NONE", **_kwargs):
        self.node.children.append(
            RecordedNode(kind="popover", operator=str(panel), text=str(text or panel), icon=str(icon or ""))
        )

    def template_icon_view(self, data, prop_name, **_kwargs):
        self.node.children.append(
            RecordedNode(
                kind="preview",
                data=data,
                prop_name=str(prop_name),
            )
        )

    def template_icon(self, icon_value=0, **_kwargs):
        self.node.children.append(
            RecordedNode(kind="preview", icon_value=int(icon_value or 0))
        )

    def separator(self, factor=1.0, **_kwargs):
        self.node.children.append(RecordedNode(kind="spacer", factor=float(factor)))

    def separator_spacer(self):
        self.separator()


def record_panels(context, panel_specs):
    roots: list[RecordedNode] = []
    for panel_id, label, draw_callable in panel_specs:
        root = RecordedNode(kind="panel", text=str(label), operator=str(panel_id))
        recorder = LayoutRecorder(root)
        try:
            draw_callable(recorder, context)
        except Exception as exc:
            root.children.append(
                RecordedNode(
                    kind="label",
                    text=t("Could not draw: {error}", error=exc),
                    enabled=False,
                )
            )
        roots.append(root)
    return roots


def set_preview_path_resolver(resolver):
    """Install the add-on's preview lookup without coupling this renderer to panels.py."""
    global _preview_path_resolver
    _preview_path_resolver = resolver


def _effective_enabled(node: RecordedNode, inherited: bool) -> bool:
    return bool(inherited and node.enabled and node.active)


def flatten_nodes(nodes, collapsed_sections):
    rows: list[dict[str, Any]] = []
    next_card_id = 0

    def visit(node: RecordedNode, enabled=True, depth=0, card_id=0):
        nonlocal next_card_id
        current_enabled = _effective_enabled(node, enabled)
        if node.kind == "panel":
            rows.append(
                {
                    "kind": "section",
                    "text": node.text,
                    "section": node.operator,
                    "enabled": True,
                    "depth": 0,
                }
            )
            if node.operator in collapsed_sections:
                return
            for child in node.children:
                visit(child, current_enabled, depth + 1, 0)
            return
        if node.kind in {"column", "row", "grid"}:
            for child in node.children:
                visit(child, current_enabled, depth, card_id)
            return
        if node.kind == "box":
            next_card_id += 1
            nested_card_id = next_card_id
            rows.append({"kind": "gap", "height": SECTION_GAP})
            for child in node.children:
                visit(child, current_enabled, depth + 1, nested_card_id)
            rows.append({"kind": "gap", "height": 3})
            return
        if node.kind == "spacer":
            rows.append({"kind": "gap", "height": 5})
            return
        if node.kind == "preview":
            rows.append(
                {
                    "kind": "preview",
                    "data": node.data,
                    "prop_name": node.prop_name,
                    "icon_value": node.icon_value,
                    "enabled": current_enabled,
                    "depth": depth,
                    "card": card_id,
                }
            )
            return
        if node.kind == "label":
            if node.text:
                rows.append(
                    {
                        "kind": "label",
                        "text": node.text,
                        "enabled": current_enabled,
                        "depth": depth,
                        "card": card_id,
                    }
                )
            return
        if node.kind == "property":
            rows.append(
                {
                    "kind": "property",
                    "text": node.text,
                    "data": node.data,
                    "prop_name": node.prop_name,
                    "enabled": current_enabled,
                    "depth": depth,
                    "card": card_id,
                }
            )
            return
        if node.kind in {"operator", "menu", "popover"}:
            rows.append(
                {
                    "kind": node.kind,
                    "text": node.text,
                    "operator": node.operator,
                    "properties": dict(node.operator_properties),
                    "enabled": current_enabled,
                    "depress": node.depress,
                    "depth": depth,
                    "card": card_id,
                }
            )

    for root in nodes:
        visit(root)
    return rows


def _property_metadata(data, prop_name):
    try:
        return data.bl_rna.properties[prop_name]
    except Exception:
        return None


def property_display_value(data, prop_name):
    try:
        value = getattr(data, prop_name)
    except Exception:
        return "—"
    metadata = _property_metadata(data, prop_name)
    prop_type = str(getattr(metadata, "type", ""))
    if prop_type == "BOOLEAN":
        return "On" if bool(value) else "Off"
    if prop_type == "ENUM":
        try:
            identifier = str(value)
            item = next(
                (
                    enum_item
                    for enum_item in metadata.enum_items
                    if str(enum_item.identifier) == identifier
                ),
                None,
            )
            return str(
                item.name
                if item is not None
                else ENUM_FALLBACK_LABELS.get(identifier, identifier.replace("_", " ").title())
            )
        except Exception:
            return str(value)
    if prop_type == "FLOAT":
        try:
            rendered = f"{float(value):.3g}"
            if str(getattr(metadata, "subtype", "")) == "DISTANCE":
                scene = data if isinstance(data, bpy.types.Scene) else bpy.context.scene
                return format_distance(float(value), scene)
            return rendered
        except Exception:
            return str(value)
    if prop_type == "INT":
        return str(int(value))
    if isinstance(value, (tuple, list)):
        return ", ".join(f"{float(item):.3g}" for item in value)
    return str(value)


def register_target(targets, data):
    try:
        token = f"rna:{int(data.as_pointer())}"
    except Exception:
        token = f"py:{id(data)}"
    targets[token] = data
    return token


def _draw_text(text, x, y, size, color, max_width=None):
    font_id = 0
    blf.size(font_id, max(8, int(size)))
    rendered = str(text)
    if max_width is not None:
        while rendered and blf.dimensions(font_id, rendered)[0] > max_width:
            rendered = rendered[:-1]
        if rendered != str(text) and len(rendered) > 1:
            rendered = rendered[:-1] + "…"
    blf.color(font_id, *color)
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, rendered)


def _resolve_preview_path(row):
    if not callable(_preview_path_resolver):
        return ""
    try:
        return str(
            _preview_path_resolver(
                int(row.get("icon_value", 0)),
                row.get("data"),
                str(row.get("prop_name", "")),
            )
            or ""
        )
    except Exception:
        return ""


def _preview_texture(path):
    cached = _preview_texture_cache.get(path)
    if cached is not None:
        image, texture = cached
        try:
            image.as_pointer()
            return image, texture
        except ReferenceError:
            _preview_texture_cache.pop(path, None)
    try:
        image = load_catalog_preview_image(path)
        texture = gpu.texture.from_image(image)
    except Exception:
        return None, None
    _preview_texture_cache[path] = (image, texture)
    return image, texture


def _draw_preview(path, x, y, width, height, enabled=True, inset=8):
    image, texture = _preview_texture(path)
    if image is None or texture is None:
        return
    try:
        image_width, image_height = image.size[:2]
    except (ReferenceError, TypeError):
        return
    if image_width <= 0 or image_height <= 0:
        return
    available_width = max(1, width - (inset * 2))
    available_height = max(1, height - (inset * 2))
    image_ratio = image_width / image_height
    draw_width = min(available_width, available_height * image_ratio)
    draw_height = draw_width / image_ratio
    if draw_height > available_height:
        draw_height = available_height
        draw_width = draw_height * image_ratio
    draw_x = x + ((width - draw_width) / 2)
    draw_y = y + ((height - draw_height) / 2)
    gpu.state.blend_set("ALPHA")
    try:
        draw_texture_2d(
            texture,
            (draw_x, draw_y),
            draw_width,
            draw_height,
            is_scene_linear_with_rec709_srgb_target=True,
        )
    finally:
        gpu.state.blend_set("NONE")


def utility_column_rect(context, region, action_count):
    """Return the visible, viewport-bounded portion of the utility column."""
    scale = _get_overlay_ui_scale(context)
    width = _scale_overlay_value(UTILITY_COLUMN_WIDTH, scale)
    gap = _scale_overlay_value(UTILITY_CARD_GAP, scale)
    right_margin = _scale_overlay_value(UTILITY_COLUMN_RIGHT_MARGIN, scale)
    top_margin = _scale_overlay_value(UTILITY_COLUMN_TOP_MARGIN, scale)
    bottom_margin = _scale_overlay_value(UTILITY_COLUMN_BOTTOM_MARGIN, scale)
    desired_card_height = _scale_overlay_value(UTILITY_CARD_HEIGHT, scale)
    minimum_card_height = _scale_overlay_value(UTILITY_CARD_MIN_HEIGHT, scale)
    available_height = max(
        minimum_card_height,
        int(region.height) - top_margin - bottom_margin,
    )
    card_height = max(
        minimum_card_height,
        min(desired_card_height, available_height),
    )
    visible_capacity = max(
        1,
        (available_height + gap) // max(1, card_height + gap),
    )
    action_count = max(0, int(action_count))
    visible_count = min(action_count, visible_capacity)
    content_height = max(
        0,
        (card_height * action_count) + (gap * max(0, action_count - 1)),
    )
    height = min(available_height, content_height)
    return {
        "x": int(region.width) - width - right_margin,
        "y": int(region.height) - top_margin - height,
        "width": width,
        "height": height,
        "card_height": card_height,
        "gap": gap,
        "scale": scale,
        "visible_count": visible_count,
        "content_height": content_height,
        "max_scroll": max(0, content_height - height),
        "scroll_step": card_height + gap,
    }


def _draw_pro_badge_gradient(x, y, width, height):
    """Fill the inset capsule with the same violet gradient as picker artwork."""
    import math

    x, y, width, height = x + 1, y + 1, width - 2, height - 2
    if width <= 0 or height <= 0:
        return
    radius = min(width, height) / 2
    perimeter = []
    for cx, cy, start in (
        (x + radius, y + radius, math.pi),
        (x + width - radius, y + radius, 1.5 * math.pi),
        (x + width - radius, y + height - radius, 0),
        (x + radius, y + height - radius, 0.5 * math.pi),
    ):
        for step in range(9):
            angle = start + step * math.pi / 16
            perimeter.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    vertices = []
    center = (x + width / 2, y + height / 2)
    for index, point in enumerate(perimeter):
        vertices.extend((center, point, perimeter[(index + 1) % len(perimeter)]))
    colors = []
    for _, py in vertices:
        t = min(1.0, max(0.0, (py - y) / height))
        colors.append(tuple(bottom * (1 - t) + top * t
                            for bottom, top in zip(PRO_BADGE_BOTTOM_COLOR, PRO_BADGE_COLOR)))
    shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": vertices, "color": colors})
    gpu.state.blend_set("ALPHA")
    try:
        shader.bind()
        batch.draw(shader)
    finally:
        gpu.state.blend_set("NONE")


def _draw_utility_pro_badge(label, left_x, top_y, scale):
    is_core_badge = str(label).upper() == "CORE"
    badge_color = CORE_BADGE_COLOR if is_core_badge else PRO_BADGE_COLOR
    badge_border = CORE_BADGE_BORDER if is_core_badge else PRO_BADGE_BORDER
    badge_text_color = (
        CORE_BADGE_TEXT_COLOR if is_core_badge else PRO_BADGE_TEXT_COLOR
    )
    badge_font_size = _scale_overlay_value(7, scale)
    badge_padding_x = _scale_overlay_value(4, scale)
    badge_height = _scale_overlay_value(14, scale)
    # The shared text helper renders at a minimum of 8 px. Measure at that
    # effective size as well, extending only the pill's right edge so the
    # badge label fits without changing the image or card layout.
    badge_render_font_size = max(8, badge_font_size)
    blf.size(0, badge_render_font_size)
    badge_width = int(blf.dimensions(0, label)[0]) + (badge_padding_x * 2)
    x = left_x
    y = top_y - badge_height
    _draw_overlay_background(
        x,
        y,
        badge_width,
        badge_height,
        color=badge_color,
        corner_radius=max(2, badge_height // 2),
        border_color=badge_border,
        border_width=1,
    )
    if not is_core_badge:
        _draw_pro_badge_gradient(x, y, badge_width, badge_height)
    _draw_text(
        label,
        x + badge_padding_x,
        y + _scale_overlay_value(4, scale),
        badge_font_size,
        badge_text_color,
        badge_width - (badge_padding_x * 2),
    )
    return badge_width, badge_height


def _draw_utility_card_label(
    label,
    x,
    y,
    width,
    height,
    scale,
    color,
):
    font_size = _scale_overlay_value(10, scale)
    blf.size(0, font_size)
    max_width = width - _scale_overlay_value(12, scale)
    words = str(label).split()
    lines = []
    for word in words:
        candidate = " ".join((*lines[-1:], word)) if lines else word
        if lines and blf.dimensions(0, candidate)[0] <= max_width:
            lines[-1] = candidate
        elif len(lines) < 2:
            lines.append(word)
        else:
            lines[-1] = f"{lines[-1]} {word}"
    lines = lines or [""]
    line_height = _scale_overlay_value(12, scale)
    first_y = y + max(
        _scale_overlay_value(4, scale),
        (height - (line_height * len(lines))) / 2,
    )
    for index, line in enumerate(reversed(lines)):
        rendered = line
        while rendered and blf.dimensions(0, rendered)[0] > max_width:
            rendered = rendered[:-1]
        if rendered != line and len(rendered) > 1:
            rendered = rendered[:-1] + "…"
        text_width = blf.dimensions(0, rendered)[0]
        _draw_text(
            rendered,
            x + max(0, (width - text_width) / 2),
            first_y + (index * line_height),
            font_size,
            color,
            max_width,
        )


def _draw_utility_overflow_indicator(
    direction,
    rect,
    hovered_id,
):
    scale = rect["scale"]
    size = _scale_overlay_value(30, scale)
    height = _scale_overlay_value(22, scale)
    indicator_id = f"viewport-utility-scroll:{direction}"
    x = rect["x"] + ((rect["width"] - size) / 2)
    if direction == "up":
        y = rect["y"] + rect["height"] - height - _scale_overlay_value(5, scale)
        glyph = "▲"
        delta = -rect["scroll_step"]
    else:
        y = rect["y"] + _scale_overlay_value(5, scale)
        glyph = "▼"
        delta = rect["scroll_step"]
    hovered = indicator_id == hovered_id
    _draw_overlay_background(
        x,
        y,
        size,
        height,
        color=ACCENT_BORDER if hovered else CONTROL_HOVER_COLOR,
        corner_radius=max(2, height // 2),
        border_color=CORE_BADGE_TEXT_COLOR,
        border_width=1,
    )
    font_size = _scale_overlay_value(11, scale)
    blf.size(0, font_size)
    glyph_width = blf.dimensions(0, glyph)[0]
    _draw_text(
        glyph,
        x + ((size - glyph_width) / 2),
        y + _scale_overlay_value(5, scale),
        font_size,
        CORE_BADGE_TEXT_COLOR,
        size,
    )
    return {
        "id": indicator_id,
        "kind": "utility-scroll",
        "delta": delta,
        "x": x,
        "y": y,
        "width": size,
        "height": height,
        "enabled": True,
    }


def _draw_utility_partial_card_fade(
    x,
    clipped_y,
    width,
    clipped_height,
    card_height,
    *,
    fade_from_top,
):
    """Visually recede a clipped card with a smooth edge gradient."""
    if clipped_height <= 0 or card_height <= 0:
        return
    visible_ratio = max(0.0, min(1.0, clipped_height / card_height))
    fade_rgb = HEADER_COLOR[:3]
    edge_alpha = 0.34 + ((1.0 - visible_ratio) * 0.18)
    inner_alpha = 0.06
    bottom_alpha = inner_alpha if fade_from_top else edge_alpha
    top_alpha = edge_alpha if fade_from_top else inner_alpha
    positions = (
        (x, clipped_y),
        (x + width, clipped_y),
        (x + width, clipped_y + clipped_height),
        (x, clipped_y + clipped_height),
    )
    colors = (
        (*fade_rgb, bottom_alpha),
        (*fade_rgb, bottom_alpha),
        (*fade_rgb, top_alpha),
        (*fade_rgb, top_alpha),
    )
    shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    batch = batch_for_shader(
        shader,
        "TRIS",
        {"pos": positions, "color": colors},
        indices=((0, 1, 2), (2, 3, 0)),
    )
    gpu.state.blend_set("ALPHA")
    try:
        batch.draw(shader)
    finally:
        gpu.state.blend_set("NONE")


def draw_utility_column(
    context,
    region,
    actions,
    hovered_id="",
    scroll_offset=0.0,
):
    """Draw a bounded, scrollable column of right-side utility cards."""
    rect = utility_column_rect(context, region, len(actions))
    scale = rect["scale"]
    scroll_offset = max(0.0, min(float(scroll_offset), rect["max_scroll"]))
    label_height = min(
        _scale_overlay_value(UTILITY_CARD_LABEL_HEIGHT, scale),
        max(22, rect["card_height"] // 3),
    )
    image_height = max(1, rect["card_height"] - label_height)
    image_label_overlap = min(
        _scale_overlay_value(UTILITY_CARD_IMAGE_LABEL_OVERLAP, scale),
        max(0, label_height // 3),
    )
    radius = _scale_overlay_value(7, scale)
    hitboxes = []
    viewport = gpu.state.viewport_get()
    gpu.state.scissor_set(
        int(viewport[0] + rect["x"]),
        int(viewport[1] + rect["y"]),
        int(rect["width"]),
        int(rect["height"]),
    )
    gpu.state.scissor_test_set(True)
    try:
        for index, action in enumerate(actions):
            card_id = f"viewport-utility-card:{index}:{action['operator']}"
            card_x = rect["x"]
            card_y = (
                int(region.height)
                - _scale_overlay_value(UTILITY_COLUMN_TOP_MARGIN, scale)
                - rect["card_height"]
                - (index * (rect["card_height"] + rect["gap"]))
                + scroll_offset
            )
            clipped_y = max(card_y, rect["y"])
            clipped_top = min(
                card_y + rect["card_height"],
                rect["y"] + rect["height"],
            )
            if clipped_top <= clipped_y:
                continue
            enabled = bool(action.get("enabled", True))
            hovered = enabled and card_id == hovered_id
            fill = CONTROL_HOVER_COLOR if hovered else CONTROL_COLOR
            border = ACCENT_BORDER if hovered else CONTROL_BORDER
            _draw_overlay_background(
                card_x,
                card_y,
                rect["width"],
                rect["card_height"],
                color=fill,
                corner_radius=radius,
                border_color=border,
                border_width=1,
            )
            preview_path = str(action.get("preview_path", "") or "")
            badge = str(action.get("badge", "") or "")
            if preview_path:
                preview_inset = _scale_overlay_value(7 if badge else 2, scale)
                _draw_preview(
                    preview_path,
                    card_x,
                    card_y + label_height - image_label_overlap,
                    rect["width"],
                    image_height + image_label_overlap,
                    enabled,
                    inset=preview_inset,
                )
            if badge:
                badge_inset = _scale_overlay_value(12, scale)
                _draw_utility_pro_badge(
                    badge,
                    card_x + badge_inset,
                    card_y + rect["card_height"] - badge_inset,
                    scale,
                )
            label = str(action.get("label", ""))
            _draw_utility_card_label(
                label,
                card_x,
                card_y,
                rect["width"],
                label_height,
                scale,
                TEXT_COLOR if enabled else DISABLED_TEXT_COLOR,
            )
            top_clipped = (
                card_y + rect["card_height"]
                > rect["y"] + rect["height"] + 0.5
            )
            bottom_clipped = card_y < rect["y"] - 0.5
            if top_clipped or bottom_clipped:
                _draw_utility_partial_card_fade(
                    card_x,
                    clipped_y,
                    rect["width"],
                    clipped_top - clipped_y,
                    rect["card_height"],
                    fade_from_top=top_clipped,
                )
            hitboxes.append(
                {
                    "id": card_id,
                    "x": card_x,
                    "y": clipped_y,
                    "width": rect["width"],
                    "height": clipped_top - clipped_y,
                    "enabled": enabled,
                    "action": action,
                }
            )
    finally:
        gpu.state.scissor_test_set(False)

    if scroll_offset > 0.5:
        hitboxes.append(
            _draw_utility_overflow_indicator("up", rect, hovered_id)
        )
    if scroll_offset < rect["max_scroll"] - 0.5:
        hitboxes.append(
            _draw_utility_overflow_indicator("down", rect, hovered_id)
        )

    return {
        "rect": rect,
        "hitboxes": hitboxes,
        "scroll": scroll_offset,
        "max_scroll": rect["max_scroll"],
        "scroll_step": rect["scroll_step"],
    }


def panel_rect(context, region):
    ui_scale = _get_overlay_ui_scale(context)
    width = min(
        _scale_overlay_value(PANEL_WIDTH, ui_scale),
        max(220, int(region.width) - 48),
    )
    right_margin = _scale_overlay_value(PANEL_RIGHT_MARGIN, ui_scale, minimum=0)
    vertical_margin = _scale_overlay_value(PANEL_VERTICAL_MARGIN, ui_scale)
    return {
        "x": int(region.width) - width - right_margin,
        "y": vertical_margin,
        "width": width,
        "height": max(160, int(region.height) - (vertical_margin * 2)),
        "ui_scale": ui_scale,
    }


def draw_panel(context, region, rows, scroll_offset, hovered_id, collapsed_sections):
    rect = panel_rect(context, region)
    x = rect["x"]
    y = rect["y"]
    width = rect["width"]
    height = rect["height"]
    scale = rect["ui_scale"]
    header_height = _scale_overlay_value(PANEL_HEADER_HEIGHT, scale)
    row_height = _scale_overlay_value(ROW_HEIGHT, scale)
    row_gap = _scale_overlay_value(ROW_GAP, scale)
    padding = _scale_overlay_value(CONTENT_PADDING, scale)
    content_top = y + height - header_height - padding
    content_bottom = y + padding

    _draw_overlay_background(
        x,
        y,
        width,
        height,
        color=PANEL_COLOR,
        corner_radius=_scale_overlay_value(8, scale),
        border_color=PANEL_BORDER,
        border_width=1,
    )
    _draw_overlay_background(
        x,
        y + height - header_height,
        width,
        header_height,
        color=HEADER_COLOR,
        corner_radius=_scale_overlay_value(8, scale),
    )
    _draw_text(
        "Moldboxer",
        x + padding,
        y + height - header_height + _scale_overlay_value(13, scale),
        _scale_overlay_value(14, scale),
        TEXT_COLOR,
    )

    targets: dict[str, Any] = {}
    hitboxes: list[dict[str, Any]] = []
    cursor_y = content_top + int(scroll_offset)
    content_height = 0
    positioned_rows = []
    for index, row in enumerate(rows):
        if row["kind"] == "gap":
            gap = _scale_overlay_value(int(row.get("height", 5)), scale)
            cursor_y -= gap
            content_height += gap
            continue
        current_height = (
            _scale_overlay_value(PREVIEW_HEIGHT, scale)
            if row["kind"] == "preview"
            else row_height
        )
        row_y = cursor_y - current_height
        cursor_y = row_y - row_gap
        content_height += current_height + row_gap
        positioned_rows.append((index, row, row_y, current_height))

    card_bounds: dict[int, list[int]] = {}
    for _index, row, row_y, current_height in positioned_rows:
        card_id = int(row.get("card", 0))
        if not card_id:
            continue
        bounds = card_bounds.setdefault(
            card_id,
            [row_y, row_y + current_height],
        )
        bounds[0] = min(bounds[0], row_y)
        bounds[1] = max(bounds[1], row_y + current_height)
    card_inset = _scale_overlay_value(5, scale)
    for card_y, card_top in card_bounds.values():
        visible_y = max(content_bottom, card_y - card_inset)
        visible_top = min(content_top, card_top + card_inset)
        if visible_top <= visible_y:
            continue
        _draw_overlay_background(
            x + padding,
            visible_y,
            width - (padding * 2),
            visible_top - visible_y,
            color=(0.085, 0.085, 0.085, 0.96),
            corner_radius=_scale_overlay_value(5, scale),
            border_color=(0.19, 0.19, 0.19, 1.0),
            border_width=1,
        )

    for index, row, row_y, current_height in positioned_rows:
        if row_y + current_height < content_bottom or row_y > content_top:
            continue
        if row["kind"] == "preview" and (
            row_y < content_bottom or row_y + current_height > content_top
        ):
            continue
        control_id = f"{row['kind']}:{index}:{row.get('section', '')}:{row.get('prop_name', '')}"
        hovered = control_id == hovered_id
        enabled = bool(row.get("enabled", True))
        indent = min(3, int(row.get("depth", 0))) * _scale_overlay_value(5, scale)
        row_x = x + padding + indent
        row_width = width - (padding * 2) - indent

        if row["kind"] == "section":
            fill = CONTROL_HOVER_COLOR if hovered else SECTION_COLOR
            border = ACCENT_BORDER if hovered else CONTROL_BORDER
            _draw_overlay_background(
                row_x,
                row_y,
                row_width,
                current_height,
                color=fill,
                corner_radius=_scale_overlay_value(5, scale),
                border_color=border,
                border_width=1,
            )
            collapsed = row["section"] in collapsed_sections
            _draw_text(
                ("▸ " if collapsed else "▾ ") + row["text"],
                row_x + _scale_overlay_value(9, scale),
                row_y + _scale_overlay_value(8, scale),
                _scale_overlay_value(11, scale),
                TEXT_COLOR,
                row_width - 16,
            )
            action = {"kind": "section", "section": row["section"]}
        elif row["kind"] == "label":
            _draw_text(
                row["text"],
                row_x + _scale_overlay_value(5, scale),
                row_y + _scale_overlay_value(8, scale),
                _scale_overlay_value(10, scale),
                MUTED_TEXT_COLOR if enabled else DISABLED_TEXT_COLOR,
                row_width - 10,
            )
            action = None
        elif row["kind"] == "preview":
            _draw_overlay_background(
                row_x,
                row_y,
                row_width,
                current_height,
                color=(0.075, 0.075, 0.075, 0.98),
                corner_radius=_scale_overlay_value(4, scale),
                border_color=CONTROL_BORDER,
                border_width=1,
            )
            preview_path = _resolve_preview_path(row)
            if preview_path:
                _draw_preview(
                    preview_path,
                    row_x,
                    row_y,
                    row_width,
                    current_height,
                    enabled,
                )
            action = None
        else:
            fill = CONTROL_HOVER_COLOR if hovered and enabled else CONTROL_COLOR
            border = ACCENT_BORDER if (hovered or row.get("depress")) and enabled else CONTROL_BORDER
            _draw_overlay_background(
                row_x,
                row_y,
                row_width,
                current_height,
                color=fill,
                corner_radius=_scale_overlay_value(4, scale),
                border_color=border,
                border_width=1,
            )
            text_color = TEXT_COLOR if enabled else DISABLED_TEXT_COLOR
            _draw_text(
                row["text"],
                row_x + _scale_overlay_value(9, scale),
                row_y + _scale_overlay_value(8, scale),
                _scale_overlay_value(10, scale),
                text_color,
                row_width * 0.58,
            )
            if row["kind"] == "property":
                value = property_display_value(row["data"], row["prop_name"])
                value_width = blf.dimensions(0, value)[0]
                _draw_text(
                    value,
                    row_x + row_width - value_width - _scale_overlay_value(9, scale),
                    row_y + _scale_overlay_value(8, scale),
                    _scale_overlay_value(10, scale),
                    text_color,
                    row_width * 0.38,
                )
                action = {
                    "kind": "property",
                    "target": register_target(targets, row["data"]),
                    "prop_name": row["prop_name"],
                }
            elif row["kind"] == "operator":
                action = {
                    "kind": "operator",
                    "operator": row["operator"],
                    "properties": row.get("properties", {}),
                }
            else:
                action = None

        if action is not None:
            hitboxes.append(
                {
                    "id": control_id,
                    "x": row_x,
                    "y": row_y,
                    "width": row_width,
                    "height": current_height,
                    "enabled": enabled,
                    "action": action,
                }
            )

    viewport_height = max(1, content_top - content_bottom)
    max_scroll = max(0, content_height - viewport_height)
    if max_scroll > 0:
        track_width = _scale_overlay_value(3, scale)
        track_x = x + width - track_width - _scale_overlay_value(3, scale)
        _draw_overlay_background(
            track_x,
            content_bottom,
            track_width,
            viewport_height,
            color=(0.10, 0.10, 0.10, 0.9),
            corner_radius=track_width,
        )
        thumb_height = max(
            _scale_overlay_value(28, scale),
            int(viewport_height * min(1.0, viewport_height / max(1, content_height))),
        )
        travel = max(0, viewport_height - thumb_height)
        ratio = min(1.0, max(0.0, float(scroll_offset) / max_scroll))
        thumb_y = content_top - thumb_height - int(travel * ratio)
        _draw_overlay_background(
            track_x,
            thumb_y,
            track_width,
            thumb_height,
            color=(0.42, 0.42, 0.42, 0.95),
            corner_radius=track_width,
        )
    return {
        "rect": rect,
        "hitboxes": hitboxes,
        "targets": targets,
        "max_scroll": max_scroll,
    }


def point_in_rect(mouse_x, mouse_y, rect):
    return (
        rect["x"] <= mouse_x <= rect["x"] + rect["width"]
        and rect["y"] <= mouse_y <= rect["y"] + rect["height"]
    )


def hitbox_at(hitboxes, mouse_x, mouse_y):
    for hitbox in reversed(hitboxes):
        if point_in_rect(mouse_x, mouse_y, hitbox):
            return hitbox
    return None
