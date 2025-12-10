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
    # Get all hearing-related actions
    scheduled = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
    rescheduled = timeline.get_actions_by_type(ActionType.HEARING_RESCHEDULED)
    location_changed = timeline.get_actions_by_type(
        ActionType.HEARING_LOCATION_CHANGED
    )
    time_changed = timeline.get_actions_by_type(ActionType.HEARING_TIME_CHANGED)
    
    all_hearing_actions = sorted(
        scheduled + rescheduled + location_changed + time_changed,
        key=lambda a: a.date
    )
    
    # Build timeline of hearings and track compliance
    all_hearings = []
    current_hearing_date = None
    hearing_announcement_date = None
    hearing_date = None
    worst_violation = None  # Track the worst compliance violation
    
    for action in all_hearing_actions:
        action_committee = action.extracted_data.get("committee_id")
        if not action_committee:
            action_committee = committee_id
        if action_committee != committee_id:
            continue
        if not (tenure_start <= action.date <= tenure_end):
            continue
        
        announcement_date = action.date
        
        # Update or use current_hearing_date
        if action.action_type in (
            ActionType.HEARING_SCHEDULED,
            ActionType.HEARING_RESCHEDULED
        ):
            # These actions set the hearing date
            hearing_date_str = action.extracted_data.get("hearing_date")
            if hearing_date_str:
                current_hearing_date = date.fromisoformat(hearing_date_str)
            else:
                continue  # Can't process without a date
        elif action.action_type in (
            ActionType.HEARING_LOCATION_CHANGED,
            ActionType.HEARING_TIME_CHANGED
        ):
            # These actions modify the current hearing
            if current_hearing_date is None:
                continue  # No hearing to modify yet
            # Use the existing current_hearing_date
        else:
            continue
        
        # Calculate notice period
        days_notice = (current_hearing_date - announcement_date).days
        
        # Skip retroactive/same-day amendments if there was a prior announcement
        # (These are clerical corrections, not compliance issues)
        is_amendment = action.action_type in (
            ActionType.HEARING_RESCHEDULED,
            ActionType.HEARING_LOCATION_CHANGED,
            ActionType.HEARING_TIME_CHANGED
        )
        is_retroactive_or_same_day = announcement_date >= current_hearing_date
        
        if is_amendment and is_retroactive_or_same_day:
            # Check if there was a prior valid announcement
            has_prior_announcement = len(all_hearings) > 0
            
            if has_prior_announcement:
                # This is a clerical correction after the fact, skip it
                continue
            # else: No prior announcement - process as violation (fall through)
        
        # Determine required notice period based on action type
        if action.action_type == ActionType.HEARING_SCHEDULED:
            # Initial hearing announcement: needs 10 days
            required_days = 10
            violation_type = "initial_hearing"
            
        elif action.action_type == ActionType.HEARING_RESCHEDULED:
            # Check if this is a date change
            previous_dates = [h["hearing_date"] for h in all_hearings]
            
            if previous_dates and current_hearing_date not in previous_dates:
                # Date changed: needs 10 days notice
                required_days = 10
                violation_type = "date_reschedule"
            else:
                # No date change (agenda/details change): needs 72 hours (3 days)
                required_days = 3
                violation_type = "agenda_change"
                
        elif action.action_type in (
            ActionType.HEARING_LOCATION_CHANGED,
            ActionType.HEARING_TIME_CHANGED
        ):
            # Location or time changes: need 72 hours (3 days)
            required_days = 3
            violation_type = "location_or_time_change"
        else:
            continue  # Unknown action type
        
        # Check compliance
        is_compliant = days_notice >= required_days
        
        # Record this hearing/change
        hearing_record = {
            "announcement_date": announcement_date,
            "hearing_date": current_hearing_date,
            "action_type": action.action_type,
            "days_notice": days_notice,
            "required_days": required_days,
            "violation_type": violation_type,
            "is_compliant": is_compliant,
        }
        all_hearings.append(hearing_record)
        
        # Track worst violation for compliance reporting
        if not is_compliant:
            if worst_violation is None:
                worst_violation = hearing_record
            else:
                # Choose the violation with fewer days notice
                if days_notice < worst_violation["days_notice"]:
                    worst_violation = hearing_record
    
    # Determine which hearing/announcement to report for compliance
    if worst_violation:
        # Report the worst violation
        hearing_announcement_date = worst_violation["announcement_date"]
        hearing_date = worst_violation["hearing_date"]
        notice_days = worst_violation["days_notice"]
    elif all_hearings:
        # All compliant - report the final hearing
        final_hearing = all_hearings[-1]
        hearing_announcement_date = final_hearing["announcement_date"]
        hearing_date = final_hearing["hearing_date"]
        notice_days = final_hearing["days_notice"]
    else:
        # No hearings found
        hearing_announcement_date = None
        hearing_date = None
        notice_days = None
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
