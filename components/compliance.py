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
) -> BillCompliance:
    """
    New business rules:
    - Compliant = "reported out" on time, votes posted, summaries posted
      (all 3 present)
    - Incomplete = one of the above is missing (1 missing)
    - Non-compliant = two or more of the above is missing (2+ missing)
    - Unknown = before deadline or insufficient data to determine
    """
    today = date.today()

    # Check if we have enough data to make a determination
    if today <= status.effective_deadline:
        state, reason = ComplianceState.UNKNOWN, "Before deadline"
    else:
        # Count how many compliance factors are present
        reported_out = status.reported_out
        votes_present = votes.present
        summary_present = summary.present

        present_count = sum([reported_out, votes_present, summary_present])

        if present_count == 3:
            state, reason = ComplianceState.COMPLIANT, (
                "All requirements met: reported out, votes posted, "
                "summaries posted"
            )
        elif present_count == 2:
            missing = _get_missing_requirements(
                reported_out, votes_present, summary_present
            )
            state, reason = ComplianceState.INCOMPLETE, (
                f"One requirement missing: {missing}"
            )
        else:  # present_count == 0 or 1
            missing = _get_missing_requirements(
                reported_out, votes_present, summary_present
            )
            state, reason = ComplianceState.NON_COMPLIANT, (
                f"Factors: {missing}"
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
