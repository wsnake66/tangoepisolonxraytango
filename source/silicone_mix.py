"""Calculate single-component silicone or a manufacturer's Part A : Part B mix."""

import math


def calculate_silicone_mix(volume_ml, density=1.12, part_a=1.0, part_b=1.0):
    """Return grams of A and B. Ratios are by weight, never by volume."""
    volume_ml, density, part_a, part_b = map(float, (volume_ml, density, part_a, part_b))
    if not all(math.isfinite(value) for value in (volume_ml, density, part_a, part_b)):
        raise ValueError("Silicone volume, density and ratio must be finite")
    if part_a <= 0 or part_b <= 0:
        raise ValueError("Both silicone ratio parts must be greater than zero")
    weight = max(volume_ml, 0.0) * max(density, 0.0)
    fraction_a = part_a / (part_a + part_b)
    return weight * fraction_a, weight * (1.0 - fraction_a)


def scene_silicone_mix(scene, volume_ml=None):
    if getattr(scene, "silicone_mix_mode", "TWO_PART") == "SINGLE":
        a, b = calculate_silicone_mix(
            getattr(scene, "volume", 0.0) if volume_ml is None else volume_ml,
            getattr(scene, "silicone_density", 1.12),
        )
        return a + b, 0.0
    return calculate_silicone_mix(
        getattr(scene, "volume", 0.0) if volume_ml is None else volume_ml,
        getattr(scene, "silicone_density", 1.12),
        getattr(scene, "silicone_mix_part_a", 1.0),
        getattr(scene, "silicone_mix_part_b", 1.0),
    )


def silicone_mix_engraving(scene, volume_ml=None):
    from .material_units import current_units, format_amount
    part_a, part_b = scene_silicone_mix(scene, volume_ml)
    if getattr(scene, "silicone_mix_mode", "TWO_PART") == "SINGLE":
        return (format_amount(part_a, "mass") if current_units() == "US"
                else f"{part_a:.0f}g")
    if current_units() == "US":
        return f"A{format_amount(part_a, 'mass')} B{format_amount(part_b, 'mass')}"
    return f"A{part_a:.0f}g B{part_b:.0f}g"
