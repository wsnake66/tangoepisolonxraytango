import math
import logging
import bpy  # type: ignore
import mathutils  # type: ignore
from typing import Iterator, Literal

from ..background_worker import BackgroundTaskSequence
from .preprocess import preprocess_patron
from ..bl_utils import BMeshObj, deselect_all_objects, retry_after_heal
from ..materials import assign_generated_material
from ..modifiers import build_voxel_modifier
from ..object import Object, remove_unused_meshes
from ..patron_state import DECIMATED_PATRON_KEY
from ..primitives import (
    create_circle_primitive,
    create_cube_primitive,
)
from .box import build_box_operator, iter_build_box_operator_steps
from .box_parts import (
    force_two_part_casting_box_standard,
    force_two_part_silicone_box_splits,
)
from .confirm_mold import confirm, iter_confirm_steps
from .geometry_adapter import (
    begin_fit_pin_circle_with_worker,
    begin_resample_closed_loop_with_worker,
    fit_pin_circle_with_worker,
    order_closed_loop_with_worker,
    resample_closed_loop_with_worker,
)
from ..progress import force_viewport_redraw
from ..voxel_size import get_master_voxel_size

logger = logging.getLogger(__name__)
TWO_PARTS_CIRCLE_SCALE_MULTIPLIER = 2


def _redraw_two_part_progress(context=None) -> None:
    try:
        force_viewport_redraw(context or bpy.context)
    except Exception:
        logger.debug("Could not redraw two-part progress", exc_info=True)


def _strip_part_name_token(name: str, token: str) -> str:
    if name == token:
        return "patron"

    name_parts = [part for part in name.split("_") if part != token]
    if not name_parts:
        return "patron"
    return "_".join(name_parts)


def _prefix_part_name_token(name: str, token: str) -> str:
    prefix = f"{token}_"
    if name.startswith(prefix):
        return name
    return f"{prefix}{name}"


def _has_part_name_token(name: str, token: str) -> bool:
    return name == token or token in name.split("_")


def _build_original_conflict_name(
    original_name: str,
    token: str,
    blocked_names: set[str],
) -> str:
    base_name = f"original_{original_name}_{token}"
    candidate = base_name
    suffix = 1
    while candidate in blocked_names:
        suffix += 1
        candidate = f"{base_name}_{suffix}"
    return candidate


def _build_tmp_name(index: int, blocked_names: set[str]) -> str:
    candidate = f"tmp_{index}"
    while candidate in blocked_names:
        index += 1
        candidate = f"tmp_{index}"
    return candidate


def _object_session_uid(obj) -> int:
    return int(obj.session_uid)


class temporary_part_object_names:
    def __init__(self, token: str):
        cleaned_token = token.strip()
        if not cleaned_token:
            raise ValueError("Part token must not be empty")

        self.token = cleaned_token
        self._original_names: dict[int, str] = {}
        self._original_object_uids: set[int] = set()

    def _rename_objects(self, objects: list, target_names: dict[int, str]) -> None:
        for index, obj in enumerate(objects):
            temp_name = f"__mb_tmp_{self.token}_{index}"
            while temp_name in bpy.data.objects:
                temp_name += "_"
            obj.name = temp_name

        for obj in objects:
            obj_uid = _object_session_uid(obj)
            obj.name = target_names[obj_uid]

    def __enter__(self):
        original_objects = list(bpy.data.objects)
        self._original_object_uids = {
            _object_session_uid(obj) for obj in original_objects
        }
        self._original_names = {
            _object_session_uid(obj): obj.name for obj in original_objects
        }

        objects_with_token = [
            obj
            for obj in original_objects
            if _has_part_name_token(
                self._original_names[_object_session_uid(obj)],
                self.token,
            )
        ]
        objects_without_token = [
            obj
            for obj in original_objects
            if not _has_part_name_token(
                self._original_names[_object_session_uid(obj)],
                self.token,
            )
        ]

        reserved_token_names = {
            _strip_part_name_token(
                self._original_names[_object_session_uid(obj)],
                self.token,
            )
            for obj in objects_with_token
        }
        target_names: dict[int, str] = {}
        used_names: set[str] = set()

        tmp_index = 1
        for obj in objects_without_token:
            obj_uid = _object_session_uid(obj)
            target_name = _build_tmp_name(
                tmp_index,
                reserved_token_names | used_names,
            )
            tmp_index += 1
            target_names[obj_uid] = target_name
            used_names.add(target_name)

        for obj in objects_with_token:
            obj_uid = _object_session_uid(obj)
            target_name = _strip_part_name_token(
                self._original_names[obj_uid], self.token
            )
            if target_name in used_names:
                target_name = _build_original_conflict_name(
                    target_name,
                    self.token,
                    used_names,
                )
            target_names[obj_uid] = target_name
            used_names.add(target_name)

        self._rename_objects(objects_without_token, target_names)
        self._rename_objects(objects_with_token, target_names)
        return self

    def __exit__(self, _exc_type, exc, _tb):
        current_objects = list(bpy.data.objects)
        target_names: dict[int, str] = {}

        for obj in current_objects:
            obj_uid = _object_session_uid(obj)
            if obj_uid in self._original_object_uids:
                target_names[obj_uid] = self._original_names[obj_uid]
                continue

            target_names[obj_uid] = _prefix_part_name_token(obj.name, self.token)

        self._rename_objects(current_objects, target_names)
        return False


