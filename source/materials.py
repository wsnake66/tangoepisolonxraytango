from array import array

import bpy  # type: ignore
from .custom_face_regions import head_region_distance

from .bl_utils import (
    ensure_moldboxer_background,
    ensure_solid_viewport_material_shading,
)

use_colored_materials = True

MASTER_MATERIAL_KEY = "master"
SHADOW_READABLE_MATERIAL_KEYS = {MASTER_MATERIAL_KEY}
SHADOW_READABLE_AO_DISTANCE = 12.0
SHADOW_READABLE_AO_FACTOR = 0.35

MATERIAL_SPECS = {
    "moldbox": ("MB_MoldBox", "#EFCA5BFF", 0.8, 0.95),
    "fixture": ("MB_Fixture", "#EFCA5BFF", 0.9, 0.7),
    "protective_shell": ("MB_ProtectiveShell", "#3F6680FF", 0.0, 0.65),
    MASTER_MATERIAL_KEY: ("MB_Master", "#EBF0AEFF", 1.0, 1.0),
    "channels": ("MB_Channels", "#21F9FFFF", 0.9, 1.0),
    "support_pilars": ("MB_Channels", "#21F9FFFF", 0.9, 1.0),
    "funnels": ("MB_Funnels", "#49FF83FF", 0.93, 1.0),
    "slip_casting_funnel_span": (
        "MB_SlipCastingFunnelSpan",
        "#49FF83FF",
        0.6,
        0.32,
    ),
    "pin_keys": ("MB_PinKeys", "#49FF83FF", 0.93, 1.0),
    "split_base_keys": ("MB_SplitBaseKeys", "#C3C0B8FF", 0.45, 0.65),
    "clear_extraction": ("MB_ClearExtraction", "#49FF83FF", 0.0, 0.5),
    "male_barriers": ("MB_MaleBarriers", "#21F9FFFF", 0.9, 1.0),
    "silicone_mold": ("MB_SiliconeMold", "#61FEFFFF", 1.0, 0.65),
    "plaster_mold": ("MB_PlasterMold", "#E8D5AEFF", 0.0, 0.92),
    "inner_core": ("MB_InnerCore", "#FF3845FF", 0.8, 0.8),
    "custom_face_neck": ("MB_CustomFaceNeck", "#459CCFFF", 0.15, 0.65),
    "skin_core_base": ("MB_SkinCoreBase", "#FF861AFF", 0.15, 0.4),
    "foundation": ("MB_Foundation", "#3F8CFFFF", 0.15, 0.4),
    "fixture_base": ("MB_FixtureBaseAluminium", "#F2F4F7FF", 0.65, 0.4),
    "clamps": ("MB_Clamps", "#49FF83FF", 0.0, 0.8),
    "wing": ("MB_Wing", "#49FF83FF", 0.93, 1.0),
    "helper": ("MB_Helper", "#A3A3A3", 0.0, 0.5),
    "guides": ("MB_Guides", "#A187C7", 0.0, 0.5),
}

GENERATED_MATERIAL_NAMES = {spec[0] for spec in MATERIAL_SPECS.values()}
MOLDBOX_OBJECT_NAMES = {"box", "box_l", "box_r"}
SILICONE_MOLD_OBJECT_NAMES = {"silicone_mold"}
MASTER_OBJECT_NAMES = {"patron", "master", "base", "master_base"}
HELPER_OBJECT_NAMES = {"inner_cavity", "text1"}


def _hex_to_rgba(hex_color: str) -> tuple[float, float, float, float]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) not in {6, 8}:
        raise ValueError(f"Expected a 6-digit or 8-digit hex color, got '{hex_color}'")

    def _srgb_channel_to_linear(channel_hex: str) -> float:
        srgb = int(channel_hex, 16) / 255.0
        if srgb <= 0.04045:
            return srgb / 12.92
        return ((srgb + 0.055) / 1.055) ** 2.4

    red = _srgb_channel_to_linear(hex_color[0:2])
    green = _srgb_channel_to_linear(hex_color[2:4])
    blue = _srgb_channel_to_linear(hex_color[4:6])
    alpha = 1.0
    if len(hex_color) == 8:
        alpha = int(hex_color[6:8], 16) / 255.0
    return (red, green, blue, alpha)


