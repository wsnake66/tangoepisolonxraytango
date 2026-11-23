"""Compose catalog badges for UI previews without changing source artwork."""

from pathlib import Path

import bpy  # type: ignore


def load_catalog_preview_image(path):
    image = bpy.data.images.load(str(path), check_existing=True)
    if Path(path).name != "slip_cast_plaster.png":
        return image
    name = "_moldboxer_slip_cast_pro_preview"
    cached = bpy.data.images.get(name)
    if cached is not None:
        return cached

    # Reuse the existing picker badge at its original proportional position.
    reference_path = (
        Path(__file__).resolve().parents[1]
        / "assets/mold_types/picker/two_parts_v2_pro.png"
    )
    reference = bpy.data.images.load(str(reference_path), check_existing=True)
    width, height = image.size[:]
    ref_width, ref_height = reference.size[:]
    pixels = list(image.pixels[:])
    badge = reference.pixels[:]
    for y in range(int(height * 46 / 768), int(height * 170 / 768) + 1):
        for x in range(int(width * 46 / 768), int(width * 250 / 768) + 1):
            rx = (x + 0.5) * 768 / width
            ry = (y + 0.5) * 768 / height
            # Capsule mask excludes the blue mold behind the reference pill.
            cx = min(188.0, max(108.0, rx))
            distance = ((rx - cx) ** 2 + (ry - 108) ** 2) ** 0.5
            coverage = min(1.0, max(0.0, 62.0 - distance))
            if not coverage:
                continue
            ref_x = int(rx * ref_width / 768)
            ref_y = ref_height - 1 - int(ry * ref_height / 768)
            source = 4 * (ref_y * ref_width + ref_x)
            target = 4 * ((height - 1 - y) * width + x)
            alpha = coverage * badge[source + 3]
            if not alpha:
                continue
            old_alpha = pixels[target + 3]
            out_alpha = alpha + old_alpha * (1 - alpha)
            for channel in range(3):
                pixels[target + channel] = (
                    badge[source + channel] * alpha
                    + pixels[target + channel] * old_alpha * (1 - alpha)
                ) / out_alpha
            pixels[target + 3] = out_alpha

    preview = bpy.data.images.new(name, width=width, height=height, alpha=True)
    preview.colorspace_settings.name = image.colorspace_settings.name
    preview.pixels.foreach_set(pixels)
    preview.update()
    return preview
