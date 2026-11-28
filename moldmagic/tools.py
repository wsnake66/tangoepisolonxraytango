import math

import bmesh
import bpy
from mathutils import Vector

from .core import (
    add_cylinder,
    apply_boolean,
    box_object,
    remove,
    selected_target,
    world_bounds,
)


class MOLDMAGIC_OT_casting_box(bpy.types.Operator):
    bl_idname = "moldmagic.casting_box"
    bl_label = "Casting Box"
    bl_description = "Generate a rigid casting box around the selected mold parts"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.moldmagic
        parts = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj.name.startswith("MoldMagic_")
        ]
        if not parts:
            self.report({'ERROR'}, "Select the generated mold parts first.")
            return {'CANCELLED'}

        mins, maxs = world_bounds(parts[0])
        for part in parts[1:]:
            pmin, pmax = world_bounds(part)
            mins = Vector(map(min, mins, pmin))
            maxs = Vector(map(max, maxs, pmax))

        thickness = props.box_thickness
        outer_min = mins - Vector((thickness, thickness, thickness))
        outer_max = maxs + Vector((thickness, thickness, max(thickness, 2.0)))
        box = box_object("MoldMagic_CastingBox", outer_min, outer_max)
        inner = box_object(
            "MoldMagic_CastingBoxWindow", mins, maxs
        )
        apply_boolean(box, inner, 'DIFFERENCE')
        remove(inner)

        center_z = (outer_max.z + outer_min.z) / 2
        radius = 2.0
        depth = (outer_max.z - outer_min.z) + 4.0
        inset = thickness
        for sign_x in (-1, 1):
            for sign_y in (-1, 1):
                center = (mins + maxs) / 2
                hole = add_cylinder(
                    context, "MoldMagic_BoxBolt",
                    (
                        center.x + sign_x * (maxs.x - mins.x) / 2 + sign_x * (thickness / 2),
                        center.y + sign_y * (maxs.y - mins.y) / 2 + sign_y * (thickness / 2),
                        center_z,
                    ),
                    radius, depth,
                )
                apply_boolean(box, hole, 'DIFFERENCE')
                remove(hole)

        box.select_set(True)
        bpy.context.view_layer.objects.active = box
        self.report({'INFO'}, "MoldMagic: casting box generated.")
        return {'FINISHED'}


class MOLDMAGIC_OT_hollow_shell(bpy.types.Operator):
    bl_idname = "moldmagic.hollow_shell"
    bl_label = "Hollow Shell"
    bl_description = "Create a hollow shelled copy of the active object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.moldmagic
        target = selected_target(context)
        if target is None:
            self.report({'ERROR'}, "Select a mesh object to shell.")
            return {'CANCELLED'}

        shell = target.copy()
        shell.data = target.data.copy()
        shell.name = target.name + "_Shell"
        bpy.context.collection.objects.link(shell)

        bm = bmesh.new()
        bm.from_mesh(shell.data)
        open_faces = [
            face for face in bm.faces
            if face.normal.z < -0.6
        ]
        if open_faces:
            bmesh.ops.delete(bm, geom=open_faces, context='FACES')
        bm.to_mesh(shell.data)
        bm.free()
        shell.data.update()

        modifier = shell.modifiers.new(name="MoldMagic_Shell", type='SOLIDIFY')
        modifier.thickness = props.shell_thickness
        modifier.offset = -1.0
        with bpy.context.temp_override(
            object=shell,
            active_object=shell,
            selected_objects=[shell],
            selected_editable_objects=[shell],
        ):
            bpy.ops.object.modifier_apply(modifier=modifier.name)

        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        shell.select_set(True)
        bpy.context.view_layer.objects.active = shell
        self.report({'INFO'}, "MoldMagic: hollow shell created.")
        return {'FINISHED'}


class MOLDMAGIC_OT_analyze_undercuts(bpy.types.Operator):
    bl_idname = "moldmagic.analyze_undercuts"
    bl_label = "Analyze Split Height"
    bl_description = "Find the object height with the widest cross-section"
    bl_options = {'REGISTER', 'UNDO'}

    _GRID = 16
    _HEIGHTS = 24

    def execute(self, context):
        target = selected_target(context)
        if target is None:
            self.report({'ERROR'}, "Select a mesh object to analyze.")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        evaluated = target.evaluated_get(depsgraph)
        mins, maxs = world_bounds(target)
        center = (mins + maxs) / 2
        height = maxs.z - mins.z

        def section_width(z):
            half_diagonal = math.hypot(
                (maxs.x - mins.x) / 2, (maxs.y - mins.y) / 2
            ) + 1.0
            hits = []
            for index in range(self._GRID):
                angle = 2.0 * math.pi * index / self._GRID
                direction = Vector((math.cos(angle), math.sin(angle), 0.0))
                origin = Vector(
                    (center.x, center.y, z)
                ) - direction * half_diagonal
                result, location, *_rest = context.scene.ray_cast(
                    depsgraph, origin, direction
                )
                if not result:
                    return None
                offset = (location - Vector((center.x, center.y, z)))
                hits.append(offset.dot(direction))
            if not hits:
                return None
            return min(hits) + half_diagonal

        best_z = None
        best_width = -1.0
        samples = []
        for row in range(self._HEIGHTS):
            z = mins.z + height * (row + 0.5) / self._HEIGHTS
            width = section_width(z)
            if width is None:
                continue
            samples.append((z, width))
            if width > best_width:
                best_width = width
                best_z = z

        if best_z is None or best_width <= 0:
            self.report(
                {'WARNING'},
                "MoldMagic: could not measure cross-sections; is the object closed?",
            )
            return {'CANCELLED'}

        props = context.scene.moldmagic
        recommended = (best_z - mins.z) / height
        props.split_position = min(max(recommended, 0.05), 0.95)
        self.report(
            {'INFO'},
            "MoldMagic: widest section at {:.0f}% height (width {:.1f} mm); split height updated.".format(
                recommended * 100.0, best_width
            ),
        )
        return {'FINISHED'}


class MOLDMAGIC_OT_export_molds(bpy.types.Operator):
    bl_idname = "moldmagic.export_molds"
    bl_label = "Export Mold Parts"
    bl_description = "Export the generated MoldMagic parts"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.moldmagic
        parts = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj.name.startswith("MoldMagic_")
        ]
        if not parts:
            self.report({'ERROR'}, "Select MoldMagic parts to export.")
            return {'CANCELLED'}

        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in parts:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = parts[0]

        directory = bpy.path.abspath("//") or "/tmp"
        exported = []
        try:
            for part in parts:
                filepath = bpy.path.ensure_ext(
                    directory + part.name, "." + props.export_format.lower()
                )
                if props.export_format == "STL":
                    bpy.ops.wm.stl_export(filepath=filepath, export_selected_objects=True)
                elif props.export_format == "OBJ":
                    bpy.ops.wm.obj_export(filepath=filepath, export_selected_objects=True)
                else:
                    bpy.ops.export_scene.gltf(
                        filepath=bpy.path.ensure_ext(filepath, ".glb"),
                        export_format='GLB',
                        use_selection=True,
                    )
                exported.append(filepath)
        except Exception as error:
            self.report({'ERROR'}, "MoldMagic: export failed: {}".format(error))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            "MoldMagic: exported {} file(s).".format(len(exported)),
        )
        return {'FINISHED'}
