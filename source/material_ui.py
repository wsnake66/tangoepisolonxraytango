"""Compact editable material controls; quantities belong in the viewport."""
from .material_units import unit_label
from .i18n import t


def draw_material_field(layout, scene, name, label, kind):
    layout.prop(scene, name + "_display", text=f"{t(label)} ({unit_label(kind)})")


def draw_powder_recipe(layout, scene, water, powder, yield_volume, *, powder_label="Plaster"):
    ingredients = layout.row(align=True)
    draw_material_field(ingredients, scene, water, "Water", "volume")
    draw_material_field(ingredients, scene, powder, powder_label, "mass")
    volume = layout.row(align=True)
    draw_material_field(volume, scene, yield_volume, "Makes", "volume")


def draw_casting_material_settings(layout, context):
    scene = context.scene
    box = layout.box()
    box.label(text=t("Casting Material"), icon="EXPERIMENTAL")
    box.prop(scene, "casting_material_preset", text=t("Material"))
    mode = scene.casting_material_mode
    if mode == "POWDER_WATER":
        draw_powder_recipe(box, scene, "casting_material_water_ml",
                           "casting_material_powder_g", "casting_material_yield_ml",
                           powder_label="Plaster" if scene.casting_material_preset == "PLASTER" else "Powder")
    else:
        row = box.row(align=True)
        draw_material_field(row, scene, "casting_material_density", "Density", "density")
        if mode == "TWO_PART":
            row = box.row(align=True)
            row.prop(scene, "casting_material_part_a", text=t("Part A"))
            row.prop(scene, "casting_material_part_b", text=t("Part B"))
