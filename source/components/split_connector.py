import mathutils  # type: ignore

from ..constants import (
    SPLIT_CONNECTOR_LENGTH,
    SPLIT_CONNECTOR_WIDTH,
)
from ..object import Object
from ..primitives import create_cylinder_primitive


def _build_cylindrical_connector(
    name: str,
    center: mathutils.Vector,
    diameter: float,
    height: float,
) -> Object:
    connector = Object(create_cylinder_primitive(diameter / 2, height), name)
    connector.translate_whole(center - connector.center_coords)
    return connector


def split_with_connector(target: Object, tolerance: float = 0.2) -> tuple[Object, Object]:
    if tolerance < 0:
        raise ValueError("Connector tolerance must be non-negative")

    split_point = target.center_coords.copy()
    split_normal = mathutils.Vector((0, 0, 1))
    split_a, split_b = target.split_optimized(split_normal, split_point)
    bottom_half, top_half = sorted(
        (split_a, split_b), key=lambda obj: obj.center_coords.z
    )

    positive_diameter = SPLIT_CONNECTOR_WIDTH
    positive_height = SPLIT_CONNECTOR_LENGTH
    negative_diameter = positive_diameter + tolerance * 2
    negative_height = positive_height + tolerance * 2

    positive_connector = _build_cylindrical_connector(
        "split_connector_positive",
        split_point,
        positive_diameter,
        positive_height,
    )
    negative_connector = _build_cylindrical_connector(
        "split_connector_negative",
        split_point,
        negative_diameter,
        negative_height,
    )

    try:
        bottom_half.join(positive_connector)
        positive_connector = None
        top_half -= negative_connector
    finally:
        if positive_connector is not None:
            positive_connector.remove()
        negative_connector.remove()

    return bottom_half, top_half
