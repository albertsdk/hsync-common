# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""
Canonical REST surface of the hsync server (single source of truth).

The FastAPI app in ``hsync-server`` registers exactly these paths and the
committed OpenAPI snapshot (:data:`hsync_common.protocol.REST_OPENAPI_PATH`) is
generated from it. Naming the surface here lets the Python consumers
(``hsync-client``, and ``hsync-server`` where useful) and the ``hsync-android``
mirror build requests from one definition instead of hand-written literals.

:data:`REST_PATH_TEMPLATES` is compared byte-for-byte with the snapshot by
``tests/test_protocol_rest.py``, so a server route change cannot silently
diverge the clients.

Consumers: ``hsync-client`` (server API requests; the peer-download plane it
mirrors) and the ``hsync-android`` mirror.
"""

from __future__ import annotations

__all__ = [
    "REST_ADMIN_BUCKETS_PATH",
    "REST_ADMIN_CLIENTS_PATH",
    "REST_ADMIN_CLIENT_DISABLE_PATH",
    "REST_ADMIN_CLIENT_ENABLE_PATH",
    "REST_ADMIN_CLIENT_EXPIRY_PATH",
    "REST_ADMIN_CLIENT_PATH",
    "REST_ADMIN_CLIENT_ROTATE_KEY_PATH",
    "REST_API_PREFIX",
    "REST_BUCKETS_PREFIX",
    "REST_BUCKET_EVENTS_PATH_TEMPLATE",
    "REST_BUCKET_PATH_TEMPLATE",
    "REST_DELTA_APPLY_SUFFIX",
    "REST_DELTA_DATA_PATH_TEMPLATE",
    "REST_DELTA_DATA_SUFFIX",
    "REST_DELTA_SIGNATURES_SUFFIX",
    "REST_DIRS_SUFFIX",
    "REST_FILES_DOWNLOAD_SUFFIX",
    "REST_FILES_PERMISSIONS_SUFFIX",
    "REST_FILES_SUFFIX",
    "REST_FILES_UPLOAD_STATUS_SUFFIX",
    "REST_HEALTH_PATH",
    "REST_MEMBERS_CLIENT_PATH_TEMPLATE",
    "REST_MEMBERS_CLIENT_SUFFIX",
    "REST_MEMBERS_SUFFIX",
    "REST_METRICS_PATH",
    "REST_OWNER_SUFFIX",
    "REST_PATH_TEMPLATES",
    "REST_PRESENCE_SUFFIX",
    "REST_SYMLINKS_SUFFIX",
    "REST_TIME_PATH",
    "REST_TOMBSTONES_SUFFIX",
    "rest_bucket_base",
    "rest_bucket_path",
    "rest_bucket_template",
    "rest_delta_data_path",
]

REST_API_PREFIX = "/api/v1"

# Service-level endpoints.
REST_HEALTH_PATH = "/health"
REST_METRICS_PATH = "/metrics"
REST_TIME_PATH = f"{REST_API_PREFIX}/time"

# Admin surface.
REST_ADMIN_BUCKETS_PATH = f"{REST_API_PREFIX}/admin/buckets"
REST_ADMIN_CLIENTS_PATH = f"{REST_API_PREFIX}/admin/clients"
REST_ADMIN_CLIENT_PATH = f"{REST_ADMIN_CLIENTS_PATH}/{{client_id}}"
REST_ADMIN_CLIENT_DISABLE_PATH = f"{REST_ADMIN_CLIENT_PATH}/disable"
REST_ADMIN_CLIENT_ENABLE_PATH = f"{REST_ADMIN_CLIENT_PATH}/enable"
REST_ADMIN_CLIENT_EXPIRY_PATH = f"{REST_ADMIN_CLIENT_PATH}/expiry"
REST_ADMIN_CLIENT_ROTATE_KEY_PATH = f"{REST_ADMIN_CLIENT_PATH}/rotate-key"

# Bucket surface: the collection path plus per-bucket suffixes.
REST_BUCKETS_PREFIX = f"{REST_API_PREFIX}/buckets"
REST_BUCKET_PATH_TEMPLATE = f"{REST_BUCKETS_PREFIX}/{{bucket}}"
REST_FILES_SUFFIX = "/files"
REST_FILES_DOWNLOAD_SUFFIX = "/files/download"
REST_FILES_PERMISSIONS_SUFFIX = "/files/permissions"
REST_FILES_UPLOAD_STATUS_SUFFIX = "/files/upload-status"
REST_DIRS_SUFFIX = "/dirs"
REST_TOMBSTONES_SUFFIX = "/tombstones"
REST_MEMBERS_SUFFIX = "/members"
REST_MEMBERS_CLIENT_SUFFIX = "/members/{client_id}"
REST_OWNER_SUFFIX = "/owner"
REST_PRESENCE_SUFFIX = "/presence"
REST_SYMLINKS_SUFFIX = "/symlinks"
REST_DELTA_SIGNATURES_SUFFIX = "/files/delta/signatures"
REST_DELTA_APPLY_SUFFIX = "/files/delta/apply"
REST_DELTA_DATA_SUFFIX = "/files/delta/data/"

# Multi-parameter templates (the server registers these verbatim).
REST_MEMBERS_CLIENT_PATH_TEMPLATE = f"{REST_BUCKET_PATH_TEMPLATE}{REST_MEMBERS_CLIENT_SUFFIX}"
REST_DELTA_DATA_PATH_TEMPLATE = f"{REST_BUCKET_PATH_TEMPLATE}{REST_DELTA_DATA_SUFFIX}{{token}}"

# Realtime control-plane template: served by the server and the LAN master on
# the same listener. It is a WebSocket upgrade, so it is kept out of
# REST_PATH_TEMPLATES (the OpenAPI snapshot lists REST paths only).
REST_BUCKET_EVENTS_PATH_TEMPLATE = f"{REST_BUCKET_PATH_TEMPLATE}/events/{{cid}}"


def rest_bucket_base(bucket: str) -> str:
    """Return ``/api/v1/buckets/<bucket>``."""
    return f"{REST_BUCKETS_PREFIX}/{bucket}"


def rest_bucket_path(bucket: str, suffix: str) -> str:
    """Return ``/api/v1/buckets/<bucket><suffix>`` (see :data:`REST_FILES_SUFFIX`)."""
    return f"{rest_bucket_base(bucket)}{suffix}"


def rest_bucket_template(suffix: str) -> str:
    """Return the ``{bucket}`` route template for *suffix*."""
    return rest_bucket_path("{bucket}", suffix)


def rest_delta_data_path(bucket: str, token: str) -> str:
    """Return the delta literal-payload path for *bucket* / *token*."""
    return rest_bucket_path(bucket, f"{REST_DELTA_DATA_SUFFIX}{token}")


# Every concrete path template in the server REST surface. Kept as one literal
# set so tests/test_protocol_rest.py can compare it with the committed OpenAPI
# snapshot and fail on any drift.
REST_PATH_TEMPLATES = frozenset(
    {
        REST_HEALTH_PATH,
        REST_METRICS_PATH,
        REST_TIME_PATH,
        REST_ADMIN_BUCKETS_PATH,
        REST_ADMIN_CLIENTS_PATH,
        REST_ADMIN_CLIENT_PATH,
        REST_ADMIN_CLIENT_DISABLE_PATH,
        REST_ADMIN_CLIENT_ENABLE_PATH,
        REST_ADMIN_CLIENT_EXPIRY_PATH,
        REST_ADMIN_CLIENT_ROTATE_KEY_PATH,
        REST_BUCKETS_PREFIX,
        REST_BUCKET_PATH_TEMPLATE,
        rest_bucket_template(REST_DIRS_SUFFIX),
        rest_bucket_template(REST_FILES_SUFFIX),
        rest_bucket_template(REST_FILES_DOWNLOAD_SUFFIX),
        rest_bucket_template(REST_FILES_PERMISSIONS_SUFFIX),
        rest_bucket_template(REST_FILES_UPLOAD_STATUS_SUFFIX),
        rest_bucket_template(REST_TOMBSTONES_SUFFIX),
        rest_bucket_template(REST_MEMBERS_SUFFIX),
        REST_MEMBERS_CLIENT_PATH_TEMPLATE,
        rest_bucket_template(REST_OWNER_SUFFIX),
        rest_bucket_template(REST_PRESENCE_SUFFIX),
        rest_bucket_template(REST_SYMLINKS_SUFFIX),
        rest_bucket_template(REST_DELTA_SIGNATURES_SUFFIX),
        rest_bucket_template(REST_DELTA_APPLY_SUFFIX),
        REST_DELTA_DATA_PATH_TEMPLATE,
    }
)
