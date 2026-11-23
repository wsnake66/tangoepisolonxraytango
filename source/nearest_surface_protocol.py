# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: MIT

"""Small framed-binary protocol shared by the nearest-surface worker and client."""

from __future__ import annotations

import json
import struct
import sys
import time


_LENGTH = struct.Struct("<I")
_MAX_HEADER_BYTES = 1_048_576
# Reserved transport envelope. Both endpoints ship this module together.
_BODY_HEADER_BYTES = "__moldboxer_body_header_bytes__"


def _make_authorization_clock():
    """Select a wall-clock-independent clock that includes system suspend.

    This clock is for client cache hints only. The protected worker owns its
    own clock implementation; it never trusts this client-side helper.
    """
    if sys.platform == "win32":
        import ctypes

        ticks = ctypes.WinDLL("kernel32", use_last_error=True).GetTickCount64
        ticks.argtypes = []
        ticks.restype = ctypes.c_ulonglong
        return lambda: ticks() / 1000.0
    if sys.platform == "darwin":
        import ctypes

        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

        lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        info = Timebase()
        lib.mach_timebase_info.argtypes = [ctypes.POINTER(Timebase)]
        lib.mach_timebase_info.restype = ctypes.c_int
        if lib.mach_timebase_info(ctypes.byref(info)) != 0 or not info.denom:
            raise RuntimeError("Unable to initialize authorization clock")
        ticks = lib.mach_continuous_time
        ticks.argtypes = []
        ticks.restype = ctypes.c_uint64
        scale = info.numer / info.denom / 1_000_000_000.0
        return lambda: ticks() * scale
    if hasattr(time, "CLOCK_BOOTTIME"):
        return lambda: time.clock_gettime(time.CLOCK_BOOTTIME)
    raise RuntimeError("No suspend-aware authorization clock on this platform")


_authorization_clock = None


def authorization_clock() -> float:
    global _authorization_clock
    if _authorization_clock is None:
        _authorization_clock = _make_authorization_clock()
    return _authorization_clock()


def _read_exact(stream, byte_count: int) -> bytearray:
    """Read one frame directly into its final mutable backing buffer."""

    byte_count = int(byte_count)
    if byte_count < 0:
        raise ValueError("nearest-surface worker read length is negative")
    buffer = bytearray(byte_count)
    view = memoryview(buffer)
    offset = 0
    readinto = getattr(stream, "readinto", None)
    while offset < byte_count:
        if callable(readinto):
            read_count = readinto(view[offset:])
        else:
            chunk = stream.read(byte_count - offset)
            read_count = len(chunk) if chunk else 0
            if read_count:
                view[offset : offset + read_count] = chunk
        if not read_count:
            raise EOFError("nearest-surface worker pipe closed unexpectedly")
        offset += int(read_count)
    return buffer


def read_message(stream) -> tuple[dict, bytearray]:
    header_length = _LENGTH.unpack(_read_exact(stream, _LENGTH.size))[0]
    if header_length > _MAX_HEADER_BYTES:
        raise ValueError(
            "nearest-surface worker incoming header is too large: "
            f"bytes={header_length} limit={_MAX_HEADER_BYTES}"
        )
    header = json.loads(_read_exact(stream, header_length).decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("nearest-surface worker header must be an object")
    payload_bytes = int(header.get("payload_bytes", 0))
    if payload_bytes < 0:
        raise ValueError("nearest-surface worker payload length is negative")
    if _BODY_HEADER_BYTES in header:
        metadata_bytes = header[_BODY_HEADER_BYTES]
        if (type(metadata_bytes) is not int
                or metadata_bytes <= 0 or metadata_bytes > payload_bytes):
            raise ValueError("nearest-surface worker invalid body header length")
        header = json.loads(_read_exact(stream, metadata_bytes))
        if not isinstance(header, dict) or _BODY_HEADER_BYTES in header:
            raise ValueError("nearest-surface worker invalid body header")
        payload_bytes -= metadata_bytes
        if header.get("payload_bytes") != payload_bytes:
            raise ValueError("nearest-surface worker body payload length mismatch")
    # Keep binary arrays in their own mutable buffer, without a second copy.
    return header, _read_exact(stream, payload_bytes)


def write_message(stream, header: dict, *payload_parts) -> None:
    if _BODY_HEADER_BYTES in header:
        raise ValueError("nearest-surface worker reserved transport field")
    views = []
    for part in payload_parts:
        view = memoryview(part)
        # Python cannot cast an ndarray view when any dimension is zero.
        # Mixed voxel surfaces commonly have no triangles or no quads.
        views.append(view.cast("B") if view.nbytes else memoryview(b""))
    message_header = dict(header)
    message_header["payload_bytes"] = sum(view.nbytes for view in views)
    encoded_header = json.dumps(
        message_header,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded_header) > _MAX_HEADER_BYTES:
        # Policies, component summaries, candidate lists and errors can grow
        # with the model. Put their JSON in the body instead of increasing the
        # framing-header limit or making each command invent its own workaround.
        body_header = encoded_header
        encoded_header = json.dumps({
            _BODY_HEADER_BYTES: len(body_header),
            "payload_bytes": len(body_header) + message_header["payload_bytes"],
        }, separators=(",", ":")).encode("utf-8")
        views.insert(0, memoryview(body_header))
    stream.write(_LENGTH.pack(len(encoded_header)))
    stream.write(encoded_header)
    for view in views:
        stream.write(view)
    stream.flush()
