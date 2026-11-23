import logging

import mathutils  # type: ignore
import bpy  # type: ignore
from ..background_worker import BackgroundTaskSequence, finish_task_sync
from ..object import Object, remove_objects_safely
from ..environment import get_server_base_url
from ..materials import assign_material, get_or_create_simple_material
from .mesh_envelope import begin_mesh_envelope
from .server import import_server_response, request_server, request_server_async
from ..modifiers import build_voxel_modifier
from ..voxel_size import get_filler_voxel_size


logger = logging.getLogger(__name__)


def _has_mesh_geometry(obj: Object) -> bool:
    blender_obj = getattr(obj, "object", obj)
    data = getattr(blender_obj, "data", None)
    return bool(
        data is not None
        and getattr(data, "vertices", None) is not None
        and len(data.vertices) > 0
        and getattr(data, "polygons", None) is not None
        and len(data.polygons) > 0
    )


def _subtract_if_nonempty(target: Object, cutter: Object) -> bool:
    """Subtract only valid mesh operands and report whether target remains."""
    if not _has_mesh_geometry(target):
        return False
    if not _has_mesh_geometry(cutter):
        return True
    target -= cutter
    return _has_mesh_geometry(target)


def _get_imported_filler(imported_objects, name_keyword: str) -> Object:
    for imported_object in imported_objects:
        if name_keyword in imported_object.name.casefold():
            return Object(imported_object)
    imported_names = ", ".join(obj.name for obj in imported_objects)
    raise ValueError(
        f"Server response did not include '{name_keyword}' filler. "
        f"Imported objects: {imported_names or 'none'}"
    )


def _set_hidden(obj, hidden: bool) -> None:
    blender_obj = getattr(obj, "object", obj)
    if blender_obj is None or blender_obj.name not in bpy.data.objects:
        return
    blender_obj.hide_set(hidden)
    blender_obj.hide_viewport = hidden
    blender_obj.hide_render = hidden


def _set_hidden_for_objects(objects, hidden: bool) -> None:
    for obj in objects:
        _set_hidden(obj, hidden)


def _set_hide_during_ui_refresh_for_wrappers(objects) -> None:
    for obj in objects:
        obj.hide_during_ui_breathe = True


def request_build_all_fillers(
    abstracted_target: Object,
    voxel_size: float,
    *,
    hide_intermediates: bool = False,
):
    response = request_server(
        f"{get_server_base_url()}/build-all-fillers/",
        [abstracted_target.name],
        params={"box_voxel_size": voxel_size},
    )
    return _finish_build_all_fillers_response(
        response,
        voxel_size,
        hide_intermediates=hide_intermediates,
    )


def request_build_all_fillers_async(
    abstracted_target: Object,
    voxel_size: float,
    *,
    hide_intermediates: bool = False,
    on_complete=None,
    on_finish=None,
):
    request = request_server_async(
        f"{get_server_base_url()}/build-all-fillers/",
        [abstracted_target.name],
        params={"box_voxel_size": voxel_size},
    )

    def steps():
        try:
            response = yield request
            prepared = _prepare_build_all_fillers_response(
                response,
                voxel_size,
                hide_intermediates=hide_intermediates,
            )
            if _has_mesh_geometry(prepared["cavities"]):
                protection = yield _begin_cavity_protection_envelope(
                    prepared["cavities"],
                    voxel_size,
                )
            else:
                protection = None
            fillers = _finish_prepared_fillers(prepared, protection)
            if on_complete is not None:
                on_complete(fillers)
            return fillers
        finally:
            if on_finish is not None:
                on_finish()

    return BackgroundTaskSequence(steps())


def _finish_build_all_fillers_response(
    response,
    voxel_size: float,
    *,
    hide_intermediates: bool = False,
):
    prepared = _prepare_build_all_fillers_response(
        response,
        voxel_size,
        hide_intermediates=hide_intermediates,
    )
    protection = None
    if _has_mesh_geometry(prepared["cavities"]):
        protection = finish_task_sync(
            _begin_cavity_protection_envelope(
                prepared["cavities"],
                voxel_size,
            )
        )
    return _finish_prepared_fillers(prepared, protection)


def _prepare_build_all_fillers_response(
    response,
    voxel_size: float,
    *,
    hide_intermediates: bool = False,
):
    imported_objects = import_server_response(response)

    tight_filler = _get_imported_filler(imported_objects, "tight")
    cavity_filler = _get_imported_filler(imported_objects, "cavity")
    air_traps_filler = _get_imported_filler(imported_objects, "air")
    cleaner = _get_imported_filler(imported_objects, "cleaner")
    if hide_intermediates:
        _set_hide_during_ui_refresh_for_wrappers(
            [tight_filler, cavity_filler, air_traps_filler, cleaner]
        )
    cleaner.apply_modifier(build_voxel_modifier(voxel_size))
    cavities = cavity_filler.duplicate(name_adder="_cavities")
    _subtract_if_nonempty(cavities, cleaner)
    if not _has_mesh_geometry(cavities):
        logger.info(
            "Skipping cavity protection envelope because cavity subtraction "
            "produced an empty mesh"
        )
    return {
        "tight_filler": tight_filler,
        "cavity_filler": cavity_filler,
        "air_traps_filler": air_traps_filler,
        "cleaner": cleaner,
        "cavities": cavities,
    }


