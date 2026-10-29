# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the mirrored ``rdv/1`` rendezvous protocol.

The canonical specification and fixtures live in the sibling ``hsync-rendezvous``
repository (the rendezvous never imports hsync-common). This module guards the
mirror under ``hsync_common/protocol``: every mirrored fixture must validate
against the mirrored validators and must stay byte-identical to the canonical
``hsync-rendezvous/fixtures/`` bytes, so the two copies cannot drift silently.
"""

import json

import pytest

from hsync_common.protocol import FIXTURES_DIR, RENDEZVOUS_FIXTURES_DIR
from hsync_common.protocol.pairing import fingerprint_matches, parse_fingerprint
from hsync_common.protocol.rdv_tokens import (
    BUCKET_TOKEN_LEN,
    MIN_GROUP_KEY_CHARS,
    MIN_GROUP_PASSPHRASE_CHARS,
    WeakGroupPassphrase,
    derive_group_key,
    passphrase_warning,
    validate_group_key,
    validate_group_passphrase,
)
from hsync_common.protocol.rendezvous import (
    CAPACITY_MAX,
    PROTOCOL_VERSION_RDV,
    derive_bucket_token,
    validate_rdv_ack,
    validate_rdv_frame,
    validate_rdv_relay_error,
    validate_rdv_relay_incoming,
    validate_rdv_relay_listening,
    validate_rdv_relay_ok,
    validate_rdv_response,
    verify_bucket_token,
)

_MIRRORED = {
    "rendezvous-register": validate_rdv_frame,
    "rendezvous-query": validate_rdv_frame,
    "rendezvous-ack": validate_rdv_ack,
    "rendezvous-response": validate_rdv_response,
    "rendezvous-relay-listen": validate_rdv_frame,
    "rendezvous-relay-ping": validate_rdv_frame,
    "rendezvous-relay-connect": validate_rdv_frame,
    "rendezvous-relay-attach": validate_rdv_frame,
    "rendezvous-relay-listening": validate_rdv_relay_listening,
    "rendezvous-relay-incoming": validate_rdv_relay_incoming,
    "rendezvous-relay-ok": validate_rdv_relay_ok,
    "rendezvous-relay-error": validate_rdv_relay_error,
}

# A canonical SHA-256 certificate fingerprint (the pin format of ADR-0037).
_FP_HEX = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_mirrored_fixture_validates(name):
    """Each mirrored fixture validates against its mirrored rdv/1 validator."""
    validated = _MIRRORED[name](_load(name))
    assert validated is not None
    assert validated["protocol_version"] == PROTOCOL_VERSION_RDV


@pytest.mark.parametrize("name", sorted(_MIRRORED))
def test_mirror_matches_canonical_rendezvous_fixture(name):
    """The mirrored fixture is byte-identical to the canonical rendezvous one."""
    canonical = RENDEZVOUS_FIXTURES_DIR / f"{name}.json"
    if not canonical.is_file():
        pytest.skip(f"hsync-rendezvous fixtures not present at {RENDEZVOUS_FIXTURES_DIR}")
    mirrored = (FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8")
    assert mirrored == canonical.read_text(encoding="utf-8"), (
        "Mirrored rdv/1 fixture drift: copy the canonical file from "
        "hsync-rendezvous/fixtures/ into hsync_common/protocol/fixtures/"
    )


def test_capacity_hint_domain_bounds():
    """The advisory capacity hint is 0..32 (0 = not a seeder); 33 is rejected."""
    register = {
        "protocol_version": "rdv/1",
        "type": "register",
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "bucket": "shared",
        "cert_fp": _FP_HEX,
        "version": "1.0.0",
        "capacity": 0,
        "endpoints": [],
    }
    assert validate_rdv_frame(register) is not None
    assert validate_rdv_frame({**register, "capacity": CAPACITY_MAX}) is not None
    assert validate_rdv_frame({**register, "capacity": CAPACITY_MAX + 1}) is None


def test_register_without_capacity_or_endpoints_defaults():
    """A register may omit capacity/endpoints (first STUN register); null is invalid.

    Mirrors the rendezvous pydantic models (``capacity=0``, ``endpoints=[]``) and
    the spec rule that a register with no known public endpoint is valid.
    """
    minimal = {
        "protocol_version": "rdv/1",
        "type": "register",
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "bucket": "shared",
        "cert_fp": _FP_HEX,
        "version": "1.0.0",
    }
    validated = validate_rdv_frame(minimal)
    assert validated is not None
    assert validated["capacity"] == 0
    assert validated["endpoints"] == []
    assert validate_rdv_frame({**minimal, "capacity": None}) is None
    assert validate_rdv_frame({**minimal, "endpoints": None}) is None


def test_unknown_field_is_rejected():
    """The mirror is strict: an unknown frame field is rejected (extra=forbid)."""
    query = {
        "protocol_version": "rdv/1",
        "type": "query",
        "bucket": "shared",
        "target_file": "secret.txt",
    }
    assert validate_rdv_frame(query) is None


def _minimal_register() -> dict:
    return {
        "protocol_version": "rdv/1",
        "type": "register",
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "bucket": "shared",
        "cert_fp": _FP_HEX,
        "version": "1.0.0",
    }


def test_register_election_advert_defaults_and_bounds():
    """The election advertisement is optional (documented defaults) and strict.

    Mirrors the rendezvous models: booleans default to false, ``startup_time`` to
    ``0.0`` ("unknown") and ``sync_direction`` to ``bidirectional``. A malformed
    value (wrong type, null, negative/non-finite/out-of-range timestamp, unknown
    direction) makes the whole frame invalid instead of being silently coerced,
    and the canonical vocabulary is the pairing/p2p SSOT pair.
    """
    validated = validate_rdv_frame(_minimal_register())
    assert validated is not None
    assert validated["server_ready"] is False
    assert validated["prefer_master"] is False
    assert validated["never_master"] is False
    assert validated["startup_time"] == 0.0
    assert validated["sync_direction"] == "bidirectional"

    advertised = validate_rdv_frame(
        {
            **_minimal_register(),
            "server_ready": True,
            "prefer_master": True,
            "startup_time": 1760000000.5,
            "sync_direction": "download-only",
        }
    )
    assert advertised is not None
    assert advertised["server_ready"] is True
    assert advertised["prefer_master"] is True
    assert advertised["never_master"] is False
    assert advertised["startup_time"] == 1760000000.5
    assert advertised["sync_direction"] == "download-only"

    for field, bad in (
        ("server_ready", 1),
        ("server_ready", None),
        ("prefer_master", "true"),
        ("never_master", None),
        ("startup_time", -1),
        ("startup_time", "1760000000"),
        ("startup_time", True),
        ("startup_time", float("inf")),
        ("startup_time", 2**53 + 1),
        ("sync_direction", "sideways"),
        ("sync_direction", 3),
    ):
        assert validate_rdv_frame({**_minimal_register(), field: bad}) is None, field


def _response_with_peer(peer: dict) -> dict:
    return {
        "protocol_version": "rdv/1",
        "type": "response",
        "peers": [peer],
        "count": 1,
        "ttl": 60,
    }


def test_response_peer_requires_the_election_advert():
    """A relayed peer always carries the advertisement; a missing key is invalid.

    The rendezvous echoes every advertisement key on every peer, so the mirror
    rejects a peer that omits one instead of defaulting it client-side: a
    silently-defaulted ``server_ready``/``never_master`` is exactly what made a
    seeder look like an electable serving master.
    """
    peer = {
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "endpoints": [{"proto": "tcp", "host": "198.51.100.7", "port": 443}],
        "cert_fp": _FP_HEX,
        "bucket": "shared",
        "version": "1.0.0",
        "capacity": 0,
        "reachable": True,
        "server_ready": False,
        "prefer_master": False,
        "never_master": True,
        "startup_time": 1760000000.0,
        "sync_direction": "bidirectional",
    }
    validated = validate_rdv_response(_response_with_peer(peer))
    assert validated is not None
    relayed = validated["peers"][0]
    assert relayed["never_master"] is True
    assert relayed["server_ready"] is False
    assert relayed["startup_time"] == 1760000000.0

    for key in (
        "server_ready",
        "prefer_master",
        "never_master",
        "startup_time",
        "sync_direction",
    ):
        partial = {name: value for name, value in peer.items() if name != key}
        assert validate_rdv_response(_response_with_peer(partial)) is None, key

    assert (
        validate_rdv_response(_response_with_peer({**peer, "sync_direction": "sideways"})) is None
    )
    assert validate_rdv_response(_response_with_peer({**peer, "startup_time": None})) is None


def test_response_peer_requires_a_non_empty_endpoints_list():
    """A relayed peer always carries at least one endpoint candidate.

    The node relays the peer's full advertised list, or a single-element list
    with the observed source endpoint when the peer advertised none, so an
    empty or missing list is malformed and rejected by the mirror.
    """
    peer = {
        "cid": "A1b2C3d4E5f6G7h8I9j0K",
        "endpoints": [{"proto": "tcp", "host": "198.51.100.7", "port": 443}],
        "cert_fp": _FP_HEX,
        "bucket": "shared",
        "version": "1.0.0",
        "capacity": 0,
        "reachable": True,
        "server_ready": False,
        "prefer_master": False,
        "never_master": True,
        "startup_time": 1760000000.0,
        "sync_direction": "bidirectional",
    }
    assert validate_rdv_response(_response_with_peer(peer)) is not None
    assert validate_rdv_response(_response_with_peer({**peer, "endpoints": []})) is None
    assert validate_rdv_response(_response_with_peer({**peer, "endpoints": None})) is None
    too_many = [{"proto": "tcp", "host": "198.51.100.7", "port": 443}] * 17
    assert validate_rdv_response(_response_with_peer({**peer, "endpoints": too_many})) is None
    bad_port = [{"proto": "tcp", "host": "198.51.100.7", "port": 0}]
    assert validate_rdv_response(_response_with_peer({**peer, "endpoints": bad_port})) is None


def test_response_refusal_error_domain():
    """Every refusal code in the spec is accepted; an unknown one is rejected.

    ``overloaded`` (node capacity) must validate like ``rate_limited`` and
    ``token_required`` so a capacity answer is not mistaken for a malformed frame.
    """
    for code in ("token_required", "rate_limited", "overloaded"):
        frame = {
            "protocol_version": "rdv/1",
            "type": "response",
            "peers": [],
            "count": 0,
            "ttl": 60,
            "error": code,
            "retry_after": 5,
        }
        validated = validate_rdv_response(frame)
        assert validated is not None, code
        assert validated["error"] == code
        assert validated["retry_after"] == 5

    unknown = {
        "protocol_version": "rdv/1",
        "type": "response",
        "peers": [],
        "count": 0,
        "ttl": 60,
        "error": "throttled",
    }
    assert validate_rdv_response(unknown) is None


def test_bucket_token_derivation_and_verify():
    """The bucket token is a 64-char hex HMAC; verification is uniform."""
    token = derive_bucket_token(b"secret", "shared")
    assert len(token) == 64
    assert verify_bucket_token(token, token) is True
    assert verify_bucket_token(token, None) is False
    assert verify_bucket_token(token, "not-a-token") is False
    assert derive_bucket_token(b"secret", "other") != token


def test_rendezvous_fingerprint_fixture_vectors():
    """The golden rendezvous-fingerprint scenarios pin the shared trust contract.

    The fixture lives in the canonical ``hsync-rendezvous/fixtures/`` (SSOT); the
    shared ``parse_fingerprint``/``fingerprint_matches`` in
    ``hsync_common.protocol.pairing`` must normalize and match every vector
    identically, so the future C/Android ports replay the same inputs.
    """
    canonical = RENDEZVOUS_FIXTURES_DIR / "rendezvous-fingerprint.json"
    if not canonical.is_file():
        pytest.skip(f"hsync-rendezvous fixtures not present at {RENDEZVOUS_FIXTURES_DIR}")
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


@pytest.mark.parametrize("host", ["198.51.100.7", "peer.example", "2001:db8::1", "[2001:db8::1]"])
def test_register_accepts_a_dialable_endpoint_host(host: str):
    frame = _load("rendezvous-register")
    frame["endpoints"] = [{"proto": "tcp", "host": host, "port": 443}]
    assert validate_rdv_frame(frame) is not None


@pytest.mark.parametrize(
    "host", ["", "..\\..", "../elsewhere", "a b", "a\x00b", "999.1.1.1", "a..b", "x" * 64]
)
def test_register_rejects_a_non_dialable_endpoint_host(host: str):
    frame = _load("rendezvous-register")
    frame["endpoints"] = [{"proto": "tcp", "host": host, "port": 443}]
    assert validate_rdv_frame(frame) is None


def test_response_peer_rejects_a_non_dialable_endpoint_host():
    doc = _load("rendezvous-response")
    doc["peers"][0]["endpoints"][0]["host"] = "../elsewhere"
    assert validate_rdv_response(doc) is None


@pytest.mark.parametrize(
    "cert_fp",
    [
        "",
        "f",
        "not-a-fingerprint",
        "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99",
        "sha256:zz",
    ],
)
def test_register_rejects_a_malformed_certificate_fingerprint(cert_fp: str):
    frame = _load("rendezvous-register")
    frame["cert_fp"] = cert_fp
    assert validate_rdv_frame(frame) is None


@pytest.mark.parametrize(
    "cert_fp",
    [
        _FP_HEX,
        "sha256:" + _FP_HEX,
        _FP_HEX.upper(),
        ":".join(_FP_HEX[index : index + 2] for index in range(0, 64, 2)),
    ],
)
def test_register_accepts_a_sha256_certificate_fingerprint(cert_fp: str):
    frame = _load("rendezvous-register")
    frame["cert_fp"] = cert_fp
    assert validate_rdv_frame(frame) is not None


def test_group_key_strength_floor():
    """The token's only entropy is the group key, so a short key is refused."""
    validate_group_key("k" * MIN_GROUP_KEY_CHARS)
    with pytest.raises(ValueError):
        validate_group_key("k" * (MIN_GROUP_KEY_CHARS - 1))
    assert MIN_GROUP_KEY_CHARS == 32


