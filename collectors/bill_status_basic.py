"""Collects basic bill status information by scanning the bill page for
'reported' phrases and grabbing a nearby date.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from components.models import BillAtHearing, BillStatus
from components.utils import (
    compute_deadlines, extract_session_from_bill_url
)
from components.interfaces import ParserInterface
from timeline.parser import extract_timeline
from timeline.models import ActionType


@dataclass
class CommitteeTenure:
    """Represents committee tenure information for a bill."""

    committee_id: str
    referred_date: date
    hearing_announcement_date: Optional[date]
    hearing_date: Optional[date]
    all_hearing_dates: list[date]
    all_hearings: list[dict]
    reported_date: Optional[date]
    discharged_date: Optional[date]
    tenure_start: date
    tenure_end: date
    notice_days: Optional[int]
    hearing_to_report_days: Optional[int]
    referred_to_report_days: Optional[int]
    is_active: bool


def get_bill_title(bill_url: str) -> str | None:
    """Return the human-readable title of a bill (e.g., "An Act …") or None.

    The bill detail page typically shows the long title just below the header.
    On live pages (e.g., https://malegislature.gov/Bills/194/H2244) the title
    appears in text that starts with "An Act", "An Resolve", or "A Resolve".
    """
    soup = ParserInterface.soup(bill_url)
    for h2 in soup.find_all('h2'):
        parent = h2.parent
        if parent:
            parent_classes = parent.get('class')
            if parent_classes and 'col-md-8' in parent_classes:
                return " ".join(h2.get_text(" ", strip=True).split())
    tag = soup.find(class_=re.compile(r"bill-title", re.I))
    if tag and tag.get_text(strip=True):
        return " ".join(tag.get_text(strip=True).split())
    candidate_rx = re.compile(r"\b(an|a)\s+(act|resolve)\b", re.I)
    candidates: list[str] = []
    for t in soup.select("h1, h2, h3, p, div")[:40]:
        txt = " ".join(t.get_text(" ", strip=True).split())
        if candidate_rx.search(txt):
            for stop in ["Bill History", "Displaying", "Tabs", "Sponsor:"]:
                if stop in txt:
                    txt = txt.split(stop, maxsplit=1)[0].strip()
            if 5 < len(txt) < 200:
                candidates.append(txt)
    if candidates:
        return min(candidates, key=len)
    return None


def get_committee_tenure(
    bill_url: str, committee_id: str
) -> Optional[CommitteeTenure]:
    """Get committee tenure information for a bill and committee."""
    try:
        timeline = extract_timeline(bill_url)
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    referrals = timeline.get_actions_by_type(ActionType.REFERRED)
    discharges = timeline.get_actions_by_type(ActionType.DISCHARGED)
    tenure_start_action = None
    for action in sorted(referrals + discharges, key=lambda a: a.date):
        action_committee = action.extracted_data.get("committee_id")
        if action_committee == committee_id:
            tenure_start_action = action
            break
    if not tenure_start_action:
        return None
    tenure_start = tenure_start_action.date
    reported_actions = timeline.get_actions_by_type(ActionType.REPORTED)
    reported_date = None
    for action in sorted(reported_actions, key=lambda a: a.date):
        action_committee = action.extracted_data.get("committee_id")
        if not action_committee:
            prior_refs = [
                r for r in (referrals + discharges) if r.date < action.date
            ]
            if prior_refs:
                latest_ref = max(prior_refs, key=lambda r: r.date)
                action_committee = latest_ref.extracted_data.get(
                    "committee_id"
                )
        if action_committee == committee_id and action.date >= tenure_start:
            reported_date = action.date
            break
    discharged_date = None
    for action in sorted(referrals + discharges, key=lambda a: a.date):
        if action.date > tenure_start:
            next_committee = action.extracted_data.get("committee_id")
            if next_committee and next_committee != committee_id:
                discharged_date = action.date
                break
    tenure_end = None
    is_active = True
    candidates = [d for d in [reported_date, discharged_date] if d]
    if candidates:
        tenure_end = min(candidates)  # earliest final action wins
        is_active = False
    else:
        tenure_end = date.today()
        is_active = True
    scheduled = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
    rescheduled = timeline.get_actions_by_type(ActionType.HEARING_RESCHEDULED)
    all_hearings = []
    hearing_announcement_date = None
    hearing_date = None
    for action in sorted(scheduled + rescheduled, key=lambda a: a.date):
        action_committee = action.extracted_data.get("committee_id")
        if not action_committee:
            action_committee = committee_id
        if action_committee != committee_id:
            continue
        if tenure_start <= action.date <= tenure_end:
            hearing_date_str = action.extracted_data.get("hearing_date")
            if not hearing_date_str:
                continue
            hearing_dt = date.fromisoformat(hearing_date_str)
            all_hearings.append({
                "announcement_date": action.date,
                "hearing_date": hearing_dt,
                "action_type": action.action_type,
            })
    if all_hearings:
        hearing_with_min_notice = min(
            all_hearings,
            key=lambda h: (h["hearing_date"] - h["announcement_date"]).days
        )
        hearing_announcement_date: date = hearing_with_min_notice["announcement_date"]
        hearing_date: date = hearing_with_min_notice["hearing_date"]
    notice_days = None
    if hearing_announcement_date and hearing_date:
        notice_days = (hearing_date - hearing_announcement_date).days
    hearing_to_report_days = None
    if hearing_date and reported_date:
        hearing_to_report_days = (reported_date - hearing_date).days
    referred_to_report_days = None
    if reported_date:
        referred_to_report_days = (reported_date - tenure_start).days
    return CommitteeTenure(
        committee_id=committee_id,
        referred_date=tenure_start,
        hearing_announcement_date=hearing_announcement_date,
        hearing_date=hearing_date,
        all_hearing_dates=[h["hearing_date"] for h in all_hearings],
        all_hearings=all_hearings,
        reported_date=reported_date,
        discharged_date=discharged_date,
        tenure_start=tenure_start,
        tenure_end=tenure_end,
        notice_days=notice_days,
        hearing_to_report_days=hearing_to_report_days,
        referred_to_report_days=referred_to_report_days,
        is_active=is_active,
    )


def build_status_row(
    _base_url: str, row: BillAtHearing, extension_until=None
) -> BillStatus:
    """Build the status row."""
    session = (
        extract_session_from_bill_url(row.bill_url)
        if row.bill_url else None
    )
    d60, d90, effective = compute_deadlines(
        row.hearing_date, extension_until, row.bill_id, session
    )
    tenure_info = get_committee_tenure(row.bill_url, row.committee_id)
    if not tenure_info:
        tenure_info = CommitteeTenure(
            committee_id=row.committee_id,
            referred_date=row.hearing_date,
            hearing_announcement_date=None,
            hearing_date=None,
            all_hearing_dates=[],
            all_hearings=[],
            reported_date=None,
            discharged_date=None,
            tenure_start=row.hearing_date,
            tenure_end=date.today(),
            notice_days=None,
            hearing_to_report_days=None,
            referred_to_report_days=None,
            is_active=True,
        )
    return BillStatus(
        bill_id=row.bill_id,
        committee_id=row.committee_id,
        hearing_date=row.hearing_date,
        deadline_60=d60,
        deadline_90=d90,
        reported_out=tenure_info.reported_date is not None,
        reported_date=tenure_info.reported_date,
        extension_until=extension_until,
        effective_deadline=effective,
        announcement_date=tenure_info.hearing_announcement_date,
        scheduled_hearing_date=tenure_info.hearing_date,
    )
