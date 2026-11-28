"""Install or upgrade the independent Moldboxer Updater extension."""

import hashlib
import os
import sys
import tempfile
import threading
import time
import urllib.request

import bpy  # type: ignore

from .constants import EXTENSION_REPO_REMOTE_URL, VERSION
from .environment import is_dev_mode
from .tls_context import create_moldboxer_ssl_context


UPDATER_PACKAGE_ID = "moldboxer_updater"
UPDATER_MIN_VERSION = "1.0.4"
_BOOTSTRAP_INITIAL_DELAY = 2.5
_BOOTSTRAP_POLL_INTERVAL = 0.25
_BOOTSTRAP_RETRY_DELAY = 5.0 * 60.0
_DEFERRED_SUSPEND_DELAY = 0.75
_MAX_UPDATER_ARCHIVE_BYTES = 5 * 1024 * 1024
_STATE_LOCK = threading.Lock()
_STATE = {
    "phase": "idle",
    "archive_path": "",
    "error": "",
    "generation": 0,
    "install_started_at": 0.0,
}


def _updater_operator_available() -> bool:
    try:
        operator = bpy.ops.moldboxer_updater.install_update
        operator.get_rna_type()
        return True
    except (AttributeError, KeyError, RuntimeError):
        return False


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for component in str(value or "").split("."):
        digits = "".join(character for character in component if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _installed_updater_version() -> str:
    try:
        from bl_pkg import repo_cache_store_ensure  # type: ignore

        cache = repo_cache_store_ensure()
        quiet_error = lambda *_args, **_kwargs: None
        local_all = list(cache.pkg_manifest_from_local_ensure(error_fn=quiet_error))
    except Exception:
        return ""

    versions = []
    for manifest in local_all:
        if manifest is None or not hasattr(manifest, "get"):
            continue
        try:
            item = manifest.get(UPDATER_PACKAGE_ID)
        except Exception:
            continue
        version = str(getattr(item, "version", "") or "").strip()
        if version:
            versions.append(version)
    return max(versions, key=_version_tuple, default="")


def _updater_is_current() -> bool:
    if not _updater_operator_available():
        return False
    installed_version = _installed_updater_version()
    if not installed_version:
        # Cache access can be temporarily unavailable during Blender startup.
        return True
    return _version_tuple(installed_version) >= _version_tuple(UPDATER_MIN_VERSION)


def _suspend_outdated_updater_runtime() -> None:
    """Stop an old updater timer before it can start an unsafe update."""
    suffix = f".{UPDATER_PACKAGE_ID}.updater"
    for module_name, module in tuple(sys.modules.items()):
        if not module_name.endswith(suffix):
            continue
        unregister_runtime = getattr(module, "unregister_runtime", None)
        if not callable(unregister_runtime):
            continue
        try:
            unregister_runtime()
        except Exception:
            pass


def _deferred_updater_suspend_timer() -> None:
    _suspend_outdated_updater_runtime()
    return None


def _schedule_deferred_updater_suspend() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered) and is_registered(_deferred_updater_suspend_timer):
        return
    bpy.app.timers.register(
        _deferred_updater_suspend_timer,
        first_interval=_DEFERRED_SUSPEND_DELAY,
    )


def _installed_extension_repo_module() -> str:
    package_name = str(globals().get("__package__", "") or "").strip()
    package_parts = package_name.split(".")
    if len(package_parts) >= 3 and package_parts[0] == "bl_ext":
        return package_parts[1].strip().lower()
    return ""


def _updater_download_url(preferences) -> str:
    installed_repo_module = _installed_extension_repo_module()
    extensions = getattr(preferences, "extensions", None)
    repos = getattr(extensions, "repos", ())
    if installed_repo_module:
        for repo in repos:
            repo_module = str(getattr(repo, "module", "")).strip().lower()
            if repo_module != installed_repo_module:
                continue
            remote_url = str(getattr(repo, "remote_url", "")).strip().rstrip("/")
            if remote_url.startswith(("https://", "http://")):
                return f"{remote_url}/updater/download"

    return f"{EXTENSION_REPO_REMOTE_URL.rstrip('/')}/updater/download"


def _enable_online_access(preferences) -> bool:
    if bool(getattr(bpy.app, "online_access", False)):
        return True
    if bool(getattr(bpy.app, "online_access_override", False)):
        return False

    for owner, attribute in (
        (getattr(preferences, "system", None), "use_online_access"),
        (preferences, "use_online_access"),
    ):
        if owner is None or not hasattr(owner, attribute):
            continue
        try:
            setattr(owner, attribute, True)
            if bool(getattr(owner, attribute)):
                return True
        except Exception:
            continue
    return bool(getattr(bpy.app, "online_access", False))


def _local_extension_repo_module(preferences) -> str:
    extensions = getattr(preferences, "extensions", None)
    repos = getattr(extensions, "repos", ())
    fallback = ""
    for repo in repos:
        if str(getattr(repo, "source", "USER")).upper() != "USER":
            continue
        if not bool(getattr(repo, "enabled", True)):
            continue
        module = str(getattr(repo, "module", "")).strip()
        if not module:
            continue
        if module == "user_default":
            return module
        remote_url = str(getattr(repo, "remote_url", "")).strip()
        use_remote_url = bool(getattr(repo, "use_remote_url", bool(remote_url)))
        if not remote_url and not use_remote_url and not fallback:
            fallback = module
    return fallback or "user_default"


