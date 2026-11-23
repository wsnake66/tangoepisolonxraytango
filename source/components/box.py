import logging

from ..slip_casting_base_pairs import slip_casting_uses_base

import bpy  # type: ignore
import mathutils  # type: ignore
from collections.abc import Callable, Iterator

from ..bl_utils import configure_metric_millimeter_units, retry_after_heal
from ..background_worker import BackgroundTaskSequence, finish_task_sync
from ..object import Object, remove_objects_safely
from ..mold_types import is_slip_casting_type, is_silicone_multipart_type, is_slip_casting_vase_type, is_multipart_type
from ..mold_types import silicone_multipart_bottom_extension, slip_casting_funnels_on_top
from ..split_specs import split_specs_query_values
from .mesh_envelope import begin_optimized_mesh_envelope
from .slip_casting_box_shape import begin_primitive_box, extrude_primitive_opening_caps
from .clear_undercuts import (
    begin_clear_undercuts,
    bottom_reference_plane,
    inner_core_undercut_plane_specs,
)
from .clear_undercuts_overlay import clear_extraction_direction_arrows
from .preprocess import preprocess_patron
from .channels_deposit import (
    add_deposit,
    clean_channels_bot_to_box_height,
    request_channels_deposit,
    request_channels_deposit_async,
    scene_channels_deposit_extraction,
    scene_channel_adjustment,
)
from .watermark_payload import build_watermark_text
from .box_parts import get_effective_box_parts, resolve_splitter_plane_specs
from .direct_split_planes import (
    capture_silicone_split_plane_specs,
    store_silicone_split_plane_specs,
)
from .funnel_reference_line import effective_silicone_funneler_offset
from ..materials import (
    assign_generated_material,
    refresh_generated_object_materials,
    refresh_viewport_material_display,
)
from ..patron_lifecycle import get_master_for_base_operations, hide_working_patron
from ..progress import breathe_viewport, force_viewport_redraw, hide_split_key_wrappers
from ..voxel_size import get_box_voxel_size

BuildBoxStep = tuple[str, Callable[[], None]]
BOX_SKIP_REDRAW_STEPS = {
    "Generating channels and funneler",
    "Generating funneler",
    "Refreshing materials",
}
SLIP_CASTING_HALF_BOX_WRAPPER_NAME = "box_slip_casting_half_wrapper"
logger = logging.getLogger(__name__)


def _pad_slip_casting_primitive_vertically(scene) -> bool:
    """Keep a closed, no-foot external-funnel mold above the master."""
    return (
        is_silicone_multipart_type(scene.mold_type_preview)
        or (
            is_slip_casting_type(scene.mold_type_preview)
            and not slip_casting_uses_base(scene)
            and not slip_casting_funnels_on_top(scene)
        )
    )


def _normalized_funneler_ref_height(scene) -> float:
    return min(max(float(scene.funneler_ref_height), 1.0), 99.0) / 100.0


def _slip_casting_vase_funneler_ref_height(context) -> float:
    """Place the Vase funneler one mold thickness below the master top."""

    box = Object(bpy.data.objects.get("box"))
    master = get_master_for_base_operations()
    if box.height <= 1e-9:
        return 0.01
    start_z = master.max_z - max(float(context.scene.box_gap), 0.0)
    return min(max((start_z - box.min_z) / box.height, 0.01), 1.0)


def _box_target(target_object=None) -> Object:
    raw_target = (
        target_object.object
        if isinstance(target_object, Object)
        else target_object
    )
    if raw_target is None:
        raw_target = bpy.data.objects.get("patron")
    if raw_target is None or raw_target.type != "MESH":
        raise RuntimeError("Box generation requires a mesh target")
    return Object(raw_target)


def extend_multipart_wrapper_bottom(wrapper, scene, *, key_wrapper=False):
    """Lower a flat wrapper bottom without changing its sides or top."""
    extension = silicone_multipart_bottom_extension(scene)
    if (key_wrapper and is_slip_casting_type(scene.mold_type_preview)
            and slip_casting_funnels_on_top(scene)
            and not getattr(scene, "slip_casting_generate_base", True)):
        extension *= 0.5
    if extension > 0:
        extrude_primitive_opening_caps(
            wrapper, bottom_z=wrapper.min_z - extension, top_z=wrapper.max_z,
        )


