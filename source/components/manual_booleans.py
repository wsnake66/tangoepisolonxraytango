import logging
import time
from contextlib import contextmanager

import bpy  # type: ignore
import mathutils  # type: ignore

from ..materials import assign_moldbox_material
from ..modifiers import diff_mod
from ..object import Object
from ..progress import force_viewport_redraw
from .base_substracter_visibility import (
    set_base_substracter_hidden,
    set_object_hidden,
)
from .clamp_reinforcement import add_vertical_reinforcements_to_clamps
from ._q7x import mirror_pending_casting_subtraction, pending_casting_boxes
from .slip_casting_box_shape import extend_primitive_opening_cutter, extrude_primitive_opening_caps

logger = logging.getLogger(__name__)


def _object_name_matches(obj_name: str, name: str) -> bool:
    obj_name = obj_name.lower()
    name = name.lower()
    return obj_name == name or obj_name.startswith(f"{name}.")


def _mesh_object(name: str) -> Object | None:
    obj = bpy.data.objects.get(name)
    if obj is not None and obj.type == "MESH":
        return Object(obj)

    for candidate in bpy.data.objects:
        if candidate.type == "MESH" and _object_name_matches(candidate.name, name):
            return Object(candidate)

    return None


def _mesh_object_latest(name: str) -> Object | None:
    matches = [
        candidate
        for candidate in bpy.data.objects
        if candidate.type == "MESH" and _object_name_matches(candidate.name, name)
    ]
    if not matches:
        return None
    matches.sort(key=lambda obj: obj.name)
    return Object(matches[-1])


def _mesh_objects(prefix: str) -> list[Object]:
    prefix = prefix.lower()
    return [
        Object(obj)
        for obj in bpy.data.objects
        if obj.type == "MESH" and obj.name.lower().startswith(prefix)
    ]


def _screw_objects_for_clamp_system(system_name: str) -> list[Object]:
    normalized_system = system_name.lower()
    all_screws = _mesh_objects("screw_")
    targeted_screws = [
        screw
        for screw in all_screws
        if screw.name.lower().split(".", 1)[0].endswith(f"_{normalized_system}")
    ]
    if targeted_screws:
        return targeted_screws

    # Preserve compatibility with the older screw_<system>_<index> naming.
    legacy_prefix = f"screw_{normalized_system}_"
    return [
        screw
        for screw in all_screws
        if screw.name.lower().startswith(legacy_prefix)
    ]


def _remove_if_exists(obj: Object | None) -> None:
    if obj is not None and obj.object.name in bpy.data.objects:
        obj.object.hide_set(False)
        obj.object.hide_viewport = False
        obj.remove()


def _object_visibility_state(obj: bpy.types.Object) -> tuple[bool, bool, bool]:
    return (obj.hide_get(), obj.hide_viewport, obj.hide_render)


@contextmanager
def _temporarily_visible(obj: bpy.types.Object):
    visibility_state = _object_visibility_state(obj)
    try:
        set_object_hidden(obj, False)
        yield
    finally:
        was_hidden, was_hide_viewport, was_hide_render = visibility_state
        obj.hide_set(was_hidden)
        obj.hide_viewport = was_hide_viewport
        obj.hide_render = was_hide_render


def _subtract(target: Object | None, cutter: Object | None) -> bool:
    if target is None or cutter is None:
        return False

    logger.debug("Subtracting %s from %s", cutter.name, target.name)
    start_time = time.perf_counter()
    with _temporarily_visible(cutter.object):
        target.apply_boolean_modifier_with_geometry_fallback(diff_mod, cutter)
    logger.debug(
        "Subtracted %s from %s in %.3fs",
        cutter.name,
        target.name,
        time.perf_counter() - start_time,
    )
    return True


def _object_bounds_for_log(obj: Object) -> str:
    return (
        f"x=({obj.min_x:.3f},{obj.max_x:.3f}) "
        f"y=({obj.min_y:.3f},{obj.max_y:.3f}) "
        f"z=({obj.min_z:.3f},{obj.max_z:.3f})"
    )


