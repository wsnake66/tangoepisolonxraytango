import bpy  # type: ignore
import mathutils  # type: ignore
from ..object import Object
from ..background_worker import BackgroundTaskSequence
from ..environment import get_server_base_url
from ..voxel_size import get_filler_voxel_size
from ..materials import assign_material, get_or_create_simple_material
from .server import import_server_response, request_server, request_server_async


def request_base_filler(
    target: Object, voxel_size: float, offset: float, patron_min_z: float
) -> Object:
    response = request_server(
        f"{get_server_base_url()}/fill-master-base/",
        [target.name],
        params={
            "voxel_size": voxel_size,
            "offset": offset,
            "patron_min_z": patron_min_z,
        },
    )
    imported_objects = import_server_response(response)
    if len(imported_objects) != 1:
        imported_names = ", ".join(
            obj.name for obj in imported_objects if getattr(obj, "name", None)
        )
        raise ValueError(
            "Server response must include exactly one base filler mesh. "
            f"Imported objects: {imported_names or 'none'}"
        )

    return Object(imported_objects[0])


def request_base_filler_async(
    target: Object,
    voxel_size: float,
    offset: float,
    patron_min_z: float,
    *,
    on_complete=None,
    on_finish=None,
):
    def complete(response):
        imported_objects = import_server_response(response)
        if len(imported_objects) != 1:
            imported_names = ", ".join(
                obj.name for obj in imported_objects if getattr(obj, "name", None)
            )
            raise ValueError(
                "Server response must include exactly one base filler mesh. "
                f"Imported objects: {imported_names or 'none'}"
            )
        base_filler = Object(imported_objects[0])
        if on_complete is not None:
            on_complete(base_filler)
        return base_filler

    return request_server_async(
        f"{get_server_base_url()}/fill-master-base/",
        [target.name],
        params={
            "voxel_size": voxel_size,
            "offset": offset,
            "patron_min_z": patron_min_z,
        },
        on_complete=complete,
        on_finish=on_finish,
    )


def _prepare_base_filler_target(
    target: Object,
    context,
    offset: float,
    quality: str | None = None,
):
    original_target_name = target.name
    patron_raw = bpy.data.objects.get("patron")
    patron_min_z = (
        Object(patron_raw).min_z
        if patron_raw is not None and patron_raw.type == "MESH"
        else target.min_z
    )
    target.name = "base_filler_target"
    # target.scale_normals(-1)
    voxel_size = get_filler_voxel_size(
        quality or context.scene.pro_master_filler_quality,
        target,
    )
    return original_target_name, patron_min_z, voxel_size


def _align_base_filler_min_z(base_filler: Object, final_min_z: float) -> None:
    """Translate the completed filler so its world-space bottom reaches final_min_z."""
    z_delta = final_min_z - base_filler.min_z
    base_filler.object.matrix_world = (
        mathutils.Matrix.Translation((0.0, 0.0, z_delta))
        @ base_filler.object.matrix_world
    )


def _finish_base_filler(
    base_filler: Object,
    original_target_name: str,
    patron_min_z: float,
    offset: float,
) -> None:
    base_filler.smooth_geometry(repeat=5)
    _finish_base_filler_after_smooth(
        base_filler,
        original_target_name,
        patron_min_z,
        offset,
    )


def _finish_base_filler_after_smooth(
    base_filler: Object,
    original_target_name: str,
    patron_min_z: float,
    offset: float,
) -> None:
    base_filler.name = f"{original_target_name}_base_filler"
    assign_material(
        base_filler.object,
        get_or_create_simple_material("MB_MasterBaseFiller", "#8B5A2BFF"),
    )
    base_filler.origin_to_geometry()
    base_filler.clean_bot(1)
    # The server result can arrive with a different object origin than the
    # exported target. Enforce the requested final position in world space
    # after every geometry-changing operation.
    _align_base_filler_min_z(base_filler, patron_min_z - offset)


def fill_master_base(
    target: Object,
    context,
    offset: float = 0.0,
    *,
    quality: str | None = None,
) -> Object:
    """Duplicate the target and remove the copy's bottom slice."""
    original_target_name, patron_min_z, voxel_size = _prepare_base_filler_target(
        target,
        context,
        offset,
        quality,
    )

    base_filler = request_base_filler(
        target,
        voxel_size=voxel_size,
        offset=offset,
        patron_min_z=patron_min_z,
    )
    _finish_base_filler(
        base_filler,
        original_target_name,
        patron_min_z,
        offset,
    )
    target.remove()
    # base_filler_cos = base_filler.center_coords

    # base_filler.cut_plane(
    #     mathutils.Vector((0, 0, -1)),
    #     mathutils.Vector((base_filler_cos.x, base_filler_cos.y, sil_min_z + 0.05)),
    # )

    return target


def fill_master_base_async(
    target: Object,
    context,
    offset: float = 0.0,
    *,
    quality: str | None = None,
    on_complete=None,
    on_finish=None,
):
    original_target_name, patron_min_z, voxel_size = _prepare_base_filler_target(
        target,
        context,
        offset,
        quality,
    )

    request = request_base_filler_async(
        target,
        voxel_size=voxel_size,
        offset=offset,
        patron_min_z=patron_min_z,
    )

    def steps():
        try:
            base_filler = yield request
            yield base_filler.begin_smooth_geometry(repeat=5)
            _finish_base_filler_after_smooth(
                base_filler,
                original_target_name,
                patron_min_z,
                offset,
            )
            if on_complete is not None:
                on_complete(base_filler)
            return base_filler
        finally:
            if target.object.name in bpy.data.objects:
                target.remove()
            if on_finish is not None:
                on_finish()

    return BackgroundTaskSequence(steps())
