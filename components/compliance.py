# compliance.py
from dataclasses import dataclass
from typing import Literal, Optional
from datetime import date

from components.models import SummaryInfo, VoteInfo, BillStatus

ComplianceState = Literal["compliant", "non-compliant", "unknown"]


@dataclass(frozen=True)
class BillCompliance:
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
    Business rule (simple, adjustable):
    - If reported_out == True → compliant (summary+votes presence still helpful but not required)
    - Else if today > effective_deadline:
        - If summary.present and votes.present → compliant
        - If summary.present XOR votes.present → unknown (partial)
        - Else → non-compliant
    - Else (before deadline) → unknown
    """
    today = date.today()

    if status.reported_out:
        state, reason = "compliant", "Reported out"
    elif today > status.effective_deadline:
        if summary.present and votes.present:
            state, reason = "compliant", "Summary + votes present by deadline"
        elif summary.present or votes.present:
            state, reason = "unknown", "Partial: one of summary/votes missing after deadline"
        else:
            state, reason = "non-compliant", "No summary or votes after deadline"
    else:
        state, reason = "unknown", "Before deadline"

    return BillCompliance(
        bill_id=bill_id,
        committee_id=committee_id,
        hearing_date=status.hearing_date,
        summary=summary,
        votes=votes,
        status=status,
        state=state,
        reason=reason,
    )