def _expected_hash_from_headers(headers) -> str:
    raw_hash = str(headers.get("X-Moldboxer-Archive-SHA256", "")).strip().lower()
    if raw_hash.startswith("sha256:"):
        raw_hash = raw_hash.split(":", 1)[1]
    if len(raw_hash) == 64 and all(character in "0123456789abcdef" for character in raw_hash):
        return raw_hash
    return ""


def _remove_archive(path: str) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except (FileNotFoundError, OSError):
        pass


def _download_updater_worker(generation: int, download_url: str) -> None:
    archive_path = ""
    try:
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": f"Moldboxer/{VERSION} Blender"},
        )
        with urllib.request.urlopen(
            request,
            timeout=30.0,
            context=create_moldboxer_ssl_context(),
        ) as response:
            payload = response.read(_MAX_UPDATER_ARCHIVE_BYTES + 1)
            expected_hash = _expected_hash_from_headers(response.headers)
        if not payload or len(payload) > _MAX_UPDATER_ARCHIVE_BYTES:
            raise RuntimeError("Updater download is empty or unexpectedly large")
        if not expected_hash:
            raise RuntimeError("Updater download did not include an integrity hash")
        actual_hash = hashlib.sha256(payload).hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError("Updater download failed its SHA-256 integrity check")

        with tempfile.NamedTemporaryFile(
            prefix="moldboxer_updater_",
            suffix=".zip",
            delete=False,
        ) as archive_file:
            archive_file.write(payload)
            archive_path = archive_file.name

        with _STATE_LOCK:
            if generation != _STATE["generation"]:
                _remove_archive(archive_path)
                return
            _STATE.update(phase="ready", archive_path=archive_path, error="")
    except Exception as error:
        _remove_archive(archive_path)
        with _STATE_LOCK:
            if generation == _STATE["generation"]:
                _STATE.update(phase="error", archive_path="", error=str(error))


def _start_updater_download() -> None:
    download_url = _updater_download_url(
        getattr(bpy.context, "preferences", None)
    )
    with _STATE_LOCK:
        _STATE["generation"] = int(_STATE["generation"]) + 1
        generation = int(_STATE["generation"])
        _STATE.update(phase="downloading", archive_path="", error="")
    thread = threading.Thread(
        target=_download_updater_worker,
        args=(generation, download_url),
        name="MoldboxerUpdaterDownload",
        daemon=True,
    )
    thread.start()


def _install_downloaded_updater(context, archive_path: str) -> bool:
    extension_ops = getattr(bpy.ops, "extensions", None)
    install_operator = (
        getattr(extension_ops, "package_install_files", None)
        if extension_ops is not None
        else None
    )
    if not callable(install_operator):
        return False

    repo_module = _local_extension_repo_module(context.preferences)
    kwargs = {
        "filepath": archive_path,
        "repo": repo_module,
        "enable_on_install": True,
        "overwrite": True,
    }
    for operator_context in (("EXEC_DEFAULT",), tuple()):
        try:
            result = install_operator(*operator_context, **kwargs)
            if "FINISHED" in result or "RUNNING_MODAL" in result:
                return True
        except Exception:
            continue
    return False


def _updater_bootstrap_timer():
    if is_dev_mode() or _updater_is_current():
        with _STATE_LOCK:
            archive_path = str(_STATE.get("archive_path", ""))
            _STATE.update(phase="installed", archive_path="", error="")
        _remove_archive(archive_path)
        return None

    if not _enable_online_access(getattr(bpy.context, "preferences", None)):
        return _BOOTSTRAP_RETRY_DELAY

    with _STATE_LOCK:
        phase = str(_STATE["phase"])
        archive_path = str(_STATE["archive_path"])
        install_started_at = float(_STATE["install_started_at"])

    if phase == "idle":
        _start_updater_download()
        return _BOOTSTRAP_POLL_INTERVAL
    if phase == "downloading":
        return _BOOTSTRAP_POLL_INTERVAL
    if phase == "error":
        with _STATE_LOCK:
            _STATE["phase"] = "idle"
        return _BOOTSTRAP_RETRY_DELAY
    if phase == "ready":
        if _install_downloaded_updater(bpy.context, archive_path):
            with _STATE_LOCK:
                _STATE.update(phase="installing", install_started_at=time.monotonic())
            return _BOOTSTRAP_POLL_INTERVAL
        _remove_archive(archive_path)
        with _STATE_LOCK:
            _STATE.update(
                phase="error",
                archive_path="",
                error="Blender could not install the updater extension",
            )
        return _BOOTSTRAP_RETRY_DELAY
    if phase == "installing":
        if time.monotonic() - install_started_at < 30.0:
            return _BOOTSTRAP_POLL_INTERVAL
        _remove_archive(archive_path)
        with _STATE_LOCK:
            _STATE.update(
                phase="error",
                archive_path="",
                error="The updater extension did not become available",
            )
        return _BOOTSTRAP_RETRY_DELAY
    return _BOOTSTRAP_RETRY_DELAY


def schedule_updater_bootstrap() -> bool:
    _suspend_outdated_updater_runtime()
    _schedule_deferred_updater_suspend()
    return False


def unregister_updater_bootstrap() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    for timer in (
        _updater_bootstrap_timer,
        _deferred_updater_suspend_timer,
    ):
        if callable(is_registered) and is_registered(timer):
            bpy.app.timers.unregister(timer)
    with _STATE_LOCK:
        _STATE["generation"] = int(_STATE["generation"]) + 1
        archive_path = str(_STATE.get("archive_path", ""))
        _STATE.update(phase="idle", archive_path="", error="")
    _remove_archive(archive_path)
