import copy
from pathlib import Path

from ..environment import get_server_base_url
from ..modifiers import build_sharp_modifier
from ..object import Object
from .server import (
    import_server_response,
    request_server_payload,
    request_server_payload_async,
)


WATERMARK_MESH_PATH = "/watermark-mesh/"
_FONT_PATHS = {
    "INTER": "assets/fonts/inter/Inter-Variable.ttf",
    "MONTSERRAT": "assets/fonts/montserrat/Montserrat-Variable.ttf",
    "ROBOTO_SLAB": "assets/fonts/roboto_slab/RobotoSlab-Variable.ttf",
    "BEBAS_NEUE": "assets/fonts/bebas_neue/BebasNeue-Regular.ttf",
    "NOTO_SANS_ARABIC": (
        "assets/fonts/noto_sans_arabic/NotoSansArabic-Variable.ttf"
    ),
}
_ARABIC_UNICODE_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x0870, 0x089F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
    (0x10E60, 0x10E7F),
    (0x1EE00, 0x1EEFF),
)


def _contains_arabic_script(text: str) -> bool:
    return any(
        start <= ord(character) <= end
        for character in str(text)
        for start, end in _ARABIC_UNICODE_RANGES
    )


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _prepare_items(items: list[dict]) -> tuple[dict, dict[str, bytes]]:
    if not items or len(items) > 8:
        raise ValueError("Expected between 1 and 8 watermark mesh items")
    prepared_items = copy.deepcopy(items)
    attachments: dict[str, bytes] = {}
    for index, item in enumerate(prepared_items):
        kind = str(item.get("kind", "")).casefold()
        if kind == "text":
            # Remeshing depends on the user's Blender version/settings and must
            # stay client-side.  The server receives only mesh-construction data.
            item.pop("sharp_remesh_level", None)
            font_identifier = str(item.get("font_identifier", "BFONT")).upper()
            if _contains_arabic_script(item.get("text", "")):
                # The Latin watermark choices have no Arabic glyph coverage.
                # Always send the Arabic-capable font for Arabic-script text.
                font_identifier = "NOTO_SANS_ARABIC"
                item["font_identifier"] = font_identifier
                item.pop("font_path", None)
            relative_font_path = _FONT_PATHS.get(font_identifier)
            if relative_font_path is not None:
                explicit_font_path = item.pop("font_path", None)
                font_path = (
                    Path(str(explicit_font_path)).expanduser()
                    if explicit_font_path
                    else _package_root() / relative_font_path
                )
                if not font_path.is_file():
                    raise FileNotFoundError(f"Bundled watermark font is missing: {font_path}")
                filename = f"font_{index}{font_path.suffix.casefold()}"
                attachments[filename] = font_path.read_bytes()
                item["font_filename"] = filename
        elif kind == "svg":
            source_path = Path(str(item.pop("svg_path", ""))).expanduser()
            if not source_path.is_file() or source_path.suffix.casefold() != ".svg":
                raise ValueError("Choose a valid SVG file")
            filename = f"watermark_{index}.svg"
            attachments[filename] = source_path.read_bytes()
            item["svg_filename"] = filename
    return {"items": prepared_items}, attachments


def _import_watermark_response(response, items: list[dict]) -> list[Object]:
    imported = import_server_response(
        response,
        remesh_imported_objects=False,
    )
    results = []
    for item in items:
        expected_name = str(item["name"])
        obj = next(
            (
                candidate
                for candidate in imported
                if candidate.name == expected_name
                or candidate.name.startswith(f"{expected_name}.")
            ),
            None,
        )
        if obj is None:
            raise RuntimeError(
                f"Server did not return watermark mesh {expected_name!r}"
            )
        result = Object(obj)
        if str(item.get("kind", "")).casefold() == "text":
            sharp_level = item.get("sharp_remesh_level")
            if sharp_level is not None:
                result.apply_modifier(build_sharp_modifier(int(sharp_level)))
        results.append(result)
    return results


def request_watermark_meshes(items: list[dict]) -> list[Object]:
    payload, attachments = _prepare_items(items)
    response = request_server_payload(
        f"{get_server_base_url()}{WATERMARK_MESH_PATH}",
        payload,
        attachments=attachments,
    )
    return _import_watermark_response(response, items)


def request_watermark_mesh(item: dict) -> Object:
    return request_watermark_meshes([item])[0]


def request_watermark_meshes_async(items: list[dict]):
    payload, attachments = _prepare_items(items)
    import_items = copy.deepcopy(items)
    return request_server_payload_async(
        f"{get_server_base_url()}{WATERMARK_MESH_PATH}",
        payload,
        attachments=attachments,
        on_complete=lambda response: _import_watermark_response(
            response,
            import_items,
        ),
    )


def request_watermark_mesh_async(item: dict):
    payload, attachments = _prepare_items([item])
    import_item = copy.deepcopy(item)
    return request_server_payload_async(
        f"{get_server_base_url()}{WATERMARK_MESH_PATH}",
        payload,
        attachments=attachments,
        on_complete=lambda response: _import_watermark_response(
            response,
            [import_item],
        )[0],
    )


def request_weight_text_mesh(text: str, *, name: str = "Text1") -> Object:
    return request_watermark_mesh(_weight_text_item(text, name=name))


def request_weight_text_mesh_async(text: str, *, name: str = "Text1"):
    return request_watermark_mesh_async(_weight_text_item(text, name=name))


def _weight_text_item(text: str, *, name: str) -> dict:
    return {
        "kind": "text",
        "name": name,
        "text": text,
        "size": 8.0,
        "depth": 2.0,
        "font_identifier": "BFONT",
        "sharp_remesh_level": 8,
    }
