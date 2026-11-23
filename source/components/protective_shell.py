from collections.abc import Callable, Iterator
import math

import mathutils  # type: ignore

from ..bl_utils import configure_metric_millimeter_units
from ..materials import (
    assign_protective_shell_material,
    refresh_viewport_material_display,
)
from ..modifiers import diff_mod
from ..object import Object
from ..split_specs import split_specs_query_values
from ..primitives import (
    MOLD_BODY_CYLINDER_VERTICES,
    create_cube_primitive,
    create_cylinder_primitive,
)
from ..progress import force_viewport_redraw
from ..voxel_size import get_box_voxel_size
from .clear_undercuts import begin_clear_undercuts
from .direct_mold import (
    apply_direct_split_barrier_grid,
    create_direct_mold_clips,
    extra_confirm_direct_mold_req,
    extra_confirm_direct_mold_req_async,
    prepare_direct_printed_mold_for_split,
    trim_nonvertical_direct_clamp_systems_to_box,
)
from .direct_split_planes import (
    DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY,
    direct_split_plane_specs,
    remove_direct_split_planes,
    sync_direct_split_planes_with_scene,
)
from .direct_split_execution import split_object_by_direct_plane_specs
from .manual_booleans import apply_clamp_booleans_after_server_import
from .mesh_envelope import OptimizedMeshEnvelope, begin_optimized_mesh_envelope
from .vertical_edge_bevel import bevel_vertical_edges


ProtectiveShellStep = tuple[str, Callable[[], object]]
PROTECTIVE_SHELL_MARKER = "moldboxer_protective_shell"
PROTECTIVE_SHELL_CLAMP_TOLERANCE = 0.25


def _protective_shell_wrapper(
    target: Object,
    *,
    distance: float,
    voxel_size: float,
) -> Object:
    return OptimizedMeshEnvelope(
        target,
        voxel_size,
        distance=distance,
        n_wraps=2,
        build_from_sphere=False,
        cut_bot=False,
    )


def _begin_protective_shell_wrapper(
    target: Object,
    *,
    distance: float,
    voxel_size: float,
):
    return begin_optimized_mesh_envelope(
        target,
        voxel_size,
        distance=distance,
        n_wraps=2,
        build_from_sphere=False,
        cut_bot=False,
    )


def _primitive_protective_shell_body(
    clearance: Object,
    *,
    thickness: float,
    shape_type: str,
) -> Object:
    width = clearance.width + thickness * 2.0
    depth = clearance.depth + thickness * 2.0
    height = clearance.height + thickness * 2.0
    if shape_type == "cube":
        body = Object(create_cube_primitive(1.0), "box")
        body.scale_to(width, axis=0)
        body.scale_to(depth, axis=1)
    elif shape_type == "cylinder":
        body = Object(
            create_cylinder_primitive(
                0.5,
                1.0,
                vertices=MOLD_BODY_CYLINDER_VERTICES,
            ),
            "box",
        )
        diameter = math.hypot(clearance.width, clearance.depth) + thickness * 2.0
        body.scale_to(diameter, axis=0)
        body.scale_to(diameter, axis=1)
    else:
        raise ValueError(
            f"Unsupported primitive protective shell shape: {shape_type}"
        )

    body.scale_to(height, axis=2)
    body.translate_whole(clearance.center_coords)
    body.apply_all_transforms()
    if shape_type == "cube":
        bevel_vertical_edges(body)
    return body


