"""Protect Boolean construction before Blender can evaluate a live modifier."""

import bpy


def boolean_inputs_are_empty(obj, target, *, index_first=True):
    """Check the meshes that the new Boolean will actually receive."""
    if index_first and len(obj.data.vertices) != 0:
        return False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    input_mesh = obj.data if index_first else obj.evaluated_get(depsgraph).data
    return (len(input_mesh.vertices) == 0
            and len(target.evaluated_get(depsgraph).data.vertices) == 0)


def safe_boolean_properties(obj, target, properties, *, index_first=True):
    """Validate operands and avoid Blender 5.0.1's empty material-transfer crash.

    Inspect input geometry before creating the modifier: earlier modifiers can
    empty a mesh, but do not affect a Boolean inserted first. Keep transfer for every non-empty
    result, and never mutate shared Modifier configuration dictionaries.
    """
    for operand in (obj, target):
        try:
            live = bpy.data.objects.get(operand.name)
            valid = (
                live is not None
                and live.as_pointer() == operand.as_pointer()
                and operand.type == "MESH"
                and operand.data is not None
            )
        except (AttributeError, ReferenceError, RuntimeError):
            valid = False
        if not valid:
            raise ValueError("Boolean requires two live mesh objects")
    if obj == target:
        raise ValueError("Boolean target must be different from its operand")

    if (
        properties.get("solver") != "MANIFOLD"
        or properties.get("material_mode", "INDEX") != "TRANSFER"
    ):
        return properties

    if boolean_inputs_are_empty(obj, target, index_first=index_first):
        return {**properties, "material_mode": "INDEX"}
    return properties
