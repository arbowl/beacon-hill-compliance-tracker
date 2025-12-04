"""Collects basic bill status information by scanning the bill page for
'reported' phrases and grabbing a nearby date.
"""

import re
from datetime import datetime, date, timedelta
from typing import Optional

from components.models import BillAtHearing, BillStatus
from components.utils import (
    Cache, compute_deadlines, extract_session_from_bill_url
)
from components.interfaces import ParserInterface

from timeline.parser import extract_timeline

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
_HEARING_PATTERNS = [
    # Most common
    re.compile(
        r"hearing\s+(scheduled|rescheduled)\s+(for|to)\s+(\d{1,2}/\d{1,2}/\d{4})",
        re.I
    ),
    # Useful if there's filler text or committee names interspersed
    re.compile(
        r"hearing\s+(scheduled|rescheduled)\b.*?\b(for|to)\s+(\d{1,2}/\d{1,2}/\d{4})",
        re.I
    ),
    # Uncommon variant
    re.compile(
        r"public\s+hearing\s+(scheduled|rescheduled)\s+(for|to)\s+(\d{1,2}/\d{1,2}/\d{4})",
        re.I
    ),
]

_BRANCH_BY_PREFIX = {"J": "Joint", "H": "House", "S": "Senate"}


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
    committee_id: Optional[str] = None,
    target_hearing_date: Optional[date] = None,
    window_days: int = 10,
) -> tuple[Optional[date], Optional[date]]:
    """
    Return (announcement_date, hearing_date) for the *latest valid* hearing
    announcement attributable to the expected branch/committee.

    Filters:
      - Only rows whose Branch column matches expected branch (from committee_id)
      - announcement_date < hearing_date <= today
      - If target_hearing_date is given, require hearing_date within +/- window_days
      - Picks the *latest* valid hearing announcement (handles reschedules)
    """
    soup = ParserInterface.soup(bill_url)
    expected_branch = None
    if committee_id:
        expected_branch = _BRANCH_BY_PREFIX.get(committee_id[0].upper(), None)
    today = date.today()
    best_announcement: Optional[date] = None
    best_hearing: Optional[date] = None
    for row in soup.find_all("tr"):  # type: ignore
        cells = row.find_all(["td", "th"])  # type: ignore
        if len(cells) < 3:
            continue
        branch_cell = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
        if expected_branch and branch_cell and branch_cell != expected_branch:
            continue
        action_text = cells[2].get_text(" ", strip=True)
        m = None
        for rx in _HEARING_PATTERNS:
            m = rx.search(action_text)
            if m:
                break
        if not m:
            continue
        announcement_date = None
        date_cell = cells[0].get_text(" ", strip=True)
        for rx, fmt in _DATE_PATTERNS:
            dm = rx.search(date_cell)
            if not dm:
                continue
            try:
                announcement_date = datetime.strptime(dm.group(1), fmt).date()
                break
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        try:
            hearing_date = datetime.strptime(m.group(3), "%m/%d/%Y").date()
        except Exception:  # pylint: disable=broad-exception-caught
            continue
        if announcement_date is None:
            continue
        if announcement_date >= hearing_date:
            continue
        if hearing_date > today:
            continue
        if target_hearing_date:
            low = target_hearing_date - timedelta(days=window_days)
            high = target_hearing_date + timedelta(days=window_days)
            if not low <= hearing_date <= high:
                continue
        if best_hearing is None or hearing_date > best_hearing:
            best_hearing = hearing_date
            best_announcement = announcement_date
        elif hearing_date == best_hearing and best_announcement and announcement_date > best_announcement:
            best_announcement = announcement_date
    return best_announcement, best_hearing

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


