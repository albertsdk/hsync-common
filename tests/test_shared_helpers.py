# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the shared helpers that centralize previously duplicated logic."""

import os
import ssl
from pathlib import Path

import pytest

from hsync_common.constants import HSYNCKEEP_FILENAME
from hsync_common.endpoint import normalize_server_url
from hsync_common.fs import atomic_write_text
from hsync_common.ids import CID_ALPHABET, CID_PATTERN, is_valid_cid, mint_cid
from hsync_common.listing import folder_has_user_content
from hsync_common.models.version import decode_wire_vclock
from hsync_common.protocol.rest import PROMETHEUS_CONTENT_TYPE
from hsync_common.ratelimit import TokenBucket
from hsync_common.runtime import platform_tag
from hsync_common.tls_context import disable_certificate_verification, unverified_ssl_context


def test_atomic_write_text_writes_and_cleans_up(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state.txt"
    atomic_write_text(target, "hello", fsync_dir=True)
    assert target.read_text(encoding="utf-8") == "hello"
    assert not list(target.parent.glob("*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_atomic_write_text_is_owner_only(tmp_path: Path) -> None:
    target = tmp_path / "state.txt"
    atomic_write_text(target, "secret")
    assert (target.stat().st_mode & 0o777) == 0o600


def test_atomic_write_fixed_temp_with_nofollow(tmp_path: Path) -> None:
    target = tmp_path / "state.txt"
    atomic_write_text(target, "one", unique_temp=False, nofollow=True)
    assert target.read_text(encoding="utf-8") == "one"


def test_single_token_bucket_charge_semantics() -> None:
    bucket = TokenBucket(capacity=2, refill=2, window=1.0)
    start = bucket._stamp
    assert bucket.charge(2.0, now=start) is None
    # Empty: reports the wait and consumes nothing.
    wait = bucket.charge(1.0, now=start)
    assert wait is not None and wait > 0
    # Half a second refills one token at 2 tokens/s.
    assert bucket.charge(1.0, now=start + 0.5) is None


def test_single_token_bucket_acquire() -> None:
    bucket = TokenBucket(capacity=1, refill=1)
    assert bucket.acquire() is True
    assert bucket.acquire() is False


def test_mint_cid_matches_wire_contract() -> None:
    cid = mint_cid()
    assert len(cid) == 21
    assert cid.isascii() and cid.isalnum()
    assert is_valid_cid(cid)
    assert len(CID_ALPHABET) == 62
    assert CID_PATTERN.startswith("^")


def test_normalize_server_url_bare_and_url() -> None:
    assert normalize_server_url(None, default_port=9753) is None
    assert normalize_server_url("   ", default_port=9753) is None
    assert normalize_server_url("host", default_port=9753) == "https://host:9753"
    assert normalize_server_url("host:1234", default_port=9753) == "https://host:1234"
    assert normalize_server_url("https://host", default_port=9753) == "https://host"


def test_normalize_server_url_rejects_non_https() -> None:
    with pytest.raises(ValueError):
        normalize_server_url("http://host", default_port=9753)


def test_platform_tag_shape() -> None:
    tag = platform_tag()
    assert tag.count("-") == 1


def test_folder_has_user_content(tmp_path: Path) -> None:
    assert folder_has_user_content(str(tmp_path)) is False
    (tmp_path / HSYNCKEEP_FILENAME).write_text("", encoding="utf-8")
    assert folder_has_user_content(str(tmp_path)) is False
    (tmp_path / "note.txt").write_text("data", encoding="utf-8")
    assert folder_has_user_content(str(tmp_path)) is True


def test_decode_wire_vclock() -> None:
    assert decode_wire_vclock('{"a":1}') == {"a": 1}
    assert decode_wire_vclock({"a": 1}) == {"a": 1}
    assert decode_wire_vclock(None) is None
    assert decode_wire_vclock("not json") is None


def test_prometheus_content_type_constant() -> None:
    assert PROMETHEUS_CONTENT_TYPE.startswith("text/plain")


def test_unverified_ssl_context() -> None:
    context = unverified_ssl_context()
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE
    other = disable_certificate_verification(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    assert other.check_hostname is False
