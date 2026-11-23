# SPDX-License-Identifier: GPL-3.0-or-later
"""Rounded funnel orchestration using opaque remote geometry records."""
import math
import json
import bpy
from mathutils import Matrix, Vector
from ..background_worker import BackgroundTaskSequence
from ..rounded_funnel_geometry import placements, frustum_mesh
from ..object import Object, remove_objects_safely
from ..materials import assign_funnels_material, assign_moldbox_material, assign_plaster_mold_material

MOLD_KEY = 'moldboxer_rounded_funnel_mold'
PLASTER_PREVIEW_KEY = 'moldboxer_rounded_funnel_plaster_preview'
LOWER_FOOT_KEY = 'moldboxer_rounded_lower_foot'
DIMENSIONS_KEY = 'moldboxer_rounded_funnel_dimensions'
SOURCE_KEY = 'moldboxer_rounded_funnel_source'
REFERENCE_KEY = 'moldboxer_rounded_funnel_reference'
REFERENCE_PLAN_KEY = 'moldboxer_rounded_funnel_reference_plan'


def _mesh(name, geometry):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(geometry[0], [], geometry[1])
    mesh.update()
    raw = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(raw)
    return Object(raw)


def _reverse_spec(spec):
    """Undo the analysis half turn while preserving the supplied metadata."""
    def point(p):
        return [p[0], -p[1], -p[2]]
    result = dict(spec)
    lo, hi = spec['minimum'], spec['maximum']
    result['minimum'] = [lo[0], -hi[1], -hi[2]]
    result['maximum'] = [hi[0], -lo[1], -lo[2]]
    result['reference'] = point(spec['reference'])
    result['vertices'] = [point(p) for p in spec['vertices']]
    return result


def _build_lower_feet(master, specs, context, voxel_size, distance):
    """Run only existing foot finishing in its expected (foot-up) frame."""
    from . import slip_casting_cavity_filler as c
    if not specs:
        raise ValueError('No usable foot regions found')
    references = c._create_slip_casting_vase_funnel_reference_objects(
        master, specs, name_prefix=c.SLIP_CASTING_VASE_BASE_PART_PREFIX,
        marker_key=c.SLIP_CASTING_VASE_BASE_PART_KEY)
    wrappers = yield from c._build_slip_casting_funnel_span_wrappers_per_reference(
        master, references, context, voxel_size=voxel_size,
        funnel_span=context.scene.slip_casting_funnel_span,
        target_wrap_distance=distance,
        name_prefix=c.SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_NAME,
        distance_override=c.SLIP_CASTING_VASE_BASE_SPAN_WRAPPER_DISTANCE_MM,
        remesh_between_wraps=True, reference_z_offset=-distance,
        minimum_half_height=distance)
    bounds = c._slip_casting_clearance_bounds_for_reference_wrappers(wrappers, references, voxel_size=voxel_size)
    bounds = c._expanded_slip_casting_clearance_region_bounds(bounds, z_margin=c.SLIP_CASTING_OPTIMIZED_CLEARANCE_REGION_Z_MARGIN_MM)
    clearances = yield from c._build_slip_casting_core_master_clearances(
        master, references, context, voxel_size=voxel_size,
        funnel_wrappers=wrappers, clearance_region_bounds=bounds,
        include_inward=False, include_outward=True)
    c._subtract_core_clearances_from_funnel_span_wrappers(wrappers, clearances, context)
    parts = []
    for wrapper, reference in zip(wrappers, references):
        parts.extend(c._keep_funnel_span_wrapper_parts_for_cores(wrapper, [reference], context, use_max_z=True))
    parts = yield from c._build_final_slip_casting_vase_base_parts(
        parts, master, context, voxel_size=voxel_size, mold_thickness=context.scene.box_gap)
    before = {raw.as_pointer() for raw in bpy.data.objects}
    split_planes = c._vase_base_pin_split_plane_specs(context, log_context='Rounded foot pin capture')
    reversed_planes = []
    for spec in split_planes:
        point, normal = c.split_spec_point_normal(spec)
        reversed_planes.append([(point[0],-point[1],-point[2]), (normal[0],-normal[1],-normal[2])])
    male, female = c._finish_funnel_generated_vase_bases(
        parts, master, context, mold_thickness=context.scene.box_gap,
        split_planes_override=reversed_planes)
    accessories = c._lower_finished_casting_bases([*male,*female], context, before)
    c._remove_detected_cores_and_clearance_masters(references, clearances, context)
    outputs = [*male,*female,*accessories]
    rotation = Matrix.Rotation(math.pi, 4, 'X')
    matrices = [(part.object, rotation @ part.object.matrix_world) for part in outputs]
    for raw, matrix in matrices:
        raw.matrix_world = matrix
        raw[LOWER_FOOT_KEY] = True
    context.view_layer.update()
    return outputs


