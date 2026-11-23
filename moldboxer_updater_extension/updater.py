import math
import os
import sys
import time

import bpy  # type: ignore


TARGET_PACKAGE_ID = "moldboxer_silicone"
TARGET_REPO_MODULE = "moldboxer_extensions"
TARGET_REPO_URL = "https://extension.moldboxer.com"

_MONITOR_INTERVAL = 0.25
_MONITOR_TIMEOUT = 15.0 * 60.0
_AUTOMATIC_CHECK_DELAY = 1.0
_AUTOMATIC_CHECK_INTERVAL = 20.0 * 60.0
_OVERLAY_HANDLE = None
_RUNTIME = {
    "phase": "idle",
    "message": "Ready to update Moldboxer",
    "expected_version": "",
    "started_at": 0.0,
    "progress": 0.0,
}


def _normalized_url(value: str) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for component in str(value or "").split("."):
        digits = "".join(character for character in component if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_newer_version(candidate: str, current: str) -> bool:
    if not candidate:
        return False
    if not current:
        return True
    return _version_tuple(candidate) > _version_tuple(current)


def _operator_finished(result) -> bool:
    try:
        return "FINISHED" in result
    except (TypeError, AttributeError):
        return False


def _operator_running_modal(result) -> bool:
    try:
        return "RUNNING_MODAL" in result
    except (TypeError, AttributeError):
        return False


def _manifest_item(manifests, repo_index: int, package_id: str):
    if manifests is None or not 0 <= repo_index < len(manifests):
        return None
    manifest = manifests[repo_index]
    if manifest is None or not hasattr(manifest, "get"):
        return None
    try:
        return manifest.get(package_id)
    except Exception:
        return None


def _item_version(item) -> str:
    return str(getattr(item, "version", "")).strip()


def _repo_matches_target(repo) -> bool:
    module = str(getattr(repo, "module", "")).strip().lower()
    remote_url = _normalized_url(getattr(repo, "remote_url", ""))
    return module == TARGET_REPO_MODULE or remote_url == _normalized_url(TARGET_REPO_URL)


def _is_legacy_local_repo(repo) -> bool:
    source = str(getattr(repo, "source", "")).strip().upper()
    remote_url = _normalized_url(getattr(repo, "remote_url", ""))
    return source == "USER" and not remote_url


def _repo_state():
    try:
        from bl_pkg import repo_cache_store_ensure  # type: ignore
        from bl_pkg.bl_extension_ops import extension_repos_read  # type: ignore

        repos = list(extension_repos_read())
        cache = repo_cache_store_ensure()
        quiet_error = lambda *_args, **_kwargs: None
        local = list(cache.pkg_manifest_from_local_ensure(error_fn=quiet_error))
        remote = list(cache.pkg_manifest_from_remote_ensure(error_fn=quiet_error))
        return repos, local, remote
    except Exception:
        return None


def _target_repo_index(repos, local_all) -> int | None:
    installed_remote_indices = []
    for repo_index, repo in enumerate(repos):
        local_item = _manifest_item(local_all, repo_index, TARGET_PACKAGE_ID)
        if local_item is not None and not _is_legacy_local_repo(repo):
            installed_remote_indices.append(repo_index)

    if installed_remote_indices:
        for repo_index in installed_remote_indices:
            if _repo_matches_target(repos[repo_index]):
                return repo_index
        return installed_remote_indices[0]

    for repo_index, repo in enumerate(repos):
        if _repo_matches_target(repo):
            return repo_index
    return None


def _target_package_state():
    state = _repo_state()
    if state is None:
        return None

    repos, local_all, remote_all = state
    repo_index = _target_repo_index(repos, local_all)
    if repo_index is None:
        return None
    repo = repos[repo_index]
    local_item = _manifest_item(local_all, repo_index, TARGET_PACKAGE_ID)
    remote_item = _manifest_item(remote_all, repo_index, TARGET_PACKAGE_ID)
    return repo_index, repo, local_item, remote_item


def _foreign_package_installs():
    state = _repo_state()
    if state is None:
        return []

    repos, local_all, _remote_all = state
    target_repo_index = _target_repo_index(repos, local_all)
    installs = []
    for repo_index, repo in enumerate(repos):
        if repo_index == target_repo_index:
            continue
        local_item = _manifest_item(local_all, repo_index, TARGET_PACKAGE_ID)
        if local_item is not None:
            installs.append((repo_index, repo, local_item))
    return installs


def _enabled_online_access(preferences) -> tuple[bool, bool]:
    if bool(getattr(bpy.app, "online_access", False)):
        return True, False
    if bool(getattr(bpy.app, "online_access_override", False)):
        return False, False

    candidates = (
        (getattr(preferences, "system", None), "use_online_access"),
        (preferences, "use_online_access"),
    )
    for owner, attribute in candidates:
        if owner is None or not hasattr(owner, attribute):
            continue
        try:
            setattr(owner, attribute, True)
            if bool(getattr(owner, attribute)):
                return True, True
        except Exception:
            continue
    return bool(getattr(bpy.app, "online_access", False)), False


def _sync_target_repository(repo_index: int, repo_directory: str) -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    sync_operator = getattr(extension_ops, "repo_sync", None) if extension_ops else None
    if not callable(sync_operator):
        return False

    kwargs = {"repo_index": repo_index}
    if repo_directory:
        kwargs["repo_directory"] = repo_directory
    for operator_context in (("EXEC_DEFAULT",), tuple()):
        try:
            if _operator_finished(sync_operator(*operator_context, **kwargs)):
                return True
        except Exception:
            continue
    return False


def _uninstall_package(repo_index: int, repo_directory: str) -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    uninstall_operator = (
        getattr(extension_ops, "package_uninstall", None) if extension_ops else None
    )
    if not callable(uninstall_operator):
        return False

    kwargs = {"repo_index": repo_index, "pkg_id": TARGET_PACKAGE_ID}
    if repo_directory:
        kwargs["repo_directory"] = repo_directory
    for operator_context in (("EXEC_DEFAULT",), tuple()):
        try:
            if _operator_finished(uninstall_operator(*operator_context, **kwargs)):
                return True
        except Exception:
            continue
    return False


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _addon_module_name(repo) -> str:
    repo_module = str(getattr(repo, "module", "")).strip()
    if not repo_module:
        return ""
    return f"bl_ext.{repo_module}.{TARGET_PACKAGE_ID}"


def _package_is_enabled(repo) -> bool:
    module_name = _addon_module_name(repo)
    if not module_name:
        return False
    try:
        import addon_utils  # type: ignore

        loaded_default, loaded_state = addon_utils.check(module_name)
        return bool(loaded_default or loaded_state)
    except Exception:
        return False


def _package_has_loaded_binary(repo_directory: str) -> bool:
    """Return whether a Windows-native module from this package is resident."""
    if not repo_directory:
        return False

    repo_directory = os.path.normcase(os.path.abspath(repo_directory))
    package_id = TARGET_PACKAGE_ID.lower()
    for module in tuple(sys.modules.values()):
        module_path = str(getattr(module, "__file__", "") or "")
        if not module_path.lower().endswith((".pyd", ".dll")):
            continue
        module_path = os.path.normcase(os.path.abspath(module_path))
        try:
            if os.path.commonpath((repo_directory, module_path)) != repo_directory:
                continue
            relative_path = os.path.relpath(module_path, repo_directory)
        except (OSError, ValueError):
            continue
        package_directory = relative_path.split(os.sep, 1)[0].lower()
        if package_id in package_directory:
            return True
    return False


def _disable_package_for_restart(repo) -> bool:
    module_name = _addon_module_name(repo)
    if not module_name:
        return False
    try:
        import addon_utils  # type: ignore

        loaded_default, loaded_state = addon_utils.check(module_name)
        if not (loaded_default or loaded_state):
            return True
        errors = []
        addon_utils.disable(
            module_name,
            default_set=True,
            refresh_handled=True,
            handle_error=errors.append,
        )
        loaded_default, loaded_state = addon_utils.check(module_name)
        return not errors and not (loaded_default or loaded_state)
    except Exception:
        return False


def _save_user_preferences() -> bool:
    save_operator = getattr(getattr(bpy.ops, "wm", None), "save_userpref", None)
    if not callable(save_operator):
        return False
    for operator_context in (("EXEC_DEFAULT",), tuple()):
        try:
            if _operator_finished(save_operator(*operator_context)):
                return True
        except Exception:
            continue
    return False


def _stage_windows_restart_if_needed(installs, expected_version: str) -> bool:
    """Disable loaded Windows packages and defer replacement until restart."""
    if not _is_windows():
        return False

    repos = []
    seen_modules = set()
    restart_needed = False
    for _repo_index, repo, _item in installs:
        module_name = _addon_module_name(repo)
        if not module_name or module_name in seen_modules:
            continue
        seen_modules.add(module_name)
        repos.append(repo)
        repo_directory = str(getattr(repo, "directory", ""))
        if _package_is_enabled(repo) or _package_has_loaded_binary(repo_directory):
            restart_needed = True

    if not restart_needed:
        return False

    for repo in repos:
        if not _package_is_enabled(repo):
            continue
        if _disable_package_for_restart(repo):
            continue
        _RUNTIME.update(
            phase="error",
            message=(
                "Could not disable Moldboxer safely. Disable it in Preferences, "
                "save preferences, and restart Blender before updating."
            ),
            progress=0.0,
        )
        _redraw_ui()
        _show_result_popup("Moldboxer Update Paused", _RUNTIME["message"], "ERROR")
        return True

    if not _save_user_preferences():
        _RUNTIME.update(
            phase="error",
            message=(
                "Moldboxer was disabled, but Blender could not save that setting. "
                "Save Preferences and restart Blender before updating."
            ),
            progress=0.0,
        )
        _redraw_ui()
        _show_result_popup("Moldboxer Update Paused", _RUNTIME["message"], "ERROR")
        return True

    version_suffix = f" {expected_version}" if expected_version else ""
    _RUNTIME.update(
        phase="restart_required",
        message=(
            f"Moldboxer{version_suffix} is ready — save your work and restart Blender"
        ),
        expected_version=expected_version,
        progress=0.0,
    )
    _redraw_ui()
    _show_result_popup(
        "Restart to Update Moldboxer",
        (
            "Moldboxer was disabled safely. Save your work and restart Blender; "
            "the update will continue automatically."
        ),
        "INFO",
    )
    return True


def _start_native_install(
    repo_index: int,
    repo_directory: str,
    expected_version: str,
) -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    install_operator = (
        getattr(extension_ops, "package_install", None) if extension_ops else None
    )
    if not callable(install_operator):
        return False

    kwargs = {
        "repo_index": repo_index,
        "pkg_id": TARGET_PACKAGE_ID,
        "enable_on_install": True,
    }
    if repo_directory:
        kwargs["repo_directory"] = repo_directory

    for operator_context in (("INVOKE_DEFAULT",), ("EXEC_DEFAULT",), tuple()):
        try:
            result = install_operator(*operator_context, **kwargs)
        except Exception:
            continue
        if not (_operator_running_modal(result) or _operator_finished(result)):
            continue

        _RUNTIME.update(
            phase="installing",
            message=f"Installing Moldboxer {expected_version}",
            expected_version=expected_version,
            started_at=time.monotonic(),
            progress=0.3,
        )
        _ensure_monitor_timer()
        return True
    return False


def _native_operation_running() -> bool:
    try:
        from bl_pkg.bl_extension_ops import repo_status_text  # type: ignore

        if bool(getattr(repo_status_text, "running", False)):
            return True
    except Exception:
        pass

    try:
        from bl_pkg.bl_extension_notify import update_in_progress  # type: ignore

        return bool(update_in_progress())
    except Exception:
        return False


def _redraw_ui() -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    for window in getattr(window_manager, "windows", ()):
        for area in getattr(getattr(window, "screen", None), "areas", ()):
            try:
                area.tag_redraw()
            except Exception:
                continue


def _draw_colored_rectangle(x: float, y: float, width: float, height: float, color) -> None:
    import gpu  # type: ignore
    from gpu_extras.batch import batch_for_shader  # type: ignore

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(
        shader,
        "TRI_FAN",
        {
            "pos": (
                (x, y),
                (x + width, y),
                (x + width, y + height),
                (x, y + height),
            )
        },
    )
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_centered_text(text: str, center_x: float, y: float, size: int, color) -> None:
    import blf  # type: ignore

    font_id = 0
    blf.size(font_id, size)
    text_width, _text_height = blf.dimensions(font_id, text)
    blf.color(font_id, *color)
    blf.position(font_id, center_x - (text_width * 0.5), y, 0)
    blf.draw(font_id, text)


def _draw_update_overlay() -> None:
    if _RUNTIME["phase"] not in {"migrating", "installing"}:
        return

    try:
        import gpu  # type: ignore

        region = getattr(bpy.context, "region", None)
        if region is None:
            return
        width = min(460.0, max(300.0, float(region.width) - 40.0))
        height = 104.0
        x = (float(region.width) - width) * 0.5
        y = float(region.height) - height - 36.0
        center_x = x + (width * 0.5)

        gpu.state.blend_set("ALPHA")
        _draw_colored_rectangle(x, y, width, height, (0.025, 0.03, 0.04, 0.94))
        _draw_colored_rectangle(x, y + height - 3.0, width, 3.0, (0.1, 0.55, 1.0, 1.0))
        _draw_centered_text(
            "Updating Moldboxer",
            center_x,
            y + 68.0,
            18,
            (0.95, 0.97, 1.0, 1.0),
        )
        _draw_centered_text(
            str(_RUNTIME["message"]),
            center_x,
            y + 45.0,
            12,
            (0.72, 0.78, 0.86, 1.0),
        )

        track_x = x + 24.0
        track_y = y + 19.0
        track_width = width - 48.0
        track_height = 8.0
        _draw_colored_rectangle(
            track_x,
            track_y,
            track_width,
            track_height,
            (0.13, 0.16, 0.2, 1.0),
        )
        if _RUNTIME["phase"] == "installing":
            segment_width = max(60.0, track_width * 0.28)
            travel = max(0.0, track_width - segment_width)
            pulse = (math.sin(time.monotonic() * 3.2) + 1.0) * 0.5
            progress_x = track_x + (travel * pulse)
            _draw_colored_rectangle(
                progress_x,
                track_y,
                segment_width,
                track_height,
                (0.1, 0.55, 1.0, 1.0),
            )
        else:
            progress = min(1.0, max(0.0, float(_RUNTIME.get("progress", 0.0))))
            _draw_colored_rectangle(
                track_x,
                track_y,
                track_width * progress,
                track_height,
                (0.1, 0.55, 1.0, 1.0),
            )
    except Exception:
        pass
    finally:
        try:
            import gpu  # type: ignore

            gpu.state.blend_set("NONE")
        except Exception:
            pass


def _show_result_popup(title: str, message: str, icon: str) -> None:
    window_manager = getattr(bpy.context, "window_manager", None)
    if window_manager is None:
        return

    def draw_result(menu, _context):
        menu.layout.label(text=message)

    try:
        window_manager.popup_menu(draw_result, title=title, icon=icon)
    except Exception:
        pass


def _monitor_install():
    if _RUNTIME["phase"] != "installing":
        return None
    if _native_operation_running():
        _redraw_ui()
        return _MONITOR_INTERVAL

    target = _target_package_state()
    local_version = ""
    if target is not None:
        _repo_index, _repo, local_item, _remote_item = target
        local_version = _item_version(local_item)

    expected_version = str(_RUNTIME["expected_version"])
    if local_version and not _is_newer_version(expected_version, local_version):
        _RUNTIME.update(
            phase="restart_required",
            message=f"Moldboxer {local_version} installed — restart Blender",
            progress=1.0,
        )
        _redraw_ui()
        _show_result_popup(
            "Moldboxer Updated",
            f"Moldboxer {local_version} is installed. Restart Blender before using it.",
            "CHECKMARK",
        )
        return None

    if time.monotonic() - float(_RUNTIME["started_at"]) < 1.0:
        _redraw_ui()
        return _MONITOR_INTERVAL
    if time.monotonic() - float(_RUNTIME["started_at"]) < _MONITOR_TIMEOUT:
        _redraw_ui()
        return _MONITOR_INTERVAL

    _RUNTIME.update(
        phase="error",
        message="The update did not finish. Check Blender's status and try again.",
        progress=0.0,
    )
    _redraw_ui()
    _show_result_popup("Moldboxer Update Failed", _RUNTIME["message"], "ERROR")
    return None


def _ensure_monitor_timer() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_monitor_install):
        return
    bpy.app.timers.register(_monitor_install, first_interval=_MONITOR_INTERVAL)


