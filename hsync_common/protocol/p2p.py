# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""
Canonical LAN master-election algorithm (single source of truth).

The election ordering used to pick the LAN coordinator lives here once and is
consumed by every component (the Python client's ``PeerManager`` and, via the
shared golden fixtures, the Android ``P2PManager``). Keeping the algorithm in
:mod:`hsync_common` is what stops the two implementations from drifting: both
are validated against the same scenario fixtures (``p2p-election-scenarios``).

Ordering (highest priority first):

1. ``server_ready`` — an already-serving incumbent wins, so a newcomer never
   triggers a takeover/split-brain for the same bucket.
2. ``force_master`` — an operator-pinned master wins over ordinary peers.
3. bidirectional ``sync_direction`` — a fully bidirectional peer is preferred
   over an upload-only/download-only one (it can serve every other peer).
4. earliest ``startup_time`` — the node that started first wins.
5. lowest ``cid`` lexicographically — a deterministic final tiebreaker.

Nodes flagged ``never_master`` are excluded from candidacy entirely; if every
candidate is excluded no master is elected (``elect_master`` returns ``None``).

The canonical TXT keys carried on the wire are defined once in
:mod:`hsync_common.protocol.schemas` (``P2P_TXT_KEYS``); this module owns only
the election semantics that read them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = [
    "SYNC_DIRECTION_BIDIRECTIONAL",
    "ElectionCandidate",
    "elect_master",
    "election_sort_key",
    "rank_election_candidates",
]

# Canonical default/preferred sync direction; a bidirectional peer can serve
# every other peer and is therefore favoured during election.
SYNC_DIRECTION_BIDIRECTIONAL = "bidirectional"


@dataclass(frozen=True)
class ElectionCandidate:
    """A node participating in (or excluded from) LAN master election.

    Field names mirror the canonical TXT keys so the same values flow from the
    mDNS record straight into the election without an intermediate vocabulary.
    """

    cid: str
    force_master: bool = False
    startup_time: float = 0.0
    sync_direction: str = SYNC_DIRECTION_BIDIRECTIONAL
    server_ready: bool = False
    never_master: bool = False


def election_sort_key(candidate: ElectionCandidate) -> tuple[bool, bool, bool, float, str]:
    """Return the canonical sort key; the smallest key wins the election.

    Booleans are negated so that ``True`` (e.g. ``server_ready``) sorts before
    ``False`` under ascending ordering.
    """
    return (
        not candidate.server_ready,
        not candidate.force_master,
        candidate.sync_direction != SYNC_DIRECTION_BIDIRECTIONAL,
        candidate.startup_time,
        candidate.cid,
    )


def rank_election_candidates(
    candidates: Iterable[ElectionCandidate],
) -> list[ElectionCandidate]:
    """Return the eligible candidates ranked by :func:`election_sort_key`.

    ``never_master`` nodes are filtered out first. Callers that need more than
    the winner (e.g. the client's pre-computed successor, or the ranked
    ``force_master`` subset for conflict reporting) must use this function so
    the ranking itself lives only here; :func:`elect_master` is its
    winner-only projection.
    """
    return sorted((c for c in candidates if not c.never_master), key=election_sort_key)


def elect_master(candidates: Iterable[ElectionCandidate]) -> str | None:
    """Elect the master CID from ``candidates``.

    ``never_master`` nodes are filtered out first; the remaining candidates are
    ranked by :func:`election_sort_key`. Returns the winning ``cid`` or ``None``
    when no node is eligible.
    """
    ranked = rank_election_candidates(candidates)
    return ranked[0].cid if ranked else None
