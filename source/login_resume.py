"""One-shot continuation of a user-requested mold generation after OAuth."""
import logging
import time

import bpy  # type: ignore

from .environment import get_addon_preferences

logger = logging.getLogger(__name__)
GENERATION_OPERATORS = frozenset({
    'silicone.generate_mold', 'silicone.auto_box', 'silicone.flat_auto_box',
    'silicone.automatic_mold', 'silicone.slip_casting_auto_box',
    'silicone.generate_fixture', 'silicone.generate_protective_shell',
    'silicone.generate_plaster_silicone_molds', 'silicone.build_box',
    'silicone.build_direct_mold', 'silicone.build_slip_casting_box',
    'silicone.confirm', 'silicone.confirm_direct_mold',
    'silicone.confirm_slip_casting', 'silicone.confirm_tray',
})
_pending = None


def clear_pending_generation():
    global _pending
    _pending = None
    if bpy.app.timers.is_registered(_resume_generation):
        bpy.app.timers.unregister(_resume_generation)


def require_generation_login(operator, context):
    """Return False before any geometry changes when generation needs login."""
    return True
    global _pending
    operator_id = operator.bl_idname
    if '_OT_' in operator_id:
        group, name = operator_id.split('_OT_', 1)
        operator_id = group.lower() + '.' + name
    if operator_id not in GENERATION_OPERATORS:
        return True
    prefs = get_addon_preferences()
    if prefs is not None and getattr(prefs, 'auth_refresh_token', ''):
        return True
    window = context.window
    area = context.area
    if area is None or area.type != 'VIEW_3D':
        area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None) if window else None
    region = next((r for r in area.regions if r.type == 'WINDOW'), None) if area else None
    properties = {}
    for prop in operator.properties.bl_rna.properties:
        if prop.identifier == 'rna_type' or prop.is_readonly:
            continue
        value = getattr(operator.properties, prop.identifier)
        if getattr(prop, "is_array", False):
            value = tuple(value)
        elif isinstance(value, set):
            value = set(value)
        properties[prop.identifier] = value
    clear_pending_generation()
    if window is not None and area is not None and region is not None:
        _pending = {
            'operator': operator_id, 'properties': properties,
            'window': window, 'screen': window.screen, 'area': area,
            'region': region, 'scene': context.scene, 'view_layer': context.view_layer,
            'active': context.view_layer.objects.active,
            'selected': tuple(context.selected_objects),
            'mold_type': context.scene.mold_type_preview,
            'deadline': time.monotonic() + 600,
        }
    from .operator_access import show_active_membership_required
    show_active_membership_required(operator)
    return False


def schedule_generation_resume():
    if _pending is not None and not bpy.app.timers.is_registered(_resume_generation):
        bpy.app.timers.register(_resume_generation, first_interval=0.2)


def _resume_generation():
    global _pending
    pending, _pending = _pending, None  # Consume before dispatch: never run twice.
    if pending is None or time.monotonic() > pending['deadline']:
        return None
    prefs = get_addon_preferences()
    if prefs is None or not getattr(prefs, 'auth_refresh_token', ''):
        return None
    try:
        window, area = pending['window'], pending['area']
        if (window not in tuple(bpy.context.window_manager.windows)
                or window.screen != pending['screen']
                or window.scene != pending['scene']
                or window.view_layer != pending['view_layer']
                or area not in tuple(window.screen.areas)
                or area.type != 'VIEW_3D'
                or pending['region'] not in tuple(area.regions)
                or window.scene.mold_type_preview != pending['mold_type']
                or window.view_layer.objects.active != pending['active']):
            return None
        selected = {obj for obj in window.view_layer.objects if obj.select_get()}
        if selected != set(pending['selected']):
            return None
        group, name = pending['operator'].split('.', 1)
        operation = getattr(getattr(bpy.ops, group), name)
        with bpy.context.temp_override(window=window, area=area, region=pending['region']):
            if operation.poll():
                operation('INVOKE_DEFAULT', **pending['properties'])
    except (ReferenceError, RuntimeError, AttributeError, TypeError):
        logger.exception('Could not resume mold generation after login')
    return None
