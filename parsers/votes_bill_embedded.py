"""A parser for when the votes are on the bill's embedded table."""

from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import BillAtHearing
from components.interfaces import ParserInterface


class VotesBillEmbeddedParser(ParserInterface):

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page Votes tab"
    cost = 1

    @staticmethod
    def _looks_like_vote_table(tbl: BeautifulSoup) -> bool:
        """Check if the table looks like a vote table."""
        # Heuristic: headers like "Member" and "Yea/Nay", or a
        # caption containing "Vote"
        head_text = " ".join(tbl.get_text(" ", strip=True).split()).lower()
        return (
            "vote"
            in head_text and (
                "yea" in head_text or "nay" in head_text or "member" in head_text
            )
        )

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the votes."""
        print(f"Trying {cls.__name__}...")
        with requests.Session() as s:
            soup = cls._soup(s, bill.bill_url)

            # Quick scan for something that looks like a vote table
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
