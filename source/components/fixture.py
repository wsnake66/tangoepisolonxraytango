from collections.abc import Callable, Iterator
import math

import bpy  # type: ignore
import bmesh  # type: ignore
import mathutils  # type: ignore

from ..bl_utils import (
    BMeshObj,
    configure_metric_millimeter_units,
    ensure_moldboxer_transform_gizmos_for_selection,
)
from ..materials import (
    assign_fixture_base_material,
    assign_fixture_material,
    refresh_viewport_material_display,
)
from ..modifiers import diff_mod
from ..object import Object
from ..primitives import (
    MOLD_BODY_CYLINDER_VERTICES,
    create_cube_primitive,
    create_cylinder_primitive,
    create_plane_primitive,
)
from ..progress import force_viewport_redraw
from ..voxel_size import get_box_voxel_size
from .clear_undercuts import begin_clear_undercuts
from .direct_split_planes import (
    _apply_skin_base_reference_style,
    remove_direct_split_planes,
)
from .mesh_envelope import OptimizedMeshEnvelope, begin_optimized_mesh_envelope
from .vertical_edge_bevel import bevel_vertical_edges


FixtureStep = tuple[str, Callable[[], None]]
FIXTURE_HEIGHT_GUIDE_NAME = "fixture_height_guide"
FIXTURE_HEIGHT_GUIDE_MARKER = "moldboxer_fixture_height_guide"
FIXTURE_ADAPTED_MIN_UNDERCUT_ISLAND_AREA_MM2 = 50.0
FIXTURE_SCREW_DIAMETER_TOLERANCE_MM = 0.25
FIXTURE_BOOLEAN_OVERTRAVEL_MM = 0.1
FIXTURE_BASE_BOOLEAN_OVERLAP_MM = 0.2
FIXTURE_BOTTOM_UNDERCUT_OVERTRAVEL_MM = 3.0
FIXTURE_BASE_CORNER_RADIUS_MM = 2.0
FIXTURE_BASE_CORNER_SEGMENTS = 6
_FIXTURE_HEIGHT_GUIDE_SYNC_PENDING = False


def _marked_fixture_object(marker: str):
    return next(
        (obj for obj in bpy.data.objects if bool(obj.get(marker, False))),
        None,
    )


def fixture_height_guide_object():
    return _marked_fixture_object(FIXTURE_HEIGHT_GUIDE_MARKER)


def _remove_raw_object(obj) -> None:
    if obj is None or obj.name not in bpy.data.objects:
        return
    mesh = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and getattr(mesh, "users", 0) == 0:
        bpy.data.meshes.remove(mesh)


def remove_fixture_height_guide() -> None:
    _remove_raw_object(fixture_height_guide_object())


def _fixture_guide_target():
    for name in ("patron", "master"):
        target = bpy.data.objects.get(name)
        if target is not None and target.type == "MESH":
            return Object(target)
    return None


def sync_fixture_height_guide(scene=None) -> None:
    scene = scene or getattr(bpy.context, "scene", None)
    should_exist = bool(
        scene is not None
        and getattr(scene, "mold_type_preview", "") == "FIXTURE"
        and _fixture_guide_target() is not None
        and bpy.data.objects.get("box") is None
        and bpy.data.objects.get("fixture") is None
    )
    guide = fixture_height_guide_object()
    if not should_exist:
        remove_fixture_height_guide()
        return
    if guide is None:
        target = _fixture_guide_target()
        guide = create_plane_primitive()
        guide.name = FIXTURE_HEIGHT_GUIDE_NAME
        guide.data.name = FIXTURE_HEIGHT_GUIDE_NAME
        guide[FIXTURE_HEIGHT_GUIDE_MARKER] = True
        _apply_skin_base_reference_style(guide)
        size = max(target.width, target.depth, target.height, 1.0) * 1.35
        guide.location = target.center_coords
        guide.rotation_euler = (0.0, 0.0, 0.0)
        guide.scale = (size / 2.0, size / 2.0, 1.0)
    guide.lock_location = (True, True, False)
    guide.lock_rotation = (False, False, False)
    guide.lock_scale = (True, True, True)
    guide.hide_render = True
    ensure_moldboxer_transform_gizmos_for_selection(bpy.context)


def _fixture_height_guide_sync_timer():
    global _FIXTURE_HEIGHT_GUIDE_SYNC_PENDING
    try:
        sync_fixture_height_guide()
    finally:
        _FIXTURE_HEIGHT_GUIDE_SYNC_PENDING = False
    return None


