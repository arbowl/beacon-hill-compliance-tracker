"""Deterministic analysis generation using composable f-string templates.

This module replaces LLM-based analysis with deterministic, reproducible
template-based analysis generation.
"""

from enum import Enum
from typing import Optional, Union, Sequence
from dataclasses import dataclass, field
from datetime import date
import random

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


class ActivityJoiner(str, Enum):
    """Joiner templates for multiple activity items."""

    SINGLE = "single"
    PAIR = "pair"
    TRIPLE = "triple"
    MANY = "many"


class ActivityPattern(str, Enum):
    """Patterns for activity item substrings."""

    REPORTED_OUT = "reported_out"
    HEARINGS = "hearings"
    SUMMARIES = "summaries"
    NEW_BILLS = "new_bills"


class AttributionTemplate(str, Enum):
    """Types of attribution scenarios."""

    STABLE_UPDATE = "stable_update"
    REPORTED_OUT_DRIVER = "reported_out_driver"
    COMPLIANCE_IMPROVEMENTS = "compliance_improvements"
    COMPLIANCE_DEGRADATIONS = "compliance_degradations"
    MIXED_ATTRIBUTION = "mixed_attribution"
    NO_ATTRIBUTION = "no_attribution"


class TransparencyTemplate(str, Enum):
    """Types of transparency note scenarios."""

    NO_HEARINGS = "no_hearings"
    ALL_COMPLIANT = "all_compliant"
    SOME_SHORT_NOTICE = "some_short_notice"
    ALL_EXEMPT = "all_exempt"
    MIXED_NOTICE = "mixed_notice"


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
    new_bills: list[str]
    bills_with_new_hearings: list[str]
    bills_reported_out: list[str]
    bills_with_new_summaries: list[str]

    # Bill objects for detailed analysis
    current_bills_by_id: dict[str, dict]
    previous_bills_by_id: Optional[dict[str, dict]]

    # Transparency metrics (computed)
    short_notice_hearings_count: int = 0
    exempt_hearings_count: int = 0

    # State transitions (computed)
    bills_improved_compliance: list[str] = field(default_factory=list)
    bills_degraded_compliance: list[str] = field(default_factory=list)