def begin_rounded_funnels(context):
    from . import slip_casting_cavity_filler as c
    scene = context.scene
    master = c._slip_casting_master(scene)
    if master is None:
        raise ValueError('No master model found')
    r0 = float(scene.slip_casting_rounded_bottom_diameter)/2
    r1 = float(scene.slip_casting_rounded_top_diameter)/2
    if not r1 > r0 > 0:
        raise ValueError('Top diameter must exceed bottom diameter')
    extension = float(scene.slip_casting_rounded_extension)
    thickness = float(scene.box_gap)
    if extension <= 0 or thickness <= 0:
        raise ValueError('Extension and mold thickness must be positive')
    if bpy.data.objects.get('input_mesh') is not None:
        raise RuntimeError('Preparation input name is already in use')
    count = 0 if scene.slip_casting_rounded_count_mode == 'AUTO' else int(scene.slip_casting_rounded_count)
    voxel = c.get_box_voxel_size(scene.box_quality, master)

    def steps():
        before = {raw.as_pointer() for raw in bpy.data.objects}
        meshes = {mesh.as_pointer() for mesh in bpy.data.meshes}
        outputs = []
        success = False
        try:
            c._ensure_preparation_source_manifold(master, role='master', voxel_size=c.get_master_voxel_size(scene.master_quality,master))
            top = float(master.max_z)+extension
            settings = c._preparation_settings(master)
            preset = getattr(scene, 'slip_casting_rounded_detection_detail', 'AGGRESSIVE')
            distance = 0.0

            def scan(envelope_settings, *, secondary, detection_preset, scan_voxel):
                source = yield c.begin_mesh_envelope(
                    master, voxel_size=scan_voxel, name_adder='_rounded_analysis', **envelope_settings)
                source.object.matrix_world = Matrix.Rotation(math.pi,4,'X') @ source.object.matrix_world
                source.name = 'input_mesh'
                context.view_layer.update()
                c._set_reference_hidden(source, True)
                response = yield c.request_server_async(
                    f'{c.get_server_base_url()}/v1/g/', [source.name],
                    params={'p0':max(master.width,master.depth,master.height), 'p1':scan_voxel,
                            'p2':0., 'p3':secondary, 'p4':3, 'p5':detection_preset})
                result = c.read_cast_plan(response)
                if result['version'] != 3:
                    raise RuntimeError('Rounded funnels require the updated location-only preparation service')
                source.remove()
                return result

            detection_envelope = {
                **settings['analysis_envelope'],
                'distance': 0.0,
                'build_from_sphere': False,
            }
            plan = yield from scan(detection_envelope, secondary=False, detection_preset=preset, scan_voxel=voxel)
            records = [_reverse_spec(spec) for spec in plan['records']]
            from .direct_split_planes import direct_split_plane_specs
            split_planes = direct_split_plane_specs()
            selected = placements(records,count,r0,r1, split_planes=split_planes,
                                  wrapper_distance=distance, funnel_top=top)
            for index,(record,(x,y)) in enumerate(selected,1):
                # Embed 2 mm into the master; keeping top fixed extends the
                # funnel height by the full downward overlap.
                bottom = record['maximum'][2]-distance-2.0
                # Local geometry starts at the bottom center, so the object
                # origin is useful for moving/scaling the finished funnel.
                funnel = _mesh(f'rounded_funnel_{index:03d}',frustum_mesh(0,0,0,top-bottom,r0,r1))
                funnel.object.location = (x, y, bottom)
                funnel.object[c.SLIP_CASTING_PENDING_MASTER_UNION_KEY] = True
                funnel.object[DIMENSIONS_KEY] = (top-bottom, r0, r1)
                assign_funnels_material(funnel.object)
                outputs.append(funnel)
            if scene.slip_casting_generate_base:
                # Preserve the original expanded analysis for feet independently.
                foot_plan = yield from scan(settings['analysis_envelope'], secondary=True,
                                           detection_preset='AGGRESSIVE', scan_voxel=voxel)
                foot_distance = settings['analysis_distance']
                # Foot references are already in the analysis (foot-up) frame.
                proxy = master.duplicate('_rounded_foot_source')
                proxy.object.matrix_world = Matrix.Rotation(math.pi,4,'X') @ proxy.object.matrix_world
                context.view_layer.update()
                outputs.extend((yield from _build_lower_feet(proxy,foot_plan['secondary'],context,voxel,foot_distance)))
                proxy.remove()
            for part in outputs:
                part.hide_during_ui_breathe = False
                c._set_reference_hidden(part,False)
            c._cleanup_finished_slip_funnel_build(before,meshes,outputs)
            master.object[c.SLIP_CASTING_FUNNELS_BUILT_KEY] = True
            context.view_layer.update()
            success = True
            return outputs
        finally:
            if not success:
                remove_objects_safely([raw for raw in bpy.data.objects if raw.as_pointer() not in before])
                for mesh in list(bpy.data.meshes):
                    if mesh.as_pointer() not in meshes and mesh.users == 0:
                        bpy.data.meshes.remove(mesh)
    return BackgroundTaskSequence(steps())


