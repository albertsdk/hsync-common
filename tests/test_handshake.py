# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Tests for the shared handshake contract."""

from hsync_common.protocol.handshake import (
    ALL_CAPABILITIES,
    PROTOCOL_VERSION_P2P,
    PROTOCOL_VERSION_REST,
    PROTOCOL_VERSION_WS,
    Capability,
    build_ws_auth_error,
    build_ws_auth_ok,
    build_ws_auth_request,
    decode_capabilities,
    encode_capabilities,
)


class TestProtocolVersions:
    """The per-channel protocol versions are distinct, stable identifiers."""

    def test_versions_are_distinct(self):
        versions = {PROTOCOL_VERSION_REST, PROTOCOL_VERSION_WS, PROTOCOL_VERSION_P2P}
        assert len(versions) == 3

    def test_versions_have_channel_prefix(self):
        assert PROTOCOL_VERSION_REST.startswith("api/")
        assert PROTOCOL_VERSION_WS.startswith("ws/")
        assert PROTOCOL_VERSION_P2P.startswith("p2p/")


class TestCapabilities:
    """Capability encode/decode round-trips and tolerates unknown tokens."""

    def test_all_capabilities_matches_enum(self):
        assert frozenset(Capability) == ALL_CAPABILITIES

    def test_encode_sorts_and_deduplicates(self):
        encoded = encode_capabilities(
            [Capability.compression, "compression", Capability.tombstones]
        )
        assert encoded == ["compression", "tombstones"]

    def test_encode_accepts_enum_and_str(self):
        assert encode_capabilities([Capability.https]) == ["https"]
        assert encode_capabilities(["https"]) == ["https"]

    def test_decode_parses_known(self):
        assert decode_capabilities(["compression", "https"]) == {
            Capability.compression,
            Capability.https,
        }

    def test_decode_drops_unknown_tokens(self):
        assert decode_capabilities(["compression", "warp_drive"]) == {Capability.compression}

    def test_decode_handles_non_list(self):
        assert decode_capabilities(None) == set()
        assert decode_capabilities("compression") == set()
        assert decode_capabilities(42) == set()

    def test_round_trip(self):
        caps = {
            Capability.compression,
            Capability.tombstones,
            Capability.never_master,
            Capability.peer_download,
        }
        assert decode_capabilities(encode_capabilities(caps)) == caps

    def test_peer_download_wire_token(self):
        assert Capability.peer_download.value == "peer_download"


class TestWsAuthBuilders:
    """The WebSocket auth frame builders emit the contract-defined shapes."""

    def test_build_request(self):
        frame = build_ws_auth_request(
            token="secret", app_version="1.0.0", capabilities=[Capability.compression]
        )
        assert frame["type"] == "auth"
        assert frame["token"] == "secret"
        assert frame["app_version"] == "1.0.0"
        assert frame["protocol_version"] == PROTOCOL_VERSION_WS
        assert frame["capabilities"] == ["compression"]

    def test_build_ok(self):
        frame = build_ws_auth_ok(app_version="1.0.0", capabilities={Capability.compression})
        assert frame["type"] == "auth"
        assert frame["status"] == "ok"
        assert frame["protocol_version"] == PROTOCOL_VERSION_WS
        assert frame["app_version"] == "1.0.0"  # type: ignore[reportTypedDictNotRequiredAccess]
        assert frame["capabilities"] == ["compression"]  # type: ignore[reportTypedDictNotRequiredAccess]

    def test_build_error(self):
        frame = build_ws_auth_error(error="protocol_incompatible", client_protocol_version="ws/999")
        assert frame["type"] == "auth"
        assert frame["status"] == "error"
        assert frame["error"] == "protocol_incompatible"  # type: ignore[reportTypedDictNotRequiredAccess]
        assert frame["protocol_version"] == PROTOCOL_VERSION_WS
        assert frame["client_protocol_version"] == "ws/999"  # type: ignore[reportTypedDictNotRequiredAccess]
