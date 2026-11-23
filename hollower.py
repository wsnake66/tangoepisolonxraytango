"""Generate an object's inner cavity with an OpenVDB signed-distance field."""

import logging
import time
from dataclasses import dataclass

import bmesh  # type: ignore
import bpy  # type: ignore
import mathutils  # type: ignore
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty  # type: ignore

try:
    from moldboxer_silicone_native.source.object import Object
    from moldboxer_silicone_native.source.bl_utils import (
        draw_modal_progress_overlay,
        resolve_utility_target,
        set_modal_progress_overlay_active,
        show_popup,
    )
    from moldboxer_silicone_native.source.components.direct_mold import (
        ensure_direct_patron_backup,
    )
    from moldboxer_silicone_native.source.components.geometry_adapter import (
        acquire_geometry_worker,
        register_nearest_surface_worker_cache,
    )
    from moldboxer_silicone_native.source.mesh_decimation import (
        get_direct_undercuts_target_reduction,
    )
    from moldboxer_silicone_native.source.patron_lifecycle import (
        create_simplified_reference_for_operation,
    )
    from moldboxer_silicone_native.source.patron_state import DECIMATED_PATRON_KEY
    from moldboxer_silicone_native.source.modifiers import (
        build_voxel_modifier,
        diff_mod,
    )
    from moldboxer_silicone_native.source.nearest_surface_worker_client import (
        NearestSurfaceWorkerError,
    )
    from moldboxer_silicone_native.source.operator_access import (
        has_basic_server_access,
        show_basic_membership_required,
    )
    from moldboxer_silicone_native.source.progress import force_viewport_redraw
    from moldboxer_silicone_native.source.voxel_size import get_master_voxel_size
    from moldboxer_silicone_native.source.background_worker import (
        BackgroundTaskSequence,
        finish_task_sync,
        submit_worker_task,
    )
    from moldboxer_silicone_native.operators import ModalProcessingOperator
except ImportError:
    from .source.object import Object
    from .source.bl_utils import (
        draw_modal_progress_overlay,
        resolve_utility_target,
        set_modal_progress_overlay_active,
        show_popup,
    )
    from .source.components.direct_mold import ensure_direct_patron_backup
    from .source.components.geometry_adapter import (
        acquire_geometry_worker,
        register_nearest_surface_worker_cache,
    )
    from .source.mesh_decimation import get_direct_undercuts_target_reduction
    from .source.patron_lifecycle import create_simplified_reference_for_operation
    from .source.patron_state import DECIMATED_PATRON_KEY
    from .source.modifiers import build_voxel_modifier, diff_mod
    from .source.nearest_surface_worker_client import NearestSurfaceWorkerError
    from .source.operator_access import (
        has_basic_server_access,
        show_basic_membership_required,
    )
    from .source.progress import force_viewport_redraw
    from .source.voxel_size import get_master_voxel_size
    from .source.background_worker import (
        BackgroundTaskSequence,
        finish_task_sync,
        submit_worker_task,
    )
    from .operators import ModalProcessingOperator


logger = logging.getLogger(__name__)

DEFAULT_MAX_ESTIMATED_VOXELS = 256_000_000
_PLANTER_TOP_CUT_CLEARANCE = 1.0
_PLANTER_TOP_CUT_RETRY_MULTIPLIER = 1.5
_PLANTER_TOP_CUT_MAX_RETRIES = 3
_PLANTER_CAVITY_CUT_DEPTH_OFFSET = 0.25
_PATRON_BOTTOM_CUT_HEIGHT = 0.25
_HOLLOWER_UI_MIN_REFRESH_INTERVAL = 0.15
_HOLLOWER_WORKER_REDRAW_INTERVAL = 0.1
SKIN_CORE_OBJECT_NAME = "skin_core"
SKIN_CORE_OBJECT_MARKER = "moldboxer_skin_core"
_last_hollower_ui_refresh_at = 0.0


class EmptyCavityError(RuntimeError):
    """Raised when the worker cannot extract the requested inner surface."""


def _require_core_hollower_access() -> bool:
    if has_basic_server_access():
        return True
    show_basic_membership_required()
    return False


def _planter_top_cut_candidates(
    requested_cut: float,
    wall_thickness: float,
    *,
    clearance: float = _PLANTER_TOP_CUT_CLEARANCE,
    retry_multiplier: float = _PLANTER_TOP_CUT_RETRY_MULTIPLIER,
    max_retries: int = _PLANTER_TOP_CUT_MAX_RETRIES,
) -> tuple[float, ...]:
    requested_cut = float(requested_cut)
    wall_thickness = float(wall_thickness)
    clearance = float(clearance)
    retry_multiplier = float(retry_multiplier)
    max_retries = int(max_retries)
    if requested_cut <= 0.0:
        raise ValueError("The planter top cut must be greater than zero")
    if wall_thickness <= 0.0:
        raise ValueError("The planter wall thickness must be greater than zero")
    if clearance < 0.0:
        raise ValueError("The planter top cut clearance cannot be negative")
    if retry_multiplier <= 1.0:
        raise ValueError("The planter top cut retry multiplier must exceed one")
    if max_retries < 0:
        raise ValueError("The planter top cut retry count cannot be negative")
    initial_cut = requested_cut
    if initial_cut < wall_thickness:
        initial_cut = wall_thickness + clearance
    return tuple(
        initial_cut * (retry_multiplier**attempt)
        for attempt in range(max_retries + 1)
    )


def _refresh_hollower_ui(
    context=None,
    stage: str = "",
    *,
    force: bool = False,
) -> None:
    """Force a Blender UI draw between expensive hollowing stages."""

    global _last_hollower_ui_refresh_at

    now = time.perf_counter()
    if (
        not force
        and now - _last_hollower_ui_refresh_at
        < _HOLLOWER_UI_MIN_REFRESH_INTERVAL
    ):
        return
    try:
        force_viewport_redraw(context or bpy.context)
        _last_hollower_ui_refresh_at = time.perf_counter()
        logger.debug("Hollower UI refreshed: stage=%s", stage or "unspecified")
    except Exception:
        logger.debug(
            "Could not refresh the Hollower UI: stage=%s",
            stage or "unspecified",
            exc_info=True,
        )