def _references(scene):
    return sorted((Object(raw) for raw in scene.objects
                   if raw.type == 'MESH' and raw.get(REFERENCE_KEY)), key=lambda part: part.name)


def _subtract_master_from_funnel_references(context, references):
    """Trim companion snapshots against the cleared master, before funnel union."""
    if not references:
        return
    from .slip_casting_cavity_filler import _slip_casting_master
    from ..modifiers import diff_mod
    master = _slip_casting_master(context.scene)
    if master is None:
        raise ValueError('No cleared master available to trim rounded-funnel references')
    active = context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    cutter = None
    try:
        evaluated = master.object.evaluated_get(context.evaluated_depsgraph_get())
        mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=context.evaluated_depsgraph_get())
        raw = bpy.data.objects.new('_rounded_funnel_master_cutter', mesh)
        context.collection.objects.link(raw)
        raw.matrix_world = master.object.matrix_world.copy()
        cutter = Object(raw)
        context.view_layer.update()
        for reference in references:
            reference.apply_boolean_modifier(diff_mod, target=cutter, retry_remesh=False)
            if not reference.object.data.polygons:
                raise ValueError(f'{reference.object[SOURCE_KEY]} is fully inside the master; no funnel remains for its open-base mold')
    finally:
        if cutter is not None:
            cutter.remove()
        for raw in list(bpy.context.selected_objects):
            raw.select_set(False)
        for raw in selected:
            raw.select_set(True)
        context.view_layer.objects.active = active


