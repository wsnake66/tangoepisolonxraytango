"""Casting batch quantities from cavity volume, separate from mold material."""
import math


def calculate_casting_material(volume_ml, mode="SINGLE", density=1.0,
                              part_a=1.0, part_b=1.0, powder_g=100.0,
                              water_ml=70.0, yield_ml=102.0):
    values = (volume_ml, density, part_a, part_b, powder_g, water_ml, yield_ml)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Casting recipe values must be finite")
    if mode not in {"SINGLE", "TWO_PART", "POWDER_WATER"}:
        raise ValueError("Unknown casting material type")
    if density <= 0 or part_a <= 0 or part_b <= 0 or powder_g <= 0 or yield_ml <= 0 or water_ml < 0:
        raise ValueError("Invalid casting recipe")
    volume = max(volume_ml, 0.0)
    if mode == "POWDER_WATER":
        return [("Powder", powder_g * volume / yield_ml, "mass"),
                ("Water", water_ml * volume / yield_ml, "volume")]
    weight = volume * density
    if mode == "TWO_PART":
        return [("Part A", weight * part_a / (part_a + part_b), "mass"),
                ("Part B", weight * part_b / (part_a + part_b), "mass")]
    return [("Material", weight, "mass")]


def scene_casting_material(scene):
    return calculate_casting_material(
        getattr(scene, "casting_volume_ml", 0.0),
        getattr(scene, "casting_material_mode", "SINGLE"),
        getattr(scene, "casting_material_density", 1.0),
        getattr(scene, "casting_material_part_a", 1.0),
        getattr(scene, "casting_material_part_b", 1.0),
        getattr(scene, "casting_material_powder_g", 100.0),
        getattr(scene, "casting_material_water_ml", 70.0),
        getattr(scene, "casting_material_yield_ml", 102.0),
    )


# Values are starting recipes for the named reference products, not universal
# ratios for every resin/wax. See docs/casting-material-presets.md.
CASTING_PRESETS = (
    ("CUSTOM_SINGLE", "Single component", "Custom density", "SINGLE", {}),
    ("CUSTOM_TWO_PART", "Part A + Part B", "Custom A:B ratio by weight", "TWO_PART", {}),
    ("CUSTOM_POWDER", "Powder + water", "Custom recipe and measured fresh yield", "POWDER_WATER", {}),
    ("WAX", "Wax (paraffin)", "Molten paraffin at 80°C: 0.7716 g/ml. Adjust for your wax and pouring temperature", "SINGLE", {"density": 0.7716}),
    ("EPOXY", "Epoxy resin", "EpoxAcast 690 reference: 100:30 by weight, 1.10 g/ml. Adjust to your product", "TWO_PART", {"density": 1.10, "part_a": 100.0, "part_b": 30.0}),
    ("URETHANE", "Polyurethane resin", "Smooth-Cast 300 reference: 100:90 by weight, 1.05 g/ml. Adjust to your product", "TWO_PART", {"density": 1.05, "part_a": 100.0, "part_b": 90.0}),
    ("PLASTER", "Plaster", "100 g plaster + 70 ml water makes approximately 102 ml, matching Slip Cast. Fresh yield remains editable", "POWDER_WATER", {"powder_g": 100.0, "water_ml": 70.0, "yield_ml": 102.0}),
    ("SILICONE", "Silicone rubber", "Dragon Skin 10 Medium reference: 1:1 by weight, 1.07 g/ml. Adjust to your product", "TWO_PART", {"density": 1.07, "part_a": 1.0, "part_b": 1.0}),
)


def get_casting_preset(scene):
    index = int(scene.get("casting_material_preset", -1))
    mode = getattr(scene, "casting_material_mode", "SINGLE")
    if 0 <= index < len(CASTING_PRESETS) and CASTING_PRESETS[index][3] == mode:
        return index
    return {"SINGLE": 0, "TWO_PART": 1, "POWDER_WATER": 2}.get(mode, 0)


def set_casting_preset(scene, index):
    preset = CASTING_PRESETS[index]
    # Ingredient callbacks must not apply the previous preset while switching.
    scene["casting_material_preset"] = -1
    scene.casting_material_mode = preset[3]
    for name, value in preset[4].items():
        setattr(scene, "casting_material_" + name, value)
    scene["casting_material_preset"] = index


def update_casting_plaster_yield(scene, context):
    if CASTING_PRESETS[get_casting_preset(scene)][0] == "PLASTER":
        scene.casting_material_yield_ml = max(
            0.001, scene.casting_material_water_ml + 0.32 * scene.casting_material_powder_g)


def register_properties(FloatProperty, EnumProperty):
    import bpy
    from .material_units import display_getter, display_setter
    from .i18n import casting_material_mode_items, casting_material_preset_items
    bpy.types.Scene.casting_material_mode = EnumProperty(
        name="Material Type", default=0, items=casting_material_mode_items)
    bpy.types.Scene.casting_material_preset = EnumProperty(
        name="Material", description="Editable starting recipe; use your material supplier's density and ratio",
        items=casting_material_preset_items,
        get=get_casting_preset, set=set_casting_preset)
    for name, label, default, minimum in (
        ("density", "Mixed Density", 1.0, 0.001),
        ("part_a", "Part A", 1.0, 0.001),
        ("part_b", "Part B", 1.0, 0.001),
        ("powder_g", "Powder", 100.0, 0.001),
        ("water_ml", "Water", 70.0, 0.0),
        ("yield_ml", "Makes", 102.0, 0.001),
    ):
        options = {}
        if name in {"water_ml", "powder_g"}:
            options["update"] = update_casting_plaster_yield
        if name in {"part_a", "part_b"}:
            options["description"] = "A:B mix ratio by weight, as specified by your material supplier"
        setattr(bpy.types.Scene, "casting_material_" + name,
                FloatProperty(name=label, default=default, min=minimum, **options))
    for name, kind, label in (
        ("silicone_density", "density", "Density"),
        ("plaster_mix_water_ml", "volume", "Water"),
        ("plaster_mix_plaster_g", "mass", "Plaster"),
        ("plaster_mix_volume_ml", "volume", "Makes"),
        ("casting_material_density", "density", "Density"),
        ("casting_material_powder_g", "mass", "Powder"),
        ("casting_material_water_ml", "volume", "Water"),
        ("casting_material_yield_ml", "volume", "Makes"),
    ):
        setattr(bpy.types.Scene, name + "_display", FloatProperty(
            name=label, min=0.0, precision=3,
            get=display_getter(name, kind), set=display_setter(name, kind)))
