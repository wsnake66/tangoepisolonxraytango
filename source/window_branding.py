import ctypes
import ctypes.util
import logging
import os
import platform
from ctypes import wintypes
from pathlib import Path

import bpy  # type: ignore

from .bl_utils import ensure_moldboxer_background
from .constants import WINDOWS_APP_USER_MODEL_ID


logger = logging.getLogger(__name__)

MOLDBOXER_APP_NAME = "Moldboxer"
_WINDOW_BRANDING_INTERVAL_SECONDS = 0.5
_WINDOW_BRANDING_FIRST_INTERVAL_SECONDS = 0.1
_WINDOW_BRANDING_MAX_RUNS = 120
_WINDOW_ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
_WINDOWS_ICON_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "logo_ico_v2.ico"
)

_cached_icon_pixels = None
_windows_small_icon_handle = None
_windows_big_icon_handle = None
_windows_icon_handles_by_size = {}
_linux_branding_warning_logged = False
_window_branding_runs = 0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT_LPWSTR(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("pwsz_val", ctypes.c_wchar_p),
    ]


def _guid(value: str):
    result = _GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(value), ctypes.byref(result))
    return result


_APPUSERMODEL_FMTID = None
_PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE = None
_PKEY_APPUSERMODEL_ID = None
if platform.system() == "Windows" and getattr(ctypes, "windll", None) is not None:
    try:
        _APPUSERMODEL_FMTID = _guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        _PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE = _PROPERTYKEY(
            _APPUSERMODEL_FMTID, 4
        )
        _PKEY_APPUSERMODEL_ID = _PROPERTYKEY(_APPUSERMODEL_FMTID, 5)
    except Exception:
        _APPUSERMODEL_FMTID = None
        _PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE = None
        _PKEY_APPUSERMODEL_ID = None


def set_windows_app_user_model_id() -> None:
    if platform.system() != "Windows":
        return

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return

    shell32 = getattr(windll, "shell32", None)
    if shell32 is None:
        return

    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(
            ctypes.c_wchar_p(WINDOWS_APP_USER_MODEL_ID)
        )
    except Exception:
        logger.debug("Could not set Windows app user model id", exc_info=True)


def _save_user_preferences() -> bool:
    save_pref_op = getattr(bpy.ops.wm, "save_userpref", None)
    if save_pref_op is None:
        return False

    for op_args in (("EXEC_DEFAULT",), ("INVOKE_DEFAULT",), tuple()):
        try:
            result = save_pref_op(*op_args)
            return "FINISHED" in result
        except Exception:
            continue
    return False


def _disable_blender_splash_for_future_starts() -> None:
    preferences = getattr(bpy.context, "preferences", None)
    view = getattr(preferences, "view", None)
    if view is None or not hasattr(view, "show_splash"):
        return

    try:
        if bool(view.show_splash):
            view.show_splash = False
            _save_user_preferences()
    except Exception:
        logger.debug("Could not update Blender splash preference", exc_info=True)


def _load_icon_pixel_data():
    global _cached_icon_pixels

    if _cached_icon_pixels is not None:
        return _cached_icon_pixels

    if not _WINDOW_ICON_PATH.is_file():
        return None

    image = None
    try:
        image = bpy.data.images.load(str(_WINDOW_ICON_PATH), check_existing=True)
        width, height = image.size[:2]
        if width <= 0 or height <= 0:
            return None

        rgba = list(image.pixels[:])
        pixels = []
        for index in range(0, len(rgba), 4):
            red = max(0, min(255, round(rgba[index] * 255.0)))
            green = max(0, min(255, round(rgba[index + 1] * 255.0)))
            blue = max(0, min(255, round(rgba[index + 2] * 255.0)))
            alpha = max(0, min(255, round(rgba[index + 3] * 255.0)))
            pixels.append((alpha << 24) | (red << 16) | (green << 8) | blue)

        _cached_icon_pixels = (width, height, pixels)
        return _cached_icon_pixels
    except Exception:
        logger.debug("Could not load Moldboxer icon pixels", exc_info=True)
        return None


