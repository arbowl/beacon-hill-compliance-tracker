"""Collects basic bill status information by scanning the bill page for
'reported' phrases and grabbing a nearby date.
"""

import re
from datetime import datetime, date
from typing import Optional

from components.models import BillAtHearing, BillStatus
from components.utils import (
    Cache, compute_deadlines, extract_session_from_bill_url
)
from components.interfaces import ParserInterface

# Common phrases on bill history when a committee moves a bill
_REPORTED_PATTERNS = [
    re.compile(r"\breported favorably\b"),
    re.compile(r"\breported adversely\b"),
    re.compile(r"\breported, rules suspended\b"),
    re.compile(r"\breported from the committee\b"),
    re.compile(r"\breported, referred to\b"),
    re.compile(r"\bstudy\b"),
    re.compile(r"\baccompan\b"),
    re.compile(r"\bdischarge\b"),
]

# Dates often appear like "8/11/2025" or "June 4, 2025" in history notes
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"), "%m/%d/%Y"),
    (re.compile(r"\b([A-Za-z]+ \d{1,2}, \d{4})\b"), "%B %d, %Y"),
]


def _reported_out_from_bill_page(
    bill_url: str,
    committee_id: str,
    hearing_date: Optional[date] = None,
) -> tuple[bool, Optional[date]]:
    """
    Heuristic: scan the bill history table for 'reported' actions and capture
    the most credible report-out date for THIS committee.

    Returns:
        (reported_out, reported_date)  — reported_date is the *latest* valid
        report-out on/after hearing_date (if provided), never in the future.
    """
    soup = ParserInterface.soup(bill_url)
    prefix = (committee_id or "J")[0].upper()
    expected_branch = {
        "J": "Joint", "H": "House", "S": "Senate"
    }.get(prefix, "Joint")
    acceptable_branches = {expected_branch}
    if expected_branch != "Joint":
        acceptable_branches.add("Joint")
    today = date.today()
    reported = False
    matched_date: Optional[date] = None
    for row in soup.find_all("tr"):  # type: ignore
        cells = row.find_all(["td", "th"])  # type: ignore
        if len(cells) < 3:
            continue
        branch_text = cells[1].get_text(" ", strip=True)
        if branch_text not in acceptable_branches:
            continue
        action_text = cells[2].get_text(" ", strip=True)
        if any(p.search(action_text) for p in _REPORTED_PATTERNS):
            date_text = cells[0].get_text(" ", strip=True)
            parsed_row_date: Optional[date] = None
            for rx, fmt in _DATE_PATTERNS:
                m = rx.search(date_text)
                if not m:
                    continue
                try:
                    parsed_row_date = datetime.strptime(m.group(1), fmt).date()
                except Exception:  # pylint: disable=broad-exception-caught
                    parsed_row_date = None
                if parsed_row_date:
                    break
            if not parsed_row_date:
                continue
            if hearing_date and parsed_row_date < hearing_date:
                continue
            if parsed_row_date > today:
                continue
            if matched_date is None or parsed_row_date > matched_date:
                matched_date = parsed_row_date
                reported = True
    if not reported:
        return False, None
    return True, matched_date


def _hearing_announcement_from_bill_page(
    bill_url: str,
    target_hearing_date: Optional[date] = None
) -> tuple[Optional[date], Optional[date]]:
    """Extract 'Hearing scheduled for ...' announcement.

    Args:
        bill_url: URL of the bill page
        target_hearing_date: If provided, find announcement for this date.
                           If None, find the earliest hearing announcement.

    Returns (announcement_date, scheduled_hearing_date) or (None, None).
    """
    soup = ParserInterface.soup(bill_url)
    # Look for table rows in the bill history
    rows = soup.find_all('tr')  # type: ignore
    earliest_announcement: Optional[date] = None
    earliest_hearing: Optional[date] = None
    for row in rows:
        cells = row.find_all(['td', 'th'])  # type: ignore
        if len(cells) < 3:
            continue
        # First cell typically contains the announcement date
        date_cell = cells[0].get_text(strip=True)
        action_cell = cells[2].get_text(strip=True) if len(cells) > 2 else ""
        # Look for "Hearing scheduled for" pattern
        hearing_match = re.search(
            r"(?i)hearing (scheduled|rescheduled) (for|to) (\d{1,2}/\d{1,2}/\d{4})",
            action_cell,
            re.I
        )
        if hearing_match:
            # Parse announcement date
            announcement_date = None
            for rx, fmt in _DATE_PATTERNS:
                match = rx.search(date_cell)
                if match:
                    try:
                        announcement_date = datetime.strptime(
                            match.group(1), fmt
                        ).date()
                        break
                    except Exception:  # pylint: disable=broad-exception-caught
                        continue
            # Parse scheduled hearing date
            try:
                hearing_date = datetime.strptime(
                    hearing_match.group(3), "%m/%d/%Y"
                ).date()
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            # If target date specified, look for exact match
            if target_hearing_date and hearing_date == target_hearing_date:
                return announcement_date, hearing_date
            # Otherwise, keep the earliest hearing (past or future)
            if (announcement_date and hearing_date and
                    (earliest_hearing is None or
                     hearing_date < earliest_hearing)):
                earliest_announcement = announcement_date
                earliest_hearing = hearing_date
    return earliest_announcement, earliest_hearing