def generate_box_wrapper(context, *, target_object=None, shape_type="adapted"):
    configure_metric_millimeter_units()
    if target_object is None:
        preprocess_patron(center=False, check_manifold=False)
    box_voxel_size = get_box_voxel_size(context.scene.box_quality)
    patron = _box_target(target_object)
    patron.select()
    slip_casting = is_multipart_type(context.scene.mold_type_preview)
    task = begin_primitive_box(
        patron, distance=context.scene.box_gap, shape_type=shape_type,
        vertical_faces=getattr(
            context.scene,
            "slip_casting_box_faces" if slip_casting else "mold_box_faces",
            4,
        ),
        pad_vertical=(
            not is_slip_casting_type(context.scene.mold_type_preview)
            or _pad_slip_casting_primitive_vertically(context.scene)
        ),
    ) if shape_type != "adapted" else begin_optimized_mesh_envelope(
        patron,
        box_voxel_size,
        distance=context.scene.box_gap,
        n_wraps=2,
        build_from_sphere=context.scene.build_from_sphere,
        cut_bot=False,
        sphere_voxel_factor=1,
    )

    def finish(box):
        # The completed envelope is the visible box preview, not a cutter.
        box.hide_during_ui_breathe = False
        hide_working_patron()
        if target_object is not None:
            patron.object.hide_set(True)
            patron.object.hide_viewport = True
            patron.object.hide_render = True
        assign_generated_material(box.object)
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)
        return box

    return task.then(finish)


def generate_slip_casting_half_box_wrapper(context, *, target_object=None, nominal=False):
    """Build the contour used to position multipart split-base keys."""
    wrapper_name = SLIP_CASTING_HALF_BOX_WRAPPER_NAME + ("_nominal" if nominal else "")
    configure_metric_millimeter_units()
    for existing_wrapper in list(bpy.data.objects):
        if existing_wrapper.name == wrapper_name:
            remove_objects_safely((existing_wrapper,))
    box_voxel_size = get_box_voxel_size(context.scene.box_quality)
    patron = _box_target(target_object)
    patron.select()
    shape_type = getattr(context.scene, "slip_casting_shape_type", "adapted")
    key_distance = float(context.scene.box_gap) / 2.0
    if is_silicone_multipart_type(context.scene.mold_type_preview):
        if context.scene.channels and not nominal:
            # Split channels provide extra material outside the nominal mold wall.
            key_distance += max(float(context.scene.channel_depth), 0.0) / 2.0
    task = begin_primitive_box(
        patron, distance=key_distance, shape_type=shape_type,
        vertical_faces=getattr(context.scene, "slip_casting_box_faces", 4),
        pad_vertical=_pad_slip_casting_primitive_vertically(context.scene),
    ) if shape_type != "adapted" else begin_optimized_mesh_envelope(
        patron,
        box_voxel_size,
        distance=key_distance,
        n_wraps=2,
        name_adder="_slip_casting_half_wrapper",
        build_from_sphere=context.scene.build_from_sphere,
        cut_bot=True,
        sphere_voxel_factor=1,
    )

    def finish(wrapper):
        if shape_type in {"cube", "cylinder"}:
            # Keep the padded top, but anchor the open key ends to the master bottom.
            wrapper.cut_plane(
                mathutils.Vector((0, 0, -1)),
                mathutils.Vector((0, 0, patron.min_z)),
            )
        wrapper.name = wrapper_name
        extend_multipart_wrapper_bottom(wrapper, context.scene, key_wrapper=True)
        wrapper.object["moldboxer_slip_casting_half_box_wrapper"] = True
        hide_split_key_wrappers()
        assign_generated_material(wrapper.object)
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)
        return wrapper

    return task.then(finish)