class AnalysisTemplateBuilder:
    """
    Structured-variety templates for committee daily briefs.
    - Never introduce numbers not passed in.
    - Keep verbs neutral and analytic.
    - Sentence blocks: delta, activity, attribution, transparency.
    """

    # ---------- DELTA SUMMARY ----------
    # Args: delta_abs (float)
    delta_templates: dict[DeltaDirection, str] = {
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
    # Args: count (int), plural_s ("s" if count!=1 else ""),
    # verb ("was"|"were"), noun ("bill"|"bills")
    activity_templates: dict[ActivityType, str] = {
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
    # Build item strings like:
    # "1 reported-out bill",
    # "3 with new hearings",
    # "2 with new summaries",
    # "4 new bills"
    # Args for joiners: item(s) are already fully formatted substrings.
    activity_joiners: dict[ActivityJoiner, str] = {
        ActivityJoiner.SINGLE: "{a}.",
        ActivityJoiner.PAIR: "{a} and {b}.",
        ActivityJoiner.TRIPLE: "{a}, {b}, and {c}.",
        ActivityJoiner.MANY: "{items}, and {last}.",  # 'items' should already be comma-separated
    }

    # Helpers for building item substrings (kept as patterns so wording is consistent).
    # Args: n (int)
    activity_patterns: dict[ActivityPattern, str] = {
        ActivityPattern.REPORTED_OUT: (
            "{n} reported-out bill" if "{n}" == "1" else "{n} reported-out bills"
        ),
        ActivityPattern.HEARINGS: (
            "{n} with new hearing" if "{n}" == "1" else "{n} with new hearings"
        ),
        ActivityPattern.SUMMARIES: (
            "{n} with new summary" if "{n}" == "1" else "{n} with new summaries"
        ),
        ActivityPattern.NEW_BILLS: (
            "{n} new bill" if "{n}" == "1" else "{n} new bills"
        ),
    }

    # ---------- ATTRIBUTION ----------
    # Keep to factual linkage; no speculation.
    # Args: bill_count (int), plural_s ("s" if bill_count!=1 else "")
    attribution_templates: dict[AttributionTemplate, str] = {
        AttributionTemplate.STABLE_UPDATE: (
            "Compliance remained neutral with respect to the latest activity.",
            "The shift reflected routine activity.",
            "No significant shift occurred over the latest observation period.",
        ),
        AttributionTemplate.REPORTED_OUT_DRIVER: (
            "The shift corresponded to reporting activity.",
            "Movement corresponded to committee report-outs.",
            "Reporting activity aligned with the observed change.",
        ),
        AttributionTemplate.COMPLIANCE_IMPROVEMENTS: (
            "Improvement was recorded on {bill_count} bill{plural_s}.",
            "Compliance improvements were observed for {bill_count} bill{plural_s}.",
            "Updates moved {bill_count} bill{plural_s} toward compliance.",
        ),
        AttributionTemplate.COMPLIANCE_DEGRADATIONS: (
            "Compliance declined for {bill_count} bill{plural_s}.",
            "Degradations were observed for {bill_count} bill{plural_s}.",
            "Updates moved {bill_count} bill{plural_s} away from compliance.",
        ),
        AttributionTemplate.MIXED_ATTRIBUTION: (
            "The change reflected a combination of reporting and administrative updates.",
            "Both reporting and administrative updates were present during the period.",
            "The observed movement corresponds to a mix of report-outs and routine updates.",
        ),
        AttributionTemplate.NO_ATTRIBUTION: (
            "The shift reflected updates outside today's postings.",
            "No specific activity in this window explains the change.",
            "The change corresponds to updates recorded outside this period.",
        ),
    }
    transparency_templates: dict[TransparencyTemplate, str] = {
        TransparencyTemplate.NO_HEARINGS: (
            "No new hearings were posted in this period.",
            "There were no hearing postings in this window.",
            "No hearings were recorded during the period.",
        ),
        TransparencyTemplate.ALL_COMPLIANT: (
            "Hearing postings aligned with the 10-day notice requirement.",
            "All hearings in this window appear to meet the 10-day notice rule.",
            "Posted hearings were publicly noticed at least ten days in advance.",
        ),
        TransparencyTemplate.SOME_SHORT_NOTICE: (
            "{count} of {total} new hearing{plural} {verb} posted with "
            "less than 10 days' notice"
        ),
        TransparencyTemplate.ALL_EXEMPT: (
            "Some hearings were exempt from the 10-day rule based on earlier announcements.",
            "Exempt hearings (announced before 2025-06-26) were included in this window.",
            "The set includes hearings exempt from the 10-day requirement by announcement date.",
        ),
        TransparencyTemplate.MIXED_NOTICE: (
            "Hearing postings align with the 10-day notice requirement; "
            "{exempt_count} hearing{exempt_plural} {exempt_verb} exempt "
            "due to announcement before the requirement took effect"
        ),
    }

    @classmethod
    def _get_template(
        cls, template_value: Union[str, Sequence[str], None]
    ) -> str:
        """Randomly select a template string from a value (string or sequence).

        Args:
            template_value: Either a string template, sequence of templates,
                or None

        Returns:
            A randomly selected template string (or the string itself if it's
            already a string)

        Raises:
            ValueError: If template_value is None or empty sequence
        """
        if template_value is None:
            raise ValueError("Template value cannot be None")
        if isinstance(template_value, str):
            return template_value
        if len(template_value) == 0:
            raise ValueError("Template sequence cannot be empty")
        return random.choice(template_value)

    @classmethod
    def get_delta_summary(cls, context: AnalysisContext) -> str:
        """Generate the delta summary component.

        Args:
            context: Analysis context with delta information

        Returns:
            Formatted delta summary string
        """
        template_value = cls.delta_templates[context.delta_direction]
        template = cls._get_template(template_value)
        return template.format(delta_abs=context.delta_abs)

    @classmethod
    def get_activity_summary(cls, context: AnalysisContext) -> str:
        """Generate the activity summary component.

        Args:
            context: Analysis context with activity information

        Returns:
            Formatted activity summary string
        """
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
        if not activities:
            template_value = cls.activity_templates[ActivityType.NONE]
            return cls._get_template(template_value)
        if len(activities) == 1:
            activity_type = activities[0][2]
            count = activities[0][1]
            template_value = cls.activity_templates[activity_type]
            template = cls._get_template(template_value)
            return template.format(
                count=count,
                plural_s="" if count == 1 else "s",
                y_ies="y" if count == 1 else "ies",
                verb="was" if count == 1 else "were",
            )
        parts = []
        for label, count, _ in activities:
            if count == 1:
                parts.append(f"{count} bill with {label}")
            else:
                parts.append(f"{count} bills with {label}")
        if len(parts) == 2:
            return f"Activity included {parts[0]} and {parts[1]}"
        if len(parts) == 3:
            return f"Activity included {parts[0]}, {parts[1]}, and {parts[2]}"
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
        if context.delta_direction == DeltaDirection.STABLE:
            template_value = cls.attribution_templates[
                AttributionTemplate.STABLE_UPDATE
            ]
            return cls._get_template(template_value)
        if (
            context.bills_reported_out_count == 0
            and context.bills_with_new_hearings_count == 0
            and context.bills_with_new_summaries_count == 0
            and context.new_bills_count == 0
        ):
            template_value = cls.attribution_templates[
                AttributionTemplate.NO_ATTRIBUTION
            ]
            return cls._get_template(template_value)
        if context.bills_reported_out_count > 0:
            if context.bills_improved_compliance:
                improved_from_reported = [
                    bid
                    for bid in context.bills_reported_out
                    if bid in context.bills_improved_compliance
                ]
                if improved_from_reported:
                    count = len(improved_from_reported)
                    template_value = cls.attribution_templates[
                        AttributionTemplate.COMPLIANCE_IMPROVEMENTS
                    ]
                    template = cls._get_template(template_value)
                    return template.format(
                        bill_count=count,
                        plural_s="" if count == 1 else "s",
                    )
            template_value = cls.attribution_templates[
                AttributionTemplate.REPORTED_OUT_DRIVER
            ]
            return cls._get_template(template_value)
        if context.bills_improved_compliance:
            count = len(context.bills_improved_compliance)
            template_value = cls.attribution_templates[
                AttributionTemplate.COMPLIANCE_IMPROVEMENTS
            ]
            template = cls._get_template(template_value)
            return template.format(
                bill_count=count, plural_s="" if count == 1 else "s"
            )
        if context.bills_degraded_compliance:
            count = len(context.bills_degraded_compliance)
            template_value = cls.attribution_templates[
                AttributionTemplate.COMPLIANCE_DEGRADATIONS
            ]
            template = cls._get_template(template_value)
            return template.format(
                bill_count=count, plural_s="" if count == 1 else "s"
            )
        template_value = cls.attribution_templates[
            AttributionTemplate.MIXED_ATTRIBUTION
        ]
        return cls._get_template(template_value)

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
        if context.bills_with_new_hearings_count == 0:
            return None
        total_hearings = context.bills_with_new_hearings_count
        if (
            context.exempt_hearings_count == total_hearings
            and context.short_notice_hearings_count == 0
        ):
            template_value = cls.transparency_templates[
                TransparencyTemplate.ALL_EXEMPT
            ]
            if template_value is None:
                return None
            return cls._get_template(template_value)
        if context.short_notice_hearings_count > 0:
            template_value = cls.transparency_templates[
                TransparencyTemplate.SOME_SHORT_NOTICE
            ]
            if template_value is None:
                return None
            template = cls._get_template(template_value)
            return template.format(
                count=context.short_notice_hearings_count,
                total=total_hearings,
                plural_s=(
                    "" if context.short_notice_hearings_count == 1
                    else "s"
                ),
                verb=(
                    "was" if context.short_notice_hearings_count == 1
                    else "were"
                ),
            )
        if context.exempt_hearings_count > 0:
            template_value = cls.transparency_templates[
                TransparencyTemplate.MIXED_NOTICE
            ]
            if template_value is None:
                return None
            template = cls._get_template(template_value)
            return template.format(
                exempt_count=context.exempt_hearings_count,
                exempt_plural=""
                if context.exempt_hearings_count == 1
                else "s",
                exempt_verb="was"
                if context.exempt_hearings_count == 1
                else "were",
            )
        template_value = cls.transparency_templates[
            TransparencyTemplate.ALL_COMPLIANT
        ]
        if template_value is None:
            return None
        return cls._get_template(template_value)

    @classmethod
    def generate_analysis(cls, context: AnalysisContext) -> str:
        """Generate the complete analysis by composing all components.

        Args:
            context: Analysis context with all required information

        Returns:
            Complete analysis string with all four components
        """
        components = []
        components.append(cls.get_delta_summary(context))
        components.append(cls.get_activity_summary(context))
        components.append(cls.get_attribution(context))
        transparency = cls.get_transparency_note(context)
        if transparency:
            components.append(transparency)
        return " ".join(components) + " "


def build_analysis_context(
    diff_report: dict,
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
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
    if delta_abs < 0.05:
        delta_direction = DeltaDirection.STABLE
    elif compliance_delta > 0:
        delta_direction = DeltaDirection.ROSE
    else:
        delta_direction = DeltaDirection.DECLINED
    current_bills_by_id = {bill["bill_id"]: bill for bill in current_bills}
    previous_bills_by_id = (
        {bill["bill_id"]: bill for bill in previous_bills}
        if previous_bills
        else None
    )
    bills_improved_compliance = []
    bills_degraded_compliance = []
    if previous_bills_by_id:
        for bill_id, current_bill in current_bills_by_id.items():
            if bill_id not in previous_bills_by_id:
                continue
            prev_bill = previous_bills_by_id[bill_id]
            prev_state = prev_bill.get("state", "")
            curr_state = current_bill.get("state", "")
            if (prev_state in ("Non-Compliant", "Incomplete") and
                    curr_state in ("Compliant", "Unknown")):
                bills_improved_compliance.append(bill_id)
            elif prev_state in ("Compliant", "Unknown") and curr_state in (
                "Non-Compliant",
                "Incomplete",
            ):
                bills_degraded_compliance.append(bill_id)

    # --- NEW: Filter diff lists so newly added bills aren't double-counted as reported-out/hearings/summaries ---
    new_bills_list = list(diff_report.get("new_bills", []))
    reported_out_raw = list(diff_report.get("bills_reported_out", []))
    hearings_raw = list(diff_report.get("bills_with_new_hearings", []))
    summaries_raw = list(diff_report.get("bills_with_new_summaries", []))

    # Exclude any bill IDs that are in new_bills from other activity categories.
    reported_out = [bid for bid in reported_out_raw if bid not in new_bills_list]
    bills_with_new_hearings = [bid for bid in hearings_raw if bid not in new_bills_list]
    bills_with_new_summaries = [bid for bid in summaries_raw if bid not in new_bills_list]

    short_notice_count = 0
    exempt_count = 0
    # iterate over the filtered hearings list for transparency calculations
    for bill_id in bills_with_new_hearings:
        if bill_id not in current_bills_by_id:
            continue
        bill = current_bills_by_id[bill_id]
        announcement_date_str = bill.get("announcement_date")
        notice_gap_days = bill.get("notice_gap_days")
        reason: str = bill.get("reason", "")
        if announcement_date_str:
            try:
                announcement_date = date.fromisoformat(announcement_date_str)
                if announcement_date < NOTICE_REQUIREMENT_START_DATE:
                    exempt_count += 1
                    continue
            except (ValueError, TypeError):
                pass
        if "exempt" in reason.lower():
            exempt_count += 1
            continue
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
        new_bills_count=len(new_bills_list),
        bills_with_new_hearings_count=len(bills_with_new_hearings),
        bills_reported_out_count=len(reported_out),
        bills_with_new_summaries_count=len(bills_with_new_summaries),
        new_bills=new_bills_list,
        bills_with_new_hearings=bills_with_new_hearings,
        bills_reported_out=reported_out,
        bills_with_new_summaries=bills_with_new_summaries,
        current_bills_by_id=current_bills_by_id,
        previous_bills_by_id=previous_bills_by_id,
        short_notice_hearings_count=short_notice_count,
        exempt_hearings_count=exempt_count,
        bills_improved_compliance=bills_improved_compliance,
        bills_degraded_compliance=bills_degraded_compliance,
    )


def generate_deterministic_analysis(
    diff_report: dict,
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
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
    context: AnalysisContext = build_analysis_context(
        diff_report, current_bills, previous_bills, committee_name
    )
    return AnalysisTemplateBuilder.generate_analysis(context)
