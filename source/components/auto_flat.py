from collections.abc import Callable, Iterator

from ..silicone_mix import silicone_mix_engraving
from ..background_worker import BackgroundTaskSequence, finish_task_sync
from ..object import *
from .mesh_envelope import *
from .slip_casting_box_shape import begin_primitive_box
from ..constants import *
from .grip import *
from ._q7x import (
    begin_z9f3,
    different_casting_box_thickness,
    mirror_pending_casting_subtraction,
)
from .preprocess import *
from .silicone_mold import (
    build_silicone_mold_preview,
    hide_silicone_mold_preview,
    reveal_silicone_mold_preview,
)
from .watermark_mesh_server import request_watermark_meshes_async
from .open import begin_tray_silhouette_req
from .base import pin_patron
from .confirm_mold import (
    casting_box_objects,
    duplicate_cut_casting_boxes,
    remove_clip,
    translate_object_location,
)
from ..operator_access import is_lite_tier
from ..materials import (
    assign_funnels_material,
    assign_generated_material,
    prepare_material_transfer,
    refresh_generated_object_materials,
    refresh_viewport_material_display,
)
from ..modifiers import diff_material_transfer_mod
from ..progress import force_viewport_redraw
from ..voxel_size import get_box_boolean_retry_voxel_size, get_box_voxel_size
from .watermark_payload import build_watermark_text_lines, calculate_casting_volume

AutoFlatStep = tuple[str, Callable[[], None]]

GRIP_SPAN = 20
GRIP_HEIGHT = 7
GRIP_DEPTH = 10
GRIP_WATERMARK_MARGIN_X = 5
GRIP_SILICONE_VOLUME_MARGIN_X = 5.0
GRIP_TEXT_MARGIN_Y = 1.0
WATERMARK_TEXT_Z = 1.9
TRAY_FIXED_MASTER_JOIN_Z_OFFSET = -0.2
TRAY_PROJECTION_SMOOTHING_VOXEL_FACTOR = 0.25
TRAY_PROJECTION_SMOOTHING_MIN = 0.15
TRAY_PROJECTION_SMOOTHING_MAX = 0.35


def _scale_text_to_fit_grip(
    vol_text: Object, grip_span: float, grip_depth: float
) -> None:
    max_width = max(grip_span - GRIP_WATERMARK_MARGIN_X, 0.1)
    max_depth = max(grip_depth - 2 * GRIP_TEXT_MARGIN_Y, 0.1)
    if vol_text.depth:
        depth_scale = max_depth / vol_text.depth
        for axis in range(2):
            vol_text.scale(depth_scale, axis)
    if vol_text.width > max_width:
        width_scale = max_width / vol_text.width
        for axis in range(2):
            vol_text.scale(width_scale, axis)


def _scale_silicone_volume_text(
    volume_text: Object, box_thickness: float, grip_span: float
) -> None:
    target_depth = max(box_thickness - 1, 0.1)
    max_width = max(grip_span - GRIP_SILICONE_VOLUME_MARGIN_X, 0.1)
    if volume_text.depth:
        depth_scale = target_depth / volume_text.depth
        for axis in range(3):
            volume_text.scale(depth_scale, axis)
    if volume_text.width > max_width:
        width_scale = max_width / volume_text.width
        for axis in range(3):
            volume_text.scale(width_scale, axis)


def _tray_grip_engraving_text(scene) -> str | None:
    watermark_text = build_watermark_text_lines(scene) or ""
    if not bool(getattr(scene, "tray_casting_volume", True)):
        return watermark_text or None

    casting_volume_ml = max(float(getattr(scene, "casting_volume_ml", 0.0)), 0.0)
    casting_volume_text = f"{casting_volume_ml:.0f} ml"
    if not watermark_text:
        return casting_volume_text
    return f"{watermark_text}\n{casting_volume_text}"


def _style_and_draw_box(context) -> None:
    box = bpy.data.objects.get("box")
    if box is not None:
        assign_generated_material(box)
    refresh_generated_object_materials()
    refresh_viewport_material_display(context)
    force_viewport_redraw(context)


