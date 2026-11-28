import math

import bpy
from mathutils import Vector


def _props(context):
    return context.scene.moldforge


def _selected_target(context):
    obj = context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        return None
    return obj


def _world_bounds(obj):
    coords = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    mins = Vector((min(c[i] for c in coords) for i in range(3)))
    maxs = Vector((max(c[i] for c in coords) for i in range(3)))
    return mins, maxs


def _box_object(name, mins, maxs):
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


def _add_cylinder(name, location, radius, depth):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=radius, depth=depth, location=location
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _add_cone(name, location, radius_base, radius_top, depth):
    bpy.ops.mesh.primitive_cone_add(
        vertices=48,
        radius1=radius_base,
        radius2=radius_top,
        depth=depth,
        location=location,
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _duplicate(obj, name):
    duplicate = obj.copy()
    duplicate.data = obj.data.copy()
    duplicate.name = name
    bpy.context.collection.objects.link(duplicate)
    return duplicate


def _apply_boolean(target_obj, operand, operation):
    modifier = target_obj.modifiers.new(name="moldforge_bool", type='BOOLEAN')
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


def _remove(obj):
    if obj is not None:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass


def _key_ring_radius(props, mins, maxs):
    size = maxs - mins
    limit = min(size.x, size.y) / 2 + props.wall_gap - props.key_radius - 1.0
    radius = props.key_ring_radius
    if radius <= 0.0:
        radius = 0.35 * min(size.x, size.y)
    return max(min(radius, limit), props.key_radius + 2.0)


class MOLDFORGE_OT_generate_mold(bpy.types.Operator):
    bl_idname = "moldforge.generate_mold"
    bl_label = "Generate Mold"
    bl_description = "Generate a mold box around the active mesh object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = _props(context)
        target = _selected_target(context)
        if target is None:
            self.report({'ERROR'}, "Select a mesh object to mold.")
            return {'CANCELLED'}

        mins, maxs = _world_bounds(target)
        if maxs.z - mins.z <= 0:
            self.report({'ERROR'}, "Object has no height.")
            return {'CANCELLED'}

        margin = Vector(
            (props.wall_gap + props.wall_thickness,) * 3
        )
        outer_min = mins - margin
        outer_max = maxs + margin

        helpers = []
        block = _box_object("MoldForge_Mold", outer_min, outer_max)
        helpers.append(block)
        _apply_boolean(block, target, 'DIFFERENCE')

        two_part = props.two_part
        split_z = mins.z + (maxs.z - mins.z) * props.split_position
        top = bottom = None
        if two_part:
            lower_box = _box_object(
                "MoldForge_CutLower",
                Vector((outer_min.x, outer_min.y, outer_min.z)),
                Vector((outer_max.x, outer_max.y, split_z)),
            )
            upper_box = _box_object(
                "MoldForge_CutUpper",
                Vector((outer_min.x, outer_min.y, split_z)),
                Vector((outer_max.x, outer_max.y, outer_max.z)),
            )
            helpers.extend((lower_box, upper_box))
            top = _duplicate(block, "MoldForge_TopHalf")
            bottom = _duplicate(block, "MoldForge_BottomHalf")
            _apply_boolean(top, lower_box, 'DIFFERENCE')
            _apply_boolean(bottom, upper_box, 'DIFFERENCE')
            _remove(block)
            helpers.remove(block)
            _add_keys(props, top, bottom, mins, maxs, split_z)

        _add_pouring(props, top or block, mins, maxs, outer_max)

        for helper in helpers:
            _remove(helper)

        result = [obj for obj in (top, bottom, block) if obj is not None]
        for obj in result:
            obj.select_set(True)
        if result:
            bpy.context.view_layer.objects.active = result[0]
        self.report(
            {'INFO'},
            "MoldForge: generated {}.".format(
                "two-part mold" if two_part else "one-piece mold"
            ),
        )
        return {'FINISHED'}


def _add_keys(props, top, bottom, mins, maxs, split_z):
    try:
        ring = _key_ring_radius(props, mins, maxs)
    except Exception:
        return
    count = max(int(props.key_count), 0)
    if count == 0:
        return
    center = (mins + maxs) / 2
    span = props.key_height * 2 + props.key_tolerance * 2
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        location = (
            center.x + ring * math.cos(angle),
            center.y + ring * math.sin(angle),
            split_z,
        )
        boss = _add_cylinder(
            "MoldForge_KeyBoss", location, props.key_radius, props.key_height * 2
        )
        _apply_boolean(bottom, boss, 'UNION')
        _remove(boss)
        socket = _add_cylinder(
            "MoldForge_KeySocket",
            location,
            props.key_radius + props.key_tolerance,
            span + 1.0,
        )
        _apply_boolean(top, socket, 'DIFFERENCE')
        _remove(socket)


def _add_pouring(props, mold_half, mins, maxs, outer_max):
    center = (mins + maxs) / 2
    reach = props.funnel_reach
    bottom_z = maxs.z - reach
    top_z = outer_max.z + 1.0
    depth = top_z - bottom_z
    cone = _add_cone(
        "MoldForge_Funnel",
        (center.x, center.y, (top_z + bottom_z) / 2),
        props.funnel_bottom_radius,
        props.funnel_top_radius,
        depth,
    )
    _apply_boolean(mold_half, cone, 'DIFFERENCE')
    _remove(cone)

    vent_count = max(int(props.vent_count), 0)
    if vent_count == 0:
        return
    try:
        ring = _key_ring_radius(props, mins, maxs) * 0.8
    except Exception:
        ring = 0.0
    offset = math.pi / max(vent_count, 1)
    for index in range(vent_count):
        angle = 2.0 * math.pi * index / vent_count + offset
        location = (
            center.x + ring * math.cos(angle),
            center.y + ring * math.sin(angle),
            (top_z + bottom_z) / 2,
        )
        vent = _add_cylinder(
            "MoldForge_Vent", location, props.vent_radius, depth
        )
        _apply_boolean(mold_half, vent, 'DIFFERENCE')
        _remove(vent)


class MOLDFORGE_PT_main(bpy.types.Panel):
    bl_label = "MoldForge"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MoldForge"

    def draw(self, context):
        props = context.scene.moldforge
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column()
        col.prop(props, "wall_gap")
        col.prop(props, "wall_thickness")
        col.prop(props, "two_part")

        box = layout.box()
        box.label(text="Split & Keys")
        col = box.column()
        col.enabled = props.two_part
        col.prop(props, "split_position")
        col.prop(props, "key_count")
        col.prop(props, "key_ring_radius")
        col.prop(props, "key_radius")
        col.prop(props, "key_tolerance")
        col.prop(props, "key_height")

        box = layout.box()
        box.label(text="Pouring")
        col = box.column()
        col.prop(props, "funnel_top_radius")
        col.prop(props, "funnel_bottom_radius")
        col.prop(props, "funnel_reach")
        col.prop(props, "vent_count")
        col.prop(props, "vent_radius")

        layout.operator("moldforge.generate_mold", icon='MESH_CUBE')


class MoldForgeProperties(bpy.types.PropertyGroup):
    wall_gap: bpy.props.FloatProperty(
        name="Gap",
        description="Clearance between the object and the mold wall (mm)",
        default=4.0,
        min=0.0,
    )
    wall_thickness: bpy.props.FloatProperty(
        name="Wall Thickness",
        description="Mold wall thickness (mm)",
        default=6.0,
        min=1.0,
    )
    two_part: bpy.props.BoolProperty(
        name="Two-Part Mold",
        description="Split the mold into two halves with registration keys",
        default=True,
    )
    split_position: bpy.props.FloatProperty(
        name="Split Height",
        description="Split plane position as a fraction of the object height",
        default=0.5,
        min=0.05,
        max=0.95,
    )
    key_count: bpy.props.IntProperty(
        name="Key Count",
        description="Number of registration keys",
        default=4,
        min=0,
        max=12,
    )
    key_ring_radius: bpy.props.FloatProperty(
        name="Key Ring Radius",
        description="Radius of the key ring (0 = automatic)",
        default=0.0,
        min=0.0,
    )
    key_radius: bpy.props.FloatProperty(
        name="Key Radius",
        description="Registration key radius (mm)",
        default=4.0,
        min=0.5,
    )
    key_tolerance: bpy.props.FloatProperty(
        name="Key Tolerance",
        description="Clearance between key and socket (mm)",
        default=0.25,
        min=0.0,
    )
    key_height: bpy.props.FloatProperty(
        name="Key Height",
        description="How far each key protrudes past the split plane (mm)",
        default=4.0,
        min=0.5,
    )
    funnel_top_radius: bpy.props.FloatProperty(
        name="Funnel Top Radius",
        description="Pour funnel radius at the mold top (mm)",
        default=10.0,
        min=0.5,
    )
    funnel_bottom_radius: bpy.props.FloatProperty(
        name="Funnel Bottom Radius",
        description="Pour funnel radius at the bottom (mm)",
        default=4.0,
        min=0.5,
    )
    funnel_reach: bpy.props.FloatProperty(
        name="Funnel Reach",
        description="How far the funnel reaches below the object top (mm)",
        default=5.0,
        min=0.0,
    )
    vent_count: bpy.props.IntProperty(
        name="Vent Count",
        description="Number of air vents",
        default=2,
        min=0,
        max=12,
    )
    vent_radius: bpy.props.FloatProperty(
        name="Vent Radius",
        description="Air vent radius (mm)",
        default=1.5,
        min=0.2,
    )


CLASSES = (
    MoldForgeProperties,
    MOLDFORGE_OT_generate_mold,
    MOLDFORGE_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.moldforge = bpy.props.PointerProperty(
        type=MoldForgeProperties
    )


def unregister():
    del bpy.types.Scene.moldforge
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
