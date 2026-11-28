"""Hard block for outbound network connections made by the add-on process."""

import ipaddress
import socket
import threading

_ENABLED = True
_LOCK = threading.Lock()
_original_connect = None
_original_create_connection = None


def is_enabled() -> bool:
    return _ENABLED


def set_enabled(enabled: bool) -> None:
    global _ENABLED
    with _LOCK:
        _ENABLED = bool(enabled)


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        return True
    text = str(host).strip().strip("[]").lower()
    if not text or text == "localhost":
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _is_local_address(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True
    return _is_loopback_host(address[0])


def _guarded_connect(self, address, *args, **kwargs):
    if _ENABLED and not _is_local_address(address):
        raise OSError(
            "MoldboxerPATCHED offline mode: outbound connections are blocked"
        )
    return _original_connect(self, address, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    if _ENABLED and not _is_local_address(address):
        raise OSError(
            "MoldboxerPATCHED offline mode: outbound connections are blocked"
        )
    return _original_create_connection(address, *args, **kwargs)


def install() -> None:
    global _original_connect, _original_create_connection
    if _original_connect is not None:
        return
    _original_connect = socket.socket.connect
    socket.socket.connect = _guarded_connect
    _original_create_connection = socket.create_connection
    socket.create_connection = _guarded_create_connection


def uninstall() -> None:
    global _original_connect, _original_create_connection
    if _original_connect is None:
        return
    socket.socket.connect = _original_connect
    _original_connect = None
    if _original_create_connection is not None:
        socket.create_connection = _original_create_connection
        _original_create_connection = None
