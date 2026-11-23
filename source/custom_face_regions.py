"""Shared local-space head/neck boundary for coloring and clearance."""

HEAD_BOTTOM_KEY = "moldboxer_custom_face_head_bottom"
HEAD_NECK_FRONT_KEY = "moldboxer_custom_face_neck_front"
HEAD_NECK_SLOPE_KEY = "moldboxer_custom_face_neck_slope"


def head_region_distance(obj, point):
    """Positive above the chin-to-nape plane; old cores retain a flat cutoff."""
    bottom = float(obj.get(HEAD_BOTTOM_KEY, -1e30))
    front = float(obj.get(HEAD_NECK_FRONT_KEY, 0.0))
    slope = float(obj.get(HEAD_NECK_SLOPE_KEY, 0.0))
    return point.z - bottom - slope * (point.y - front)
