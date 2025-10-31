"""Deterministic analysis generation using composable f-string templates.

This module replaces LLM-based analysis with deterministic, reproducible
template-based analysis generation.
"""

from enum import Enum
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import date

from components.compliance import NOTICE_REQUIREMENT_START_DATE


class AnalysisComponent(str, Enum):
    """The four required components of an analysis."""

    DELTA_SUMMARY = "delta_summary"
    ACTIVITY_SUMMARY = "activity_summary"
    ATTRIBUTION = "attribution"
    TRANSPARENCY_NOTE = "transparency_note"


class DeltaDirection(str, Enum):
    """Direction of compliance movement."""

    STABLE = "stable"
    ROSE = "rose"
    DECLINED = "declined"


class ActivityType(str, Enum):
    """Types of activity that can occur."""

    NEW_BILLS = "new_bills"
    NEW_HEARINGS = "new_hearings"
    REPORTED_OUT = "reported_out"
    NEW_SUMMARIES = "new_summaries"
    NONE = "none"


@dataclass
class AnalysisContext:
    """Context data needed to generate analysis components."""

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

    # Activity lists (bill IDs)
    new_bills: List[str]
    bills_with_new_hearings: List[str]
    bills_reported_out: List[str]
    bills_with_new_summaries: List[str]

    # Bill objects for detailed analysis
    current_bills_by_id: Dict[str, dict]
    previous_bills_by_id: Optional[Dict[str, dict]]

    # Transparency metrics (computed)
    short_notice_hearings_count: int = 0
    exempt_hearings_count: int = 0

    # State transitions (computed)
    bills_improved_compliance: List[str] = field(default_factory=list)
    bills_degraded_compliance: List[str] = field(default_factory=list)


