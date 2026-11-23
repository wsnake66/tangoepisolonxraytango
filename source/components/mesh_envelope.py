from ..object import Object
from .geometry_adapter import WorkerMeshEnvelope, begin_worker_mesh_envelope


class MeshEnvelope(WorkerMeshEnvelope):
    """Base mesh envelope with intermediate remeshes executed by the worker."""

    def __init__(
        self,
        target: Object,
        voxel_size: float = 1,
        distance: float = 6,
        n_wraps: int = 3,
        name_adder: str = "",
        geometry_to_origin: bool = False,
        cut_bot: bool = True,
        build_from_sphere: bool = False,
        normal_offset: float = 2,
        remesh_scaled: bool = True,
        sphere_voxel_factor: float = 2,
        sphere_size_factor: float = 1.0,
        sphere_height_factor: float | None = None,
        cut_top_bf_wrap: bool = False,
        smooth_after_wrap: bool = True,
        target_cache_object=None,
        simplify_target_reduction: float | None = None,
    ):
        super().__init__(
            target,
            voxel_size,
            distance,
            n_wraps,
            algorithm="BASE",
            name_adder=name_adder,
            geometry_to_origin=geometry_to_origin,
            cut_bot=cut_bot,
            build_from_sphere=build_from_sphere,
            normal_offset=normal_offset,
            remesh_scaled=remesh_scaled,
            sphere_voxel_factor=sphere_voxel_factor,
            sphere_size_factor=sphere_size_factor,
            sphere_height_factor=sphere_height_factor,
            cut_top_bf_wrap=cut_top_bf_wrap,
            smooth_after_wrap=smooth_after_wrap,
            target_cache_object=target_cache_object,
            simplify_target_reduction=simplify_target_reduction,
        )


class OptimizedMeshEnvelope(MeshEnvelope):
    """Optimized mesh envelope with one final Blender voxel remesh."""

    def __init__(
        self,
        target: Object,
        voxel_size: float = 1,
        distance: float = 6,
        n_wraps: int = 3,
        name_adder: str = "",
        geometry_to_origin: bool = False,
        cut_bot: bool = True,
        build_from_sphere: bool = False,
        normal_offset: float = 2,
        remesh_scaled: bool = True,
        sphere_voxel_factor: float = 2,
        cut_top_bf_wrap: bool = False,
        smooth_after_wrap: bool = True,
        target_cache_object=None,
        simplify_target_reduction: float | None = None,
    ):
        del sphere_voxel_factor
        WorkerMeshEnvelope.__init__(
            self,
            target,
            voxel_size,
            distance,
            n_wraps,
            algorithm="OPTIMIZED",
            name_adder=name_adder,
            geometry_to_origin=geometry_to_origin,
            cut_bot=cut_bot,
            build_from_sphere=build_from_sphere,
            normal_offset=normal_offset,
            remesh_scaled=remesh_scaled,
            sphere_voxel_factor=2.0,
            cut_top_bf_wrap=cut_top_bf_wrap,
            smooth_after_wrap=smooth_after_wrap,
            target_cache_object=target_cache_object,
            simplify_target_reduction=simplify_target_reduction,
        )


def begin_mesh_envelope(
    target: Object,
    voxel_size: float = 1,
    distance: float = 6,
    n_wraps: int = 3,
    **kwargs,
):
    return begin_worker_mesh_envelope(
        target,
        voxel_size,
        distance,
        n_wraps,
        algorithm="BASE",
        **kwargs,
    )


def begin_optimized_mesh_envelope(
    target: Object,
    voxel_size: float = 1,
    distance: float = 6,
    n_wraps: int = 3,
    **kwargs,
):
    kwargs.pop("sphere_voxel_factor", None)
    return begin_worker_mesh_envelope(
        target,
        voxel_size,
        distance,
        n_wraps,
        algorithm="OPTIMIZED",
        sphere_voxel_factor=2.0,
        **kwargs,
    )
