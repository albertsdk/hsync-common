# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared SSL/TLS primitives for HSYNC projects.

Low-level helpers for self-signed certificate generation, PEM serialization
and fingerprint handling. Higher-level wrappers (p2p certs in the client,
file-backed server certs in the server) live in the consumer projects.

Service identities (the bootnode node key and the server TLS certificate)
follow one shared model (ADR-0037): ECDSA P-256, an unencrypted PKCS#8 key
guarded by ``0o600``/``0o700`` filesystem permissions instead of a passphrase,
a :data:`SERVICE_CERT_VALIDITY_DAYS` (20-year) lifetime with a backdated
``NotBefore``, and rotation announced by fingerprint.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

# Default RSA key size in bits (good security/performance balance).
DEFAULT_KEY_SIZE = 2048

# Validity of a long-lived, self-signed *service* identity (bootnode node key,
# server TLS certificate): 20 years. Such an identity is authenticated by a
# pinned certificate fingerprint, not by a public CA or a browser trust store,
# so the Apple/CA-Browser-Forum 825-day cap does not apply — it exists only to
# bound WebPKI exposure. A pinned identity (SSH host key / Syncthing device key
# model) should live for the lifetime of the deployment; Syncthing hardcodes 20
# years for exactly this case. 7305 = 20 * 365 + 5 (leap-day allowance).
# Consumers: ``hsync-bootnode``, ``hsync-server`` (ADR-0037).
SERVICE_CERT_VALIDITY_DAYS = 7305

# NotBefore is backdated by one day so a freshly generated certificate is still
# valid on a peer whose clock lags behind the issuer's (small clock skew).
_CERT_NOT_BEFORE_BACKDATE = timedelta(days=1)

# The certificate builder accepts any of these key types. HSYNC *service*
# identities are always ECDSA P-256 (ADR-0037); RSA and Ed25519 generators exist
# only for the builder's tests.
PrivateKey = rsa.RSAPrivateKey | ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey


def generate_rsa_private_key(key_size: int = DEFAULT_KEY_SIZE) -> rsa.RSAPrivateKey:
    """Generate an RSA private key suitable for self-signed certificates."""
    return rsa.generate_private_key(public_exponent=65537, key_size=key_size)


def generate_ecdsa_private_key() -> ec.EllipticCurvePrivateKey:
    """Generate an ECDSA P-256 private key.

    P-256 (secp256r1) is the standard key type for HSYNC service identities
    (bootnode node key, server TLS certificate — ADR-0034/ADR-0037): it is
    advertised by every mainstream TLS stack (BoringSSL/OpenSSL/rustls), unlike
    Ed25519 which BoringSSL omits from the default client signature algorithms.
    Certificates are signed with SHA-256. Consumers: ``hsync-bootnode``
    (ephemeral and persistent identity), ``hsync-server``, tests.
    """
    return ec.generate_private_key(ec.SECP256R1())


def generate_ed25519_private_key() -> ed25519.Ed25519PrivateKey:
    """Generate an Ed25519 private key.

    Not used for HSYNC service identities (those are ECDSA P-256, ADR-0037), but
    supported by the certificate builder and exercised by tests. Consumers:
    tests, and callers that explicitly want an Ed25519 identity.
    """
    return ed25519.Ed25519PrivateKey.generate()


def build_self_signed_certificate(
    private_key: PrivateKey,
    subject_attrs: Sequence[x509.NameAttribute],
    san_list: Sequence[x509.GeneralName],
    validity_days: int,
    *,
    basic_constraints_ca: bool = False,
) -> x509.Certificate:
    """
    Build a self-signed X.509 certificate.

    Args:
        private_key: The RSA, ECDSA, or Ed25519 private key used to sign the certificate.
        subject_attrs: Name attributes for both subject and issuer.
        san_list: Subject Alternative Names (DNS names, IP addresses, ...).
        validity_days: Days the certificate is valid for. Pass
            :data:`SERVICE_CERT_VALIDITY_DAYS` for a long-lived, pinned service
            identity (bootnode/server); the value only bounds the certificate's
            own lifetime, since such identities never rely on WebPKI validity.
        basic_constraints_ca: When True, mark the certificate as a CA with
            ``path_length=0`` (used for server-side self-signed certs).

    Returns:
        The signed :class:`x509.Certificate`. ``NotBefore`` is backdated by one
        day (see ``_CERT_NOT_BEFORE_BACKDATE``) to tolerate clock skew.
    """
    subject = issuer = x509.Name(list(subject_attrs))

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _CERT_NOT_BEFORE_BACKDATE)
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

    # Ed25519 is a fixed scheme with no hash parameter; RSA/ECDSA sign over SHA-256.
    signature_algorithm: hashes.HashAlgorithm | None = (
        None if isinstance(private_key, ed25519.Ed25519PrivateKey) else hashes.SHA256()
    )
    return builder.sign(private_key, signature_algorithm)


def serialize_cert_pem(cert: x509.Certificate) -> bytes:
    """Serialize an X.509 certificate to PEM bytes."""
    return cert.public_bytes(serialization.Encoding.PEM)


def serialize_private_key_unencrypted(private_key: PrivateKey) -> bytes:
    """Serialize an RSA, ECDSA, or Ed25519 private key to *unencrypted* PKCS#8 PEM bytes.

    Intended for long-lived self-signed service identities whose confidentiality
    is enforced by filesystem permissions (``0o600`` in a ``0o700`` directory)
    rather than a passphrase — the standard model for SSH host keys and
    Syncthing device keys. Identity is established by fingerprint pinning, not by
    an encrypted-at-rest secret, so there is no co-located password to protect.
    The caller is responsible for writing the result with restrictive
    permissions.

    Consumers: ``hsync-bootnode`` (persistent node identity), ``hsync-server``
    (server TLS certificate), ``hsync-client`` (P2P certificate), tests.
    """
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def compute_cert_fingerprint(cert: x509.Certificate) -> str:
    """Return the SHA-256 fingerprint (hex) of a certificate's DER encoding."""
    return fingerprint_from_der(cert.public_bytes(serialization.Encoding.DER))


def fingerprint_from_der(cert_der: bytes) -> str:
    """Return the SHA-256 fingerprint (hex) of a DER-encoded certificate.

    Used where only the raw DER bytes are available (a stdlib TLS handshake's
    ``getpeercert(binary_form=True)`` or a PEM converted with
    ``ssl.PEM_cert_to_DER_cert``): the client's server TLS probe and WSS pin, and
    the server's ``admin tls fingerprint`` command.

    Consumers: ``hsync-client`` (``server_trust.fetch_server_fingerprint``,
    ``remote_websocket``), ``hsync-server`` (``admin tls fingerprint``), tests.
    """
    return hashlib.sha256(cert_der).hexdigest()


def verify_cert_fingerprint(cert_der: bytes, expected_fingerprint: str) -> bool:
    """Compare a DER-encoded certificate's SHA-256 fingerprint to the expected one."""
    return fingerprint_from_der(cert_der).lower() == expected_fingerprint.lower()
