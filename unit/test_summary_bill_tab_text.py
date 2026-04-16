"""Tests for SummaryBillTabTextParser using the real S1262 cassette."""

from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from components.interfaces import ParserInterface
from components.models import BillAtHearing
from parsers.summary_bill_tab_text import SummaryBillTabTextParser

BASE_URL = "https://malegislature.gov"
CASSETTE_PATH = Path(__file__).parent / "cassettes" / "test_summary_bill_tab_text.html"


def _make_bill(bill_id="S1262", committee_id="J22"):
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


class TestSummaryBillTabTextParserDiscover:
    """Tests for SummaryBillTabTextParser.discover() against real HTML."""

    def test_discovers_summary_from_cassette(self):
        """Parser finds the primary sponsor summary in real S1262 HTML."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = SummaryBillTabTextParser.discover(BASE_URL, bill)

        assert result is not None

    def test_full_text_contains_summary_content(self):
        """full_text must contain the actual bill summary prose."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = SummaryBillTabTextParser.discover(BASE_URL, bill)

        assert result is not None
        assert "hate crime" in result.full_text.lower()

    def test_source_url_points_to_primary_sponsor_summary(self):
        """Source URL must reference the PrimarySponsorSummary endpoint."""
        bill = _make_bill()

        with patch.object(ParserInterface, "soup", return_value=_cassette_soup()):
            result = SummaryBillTabTextParser.discover(BASE_URL, bill)

        assert result is not None
        assert "PrimarySponsorSummary" in result.source_url

    def test_returns_none_when_no_summary_content(self):
        """Returns None when the active tab-pane has no summary prose."""
        bill = _make_bill()
        empty_html = """
        <html><body>
        <div class="active tab-pane" role="tabpanel">
            <p>No summary provided.</p>
        </div>
        </body></html>
        """

        with patch.object(ParserInterface, "soup", return_value=_soup(empty_html)):
            result = SummaryBillTabTextParser.discover(BASE_URL, bill)

        assert result is None


class TestSummaryBillTabTextParserParse:
    """Tests for SummaryBillTabTextParser.parse()."""

    def test_parse_returns_source_url(self):
        candidate = ParserInterface.DiscoveryResult(
            preview="The bill proposes...",
            full_text="The bill proposes to amend the existing hate crime law.",
            source_url=f"{BASE_URL}/Bills/194/S1262/PrimarySponsorSummary",
            confidence=0.95,
        )
        result = SummaryBillTabTextParser.parse(BASE_URL, candidate)
        assert result["source_url"] == candidate.source_url
