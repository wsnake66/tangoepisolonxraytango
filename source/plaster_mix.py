"""Scale a reference plaster recipe by its fresh, pourable mix volume.

Default reference: 100 g plaster + 70 ml water yields approximately 102 ml.
USG IG503 gives theoretical fresh slurry weight of 1674 g/l at 70/100:
170 / 1.674 = 101.55 ml, rounded to 102 ml. This is an estimate; measured
fresh batch yield at the chosen recipe overrides it. No excess is added.
https://www.usg.com/content/dam/USG/pdpmovedocuments/plaster-mixing-procedures-application-en-IG503.pdf
"""


def update_plaster_mix_volume(scene, context):
    """Estimate fresh yield after an ingredient edit; measured yield stays editable.

    Preserve the existing 70 ml + 100 g -> 102 ml reference by estimating
    plaster's volume contribution as 0.32 ml/g, independently of the water.
    """
    scene.plaster_mix_volume_ml = max(
        0.1,
        scene.plaster_mix_water_ml + 0.32 * scene.plaster_mix_plaster_g,
    )


def calculate_plaster_mix(volume_ml, mix_volume_ml=102.0, water_ml=70.0, plaster_g=100.0):
    """Return (water ml, dry plaster g) using a reference recipe's yield."""
    volume_ml = max(float(volume_ml), 0.0)
    mix_volume_ml = float(mix_volume_ml)
    water_ml = max(float(water_ml), 0.0)
    plaster_g = float(plaster_g)
    if mix_volume_ml <= 0 or plaster_g <= 0:
        raise ValueError("Mix volume and plaster amount must be greater than zero")
    scale = volume_ml / mix_volume_ml
    return water_ml * scale, plaster_g * scale


def scene_plaster_mix(scene):
    return calculate_plaster_mix(
        getattr(scene, "volume", 0.0),
        getattr(scene, "plaster_mix_volume_ml", 102.0),
        getattr(scene, "plaster_mix_water_ml", 70.0),
        getattr(scene, "plaster_mix_plaster_g", 100.0),
    )


def plaster_mix_engraving(scene):
    from .material_units import current_units, format_amount
    water_ml, plaster_g = scene_plaster_mix(scene)
    if current_units() == "US":
        return f"W{format_amount(water_ml, 'volume')} P{format_amount(plaster_g, 'mass')}"
    return f"W{water_ml:.0f}ml P{plaster_g:.0f}g"
