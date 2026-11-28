import sys
import bpy  # type: ignore
import time

from .constants import EXTENSION_PACKAGE_ID, EXTENSION_REPO_MODULE, VERSION
from .environment import is_dev_mode
from .i18n import t

EXTENSION_UPDATE_SEARCH_QUERY = "moldboxer"
_UPDATE_STATUS_CACHE = {
    "available": False,
    "version": "",
    "checked_at": None,
}
_UPDATE_STATUS_CACHE_TTL = 300.0
_BACKGROUND_UPDATE_CHECK_DELAY = 0.75
_BACKGROUND_UPDATE_POLL_INTERVAL = 0.25
_BACKGROUND_UPDATE_CHECK_INTERVAL = 20.0 * 60.0
_LEGACY_UNINSTALL_POLL_INTERVAL = 0.25
_LEGACY_UNINSTALL_SETTLE_DELAY = 0.5


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _try_set_search_value(target, query: str) -> bool:
    for attr_name in (
        "extension_search",
        "addon_search",
        "search",
        "search_filter",
        "filter_search",
        "filter_text",
    ):
        if not hasattr(target, attr_name):
            continue
        try:
            setattr(target, attr_name, query)
            return True
        except Exception:
            continue
    return False


def _ensure_online_access(preferences) -> tuple[bool, bool]:
    if preferences is None:
        return False, False

    candidates = (
        (getattr(preferences, "system", None), "use_online_access"),
        (preferences, "use_online_access"),
        (getattr(preferences, "experimental", None), "use_online_access"),
    )
    for owner, attr_name in candidates:
        if owner is None or not hasattr(owner, attr_name):
            continue
        try:
            if bool(getattr(owner, attr_name)):
                return True, False
        except Exception:
            continue
        try:
            setattr(owner, attr_name, True)
            return bool(getattr(owner, attr_name)), True
        except Exception:
            continue

    return False, False


def _open_get_extensions() -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    if extension_ops is not None:
        show_for_update = getattr(extension_ops, "userpref_show_for_update", None)
        if callable(show_for_update):
            try:
                show_for_update()
                return True
            except Exception:
                pass

    legacy_extension_ops = getattr(bpy.ops, "bl_pkg", None)
    if legacy_extension_ops is not None:
        show_for_update = getattr(legacy_extension_ops, "extensions_show_for_update", None)
        if callable(show_for_update):
            try:
                show_for_update()
                return True
            except Exception:
                pass

    return False


def _expand_available_extensions_panel(wm) -> bool:
    if wm is None or not hasattr(wm, "extension_show_panel_available"):
        return False
    try:
        wm.extension_show_panel_available = True
        return bool(getattr(wm, "extension_show_panel_available"))
    except Exception:
        return False


def _extension_repo_state():
    try:
        from bl_pkg import repo_cache_store_ensure  # type: ignore
        from bl_pkg.bl_extension_ops import extension_repos_read  # type: ignore
    except Exception:
        return None

    try:
        repos_all = list(extension_repos_read())
        repo_cache_store = repo_cache_store_ensure()
        quiet_error = lambda *_args, **_kwargs: None
        local_all = list(repo_cache_store.pkg_manifest_from_local_ensure(error_fn=quiet_error))
        remote_all = list(
            repo_cache_store.pkg_manifest_from_remote_ensure(error_fn=quiet_error)
        )
        return repos_all, local_all, remote_all
    except Exception:
        return None


def _manifest_item(manifests, repo_index: int, pkg_id: str):
    if manifests is None or repo_index < 0 or repo_index >= len(manifests):
        return None
    manifest = manifests[repo_index]
    if manifest is None or not hasattr(manifest, "get"):
        return None
    try:
        return manifest.get(pkg_id)
    except Exception:
        return None


def _repo_module(repo) -> str:
    return str(getattr(repo, "module", "")).strip().lower()


def _is_legacy_local_repo(repo) -> bool:
    remote_url = str(getattr(repo, "remote_url", "")).strip()
    source = str(getattr(repo, "source", "")).strip().upper()
    return not remote_url and source == "USER"


def _item_version(item) -> str:
    return str(getattr(item, "version", "")).strip()


def _is_newer_version(candidate: str, current: str) -> bool:
    if not candidate or not current:
        return False

    def _version_tuple(raw: str) -> tuple[int, ...]:
        values = []
        for part in str(raw).split("."):
            digits = "".join(ch for ch in part if ch.isdigit())
            values.append(int(digits) if digits else 0)
        return tuple(values)

    return _version_tuple(candidate) > _version_tuple(current)


