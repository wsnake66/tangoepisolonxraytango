"""Smooth, independently measured neck extension for mask cores."""

import math

from .custom_face_regions import HEAD_BOTTOM_KEY, HEAD_NECK_FRONT_KEY, HEAD_NECK_SLOPE_KEY


DEFAULT_NECK_SETTINGS = {
    "custom_face_neck_width": 100.0,
    "custom_face_neck_length": 50.0,
    "custom_face_neck_offset": 0.0,
    "custom_face_neck_flare": 5.0,
}


def neck_settings(scene, dimensions):
    values = {name: float(getattr(scene, name, default))
              for name, default in DEFAULT_NECK_SETTINGS.items()}
    if dimensions["custom_face_neck_circumference"] <= 2 * values["custom_face_neck_width"]:
        raise ValueError("Neck circumference must be greater than twice the neck width")
    return values


def _ellipse_perimeter(a, b):
    h = ((a - b) / (a + b)) ** 2
    return math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def _blend(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def _neck_profile(t, rear, a, b):
    """Soft mask-core contour, without muscle detail or deep undercuts.

    Use a long jaw-to-throat transition instead of an abrupt under-chin
    notch. Bring the middle section forward to fill the throat notch and
    recess the nape, returning to the measured opening at the base.
    """
    transition = 0.85 + 0.05 * rear
    blend = _blend(t / transition)
    waist = math.sin(math.pi * t) ** 2 if 0.0 < t < 1.0 else 0.0
    return blend, a * (1.0 - 0.045 * waist), b * (1.0 - 0.035 * waist), -b * 0.22 * waist


def shape_neck(core, dimensions, settings):
    """Only deform the blue region; preserve the red head and the flat base."""
    mesh = core.data
    bottom = min(vertex.co.z for vertex in mesh.vertices)
    ring = [vertex.co for vertex in mesh.vertices if abs(vertex.co.z - bottom) < 0.001]
    if not ring:
        return
    center_x = (min(p.x for p in ring) + max(p.x for p in ring)) / 2
    center_y = (min(p.y for p in ring) + max(p.y for p in ring)) / 2
    old_a = max((max(p.x for p in ring) - min(p.x for p in ring)) / 2, 0.001)
    old_b = max((max(p.y for p in ring) - min(p.y for p in ring)) / 2, 0.001)
    a = settings["custom_face_neck_width"] / 2
    circumference = dimensions["custom_face_neck_circumference"]
    if circumference <= 4 * a:
        raise ValueError("Neck circumference must be greater than twice the neck width")
    lower, upper = 0.001, circumference / 2
    for _ in range(48):
        middle = (lower + upper) / 2
        if _ellipse_perimeter(a, middle) < circumference:
            lower = middle
        else:
            upper = middle
    comfort = dimensions["custom_face_comfort_clearance"]
    a, b = a + comfort, (lower + upper) / 2 + comfort
    front = float(core[HEAD_NECK_FRONT_KEY])
    slope = float(core[HEAD_NECK_SLOPE_KEY])
    chin_z = float(core[HEAD_BOTTOM_KEY])
    final_bottom = chin_z - settings["custom_face_neck_length"]
    for vertex in mesh.vertices:
        point = vertex.co
        boundary = chin_z + slope * (point.y - front)
        if point.z >= boundary:
            continue
        t = min(1.0, max(0.0, (boundary - point.z) / max(boundary - bottom, 0.001)))
        flare = settings["custom_face_neck_flare"] * _blend((t - 0.72) / 0.28)
        angle = math.atan2((point.y - center_y) / old_b, (point.x - center_x) / old_a)
        rear = (math.sin(angle) + 1.0) / 2.0
        blend, section_a, section_b, profile_shift = _neck_profile(t, rear, a, b)
        target_x = center_x + (section_a + flare) * math.cos(angle)
        target_y = (center_y - settings["custom_face_neck_offset"]
                    + (section_b + flare) * math.sin(angle))
        point.x += (target_x - point.x) * blend
        point.y += (target_y - point.y) * blend + profile_shift
        point.z += (final_bottom - bottom) * _blend(t)
    mesh.update()
