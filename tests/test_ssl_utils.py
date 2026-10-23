"""Tests for hsync_common.ssl_utils."""

import hashlib
import os
from datetime import UTC, datetime

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import NameOID

from hsync_common.ssl_utils import (
    DEFAULT_KEY_SIZE,
    IDENTITY_DIR_MODE,
    KEY_FILE_MODE,
    PUBLIC_CERT_FILE_MODE,
    SERVICE_CERT_VALIDITY_DAYS,
    build_self_signed_certificate,
    compute_cert_fingerprint,
    create_service_identity,
    generate_ecdsa_private_key,
    generate_ed25519_private_key,
    generate_rsa_private_key,
    load_or_create_service_identity,
    load_pem_keypair,
    serialize_cert_pem,
    serialize_private_key_unencrypted,
    verify_cert_fingerprint,
    write_pem_keypair,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return generate_rsa_private_key()


@pytest.fixture(scope="module")
def self_signed_cert(private_key: rsa.RSAPrivateKey) -> x509.Certificate:
    return build_self_signed_certificate(
        private_key=private_key,
        subject_attrs=[
            x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "test.hsync.local"),
        ],
        san_list=[x509.DNSName("test.hsync.local")],
        validity_days=1,
    )


# ---------------------------------------------------------------------------
# generate_rsa_private_key
# ---------------------------------------------------------------------------


class TestGenerateRsaPrivateKey:
    def test_returns_rsa_key(self, private_key):
        assert isinstance(private_key, rsa.RSAPrivateKey)

    def test_default_key_size(self, private_key):
        assert private_key.key_size == DEFAULT_KEY_SIZE

    def test_custom_key_size(self):
        key = generate_rsa_private_key(key_size=1024)
        assert key.key_size == 1024

    def test_default_key_size_constant(self):
        assert DEFAULT_KEY_SIZE == 2048


# ---------------------------------------------------------------------------
# build_self_signed_certificate
# ---------------------------------------------------------------------------


class TestBuildSelfSignedCertificate:
    def test_returns_certificate(self, self_signed_cert):
        assert isinstance(self_signed_cert, x509.Certificate)

    def test_has_san_extension(self, self_signed_cert):
        san = self_signed_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "test.hsync.local" in dns_names

    def test_validity_period(self, self_signed_cert):
        from datetime import timedelta

        not_before = self_signed_cert.not_valid_before_utc
        not_after = self_signed_cert.not_valid_after_utc
        diff = not_after - not_before
        # The span is validity_days (from now) plus the 1-day NotBefore backdate.
        assert diff == timedelta(days=2)

    def test_ca_flag_false_by_default(self, self_signed_cert):
        try:
            bc = self_signed_cert.extensions.get_extension_for_class(x509.BasicConstraints)
            assert bc.value.ca is False
        except x509.ExtensionNotFound:
            pass  # No BasicConstraints extension — also valid for non-CA cert

    def test_ca_flag_true_when_requested(self, private_key):
        cert = build_self_signed_certificate(
            private_key=private_key,
            subject_attrs=[x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "ca.local")],
            san_list=[x509.DNSName("ca.local")],
            validity_days=365,
            basic_constraints_ca=True,
        )
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True

    def test_not_before_is_backdated_for_clock_skew(self, private_key):
        from datetime import UTC, datetime, timedelta

        cert = build_self_signed_certificate(
            private_key=private_key,
            subject_attrs=[x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "skew.local")],
            san_list=[x509.DNSName("skew.local")],
            validity_days=1,
        )
        # NotBefore must be strictly in the past (backdated ~1 day), never "now".
        assert cert.not_valid_before_utc < datetime.now(UTC)
        assert cert.not_valid_before_utc >= datetime.now(UTC) - timedelta(days=2)

    def test_service_validity_constant_is_twenty_years(self):
        # SSOT: 20 years, shared by the bootnode and the server (ADR-0037).
        assert SERVICE_CERT_VALIDITY_DAYS == 7305


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_serialize_cert_pem_returns_bytes(self, self_signed_cert):
        pem = serialize_cert_pem(self_signed_cert)
        assert isinstance(pem, bytes)

    def test_serialize_cert_pem_starts_with_header(self, self_signed_cert):
        pem = serialize_cert_pem(self_signed_cert)
        assert pem.startswith(b"-----BEGIN CERTIFICATE-----")

    def test_serialize_private_key_unencrypted_returns_bytes(self, private_key):
        pem = serialize_private_key_unencrypted(private_key)
        assert isinstance(pem, bytes)

    def test_serialize_private_key_unencrypted_starts_with_plain_header(self, private_key):
        pem = serialize_private_key_unencrypted(private_key)
        assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")

    def test_serialize_private_key_unencrypted_round_trip_without_password(self, private_key):
        from cryptography.hazmat.primitives import serialization

        pem = serialize_private_key_unencrypted(private_key)
        loaded = serialization.load_pem_private_key(pem, password=None)
        assert loaded is not None


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


