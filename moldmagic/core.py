import math

import bpy
from mathutils import Vector

from .props import QUALITY_VERTS


def selected_target(context):
    obj = context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def world_bounds(obj):
    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c[i] for c in coords) for i in range(3)))
    maxs = Vector((max(c[i] for c in coords) for i in range(3)))
    return mins, maxs


def box_object(name, mins, maxs):
    cx, cy, cz = (mins + maxs) / 2
    sx, sy, sz = (maxs - mins) / 2
    verts = [
        (cx - sx, cy - sy, cz - sz),
        (cx + sx, cy - sy, cz - sz),
        (cx + sx, cy + sy, cz - sz),
        (cx - sx, cy + sy, cz - sz),
        (cx - sx, cy - sy, cz + sz),
        (cx + sx, cy - sy, cz + sz),
        (cx + sx, cy + sy, cz + sz),
        (cx - sx, cy + sy, cz + sz),
    ]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def _round_verts(context):
    props = context.scene.moldmagic
    return QUALITY_VERTS.get(props.quality, 48)


def add_cylinder(context, name, location, radius, depth, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=_round_verts(context),
        radius=radius,
        depth=depth,
        location=location,
        rotation=rotation,
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def add_cone(context, name, location, radius_base, radius_top, depth):
    bpy.ops.mesh.primitive_cone_add(
        vertices=_round_verts(context),
        radius1=radius_base,
        radius2=radius_top,
        depth=depth,
        location=location,
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def apply_boolean(target_obj, operand, operation):
    modifier = target_obj.modifiers.new(name="moldmagic_bool", type='BOOLEAN')
    modifier.operation = operation
    modifier.solver = 'EXACT'
    modifier.object = operand
    with bpy.context.temp_override(
        object=target_obj,
        active_object=target_obj,
        selected_objects=[target_obj],
        selected_editable_objects=[target_obj],
    ):
        bpy.ops.object.modifier_apply(modifier=modifier.name)


def remove(obj):
    if obj is not None:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def finish_result(context, parts, message):
    for obj in parts:
        obj.select_set(True)
    if parts:
        bpy.context.view_layer.objects.active = parts[0]
    context.view_layer.update()
    return {'FINISHED'} if not message else None


def split_planes(props, mins, maxs):
    height = maxs.z - mins.z
    fractions = [props.split_position]
    extra = max(int(props.n_z_splits), 0)
    if extra:
        band = 1.0 / (extra + 1)
        fractions = [band * (i + 1) for i in range(extra + 1)]
    return [mins.z + height * f for f in sorted(fractions)]


def key_ring_radius(props, mins, maxs):
    size = maxs - mins
    limit = min(size.x, size.y) / 2 + props.wall_gap - props.key_radius - 1.0
    radius = props.key_ring_radius
    if radius <= 0.0:
        radius = 0.35 * min(size.x, size.y)
    return max(min(radius, limit), props.key_radius + 2.0)
