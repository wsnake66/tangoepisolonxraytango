import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import bpy  # type: ignore

from .geometry_adapter import acquire_geometry_worker
from ..background_worker import BackgroundTaskSequence, submit_worker_task
from ..environment import get_addon_preferences, get_oauth_base_url, is_dev_mode
from ..i18n import t
from ..login_resume import clear_pending_generation, schedule_generation_resume

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
ACCESS_TOKEN_SKEW_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 15


def _oauth_url(path: str, *, for_login: bool = False) -> str:
    return f"{get_oauth_base_url(for_login=for_login)}{path}"


def _apply_current_tier_scene_defaults() -> None:
    scene = getattr(bpy.context, "scene", None)
    if scene is None:
        return
    try:
        from ..operator_access import apply_lite_access_defaults, is_lite_tier

        if is_lite_tier():
            apply_lite_access_defaults(scene)
    except Exception:
        logger.exception("Failed to apply tier scene defaults")


def _clear_pending_state(prefs: Any, *, keep_generation: bool = False) -> None:
    if not keep_generation:
        clear_pending_generation()
    prefs.auth_polling_active = False
    prefs.auth_device_code = ""
    prefs.auth_device_expires_at = 0.0
    prefs.auth_pending_provider = ""


def _clear_login_state(prefs: Any) -> None:
    _clear_pending_state(prefs)
    prefs.auth_logged_in = False
    prefs.auth_provider = ""
    prefs.auth_refresh_token = ""
    prefs.auth_access_token = ""
    prefs.auth_access_expires_at = 0.0
    prefs.auth_tier = ""
    prefs.auth_stripe_status = ""
    prefs.auth_pro_trial_available = False


def _force_logout_for_revoked_refresh_token(prefs: Any, error_label: str) -> None:
    _clear_login_state(prefs)
    prefs.auth_last_error = error_label or "refresh_token_revoked"
    _persist_auth_state()


def is_free_trial_status(stripe_status: str) -> bool:
    return str(stripe_status).upper() in {
        "FREE_BASIC_GOOGLE",
        "FREE_PRO_TRIAL_GOOGLE",
    }


def initialize_trial_export_counter(
    prefs: Any, stripe_status: str, user_email: str = ""
) -> None:
    if not is_free_trial_status(stripe_status):
        return
    normalized_email = str(user_email).strip().lower()
    stored_email = str(getattr(prefs, "auth_trial_export_email", "")).strip().lower()
    if not normalized_email:
        normalized_email = str(getattr(prefs, "auth_user_email", "")).strip().lower()
    if normalized_email and normalized_email != stored_email:
        prefs.auth_trial_exports_remaining = 2
    if normalized_email:
        prefs.auth_trial_export_email = normalized_email
    if int(getattr(prefs, "auth_trial_exports_remaining", 0)) < 0:
        prefs.auth_trial_exports_remaining = 2


def get_trial_exports_remaining(prefs: Any | None = None) -> int:
    prefs = prefs or get_addon_preferences()
    if prefs is None:
        return 0
    return max(0, int(getattr(prefs, "auth_trial_exports_remaining", 0)))


def consume_trial_export(prefs: Any | None = None) -> bool:
    prefs = prefs or get_addon_preferences()
    if prefs is None:
        return False
    remaining = get_trial_exports_remaining(prefs)
    if remaining <= 0:
        return False
    prefs.auth_trial_exports_remaining = remaining - 1
    _persist_auth_state()
    return True


def _save_user_preferences() -> bool:
    save_pref_op = getattr(bpy.ops.wm, "save_userpref", None)
    if save_pref_op is None:
        return False

    for op_args in (("EXEC_DEFAULT",), tuple()):
        try:
            result = save_pref_op(*op_args)
            return "FINISHED" in result
        except Exception:
            continue
    return False


def _persist_auth_state() -> None:
    if not _save_user_preferences():
        logger.warning("Could not save Blender preferences after auth state update")


def logout_user() -> bool:
    prefs = get_addon_preferences()
    if prefs is None:
        return False
    _clear_login_state(prefs)
    prefs.auth_last_error = ""
    _persist_auth_state()
    return True


def is_logged_in() -> bool:
    prefs = get_addon_preferences()
    return bool(
        prefs
        and getattr(prefs, "auth_logged_in", False)
        and getattr(prefs, "auth_refresh_token", "")
    )