def get_committee_tenure(bill_url: str, committee_id: str) -> Optional[dict]:
    """Get committee tenure information for a bill and committee."""
    # Report-out
    try:
        timeline = extract_timeline(bill_url)
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    referrals = timeline.get_actions_by_type("REFERRED")
    discharges = timeline.get_actions_by_type("DISCHARGED")
    tenure_start_action = None
    for action in sorted(referrals + discharges, key=lambda a: a.date):
        action_committee = action.extracted_data.get("committee_id")
        if action_committee == committee_id:
            tenure_start_action = action
            break
    if not tenure_start_action:
        return None
    tenure_start = tenure_start_action.date
    reported_actions = timeline.get_actions_by_type("REPORTED")
    reported_date = None
    for action in reported_actions:
        action_committee = action.extracted_data.get("committee_id")
        if not action_committee:
            prior_refs = [r for r in (referrals + discharges) if r.date < action.date]
            if prior_refs:
                latest_ref = max(prior_refs, key=lambda r: r.date)
                action_committee = latest_ref.extracted_data.get("committee_id")
        if action_committee == committee_id and action.date >= tenure_start:
            reported_date = action.date
            break
    discharged_date = None
    for action in sorted(referrals + discharges, key=lambda a: a.date):
        if action.date > tenure_start:
            next_committee = action.extracted_data
            if next_committee and next_committee != committee_id:
                discharged_date = action.date
                break
    tenure_end = None
    is_active = True
    if reported_date:
        tenure_end = reported_date
        is_active = False
    elif discharged_date:
        tenure_end = discharged_date
        is_active = False
    else:
        tenure_end = date.today()
        is_active = True
    scheduled = timeline.get_actions_by_type("HEARING_SCHEDULED")
    rescheduled = timeline.get_actions_by_type("HEARING_RESCHEDULED")
    all_hearings = []
    hearing_announcement_date = None
    hearing_date = None
    for action in sorted(scheduled + rescheduled, key=lambda a: a.date):
        action_committee = action.extracted_data.get("committee_id")
        if not action_committee:
            action_committee = committee_id
        if action_committee == committee_id:
            if tenure_start <= action.date <= tenure_end:
                hearing_date_str = action.extracted_data.get("hearing_date")
                if hearing_date_str:
                    hearing_dt = date.fromisoformat(hearing_date_str)
                    all_hearings.append({
                        "announcement_date": action.date,
                        "hearing_date": hearing_dt,
                        "action_type": action.action_type,
                    })
    if all_hearings:
        latest_hearing = max(all_hearings, key=lambda h: h["hearing_date"])
        hearing_announcement_date = latest_hearing["announcement_date"]
        hearing_date = latest_hearing["hearing_date"]
    notice_days = None
    if hearing_announcement_date and hearing_date:
        notice_days = (hearing_date - hearing_announcement_date).days
    hearing_to_report_days = None
    if hearing_date and reported_date:
        hearing_to_report_days = (reported_date - hearing_date).days
    referred_to_report_days = None
    if reported_date:
        referred_to_report_days = (reported_date - tenure_start).days
    return {
        "committee_id": committee_id,
        "referred_date": tenure_start,
        "hearing_announcement_date": hearing_announcement_date,
        "hearing_date": hearing_date,
        "all_hearing_dates": [h["hearing_date"] for h in all_hearings],
        "all_hearings": all_hearings,
        "reported_date": reported_date,
        "discharged_date": discharged_date,
        "tenure_start": tenure_start,
        "tenure_end": tenure_end,
        "notice_days": notice_days,
        "hearing_to_report_days": hearing_to_report_days,
        "referred_to_report_days": referred_to_report_days,
        "is_active": is_active,
    }


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
                    row.bill_url, row.committee_id, row.hearing_date
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
                row.bill_url, row.committee_id, row.hearing_date
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
    tenure_info = get_committee_tenure(row.bill_url, row.committee_id)
    if tenure_info:
        if tenure_info["reported_date"] != rdate:
            print(row.bill_url)
            print(
                f"Discrepancy in reported_date for bill {row.bill_id} "
                f"committee {row.committee_id}: "
                f"tenure_info has {tenure_info['reported_date']}, "
                f"but _reported_out_from_bill_page found {rdate}."
            )
        if tenure_info["hearing_date"] != sched_hearing:
            print(row.bill_url)
            print(
                f"Discrepancy in hearing_date for bill {row.bill_id} "
                f"committee {row.committee_id}: "
                f"tenure_info has {tenure_info['hearing_date']}, "
                f"but _hearing_announcement_from_bill_page found {sched_hearing}."
            )
        if tenure_info["hearing_announcement_date"] != announce_date:
            print(row.bill_url)
            print(
                f"Discrepancy in hearing_announcement_date for bill "
                f"{row.bill_id} committee {row.committee_id}: "
                f"tenure_info has {tenure_info['hearing_announcement_date']}, "
                f"but _hearing_announcement_from_bill_page found "
                f"{announce_date}."
            )
    if not tenure_info:
        tenure_info = {
            "reported_date": None,
            "hearing_announcement_date": None,
            "hearing_date": None,
        }
    if "4693" in row.bill_id:
        breakpoint()
    return BillStatus(
        bill_id=row.bill_id,
        committee_id=row.committee_id,
        hearing_date=row.hearing_date,
        deadline_60=d60,
        deadline_90=d90,
        reported_out=tenure_info["reported_date"] is not None,
        reported_date=tenure_info["reported_date"],
        extension_until=extension_until,
        effective_deadline=effective,
        announcement_date=tenure_info["hearing_announcement_date"],
        scheduled_hearing_date=tenure_info["hearing_date"],
    )