# =============================================================================
# Public helper: fetch bill title
# =============================================================================


def get_bill_title(bill_url: str) -> str | None:
    """Return the human-readable title of a bill (e.g., "An Act …") or None.

    The bill detail page typically shows the long title just below the header.
    On live pages (e.g., https://malegislature.gov/Bills/194/H2244) the title
    appears in text that starts with "An Act", "An Resolve", or "A Resolve".
    """
    soup = ParserInterface.soup(bill_url)
    # 0. Find the H2 whose parent is the main content area (col-md-8 container)
    # The bill title is consistently in an H2 whose parent div has Bootstrap
    # classes col-xs-12 col-md-8 (the main content column)
    for h2 in soup.find_all('h2'):
        parent = h2.parent
        if parent:
            parent_classes = parent.get('class')
            if parent_classes and 'col-md-8' in parent_classes:
                return " ".join(h2.get_text(" ", strip=True).split())

    # 1. Direct class match (fallback if H2 missing)
    tag = soup.find(class_=re.compile(r"bill-title", re.I))
    if tag and tag.get_text(strip=True):
        return " ".join(tag.get_text(strip=True).split())

    # 2. Heuristic: scan heading/paragraph/div tags near top of page and pick
    #    the shortest plausible line containing "An Act"/"A Resolve".
    candidate_rx = re.compile(r"\b(an|a)\s+(act|resolve)\b", re.I)
    candidates: list[str] = []
    for t in soup.select("h1, h2, h3, p, div")[:40]:
        txt = " ".join(t.get_text(" ", strip=True).split())
        if candidate_rx.search(txt):
            # Remove obvious trailing boilerplate if present
            for stop in ["Bill History", "Displaying", "Tabs", "Sponsor:"]:
                if stop in txt:
                    txt = txt.split(stop, maxsplit=1)[0].strip()
            # sanity length filter
            if 5 < len(txt) < 200:
                candidates.append(txt)

    if candidates:
        # prefer the shortest (usually the clean title)
        return min(candidates, key=len)

    return None


def build_status_row(
    _base_url: str, row: BillAtHearing, cache: Cache, extension_until=None
) -> BillStatus:
    """Build the status row."""
    # Extract session from bill_url if available
    session = (
        extract_session_from_bill_url(row.bill_url)
        if row.bill_url else None
    )
    d60, d90, effective = compute_deadlines(
        row.hearing_date, extension_until, row.bill_id, session
    )
    # Try to get hearing announcement from cache first
    cached_announcement = cache.get_hearing_announcement(row.bill_id)
    if cached_announcement:
        announce_date_str = cached_announcement.get("announcement_date")
        sched_hearing_str = cached_announcement.get("scheduled_hearing_date")
        # Convert strings back to dates
        announce_date = None
        sched_hearing = None
        if announce_date_str:
            try:
                announce_date = datetime.strptime(
                    announce_date_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass
        if sched_hearing_str:
            try:
                sched_hearing = datetime.strptime(
                    sched_hearing_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                pass
        # Re-fetch if we have a hearing_date but no cached announcement,
        # or if the cached hearing date doesn't match the current hearing_date
        should_refetch = False
        if row.hearing_date is not None:
            # If we have a hearing date but no cached announcement, re-fetch
            if announce_date is None or sched_hearing is None:
                should_refetch = True
            # If the cached hearing date doesn't match the current, re-fetch
            elif sched_hearing != row.hearing_date:
                should_refetch = True
        if should_refetch:
            announce_date, sched_hearing = (
                _hearing_announcement_from_bill_page(
                    row.bill_url, row.hearing_date
                )
            )
            announce_date_str = str(announce_date) if announce_date else None
            sched_hearing_str = str(sched_hearing) if sched_hearing else None
            cache.set_hearing_announcement(
                row.bill_id, announce_date_str, sched_hearing_str, row.bill_url
            )
    else:
        announce_date, sched_hearing = (
            _hearing_announcement_from_bill_page(
                row.bill_url, row.hearing_date
            )
        )
        announce_date_str = str(announce_date) if announce_date else None
        sched_hearing_str = str(sched_hearing) if sched_hearing else None
        cache.set_hearing_announcement(
            row.bill_id, announce_date_str, sched_hearing_str, row.bill_url
        )
    reported, rdate = _reported_out_from_bill_page(
        row.bill_url, row.committee_id, row.hearing_date
    )
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
        announcement_date=announce_date,
        scheduled_hearing_date=sched_hearing,
    )
