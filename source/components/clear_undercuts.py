"""Fast, non-destructive undercut extraction from a virtual split plane."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import Optional

import bpy  # type: ignore
import mathutils  # type: ignore

try:
    import numpy as np  # type: ignore
except ImportError:  # Blender normally bundles NumPy; retain a Python fallback.
    np = None

from ..background_worker import (
    BackgroundTaskSequence,
    finish_task_sync,
    submit_worker_task,
)
from ..modifiers import build_voxel_modifier
from ..nearest_surface_worker_client import NearestSurfaceWorkerError
from ..object import Object
from .clear_undercuts_hybrid import begin_worker_server_request_config
from .clear_undercuts_overlay import (
    display_worker_extraction_direction_arrows,
)
from .geometry_adapter import acquire_geometry_worker
from .server import AuthorizationError, ServerConnectionError

_DISTANCE_EPSILON = 1e-6
_NORMAL_EPSILON = 1e-6
_UNDERCUT_SPLIT_PLANE_OVERTRAVEL = 1.5
_UNDERCUT_SPLIT_PLANE_VOXEL_FACTOR = 1.0
_UNDERCUT_SECTION_EXPANSION = 1.5
_UNDERCUT_SECTION_EXPANSION_VOXEL_FACTOR = 1.0
_UI_REFRESH_INTERVAL = 0.05
_VERTICAL_SPLIT_PLANE_Z_TOLERANCE = 1e-6
_PRECISE_COST_RAY_EPSILON = 1e-5
_PRECISE_COST_MAX_RAY_HITS = 256
logger = logging.getLogger(__name__)


def _worker_path_cost_metrics(path, *, locked: bool) -> tuple[float, float]:
    """Read planner scores; locked replays have routing but no fresh scores."""

    if locked:
        return (
            float(path.get("affected_area", 0.0)),
            float(path.get("swept_volume", 0.0)),
        )
    return float(path["affected_area"]), float(path["swept_volume"])


def _worker_plane_arrays(planes):
    if not planes:
        raise ValueError("at least one undercut projection plane is required")
    return (
        np.ascontiguousarray(
            [tuple(point) for point, _normal in planes], dtype=np.float32
        ),
        np.ascontiguousarray(
            [tuple(normal) for _point, normal in planes], dtype=np.float32
        ),
    )


def _mesh_polygon_arrays(source_mesh, world_matrix):
    """Extract an indexed polygon mesh and transform it to world float32."""

    vertices = np.empty((len(source_mesh.vertices), 3), dtype=np.float32)
    source_mesh.vertices.foreach_get("co", vertices.ravel())
    matrix = np.asarray(world_matrix, dtype=np.float32)
    homogeneous = np.ones((len(vertices), 4), dtype=np.float32)
    homogeneous[:, :3] = vertices
    world_vertices = np.ascontiguousarray(
        np.einsum("ij,kj->ik", homogeneous, matrix[:3], optimize=True),
        dtype=np.float32,
    )
    face_offsets = np.empty(len(source_mesh.polygons) + 1, dtype=np.int32)
    face_offsets[0] = 0
    if source_mesh.polygons:
        loop_starts = np.empty(len(source_mesh.polygons), dtype=np.int32)
        loop_totals = np.empty(len(source_mesh.polygons), dtype=np.int32)
        source_mesh.polygons.foreach_get("loop_start", loop_starts)
        source_mesh.polygons.foreach_get("loop_total", loop_totals)
        face_offsets[:-1] = loop_starts
        face_offsets[-1] = int(loop_starts[-1] + loop_totals[-1])
    face_indices = np.empty(len(source_mesh.loops), dtype=np.int32)
    source_mesh.loops.foreach_get("vertex_index", face_indices)
    return world_vertices, face_offsets, face_indices


def _mesh_triangle_indices(source_mesh):
    source_mesh.calc_loop_triangles()
    triangles = np.empty((len(source_mesh.loop_triangles), 3), dtype=np.int32)
    source_mesh.loop_triangles.foreach_get("vertices", triangles.ravel())
    return triangles


def _mesh_from_worker_polygon_result(name: str, result):
    """Create a Blender mesh from the packed worker ABI without Python faces."""

    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(len(result.vertices))
    if len(result.vertices):
        mesh.vertices.foreach_set("co", result.vertices.ravel())
    mesh.loops.add(len(result.face_indices))
    if len(result.face_indices):
        mesh.loops.foreach_set("vertex_index", result.face_indices)
    face_count = len(result.face_offsets) - 1
    mesh.polygons.add(face_count)
    if face_count:
        mesh.polygons.foreach_set("loop_start", result.face_offsets[:-1])
        mesh.polygons.foreach_set(
            "loop_total", np.diff(result.face_offsets).astype(np.int32)
        )
    mesh.update(calc_edges=True)
    return mesh


def vertical_split_plane_specs(
    split_plane_specs: Optional[list[list[list[float]]]],
    z_tolerance: float = _VERTICAL_SPLIT_PLANE_Z_TOLERANCE,
) -> list[list[list[float]]]:
    """Return clearance copies of planes whose normals are horizontal.

    A geometrically vertical plane has no Z component in its normal. Tiny Z
    components within ``z_tolerance`` are treated as transform noise and
    removed from the returned clearance-only copy.
    """
    result = acquire_geometry_worker().geometry_policy(
        "vertical_split_planes",
        specs=split_plane_specs or [],
        z_tolerance=float(z_tolerance),
    )
    return result["planes"]


def inner_core_undercut_plane_specs(
    target_object: Object,
    split_plane_specs: Optional[list[list[list[float]]]],
) -> list[list[list[float]]]:
    """Resolve horizontal-only undercut planes for an inner-core mold.

    The center-X fallback is virtual: callers use this returned collection only
    for local undercut clearance and must keep the original split-plane
    collection for server payloads and physical mold splitting.
    """
    vertical_planes = vertical_split_plane_specs(split_plane_specs)
    if vertical_planes:
        return vertical_planes

    target = (
        target_object
        if isinstance(target_object, Object)
        else Object(target_object)
    )
    center = target.center_coords
    return [
        [
            [float(center.x), float(center.y), float(center.z)],
            [1.0, 0.0, 0.0],
        ]
    ]


def bottom_reference_plane(target_object: Object) -> list[list[float]]:
    """Return the upward-facing reference plane at an object's world min Z."""
    target = (
        target_object
        if isinstance(target_object, Object)
        else Object(target_object)
    )
    center = target.center_coords
    return [
        [float(center.x), float(center.y), float(target.min_z)],
        [0.0, 0.0, 1.0],
    ]


