"""Tests for hsync_common.ssl_utils."""

import hashlib

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from hsync_common.ssl_utils import (
    DEFAULT_KEY_SIZE,
    build_self_signed_certificate,
    compute_cert_fingerprint,
    generate_ecdsa_private_key,
    generate_ed25519_private_key,
    generate_rsa_private_key,
    serialize_cert_pem,
    serialize_key_pem,
    serialize_private_key_unencrypted,
    verify_cert_fingerprint,
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
        assert diff == timedelta(days=1)

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

    def test_serialize_key_pem_returns_bytes(self, private_key):
        pem = serialize_key_pem(private_key, password=b"test-password")
        assert isinstance(pem, bytes)

    def test_serialize_key_pem_starts_with_encrypted_header(self, private_key):
        pem = serialize_key_pem(private_key, password=b"test-password")
        assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")

    def test_serialize_key_pem_round_trip_with_password(self, private_key):
        from cryptography.hazmat.primitives import serialization

        password = b"another-password"
        pem = serialize_key_pem(private_key, password=password)
        loaded = serialization.load_pem_private_key(pem, password=password)
        assert loaded is not None

    def test_serialize_key_pem_wrong_password_fails(self, private_key):
        from cryptography.hazmat.primitives import serialization

        pem = serialize_key_pem(private_key, password=b"correct")
        with pytest.raises(ValueError):
            serialization.load_pem_private_key(pem, password=b"wrong")

    def test_serialize_key_pem_empty_password_rejected(self, private_key):
        with pytest.raises(ValueError, match="password is required"):
            serialize_key_pem(private_key, password=b"")

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