def get_or_create_simple_material(
    name: str,
    hex_color: str,
    metallic: float = 0.0,
    roughness: float = 0.5,
    shadow_readable: bool = False,
):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name=name)

    material.use_nodes = True
    node_tree = material.node_tree
    if node_tree is None:
        return material

    nodes = node_tree.nodes
    links = node_tree.links

    principled = None
    material_output = None
    for node in list(nodes):
        if node.type == "BSDF_PRINCIPLED" and principled is None:
            principled = node
            continue
        if node.type == "OUTPUT_MATERIAL" and material_output is None:
            material_output = node
            continue
        nodes.remove(node)

    if principled is None:
        principled = nodes.new(type="ShaderNodeBsdfPrincipled")
    if material_output is None:
        material_output = nodes.new(type="ShaderNodeOutputMaterial")

    for link in list(links):
        links.remove(link)
    links.new(principled.outputs["BSDF"], material_output.inputs["Surface"])
    rgba = _hex_to_rgba(hex_color)
    base_color_input = principled.inputs["Base Color"]
    base_color_input.default_value = rgba
    if shadow_readable:
        ambient_occlusion = nodes.new(type="ShaderNodeAmbientOcclusion")
        color_input = ambient_occlusion.inputs.get("Color")
        distance_input = ambient_occlusion.inputs.get("Distance")
        factor_input = ambient_occlusion.inputs.get("Factor")
        color_output = ambient_occlusion.outputs.get("Color")
        if color_input is not None:
            color_input.default_value = rgba
        if distance_input is not None:
            distance_input.default_value = SHADOW_READABLE_AO_DISTANCE
        if factor_input is not None:
            factor_input.default_value = SHADOW_READABLE_AO_FACTOR
        if color_output is not None:
            links.new(color_output, base_color_input)
    principled.inputs["Metallic"].default_value = metallic
    principled.inputs["Roughness"].default_value = roughness
    material.diffuse_color = rgba
    if hasattr(material, "metallic"):
        material.metallic = metallic
    if hasattr(material, "roughness"):
        material.roughness = roughness
    return material


def assign_material(obj, mat) -> None:
    if obj is None or mat is None:
        return

    object_data = getattr(obj, "data", None)
    if object_data is None or getattr(obj, "type", None) != "MESH":
        return

    object_data.materials.clear()
    object_data.materials.append(mat)
    polygon_count = len(object_data.polygons)
    if polygon_count:
        object_data.polygons.foreach_set(
            "material_index",
            array("i", [0]) * polygon_count,
        )
    ensure_solid_viewport_material_shading(bpy.context)