class TestFingerprints:
    def test_compute_fingerprint_returns_hex_string(self, self_signed_cert):
        fp = compute_cert_fingerprint(self_signed_cert)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 = 32 bytes = 64 hex chars

    def test_fingerprint_is_hex(self, self_signed_cert):
        fp = compute_cert_fingerprint(self_signed_cert)
        int(fp, 16)  # should not raise

    def test_verify_fingerprint_correct(self, self_signed_cert):
        from cryptography.hazmat.primitives.serialization import Encoding

        der = self_signed_cert.public_bytes(Encoding.DER)
        expected = hashlib.sha256(der).hexdigest()
        assert verify_cert_fingerprint(der, expected) is True

    def test_verify_fingerprint_wrong(self, self_signed_cert):
        from cryptography.hazmat.primitives.serialization import Encoding

        der = self_signed_cert.public_bytes(Encoding.DER)
        assert verify_cert_fingerprint(der, "0" * 64) is False

    def test_verify_fingerprint_case_insensitive(self, self_signed_cert):
        from cryptography.hazmat.primitives.serialization import Encoding

        der = self_signed_cert.public_bytes(Encoding.DER)
        expected = hashlib.sha256(der).hexdigest().upper()
        assert verify_cert_fingerprint(der, expected) is True


class TestEcdsa:
    def test_generate_returns_p256_key(self):
        key = generate_ecdsa_private_key()
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        assert isinstance(key.curve, ec.SECP256R1)

    def test_self_signed_cert_with_ecdsa(self):
        key = generate_ecdsa_private_key()
        cert = build_self_signed_certificate(
            private_key=key,
            subject_attrs=[x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "boot.hsync.local")],
            san_list=[x509.DNSName("boot.hsync.local")],
            validity_days=365,
        )
        assert isinstance(cert, x509.Certificate)
        assert isinstance(cert.signature_hash_algorithm, hashes.SHA256)
        assert len(compute_cert_fingerprint(cert)) == 64

    def test_ecdsa_private_key_serializes_unencrypted(self):
        from cryptography.hazmat.primitives import serialization

        key = generate_ecdsa_private_key()
        pem = serialize_private_key_unencrypted(key)
        assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
        loaded = serialization.load_pem_private_key(pem, password=None)
        assert isinstance(loaded, ec.EllipticCurvePrivateKey)


class TestEd25519:
    def test_generate_returns_ed25519_key(self):
        key = generate_ed25519_private_key()
        assert isinstance(key, ed25519.Ed25519PrivateKey)

    def test_self_signed_cert_with_ed25519(self):
        key = generate_ed25519_private_key()
        cert = build_self_signed_certificate(
            private_key=key,
            subject_attrs=[x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "boot.hsync.local")],
            san_list=[x509.DNSName("boot.hsync.local")],
            validity_days=365,
        )
        assert isinstance(cert, x509.Certificate)
        assert len(compute_cert_fingerprint(cert)) == 64

    def test_ed25519_private_key_serializes_unencrypted(self):
        from cryptography.hazmat.primitives import serialization

        key = generate_ed25519_private_key()
        pem = serialize_private_key_unencrypted(key)
        assert pem.startswith(b"-----BEGIN PRIVATE KEY-----")
        loaded = serialization.load_pem_private_key(pem, password=None)
        assert isinstance(loaded, ed25519.Ed25519PrivateKey)


# ---------------------------------------------------------------------------
# write_pem_keypair / load_pem_keypair
# ---------------------------------------------------------------------------


def _identity_material(key) -> tuple[bytes, bytes, str]:
    """Cert PEM, key PEM and fingerprint for *key* (an ECDSA or RSA key)."""
    cert = build_self_signed_certificate(
        key,
        subject_attrs=[x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "svc")],
        san_list=[x509.DNSName("svc")],
        validity_days=1,
    )
    return (
        serialize_cert_pem(cert),
        serialize_private_key_unencrypted(key),
        compute_cert_fingerprint(cert),
    )


