import bpy

from . import props as props_module
from .generate import MOLDFORGE_OT_generate_mold
from .tools import (
    MOLDFORGE_OT_analyze_undercuts,
    MOLDFORGE_OT_casting_box,
    MOLDFORGE_OT_export_molds,
    MOLDFORGE_OT_hollow_shell,
)

MoldForgeProperties = props_module.MoldForgeProperties


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
        col.prop(props, "mold_preset")
        col.prop(props, "quality")

        box = layout.box()
        box.label(text="Box")
        col = box.column()
        col.prop(props, "wall_gap")
        col.prop(props, "wall_thickness")
        col.prop(props, "two_part")
        col = box.column()
        col.enabled = props.two_part
        col.prop(props, "n_z_splits")
        col.prop(props, "split_position")

        box = layout.box()
        box.label(text="Registration")
        col = box.column()
        col.enabled = props.two_part
        col.prop(props, "key_count")
        col.prop(props, "key_ring_radius")
        col.prop(props, "key_radius")
        col.prop(props, "key_tolerance")
        col.prop(props, "key_height")
        col.prop(props, "master_base_pin")
        col = box.column()
        col.enabled = props.two_part and props.master_base_pin
        col.prop(props, "master_pin_radius")
        col.prop(props, "master_pin_tolerance")

        box = layout.box()
        box.label(text="Pouring & Air")
        col = box.column()
        col.prop(props, "funnel_count")
        col.prop(props, "funnel_top_radius")
        col.prop(props, "funnel_bottom_radius")
        col.prop(props, "funnel_reach")
        col.prop(props, "vent_count")
        col.prop(props, "vent_radius")
        col.prop(props, "channel_count")
        col.prop(props, "channel_radius")

        box = layout.box()
        box.label(text="Handling")
        col = box.column()
        col.prop(props, "casting_feet")
        col = box.column()
        col.enabled = props.casting_feet
        col.prop(props, "feet_height")
        col = box.column()
        col.prop(props, "casting_grip")
        col = box.column()
        col.enabled = props.casting_grip
        col.prop(props, "grip_width")
        col.prop(props, "grip_depth")
        col = box.column()
        col.prop(props, "clamp_bolt_count")
        col = box.column()
        col.enabled = props.clamp_bolt_count > 0
        col.prop(props, "clamp_bolt_diameter")

        layout.operator("moldforge.analyze_undercuts", icon='VIEWZOOM')
        layout.operator("moldforge.generate_mold", icon='MESH_CUBE')

        box = layout.box()
        box.label(text="Post Steps")
        col = box.column()
        col.prop(props, "add_casting_box")
        col = box.column()
        col.enabled = props.add_casting_box
        col.prop(props, "box_thickness")
        col.operator("moldforge.casting_box", icon='CUBE')
        col.separator()
        col.prop(props, "shell_thickness")
        col.operator("moldforge.hollow_shell", icon='SPHERE')
        col.separator()
        col.prop(props, "export_format")
        col.operator("moldforge.export_molds", icon='EXPORT')


CLASSES = (
    MoldForgeProperties,
    MOLDFORGE_OT_generate_mold,
    MOLDFORGE_OT_casting_box,
    MOLDFORGE_OT_hollow_shell,
    MOLDFORGE_OT_analyze_undercuts,
    MOLDFORGE_OT_export_molds,
    MOLDFORGE_PT_main,
)


def register():
    props_module.register()
    for cls in CLASSES:
        if cls is not MoldForgeProperties:
            bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        if cls is not MoldForgeProperties:
            bpy.utils.unregister_class(cls)
    props_module.unregister()


if __name__ == "__main__":
    register()
