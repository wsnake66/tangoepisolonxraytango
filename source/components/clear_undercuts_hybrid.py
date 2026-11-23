"""Blender-side credentials bridge for protected Clear Undercuts planning."""

from __future__ import annotations

from ..background_worker import BackgroundTaskSequence
from ..environment import is_dev_mode
from .auth import begin_get_valid_access_token, get_valid_access_token
from .server import (
    AuthorizationError,
    SERVER_JSON_REQUEST_TIMEOUT_SECONDS,
    SERVER_REQUEST_MAX_ATTEMPTS,
    SERVER_REQUEST_RETRY_BACKOFF_SECONDS,
)


def worker_server_request_config(
    access_token=None,
    *,
    refresh_if_missing: bool = True,
) -> dict:
    """Return short-lived request credentials for the local worker process."""

    if access_token is None and refresh_if_missing:
        access_token = get_valid_access_token()
    access_token = str(access_token or "").strip()
    if not access_token:
        raise AuthorizationError("Missing access token. Please log in again.")
    if access_token.casefold().startswith("bearer "):
        access_token = access_token[7:].strip()
    if not access_token:
        raise AuthorizationError("Invalid access token. Please log in again.")
    return {
        "access_token": access_token,
        "dev_requested": is_dev_mode(),
        "timeout_seconds": float(SERVER_JSON_REQUEST_TIMEOUT_SECONDS),
        "max_attempts": int(SERVER_REQUEST_MAX_ATTEMPTS),
        "retry_backoff_seconds": float(
            SERVER_REQUEST_RETRY_BACKOFF_SECONDS
        ),
    }


def begin_worker_server_request_config() -> BackgroundTaskSequence:
    """Refresh worker request credentials without blocking Blender's UI."""

    def steps():
        access_token = yield begin_get_valid_access_token()
        return worker_server_request_config(
            access_token,
            refresh_if_missing=False,
        )

    sequence = BackgroundTaskSequence(steps())
    sequence.redraw_interval = 0.1
    return sequence
