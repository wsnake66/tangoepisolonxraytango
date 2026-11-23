"""Primitive mold boxes and their wall-thickness expansion."""
import math
import random
import numpy as np
import bmesh  # type: ignore
import bpy  # type: ignore

from ..bl_utils import BMeshObj

from ..background_worker import BackgroundTaskSequence
from ..object import Object
from ..primitives import (
    MOLD_BODY_CYLINDER_VERTICES,
    create_cube_primitive,
    create_cylinder_primitive,
)


def begin_primitive_box(
    source, *, distance, shape_type, matching_shape=False,
    vertical_faces=4, pad_vertical=False,
):
    """Enclose a source, or expand an existing matching primitive.

    Cylinder offsets are measured at the polygon faces so the minimum wall
    thickness is maintained between vertices as well. ``pad_vertical`` keeps
    material above and below silicone/direct masters before bottom refinement;
    Slip Casting retains its original unpadded cube caps by default.
    """
    def steps():
        padding = max(float(distance), 0.0)
        vertical_padding = (
            0.0 if shape_type == "cube" and not matching_shape and not pad_vertical
            else padding
        )
        placement = source.center_coords.copy()
        polygonal = shape_type == "cube" and int(vertical_faces) != 4
        if polygonal:
            body = _polygon_box(source, padding, int(vertical_faces), matching_shape, pad_vertical)
            width, depth = body.width, body.depth
        elif shape_type == "cube":
            body = Object(create_cube_primitive(1.0), "box")
            width = source.width + 2.0 * padding
            depth = source.depth + 2.0 * padding
        elif shape_type == "cylinder":
            sides = MOLD_BODY_CYLINDER_VERTICES
            cosine = math.cos(math.pi / sides)
            if matching_shape:
                # The 64-sided source has symmetric XY bounds, even after
                # server import. Reuse its center and expand the face offset.
                diameter = max(source.width, source.depth) + 2.0 * padding / cosine
            else:
                center, radius = _minimum_enclosing_circle(_world_xy_points(source))
                placement.x, placement.y = center
                diameter = 2.0 * (radius + padding) / cosine
            body = Object(create_cylinder_primitive(0.5, 1.0, vertices=sides), "box")
            width = depth = diameter
        else:
            raise ValueError(f"Unsupported mold box shape: {shape_type}")
        if not polygonal:
            body.scale_to(width, axis=0)
            body.scale_to(depth, axis=1)
            body.scale_to(source.height + 2.0 * vertical_padding, axis=2)
            body.translate_whole(placement)
        body.apply_all_transforms()
        if shape_type == "cube":
            radius = min(5.0 + padding if matching_shape else min(5.0, padding),
                         min(width, depth, body.height) * 0.25)
            if radius > 1e-6:
                with BMeshObj(body, repair_winding=True) as bm:
                    # Keep a flat portion on every side, even at high counts.
                    radius = min(radius, min(edge.calc_length() for edge in bm.edges) * 0.35)
                    edges = list(bm.edges)
                    if matching_shape and polygonal and int(vertical_faces) > 4:
                        # A rounded offset corner must not cut inside the
                        # requested wall distance between the fitted planes.
                        radius = min(radius, padding * math.tan(math.pi / int(vertical_faces)) * 0.9)
                    # Keep the top and bottom perimeters square on every cubic box.
                    edges = [edge for edge in edges
                             if abs((edge.verts[1].co - edge.verts[0].co).normalized().z) > 0.999]
                    bm.normal_update()
                    center = sum((v.co for v in bm.verts), bm.verts[0].co * 0.0) / len(bm.verts)
                    planes = [(f.normal.copy(), f.normal.dot(f.verts[0].co)) for f in bm.faces]
                    bmesh.ops.bevel(bm, geom=edges, offset=radius,
                                    segments=6, profile=0.5, affect="EDGES", clamp_overlap=True)
                    # Keep bevel vertices inside the original convex solid.
                    # Blender 4.5 can slightly overshoot the fitted side planes.
                    for vertex in bm.verts:
                        direction = vertex.co - center
                        factor = 1.0
                        for normal, offset in planes:
                            projection = normal.dot(direction)
                            if projection > 0.0 and normal.dot(vertex.co) > offset + 1e-6:
                                factor = min(factor, (offset - normal.dot(center)) / projection)
                        if factor < 1.0:
                            vertex.co = center + direction * max(0.0, factor)
        return body
        yield  # Keep primitive creation inside the task lifecycle.

    return BackgroundTaskSequence(steps())


def extend_primitive_opening_cutter(cutter, top_z):
    """Raise the upper half beyond the assembly without moving the bottom."""
    cutter.apply_all_transforms()
    midpoint = (cutter.min_z + cutter.max_z) * 0.5
    # Carry the entire upper bevel beyond the box, not just its top face.
    upper = [v for v in cutter.object.data.vertices if v.co.z > midpoint]
    if not upper:
        raise ValueError("Primitive opening cutter has no upper vertices")
    distance = max(0.0, float(top_z) - min(v.co.z for v in upper))
    for vertex in upper:
        vertex.co.z += distance
    cutter.object.data.update()