def _automatic_update_timer():
    if _RUNTIME["phase"] in {
        "checking",
        "migrating",
        "installing",
        "restart_required",
    }:
        return _AUTOMATIC_CHECK_INTERVAL
    try:
        result = bpy.ops.moldboxer_updater.install_update("EXEC_DEFAULT")
        if "CANCELLED" in result and _RUNTIME["phase"] == "error":
            return _AUTOMATIC_CHECK_INTERVAL
    except Exception:
        pass
    return _AUTOMATIC_CHECK_INTERVAL


def register_runtime() -> None:
    global _OVERLAY_HANDLE
    if _OVERLAY_HANDLE is None:
        try:
            _OVERLAY_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
                _draw_update_overlay,
                (),
                "WINDOW",
                "POST_PIXEL",
            )
        except Exception:
            _OVERLAY_HANDLE = None

    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if not callable(is_registered) or not is_registered(_automatic_update_timer):
        bpy.app.timers.register(
            _automatic_update_timer,
            first_interval=_AUTOMATIC_CHECK_DELAY,
        )


def unregister_runtime() -> None:
    global _OVERLAY_HANDLE
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_monitor_install):
        bpy.app.timers.unregister(_monitor_install)
    if callable(is_registered) and is_registered(_automatic_update_timer):
        bpy.app.timers.unregister(_automatic_update_timer)
    if _OVERLAY_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_OVERLAY_HANDLE, "WINDOW")
        except Exception:
            pass
        _OVERLAY_HANDLE = None


