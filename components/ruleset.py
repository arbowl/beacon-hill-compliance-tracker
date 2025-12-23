"""Composable compliance ruleset system for bill compliance evaluation.

This module provides a flexible, testable architecture for evaluating
bill compliance by composing discrete rules based on bill and committee
characteristics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Optional

from components.models import BillStatus, SummaryInfo, VoteInfo
from components.compliance import BillCompliance, ComplianceState


@dataclass(frozen=True)
class Constants194:
    """Constants for the 194th Session of the Massachusetts Legislature."""

    notice_requirement_start_date: date = date(2025, 6, 26)
    senate_october_deadline: date = date(2025, 10, 1)
    first_wednesday_december: date = date(2025, 12, 3)
    third_wednesday_december: date = date(2025, 12, 17)
    third_wednesday_march: date = date(2026, 3, 18)
    hcf_december_deadline: date = date(2025, 12, 24)
    last_wednesday_january: date = date(2026, 1, 28)
    end_of_session: date = date(2026, 12, 31)


class BillType(str, Enum):
    """Type of bill (House or Senate)."""

    HOUSE = "House"
    SENATE = "Senate"

    @staticmethod
    def from_bill_id(bill_id: str) -> BillType:
        """Get the chamber of a bill."""
        if bill_id.upper().startswith("H"):
            return BillType.HOUSE
        if bill_id.upper().startswith("S"):
            return BillType.SENATE
        raise ValueError(f"Invalid bill ID: {bill_id}")


class CommitteeType(str, Enum):
    """Type of committee (House, Joint, or Senate)."""

    HOUSE = "House"
    JOINT = "Joint"
    SENATE = "Senate"

    @staticmethod
    def from_committee_id(committee_id: str) -> CommitteeType:
        """Get the chamber of a committee."""
        if committee_id.upper().startswith("H"):
            return CommitteeType.HOUSE
        if committee_id.upper().startswith("S"):
            return CommitteeType.SENATE
        if committee_id.upper().startswith("J"):
            return CommitteeType.JOINT
        raise ValueError(f"Invalid committee ID: {committee_id}")

    @staticmethod
    def get_notice_requirement(committee_type: CommitteeType) -> int:
        """Get the notice requirement for a committee type."""
        _notice_matrix = {
            CommitteeType.HOUSE: 0,
            CommitteeType.SENATE: 5,
            CommitteeType.JOINT: 10,
        }
        return _notice_matrix[committee_type]


@dataclass(frozen=True)
class BillContext:
    """Context information about a bill and its committee.

    This encapsulates the characteristics that determine which rules
    apply and how they should be evaluated.
    """

    bill_id: str
    committee_id: str
    bill_type: BillType
    committee_type: CommitteeType
    session: Optional[str] = None


class Status(Enum):
    """Compliant, provisional, or non-compliant."""

    COMPLIANT = "Compliant"
    UNKNOWN = "Unknown"
    NON_COMPLIANT = "Non-Compliant"


@dataclass(frozen=True)
class RuleResult:
    """Result of evaluating a single compliance rule."""

    passed: Status
    reason: str
    # Metadata exposed by rules for aggregation
    is_before_deadline: bool = False
    is_missing_notice: bool = False
    is_core_requirement: bool = False  # True for ReportedOut, Votes, Summary
    missing_description: Optional[str] = None  # Missing requirement text
    notice_description: Optional[str] = None  # Notice rule description


class ComplianceRule(ABC):
    """Abstract base class for compliance rules.

    Each rule represents a discrete compliance requirement that can be
    evaluated independently. Rules are composed into rule sets based on
    bill and committee characteristics.
    """

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority for rule evaluation (lower = evaluated first)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this rule."""

    @abstractmethod
    def check(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> RuleResult:
        """Evaluate this rule against the given bill data.

        Args:
            context: Bill and committee context
            status: Bill status information
            summary: Summary information
            votes: Vote information

        Returns:
            RuleResult indicating whether the rule passed and why
        """

    def is_deal_breaker(self, result: RuleResult) -> bool:
        """Return True if this rule's failure short-circuits aggregation."""
        return False  # Override in rules that are deal-breakers

    def requires_special_handling(self, result: RuleResult) -> bool:
        """Return True if this rule requires special aggregation logic."""
        return False  # Override in rules that need special handling

    def get_special_state(
        self, result: RuleResult, all_results: list[tuple[ComplianceRule, RuleResult]]
    ) -> Optional[tuple[ComplianceState, str]]:
        """Return (state, reason) if this rule determines final state, else
        None.

        Called only if requires_special_handling() returns True.
        """
        return None

    def is_core_requirement(self) -> bool:
        """Return True if this rule is a core requirement (counted)."""
        return False  # Override in ReportedOut, Votes, Summary rules

    def contributes_to_reason(self, result: RuleResult) -> Optional[str]:
        """Return a string to add to the final reason, or None."""
        return None  # Override in rules that contribute to reason


class NoticeRequirementRule(ComplianceRule):
    """Rule checking advance notice requirements for hearings."""

    @property
    def priority(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "Advance Notice Requirement"

    def check(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> RuleResult:
        if status.announcement_date is None:
            return RuleResult(
                passed=Status.UNKNOWN,
                reason="Announcement date missing",
                is_missing_notice=True,
            )
        if status.scheduled_hearing_date is None:
            return RuleResult(
                passed=Status.UNKNOWN,
                reason="Hearing date missing",
                is_missing_notice=True,
            )
        days_notice: int = (
            status.scheduled_hearing_date - status.announcement_date
        ).days
        notice_requirement: int = CommitteeType.get_notice_requirement(
            context.committee_type
        )
        if status.announcement_date < Constants194.notice_requirement_start_date:
            notice_requirement = 0
            # Exempt from notice requirement
            notice_desc = (
                f"exempt from notice requirement "
                f"(announced {status.announcement_date}, before 2025-06-26)"
            )
            return RuleResult(
                passed=Status.COMPLIANT,
                reason=f"Notice requirement met (days' notice: {days_notice})",
                notice_description=notice_desc,
            )
        if days_notice >= notice_requirement:
            notice_desc = f"adequate notice ({days_notice} days)"
            return RuleResult(
                passed=Status.COMPLIANT,
                reason=f"Notice requirement met (days' notice: {days_notice})",
                notice_description=notice_desc,
            )
        return RuleResult(
            passed=Status.NON_COMPLIANT,
            reason=(
                f"Insufficient notice: {days_notice} days "
                f"(minimum {notice_requirement})"
            ),
        )

    def is_deal_breaker(self, result: RuleResult) -> bool:
        return result.passed == Status.NON_COMPLIANT

    def requires_special_handling(self, result: RuleResult) -> bool:
        return result.is_missing_notice

    def get_special_state(
        self, result: RuleResult, all_results: list[tuple[ComplianceRule, RuleResult]]
    ) -> Optional[tuple[ComplianceState, str]]:
        if not result.is_missing_notice:
            return None

        # Count evidence from core requirements
        core_results = [r for rule, r in all_results if rule.is_core_requirement()]
        compliant_count = sum(1 for r in core_results if r.passed == Status.COMPLIANT)

        if compliant_count == 0:
            return (
                ComplianceState.UNKNOWN,
                "No hearing announcement found and no other evidence",
            )
        return (ComplianceState.NON_COMPLIANT, "No hearing announcement found")

    def contributes_to_reason(self, result: RuleResult) -> Optional[str]:
        return result.notice_description


class ReportedOutRequirementRule(ComplianceRule):
    """Rule checking if bill action occurred within deadline.

    Deadlines vary by bill type:
    - House bills: 60 days from hearing (+ 30 day extension = 90 max)
    - Senate bills: Session-specific Wednesday deadline (+ 30 day extension)

    This rule mirrors the logic from compute_deadlines() and classify():
    - Computes deadline_60, deadline_90, and effective_deadline based on
      bill type and extensions (equivalent to compute_deadlines()
      lines 847-858)
    - Checks if action occurred within deadline by comparing reported_date
      to effective_deadline, or using votes/summaries as evidence
      (equivalent to classify() lines 175-198)
    """

    @property
    def priority(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return "Deadline Requirement"

    def check(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> RuleResult:
        c = Constants194()
        today = date.today()
        if status.hearing_date is None:
            return RuleResult(
                passed=Status.UNKNOWN,
                reason="No hearing scheduled - cannot evaluate deadline",
                is_core_requirement=True,
            )
        hearing_date = status.hearing_date
        referred_date = status.referred_date or hearing_date
        deadline_60: date
        deadline_90: date
        if context.committee_id == "J24":
            if status.referred_date and status.referred_date <= c.hcf_december_deadline:
                deadline_60 = c.last_wednesday_january
                deadline_90 = deadline_60
            elif status.referred_date:
                deadline_60 = status.referred_date + timedelta(days=60)
                deadline_90 = deadline_60
            else:
                deadline_60 = c.last_wednesday_january
                deadline_90 = deadline_60
        elif context.bill_type == BillType.HOUSE:
            if hearing_date < c.third_wednesday_december:
                deadline_60 = hearing_date + timedelta(days=60)
                deadline_90 = hearing_date + timedelta(days=90)
                deadline_90 = min(deadline_90, c.third_wednesday_march)
                deadline_60 = min(deadline_60, c.third_wednesday_march)
            else:
                base = hearing_date + timedelta(days=60)
                deadline_60 = max(base, c.third_wednesday_march)
                deadline_90 = deadline_60
        else:
            if context.committee_type == CommitteeType.JOINT:
                if referred_date < c.senate_october_deadline:
                    deadline_60 = c.first_wednesday_december
                    deadline_90 = deadline_60
                else:
                    deadline_60 = referred_date + timedelta(days=60)
                    deadline_90 = deadline_60
            else:
                deadline_60 = c.end_of_session
                deadline_90 = deadline_60
        if not status.extension_until:
            effective_deadline = deadline_60
        else:
            if context.committee_id == "J24":
                effective_deadline = deadline_60
            elif context.bill_type == BillType.HOUSE:
                effective_deadline = min(status.extension_until, deadline_90)
                effective_deadline = max(effective_deadline, deadline_60)
            else:
                effective_deadline = max(status.extension_until, deadline_60)
        if status.reported_date and status.reported_date <= effective_deadline:
            return RuleResult(
                passed=Status.COMPLIANT,
                reason=(
                    f"Reported out on {status.reported_date} "
                    f"(within deadline {effective_deadline})"
                ),
                is_core_requirement=True,
            )
        if votes.present and not status.reported_date:
            return RuleResult(
                passed=Status.COMPLIANT,
                reason=(
                    "Action confirmed by vote record despite "
                    "missing reported-out date"
                ),
                is_core_requirement=True,
            )
        if today <= effective_deadline:
            return RuleResult(
                passed=Status.UNKNOWN,
                reason=f"Before deadline ({effective_deadline})",
                is_before_deadline=True,
                is_core_requirement=True,
            )
        if status.reported_date and status.reported_date > effective_deadline:
            return RuleResult(
                passed=Status.NON_COMPLIANT,
                reason=(
                    f"Action on {status.reported_date} after deadline {effective_deadline}"
                ),
                is_core_requirement=True,
                missing_description="reported out late",
            )
        missing_description = f"not reported out by deadline {effective_deadline}"
        return RuleResult(
            passed=Status.NON_COMPLIANT,
            reason=f"Deadline passed ({effective_deadline}) with no evidence of action",
            is_core_requirement=True,
            missing_description=missing_description,
        )

    def requires_special_handling(self, result: RuleResult) -> bool:
        return result.is_before_deadline

    def get_special_state(
        self, result: RuleResult, all_results: list[tuple[ComplianceRule, RuleResult]]
    ) -> Optional[tuple[ComplianceState, str]]:
        if not result.is_before_deadline:
            return None
        notice_desc = None
        for rule, r in all_results:
            if isinstance(rule, NoticeRequirementRule):
                notice_desc = rule.contributes_to_reason(r)
                break
        reason_parts = ["Before deadline"]
        if notice_desc:
            reason_parts.append(notice_desc)
        return (ComplianceState.UNKNOWN, ", ".join(reason_parts))

    def is_core_requirement(self) -> bool:
        return True

    def contributes_to_reason(self, result: RuleResult) -> Optional[str]:
        if result.passed != Status.COMPLIANT and result.missing_description:
            return result.missing_description
        return None


class VoteRequirementRule(ComplianceRule):
    """Rule checking if vote record is present.

    This rule mirrors the logic from classify():
    - Checks if votes.present is True (equivalent to classify() line 122)
    - Votes are a required component for full compliance
    - Missing votes contribute to non-compliance
    """

    @property
    def priority(self) -> int:
        return 5

    @property
    def name(self) -> str:
        return "Vote Requirement"

    def check(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> RuleResult:
        if votes.present:
            return RuleResult(
                passed=Status.COMPLIANT,
                reason="Votes posted",
                is_core_requirement=True,
            )
        return RuleResult(
            passed=Status.NON_COMPLIANT,
            reason="No votes posted",
            is_core_requirement=True,
            missing_description="no votes posted",
        )

    def is_core_requirement(self) -> bool:
        return True

    def contributes_to_reason(self, result: RuleResult) -> Optional[str]:
        if result.passed != Status.COMPLIANT and result.missing_description:
            return result.missing_description
        return None


class SummaryRequirementRule(ComplianceRule):
    """Rule checking if summary document is present.

    This rule mirrors the logic from classify():
    - Checks if summary.present is True (equivalent to classify() line 123)
    - Summaries are a required component for full compliance
    - Missing summaries contribute to non-compliance
    """

    @property
    def priority(self) -> int:
        return 4

    @property
    def name(self) -> str:
        return "Summary Requirement"

    def check(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> RuleResult:
        if summary.present:
            return RuleResult(
                passed=Status.COMPLIANT,
                reason="Summaries posted",
                is_core_requirement=True,
            )
        return RuleResult(
            passed=Status.NON_COMPLIANT,
            reason="No summaries posted",
            is_core_requirement=True,
            missing_description="no summaries posted",
        )

    def is_core_requirement(self) -> bool:
        return True

    def contributes_to_reason(self, result: RuleResult) -> Optional[str]:
        if result.passed != Status.COMPLIANT and result.missing_description:
            return result.missing_description
        return None


class ComplianceRuleSet:
    """A set of compliance rules to evaluate for a bill.

    Rules are evaluated in priority order. Deal-breaker rules that fail
    will short-circuit evaluation.
    """

    def __init__(self, rules: list[ComplianceRule]):
        """Initialize rule set with ordered rules.

        Args:
            rules: List of rules, will be sorted by priority
        """
        self.rules = sorted(rules, key=lambda r: r.priority)

    def evaluate(
        self,
        context: BillContext,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
    ) -> list[tuple[ComplianceRule, RuleResult]]:
        """Evaluate all rules in this set.

        Args:
            context: Bill and committee context
            status: Bill status information
            summary: Summary information
            votes: Vote information

        Returns:
            List of (rule, result) tuples, ordered by priority
        """
        rule_results = []
        for rule in self.rules:
            result = rule.check(context, status, summary, votes)
            rule_results.append((rule, result))
        return rule_results


class RuleFactory:
    """Factory for creating appropriate rule sets based on bill context."""

    @staticmethod
    def create_rule_set(context: BillContext) -> ComplianceRuleSet:
        """Create a rule set appropriate for the given bill context.

        Args:
            context: Bill and committee context

        Returns:
            ComplianceRuleSet with rules appropriate for this context
        """
        notice_rule: NoticeRequirementRule = NoticeRequirementRule()
        report_rule: ReportedOutRequirementRule = ReportedOutRequirementRule()
        summary_rule: SummaryRequirementRule = SummaryRequirementRule()
        vote_rule: VoteRequirementRule = VoteRequirementRule()
        rules: list[ComplianceRule] = [
            notice_rule,
            report_rule,
            summary_rule,
            vote_rule,
        ]
        if context.committee_type == CommitteeType.HOUSE:
            rules.remove(notice_rule)
        return ComplianceRuleSet(rules)

    @staticmethod
    def create_context(
        bill_id: str, committee_id: str, session: Optional[str] = None
    ) -> BillContext:
        """Create a BillContext from bill and committee IDs.

        Args:
            bill_id: Bill identifier (e.g., "H73", "S197")
            committee_id: Committee identifier (e.g., "H33", "J33", "S33")
            session: Optional session number (e.g., "194")

        Returns:
            BillContext with inferred bill and committee types
        """
        bill_type = BillType.from_bill_id(bill_id)
        committee_type = CommitteeType.from_committee_id(committee_id)
        return BillContext(
            bill_id=bill_id,
            committee_id=committee_id,
            bill_type=bill_type,
            committee_type=committee_type,
            session=session,
        )


def aggregate_to_compliance(
    rule_results: list[tuple[ComplianceRule, RuleResult]],
    context: BillContext,
    status: BillStatus,
    summary: SummaryInfo,
    votes: VoteInfo,
) -> BillCompliance:
    """Aggregate rule results into final BillCompliance.

    This function assembles building blocks
    provided by the rules. All logic lives in the rule classes.

    Args:
        rule_results: List of (rule, result) tuples from evaluate()
        context: Bill and committee context
        status: Bill status information
        summary: Summary information
        votes: Vote information

    Returns:
        BillCompliance with final state and reason
    """
    if status.hearing_date is None:
        status = BillStatus(
            bill_id=status.bill_id,
            committee_id=status.committee_id,
            hearing_date=status.hearing_date,
            deadline_60=status.deadline_60,
            deadline_90=status.deadline_90,
            reported_out=False,
            reported_date=None,
            extension_until=status.extension_until,
            effective_deadline=status.effective_deadline,
            announcement_date=status.announcement_date,
            scheduled_hearing_date=status.scheduled_hearing_date,
        )
        return BillCompliance(
            bill_id=context.bill_id,
            committee_id=context.committee_id,
            hearing_date=None,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.UNKNOWN,
            reason=("No hearing scheduled - " "cannot evaluate deadline compliance"),
        )
    deal_breaker_result = None
    for rule, result in rule_results:
        if rule.is_deal_breaker(result):
            deal_breaker_result = (rule, result)
            break
    if deal_breaker_result:
        rule, result = deal_breaker_result
        non_dealbreaker_results = [(r, res) for r, res in rule_results if r != rule]
        core_results = [
            res for r, res in non_dealbreaker_results if r.is_core_requirement()
        ]
        is_before_deadline = any(res.is_before_deadline for res in core_results)
        if not is_before_deadline:
            notice_part = result.reason.replace(
                "Insufficient notice: ", "insufficient hearing notice ("
            )
            notice_part += ")"
            factors = [notice_part]
            for r, res in non_dealbreaker_results:
                contrib = r.contributes_to_reason(res)
                if contrib:
                    factors.append(contrib)
            reason = f"Factors: {', '.join(factors)}"
        else:
            reason = result.reason
        return BillCompliance(
            bill_id=context.bill_id,
            committee_id=context.committee_id,
            hearing_date=status.hearing_date,
            summary=summary,
            votes=votes,
            status=status,
            state=ComplianceState.NON_COMPLIANT,
            reason=reason,
        )
    for rule, result in rule_results:
        if rule.requires_special_handling(result):
            special_state = rule.get_special_state(result, rule_results)
            if special_state is not None:
                state, reason = special_state
                return BillCompliance(
                    bill_id=context.bill_id,
                    committee_id=context.committee_id,
                    hearing_date=status.hearing_date,
                    summary=summary,
                    votes=votes,
                    status=status,
                    state=state,
                    reason=reason,
                )
    core_results = [
        (rule, result) for rule, result in rule_results if rule.is_core_requirement()
    ]
    compliant_count = sum(1 for _, r in core_results if r.passed == Status.COMPLIANT)
    reason_parts = []
    if compliant_count == 3:
        reason_parts.append(
            "All requirements met: " "reported out, votes posted, summaries posted"
        )
    else:
        missing_parts = []
        for rule, result in core_results:
            contrib = rule.contributes_to_reason(result)
            if contrib:
                missing_parts.append(contrib)
        if missing_parts:
            reason_parts.append(f"Factors: {', '.join(missing_parts)}")
    for rule, result in rule_results:
        if isinstance(rule, NoticeRequirementRule):
            notice_desc = rule.contributes_to_reason(result)
            if notice_desc:
                reason_parts.append(notice_desc)
            break
    final_state = (
        ComplianceState.COMPLIANT
        if compliant_count == 3
        else ComplianceState.NON_COMPLIANT
    )
    reason = ", ".join(reason_parts)
    return BillCompliance(
        bill_id=context.bill_id,
        committee_id=context.committee_id,
        hearing_date=status.hearing_date,
        summary=summary,
        votes=votes,
        status=status,
        state=final_state,
        reason=reason,
    )


def classify(
    bill_id: str,
    committee_id: str,
    status: BillStatus,
    summary: SummaryInfo,
    votes: VoteInfo,
) -> BillCompliance:
    """Classify bill compliance using ruleset approach.

    This is a drop-in replacement for compliance.classify() that uses
    the composable ruleset architecture instead of complex conditionals.

    Args:
        bill_id: Bill identifier
        committee_id: Committee identifier
        status: Bill status information
        summary: Summary information
        votes: Vote information

    Returns:
        BillCompliance with final state and reason
    """
    context = RuleFactory.create_context(bill_id, committee_id)
    rule_set = RuleFactory.create_rule_set(context)
    rule_results = rule_set.evaluate(context, status, summary, votes)
    return aggregate_to_compliance(rule_results, context, status, summary, votes)
