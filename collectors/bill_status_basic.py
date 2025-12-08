"""Collects basic bill status information by scanning the bill page for
'reported' phrases and grabbing a nearby date.
"""

import re
import logging
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
from components.suspicious_notices import (
    SuspiciousHearingNotice,
    SuspiciousNoticeLogger,
    compute_signature,
    should_whitelist_as_clerical,
)

logger = logging.getLogger(__name__)


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


# Minimum acceptable notice days for detecting suspicious cases
MINIMUM_ACCEPTABLE_NOTICE = 3  # Flag anything with < 3 days notice


def detect_and_log_suspicious_notice(
    bill_url: str,
    bill_id: str,
    committee_id: str,
    all_hearings: list[dict],
    selected_hearing: dict,
    notice_days: int,
) -> Optional[SuspiciousHearingNotice]:
    """Detect and log suspicious hearing notices (same-day or retroactive).
    
    This function is called when a hearing has insufficient notice and creates
    a detailed record for later review by domain experts.
    
    Args:
        bill_url: URL of the bill
        bill_id: Bill identifier
        committee_id: Committee identifier
        all_hearings: All hearing actions for this bill/committee
        selected_hearing: The hearing with minimum notice (the problematic one)
        notice_days: Number of days notice (can be 0 or negative)
    
    Returns:
        SuspiciousHearingNotice if one was created and logged, None otherwise
    """
    # Extract session from URL
    session = extract_session_from_bill_url(bill_url) or "unknown"
    
    # Find if there was a prior valid announcement
    prior_hearings = [
        h for h in all_hearings
        if (h["hearing_date"] - h["announcement_date"]).days >= MINIMUM_ACCEPTABLE_NOTICE
    ]
    
    had_prior_announcement = len(prior_hearings) > 0
    prior_best = None
    prior_best_notice_days = None
    
    if had_prior_announcement:
        # Find the prior hearing with the best (most) notice
        prior_best = max(
            prior_hearings,
            key=lambda h: (h["hearing_date"] - h["announcement_date"]).days
        )
        prior_best_notice_days = (
            prior_best["hearing_date"] - prior_best["announcement_date"]
        ).days
    
    # Get the raw action text from the timeline (we'll need to enhance this)
    action_type_str = selected_hearing.get("action_type", "UNKNOWN")
    if hasattr(action_type_str, "value"):
        action_type_str = action_type_str.value
    
    # Construct a representative raw text (ideally we'd get this from the actual action)
    announcement_date = selected_hearing["announcement_date"]
    hearing_date = selected_hearing["hearing_date"]
    raw_text = f"Hearing {action_type_str.lower().replace('_', ' ')} for {hearing_date.strftime('%m/%d/%Y')}"
    
    # Calculate temporal relationships
    days_between = (announcement_date - hearing_date).days if notice_days < 0 else 0
    
    # Create the suspicious notice record
    notice = SuspiciousHearingNotice(
        bill_id=bill_id,
        committee_id=committee_id,
        session=session,
        bill_url=bill_url,
        announcement_date=announcement_date,
        scheduled_hearing_date=hearing_date,
        notice_days=notice_days,
        action_type=action_type_str,
        raw_action_text=raw_text,
        all_hearing_actions=[
            {
                "announcement_date": h["announcement_date"].isoformat(),
                "hearing_date": h["hearing_date"].isoformat(),
                "action_type": h["action_type"].value if hasattr(h["action_type"], "value") else str(h["action_type"]),
                "notice_days": (h["hearing_date"] - h["announcement_date"]).days,
            }
            for h in all_hearings
        ],
        had_prior_announcement=had_prior_announcement,
        prior_best_notice_days=prior_best_notice_days,
        prior_announcement_date=prior_best["announcement_date"] if prior_best else None,
        prior_scheduled_date=prior_best["hearing_date"] if prior_best else None,
        action_date=announcement_date,
        days_between_action_and_hearing=days_between,
    )
    
    # Compute signature
    notice.signature = compute_signature(notice)
    
    # Check if this matches a known clerical pattern
    is_whitelisted, pattern_id = should_whitelist_as_clerical(notice)
    
    if is_whitelisted:
        notice.whitelist_pattern_id = pattern_id
        logger.info(
            f"Bill {bill_id}: Suspicious notice whitelisted as clerical "
            f"(pattern: {pattern_id})"
        )
        # Still log it for tracking, but mark as whitelisted
    
    # Log the suspicious notice
    try:
        notice_logger = SuspiciousNoticeLogger()
        notice_logger.log(notice)
        logger.debug(
            f"Logged suspicious notice for {bill_id}: "
            f"{notice_days} days notice (signature: {notice.signature.get('composite_key', 'unknown')})"
        )
    except Exception as e:
        logger.error(f"Failed to log suspicious notice for {bill_id}: {e}")
    
    return notice


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
        
        # DETECTION: Log same-day and retroactive hearing reschedules
        # These may be clerical corrections or actual violations
        if notice_days < MINIMUM_ACCEPTABLE_NOTICE:
            # Extract bill_id from the bill_url
            # URL format: https://malegislature.gov/Bills/194/H2244
            bill_id_match = re.search(r'/([HS]\d+)', bill_url)
            if bill_id_match:
                bill_id = bill_id_match.group(1)
                detect_and_log_suspicious_notice(
                    bill_url=bill_url,
                    bill_id=bill_id,
                    committee_id=committee_id,
                    all_hearings=all_hearings,
                    selected_hearing=hearing_with_min_notice,
                    notice_days=notice_days,
                )
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