def _clear_undercuts_steps(
    target_object: Object,
    bidirectional: bool,
    voxel_size: float = 0.4,
    target_retry_voxel_size: Optional[float] = None,
    target_point: mathutils.Vector = mathutils.Vector((0, 0, 0)),
    plane_direction: mathutils.Vector = mathutils.Vector((1, 0, 0)),
    progress_callback: Optional[Callable[[str], None]] = None,
    split_plane_specs: Optional[list[list[list[float]]]] = None,
    boundary_plane_specs: Optional[list[list[list[float]]]] = None,
    ui_refresh_callback: Optional[Callable[[], None]] = None,
    temporary_analysis_object: Optional[Object] = None,
    local_sections_only: bool = False,
    easy_extraction: bool = False,
    precise_cost: bool = False,
    restrict_bottom_extraction: bool = True,
    restrict_bottom_vertical_extraction: bool = False,
    horizontal_extraction: bool = False,
    mid_horizontal_extraction: bool = False,
    split_plane_overtravel_override: Optional[float] = None,
    split_plane_overtravel_offset: float = 0.0,
    clearance_build_overtravel_override: Optional[float] = None,
    selected_paths_out: Optional[dict] = None,
    locked_extraction_paths: Optional[dict] = None,
    display_extraction_directions: bool = True,
    planning_only: bool = False,
    preview_faces_out: Optional[dict] = None,
    before_target_join: Optional[Callable[[Object], None]] = None,
    after_target_remesh: Optional[Callable[[Object], None]] = None,
    join_target: bool = True,
    remesh_target_after_join: bool = True,
    smooth_target_after_remesh: bool = True,
    normal_angle_threshold_degrees: Optional[float] = None,
    minimum_undercut_island_area: float = 0.0,
    face_limit_plane_spec: Optional[list[list[float]]] = None,
) -> Optional[Object]:
    """Extract the target's undercut faces as a new, closed mesh object.

    When ``split_plane_specs`` contains one or more ``[point, normal]`` pairs,
    the mesh is divided into the sections made by those planes. Every section
    evaluates the split planes that actually border it and uses one extraction
    direction for the whole section. Silicone sections evaluate both the
    axis-perpendicular directions and stable directions inside the cone formed by
    pairs of bordering planes. Candidate paths traverse a cached contact graph.
    When a direct exit exists, transit paths are discarded before local geometry
    worker scoring. If every allowed direction crosses another section, only the
    selected winner lazily adds the original geometry of its passing sections
    to its own clearance. Expansion remains an analytical clearance margin and
    does not create extra topology cuts around each plane.

    The protected worker requests candidate directions from section signs,
    touched-plane IDs, and plane normals, scores them against its retained
    analysis faces, and sends only aggregate measurements for final server
    selection. No patron face or vertex data is included in either request.
    Blender sends the original indexed mesh once. The worker splits and
    classifies its sections, retains that topology for planning, and passes the
    selected dependency order directly to the compiled clearance builder. Split
    topology never returns through Blender. Direct exits
    generate only from their owning section. When a selected path crosses other
    sections, the source section classifies their original geometry with its own
    frozen direction and sweeps it to the source's final anchor. Saver faces
    which enter a following section are also added to that section's locked
    generation without reopening its path search. Production construction has
    no Blender fallback: a worker construction error stops the operation.

    ``boundary_plane_specs`` adds reference planes which may lie on the mesh
    boundary instead of dividing it. They are extraction candidates only for
    sections that physically touch them. For a normal silicone adapted box,
    every section touching the bottom boundary is restricted to extraction with
    a nonnegative world-Z component, whether or not a real horizontal split
    plane also touches it. Sections that do not touch the bottom are unaffected.

    Without either plane-spec collection, ``target_point`` and
    ``plane_direction`` retain the single-plane behavior.
    ``plane_direction`` is the extraction direction for geometry on the
    positive side, and ``bidirectional`` enables the reversed negative-side
    direction.

    A face is an undercut when its world-space normal opposes its side's
    extraction direction.  Each selected face is copied without changing the
    source mesh data, offset 0.2 mm opposite the extrusion direction, and
    swept back to the selected anchor plane along its extraction direction, then
    extended beyond it by at least 1.5 mm or one remesh voxel. Adjacent selected
    faces share generated vertices and internal walls are omitted.

    The analytical solid is joined into the target and the combined target is
    voxel-remeshed at ``target_retry_voxel_size``.

    The function accepts either the project's :class:`Object` wrapper or a raw
    Blender mesh object. ``None`` is returned when no undercut faces exist on
    the requested side or sides. ``ui_refresh_callback``, when supplied, is
    called at throttled checkpoints inside the expensive Python loops so a
    modal caller can keep Blender's viewport drawing.

    When ``temporary_analysis_object`` is supplied, undercut faces and swept
    geometry are generated from that object while the completed undercut mesh
    is still joined into ``target_object``. The temporary object is deleted as
    soon as the independent undercut mesh has been created.

    ``local_sections_only`` preserves the direct-mold behavior from before
    neighboring saver propagation was introduced. Each split section is scored
    once using only its own faces, analytical section expansion and split-plane
    overtravel are disabled, and generated saver faces are not fed into later
    sections. The default retains the sequential neighboring-section behavior
    used by silicone molds.

    ``precise_cost`` retains unrestricted candidate directions and changes only
    their worker-side cost estimate. Each affected face-center ray counts sweep
    distance only while it is outside the model; final clearance generation
    still uses the complete selected analytical path.

    ``easy_extraction`` keeps every silicone direction either purely lateral
    or exactly +Z. Lateral cone candidates are formed only from vertical split
    planes; the bottom reference remains an independent upward candidate and
    is never blended into an upward diagonal. Optimized mode retains the full
    conic candidate set. The Easy restriction is section-local: if any real
    split plane touching a section is nonvertical, that section retains the
    full Optimized candidates instead. The bottom reference is not considered
    a real split plane for this exception.

    ``restrict_bottom_extraction`` controls the silicone-specific world-Z rule.
    Every bottom-touching section in a normal silicone adapted box must extract
    with a nonnegative world-Z component, including when real split planes also
    touch that section. Direct molds disable this only in Optimized mode so
    their full conic search has no special directional restriction.

    ``horizontal_extraction`` limits all candidate directions to world Z = 0
    while retaining their normal scoring and route selection.

    ``restrict_bottom_vertical_extraction`` additionally forces bottom-touching
    sections to extract laterally (Z = 0).
    Silicone molds enable this for the optimized base so its bottom sections
    cannot clear vertically through the compact base. The optimized-base
    settings guard separately guarantees at least one real vertical split
    plane. Normal silicone bases may have no split planes and always extract
    bottom-touching sections with nonnegative world Z.

    ``split_plane_overtravel_override`` replaces the normal 1.5 mm/one-voxel
    projection beyond split planes without changing analytical section
    expansion. Direct molds pass zero so their analysis and saver propagation
    end at the extraction boundary; silicone molds retain the default margin.

    ``split_plane_overtravel_offset`` is added after resolving the normal or
    overridden distance. Silicone funnels use it to overlap 0.5 mm farther
    than their box without changing the box clearance itself.

    ``clearance_build_overtravel_override`` changes only the final clearance
    solid. Candidate scoring, section analysis, and saver-face propagation keep
    using ``split_plane_overtravel``. Direct molds use this for a 0.25 mm build
    overlap without passing that margin into neighboring sections or funnels.

    ``selected_paths_out`` receives the frozen section paths chosen during the
    normal box pass. Supplying those records later through
    ``locked_extraction_paths`` reuses the exact directions and generation
    order without requesting or selecting a second set of candidates. This is
    used for server-generated funnel geometry belonging to the same sections.

    ``planning_only`` stops immediately after selecting and optionally storing
    the frozen section paths. It never builds clearance geometry or modifies
    the target, allowing a Direct master to provide funnel directions even
    when Clear Undercuts was not previously applied to that master.

    ``preview_faces_out`` optionally receives the worker's affected original
    surface mesh during a planning-only pass. It contains no swept geometry
    and does not modify the target. Callers may draw it as a viewport overlay.

    ``before_target_join`` runs only when clearance geometry exists, immediately
    before that geometry is joined into the target. ``after_target_remesh`` runs
    after the combined target has been remeshed and, when enabled, smoothed.
    These hooks let a caller protect temporary boundary geometry without
    changing the mesh used for undercut analysis.

    ``join_target=False`` returns the separate clearance object for dev inspection,
    without joining or remeshing the target.

    ``remesh_target_after_join`` disables the final target remesh and leaves the
    generated clearance joined with its analytical topology. When disabled,
    smoothing and ``after_target_remesh`` are skipped as well.

    ``smooth_target_after_remesh`` disables the final vertex-smoothing pass for
    callers that need to preserve the voxel-remeshed clearance shape.

    ``normal_angle_threshold_degrees`` optionally restricts single-plane
    clearing to face islands whose normals are within that angle of the exact
    direction opposing extraction. A 30 degree threshold, for example, keeps
    strongly downward-facing islands while ignoring shallow slopes.

    ``minimum_undercut_island_area`` optionally ignores smaller edge-connected
    face islands after that direction filter. Its unit is the target
    mesh's squared world unit.

    ``face_limit_plane_spec`` optionally restricts single-plane
    classification to face centers on or below the negative side of its
    ``[point, normal]`` plane. It does not perform the final geometry cut.
    """
    total_start = time.perf_counter()
    last_ui_refresh_at = 0.0
    if selected_paths_out is not None:
        selected_paths_out.clear()

    def report_progress(label: str) -> None:
        if progress_callback is not None:
            progress_callback(label)

    def refresh_ui(force: bool = False) -> None:
        nonlocal last_ui_refresh_at
        if ui_refresh_callback is None:
            return
        now = time.perf_counter()
        if not force and now - last_ui_refresh_at < _UI_REFRESH_INTERVAL:
            return
        last_ui_refresh_at = now
        ui_refresh_callback()

    def redraw_checkpoint(label: str) -> None:
        report_progress(label)
        refresh_ui(force=True)

    voxel_size = float(voxel_size)
    if voxel_size <= 0:
        raise ValueError("voxel_size must be greater than zero")
    if precise_cost and easy_extraction:
        raise ValueError(
            "precise_cost and easy_extraction are mutually exclusive"
        )
    target_retry_voxel_size = float(
        voxel_size if target_retry_voxel_size is None else target_retry_voxel_size
    )
    if target_retry_voxel_size <= 0:
        raise ValueError("target_retry_voxel_size must be greater than zero")
    normal_dot_threshold = -_NORMAL_EPSILON
    if normal_angle_threshold_degrees is not None:
        angle_threshold = float(normal_angle_threshold_degrees)
        if angle_threshold < 0.0 or angle_threshold > 90.0:
            raise ValueError(
                "normal_angle_threshold_degrees must be between 0 and 90"
            )
        normal_dot_threshold = -math.cos(math.radians(angle_threshold))
    minimum_undercut_island_area = float(minimum_undercut_island_area)
    if minimum_undercut_island_area < 0.0:
        raise ValueError("minimum_undercut_island_area must not be negative")
    face_limit_plane = None
    if face_limit_plane_spec is not None:
        try:
            face_limit_point = mathutils.Vector(face_limit_plane_spec[0])
            face_limit_normal = mathutils.Vector(face_limit_plane_spec[1])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "face_limit_plane_spec must contain [point, normal]"
            ) from exc
        if (
            face_limit_normal.length_squared
            <= _NORMAL_EPSILON * _NORMAL_EPSILON
        ):
            raise ValueError("face_limit_plane_spec normal must not be zero")
        face_limit_normal.normalize()
        face_limit_plane = (face_limit_point, face_limit_normal)
    if (
        split_plane_overtravel_override is not None
        and float(split_plane_overtravel_override) < 0.0
    ):
        raise ValueError("split_plane_overtravel_override must not be negative")
    if float(split_plane_overtravel_offset) < 0.0:
        raise ValueError("split_plane_overtravel_offset must not be negative")
    if (
        clearance_build_overtravel_override is not None
        and float(clearance_build_overtravel_override) < 0.0
    ):
        raise ValueError(
            "clearance_build_overtravel_override must not be negative"
        )
    setup = yield submit_worker_task(
        acquire_geometry_worker().geometry_policy,
        "clear_undercut_setup",
        requested_specs=split_plane_specs or [],
        boundary_specs=boundary_plane_specs or [],
        margin_arguments={
            "remesh_voxel_size": float(target_retry_voxel_size),
            "local_sections_only": bool(local_sections_only),
            "overtravel_override": (
                None
                if split_plane_overtravel_override is None
                else float(split_plane_overtravel_override)
            ),
            "overtravel_offset": float(split_plane_overtravel_offset),
            "build_overtravel_override": (
                None
                if clearance_build_overtravel_override is None
                else float(clearance_build_overtravel_override)
            ),
            "minimum_overtravel": _UNDERCUT_SPLIT_PLANE_OVERTRAVEL,
            "overtravel_voxel_factor": _UNDERCUT_SPLIT_PLANE_VOXEL_FACTOR,
            "minimum_expansion": _UNDERCUT_SECTION_EXPANSION,
            "expansion_voxel_factor": _UNDERCUT_SECTION_EXPANSION_VOXEL_FACTOR,
        },
    )
    margin_policy = setup["margins"]
    split_plane_overtravel = float(margin_policy["split_plane_overtravel"])
    clearance_build_overtravel = float(
        margin_policy["clearance_build_overtravel"]
    )
    section_analysis_expansion = float(
        margin_policy["section_analysis_expansion"]
    )

    split_point = mathutils.Vector(target_point)
    split_normal = mathutils.Vector(plane_direction)
    if split_normal.length_squared <= _DISTANCE_EPSILON * _DISTANCE_EPSILON:
        raise ValueError("plane_direction must not be a zero vector")
    split_normal.normalize()

    target_raw_object = getattr(target_object, "object", target_object)
    source_object = getattr(
        temporary_analysis_object,
        "object",
        temporary_analysis_object,
    )
    if source_object is None:
        source_object = target_raw_object
    if source_object is None or getattr(source_object, "type", None) != "MESH":
        raise TypeError("target_object must be a Blender mesh object")
    if (
        target_raw_object is None
        or getattr(target_raw_object, "type", None) != "MESH"
    ):
        raise TypeError("target_object must be a Blender mesh object")
    remove_analysis_object = source_object is not target_raw_object

    def cleanup_analysis_object() -> None:
        nonlocal remove_analysis_object
        if not remove_analysis_object:
            return
        remove_analysis_object = False
        analysis_mesh = getattr(source_object, "data", None)
        try:
            if source_object.name in bpy.data.objects:
                bpy.data.objects.remove(source_object, do_unlink=True)
        except ReferenceError:
            pass
        if (
            analysis_mesh is not None
            and getattr(analysis_mesh, "users", 0) == 0
            and analysis_mesh.name in bpy.data.meshes
        ):
            bpy.data.meshes.remove(analysis_mesh)

    source_mesh = source_object.data
    if not source_mesh.polygons:
        cleanup_analysis_object()
        return None

    world_matrix = source_object.matrix_world
    try:
        world_matrix.inverted()
    except ValueError as exc:
        raise ValueError(
            "target_object must have an invertible world transform"
        ) from exc

    requested_split_planes = [
        (mathutils.Vector(point), mathutils.Vector(normal))
        for point, normal in setup["requested_planes"]
    ]
    boundary_split_planes = [
        (mathutils.Vector(point), mathutils.Vector(normal))
        for point, normal in setup["boundary_planes"]
    ]
    candidate_split_planes = requested_split_planes + boundary_split_planes
    analysis_split_planes = candidate_split_planes or [(split_point, split_normal)]
    section_plane_count = (
        len(requested_split_planes)
        if candidate_split_planes
        else len(analysis_split_planes)
    )

    redraw_checkpoint("Preparing split sections")
    phase_start = time.perf_counter()
    geometry_worker = acquire_geometry_worker()
    source_vertices = None
    source_face_offsets = None
    source_face_indices = None

    def ensure_source_mesh_arrays():
        nonlocal source_vertices, source_face_offsets, source_face_indices
        if source_vertices is None:
            (
                source_vertices,
                source_face_offsets,
                source_face_indices,
            ) = _mesh_polygon_arrays(source_mesh, world_matrix)
        return source_vertices, source_face_offsets, source_face_indices
    fused_single_plane_result = None
    fused_multi_plane_result = None
    fused_worker_result = None
    if horizontal_extraction and locked_extraction_paths:
        # Replan stale saved paths; flattening a winner would invalidate its
        # score, transit route and dependent sections.
        try:
            needs_replan = any(float(path["direction"][2]) != 0.0
                               for path in locked_extraction_paths.values())
        except (KeyError, TypeError, ValueError, IndexError):
            needs_replan = True
        if needs_replan:
            locked_extraction_paths = None
    if candidate_split_planes and locked_extraction_paths is None:
        analysis_plane_points, analysis_plane_normals = _worker_plane_arrays(
            analysis_split_planes
        )
        boundary_plane_indices = set(
            range(len(requested_split_planes), len(candidate_split_planes))
        )
        try:
            ensure_source_mesh_arrays()
            redraw_checkpoint("Splitting and building undercuts in worker")
            refresh_ui(force=True)
            server_request_config = yield begin_worker_server_request_config()
            fused_worker_result = (
                yield submit_worker_task(
                    geometry_worker.split_plan_and_build_undercuts,
                    source_vertices,
                    source_face_offsets,
                    source_face_indices,
                    plane_points=analysis_plane_points,
                    plane_normals=analysis_plane_normals,
                    section_plane_count=section_plane_count,
                    server_request_config=server_request_config,
                    requested_plane_count=len(requested_split_planes),
                    boundary_plane_indices=boundary_plane_indices,
                    local_sections_only=local_sections_only,
                    easy_extraction=easy_extraction,
                    horizontal_extraction=horizontal_extraction,
                    mid_horizontal_extraction=mid_horizontal_extraction,
                    restrict_bottom_extraction=restrict_bottom_extraction,
                    restrict_bottom_vertical_extraction=(
                        restrict_bottom_vertical_extraction
                    ),
                    split_overtravel=split_plane_overtravel,
                    clearance_overtravel=clearance_build_overtravel,
                    precise_cost=precise_cost,
                    ray_target_triangles=(
                        _mesh_triangle_indices(source_mesh)
                        if precise_cost
                        else None
                    ),
                    ray_epsilon=_PRECISE_COST_RAY_EPSILON,
                    ray_max_hits=_PRECISE_COST_MAX_RAY_HITS,
                    planning_only=planning_only,
                    preview_faces=preview_faces_out is not None,
                )
            )
        except NearestSurfaceWorkerError as error:
            message = str(error)
            normalized_message = message.casefold()
            if (
                "unauthorized" in normalized_message
                or "access token" in normalized_message
                or "log in again" in normalized_message
            ):
                raise AuthorizationError(message) from error
            if "connection error" in normalized_message:
                raise ServerConnectionError(message) from error
            raise
        analyzed_face_count = fused_worker_result.analyzed_face_count
        fused_multi_plane_result = (
            None if planning_only else fused_worker_result.mesh
        )
    elif candidate_split_planes:
        analysis_plane_points, analysis_plane_normals = _worker_plane_arrays(
            analysis_split_planes
        )
        ensure_source_mesh_arrays()
        locked_worker_paths = []
        for section, path in locked_extraction_paths.items():
            if not isinstance(path, dict):
                continue
            try:
                section_values = [int(side) for side in section]
                plane_index = int(path["plane_index"])
                direction = mathutils.Vector(path["direction"])
                projection_indices = [
                    int(value)
                    for value in path["projection_plane_indices"]
                ]
                route_sections = [
                    [int(side) for side in route]
                    for route in path["path_sections"]
                ]
                order = int(path["order"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                len(section_values) != len(analysis_split_planes)
                or not 0 <= plane_index < len(analysis_split_planes)
                or direction.length_squared
                <= _DISTANCE_EPSILON * _DISTANCE_EPSILON
                or not projection_indices
                or any(
                    index < 0 or index >= len(analysis_split_planes)
                    for index in projection_indices
                )
                or any(
                    len(route) != len(analysis_split_planes)
                    for route in route_sections
                )
            ):
                continue
            direction.normalize()
            locked_worker_paths.append(
                {
                    "section": section_values,
                    "plane_index": plane_index,
                    "side": section_values[plane_index],
                    "direction": list(direction),
                    "projection_plane_indices": projection_indices,
                    "path_sections": route_sections or [section_values],
                    "order": order,
                }
            )
        fused_worker_result = (
            yield submit_worker_task(
                geometry_worker.split_and_build_locked_undercuts,
                source_vertices,
                source_face_offsets,
                source_face_indices,
                plane_points=analysis_plane_points,
                plane_normals=analysis_plane_normals,
                section_plane_count=section_plane_count,
                selected_paths=locked_worker_paths,
                split_overtravel=split_plane_overtravel,
                clearance_overtravel=clearance_build_overtravel,
                local_sections_only=local_sections_only,
            )
        )
        fused_multi_plane_result = fused_worker_result.mesh
        analyzed_face_count = fused_worker_result.analyzed_face_count
    else:
        ensure_source_mesh_arrays()
        face_limit_point, face_limit_normal = (
            face_limit_plane if face_limit_plane is not None else (None, None)
        )
        fused_single_plane_result = (
            yield submit_worker_task(
                geometry_worker.build_single_plane_undercut_mesh,
                source_vertices,
                source_face_offsets,
                source_face_indices,
                split_point=tuple(split_point),
                split_normal=tuple(split_normal),
                bidirectional=bidirectional,
                normal_dot_threshold=normal_dot_threshold,
                overtravel=clearance_build_overtravel,
                face_limit_point=(
                    None
                    if face_limit_point is None
                    else tuple(face_limit_point)
                ),
                face_limit_normal=(
                    None
                    if face_limit_normal is None
                    else tuple(face_limit_normal)
                ),
                minimum_area=minimum_undercut_island_area,
            )
        )
        analyzed_face_count = len(source_mesh.polygons)
    logger.debug(
        "Clear undercuts split analysis mesh: source_faces=%d analyzed_faces=%d "
        "planes=%d preclassified_plan=%s section_expansion=%.6f elapsed=%.3fs",
        len(source_mesh.polygons),
        analyzed_face_count,
        len(analysis_split_planes),
        fused_worker_result is not None,
        section_analysis_expansion if candidate_split_planes else 0.0,
        time.perf_counter() - phase_start,
    )

    if planning_only and not candidate_split_planes:
        cleanup_analysis_object()
        raise ValueError("planning_only requires at least one split plane")

    if fused_single_plane_result is not None:
        logger.debug(
            "Clear undercuts fused single-plane geometry: vertices=%d faces=%d",
            len(fused_single_plane_result.vertices),
            len(fused_single_plane_result.face_offsets) - 1,
        )
    else:
        extraction_plane_indices_by_section = {}
        initial_candidates = {}
        sequential_sections = []
        for path in fused_worker_result.selected_paths:
            section = tuple(int(side) for side in path["section"])
            plane_index = int(path["plane_index"])
            if not 0 <= plane_index < len(candidate_split_planes):
                raise RuntimeError(
                    "Worker returned an incompatible extraction path"
                )
            path_sections = [
                tuple(int(side) for side in value)
                for value in path["path_sections"]
            ]
            extraction_direction = mathutils.Vector(path["direction"])
            candidate_point, candidate_normal = candidate_split_planes[
                plane_index
            ]
            affected_area, swept_volume = _worker_path_cost_metrics(
                path,
                locked=locked_extraction_paths is not None,
            )
            extraction_plane_indices_by_section[section] = [
                int(index) for index in path["projection_plane_indices"]
            ]
            initial_candidates[section] = (
                None,
                plane_index,
                int(path["side"]),
                candidate_point,
                candidate_normal,
                extraction_direction,
                [],
                affected_area,
                swept_volume,
                path_sections,
            )
            sequential_sections.append(section)

        if selected_paths_out is not None:
            for order, section in enumerate(sequential_sections):
                candidate = initial_candidates[section]
                selected_paths_out[section] = {
                    "plane_index": int(candidate[1]),
                    "direction": tuple(float(value) for value in candidate[5]),
                    "projection_plane_indices": tuple(
                        extraction_plane_indices_by_section[section]
                    ),
                    "path_sections": tuple(candidate[9]),
                    "order": order,
                }

        if display_extraction_directions:
            display_worker_extraction_direction_arrows(
                fused_worker_result.selected_paths
            )

        if planning_only:
            if preview_faces_out is not None:
                preview_faces_out["mesh"] = fused_worker_result.mesh
                preview_faces_out["selected_paths"] = fused_worker_result.selected_paths
            cleanup_analysis_object()
            logger.info(
                "Clear undercuts planning completed without geometry generation "
                "in %.3fs: sections=%d",
                time.perf_counter() - total_start,
                len(initial_candidates),
            )
            return None

        unresolved_dependency_sections = list(
            fused_worker_result.unresolved_sections
        )
        if unresolved_dependency_sections:
            logger.warning(
                "Clear undercuts frozen paths contain cyclic dependencies; "
                "worker used deterministic generation order for sections=%s",
                unresolved_dependency_sections,
            )

    packed_worker_result = (
        fused_single_plane_result
        if fused_single_plane_result is not None
        else fused_multi_plane_result
    )
    fused_face_count = len(packed_worker_result.face_offsets) - 1
    if not fused_face_count:
        logger.debug(
            "Clear undercuts completed without extracted faces in %.3fs",
            time.perf_counter() - total_start,
        )
        cleanup_analysis_object()
        return None

    logger.debug(
        "Clear undercuts worker geometry: vertices=%d faces=%d",
        len(packed_worker_result.vertices),
        fused_face_count,
    )

    redraw_checkpoint("Creating undercut mesh")
    phase_start = time.perf_counter()
    suffix = "_item" if target_raw_object.name.startswith(("cast_", "_cast_")) else "_undercuts"
    result_name = f"{target_raw_object.name}{suffix}"
    result_mesh = _mesh_from_worker_polygon_result(
        f"{result_name}_mesh", packed_worker_result
    )
    result_object = bpy.data.objects.new(result_name, result_mesh)
    if target_raw_object.users_collection:
        target_raw_object.users_collection[0].objects.link(result_object)
    else:
        bpy.context.collection.objects.link(result_object)
    cleanup_analysis_object()
    refresh_ui(force=True)
    logger.debug(
        "Clear undercuts mesh creation and linking: elapsed=%.3fs",
        time.perf_counter() - phase_start,
    )

    undercuts = Object(result_object)
    undercuts.hide_during_ui_breathe = bool(
        getattr(target_object, "hide_during_ui_breathe", False)
    )
    # Preserve caller-owned runtime flags such as hide_during_ui_breathe.
    target = (
        target_object
        if isinstance(target_object, Object)
        else Object(target_raw_object)
    )

    logger.info(
        "Clear undercuts finalization: target=%s input_vertices=%d input_faces=%d "
        "clearance_vertices=%d clearance_faces=%d voxel_size=%.6f "
        "remesh=%s smoothing=%s smoothing_factor=%.3f smoothing_passes=%d",
        target_raw_object.name, len(target_raw_object.data.vertices), len(target_raw_object.data.polygons),
        len(result_mesh.vertices), len(result_mesh.polygons), target_retry_voxel_size,
        remesh_target_after_join, smooth_target_after_remesh and remesh_target_after_join,
        0.5 if smooth_target_after_remesh and remesh_target_after_join else 0.0,
        5 if smooth_target_after_remesh and remesh_target_after_join else 0,
    )

    if not join_target:
        return undercuts

    redraw_checkpoint("Joining undercuts into target")
    phase_start = time.perf_counter()
    if before_target_join is not None:
        before_target_join(target)
    target.join(undercuts)
    join_elapsed = time.perf_counter() - phase_start

    remesh_elapsed = 0.0
    smooth_elapsed = 0.0
    if remesh_target_after_join:
        redraw_checkpoint("Remeshing target with undercuts")
        remesh_start = time.perf_counter()
        target.apply_modifier(build_voxel_modifier(target_retry_voxel_size))
        remesh_elapsed = time.perf_counter() - remesh_start
        if smooth_target_after_remesh:
            redraw_checkpoint("Smoothing remeshed target")
            smooth_start = time.perf_counter()
            target.smooth_geometry(factor=0.5, repeat=5)
            smooth_elapsed = time.perf_counter() - smooth_start
        if after_target_remesh is not None:
            redraw_checkpoint("Restoring target boundary after remesh")
            after_target_remesh(target)
    refresh_ui(force=True)
    logger.info(
        "Clear undercuts joined in %.3fs: join=%.3fs remesh=%.3fs "
        "smooth=%.3fs target_remeshed=%s voxel_size=%.6f output_vertices=%d output_faces=%d",
        time.perf_counter() - phase_start,
        join_elapsed,
        remesh_elapsed,
        smooth_elapsed,
        remesh_target_after_join,
        target_retry_voxel_size,
        len(target_raw_object.data.vertices),
        len(target_raw_object.data.polygons),
    )
    logger.info(
        "Clear undercuts geometry completed in %.3fs",
        time.perf_counter() - total_start,
    )

    return


def begin_clear_undercuts(*args, **kwargs) -> BackgroundTaskSequence:
    """Start Clear Undercuts without blocking Blender's main event loop."""

    sequence = BackgroundTaskSequence(_clear_undercuts_steps(*args, **kwargs))
    sequence.redraw_interval = 0.1
    return sequence


def clear_undercuts(*args, **kwargs) -> Optional[Object]:
    """Run Clear Undercuts synchronously for blocking callers."""

    return finish_task_sync(begin_clear_undercuts(*args, **kwargs))
