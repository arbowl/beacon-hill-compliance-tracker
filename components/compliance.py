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
