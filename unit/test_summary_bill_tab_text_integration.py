"""Integration tests for SummaryBillTabTextParser against live bill pages."""

import pytest

from components.models import BillAtHearing
from parsers.summary_bill_tab_text import SummaryBillTabTextParser

BASE_URL = "https://malegislature.gov"


def _make_bill(bill_id, committee_id="J22"):
    return BillAtHearing(
        bill_id=bill_id,
        bill_label=bill_id,
        bill_url=f"{BASE_URL}/Bills/194/{bill_id}",
        committee_id=committee_id,
    )


@pytest.mark.integration
@pytest.mark.slow
class TestSummaryBillTabTextParserLive:
    """Live scrape tests -- make real HTTP requests, no mocking."""

    def test_discovers_summary_for_s1262(self):
        """S1262 has a known Primary Sponsor Summary -- parser must find it."""
        bill = _make_bill("S1262")
        result = SummaryBillTabTextParser.discover(BASE_URL, bill)
        assert result is not None

    def test_s1262_full_text_is_substantive(self):
        """full_text must contain actual prose, not navigation or boilerplate."""
        bill = _make_bill("S1262")
        result = SummaryBillTabTextParser.discover(BASE_URL, bill)
        assert result is not None
        assert len(result.full_text) > 50
        assert "hate crime" in result.full_text.lower()

    def test_s1262_source_url(self):
        """Source URL must point to the PrimarySponsorSummary endpoint."""
        bill = _make_bill("S1262")
        result = SummaryBillTabTextParser.discover(BASE_URL, bill)
        assert result is not None
        assert result.source_url == f"{BASE_URL}/Bills/194/S1262/PrimarySponsorSummary"