def _is_direct_update_available(local_version: str, remote_version: str) -> bool:
    if not local_version or not remote_version or local_version == remote_version:
        return False

    if is_dev_mode():
        return _is_newer_version(remote_version, VERSION)

    return _is_newer_version(remote_version, local_version)


def _operator_finished(result) -> bool:
    try:
        return "FINISHED" in result
    except Exception:
        return False


def _operator_running_modal(result) -> bool:
    try:
        return "RUNNING_MODAL" in result
    except Exception:
        return False


def _invalidate_update_status_cache() -> None:
    _UPDATE_STATUS_CACHE["available"] = False
    _UPDATE_STATUS_CACHE["version"] = ""
    _UPDATE_STATUS_CACHE["checked_at"] = None


def _extension_update_in_progress() -> bool:
    try:
        from bl_pkg.bl_extension_notify import update_in_progress  # type: ignore

        return bool(update_in_progress())
    except Exception:
        return False


def _refresh_extension_repositories_remote() -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    if extension_ops is not None:
        sync_all_op = getattr(extension_ops, "repo_sync_all", None)
        if callable(sync_all_op):
            for op_args in (("INVOKE_DEFAULT",), ("EXEC_DEFAULT",), tuple()):
                try:
                    result = sync_all_op(*op_args)
                    if _operator_finished(result) or _operator_running_modal(result):
                        _invalidate_update_status_cache()
                        return True
                except Exception:
                    continue

    legacy_ops = getattr(bpy.ops, "bl_pkg", None)
    if legacy_ops is not None:
        sync_all_op = getattr(legacy_ops, "repo_sync_all", None)
        if callable(sync_all_op):
            for op_args in (("INVOKE_DEFAULT",), ("EXEC_DEFAULT",), tuple()):
                try:
                    result = sync_all_op(*op_args)
                    if _operator_finished(result) or _operator_running_modal(result):
                        _invalidate_update_status_cache()
                        return True
                except Exception:
                    continue

    return False


def _uninstall_extension_package(repo_index: int, pkg_id: str, repo_directory: str = "") -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    if extension_ops is not None:
        uninstall_op = getattr(extension_ops, "package_uninstall", None)
        if callable(uninstall_op):
            for kwargs in (
                {
                    "repo_index": repo_index,
                    "pkg_id": pkg_id,
                    "repo_directory": repo_directory,
                },
                {"repo_index": repo_index, "pkg_id": pkg_id},
            ):
                try:
                    if _operator_finished(uninstall_op(**kwargs)):
                        return True
                except Exception:
                    continue

    legacy_ops = getattr(bpy.ops, "bl_pkg", None)
    if legacy_ops is not None:
        uninstall_op = getattr(legacy_ops, "pkg_uninstall", None)
        if callable(uninstall_op):
            for kwargs in (
                {
                    "repo_index": repo_index,
                    "pkg_id": pkg_id,
                    "repo_directory": repo_directory,
                },
                {"repo_index": repo_index, "pkg_id": pkg_id},
            ):
                try:
                    if _operator_finished(uninstall_op(**kwargs)):
                        return True
                except Exception:
                    continue

    return False


def _auto_uninstall_legacy_disk_install() -> bool:
    if is_dev_mode() or _is_windows():
        return False

    state = _extension_repo_state()
    if state is None:
        return False

    repos_all, local_all, remote_all = state
    target_repo_module = EXTENSION_REPO_MODULE.strip().lower()
    legacy_repo_indices = []
    has_direct_update = False
    has_remote_newer_version = False

    for repo_index, repo in enumerate(repos_all):
        repo_module = _repo_module(repo)
        local_item = _manifest_item(local_all, repo_index, EXTENSION_PACKAGE_ID)
        remote_item = _manifest_item(remote_all, repo_index, EXTENSION_PACKAGE_ID)
        local_version = _item_version(local_item)
        remote_version = _item_version(remote_item)

        if (
            local_item is not None
            and repo_module != target_repo_module
            and _is_legacy_local_repo(repo)
        ):
            legacy_repo_indices.append(repo_index)

        if (
            local_item is not None
            and remote_item is not None
            and not bool(getattr(remote_item, "block", False))
            and _is_direct_update_available(local_version, remote_version)
        ):
            has_direct_update = True

        if (
            repo_module == target_repo_module
            and remote_item is not None
            and remote_version
            and _is_newer_version(remote_version, VERSION)
        ):
            has_remote_newer_version = True

    if has_direct_update:
        return False
    if not has_remote_newer_version:
        return False
    if not legacy_repo_indices:
        return False

    uninstalled_any = False
    for repo_index in legacy_repo_indices:
        repo = repos_all[repo_index]
        repo_directory = str(getattr(repo, "directory", ""))
        if _uninstall_extension_package(
            repo_index,
            EXTENSION_PACKAGE_ID,
            repo_directory=repo_directory,
        ):
            uninstalled_any = True

    return uninstalled_any


