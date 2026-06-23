"""Tests for hsync_common.constants."""

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_OCTET_STREAM,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
    HEADER_CLIENT_NAME,
    HEADER_CLIENT_VERSION,
    HEADER_PROTOCOL_VERSION,
    HEADER_SERVER_VERSION,
    HSYNC_VERSION,
    HSYNCKEEP_FILENAME,
    is_valid_client_name,
)


class TestVersion:
    def test_version_is_string(self):
        assert isinstance(HSYNC_VERSION, str)

    def test_version_has_three_parts(self):
        parts = HSYNC_VERSION.split(".")
        assert len(parts) == 3, f"Expected semver X.Y.Z, got '{HSYNC_VERSION}'"

    def test_version_parts_are_numeric(self):
        for part in HSYNC_VERSION.split("."):
            assert part.isdigit(), f"Version part '{part}' is not numeric"


class TestWireHeaders:
    def test_header_names_have_x_prefix(self):
        for header in (
            HEADER_CLIENT_NAME,
            HEADER_CLIENT_VERSION,
            HEADER_SERVER_VERSION,
            HEADER_PROTOCOL_VERSION,
        ):
            assert header.startswith("X-")

    def test_header_names_are_distinct(self):
        headers = {
            HEADER_CLIENT_NAME,
            HEADER_CLIENT_VERSION,
            HEADER_SERVER_VERSION,
            HEADER_PROTOCOL_VERSION,
        }
        assert len(headers) == 4


class TestWireContentTypes:
    def test_content_types_are_literals(self):
        assert CONTENT_TYPE_OCTET_STREAM == "application/octet-stream"
        assert CONTENT_TYPE_JSON == "application/json"

    def test_content_types_are_distinct(self):
        assert CONTENT_TYPE_OCTET_STREAM != CONTENT_TYPE_JSON


class TestClientNameValidation:
    def test_accepts_product_slugs(self):
        for name in ("hsync-client", "hsync-android", "hsync-desktop"):
            assert is_valid_client_name(name)

    def test_rejects_upper_case_or_underscores(self):
        for name in ("HSYNC Client", "hsync_client", "Hsync-Client"):
            assert not is_valid_client_name(name)

    def test_rejects_empty_and_whitespace(self):
        assert not is_valid_client_name("")
        assert not is_valid_client_name("   ")


class TestHsyncKeepFilename:
    def test_is_string(self):
        assert isinstance(HSYNCKEEP_FILENAME, str)

    def test_starts_with_dot(self):
        assert HSYNCKEEP_FILENAME.startswith(".")

    def test_non_empty(self):
        assert len(HSYNCKEEP_FILENAME) > 1


class TestChunkSizes:
    def test_chunk_size_ordering(self):
        """Small < Medium < Large chunks."""
        assert CHUNK_SIZE_SMALL < CHUNK_SIZE_MEDIUM < CHUNK_SIZE_LARGE

    def test_chunk_sizes_positive(self):
        for size in (CHUNK_SIZE_SMALL, CHUNK_SIZE_MEDIUM, CHUNK_SIZE_LARGE):
            assert size > 0

    def test_chunk_sizes_are_powers_of_two_multiples(self):
        """Chunk sizes should be multiples of 1024 (KB-aligned)."""
        for size in (CHUNK_SIZE_SMALL, CHUNK_SIZE_MEDIUM, CHUNK_SIZE_LARGE):
            assert size % 1024 == 0


class TestFileSizeThresholds:
    def test_size_ordering(self):
        assert FILE_SIZE_SMALL < FILE_SIZE_MEDIUM

    def test_sizes_positive(self):
        assert FILE_SIZE_SMALL > 0
        assert FILE_SIZE_MEDIUM > 0

    def test_small_is_around_1mb(self):
        # Should be approximately 1 MB (order of magnitude check)
        assert 500_000 < FILE_SIZE_SMALL < 2_000_000

    def test_medium_is_around_100mb(self):
        assert 50_000_000 < FILE_SIZE_MEDIUM < 200_000_000