class _HollowerProgressOverlay:
    """Draw an operation label and elapsed time during blocking hollowing work."""

    progress_label = ""
    _progress_draw_handler = None
    _progress_started_at = None

    def _start_progress_overlay(self, context) -> None:
        self._progress_started_at = time.perf_counter()
        try:
            self._progress_draw_handler = bpy.types.SpaceView3D.draw_handler_add(
                self._draw_progress_overlay,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
            set_modal_progress_overlay_active(True, context)
        except Exception:
            self._progress_draw_handler = None
            logger.debug("Could not add the Hollower progress overlay", exc_info=True)
        _refresh_hollower_ui(
            context,
            f"showing {self.progress_label} progress",
            force=True,
        )

    def _stop_progress_overlay(self, context) -> None:
        draw_handler = self._progress_draw_handler
        self._progress_draw_handler = None
        self._progress_started_at = None
        if draw_handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(draw_handler, "WINDOW")
            except Exception:
                logger.debug(
                    "Could not remove the Hollower progress overlay",
                    exc_info=True,
                )
            finally:
                set_modal_progress_overlay_active(False, context)
        _refresh_hollower_ui(
            context,
            f"cleared {self.progress_label} progress",
            force=True,
        )

    def _draw_progress_overlay(self) -> None:
        if self._progress_started_at is None:
            return

        elapsed = max(
            time.perf_counter() - self._progress_started_at,
            0.0,
        )
        region = getattr(bpy.context, "region", None)
        draw_modal_progress_overlay(
            self.progress_label,
            elapsed,
            region,
        )


def _matrix_to_numpy(matrix) -> np.ndarray:
    return np.asarray([tuple(row) for row in matrix], dtype=np.float64)


def _as_shaped_array(values, dtype, columns: int) -> np.ndarray:
    array = np.asarray(values, dtype=dtype)
    if array.size == 0:
        return np.empty((0, columns), dtype=dtype)
    return np.ascontiguousarray(array.reshape((-1, columns)))


def _transform_points(points: np.ndarray, matrix) -> np.ndarray:
    if not len(points):
        return np.empty((0, 3), dtype=np.float64)
    matrix_array = _matrix_to_numpy(matrix)
    source = np.asarray(points, dtype=np.float64)
    transformed = np.empty((len(source), 3), dtype=np.float64)
    transformed[:, 0] = (
        source[:, 0] * matrix_array[0, 0]
        + source[:, 1] * matrix_array[0, 1]
        + source[:, 2] * matrix_array[0, 2]
        + matrix_array[0, 3]
    )
    transformed[:, 1] = (
        source[:, 0] * matrix_array[1, 0]
        + source[:, 1] * matrix_array[1, 1]
        + source[:, 2] * matrix_array[1, 2]
        + matrix_array[1, 3]
    )
    transformed[:, 2] = (
        source[:, 0] * matrix_array[2, 0]
        + source[:, 1] * matrix_array[2, 1]
        + source[:, 2] * matrix_array[2, 2]
        + matrix_array[2, 3]
    )
    return np.ascontiguousarray(transformed)


def _evaluated_world_triangles(
    source,
    depsgraph,
    context=None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return evaluated, triangulated vertices and faces in world space."""

    evaluated = source.evaluated_get(depsgraph)
    temporary_mesh = evaluated.to_mesh(
        preserve_all_data_layers=False,
        depsgraph=depsgraph,
    )
    if temporary_mesh is None:
        raise RuntimeError("Blender could not evaluate the source mesh")
    _refresh_hollower_ui(context, "after evaluated mesh creation")

    bm = bmesh.new()
    try:
        bm.from_mesh(temporary_mesh)
        if not bm.verts or not bm.faces:
            raise ValueError("The evaluated source mesh is empty")
        _refresh_hollower_ui(context, "after evaluated BMesh creation")
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()
        _refresh_hollower_ui(context, "after evaluated mesh triangulation")

        local_points = np.asarray(
            [tuple(vertex.co) for vertex in bm.verts], dtype=np.float64
        )
        triangles = np.asarray(
            [tuple(vertex.index for vertex in face.verts) for face in bm.faces],
            dtype=np.int64,
        )
        _refresh_hollower_ui(context, "after evaluated geometry array extraction")
    finally:
        bm.free()
        evaluated.to_mesh_clear()

    triangles = _as_shaped_array(triangles, np.int64, 3)
    world_points = _transform_points(local_points, source.matrix_world)
    _refresh_hollower_ui(context, "after evaluated world-space transformation")

    # Degenerate input polygons are not useful to the VDB rasterizer and can
    # produce unstable sign classification.
    triangle_points = world_points[triangles]
    doubled_areas = np.linalg.norm(
        np.cross(
            triangle_points[:, 1] - triangle_points[:, 0],
            triangle_points[:, 2] - triangle_points[:, 0],
        ),
        axis=1,
    )
    scale = max(float(np.ptp(world_points, axis=0).max()), 1.0)
    triangles = triangles[doubled_areas > np.finfo(np.float64).eps * scale * scale]
    if not len(triangles):
        raise ValueError("The evaluated source mesh has no non-degenerate triangles")
    _refresh_hollower_ui(context, "after degenerate triangle filtering")
    return world_points, np.ascontiguousarray(triangles)


def _create_cavity_object(
    context,
    source,
    surface,
):
    object_name = f"{source.name}_InnerCavity"
    if bpy.data.objects.get(object_name) is not None:
        raise RuntimeError(
            f'An object named "{object_name}" already exists; rename or remove it first'
        )

    inverse_world = source.matrix_world.inverted()
    local_points = _transform_points(surface.vertices, inverse_world)
    _refresh_hollower_ui(context, "after cavity point transformation")

    faces = []
    total_faces = len(surface.triangles) + len(surface.quads)
    processed_faces = 0
    face_batch_size = 250_000
    for face_kind, surface_faces in (
        ("triangles", surface.triangles),
        ("quads", surface.quads),
    ):
        for batch_start in range(0, len(surface_faces), face_batch_size):
            batch_end = min(batch_start + face_batch_size, len(surface_faces))
            faces.extend(surface_faces[batch_start:batch_end].tolist())
            processed_faces += batch_end - batch_start
            _refresh_hollower_ui(
                context,
                f"built cavity {face_kind} {processed_faces}/{total_faces}",
            )

    mesh = bpy.data.meshes.new(f"{object_name}_Mesh")
    cavity = None
    try:
        _refresh_hollower_ui(
            context,
            "before cavity mesh population",
            force=True,
        )
        mesh.from_pydata(local_points.tolist(), [], faces)
        _refresh_hollower_ui(context, "after cavity mesh population")
        mesh.validate(verbose=False, clean_customdata=False)
        _refresh_hollower_ui(context, "after cavity mesh validation")

        normal_mesh = bmesh.new()
        try:
            normal_mesh.from_mesh(mesh)
            _refresh_hollower_ui(context, "after cavity normal BMesh creation")
            if normal_mesh.faces:
                _refresh_hollower_ui(
                    context,
                    "before cavity normal recalculation",
                    force=True,
                )
                bmesh.ops.recalc_face_normals(
                    normal_mesh,
                    faces=list(normal_mesh.faces),
                )
                _refresh_hollower_ui(context, "after cavity normal recalculation")
                normal_mesh.to_mesh(mesh)
                _refresh_hollower_ui(context, "after cavity normal mesh write")
        finally:
            normal_mesh.free()

        mesh.update(calc_edges=True)
        _refresh_hollower_ui(context, "after cavity mesh edge update")
        cavity = bpy.data.objects.new(object_name, mesh)
        _refresh_hollower_ui(context, "after cavity object allocation")

        target_collection = (
            source.users_collection[0]
            if source.users_collection
            else context.collection
        )
        target_collection.objects.link(cavity)
        cavity.matrix_world = source.matrix_world.copy()
        _refresh_hollower_ui(context, "after cavity object linking")
    except Exception:
        if cavity is not None:
            bpy.data.objects.remove(cavity, do_unlink=True)
        if mesh.name in bpy.data.meshes and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise

    return cavity


def generate_inner_cavity(
    context,
    source,
    cavity_inset: float,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    *,
    evaluated_geometry: tuple[np.ndarray, np.ndarray] | None = None,
):
    """Generate and return a new inner-cavity object without editing ``source``."""

    cavity_inset = float(cavity_inset)
    if cavity_inset <= 0.0:
        raise ValueError("Cavity inset must be greater than zero")
    if source is None or source.type != "MESH":
        raise ValueError("The source must be a mesh object")

    object_name = f"{source.name}_InnerCavity"
    if bpy.data.objects.get(object_name) is not None:
        raise RuntimeError(
            f'An object named "{object_name}" already exists; rename or remove it first'
        )

    if evaluated_geometry is None:
        world_points, triangles = _evaluated_world_triangles(
            source,
            context.evaluated_depsgraph_get(),
            context,
        )
    else:
        world_points, triangles = evaluated_geometry
    _refresh_hollower_ui(
        context,
        "before worker cavity generation",
        force=True,
    )
    worker = acquire_geometry_worker()
    try:
        surface = worker.generate_hollow_surface(
            world_points,
            triangles,
            cavity_inset=cavity_inset,
            quality=quality,
            max_estimated_voxels=int(max_estimated_voxels),
        )
    except NearestSurfaceWorkerError as error:
        if str(error).startswith("EmptyCavityError:"):
            raise EmptyCavityError(str(error).split(":", 1)[1].strip()) from error
        raise
    _refresh_hollower_ui(context, "after worker cavity generation")
    cavity = _create_cavity_object(context, source, surface)
    _refresh_hollower_ui(context, "after cavity object creation")
    return (
        cavity,
        surface.voxel_size,
        surface.requested_voxel_size,
        surface.estimated_voxels,
    )


def generate_skin_core(
    context,
    source,
    skin_thickness: float,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
):
    """Generate an inward core from a temporary simplified analysis target."""

    previous_core = bpy.data.objects.get(SKIN_CORE_OBJECT_NAME)
    temporary_analysis_object = None
    try:
        temporary_analysis_object = _create_temporary_hollow_analysis_object(
            context,
            source,
        )
        analysis_source = (
            temporary_analysis_object.object
            if temporary_analysis_object is not None
            else source
        )
        cavity, voxel_size, requested_voxel_size, estimated_voxels = (
            generate_inner_cavity(
                context,
                analysis_source,
                skin_thickness,
                quality,
                max_estimated_voxels,
            )
        )
    finally:
        _remove_temporary_hollow_analysis_object(temporary_analysis_object)

    if previous_core is not None and previous_core is not cavity:
        previous_mesh = previous_core.data
        bpy.data.objects.remove(previous_core, do_unlink=True)
        if (
            previous_mesh is not None
            and previous_mesh.users == 0
            and bpy.data.meshes.get(previous_mesh.name) is previous_mesh
        ):
            bpy.data.meshes.remove(previous_mesh)

    cavity.name = SKIN_CORE_OBJECT_NAME
    cavity.data.name = f"{SKIN_CORE_OBJECT_NAME}_mesh"
    cavity[SKIN_CORE_OBJECT_MARKER] = True
    return cavity, voxel_size, requested_voxel_size, estimated_voxels


def _remesh_for_hollow_boolean_retry(
    target: Object,
    voxel_size: float,
    label: str,
    context=None,
) -> None:
    voxel_size = float(voxel_size)
    if voxel_size <= 0.0:
        raise ValueError(f"{label} retry voxel size must be greater than zero")
    logger.warning(
        "Remeshing %s %s for hollow Boolean retry: voxel_size=%.6g",
        label,
        target.name,
        voxel_size,
    )
    _refresh_hollower_ui(
        context,
        f"before {label} retry remesh",
        force=True,
    )
    target.apply_modifier(build_voxel_modifier(voxel_size))
    _refresh_hollower_ui(context, f"after {label} retry remesh")


def _master_retry_voxel_size(patron: Object, context=None) -> float:
    scene = getattr(context, "scene", None) or bpy.context.scene
    quality = getattr(scene, "master_quality", "HIGH")
    return get_master_voxel_size(quality, patron)


def _cut_patron_with_hollow_boolean_retry(
    patron: Object,
    cavity: Object,
    plane_normal: mathutils.Vector,
    plane_point: mathutils.Vector,
    cavity_voxel_size: float,
    context=None,
) -> None:
    _refresh_hollower_ui(
        context,
        "before initial patron cut Boolean",
        force=True,
    )
    try:
        patron.cut_plane(plane_normal, plane_point)
        _refresh_hollower_ui(context, "after initial patron cut Boolean")
        return
    except Exception:
        _refresh_hollower_ui(context, "after failed initial patron cut Boolean")
        logger.warning(
            "Patron cut Boolean failed; remeshing the inner cavity before retry",
            exc_info=True,
        )

    _remesh_for_hollow_boolean_retry(
        cavity,
        cavity_voxel_size,
        "inner cavity",
        context,
    )
    _refresh_hollower_ui(
        context,
        "before patron cut Boolean cavity-remesh retry",
        force=True,
    )
    try:
        patron.cut_plane(plane_normal, plane_point)
        _refresh_hollower_ui(context, "after patron cut Boolean cavity-remesh retry")
        return
    except Exception:
        _refresh_hollower_ui(
            context,
            "after failed patron cut Boolean cavity-remesh retry",
        )
        logger.warning(
            "Patron cut Boolean still failed after the inner-cavity remesh; "
            "remeshing the patron before the final retry",
            exc_info=True,
        )

    patron_voxel_size = _master_retry_voxel_size(patron, context)
    _remesh_for_hollow_boolean_retry(
        patron,
        patron_voxel_size,
        "patron",
        context,
    )
    _refresh_hollower_ui(
        context,
        "before final patron cut Boolean retry",
        force=True,
    )
    patron.cut_plane(plane_normal, plane_point)
    _refresh_hollower_ui(context, "after final patron cut Boolean retry")


def _apply_hollow_difference_once(source, cavity, context) -> None:
    modifier = source.modifiers.new(
        name="Moldboxer Hollow",
        type="BOOLEAN",
    )
    modifier.operation = "DIFFERENCE"
    modifier.solver = "MANIFOLD"
    modifier.object = cavity
    modifier_name = modifier.name
    _refresh_hollower_ui(context, "after hollow Boolean setup")
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        source.select_set(True)
        context.view_layer.objects.active = source
        _refresh_hollower_ui(
            context,
            "before hollow Boolean modifier apply",
            force=True,
        )
        bpy.ops.object.modifier_apply(modifier=modifier_name)
        _refresh_hollower_ui(context, "after hollow Boolean modifier apply")
        if source.modifiers.get(modifier_name) is not None:
            raise RuntimeError("Blender could not apply the hollow Boolean modifier")
    finally:
        remaining_modifier = source.modifiers.get(modifier_name)
        if remaining_modifier is not None:
            source.modifiers.remove(remaining_modifier)
            _refresh_hollower_ui(context, "after hollow Boolean modifier cleanup")


def _apply_hollow_difference_with_retry(
    source,
    cavity,
    cavity_voxel_size: float,
    context,
) -> None:
    _refresh_hollower_ui(context, "before initial hollow Boolean attempt")
    try:
        _apply_hollow_difference_once(source, cavity, context)
        _refresh_hollower_ui(context, "after initial hollow Boolean attempt")
        return
    except Exception:
        _refresh_hollower_ui(context, "after failed initial hollow Boolean attempt")
        logger.warning(
            "Hollow Boolean failed; remeshing the inner cavity before retry",
            exc_info=True,
        )

    cavity_object = Object(cavity)
    _remesh_for_hollow_boolean_retry(
        cavity_object,
        cavity_voxel_size,
        "inner cavity",
        context,
    )
    _refresh_hollower_ui(context, "before hollow Boolean cavity-remesh retry")
    try:
        _apply_hollow_difference_once(source, cavity, context)
        _refresh_hollower_ui(context, "after hollow Boolean cavity-remesh retry")
        return
    except Exception:
        _refresh_hollower_ui(
            context,
            "after failed hollow Boolean cavity-remesh retry",
        )
        logger.warning(
            "Hollow Boolean still failed after the inner-cavity remesh; "
            "remeshing the patron before the final retry",
            exc_info=True,
        )

    source_object = Object(source)
    patron_voxel_size = _master_retry_voxel_size(source_object, context)
    _remesh_for_hollow_boolean_retry(
        source_object,
        patron_voxel_size,
        "patron",
        context,
    )
    _refresh_hollower_ui(context, "before final hollow Boolean retry")
    _apply_hollow_difference_once(source, cavity, context)
    _refresh_hollower_ui(context, "after final hollow Boolean retry")


def _apply_inner_core_manifold_hollow_difference_with_retry(
    source,
    cavity,
    cavity_voxel_size: float,
    context,
) -> None:
    """Subtract a remeshed cavity with MANIFOLD, remeshing the core on retry."""

    source_object = Object(source)
    cavity_object = Object(cavity)
    _refresh_hollower_ui(
        context,
        "before inner-core manifold hollow Boolean",
        force=True,
    )
    source_object.apply_boolean_modifier(
        diff_mod,
        target=cavity_object,
        retry_remesh=build_voxel_modifier(cavity_voxel_size),
        retry_remesh_on="self",
    )
    _refresh_hollower_ui(
        context,
        "after inner-core manifold hollow Boolean",
    )


@dataclass(frozen=True)
class _HollowWorkerPreparation:
    analysis_source: object
    evaluated_geometry: tuple[np.ndarray, np.ndarray]
    target_geometry: tuple[np.ndarray, np.ndarray] | None
    target_min_z: float
    target_max_z: float
    final_top_cut_z: float | None
    top_cut_amount: float
    top_cut_candidates: tuple[float, ...]
    has_opening: bool


def _prepare_hollow_worker_operation(
    context,
    source,
    cavity_inset: float,
    *,
    open_bottom: bool,
    open_top: bool,
    top_cut_amount: float,
    cavity_source,
    strict_top_cut: bool,
) -> _HollowWorkerPreparation:
    """Extract Blender geometry and register lifecycle hooks on the main thread."""

    if open_bottom and open_top:
        raise ValueError("The cavity cannot open through both ends at once")
    analysis_source = cavity_source or source
    _refresh_hollower_ui(context, "before evaluated geometry extraction")
    evaluated_geometry = _evaluated_world_triangles(
        analysis_source,
        context.evaluated_depsgraph_get(),
        context,
    )
    source_object = Object(source)
    target_min_z = float(source_object.min_z)
    target_max_z = float(source_object.max_z)
    final_top_cut_z = None
    top_cut_candidates = ()
    top_cut_amount = float(top_cut_amount)
    if open_top:
        if strict_top_cut:
            if top_cut_amount <= 0.0:
                raise ValueError("The planter top cut must be greater than zero")
            top_cut_candidates = (top_cut_amount,)
        else:
            top_cut_candidates = _planter_top_cut_candidates(
                top_cut_amount,
                cavity_inset,
            )
        effective_top_cut = top_cut_candidates[0]
        if effective_top_cut != top_cut_amount:
            logger.info(
                "Raised planter top cut to exceed wall thickness: "
                "requested=%.6g wall_thickness=%.6g applied=%.6g",
                top_cut_amount,
                cavity_inset,
                effective_top_cut,
            )
        top_cut_amount = effective_top_cut
        final_top_cut_z = target_max_z - effective_top_cut
        if final_top_cut_z <= target_min_z:
            raise ValueError("The planter top cut removes the complete patron")

    has_opening = bool(open_bottom or open_top)
    target_geometry = (
        _evaluated_world_triangles(
            source,
            context.evaluated_depsgraph_get(),
            context,
        )
        if has_opening and analysis_source is not source
        else None
    )
    # Handler registration touches Blender and must happen on the main thread.
    # Process acquisition itself is deferred to the background task so the
    # first worker launch cannot stall the UI.
    register_nearest_surface_worker_cache()
    return _HollowWorkerPreparation(
        analysis_source=analysis_source,
        evaluated_geometry=evaluated_geometry,
        target_geometry=target_geometry,
        target_min_z=target_min_z,
        target_max_z=target_max_z,
        final_top_cut_z=final_top_cut_z,
        top_cut_amount=top_cut_amount,
        top_cut_candidates=top_cut_candidates,
        has_opening=has_opening,
    )


def _run_hollow_worker_operation(
    preparation: _HollowWorkerPreparation,
    *,
    cavity_inset: float,
    quality: str,
    max_estimated_voxels: int,
    open_bottom: bool,
    open_top: bool,
    top_overlap_height: float,
):
    """Run only Blender-free IPC and geometry work on a background thread."""

    points, triangles = preparation.evaluated_geometry
    worker = acquire_geometry_worker(register_cache=False)
    try:
        if preparation.has_opening:
            target_geometry = preparation.target_geometry
            return worker.generate_hollow_cutter(
                points,
                triangles,
                target_vertices=(
                    None if target_geometry is None else target_geometry[0]
                ),
                target_triangles=(
                    None if target_geometry is None else target_geometry[1]
                ),
                cavity_inset=cavity_inset,
                quality=quality,
                max_estimated_voxels=int(max_estimated_voxels),
                opening_mode="TOP" if open_top else "BOTTOM",
                target_min_z=preparation.target_min_z,
                target_max_z=preparation.target_max_z,
                top_cut_candidates=preparation.top_cut_candidates,
                top_cavity_cut_depth_offset=(
                    _PLANTER_CAVITY_CUT_DEPTH_OFFSET
                ),
                top_overlap_height=top_overlap_height,
                bottom_cut_height=1.0,
                source_bottom_cut_height=_PATRON_BOTTOM_CUT_HEIGHT,
            )
        return worker.generate_hollow_surface(
            points,
            triangles,
            cavity_inset=cavity_inset,
            quality=quality,
            max_estimated_voxels=int(max_estimated_voxels),
        )
    except NearestSurfaceWorkerError as error:
        if str(error).startswith("EmptyCavityError:"):
            raise EmptyCavityError(
                str(error).split(":", 1)[1].strip()
            ) from error
        raise


def hollow_object(
    context,
    source,
    cavity_inset: float,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    open_bottom: bool = False,
    open_top: bool = False,
    top_cut_amount: float = 0.0,
    cavity_source=None,
    strict_top_cut: bool = False,
    top_overlap_height: float = 1.0,
    remesh_after_top_opening: bool = False,
    smooth_after_top_opening_remesh: bool = False,
    cavity_exclusion=None,
    keep_cavity: bool = False,
    kept_cavity_name: str | None = None,
    use_manifold_hollow_difference: bool = False,
    _worker_preparation: _HollowWorkerPreparation | None = None,
    _worker_result=None,
):
    """Subtract a generated cavity from ``source`` and remove the cutter.

    ``cavity_source`` may be a temporary simplified duplicate.  It supplies
    only the surface used to generate the inner cavity; all opening cuts and
    the final Boolean continue to modify ``source``.
    """

    cavity = None
    cavity_mesh = None
    try:
        preparation = _worker_preparation or _prepare_hollow_worker_operation(
            context,
            source,
            cavity_inset,
            open_bottom=open_bottom,
            open_top=open_top,
            top_cut_amount=top_cut_amount,
            cavity_source=cavity_source,
            strict_top_cut=strict_top_cut,
        )
        analysis_source = preparation.analysis_source
        evaluated_target_max_z = preparation.target_max_z
        final_top_cut_z = preparation.final_top_cut_z
        top_cut_amount = preparation.top_cut_amount
        has_opening = preparation.has_opening
        worker_result = _worker_result
        if worker_result is None:
            worker_result = _run_hollow_worker_operation(
                preparation,
                cavity_inset=cavity_inset,
                quality=quality,
                max_estimated_voxels=max_estimated_voxels,
                open_bottom=open_bottom,
                open_top=open_top,
                top_overlap_height=top_overlap_height,
            )
        fused_cutter = None
        if has_opening:
            fused_cutter = worker_result
            cavity = _create_cavity_object(
                context,
                analysis_source,
                fused_cutter,
            )
            voxel_size = fused_cutter.voxel_size
            requested_voxel_size = fused_cutter.requested_voxel_size
            estimated_voxels = fused_cutter.estimated_voxels
            logger.info(
                "Fused worker hollow cutter ready: source=%s opening=%s "
                "cavity_cut_z=%s source_cut_z=%s selected=%s "
                "cavity_area=%s source_area=%s construction=%.3fs "
                "worker=%.3fs roundtrip=%.3fs",
                source.name,
                fused_cutter.opening_mode,
                fused_cutter.cavity_cut_z,
                fused_cutter.source_cut_z,
                fused_cutter.selected_source,
                fused_cutter.cavity_area,
                fused_cutter.source_area,
                fused_cutter.construction_seconds,
                fused_cutter.worker_seconds,
                fused_cutter.roundtrip_seconds,
            )
            if open_top and fused_cutter.cavity_cut_z is None:
                logger.info(
                    "Fused worker reused the existing inward cavity for the top "
                    "opening: top_cut=%s wall_thickness=%.6g "
                    "source_cut_z=%s; skipped cavity trim, inset, extrusion "
                    "and union",
                    fused_cutter.applied_top_cut,
                    cavity_inset,
                    fused_cutter.source_cut_z,
                )
        else:
            cavity = _create_cavity_object(
                context,
                analysis_source,
                worker_result,
            )
            voxel_size = worker_result.voxel_size
            requested_voxel_size = worker_result.requested_voxel_size
            estimated_voxels = worker_result.estimated_voxels
        cavity_mesh = cavity.data
        if keep_cavity and kept_cavity_name:
            cavity.name = kept_cavity_name
            cavity.data.name = f"{cavity.name}_mesh"
        _refresh_hollower_ui(context, "after inner cavity generation")
        if open_bottom and open_top:
            raise ValueError("The cavity cannot open through both ends at once")
        if open_bottom:
            if fused_cutter.source_cut_z is None:
                raise RuntimeError("Worker omitted the bottom source cut plane")
            _cut_patron_with_hollow_boolean_retry(
                Object(source),
                Object(cavity),
                mathutils.Vector((0.0, 0.0, -1.0)),
                mathutils.Vector((0.0, 0.0, fused_cutter.source_cut_z)),
                voxel_size,
                context,
            )
            _refresh_hollower_ui(context, "after fused open-bottom construction")
        if open_top:
            if (
                fused_cutter.source_cut_z is None
                or fused_cutter.applied_top_cut is None
            ):
                raise RuntimeError("Worker omitted the top opening cut metadata")
            final_top_cut_z = fused_cutter.source_cut_z
            top_cut_amount = fused_cutter.applied_top_cut
            _cut_patron_with_hollow_boolean_retry(
                Object(source),
                Object(cavity),
                mathutils.Vector((0.0, 0.0, 1.0)),
                mathutils.Vector((0.0, 0.0, fused_cutter.source_cut_z)),
                voxel_size,
                context,
            )
            _refresh_hollower_ui(context, "after fused open-top construction")
        if open_top and remesh_after_top_opening:
            _refresh_hollower_ui(
                context,
                "before post-opening cavity remesh",
                force=True,
            )
            Object(cavity).apply_modifier(build_voxel_modifier(voxel_size))
            _refresh_hollower_ui(
                context,
                "after post-opening cavity remesh",
            )
            if smooth_after_top_opening_remesh:
                Object(cavity).smooth_geometry(factor=0.5, repeat=5)
                _refresh_hollower_ui(
                    context,
                    "after post-opening cavity smooth",
                )
        if cavity_exclusion is not None:
            _refresh_hollower_ui(
                context,
                "before cavity exclusion subtraction",
                force=True,
            )
            cavity_object = Object(cavity)
            cavity_object -= Object(cavity_exclusion)
            _refresh_hollower_ui(
                context,
                "after cavity exclusion subtraction",
            )

        _refresh_hollower_ui(context, "before hollow Boolean")
        if use_manifold_hollow_difference:
            _apply_inner_core_manifold_hollow_difference_with_retry(
                source,
                cavity,
                voxel_size,
                context,
            )
        else:
            _apply_hollow_difference_with_retry(
                source,
                cavity,
                voxel_size,
                context,
            )
        _refresh_hollower_ui(context, "after hollow Boolean")

        if open_top:
            source_object = Object(source)
            current_max_z = source_object.max_z
            cut_tolerance = max(1e-4, source_object.height * 1e-6)
            if current_max_z > final_top_cut_z + cut_tolerance:
                _cut_patron_with_hollow_boolean_retry(
                    source_object,
                    Object(cavity),
                    mathutils.Vector((0.0, 0.0, 1.0)),
                    mathutils.Vector((0.0, 0.0, final_top_cut_z)),
                    voxel_size,
                    context,
                )
                logger.info(
                    "Cut planter top after hollowing: amount=%.6g "
                    "original_max_z=%.6g cut_z=%.6g previous_max_z=%.6g",
                    top_cut_amount,
                    evaluated_target_max_z,
                    final_top_cut_z,
                    current_max_z,
                )
            else:
                logger.info(
                    "Planter top already trimmed at comparison plane: amount=%.6g "
                    "original_max_z=%.6g cut_z=%.6g result_max_z=%.6g",
                    top_cut_amount,
                    evaluated_target_max_z,
                    final_top_cut_z,
                    current_max_z,
                )
            _refresh_hollower_ui(context, "after final planter top cut")

        return voxel_size, requested_voxel_size, estimated_voxels
    finally:
        cavity_meshes = [cavity_mesh] if cavity_mesh is not None else []
        if cavity is not None and getattr(cavity, "data", None) is not None:
            cavity_meshes.append(cavity.data)
        _refresh_hollower_ui(context, "before hollow cavity cleanup")
        if (
            not keep_cavity
            and cavity is not None
            and bpy.data.objects.get(cavity.name) is cavity
        ):
            bpy.data.objects.remove(cavity, do_unlink=True)
            _refresh_hollower_ui(context, "after hollow cavity object cleanup")
        for mesh in dict.fromkeys(cavity_meshes):
            if mesh.users == 0 and bpy.data.meshes.get(mesh.name) is mesh:
                mesh_name = mesh.name
                bpy.data.meshes.remove(mesh)
                _refresh_hollower_ui(
                    context,
                    f"after hollow cavity mesh cleanup: {mesh_name}",
                )
        _refresh_hollower_ui(context, "after hollow cleanup")


def begin_hollow_object(
    context,
    source,
    cavity_inset: float,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    open_bottom: bool = False,
    open_top: bool = False,
    top_cut_amount: float = 0.0,
    cavity_source=None,
    strict_top_cut: bool = False,
    top_overlap_height: float = 1.0,
    remesh_after_top_opening: bool = False,
    smooth_after_top_opening_remesh: bool = False,
    cavity_exclusion=None,
    keep_cavity: bool = False,
    kept_cavity_name: str | None = None,
    use_manifold_hollow_difference: bool = False,
):
    """Begin worker geometry asynchronously and finalize Blender work on main."""

    preparation = _prepare_hollow_worker_operation(
        context,
        source,
        cavity_inset,
        open_bottom=open_bottom,
        open_top=open_top,
        top_cut_amount=top_cut_amount,
        cavity_source=cavity_source,
        strict_top_cut=strict_top_cut,
    )
    task = submit_worker_task(
        _run_hollow_worker_operation,
        preparation,
        cavity_inset=cavity_inset,
        quality=quality,
        max_estimated_voxels=max_estimated_voxels,
        open_bottom=open_bottom,
        open_top=open_top,
        top_overlap_height=top_overlap_height,
    )
    task.redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
    return task.then(
        lambda worker_result: hollow_object(
            context,
            source,
            cavity_inset,
            quality,
            max_estimated_voxels,
            open_bottom=open_bottom,
            open_top=open_top,
            top_cut_amount=top_cut_amount,
            cavity_source=cavity_source,
            strict_top_cut=strict_top_cut,
            top_overlap_height=top_overlap_height,
            remesh_after_top_opening=remesh_after_top_opening,
            smooth_after_top_opening_remesh=smooth_after_top_opening_remesh,
            cavity_exclusion=cavity_exclusion,
            keep_cavity=keep_cavity,
            kept_cavity_name=kept_cavity_name,
            use_manifold_hollow_difference=use_manifold_hollow_difference,
            _worker_preparation=preparation,
            _worker_result=worker_result,
        )
    )


def begin_convert_object_to_planter(
    context,
    source,
    cavity_inset: float = 2.0,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    top_cut_amount: float = 10.0,
    strict_top_cut: bool = False,
    top_overlap_height: float = 1.0,
    remesh_after_top_opening: bool = False,
):
    """Begin an asynchronous planter conversion with main-thread cleanup."""

    def steps():
        temporary_analysis_object = None
        try:
            temporary_analysis_object = _create_temporary_hollow_analysis_object(
                context,
                source,
            )
            return (yield begin_hollow_object(
                context,
                source,
                cavity_inset,
                quality,
                max_estimated_voxels,
                open_bottom=False,
                open_top=True,
                top_cut_amount=top_cut_amount,
                cavity_source=(
                    temporary_analysis_object.object
                    if temporary_analysis_object is not None
                    else None
                ),
                strict_top_cut=strict_top_cut,
                top_overlap_height=top_overlap_height,
                remesh_after_top_opening=remesh_after_top_opening,
            ))
        finally:
            _remove_temporary_hollow_analysis_object(temporary_analysis_object)

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
    return sequence


def convert_object_to_planter(
    context,
    source,
    cavity_inset: float = 2.0,
    quality: str = "NORMAL",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    top_cut_amount: float = 10.0,
    strict_top_cut: bool = False,
    top_overlap_height: float = 1.0,
    remesh_after_top_opening: bool = False,
):
    """Convert an exact mesh object to a planter and return resolution details."""

    return finish_task_sync(
        begin_convert_object_to_planter(
            context,
            source,
            cavity_inset=cavity_inset,
            quality=quality,
            max_estimated_voxels=max_estimated_voxels,
            top_cut_amount=top_cut_amount,
            strict_top_cut=strict_top_cut,
            top_overlap_height=top_overlap_height,
            remesh_after_top_opening=remesh_after_top_opening,
        )
    )


def convert_inner_core_to_planter(
    context,
    source,
    cavity_exclusion,
    cavity_inset: float = 2.0,
    quality: str = "DRAFT",
    max_estimated_voxels: int = DEFAULT_MAX_ESTIMATED_VOXELS,
    top_cut_amount: float = 3.0,
    top_overlap_height: float = 3.0,
    remesh_after_top_opening: bool = True,
    smooth_after_top_opening_remesh: bool = True,
    keep_cavity: bool = False,
    kept_cavity_name: str | None = None,
):
    """Convert one imported core while excluding the main-core footprint."""

    temporary_analysis_object = None
    try:
        temporary_analysis_object = _create_temporary_hollow_analysis_object(
            context,
            source,
        )
        return hollow_object(
            context,
            source,
            cavity_inset,
            quality,
            max_estimated_voxels,
            open_bottom=False,
            open_top=True,
            top_cut_amount=top_cut_amount,
            cavity_source=(
                temporary_analysis_object.object
                if temporary_analysis_object is not None
                else None
            ),
            strict_top_cut=True,
            top_overlap_height=top_overlap_height,
            remesh_after_top_opening=remesh_after_top_opening,
            smooth_after_top_opening_remesh=smooth_after_top_opening_remesh,
            cavity_exclusion=cavity_exclusion,
            keep_cavity=keep_cavity,
            kept_cavity_name=kept_cavity_name,
            use_manifold_hollow_difference=True,
        )
    finally:
        _remove_temporary_hollow_analysis_object(temporary_analysis_object)


def _create_temporary_hollow_analysis_object(context, source):
    """Return a Direct-style simplified copy for cavity analysis when useful."""

    source.data.calc_loop_triangles()
    source_triangle_count = len(source.data.loop_triangles)
    target_reduction = get_direct_undercuts_target_reduction(
        source_triangle_count
    )
    if target_reduction is None or target_reduction <= 0.0:
        logger.info(
            "Hollow cavity analysis using original target directly: "
            "target=%s triangles=%d",
            source.name,
            source_triangle_count,
        )
        return None

    analysis_object = create_simplified_reference_for_operation(
        Object(source),
        context,
        name="hollow_analysis_reference",
        target_reduction=target_reduction,
    )
    analysis_raw = analysis_object.object
    analysis_raw.hide_set(True)
    analysis_raw.hide_viewport = True
    analysis_raw.hide_render = True
    logger.info(
        "Hollow cavity analysis using temporary simplified reference: "
        "target=%s source_triangles=%d reference=%s reference_polygons=%d "
        "target_reduction=%.2f%%",
        source.name,
        source_triangle_count,
        analysis_raw.name,
        len(analysis_raw.data.polygons),
        target_reduction * 100.0,
    )
    return analysis_object


def _resolve_hollow_target(context):
    """Resolve the editable original, never a temporary working patron."""

    source = resolve_utility_target(context)
    if source is None or not bool(source.get(DECIMATED_PATRON_KEY, False)):
        return source

    master = context.scene.objects.get("master")
    if master is None or master.type != "MESH":
        return source

    source.select_set(False)
    master.hide_set(False)
    master.hide_viewport = False
    master.select_set(True)
    context.view_layer.objects.active = master
    logger.info(
        "Hollow target redirected from temporary working patron %s to "
        "original master %s",
        source.name,
        master.name,
    )
    return master


def _remove_temporary_hollow_analysis_object(analysis_object) -> None:
    if analysis_object is None:
        return
    raw_object = getattr(analysis_object, "object", analysis_object)
    try:
        analysis_mesh = raw_object.data
        object_name = raw_object.name
    except ReferenceError:
        return
    if object_name in bpy.data.objects:
        bpy.data.objects.remove(raw_object, do_unlink=True)
    if (
        analysis_mesh is not None
        and getattr(analysis_mesh, "users", 0) == 0
        and analysis_mesh.name in bpy.data.meshes
    ):
        bpy.data.meshes.remove(analysis_mesh)


class SILICONE_OT_generate_inner_cavity(bpy.types.Operator):
    """Generate an inward SDF iso-surface from the active evaluated mesh."""

    bl_idname = "silicone.generate_inner_cavity"
    bl_label = "Generate Inner Cavity"
    bl_description = "Generate a non-self-intersecting inner cavity with OpenVDB"
    bl_options = {"REGISTER", "UNDO"}

    cavity_inset: FloatProperty(  # type: ignore
        name="Cavity Inset",
        description="Distance from the evaluated source surface to the cavity",
        default=2.0,
        min=0.000001,
        soft_min=0.01,
        subtype="DISTANCE",
        unit="LENGTH",
    )
    quality: EnumProperty(  # type: ignore
        name="Quality",
        description="Voxel size relative to the cavity inset",
        items=(
            ("DRAFT", "Draft", "Voxel size = cavity inset / 2"),
            ("NORMAL", "Normal", "Voxel size = cavity inset / 4"),
            ("FINE", "Fine", "Voxel size = cavity inset / 8"),
        ),
        default="NORMAL",
    )
    max_estimated_voxels: IntProperty(  # type: ignore
        name="Maximum Estimated Voxels",
        description="Coarsen the voxel size if the padded domain exceeds this budget",
        default=DEFAULT_MAX_ESTIMATED_VOXELS,
        min=1_000_000,
        max=2_000_000_000,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        source = context.view_layer.objects.active
        return bool(source is not None and source.type == "MESH")

    def execute(self, context):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        source = context.view_layer.objects.active
        _refresh_hollower_ui(context, "starting inner cavity generation")
        try:
            cavity, voxel_size, requested_voxel_size, estimate = (
                generate_inner_cavity(
                    context,
                    source,
                    self.cavity_inset,
                    self.quality,
                    self.max_estimated_voxels,
                )
            )
        except Exception as exc:
            logger.exception("Inner cavity generation failed")
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        cavity.select_set(True)
        context.view_layer.objects.active = cavity
        _refresh_hollower_ui(context, "inner cavity generation complete")

        if voxel_size > requested_voxel_size * (1.0 + 1e-9):
            self.report(
                {"WARNING"},
                f"Generated {cavity.name}; resolution was limited to voxel size "
                f"{voxel_size:.6g} ({estimate:,} estimated voxels)",
            )
        else:
            self.report(
                {"INFO"},
                f"Generated {cavity.name} at voxel size {voxel_size:.6g}",
            )
        return {"FINISHED"}

    def invoke(self, context, event):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)


class SILICONE_OT_hollow(ModalProcessingOperator):
    """Hollow the active mesh using a temporary OpenVDB cavity."""

    bl_idname = "silicone.hollow"
    bl_label = "Hollow"
    bl_description = "Generate an inner cavity and subtract it from the selected mesh"
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
    modal_refresh_materials_on_redraw = False

    cavity_inset: FloatProperty(  # type: ignore
        name="Wall Thickness",
        description="Distance from the evaluated outer surface to the inner cavity",
        default=2.0,
        min=0.000001,
        soft_min=0.01,
        subtype="DISTANCE",
        unit="LENGTH",
    )
    quality: EnumProperty(  # type: ignore
        name="Quality",
        description="Voxel size relative to the wall thickness",
        items=(
            ("DRAFT", "Draft", "Voxel size = wall thickness / 2"),
            ("NORMAL", "Normal", "Voxel size = wall thickness / 4"),
            ("FINE", "Fine", "Voxel size = wall thickness / 8"),
        ),
        default="NORMAL",
    )
    open_bottom: BoolProperty(  # type: ignore
        name="Open Bottom",
        description=(
            "Compare the patron and cavity bottom cut faces, reduce the smaller "
            "one by the wall thickness, and open the bottom"
        ),
        default=True,
    )
    max_estimated_voxels: IntProperty(  # type: ignore
        name="Maximum Estimated Voxels",
        description="Coarsen the voxel size if the padded domain exceeds this budget",
        default=DEFAULT_MAX_ESTIMATED_VOXELS,
        min=1_000_000,
        max=2_000_000_000,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        patron = context.scene.objects.get("patron")
        return bool(
            context.mode == "OBJECT"
            and (context.object is not None or patron is not None)
        )

    def _create_modal_step_iterator(self, context):
        self._hollow_result = {"FINISHED"}

        def remember_result(result):
            self._hollow_result = result
            return result

        yield (
            "Hollowing",
            lambda: self._begin_hollow_operation(context).then(remember_result),
        )
        return self._hollow_result

    def execute(self, context):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        return finish_task_sync(self._begin_hollow_operation(context))

    def _begin_hollow_operation(self, context):
        sequence = BackgroundTaskSequence(self._hollow_operation_steps(context))
        sequence.redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
        return sequence

    def _hollow_operation_steps(self, context):
        source = _resolve_hollow_target(context)
        if source is None:
            message = "Select a valid mesh object"
            self.report({"ERROR"}, message)
            show_popup(message, title="Invalid Selection")
            return {"CANCELLED"}

        _refresh_hollower_ui(context, "starting hollow operation")
        backup_start = time.perf_counter()
        existing_backup = bpy.data.objects.get("backup")
        backup = ensure_direct_patron_backup()
        logger.info(
            "Hollow master backup preparation: status=%s backup=%s elapsed=%.3fs",
            (
                "reused"
                if backup is not None and backup is existing_backup
                else "created"
                if backup is not None
                else "unavailable"
            ),
            backup.name if backup is not None else "none",
            time.perf_counter() - backup_start,
        )
        _refresh_hollower_ui(context, "after backup preparation")
        temporary_analysis_object = None
        try:
            temporary_analysis_object = (
                _create_temporary_hollow_analysis_object(context, source)
            )
            voxel_size, requested_voxel_size, estimate = yield begin_hollow_object(
                context,
                source,
                self.cavity_inset,
                self.quality,
                self.max_estimated_voxels,
                self.open_bottom,
                cavity_source=(
                    temporary_analysis_object.object
                    if temporary_analysis_object is not None
                    else None
                ),
            )
        finally:
            _remove_temporary_hollow_analysis_object(temporary_analysis_object)

        source.select_set(True)
        context.view_layer.objects.active = source
        _refresh_hollower_ui(context, "hollow operation complete")

        if voxel_size > requested_voxel_size * (1.0 + 1e-9):
            self.report(
                {"WARNING"},
                f"Hollowed {source.name}; resolution was limited to voxel size "
                f"{voxel_size:.6g} ({estimate:,} estimated voxels)",
            )
        else:
            self.report(
                {"INFO"},
                f"Hollowed {source.name} at voxel size {voxel_size:.6g}",
            )
        result = {"FINISHED"}
        return result

    def invoke(self, context, event):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)


class SILICONE_OT_convert_to_planter(ModalProcessingOperator):
    """Hollow the active mesh, open its top, and trim the finished rim."""

    bl_idname = "silicone.convert_to_planter"
    bl_label = "Convert to Planter"
    bl_description = (
        "Hollow the selected mesh, open the cavity through the top, and trim "
        "the finished top"
    )
    bl_options = {"REGISTER", "UNDO"}
    modal_show_progress_overlay = True
    modal_wait_redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
    modal_refresh_materials_on_redraw = False

    cavity_inset: FloatProperty(  # type: ignore
        name="Wall Thickness",
        description="Distance from the evaluated outer surface to the inner cavity",
        default=2.0,
        min=0.000001,
        soft_min=0.01,
        subtype="DISTANCE",
        unit="LENGTH",
    )
    quality: EnumProperty(  # type: ignore
        name="Quality",
        description="Voxel size relative to the wall thickness",
        items=(
            ("DRAFT", "Draft", "Voxel size = wall thickness / 2"),
            ("NORMAL", "Normal", "Voxel size = wall thickness / 4"),
            ("FINE", "Fine", "Voxel size = wall thickness / 8"),
        ),
        default="NORMAL",
    )
    top_cut_amount: FloatProperty(  # type: ignore
        name="Top Cut",
        description="Amount removed from the original top after hollowing",
        default=10.0,
        min=0.000001,
        soft_min=0.25,
        subtype="DISTANCE",
        unit="LENGTH",
    )
    max_estimated_voxels: IntProperty(  # type: ignore
        name="Maximum Estimated Voxels",
        description="Coarsen the voxel size if the padded domain exceeds this budget",
        default=DEFAULT_MAX_ESTIMATED_VOXELS,
        min=1_000_000,
        max=2_000_000_000,
        options={"HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        patron = context.scene.objects.get("patron")
        return bool(
            context.mode == "OBJECT"
            and (context.object is not None or patron is not None)
        )

    def _create_modal_step_iterator(self, context):
        self._planter_result = {"FINISHED"}

        def remember_result(result):
            self._planter_result = result
            return result

        yield (
            "Converting to planter",
            lambda: self._begin_planter_operation(context).then(remember_result),
        )
        return self._planter_result

    def execute(self, context):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        return finish_task_sync(self._begin_planter_operation(context))

    def _begin_planter_operation(self, context):
        sequence = BackgroundTaskSequence(self._planter_operation_steps(context))
        sequence.redraw_interval = _HOLLOWER_WORKER_REDRAW_INTERVAL
        return sequence

    def _planter_operation_steps(self, context):
        source = _resolve_hollow_target(context)
        if source is None:
            message = "Select a valid mesh object"
            self.report({"ERROR"}, message)
            show_popup(message, title="Invalid Selection")
            return {"CANCELLED"}

        _refresh_hollower_ui(context, "starting planter conversion")
        backup_start = time.perf_counter()
        existing_backup = bpy.data.objects.get("backup")
        backup = ensure_direct_patron_backup()
        logger.info(
            "Planter master backup preparation: status=%s backup=%s elapsed=%.3fs",
            (
                "reused"
                if backup is not None and backup is existing_backup
                else "created"
                if backup is not None
                else "unavailable"
            ),
            backup.name if backup is not None else "none",
            time.perf_counter() - backup_start,
        )
        _refresh_hollower_ui(context, "after planter backup preparation")

        voxel_size, requested_voxel_size, estimate = (
            yield begin_convert_object_to_planter(
                context,
                source,
                cavity_inset=self.cavity_inset,
                quality=self.quality,
                max_estimated_voxels=self.max_estimated_voxels,
                top_cut_amount=self.top_cut_amount,
            )
        )

        source.select_set(True)
        context.view_layer.objects.active = source
        _refresh_hollower_ui(context, "planter conversion complete")

        if voxel_size > requested_voxel_size * (1.0 + 1e-9):
            self.report(
                {"WARNING"},
                f"Converted {source.name} to a planter; resolution was limited "
                f"to voxel size {voxel_size:.6g} ({estimate:,} estimated voxels)",
            )
        else:
            self.report(
                {"INFO"},
                f"Converted {source.name} to a planter at voxel size "
                f"{voxel_size:.6g}",
            )
        result = {"FINISHED"}
        return result

    def invoke(self, context, event):
        if not _require_core_hollower_access():
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self)


CLASSES = (
    SILICONE_OT_generate_inner_cavity,
    SILICONE_OT_hollow,
    SILICONE_OT_convert_to_planter,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