class TestPersistence:
    def test_write_creates_protected_files_and_directories(self, tmp_path):
        cert_pem, key_pem, _ = _identity_material(generate_ecdsa_private_key())
        cert_path = tmp_path / "deep" / "dir" / "svc.crt"
        key_path = tmp_path / "deep" / "dir" / "svc.key"

        write_pem_keypair(cert_pem, key_pem, cert_path, key_path, cert_mode=PUBLIC_CERT_FILE_MODE)

        assert cert_path.read_bytes() == cert_pem
        assert key_path.read_bytes() == key_pem
        assert (os.stat(key_path).st_mode & 0o777) == KEY_FILE_MODE
        assert (os.stat(cert_path).st_mode & 0o777) == PUBLIC_CERT_FILE_MODE
        assert (os.stat(cert_path.parent).st_mode & 0o777) == IDENTITY_DIR_MODE

    def test_write_leaves_an_existing_parent_alone_unless_asked(self, tmp_path):
        parent = tmp_path / "certs"
        parent.mkdir()
        os.chmod(parent, 0o755)  # umask-independent starting state
        cert_pem, key_pem, _ = _identity_material(generate_ecdsa_private_key())

        write_pem_keypair(cert_pem, key_pem, parent / "a.crt", parent / "a.key")
        assert (os.stat(parent).st_mode & 0o777) == 0o755

        write_pem_keypair(cert_pem, key_pem, parent / "b.crt", parent / "b.key", chmod_parents=True)
        assert (os.stat(parent).st_mode & 0o777) == IDENTITY_DIR_MODE

    def test_load_returns_the_stored_bytes_and_fingerprint(self, tmp_path):
        cert_pem, key_pem, fingerprint = _identity_material(generate_ecdsa_private_key())
        cert_path = tmp_path / "svc.crt"
        key_path = tmp_path / "svc.key"
        write_pem_keypair(cert_pem, key_pem, cert_path, key_path)

        assert load_pem_keypair(cert_path, key_path) == (cert_pem, key_pem, fingerprint)

    def test_load_rejects_a_non_ec_key(self, tmp_path):
        cert_pem, key_pem, _ = _identity_material(generate_rsa_private_key())
        cert_path = tmp_path / "svc.crt"
        key_path = tmp_path / "svc.key"
        write_pem_keypair(cert_pem, key_pem, cert_path, key_path)

        with pytest.raises(ValueError, match="P2P master identity .* ECDSA P-256"):
            load_pem_keypair(cert_path, key_path, subject="P2P master identity")


class TestServiceIdentityOperations:
    """The shared load-or-create / create skeleton for service identities."""

    @staticmethod
    def _params():
        return {
            "subject_attrs": [x509.NameAttribute(NameOID.COMMON_NAME, "svc")],
            "san_list": [x509.DNSName("localhost")],
        }

    def test_create_writes_an_ecdsa_identity(self, tmp_path):
        identity = create_service_identity(
            tmp_path / "svc.crt", tmp_path / "svc.key", **self._params()
        )

        assert identity.created is True
        assert identity.fingerprint == compute_cert_fingerprint(
            x509.load_pem_x509_certificate(identity.cert_pem)
        )
        assert os.path.exists(identity.cert_file)
        assert oct(os.stat(identity.key_file).st_mode & 0o777) == oct(KEY_FILE_MODE)
        assert identity.not_valid_after > datetime.now(UTC)

    def test_create_honours_the_certificate_mode(self, tmp_path):
        identity = create_service_identity(
            tmp_path / "svc.crt",
            tmp_path / "svc.key",
            cert_mode=PUBLIC_CERT_FILE_MODE,
            **self._params(),
        )

        assert oct(os.stat(identity.cert_file).st_mode & 0o777) == oct(PUBLIC_CERT_FILE_MODE)

    def test_create_always_regenerates(self, tmp_path):
        first = create_service_identity(tmp_path / "c.pem", tmp_path / "k.pem", **self._params())
        second = create_service_identity(tmp_path / "c.pem", tmp_path / "k.pem", **self._params())

        assert first.fingerprint != second.fingerprint

    def test_load_or_create_generates_then_loads(self, tmp_path):
        cert = tmp_path / "svc.crt"
        key = tmp_path / "svc.key"

        created = load_or_create_service_identity(cert, key, **self._params())
        loaded = load_or_create_service_identity(cert, key, **self._params())

        assert created.created is True
        assert loaded.created is False
        assert created.fingerprint == loaded.fingerprint
        assert loaded.cert_pem == created.cert_pem

    def test_a_partial_pair_is_never_accepted(self, tmp_path):
        cert = tmp_path / "svc.crt"
        key = tmp_path / "svc.key"
        cert.write_bytes(b"")

        identity = load_or_create_service_identity(cert, key, **self._params())

        assert identity.created is True
        assert key.exists()

    def test_load_or_create_rejects_a_foreign_key_type(self, tmp_path):
        cert_pem, key_pem, _ = _identity_material(generate_rsa_private_key())
        cert = tmp_path / "svc.crt"
        key = tmp_path / "svc.key"
        write_pem_keypair(cert_pem, key_pem, cert, key)

        with pytest.raises(ValueError, match="svc identity .* ECDSA P-256"):
            load_or_create_service_identity(cert, key, subject="svc identity", **self._params())
