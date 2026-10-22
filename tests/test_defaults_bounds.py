# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""The shared user-facing bounds must stay internally consistent.

``hsync_common.defaults`` owns both a knob's default and the range the CLI
validates (and the GUI clamps) against, so a default that falls outside its own
range — or an inverted range — is a contract bug no consumer test would catch.
"""

from __future__ import annotations

import pytest

from hsync_common import defaults

# (name, min, default, max) for every bounded knob.
BOUNDED_KNOBS = [
    (
        "HTTP_TIMEOUT",
        defaults.HTTP_TIMEOUT_MIN,
        defaults.HTTP_TIMEOUT_DEFAULT,
        defaults.HTTP_TIMEOUT_MAX,
    ),
    (
        "STABILITY_DELAY",
        defaults.STABILITY_DELAY_MIN,
        defaults.STABILITY_DELAY_DEFAULT,
        defaults.STABILITY_DELAY_MAX,
    ),
    (
        "MAX_WAIT_TIMEOUT",
        defaults.MAX_WAIT_TIMEOUT_MIN,
        defaults.MAX_WAIT_TIMEOUT_DEFAULT,
        defaults.MAX_WAIT_TIMEOUT_MAX,
    ),
    (
        "RECONNECT_DELAY",
        defaults.RECONNECT_DELAY_MIN,
        defaults.RECONNECT_DELAY_DEFAULT,
        defaults.RECONNECT_DELAY_MAX,
    ),
    (
        "MAX_CONCURRENT_TRANSFERS",
        defaults.MAX_CONCURRENT_TRANSFERS_MIN,
        defaults.MAX_CONCURRENT_TRANSFERS_DEFAULT,
        defaults.MAX_CONCURRENT_TRANSFERS_MAX,
    ),
    (
        "MIN_FREE_DISK_SPACE_MB",
        defaults.MIN_FREE_DISK_SPACE_MB_MIN,
        defaults.MIN_FREE_DISK_SPACE_MB_DEFAULT,
        defaults.MIN_FREE_DISK_SPACE_MB_MAX,
    ),
    (
        "MAX_INBOUND_SIZE_MB",
        defaults.MAX_INBOUND_SIZE_MB_MIN,
        defaults.MAX_INBOUND_SIZE_MB_DEFAULT,
        defaults.MAX_INBOUND_SIZE_MB_MAX,
    ),
    (
        "P2P_PEER_READ_CAP",
        defaults.P2P_PEER_READ_CAP_MIN,
        defaults.P2P_PEER_READ_CAP_DEFAULT,
        defaults.P2P_PEER_READ_CAP_MAX,
    ),
    (
        "P2P_PEER_SOURCES_MAX",
        defaults.P2P_PEER_SOURCES_MAX_MIN,
        defaults.P2P_PEER_SOURCES_MAX_DEFAULT,
        defaults.P2P_PEER_SOURCES_MAX_MAX,
    ),
]


@pytest.mark.parametrize("name,low,default,high", BOUNDED_KNOBS, ids=[k[0] for k in BOUNDED_KNOBS])
def test_default_sits_inside_its_bounds(name: str, low: int, default: int, high: int) -> None:
    assert low < high, f"{name}: inverted bounds"
    assert low <= default <= high, f"{name}: default outside [{low}, {high}]"


def test_bounds_are_exported() -> None:
    """``__all__`` is what consumer alias checks enumerate."""
    for name, *_ in BOUNDED_KNOBS:
        for suffix in ("_MIN", "_MAX"):
            assert name + suffix in defaults.__all__
