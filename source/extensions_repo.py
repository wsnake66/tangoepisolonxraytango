import traceback
import bpy  # type: ignore

from .constants import (
    EXTENSION_REPO_MODULE,
    EXTENSION_REPO_NAME,
    EXTENSION_REPO_REMOTE_URL,
)

_ENSURE_REPO_MAX_ATTEMPTS = 6
_ensure_repo_attempts = 0


def _normalize_url(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def _get_repos():
    preferences = getattr(bpy.context, "preferences", None)
    if preferences is None:
        return None
    extensions = getattr(preferences, "extensions", None)
    if extensions is None:
        return None
    return getattr(extensions, "repos", None)


def _repo_matches(repo) -> bool:
    name = str(getattr(repo, "name", "")).strip().lower()
    module = str(getattr(repo, "module", "")).strip().lower()
    remote_url = _normalize_url(getattr(repo, "remote_url", ""))
    target_url = _normalize_url(EXTENSION_REPO_REMOTE_URL)

    if remote_url and remote_url == target_url:
        return True
    if name and name == EXTENSION_REPO_NAME.lower():
        return True
    if module and module == EXTENSION_REPO_MODULE.lower():
        return True
    return False


def _set_repo_fields(repo) -> None:
    for attr_name, attr_value in (
        ("name", EXTENSION_REPO_NAME),
        ("remote_url", EXTENSION_REPO_REMOTE_URL),
    ):
        if not hasattr(repo, attr_name):
            continue
        try:
            setattr(repo, attr_name, attr_value)
        except Exception:
            continue

    # Blender has used different property names across versions for these toggles.
    for attr_name in (
        "use_remote_url",
        "use_sync_on_startup",
        "use_check_for_updates",
        "check_for_updates",
        "use_auto_update",
    ):
        if not hasattr(repo, attr_name):
            continue
        try:
            setattr(repo, attr_name, True)
        except Exception:
            continue


def _add_repo_with_collection(repos) -> bool:
    new_fn = getattr(repos, "new", None)
    if not callable(new_fn):
        return False

    for kwargs in (
        {
            "name": EXTENSION_REPO_NAME,
            "module": EXTENSION_REPO_MODULE,
            "remote_url": EXTENSION_REPO_REMOTE_URL,
        },
        {
            "name": EXTENSION_REPO_NAME,
            "module": EXTENSION_REPO_MODULE,
        },
        {"name": EXTENSION_REPO_NAME},
    ):
        try:
            repo = new_fn(**kwargs)
            _set_repo_fields(repo)
            return True
        except Exception:
            continue

    return False


def _add_repo_with_operator() -> bool:
    add_repo_op = getattr(bpy.ops.preferences, "extension_repo_add", None)
    if add_repo_op is None:
        return False

    for kwargs in (
        {
            "name": EXTENSION_REPO_NAME,
            "module": EXTENSION_REPO_MODULE,
            "remote_url": EXTENSION_REPO_REMOTE_URL,
        },
        {"name": EXTENSION_REPO_NAME, "module": EXTENSION_REPO_MODULE},
        {"name": EXTENSION_REPO_NAME},
    ):
        try:
            add_repo_op(**kwargs)
            return True
        except Exception:
            continue

    return False


def ensure_extension_repo() -> bool:
    repos = _get_repos()
    if repos is None:
        return False

    for repo in repos:
        if _repo_matches(repo):
            _set_repo_fields(repo)
            return True

    added = _add_repo_with_collection(repos)
    if not added:
        added = _add_repo_with_operator()
    if not added:
        return False

    for repo in repos:
        if _repo_matches(repo):
            _set_repo_fields(repo)
            return True
    return False


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


def _ensure_extension_repo_timer():
    global _ensure_repo_attempts
    _ensure_repo_attempts += 1

    try:
        if ensure_extension_repo():
            _save_user_preferences()
            try:
                from .extension_updates import schedule_extension_update_check

                schedule_extension_update_check()
            except Exception:
                pass
            print("[Moldboxer Silicone] Extension repository is configured")
            return None
    except Exception:
        traceback.print_exc()
        return None

    if _ensure_repo_attempts >= _ENSURE_REPO_MAX_ATTEMPTS:
        return None
    return 1.5


def schedule_ensure_extension_repo() -> None:
    return


def unregister_ensure_extension_repo_timer() -> None:
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if not callable(is_registered) or not is_registered(_ensure_extension_repo_timer):
        pass
    else:
        bpy.app.timers.unregister(_ensure_extension_repo_timer)

    try:
        from .extension_updates import unregister_extension_update_check_timer

        unregister_extension_update_check_timer()
    except Exception:
        pass
