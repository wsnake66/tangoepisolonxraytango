"""Conservative surface clearance checks for the custom head fitting preview."""

import bmesh
from itertools import product
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..progress import breathe_viewport
from ..custom_face_regions import HEAD_BOTTOM_KEY, head_region_distance

FACE_REFERENCES_KEY = "moldboxer_custom_face_references"
SURFACE_REFERENCES_KEY = "moldboxer_custom_face_surface_references"


def update_face_reference_points(core, dimensions):
    """Locate eye surfaces, nose tip and ear surfaces on the finished mesh."""
    clearance = dimensions["custom_face_comfort_clearance"]
    width = dimensions["custom_face_head_width"] + 2 * clearance
    depth = dimensions["custom_face_head_depth"] + 2 * clearance
    height = dimensions["custom_face_head_height"] + 2 * clearance
    bm = bmesh.new()
    try:
        bm.from_mesh(core.data)
        tree = BVHTree.FromBMesh(bm)
    finally:
        bm.free()
    references = {}
    surface_references = {}

    def project(name, origin, direction, target=None):
        point, _, _, _ = tree.ray_cast(Vector(origin), Vector(direction))
        if point is not None and head_region_distance(core, point) >= 0:
            (references if target is None else target)[name] = list(point)

    for side, label in ((-1, "left"), (1, "right")):
        # Probe the filled eye region from the front (-Y), not the brow's
        # outermost silhouette. Ears are probed laterally at three heights.
        project(f"{label}_eye", (side * width * 0.20, -depth * 2, height * 0.015), (0, 1, 0))
        for level, z in (("upper", 0.055), ("middle", -0.025), ("lower", -0.105)):
            project(f"{label}_ear_{level}", (side * width * 2, depth * 0.10, height * z), (-side, 0, 0))
    nose = [vertex.co for vertex in core.data.vertices
            if abs(vertex.co.x) < width * 0.12
            and -height * 0.22 <= vertex.co.z <= height * 0.04
            and head_region_distance(core, vertex.co) >= 0]
    if nose:
        references["nose_tip"] = list(min(nose, key=lambda point: point.y))
    # Front-facing probes cover recesses and facial details which broad
    # farthest-point sampling can miss between silhouette references.
    for row, z in enumerate((-0.34, -0.24, -0.14, -0.04, 0.06, 0.16, 0.26)):
        for column, x in enumerate((-0.36, -0.24, -0.12, 0, 0.12, 0.24, 0.36)):
            project(f"face_{row}_{column}", (x * width, -depth * 2, z * height),
                    (0, 1, 0), surface_references)
    core[FACE_REFERENCES_KEY] = references
    core[SURFACE_REFERENCES_KEY] = surface_references


def head_triangles(core):
    """Clip triangles at the local chin/neck limit, including crossing faces."""
    mesh = core.data
    mesh.calc_loop_triangles()
    matrix = core.matrix_world
    result = []
    for triangle in mesh.loop_triangles:
        polygon = [mesh.vertices[index].co.copy() for index in triangle.vertices]
        clipped = []
        for start, end in zip(polygon, polygon[1:] + polygon[:1]):
            start_distance = head_region_distance(core, start)
            end_distance = head_region_distance(core, end)
            if start_distance >= 0:
                clipped.append(start)
            if (start_distance >= 0) != (end_distance >= 0):
                clipped.append(start.lerp(end, start_distance / (start_distance - end_distance)))
        for index in range(1, len(clipped) - 1):
            result.append(tuple(matrix @ point for point in (
                clipped[0], clipped[index], clipped[index + 1],
            )))
    if not result:
        raise RuntimeError("No head surface found for the skin clearance check")
    return result


def head_reference_points(triangles, count=128):
    """Spread a small set of references over only the red head surface."""
    points = list({tuple(point): point for triangle in triangles for point in triangle}.values())
    # Farthest-point sampling is independent of local tessellation density.
    selected = [max(points, key=lambda point: point.z)]
    distances = [float("inf")] * len(points)
    for _ in range(min(count, len(points)) - 1):
        last = selected[-1]
        distances = [min(distance, (point - last).length_squared)
                     for point, distance in zip(points, distances)]
        selected.append(points[max(range(len(points)), key=distances.__getitem__)])
    return selected