def prepare_two_parts_box_build(context) -> dict[str, object]:
    force_two_part_casting_box_standard(context.scene)
    force_two_part_silicone_box_splits(context.scene)
    target_raw = context.active_object or bpy.context.active_object
    if target_raw is None:
        raise ValueError("No active object selected")
    if target_raw.type != "MESH":
        raise ValueError("Selected object must be a mesh")
    preprocess_patron(center=False, check_manifold=False)
    _redraw_two_part_progress(context)

    master_raw = bpy.data.objects.get("master")
    master = None
    if (
        master_raw is not None
        and master_raw.type == "MESH"
        and master_raw is not target_raw
    ):
        master = Object(master_raw)
        master.apply_all_transforms()

    target, female_pins, male_pins, female_refs = build_pins_circle(
        target_raw,
        open_base=bool(context.scene.pro_open_base),
        pin_size=float(context.scene.pro_key_size),
        pin_tolerance=float(context.scene.pro_key_tolearnce),
    )
    _redraw_two_part_progress(context)
    left_part, right_part = split_system(target)
    if bool(target.object.get(DECIMATED_PATRON_KEY, False)):
        left_part.object[DECIMATED_PATRON_KEY] = True
        right_part.object[DECIMATED_PATRON_KEY] = True

    left_master = None
    right_master = None
    if master is not None:
        left_master, right_master = split_system(
            master,
            left_name="left_master",
            right_name="right_master",
        )
    _redraw_two_part_progress(context)

    rotate_system_group([left_part, *male_pins, *female_refs], 90)
    rotate_system_group([right_part, *female_pins], -90)
    left_master_parts = [part for part in (left_master,) if part is not None]
    right_master_parts = [part for part in (right_master,) if part is not None]
    rotate_system_group(left_master_parts, 90)
    rotate_system_group(right_master_parts, -90)
    left_source, right_source = prepare_box_sources(
        left_part,
        right_part,
        female_pins,
        male_pins,
        female_refs,
        context.scene.pro_open_base,
        float(context.scene.pro_key_tolearnce),
        left_sync_objects=left_master_parts,
        right_sync_objects=right_master_parts,
    )
    _redraw_two_part_progress(context)
    left_original_objects = [left_part, *male_pins, *female_refs]
    if left_master is not None:
        left_original_objects.append(left_master)
    return {
        "target": target,
        "left_source": left_source,
        "right_source": right_source,
        "reference_master": master,
        "left_original_objects": left_original_objects,
    }


def begin_prepare_two_parts_box_build(context):
    force_two_part_casting_box_standard(context.scene)
    force_two_part_silicone_box_splits(context.scene)
    target_raw = context.active_object or bpy.context.active_object
    if target_raw is None:
        raise ValueError("No active object selected")
    if target_raw.type != "MESH":
        raise ValueError("Selected object must be a mesh")
    preprocess_patron(center=False, check_manifold=False)
    _redraw_two_part_progress(context)

    master_raw = bpy.data.objects.get("master")
    master = None
    if (
        master_raw is not None
        and master_raw.type == "MESH"
        and master_raw is not target_raw
    ):
        master = Object(master_raw)
        master.apply_all_transforms()
    pin_task = begin_build_pins_circle(
        target_raw,
        open_base=bool(context.scene.pro_open_base),
        pin_size=float(context.scene.pro_key_size),
        pin_tolerance=float(context.scene.pro_key_tolearnce),
    )

    def steps():
        target, female_pins, male_pins, female_refs = yield pin_task
        _redraw_two_part_progress(context)
        left_part, right_part = split_system(target)
        if bool(target.object.get(DECIMATED_PATRON_KEY, False)):
            left_part.object[DECIMATED_PATRON_KEY] = True
            right_part.object[DECIMATED_PATRON_KEY] = True
        left_master = right_master = None
        if master is not None:
            left_master, right_master = split_system(
                master,
                left_name="left_master",
                right_name="right_master",
            )
        _redraw_two_part_progress(context)
        rotate_system_group([left_part, *male_pins, *female_refs], 90)
        rotate_system_group([right_part, *female_pins], -90)
        left_master_parts = [part for part in (left_master,) if part is not None]
        right_master_parts = [part for part in (right_master,) if part is not None]
        rotate_system_group(left_master_parts, 90)
        rotate_system_group(right_master_parts, -90)
        left_source, right_source = prepare_box_sources(
            left_part,
            right_part,
            female_pins,
            male_pins,
            female_refs,
            context.scene.pro_open_base,
            float(context.scene.pro_key_tolearnce),
            left_sync_objects=left_master_parts,
            right_sync_objects=right_master_parts,
        )
        _redraw_two_part_progress(context)
        left_original_objects = [left_part, *male_pins, *female_refs]
        if left_master is not None:
            left_original_objects.append(left_master)
        return {
            "target": target,
            "left_source": left_source,
            "right_source": right_source,
            "reference_master": master,
            "left_original_objects": left_original_objects,
        }

    return BackgroundTaskSequence(steps())