def _polygon_box(source, padding, sides, matching_shape, pad_vertical=False):
    """Intersect upright side planes; expand each face by the wall thickness.

    Recover planes from the mesh for the opener, since server import does not
    retain custom properties and odd-sided polygons have asymmetric bounds.
    """
    if not 3 <= sides <= 64:
        raise ValueError("Vertical face count must be between 3 and 64")
    normals = [(math.cos(2 * math.pi * i / sides),
                math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    if matching_shape or sides > 4:
        points = [source.object.matrix_world @ v.co for v in source.object.data.vertices]
        supports = [max(x * p.x + y * p.y for p in points) + padding
                    for x, y in normals]
    else:
        center = source.center_coords
        apothem = max(abs(x) * source.width / 2 + abs(y) * source.depth / 2
                      for x, y in normals) + padding
        supports = [x * center.x + y * center.y + apothem for x, y in normals]
    ring = []
    for i, (x1, y1) in enumerate(normals):
        j = (i + 1) % sides
        x2, y2 = normals[j]
        determinant = x1 * y2 - y1 * x2
        ring.append(((supports[i] * y2 - y1 * supports[j]) / determinant,
                     (x1 * supports[j] - supports[i] * x2) / determinant))
    vertical_padding = padding if matching_shape or pad_vertical else 0.0
    verts = [(x, y, z) for z in (source.min_z - vertical_padding, source.max_z + vertical_padding)
             for x, y in ring]
    faces = [tuple(reversed(range(sides))), tuple(range(sides, 2 * sides))]
    faces += [(i, (i + 1) % sides, (i + 1) % sides + sides, i + sides)
              for i in range(sides)]
    mesh = bpy.data.meshes.new("box")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    raw = bpy.data.objects.new("box", mesh)
    bpy.context.collection.objects.link(raw)
    return Object(raw)


def extrude_primitive_opening_caps(cutter, *, bottom_z, top_z):
    """Extrude the flat end caps while keeping the surrounding bevels fixed."""
    cutter.apply_all_transforms()
    with BMeshObj(cutter, repair_winding=True) as bm:
        bm.normal_update()
        low = min(v.co.z for v in bm.verts)
        high = max(v.co.z for v in bm.verts)
        tolerance = max((high - low) * 1e-6, 1e-5)
        for level, target, sign in ((low, bottom_z, -1), (high, top_z, 1)):
            distance = float(target) - level
            if distance * sign <= tolerance:
                continue
            caps = [face for face in bm.faces
                    if face.normal.z * sign > 0.99999
                    and all(abs(v.co.z - level) <= tolerance for v in face.verts)]
            if not caps:
                raise ValueError("Opening cutter is missing a flat central end face")
            result = bmesh.ops.extrude_face_region(bm, geom=caps)
            for vertex in result["geom"]:
                if isinstance(vertex, bmesh.types.BMVert):
                    vertex.co.z += distance
            remaining_caps = [face for face in caps if face.is_valid]
            if remaining_caps:
                bmesh.ops.delete(bm, geom=remaining_caps, context="FACES_ONLY")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))


def _world_xy_points(source):
    coordinates = np.empty(len(source.object.data.vertices) * 3, dtype=np.float64)
    source.object.data.vertices.foreach_get("co", coordinates)
    coordinates = coordinates.reshape((-1, 3))
    matrix = np.asarray(source.object.matrix_world, dtype=np.float64)
    return np.einsum("ij,kj->ik", coordinates, matrix[:2, :3]) + matrix[:2, 3]


def _minimum_enclosing_circle(points):
    """Deterministic randomized incremental circle on the footprint's hull."""
    points = sorted({(float(p[0]), float(p[1])) for p in points})
    if not points:
        raise ValueError("Cylinder generation requires a nonempty mesh")
    if not all(math.isfinite(x) and math.isfinite(y) for x, y in points):
        raise ValueError("Cylinder footprint contains nonfinite coordinates")

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    lower, upper = [], []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1] if len(points) > 1 else points
    random.Random(0).shuffle(hull)

    def contains(circle, point):
        if circle is None:
            return False
        x, y, radius = circle
        return math.hypot(point[0] - x, point[1] - y) <= radius + max(radius, 1.0) * 1e-12

    def diameter(a, b):
        center = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        return (*center, math.hypot(a[0] - b[0], a[1] - b[1]) / 2)

    def circumcircle(a, b, c):
        bx, by = b[0] - a[0], b[1] - a[1]
        cx, cy = c[0] - a[0], c[1] - a[1]
        determinant = 2 * (bx * cy - by * cx)
        if abs(determinant) <= 1e-14 * max(bx*bx + by*by, cx*cx + cy*cy, 1e-30):
            return max((diameter(a, b), diameter(a, c), diameter(b, c)), key=lambda circle: circle[2])
        b2, c2 = bx*bx + by*by, cx*cx + cy*cy
        x, y = (cy*b2 - by*c2) / determinant, (bx*c2 - cx*b2) / determinant
        return (a[0] + x, a[1] + y, math.hypot(x, y))

    circle = None
    for i, a in enumerate(hull):
        if contains(circle, a):
            continue
        circle = (a[0], a[1], 0.0)
        for j in range(i):
            b = hull[j]
            if contains(circle, b):
                continue
            circle = diameter(a, b)
            for k in range(j):
                c = hull[k]
                if not contains(circle, c):
                    circle = circumcircle(a, b, c)
    x, y, radius = circle
    # Protect containment against accumulated floating-point rounding.
    radius = max(radius, max(math.hypot(px - x, py - y) for px, py in hull))
    return (x, y), radius
