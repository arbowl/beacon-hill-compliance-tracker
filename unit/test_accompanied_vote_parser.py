"""Tests for VotesAccompaniedBillParser."""

from unittest.mock import patch

from bs4 import BeautifulSoup

from components.interfaces import ParserInterface
from components.models import BillAtHearing
from parsers.votes_accompanied_bill import VotesAccompaniedBillParser


BASE_URL = "https://malegislature.gov"


def _make_bill(bill_id="H100", committee_id="J33"):
    return BillAtHearing(
        bill_id=bill_id,
        bill_label=bill_id,
        bill_url=f"{BASE_URL}/Bills/194/{bill_id}",
        committee_id=committee_id,
    )


def _bill_page_html(action_text, related_bill_id=None, include_link=True):
    """Build a minimal bill page with an action-history row."""
    link = ""
    if related_bill_id and include_link:
        link = (
            f' <a href="/Bills/194/{related_bill_id}">{related_bill_id}</a>'
        )
    return f"""
    <html><body>
    <table>
      <tr><th>Date</th><th>Branch</th><th>Action</th></tr>
      <tr>
        <td>01/15/2025</td>
        <td>Senate</td>
        <td>{action_text}{link}</td>
      </tr>
    </table>
    </body></html>
    """


def _vote_page_html(has_votes=True):
    """Build a minimal CommitteeVote page."""
    if has_votes:
        return """
        <html><body>
        <div class="committeeVote panel panel-primary">
          <table>
            <tr><th>Member</th><th>Vote</th></tr>
            <tr><td>Smith</td><td>Yea</td></tr>
            <tr><td>Jones</td><td>Nay</td></tr>
          </table>
        </div>
        </body></html>
        """
    return "<html><body><p>No votes recorded.</p></body></html>"


def _soup(html):
    return BeautifulSoup(html, "html.parser")


class TestVotesAccompaniedBillParser:
    """Tests for VotesAccompaniedBillParser.discover()."""

    def test_study_order_with_see(self):
        """Accompanied a study order, see S2774 — with <a> tag."""
        bill = _make_bill()
        bill_html = _bill_page_html(
            "Accompanied a study order, see S2774", "S2774"
        )
        vote_html = _vote_page_html(has_votes=True)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S2774/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert "S2774" in result.preview
        assert "S2774/CommitteeVote" in result.source_url
        assert result.confidence == 0.85

    def test_new_draft_with_see(self):
        """Accompanied a new draft, see S1000."""
        bill = _make_bill()
        bill_html = _bill_page_html(
            "Accompanied a new draft, see S1000", "S1000"
        )
        vote_html = _vote_page_html(has_votes=True)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S1000/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is None

    def test_accompanied_by(self):
        """Accompanied by H5000."""
        bill = _make_bill()
        bill_html = _bill_page_html("Accompanied by H5000", "H5000")
        vote_html = _vote_page_html(has_votes=True)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "H5000/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert "H5000" in result.preview

    def test_accompanied_without_by(self):
        """Accompanied S3000 (no 'by' keyword)."""
        bill = _make_bill()
        bill_html = _bill_page_html("Accompanied S3000", "S3000")
        vote_html = _vote_page_html(has_votes=True)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S3000/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert "S3000" in result.preview

    def test_no_accompanied_action(self):
        """Bill page with no accompanied action returns None."""
        bill = _make_bill()
        bill_html = """
        <html><body>
        <table>
          <tr><th>Date</th><th>Branch</th><th>Action</th></tr>
          <tr>
            <td>01/15/2025</td>
            <td>House</td>
            <td>Referred to the committee on Ways and Means</td>
          </tr>
        </table>
        </body></html>
        """

        with patch.object(
            ParserInterface, "soup", return_value=_soup(bill_html)
        ):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is None

    def test_accompanied_bill_has_no_votes(self):
        """Accompanied bill exists but has no vote content."""
        bill = _make_bill()
        bill_html = _bill_page_html(
            "Accompanied a study order, see S2774", "S2774"
        )
        vote_html = _vote_page_html(has_votes=False)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S2774/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is None

    def test_fallback_url_when_no_link_tag(self):
        """When no <a> tag is present, construct the URL from the bill ID."""
        bill = _make_bill()
        bill_html = _bill_page_html(
            "Accompanied a study order, see S2774",
            related_bill_id="S2774",
            include_link=False,
        )
        vote_html = _vote_page_html(has_votes=True)

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S2774/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert result.source_url == f"{BASE_URL}/Bills/194/S2774/CommitteeVote"

    def test_vote_summary_div(self):
        """Detect votes via committeeVoteSummary div."""
        bill = _make_bill()
        bill_html = _bill_page_html(
            "Accompanied a study order, see S2774", "S2774"
        )
        vote_html = """
        <html><body>
        <div class="committeeVoteSummary">
          <p>Question: Ought to pass - Favorable: 8, Adverse: 3</p>
        </div>
        </body></html>
        """

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S2774/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert "S2774" in result.preview

    def test_vote_table_fallback(self):
        """Detect votes via bare <table> with vote keywords."""
        bill = _make_bill()
        bill_html = _bill_page_html("Accompanied by S5555", "S5555")
        vote_html = """
        <html><body>
        <table>
          <tr><th>Member</th><th>Vote</th></tr>
          <tr><td>Rep. Adams</td><td>Yea</td></tr>
          <tr><td>Rep. Baker</td><td>Nay</td></tr>
        </table>
        </body></html>
        """

        def fake_soup(url, **kwargs):
            if url == bill.bill_url:
                return _soup(bill_html)
            if "S5555/CommitteeVote" in url:
                return _soup(vote_html)
            return _soup("")

        with patch.object(ParserInterface, "soup", side_effect=fake_soup):
            result = VotesAccompaniedBillParser.discover(BASE_URL, bill)

        assert result is not None
        assert "S5555" in result.preview


class TestVotesAccompaniedBillParserParse:
    """Tests for VotesAccompaniedBillParser.parse()."""

    def test_parse_returns_location_and_url(self):
        candidate = ParserInterface.DiscoveryResult(
            preview="Vote found",
            full_text="",
            source_url=f"{BASE_URL}/Bills/194/S2774/CommitteeVote",
            confidence=0.85,
        )
        result = VotesAccompaniedBillParser.parse(BASE_URL, candidate)
        assert result["location"] == "Accompanied bill Votes tab"
        assert result["source_url"] == candidate.source_url
