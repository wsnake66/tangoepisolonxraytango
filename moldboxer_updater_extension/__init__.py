def register():
    import bpy  # type: ignore
    from .updater import CLASSES, register_runtime

    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_runtime()


def unregister():
    import bpy  # type: ignore
    from .updater import CLASSES, unregister_runtime

    unregister_runtime()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