def iter_generate_protective_shell_steps(
    context,
    *,
    target_object=None,
    async_server: bool = False,
) -> Iterator[ProtectiveShellStep]:
    """Build a split shell while clearing undercuts on its first wrapper only."""
    scene = context.scene
    sync_direct_split_planes_with_scene()
    split_plane_specs = direct_split_plane_specs(
        log_context="Protective Shell server capture",
    )
    split_planes, organic_split_planes = split_specs_query_values(
        split_plane_specs
    )
    state: dict[str, object] = {
        "split_plane_specs": split_plane_specs,
    }
    had_hidden_setting = DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY in scene
    original_hidden_setting = bool(
        scene.get(DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY, False)
    )
    original_box_thickness = float(scene.box_thickness)

    scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY] = True
    remove_direct_split_planes()

    def generate_clearance_wrapper():
        configure_metric_millimeter_units()
        raw_target = target_object or getattr(context, "object", None)
        if raw_target is None or getattr(raw_target, "type", None) != "MESH":
            raise RuntimeError(
                "No imported mesh available for Protective Shell generation"
            )
        patron = Object(raw_target)
        patron.select()
        voxel_size = get_box_voxel_size(
            scene.protective_shell_box_quality,
            patron,
        )
        task = _begin_protective_shell_wrapper(
            patron,
            distance=float(scene.protective_shell_fit_tolerance),
            voxel_size=voxel_size,
        )
        state["voxel_size"] = voxel_size

        def finish(clearance):
            clearance.name = "protective_shell_clearance"
            state["clearance"] = clearance
            return clearance

        return task.then(finish)

    def clear_first_wrapper_undercuts():
        clearance = state["clearance"]
        return begin_clear_undercuts(
            target_object=clearance,
            bidirectional=True,
            voxel_size=state["voxel_size"],
            target_retry_voxel_size=state["voxel_size"],
            target_point=mathutils.Vector((0.0, 0.0, 0.0)),
            plane_direction=mathutils.Vector((1.0, 0.0, 0.0)),
            split_plane_specs=state["split_plane_specs"],
            restrict_bottom_extraction=False,
            progress_callback=lambda _label: force_viewport_redraw(context),
            display_extraction_directions=False,
        )

    def generate_shell_body():
        clearance = state["clearance"]
        thickness = float(scene.protective_shell_thickness)
        shape_type = str(scene.protective_shell_shape_type).lower()
        if shape_type == "adapted":
            # The already-cleared first wrapper is the only source for this
            # second wrapper. Do not run undercut clearance on the body again.
            task = _begin_protective_shell_wrapper(
                clearance,
                distance=thickness,
                voxel_size=state["voxel_size"],
            )
            def finish(body):
                body.name = "box"
                bottom_clean_height = max(thickness - 1.0, 0.0)
                if bottom_clean_height > 0.0:
                    body.clean_bot(bottom_clean_height)
                body.object[PROTECTIVE_SHELL_MARKER] = True
                assign_protective_shell_material(body.object)
                state["body"] = body
                return body

            return task.then(finish)
        else:
            body = _primitive_protective_shell_body(
                clearance,
                thickness=thickness,
                shape_type=shape_type,
            )
            body.object[PROTECTIVE_SHELL_MARKER] = True
            assign_protective_shell_material(body.object)
            state["body"] = body
        return None

    def subtract_clearance() -> None:
        body = state["body"]
        clearance = state["clearance"]
        body.apply_boolean_modifier_with_geometry_fallback(
            diff_mod,
            clearance,
        )
        clearance.remove()

    def restore_box_thickness() -> None:
        scene.box_thickness = original_box_thickness

    def finish_clamp_import() -> None:
        try:
            trim_nonvertical_direct_clamp_systems_to_box(split_plane_specs)
        finally:
            restore_box_thickness()

    def request_split_clamps():
        if not split_plane_specs:
            return None
        scene.box_thickness = float(scene.protective_shell_thickness)
        request = (
            extra_confirm_direct_mold_req_async
            if async_server
            else extra_confirm_direct_mold_req
        )
        return request(
            box_voxel_size=state["voxel_size"],
            box_thickness=float(scene.protective_shell_thickness),
            clamp_width=float(scene.clamp_width),
            clamp_depth=float(scene.clamp_depth),
            barrier_tolerance=PROTECTIVE_SHELL_CLAMP_TOLERANCE,
            split_planes=split_planes,
            organic_split_planes=organic_split_planes,
            pin_system_type="PIN",
            clamp_pin_type="pin",
            after_import=finish_clamp_import,
        )

    def apply_clamp_booleans() -> None:
        if not split_plane_specs:
            return
        apply_clamp_booleans_after_server_import(
            screw_mode=False,
        )

    def join_clamps_to_shell() -> None:
        if not split_plane_specs:
            return
        prepare_direct_printed_mold_for_split(split_plane_specs)

    def split_shell() -> None:
        body = state["body"]
        if not split_plane_specs:
            body.name = "protective_shell"
            state["parts"] = [body]
            return
        parts = split_object_by_direct_plane_specs(
            body,
            split_plane_specs,
            preserve_isolated_meshes=True,
        )
        apply_direct_split_barrier_grid(parts, split_plane_specs)
        for index, part in enumerate(parts, start=1):
            part.name = f"protective_shell_part_{index:02d}"
            part.object[PROTECTIVE_SHELL_MARKER] = True
        state["parts"] = parts

    def generate_locking_clips() -> None:
        if not split_plane_specs:
            return
        parts = state["parts"]
        if not parts:
            return
        create_direct_mold_clips(scene)
        system_min_x = min(part.min_x for part in parts)
        system_max_x = max(part.max_x for part in parts)
        from .confirm_mold import place_clips_left_of_patron

        place_clips_left_of_patron(
            reference_width=system_max_x - system_min_x,
        )

    def finalize_shell() -> None:
        parts = state["parts"]
        if parts:
            parts[0].select()
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)

    try:
        yield (
            "Generating Protective Shell clearance wrapper",
            generate_clearance_wrapper,
        )
        yield "Clearing Protective Shell undercuts", clear_first_wrapper_undercuts
        yield "Generating Protective Shell body", generate_shell_body
        yield "Generating Protective Shell clamps", request_split_clamps
        yield "Applying Protective Shell clamp booleans", apply_clamp_booleans
        yield "Joining Protective Shell clamps", join_clamps_to_shell
        yield "Subtracting Protective Shell clearance", subtract_clearance
        yield "Splitting Protective Shell", split_shell
        yield "Generating Protective Shell locking clips", generate_locking_clips
        yield "Finalizing Protective Shell", finalize_shell
    finally:
        restore_box_thickness()
        if had_hidden_setting:
            scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY] = original_hidden_setting
        elif DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY in scene:
            del scene[DIRECT_SPLIT_PLANE_UI_HIDDEN_KEY]
