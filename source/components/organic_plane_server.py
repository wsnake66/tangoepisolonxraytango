"""Authenticated remote geometry boundary for coarse organic-plane operations."""

from __future__ import annotations

from ..environment import get_server_base_url
from .server import request_server_json


ORGANIC_PLANE_PATH = "/organic-plane/"
_SERVER_OPERATIONS = frozenset({"create_surface", "top_profile", "cutter_mesh"})


def request_organic_plane(operation: str, **arguments) -> dict:
    """Run one infrequent organic-plane operation on the Moldboxer server."""

    operation = str(operation)
    if operation not in _SERVER_OPERATIONS:
        raise ValueError(f"Unsupported organic-plane server operation: {operation!r}")
    result = request_server_json(
        f"{get_server_base_url()}{ORGANIC_PLANE_PATH}",
        {"operation": operation, "arguments": arguments},
    )
    if not isinstance(result, dict):
        raise RuntimeError("Server returned invalid organic-plane data")
    return result
