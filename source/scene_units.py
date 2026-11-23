"""Millimeter geometry with user-selected Blender display units."""

import bpy
from bpy.app.handlers import persistent


_INITIALIZED_KEY = "_moldboxer_length_units_initialized"
_account_units_callback = None
_account_units = None
_LENGTH_UNITS = {
    "MICROMETERS": (1e-6, "µm"),
    "MILLIMETERS": (0.001, "mm"),
    "CENTIMETERS": (0.01, "cm"),
    "METERS": (1.0, "m"),
    "KILOMETERS": (1000.0, "km"),
    "INCHES": (0.0254, "in"),
    "FEET": (0.3048, "ft"),
    "MILES": (1609.344, "mi"),
}


def configure_scene_units(scene):
    settings = scene.unit_settings
    if not scene.get(_INITIALIZED_KEY, False):
        # Default new metric/unitless projects to mm. An existing Imperial
        # selection (including feet/inches/adaptive) must survive initialization.
        if _account_units is not None:
            settings.system = "IMPERIAL" if _account_units == "US" else "METRIC"
            settings.length_unit = "INCHES" if _account_units == "US" else "MILLIMETERS"
        elif settings.system in {"NONE", "METRIC"}:
            settings.system = "METRIC"
            settings.length_unit = "MILLIMETERS"
        scene[_INITIALIZED_KEY] = True
    # Geometry, tolerances and recipes use millimeters internally. This scale
    # also lets native RNA distance widgets convert inch input back to mm.
    settings.scale_length = 0.001


def format_distance(value, scene):
    settings = scene.unit_settings
    if settings.system == "NONE":
        return f"{value:.4g}"
    meters = float(value) * settings.scale_length
    unit = _LENGTH_UNITS.get(settings.length_unit)
    if unit is not None:
        factor, label = unit
        return f"{meters / factor:.4g} {label}"
    return bpy.utils.units.to_string(
        settings.system, "LENGTH", meters, precision=4,
        split_unit=settings.use_separate,
    )


def apply_account_units(units):
    """Apply the account display choice without changing saved geometry/values."""
    global _account_units
    _account_units = units
    imperial = units == "US"
    for scene in bpy.data.scenes:
        configure_scene_units(scene)
        scene.unit_settings.system = "IMPERIAL" if imperial else "METRIC"
        scene.unit_settings.length_unit = "INCHES" if imperial else "MILLIMETERS"


@persistent
def _initialize_scene_units(_unused=None):
    for scene in bpy.data.scenes:
        configure_scene_units(scene)
    if _account_units_callback is not None:
        _account_units_callback()
    return None


def register_scene_units(account_units_callback=None):
    global _account_units_callback
    unregister_scene_units()
    _account_units_callback = account_units_callback
    bpy.app.handlers.load_post.append(_initialize_scene_units)
    # Registration can run in Blender's restricted context. Defer data writes.
    bpy.app.timers.register(_initialize_scene_units, first_interval=0.0)


def unregister_scene_units():
    global _account_units_callback, _account_units
    _account_units_callback = None
    _account_units = None
    if _initialize_scene_units in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_initialize_scene_units)
    if bpy.app.timers.is_registered(_initialize_scene_units):
        bpy.app.timers.unregister(_initialize_scene_units)