def _begin_cavity_protection_envelope(cavities: Object, voxel_size: float):
    return begin_mesh_envelope(
        cavities,
        voxel_size=voxel_size,
        distance=1.5,
        n_wraps=1,
        name_adder="_o",
        geometry_to_origin=False,
        cut_bot=False,
        build_from_sphere=False,
        normal_offset=1,
        remesh_scaled=True,
    )


def _finish_prepared_fillers(prepared, protection):
    tight_filler = prepared["tight_filler"]
    cavity_filler = prepared["cavity_filler"]
    air_traps_filler = prepared["air_traps_filler"]
    cleaner = prepared["cleaner"]
    cavities = prepared["cavities"]
    if protection is not None:
        _subtract_if_nonempty(cleaner, protection)
        protection.remove()
    cavities.remove()
    _subtract_if_nonempty(cavity_filler, cleaner)
    _subtract_if_nonempty(air_traps_filler, cleaner)  # testing
    cleaner.remove()
    assign_material(
        tight_filler.object,
        get_or_create_simple_material("MB_TightFiller", "#49FF83FF"),
    )
    assign_material(
        cavity_filler.object,
        get_or_create_simple_material("MB_CavityFiller", "#0F99E9FF"),
    )
    assign_material(
        air_traps_filler.object,
        get_or_create_simple_material("MB_AirTrapsFiller", "#E28B09FF"),
    )

    return tight_filler, cavity_filler, air_traps_filler


def _prepare_all_fillers_target(
    target: Object,
    context,
    *,
    quality: str | None = None,
    hide_during_prepare: bool = False,
) -> tuple[Object, float]:
    scene = context.scene
    voxel_size = get_filler_voxel_size(
        quality or scene.pro_master_filler_quality,
        target,
    )

    abstracted_target = target.duplicate(name_adder="_abstracted")
    abstracted_target.hide_during_ui_breathe = hide_during_prepare
    abstracted_target.scale_normals(-0.3)
    abstracted_target.apply_modifier(build_voxel_modifier(voxel_size * 0.75))
    abstracted_target.name = "abstracted_target"
    return abstracted_target, voxel_size


def prepare_abstracted_target(
    target: Object,
    context,
    *,
    quality: str | None = None,
    hide_during_prepare: bool = False,
) -> tuple[Object, float]:
    """Build the voxel-remeshed upload reference used by Smart Sealer."""
    return _prepare_all_fillers_target(
        target,
        context,
        quality=quality,
        hide_during_prepare=hide_during_prepare,
    )


def _begin_prepare_all_fillers_target(
    target: Object,
    context,
    *,
    quality: str | None = None,
    hide_during_prepare: bool = False,
):
    scene = context.scene
    voxel_size = get_filler_voxel_size(
        quality or scene.pro_master_filler_quality,
        target,
    )
    abstracted_target = target.duplicate(name_adder="_abstracted")
    abstracted_target.hide_during_ui_breathe = hide_during_prepare
    task = abstracted_target.begin_scale_normals(-0.3)

    def finish(_target):
        abstracted_target.apply_modifier(
            build_voxel_modifier(voxel_size * 0.75)
        )
        abstracted_target.name = "abstracted_target"
        return abstracted_target

    return task.then(finish), abstracted_target, voxel_size


def _finish_all_fillers(
    fillers: tuple[Object, Object, Object],
    abstracted_target: Object,
    target: Object,
    voxel_size: float,
    *,
    hide_intermediates: bool = False,
):
    tight_filler, cavity_filler, air_traps_filler = fillers
    if hide_intermediates:
        _set_hide_during_ui_refresh_for_wrappers(
            [abstracted_target, tight_filler, cavity_filler, air_traps_filler]
        )

    _subtract_if_nonempty(air_traps_filler, abstracted_target)
    _subtract_if_nonempty(air_traps_filler, cavity_filler)
    _subtract_if_nonempty(air_traps_filler, tight_filler)
    _subtract_if_nonempty(cavity_filler, abstracted_target)
    _subtract_if_nonempty(tight_filler, abstracted_target)

    result_fillers = []
    for filler in [tight_filler, cavity_filler, air_traps_filler]:
        result_fillers.extend(
            split_and_filter(filler, target, volume_th=0.01, voxel_size=voxel_size)
        )

    if hide_intermediates:
        _set_hidden_for_objects(result_fillers, True)
    return result_fillers