def build_two_parts_box(context):
    state = prepare_two_parts_box_build(context)
    build_boxes(
        context,
        state["target"],
        state["left_source"],
        state["right_source"],
        reference_master=state["reference_master"],
        left_original_objects=state["left_original_objects"],
    )


def iter_build_two_parts_box_steps(context) -> Iterator[tuple[str, object]]:
    state: dict[str, object] = {}

    def prepare():
        task = begin_prepare_two_parts_box_build(context)
        return task.then(lambda prepared: state.update(prepared))

    yield "Preparing two-part box", prepare
    yield "Preparing left two-part box", lambda: prepare_two_part_box_side(
        context,
        state,
        "left",
    )
    yield from (
        (f"Left {label[0].lower()}{label[1:]}", step)
        for label, step in iter_build_box_operator_steps(context, async_server=True)
    )
    yield "Collecting left two-part box", lambda: collect_two_part_box_side(
        context,
        state,
        "left",
    )
    yield "Preparing right two-part box", lambda: prepare_two_part_box_side(
        context,
        state,
        "right",
    )
    yield from (
        (f"Right {label[0].lower()}{label[1:]}", step)
        for label, step in iter_build_box_operator_steps(context, async_server=True)
    )
    yield "Collecting right two-part box", lambda: collect_two_part_box_side(
        context,
        state,
        "right",
    )
    yield "Arranging two-part box", lambda: finish_two_part_boxes(context, state)


def confirm_two_parts(context):
    """
    Confirm each system half separately.

    Use temporary_part_object_names to expose one side at a time while
    preserving original names and prefixing any newly created objects on exit.
    """
    left_keys = [Object(obj) for obj in bpy.data.objects if obj.name.startswith("male")]
    right_keys = [
        Object(obj) for obj in bpy.data.objects if obj.name.startswith("female")
    ]
    silicone_volume = 0.0
    casting_volume = 0.0

    with temporary_part_object_names("left"):
        confirm(
            context,
            two_part_casting_side="left",
            cut_casting_open_base_side=context.scene.pro_open_base,
            cut_casting_vertical=False,
            pre_join_base_callback=lambda base, _patron: apply_two_part_base_keys(
                base,
                left_keys,
                "DIFFERENCE",
            ),
        )
        silicone_volume += float(getattr(context.scene, "volume", 0.0))
        casting_volume += float(getattr(context.scene, "casting_volume_ml", 0.0))
    _redraw_two_part_progress(context)

    with temporary_part_object_names("right"):
        confirm(
            context,
            two_part_casting_side="right",
            cut_casting_open_base_side=context.scene.pro_open_base,
            cut_casting_vertical=False,
            pre_join_base_callback=lambda base, _patron: apply_two_part_base_keys(
                base,
                right_keys,
                "UNION",
            ),
        )
        silicone_volume += float(getattr(context.scene, "volume", 0.0))
        casting_volume += float(getattr(context.scene, "casting_volume_ml", 0.0))
    _redraw_two_part_progress(context)

    for side in ("left", "right"):
        side_patron = bpy.data.objects.get(side)
        if side_patron is not None:
            Object(side_patron).name = f"{side}_patron"

    context.scene.volume = silicone_volume
    context.scene.casting_volume_ml = casting_volume


def _label_for_part(side: Literal["left", "right"], label: str) -> str:
    return f"{side.title()} {label[0].lower()}{label[1:]}"


