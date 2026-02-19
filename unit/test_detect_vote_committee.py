"""Tests for _detect_vote_committee in the pipeline module."""

import pytest

from components.pipeline import _detect_vote_committee


class TestDetectVoteCommittee:
    """Tests for committee detection from vote text."""

    def test_returns_none_for_empty_text(self):
        assert _detect_vote_committee("") is None
        assert _detect_vote_committee(None) is None

    def test_returns_none_for_no_match(self):
        assert _detect_vote_committee("Some random text with no committee") is None

    def test_agriculture_and_fisheries_not_shadowed_by_agriculture(self):
        """Regression: 'Agriculture' (J38) must not shadow 'Agriculture and Fisheries' (J45)."""
        text = (
            "Joint Committee on Agriculture and Fisheries "
            "November 05, 2025 Question: Shall the bill be reported favorably? "
            "Favorable: 11 Adverse: 0 Reserve Right: 0 No Action: 0"
        )
        assert _detect_vote_committee(text) == "J45"

    def test_agriculture_alone_matches_j38(self):
        text = (
            "Joint Committee on Agriculture "
            "October 15, 2025 Question: Shall the bill be reported favorably? "
            "Favorable: 8 Adverse: 3"
        )
        assert _detect_vote_committee(text) == "J38"

    def test_specific_committee_match(self):
        text = "Joint Committee on the Judiciary voted on this bill"
        assert _detect_vote_committee(text) == "J19"

    def test_prefers_longer_match_over_iteration_order(self):
        """When two committee names overlap as substrings, the longer one wins."""
        # "Public Safety and Homeland Security" vs shorter potential matches
        text = (
            "Joint Committee on Public Safety and Homeland Security "
            "Favorable: 5"
        )
        assert _detect_vote_committee(text) == "J22"

    def test_case_insensitive(self):
        text = "JOINT COMMITTEE ON EDUCATION voted favorably"
        assert _detect_vote_committee(text) == "J14"

    def test_multiline_input(self):
        text = (
            "Joint Committee on Revenue\n"
            "December 01, 2025\n"
            "Question: Shall the bill be reported favorably?\n"
            "Favorable: 7\n"
        )
        assert _detect_vote_committee(text) == "J26"
