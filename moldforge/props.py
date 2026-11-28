import bpy


QUALITY_VERTS = {"LOW": 24, "MID": 48, "HIGH": 96}

MOLD_PRESETS = {
    "TWO_PART": {
        "wall_gap": 4.0, "wall_thickness": 6.0, "two_part": True,
        "key_count": 4, "key_radius": 4.0, "key_tolerance": 0.25,
        "key_height": 4.0, "master_base_pin": True,
        "funnel_top_radius": 10.0, "funnel_bottom_radius": 4.0,
        "vent_count": 2, "casting_feet": False, "casting_grip": False,
        "clamp_bolt_count": 0, "add_casting_box": False,
    },
    "ONE_PIECE": {
        "wall_gap": 4.0, "wall_thickness": 6.0, "two_part": False,
        "key_count": 0, "funnel_top_radius": 12.0,
        "funnel_bottom_radius": 5.0, "vent_count": 3,
        "casting_feet": False, "casting_grip": False,
        "clamp_bolt_count": 0, "add_casting_box": False,
    },
    "SHELL": {
        "wall_gap": 0.8, "wall_thickness": 3.0, "two_part": True,
        "key_count": 4, "key_radius": 3.0, "key_tolerance": 0.15,
        "key_height": 3.0, "master_base_pin": True,
        "funnel_top_radius": 8.0, "funnel_bottom_radius": 3.0,
        "vent_count": 2, "casting_feet": False, "casting_grip": True,
        "clamp_bolt_count": 4, "add_casting_box": False,
    },
    "FIXTURE": {
        "wall_gap": 2.0, "wall_thickness": 8.0, "two_part": False,
        "key_count": 0, "vent_count": 0, "casting_feet": True,
        "casting_grip": True, "clamp_bolt_count": 0,
        "add_casting_box": False,
    },
    "PLASTER": {
        "wall_gap": 5.0, "wall_thickness": 10.0, "two_part": True,
        "key_count": 4, "key_radius": 5.0, "key_tolerance": 0.4,
        "key_height": 5.0, "master_base_pin": True,
        "funnel_top_radius": 14.0, "funnel_bottom_radius": 6.0,
        "vent_count": 4, "channel_count": 4,
        "casting_feet": True, "casting_grip": False,
        "clamp_bolt_count": 0, "add_casting_box": False,
    },
    "SLIP_CASTING": {
        "wall_gap": 3.0, "wall_thickness": 8.0, "two_part": True,
        "key_count": 4, "key_radius": 4.0, "key_tolerance": 0.3,
        "key_height": 4.0, "master_base_pin": True,
        "funnel_top_radius": 12.0, "funnel_bottom_radius": 5.0,
        "funnel_reach": 8.0, "vent_count": 2, "channel_count": 2,
        "casting_feet": True, "casting_grip": True,
        "clamp_bolt_count": 4, "add_casting_box": True,
    },
}


def _update_mold_preset(self, context):
    values = MOLD_PRESETS.get(self.mold_preset)
    if not values:
        return
    for name, value in values.items():
        if hasattr(self, name):
            setattr(self, name, value)


