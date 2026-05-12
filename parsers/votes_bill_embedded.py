"""A parser for when the votes are on the bill's embedded table."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from timeline.normalizers import get_committee

logger = logging.getLogger(__name__)


class VotesBillEmbeddedParser(ParserInterface):
    """Parser for when the votes are on the bill's embedded table."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page Votes tab"
    cost = 1
    file_format = "html"

    @staticmethod
    def _pick_for_committee(candidates: list, committee_id: str) -> BeautifulSoup:
        """Return the candidate whose text matches the committee; fall back to first."""
        committee = get_committee(committee_id)
        if committee:
            for candidate in candidates:
                if committee.matches(candidate.get_text(" ", strip=True)):
                    return candidate
        return candidates[0]

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
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the votes."""
        logger.debug("Trying %s...", cls.__name__)
        url = f"{bill.bill_url}/CommitteeVote"
        soup = cls.soup(url, cache=cache, config=config)

        # 1) committeeVote panels (highest confidence)
        candidates = [
            p for p in soup.find_all("div", class_=lambda c: c and "committeeVote" in c)
            if cls._looks_like_vote_table(p)
        ]
        confidence = 0.95

        # 2) committeeVoteSummary divs
        if not candidates:
            candidates = [
                s for s in soup.find_all(
                    "div", class_=lambda c: c and "committeeVoteSummary" in c
                )
                if cls._looks_like_vote_table(s)
            ]

        # 3) Fallback: any table
        if not candidates:
            candidates = [t for t in soup.find_all("table") if cls._looks_like_vote_table(t)]
            confidence = 0.9

        if not candidates:
            return None

        chosen = cls._pick_for_committee(candidates, bill.committee_id)
        txt = " ".join(chosen.get_text(" ", strip=True).split())
        preview = (txt[:180] + "...") if len(txt) > 180 else txt
        return ParserInterface.DiscoveryResult(
            f"Embedded committee vote detected on bill page for {bill.bill_id}\n\n{preview}",
            txt,
            url,
            confidence,
        )

    @classmethod
    def parse(cls, base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the votes."""
        # For compliance we only need presence + URL right now.
        return {"location": cls.location, "source_url": candidate.source_url}