def _extract_email(user_data: Any) -> str:
    if isinstance(user_data, dict):
        return str(user_data.get("email", ""))
    if isinstance(user_data, str):
        return user_data
    return ""


def _extract_error_detail(response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail.strip()
    return ""


def _normalize_error_label(value: str) -> str:
    return "_".join(part for part in value.strip().lower().split() if part)


def _send_oauth_request(worker, path: str, payload: dict, dev_requested: bool):
    """Execute OAuth transport without reading Blender state."""

    return worker.service_json_request(
        "oauth",
        path,
        payload,
        dev_requested=dev_requested,
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        max_attempts=1,
        retry_backoff_seconds=0.0,
    )


def _oauth_request(path: str, payload: dict):
    """Execute OAuth transport inside the protected external worker."""

    worker = acquire_geometry_worker(authorize=False)
    return worker.service_json_request(
        "oauth",
        path,
        payload,
        dev_requested=is_dev_mode(),
        timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        max_attempts=1,
        retry_backoff_seconds=0.0,
    )


def _parse_expiry_timestamp(payload: dict[str, Any], now: float) -> float:
    expiry_value = payload.get("access_token_expires_at")
    if expiry_value is None:
        expiry_value = payload.get("expires_at")

    if isinstance(expiry_value, (int, float)):
        return float(expiry_value)

    if isinstance(expiry_value, str):
        candidate = expiry_value.strip()
        if candidate:
            try:
                return float(candidate)
            except ValueError:
                pass

            try:
                iso_value = candidate.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(iso_value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                pass

    expires_in = payload.get("access_token_expires_in")
    if expires_in is None:
        expires_in = payload.get("expires_in")

    try:
        return now + float(expires_in)
    except (TypeError, ValueError):
        return now + 3600.0


def get_login_status_text(provider: str, tier: str, stripe_status: str = "") -> str:
    provider_upper = str(provider).upper()
    tier_upper = str(tier).upper()
    stripe_status_upper = str(stripe_status).upper()

    if provider_upper == "GOOGLE":
        if is_free_trial_status(stripe_status_upper):
            return t("Logged in - Free Trial")
        if tier_upper == "T0":
            return t("Logged in - Lite")
        if tier_upper == "FL":
            return t("Logged in - Free Lite")
        if tier_upper == "T3":
            return t("Logged in - Pro")
        if tier_upper == "T2":
            return t("Logged in - Core")
        return t("Logged in")

    if provider_upper == "PATREON":
        if tier_upper == "T0":
            return t("Logged in - Lite")
        if tier_upper == "T3":
            return t("Logged in - Pro")
        if tier_upper == "T2":
            return t("Logged in - Core")
        return t("Logged in")

    return t("Logged in")


def _finish_access_token_response(prefs: Any, response) -> bool:
    if not response.ok:
        logger.warning(
            "Access-token request failed with status %s", response.status_code
        )
        detail = _extract_error_detail(response)
        if response.status_code == 401 and detail:
            error_label = _normalize_error_label(detail) or "refresh_token_revoked"
            _force_logout_for_revoked_refresh_token(prefs, error_label)
        elif response.status_code == 401:
            _force_logout_for_revoked_refresh_token(prefs, "refresh_token_revoked")
        else:
            prefs.auth_last_error = f"access_http_{response.status_code}"
        return False

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Access-token response is not valid JSON")
        prefs.auth_last_error = "access_invalid_json"
        return False
    if not isinstance(payload, dict):
        logger.warning("Access-token response JSON is not an object")
        prefs.auth_last_error = "access_invalid_payload"
        return False

    access_token = payload.get("access_token")
    if not access_token:
        logger.warning("Access-token response missing access_token")
        prefs.auth_last_error = "access_missing_token"
        return False

    now = time.time()
    expiry_ts = _parse_expiry_timestamp(payload, now)

    prefs.auth_access_token = str(access_token)
    prefs.auth_access_expires_at = expiry_ts
    prefs.auth_logged_in = True
    payload_user = payload.get("user")
    if payload_user is not None:
        prefs.auth_user_email = _extract_email(payload_user)
    payload_tier = payload.get("tier")
    if payload_tier is not None:
        prefs.auth_tier = str(payload_tier).upper()
        _apply_current_tier_scene_defaults()
    payload_stripe_status = payload.get("stripe_status")
    if payload_stripe_status is not None:
        prefs.auth_stripe_status = str(payload_stripe_status).upper()
        initialize_trial_export_counter(
            prefs,
            prefs.auth_stripe_status,
            getattr(prefs, "auth_user_email", ""),
        )
    if "pro_trial_available" in payload:
        prefs.auth_pro_trial_available = bool(payload.get("pro_trial_available"))
    prefs.auth_last_error = ""
    return True


def request_access_token(prefs: Any | None = None) -> bool:
    prefs = prefs or get_addon_preferences()
    if prefs is None or not getattr(prefs, "auth_refresh_token", ""):
        return False

    try:
        response = _oauth_request(
            _oauth_url("/auth/token/access"),
            {"refresh_token": prefs.auth_refresh_token},
        )
    except Exception:
        logger.exception("Access-token request failed")
        prefs.auth_last_error = "access_request_failed"
        return False

    return _finish_access_token_response(prefs, response)


def get_valid_access_token(force_refresh: bool = False) -> str | None:
    prefs = get_addon_preferences()
    if prefs is None:
        return None
    if not getattr(prefs, "auth_refresh_token", ""):
        return None

    now = time.time()
    access_token = getattr(prefs, "auth_access_token", "")
    access_expires_at = float(getattr(prefs, "auth_access_expires_at", 0.0))
    token_is_valid = bool(
        access_token and now < (access_expires_at - ACCESS_TOKEN_SKEW_SECONDS)
    )
    if not force_refresh and token_is_valid and getattr(prefs, "auth_logged_in", False):
        return access_token

    if request_access_token(prefs):
        return str(getattr(prefs, "auth_access_token", ""))
    return None


def _open_geometry_login_dialog():
    """Run on Blender's main thread after the failed operation unwinds."""
    from ..operator_access import _invoke_access_dialog_once

    prefs = get_addon_preferences()
    if prefs is None or (
        getattr(prefs, "auth_logged_in", False)
        and getattr(prefs, "auth_refresh_token", "")
    ):
        return None
    _invoke_access_dialog_once("silicone.auth_required_dialog")
    return None


def get_geometry_access_token(force_refresh: bool = False) -> str:
    """Recover a durable session, or route failure to the appropriate UI."""
    from ..nearest_surface_worker_client import NearestSurfaceWorkerError

    token = get_valid_access_token(force_refresh=force_refresh)
    if token:
        return token
    prefs = get_addon_preferences()
    if prefs is None:
        raise NearestSurfaceWorkerError("Moldboxer account preferences are unavailable")
    if getattr(prefs, "auth_refresh_token", ""):
        # A transient refresh failure must not masquerade as a revoked license.
        token = get_valid_access_token(force_refresh=True)
        if token:
            return token
    if getattr(prefs, "auth_refresh_token", ""):
        raise NearestSurfaceWorkerError(
            "ServiceConnectionError: Could not renew the Moldboxer session. Please try again."
        )
    raise NearestSurfaceWorkerError(
        "This operation requires the licensed Moldboxer Worker engine."
    )


def start_pro_trial() -> tuple[bool, str]:
    prefs = get_addon_preferences()
    if prefs is None:
        return False, "Addon preferences are unavailable"
    if not getattr(prefs, "auth_logged_in", False):
        return False, "Login is required before starting the Pro trial"
    if str(getattr(prefs, "auth_tier", "")).upper() != "FL":
        return False, "The Pro trial can only be started from Free Lite"

    refresh_token = str(getattr(prefs, "auth_refresh_token", ""))
    if not refresh_token:
        return False, "Login has expired; please log in again"

    try:
        response = _oauth_request(
            _oauth_url("/trial/pro/start"),
            {"refresh_token": refresh_token},
        )
    except Exception:
        logger.exception("Pro trial activation request failed")
        return False, "Could not connect to the trial service"

    if not response.ok:
        detail = _extract_error_detail(response)
        return False, detail or f"Pro trial activation failed ({response.status_code})"

    try:
        payload = response.json()
    except ValueError:
        return False, "Invalid response from the trial service"
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return False, "Invalid response from the trial service"

    prefs.auth_tier = str(payload.get("tier", "T3")).upper()
    prefs.auth_stripe_status = str(payload.get("stripe_status", "")).upper()
    prefs.auth_pro_trial_available = bool(payload.get("pro_trial_available", False))
    prefs.auth_access_token = ""
    prefs.auth_access_expires_at = 0.0
    initialize_trial_export_counter(
        prefs,
        prefs.auth_stripe_status,
        getattr(prefs, "auth_user_email", ""),
    )
    request_access_token(prefs)
    _apply_current_tier_scene_defaults()
    _persist_auth_state()
    return True, "Your 1-day Pro trial is now active"


def begin_get_valid_access_token(force_refresh: bool = False):
    """Return a pollable access-token refresh with main-thread finalization."""

    prefs = get_addon_preferences()

    def steps():
        if prefs is None:
            return None
        refresh_token = str(getattr(prefs, "auth_refresh_token", ""))
        if not refresh_token:
            return None

        now = time.time()
        access_token = str(getattr(prefs, "auth_access_token", ""))
        access_expires_at = float(
            getattr(prefs, "auth_access_expires_at", 0.0)
        )
        token_is_valid = bool(
            access_token
            and now < (access_expires_at - ACCESS_TOKEN_SKEW_SECONDS)
        )
        if not force_refresh and token_is_valid and getattr(prefs, "auth_logged_in", False):
            return access_token

        worker = acquire_geometry_worker(authorize=False)
        try:
            response = yield submit_worker_task(
                _send_oauth_request,
                worker,
                _oauth_url("/auth/token/access"),
                {"refresh_token": refresh_token},
                is_dev_mode(),
            )
        except Exception:
            logger.exception("Access-token request failed")
            prefs.auth_last_error = "access_request_failed"
            return None
        if not _finish_access_token_response(prefs, response):
            return None
        return str(getattr(prefs, "auth_access_token", ""))

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence


def _start_endpoint_paths(provider: str) -> list[str]:
    provider = provider.lower()
    paths = [f"/{provider}/start"]
    if provider == "patreon":
        paths.append("/patreon")
    return paths


def _oauth_connection_error_message(error: Exception) -> str:
    if "tls certificate verification failed" in str(error).casefold():
        return (
            "Could not verify the OAuth server's secure connection. "
            "Please install the latest Moldboxer update."
        )
    return "Failed to connect to OAuth server"


def _start_device_login(provider: str) -> tuple[bool, str]:
    prefs = get_addon_preferences()
    if prefs is None:
        return False, "Addon preferences are unavailable"

    provider = provider.lower()
    provider_label = provider.capitalize()
    device_id = uuid.uuid4().hex
    response = None
    for endpoint_path in _start_endpoint_paths(provider):
        try:
            response = _oauth_request(
                _oauth_url(endpoint_path, for_login=True),
                {"device_id": device_id},
            )
        except Exception as error:
            logger.exception("Failed to start %s device login", provider_label)
            return False, _oauth_connection_error_message(error)
        if response.ok or response.status_code != 404:
            break

    if response is None or not response.ok:
        status_code = response.status_code if response is not None else "unknown"
        logger.warning(
            "%s login start failed with status %s", provider_label, status_code
        )
        return False, f"{provider_label} login start failed ({status_code})"

    try:
        payload = response.json()
    except ValueError:
        return False, "Invalid response from OAuth server"

    device_code = payload.get("device_code")
    login_url = (
        payload.get(f"{provider}_url")
        or payload.get("google_url")
        or payload.get("url")
    )
    expires_in = payload.get("expires_in")
    if not device_code or not login_url:
        return False, "OAuth response missing device_code or login URL"

    try:
        expires_in_seconds = float(expires_in)
    except (TypeError, ValueError):
        expires_in_seconds = 600.0

    prefs.auth_last_error = ""
    prefs.auth_logged_in = False
    prefs.auth_refresh_token = ""
    prefs.auth_user_email = ""
    prefs.auth_tier = ""
    prefs.auth_stripe_status = ""
    prefs.auth_provider = ""
    prefs.auth_access_token = ""
    prefs.auth_access_expires_at = 0.0
    prefs.auth_device_code = str(device_code)
    prefs.auth_device_expires_at = time.time() + expires_in_seconds
    prefs.auth_polling_active = True
    prefs.auth_pending_provider = provider.upper()
    _persist_auth_state()

    bpy.ops.wm.url_open(url=str(login_url))
    is_registered = getattr(bpy.app.timers, "is_registered", None)
    if callable(is_registered):
        if not is_registered(poll_google_login):
            bpy.app.timers.register(
                poll_google_login, first_interval=POLL_INTERVAL_SECONDS
            )
    else:
        bpy.app.timers.register(poll_google_login, first_interval=POLL_INTERVAL_SECONDS)
    return True, f"Opened {provider_label} sign-in page"


def start_google_device_login() -> tuple[bool, str]:
    return _start_device_login("google")


def start_patreon_device_login() -> tuple[bool, str]:
    return _start_device_login("patreon")


def poll_google_login() -> float | None:
    prefs = get_addon_preferences()
    if prefs is None:
        return None

    if not getattr(prefs, "auth_polling_active", False):
        return None

    device_code = getattr(prefs, "auth_device_code", "")
    if not device_code:
        _clear_pending_state(prefs)
        _persist_auth_state()
        return None

    if time.time() > float(getattr(prefs, "auth_device_expires_at", 0.0)):
        prefs.auth_last_error = "expired"
        _clear_pending_state(prefs)
        _persist_auth_state()
        return None

    try:
        response = _oauth_request(
            _oauth_url("/auth/device/poll", for_login=True),
            {"device_code": device_code},
        )
    except Exception:
        logger.exception("Polling OAuth device login failed")
        return POLL_INTERVAL_SECONDS

    payload: dict[str, Any] = {}
    try:
        payload = response.json()
    except ValueError:
        logger.warning("OAuth poll returned non-JSON payload")

    status = payload.get("status")

    if response.status_code == 202 and status == "pending":
        return POLL_INTERVAL_SECONDS
    if status == "pending":
        return POLL_INTERVAL_SECONDS

    if status == "approved":
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            prefs.auth_last_error = "missing_refresh_token"
            _clear_pending_state(prefs)
            _persist_auth_state()
            return None

        prefs.auth_refresh_token = str(refresh_token)
        prefs.auth_user_email = _extract_email(payload.get("user"))
        prefs.auth_tier = str(payload.get("tier", "")).upper()
        prefs.auth_stripe_status = str(payload.get("stripe_status", "")).upper()
        prefs.auth_pro_trial_available = bool(
            payload.get("pro_trial_available", False)
        )
        initialize_trial_export_counter(
            prefs, prefs.auth_stripe_status, prefs.auth_user_email
        )
        prefs.auth_provider = str(getattr(prefs, "auth_pending_provider", "")).upper()
        prefs.auth_logged_in = True
        prefs.auth_last_error = ""
        _clear_pending_state(prefs, keep_generation=True)

        # Requirement: fetch an access token as soon as approval arrives.
        request_access_token(prefs)
        _apply_current_tier_scene_defaults()
        _persist_auth_state()
        schedule_generation_resume()
        return None

    if status in {
        "failed",
        "expired",
        "not_found",
        "not_ready",
        "cancelled",
        "canceled",
        "denied",
        "access_denied",
    }:
        prefs.auth_last_error = str(status)
        _clear_pending_state(prefs)
        _persist_auth_state()
        return None

    if response.status_code == 202:
        return POLL_INTERVAL_SECONDS

    prefs.auth_last_error = str(status or f"http_{response.status_code}")
    _clear_pending_state(prefs)
    _persist_auth_state()
    return None


def initialize_auth_state_on_startup() -> None:
    prefs = get_addon_preferences()
    if prefs is None:
        return

    has_refresh_token = bool(getattr(prefs, "auth_refresh_token", ""))
    is_logged_in_flag = bool(getattr(prefs, "auth_logged_in", False))
    is_waiting = bool(getattr(prefs, "auth_polling_active", False))

    if is_waiting:
        device_code = str(getattr(prefs, "auth_device_code", "")).strip()
        expires_at = float(getattr(prefs, "auth_device_expires_at", 0.0))
        pending_is_valid = bool(device_code and time.time() <= expires_at)

        # If we already have a persisted session, pending state is stale.
        if has_refresh_token or is_logged_in_flag:
            _clear_pending_state(prefs)
        elif pending_is_valid:
            is_registered = getattr(bpy.app.timers, "is_registered", None)
            if callable(is_registered):
                if not is_registered(poll_google_login):
                    bpy.app.timers.register(
                        poll_google_login, first_interval=POLL_INTERVAL_SECONDS
                    )
            else:
                bpy.app.timers.register(
                    poll_google_login, first_interval=POLL_INTERVAL_SECONDS
                )
        else:
            _clear_pending_state(prefs)

    # Restore logged-in state from persisted refresh token after restart.
    if has_refresh_token and not getattr(prefs, "auth_logged_in", False):
        prefs.auth_logged_in = True

    # Recover from impossible persisted state.
    if not has_refresh_token and getattr(prefs, "auth_logged_in", False):
        _clear_login_state(prefs)

    _apply_current_tier_scene_defaults()