class MoldForgeProperties(bpy.types.PropertyGroup):
    mold_preset: bpy.props.EnumProperty(
        name="Preset",
        description="Mold style preset",
        items=(
            ("TWO_PART", "Silicone Two-Part", "Classic two-part silicone mold"),
            ("ONE_PIECE", "Silicone One-Piece", "Single block with cavity and funnel"),
            ("SHELL", "Protective Shell", "Tight two-part hard shell"),
            ("FIXTURE", "Fixture Frame", "Open-top frame around the object"),
            ("PLASTER", "Plaster Mold", "Thick two-part mold with channels"),
            ("SLIP_CASTING", "Slip Casting Box", "Two-part mold plus casting box"),
        ),
        default="TWO_PART",
        update=_update_mold_preset,
    )
    quality: bpy.props.EnumProperty(
        name="Quality",
        description="Round feature resolution",
        items=(
            ("LOW", "Low", "Fast, coarse round features"),
            ("MID", "Mid", "Balanced"),
            ("HIGH", "High", "Fine round features, slower booleans"),
        ),
        default="MID",
    )
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
        description="Split the mold into stacked parts with registration keys",
        default=True,
    )
    n_z_splits: bpy.props.IntProperty(
        name="Extra Splits",
        description="Additional horizontal splits (parts = splits + 2)",
        default=0,
        min=0,
        max=3,
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
        description="Number of registration keys per interface",
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
    master_base_pin: bpy.props.BoolProperty(
        name="Master Base Pin",
        description="Center alignment pin on the lowest interface",
        default=True,
    )
    master_pin_radius: bpy.props.FloatProperty(
        name="Master Pin Radius",
        description="Master base pin radius (mm)",
        default=5.0,
        min=1.0,
    )
    master_pin_tolerance: bpy.props.FloatProperty(
        name="Master Pin Tolerance",
        description="Master base pin socket clearance (mm)",
        default=0.3,
        min=0.0,
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
    funnel_count: bpy.props.IntProperty(
        name="Funnel Count",
        description="Number of pour funnels",
        default=1,
        min=1,
        max=3,
    )
    channel_count: bpy.props.IntProperty(
        name="Channel Count",
        description="Horizontal air/channel grooves at the split plane",
        default=0,
        min=0,
        max=4,
    )
    channel_radius: bpy.props.FloatProperty(
        name="Channel Radius",
        description="Channel groove radius (mm)",
        default=3.0,
        min=0.5,
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
    casting_feet: bpy.props.BoolProperty(
        name="Casting Feet",
        description="Add feet under the mold bottom",
        default=False,
    )
    feet_height: bpy.props.FloatProperty(
        name="Feet Height",
        description="Casting feet height (mm)",
        default=5.0,
        min=1.0,
    )
    casting_grip: bpy.props.BoolProperty(
        name="Grip Notches",
        description="Add grip notches to the lower part sides",
        default=False,
    )
    grip_width: bpy.props.FloatProperty(
        name="Grip Width",
        description="Grip notch height (mm)",
        default=8.0,
        min=2.0,
    )
    grip_depth: bpy.props.FloatProperty(
        name="Grip Depth",
        description="Grip notch depth (mm)",
        default=7.0,
        min=1.0,
    )
    clamp_bolt_count: bpy.props.IntProperty(
        name="Clamp Bolts",
        description="Vertical clamp bolt holes through both parts",
        default=0,
        min=0,
        max=8,
    )
    clamp_bolt_diameter: bpy.props.FloatProperty(
        name="Bolt Diameter",
        description="Clamp bolt hole diameter (mm)",
        default=4.2,
        min=1.0,
    )
    add_casting_box: bpy.props.BoolProperty(
        name="Add Casting Box",
        description="Also generate a rigid casting box around the mold",
        default=False,
    )
    box_thickness: bpy.props.FloatProperty(
        name="Box Thickness",
        description="Casting box wall thickness (mm)",
        default=5.0,
        min=1.0,
    )
    shell_thickness: bpy.props.FloatProperty(
        name="Shell Thickness",
        description="Hollow shell wall thickness (mm)",
        default=3.0,
        min=0.5,
    )
    export_format: bpy.props.EnumProperty(
        name="Format",
        description="Batch export format",
        items=(
            ("STL", "STL", "Stereolithography"),
            ("OBJ", "OBJ", "Wavefront OBJ"),
            ("GLB", "glTF", "glTF binary"),
        ),
        default="STL",
    )


def register():
    bpy.utils.register_class(MoldForgeProperties)
    bpy.types.Scene.moldforge = bpy.props.PointerProperty(
        type=MoldForgeProperties
    )


def unregister():
    del bpy.types.Scene.moldforge
    bpy.utils.unregister_class(MoldForgeProperties)
