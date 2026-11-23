import logging
import bpy  # type: ignore
import mathutils  # type: ignore
import math
import time
from contextlib import contextmanager


from .standalone_inner_cavity_finish import (
    SILICONE_DISPLACEMENT_CUTTER_MARKER,
    finish_inner_cavity_from_scene,
)
from ..silicone_mix import silicone_mix_engraving
from ..modifiers import (
    build_sharp_modifier,
    build_voxel_modifier,
    diff_mod,
    diff_no_material_transfer_mod,
    union_mod,
)
from ..environment import get_server_base_url
from .mesh_envelope import MeshEnvelope, begin_optimized_mesh_envelope
from .server import request_server, request_server_async, import_server_response
from ..object import Object, suppress_ui_breathe, remove_objects_safely
from ..background_worker import BackgroundTaskSequence, finish_task_sync
from .clear_undercuts import begin_clear_undercuts
from .silicone_mold import (
    hide_silicone_mold_preview,
    reveal_silicone_mold_preview,
)
from .watermark_mesh_server import (
    request_weight_text_mesh,
    request_weight_text_mesh_async,
)
from .watermark_payload import calculate_casting_volume
from ..materials import assign_inner_core_material, assign_moldbox_material
from ..voxel_size import get_box_voxel_size
from ..progress import breathe_viewport
from ._q7x import (
    mirror_pending_casting_addition,
    mirror_pending_casting_subtraction,
)
from .base_substracter_visibility import is_base_substracter_object
from .base import subtract_weight_text_with_validation

logger = logging.getLogger(__name__)

INNER_CORE_BOX_INTERSECTION_QUALITY = "FAST"
INNER_CORE_REFERENCE_OBJECT_NAMES = ("w", "extr")
INNER_CORE_TRANSIENT_OBJECT_NAME_PARTS = (
    "_w",
    "_ref",
    "box_ref",
    "optimized_cut",
    "face_prism",
    "inner_cavity_standalone_core",
    "inner_core",
    "attacher",
    "attach_socket",
    "to_add",
    "to_cut",
    "to_sub",
)


def _inner_core_secret_objects() -> list[bpy.types.Object]:
    secret_objects = []
    for obj in bpy.data.objects:
        normalized_name = obj.name.lower()
        if normalized_name in INNER_CORE_REFERENCE_OBJECT_NAMES or any(
            name_part in normalized_name
            for name_part in INNER_CORE_TRANSIENT_OBJECT_NAME_PARTS
        ):
            secret_objects.append(obj)
    return secret_objects


def _draw_inner_core_progress(
    generation_start: float | None = None,
    label: str | None = None,
) -> None:
    visibility_state = []
    for obj in _inner_core_secret_objects():
        visibility_state.append(
            (
                obj,
                obj.hide_get(),
                bool(getattr(obj, "hide_viewport", False)),
                bool(getattr(obj, "hide_render", False)),
            )
        )
        obj.hide_set(True)
        obj.hide_viewport = True
        obj.hide_render = True
    try:
        breathe_viewport()
        _log_inner_core_draw_timing(generation_start, label)
    finally:
        for obj, was_hidden, was_hide_viewport, was_hide_render in visibility_state:
            if obj.name not in bpy.data.objects:
                continue
            obj.hide_set(was_hidden)
            obj.hide_viewport = was_hide_viewport
            obj.hide_render = was_hide_render


def _log_inner_core_draw_timing(
    generation_start: float | None,
    label: str | None,
) -> None:
    if generation_start is None:
        logger.info("Inner core draw performed: label=%s", label or "unknown")
        return

    elapsed = max(time.perf_counter() - generation_start, 0)
    seconds = int(elapsed)
    centiseconds = int((elapsed - seconds) * 100)
    logger.info(
        "Inner core draw at second %d:%02d: label=%s",
        seconds,
        centiseconds,
        label or "unknown",
    )


def _hide_inner_core_reference_objects() -> None:
    for name in INNER_CORE_REFERENCE_OBJECT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.hide_set(True)
        obj.hide_viewport = True
        obj.hide_render = True


