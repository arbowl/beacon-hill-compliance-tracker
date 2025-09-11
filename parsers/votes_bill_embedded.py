"""A parser for when the votes are on the bill's embedded table."""

from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import BillAtHearing


def _soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


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


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover the votes."""
    with requests.Session() as s:
        soup = _soup(s, bill.bill_url)

        # Quick scan for something that looks like a vote table
        tables = soup.find_all("table")
        for tbl in tables:
            if _looks_like_vote_table(tbl):
                # Build a short preview line (e.g., first few cells)
                txt = " ".join(tbl.get_text(" ", strip=True).split())
                preview = (txt[:180] + "...") if len(txt) > 180 else txt
                return {
                    "preview": f"Embedded vote table detected on bill page "
                    f"for {bill.bill_id}\n\n{preview}",
                    "source_url": bill.bill_url,
                    "confidence": 0.9,
                }
    return None


def parse(base_url: str, candidate: dict) -> dict:
    """Parse the votes."""
    # For compliance we only need presence + URL right now.
    return {"location": "bill_embedded", "source_url": candidate["source_url"]}
