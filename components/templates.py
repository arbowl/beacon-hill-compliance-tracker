"""
Deterministic, rule-based analysis generation.

Public API preserved:
- AnalysisContext
- build_analysis_context(...)
- generate_deterministic_analysis(...)

Behavioral guarantees:
- No randomness (fully reproducible).
- Never assert activity that isn't present.
- One clear sentence per section (Delta, Activity, Attribution, Transparency).
- Canonical wording, consistent punctuation, correct grammar.
"""

from __future__ import annotations

from enum import Enum
import json
from typing import Optional
from dataclasses import dataclass, field
from datetime import date

try:
    from components.compliance import NOTICE_REQUIREMENT_START_DATE
except ImportError:
    # Fallback if unit testing below
    NOTICE_REQUIREMENT_START_DATE = date(2025, 6, 26)


class DeltaDirection(str, Enum):
    """Direction of compliance change."""

    STABLE = "stable"
    ROSE = "rose"
    DECLINED = "declined"


class State(str, Enum):
    """The bill's status"""

    COMPLIANT = "Compliant"
    NONCOMPLIANT = "Non-Compliant"
    INCOMPLETE = "Incomplete"
    UNKNOWN = "Unknown"


def _plural(
    n: int,
    singular: str,
    plural: Optional[str] = None,
    capitalize: bool = False,
) -> str:
    """Return grammatically correct token for n with singular/plural noun."""
    if n == 1:
        return f"{_num(1, capitalize)} {singular}"
    return f"{_num(n, capitalize)} {plural or singular + 's'}"


