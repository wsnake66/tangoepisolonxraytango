import logging
import os
from contextlib import contextmanager
import time
from weakref import WeakSet

import bpy  # type: ignore

logger = logging.getLogger(__name__)

# Construction objects can outlive a single operation (or its Boolean target).
# Keep them out of every refresh, including worker waits and cleanup retries.
_hidden_during_redraw = WeakSet()


@contextmanager
def _hide_construction_objects():
    states = {}
    try:
        for wrapper in list(_hidden_during_redraw):
            try:
                raw = wrapper.object
                if raw in states:
                    continue
                states[raw] = (raw.hide_get(), raw.hide_viewport, raw.hide_render)
                raw.hide_set(True)
                raw.hide_viewport = True
                raw.hide_render = True
            except ReferenceError:
                continue
        yield
    finally:
        for raw, (hidden, viewport, render) in states.items():
            try:
                raw.hide_set(hidden)
                raw.hide_viewport = viewport
                raw.hide_render = render
            except ReferenceError:
                pass


@contextmanager
def _suppress_native_output():
    """Temporarily silence native stdout/stderr writes from Blender operators."""
    saved_fds = []
    try:
        with open(os.devnull, "w") as devnull:
            for fd in (1, 2):
                try:
                    saved_fd = os.dup(fd)
                    os.dup2(devnull.fileno(), fd)
                    saved_fds.append((fd, saved_fd))
                except OSError:
                    continue
            yield
    finally:
        for fd, saved_fd in reversed(saved_fds):
            try:
                os.dup2(saved_fd, fd)
            finally:
                os.close(saved_fd)


def _hide_base_substracter_before_redraw() -> None:
    try:
        from .components.base_substracter_visibility import set_base_substracter_hidden

        set_base_substracter_hidden(True)
    except Exception:
        logger.debug("Could not hide base substracter before redraw", exc_info=True)


def hide_split_key_wrappers() -> None:
    """Keep internal key-placement envelopes out of the viewport and renders."""
    for obj in bpy.data.objects:
        if (obj.name.startswith("box_slip_casting_half_wrapper")
                or obj.get("moldboxer_slip_casting_half_box_wrapper", False)):
            obj.hide_set(True)
            obj.hide_render = True


def tag_viewport_redraw(context=None) -> None:
    _hide_base_substracter_before_redraw()
    hide_split_key_wrappers()
    context = context or bpy.context
    view_layer = getattr(context, "view_layer", None)
    if view_layer is not None:
        view_layer.update()

    window_manager = getattr(context, "window_manager", None)
    windows = getattr(window_manager, "windows", None) or []
    for window in windows:
        screen = getattr(window, "screen", None)
        if screen is None:
            continue
        for area in getattr(screen, "areas", []):
            area.tag_redraw()


def force_viewport_redraw(context=None) -> None:
    with _hide_construction_objects():
        _force_viewport_redraw(context)


def _force_viewport_redraw(context=None) -> None:
    tag_viewport_redraw(context)
    try:
        redraw_timer = bpy.ops.wm.redraw_timer
        if redraw_timer.poll():
            with _suppress_native_output():
                redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except Exception:
        logger.debug("Could not force viewport redraw", exc_info=True)


def breathe_viewport(context=None) -> None:
    """Give Blender a small UI refresh point around long main-thread work."""
    force_viewport_redraw(context)
    time.sleep(0)