def shape_box_for_extraction(
    context,
    split_plane_specs: list[list[list[float]]] | None = None,
):
    clear_extraction_direction_arrows()
    box_voxel_size = get_box_voxel_size(context.scene.box_quality)
    slip_casting = is_slip_casting_type(context.scene.mold_type_preview)
    if slip_casting or context.scene.clear_extraction or context.scene.pro_inner_cavity:
        source_box = Object(bpy.data.objects.get("box"))
        undercut_plane_specs = split_plane_specs
        boundary_plane_specs = [bottom_reference_plane(source_box)]
        if context.scene.pro_inner_cavity:
            # Inner cores must release horizontally. The fallback returned here
            # is clearance-only and never replaces the captured split planes
            # used by the server or the physical split operation.
            undercut_plane_specs = inner_core_undercut_plane_specs(
                source_box,
                split_plane_specs,
            )
            boundary_plane_specs = None
        task = begin_clear_undercuts(
            target_object=source_box,
            horizontal_extraction=slip_casting,
            mid_horizontal_extraction=slip_casting,
            display_extraction_directions=not slip_casting,
            bidirectional=True,
            voxel_size=box_voxel_size,
            target_retry_voxel_size=box_voxel_size,
            target_point=mathutils.Vector((0, 0, 0)),
            plane_direction=mathutils.Vector((1, 0, 0)),
            progress_callback=lambda _label: force_viewport_redraw(context),
            split_plane_specs=undercut_plane_specs,
            boundary_plane_specs=boundary_plane_specs,
            easy_extraction=(
                slip_casting or (context.scene.clear_extraction
                and getattr(
                    context.scene,
                    "clear_undercuts_mode",
                    "OPTIMIZED",
                )
                == "EASY_EXTRACTION")
            ),
            precise_cost=(
                not slip_casting and context.scene.clear_extraction
                and getattr(
                    context.scene,
                    "clear_undercuts_mode",
                    "OPTIMIZED",
                )
                == "PRECISE"
            ),
            restrict_bottom_vertical_extraction=(
                getattr(context.scene, "base_type", "classic") == "optimized"
            ),
        )
        def finish(_result):
            box = Object(bpy.data.objects.get("box"))
            hide_working_patron()
            assign_generated_material(box.object)
            refresh_viewport_material_display(context)
            force_viewport_redraw(context)
            return box

        return task.then(finish)
    else:
        box = Object(bpy.data.objects.get("box"))
        breathe_viewport(context)
        box.smooth_geometry(factor=0.5, repeat=5)
        breathe_viewport(context)
    return None


def refine_box(
    context,
    *,
    bottom_cut_offset: float = 0.0,
    bottom_clean_height: float | None = None,
    target_object=None,
):
    patron = _box_target(target_object)
    box = Object(bpy.data.objects.get("box"))
    if bottom_clean_height is None:
        # box.clean_top(5)
        box.cut_plane(
            mathutils.Vector((0, 0, -1)),
            mathutils.Vector((0, 0, patron.min_z + bottom_cut_offset)),
        )
    else:
        box.clean_bot(bottom_clean_height)
    extend_multipart_wrapper_bottom(box, context.scene)
    hide_working_patron()
    assign_generated_material(box.object)
    refresh_viewport_material_display(context)
    force_viewport_redraw(context)


def _cut_slip_casting_vase_object_at_master_max_z(
    context,
    object_name: str,
) -> Object:
    """Open Vase helper geometry 0.5 mm below the master top when based."""

    target = Object(bpy.data.objects.get(object_name))
    master = get_master_for_base_operations()
    target.cut_plane(
        mathutils.Vector((0, 0, 1)),
        mathutils.Vector(
            (
                master.center_coords.x,
                master.center_coords.y,
                master.max_z - (
                    0.5 if (slip_casting_uses_base(context.scene)
                            and not slip_casting_funnels_on_top(context.scene)) else 0.0
                ),
            )
        ),
    )
    assign_generated_material(target.object)
    refresh_viewport_material_display(context)
    force_viewport_redraw(context)
    return target


def cut_slip_casting_vase_box_at_master_max_z(context) -> Object:
    """Open the Vase box at the prepared master's configured top cut."""

    return _cut_slip_casting_vase_object_at_master_max_z(context, "box")


def cut_slip_casting_vase_half_box_wrapper_at_master_max_z(context) -> Object:
    """Open the half-thickness pin guide at the same height as the Vase box."""

    return _cut_slip_casting_vase_object_at_master_max_z(
        context,
        SLIP_CASTING_HALF_BOX_WRAPPER_NAME,
    )