def _subtract_tray_text_with_material_transfer(
    box: Object,
    text: Object,
) -> None:
    assign_funnels_material(text.object)
    prepare_material_transfer(box.object, text.object)
    box.apply_boolean_modifier(
        diff_material_transfer_mod,
        target=text,
    )


def iter_build_tray_steps(
    context,
    state: dict[str, object] | None = None,
) -> Iterator[AutoFlatStep]:
    state = state if state is not None else {}

    def generate_tray_box():
        remove_clip()
        preprocess_patron(check_manifold=False)
        build_from_sphere = context.scene.tray_type == "CONTOUR"
        box_voxel_size = get_box_voxel_size(context.scene.box_quality)
        state["box_voxel_size"] = box_voxel_size
        state["box_boolean_retry_voxel_size"] = get_box_boolean_retry_voxel_size(
            context.scene.box_quality
        )
        shape_type = getattr(context.scene, "mold_box_shape_type", "adapted")
        task = begin_primitive_box(
            Object(bpy.data.objects.get("patron")),
            distance=context.scene.box_gap,
            shape_type=shape_type,
            vertical_faces=getattr(context.scene, "mold_box_faces", 4),
            pad_vertical=True,
        ) if shape_type != "adapted" else begin_mesh_envelope(
            Object(bpy.data.objects.get("patron")),
            box_voxel_size,
            distance=context.scene.box_gap,
            n_wraps=2,
            build_from_sphere=build_from_sphere,
            sphere_voxel_factor=2,
        )

        def finish(box):
            _style_and_draw_box(context)
            return box

        return task.then(finish)

    def generate_tray_silhouette():
        smoothing_radius = min(
            max(
                float(state["box_voxel_size"])
                * TRAY_PROJECTION_SMOOTHING_VOXEL_FACTOR,
                TRAY_PROJECTION_SMOOTHING_MIN,
            ),
            TRAY_PROJECTION_SMOOTHING_MAX,
        )

        def finish(box):
            state["box"] = box
            _style_and_draw_box(context)
            return box

        return begin_tray_silhouette_req(
            smoothing_radius=smoothing_radius,
            on_complete=finish,
        )

    def generate_tray_grip() -> None:
        flat_grip = bool(context.scene.flat_grip)
        state["flat_grip"] = flat_grip
        if flat_grip:
            grip = build_grip(
                height=GRIP_HEIGHT, grip_span=GRIP_SPAN, grip_depth=GRIP_DEPTH
            )
            assign_generated_material(grip.object)
        _style_and_draw_box(context)
        Object(bpy.data.objects.get("box")).select()

    yield "Generating tray box", generate_tray_box
    yield "Clearing undercuts and air traps", generate_tray_silhouette
    yield "Generating editable tray grip", generate_tray_grip