def _ensure_moldboxer_visuals() -> None:
    if getattr(bpy.app, "background", False):
        return

    context = getattr(bpy, "context", None)
    if context is None or getattr(context, "window_manager", None) is None:
        return

    try:
        ensure_moldboxer_background(context)
    except Exception:
        logger.debug("Could not apply Moldboxer viewport visuals", exc_info=True)


def _find_windows_launcher_icon_resource() -> str | None:
    for parent in Path(__file__).resolve().parents:
        launcher = parent / "Moldboxer.exe"
        if launcher.is_file():
            return f"{launcher},0"
    return None


def _set_window_property_string(hwnd, key, value: str | None) -> None:
    if key is None or not value:
        return

    try:
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass

    shell32 = ctypes.windll.shell32
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long

    iid_property_store = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    store = ctypes.c_void_p()
    if shell32.SHGetPropertyStoreForWindow(
        hwnd, ctypes.byref(iid_property_store), ctypes.byref(store)
    ) != 0 or not store.value:
        return

    vtable = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    set_value = ctypes.WINFUNCTYPE(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(_PROPERTYKEY),
        ctypes.POINTER(_PROPVARIANT_LPWSTR),
    )(vtable[6])
    commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])

    variant = _PROPVARIANT_LPWSTR()
    variant.vt = 31  # VT_LPWSTR
    variant.pwsz_val = value
    try:
        set_value(store, ctypes.byref(key), ctypes.byref(variant))
        commit(store)
    finally:
        release(store)


def _load_windows_icon(size: int):
    if not _WINDOWS_ICON_PATH.is_file():
        return None
    try:
        shared_handles = bpy.app.driver_namespace.setdefault(
            "_moldboxer_windows_icon_handles_by_size", {}
        )
        if size in shared_handles:
            return shared_handles[size]
    except Exception:
        shared_handles = None

    if size in _windows_icon_handles_by_size:
        return _windows_icon_handles_by_size[size]

    try:
        user32 = ctypes.windll.user32
        image_icon = 1
        load_from_file = 0x00000010
        handle = user32.LoadImageW(
            None,
            str(_WINDOWS_ICON_PATH),
            image_icon,
            size,
            size,
            load_from_file,
        )
        if handle:
            _windows_icon_handles_by_size[size] = handle
            if shared_handles is not None:
                try:
                    shared_handles[size] = handle
                except Exception:
                    pass
        return handle
    except Exception:
        logger.debug("Could not load Windows icon", exc_info=True)
        return None


def _get_windows_titlebar_icon_size(hwnd) -> int:
    user32 = ctypes.windll.user32
    try:
        get_dpi_for_window = user32.GetDpiForWindow
        get_dpi_for_window.argtypes = [wintypes.HWND]
        get_dpi_for_window.restype = wintypes.UINT
        dpi = get_dpi_for_window(hwnd)
        if dpi:
            return max(24, round(16 * dpi / 96))
    except Exception:
        pass

    try:
        sm_cxsmicon = 49
        size = user32.GetSystemMetrics(sm_cxsmicon)
        if size:
            return max(24, size)
    except Exception:
        pass
    return 24