def capture_rounded_funnel_references(context):
    """Freeze evaluated geometry and world placement at Generate Mold time."""
    if getattr(context.scene, 'slip_casting_funnel_type', '') != 'ROUNDED':
        return []
    from . import slip_casting_cavity_filler as c
    existing = {raw.get(SOURCE_KEY) for raw in context.scene.objects if raw.get(MOLD_KEY)}
    sources = sorted((raw for raw in context.scene.objects
                      if raw.type == 'MESH' and not raw.get(MOLD_KEY) and not raw.get(REFERENCE_KEY)
                      and (DIMENSIONS_KEY in raw or raw.name.startswith('rounded_funnel_'))
                      and raw.name not in existing), key=lambda raw: raw.name)
    created = []
    try:
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        for source in sources:
            evaluated = source.evaluated_get(depsgraph)
            mesh = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
            raw = bpy.data.objects.new(f'_rounded_funnel_reference_{source.name}', mesh)
            context.collection.objects.link(raw)
            created.append(Object(raw))
            raw.matrix_world = source.matrix_world.copy()
            raw[REFERENCE_KEY] = True
            raw[SOURCE_KEY] = source.name
            # Fresh objects deliberately omit the source's pending-union flag.
        for reference in created:
            c._set_reference_hidden(reference, True)
        for previous in _references(context.scene):
            if previous.object not in {part.object for part in created}:
                previous.remove()
        return created
    except BaseException:
        for part in created:
            part.remove()
        raise


def _flip_funnel_reference(reference):
    """Put the wide end down without changing the master-union operand."""
    corners = [reference.object.matrix_world @ v.co for v in reference.object.data.vertices]
    center = Vector(tuple((min(p[a] for p in corners)+max(p[a] for p in corners))/2 for a in range(3)))
    rotation = Matrix.Diagonal((1.,-1.,-1.,1.))
    reference.object.matrix_world = (Matrix.Translation(center) @ rotation
                                    @ Matrix.Translation(-center) @ reference.object.matrix_world)


def begin_prepare_rounded_funnel_reference_plans(context):
    """After master clearance: trim copies, flip, and use one central Y split."""
    def steps():
        if False:
            yield  # Keep the generation sequence's task interface.
        references = [ref for ref in _references(context.scene)
                      if not ref.object.get(REFERENCE_PLAN_KEY)]
        if not references:
            return []
        from .direct_mold import store_direct_undercut_paths
        from . import slip_casting_cavity_filler as c
        backups = [(ref, ref.object.data.copy(), ref.object.matrix_world.copy()) for ref in references]
        success = False
        try:
            for reference in references:
                c._set_reference_hidden(reference, False)
            # One snapshot of the cleared master cuts all copies before any
            # rounded funnel is committed by the subsequent box-generation stage.
            _subtract_master_from_funnel_references(context, references)
            for reference in references:
                _flip_funnel_reference(reference)
            context.view_layer.update()
            for reference in references:
                corners = [reference.object.matrix_world @ v.co for v in reference.object.data.vertices]
                center = [(min(p[a] for p in corners)+max(p[a] for p in corners))/2 for a in range(3)]
                specs = [[center, [0.,1.,0.]]]
                paths = {(side,): dict(plane_index=0, direction=(0.,float(side),0.),
                                      projection_plane_indices=(0,), path_sections=((side,),), order=index)
                         for index,side in enumerate((-1,1))}
                store_direct_undercut_paths(reference.object, specs, paths,
                                           easy_extraction=True, precise_cost=False,
                                           restrict_bottom_extraction=False)
                reference.object[REFERENCE_PLAN_KEY] = json.dumps({'specs': specs, 'boundary': []})
            success = True
        finally:
            for reference, mesh, matrix in backups:
                if success:
                    bpy.data.meshes.remove(mesh)
                else:
                    changed = reference.object.data
                    reference.object.data = mesh
                    reference.object.matrix_world = matrix
                    if changed.users == 0:
                        bpy.data.meshes.remove(changed)
                    if REFERENCE_PLAN_KEY in reference.object:
                        del reference.object[REFERENCE_PLAN_KEY]
                c._set_reference_hidden(reference, True)
            context.view_layer.update()
        return references
    return BackgroundTaskSequence(steps())


