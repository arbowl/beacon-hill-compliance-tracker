"""A parser for votes on an accompanied (cross-referenced) bill's page."""

import re
import logging
from typing import Optional

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from parsers.votes_bill_embedded import VotesBillEmbeddedParser

logger = logging.getLogger(__name__)

# Patterns for "accompanied" action text that references another bill.
# Ordered most-specific first so the first match wins.
_ACCOMPANIED_PATTERNS = [
    re.compile(
        r"Accompanied\s+a\s+(?:study\s+order)[,\s]+see\s+(?P<bill>[HS]\d+)",
        re.I,
    ),
    re.compile(
        r"Accompanied\s+(?:by\s+)?(?P<bill>[HS]\d+)",
        re.I,
    ),
]


class VotesAccompaniedBillParser(ParserInterface):
    """Parser that follows accompanied-bill cross-references to find votes.

    When a bill's action history says something like
    "Accompanied a study order, see S2774", the actual committee vote may
    live on S2774's /CommitteeVote page rather than the original bill's.
    """

    parser_type = ParserInterface.ParserType.VOTES
    location = "Accompanied bill Votes tab"
    cost = 3

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover votes on an accompanied bill's page."""
        logger.debug("Trying %s for %s...", cls.__name__, bill.bill_id)
        soup = cls.soup(bill.bill_url, cache=cache, config=config)
        # Scan action-history rows (date | branch | action text)
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            action_text = cells[2].get_text(" ", strip=True)
            # Try each accompanied pattern
            related_bill_id = None
            for pat in _ACCOMPANIED_PATTERNS:
                m = pat.search(action_text)
                if m:
                    related_bill_id = m.group("bill")
                    break
            if not related_bill_id:
                continue
            # Try to get the URL from an <a> tag in the action cell (more reliable)
            related_url = None
            for a_tag in cells[2].find_all("a", href=True):
                href = a_tag["href"]
                if related_bill_id in href:
                    # Ensure absolute URL
                    if href.startswith("/"):
                        related_url = f"{base_url}{href}"
                    elif href.startswith("http"):
                        related_url = href
                    break
            # Fall back to constructing the URL
            if not related_url:
                related_url = f"{base_url}/Bills/194/{related_bill_id}"
            vote_url = f"{related_url}/CommitteeVote"
            # Fetch the related bill's vote page and check for vote content
            vote_soup = cls.soup(vote_url, cache=cache, config=config)
            # Reuse VotesBillEmbeddedParser's heuristic checks
            panels = vote_soup.find_all(
                "div", class_=lambda c: c and "committeeVote" in c
            )
            for panel in panels:
                if VotesBillEmbeddedParser._looks_like_vote_table(panel):
                    txt = " ".join(panel.get_text(" ", strip=True).split())
                    preview = (txt[:180] + "...") if len(txt) > 180 else txt
                    return ParserInterface.DiscoveryResult(
                        f"Vote found on accompanied bill {related_bill_id} "
                        f"(referenced from {bill.bill_id})\n\n{preview}",
                        txt,
                        vote_url,
                        0.85,
                    )
            summaries = vote_soup.find_all(
                "div", class_=lambda c: c and "committeeVoteSummary" in c
            )
            for summ in summaries:
                if VotesBillEmbeddedParser._looks_like_vote_table(summ):
                    txt = " ".join(summ.get_text(" ", strip=True).split())
                    preview = (txt[:180] + "...") if len(txt) > 180 else txt
                    return ParserInterface.DiscoveryResult(
                        f"Vote summary found on accompanied bill "
                        f"{related_bill_id} (referenced from "
                        f"{bill.bill_id})\n\n{preview}",
                        txt,
                        vote_url,
                        0.85,
                    )
            tables = vote_soup.find_all("table")
            for tbl in tables:
                if VotesBillEmbeddedParser._looks_like_vote_table(tbl):
                    txt = " ".join(tbl.get_text(" ", strip=True).split())
                    preview = (txt[:180] + "...") if len(txt) > 180 else txt
                    return ParserInterface.DiscoveryResult(
                        f"Vote table found on accompanied bill "
                        f"{related_bill_id} (referenced from "
                        f"{bill.bill_id})\n\n{preview}",
                        txt,
                        vote_url,
                        0.85,
                    )
        return None

    @classmethod
    def parse(cls, base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the votes."""
        return {"location": cls.location, "source_url": candidate.source_url}
