"""Tests for hsync_common.ssl_utils."""

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

from hsync_common.ssl_utils import (
    DEFAULT_KEY_SIZE,
    build_self_signed_certificate,
    compute_cert_fingerprint,
    generate_rsa_private_key,
    serialize_cert_pem,
    serialize_key_pem,
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
        san = self_signed_cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "test.hsync.local" in dns_names

    def test_validity_period(self, self_signed_cert):
        from datetime import UTC, timedelta, datetime
        not_before = self_signed_cert.not_valid_before_utc
        not_after = self_signed_cert.not_valid_after_utc
        diff = not_after - not_before
        assert diff == timedelta(days=1)

    def test_ca_flag_false_by_default(self, self_signed_cert):
        try:
            bc = self_signed_cert.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
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
        pem = serialize_key_pem(private_key)
        assert isinstance(pem, bytes)

    def test_serialize_key_pem_starts_with_header(self, private_key):
        pem = serialize_key_pem(private_key)
        assert pem.startswith(b"-----BEGIN RSA PRIVATE KEY-----")


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
        import hashlib
        der = self_signed_cert.public_bytes(Encoding.DER)
        expected = hashlib.sha256(der).hexdigest()
        assert verify_cert_fingerprint(der, expected) is True

    def test_verify_fingerprint_wrong(self, self_signed_cert):
        from cryptography.hazmat.primitives.serialization import Encoding
        der = self_signed_cert.public_bytes(Encoding.DER)
        assert verify_cert_fingerprint(der, "0" * 64) is False

    def test_verify_fingerprint_case_insensitive(self, self_signed_cert):
        from cryptography.hazmat.primitives.serialization import Encoding
        import hashlib
        der = self_signed_cert.public_bytes(Encoding.DER)
        expected = hashlib.sha256(der).hexdigest().upper()
        assert verify_cert_fingerprint(der, expected) is True
