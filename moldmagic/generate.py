import math

import bpy
from mathutils import Vector

from .core import (
    add_cone,
    add_cylinder,
    apply_boolean,
    box_object,
    finish_result,
    key_ring_radius,
    remove,
    selected_target,
    split_planes,
    world_bounds,
)


def _split_into_parts(context, block, outer_min, outer_max, planes):
    parts = []
    previous_z = outer_min.z
    cutters = []
    for index, plane_z in enumerate(list(planes) + [outer_max.z]):
        cutter = box_object(
            "MoldMagic_Cutter",
            Vector((outer_min.x, outer_min.y, previous_z)),
            Vector((outer_max.x, outer_max.y, plane_z)),
        )
        part = block.copy()
        part.data = block.data.copy()
        part.name = f"MoldMagic_Part_{index:02d}"
        bpy.context.collection.objects.link(part)
        apply_boolean(part, cutter, 'INTERSECT')
        parts.append(part)
        cutters.append(cutter)
        previous_z = plane_z
    remove(block)
    for cutter in cutters:
        remove(cutter)
    return parts


def _add_interface_keys(context, props, lower, upper, mins, maxs, plane_z):
    count = max(int(props.key_count), 0)
    if count:
        try:
            ring = key_ring_radius(props, mins, maxs)
        except Exception:
            ring = 0.0
        center = (mins + maxs) / 2
        span = props.key_height * 2 + props.key_tolerance * 2
        for index in range(count):
            angle = 2.0 * math.pi * index / count
            location = (
                center.x + ring * math.cos(angle),
                center.y + ring * math.sin(angle),
                plane_z,
            )
            boss = add_cylinder(
                context, "MoldMagic_KeyBoss",
                location, props.key_radius, props.key_height * 2,
            )
            apply_boolean(lower, boss, 'UNION')
            remove(boss)
            socket = add_cylinder(
                context, "MoldMagic_KeySocket",
                location, props.key_radius + props.key_tolerance,
                span + 1.0,
            )
            apply_boolean(upper, socket, 'DIFFERENCE')
            remove(socket)

    if props.master_base_pin:
        center = (mins + maxs) / 2
        height = props.key_height * 2 + props.master_pin_tolerance * 2
        pin = add_cone(
            context, "MoldMagic_MasterPin",
            (center.x, center.y, plane_z),
            props.master_pin_radius + props.master_pin_tolerance,
            props.master_pin_radius + props.master_pin_tolerance,
            height,
        )
        apply_boolean(lower, pin, 'UNION')
        remove(pin)
        socket = add_cylinder(
            context, "MoldMagic_MasterSocket",
            (center.x, center.y, plane_z),
            props.master_pin_radius + props.master_pin_tolerance * 2,
            height + 1.0,
        )
        apply_boolean(upper, socket, 'DIFFERENCE')
        remove(socket)


def _add_pouring(context, props, part, mins, maxs, outer_min, outer_max):
    center = (mins + maxs) / 2
    reach = props.funnel_reach
    bottom_z = maxs.z - reach
    top_z = outer_max.z + 1.0
    depth = top_z - bottom_z
    count = max(int(props.funnel_count), 1)
    ring = key_ring_radius(props, mins, maxs) * 0.6 if count > 1 else 0.0
    for index in range(count):
        angle = 2.0 * math.pi * index / count + (math.pi / count if count > 1 else 0.0)
        location = (
            center.x + ring * math.cos(angle),
            center.y + ring * math.sin(angle),
            (top_z + bottom_z) / 2,
        )
        cone = add_cone(
            context, "MoldMagic_Funnel",
            location, props.funnel_bottom_radius, props.funnel_top_radius, depth,
        )
        apply_boolean(part, cone, 'DIFFERENCE')
        remove(cone)

    vent_count = max(int(props.vent_count), 0)
    if vent_count:
        vent_ring = key_ring_radius(props, mins, maxs) * 0.8
        offset = math.pi / max(vent_count, 1)
        for index in range(vent_count):
            angle = 2.0 * math.pi * index / vent_count + offset
            location = (
                center.x + vent_ring * math.cos(angle),
                center.y + vent_ring * math.sin(angle),
                (top_z + bottom_z) / 2,
            )
            vent = add_cylinder(
                context, "MoldMagic_Vent", location, props.vent_radius, depth
            )
            apply_boolean(part, vent, 'DIFFERENCE')
            remove(vent)


