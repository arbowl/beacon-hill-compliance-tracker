"""Collects basic bill status information by scanning the bill page for
'reported' phrases and grabbing a nearby date.
"""

import re
from datetime import datetime, date
from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import BillAtHearing, BillStatus
from components.utils import compute_deadlines

# Common phrases on bill history when a committee moves a bill
_REPORTED_PATTERNS = [
    r"\breported favorably\b",
    r"\breported adversely\b",
    r"\breported, rules suspended\b",
    r"\breported from the committee\b",
    r"\breported, referred to\b",
]

# Dates often appear like "8/11/2025" or "June 4, 2025" in history notes
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"), "%m/%d/%Y"),
    (re.compile(r"\b([A-Za-z]+ \d{1,2}, \d{4})\b"), "%B %d, %Y"),
]


def _soup(session: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = session.get(url, timeout=20, headers={
        "User-Agent": "legis-scraper/0.1"
    })
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _reported_out_from_bill_page(
    session: requests.Session, bill_url: str
) -> tuple[bool, Optional[date]]:
    """Heuristic: scan the bill page text/history for 'reported' phrases and
    grab a nearby date. Good enough for a baseline.
    """
    soup = _soup(session, bill_url)
    text = soup.get_text(" ", strip=True)
    reported = any(re.search(pat, text, re.I) for pat in _REPORTED_PATTERNS)
    if not reported:
        return False, None
    # Try to pull the closest/last date on the page as an approximation
    last_date: Optional[date] = None
    for rx, fmt in _DATE_PATTERNS:
        for m in rx.finditer(text):
            try:
                last_date = datetime.strptime(m.group(1), fmt).date()
            except Exception:  # pylint: disable=broad-exception-caught
                continue
    return True, last_date


def build_status_row(
    _base_url: str, row: BillAtHearing, extension_until=None
) -> BillStatus:
    """Build the status row."""
    d60, d90, effective = compute_deadlines(row.hearing_date, extension_until)
    with requests.Session() as s:
        reported, rdate = _reported_out_from_bill_page(s, row.bill_url)
    return BillStatus(
        bill_id=row.bill_id,
        committee_id=row.committee_id,
        hearing_date=row.hearing_date,
        deadline_60=d60,
        deadline_90=d90,
        reported_out=reported,
        reported_date=rdate,
        extension_until=extension_until,
        effective_deadline=effective,
    )