def assign_moldbox_material(obj) -> None:
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["moldbox"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_plaster_mold_material(obj) -> None:
    """Assign the warm-white, matte material used by Slip Casting plaster."""
    if not use_colored_materials:
        return

    material_name, hex_color, metallic, roughness = MATERIAL_SPECS[
        "plaster_mold"
    ]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_fixture_material(obj) -> None:
    """Assign the box-yellow material with a stronger Fixture-only finish."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["fixture"]
    if _has_single_expected_material(obj, material_name):
        return
    if _has_transferred_generated_material_mix(obj, material_name):
        return
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_protective_shell_material(obj) -> None:
    """Assign the matte protective-blue shell material."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS[
        "protective_shell"
    ]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_funnels_material(obj) -> None:
    """Assign the green casting-funnel/deposit material explicitly."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["funnels"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_slip_casting_funnel_span_material(obj) -> None:
    """Assign the dedicated green metallic Slip Casting funnel-span finish."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS[
        "slip_casting_funnel_span"
    ]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_inner_core_material(obj) -> None:
    """Assign the red inner-core material explicitly."""
    if not use_colored_materials:
        return

    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["inner_core"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_skin_core_base_material(obj) -> None:
    """Assign the lightly metallic orange material for removable Skin bases."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["skin_core_base"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_foundation_material(obj) -> None:
    """Assign the blue material used by Foundation geometry."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["foundation"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_fixture_base_material(obj) -> None:
    """Assign a metallic aluminium material to Fixture base geometry."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["fixture_base"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def assign_split_base_keys_material(obj) -> None:
    """Warm silver satin registration features, distinct from the red split base."""
    assign_material(obj, get_or_create_simple_material(*MATERIAL_SPECS["split_base_keys"]))


def assign_pin_keys_material(obj) -> None:
    """Assign the green master-base pin-key material explicitly."""
    material_name, hex_color, metallic, roughness = MATERIAL_SPECS["pin_keys"]
    assign_material(
        obj,
        get_or_create_simple_material(
            material_name,
            hex_color,
            metallic,
            roughness,
        ),
    )


def _has_transferred_generated_material_mix(obj, expected_material_name: str) -> bool:
    object_data = getattr(obj, "data", None)
    if object_data is None or getattr(obj, "type", None) != "MESH":
        return False

    generated_materials_by_index = {}
    for material_index, material in enumerate(object_data.materials):
        if material is None:
            continue
        if material.name in GENERATED_MATERIAL_NAMES:
            generated_materials_by_index[material_index] = material.name

    if len(generated_materials_by_index) <= 1:
        return False

    used_generated_material_names = {
        generated_materials_by_index[polygon.material_index]
        for polygon in object_data.polygons
        if polygon.material_index in generated_materials_by_index
    }
    return (
        expected_material_name in used_generated_material_names
        and len(used_generated_material_names) > 1
    )


def _has_single_expected_material(obj, expected_material_name: str) -> bool:
    object_data = getattr(obj, "data", None)
    if object_data is None or getattr(obj, "type", None) != "MESH":
        return False

    materials = object_data.materials
    return (
        len(materials) == 1
        and materials[0] is not None
        and materials[0].name == expected_material_name
    )


def prepare_material_transfer(destination_obj, source_obj) -> None:
    if destination_obj is None or source_obj is None:
        return
    if getattr(destination_obj, "type", None) != "MESH":
        return
    if getattr(source_obj, "type", None) != "MESH":
        return

    destination_data = getattr(destination_obj, "data", None)
    source_data = getattr(source_obj, "data", None)
    if destination_data is None or source_data is None:
        return

    destination_materials = destination_data.materials
    source_materials_by_index = list(source_data.materials)
    material_index_map = {}

    for source_index, material in enumerate(source_materials_by_index):
        if material is None:
            continue
        destination_index = destination_materials.find(material.name)
        if destination_index < 0:
            destination_materials.append(material)
            destination_index = len(destination_materials) - 1
        material_index_map[source_index] = destination_index

    if not material_index_map:
        return

    polygon_count = len(source_data.polygons)
    single_source_material = (
        len(source_materials_by_index) == 1 and 0 in material_index_map
    )
    source_polygon_material_indices = None
    if not single_source_material:
        source_polygon_material_indices = [
            polygon.material_index for polygon in source_data.polygons
        ]

    source_data.materials.clear()
    for material in destination_materials:
        source_data.materials.append(material)

    if single_source_material:
        if polygon_count:
            source_data.polygons.foreach_set(
                "material_index",
                array("i", [material_index_map[0]]) * polygon_count,
            )
        return

    for polygon, source_index in zip(
        source_data.polygons,
        source_polygon_material_indices,
    ):
        polygon.material_index = material_index_map.get(
            source_index,
            source_index,
        )


def _is_moldbox_object_name(normalized_name: str) -> bool:
    return (
        normalized_name in MOLDBOX_OBJECT_NAMES
        or normalized_name.startswith("box_l_")
        or normalized_name.startswith("box_r_")
    )


def _name_tokens(normalized_name: str) -> set[str]:
    normalized_name = normalized_name.replace(".", "_").replace("-", "_")
    return {token for token in normalized_name.split("_") if token}


def _material_key_for_object_name(obj_name: str) -> str | None:
    normalized_name = obj_name.lower()
    name_tokens = _name_tokens(normalized_name)

    base_name = normalized_name.split(".", 1)[0]
    if any(base_name == prefix or (base_name.startswith(prefix + "_")
           and base_name[len(prefix) + 1:].isdigit()) for prefix in ("foot", "vase_base")):
        return "moldbox"
    if normalized_name.startswith("rounded_funnel_plaster_preview_"):
        return "plaster_mold"
    if normalized_name.startswith("rounded_funnel_mold_"):
        return "moldbox"
    if normalized_name.startswith("rounded_funnel_"):
        return "funnels"
    if normalized_name in MASTER_OBJECT_NAMES:
        return "master"
    if "barrier" in name_tokens:
        if "female" in name_tokens:
            return "moldbox"
        if "male" in name_tokens:
            return "male_barriers"
        return "male_barriers"
    if normalized_name.startswith("clamp_pin_"):
        if "female" in name_tokens:
            return "moldbox"
        if "male" in name_tokens:
            return "male_barriers"
        return "male_barriers"
    if normalized_name.startswith("base_pin"):
        return "male_barriers"
    if normalized_name.startswith(("split_base", "split_wall")):
        return "inner_core"
    if normalized_name.startswith("cast_part_") and "final" in name_tokens:
        return "funnels"
    if (
        normalized_name.startswith("slip_casting_funnel_span_core")
        and "wrapper" in name_tokens
    ):
        return "funnels"
    if "core" in normalized_name or "casting_feet" in normalized_name:
        return "inner_core"
    if normalized_name in SILICONE_MOLD_OBJECT_NAMES or normalized_name.startswith("silicone_mold_part_"):
        return "silicone_mold"
    if normalized_name == "plaster_mold" or normalized_name.startswith(
        "plaster_mold_part_"
    ):
        return "plaster_mold"
    if normalized_name == "wing":
        return "wing"
    if _is_moldbox_object_name(normalized_name):
        return "moldbox"
    if normalized_name.startswith("support_pilar"):
        return "support_pilars"
    if normalized_name.startswith("channel"):
        return "channels"
    if normalized_name.startswith("master_air_trap_pilar"):
        return "funnels"
    if (
        normalized_name.startswith("deposit")
        or normalized_name.startswith("funnel")
        or normalized_name == "grip"
        or "casting_box" in normalized_name
        or "clip" in normalized_name
        or "locker" in normalized_name
    ):
        return "funnels"
    if normalized_name.startswith("clamp"):
        return "clamps"
    if normalized_name.startswith("debug_organic_cut_loop"):
        return "guides"
    if normalized_name.startswith("guide"):
        return "guides"
    if (
        normalized_name in HELPER_OBJECT_NAMES
        or "helper" in normalized_name
    ):
        return "helper"
    return None


def assign_custom_face_section_materials(obj) -> None:
    """Show the clearance-tested head in red and the exempt neck in blue."""
    mesh = obj.data
    materials = [
        get_or_create_simple_material(*MATERIAL_SPECS[key])
        for key in ("inner_core", "custom_face_neck")
    ]
    # Reuse slots so repeated viewport refreshes do not accumulate materials.
    slots = []
    for material in materials:
        index = mesh.materials.find(material.name)
        if index < 0:
            index = len(mesh.materials)
            mesh.materials.append(material)
        slots.append(index)
    for polygon in mesh.polygons:
        # Crossing faces belong to the checked head region as well.
        is_head = any(
            head_region_distance(obj, mesh.vertices[index].co) >= 0
            for index in polygon.vertices
        )
        polygon.material_index = slots[0 if is_head else 1]
    ensure_solid_viewport_material_shading(bpy.context)


def finalize_slip_casting_foot_materials(scene) -> None:
    """Switch feet to plaster only after the complete slip-cast mold succeeds."""
    for obj in scene.objects:
        if (obj.type == "MESH" and obj.get("moldboxer_slip_casting_vase_base", False)
                and obj.get("moldboxer_slip_casting_vase_base_role") == "MALE"):
            obj["moldboxer_slip_casting_foot_finished"] = True
            assign_plaster_mold_material(obj)


def assign_generated_material(obj) -> None:
    if not use_colored_materials or obj is None:
        return

    object_get = getattr(obj, "get", None)
    if callable(object_get) and object_get("moldboxer_slip_casting_foot_finished", False):
        assign_plaster_mold_material(obj)
        return
    if (
        callable(object_get)
        and getattr(obj, "type", None) == "MESH"
        and object_get("moldboxer_custom_face_core", False)
        and not object_get("moldboxer_skin_core_confirmed", False)
        and object_get("moldboxer_custom_face_head_bottom") is not None
    ):
        assign_custom_face_section_materials(obj)
        return
    is_fixture = callable(object_get) and bool(
        object_get("moldboxer_fixture", False)
    )
    is_protective_shell = callable(object_get) and bool(
        object_get("moldboxer_protective_shell", False)
    )
    material_key = (
        "fixture"
        if is_fixture
        else (
            "protective_shell"
            if is_protective_shell
            else _material_key_for_object_name(obj.name)
        )
    )
    if material_key is None:
        return

    material_name, hex_color, metallic, roughness = MATERIAL_SPECS[material_key]
    if _has_single_expected_material(obj, material_name):
        return

    if _has_transferred_generated_material_mix(obj, material_name):
        return

    material = get_or_create_simple_material(
        material_name,
        hex_color,
        metallic,
        roughness,
        shadow_readable=material_key in SHADOW_READABLE_MATERIAL_KEYS,
    )
    assign_material(obj, material)


def refresh_generated_object_materials() -> None:
    if not use_colored_materials:
        return

    for obj in bpy.data.objects:
        assign_generated_material(obj)


def refresh_viewport_material_display(context) -> None:
    if not use_colored_materials or context is None:
        return

    ensure_moldboxer_background(context)
    ensure_solid_viewport_material_shading(context)
