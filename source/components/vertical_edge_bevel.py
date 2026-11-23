import bmesh  # type: ignore

from ..bl_utils import BMeshObj
from ..object import Object


PRIMITIVE_CUBE_CORNER_RADIUS_MM = 2.0
PRIMITIVE_CUBE_CORNER_SEGMENTS = 6


def bevel_vertical_edges(
    obj: Object,
    *,
    radius: float = PRIMITIVE_CUBE_CORNER_RADIUS_MM,
    segments: int = PRIMITIVE_CUBE_CORNER_SEGMENTS,
) -> None:
    """Round upright corners without beveling the top or bottom perimeter."""
    safe_radius = min(
        max(float(radius), 0.0),
        max(min(float(obj.width), float(obj.depth)) * 0.25, 0.0),
    )
    if safe_radius <= 1e-6:
        return

    with BMeshObj(obj, repair_winding=True) as bm:
        vertical_edges = []
        for edge in bm.edges:
            direction = edge.verts[1].co - edge.verts[0].co
            if direction.length <= 1e-6:
                continue
            if abs(direction.normalized().z) > 0.999:
                vertical_edges.append(edge)
        if not vertical_edges:
            return
        bmesh.ops.bevel(
            bm,
            geom=vertical_edges,
            offset=safe_radius,
            segments=max(int(segments), 1),
            profile=0.5,
            affect="EDGES",
        )
