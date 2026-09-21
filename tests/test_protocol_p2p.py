# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# Copyright (C) 2025 Alberto Basso

"""Tests for the canonical LAN master-election algorithm.

These verify the single source of truth in ``hsync_common.protocol.p2p`` against
hand-written expectations (independent of the committed fixtures) and assert that
the published election-scenario fixture is exactly what the algorithm decides, so
the cross-language parity test consumes a known-correct contract.
"""

from hsync_common.protocol.fixtures import build_fixtures
from hsync_common.protocol.p2p import (
    SYNC_DIRECTION_BIDIRECTIONAL,
    ElectionCandidate,
    elect_master,
    election_sort_key,
    rank_election_candidates,
)


class TestElectionOrdering:
    """The sort key encodes the documented priority order."""

    def test_server_ready_incumbent_wins_over_force_master(self):
        candidates = [
            ElectionCandidate(cid="local", force_master=True, startup_time=10.0),
            ElectionCandidate(cid="incumbent", startup_time=200.0, server_ready=True),
        ]
        assert elect_master(candidates) == "incumbent"

    def test_force_master_wins_over_plain_peer(self):
        candidates = [
            ElectionCandidate(cid="plain", startup_time=50.0),
            ElectionCandidate(cid="forced", force_master=True, startup_time=300.0),
        ]
        assert elect_master(candidates) == "forced"

    def test_bidirectional_preferred_over_directional(self):
        candidates = [
            ElectionCandidate(cid="aaa", startup_time=100.0, sync_direction="upload-only"),
            ElectionCandidate(cid="bbb", startup_time=100.0),
        ]
        assert elect_master(candidates) == "bbb"

    def test_earliest_startup_wins(self):
        candidates = [
            ElectionCandidate(cid="late", startup_time=200.0),
            ElectionCandidate(cid="early", startup_time=100.0),
        ]
        assert elect_master(candidates) == "early"

    def test_lowest_cid_breaks_tie(self):
        candidates = [
            ElectionCandidate(cid="zzz", startup_time=100.0),
            ElectionCandidate(cid="aaa", startup_time=100.0),
        ]
        assert elect_master(candidates) == "aaa"

    def test_default_sync_direction_is_bidirectional(self):
        assert ElectionCandidate(cid="x").sync_direction == SYNC_DIRECTION_BIDIRECTIONAL


class TestNeverMaster:
    """``never_master`` nodes are excluded from candidacy."""

    def test_never_master_peer_excluded(self):
        candidates = [
            ElectionCandidate(cid="never", startup_time=100.0, never_master=True),
            ElectionCandidate(cid="eligible", startup_time=200.0),
        ]
        assert elect_master(candidates) == "eligible"

    def test_all_never_master_yields_no_master(self):
        candidates = [
            ElectionCandidate(cid="a", never_master=True),
            ElectionCandidate(cid="b", never_master=True),
        ]
        assert elect_master(candidates) is None

    def test_empty_candidate_set_yields_no_master(self):
        assert elect_master([]) is None


class TestRankElectionCandidates:
    """``rank_election_candidates`` is the SSOT ranking every consumer shares."""

    def test_full_ranking_order(self):
        # server_ready > force_master > bidirectional > earliest startup > cid
        candidates = [
            ElectionCandidate(cid="plain-late", startup_time=500.0),
            ElectionCandidate(cid="forced", force_master=True, startup_time=300.0),
            ElectionCandidate(cid="incumbent", startup_time=200.0, server_ready=True),
            ElectionCandidate(cid="plain-early", startup_time=100.0),
        ]
        ranked = rank_election_candidates(candidates)
        assert [c.cid for c in ranked] == [
            "incumbent",
            "forced",
            "plain-early",
            "plain-late",
        ]

    def test_never_master_filtered_out(self):
        candidates = [
            ElectionCandidate(cid="never", never_master=True),
            ElectionCandidate(cid="eligible", startup_time=100.0),
        ]
        assert [c.cid for c in rank_election_candidates(candidates)] == ["eligible"]

    def test_empty_and_all_excluded_yield_empty_list(self):
        assert rank_election_candidates([]) == []
        assert rank_election_candidates([ElectionCandidate(cid="a", never_master=True)]) == []

    def test_winner_matches_elect_master(self):
        # elect_master must be the winner-only projection of the shared ranking.
        candidates = [
            ElectionCandidate(cid="zzz", startup_time=100.0),
            ElectionCandidate(cid="aaa", startup_time=100.0),
            ElectionCandidate(cid="mmm", never_master=True),
        ]
        ranked = rank_election_candidates(candidates)
        assert elect_master(candidates) == ranked[0].cid

    def test_input_order_does_not_affect_ranking(self):
        base = [
            ElectionCandidate(cid="a", startup_time=100.0),
            ElectionCandidate(cid="b", startup_time=50.0),
            ElectionCandidate(cid="c", startup_time=75.0),
        ]
        assert rank_election_candidates(base) == rank_election_candidates(list(reversed(base)))


class TestSortKey:
    """The exposed sort key is usable directly and is stable."""

    def test_sort_key_orders_candidates(self):
        a = ElectionCandidate(cid="a", startup_time=100.0)
        b = ElectionCandidate(cid="b", startup_time=100.0, server_ready=True)
        assert election_sort_key(b) < election_sort_key(a)


class TestElectionScenarioFixture:
    """The published scenario fixture matches the algorithm decision."""

    def test_each_scenario_expectation_is_recomputable(self):
        scenarios = build_fixtures()["p2p-election-scenarios"]["scenarios"]
        assert scenarios, "expected at least one election scenario"
        for scenario in scenarios:
            candidates = [ElectionCandidate(**c) for c in scenario["candidates"]]
            assert scenario["expected_master"] == elect_master(candidates), scenario["name"]
