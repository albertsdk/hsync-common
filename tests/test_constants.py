"""Tests for hsync_common.constants."""

from hsync_common.constants import (
    CHUNK_SIZE_LARGE,
    CHUNK_SIZE_MEDIUM,
    CHUNK_SIZE_SMALL,
    FILE_SIZE_MEDIUM,
    FILE_SIZE_SMALL,
    HSYNCKEEP_FILENAME,
    VERSION,
)


class TestVersion:
    def test_version_is_string(self):
        assert isinstance(VERSION, str)

    def test_version_has_three_parts(self):
        parts = VERSION.split(".")
        assert len(parts) == 3, f"Expected semver X.Y.Z, got '{VERSION}'"

    def test_version_parts_are_numeric(self):
        for part in VERSION.split("."):
            assert part.isdigit(), f"Version part '{part}' is not numeric"


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
