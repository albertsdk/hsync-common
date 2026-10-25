# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Shared SSL/TLS primitives for HSYNC projects.

Low-level helpers for self-signed certificate generation, PEM serialization
and fingerprint handling, plus the two identity operations every service
shares (:func:`create_service_identity` for rotation,
:func:`load_or_create_service_identity` for normal startup). Consumers only
supply their subject/SAN/file-name parameters.

Service identities (the bootnode node key, the server TLS certificate and the
client's P2P master certificate) follow one shared model (ADR-0037): ECDSA
P-256, an unencrypted PKCS#8 key guarded by ``0o600``/``0o700`` filesystem
permissions instead of a passphrase, a :data:`SERVICE_CERT_VALIDITY_DAYS`
(20-year) lifetime with a backdated ``NotBefore``, and rotation announced by
fingerprint.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

# Default RSA key size in bits (good security/performance balance).
DEFAULT_KEY_SIZE = 2048

# Identity file permissions. The private key is always owner-only inside an
# owner-only directory; the certificate is world-readable only when another
# process must be served it (the sync server), and stays owner-only for the
# client's P2P identity.
KEY_FILE_MODE = 0o600
PUBLIC_CERT_FILE_MODE = 0o644
IDENTITY_DIR_MODE = 0o700

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


def write_pem_keypair(
    cert_pem: bytes,
    key_pem: bytes,
    cert_path: str | os.PathLike[str],
    key_path: str | os.PathLike[str],
    *,
    cert_mode: int = KEY_FILE_MODE,
    key_mode: int = KEY_FILE_MODE,
    create_parents: bool = True,
    chmod_parents: bool = False,
) -> None:
    """Write an identity pair with permission-enforced files.

    Missing parent directories are created with :data:`IDENTITY_DIR_MODE` so the
    key never sits in a directory other users can traverse. ``chmod_parents``
    also tightens an *existing* parent (the client keeps its device directory
    ``0o700`` unconditionally); the server leaves an operator-provided
    certificate directory untouched. The key is written first, so a crash
    between the two writes leaves the secret protected and no half identity that
    a later load would accept (callers load only when both files exist).

    Consumers: ``hsync-server`` (server TLS certificate), ``hsync-client``
    (P2P master identity), tests.
    """
    cert = Path(cert_path)
    key = Path(key_path)
    if create_parents or chmod_parents:
        for parent in {cert.parent, key.parent}:
            if not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
                os.chmod(parent, IDENTITY_DIR_MODE)
            elif chmod_parents:
                os.chmod(parent, IDENTITY_DIR_MODE)
    key.write_bytes(key_pem)
    os.chmod(key, key_mode)
    cert.write_bytes(cert_pem)
    os.chmod(cert, cert_mode)


def load_pem_keypair(
    cert_path: str | os.PathLike[str],
    key_path: str | os.PathLike[str],
    *,
    subject: str = "identity",
) -> tuple[bytes, bytes, str]:
    """Read a persisted identity pair; return cert PEM, key PEM and fingerprint.

    The key must be an ECDSA private key (ADR-0037). A non-EC key is rejected
    rather than silently used: the identity model is pinned, so an old or
    foreign keypair must be deleted and regenerated, and a clear error is the
    only safe behaviour. ``subject`` names the identity in the error message
    (e.g. ``"P2P master identity"``).

    Consumers: ``hsync-client`` (P2P master identity), tests.
    """
    cert_bytes = Path(cert_path).read_bytes()
    key_bytes = Path(key_path).read_bytes()
    cert = x509.load_pem_x509_certificate(cert_bytes)
    key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError(
            f"{subject} {Path(key_path)} must hold an ECDSA P-256 private "
            "key; delete the keypair to regenerate it under the current model."
        )
    return cert_bytes, key_bytes, compute_cert_fingerprint(cert)


def load_pem_certificate_and_key(
    cert_path: str | os.PathLike[str],
    key_path: str | os.PathLike[str],
) -> tuple[x509.Certificate, PrivateKey]:
    """Parse a PEM certificate and its unencrypted private key (no match check).

    Used by the rotation commands to re-read what they just wrote, so the
    reported fingerprint comes from a freshly parsed certificate rather than the
    serialized bytes; pair consistency is checked separately with
    :func:`verify_keypair_matches`.

    Consumers: ``hsync-server`` (``admin tls rotate``), ``hsync-bootnode``
    (``identity rotate``).
    """
    certificate = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    private_key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    return certificate, private_key


def public_keys_match(certificate: x509.Certificate, private_key: PrivateKey) -> bool:
    """True when ``private_key`` is the key behind ``certificate``'s public key.

    Both public keys are serialized to DER SubjectPublicKeyInfo and compared, so
    a keypair that pairs a certificate with a different key (a corrupted or
    hand-edited file, or a half-completed rotation) is refused with a clear error
    instead of failing later inside a TLS handshake.

    Consumers: ``hsync-bootnode`` (identity load), tests.
    """
    cert_public = certificate.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    file_public = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return cert_public == file_public


def verify_keypair_matches(
    certificate: x509.Certificate,
    private_key: PrivateKey,
    *,
    who: str = "service identity",
) -> None:
    """Raise :class:`ValueError` unless *private_key* matches *certificate*.

    Called right after a rotation writes a new keypair, so a half-completed or
    corrupted write is reported at the command instead of surfacing as handshake
    failures (or, worse, as a silently announced fingerprint the process cannot
    serve).

    Consumers: ``hsync-server`` (``admin tls rotate``), ``hsync-bootnode``
    (``identity rotate``), tests.
    """
    if not public_keys_match(certificate, private_key):
        raise ValueError(f"{who} private key does not match its certificate")


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    """A persisted self-signed service keypair plus its fingerprint.

    Attributes:
        cert_pem: Certificate PEM bytes (as loaded or generated).
        key_pem: Unencrypted PKCS#8 private-key PEM bytes.
        fingerprint: ``sha256:<hex>``-style bare hex digest of the certificate
            (see :func:`compute_cert_fingerprint`).
        cert_file: Path the certificate was read from / written to.
        key_file: Path the private key was read from / written to.
        created: ``True`` when this call generated the keypair, ``False`` when
            an existing one was loaded (consumers log the distinction).
        not_valid_after: Certificate expiry (UTC), for operator warnings.

    Consumers: ``hsync-server`` (``ssl_utils.ensure_certificates``),
    ``hsync-client`` (``ssl_utils.load_or_create_master_cert``), tests.
    """

    cert_pem: bytes
    key_pem: bytes
    fingerprint: str
    cert_file: str
    key_file: str
    created: bool
    not_valid_after: datetime


def create_service_identity(
    cert_path: str | os.PathLike[str],
    key_path: str | os.PathLike[str],
    *,
    subject_attrs: Sequence[x509.NameAttribute],
    san_list: Sequence[x509.GeneralName],
    validity_days: int = SERVICE_CERT_VALIDITY_DAYS,
    cert_mode: int = KEY_FILE_MODE,
    chmod_parents: bool = False,
) -> ServiceIdentity:
    """Generate and persist a fresh ECDSA P-256 service identity (overwrites).

    The single *generation* implementation: a bootnode/server/client identity
    differs only in its subject, SANs, file names and certificate mode, so this
    function takes those as parameters instead of being copied per project.
    Used directly by rotation paths that must always regenerate.

    Args:
        cert_path: Destination of the certificate PEM.
        key_path: Destination of the unencrypted PKCS#8 private key.
        subject_attrs: X.509 name attributes for subject and issuer.
        san_list: Subject Alternative Names.
        validity_days: Certificate lifetime; pass
            :data:`SERVICE_CERT_VALIDITY_DAYS` for a pinned identity.
        cert_mode: File mode for the certificate (owner-only for P2P, world
            readable when another process must be served it).
        chmod_parents: Also tighten an *existing* parent directory to
            :data:`IDENTITY_DIR_MODE` (client device dir).

    Returns:
        The generated :class:`ServiceIdentity` with ``created=True``.

    Raises:
        OSError: If the files cannot be written.
    """
    private_key = generate_ecdsa_private_key()
    certificate = build_self_signed_certificate(
        private_key,
        subject_attrs=subject_attrs,
        san_list=san_list,
        validity_days=validity_days,
    )
    cert_pem = serialize_cert_pem(certificate)
    key_pem = serialize_private_key_unencrypted(private_key)
    write_pem_keypair(
        cert_pem,
        key_pem,
        cert_path,
        key_path,
        cert_mode=cert_mode,
        key_mode=KEY_FILE_MODE,
        chmod_parents=chmod_parents,
    )
    return ServiceIdentity(
        cert_pem=cert_pem,
        key_pem=key_pem,
        fingerprint=compute_cert_fingerprint(certificate),
        cert_file=str(cert_path),
        key_file=str(key_path),
        created=True,
        not_valid_after=certificate.not_valid_after_utc,
    )


def load_or_create_service_identity(
    cert_path: str | os.PathLike[str],
    key_path: str | os.PathLike[str],
    *,
    subject_attrs: Sequence[x509.NameAttribute],
    san_list: Sequence[x509.GeneralName],
    validity_days: int = SERVICE_CERT_VALIDITY_DAYS,
    subject: str = "service identity",
    cert_mode: int = KEY_FILE_MODE,
    chmod_parents: bool = False,
) -> ServiceIdentity:
    """Load the persisted keypair at the given paths, generating it on first use.

    Single definition of the load-or-create skeleton shared by every HSYNC
    service identity: ``both files exist`` → load; otherwise generate (see
    :func:`create_service_identity`). Consumers only supply their identity
    parameters, so the "a partial pair is never accepted" rule and the key-first
    write order cannot drift.

    Args:
        cert_path: Certificate PEM path.
        key_path: Private-key PEM path.
        subject_attrs: X.509 name attributes used when generating.
        san_list: Subject Alternative Names used when generating.
        validity_days: Certificate lifetime used when generating.
        subject: Name of the identity in error messages (e.g.
            ``"P2P master identity"``).
        cert_mode: File mode for the certificate.
        chmod_parents: Also tighten an existing parent directory.

    Returns:
        The loaded or generated :class:`ServiceIdentity`; ``created`` says which.

    Raises:
        ValueError: When an existing key is not ECDSA P-256 (see
            :func:`load_pem_keypair`).
        OSError: If an existing pair cannot be read or a new one written.
    """
    cert = Path(cert_path)
    key = Path(key_path)
    if cert.exists() and key.exists():
        cert_pem, key_pem, fingerprint = load_pem_keypair(cert, key, subject=subject)
        certificate = x509.load_pem_x509_certificate(cert_pem)
        return ServiceIdentity(
            cert_pem=cert_pem,
            key_pem=key_pem,
            fingerprint=fingerprint,
            cert_file=str(cert),
            key_file=str(key),
            created=False,
            not_valid_after=certificate.not_valid_after_utc,
        )
    return create_service_identity(
        cert,
        key,
        subject_attrs=subject_attrs,
        san_list=san_list,
        validity_days=validity_days,
        cert_mode=cert_mode,
        chmod_parents=chmod_parents,
    )