def _set_inner_core_object_hidden(obj, hidden: bool) -> None:
    blender_object = getattr(obj, "object", obj)
    blender_object.hide_set(hidden)
    blender_object.hide_viewport = hidden
    blender_object.hide_render = hidden


@contextmanager
def _inner_core_processing_visibility(*objects):
    visibility_state = []
    for obj in objects:
        blender_object = getattr(obj, "object", obj)
        visibility_state.append(
            (
                blender_object,
                blender_object.hide_get(),
                bool(getattr(blender_object, "hide_viewport", False)),
                bool(getattr(blender_object, "hide_render", False)),
            )
        )
        blender_object.hide_viewport = False
        blender_object.hide_set(False)
        blender_object.hide_render = False
    try:
        with suppress_ui_breathe():
            yield
    finally:
        for (
            blender_object,
            was_hidden,
            was_hide_viewport,
            was_hide_render,
        ) in visibility_state:
            if blender_object.name not in bpy.data.objects:
                continue
            blender_object.hide_set(was_hidden)
            blender_object.hide_viewport = was_hide_viewport
            blender_object.hide_render = was_hide_render


def _remove_inner_core_reference_objects() -> None:
    for name in INNER_CORE_REFERENCE_OBJECT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            remove_objects_safely((obj,))


def _remove_silicone_displacement_cutters() -> None:
    for obj in list(bpy.data.objects):
        if bool(obj.get(SILICONE_DISPLACEMENT_CUTTER_MARKER, False)):
            remove_objects_safely((obj,))


def _create_ref_steps(context):
    generation_start = time.perf_counter()
    patron = Object(bpy.data.objects.get("patron"))
    box_voxel_size = get_box_voxel_size(context.scene.box_quality, patron)
    if int(context.scene.pro_inner_cavity_sensitivity) == 1:
        smooth_after_wrap = False
    else:
        smooth_after_wrap = True
    with suppress_ui_breathe():
        w = yield begin_optimized_mesh_envelope(
            patron,
            voxel_size=box_voxel_size,
            distance=0,
            n_wraps=int(context.scene.pro_inner_cavity_sensitivity),
            name_adder="_w",
            cut_bot=False,
            build_from_sphere=True,
            cut_top_bf_wrap=True,
            smooth_after_wrap=smooth_after_wrap,
        )

    w.name = "w"
    w.hide_during_ui_breathe = True
    _set_inner_core_object_hidden(w, True)
    _draw_inner_core_progress(generation_start, "wrapped patron reference")
    with suppress_ui_breathe():
        box_ref = yield begin_optimized_mesh_envelope(
            patron,
            voxel_size=box_voxel_size,
            distance=context.scene.box_gap,
            n_wraps=2,
            name_adder="_ref",
            cut_bot=False,
            remesh_scaled=True,
        )
    box_ref.name = "box_ref"
    box_ref.hide_during_ui_breathe = True
    _set_inner_core_object_hidden(box_ref, True)
    _draw_inner_core_progress(generation_start, "box reference")
    _draw_inner_core_progress(generation_start, "clearing extraction reference")
    with _inner_core_processing_visibility(box_ref):
        yield begin_clear_undercuts(
            target_object=box_ref,
            bidirectional=False,
            voxel_size=box_voxel_size * 0.9,
            target_retry_voxel_size=box_voxel_size * 0.9,
            target_point=mathutils.Vector((0, 0, w.min_z)),
            plane_direction=mathutils.Vector((0, 0, 1)),
            clearance_build_overtravel_override=1.0,
            display_extraction_directions=False,
        )
    extr = box_ref
    extr.name = "extr"
    extr.hide_during_ui_breathe = True
    _draw_inner_core_progress(generation_start, "extraction reference")
    with _inner_core_processing_visibility(extr):
        extr.cut_plane(
            mathutils.Vector((0, 0, -1)),
            mathutils.Vector((0, 0, w.min_z - 1)),
        )
    _draw_inner_core_progress(generation_start, "cut extraction reference")

    box = Object(bpy.data.objects.get("box"))
    return box.min_z, box.max_z


def begin_create_ref(context):
    return BackgroundTaskSequence(_create_ref_steps(context))


def create_ref(context):
    return finish_task_sync(begin_create_ref(context))