def iter_build_box_geometry_steps(
    context,
    *,
    bottom_cut_offset: float = 0.0,
    bottom_clean_height: float | None = None,
    split_plane_specs: list[list[list[float]]] | None = None,
    target_object=None,
    defer_extraction_clearance: bool = False,
) -> Iterator[BuildBoxStep]:
    shape_type = (
        getattr(context.scene, "slip_casting_shape_type", "adapted")
        if is_multipart_type(context.scene.mold_type_preview)
        else getattr(context.scene, "mold_box_shape_type", "adapted")
    )
    if is_multipart_type(context.scene.mold_type_preview) and (
        defer_extraction_clearance or target_object is not None
    ):
        shape_type = "adapted"
    yield "Generating box", lambda: generate_box_wrapper(
        context,
        target_object=target_object,
        shape_type=shape_type,
    )
    if shape_type != "adapted":
        # Convex primitives already permit horizontal extraction.
        pass
    elif defer_extraction_clearance:
        # The companion mold applies its frozen master paths after joining
        # components. An independent pass here would alter the box first.
        pass
    elif (is_slip_casting_type(context.scene.mold_type_preview)
            or context.scene.clear_extraction or context.scene.pro_inner_cavity):
        yield "Clearing undercuts", lambda: shape_box_for_extraction(
            context,
            split_plane_specs=split_plane_specs,
        )
    else:
        yield "Smoothing box", lambda: shape_box_for_extraction(
            context,
            split_plane_specs=split_plane_specs,
        )
    # Anchor every shape to the same master bottom before adding the shared
    # funnel/foot clearance. A horizontal cut preserves the cubic flat caps.
    yield "Refining box", lambda: refine_box(
        context,
        bottom_cut_offset=bottom_cut_offset,
        bottom_clean_height=bottom_clean_height,
        target_object=target_object,
    )

def request_box_channels_deposit(
    context,
    *,
    channels_deposit_path="/channels-deposit/",
    funnel_depth: float | None = None,
    split_plane_specs: list[list[list[float]]] | None = None,
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
    generate_funneler: bool = True,
    funneler_ref_height: float | None = None,
    funneler_offset: float | None = None,
):
    split_planes, organic_split_planes = split_specs_query_values(
        split_plane_specs
    )
    casting_feet = (
        context.scene.casting_feet and not context.scene.pro_two_part_silicone
    )
    channel_adjustment = scene_channel_adjustment(context.scene)
    request_channels_deposit(
        context.scene.channel_width,
        context.scene.channel_depth,
        channel_adjustment=channel_adjustment,
        larger_back=context.scene.channel_back_larger,
        add_funneler=context.scene.funneler == "cylinder",
        generate_funneler=generate_funneler,
        channels=context.scene.channels,
        support_pilars=context.scene.silicone_support_pilars,
        extraction=scene_channels_deposit_extraction(context.scene),
        progressive_channels=True,
        channels_contact_scale=context.scene.channels_contact_scale,
        n_horizontal_channels=context.scene.horizontal_channels_count,
        n_splits_z=context.scene.n_splits_z,
        channel_end_shape=getattr(context.scene, "channel_end_shape", "V"),
        channels_type=context.scene.channels_type,
        funneler_ref_height=(
            _normalized_funneler_ref_height(context.scene)
            if funneler_ref_height is None
            else funneler_ref_height
        ),
        funneler_offset=(
            effective_silicone_funneler_offset(context.scene)
            if funneler_offset is None
            else funneler_offset
        ),
        funnel_size_factor=context.scene.funneler_size_factor,
        funnel_depth=funnel_depth,
        casting_feet=casting_feet,
        casting_feet_height=context.scene.casting_feet_height,
        casting_feet_size_factor=context.scene.casting_feet_size_factor,
        casting_grip=context.scene.casting_grip,
        casting_grip_width=context.scene.casting_grip_width,
        casting_grip_depth=context.scene.casting_grip_depth,
        watermark_text=build_watermark_text(context.scene),
        n_splits=get_effective_box_parts(context.scene),
        split_planes=split_planes,
        organic_split_planes=organic_split_planes,
        endpoint_path=channels_deposit_path,
        include_x_channel=include_x_channel,
        include_y_channel=include_y_channel,
    )
    clean_channels_bot_to_box_height()