def prepare_base_substracter_after_server_import() -> None:
    scene = bpy.context.scene
    base_substracter = _mesh_object_latest("base_substracter")
    if base_substracter is None:
        return

    start_time = time.perf_counter()
    movement_distance = float(scene.base_thickness) * 2
    logger.debug(
        "Moving top and bottom faces of %s outward by %.3f",
        base_substracter.name,
        movement_distance,
    )
    try:
        with _temporarily_visible(base_substracter.object):
            bottom_face_count = base_substracter.select_limit_flat_faces(max_co=False)
            if bottom_face_count > 0:
                base_substracter.move_selected(-movement_distance)
            else:
                logger.warning(
                    "Could not find a flat bottom face on %s; skipping movement",
                    base_substracter.name,
                )

            top_face_count = base_substracter.select_limit_flat_faces(max_co=True)
            if top_face_count > 0:
                base_substracter.move_selected(movement_distance)
            else:
                logger.warning(
                    "Could not find a flat top face on %s; skipping movement",
                    base_substracter.name,
                )

            if bottom_face_count > 0 or top_face_count > 0:
                base_substracter.recalculate_normals()

            assign_moldbox_material(base_substracter.object)
    finally:
        set_base_substracter_hidden(True)
    logger.debug(
        "Prepared %s in %.3fs",
        base_substracter.name,
        time.perf_counter() - start_time,
    )


def _apply_clamp_manual_booleans(axis: str, screw_mode: bool) -> None:
    start_time = time.perf_counter()
    clamp_prefix = f"clamp_optimized_{axis}"
    optimized_clamps = _mesh_objects(clamp_prefix)
    if not optimized_clamps and axis in {"x", "y"}:
        legacy_clamp = _mesh_object("clamp_l" if axis == "x" else "clamp_r")
        if legacy_clamp is not None:
            optimized_clamps = [legacy_clamp]
    if not optimized_clamps:
        logger.warning(
            "Clamp Boolean mapping: axis=%s screw_mode=%s targets=none",
            axis,
            screw_mode,
        )
        return
    logger.warning(
        "Clamp Boolean mapping: axis=%s screw_mode=%s targets=%s",
        axis,
        screw_mode,
        ", ".join(clamp.name for clamp in optimized_clamps),
    )

    for optimized in optimized_clamps:
        normalized_name = optimized.name.lower().split(".", 1)[0]
        system_name = (
            normalized_name[len("clamp_optimized_") :]
            if normalized_name.startswith("clamp_optimized_")
            else axis
        )
        stepper = _mesh_object(f"clamp_stepper_{system_name}")
        stepper_substracter = _mesh_object(
            f"clamp_stepper_substracter_{system_name}"
        )
        screw_objects = (
            _screw_objects_for_clamp_system(system_name) if screw_mode else []
        )
        logger.warning(
            "Clamp screw mapping: axis=%s system=%s target=%s "
            "target_bounds=[%s] cutters=%s",
            axis,
            system_name,
            optimized.name,
            _object_bounds_for_log(optimized),
            ", ".join(screw.name for screw in screw_objects) or "none",
        )

        try:
            if stepper is not None:
                _subtract(stepper, stepper_substracter)
                _subtract(optimized, stepper)

            for screw in screw_objects:
                logger.warning(
                    "Subtracting mapped screw: cutter=%s cutter_bounds=[%s] "
                    "target=%s target_bounds=[%s]",
                    screw.name,
                    _object_bounds_for_log(screw),
                    optimized.name,
                    _object_bounds_for_log(optimized),
                )
                _subtract(optimized, screw)
        finally:
            for screw in screw_objects:
                _remove_if_exists(screw)
            _remove_if_exists(stepper_substracter)
            _remove_if_exists(stepper)
    logger.debug(
        "Applied manual clamp booleans for axis %s in %.3fs",
        axis,
        time.perf_counter() - start_time,
    )


def _apply_male_barrier_base_booleans() -> None:
    start_time = time.perf_counter()
    base_substracter = _mesh_object_latest("base_substracter")
    male_barriers = _mesh_objects("barrier_male")
    if base_substracter is None or not male_barriers:
        return

    for male_barrier in male_barriers:
        _subtract(male_barrier, base_substracter)

    logger.debug(
        "Subtracted base from %d male barrier%s in %.3fs",
        len(male_barriers),
        "" if len(male_barriers) == 1 else "s",
        time.perf_counter() - start_time,
    )


def _prepare_base_top_stepper() -> None:
    base_top_stepper = _mesh_object("base_top_stepper")
    base_top_stepper_inner_cutter = _mesh_object("base_top_stepper_inner_cutter")
    if base_top_stepper is not None:
        _subtract(base_top_stepper, base_top_stepper_inner_cutter)


def _apply_prepared_base_top_stepper() -> None:
    start_time = time.perf_counter()
    base = _mesh_object("base")
    base_top_stepper = _mesh_object("base_top_stepper")
    base_top_stepper_inner_cutter = _mesh_object("base_top_stepper_inner_cutter")
    try:
        if base_top_stepper is not None:
            _subtract(base, base_top_stepper)
    finally:
        _remove_if_exists(base_top_stepper_inner_cutter)
        _remove_if_exists(base_top_stepper)
    logger.debug(
        "Applied manual base booleans in %.3fs",
        time.perf_counter() - start_time,
    )