def create_inner_core(context):
    try:
        min_z, max_z = create_ref(context)
        box_voxel_size = get_box_voxel_size(context.scene.box_quality)
        box_intersection_voxel_size = get_box_voxel_size(
            INNER_CORE_BOX_INTERSECTION_QUALITY,
            bpy.data.objects.get("box"),
        )
        obj_names = [*INNER_CORE_REFERENCE_OBJECT_NAMES, "box"]
        response = request_server(
            f"{get_server_base_url()}/inner-core/",
            obj_names,
            params={
                "box_voxel_size": box_voxel_size,
                "max_box_z": max_z,
                "min_box_z": min_z,
                "clamp_width": context.scene.clamp_width,
                "core_type": str(
                    getattr(
                        context.scene,
                        "pro_inner_cavity_core_type",
                        "SINGLE_PART",
                    )
                ),
                "box_thickness": context.scene.box_thickness,
                "mold_thickness": context.scene.box_gap,
                "box_intersection_voxel_size": box_intersection_voxel_size,
            },
        )
        _finish_inner_core_response(context, response)
    finally:
        _remove_silicone_displacement_cutters()
        _remove_inner_core_reference_objects()


def create_inner_core_async(context):
    def steps():
        try:
            min_z, max_z = yield begin_create_ref(context)
            box_voxel_size = get_box_voxel_size(context.scene.box_quality)
            box_intersection_voxel_size = get_box_voxel_size(
                INNER_CORE_BOX_INTERSECTION_QUALITY,
                bpy.data.objects.get("box"),
            )
            obj_names = [*INNER_CORE_REFERENCE_OBJECT_NAMES, "box"]
            response = yield request_server_async(
                f"{get_server_base_url()}/inner-core/",
                obj_names,
                params={
                    "box_voxel_size": box_voxel_size,
                    "max_box_z": max_z,
                    "min_box_z": min_z,
                    "clamp_width": context.scene.clamp_width,
                    "core_type": str(
                        getattr(
                            context.scene,
                            "pro_inner_cavity_core_type",
                            "SINGLE_PART",
                        )
                    ),
                    "box_thickness": context.scene.box_thickness,
                    "mold_thickness": context.scene.box_gap,
                    "box_intersection_voxel_size": box_intersection_voxel_size,
                },
            )
            _hide_inner_core_reference_objects()
            _finish_inner_core_response(
                context,
                response,
                refresh_volume_text=False,
            )
            return (yield begin_recreate_volume_text(context))
        finally:
            _remove_silicone_displacement_cutters()
            _remove_inner_core_reference_objects()

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _finish_inner_core_response(
    context,
    response,
    *,
    refresh_volume_text: bool = True,
) -> None:
    finish_start = time.perf_counter()
    logger.debug(
        "Received inner-core response from server",
    )
    imported_objects = import_server_response(response)
    for imported_object in imported_objects:
        imported_name = imported_object.name.lower()
        if (
            imported_name == "attach_socket"
            or imported_name.startswith("attach_socket_")
            or "to_cut" in imported_name
            or "to_sub" in imported_name
        ):
            assign_moldbox_material(imported_object)
        else:
            assign_inner_core_material(imported_object)
    _draw_inner_core_progress(finish_start, "imported inner core response")
    finish_inner_cavity_from_scene(context=context)
    _draw_inner_core_progress(finish_start, "finished inner cavity")
    add_inner_core_objects_to_box(context)
    _draw_inner_core_progress(finish_start, "added inner cores to box")
    if refresh_volume_text:
        recreate_volume_text(context)
        _draw_inner_core_progress(finish_start, "refreshed inner core volume")


def _male_split_lock_objects() -> list[Object]:
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (
            obj.name.lower().startswith("barrier_male")
            or obj.name.lower().startswith("clamp_pin_male")
        )
    ]


def _keep_highest_vertex_count_box_island(box: Object) -> Object:
    original_name = box.name
    isolated_meshes = box.split_isolated_meshes()
    largest = max(
        isolated_meshes,
        key=lambda part: len(part.object.data.vertices),
    )
    removed_count = 0
    for part in isolated_meshes:
        if part.object == largest.object:
            continue
        part.remove()
        removed_count += 1

    largest.name = original_name
    logger.info(
        "Pre-split inner-core cleanup kept %s with %d vertices and removed %d "
        "isolated mesh%s",
        largest.name,
        len(largest.object.data.vertices),
        removed_count,
        "" if removed_count == 1 else "es",
    )
    return largest


