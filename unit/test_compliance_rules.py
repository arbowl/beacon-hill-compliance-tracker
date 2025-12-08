"""Test individual compliance rules in isolation."""

import pytest
from datetime import date, timedelta

from components.ruleset import (
    NoticeRequirementRule, ReportedOutRequirementRule,
    VoteRequirementRule, SummaryRequirementRule,
    RuleFactory, Status, BillContext, BillType, CommitteeType
)
from unit.fixtures.bill_factory import BillFactory


class TestNoticeRequirementRule:
    """Test notice requirement rule in isolation."""
    
    def test_adequate_notice_joint_committee(self, bill_factory):
        """Joint committee with 10+ days notice should pass."""
        rule = NoticeRequirementRule()
        
        announcement = date(2025, 7, 1)
        hearing = date(2025, 7, 15)  # 14 days
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=announcement,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.COMPLIANT
        assert "14 days" in result.reason
    
    def test_inadequate_notice_joint_committee(self, bill_factory):
        """Joint committee with <10 days notice should fail."""
        rule = NoticeRequirementRule()
        
        announcement = date(2025, 7, 10)
        hearing = date(2025, 7, 15)  # Only 5 days
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=announcement,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.NON_COMPLIANT
        assert "5 days" in result.reason
        assert rule.is_deal_breaker(result)
    
    def test_exempt_before_requirement_date(self, bill_factory):
        """Hearings announced before 2025-06-26 are exempt."""
        rule = NoticeRequirementRule()
        
        announcement = date(2025, 6, 20)  # Before requirement date
        hearing = date(2025, 6, 22)  # Only 2 days
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=announcement,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.COMPLIANT
        assert result.notice_description
        assert "exempt" in result.notice_description
    
    def test_missing_announcement_date(self, bill_factory):
        """Missing announcement date should return UNKNOWN."""
        rule = NoticeRequirementRule()
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=date(2025, 7, 15),
            announcement_date=None,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.UNKNOWN
        assert result.is_missing_notice


class TestReportedOutRequirementRule:
    """Test reported-out requirement rule."""
    
    def test_reported_within_deadline(self, bill_factory):
        """Bill reported within 60 days should pass."""
        rule = ReportedOutRequirementRule()
        
        hearing = date(2025, 1, 15)
        reported = date(2025, 2, 15)  # 31 days later
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            reported_out=True,
            reported_date=reported,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.COMPLIANT
        assert result.is_core_requirement
    
    def test_before_deadline_unknown_state(self, bill_factory):
        """Bill within deadline window but not yet reported should be UNKNOWN."""
        rule = ReportedOutRequirementRule()
        
        hearing = date.today() - timedelta(days=30)
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            reported_out=False,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.UNKNOWN
        assert result.is_before_deadline
    
    def test_votes_compensate_for_missing_reported_date(self, bill_factory):
        """Votes present can confirm action even without reported_date."""
        rule = ReportedOutRequirementRule()
        
        hearing = date(2025, 1, 15)
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            reported_out=False,  # No formal report-out flag
            reported_date=None,
        )
        votes = bill_factory.create_votes(present=True)
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            votes
        )
        
        assert result.passed == Status.COMPLIANT
        assert "vote record" in result.reason.lower()
    
    def test_reported_after_deadline(self, bill_factory):
        """Bill reported after deadline should fail."""
        rule = ReportedOutRequirementRule()
        
        hearing = date(2025, 1, 15)
        deadline = hearing + timedelta(days=60)
        reported = deadline + timedelta(days=10)  # 10 days late
        
        status = bill_factory.create_status(
            committee_id="J33",
            hearing_date=hearing,
            reported_out=True,
            reported_date=reported,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.NON_COMPLIANT
        assert "after deadline" in result.reason.lower()
    
    def test_no_hearing_scheduled(self, bill_factory):
        """Bill with no hearing should return UNKNOWN."""
        rule = ReportedOutRequirementRule()
        
        status = bill_factory.create_status(
            hearing_date=None,
        )
        context = RuleFactory.create_context("H100", "J33")
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.UNKNOWN
        assert "No hearing scheduled" in result.reason


class TestVoteAndSummaryRules:
    """Test vote and summary requirement rules."""
    
    def test_votes_present(self, bill_factory):
        """Votes present should pass."""
        rule = VoteRequirementRule()
        votes = bill_factory.create_votes(present=True)
        context = RuleFactory.create_context("H100", "J33")
        status = bill_factory.create_status()
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            votes
        )
        
        assert result.passed == Status.COMPLIANT
        assert rule.is_core_requirement()
    
    def test_votes_missing(self, bill_factory):
        """Missing votes should fail."""
        rule = VoteRequirementRule()
        votes = bill_factory.create_votes(present=False)
        context = RuleFactory.create_context("H100", "J33")
        status = bill_factory.create_status()
        
        result = rule.check(
            context, status,
            bill_factory.create_summary(),
            votes
        )
        
        assert result.passed == Status.NON_COMPLIANT
        assert "no votes" in result.reason.lower()
        assert result.missing_description == "no votes posted"
    
    def test_summary_present(self, bill_factory):
        """Summary present should pass."""
        rule = SummaryRequirementRule()
        summary = bill_factory.create_summary(present=True)
        context = RuleFactory.create_context("H100", "J33")
        status = bill_factory.create_status()
        
        result = rule.check(
            context, status,
            summary,
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.COMPLIANT
    
    def test_summary_missing(self, bill_factory):
        """Missing summary should fail."""
        rule = SummaryRequirementRule()
        summary = bill_factory.create_summary(present=False)
        context = RuleFactory.create_context("H100", "J33")
        status = bill_factory.create_status()
        
        result = rule.check(
            context, status,
            summary,
            bill_factory.create_votes()
        )
        
        assert result.passed == Status.NON_COMPLIANT
        assert "no summaries" in result.reason.lower()
        assert result.missing_description == "no summaries posted"