def iter_confirm_tray_steps(
    context,
    state: dict[str, object] | None = None,
) -> Iterator[AutoFlatStep]:
    state = state if state is not None else {}
    state.setdefault(
        "box_voxel_size",
        get_box_voxel_size(context.scene.box_quality),
    )
    state.setdefault(
        "box_boolean_retry_voxel_size",
        get_box_boolean_retry_voxel_size(context.scene.box_quality),
    )

    def add_edited_tray_grip() -> None:
        grip_object = bpy.data.objects.get("grip")
        flat_grip = bool(context.scene.flat_grip) and grip_object is not None
        state["flat_grip"] = flat_grip
        if not flat_grip:
            if grip_object is not None:
                Object(grip_object).remove()
            _style_and_draw_box(context)
            return

        box = Object(bpy.data.objects.get("box"))
        grip = Object(grip_object)
        state["grip_center_y"] = grip.center_coords.y
        state["silicone_volume_grip_max_x"] = grip.max_x
        state["silicone_volume_grip_max_y"] = grip.max_y
        state["silicone_volume_grip_max_z"] = grip.max_z
        state["grip_max_x"] = grip.max_x
        state["grip_min_z"] = grip.min_z
        state["grip_extension"] = max(grip.max_x - box.max_x, 0.1)
        state["grip_depth"] = max(grip.depth, 0.1)
        add_grip(float(state["box_voxel_size"]))
        _style_and_draw_box(context)

    def simulate_silicone_mold():
        vol = build_silicone_mold_preview(
            float(state["box_voxel_size"]),
            retry_voxel_size=float(state["box_boolean_retry_voxel_size"]),
            is_tray_mold=True,
        )
        state["volume"] = vol
        context.scene.volume = vol
        context.scene.casting_volume_ml = calculate_casting_volume()
        hide_silicone_mold_preview()
        task = begin_z9f3(
            _a7=float(state["box_voxel_size"]),
            _b4=context.scene.box_thickness,
            _casting_b4=different_casting_box_thickness(context.scene),
        )

        def finish(_opened_box):
            box = Object(bpy.data.objects.get("box"))
            box.clean_top(3)
            box.clean_bot(context.scene.box_thickness - 0.3)
            state["box"] = box
            _style_and_draw_box(context)
            return box

        return task.then(finish)

    def finish_tray_markings(marking_meshes, grip_engraving_text) -> None:
        box = Object(bpy.data.objects.get("box"))
        silicone_volume_text = None
        vol_text = None
        if marking_meshes:
            for marking_mesh in marking_meshes:
                assign_funnels_material(marking_mesh.object)
            silicone_volume_text = marking_meshes[0]
            _scale_silicone_volume_text(
                silicone_volume_text,
                context.scene.box_thickness,
                float(state["grip_extension"]),
            )
            silicone_volume_text.translate_whole(
                mathutils.Vector(
                    (
                        float(state["silicone_volume_grip_max_x"])
                        - GRIP_SILICONE_VOLUME_MARGIN_X
                        - silicone_volume_text.max_x,
                        float(state["silicone_volume_grip_max_y"])
                        + 0.5
                        - silicone_volume_text.min_y,
                        float(state["silicone_volume_grip_max_z"])
                        + 0.1
                        - silicone_volume_text.max_z,
                    )
                )
            )
            if grip_engraving_text:
                vol_text = marking_meshes[1]
                _scale_text_to_fit_grip(
                    vol_text,
                    float(state["grip_extension"]),
                    float(state["grip_depth"]),
                )
                vol_text.origin_to_geometry()
                vol_text.scale(-1, axis=0)
                vol_text.apply_all_transforms()
                text_translation_vector = mathutils.Vector(
                    (
                        float(state["grip_max_x"]) - 2 - vol_text.max_x,
                        float(state["grip_center_y"]) - vol_text.center_coords.y,
                        float(state["grip_min_z"]) - 1 - vol_text.min_z,
                    )
                )
                vol_text.translate_whole(text_translation_vector)

        if vol_text is not None:
            mirror_pending_casting_subtraction(vol_text)
            _subtract_tray_text_with_material_transfer(box, vol_text)
            vol_text.remove()
        if silicone_volume_text is not None:
            for piece in silicone_volume_text.split_isolated_meshes():
                mirror_pending_casting_subtraction(piece)
                _subtract_tray_text_with_material_transfer(box, piece)
                piece.remove()
        _style_and_draw_box(context)

    def generate_tray_markings():
        state["box"] = Object(bpy.data.objects.get("box"))

        def steps():
            marking_meshes = []
            grip_engraving_text = ""
            if not (bool(state.get("flat_grip")) and not is_lite_tier()):
                finish_tray_markings(marking_meshes, grip_engraving_text)
                return

            weight_text = silicone_mix_engraving(context.scene, float(state["volume"]))
            grip_engraving_text = _tray_grip_engraving_text(context.scene)
            marking_items = [
                {
                    "kind": "text",
                    "name": "tray_silicone_weight_text",
                    "text": weight_text,
                    "size": 5.0,
                    "depth": 2.0,
                    "font_identifier": "BFONT",
                    "sharp_remesh_level": 8,
                }
            ]
            if grip_engraving_text:
                marking_items.append(
                    {
                        "kind": "text",
                        "name": "tray_grip_engraving_text",
                        "text": grip_engraving_text,
                        "size": 5.0,
                        "depth": 2.0,
                        "font_identifier": "BFONT",
                        "sharp_remesh_level": 8,
                    }
                )
            marking_meshes = yield request_watermark_meshes_async(marking_items)
            finish_tray_markings(marking_meshes, grip_engraving_text)

        sequence = BackgroundTaskSequence(steps())
        sequence.redraw_interval = 0.1
        return sequence

    def finish_tray_master() -> None:
        box = Object(bpy.data.objects.get("box"))
        patron = Object(bpy.data.objects.get("patron"))
        state["patron"] = patron
        if context.scene.wing_join_patron:
            patron_for_box = patron.duplicate(name_adder="_tray_base_join")
            # Joining applies the duplicate's transform to the tray mesh. Move
            # the copy in its local coordinates without editing every vertex:
            # a BMesh translate recalculates normals on the imported master.
            patron_for_box.object.matrix_world = (
                patron_for_box.object.matrix_world
                @ mathutils.Matrix.Translation(
                    (0, 0, TRAY_FIXED_MASTER_JOIN_Z_OFFSET)
                )
            )
            bpy.context.view_layer.update()
            logger.info("Tray fixed-master copy positioned; joining to box")
            box.join(patron_for_box)
            logger.info("Tray fixed-master join completed")
        else:
            logger.debug("Skipping patron join to box (Fixed Master disabled)")
            if context.scene.master_base_pin:
                pin_patron(
                    box,
                    patron,
                    context.scene.master_base_pin_tolerance,
                    context.scene.master_base_pin_height,
                )
        _style_and_draw_box(context)

    def generate_casting_boxes() -> None:
        patron = state.get("patron")
        if not isinstance(patron, Object):
            patron = Object(bpy.data.objects.get("patron"))
        if context.scene.pro_casting_box:
            master_join_z_offset = (
                TRAY_FIXED_MASTER_JOIN_Z_OFFSET
                if context.scene.wing_join_patron
                else 0.0
            )
            casting_boxes = duplicate_cut_casting_boxes(
                vertical_cut_height=patron.min_z + master_join_z_offset + 1
            )
            for casting_box in casting_boxes:
                assign_funnels_material(casting_box.object)
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)

    def space_tray_system() -> None:
        reveal_silicone_mold_preview()
        space_mold_system()
        refresh_generated_object_materials()
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)

    yield "Adding edited tray grip", add_edited_tray_grip
    yield "Simulating silicone mold", simulate_silicone_mold
    yield "Generating tray markings", generate_tray_markings
    # Finalize the casting shell before Fixed Master changes the mold box.
    yield "Generating casting boxes", generate_casting_boxes
    yield "Finalizing tray master", finish_tray_master
    yield "Spacing tray system", space_tray_system


