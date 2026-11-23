"""Development helper for restoring the OBS recording window layout."""

from __future__ import annotations

import ctypes
import platform
import sys


# Captured from the Moldboxer main window on the OBS recording display.
# These are macOS accessibility coordinates and include the native title bar.
RECORDING_WINDOW_X = 57
RECORDING_WINDOW_Y = 1075
RECORDING_WINDOW_WIDTH = 632
RECORDING_WINDOW_HEIGHT = 848
# Cocoa uses a bottom-left origin; this is the same captured placement in the
# native NSWindow coordinate space.
RECORDING_WINDOW_COCOA_Y = 1165
_NS_WINDOW_STYLE_MASK_FULLSCREEN = 1 << 14


class _NSPoint(ctypes.Structure):
    _fields_ = (("x", ctypes.c_double), ("y", ctypes.c_double))


class _NSSize(ctypes.Structure):
    _fields_ = (("width", ctypes.c_double), ("height", ctypes.c_double))


class _NSRect(ctypes.Structure):
    _fields_ = (("origin", _NSPoint), ("size", _NSSize))


def _objc_runtime():
    appkit = ctypes.CDLL(
        "/System/Library/Frameworks/AppKit.framework/AppKit"
    )
    runtime = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
    runtime.objc_getClass.argtypes = (ctypes.c_char_p,)
    runtime.objc_getClass.restype = ctypes.c_void_p
    runtime.sel_registerName.argtypes = (ctypes.c_char_p,)
    runtime.sel_registerName.restype = ctypes.c_void_p
    return appkit, runtime


def _selector(runtime, name: str):
    return runtime.sel_registerName(name.encode("ascii"))


def _objc_message(runtime, restype, *argument_types):
    signature = ctypes.CFUNCTYPE(
        restype,
        ctypes.c_void_p,
        ctypes.c_void_p,
        *argument_types,
    )
    return signature(("objc_msgSend", runtime))


def _main_macos_window():
    _appkit, runtime = _objc_runtime()
    application_class = runtime.objc_getClass(b"NSApplication")
    send_object = _objc_message(runtime, ctypes.c_void_p)
    application = send_object(
        application_class,
        _selector(runtime, "sharedApplication"),
    )
    window = send_object(application, _selector(runtime, "mainWindow"))
    if not window:
        window = send_object(application, _selector(runtime, "keyWindow"))
    if not window:
        raise RuntimeError("Could not find the Moldboxer main window")
    return runtime, window


def _macos_window_frame(runtime, window) -> _NSRect:
    if platform.machine() == "x86_64":
        frame = _NSRect()
        signature = ctypes.CFUNCTYPE(
            None,
            ctypes.POINTER(_NSRect),
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        get_frame = signature(("objc_msgSend_stret", runtime))
        get_frame(ctypes.byref(frame), window, _selector(runtime, "frame"))
        return frame
    get_frame = _objc_message(runtime, _NSRect)
    return get_frame(window, _selector(runtime, "frame"))


def current_macos_window_frame() -> tuple[int, int, int, int]:
    """Return the native Cocoa frame as x, y, width, height."""

    runtime, window = _main_macos_window()
    frame = _macos_window_frame(runtime, window)
    return (
        round(frame.origin.x),
        round(frame.origin.y),
        round(frame.size.width),
        round(frame.size.height),
    )


def _macos_window_is_fullscreen(runtime, window) -> bool:
    get_style_mask = _objc_message(runtime, ctypes.c_ulong)
    style_mask = get_style_mask(window, _selector(runtime, "styleMask"))
    return bool(style_mask & _NS_WINDOW_STYLE_MASK_FULLSCREEN)


def _toggle_macos_window_fullscreen(runtime, window) -> None:
    toggle = _objc_message(runtime, None, ctypes.c_void_p)
    toggle(window, _selector(runtime, "toggleFullScreen:"), None)


def _apply_macos_recording_frame() -> tuple[int, int, int, int]:
    runtime, window = _main_macos_window()
    target_frame = _NSRect(
        _NSPoint(RECORDING_WINDOW_X, RECORDING_WINDOW_COCOA_Y),
        _NSSize(RECORDING_WINDOW_WIDTH, RECORDING_WINDOW_HEIGHT),
    )
    set_frame = _objc_message(
        runtime,
        None,
        _NSRect,
        ctypes.c_bool,
        ctypes.c_bool,
    )
    set_frame(
        window,
        _selector(runtime, "setFrame:display:animate:"),
        target_frame,
        True,
        False,
    )

    actual = current_macos_window_frame()
    expected = (
        RECORDING_WINDOW_X,
        RECORDING_WINDOW_COCOA_Y,
        RECORDING_WINDOW_WIDTH,
        RECORDING_WINDOW_HEIGHT,
    )
    if actual != expected:
        raise RuntimeError(
            "Moldboxer reported an unexpected native window frame: "
            f"expected {expected}, got {actual}"
        )
    return recording_window_geometry()


def recording_window_geometry() -> tuple[int, int, int, int]:
    """Return the target outer-frame geometry as x, y, width, height."""

    return (
        RECORDING_WINDOW_X,
        RECORDING_WINDOW_Y,
        RECORDING_WINDOW_WIDTH,
        RECORDING_WINDOW_HEIGHT,
    )


def _exit_blender_area_fullscreen(context) -> bool:
    """Leave Blender's maximized-area mode when the active screen uses it."""

    screen = getattr(context, "screen", None)
    if not bool(getattr(screen, "show_fullscreen", False)):
        return False

    import bpy  # type: ignore

    result = bpy.ops.screen.screen_full_area()
    if "FINISHED" not in result:
        raise RuntimeError("Could not exit Blender fullscreen-area mode")
    return True


def _restore_macos_window_frame() -> tuple[int, int, int, int]:
    """Exit native fullscreen and restore the main window's outer frame."""

    runtime, window = _main_macos_window()
    if not _macos_window_is_fullscreen(runtime, window):
        return _apply_macos_recording_frame()

    _toggle_macos_window_fullscreen(runtime, window)

    import bpy  # type: ignore

    attempts_remaining = 120

    def apply_after_fullscreen_transition():
        nonlocal attempts_remaining
        runtime, window = _main_macos_window()
        if _macos_window_is_fullscreen(runtime, window):
            attempts_remaining -= 1
            if attempts_remaining <= 0:
                return None
            return 0.05
        _apply_macos_recording_frame()
        return None

    bpy.app.timers.register(
        apply_after_fullscreen_transition,
        first_interval=0.05,
    )
    return recording_window_geometry()


def restore_recording_window_layout(context) -> tuple[int, int, int, int]:
    """Restore the captured OBS layout for the active Moldboxer main window."""

    if sys.platform != "darwin":
        raise RuntimeError("The saved OBS window layout is currently macOS-only")

    _exit_blender_area_fullscreen(context)
    return _restore_macos_window_frame()