def iter_build_rounded_funnel_mold_steps(context, *, async_server=False):
    """Use the foot companion's Direct Open Base builder for each live snapshot."""
    from ... import operators as op
    from .direct_mold import load_direct_undercut_paths
    from . import slip_casting_cavity_filler as c
    references = _references(context.scene)
    center_single_funnel = len(references) == 1
    existing = {raw.get(SOURCE_KEY) for raw in context.scene.objects if raw.get(MOLD_KEY)}
    references = [part for part in references if part.object[SOURCE_KEY] not in existing]
    if not references:
        return []
    visible = [Object(raw) for raw in context.scene.objects
               if raw.type == 'MESH' and not raw.hide_viewport and not raw.hide_get()
               and not raw.get(REFERENCE_KEY)]
    gap = max(10., float(context.scene.clamp_depth))
    row_y = max((part.max_y for part in visible), default=0.) + gap
    next_x = min((part.min_x for part in visible), default=0.)
    outputs = []
    for index, reference in enumerate(references, 1):
        payload = reference.object.get(REFERENCE_PLAN_KEY)
        if not payload:
            raise RuntimeError('Generate Mold again to capture the edited rounded funnels and their split plan')
        plan = json.loads(payload)
        paths = load_direct_undercut_paths(reference.object, plan['specs'],
                                         easy_extraction=True, precise_cost=False,
                                         restrict_bottom_extraction=len(plan['specs']) != 1)
        if not paths:
            raise RuntimeError('Rounded-funnel reference has no matching central split plan')
        source_name = reference.object[SOURCE_KEY]
        state = op._prepare_slip_casting_vase_base_direct_mold(
            context, companion=reference, split_specs_override=plan['specs'],
            paths_override=paths, boundary_override=plan['boundary'],
            output_key=MOLD_KEY, output_prefix=f'rounded_funnel_mold_{index:03d}')
        try:
            yield from op.iter_build_direct_automatic_mold_steps(
                context, async_server=async_server,
                split_plane_specs_override=state['split_plane_specs'],
                locked_extraction_paths_override=state['undercut_paths'],
                undercut_boundary_specs_override=state['undercut_boundary_specs'])
            parts = op._restore_slip_casting_objects_after_vase_base_mold(
                context, state, keep_direct_outputs=True)
            for part in parts:
                part.object[SOURCE_KEY] = source_name
                for key in (REFERENCE_KEY, REFERENCE_PLAN_KEY):
                    if key in part.object:
                        del part.object[key]
            assembly = [reference, *parts]
            meshes = [part for part in assembly if part.object.type == 'MESH']
            left = min(part.min_x for part in meshes)
            right = max(part.max_x for part in meshes)
            lower = min(part.min_y for part in meshes)
            offset_x = -(left + right) / 2.0 if center_single_funnel else next_x - left
            translation = Matrix.Translation((offset_x, row_y-lower, 0.))
            placements = [(part.object, translation @ part.object.matrix_world) for part in assembly]
            for raw, matrix in placements:
                raw.matrix_world = matrix
            next_x += right-left+gap
            # The trimmed casting reference is also the plaster preview inside
            # this companion. Keep its reference tag so it is never recaptured
            # as a new funnel or added to the main master.
            reference.name = f'rounded_funnel_plaster_preview_{index:03d}'
            reference.object[PLASTER_PREVIEW_KEY] = True
            assign_plaster_mold_material(reference.object)
            c._set_reference_hidden(reference, False)
            context.view_layer.update()
            state['finished'] = True
            outputs.extend(parts)
        finally:
            if not state['finished']:
                op._restore_slip_casting_objects_after_vase_base_mold(context, state, keep_direct_outputs=False)
    return outputs


def build_rounded_funnel_molds(context):
    from ..background_worker import finish_task_sync
    steps = iter_build_rounded_funnel_mold_steps(context)
    while True:
        try:
            _label, callback = next(steps)
        except StopIteration as done:
            return done.value or []
        finish_task_sync(callback())
