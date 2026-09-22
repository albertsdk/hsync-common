# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the mirrored ``boot/1`` bootstrap protocol.

The canonical specification and fixtures live in the sibling ``hsync-bootnode``
repository (the bootnode never imports hsync-common). This module guards the
mirror under ``hsync_common/protocol``: every mirrored fixture must validate
against the mirrored validators and must stay byte-identical to the canonical
``hsync-bootnode/fixtures/`` bytes, so the two copies cannot drift silently.
"""

import json

import pytest

from hsync_common.protocol import BOOTNODE_FIXTURES_DIR, FIXTURES_DIR
from hsync_common.protocol.bootnode import (
    CAPACITY_MAX,
    PROTOCOL_VERSION_BOOT,
    derive_bucket_token,
    validate_boot_ack,
    validate_boot_frame,
    validate_boot_response,
    verify_bucket_token,
)
from hsync_common.protocol.pairing import fingerprint_matches, parse_fingerprint

_MIRRORED = {
    "bootnode-register": validate_boot_frame,
    "bootnode-query": validate_boot_frame,
    "bootnode-ack": validate_boot_ack,
    "bootnode-response": validate_boot_response,
}


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_mirrored_fixture_validates(name):
    """Each mirrored fixture validates against its mirrored boot/1 validator."""
    validated = _MIRRORED[name](_load(name))
    assert validated is not None
    assert validated["protocol_version"] == PROTOCOL_VERSION_BOOT


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_mirror_matches_canonical_bootnode_fixture(name):
    """The mirrored fixture is byte-identical to the canonical bootnode one."""
    canonical = BOOTNODE_FIXTURES_DIR / f"{name}.json"
    if not canonical.is_file():
        pytest.skip(f"hsync-bootnode fixtures not present at {BOOTNODE_FIXTURES_DIR}")
    mirrored = (FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8")
    assert mirrored == canonical.read_text(encoding="utf-8"), (
        "Mirrored boot/1 fixture drift: copy the canonical file from "
        "hsync-bootnode/fixtures/ into hsync_common/protocol/fixtures/"
    )


def test_capacity_hint_domain_bounds():
    """The advisory capacity hint is 0..32 (0 = not a seeder); 33 is rejected."""
    register = {
        "protocol_version": "boot/1",
        "type": "register",
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "bucket": "shared",
        "cert_fp": "AA:BB",
        "version": "1.0.0",
        "capacity": 0,
        "endpoints": [],
    }
    assert validate_boot_frame(register) is not None
    assert validate_boot_frame({**register, "capacity": CAPACITY_MAX}) is not None
    assert validate_boot_frame({**register, "capacity": CAPACITY_MAX + 1}) is None


def test_register_without_capacity_or_endpoints_defaults():
    """A register may omit capacity/endpoints (first STUN register); null is invalid.

    Mirrors the bootnode pydantic models (``capacity=0``, ``endpoints=[]``) and
    the spec rule that a register with no known public endpoint is valid.
    """
    minimal = {
        "protocol_version": "boot/1",
        "type": "register",
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "bucket": "shared",
        "cert_fp": "AA:BB",
        "version": "1.0.0",
    }
    validated = validate_boot_frame(minimal)
    assert validated is not None
    assert validated["capacity"] == 0
    assert validated["endpoints"] == []
    assert validate_boot_frame({**minimal, "capacity": None}) is None
    assert validate_boot_frame({**minimal, "endpoints": None}) is None


def test_unknown_field_is_rejected():
    """The mirror is strict: an unknown frame field is rejected (extra=forbid)."""
    query = {
        "protocol_version": "boot/1",
        "type": "query",
        "bucket": "shared",
        "target_file": "secret.txt",
    }
    assert validate_boot_frame(query) is None


def test_bucket_token_derivation_and_verify():
    """The bucket token is a 64-char hex HMAC; verification is uniform."""
    token = derive_bucket_token(b"secret", "shared")
    assert len(token) == 64
    assert verify_bucket_token(token, token) is True
    assert verify_bucket_token(token, None) is False
    assert verify_bucket_token(token, "not-a-token") is False
    assert derive_bucket_token(b"secret", "other") != token


def test_bootnode_fingerprint_fixture_vectors():
    """The golden bootnode-fingerprint scenarios pin the shared trust contract.

    The fixture lives in the canonical ``hsync-bootnode/fixtures/`` (SSOT); the
    shared ``parse_fingerprint``/``fingerprint_matches`` in
    ``hsync_common.protocol.pairing`` must normalize and match every vector
    identically, so the future Rust/Android ports replay the same inputs.
    """
    canonical = BOOTNODE_FIXTURES_DIR / "bootnode-fingerprint.json"
    if not canonical.is_file():
        pytest.skip(f"hsync-bootnode fixtures not present at {BOOTNODE_FIXTURES_DIR}")
    doc = json.loads(canonical.read_text(encoding="utf-8"))

    for scenario in doc["parse_scenarios"]:
        assert parse_fingerprint(scenario["input"]) == scenario["normalized"], scenario

    for scenario in doc["match_scenarios"]:
        assert fingerprint_matches(scenario["observed"], scenario["pins"]) is scenario["matches"], (
            scenario
        )

    # The canonical form round-trips to the bare hex digest and back.
    assert parse_fingerprint(doc["canonical"]) == doc["hex"]
    assert parse_fingerprint(doc["hex"]) == doc["hex"]
