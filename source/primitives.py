import bpy  # type: ignore

from functools import wraps


MOLD_BODY_CYLINDER_VERTICES = 64


def return_created_object(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        before = set(bpy.context.scene.objects)
        func(*args, **kwargs)
        after = set(bpy.context.scene.objects)

        new_objects = after - before
        if not new_objects:
            return None

        # If only one object was created (most primitives)
        if len(new_objects) == 1:
            return new_objects.pop()

        # Fallback: return all created objects
        return list(new_objects)

    return wrapper


@return_created_object
def create_cylinder_primitive(
    radius: float,
    height: float,
    vertices: int | None = None,
):
    kwargs = {
        "radius": radius,
        "depth": height,
        "enter_editmode": False,
    }
    if vertices is not None:
        kwargs["vertices"] = max(int(vertices), 3)
    bpy.ops.mesh.primitive_cylinder_add(**kwargs)


@return_created_object
def create_circle_primitive(radius: float, vertices: int | None = None):
    kwargs = {"radius": radius, "enter_editmode": False}
    if vertices is not None:
        kwargs["vertices"] = vertices
    bpy.ops.mesh.primitive_circle_add(**kwargs)


@return_created_object
def create_cube_primitive(size: float):
    bpy.ops.mesh.primitive_cube_add(size=size)


@return_created_object
def create_plane_primitive():
    bpy.ops.mesh.primitive_plane_add(
        enter_editmode=False, align="WORLD", location=(0, 0, 0), scale=(1, 1, 1)
    )


@return_created_object
def create_uv_sphere_primitive(radius: float):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius)


@return_created_object
def create_text_object(
    text: str,
    size: float,
    location: tuple[float, float, float] = (0, 0, 0),
    height: float = 20,
) -> bpy.types.Object:
    bpy.ops.object.text_add(enter_editmode=False, location=location)
    text_object = bpy.context.object
    text_object.data.body = text
    text_object.data.size = size
    text_object.data.extrude = height / 2  # it is extruded in both directions
    bpy.ops.object.select_all(action="DESELECT")
    text_object.select_set(True)
    bpy.context.view_layer.objects.active = text_object
    bpy.ops.object.convert(target="MESH")