def request_box_channels_deposit_async(
    context,
    *,
    channels_deposit_path="/channels-deposit/",
    funnel_depth: float | None = None,
    split_plane_specs: list[list[list[float]]] | None = None,
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
    generate_funneler: bool = True,
    funneler_ref_height: float | None = None,
    funneler_offset: float | None = None,
):
    casting_feet = (
        context.scene.casting_feet and not context.scene.pro_two_part_silicone
    )
    channel_adjustment = scene_channel_adjustment(context.scene)
    split_planes, organic_split_planes = split_specs_query_values(
        split_plane_specs
    )

    def steps():
        imported_objs = yield request_channels_deposit_async(
            context.scene.channel_width,
            context.scene.channel_depth,
            channel_adjustment=channel_adjustment,
            larger_back=context.scene.channel_back_larger,
            add_funneler=context.scene.funneler == "cylinder",
            generate_funneler=generate_funneler,
            channels=context.scene.channels,
            support_pilars=context.scene.silicone_support_pilars,
            extraction=scene_channels_deposit_extraction(context.scene),
            progressive_channels=True,
            channels_contact_scale=context.scene.channels_contact_scale,
            n_horizontal_channels=context.scene.horizontal_channels_count,
            n_splits_z=context.scene.n_splits_z,
            channel_end_shape=getattr(context.scene, "channel_end_shape", "V"),
            channels_type=context.scene.channels_type,
            funneler_ref_height=(
                _normalized_funneler_ref_height(context.scene)
                if funneler_ref_height is None
                else funneler_ref_height
            ),
            funneler_offset=(
                effective_silicone_funneler_offset(context.scene)
                if funneler_offset is None
                else funneler_offset
            ),
            funnel_size_factor=context.scene.funneler_size_factor,
            funnel_depth=funnel_depth,
            casting_feet=casting_feet,
            casting_feet_height=context.scene.casting_feet_height,
            casting_feet_size_factor=context.scene.casting_feet_size_factor,
            casting_grip=context.scene.casting_grip,
            casting_grip_width=context.scene.casting_grip_width,
            casting_grip_depth=context.scene.casting_grip_depth,
            watermark_text=build_watermark_text(context.scene),
            n_splits=get_effective_box_parts(context.scene),
            split_planes=split_planes,
            organic_split_planes=organic_split_planes,
            endpoint_path=channels_deposit_path,
            include_x_channel=include_x_channel,
            include_y_channel=include_y_channel,
        )
        clean_channels_bot_to_box_height()
        return imported_objs

    return BackgroundTaskSequence(steps())


def refresh_box_build_display(context):
    hide_split_key_wrappers()
    refresh_generated_object_materials()
    refresh_viewport_material_display(context)


def iter_build_box_operator_steps(
    context,
    *,
    async_server: bool = False,
    refresh_materials: bool = True,
    generate_channels_deposit: bool = True,
    channels_deposit_path: str = "/channels-deposit/",
    bottom_cut_offset: float = 0.0,
    bottom_clean_height: float | None = None,
    funnel_depth: float | None = None,
    split_plane_specs: list[list[list[float]]] | None = None,
    include_x_channel: bool | None = None,
    include_y_channel: bool | None = None,
    target_object=None,
    generate_funneler: bool = True,
    funneler_ref_height_provider: Callable[[], float] | None = None,
    funneler_offset: float | None = None,
    channels_step_label: str = "Generating channels and funneler",
    defer_extraction_clearance: bool = False,
) -> Iterator[BuildBoxStep]:
    if context.scene.pro_two_part_silicone:
        captured_plane_specs = (
            capture_silicone_split_plane_specs(context.scene)
            if split_plane_specs is None
            else list(split_plane_specs)
        )
        split_plane_specs = resolve_splitter_plane_specs(
            context.scene,
            captured_plane_specs,
        )
        store_silicone_split_plane_specs(split_plane_specs, context.scene)
    elif split_plane_specs is None:
        split_plane_specs = capture_silicone_split_plane_specs(context.scene)
    else:
        store_silicone_split_plane_specs(split_plane_specs, context.scene)
    yield from iter_build_box_geometry_steps(
        context,
        bottom_cut_offset=bottom_cut_offset,
        bottom_clean_height=bottom_clean_height,
        split_plane_specs=split_plane_specs,
        target_object=target_object,
        defer_extraction_clearance=defer_extraction_clearance,
    )
    if generate_channels_deposit:
        yield channels_step_label, (
            lambda: (
                request_box_channels_deposit_async(
                    context,
                    channels_deposit_path=channels_deposit_path,
                    funnel_depth=funnel_depth,
                    split_plane_specs=split_plane_specs,
                    include_x_channel=include_x_channel,
                    include_y_channel=include_y_channel,
                    generate_funneler=generate_funneler,
                    funneler_ref_height=(
                        funneler_ref_height_provider()
                        if funneler_ref_height_provider is not None
                        else None
                    ),
                    funneler_offset=funneler_offset,
                )
                if async_server
                else request_box_channels_deposit(
                    context,
                    channels_deposit_path=channels_deposit_path,
                    funnel_depth=funnel_depth,
                    split_plane_specs=split_plane_specs,
                    include_x_channel=include_x_channel,
                    include_y_channel=include_y_channel,
                    generate_funneler=generate_funneler,
                    funneler_ref_height=(
                        funneler_ref_height_provider()
                        if funneler_ref_height_provider is not None
                        else None
                    ),
                    funneler_offset=funneler_offset,
                )
            )
        )
    from .base import prepare_master_base_pins

    yield "Preparing master pin keys", lambda: prepare_master_base_pins(context)
    if refresh_materials:
        yield "Refreshing materials", lambda: refresh_box_build_display(context)