def test_group_key_derivation_is_pinned():
    """Python and Kotlin must derive this exact key (cross-language vector)."""
    assert (
        derive_group_key("correct horse battery")
        == "02d6cc2221b988cd84b9ccc08d8c894a36e51f31917b0cffcd238a7ba67c3a92"
    )
    token = derive_bucket_token(derive_group_key("correct horse battery").encode("utf-8"), "shared")
    assert token == "bb26e3983ed36ec3e8ea10f0a91771330c5f5a1662d7b7d254caea95fe3520da"
    assert len(token) == BUCKET_TOKEN_LEN


def test_passphrase_normalization_is_nfkc_and_trimmed():
    """Composed/decomposed accents and padding must derive the same key."""
    composed = "caf\u00e9-abcdwxyz1234"
    decomposed = "cafe\u0301-abcdwxyz1234"
    assert derive_group_key(composed) == derive_group_key(decomposed)
    assert derive_group_key("  correct horse battery  ") == derive_group_key(
        "correct horse battery"
    )


@pytest.mark.parametrize(
    ("passphrase", "code"),
    [
        ("short", "too_short"),
        ("abcdefghijk", "too_short"),  # 11 chars
        ("aaaaaaaaaaaaaaaa", "too_weak"),
        ("abcdefghijklmnop", "too_weak"),  # consecutive run
        ("password1234", "too_weak"),
    ],
)
def test_validate_group_passphrase_rejects_weak_input(passphrase, code):
    with pytest.raises(WeakGroupPassphrase) as exc:
        validate_group_passphrase(passphrase)
    assert exc.value.code == code


def test_validate_group_passphrase_accepts_the_floor():
    validate_group_passphrase("abcdwxyz1234")
    assert MIN_GROUP_PASSPHRASE_CHARS == 12
    assert passphrase_warning("abcdwxyz1234") == "short"
    validate_group_passphrase("abcdwxyz12345678")
    assert passphrase_warning("abcdwxyz12345678") is None