def _schedule_auto_uninstall_legacy_disk_install(
    delay_seconds: float = 0.35,
    poll_interval: float = _LEGACY_UNINSTALL_POLL_INTERVAL,
    settle_delay: float = _LEGACY_UNINSTALL_SETTLE_DELAY,
) -> bool:
    if is_dev_mode() or _is_windows():
        return False

    try:
        idle_observed = False

        def _run_when_idle():
            nonlocal idle_observed
            if _extension_update_in_progress():
                idle_observed = False
                return poll_interval

            if not idle_observed:
                idle_observed = True
                return settle_delay

            try:
                _auto_uninstall_legacy_disk_install()
            except Exception:
                pass
            return None

        bpy.app.timers.register(_run_when_idle, first_interval=delay_seconds)
        return True
    except Exception:
        return False


def _compute_update_status() -> tuple[bool, str]:
    state = _extension_repo_state()
    if state is None:
        return False, ""

    repos_all, local_all, remote_all = state
    target_repo_module = EXTENSION_REPO_MODULE.strip().lower()
    fallback_remote_version = ""

    for repo_index, repo in enumerate(repos_all):
        repo_module = _repo_module(repo)
        local_item = _manifest_item(local_all, repo_index, EXTENSION_PACKAGE_ID)
        remote_item = _manifest_item(remote_all, repo_index, EXTENSION_PACKAGE_ID)
        local_version = _item_version(local_item)
        remote_version = _item_version(remote_item)

        if (
            repo_module == target_repo_module
            and local_item is not None
            and remote_item is not None
            and not bool(getattr(remote_item, "block", False))
            and _is_direct_update_available(local_version, remote_version)
        ):
            return True, remote_version

        if (
            repo_module == target_repo_module
            and remote_item is not None
            and remote_version
            and _is_newer_version(remote_version, VERSION)
        ):
            fallback_remote_version = remote_version

    return bool(fallback_remote_version), fallback_remote_version


def get_extension_update_status(force: bool = False) -> tuple[bool, str]:
    now = time.monotonic()
    checked_at = _UPDATE_STATUS_CACHE.get("checked_at")
    cache_age = None
    if checked_at is not None:
        try:
            cache_age = now - float(checked_at)
        except Exception:
            cache_age = None

    if not force and cache_age is not None and cache_age <= _UPDATE_STATUS_CACHE_TTL:
        return bool(_UPDATE_STATUS_CACHE["available"]), str(_UPDATE_STATUS_CACHE["version"])

    available, version = _compute_update_status()
    _UPDATE_STATUS_CACHE["available"] = available
    _UPDATE_STATUS_CACHE["version"] = version
    _UPDATE_STATUS_CACHE["checked_at"] = now
    return available, version


def has_extension_update_available(force: bool = False) -> bool:
    available, _version = get_extension_update_status(force=force)
    return available


def block_if_extension_update_available(context, report) -> bool:
    return False


def _background_extension_update_check():
    if not bool(getattr(bpy.app, "online_access", False)):
        return _BACKGROUND_UPDATE_CHECK_INTERVAL

    try:
        from bl_pkg.bl_extension_notify import update_non_blocking  # type: ignore
        from bl_pkg.bl_extension_ops import extension_repos_read  # type: ignore

        target_module = EXTENSION_REPO_MODULE.strip().lower()
        repos = [
            repo
            for repo in extension_repos_read()
            if _repo_module(repo) == target_module
        ]
        if repos:
            update_non_blocking(
                repos_fn=lambda: [(repo, True) for repo in repos],
                immediate=True,
            )
            _invalidate_update_status_cache()
            is_registered = getattr(bpy.app.timers, "is_registered", None)
            if not callable(is_registered) or not is_registered(
                _finish_background_extension_update_check
            ):
                bpy.app.timers.register(
                    _finish_background_extension_update_check,
                    first_interval=_BACKGROUND_UPDATE_POLL_INTERVAL,
                )
            return _BACKGROUND_UPDATE_CHECK_INTERVAL
    except Exception:
        pass

    _refresh_extension_repositories_remote()
    return _BACKGROUND_UPDATE_CHECK_INTERVAL


