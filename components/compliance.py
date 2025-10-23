"""Compliance module for the Massachusetts Legislature."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import date

from components.models import SummaryInfo, VoteInfo, BillStatus

# Bills weren't subject to the 10-day hearing advance notice requirement
# before this date. Any hearing announced PRIOR to this date is
# automatically compliant with notice requirements.
NOTICE_REQUIREMENT_START_DATE = date(2025, 6, 26)


class ComplianceState(str, Enum):
    """Compliance states for bills."""

    COMPLIANT = "Compliant"
    NON_COMPLIANT = "Non-Compliant"
    INCOMPLETE = "Incomplete"
    UNKNOWN = "Unknown"


class NoticeStatus(str, Enum):
    """Notice compliance status for hearings."""

    IN_RANGE = "In range"
    OUT_OF_RANGE = "Out of range"
    MISSING = "Missing"


@dataclass(frozen=True)
class BillCompliance:
    """A bill compliance in the Massachusetts Legislature."""
    bill_id: str
    committee_id: str
    hearing_date: Optional[date]
    summary: SummaryInfo
    votes: VoteInfo
    status: BillStatus
    state: ComplianceState
    reason: Optional[str] = None

    def __post_init__(self):
        """Convert StrEnums to their string values"""
        if isinstance(self.state, ComplianceState):
            object.__setattr__(self, "state", self.state.value)


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
    if status.hearing_date is None:
        return BillCompliance(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=None,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.UNKNOWN,
            reason=(
                "No hearing scheduled - "
                "cannot evaluate deadline compliance"
            ),
        )
    today = date.today()

    # First, check notice compliance (applies to all bills)
    notice_status, gap_days = compute_notice_status(status, min_notice_days)
    effective_reported_out = status.reported_out or votes.present

    # Generate appropriate notice description for reason strings
    if notice_status == NoticeStatus.IN_RANGE and gap_days is not None:
        # Check if this is due to exemption or actual compliance
        if (status.announcement_date and
                status.announcement_date < NOTICE_REQUIREMENT_START_DATE):
            announce_date = status.announcement_date
            notice_desc = (
                f"exempt from notice requirement "
                f"(announced {announce_date}, before 2025-06-26)"
            )
        else:
            notice_desc = f"adequate notice ({gap_days} days)"
    else:
        notice_desc = ""  # Not used for missing/out of range cases
    # Deal-breaker: insufficient notice
    if notice_status == NoticeStatus.OUT_OF_RANGE:
        return BillCompliance(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=status.hearing_date,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.NON_COMPLIANT,
            reason=(f"Insufficient notice: {gap_days} days "
                    f"(minimum {min_notice_days})"),
        )
    # Compute presence flags and counts
    reported_out = effective_reported_out
    votes_present = votes.present
    summary_present = summary.present

    present_count = sum([reported_out, votes_present, summary_present])

    if present_count == 3:
        reason = (
            "All requirements met: "
            "reported out, votes posted, summaries posted"
        )
        if notice_desc:
            reason = f"{reason}, {notice_desc}"

        return BillCompliance(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=status.hearing_date,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.COMPLIANT,
            reason=reason,
        )

    # Handle missing notice cases
    if notice_status == NoticeStatus.MISSING:
        # If there's no evidence at all, this is unknown; otherwise non-compliant
        if present_count == 0:
            return BillCompliance(
                bill_id=bill_id,
                committee_id=committee_id,
                hearing_date=status.hearing_date,
                summary=summary,
                votes=votes,
                status=status,
                state=ComplianceState.UNKNOWN,
                reason=(
                    "No hearing announcement found "
                    "and no other evidence"
                ),
            )
        else:
            return BillCompliance(
                bill_id=bill_id,
                committee_id=committee_id,
                hearing_date=status.hearing_date,
                summary=summary,
                votes=votes,
                status=status,
                state=ComplianceState.NON_COMPLIANT,
                reason="No hearing announcement found",
            )

    if status.effective_deadline and today <= status.effective_deadline:
        return BillCompliance(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=status.hearing_date,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.UNKNOWN,
            reason=(f"Before deadline, {notice_desc}"),
        )

    if present_count == 2:
        missing = _get_missing_requirements(
            reported_out, votes_present, summary_present
        )
        state = ComplianceState.INCOMPLETE
        reason = f"One requirement missing: {missing}, {notice_desc}"
    else:
        missing = _get_missing_requirements(
            reported_out, votes_present, summary_present
        )
        state = ComplianceState.NON_COMPLIANT
        reason = f"Factors: {missing}, {notice_desc}"

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

    # Exemption: hearings announced before NOTICE_REQUIREMENT_START_DATE are
    # automatically compliant with notice requirements
    if status.announcement_date < NOTICE_REQUIREMENT_START_DATE:
        return NoticeStatus.IN_RANGE, gap_days

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