class HeadClearance:
    """Certify complete triangle patches using distance's Lipschitz bound.

    Tests run in the master's initial world coordinates. Inverse scaling the
    queries avoids rebuilding the BVH on every fitting iteration.
    """

    def __init__(self, master, core, pivot):
        bm = bmesh.new()
        try:
            bm.from_mesh(master.data)
            if not bm.faces or any(not edge.is_manifold for edge in bm.edges):
                raise RuntimeError(
                    "Head clearance requires a closed master mesh. "
                    "Close the master openings before fitting the custom head."
                )
            bm.transform(master.matrix_world)
            self.tree = BVHTree.FromBMesh(bm)
        finally:
            bm.free()
        self.triangles = head_triangles(core)
        self.references = head_reference_points(self.triangles)
        for coordinates in core.get(SURFACE_REFERENCES_KEY, {}).values():
            point = core.matrix_world @ Vector(coordinates)
            if all((point - reference).length > 0.01 for reference in self.references):
                self.references.append(point)
        # Explicit anatomy references supplement the broad head coverage;
        # storing them locally keeps manual object transforms correct.
        self.landmark_indices = {}
        for name, coordinates in core.get(FACE_REFERENCES_KEY, {}).items():
            point = core.matrix_world @ Vector(coordinates)
            index = next((index for index, reference in enumerate(self.references)
                          if (point - reference).length <= 0.01), None)
            if index is None:
                index = len(self.references)
                self.references.append(point)
            self.landmark_indices[name] = index
        # Classify the rear skull cap in core-local space (-Y is face-front).
        # Keep lateral ear recesses on their dedicated landmark constraints.
        # This remains correct after the user rotates or translates the core.
        inverse = core.matrix_world.inverted()
        local_points = [inverse @ point for point in self.references]
        front_y = min(point.y for point in local_points)
        back_y = max(point.y for point in local_points)
        rear_start = front_y + (back_y - front_y) * 0.75
        self.rear_indices = [index for index, point in enumerate(local_points)
                             if point.y >= rear_start]
        self.pivot = pivot.copy()
        self.direction = Vector((0.37139, 0.52913, 0.76217)).normalized()

    def inside(self, point):
        origin = point.copy()
        crossings = 0
        for _ in range(256):
            location, _, _, _ = self.tree.ray_cast(origin, self.direction)
            if location is None:
                return crossings % 2 == 1
            crossings += 1
            origin = location + self.direction * 0.001
        return False

    def fits(self, scale, gap):
        # A small reserve absorbs mesh/transform float rounding at confirmation.
        required = (gap + 0.02) / scale
        pivot = self.pivot
        queries = 0
        for triangle in self.triangles:
            points = tuple(pivot + (point - pivot) / scale for point in triangle)
            pending = [(points, 0)]
            while pending:
                queries += 1
                if queries % 2048 == 0:
                    breathe_viewport()
                if queries > 200000:
                    return False
                (a, b, c), depth = pending.pop()
                center = (a + b + c) / 3.0
                _, _, _, distance = self.tree.find_nearest(center)
                if distance is None or distance < required or not self.inside(center):
                    return False
                radius = max((point - center).length for point in (a, b, c))
                # Every point in this triangle lies inside this ball, which
                # cannot touch the master surface or cross to its outside.
                if distance - radius >= required:
                    continue
                if depth >= 8:
                    return False  # Unresolved patches are never accepted.
                ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
                pending.extend(((patch, depth + 1) for patch in (
                    (a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca),
                )))
        return True

    def reference_points_fit(self, scale, gap):
        """Approximate skin spacing without imposing a whole-surface bound."""
        for reference in self.references:
            point = self.pivot + (reference - self.pivot) / scale
            _, _, _, distance = self.tree.find_nearest(point)
            if distance is None or distance * scale < gap + 0.02 or not self.inside(point):
                return False
        return True

    def reference_gaps(self, scale=1.0, translation=None, indices=None):
        translation = translation if translation is not None else Vector()
        gaps = []
        references = self.references if indices is None else [self.references[index] for index in indices]
        for reference in references:
            point = self.pivot + (reference - translation - self.pivot) / scale
            _, _, _, distance = self.tree.find_nearest(point)
            if distance is None:
                raise RuntimeError("Could not measure the master surface")
            gaps.append(distance * scale * (1.0 if self.inside(point) else -1.0))
        return gaps

    def fit_reference_gap(self, gap):
        """Balance surface spacing with uniform scale AND translation.

        Eye, nose, ear and rear-head points have hard minimum clearance. The
        remaining references minimize typical spacing with a robust loss.
        """
        span = [max(p[a] for p in self.references) - min(p[a] for p in self.references)
                for a in range(3)]
        limits = [max(span[0] * 0.15, 5), max(span[1] * 0.3, 10), max(span[2] * 0.15, 10)]
        # All sampled head surfaces must be inside; anatomical landmarks keep
        # their full skin-thickness minimum. The overall objective stays 4 mm.
        required = [0.30] * len(self.references)
        for index in set(self.landmark_indices.values()) | set(self.rear_indices):
            required[index] = gap + 0.05

        def cost(values):
            scale, x, y, z = values
            if not 0.6 <= scale <= 1.8 or any(abs(v) > limit for v, limit in zip((x, y, z), limits)):
                return (float("inf"), float("inf"))
            gaps = self.reference_gaps(scale, Vector((x, y, z)))
            residuals = [value - gap for value in gaps]
            # Lexicographic feasibility: average-fit improvements cannot trade
            # away the eye/nose/ear clearance. Reserve covers float roundoff.
            violation = sum(max(0.0, minimum - measured) ** 2
                            for minimum, measured in zip(required, gaps))
            delta = max(gap, 2.0)
            # Huber loss: isolated geometry differences have bounded influence.
            loss = sum(0.5 * r * r if abs(r) <= delta else delta * (abs(r) - 0.5 * delta)
                       for r in residuals) / len(residuals)
            return (violation, loss)

        values = [1.0, 0.0, 0.0, 0.0]
        best = cost(values)
        steps = [0.06, 4.0, 6.0, 4.0]
        for _ in range(8):
            for _ in range(12):
                changed = False
                for axis in range(4):
                    for sign in (-1, 1):
                        candidate = values.copy()
                        candidate[axis] += sign * steps[axis]
                        score = cost(candidate)
                        if score < best:
                            values, best, changed = candidate, score, True
                if not changed:
                    break
            steps = [step * 0.5 for step in steps]
            breathe_viewport()
        if best[0] == 0.0:
            # At an active clearance constraint, translation alone and scale
            # alone can both look worse. Search them together: for each nearby
            # position, find the smallest landmark-safe scale, then compare
            # the overall head spacing. This avoids sticking at an oversized
            # solution simply because one landmark is touching its limit.
            def smallest_feasible(candidate):
                shift = Vector(candidate[1:])

                def feasible(scale):
                    for index in sorted(range(len(required)), key=required.__getitem__, reverse=True):
                        point = self.pivot + (self.references[index] - shift - self.pivot) / scale
                        _, _, _, distance = self.tree.find_nearest(point)
                        if distance is None or distance * scale < required[index] or not self.inside(point):
                            return False
                    return True

                lower, upper = 0.6, min(1.8, values[0] + 0.04)
                if not feasible(upper):
                    return None
                for _ in range(13):
                    middle = (lower + upper) / 2
                    if feasible(middle):
                        upper = middle
                    else:
                        lower = middle
                candidate[0] = upper
                return candidate

            for step in (4.0, 2.0, 1.0, 0.5, 0.25, 0.125):
                for _ in range(8):
                    changed = False
                    for direction in product((-1, 0, 1), repeat=3):
                        if direction == (0, 0, 0):
                            continue
                        candidate = values.copy()
                        for axis, sign in enumerate(direction, 1):
                            candidate[axis] += sign * step
                        candidate = smallest_feasible(candidate)
                        if candidate is None:
                            continue
                        score = cost(candidate)
                        if score < best:
                            values, best, changed = candidate, score, True
                    breathe_viewport()
                    if not changed:
                        break
                breathe_viewport()
        scale, x, y, z = values
        translation = Vector((x, y, z))
        gaps = self.reference_gaps(scale, translation)
        failed = [name for name, index in self.landmark_indices.items() if gaps[index] < gap + 0.02]
        if any(gaps[index] < gap + 0.02 for index in self.rear_indices):
            failed.append("back of head")
        if failed:
            raise RuntimeError(
                "Could not fit the eye, nose, ear and rear-head references with "
                f"{gap:g} mm clearance. Check the master shape and alignment."
            )
        if min(gaps) < 0.25:
            raise RuntimeError(
                "Some head references remain outside the master. "
                "Check the master shape and alignment before continuing."
            )
        return scale, translation, gaps