def subtract_inner_core_objects_from_box(context):
    box_object = bpy.data.objects.get("box")
    if box_object is None:
        raise ValueError("Inner core requires the unsplit box object")
    box = Object(box_object)
    male_split_locks = _male_split_lock_objects()

    for obj in list(bpy.data.objects):
        name = obj.name.lower()
        is_core_clearance = name.startswith("temp_clear_")
        if name.startswith("temp_") and not is_core_clearance:
            continue
        if (
            not is_core_clearance
            and "to_cut" not in name
            and "to_sub" not in name
        ):
            continue

        bobj = Object(obj)
        bobj.hide_during_ui_breathe = True
        assign_moldbox_material(bobj.object)
        if is_core_clearance:
            for male_split_lock in male_split_locks:
                male_split_lock.apply_boolean_modifier(
                    diff_no_material_transfer_mod,
                    target=bobj,
                )
        mirror_pending_casting_subtraction(bobj, material_transfer=False)
        box.apply_boolean_modifier(
            diff_no_material_transfer_mod,
            target=bobj,
        )
        bobj.remove()

    _keep_highest_vertex_count_box_island(box)


def add_inner_core_objects_to_box(context):
    box = Object(bpy.data.objects.get("box"))
    objects_to_add = []

    # The base wing has already been merged into the box when the inner-core
    # response arrives. Add the dedicated socket immediately afterward with a
    # MANIFOLD union, before processing any other imported additions.
    attach_socket_objects = sorted(
        (
            obj
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                obj.name == "attach_socket"
                or obj.name.startswith("attach_socket_")
            )
        ),
        key=lambda obj: obj.name,
    )
    base_substracter_object = next(
        (
            obj
            for obj in bpy.data.objects
            if is_base_substracter_object(obj)
        ),
        None,
    )
    base_substracter = (
        Object(base_substracter_object)
        if base_substracter_object is not None
        else None
    )
    base_substracter_wrapper = None
    try:
        if base_substracter is not None:
            base_substracter_wrapper = MeshEnvelope(
                base_substracter,
                voxel_size=1.0,
                distance=1.0,
                n_wraps=2,
                name_adder="_attach_socket_base_substracter",
                build_from_sphere=False,
            )
            base_substracter_wrapper.name = (
                "temp_attach_socket_base_substracter_wrapper"
            )
            base_substracter_wrapper.hide_during_ui_breathe = True

        for attach_socket_object in attach_socket_objects:
            attach_socket = Object(attach_socket_object)
            attach_socket.hide_during_ui_breathe = True
            if base_substracter_wrapper is not None:
                attach_socket.apply_boolean_modifier(
                    diff_mod,
                    target=base_substracter_wrapper,
                )
            mirror_pending_casting_addition(attach_socket)
            box.apply_boolean_modifier(union_mod, target=attach_socket)
            attach_socket.remove()
    finally:
        if base_substracter_wrapper is not None:
            base_substracter_wrapper.remove()
        if base_substracter is not None:
            base_substracter.remove()

    for obj in list(bpy.data.objects):
        name = obj.name.lower()
        if name.startswith("temp_"):
            continue
        if "to_add" in name:
            objects_to_add.append(Object(obj))

    for bobj in objects_to_add:
        bobj.hide_during_ui_breathe = True
        mirror_pending_casting_addition(bobj)
        box += bobj
        bobj.remove()