class AnalysisTemplateBuilder:
    """
    Structured-variety templates for committee daily briefs.
    - Never introduce numbers not passed in.
    - Keep verbs neutral and analytic.
    - Sentence blocks: delta, activity, attribution, transparency.
    """

    # ---------- DELTA SUMMARY ----------
    # Args: delta_abs (float)
    DELTA_TEMPLATES = {
        DeltaDirection.STABLE: (
            "Compliance remained stable.",
            "Compliance did not change.",
            "Compliance was unchanged over the period.",
        ),
        DeltaDirection.ROSE: (
            "Compliance rose by {delta_abs:.1f} percentage points.",
            "The compliance rate increased by {delta_abs:.1f} percentage points.",
            "Compliance improved by {delta_abs:.1f} percentage points.",
        ),
        DeltaDirection.DECLINED: (
            "Compliance declined by {delta_abs:.1f} percentage points.",
            "The compliance rate decreased by {delta_abs:.1f} percentage points.",
            "Compliance fell by {delta_abs:.1f} percentage points.",
        ),
    }

    # ---------- ACTIVITY SUMMARY ----------
    # Single-activity sentences.
    # Args: count (int), plural_s ("s" if count!=1 else ""), verb ("was"|"were"), noun ("bill"|"bills")
    ACTIVITY_TEMPLATES = {
        ActivityType.NONE: (
            "No new hearings, reports, or summaries were recorded.",
            "No new hearings, report-outs, or summaries were posted.",
            "No hearings, report-outs, or summaries were added in this period.",
        ),
        ActivityType.NEW_BILLS: (
            "{count} new bill{plural_s} {verb} added to the tracker.",
            "{count} bill{plural_s} {verb} newly added.",
            "The tracker added {count} bill{plural_s}.",
        ),
        ActivityType.NEW_HEARINGS: (
            "{count} bill{plural_s} {verb} assigned new hearings.",
            "{count} hearing{plural_s} {verb} posted for bill{plural_s}.",
            "New hearings were posted for {count} bill{plural_s}.",
        ),
        ActivityType.REPORTED_OUT: (
            "{count} bill{plural_s} {verb} reported out of committee.",
            "{count} report-out{plural_s} {verb} recorded.",
            "Committee report-outs were posted for {count} bill{plural_s}.",
        ),
        ActivityType.NEW_SUMMARIES: (
            "{count} bill{plural_s} {verb} posted with new summaries.",
            "Plain-language summaries were posted for {count} bill{plural_s}.",
            "{count} new summar{y_ies} {verb} posted for bill{plural_s}.",
        ),
    }

    # Mixed-activity fragments (compose a single sentence listing the nonzero buckets).
    # Build item strings like "1 reported-out bill", "3 with new hearings", "2 with new summaries", "4 new bills"
    # Args for joiners: item(s) are already fully formatted substrings.
    ACTIVITY_JOINERS = {
        "single": "{a}.",
        "pair": "{a} and {b}.",
        "triple": "{a}, {b}, and {c}.",
        "many": "{items}, and {last}.",  # 'items' should already be comma-separated
    }

    # Helpers for building item substrings (kept as patterns so wording is consistent).
    # Args: n (int)
    ACTIVITY_ITEM_PATTERNS = {
        "reported_out": (
            "{n} reported-out bill" if "{n}" == "1" else "{n} reported-out bills"
        ),
        "hearings": (
            "{n} with new hearing" if "{n}" == "1" else "{n} with new hearings"
        ),
        "summaries": (
            "{n} with new summary" if "{n}" == "1" else "{n} with new summaries"
        ),
        "new_bills": (
            "{n} new bill" if "{n}" == "1" else "{n} new bills"
        ),
    }

    # ---------- ATTRIBUTION ----------
    # Keep to factual linkage; no speculation.
    # Args: bill_count (int), plural_s ("s" if bill_count!=1 else "")
    ATTRIBUTION_TEMPLATES = {
        "stable_update": (
            "The change reflected administrative updates.",
            "The shift reflected routine updates rather than new postings.",
            "The result corresponds to status updates recorded during the period.",
        ),
        "reported_out_driver": (
            "The shift corresponded to reporting activity.",
            "Movement corresponded to committee report-outs.",
            "Reporting activity aligned with the observed change.",
        ),
        "compliance_improvements": (
            "Improvement was recorded on {bill_count} bill{plural_s}.",
            "Compliance improvements were observed for {bill_count} bill{plural_s}.",
            "Updates moved {bill_count} bill{plural_s} toward compliance.",
        ),
        "compliance_degradations": (
            "Compliance declined for {bill_count} bill{plural_s}.",
            "Degradations were observed for {bill_count} bill{plural_s}.",
            "Updates moved {bill_count} bill{plural_s} away from compliance.",
        ),
        "mixed_attribution": (
            "The change reflected a combination of reporting and administrative updates.",
            "Both reporting and administrative updates were present during the period.",
            "The observed movement corresponds to a mix of report-outs and routine updates.",
        ),
        "no_attribution": (
            "The shift reflected updates outside today's postings.",
            "No specific activity in this window explains the change.",
            "The change corresponds to updates recorded outside this period.",
        ),
    }
    TRANSPARENCY_TEMPLATES = {
        "no_hearings": (
            "No new hearings were posted in this period.",
            "There were no hearing postings in this window.",
            "No hearings were recorded during the period.",
        ),
        "all_compliant": (
            "Hearing postings aligned with the 10-day notice requirement.",
            "All hearings in this window appear to meet the 10-day notice rule.",
            "Posted hearings were publicly noticed at least ten days in advance.",
        ),
        "some_short_notice": (
            "{count} of {total} new hearing{plural} {verb} posted with "
            "less than 10 days' notice"
        ),
        "all_exempt": (
            "Some hearings were exempt from the 10-day rule based on earlier announcements.",
            "Exempt hearings (announced before 2025-06-26) were included in this window.",
            "The set includes hearings exempt from the 10-day requirement by announcement date.",
        ),
        "mixed_notice": (
            "Hearing postings align with the 10-day notice requirement; "
            "{exempt_count} hearing{exempt_plural} {exempt_verb} exempt "
            "due to announcement before the requirement took effect"
        ),
    }

    @classmethod
    def get_delta_summary(cls, context: AnalysisContext) -> str:
        """Generate the delta summary component.

        Args:
            context: Analysis context with delta information

        Returns:
            Formatted delta summary string
        """
        template = cls.DELTA_TEMPLATES[context.delta_direction]
        return template.format(delta_abs=context.delta_abs)

    @classmethod
    def get_activity_summary(cls, context: AnalysisContext) -> str:
        """Generate the activity summary component.

        Args:
            context: Analysis context with activity information

        Returns:
            Formatted activity summary string
        """
        # Collect non-zero activity counts
        activities = []
        if context.new_bills_count > 0:
            activities.append(
                ("new bills", context.new_bills_count, ActivityType.NEW_BILLS)
            )
        if context.bills_with_new_hearings_count > 0:
            activities.append(
                (
                    "hearings",
                    context.bills_with_new_hearings_count,
                    ActivityType.NEW_HEARINGS,
                )
            )
        if context.bills_reported_out_count > 0:
            activities.append(
                (
                    "reported out",
                    context.bills_reported_out_count,
                    ActivityType.REPORTED_OUT,
                )
            )
        if context.bills_with_new_summaries_count > 0:
            activities.append(
                (
                    "summaries",
                    context.bills_with_new_summaries_count,
                    ActivityType.NEW_SUMMARIES,
                )
            )

        # Handle no activity
        if not activities:
            return cls.ACTIVITY_TEMPLATES[ActivityType.NONE]

        # Handle single activity
        if len(activities) == 1:
            activity_type = activities[0][2]
            count = activities[0][1]
            template = cls.ACTIVITY_TEMPLATES[activity_type]
            return template.format(
                count=count,
                plural="" if count == 1 else "s",
                verb="was" if count == 1 else "were",
            )

        # Handle multiple activities - build a natural language list
        parts = []
        for label, count, _ in activities:
            if count == 1:
                parts.append(f"{count} bill with {label}")
            else:
                parts.append(f"{count} bills with {label}")

        if len(parts) == 2:
            return f"Activity included {parts[0]} and {parts[1]}"
        elif len(parts) == 3:
            return f"Activity included {parts[0]}, {parts[1]}, and {parts[2]}"
        else:
            return (
                f"Activity included {', '.join(parts[:-1])}, "
                f"and {parts[-1]}"
            )

    @classmethod
    def get_attribution(cls, context: AnalysisContext) -> str:
        """Generate the attribution component.

        Args:
            context: Analysis context with attribution information

        Returns:
            Formatted attribution string
        """
        # Stable delta - just administrative updates
        if context.delta_direction == DeltaDirection.STABLE:
            return cls.ATTRIBUTION_TEMPLATES["stable_update"]

        # No activity but delta exists - external updates
        if (
            context.bills_reported_out_count == 0
            and context.bills_with_new_hearings_count == 0
            and context.bills_with_new_summaries_count == 0
            and context.new_bills_count == 0
        ):
            return cls.ATTRIBUTION_TEMPLATES["no_attribution"]

        # Reported out activity is a strong driver
        if context.bills_reported_out_count > 0:
            # Check if any of these bills improved compliance
            if context.bills_improved_compliance:
                improved_from_reported = [
                    bid
                    for bid in context.bills_reported_out
                    if bid in context.bills_improved_compliance
                ]
                if improved_from_reported:
                    count = len(improved_from_reported)
                    return cls.ATTRIBUTION_TEMPLATES[
                        "compliance_improvements"
                    ].format(
                        bill_count=count,
                        plural="" if count == 1 else "s",
                    )
            return cls.ATTRIBUTION_TEMPLATES["reported_out_driver"]

        # Check for other compliance improvements/degradations
        if context.bills_improved_compliance:
            count = len(context.bills_improved_compliance)
            return cls.ATTRIBUTION_TEMPLATES["compliance_improvements"].format(
                bill_count=count, plural="" if count == 1 else "s"
            )

        if context.bills_degraded_compliance:
            count = len(context.bills_degraded_compliance)
            return cls.ATTRIBUTION_TEMPLATES["compliance_degradations"].format(
                bill_count=count, plural="" if count == 1 else "s"
            )

        # Default to mixed/administrative
        return cls.ATTRIBUTION_TEMPLATES["mixed_attribution"]

    @classmethod
    def get_transparency_note(
        cls, context: AnalysisContext
    ) -> Optional[str]:
        """Generate the transparency note component.

        Args:
            context: Analysis context with transparency information

        Returns:
            Formatted transparency note string, or None if not applicable
        """
        # Only include if there were new hearings
        if context.bills_with_new_hearings_count == 0:
            return None

        total_hearings = context.bills_with_new_hearings_count

        # All exempt
        if (
            context.exempt_hearings_count == total_hearings
            and context.short_notice_hearings_count == 0
        ):
            return cls.TRANSPARENCY_TEMPLATES["all_exempt"]

        # Some short notice
        if context.short_notice_hearings_count > 0:
            template = cls.TRANSPARENCY_TEMPLATES["some_short_notice"]
            if template is None:
                return None
            return template.format(
                count=context.short_notice_hearings_count,
                total=total_hearings,
                plural=(
                    "" if context.short_notice_hearings_count == 1
                    else "s"
                ),
                verb=(
                    "was" if context.short_notice_hearings_count == 1
                    else "were"
                ),
            )

        # All compliant, but some may be exempt
        if context.exempt_hearings_count > 0:
            template = cls.TRANSPARENCY_TEMPLATES["mixed_notice"]
            if template is None:
                return None
            return template.format(
                exempt_count=context.exempt_hearings_count,
                exempt_plural=""
                if context.exempt_hearings_count == 1
                else "s",
                exempt_verb="was"
                if context.exempt_hearings_count == 1
                else "were",
            )

        # All compliant, none exempt
        return cls.TRANSPARENCY_TEMPLATES["all_compliant"]

    @classmethod
    def generate_analysis(cls, context: AnalysisContext) -> str:
        """Generate the complete analysis by composing all components.

        Args:
            context: Analysis context with all required information

        Returns:
            Complete analysis string with all four components
        """
        components = []

        # 1. Delta summary (always present)
        components.append(cls.get_delta_summary(context))

        # 2. Activity summary (always present)
        components.append(cls.get_activity_summary(context))

        # 3. Attribution (always present)
        components.append(cls.get_attribution(context))

        # 4. Transparency note (only if there were hearings)
        transparency = cls.get_transparency_note(context)
        if transparency:
            components.append(transparency)

        # Join with periods and spaces
        return ". ".join(components) + "."


