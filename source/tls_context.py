# SPDX-FileCopyrightText: 2026 MOLDBOXER, S.L.
# SPDX-License-Identifier: MIT

"""Shared TLS trust configuration for Moldboxer HTTPS clients."""

from __future__ import annotations

from pathlib import Path
import ssl


def bundled_ca_file() -> Path:
    """Return the CA bundle supplied by the pinned certifi dependency."""

    import certifi

    ca_file = Path(certifi.where()).resolve()
    if not ca_file.is_file():
        raise RuntimeError("Moldboxer CA bundle is missing")
    return ca_file


def create_moldboxer_ssl_context() -> ssl.SSLContext:
    """Verify servers against the bundled roots, without implicit system CAs."""

    # Loading Windows' default CA/intermediate stores first can select a broken
    # issuer chain even after certifi is added. Supply the bundle at creation:
    # this retains hostname/certificate verification without merging those stores.
    return ssl.create_default_context(cafile=str(bundled_ca_file()))