def _prepare_volume_text_refresh(context):
    reveal_silicone_mold_preview()
    silicone_mold = Object(bpy.data.objects.get("silicone_mold"))
    try:
        preview_operands = [
            Object(obj)
            for obj in bpy.data.objects
            if obj.type == "MESH"
            and (
                bool(obj.get(SILICONE_DISPLACEMENT_CUTTER_MARKER, False))
                or (
                    not obj.name.lower().startswith("temp_")
                    and (
                        obj.name.lower().startswith("attacher_")
                        or obj.name.lower().startswith("core_pin_")
                    )
                )
            )
        ]
        for operand in preview_operands:
            operand.hide_during_ui_breathe = True
            with _inner_core_processing_visibility(operand):
                silicone_mold.apply_boolean_modifier_with_target_manifold_retry(
                    diff_mod,
                    target=operand,
                    self_remesh=build_voxel_modifier(
                        get_box_voxel_size(
                            context.scene.box_quality,
                            silicone_mold,
                        )
                    ),
                    target_remesh=build_sharp_modifier(8),
                )
        isolated_meshes = silicone_mold.split_isolated_meshes()
        # Only keep the largest piece, which is the main mold body by volume
        if len(isolated_meshes) > 1:
            largest_piece = max(isolated_meshes, key=lambda obj: obj.volume)
            for obj in isolated_meshes:
                if obj != largest_piece:
                    obj.remove()
            largest_piece.name = "silicone_mold"
            silicone_mold = largest_piece

        context.scene.volume = silicone_mold.volume
        context.scene.casting_volume_ml = calculate_casting_volume()
        old_volume_text_obj = bpy.data.objects.get("Text1")
        if old_volume_text_obj is None:
            logger.debug(
                "Volume text object Text1 not found; skipping volume text refresh"
            )
            return None

        old_volume_text = Object(old_volume_text_obj)
        text_min_x = float(
            old_volume_text.object.get(
                "_moldboxer_weight_text_min_x", old_volume_text.min_x
            )
        )
        text_center_y = float(
            old_volume_text.object.get(
                "_moldboxer_weight_text_center_y", old_volume_text.center_coords.y
            )
        )
        text_min_z = float(
            old_volume_text.object.get(
                "_moldboxer_weight_text_min_z", old_volume_text.min_z
            )
        )
        text_height = float(
            old_volume_text.object.get(
                "_moldboxer_weight_text_height", old_volume_text.height
            )
        )
        weight_text = silicone_mix_engraving(context.scene)
        return {
            "old_volume_text": old_volume_text,
            "text": weight_text,
            "text_min_x": text_min_x,
            "text_center_y": text_center_y,
            "text_min_z": text_min_z,
            "text_height": text_height,
        }
    finally:
        _remove_silicone_displacement_cutters()
        hide_silicone_mold_preview()


def _finish_volume_text_refresh(refresh_state, refreshed_text) -> None:
    old_volume_text = refresh_state["old_volume_text"]
    old_volume_text.remove()
    refreshed_text.name = "Text1"
    vol_text = refreshed_text
    vol_text.scale_to(refresh_state["text_height"], axis=2)
    vol_text.rotate_whole(mathutils.Matrix.Rotation(math.radians(270), 4, "Z"))
    vol_text.translate_whole(
        mathutils.Vector(
            (
                refresh_state["text_min_x"] - vol_text.min_x,
                refresh_state["text_center_y"] - vol_text.center_coords.y,
                refresh_state["text_min_z"] - vol_text.min_z,
            )
        )
    )
    box = bpy.data.objects.get("box")
    if box is None:
        logger.debug("Mold box object not found; skipping volume text engraving")
        vol_text.remove()
        return
    box_obj = Object(box)
    vol_text.object.hide_set(False)
    vol_text.object.hide_viewport = False
    vol_text.object.hide_render = False
    if not subtract_weight_text_with_validation(box_obj, vol_text):
        logger.debug("Silicone weight text engraving left an empty boolean")
    vol_text.remove()


def recreate_volume_text(context):
    refresh_state = _prepare_volume_text_refresh(context)
    if refresh_state is None:
        return None
    refreshed_text = request_weight_text_mesh(
        refresh_state["text"],
        name="Text1_refresh",
    )
    _finish_volume_text_refresh(refresh_state, refreshed_text)
    return None


def begin_recreate_volume_text(context):
    def steps():
        refresh_state = _prepare_volume_text_refresh(context)
        if refresh_state is None:
            return None
        refreshed_text = yield request_weight_text_mesh_async(
            refresh_state["text"],
            name="Text1_refresh",
        )
        _finish_volume_text_refresh(refresh_state, refreshed_text)
        return None

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence
