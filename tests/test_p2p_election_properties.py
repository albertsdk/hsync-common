# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Alberto Basso

"""Property tests for the canonical election ordering.

The election is a *total order* built only from values a peer advertises about
itself (`hsync_common.protocol.p2p::election_sort_key`). Every consumer —
client, Android mirror, fixtures — re-derives the same winner from the same
candidate set, so the properties below are what makes that agreement safe:

* the winner and the full ranking do not depend on input order,
* the relation is transitive and antisymmetric (a real total order),
* strengthening the winner never unseats it, and adding a weaker candidate
  never changes the outcome,
* no clock-derived field participates (ADR-0054),
* `never_master` candidates never win.

Checked over every permutation of small candidate sets, plus randomized larger
sets with an input-independent seed, so a future change to the key that breaks
one of these properties fails here instead of in the field.
"""

from __future__ import annotations

import itertools
import random

import pytest

from hsync_common.protocol.p2p import (
    ElectionCandidate,
    elect_master,
    election_sort_key,
    rank_election_candidates,
)

CID_POOL = ("aaa", "aab", "bbb", "ccc", "zzz", "000", "mid")


def _candidates(rng: random.Random, size: int) -> list[ElectionCandidate]:
    """Build a mixed candidate set: every policy component varies."""
    return [
        ElectionCandidate(
            cid=rng.choice(CID_POOL) + str(index),
            prefer_master=rng.random() < 0.25,
            server_ready=rng.random() < 0.25,
            inbound=rng.random() < 0.5,
            never_master=False,
            sync_direction=rng.choice(["bidirectional", "upload-only", "download-only"]),
            epoch=rng.randint(0, 4),
        )
        for index in range(size)
    ]


class TestPermutationInvariance:
    @pytest.mark.parametrize("seed", range(12))
    def test_winner_and_ranking_ignore_input_order(self, seed: int) -> None:
        rng = random.Random(seed)
        candidates = _candidates(rng, 5)
        expected = [c.cid for c in rank_election_candidates(candidates)]
        expected_winner = elect_master(candidates)
        for permutation in itertools.permutations(candidates):
            assert [c.cid for c in rank_election_candidates(permutation)] == expected
            assert elect_master(permutation) == expected_winner

    def test_winner_is_the_first_of_the_ranking(self) -> None:
        rng = random.Random(7)
        candidates = _candidates(rng, 6)
        ranked = rank_election_candidates(candidates)
        assert elect_master(candidates) == ranked[0].cid


class TestTotalOrder:
    @pytest.mark.parametrize("seed", range(8))
    def test_key_is_a_total_order(self, seed: int) -> None:
        """Antisymmetry + transitivity over the keys actually produced."""
        rng = random.Random(seed)
        candidates = _candidates(rng, 6)
        keys = {c.cid: election_sort_key(c) for c in candidates}
        for left, right in itertools.permutations(candidates, 2):
            a, b = keys[left.cid], keys[right.cid]
            # Antisymmetry: one direction is strictly smaller, never both.
            assert (a < b) != (b < a) or a == b
        for first, second, third in itertools.permutations(candidates, 3):
            a, b, c = keys[first.cid], keys[second.cid], keys[third.cid]
            if a < b < c:
                assert a < c


class TestMonotonicity:
    def test_strengthening_the_winner_keeps_it_winning(self) -> None:
        """Making the winner a serving incumbent can never unseat it."""
        rng = random.Random(3)
        candidates = _candidates(rng, 5)
        winner = elect_master(candidates)
        assert winner is not None
        strengthened = [
            ElectionCandidate(**{**c.__dict__, "server_ready": True}) if c.cid == winner else c
            for c in candidates
        ]
        assert elect_master(strengthened) == winner

    def test_adding_a_weaker_candidate_does_not_change_the_winner(self) -> None:
        rng = random.Random(5)
        candidates = _candidates(rng, 4)
        winner = elect_master(candidates)
        weakest = ElectionCandidate(cid="zzz-weak", sync_direction="download-only", epoch=0)
        current = next(c for c in candidates if c.cid == winner)
        assert election_sort_key(weakest) > election_sort_key(current)
        assert elect_master([*candidates, weakest]) == winner


class TestClockFreeContract:
    def test_candidate_carries_no_timestamp(self) -> None:
        """Regression guard for ADR-0054: no clock-derived field can creep back."""
        candidate = ElectionCandidate(cid="aaa")
        for forbidden in ("startup_time", "start_time", "timestamp", "mtime"):
            assert not hasattr(candidate, forbidden)

    def test_never_master_never_wins(self) -> None:
        rng = random.Random(11)
        candidates = [
            ElectionCandidate(**{**c.__dict__, "never_master": True}) for c in _candidates(rng, 4)
        ]
        assert elect_master(candidates) is None
        assert rank_election_candidates(candidates) == []

    def test_epoch_only_matters_after_readiness(self) -> None:
        """A higher term outranks a newer preference, but not a serving peer."""
        assert (
            elect_master(
                [
                    ElectionCandidate(cid="old-pinned", prefer_master=True, epoch=1),
                    ElectionCandidate(cid="fresh", epoch=2),
                ]
            )
            == "fresh"
        )
        assert (
            elect_master(
                [
                    ElectionCandidate(cid="serving-old", server_ready=True, epoch=1),
                    ElectionCandidate(cid="idle-new", epoch=9),
                ]
            )
            == "serving-old"
        )
        assert (
            elect_master(
                [
                    ElectionCandidate(cid="serving-old", server_ready=True, epoch=1),
                    ElectionCandidate(cid="serving-new", server_ready=True, epoch=2),
                ]
            )
            == "serving-new"
        )
