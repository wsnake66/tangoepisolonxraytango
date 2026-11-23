# SPDX-License-Identifier: GPL-3.0-or-later
"""Client glue and closed meshes for rounded casting funnels."""
import math


def base_on_top(funnel_type, generate_foot):
    return bool(generate_foot) != (funnel_type == 'ROUNDED')


def _top_triangles(spec, height=1.0):
    """Clip once in Z, then use the projected union for cheap contact checks."""
    vertices = spec['vertices']
    if not vertices or not math.isfinite(height) or height <= 0:
        raise ValueError('A nonempty surface and positive top-band height are required')
    cutoff = max(p[2] for p in vertices) - height
    triangles = []
    for face in spec['faces']:
        polygon = []
        for a, b in zip(face, face[1:]+face[:1]):
            start, end = vertices[a], vertices[b]
            if start[2] >= cutoff:
                polygon.append(start)
            if (start[2] < cutoff) != (end[2] < cutoff):
                fraction = (cutoff-start[2]) / (end[2]-start[2])
                polygon.append(tuple(start[axis]+fraction*(end[axis]-start[axis]) for axis in range(3)))
        for i in range(1, len(polygon)-1):
            t = [polygon[0], polygon[i], polygon[i+1]]
            area = (t[1][0]-t[0][0])*(t[2][1]-t[0][1])-(t[1][1]-t[0][1])*(t[2][0]-t[0][0])
            if abs(area) > 1e-10:
                triangles.append(t)
    if not triangles:
        raise ValueError('No usable surface was found in the top height band')
    return triangles


def _bounds(triangles):
    return [tuple(fn(p[a] for t in triangles for p in t) for a in (0, 1))
            for fn in (min, max)]


def top_band_center(spec, height=1.0):
    """XY bounds center of the supplied surface's top band."""
    lo, hi = _bounds(_top_triangles(spec, height))
    return tuple((lo[a]+hi[a])/2 for a in (0, 1))


def placements(records, count, bottom_radius, top_radius, *, split_planes=(), wrapper_distance=0., funnel_top=None):
    """Request licensed placement through an opaque wire contract."""
    from .components.geometry_adapter import acquire_geometry_worker
    wire_records = [[record[key] for key in (
        'vertices', 'faces', 'minimum', 'maximum', 'area', 'reference')]
        for record in records]
    result = acquire_geometry_worker().geometry_policy(
        'q83', p0=wire_records, p1=count, p2=bottom_radius, p3=top_radius,
        p4=split_planes, p5=wrapper_distance, p6=funnel_top,
    )
    return [(records[index], tuple(point)) for index, point in result['p0']]


def frustum_mesh(x, y, bottom, top, bottom_radius, top_radius, segments=96):
    if not top > bottom or not top_radius > bottom_radius > 0:
        raise ValueError('Rounded funnel requires top diameter > bottom diameter and positive height')
    vertices = [(x+r*math.cos(2*math.pi*i/segments), y+r*math.sin(2*math.pi*i/segments), z)
                for z,r in ((bottom,bottom_radius),(top,top_radius)) for i in range(segments)]
    faces = [tuple(reversed(range(segments))), tuple(range(segments,2*segments))]
    faces.extend((i,(i+1)%segments,(i+1)%segments+segments,i+segments) for i in range(segments))
    return vertices, faces


def open_bottom_mold_mesh(height, bottom_radius, top_radius, thickness, segments=96):
    """Closed mold material with inverted funnel cavity opening downward."""
    if thickness <= 0 or height <= 0:
        raise ValueError('Mold thickness and funnel height must be positive')
    # Profile follows the outside upward and the cavity back to its open rim.
    outer = top_radius+thickness
    rings = [(outer,0.), (outer,height+thickness), (bottom_radius,height), (top_radius,0.)]
    vertices = [(r*math.cos(2*math.pi*i/segments), r*math.sin(2*math.pi*i/segments),z)
                for r,z in rings for i in range(segments)]
    faces = []
    for a,b in ((0,1),(2,3),(3,0)):
        faces.extend((a*segments+i,a*segments+(i+1)%segments,b*segments+(i+1)%segments,b*segments+i) for i in range(segments))
    faces.append(tuple(range(segments,2*segments)))
    faces.append(tuple(reversed(range(2*segments,3*segments))))
    return vertices,faces