class MOLDBOXER_UPDATER_OT_install_update(bpy.types.Operator):
    bl_idname = "moldboxer_updater.install_update"
    bl_label = "Install Moldboxer Update"
    bl_description = "Check the Moldboxer repository and install the latest version"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if _RUNTIME["phase"] == "installing":
            self.report({"INFO"}, "A Moldboxer update is already running")
            return {"CANCELLED"}

        online_access, changed = _enabled_online_access(context.preferences)
        if not online_access:
            self.report(
                {"ERROR"},
                "Enable Allow Online Access in Preferences > System to update Moldboxer",
            )
            return {"CANCELLED"}

        target = _target_package_state()
        if target is None:
            self.report(
                {"ERROR"},
                "The Moldboxer Extensions repository is not configured",
            )
            return {"CANCELLED"}

        repo_index, repo, _local_item, _remote_item = target
        repo_directory = str(getattr(repo, "directory", ""))
        _RUNTIME.update(
            phase="checking",
            message="Checking the Moldboxer repository",
            progress=0.12,
        )
        _redraw_ui()

        if not _sync_target_repository(repo_index, repo_directory):
            _RUNTIME.update(
                phase="error",
                message="Could not synchronize the Moldboxer repository",
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        target = _target_package_state()
        if target is None:
            _RUNTIME.update(
                phase="error",
                message="Moldboxer repository data is unavailable",
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        repo_index, repo, local_item, remote_item = target
        if remote_item is None or bool(getattr(remote_item, "block", False)):
            _RUNTIME.update(
                phase="error",
                message="No installable Moldboxer release was found",
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        local_version = _item_version(local_item)
        remote_version = _item_version(remote_item)
        foreign_installs = _foreign_package_installs()
        unsupported_installs = [
            (repo, item)
            for _index, repo, item in foreign_installs
            if not _is_legacy_local_repo(repo)
        ]
        if unsupported_installs:
            foreign_version = _item_version(unsupported_installs[0][1])
            _RUNTIME.update(
                phase="error",
                message=(
                    f"Moldboxer {foreign_version} is installed from another remote "
                    "repository; the selected repository will not replace it"
                ),
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        legacy_installs = [
            (repo_index, repo, item)
            for repo_index, repo, item in foreign_installs
            if _is_legacy_local_repo(repo)
        ]
        installed_versions = [local_version]
        installed_versions.extend(_item_version(item) for _index, _repo, item in legacy_installs)
        newest_installed = max(
            (version for version in installed_versions if version),
            key=_version_tuple,
            default="",
        )
        if newest_installed and _is_newer_version(newest_installed, remote_version):
            _RUNTIME.update(
                phase="error",
                message=(
                    f"Installed Moldboxer {newest_installed} is newer than the "
                    f"production release {remote_version}"
                ),
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        installed_packages = []
        if local_item is not None:
            installed_packages.append((repo_index, repo, local_item))
        installed_packages.extend(legacy_installs)
        filesystem_change_needed = bool(legacy_installs) or not local_version or (
            _is_newer_version(remote_version, local_version)
        )
        if filesystem_change_needed and _stage_windows_restart_if_needed(
            installed_packages,
            remote_version,
        ):
            if _RUNTIME["phase"] == "restart_required":
                self.report({"WARNING"}, _RUNTIME["message"])
                return {"FINISHED"}
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        for legacy_repo_index, legacy_repo, _legacy_item in legacy_installs:
            _RUNTIME.update(
                phase="migrating",
                message="Migrating the legacy Moldboxer installation",
                progress=0.24,
            )
            _redraw_ui()
            legacy_directory = str(getattr(legacy_repo, "directory", ""))
            if _uninstall_package(legacy_repo_index, legacy_directory):
                continue
            _RUNTIME.update(
                phase="error",
                message="Could not remove the legacy Moldboxer disk installation",
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        if local_version and not _is_newer_version(remote_version, local_version):
            _RUNTIME.update(
                phase="current",
                message=f"Moldboxer {local_version} is already up to date",
                progress=1.0,
            )
            self.report({"INFO"}, _RUNTIME["message"])
            _redraw_ui()
            return {"FINISHED"}

        repo_directory = str(getattr(repo, "directory", ""))
        if not _start_native_install(repo_index, repo_directory, remote_version):
            _RUNTIME.update(
                phase="error",
                message="Could not start the Moldboxer installer",
                progress=0.0,
            )
            self.report({"ERROR"}, _RUNTIME["message"])
            return {"CANCELLED"}

        prefix = "Online access enabled. " if changed else ""
        self.report(
            {"INFO"},
            f"{prefix}Installing Moldboxer {remote_version}; restart Blender when it finishes",
        )
        return {"FINISHED"}


CLASSES = (
    MOLDBOXER_UPDATER_OT_install_update,
)