def _finish_background_extension_update_check():
    if _extension_update_in_progress():
        return _BACKGROUND_UPDATE_POLL_INTERVAL

    _invalidate_update_status_cache()
    wm = getattr(bpy.context, "window_manager", None)
    for window in getattr(wm, "windows", ()):
        for area in getattr(getattr(window, "screen", None), "areas", ()):
            try:
                area.tag_redraw()
            except Exception:
                continue
    return None


def schedule_extension_update_check() -> bool:
    return False


def unregister_extension_update_check_timer() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if not callable(is_registered):
        return
    if is_registered(_background_extension_update_check):
        bpy.app.timers.unregister(_background_extension_update_check)
    if is_registered(_finish_background_extension_update_check):
        bpy.app.timers.unregister(_finish_background_extension_update_check)


def open_extension_updates(context, report):
    opened_preferences = False
    for op_args in (("INVOKE_DEFAULT",), tuple()):
        try:
            bpy.ops.screen.userpref_show(*op_args)
            opened_preferences = True
            break
        except Exception:
            continue

    if not opened_preferences:
        report({"ERROR"}, t("Could not open Blender Preferences"))
        return {"CANCELLED"}

    preferences = getattr(context, "preferences", None)
    online_enabled, online_changed = _ensure_online_access(preferences)

    section_set = False
    target_sections = ("EXTENSIONS",)
    if not online_enabled:
        target_sections = ("SYSTEM", "EXTENSIONS")
    if preferences is not None:
        for section in target_sections:
            try:
                preferences.active_section = section
                section_set = True
                break
            except Exception:
                continue

    wm = getattr(context, "window_manager", None)
    if not _is_windows():
        _open_get_extensions()
    available_panel_expanded = (
        False if _is_windows() else _expand_available_extensions_panel(wm)
    )
    remote_refresh_started = False
    scheduled_legacy_uninstall = False
    if online_enabled:
        remote_refresh_started = _refresh_extension_repositories_remote()
        if remote_refresh_started:
            scheduled_legacy_uninstall = (
                _schedule_auto_uninstall_legacy_disk_install()
            )

    search_set = False
    if wm is not None and not _is_windows():
        search_set = _try_set_search_value(wm, EXTENSION_UPDATE_SEARCH_QUERY)

        for window in wm.windows:
            if search_set:
                break
            for area in window.screen.areas:
                if area.type != "PREFERENCES":
                    continue
                for space in area.spaces:
                    if space.type != "PREFERENCES":
                        continue
                    search_set = _try_set_search_value(space, EXTENSION_UPDATE_SEARCH_QUERY)
                    if search_set:
                        break
                if search_set:
                    break

    if not online_enabled:
        report(
            {"WARNING"},
            t("Enable 'Allow Online Access' in Preferences > System to update extensions."),
        )
        return {"FINISHED"}

    if online_changed and remote_refresh_started and section_set and search_set:
        report(
            {"INFO"},
            t("Online access enabled. Refreshing remote extensions and searched Moldboxer."),
        )
    elif online_changed and section_set and search_set:
        report(
            {"INFO"},
            t("Online access enabled. Opened Preferences > Extensions and searched Moldboxer."),
        )
    elif remote_refresh_started and section_set and search_set:
        report(
            {"INFO"},
            t("Refreshing remote extensions. Opened Preferences > Extensions and searched Moldboxer."),
        )
    elif remote_refresh_started and section_set:
        report(
            {"INFO"},
            t("Refreshing remote extensions. Opened Preferences > Extensions."),
        )
    elif section_set and search_set and available_panel_expanded:
        report(
            {"INFO"},
            t("Opened Preferences > Extensions, expanded Available, and searched Moldboxer"),
        )
    elif section_set and search_set:
        report({"INFO"}, t("Opened Preferences > Extensions and searched Moldboxer"))
    else:
        report(
            {"INFO"},
            t("Opened Preferences. Search for 'moldboxer' in Extensions to update."),
        )

    if scheduled_legacy_uninstall:
        report(
            {"INFO"},
            t("Opened Get Extensions first. Legacy disk uninstall will run in background if needed."),
        )

    return {"FINISHED"}
