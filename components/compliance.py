"""Compliance module for the Massachusetts Legislature."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import date

from components.models import SummaryInfo, VoteInfo, BillStatus


class ComplianceState(str, Enum):
    """Compliance states for bills."""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non-compliant"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class NoticeStatus(str, Enum):
    """Notice compliance status for hearings."""
    IN_RANGE = "in_range"      # ≥ 10 days notice
    OUT_OF_RANGE = "out_of_range"  # < 10 days notice
    MISSING = "missing"        # no announcement found


@dataclass(frozen=True)
class BillCompliance:  # pylint: disable=too-many-instance-attributes
    """A bill compliance in the Massachusetts Legislature."""

    bill_id: str
    committee_id: str
    hearing_date: date
    summary: SummaryInfo
    votes: VoteInfo
    status: BillStatus
    state: ComplianceState
    reason: Optional[str] = None


def classify(
    bill_id: str,
    committee_id: str,
    status: BillStatus,
    summary: SummaryInfo,
    votes: VoteInfo,
    min_notice_days: int = 10,
) -> BillCompliance:
    """
    Business rules with hearing notice requirements:
    - Notice < 10 days → NON-COMPLIANT (deal-breaker, overrides all else)
    - Notice missing + no other evidence → UNKNOWN
    - Notice missing + any other evidence → NON-COMPLIANT
    - Notice ≥ 10 days → proceed with normal compliance logic
    
    Normal compliance logic:
    - Senate bills: only check summaries and votes (no deadline enforcement)
    - House bills: check reported-out, summaries, votes within deadlines
    """
    today = date.today()
    
    # First, check notice compliance (applies to all bills)
    notice_status, gap_days = compute_notice_status(status, min_notice_days)
    
    # Deal-breaker: insufficient notice
    if notice_status == NoticeStatus.OUT_OF_RANGE:
        return BillCompliance(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=status.hearing_date,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.NON_COMPLIANT.value,
            reason=(f"Insufficient notice: {gap_days} days "
                    f"(minimum {min_notice_days})"),
        )
    
    # Handle missing notice cases
    if notice_status == NoticeStatus.MISSING:
        # Check if there's any other compliance evidence
        has_evidence = (status.reported_out or votes.present or 
                        summary.present)
        
        if not has_evidence:
            return BillCompliance(
                bill_id=bill_id,
                committee_id=committee_id,
                hearing_date=status.hearing_date,
                summary=summary,
                votes=votes,
                status=status,
                state=ComplianceState.UNKNOWN.value,
                reason="No hearing announcement found and no other evidence",
            )
        else:
            return BillCompliance(
                bill_id=bill_id,
                committee_id=committee_id,
                hearing_date=status.hearing_date,
                summary=summary,
                votes=votes,
                status=status,
                state=ComplianceState.NON_COMPLIANT.value,
                reason="No hearing announcement found",
            )
    
    # Notice is adequate (IN_RANGE), proceed with normal compliance logic
    
    # Senate bills are exempt from 60-day deadline requirements
    if bill_id.upper().startswith('S'):
        # For Senate bills, only check if summaries and votes are posted
        votes_present = votes.present
        summary_present = summary.present

        if votes_present and summary_present:
            state, reason = ComplianceState.COMPLIANT.value, (
                "Senate bill: summaries and votes posted, adequate notice "
                f"({gap_days} days)"
            )
        elif votes_present or summary_present:
            missing = "summaries" if not summary_present else "votes"
            state, reason = ComplianceState.INCOMPLETE.value, (
                f"Senate bill: {missing} missing, adequate notice "
                f"({gap_days} days)"
            )
        else:
            state, reason = ComplianceState.NON_COMPLIANT.value, (
                f"Senate bill: no votes or summaries posted, adequate notice "
                f"({gap_days} days)"
            )
    else:
        # House bills and others - check deadlines and all requirements
        if today <= status.effective_deadline:
            state, reason = ComplianceState.UNKNOWN.value, (
                f"Before deadline, adequate notice ({gap_days} days)"
            )
        else:
            # Count how many compliance factors are present
            reported_out = status.reported_out
            votes_present = votes.present
            summary_present = summary.present

            present_count = sum([reported_out, votes_present, summary_present])

            if present_count == 3:
                state, reason = ComplianceState.COMPLIANT.value, (
                    "All requirements met: reported out, votes posted, "
                    f"summaries posted, adequate notice ({gap_days} days)"
                )
            elif present_count == 2:
                missing = _get_missing_requirements(
                    reported_out, votes_present, summary_present
                )
                state, reason = ComplianceState.INCOMPLETE.value, (
                    f"One requirement missing: {missing}, adequate notice "
                    f"({gap_days} days)"
                )
            else:  # present_count == 0 or 1
                missing = _get_missing_requirements(
                    reported_out, votes_present, summary_present
                )
                state, reason = ComplianceState.NON_COMPLIANT.value, (
                    f"Factors: {missing}, adequate notice ({gap_days} days)"
                )

    return BillCompliance(
        bill_id=bill_id,
        committee_id=committee_id,
        hearing_date=status.hearing_date,
        summary=summary,
        votes=votes,
        status=status,
        state=state,  # type: ignore
        reason=reason,
    )


def compute_notice_status(
    status: BillStatus, min_notice_days: int = 10
) -> tuple[NoticeStatus, Optional[int]]:
    """Compute notice status and gap days for a bill.
    
    Args:
        status: BillStatus containing announcement and hearing dates
        min_notice_days: Minimum required notice days (default 10)
        
    Returns:
        Tuple of (NoticeStatus, gap_days) where gap_days is None if missing
    """
    if (status.announcement_date is None or 
            status.scheduled_hearing_date is None):
        return NoticeStatus.MISSING, None
    
    # Calculate the gap in days
    gap_days = (status.scheduled_hearing_date - status.announcement_date).days
    
    if gap_days >= min_notice_days:
        return NoticeStatus.IN_RANGE, gap_days
    else:
        return NoticeStatus.OUT_OF_RANGE, gap_days


def _get_missing_requirements(
    reported_out: bool, votes_present: bool, summary_present: bool
) -> str:
    """Generate a human-readable list of missing requirements."""
    missing = []
    if not reported_out:
        missing.append("not reported out")
    if not votes_present:
        missing.append("no votes posted")
    if not summary_present:
        missing.append("no summaries posted")
    return ", ".join(missing)
