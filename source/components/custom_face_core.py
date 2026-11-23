"""Parametric human-head geometry for Direct Skin custom face cores."""

import logging
import math

import bmesh  # type: ignore
import bpy  # type: ignore
import mathutils  # type: ignore

from ..constants import ENABLE_CUSTOM_FACE_CORE
from ..materials import assign_generated_material
from ..custom_face_regions import HEAD_NECK_FRONT_KEY, HEAD_NECK_SLOPE_KEY, head_region_distance
from ..custom_face_neck import DEFAULT_NECK_SETTINGS, neck_settings, shape_neck
from .head_clearance import HEAD_BOTTOM_KEY, HeadClearance, head_triangles, update_face_reference_points
from .geometry_adapter import (
    acquire_geometry_worker,
    begin_custom_face_core_geometry,
)


CUSTOM_FACE_CORE_MARKER = "moldboxer_custom_face_core"
CUSTOM_FACE_CORE_BASES_DIRTY_MARKER = "moldboxer_custom_face_bases_dirty"
CUSTOM_FACE_CORE_LOCATION_MARKER = "moldboxer_custom_face_location"
CUSTOM_FACE_MASTER_BASE_MATRIX_MARKER = "moldboxer_custom_face_master_base_matrix"
SKIN_CORE_NAME = "skin_core"
SKIN_CORE_MARKER = "moldboxer_skin_core"
SKIN_CORE_CONFIRMED_MARKER = "moldboxer_skin_core_confirmed"
CUSTOM_FACE_MASTER_FIT_MARGIN = 4.0
CUSTOM_FACE_MASTER_VOLUME_RATIO = 1.15
CUSTOM_FACE_REMESH_RESOLUTION = 72.0
CUSTOM_FACE_SMOOTHING_ITERATIONS = 6
CUSTOM_FACE_SMOOTHING_FACTOR = 0.32

DEFAULT_FACE_DIMENSIONS = {
    "custom_face_head_height": 230.0,
    "custom_face_head_width": 155.0,
    "custom_face_head_depth": 195.0,
    "custom_face_cheek_width": 135.0,
    "custom_face_neck_circumference": 305.0,
    "custom_face_comfort_clearance": 2.0,
    "custom_face_ear_clearance": 2.0,
    "custom_face_hair_allowance": 0.0,
    "custom_face_forehead_width": 142.0,
    "custom_face_jaw_width": 116.0,
    "custom_face_chin_length": 32.0,
    "custom_face_nose_length": 22.0,
    "custom_face_nose_width": 38.0,
    "custom_face_nose_height": 52.0,
}

_ZERO_ALLOWED_FACE_DIMENSIONS = {
    "custom_face_comfort_clearance",
    "custom_face_ear_clearance",
    "custom_face_hair_allowance",
}

_CUSTOM_FACE_MASTER_FIT_UPDATE_ACTIVE = False

logger = logging.getLogger(__name__)


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    if edge0 == edge1:
        return float(value >= edge1)
    amount = min(max((value - edge0) / (edge1 - edge0), 0.0), 1.0)
    return amount * amount * (3.0 - 2.0 * amount)


def custom_face_dimensions(scene) -> dict[str, float]:
    """Return sanitized scene dimensions used to construct the face core."""

    values = {}
    for name, default in DEFAULT_FACE_DIMENSIONS.items():
        minimum = 0.0 if name in _ZERO_ALLOWED_FACE_DIMENSIONS else 0.1
        values[name] = max(float(getattr(scene, name, default)), minimum)
    return values


