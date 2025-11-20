"""A parser for when the votes are on the bill's embedded table."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)


class VotesBillEmbeddedParser(ParserInterface):
    """Parser for when the votes are on the bill's embedded table."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page Votes tab"
    cost = 1

    @staticmethod
    def _looks_like_vote_table(tbl: BeautifulSoup) -> bool:
        """Check if the table looks like a vote table."""
        # Heuristic: common vote-related keywords (expandable)
        head_text = " ".join(tbl.get_text(" ", strip=True).split()).lower()
        vote_keywords = [
            "vote",
            "yea",
            "nay",
            "member",
            # committee panel wording seen on the site
            "favorable",
            "adverse",
            "reserve right",
            "no action",
            "question",
            "ought to pass",
        ]

        return any(k in head_text for k in vote_keywords)

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the votes."""
        logger.debug("Trying %s...", cls.__name__)
        soup = cls.soup(f"{bill.bill_url}/CommitteeVote")
        # 1) Look for site-specific committee vote panels by class name
        # Example seen in HTML: div.panel.panel-primary committeeVote
        panels = soup.find_all(
            "div", class_=lambda c: c and "committeeVote" in c
        )
        for panel in panels:
            if cls._looks_like_vote_table(panel):
                txt = " ".join(panel.get_text(" ", strip=True).split())
                preview = (txt[:180] + "...") if len(txt) > 180 else txt
                return ParserInterface.DiscoveryResult(
                    f"Embedded committee vote panel detected on"
                    f"bill page for {bill.bill_id}\n\n{preview}",
                    "",
                    f"{bill.bill_url}/CommitteeVote",
                    0.95,
                )

        # 2) Look for a summary block that may contain vote counts/names
        summaries = soup.find_all(
            "div", class_=lambda c: c and "committeeVoteSummary" in c
        )
        for summ in summaries:
            if cls._looks_like_vote_table(summ):
                txt = " ".join(summ.get_text(" ", strip=True).split())
                preview = (txt[:180] + "...") if len(txt) > 180 else txt
                return ParserInterface.DiscoveryResult(
                    f"Embedded committee vote summary detected on "
                    f"bill page for {bill.bill_id}\n\n{preview}",
                    "",
                    f"{bill.bill_url}/CommitteeVote",
                    0.95,
                )

        # 3) Fallback: scan tables as before
        tables = soup.find_all("table")
        for tbl in tables:
            if cls._looks_like_vote_table(tbl):
                # Build a short preview line (e.g., first few cells)
                txt = " ".join(tbl.get_text(" ", strip=True).split())
                preview = (txt[:180] + "...") if len(txt) > 180 else txt
                return ParserInterface.DiscoveryResult(
                    f"Embedded vote table detected on bill page "
                    f"for {bill.bill_id}\n\n{preview}",
                    "",
                    bill.bill_url,
                    0.9,
                )
        return None

    @classmethod
    def parse(
        cls, base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the votes."""
        # For compliance we only need presence + URL right now.
        return {"location": cls.location, "source_url": candidate.source_url}

