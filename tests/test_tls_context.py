# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for hsync_common.tls_context — the shared client TLS policies."""

from __future__ import annotations

import ssl

import pytest

from hsync_common.tls_context import (
    disable_certificate_verification,
    unverified_ssl_context,
    verified_ssl_context,
)


class TestUnverified:
    def test_disables_chain_and_hostname(self):
        context = unverified_ssl_context()
        assert context.verify_mode == ssl.CERT_NONE
        assert context.check_hostname is False

    def test_disable_certificate_verification_returns_the_same_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        assert disable_certificate_verification(context) is context


class TestVerified:
    def test_default_uses_the_system_ca(self):
        context = verified_ssl_context()
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_a_missing_anchor_raises_for_the_caller(self):
        # The helper does not swallow: the caller keeps its own error policy for
        # a missing/unreadable CA file.
        with pytest.raises((OSError, ssl.SSLError)):
            verified_ssl_context("/nonexistent/ca.pem")