def _add_channels(context, props, part, mins, maxs, outer_min, outer_max, plane_z):
    count = max(int(props.channel_count), 0)
    if count == 0:
        return
    center = (mins + maxs) / 2
    size = maxs - mins
    inner = min(size.x, size.y) / 2 + props.wall_gap
    outer = max(size.x, size.y) / 2 + props.wall_gap + props.wall_thickness + 1.0
    length = inner + outer
    directions = [
        ((1.0, 0.0, 0.0), (math.pi / 2, 0.0, 0.0)),
        ((-1.0, 0.0, 0.0), (math.pi / 2, 0.0, 0.0)),
        ((0.0, 1.0, 0.0), (0.0, math.pi / 2, 0.0)),
        ((0.0, -1.0, 0.0), (0.0, math.pi / 2, 0.0)),
    ]
    for index in range(min(count, 4)):
        direction, rotation = directions[index]
        start = Vector((center.x, center.y, plane_z)) + Vector(direction) * (inner - 1.0)
        location = start + Vector(direction) * (length / 2)
        channel = add_cylinder(
            context, "MoldMagic_Channel",
            location, props.channel_radius, length + 2.0, rotation=rotation,
        )
        apply_boolean(part, channel, 'DIFFERENCE')
        remove(channel)


def _add_clamp_bolts(context, props, parts, mins, maxs, outer_min, outer_max):
    count = max(int(props.clamp_bolt_count), 0)
    if count == 0 or not parts:
        return
    size = maxs - mins
    inset_x = size.x / 2 + props.wall_gap + props.wall_thickness / 2
    inset_y = size.y / 2 + props.wall_gap + props.wall_thickness / 2
    center = (mins + maxs) / 2
    corners = {
        1: [(0.0, -inset_y)],
        2: [(0.0, -inset_y), (0.0, inset_y)],
        3: [(-inset_x, -inset_y), (inset_x, -inset_y), (0.0, inset_y)],
    }.get(count)
    if corners is None:
        if count == 4:
            corners = [(-inset_x, -inset_y), (inset_x, -inset_y),
                       (-inset_x, inset_y), (inset_x, inset_y)]
        else:
            corners = []
            for index in range(count):
                angle = 2.0 * math.pi * index / count
                corners.append((inset_x * math.cos(angle), inset_y * math.sin(angle)))
    depth = (outer_max.z - outer_min.z) + 2.0
    center_z = (outer_max.z + outer_min.z) / 2
    radius = props.clamp_bolt_diameter / 2
    for offset_x, offset_y in corners:
        hole = add_cylinder(
            context, "MoldMagic_BoltHole",
            (center.x + offset_x, center.y + offset_y, center_z),
            radius, depth,
        )
        for part in parts:
            apply_boolean(part, hole, 'DIFFERENCE')
        remove(hole)


def _add_feet(context, props, part, mins, maxs, outer_min, outer_max):
    if not props.casting_feet:
        return
    size = maxs - mins
    inset_x = size.x / 2 + props.wall_gap - props.feet_height
    inset_y = size.y / 2 + props.wall_gap - props.feet_height
    center = (mins + maxs) / 2
    radius = props.feet_height
    z = outer_min.z - radius / 2
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            foot = add_cylinder(
                context, "MoldMagic_Foot",
                (center.x + sign_x * inset_x, center.y + sign_y * inset_y, z),
                radius, radius,
            )
            apply_boolean(part, foot, 'UNION')
            remove(foot)


