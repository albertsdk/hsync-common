# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Lightweight client TLS contexts (stdlib ``ssl`` only).

These helpers disable chain/hostname verification for the TOFU/pinning model
(the caller establishes trust on the same connection: a pinned certificate
fingerprint, or an explicit ``--insecure`` opt-in). They live in their own
stdlib-only module — separate from :mod:`hsync_common.ssl_utils`, which imports
``cryptography`` — so a consumer on a startup fast path (the CLI) can build an
unverified context without pulling the certificate toolkit.
"""

from __future__ import annotations

import ssl

__all__ = [
    "disable_certificate_verification",
    "unverified_ssl_context",
]


def disable_certificate_verification(context: ssl.SSLContext) -> ssl.SSLContext:
    """Turn off chain and hostname verification on *context*.

    Trust must then be established by the caller on the *same* connection. The
    assignment order matters: ``PROTOCOL_TLS_CLIENT`` sets
    ``check_hostname=True``, so setting ``verify_mode`` first raises.
    """
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def unverified_ssl_context() -> ssl.SSLContext:
    """A default client context with chain/hostname verification disabled."""
    return disable_certificate_verification(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
