import bpy  # type: ignore


def object_name_matches_base_substracter(obj_name: str) -> bool:
    obj_name = obj_name.lower()
    if obj_name == "base_substracter":
        return True
    if not obj_name.startswith("base_substracter"):
        return False
    return obj_name[len("base_substracter")] in "._-"


def is_base_substracter_object(obj) -> bool:
    return getattr(obj, "type", None) == "MESH" and object_name_matches_base_substracter(
        str(getattr(obj, "name", ""))
    )


def set_object_hidden(obj: bpy.types.Object, hidden: bool) -> None:
    obj.hide_set(hidden)
    obj.hide_viewport = hidden
    obj.hide_render = hidden


def set_base_substracter_hidden(hidden: bool, *, update_view_layer: bool = True) -> None:
    for base_substracter in bpy.data.objects:
        if is_base_substracter_object(base_substracter):
            set_object_hidden(base_substracter, hidden)
    if update_view_layer:
        bpy.context.view_layer.update()
