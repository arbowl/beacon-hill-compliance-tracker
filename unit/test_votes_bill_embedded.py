"""Tests for VotesBillEmbeddedParser using the real H4844 cassette."""

from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from components.interfaces import ParserInterface
from components.models import BillAtHearing
from parsers.votes_bill_embedded import VotesBillEmbeddedParser

BASE_URL = "https://malegislature.gov"
CASSETTE_PATH = Path(__file__).parent / "cassettes" / "test_votes_bill_embedded.html"


def _make_bill(bill_id="H4844", committee_id="J10"):
    return BillAtHearing(
        bill_id=bill_id,
        bill_label=bill_id,
        bill_url=f"{BASE_URL}/Bills/194/{bill_id}",
        committee_id=committee_id,
    )


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _cassette_soup() -> BeautifulSoup:
    return _soup(CASSETTE_PATH.read_text(encoding="utf-8"))


class TestVotesBillEmbeddedParserDiscover:
    """Tests for VotesBillEmbeddedParser.discover() against real HTML."""

    def test_discovers_vote_panel_from_cassette(self):
        """Parser finds committeeVote panel in real H4844 HTML."""
        bill = _make_bill()
        cassette = _cassette_soup()

        with patch.object(ParserInterface, "soup", return_value=cassette):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is not None

    def test_source_url_points_to_committee_vote_tab(self):
        """Source URL must reference the CommitteeVote endpoint."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is not None
        assert "CommitteeVote" in result.source_url

    def test_full_text_contains_committee_name(self):
        """full_text must contain the committee name for attribution checks."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is not None
        assert "Municipalities and Regional Government" in result.full_text

    def test_full_text_contains_vote_counts(self):
        """full_text should contain the favorable/adverse vote counts."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is not None
        assert "Favorable" in result.full_text

    def test_confidence_is_high(self):
        """Parser should report high confidence for an embedded panel."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is not None
        assert result.confidence >= 0.9

    def test_returns_none_when_no_vote_panel(self):
        """Returns None when the page has no vote panel or vote keywords."""
        bill = _make_bill()
        empty_html = "<html><body><p>No votes recorded.</p></body></html>"

        with patch.object(ParserInterface, "soup", return_value=_soup(empty_html)):
            result = VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert result is None

    def test_fetches_committee_vote_url(self):
        """discover() must request the /CommitteeVote URL, not the base bill URL."""
        bill = _make_bill()
        fetched_urls = []

        def fake_soup(url, **kwargs):
            fetched_urls.append(url)
            return _cassette_soup()

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            VotesBillEmbeddedParser.discover(BASE_URL, bill)

        assert any("CommitteeVote" in url for url in fetched_urls)


class TestVotesBillEmbeddedParserParse:
    """Tests for VotesBillEmbeddedParser.parse()."""

    def test_parse_returns_location_and_url(self):
        candidate = ParserInterface.DiscoveryResult(
            preview="Vote found",
            full_text="Joint Committee on Municipalities and Regional Government Favorable: 11",
            source_url=f"{BASE_URL}/Bills/194/H4844/CommitteeVote",
            confidence=0.95,
        )
        result = VotesBillEmbeddedParser.parse(BASE_URL, candidate)
        assert result["location"] == "Bill page Votes tab"
        assert result["source_url"] == candidate.source_url