def _apply_windows_branding() -> None:
    global _windows_small_icon_handle, _windows_big_icon_handle

    user32 = ctypes.windll.user32
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.restype = wintypes.BOOL
    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.SetWindowTextW.restype = wintypes.BOOL
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_size_t,
        ctypes.c_void_p,
    ]
    user32.SendMessageW.restype = ctypes.c_void_p
    if hasattr(user32, "SetClassLongPtrW"):
        user32.GetClassLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
        ]
        user32.GetClassLongPtrW.restype = ctypes.c_void_p
        user32.SetClassLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        user32.SetClassLongPtrW.restype = ctypes.c_void_p

    set_windows_app_user_model_id()

    top_level_windows = []
    current_pid = os.getpid()

    enum_proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p
    )

    def _collect_window(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == current_pid and user32.IsWindowVisible(hwnd):
            top_level_windows.append(hwnd)
        return 1

    user32.EnumWindows(enum_proc_type(_collect_window), 0)
    if not top_level_windows:
        return

    for hwnd in top_level_windows:
        try:
            user32.SetWindowTextW(hwnd, MOLDBOXER_APP_NAME)
        except Exception:
            logger.debug("Could not set Windows window title", exc_info=True)

        try:
            _set_window_property_string(
                hwnd, _PKEY_APPUSERMODEL_ID, WINDOWS_APP_USER_MODEL_ID
            )
            _set_window_property_string(
                hwnd,
                _PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE,
                _find_windows_launcher_icon_resource(),
            )
        except Exception:
            logger.debug("Could not set Windows taskbar properties", exc_info=True)

    if _windows_small_icon_handle is None:
        _windows_small_icon_handle = _load_windows_icon(16)
    if _windows_big_icon_handle is None:
        _windows_big_icon_handle = (
            _load_windows_icon(256) or _load_windows_icon(48) or _load_windows_icon(32)
        )

    if _windows_small_icon_handle is None and _windows_big_icon_handle is None:
        return

    # Keep a fallback default-size icon for Windows shells that prefer class icons.
    class_icon_handle = _windows_big_icon_handle or _windows_small_icon_handle
    if class_icon_handle is None and _WINDOWS_ICON_PATH.is_file():
        try:
            image_icon = 1
            load_from_file = 0x00000010
            default_size = 0x00000040
            class_icon_handle = user32.LoadImageW(
                None,
                str(_WINDOWS_ICON_PATH),
                image_icon,
                0,
                0,
                load_from_file | default_size,
            )
        except Exception:
            logger.debug("Could not load Windows icon", exc_info=True)

    wm_seticon = 0x0080
    wm_geticon = 0x007F
    icon_small = 0
    icon_big = 1
    gclp_hicon = -14
    gclp_hiconsm = -34

    for hwnd in top_level_windows:
        try:
            window_small_icon_handle = (
                _load_windows_icon(_get_windows_titlebar_icon_size(hwnd))
                or _windows_small_icon_handle
            )
            if window_small_icon_handle:
                if (
                    user32.SendMessageW(hwnd, wm_geticon, icon_small, None)
                    != window_small_icon_handle
                ):
                    user32.SendMessageW(
                        hwnd, wm_seticon, icon_small, window_small_icon_handle
                    )
            if _windows_big_icon_handle:
                if (
                    user32.SendMessageW(hwnd, wm_geticon, icon_big, None)
                    != _windows_big_icon_handle
                ):
                    user32.SendMessageW(
                        hwnd, wm_seticon, icon_big, _windows_big_icon_handle
                    )
            if hasattr(user32, "SetClassLongPtrW"):
                big_class_icon = _windows_big_icon_handle or class_icon_handle
                small_class_icon = window_small_icon_handle or class_icon_handle
                if (
                    big_class_icon
                    and user32.GetClassLongPtrW(hwnd, gclp_hicon) != big_class_icon
                ):
                    user32.SetClassLongPtrW(
                        hwnd, gclp_hicon, big_class_icon
                    )
                if (
                    small_class_icon
                    and user32.GetClassLongPtrW(hwnd, gclp_hiconsm) != small_class_icon
                ):
                    user32.SetClassLongPtrW(
                        hwnd,
                        gclp_hiconsm,
                        small_class_icon,
                    )
        except Exception:
            logger.debug("Could not set Windows window icon", exc_info=True)


def _apply_linux_branding() -> None:
    global _linux_branding_warning_logged

    # Raw X11 window enumeration/property updates are brittle under Blender on Linux
    # and can raise fatal BadWindow/X_GetProperty errors on some X11/XWayland setups.
    # Keep Linux branding opt-in so the addon stays stable by default.
    if os.environ.get("MOLDBOXER_ENABLE_LINUX_WINDOW_BRANDING") != "1":
        if not _linux_branding_warning_logged:
            logger.debug(
                "Skipping Linux native window branding. Set "
                "MOLDBOXER_ENABLE_LINUX_WINDOW_BRANDING=1 to re-enable it."
            )
            _linux_branding_warning_logged = True
        return

    x11_path = ctypes.util.find_library("X11")
    if not x11_path:
        return

    icon_pixels = _load_icon_pixel_data()
    if icon_pixels is None:
        return

    try:
        x11 = ctypes.cdll.LoadLibrary(x11_path)
    except OSError:
        return

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XDefaultScreen.restype = ctypes.c_int
    x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XRootWindow.restype = ctypes.c_ulong
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XQueryTree.restype = ctypes.c_int
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    x11.XGetWindowProperty.restype = ctypes.c_int
    x11.XChangeProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    x11.XChangeProperty.restype = ctypes.c_int
    x11.XStoreName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
    x11.XStoreName.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XFlush.restype = ctypes.c_int
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XFree.restype = ctypes.c_int
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.restype = ctypes.c_int

    display = x11.XOpenDisplay(None)
    if not display:
        return

    try:
        current_pid = os.getpid()
        root = x11.XRootWindow(display, x11.XDefaultScreen(display))
        root_return = ctypes.c_ulong()
        parent_return = ctypes.c_ulong()
        children_return = ctypes.POINTER(ctypes.c_ulong)()
        child_count = ctypes.c_uint()

        if not x11.XQueryTree(
            display,
            root,
            ctypes.byref(root_return),
            ctypes.byref(parent_return),
            ctypes.byref(children_return),
            ctypes.byref(child_count),
        ):
            return

        try:
            net_wm_pid = x11.XInternAtom(display, b"_NET_WM_PID", 0)
            net_wm_name = x11.XInternAtom(display, b"_NET_WM_NAME", 0)
            net_wm_icon = x11.XInternAtom(display, b"_NET_WM_ICON", 0)
            utf8_string = x11.XInternAtom(display, b"UTF8_STRING", 0)
            cardinal = x11.XInternAtom(display, b"CARDINAL", 0)
            title_bytes = MOLDBOXER_APP_NAME.encode("utf-8")
            width, height, pixels = icon_pixels
            icon_data = (ctypes.c_uint32 * (2 + len(pixels)))()
            icon_data[0] = width
            icon_data[1] = height
            for index, pixel in enumerate(pixels, start=2):
                icon_data[index] = pixel

            for index in range(child_count.value):
                window_id = children_return[index]
                actual_type = ctypes.c_ulong()
                actual_format = ctypes.c_int()
                items = ctypes.c_ulong()
                bytes_after = ctypes.c_ulong()
                property_data = ctypes.c_void_p()

                status = x11.XGetWindowProperty(
                    display,
                    window_id,
                    net_wm_pid,
                    0,
                    1,
                    0,
                    cardinal,
                    ctypes.byref(actual_type),
                    ctypes.byref(actual_format),
                    ctypes.byref(items),
                    ctypes.byref(bytes_after),
                    ctypes.byref(property_data),
                )
                if status != 0 or not property_data or items.value == 0:
                    if property_data:
                        x11.XFree(property_data)
                    continue

                try:
                    pid_value = ctypes.cast(
                        property_data, ctypes.POINTER(ctypes.c_ulong)
                    )[0]
                finally:
                    x11.XFree(property_data)

                if pid_value != current_pid:
                    continue

                x11.XChangeProperty(
                    display,
                    window_id,
                    net_wm_name,
                    utf8_string,
                    8,
                    0,
                    ctypes.c_char_p(title_bytes),
                    len(title_bytes),
                )
                x11.XChangeProperty(
                    display,
                    window_id,
                    net_wm_icon,
                    cardinal,
                    32,
                    0,
                    ctypes.cast(icon_data, ctypes.c_void_p),
                    len(icon_data),
                )
                x11.XStoreName(display, window_id, title_bytes)

            x11.XFlush(display)
        finally:
            if children_return:
                x11.XFree(children_return)
    except Exception:
        logger.debug("Could not apply Linux window branding", exc_info=True)
    finally:
        x11.XCloseDisplay(display)


def _objc_selector(objc_runtime, name: str):
    objc_runtime.sel_registerName.restype = ctypes.c_void_p
    return objc_runtime.sel_registerName(name.encode("utf-8"))


def _objc_send(
    objc_runtime,
    receiver,
    selector: str,
    restype=ctypes.c_void_p,
    argtypes=None,
    *args,
):
    argtypes = argtypes or []
    msg_send = objc_runtime.objc_msgSend
    msg_send.restype = restype
    msg_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
    return msg_send(receiver, _objc_selector(objc_runtime, selector), *args)


def _objc_nsstring(objc_runtime, text: str):
    nsstring_class = objc_runtime.objc_getClass(b"NSString")
    allocated = _objc_send(objc_runtime, nsstring_class, "alloc")
    return _objc_send(
        objc_runtime,
        allocated,
        "initWithUTF8String:",
        ctypes.c_void_p,
        [ctypes.c_char_p],
        text.encode("utf-8"),
    )


def _apply_macos_branding() -> None:
    objc_path = ctypes.util.find_library("objc")
    appkit_path = ctypes.util.find_library("AppKit")
    if not objc_path or not appkit_path:
        return

    try:
        ctypes.cdll.LoadLibrary(appkit_path)
        objc = ctypes.cdll.LoadLibrary(objc_path)
    except OSError:
        return

    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]

    try:
        nsapplication = objc.objc_getClass(b"NSApplication")
        app = _objc_send(objc, nsapplication, "sharedApplication")
        if not app:
            return

        process_info_class = objc.objc_getClass(b"NSProcessInfo")
        process_info = _objc_send(objc, process_info_class, "processInfo")
        title_ns = _objc_nsstring(objc, MOLDBOXER_APP_NAME)

        if process_info and title_ns:
            _objc_send(
                objc,
                process_info,
                "setProcessName:",
                ctypes.c_void_p,
                [ctypes.c_void_p],
                title_ns,
            )

        windows = _objc_send(objc, app, "windows")
        window_count = (
            _objc_send(objc, windows, "count", ctypes.c_ulonglong) if windows else 0
        )

        for index in range(window_count):
            window = _objc_send(
                objc,
                windows,
                "objectAtIndex:",
                ctypes.c_void_p,
                [ctypes.c_ulonglong],
                index,
            )
            if not window or not title_ns:
                continue
            _objc_send(
                objc,
                window,
                "setTitle:",
                ctypes.c_void_p,
                [ctypes.c_void_p],
                title_ns,
            )

        if _WINDOW_ICON_PATH.is_file():
            nsimage_class = objc.objc_getClass(b"NSImage")
            image_path_ns = _objc_nsstring(objc, str(_WINDOW_ICON_PATH))
            image = _objc_send(objc, nsimage_class, "alloc")
            image = _objc_send(
                objc,
                image,
                "initWithContentsOfFile:",
                ctypes.c_void_p,
                [ctypes.c_void_p],
                image_path_ns,
            )
            if image:
                _objc_send(
                    objc,
                    app,
                    "setApplicationIconImage:",
                    ctypes.c_void_p,
                    [ctypes.c_void_p],
                    image,
                )
    except Exception:
        logger.debug("Could not apply macOS window branding", exc_info=True)


def apply_native_window_branding() -> None:
    if getattr(bpy.app, "background", False):
        return

    system = platform.system()
    if system == "Windows":
        _apply_windows_branding()
        return
    if system == "Darwin":
        _apply_macos_branding()
        return
    if system == "Linux":
        _apply_linux_branding()


def _window_branding_timer():
    global _window_branding_runs

    _window_branding_runs += 1
    try:
        _disable_blender_splash_for_future_starts()
        _ensure_moldboxer_visuals()
        apply_native_window_branding()
    except Exception:
        logger.debug("Could not refresh Moldboxer window branding", exc_info=True)
    if _window_branding_runs >= _WINDOW_BRANDING_MAX_RUNS:
        return None
    return _WINDOW_BRANDING_INTERVAL_SECONDS


def schedule_window_branding() -> None:
    global _window_branding_runs

    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_window_branding_timer):
        return

    _window_branding_runs = 0
    bpy.app.timers.register(
        _window_branding_timer,
        first_interval=_WINDOW_BRANDING_FIRST_INTERVAL_SECONDS,
    )


def unregister_window_branding() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_window_branding_timer):
        bpy.app.timers.unregister(_window_branding_timer)