def schedule_fixture_height_guide_sync(context=None) -> None:
    global _FIXTURE_HEIGHT_GUIDE_SYNC_PENDING
    if _FIXTURE_HEIGHT_GUIDE_SYNC_PENDING:
        return
    _FIXTURE_HEIGHT_GUIDE_SYNC_PENDING = True
    try:
        bpy.app.timers.register(
            _fixture_height_guide_sync_timer,
            first_interval=0.0,
        )
    except Exception:
        _fixture_height_guide_sync_timer()


def fixture_height_plane() -> tuple[mathutils.Vector, mathutils.Vector]:
    guide = fixture_height_guide_object()
    if guide is None:
        sync_fixture_height_guide()
        guide = fixture_height_guide_object()
    if guide is None:
        raise RuntimeError("Fixture height plane is unavailable")
    bpy.context.view_layer.update()
    point = guide.matrix_world.translation.copy()
    normal = guide.matrix_world.to_quaternion() @ mathutils.Vector((0.0, 0.0, 1.0))
    if normal.length_squared <= 1e-12:
        normal = mathutils.Vector((0.0, 0.0, 1.0))
    else:
        normal.normalize()
    return point, normal


def _cut_fixture_body_at_height(
    body: Object,
    *,
    plane_point: mathutils.Vector,
    plane_normal: mathutils.Vector,
) -> None:
    matrix_world = body.object.matrix_world.copy()
    inverse_matrix = matrix_world.inverted()
    with BMeshObj(body, repair_winding=True) as bm:
        bm.transform(matrix_world)
        result = bmesh.ops.bisect_plane(
            bm,
            geom=[*bm.verts, *bm.edges, *bm.faces],
            dist=1e-5,
            plane_co=plane_point,
            plane_no=plane_normal,
            clear_inner=False,
            clear_outer=True,
        )
        cut_edges = [
            element
            for element in result.get("geom_cut", ())
            if isinstance(element, bmesh.types.BMEdge)
            and element.is_valid
            and len(element.link_faces) == 1
        ]
        if cut_edges:
            bmesh.ops.holes_fill(bm, edges=cut_edges, sides=0)
        bm.transform(inverse_matrix)
    body.object.data.update()
    bpy.context.view_layer.update()


def _fixture_body_opposite_anchor(
    body: Object,
    plane_normal: mathutils.Vector,
) -> mathutils.Vector:
    matrix_world = body.object.matrix_world
    world_vertices = [
        matrix_world @ vertex.co for vertex in body.object.data.vertices
    ]
    if not world_vertices:
        raise RuntimeError("Adapted fixture body has no vertices")
    return min(world_vertices, key=lambda vertex: vertex.dot(plane_normal)).copy()