def _join_with_commas(parts: list[str]) -> str:
    """Oxford-comma joiner for human-readable lists."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _num(number: int, capitalize: bool = False) -> str:
    """Grammar rule: spell numbers below 10 out."""
    if number < 0:
        raise ValueError(f"{number} cannot be less than 0.")
    if number > 9:
        return str(number)
    number_map: dict[int, str] = {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
    }
    if capitalize:
        return number_map[number].capitalize()
    return number_map[number]


def _print_preview(list_of_bills: list[str], limit: int = 5) -> str:
    """Limits how many bills are mentioned by name"""
    if len(list_of_bills) < (limit + 1):
        return _join_with_commas(list_of_bills)
    return (
        f"{', '.join(list_of_bills[limit:])}, and "
        f"{len(list_of_bills) - limit} more"
    )


# pylint: disable=too-many-instance-attributes
# Needed here to mimic the JSON output
@dataclass
class AnalysisContext:
    """Normalized facts used by the generator."""

    # Delta
    compliance_delta: float
    delta_abs: float
    delta_direction: DeltaDirection
    time_interval: str
    previous_date: str
    current_date: str
    committee_name: str

    # Activity counts
    new_bills_count: int
    bills_with_new_hearings_count: int
    bills_reported_out_count: int
    bills_with_new_summaries_count: int

    # Activity lists (IDs)
    new_bills: list[str]
    bills_with_new_hearings: list[str]
    bills_reported_out: list[str]
    bills_with_new_summaries: list[str]

    # Bill dicts
    current_bills_by_id: dict[str, dict]
    previous_bills_by_id: Optional[dict[str, dict]]

    # Transparency
    short_notice_hearings_count: int = 0
    exempt_hearings_count: int = 0

    # State transitions
    bills_improved_compliance: list[str] = field(default_factory=list)
    bills_degraded_compliance: list[str] = field(default_factory=list)


class _Renderer:
    """Pure functions that render each section from facts with strict
    precedence.
    """

    @staticmethod
    def delta(ctx: AnalysisContext) -> str:
        """Emit at most one line."""
        if ctx.delta_direction is DeltaDirection.ROSE:
            return (
                f"Compliance within the {ctx.committee_name} increased by "
                f"{ctx.delta_abs:.1f} percentage points over the past "
                f"{ctx.time_interval}."
            )
        if ctx.delta_direction is DeltaDirection.DECLINED:
            return (
                f"Compliance within the {ctx.committee_name} decreased by "
                f"{ctx.delta_abs:.1f} percentage points over the past "
                f"{ctx.time_interval}."
            )
        return (
            f"Compliance was unchanged within the {ctx.committee_name} "
            f"over the past {ctx.time_interval}."
        )

    @staticmethod
    def activity(ctx: AnalysisContext) -> str:
        """Emit at most one line."""
        nb = ctx.new_bills_count
        hr = ctx.bills_with_new_hearings_count
        ro = ctx.bills_reported_out_count
        sm = ctx.bills_with_new_summaries_count
        total = nb + hr + ro + sm
        if total == 0:
            # Keep a concise negative statement for parity with prior behavior.
            return "No new hearings, report-outs, or summaries were detected."
        # If more than one bucket is non-zero, emit a single mixed sentence.
        nonzero_parts = 0
        parts: list[str] = []
        if ro > 0:
            noun = "reported-out bill" if ro == 1 else "reported-out bills"
            parts.append(_plural(ro, noun, noun))
            nonzero_parts += 1
        if hr > 0:
            phrase = "heard at a hearing" if hr == 1 else "heard at hearings"
            parts.append(_plural(hr, "bill", "bills") + f" {phrase}")
            nonzero_parts += 1
        if sm > 0:
            phrase = "with a new summary" if sm == 1 else "with new summaries"
            parts.append(_plural(sm, "bill", "bills") + f" {phrase}")
            nonzero_parts += 1
        if nb > 0:
            parts.append(_plural(nb, "new bill", "new bills"))
            nonzero_parts += 1

        if nonzero_parts > 1:
            return f"Activity included {_join_with_commas(parts)}."

        # Single-bucket canonical sentences
        if ro > 0:
            return (
                f"{_plural(ro, 'bill was', 'bills were', True)} reported out "
                f"of committee ({_print_preview(ctx.bills_reported_out, 2)})."
            )
        if hr > 0:
            return (
                f"New hearings were posted for "
                f"{_plural(hr, 'bill', 'bills', False)} "
                f"({_print_preview(ctx.bills_with_new_hearings, 2)})."
            )
        if sm > 0:
            return (
                f"Plain-language summaries were posted for "
                f"{_plural(sm, 'bill', 'bills', False)} "
                f"({_print_preview(ctx.bills_with_new_summaries, 2)})."
            )
        # nb > 0 only
        return (
            f"{_plural(nb, 'bill was', 'bills were', True)} newly detected by "
            "the compliance tracking algorithm "
            f"({_print_preview(ctx.new_bills, 2)})."
        )

    @staticmethod
    def attribution(ctx: AnalysisContext) -> str:
        """Emit at most one line. Prefer specific, suppress filler."""
        nb = ctx.new_bills_count
        hr = ctx.bills_with_new_hearings_count
        ro = ctx.bills_reported_out_count
        sm = ctx.bills_with_new_summaries_count
        any_activity = (nb + hr + ro + sm) > 0

        if ctx.delta_direction is DeltaDirection.ROSE:
            # Strongest specific cause first
            if ro > 0:
                return "The movement aligns with committee report-outs."
            if ctx.bills_improved_compliance:
                k = len(ctx.bills_improved_compliance)
                return (
                    f"Updates moved {_plural(k, 'bill', 'bills')} "
                    f"({_print_preview(ctx.bills_improved_compliance, 5)}) "
                    "toward compliance."
                )
        elif ctx.delta_direction is DeltaDirection.DECLINED:
            if ro > 0:
                # Decline with report-outs doesn't imply cause; keep neutral.
                return "The change coincided with committee report-outs."
            if ctx.bills_degraded_compliance:
                k = len(ctx.bills_degraded_compliance)
                return (
                    f"{_plural(k, 'bill', 'bills', True)} "
                    f"({_print_preview(ctx.bills_degraded_compliance, 5)}) "
                    "dropped below compliance thresholds this period."
                )
        else:
            # Stable: avoid speculation; only emit if we truly have
            # nothing moving.
            return (
                "No material shift is attributable to activity in this "
                "window."
            )

        if (
            not any_activity
            and ctx.delta_direction is not DeltaDirection.STABLE
        ):
            return (
                "The change reflects updates recorded outside this "
                "window."
            )

        # If we get here, skip attribution instead of emitting filler.
        return ""

    @staticmethod
    def transparency(ctx: AnalysisContext) -> str:
        """Emit at most one line."""
        total = ctx.bills_with_new_hearings_count
        if total == 0:
            return ""

        short_ = ctx.short_notice_hearings_count
        exempt = ctx.exempt_hearings_count

        if total == exempt and short_ == 0:
            return (
                "All hearings in this window are exempt from the "
                "10-day notice rule."
            )
        if short_ > 0:
            return (
                f"{_plural(short_, 'hearing was', 'hearings were', True)} "
                f"posted with less than 10 days’ notice "
                f"({short_} of {total})."
            )
        if exempt > 0:
            return (
                "Hearings met the 10-day notice rule; "
                f"{_plural(exempt, 'hearing is', 'hearings are', True)} "
                "exempt based on earlier announcements."
            )
        return "All hearings met the 10-day notice requirement."


def build_analysis_context(
    diff_report: dict,
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
    committee_name: str = "The Committee",
) -> AnalysisContext:
    """Normalize incoming packet into facts. This is the only place that
    transforms counts/lists.
    """
    compliance_delta = float(diff_report.get("compliance_delta", 0.0))
    delta_abs = abs(compliance_delta)
    if delta_abs < 0.05:
        delta_direction = DeltaDirection.STABLE
    elif compliance_delta > 0:
        delta_direction = DeltaDirection.ROSE
    else:
        delta_direction = DeltaDirection.DECLINED

    current_bills_by_id = {b["bill_id"]: b for b in current_bills}
    previous_bills_by_id = {
        b["bill_id"]: b for b in (previous_bills or [])
    } or None

    # Track state transitions for attribution
    improved: list[str] = []
    degraded: list[str] = []
    if previous_bills_by_id:
        for bill_id, curr in current_bills_by_id.items():
            prev = previous_bills_by_id.get(bill_id)
            if not prev:
                continue
            prev_state = prev.get("state", "")
            curr_state = curr.get("state", "")
            if (prev_state in ("Non-Compliant", "Incomplete") and
                    curr_state in ("Compliant", "Unknown")):
                improved.append(bill_id)
            elif prev_state in ("Compliant", "Unknown") and curr_state in (
                "Non-Compliant", "Incomplete"
            ):
                degraded.append(bill_id)

    # Lists from diff report
    new_bills_raw = list(diff_report.get("new_bills", []))
    ro_raw = list(diff_report.get("bills_reported_out", []))
    hr_raw = list(diff_report.get("bills_with_new_hearings", []))
    sm_raw = list(diff_report.get("bills_with_new_summaries", []))

    # Prevent double counting: remove newly added bills from other buckets.
    new_set = set(new_bills_raw)
    reported_out = [bid for bid in ro_raw if bid not in new_set]
    bills_with_new_hearings = [bid for bid in hr_raw if bid not in new_set]
    bills_with_new_summaries = [bid for bid in sm_raw if bid not in new_set]

    # Transparency: compute short notice & exemptions only over the filtered
    # hearing list.
    short_notice = 0
    exempt = 0
    for bid in bills_with_new_hearings:
        bill = current_bills_by_id.get(bid)
        if not bill:
            continue
        announcement_date_str = bill.get("announcement_date")
        notice_gap_days = bill.get("notice_gap_days")
        reason: str = str(bill.get("reason", "") or "")

        if announcement_date_str:
            try:
                announcement_date = date.fromisoformat(announcement_date_str)
                if announcement_date < NOTICE_REQUIREMENT_START_DATE:
                    exempt += 1
                    continue
            except Exception:  # pylint: disable=broad-exception-caught
                # If date is malformed, fall through to other checks.
                pass
        if "exempt" in reason.lower():
            exempt += 1
            continue
        if notice_gap_days is not None and notice_gap_days < 10:
            short_notice += 1

    return AnalysisContext(
        compliance_delta=compliance_delta,
        delta_abs=delta_abs,
        delta_direction=delta_direction,
        time_interval=diff_report.get("time_interval", "period"),
        previous_date=diff_report.get("previous_date", "N/A"),
        current_date=diff_report.get("current_date", "N/A"),
        committee_name=committee_name,
        new_bills_count=len(new_bills_raw),
        bills_with_new_hearings_count=len(bills_with_new_hearings),
        bills_reported_out_count=len(reported_out),
        bills_with_new_summaries_count=len(bills_with_new_summaries),
        new_bills=new_bills_raw,
        bills_with_new_hearings=bills_with_new_hearings,
        bills_reported_out=reported_out,
        bills_with_new_summaries=bills_with_new_summaries,
        current_bills_by_id=current_bills_by_id,
        previous_bills_by_id=previous_bills_by_id,
        short_notice_hearings_count=short_notice,
        exempt_hearings_count=exempt,
        bills_improved_compliance=improved,
        bills_degraded_compliance=degraded,
    )


def generate_deterministic_analysis(
    diff_report: dict,
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
    committee_name: str = "The Committee",
) -> str:
    """
    Compose the final paragraph from the four sections.
    Order: Delta. Activity. Attribution (if any). Transparency (if any).
    Each section is at most one sentence. Empty sections are skipped.
    """
    ctx = build_analysis_context(
        diff_report, current_bills, previous_bills, committee_name
    )
    lines = [
        _Renderer.delta(ctx),
        _Renderer.activity(ctx),
        _Renderer.attribution(ctx),
        _Renderer.transparency(ctx),
    ]
    # Remove empty lines and join with spaces; guarantee trailing period
    # only once.
    text = " ".join([ln.strip() for ln in lines if ln and ln.strip()])
    return (text + ".") if text and not text.endswith(".") else text


# Use the below code to test the template generator.
# Run this file directly.
if __name__ == "__main__":
    def create_bill(
        bill_id: str,
        state: str = "Unknown",
        announcement_date: Optional[date] = None,
        notice_gap_days: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> dict:
        """Create a bill dictionary."""
        d: dict[str, str | int] = {"bill_id": bill_id, "state": state}
        if announcement_date is not None:
            d["announcement_date"] = str(announcement_date)
        if notice_gap_days is not None:
            d["notice_gap_days"] = int(notice_gap_days)
        if reason is not None:
            d["reason"] = reason
        return d

    def run_scenario(
        bill_name: str,
        diff_report: dict,
        current_bills: list[dict],
        previous_bills: Optional[list[dict]] = None,
    ) -> None:
        """Run a scenario and print the results."""
        print(f"\n=== {bill_name} ===")
        print(json.dumps(diff_report, indent=2))
        output = generate_deterministic_analysis(
            diff_report, current_bills, previous_bills
        )
        print("→", output)

    PREVIOUS = [
        create_bill("A1", state=State.UNKNOWN),
        create_bill("A2", state=State.UNKNOWN),
        create_bill("H1", state=State.UNKNOWN),
        create_bill("H2", state=State.UNKNOWN),
        create_bill("H3", state=State.UNKNOWN),
    ]

    CURRENT = [
        create_bill("A1", state=State.NONCOMPLIANT),
        create_bill("A2", state=State.NONCOMPLIANT),
        create_bill(
            "H1", state=State.UNKNOWN, announcement_date=date(2025, 7, 10),
            notice_gap_days=12,
        ),
        create_bill(
            "H2", state=State.UNKNOWN, announcement_date=date(2025, 7, 12),
            notice_gap_days=7,
        ),
        create_bill(
            "H3", state=State.UNKNOWN, announcement_date=date(2025, 6, 10),
            notice_gap_days=15,  # exempt by date
        ),
    ]

    # --- Scenarios ---
    scenarios = [
        ("Stable / No activity",
         {"time_interval": "day", "previous_date": "2025-06-25",
          "current_date": "2025-06-26",
          "compliance_delta": 0.0, "new_bills": [],
          "bills_with_new_hearings": [],
          "bills_reported_out": [], "bills_with_new_summaries": []}),

        ("Rose / Report-outs",
         {"time_interval": "day", "previous_date": "2025-06-25",
          "current_date": "2025-06-26",
          "compliance_delta": +1.2, "new_bills": [],
          "bills_with_new_hearings": [],
          "bills_reported_out": ["A1", "A2"], "bills_with_new_summaries": []}),

        ("Hearings short notice",
         {"time_interval": "day", "previous_date": "2025-06-25",
          "current_date": "2025-06-26",
          "compliance_delta": -0.2, "new_bills": [],
          "bills_with_new_hearings": ["H1", "H2"],
          "bills_reported_out": [], "bills_with_new_summaries": []}),

        ("Lots of new provisional bills",
         {"time_interval": "day", "previous_date": "2025-10-30",
          "current_date": "2025-10-31",
          "compliance_delta": 5.0, "new_bills": [
            "H123",
            "H124",
            "H125",
            "H126",
            "H127",
            "H128",
            "H129",
          ], "bills_with_new_hearings": [], "bills_reported_out": [],
          "bills_with_new_summaries": ["H2"]}),
    ]

    for name, diff in scenarios:
        run_scenario(name, diff, CURRENT, PREVIOUS)