def build_all_fillers(
    target: Object,
    context,
    *,
    quality: str | None = None,
    hide_until_complete: bool = False,
):
    abstracted_target, voxel_size = _prepare_all_fillers_target(
        target,
        context,
        quality=quality,
        hide_during_prepare=hide_until_complete,
    )
    try:
        fillers = request_build_all_fillers(
            abstracted_target,
            voxel_size=voxel_size,
            hide_intermediates=hide_until_complete,
        )
        result_fillers = _finish_all_fillers(
            fillers,
            abstracted_target,
            target,
            voxel_size,
            hide_intermediates=hide_until_complete,
        )
        if hide_until_complete:
            _set_hidden_for_objects(result_fillers, False)
    finally:
        abstracted_target.remove()


def build_all_fillers_async(
    target: Object,
    context,
    *,
    quality: str | None = None,
    hide_until_complete: bool = False,
    on_complete=None,
    on_finish=None,
):
    prepare_task, abstracted_target, voxel_size = _begin_prepare_all_fillers_target(
        target,
        context,
        quality=quality,
        hide_during_prepare=hide_until_complete,
    )

    if hide_until_complete:
        _set_hidden(abstracted_target, True)

    def steps():
        try:
            yield prepare_task
            request = request_build_all_fillers_async(
                abstracted_target,
                voxel_size=voxel_size,
                hide_intermediates=hide_until_complete,
            )
            fillers = yield request
            result_fillers = _finish_all_fillers(
                fillers,
                abstracted_target,
                target,
                voxel_size,
                hide_intermediates=hide_until_complete,
            )
            if hide_until_complete:
                _set_hidden_for_objects(result_fillers, False)
            if on_complete is not None:
                on_complete()
            return result_fillers
        finally:
            if abstracted_target.object.name in bpy.data.objects:
                remove_objects_safely((abstracted_target.object,))
            if on_finish is not None:
                on_finish()

    return BackgroundTaskSequence(steps())


def split_and_filter(
    target: Object, original_target: Object, volume_th: float = 1, voxel_size: float = 1
):
    if not _has_mesh_geometry(target):
        logger.info("Discarding empty filler mesh: %s", target.name)
        target.remove()
        return []
    if target.min_z < original_target.min_z:
        target_co = target.center_coords
        target_co.z = original_target.min_z + 0.01
        target.cut_plane(
            plane_normal=mathutils.Vector((0, 0, -1)),
            plane_point=target_co,
        )
        if not _has_mesh_geometry(target):
            logger.info("Discarding filler emptied by bottom cut: %s", target.name)
            target.remove()
            return []
    kept_fillers = []
    for filler in target.split_isolated_meshes():
        if not _has_mesh_geometry(filler) or filler.volume < volume_th:
            filler.remove()
        else:
            # filler.apply_modifier(build_voxel_modifier(voxel_size))
            filler.origin_to_geometry()
            kept_fillers.append(filler)
    return kept_fillers


FILLER_TYPE_KEYWORDS = {
    "GREEN": "tight",
    "BLUE": "cavity",
    "ORANGE": "air",
}


def remove_fillers_by_type(filler_type: str) -> int:
    """Remove generated filler objects matching the selected color/type."""
    keyword = FILLER_TYPE_KEYWORDS.get(str(filler_type).upper())
    if not keyword:
        raise ValueError(f"Unknown filler type: {filler_type}")

    objects_to_remove = [
        obj for obj in bpy.data.objects if keyword in obj.name.casefold()
    ]
    for obj in objects_to_remove:
        if obj.name in bpy.data.objects:
            remove_objects_safely((obj,))

    return len(objects_to_remove)


def confirm_filler(context, quality: str | None = None) -> Object:
    """Trim each filler to the patron base, then mesh-join it to patron."""
    patron_raw = bpy.data.objects.get("patron")
    if patron_raw is None or patron_raw.type != "MESH":
        raise ValueError("No patron object found")

    filler_objects = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH" and "filler" in obj.name.casefold()
    ]
    if not filler_objects:
        raise ValueError("No filler objects found")

    patron = Object(patron_raw)
    retry_voxel_size = (
        get_filler_voxel_size(
            quality or context.scene.pro_master_filler_quality,
            patron,
        )
        * 0.2
    )
    fillers = [Object(filler_object) for filler_object in filler_objects]

    previous_hide_select = bool(getattr(patron.object, "hide_select", False))
    patron.object.hide_select = False
    try:
        for filler in fillers:
            if filler.min_z >= patron.min_z:
                continue
            cut_point = filler.center_coords
            cut_point.z = patron.min_z
            filler.cut_plane(
                plane_normal=mathutils.Vector((0, 0, -1)),
                plane_point=cut_point,
                retry_remesh=build_voxel_modifier(retry_voxel_size),
            )

        patron_name = patron.name
        try:
            for filler in fillers:
                if filler.object.name not in bpy.data.objects:
                    continue
                patron.join(filler)
        finally:
            patron.name = patron_name
    finally:
        patron.object.hide_select = (
            False if previous_hide_select else previous_hide_select
        )

    patron.select()
    return patron
