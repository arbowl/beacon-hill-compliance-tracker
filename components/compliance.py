"""Compliance module for the Massachusetts Legislature."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional
from datetime import date

from components.models import SummaryInfo, VoteInfo, BillStatus

# Bills weren't subject to the 10-day hearing advance notice requirement
# before this date. Any hearing announced PRIOR to this date is
# automatically compliant with notice requirements.
NOTICE_REQUIREMENT_START_DATE: date = date(2025, 6, 26)
ADVANCE_NOTICE_REQ: dict[str, int] = {
    "H": 0,
    "J": 10,
    "S": 5,
}


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
) -> BillCompliance:
    """
    Business rules with hearing notice requirements:
    - Notice < 10 days → NON-COMPLIANT (deal-breaker, overrides all else)
    - Notice missing + no other evidence → UNKNOWN
    - Notice missing + any other evidence → NON-COMPLIANT
    - Notice ≥ 10 days → proceed with normal compliance logic
    - Check votes, summaries, and reported-out within deadlines
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

    # First, check notice compliance (applies to all except Senate committees)
    notice_status, gap_days = compute_notice_status(status)
    effective_reported_out = status.reported_out or votes.present
    is_house_committee = committee_id and committee_id.upper().startswith('H')
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
    # Deal-breaker: insufficient notice (does not apply to House committees)
    if notice_status == NoticeStatus.OUT_OF_RANGE and not is_house_committee:
        committee_prefix = committee_id[0].upper() if committee_id else "J"
        min_notice_days = ADVANCE_NOTICE_REQ.get(committee_prefix, 10)
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

    # Handle missing notice cases (does not apply to Senate committees)
    if notice_status == NoticeStatus.MISSING:
        # If there's no evidence at all, this is unknown; otherwise
        # non-compliant
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

    # After deadline: check if reported out by the deadline
    reported_on_time = False
    reported_late = False
    if status.effective_deadline:
        if status.reported_date:
            if status.reported_date <= status.effective_deadline:
                reported_on_time = True
            else:
                reported_late = True

    # Adjust reported_out flag based on deadline compliance
    # For deadline compliance, we need to verify timeliness:
    # - If reported on time (reported_date <= deadline), it counts
    # - If reported late (reported_date > deadline), it doesn't count
    # - If no reported_date, we can't verify timeliness, so it doesn't count
    #   for deadline purposes (even if reported_out flag is True)
    if reported_on_time:
        effective_reported_out_for_count = True
    elif reported_late:
        effective_reported_out_for_count = False
    else:
        # No reported_date - can't verify timeliness, so don't count for deadline
        effective_reported_out_for_count = False

    # Recalculate present_count with deadline-aware reported_out
    present_count_with_deadline = sum([
        effective_reported_out_for_count,
        votes_present,
        summary_present
    ])

    if present_count_with_deadline == 3:
        reason = (
            "All requirements met: "
            "reported out, votes posted, summaries posted"
        )
        if reported_on_time:
            reason += f" (reported on {status.reported_date}, within deadline {status.effective_deadline})"
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

    if present_count_with_deadline == 2:
        missing = _get_missing_requirements(
            effective_reported_out_for_count, votes_present, summary_present
        )
        state = ComplianceState.INCOMPLETE
        reason = f"One requirement missing: {missing}, {notice_desc}"
        if reported_late:
            reason = (
                f"Reported out late ({status.reported_date} after deadline "
                f"{status.effective_deadline}), {missing}, {notice_desc}"
            )
        elif status.effective_deadline and reported_out and not status.reported_date:
            reason = (
                f"Reported out but date unknown (cannot verify deadline "
                f"compliance), {missing}, {notice_desc}"
            )
    else:
        missing = _get_missing_requirements(
            effective_reported_out_for_count, votes_present, summary_present
        )
        state = ComplianceState.NON_COMPLIANT
        reason = f"Factors: {missing}, {notice_desc}"
        if reported_late:
            reason = (
                f"Reported out late ({status.reported_date} after deadline "
                f"{status.effective_deadline}), {missing}, {notice_desc}"
            )
        elif status.effective_deadline and reported_out and not status.reported_date:
            reason = (
                f"Reported out but date unknown (cannot verify deadline "
                f"compliance), {missing}, {notice_desc}"
            )
        elif status.effective_deadline and not reported_out:
            reason = (
                f"Deadline passed ({status.effective_deadline}) without "
                f"reporting out, {missing}, {notice_desc}"
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
    status: BillStatus
) -> tuple[NoticeStatus, Optional[int]]:
    """Compute notice status and gap days for a bill.

    Args:
        status: BillStatus containing announcement and hearing dates

    Returns:
        Tuple of (NoticeStatus, gap_days) where gap_days is None if missing
    """
    if (
        status.announcement_date is None
        or status.scheduled_hearing_date is None
    ):
        return NoticeStatus.MISSING, None
    gap_days = (
        status.scheduled_hearing_date - status.announcement_date
    ).days
    if status.announcement_date < NOTICE_REQUIREMENT_START_DATE:
        return NoticeStatus.IN_RANGE, gap_days
    committee_prefix = (
        status.committee_id[0].upper() if status.committee_id else "J"
    )
    min_notice_days = ADVANCE_NOTICE_REQ.get(committee_prefix, 10)
    if gap_days >= min_notice_days:
        return NoticeStatus.IN_RANGE, gap_days
    return NoticeStatus.OUT_OF_RANGE, gap_days


def _get_missing_requirements(
    reported_out: bool, votes_present: bool, summary_present: bool
) -> str:
    """Generate a human-readable list of missing requirements."""
    missing: list[str] = []
    if not reported_out:
        missing.append("not reported out")
    if not votes_present:
        missing.append("no votes posted")
    if not summary_present:
        missing.append("no summaries posted")
    return ", ".join(missing)