def _fixture_wrapper(
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


def _begin_fixture_wrapper(
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


def _primitive_fixture_body(
    clearance: Object,
    *,
    thickness: float,
    shape_type: str,
) -> Object:
    width = clearance.width + thickness * 2.0
    depth = clearance.depth + thickness * 2.0
    height = clearance.height + thickness * 2.0
    if shape_type == "cube":
        body = Object(create_cube_primitive(1.0), "fixture")
        body.scale_to(width, axis=0)
        body.scale_to(depth, axis=1)
    elif shape_type == "cylinder":
        body = Object(
            create_cylinder_primitive(
                0.5,
                1.0,
                vertices=MOLD_BODY_CYLINDER_VERTICES,
            ),
            "fixture",
        )
        diameter = math.hypot(clearance.width, clearance.depth) + thickness * 2.0
        body.scale_to(diameter, axis=0)
        body.scale_to(diameter, axis=1)
    else:
        raise ValueError(f"Unsupported primitive fixture shape: {shape_type}")

    body.scale_to(height, axis=2)
    body.translate_whole(clearance.center_coords)
    body.apply_all_transforms()
    if shape_type == "cube":
        bevel_vertical_edges(body)
    return body


def _fixture_base_effective_span(
    configured_span: float,
    *,
    screw_holes: bool,
    screw_body_diameter: float,
    screw_head_diameter: float,
) -> float:
    span = max(float(configured_span), 0.0)
    if not screw_holes:
        return span
    return max(
        span,
        float(screw_body_diameter) + FIXTURE_SCREW_DIAMETER_TOLERANCE_MM,
        float(screw_head_diameter) + FIXTURE_SCREW_DIAMETER_TOLERANCE_MM,
    )


def _fixture_base_corner_positions(
    base: Object,
    span: float,
) -> tuple[tuple[float, float], ...]:
    inset = span / 2.0
    return (
        (base.min_x + inset, base.min_y + inset),
        (base.min_x + inset, base.max_y - inset),
        (base.max_x - inset, base.min_y + inset),
        (base.max_x - inset, base.max_y - inset),
    )


def _subtract_fixture_base_screw_holes(
    base: Object,
    *,
    span: float,
    body_diameter: float,
    head_diameter: float,
    head_height: float,
) -> None:
    body_cut_diameter = (
        float(body_diameter) + FIXTURE_SCREW_DIAMETER_TOLERANCE_MM
    )
    head_cut_diameter = (
        float(head_diameter) + FIXTURE_SCREW_DIAMETER_TOLERANCE_MM
    )
    through_height = base.height + FIXTURE_BOOLEAN_OVERTRAVEL_MM * 2.0
    recess_height = float(head_height) + FIXTURE_BOOLEAN_OVERTRAVEL_MM
    base_center_z = base.center_coords.z
    recess_center_z = (
        base.max_z
        - float(head_height) / 2.0
        + FIXTURE_BOOLEAN_OVERTRAVEL_MM / 2.0
    )

    for corner_index, (x, y) in enumerate(
        _fixture_base_corner_positions(base, span)
    ):
        cutters = (
            Object(
                create_cylinder_primitive(body_cut_diameter / 2.0, through_height),
                f"fixture_screw_body_{corner_index}",
            ),
            Object(
                create_cylinder_primitive(head_cut_diameter / 2.0, recess_height),
                f"fixture_screw_head_{corner_index}",
            ),
        )
        cutters[0].translate_whole(mathutils.Vector((x, y, base_center_z)))
        cutters[1].translate_whole(mathutils.Vector((x, y, recess_center_z)))
        try:
            for cutter in cutters:
                base.apply_boolean_modifier_with_geometry_fallback(
                    diff_mod,
                    cutter,
                )
        finally:
            for cutter in cutters:
                cutter.remove()


def _round_fixture_base_vertical_edges(base: Object) -> None:
    """Round only the base's four upright corner edges."""
    bevel_vertical_edges(
        base,
        radius=FIXTURE_BASE_CORNER_RADIUS_MM,
        segments=FIXTURE_BASE_CORNER_SEGMENTS,
    )


def _add_fixture_base(body: Object, scene) -> None:
    thickness = float(scene.fixture_base_thickness)
    screw_holes = bool(scene.fixture_base_screw_holes)
    body_diameter = float(scene.fixture_base_screw_body_diameter)
    head_diameter = float(scene.fixture_base_screw_head_diameter)
    span = _fixture_base_effective_span(
        float(scene.fixture_base_span),
        screw_holes=screw_holes,
        screw_body_diameter=body_diameter,
        screw_head_diameter=head_diameter,
    )
    if span > float(scene.fixture_base_span):
        scene.fixture_base_span = span

    fixture_center = body.center_coords
    fixture_min_z = body.min_z
    base = Object(create_cube_primitive(1.0), "fixture_base")
    base.scale_to(body.width + span * 2.0, axis=0)
    base.scale_to(body.depth + span * 2.0, axis=1)
    base.scale_to(thickness, axis=2)
    base.translate_whole(
        mathutils.Vector(
            (
                fixture_center.x,
                fixture_center.y,
                fixture_min_z
                + FIXTURE_BASE_BOOLEAN_OVERLAP_MM
                - thickness / 2.0,
            )
        )
    )
    base.apply_all_transforms()
    _round_fixture_base_vertical_edges(base)

    try:
        if screw_holes:
            _subtract_fixture_base_screw_holes(
                base,
                span=span,
                body_diameter=body_diameter,
                head_diameter=head_diameter,
                head_height=float(scene.fixture_base_screw_head_height),
            )
        assign_fixture_base_material(base.object)
        body.add_with_material_transfer_and_geometry_fallback(base)
    finally:
        base.remove()


def iter_generate_fixture_steps(
    context,
    *,
    target_object=None,
) -> Iterator[FixtureStep]:
    scene = context.scene
    height_point, height_normal = fixture_height_plane()
    state: dict[str, object] = {
        "height_point": height_point,
        "height_normal": height_normal,
    }

    def generate_clearance_wrapper():
        configure_metric_millimeter_units()
        raw_target = target_object or getattr(context, "object", None)
        if raw_target is None or getattr(raw_target, "type", None) != "MESH":
            raise RuntimeError("No imported mesh available for fixture generation")
        patron = Object(raw_target)
        patron.select()
        voxel_size = get_box_voxel_size(
            scene.fixture_box_quality,
            patron,
        )
        task = _begin_fixture_wrapper(
            patron,
            distance=float(scene.fixture_fit_tolerance),
            voxel_size=voxel_size,
        )
        state["voxel_size"] = voxel_size
        remove_direct_split_planes()

        def finish(clearance):
            clearance.name = "fixture_clearance"
            state["clearance"] = clearance
            return clearance

        return task.then(finish)

    def generate_fixture_body():
        clearance = state["clearance"]
        thickness = float(scene.fixture_thickness)
        shape_type = str(scene.fixture_shape_type).lower()
        if shape_type == "adapted":
            task = _begin_fixture_wrapper(
                clearance,
                distance=thickness,
                voxel_size=state["voxel_size"],
            )
            def finish(body):
                body.name = "fixture"
                state["body"] = body
                return body

            return task.then(finish)
        else:
            body = _primitive_fixture_body(
                clearance,
                thickness=thickness,
                shape_type=shape_type,
            )
            state["body"] = body
        return None

    def clear_upward_undercuts():
        clearance = state["clearance"]
        clearance_center = clearance.center_coords
        return begin_clear_undercuts(
            target_object=clearance,
            bidirectional=False,
            voxel_size=state["voxel_size"],
            target_retry_voxel_size=state["voxel_size"],
            target_point=mathutils.Vector(
                (clearance_center.x, clearance_center.y, clearance.max_z)
            ),
            plane_direction=mathutils.Vector((0.0, 0.0, -1.0)),
            split_plane_specs=[],
            progress_callback=lambda _label: force_viewport_redraw(context),
            display_extraction_directions=False,
        )

    def cut_fixture_height() -> None:
        body = state["body"]
        _cut_fixture_body_at_height(
            body,
            plane_normal=state["height_normal"],
            plane_point=state["height_point"],
        )
        remove_fixture_height_guide()

    def clear_adapted_fixture_undercuts():
        if str(scene.fixture_shape_type).lower() != "adapted":
            return
        body = state["body"]
        extraction_direction = mathutils.Vector(state["height_normal"])
        opposite_anchor = _fixture_body_opposite_anchor(
            body,
            extraction_direction,
        )
        return begin_clear_undercuts(
            target_object=body,
            bidirectional=False,
            voxel_size=state["voxel_size"],
            target_retry_voxel_size=state["voxel_size"],
            target_point=opposite_anchor,
            plane_direction=extraction_direction,
            split_plane_specs=[],
            split_plane_overtravel_override=0.0,
            clearance_build_overtravel_override=0.0,
            normal_angle_threshold_degrees=30.0,
            minimum_undercut_island_area=(
                FIXTURE_ADAPTED_MIN_UNDERCUT_ISLAND_AREA_MM2
            ),
            face_limit_plane_spec=[
                list(state["height_point"]),
                list(state["height_normal"]),
            ],
            progress_callback=lambda _label: force_viewport_redraw(context),
            display_extraction_directions=False,
            smooth_target_after_remesh=False,
        )

    def prepare_adapted_fixture_bottom() -> None:
        if str(scene.fixture_shape_type).lower() != "adapted":
            return
        body = state["body"]
        state["fixture_original_min_z"] = body.min_z
        clean_height = max(float(scene.fixture_thickness) - 1.0, 0.0)
        if clean_height > 0.0:
            body.clean_bot(clean_height)
        selected_count = body.select_limit_flat_faces(max_co=False)
        if selected_count > 0:
            body.extrude_selected(-FIXTURE_BOTTOM_UNDERCUT_OVERTRAVEL_MM)
            body.recalculate_normals()

    def trim_adapted_fixture_bottom() -> None:
        if str(scene.fixture_shape_type).lower() != "adapted":
            return
        body = state["body"]
        original_min_z = float(state["fixture_original_min_z"])
        center = body.center_coords
        body.cut_plane(
            mathutils.Vector((0.0, 0.0, -1.0)),
            mathutils.Vector((center.x, center.y, original_min_z)),
        )
        body.recalculate_normals()

    def subtract_clearance() -> None:
        body = state["body"]
        clearance = state["clearance"]
        body.apply_boolean_modifier_with_geometry_fallback(
            diff_mod,
            clearance,
        )
        clearance.remove()
        body.object["moldboxer_fixture"] = True
        assign_fixture_material(body.object)

    def add_fixture_base() -> None:
        if not bool(scene.fixture_base):
            return
        _add_fixture_base(state["body"], scene)

    def finalize_fixture() -> None:
        body = state["body"]
        remove_direct_split_planes()
        body.name = "fixture"
        body.select()
        refresh_viewport_material_display(context)
        force_viewport_redraw(context)

    yield "Generating clearance wrapper", generate_clearance_wrapper
    yield "Clearing fixture undercuts", clear_upward_undercuts
    yield "Generating fixture body", generate_fixture_body
    yield "Preparing adapted fixture bottom", prepare_adapted_fixture_bottom
    yield "Clearing adapted fixture undercuts", clear_adapted_fixture_undercuts
    yield "Trimming adapted fixture bottom", trim_adapted_fixture_bottom
    yield "Cutting fixture height", cut_fixture_height
    yield "Subtracting fixture clearance", subtract_clearance
    yield "Adding fixture base", add_fixture_base
    yield "Finalizing fixture", finalize_fixture