def iter_auto_flat_steps(context) -> Iterator[AutoFlatStep]:
    state: dict[str, object] = {}
    yield from iter_build_tray_steps(context, state)
    yield from iter_confirm_tray_steps(context, state)


def build_tray(context) -> None:
    for _label, step in iter_build_tray_steps(context):
        finish_task_sync(step())


def confirm_tray(context) -> None:
    for _label, step in iter_confirm_tray_steps(context):
        finish_task_sync(step())


def auto_flat(context):
    for _label, step in iter_auto_flat_steps(context):
        finish_task_sync(step())


def space_mold_system():

    box = Object(bpy.data.objects.get("box"))
    patron = Object(bpy.data.objects.get("patron"))
    silicone_mold = Object(bpy.data.objects.get("silicone_mold"))
    translate_object_location(
        silicone_mold,
        mathutils.Vector(
            (
                box.width + silicone_mold.width / 2,
                0,
                0,
            )
        ),
    )
    casting_objects = casting_box_objects()
    if casting_objects:
        casting_min_x = min(casting_object.min_x for casting_object in casting_objects)
        casting_translation = mathutils.Vector(
            (
                silicone_mold.max_x + silicone_mold.width / 2 - casting_min_x,
                0,
                0,
            )
        )
        for casting_object in casting_objects:
            translate_object_location(casting_object, casting_translation)

    translate_object_location(
        patron,
        mathutils.Vector(
            (
                -box.width - patron.width / 2,
                0,
                0,
            )
        ),
    )