def subtract_base_substracter_from_box(*, extend_opening: bool = False, extrude_caps: bool = False) -> bool:
    """Trim the assembled box and retain its cutter for an inner-core socket."""
    box = _mesh_object("box")
    base_substracter = _mesh_object_latest("base_substracter")
    if box is None or base_substracter is None:
        return False

    if extrude_caps:
        bounds = [box, *pending_casting_boxes()]
        # Channel trimming permits a 0.01 mm overshoot. Extending only the
        # highest cap then extends the channels, leaving a thin roof above
        # the main cube. Cut the temporary opener to a common plane first.
        # This changes only the cutter; the assembled box keeps its height.
        top_cleanup = min(0.1, base_substracter.height * 0.25)
        base_substracter.cut_plane(
            mathutils.Vector((0, 0, 1)),
            mathutils.Vector((0, 0, base_substracter.max_z - top_cleanup)),
        )
        extrude_primitive_opening_caps(
            base_substracter,
            bottom_z=min(part.min_z for part in bounds) - 1.0,
            top_z=max(part.max_z for part in bounds) + 1.0,
        )
    elif extend_opening:
        top_z = max([box.max_z, *(part.max_z for part in pending_casting_boxes())])
        extend_primitive_opening_cutter(base_substracter, top_z + max(box.height, 1.0))

    preserve_for_inner_core = bool(
        getattr(getattr(bpy.context, "scene", None), "pro_inner_cavity", False)
    )
    try:
        mirror_pending_casting_subtraction(base_substracter)
        return _subtract(box, base_substracter)
    finally:
        if preserve_for_inner_core:
            set_base_substracter_hidden(True)
        else:
            _remove_if_exists(base_substracter)


def apply_manual_booleans_after_server_import(
    screw_mode: bool = False,
    *,
    include_clamps: bool = True,
) -> None:
    """Apply server-provided helper cutters that Blender must resolve locally."""
    start_time = time.perf_counter()
    for _label, step in iter_manual_booleans_after_server_import(
        screw_mode,
        include_clamps=include_clamps,
    ):
        step()
    _remove_if_exists(_mesh_object_latest("base_substracter"))
    logger.debug(
        "Applied all manual booleans after server import in %.3fs",
        time.perf_counter() - start_time,
    )


def apply_clamp_booleans_after_server_import(screw_mode: bool = False) -> None:
    """Apply server-provided clamp cutters that Blender must resolve locally."""
    start_time = time.perf_counter()
    for step in (
        add_vertical_reinforcements_to_clamps,
        lambda: _apply_clamp_manual_booleans("y", screw_mode),
        lambda: _apply_clamp_manual_booleans("x", screw_mode),
        lambda: _apply_clamp_manual_booleans("z", screw_mode),
        _apply_male_barrier_base_booleans,
    ):
        _run_boolean_step(step)
    logger.debug(
        "Applied clamp manual booleans after server import in %.3fs",
        time.perf_counter() - start_time,
    )


def _run_boolean_step(step) -> None:
    set_base_substracter_hidden(True)
    force_viewport_redraw()
    step()
    set_base_substracter_hidden(True)
    force_viewport_redraw()


def iter_manual_booleans_after_server_import(
    screw_mode: bool = False,
    *,
    include_clamps: bool = True,
):
    """Yield manual boolean batches so modal operators can repaint between them."""
    if include_clamps:
        yield "Adding clamp reinforcements", (
            lambda: _run_boolean_step(add_vertical_reinforcements_to_clamps)
        )
        yield "Applying clamp booleans Y", (
            lambda: _run_boolean_step(
                lambda: _apply_clamp_manual_booleans("y", screw_mode)
            )
        )
        yield "Applying clamp booleans X", (
            lambda: _run_boolean_step(
                lambda: _apply_clamp_manual_booleans("x", screw_mode)
            )
        )
        yield "Applying clamp booleans Z", (
            lambda: _run_boolean_step(
                lambda: _apply_clamp_manual_booleans("z", screw_mode)
            )
        )
        yield "Applying male barrier base booleans", (
            lambda: _run_boolean_step(_apply_male_barrier_base_booleans)
        )
    yield "Preparing base top stepper", (
        lambda: _run_boolean_step(_prepare_base_top_stepper)
    )
    yield "Applying base top stepper", (
        lambda: _run_boolean_step(_apply_prepared_base_top_stepper)
    )