def iter_slip_casting_build_box_operator_steps(
    context,
    *,
    async_server: bool = False,
    channels_deposit_path: str,
    channels_step_label: str = "Generating funneler",
) -> Iterator[BuildBoxStep]:
    """Add the Slip Casting helper wrapper without changing other builds."""
    vase_mode = is_slip_casting_vase_type(context.scene.mold_type_preview)
    from .slip_casting_cavity_filler import commit_slip_casting_parts_to_master

    silicone_mode = is_silicone_multipart_type(context.scene.mold_type_preview)
    if not silicone_mode:
        yield (
            "Adding prepared funnels and base to master",
            lambda: commit_slip_casting_parts_to_master(context),
        )
    # Committing also removes orphaned base partners before mode detection.
    no_base = not slip_casting_uses_base(context.scene)
    funnels_on_top = vase_mode and slip_casting_funnels_on_top(context.scene)
    open_top = funnels_on_top or (vase_mode and not no_base and getattr(context.scene, "slip_casting_shape_type", "adapted") != "cube")
    yield from iter_build_box_operator_steps(
        context,
        async_server=async_server,
        refresh_materials=False,
        generate_channels_deposit=silicone_mode or (no_base and not funnels_on_top),
        channels_deposit_path="/channels-deposit/" if silicone_mode else channels_deposit_path,
        channels_step_label="Generating channels and funneler" if silicone_mode else channels_step_label,
        generate_funneler=not funnels_on_top,
        funneler_ref_height_provider=(lambda: 0.8) if no_base and not silicone_mode else None,
        funneler_offset=1.0 if no_base and not silicone_mode else None,
    )
    if no_base and not silicone_mode and not funnels_on_top:
        # The server returns deposits separately; merge them before wrapping.
        yield "Adding funnels to box", add_deposit
    if open_top:
        yield (
            "Cutting vase box at master top",
            lambda: cut_slip_casting_vase_box_at_master_max_z(context),
        )
    yield (
        "Generating half-thickness box wrapper",
        lambda: generate_slip_casting_half_box_wrapper(context),
    )
    if open_top:
        yield (
            "Cutting half-thickness wrapper at master top",
            lambda: cut_slip_casting_vase_half_box_wrapper_at_master_max_z(context),
        )
    yield "Refreshing materials", lambda: refresh_box_build_display(context)


@retry_after_heal
def build_box_operator(
    context,
    *,
    channels_deposit_path="/channels-deposit/",
    bottom_cut_offset: float = 0.0,
):
    for _label, step in iter_build_box_operator_steps(
        context,
        channels_deposit_path=channels_deposit_path,
        bottom_cut_offset=bottom_cut_offset,
    ):
        finish_task_sync(step())


@retry_after_heal
def build_slip_casting_box_operator(
    context,
    *,
    channels_deposit_path: str,
):
    for _label, step in iter_slip_casting_build_box_operator_steps(
        context,
        channels_deposit_path=channels_deposit_path,
    ):
        finish_task_sync(step())