def _cut_flat_neck_base(mesh, height: float) -> None:
    """Trim and cap the lower neck so the generated core has a planar base."""

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bottom_z = min((vertex.co.z for vertex in bm.verts), default=-height / 2.0)
        cut_z = bottom_z + max(1.0, height * 0.01)
        bmesh.ops.bisect_plane(
            bm,
            geom=tuple(bm.verts) + tuple(bm.edges) + tuple(bm.faces),
            dist=0.0001,
            plane_co=mathutils.Vector((0.0, 0.0, cut_z)),
            plane_no=mathutils.Vector((0.0, 0.0, 1.0)),
            clear_inner=True,
            clear_outer=False,
        )
        loose_vertices = tuple(vertex for vertex in bm.verts if not vertex.link_faces)
        if loose_vertices:
            bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")
        cut_boundary = tuple(
            edge
            for edge in bm.edges
            if edge.is_boundary
            and all(abs(vertex.co.z - cut_z) <= 0.001 for vertex in edge.verts)
        )
        if cut_boundary:
            boundary_vertices = tuple(
                {vertex for edge in cut_boundary for vertex in edge.verts}
            )
            lower_neck_vertices = tuple(
                vertex
                for vertex in bm.verts
                if vertex.co.z <= cut_z + height * 0.08
            )
            for _iteration in range(5):
                bmesh.ops.smooth_vert(
                    bm,
                    verts=lower_neck_vertices,
                    factor=0.5,
                    use_axis_x=True,
                    use_axis_y=True,
                    use_axis_z=False,
                )
            minimum_x = min(vertex.co.x for vertex in boundary_vertices)
            maximum_x = max(vertex.co.x for vertex in boundary_vertices)
            minimum_y = min(vertex.co.y for vertex in boundary_vertices)
            maximum_y = max(vertex.co.y for vertex in boundary_vertices)
            center_x = (minimum_x + maximum_x) / 2.0
            center_y = (minimum_y + maximum_y) / 2.0
            radius_x = max((maximum_x - minimum_x) * 0.45, 0.1)
            radius_y = max((maximum_y - minimum_y) * 0.45, 0.1)
            for vertex in boundary_vertices:
                angle = math.atan2(
                    (vertex.co.y - center_y) / radius_y,
                    (vertex.co.x - center_x) / radius_x,
                )
                vertex.co.x = center_x + math.cos(angle) * radius_x
                vertex.co.y = center_y + math.sin(angle) * radius_y
                vertex.co.z = cut_z
            bmesh.ops.holes_fill(bm, edges=cut_boundary, sides=0)
        bmesh.ops.recalc_face_normals(bm, faces=tuple(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()


def _voxel_solidify(obj, dimensions: dict[str, float]):
    """Rebuild a clean, intentionally simplified exterior boundary."""

    source_mesh = obj.data
    solidifier = obj.modifiers.new("Solid Face Core", type="REMESH")
    solidifier.mode = "VOXEL"
    solidifier.voxel_size = max(
        min(
            dimensions["custom_face_head_width"],
            dimensions["custom_face_head_depth"],
            dimensions["custom_face_head_height"],
        )
        / CUSTOM_FACE_REMESH_RESOLUTION,
        0.5,
    )
    solidifier.adaptivity = 0.0
    solidifier.use_remove_disconnected = True
    solidifier.use_smooth_shade = True
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = obj.evaluated_get(depsgraph)
    solid_mesh = bpy.data.meshes.new_from_object(
        evaluated_object,
        preserve_all_data_layers=False,
        depsgraph=depsgraph,
    )
    obj.modifiers.clear()
    obj.data = solid_mesh
    if source_mesh is not None and getattr(source_mesh, "users", 0) == 0:
        bpy.data.meshes.remove(source_mesh)
    return solid_mesh


def _smooth_core_surface(mesh) -> None:
    """Soften anatomical creases while retaining the core's overall volume."""

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        vertices = tuple(bm.verts)
        for _iteration in range(CUSTOM_FACE_SMOOTHING_ITERATIONS):
            bmesh.ops.smooth_laplacian_vert(
                bm,
                verts=vertices,
                lambda_factor=CUSTOM_FACE_SMOOTHING_FACTOR,
                lambda_border=0.0,
                use_x=True,
                use_y=True,
                use_z=True,
                preserve_volume=True,
            )
        bmesh.ops.recalc_face_normals(bm, faces=tuple(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def _fit_neck_opening(mesh, target_circumference: float, height: float) -> None:
    """Match the finished flat neck boundary to its measurable circumference."""

    if not mesh.vertices or not mesh.edges:
        return
    bottom_z = min(vertex.co.z for vertex in mesh.vertices)
    boundary_edges = tuple(
        edge
        for edge in mesh.edges
        if all(
            abs(mesh.vertices[index].co.z - bottom_z) <= 0.001
            for index in edge.vertices
        )
    )
    if not boundary_edges:
        return
    current_circumference = sum(
        (
            mesh.vertices[edge.vertices[0]].co
            - mesh.vertices[edge.vertices[1]].co
        ).length
        for edge in boundary_edges
    )
    if current_circumference <= 0.0:
        return
    boundary_indices = {
        index for edge in boundary_edges for index in edge.vertices
    }
    center_x = sum(mesh.vertices[index].co.x for index in boundary_indices) / len(
        boundary_indices
    )
    center_y = sum(mesh.vertices[index].co.y for index in boundary_indices) / len(
        boundary_indices
    )
    boundary_scale = target_circumference / current_circumference
    blend_height = max(height * 0.14, 1.0)
    for vertex in mesh.vertices:
        blend = 1.0 - _smoothstep(
            bottom_z,
            bottom_z + blend_height,
            vertex.co.z,
        )
        scale = 1.0 + (boundary_scale - 1.0) * blend
        vertex.co.x = center_x + (vertex.co.x - center_x) * scale
        vertex.co.y = center_y + (vertex.co.y - center_y) * scale
    mesh.update()


def _add_ear_attachment_fillers(mesh, dimensions: dict[str, float], contour) -> None:
    """Bridge each ear and replace deep inner folds with a shallow smooth inset."""

    width = dimensions["custom_face_head_width"]
    depth = dimensions["custom_face_head_depth"]
    height = dimensions["custom_face_head_height"]
    ear_clearance = dimensions["custom_face_ear_clearance"]
    center_y = (min(point[0] for point in contour) + max(point[0] for point in contour)) / 2.0
    center_z = (min(point[1] for point in contour) + max(point[1] for point in contour)) / 2.0
    detail_inset = 0.82

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        for side in (-1.0, 1.0):
            inner_x = side * width * 0.30
            outer_x = side * (width * 0.45 + ear_clearance)
            inner_ring = tuple(
                bm.verts.new((inner_x, point_y * depth / 2.0, point_z * height / 2.0))
                for point_y, point_z in contour
            )
            outer_ring = tuple(
                bm.verts.new((outer_x, point_y * depth / 2.0, point_z * height / 2.0))
                for point_y, point_z in contour
            )
            detail_ring = tuple(
                bm.verts.new(
                    (
                        side * (width * 0.475 + ear_clearance),
                        (
                            center_y
                            + (point_y - center_y)
                            * (0.96 if point_y <= center_y else detail_inset)
                        )
                        * depth
                        / 2.0,
                        (
                            center_z + (point_z - center_z) * detail_inset
                        )
                        * height
                        / 2.0,
                    )
                )
                for point_y, point_z in contour
            )
            surface_center = bm.verts.new(
                (
                    side * (width * 0.48 + ear_clearance),
                    center_y * depth / 2.0,
                    center_z * height / 2.0,
                )
            )
            bm.faces.new(inner_ring)
            for index in range(len(contour)):
                next_index = (index + 1) % len(contour)
                bm.faces.new(
                    (
                        inner_ring[index],
                        inner_ring[next_index],
                        outer_ring[next_index],
                        outer_ring[index],
                    )
                )
                bm.faces.new(
                    (
                        outer_ring[index],
                        outer_ring[next_index],
                        detail_ring[next_index],
                        detail_ring[index],
                    )
                )
                bm.faces.new(
                    (
                        detail_ring[index],
                        detail_ring[next_index],
                        surface_center,
                    )
                )
        bm.to_mesh(mesh)
    finally:
        bm.free()


def _compact_ears(mesh, dimensions):
    """Compress the ears and their solid backing into shallow side cushions."""
    width = dimensions["custom_face_head_width"] + 2 * dimensions["custom_face_comfort_clearance"]
    depth = dimensions["custom_face_head_depth"] + 2 * dimensions["custom_face_comfort_clearance"]
    height = dimensions["custom_face_head_height"] + 2 * dimensions["custom_face_comfort_clearance"]
    root = width * 0.46 + dimensions["custom_face_ear_clearance"]
    for vertex in mesh.vertices:
        point = vertex.co
        y, z = point.y / depth, point.z / height
        weight = _smoothstep(-0.03, 0.04, y) * (1 - _smoothstep(0.18, 0.26, y))
        weight *= _smoothstep(-0.22, -0.16, z) * (1 - _smoothstep(0.10, 0.16, z))
        projection = max(0.0, abs(point.x) - root)
        point.x -= math.copysign(projection * 0.88 * weight, point.x)
    mesh.update()


def _smooth_compact_ears(mesh, dimensions):
    """Blend the residual ear rims into the solid side of the head."""
    width = dimensions["custom_face_head_width"]
    depth = dimensions["custom_face_head_depth"]
    height = dimensions["custom_face_head_height"]
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        vertices = [vertex for vertex in bm.verts
                    if abs(vertex.co.x) > width * 0.42
                    and -0.02 < vertex.co.y / depth < 0.23
                    and -0.20 < vertex.co.z / height < 0.13]
        for _ in range(18):
            bmesh.ops.smooth_vert(bm, verts=vertices, factor=0.65,
                                 use_axis_x=True, use_axis_y=True, use_axis_z=True)
        bmesh.ops.recalc_face_normals(bm, faces=tuple(bm.faces))
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


def _replace_mesh_geometry(obj, dimensions: dict[str, float], *, geometry=None, neck=None) -> None:
    result = (
        geometry if geometry is not None
        else acquire_geometry_worker().custom_face_core(dimensions)
    )
    vertices, faces = result["vertices"], result["faces"]
    control_mesh = bpy.data.meshes.new(f"{SKIN_CORE_NAME}_control_mesh")
    control_mesh.from_pydata(vertices, [], faces)
    control_mesh.validate(clean_customdata=False)

    bm = bmesh.new()
    try:
        bm.from_mesh(control_mesh)
        bmesh.ops.recalc_face_normals(bm, faces=tuple(bm.faces))
        bm.to_mesh(control_mesh)
    finally:
        bm.free()

    previous_mesh = getattr(obj, "data", None)
    previous_materials = tuple(getattr(previous_mesh, "materials", ()))
    for material in previous_materials:
        control_mesh.materials.append(material)
    obj.data = control_mesh
    obj.modifiers.clear()
    final_mesh = control_mesh
    _add_ear_attachment_fillers(final_mesh, dimensions, result["ear_contour"])
    _compact_ears(final_mesh, dimensions)
    _cut_flat_neck_base(final_mesh, dimensions["custom_face_head_height"])
    final_mesh = _voxel_solidify(obj, dimensions)
    _smooth_core_surface(final_mesh)
    _smooth_compact_ears(final_mesh, dimensions)
    _cut_flat_neck_base(final_mesh, dimensions["custom_face_head_height"])
    _fit_neck_opening(
        final_mesh,
        dimensions["custom_face_neck_circumference"]
        + math.tau * dimensions["custom_face_comfort_clearance"],
        dimensions["custom_face_head_height"]
        + dimensions["custom_face_comfort_clearance"] * 2.0,
    )
    for polygon in final_mesh.polygons:
        polygon.use_smooth = True
    final_mesh.update()
    if previous_mesh is not None and getattr(previous_mesh, "users", 0) == 0:
        bpy.data.meshes.remove(previous_mesh)
    final_mesh.name = f"{SKIN_CORE_NAME}_mesh"
    # Rise from below the chin to the nape, leaving the jaw and ears in the head.
    height = dimensions["custom_face_head_height"]
    chin_extension = max(0.0, dimensions["custom_face_chin_length"] - 32.0 * height / 230.0)
    obj[HEAD_BOTTOM_KEY] = (
        -0.40 * (height + 2.0 * dimensions["custom_face_comfort_clearance"])
        - chin_extension * 0.72
    )
    depth = dimensions["custom_face_head_depth"] + 2.0 * dimensions["custom_face_comfort_clearance"]
    obj[HEAD_NECK_FRONT_KEY] = -0.30 * depth
    obj[HEAD_NECK_SLOPE_KEY] = 0.27 * height / (0.65 * depth)
    shape_neck(obj, dimensions, neck if neck is not None else DEFAULT_NECK_SETTINGS)
    update_face_reference_points(obj, dimensions)
    assign_generated_material(obj)


def _world_bounds(obj) -> tuple[mathutils.Vector, mathutils.Vector]:
    corners = [
        obj.matrix_world @ mathutils.Vector(corner)
        for corner in obj.bound_box
    ]
    return (
        mathutils.Vector(
            tuple(min(corner[axis] for corner in corners) for axis in range(3))
        ),
        mathutils.Vector(
            tuple(max(corner[axis] for corner in corners) for axis in range(3))
        ),
    )


def _world_volume_centroid(obj) -> tuple[float, mathutils.Vector, bool]:
    """Return world volume, volume centroid, and whether mesh volume was usable."""

    minimum, maximum = _world_bounds(obj)
    bounds_size = maximum - minimum
    bounds_volume = max(
        float(bounds_size.x * bounds_size.y * bounds_size.z),
        0.001,
    )
    bounds_center = (minimum + maximum) / 2.0
    mesh = getattr(obj, "data", None)
    if mesh is None or not getattr(mesh, "polygons", None):
        return bounds_volume, bounds_center, False

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        closed = bool(bm.faces) and all(edge.is_manifold for edge in bm.edges)
    finally:
        bm.free()
    if not closed:
        return bounds_volume, bounds_center, False

    mesh.calc_loop_triangles()
    reference = bounds_center
    signed_volume = 0.0
    weighted_center = mathutils.Vector((0.0, 0.0, 0.0))
    matrix_world = obj.matrix_world
    for triangle in mesh.loop_triangles:
        point_a, point_b, point_c = (
            matrix_world @ mesh.vertices[index].co
            for index in triangle.vertices
        )
        relative_a = point_a - reference
        relative_b = point_b - reference
        relative_c = point_c - reference
        tetrahedron_volume = float(
            relative_a.dot(relative_b.cross(relative_c)) / 6.0
        )
        signed_volume += tetrahedron_volume
        weighted_center += (
            reference + point_a + point_b + point_c
        ) * (tetrahedron_volume / 4.0)

    if abs(signed_volume) <= max(bounds_volume * 1e-8, 1e-6):
        return bounds_volume, bounds_center, False
    return abs(signed_volume), weighted_center / signed_volume, True


def _average_vectors(vectors) -> mathutils.Vector:
    if not vectors:
        return mathutils.Vector((0.0, 0.0, 0.0))
    result = mathutils.Vector((0.0, 0.0, 0.0))
    for vector in vectors:
        result += vector
    return result / len(vectors)


def _world_head_face_landmarks(
    obj,
) -> tuple[mathutils.Vector, mathutils.Vector, bool]:
    """Return a head center and robust central-face anchor in world space."""

    mesh = getattr(obj, "data", None)
    if mesh is None or not getattr(mesh, "vertices", None):
        minimum, maximum = _world_bounds(obj)
        center = (minimum + maximum) / 2.0
        return center, center, False

    matrix_world = obj.matrix_world
    vertices = [matrix_world @ vertex.co for vertex in mesh.vertices]
    if obj.get(HEAD_BOTTOM_KEY) is not None:
        vertices = [matrix_world @ vertex.co for vertex in mesh.vertices
                    if head_region_distance(obj, vertex.co) >= 0]
    minimum, maximum = _world_bounds(obj)
    if obj.get(HEAD_BOTTOM_KEY) is not None and vertices:
        minimum = mathutils.Vector(tuple(min(point[axis] for point in vertices) for axis in range(3)))
        maximum = mathutils.Vector(tuple(max(point[axis] for point in vertices) for axis in range(3)))
    total_height = max(float(maximum.z - minimum.z), 0.001)
    head_width = max(float(maximum.x - minimum.x), 0.001)
    # Human crown-to-chin height is about 1.5 times maximum head breadth.
    # Measuring down from the crown deliberately excludes long necks, busts,
    # and shoulder bases that otherwise pull the volume center downward.
    head_height = min(total_height, head_width * 1.5)
    head_bottom = float(maximum.z) - head_height
    head_vertices = [vertex for vertex in vertices if vertex.z >= head_bottom]
    if not head_vertices:
        center = (minimum + maximum) / 2.0
        return center, center, False

    head_minimum = mathutils.Vector(
        tuple(min(vertex[axis] for vertex in head_vertices) for axis in range(3))
    )
    head_maximum = mathutils.Vector(
        tuple(max(vertex[axis] for vertex in head_vertices) for axis in range(3))
    )
    head_center = (head_minimum + head_maximum) / 2.0

    face_top = float(maximum.z) - head_height * 0.20
    face_bottom = float(maximum.z) - head_height * 0.78
    center_half_width = head_width * 0.22
    candidates = [
        vertex
        for vertex in head_vertices
        if face_bottom <= vertex.z <= face_top
        and abs(vertex.x - head_center.x) <= center_half_width
    ]
    if len(candidates) < 12:
        center_half_width = head_width * 0.35
        candidates = [
            vertex
            for vertex in head_vertices
            if face_bottom <= vertex.z <= face_top
            and abs(vertex.x - head_center.x) <= center_half_width
        ]
    if len(candidates) < 3:
        return head_center, head_center, False

    # Face-front is -Y in the normalized Moldboxer orientation. Averaging a
    # small front percentile is more stable than using one nose-tip vertex and
    # still anchors the vertical placement to the eyes/nose/mouth region.
    candidates.sort(key=lambda vertex: vertex.y)
    front_count = min(
        len(candidates),
        max(12, int(math.ceil(len(candidates) * 0.06))),
    )
    face_anchor = _average_vectors(candidates[:front_count])
    return head_center, face_anchor, True


def initialize_custom_face_dimensions(scene, source) -> None:
    """Initialize a predictable adult-size head independently of the master."""

    del source
    for name, default in DEFAULT_FACE_DIMENSIONS.items():
        setattr(scene, name, default)
    for name, default in DEFAULT_NECK_SETTINGS.items():
        setattr(scene, name, default)


def _custom_face_master(scene):
    scene_objects = getattr(scene, "objects", None)
    if scene_objects is None:
        return None
    for object_name in ("master", "patron"):
        obj = scene_objects.get(object_name)
        if obj is not None and getattr(obj, "type", None) == "MESH":
            return obj
    return None


def _flatten_matrix(matrix) -> list[float]:
    return [float(matrix[row][column]) for row in range(4) for column in range(4)]


def _matrix_from_flat_values(values):
    try:
        if len(values) != 16:
            return None
    except (TypeError, AttributeError):
        return None
    return mathutils.Matrix(
        tuple(tuple(float(values[row * 4 + column]) for column in range(4)) for row in range(4))
    )


def _master_base_matrix(master):
    stored = _matrix_from_flat_values(
        master.get(CUSTOM_FACE_MASTER_BASE_MATRIX_MARKER)
    )
    if stored is not None:
        return stored

    backup = bpy.data.objects.get("backup")
    if backup is not None and getattr(backup, "type", None) == "MESH":
        base_matrix = backup.matrix_world.copy()
    else:
        base_matrix = master.matrix_world.copy()
    master[CUSTOM_FACE_MASTER_BASE_MATRIX_MARKER] = _flatten_matrix(base_matrix)
    return base_matrix


def center_skin_master_origin(master) -> None:
    """Center the editing pivot without moving mesh geometry or children."""
    corners = [mathutils.Vector(corner) for corner in master.bound_box]
    center = mathutils.Vector(tuple(
        (min(point[axis] for point in corners) + max(point[axis] for point in corners)) / 2.0
        for axis in range(3)
    ))
    if center.length < 1e-6:
        return
    child_matrices = [(child, child.matrix_world.copy()) for child in master.children]
    if master.data.users > 1:
        master.data = master.data.copy()
    offset = mathutils.Matrix.Translation(center)
    master.data.transform(mathutils.Matrix.Translation(-center), shape_keys=True)
    master.matrix_world = master.matrix_world @ offset
    stored = _matrix_from_flat_values(master.get(CUSTOM_FACE_MASTER_BASE_MATRIX_MARKER))
    if stored is not None:
        master[CUSTOM_FACE_MASTER_BASE_MATRIX_MARKER] = _flatten_matrix(stored @ offset)
    for child, matrix in child_matrices:
        child.matrix_world = matrix
    master.data.update()


def _refresh_master_half_preview(master) -> None:
    """Rebuild an existing half-master preview around the transformed master."""

    preview_exists = bpy.data.objects.get("skin_master_half_preview_cutter") is not None
    if not preview_exists:
        preview_exists = any(
            getattr(modifier, "name", "") == "skin_master_half_preview"
            for modifier in getattr(master, "modifiers", ())
        )
    if not preview_exists:
        return
    try:
        from .direct_mold import (
            create_skin_master_half_preview,
            remove_skin_master_half_preview,
        )

        remove_skin_master_half_preview()
        create_skin_master_half_preview(master)
    except Exception:
        # The fit remains valid even when the temporary viewport preview cannot
        # be rebuilt (for example while Blender is unregistering the add-on).
        pass


def _redraw_custom_face_views() -> None:
    try:
        windows = tuple(getattr(bpy.context.window_manager, "windows", ()))
    except Exception:
        windows = ()
    for window in windows:
        for area in tuple(getattr(window.screen, "areas", ())):
            if area.type == "VIEW_3D":
                area.tag_redraw()


def apply_custom_face_master_fit(scene, *, select_master=False) -> bool:
    """Uniformly fit and align the original master around the custom head."""

    global _CUSTOM_FACE_MASTER_FIT_UPDATE_ACTIVE
    if _CUSTOM_FACE_MASTER_FIT_UPDATE_ACTIVE:
        return False

    core = bpy.data.objects.get(SKIN_CORE_NAME)
    master = _custom_face_master(scene)
    if (
        core is None
        or master is None
        or not bool(core.get(CUSTOM_FACE_CORE_MARKER, False))
        or bool(core.get(SKIN_CORE_CONFIRMED_MARKER, False))
    ):
        return False

    original_matrix = master.matrix_world.copy()
    _CUSTOM_FACE_MASTER_FIT_UPDATE_ACTIVE = True
    try:
        base_matrix = _master_base_matrix(master)
        master.matrix_world = base_matrix.copy()
        bpy.context.view_layer.update()

        core_minimum, core_maximum = _world_bounds(core)
        master_minimum, master_maximum = _world_bounds(master)
        core_volume, core_center, core_uses_mesh_volume = _world_volume_centroid(
            core
        )
        master_volume, _master_center, master_uses_mesh_volume = (
            _world_volume_centroid(master)
        )
        red_points = [point for triangle in head_triangles(core) for point in triangle]
        core_width = max(max(point.x for point in red_points) - min(point.x for point in red_points), 0.001)
        # Establish head breadth first. Neck height, shoulder width and total
        # object volume must not impose a minimum scale on the master.
        upper_cut = master_maximum.z - (master_maximum.z - master_minimum.z) * 0.5
        upper_points = [master.matrix_world @ vertex.co for vertex in master.data.vertices]
        upper_points = [point for point in upper_points if point.z >= upper_cut]
        master_width = max(max(point.x for point in upper_points) - min(point.x for point in upper_points), 0.001)
        automatic_scale = core_width / master_width
        fitted_matrix = base_matrix @ mathutils.Matrix.Diagonal(
            (automatic_scale, automatic_scale, automatic_scale, 1.0)
        )
        master.matrix_world = fitted_matrix
        bpy.context.view_layer.update()

        _, master_center, _ = _world_volume_centroid(master)
        core_head_center, core_face_anchor, core_has_face_anchor = (
            _world_head_face_landmarks(core)
        )
        master_head_center, master_face_anchor, master_has_face_anchor = (
            _world_head_face_landmarks(master)
        )
        if core_has_face_anchor and master_has_face_anchor:
            fit_translation = mathutils.Vector(
                (
                    core_head_center.x - master_head_center.x,
                    core_face_anchor.y - master_face_anchor.y,
                    core_face_anchor.z - master_face_anchor.z,
                )
            )
            placement_source = "face"
        else:
            fit_translation = core_center - master_center
            placement_source = "volume"
        master.matrix_world.translation += fit_translation
        bpy.context.view_layer.update()
        # Refine the landmark placement with scale and translation together,
        # so local shape differences do not dictate the whole master's size.
        pivot = master_head_center + fit_translation
        if core_has_face_anchor:
            pivot.z = core_face_anchor.z
        required_gap = max(float(getattr(scene, "skin_thickness", 4.0)), 0.0)
        clearance = HeadClearance(master, core, pivot)
        expansion, adjustment, gaps = clearance.fit_reference_gap(required_gap)
        master.matrix_world = (
            mathutils.Matrix.Translation(pivot + adjustment)
            @ mathutils.Matrix.Scale(expansion, 4)
            @ mathutils.Matrix.Translation(-pivot)
            @ master.matrix_world
        )
        bpy.context.view_layer.update()
        automatic_scale *= expansion
        logger.info(
            "Custom-face balanced head fit: target_gap=%.3f scale_adjustment=%.6f "
            "references=%d gap_min=%.3f gap_median=%.3f gap_max=%.3f outside=%d",
            required_gap, expansion, len(clearance.references),
            min(gaps), sorted(gaps)[len(gaps) // 2], max(gaps),
            sum(value < 0 for value in gaps),
        )
        logger.info(
            "Custom-face required landmark clearances: %s",
            ", ".join(f"{name}={gaps[index]:.3f}"
                      for name, index in clearance.landmark_indices.items()),
        )
        logger.info(
            "Custom-face rear-head clearance: references=%d minimum_gap=%.3f",
            len(clearance.rear_indices),
            min(gaps[index] for index in clearance.rear_indices),
        )
        final_master_volume, final_master_center, final_master_uses_mesh_volume = (
            _world_volume_centroid(master)
        )
        _final_master_head_center, final_master_face_anchor, final_has_face_anchor = (
            _world_head_face_landmarks(master)
        )
        volume_center_error = float((final_master_center - core_center).length)
        face_center_error = (
            float((final_master_face_anchor - core_face_anchor).length)
            if core_has_face_anchor and final_has_face_anchor
            else -1.0
        )
        logger.info(
            "Automatically fit custom-face master %s around %s: scale=%.6f "
            "core_volume=%.3f master_volume_before=%.3f "
            "master_volume_after=%.3f placement=%s "
            "face_center_error=%.6f volume_center_error=%.6f "
            "core_center=(%.3f, %.3f, %.3f) "
            "master_center_after=(%.3f, %.3f, %.3f) "
            "volume_sources=(core:%s master:%s fitted_master:%s)",
            master.name,
            core.name,
            automatic_scale,
            core_volume,
            master_volume,
            final_master_volume,
            placement_source,
            face_center_error,
            volume_center_error,
            core_center.x,
            core_center.y,
            core_center.z,
            final_master_center.x,
            final_master_center.y,
            final_master_center.z,
            "mesh" if core_uses_mesh_volume else "bounds",
            "mesh" if master_uses_mesh_volume else "bounds",
            "mesh" if final_master_uses_mesh_volume else "bounds",
        )
        _refresh_master_half_preview(master)

        if select_master:
            for selected in tuple(getattr(bpy.context, "selected_objects", ())):
                selected.select_set(False)
            master.hide_select = False
            master.hide_set(False)
            master.select_set(True)
            bpy.context.view_layer.objects.active = master
        _redraw_custom_face_views()
        return True
    except Exception:
        master.matrix_world = original_matrix
        bpy.context.view_layer.update()
        raise
    finally:
        _CUSTOM_FACE_MASTER_FIT_UPDATE_ACTIVE = False


def validate_custom_face_head_clearance(scene, core, master):
    """Check the user's final placement without changing their adjustments."""
    minimum, maximum = _world_bounds(core)
    checker = HeadClearance(master, core, (minimum + maximum) / 2.0)
    gap = max(float(getattr(scene, "skin_thickness", 4.0)), 0.0)
    measured = checker.reference_gaps()
    failed = [name.replace("_", " ") for name, index in checker.landmark_indices.items()
              if measured[index] < gap]
    if any(measured[index] < gap for index in checker.rear_indices):
        failed.append("back of head")
    if failed:
        raise RuntimeError(
            f"At least {gap:g} mm clearance is required at: {', '.join(failed)}. "
            "Adjust the master before confirming."
        )
    gaps = sorted(measured)
    # Every sampled red-head point must remain inside after manual edits.
    if min(gaps) < 0:
        raise RuntimeError(
            "Some head references are outside the master. Adjust the master "
            f"toward the {gap:g} mm Skin Thickness clearance; "
            "the neck is excluded."
        )


def _finish_create_custom_face_core(context, source, geometry):
    """Create Blender geometry after the licensed worker request completes."""

    previous = bpy.data.objects.get(SKIN_CORE_NAME)
    if previous is not None:
        previous_mesh = getattr(previous, "data", None)
        bpy.data.objects.remove(previous, do_unlink=True)
        if previous_mesh is not None and getattr(previous_mesh, "users", 0) == 0:
            bpy.data.meshes.remove(previous_mesh)

    initialize_custom_face_dimensions(context.scene, source)
    minimum, maximum = _world_bounds(source)
    center = (minimum + maximum) / 2.0
    mesh = bpy.data.meshes.new(f"{SKIN_CORE_NAME}_mesh")
    core = bpy.data.objects.new(SKIN_CORE_NAME, mesh)
    context.scene.collection.objects.link(core)
    core.location = center
    core[SKIN_CORE_MARKER] = True
    core[CUSTOM_FACE_CORE_MARKER] = True
    core[CUSTOM_FACE_CORE_BASES_DIRTY_MARKER] = True
    core[CUSTOM_FACE_CORE_LOCATION_MARKER] = [float(value) for value in center]
    dimensions = custom_face_dimensions(context.scene)
    _replace_mesh_geometry(core, dimensions, geometry=geometry, neck=neck_settings(context.scene, dimensions))

    for selected in tuple(getattr(context, "selected_objects", ())):
        selected.select_set(False)
    core.hide_set(False)
    core.select_set(True)
    context.view_layer.objects.active = core
    context.view_layer.update()
    apply_custom_face_master_fit(context.scene, select_master=True)
    return core


def begin_create_custom_face_core(context, source):
    """Begin default head generation while leaving Blender responsive."""

    if not ENABLE_CUSTOM_FACE_CORE:
        raise RuntimeError("Custom Face Core is still in development")
    return begin_custom_face_core_geometry(DEFAULT_FACE_DIMENSIONS).then(
        lambda geometry: _finish_create_custom_face_core(
            context,
            source,
            geometry,
        )
    )


def create_custom_face_core(context, source):
    """Synchronously create the default adjustable head for legacy callers."""

    if not ENABLE_CUSTOM_FACE_CORE:
        raise RuntimeError("Custom Face Core is still in development")

    # Complete the licensed request before replacing any existing scene object.
    geometry = acquire_geometry_worker().custom_face_core(DEFAULT_FACE_DIMENSIONS)
    return _finish_create_custom_face_core(context, source, geometry)


def update_custom_face_core_from_scene(scene) -> bool:
    """Rebuild the live head after a panel edit, preserving manual placement."""

    if not ENABLE_CUSTOM_FACE_CORE:
        return False

    core = bpy.data.objects.get(SKIN_CORE_NAME)
    if (
        core is None
        or not bool(core.get(CUSTOM_FACE_CORE_MARKER, False))
        or bool(core.get(SKIN_CORE_CONFIRMED_MARKER, False))
    ):
        return False
    dimensions = custom_face_dimensions(scene)
    _replace_mesh_geometry(core, dimensions, neck=neck_settings(scene, dimensions))
    core[CUSTOM_FACE_CORE_BASES_DIRTY_MARKER] = True
    try:
        bpy.context.view_layer.update()
    except Exception:
        pass
    _redraw_custom_face_views()
    return True
