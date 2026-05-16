# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Shared SSL/TLS primitives for HSYNC projects.

Low-level helpers for self-signed certificate generation, PEM serialization
and fingerprint handling. Higher-level wrappers (LAN P2P certs in the client,
file-backed server certs in the server) live in the consumer projects.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
from datetime import UTC, datetime, timedelta
from typing import Sequence

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from loguru import logger as log

# Default RSA key size in bits (good security/performance balance).
DEFAULT_KEY_SIZE = 2048


def generate_rsa_private_key(key_size: int = DEFAULT_KEY_SIZE) -> rsa.RSAPrivateKey:
    """Generate an RSA private key suitable for self-signed certificates."""
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size)


def build_self_signed_certificate(
    private_key: rsa.RSAPrivateKey,
    subject_attrs: Sequence[x509.NameAttribute],
    san_list: Sequence[x509.GeneralName],
    validity_days: int,
    *,
    basic_constraints_ca: bool = False,
) -> x509.Certificate:
    """
    Build a self-signed X.509 certificate.

    Args:
        private_key: The RSA private key used to sign the certificate.
        subject_attrs: Name attributes for both subject and issuer.
        san_list: Subject Alternative Names (DNS names, IP addresses, ...).
        validity_days: Days the certificate is valid for.
        basic_constraints_ca: When True, mark the certificate as a CA with
            ``path_length=0`` (used for server-side self-signed certs).

    Returns:
        The signed :class:`x509.Certificate`.
    """
    subject = issuer = x509.Name(list(subject_attrs))

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(
            x509.SubjectAlternativeName(list(san_list)),
            critical=False,
        )
    )

    if basic_constraints_ca:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )

    return builder.sign(private_key, hashes.SHA256())


def serialize_cert_pem(cert: x509.Certificate) -> bytes:
    """Serialize an X.509 certificate to PEM bytes."""
    return cert.public_bytes(serialization.Encoding.PEM)


def serialize_key_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    """Serialize an RSA private key to unencrypted PEM bytes."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


def compute_cert_fingerprint(cert: x509.Certificate) -> str:
    """Return the SHA-256 fingerprint (hex) of a certificate's DER encoding."""
    der = cert.public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


def verify_cert_fingerprint(cert_der: bytes, expected_fingerprint: str) -> bool:
    """Compare a DER-encoded certificate's SHA-256 fingerprint to the expected one."""
    actual = hashlib.sha256(cert_der).hexdigest()
    return actual.lower() == expected_fingerprint.lower()


def get_server_cert_fingerprint(
    host: str,
    port: int,
    timeout: float = 5.0,
) -> str | None:
    """
    Fetch the SHA-256 fingerprint of a remote server's TLS certificate.

    Returns ``None`` on any connection or handshake error.
    """
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                if cert_der:
                    return hashlib.sha256(cert_der).hexdigest()
    except Exception as e:
        log.debug(f"Error getting server certificate: {e}")

    return None