def prepare_confirm_two_parts(context, state: dict[str, object]) -> None:
    force_two_part_casting_box_standard(context.scene)
    state["left_keys"] = [
        Object(obj) for obj in bpy.data.objects if obj.name.startswith("male")
    ]
    state["right_keys"] = [
        Object(obj) for obj in bpy.data.objects if obj.name.startswith("female")
    ]
    state["silicone_volume"] = 0.0
    state["casting_volume"] = 0.0


def enter_confirm_two_part_side(
    state: dict[str, object],
    side: Literal["left", "right"],
) -> None:
    manager = temporary_part_object_names(side)
    manager.__enter__()
    state["active_name_manager"] = manager
    state["active_side"] = side


def exit_confirm_two_part_side(context, state: dict[str, object]) -> None:
    state["silicone_volume"] = float(state.get("silicone_volume", 0.0)) + float(
        getattr(context.scene, "volume", 0.0)
    )
    state["casting_volume"] = float(state.get("casting_volume", 0.0)) + float(
        getattr(context.scene, "casting_volume_ml", 0.0)
    )
    _exit_active_confirm_name_manager(state)
    _redraw_two_part_progress(context)


def finish_confirm_two_parts(context, state: dict[str, object]) -> None:
    for side in ("left", "right"):
        side_patron = bpy.data.objects.get(side)
        if side_patron is not None:
            Object(side_patron).name = f"{side}_patron"

    context.scene.volume = float(state.get("silicone_volume", 0.0))
    context.scene.casting_volume_ml = float(state.get("casting_volume", 0.0))