def _add_grips(context, props, part, mins, maxs, outer_min, outer_max, plane_z):
    if not props.casting_grip:
        return
    size = maxs - mins
    center = (mins + maxs) / 2
    half_width = props.grip_width / 2
    depth = props.grip_depth + props.wall_thickness + props.wall_gap + 1.0
    for sign in (-1, 1):
        notch = box_object(
            "MoldMagic_Grip",
            Vector((center.x - half_width, center.y + sign * (size.y / 2 + props.wall_gap), plane_z - props.grip_width)),
            Vector((center.x + half_width, center.y + sign * (size.y / 2 + props.wall_gap + depth), plane_z + props.grip_width)),
        )
        apply_boolean(part, notch, 'DIFFERENCE')
        remove(notch)


def _make_fixture_frame(context, props, mins, maxs, outer_min, outer_max):
    frame = box_object("MoldMagic_Fixture", outer_min, outer_max)
    window = box_object(
        "MoldMagic_FixtureWindow",
        Vector((mins.x - props.wall_gap, mins.y - props.wall_gap, outer_min.z - 1.0)),
        Vector((maxs.x + props.wall_gap, maxs.y + props.wall_gap, outer_max.z + 1.0)),
    )
    apply_boolean(frame, window, 'DIFFERENCE')
    remove(window)
    return frame


class MOLDMAGIC_OT_generate_mold(bpy.types.Operator):
    bl_idname = "moldmagic.generate_mold"
    bl_label = "Generate Mold"
    bl_description = "Generate a mold around the active mesh object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.moldmagic
        target = selected_target(context)
        if target is None:
            self.report({'ERROR'}, "Select a mesh object to mold.")
            return {'CANCELLED'}

        mins, maxs = world_bounds(target)
        if maxs.z - mins.z <= 0:
            self.report({'ERROR'}, "Object has no height.")
            return {'CANCELLED'}

        margin = Vector((props.wall_gap + props.wall_thickness,) * 3)
        outer_min = mins - margin
        outer_max = maxs + margin
        helpers = []
        parts = []

        if props.mold_preset == "FIXTURE":
            parts.append(_make_fixture_frame(context, props, mins, maxs, outer_min, outer_max))
            for part in parts:
                _add_feet(context, props, part, mins, maxs, outer_min, outer_max)
            for helper in helpers:
                remove(helper)
            for obj in parts:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = parts[0]
            self.report({'INFO'}, "MoldMagic: fixture frame generated.")
            return {'FINISHED'}

        block = box_object("MoldMagic_Mold", outer_min, outer_max)
        helpers.append(block)
        apply_boolean(block, target, 'DIFFERENCE')

        if props.two_part:
            planes = split_planes(props, mins, maxs)
            parts = _split_into_parts(context, block, outer_min, outer_max, planes)
            if block in helpers:
                helpers.remove(block)
            for index in range(len(parts) - 1):
                _add_interface_keys(
                    context, props, parts[index], parts[index + 1],
                    mins, maxs, planes[index],
                )
            lower = parts[0]
            upper = parts[-1]
            _add_channels(
                context, props, upper, mins, maxs, outer_min, outer_max,
                planes[0],
            )
            _add_clamp_bolts(context, props, parts, mins, maxs, outer_min, outer_max)
            _add_grips(
                context, props, lower, mins, maxs, outer_min, outer_max,
                planes[0],
            )
            _add_feet(context, props, lower, mins, maxs, outer_min, outer_max)
            _add_pouring(context, props, upper, mins, maxs, outer_min, outer_max)
        else:
            parts.append(block)
            if block in helpers:
                helpers.remove(block)
            _add_feet(context, props, block, mins, maxs, outer_min, outer_max)
            _add_pouring(context, props, block, mins, maxs, outer_min, outer_max)

        for helper in helpers:
            remove(helper)

        for obj in parts:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = parts[0]

        if props.add_casting_box:
            bpy.ops.moldmagic.casting_box('INVOKE_DEFAULT')

        self.report(
            {'INFO'},
            "MoldMagic: {} with {} part(s) generated.".format(
                props.mold_preset.replace('_', ' ').title(), len(parts)
            ),
        )
        return {'FINISHED'}
