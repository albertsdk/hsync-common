# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the canonical REST surface (single source of truth).

``hsync_common.protocol.rest`` names the hsync-server REST surface; the
committed OpenAPI snapshot is generated from the same FastAPI app. These tests
pin the builders and assert the named surface and the snapshot agree exactly, so
a server route change cannot silently diverge the clients.
"""

import json

from hsync_common.protocol import REST_OPENAPI_PATH
from hsync_common.protocol.rest import (
    REST_API_PREFIX,
    REST_BUCKETS_PREFIX,
    REST_DELTA_DATA_SUFFIX,
    REST_FILES_DOWNLOAD_SUFFIX,
    REST_FILES_SUFFIX,
    REST_HEALTH_PATH,
    REST_METRICS_PATH,
    REST_PATH_TEMPLATES,
    REST_TIME_PATH,
    rest_bucket_base,
    rest_bucket_path,
    rest_bucket_template,
    rest_delta_data_path,
)


class TestRestSurface:
    def test_prefixes_and_service_paths(self):
        assert REST_API_PREFIX == "/api/v1"
        assert REST_BUCKETS_PREFIX == "/api/v1/buckets"
        assert REST_HEALTH_PATH == "/health"
        assert REST_METRICS_PATH == "/metrics"
        assert REST_TIME_PATH == "/api/v1/time"

    def test_bucket_builders(self):
        assert rest_bucket_base("b1") == "/api/v1/buckets/b1"
        assert (
            rest_bucket_path("b1", REST_FILES_DOWNLOAD_SUFFIX)
            == "/api/v1/buckets/b1/files/download"
        )
        assert rest_bucket_template(REST_FILES_SUFFIX) == "/api/v1/buckets/{bucket}/files"
        assert (
            rest_delta_data_path("b1", "tok")
            == "/api/v1/buckets/b1" + REST_DELTA_DATA_SUFFIX + "tok"
        )


class TestRestPathSnapshotAlignment:
    """The named surface and the committed OpenAPI snapshot must agree exactly."""

    def test_snapshot_file_exists(self):
        assert REST_OPENAPI_PATH.is_file()

    def test_templates_match_the_snapshot_paths(self):
        snapshot = json.loads(REST_OPENAPI_PATH.read_text(encoding="utf-8"))
        assert set(snapshot["paths"]) == set(REST_PATH_TEMPLATES)