def _exit_active_confirm_name_manager(state: dict[str, object]) -> None:
    manager = state.pop("active_name_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)
    state.pop("active_side", None)


class TwoPartConfirmTaskGuard:
    def __init__(self, task, state: dict[str, object]):
        self._task = task
        self._state = state

    def done(self) -> bool:
        return self._task.done()

    def finish(self):
        try:
            return self._task.finish()
        except Exception:
            _exit_active_confirm_name_manager(self._state)
            raise


def _wrap_confirm_two_part_step(
    state: dict[str, object],
    step,
):
    def wrapped_step():
        try:
            result = step()
            if (
                result is not None
                and callable(getattr(result, "done", None))
                and callable(getattr(result, "finish", None))
            ):
                return TwoPartConfirmTaskGuard(result, state)
            return result
        except Exception:
            _exit_active_confirm_name_manager(state)
            raise

    return wrapped_step


def iter_confirm_two_parts_steps(context) -> Iterator[tuple[str, object]]:
    state: dict[str, object] = {}

    yield "Preparing two-part mold system", lambda: prepare_confirm_two_parts(
        context,
        state,
    )
    for side in ("left", "right"):
        yield ("Preparing left mold system" if side == "left" else "Preparing right mold system"), lambda side=side: enter_confirm_two_part_side(
            state,
            side,
        )
        keys_name = f"{side}_keys"
        operation = "DIFFERENCE" if side == "left" else "UNION"
        yield from (
            (
                _label_for_part(side, label),
                _wrap_confirm_two_part_step(state, step),
            )
            for label, step in iter_confirm_steps(
                context,
                two_part_casting_side=side,
                cut_casting_open_base_side=context.scene.pro_open_base,
                cut_casting_vertical=False,
                pre_join_base_callback=lambda base, _patron, keys_name=keys_name, operation=operation: apply_two_part_base_keys(
                    base,
                    state[keys_name],
                    operation,
                ),
                async_server=True,
            )
        )
        yield ("Collecting left mold system" if side == "left" else "Collecting right mold system"), lambda: exit_confirm_two_part_side(
            context,
            state,
        )

    yield "Finalizing two-part mold system", lambda: finish_confirm_two_parts(
        context,
        state,
    )


def apply_two_part_base_keys(
    base: Object,
    keys: list[Object],
    operation: Literal["DIFFERENCE", "UNION"],
) -> None:
    if not keys:
        return

    joined_keys = join_object_group(keys, f"two_part_{operation.lower()}_keys")
    try:
        if operation == "DIFFERENCE":
            base.cut_plane(
                mathutils.Vector((0, 0, -1)),
                mathutils.Vector((0, 0, base.min_z + 0.1)),
            )
            if base.select_limit_flat_faces(max_co=False) == 0:
                base.select_face(base.get_limit_face_idx(axis=2, max_co=False))
            base.extrude_selected(-joined_keys.height)
            joined_keys.translate_whole(mathutils.Vector((0, 0, 0.1)))
            base -= joined_keys
        else:
            base.join(joined_keys)
            joined_keys = None
    finally:
        if joined_keys is not None:
            joined_keys.remove()


def _replace_circle_vertices(
    circle: Object, world_points: list[mathutils.Vector]
) -> None:
    if len(world_points) < 3:
        return

    local_points = [circle.inverse_matrix_world @ point for point in world_points]
    edges = [
        (index, (index + 1) % len(local_points)) for index in range(len(local_points))
    ]

    mesh = circle.object.data
    mesh.clear_geometry()
    mesh.from_pydata(local_points, edges, [])
    mesh.update()


def evenly_space_circle_vertices(circle: Object) -> None:
    points = resample_closed_loop_with_worker(
        circle.object,
        point_count=len(circle.object.data.vertices),
    )
    _replace_circle_vertices(circle, [mathutils.Vector(point) for point in points])


def redo_circle_vertices(circle: Object, spacing_mm: float) -> None:
    if spacing_mm <= 1.0e-6:
        return
    points = resample_closed_loop_with_worker(
        circle.object,
        spacing=float(spacing_mm),
    )
    _replace_circle_vertices(circle, [mathutils.Vector(point) for point in points])


def delete_circle_vertices_below_min_z(circle: Object, min_z: float) -> None:
    points = order_closed_loop_with_worker(
        circle.object,
        min_z=float(min_z),
    )
    _replace_circle_vertices(circle, [mathutils.Vector(point) for point in points])


def taper_pin_cube_right_face(pin_cube: Object, pin_size: float) -> None:
    right_face_size = pin_size * 0.7
    if pin_size <= 1e-6 or right_face_size <= 1e-6:
        return

    scale_factor = right_face_size / pin_size
    with BMeshObj(pin_cube, repair_winding=True) as bm:
        bm.faces.ensure_lookup_table()
        right_face = max(bm.faces, key=lambda face: face.calc_center_median().x)
        face_center = right_face.calc_center_median().copy()

        for vert in right_face.verts:
            vert.co.y = face_center.y + (vert.co.y - face_center.y) * scale_factor
            vert.co.z = face_center.z + (vert.co.z - face_center.z) * scale_factor


def build_pin_cube(
    name: str,
    point: mathutils.Vector,
    pin_size: float,
    x_offset: float,
) -> Object:
    pin_cube = Object(create_cube_primitive(pin_size), name)
    taper_pin_cube_right_face(pin_cube, pin_size)
    pin_cube.translate_whole(
        point + mathutils.Vector((x_offset, 0, 0)) - pin_cube.center_coords
    )
    return pin_cube


def duplicate_female_pin_refs(female_pins: list[Object]) -> list[Object]:
    """These pins are used for the half with males, just
    to generate the box with same tolerance pins size
    """
    female_refs = []
    for female_pin in female_pins:
        female_ref = female_pin.duplicate(name_adder="_ref")
        female_ref.name = f"{female_pin.name}_ref"
        female_refs.append(female_ref)
    return female_refs


def build_pin_cubes(
    circle: Object,
    pin_size: float,
    pin_tolerance: float,
    *,
    ordered_world_points=None,
) -> tuple[list[Object], list[Object], list[Object]]:
    if pin_size <= 1e-6:
        return [], [], []

    if ordered_world_points is None:
        ordered_world_points = order_closed_loop_with_worker(circle.object)
    world_points = [mathutils.Vector(point) for point in ordered_world_points]
    female_pins = []
    male_pins = []
    male_pin_size = max(pin_size - pin_tolerance, 0.1)
    pin_x_offset = pin_size / 2 - 0.1 - pin_tolerance / 2

    for index, point in enumerate(world_points):
        female_pins.append(
            build_pin_cube(f"female_{index}", point, pin_size, pin_x_offset)
        )
        male_pins.append(
            build_pin_cube(f"male_{index}", point, male_pin_size, pin_x_offset)
        )

    female_refs = duplicate_female_pin_refs(female_pins)
    return female_pins, male_pins, female_refs


@retry_after_heal
def cut_bot_from_patreon_min_z(
    side: Literal["left", "right"], moldbox_parts: list[Object]
) -> None:
    side_patron = Object(bpy.data.objects.get(side))
    side_patron_coos = side_patron.center_coords
    for left_part in moldbox_parts:
        left_part.cut_plane(
            mathutils.Vector((0, 0, -1)),
            mathutils.Vector(
                (side_patron_coos.x, side_patron_coos.y, side_patron.min_z + 0.02)
            ),
        )


def prepare_two_part_box_side(
    context,
    state: dict[str, object],
    side: Literal["left", "right"],
) -> None:
    context.scene.build_from_sphere = True
    if side == "left":
        target = state.get("target")
        if target is not None:
            target.remove()
            state["target"] = None

    source = state[f"{side}_source"]
    source.name = "patron"
    source.select()
    state[f"{side}_object_names_snap"] = set(obj.name for obj in bpy.data.objects)


def collect_two_part_box_side(
    context,
    state: dict[str, object],
    side: Literal["left", "right"],
) -> None:
    source = state[f"{side}_source"]
    object_names_snap = state[f"{side}_object_names_snap"]
    after_names_snap = set(obj.name for obj in bpy.data.objects)
    new_objects = after_names_snap - object_names_snap
    source.remove()

    box_parts: list[Object] = []
    for obj in bpy.data.objects:
        if obj.name in new_objects:
            obj.name = f"{side}_{obj.name}"
            box_parts.append(Object(obj))

    state[f"{side}_box_parts"] = box_parts
    _redraw_two_part_progress(context)


def finish_two_part_boxes(context, state: dict[str, object]) -> None:
    left_box_parts = state.get("left_box_parts", [])
    right_box_parts = state.get("right_box_parts", [])
    left_original_objects = state.get("left_original_objects", [])
    reference_master = state.get("reference_master")

    right_box = Object(bpy.data.objects.get("right_box"))
    translation = mathutils.Vector((0, right_box.depth + 50, 0))
    for obj in [*left_box_parts, *left_original_objects]:
        obj.translate_whole(translation)
        obj.origin_to_geometry()

    for part in left_original_objects:
        if "_ref" in part.name:
            part.remove()
    if reference_master is not None:
        reference_master.translate_whole(
            mathutils.Vector((0, right_box.depth * 2 + 100, 0))
        )
        reference_master.origin_to_geometry()

    if context.scene.pro_open_base:
        cut_parts_for_open_base()
        _redraw_two_part_progress(context)

    if context.scene.pro_casting_feet:
        build_casting_feet(left_box_parts, right_box_parts)
        _redraw_two_part_progress(context)

    cut_bot_from_patreon_min_z("left", left_box_parts)
    _redraw_two_part_progress(context)
    cut_bot_from_patreon_min_z("right", right_box_parts)
    _redraw_two_part_progress(context)


def build_boxes(
    context,
    target: Object | None,
    left_source: Object,
    right_source: Object,
    reference_master: Object | None = None,
    left_original_objects: list[Object] | None = None,
) -> None:
    if left_original_objects is None:
        left_original_objects = []
    state: dict[str, object] = {
        "target": target,
        "left_source": left_source,
        "right_source": right_source,
        "reference_master": reference_master,
        "left_original_objects": left_original_objects,
    }

    prepare_two_part_box_side(context, state, "left")
    build_box_operator(context)
    _redraw_two_part_progress(context)
    collect_two_part_box_side(context, state, "left")

    prepare_two_part_box_side(context, state, "right")
    build_box_operator(context)
    _redraw_two_part_progress(context)
    collect_two_part_box_side(context, state, "right")
    finish_two_part_boxes(context, state)


@retry_after_heal
def cut_parts_for_open_base() -> None:
    left = Object(bpy.data.objects.get("left"))
    for index, part in enumerate(get_side_box_parts("left")):
        if part.min_x < left.min_x - 0.1:
            logger.debug(f"Cutting {part.name} minx for open base")
            part.cut_plane(
                plane_normal=mathutils.Vector((-1, 0, 0)),
                plane_point=mathutils.Vector((left.min_x + 0.1, 0, 0)),
            )
        if index % 3 == 2:
            _redraw_two_part_progress()
    right = Object(bpy.data.objects.get("right"))
    for index, part in enumerate(get_side_box_parts("right")):
        logger.debug(f"Cutting {part.name} max for open base")
        if part.max_x > right.max_x + 0.1:
            part.cut_plane(
                plane_normal=mathutils.Vector((1, 0, 0)),
                plane_point=mathutils.Vector((right.max_x - 0.1, 0, 0)),
            )
        if index % 3 == 2:
            _redraw_two_part_progress()


def get_group_part(objects: list[Object], name_parts: tuple[str, ...]) -> Object | None:
    for obj in objects:
        lowered_name = obj.name.lower()
        if all(name_part in lowered_name for name_part in name_parts):
            return obj
    return None


def create_casting_foot(
    name: str,
    width: float,
    depth: float,
    height: float,
    center: mathutils.Vector,
) -> Object | None:
    if min(width, depth, height) <= 1e-6:
        return None

    foot = Object(create_cube_primitive(1), name)
    foot.scale_to(width, axis=0)
    foot.scale_to(depth, axis=1)
    foot.scale_to(height, axis=2)
    foot.translate_whole(center - foot.center_coords)
    foot.origin_to_geometry()
    assign_generated_material(foot.object)
    return foot


def build_casting_feet(
    left_box_parts: list[Object],
    right_box_parts: list[Object],
) -> None:
    left_box = get_group_part(left_box_parts, ("box",))
    right_box = get_group_part(right_box_parts, ("box",))
    left_channel = get_group_part(left_box_parts, ("channel",))
    right_channel = get_group_part(right_box_parts, ("channel",))
    left_funneler = get_group_part(left_box_parts, ("funnel",)) or get_group_part(
        left_box_parts, ("deposit",)
    )
    right_funneler = get_group_part(right_box_parts, ("funnel",)) or get_group_part(
        right_box_parts, ("deposit",)
    )

    if left_box and left_channel and left_funneler:
        left_width = max(left_box.max_x - left_funneler.center_coords.x, 0.1)
        left_center = mathutils.Vector(
            (
                left_box.max_x - left_width / 2,
                left_box.center_coords.y,
                left_channel.center_coords.z,
            )
        )
        create_casting_foot(
            "left_channel_casting_feet",
            left_width,
            left_box.depth / 4,
            left_channel.height,
            left_center,
        )

    if right_box and right_channel and right_funneler:
        right_width = max(right_funneler.center_coords.x - right_box.min_x, 0.1)
        right_center = mathutils.Vector(
            (
                right_box.min_x + right_width / 2,
                right_box.center_coords.y,
                right_channel.center_coords.z,
            )
        )
        create_casting_foot(
            "right_channel_casting_feet",
            right_width,
            right_box.depth / 4,
            right_channel.height,
            right_center,
        )


def get_side_box_parts(side: str) -> list[Object]:
    side_parts = []
    for obj in bpy.data.objects:
        if side in obj.name and side != obj.name:  # it would be the patron
            side_parts.append(Object(obj))
    return side_parts


def rotate_system_group(objects: list[Object], angle_degrees: float) -> None:
    rotation_matrix = mathutils.Matrix.Rotation(
        math.radians(angle_degrees),
        4,
        "Y",
    )
    for obj in objects:
        obj.rotate_whole(rotation_matrix, center=mathutils.Vector((0, 0, 0)))


def duplicate_object_group(objects: list[Object]) -> list[Object]:
    if not objects:
        return []

    deselect_all_objects()
    for obj in objects:
        obj.object.select_set(True)
    bpy.context.view_layer.objects.active = objects[0].object
    bpy.ops.object.duplicate()
    return [Object(obj) for obj in bpy.context.selected_objects]


def join_object_group(objects: list[Object], name: str) -> Object:
    if not objects:
        raise ValueError("No objects to join")

    deselect_all_objects()
    for obj in objects:
        obj.object.select_set(True)
    bpy.context.view_layer.objects.active = objects[0].object
    consumed_meshes = [obj.object.data for obj in objects]
    bpy.ops.object.join()
    remove_unused_meshes(consumed_meshes)
    joined = Object(bpy.context.view_layer.objects.active)
    joined.name = name
    return joined


def center_object_group(group_root: Object) -> mathutils.Vector:
    translation = mathutils.Vector(
        (
            -group_root.center_coords.x,
            -group_root.center_coords.y,
            -group_root.min_z,
        )
    )
    group_root.object.location += translation
    return translation


def apply_group_translation(
    objects: list[Object],
    translation: mathutils.Vector,
) -> None:
    for obj in objects:
        obj.object.location += translation


def prepare_box_sources(
    left_part: Object,
    right_part: Object,
    female_pins: list[Object],
    male_pins: list[Object],
    female_refs: list[Object],
    open_base: bool,
    pin_tolerance: float,
    left_sync_objects: list[Object] | None = None,
    right_sync_objects: list[Object] | None = None,
) -> tuple[Object, Object]:
    if left_sync_objects is None:
        left_sync_objects = []
    if right_sync_objects is None:
        right_sync_objects = []

    left_translation = center_object_group(left_part)
    apply_group_translation(
        [*male_pins, *female_refs, *left_sync_objects],
        left_translation,
    )
    if open_base:
        kept_female_refs = []
        for pin in female_refs:
            if pin.min_x < left_part.min_x:
                pin.remove()
            else:
                kept_female_refs.append(pin)
        female_refs[:] = kept_female_refs

        kept_male_pins = []
        for pin in male_pins:
            if pin.min_x < left_part.min_x + pin_tolerance:
                pin.remove()
            else:
                kept_male_pins.append(pin)
        male_pins[:] = kept_male_pins
    left_source_duplicates = duplicate_object_group([left_part, *female_refs])
    left_box_source = join_object_group(left_source_duplicates, "left_box_source")

    right_translation = center_object_group(right_part)
    apply_group_translation([*female_pins, *right_sync_objects], right_translation)
    if open_base:
        kept_female_pins = []
        for pin in female_pins:
            if pin.max_x > right_part.max_x:
                pin.remove()
            else:
                kept_female_pins.append(pin)
        female_pins[:] = kept_female_pins
    right_source_duplicates = duplicate_object_group([right_part, *female_pins])
    right_box_source = join_object_group(right_source_duplicates, "right_box_source")

    return left_box_source, right_box_source


@retry_after_heal
def split_system(
    target: Object,
    left_name: str = "left",
    right_name: str = "right",
) -> tuple[Object, Object]:
    # split_optimized consumes its input while separating mesh islands. Keep
    # the caller-owned patron/master intact and preserve every island assigned
    # to each side of the split.
    split_source = target.duplicate(name_adder="_two_parts_split_source")
    master_voxel_size = get_master_voxel_size(
        bpy.context.scene.master_quality,
        split_source,
    )
    left_part, right_part = split_source.split_optimized(
        plane_normal=mathutils.Vector((1, 0, 0)),
        plane_point=mathutils.Vector((0, 0, 0)),
        preserve_isolated_meshes=True,
        retry_remesh=build_voxel_modifier(master_voxel_size),
    )
    left_part.name = left_name
    right_part.name = right_name
    return left_part, right_part


def build_pins_circle(
    target_raw,
    open_base: bool = True,
    pin_size: float = 10,
    pin_tolerance: float = 0.3,
):
    target = Object(target_raw)
    target.apply_all_transforms()
    wrap_distance = pin_size * 1
    circle = Object(create_circle_primitive(1), "two_parts_circle")
    circle.hide_during_ui_breathe = True
    circle.object.hide_render = True
    circle.rotate_whole(mathutils.Matrix.Rotation(math.radians(90), 4, "Y"))
    circle.scale_to(target.depth * TWO_PARTS_CIRCLE_SCALE_MULTIPLIER, axis=1)
    circle.scale_to(target.height * TWO_PARTS_CIRCLE_SCALE_MULTIPLIER, axis=2)
    circle.translate_whole(target.center_coords - circle.center_coords)
    fitted_points = fit_pin_circle_with_worker(
        target,
        circle.object,
        offset=wrap_distance,
        pass_count=3,
    )
    _replace_circle_vertices(
        circle,
        [mathutils.Vector(point) for point in fitted_points],
    )
    circle.scale(0, axis=0)
    pin_points = resample_closed_loop_with_worker(
        circle.object,
        spacing=pin_size * 2,
        min_z=(target.min_z + pin_size / 2) if open_base else None,
    )
    _replace_circle_vertices(
        circle,
        [mathutils.Vector(point) for point in pin_points],
    )
    female_pins, male_pins, female_refs = build_pin_cubes(
        circle,
        pin_size,
        pin_tolerance,
        ordered_world_points=pin_points,
    )

    circle.remove()
    return target, female_pins, male_pins, female_refs


def begin_build_pins_circle(
    target_raw,
    open_base: bool = True,
    pin_size: float = 10,
    pin_tolerance: float = 0.3,
):
    target = Object(target_raw)
    target.apply_all_transforms()
    wrap_distance = pin_size
    circle = Object(create_circle_primitive(1), "two_parts_circle")
    circle.hide_during_ui_breathe = True
    circle.object.hide_render = True
    circle.rotate_whole(mathutils.Matrix.Rotation(math.radians(90), 4, "Y"))
    circle.scale_to(target.depth * TWO_PARTS_CIRCLE_SCALE_MULTIPLIER, axis=1)
    circle.scale_to(target.height * TWO_PARTS_CIRCLE_SCALE_MULTIPLIER, axis=2)
    circle.translate_whole(target.center_coords - circle.center_coords)
    fit_task = begin_fit_pin_circle_with_worker(
        target,
        circle.object,
        offset=wrap_distance,
        pass_count=3,
    )

    def steps():
        try:
            fitted_points = yield fit_task
            _replace_circle_vertices(
                circle,
                [mathutils.Vector(point) for point in fitted_points],
            )
            circle.scale(0, axis=0)
            pin_points = yield begin_resample_closed_loop_with_worker(
                circle.object,
                spacing=pin_size * 2,
                min_z=(target.min_z + pin_size / 2) if open_base else None,
            )
            _replace_circle_vertices(
                circle,
                [mathutils.Vector(point) for point in pin_points],
            )
            female_pins, male_pins, female_refs = build_pin_cubes(
                circle,
                pin_size,
                pin_tolerance,
                ordered_world_points=pin_points,
            )
            return target, female_pins, male_pins, female_refs
        finally:
            if circle.object.name in bpy.data.objects:
                circle.remove()

    return BackgroundTaskSequence(steps())