def build_analysis_context(
    diff_report: dict,
    current_bills: List[dict],
    previous_bills: Optional[List[dict]],
    committee_name: str = "Unknown Committee",
) -> AnalysisContext:
    """Build an AnalysisContext from diff report and bill data.

    This function enriches the diff_report with computed fields needed
    for template selection, including:
    - Delta direction calculation
    - State transitions for attribution
    - Transparency metrics (notice gaps, exemptions)

    Args:
        diff_report: The diff report dictionary
        current_bills: List of current bill dictionaries
        previous_bills: List of previous bill dictionaries (or None)
        committee_name: Name of the committee

    Returns:
        AnalysisContext object with all computed fields
    """
    compliance_delta = diff_report.get("compliance_delta", 0.0)
    delta_abs = abs(compliance_delta)

    # Determine delta direction
    if delta_abs < 0.05:
        delta_direction = DeltaDirection.STABLE
    elif compliance_delta > 0:
        delta_direction = DeltaDirection.ROSE
    else:
        delta_direction = DeltaDirection.DECLINED

    # Build bill lookup dictionaries
    current_bills_by_id = {bill["bill_id"]: bill for bill in current_bills}
    previous_bills_by_id = (
        {bill["bill_id"]: bill for bill in previous_bills}
        if previous_bills
        else None
    )

    # Compute state transitions for attribution
    bills_improved_compliance = []
    bills_degraded_compliance = []

    if previous_bills_by_id:
        for bill_id, current_bill in current_bills_by_id.items():
            if bill_id not in previous_bills_by_id:
                continue

            prev_bill = previous_bills_by_id[bill_id]
            prev_state = prev_bill.get("state", "")
            curr_state = current_bill.get("state", "")

            # Check for compliance improvement
            if (prev_state in ("Non-Compliant", "Incomplete") and
                    curr_state in ("Compliant", "Unknown")):
                bills_improved_compliance.append(bill_id)
            # Check for compliance degradation
            elif prev_state in ("Compliant", "Unknown") and curr_state in (
                "Non-Compliant",
                "Incomplete",
            ):
                bills_degraded_compliance.append(bill_id)

    # Compute transparency metrics for new hearings
    short_notice_count = 0
    exempt_count = 0

    for bill_id in diff_report.get("bills_with_new_hearings", []):
        if bill_id not in current_bills_by_id:
            continue

        bill = current_bills_by_id[bill_id]
        announcement_date_str = bill.get("announcement_date")
        notice_gap_days = bill.get("notice_gap_days")
        reason = bill.get("reason", "")

        # Check if exempt
        if announcement_date_str:
            try:
                announcement_date = date.fromisoformat(announcement_date_str)
                if announcement_date < NOTICE_REQUIREMENT_START_DATE:
                    exempt_count += 1
                    continue
            except (ValueError, TypeError):
                pass

        # Check if exempt by reason
        if "exempt" in reason.lower():
            exempt_count += 1
            continue

        # Check for short notice
        if notice_gap_days is not None and notice_gap_days < 10:
            short_notice_count += 1

    return AnalysisContext(
        compliance_delta=compliance_delta,
        delta_abs=delta_abs,
        delta_direction=delta_direction,
        time_interval=diff_report.get("time_interval", "period"),
        previous_date=diff_report.get("previous_date", "N/A"),
        current_date=diff_report.get("current_date", "N/A"),
        committee_name=committee_name,
        new_bills_count=diff_report.get("new_bills_count", 0),
        bills_with_new_hearings_count=len(
            diff_report.get("bills_with_new_hearings", [])
        ),
        bills_reported_out_count=len(
            diff_report.get("bills_reported_out", [])
        ),
        bills_with_new_summaries_count=len(
            diff_report.get("bills_with_new_summaries", [])),
        new_bills=diff_report.get("new_bills", []),
        bills_with_new_hearings=diff_report.get("bills_with_new_hearings", []),
        bills_reported_out=diff_report.get("bills_reported_out", []),
        bills_with_new_summaries=diff_report.get(
            "bills_with_new_summaries", []
        ),
        current_bills_by_id=current_bills_by_id,
        previous_bills_by_id=previous_bills_by_id,
        short_notice_hearings_count=short_notice_count,
        exempt_hearings_count=exempt_count,
        bills_improved_compliance=bills_improved_compliance,
        bills_degraded_compliance=bills_degraded_compliance,
    )


def generate_deterministic_analysis(
    diff_report: dict,
    current_bills: List[dict],
    previous_bills: Optional[List[dict]],
    committee_name: str = "Unknown Committee",
) -> str:
    """Generate deterministic analysis using template composition.

    This is the main entry point that replaces generate_llm_analysis().

    Args:
        diff_report: The diff report dictionary
        current_bills: List of current bill dictionaries
        previous_bills: List of previous bill dictionaries (or None)
        committee_name: Name of the committee

    Returns:
        Complete analysis string
    """
    context = build_analysis_context(
        diff_report, current_bills, previous_bills, committee_name
    )
    return AnalysisTemplateBuilder.generate_analysis(context)
