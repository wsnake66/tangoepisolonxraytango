from pathlib import Path
from typing import Any

import bpy  # type: ignore


def _addon_module_name_from_package_name(package_name: str) -> str:
    normalized = package_name.strip()
    if not normalized:
        return ""

    if ".source" in normalized:
        normalized = normalized.split(".source", 1)[0]

    if normalized.endswith("_native"):
        normalized = normalized[: -len("_native")]

    return normalized


def _addon_module_candidates() -> list[str]:
    package_name = __package__ or __name__ or ""
    if not package_name:
        return []

    parts = package_name.split(".")
    candidates = []
    for i in range(len(parts), 0, -1):
        candidate = _addon_module_name_from_package_name(".".join(parts[:i]))
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    normalized_package = _addon_module_name_from_package_name(package_name)
    if normalized_package and normalized_package not in candidates:
        candidates.append(normalized_package)

    return candidates


def _get_preferences_from_addon(addon: Any) -> Any | None:
    if addon is None or not hasattr(addon, "preferences"):
        return None

    try:
        return addon.preferences
    except Exception:
        return None


def _looks_like_moldboxer_preferences(prefs: Any) -> bool:
    if prefs is None:
        return False

    if type(prefs).__name__ == "MoldboxerAddonPreferences":
        return True

    required_properties = (
        "auth_refresh_token",
        "auth_trial_exports_remaining",
        "dev_repo_path",
    )
    return all(hasattr(prefs, property_name) for property_name in required_properties)


def get_addon_preferences() -> Any | None:
    # Blender may replace the AddonPreferences RNA object during Reload Scripts.
    # Resolve it from the current preferences collection on every call so UI
    # visibility and authentication settings never use an invalid/stale object.
    addons = bpy.context.preferences.addons

    for module_name in _addon_module_candidates():
        addon = addons.get(module_name)
        prefs = _get_preferences_from_addon(addon)
        if prefs is not None:
            return prefs

    addon_folder_name = _addon_module_name_from_package_name(Path(__file__).resolve().parents[1].name)
    for addon_key, addon in addons.items():
        if addon_key == addon_folder_name or addon_key.endswith(f".{addon_folder_name}"):
            prefs = _get_preferences_from_addon(addon)
            if prefs is not None:
                return prefs

    for addon in addons.values():
        prefs = _get_preferences_from_addon(addon)
        if _looks_like_moldboxer_preferences(prefs):
            return prefs

    return None


def is_dev_mode() -> bool:
    prefs = get_addon_preferences()
    return bool(prefs and getattr(prefs, "dev_mode", False))


def get_server_base_url() -> str:
    """Compatibility prefix; the protected worker owns service routing."""

    return ""


def get_oauth_base_url(*, for_login: bool = False) -> str:
    """Compatibility prefix; OAuth transport always routes inside the worker."""

    del for_login
    return ""
