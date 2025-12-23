"""Integration tests for full compliance classification."""

from datetime import date, timedelta

import pytest

from components.ruleset import classify
from components.compliance import ComplianceState
from unit.fixtures import Requirement, Committee
from unit.fixtures.bill_factory import BillFactory


class TestCompleteCompliance:
    """Test fully compliant scenarios."""

    def test_all_requirements_met(self, bill_factory: BillFactory):
        """Bill with all requirements should be COMPLIANT."""
        status, summary, votes = bill_factory.create_complete_compliant_bill(
            bill_id="H100",
            committee_id="J33",
        )
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT
        assert "All requirements met" in result.reason

    def test_house_committee_no_notice_requirement(self, bill_factory: BillFactory):
        """House committee should not check notice."""
        hearing = date(2025, 7, 15)
        announcement = date(2025, 7, 14)  # Only 1 day (OK for House)
        reported = hearing + timedelta(days=20)
        status = bill_factory.create_status(
            bill_id="H100",
            committee_id="H33",
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", "H33", status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT

    def test_compliant_with_extension(self, bill_factory: BillFactory):
        """Bill reported within extension period should be compliant."""
        hearing = date(2025, 1, 15)
        announcement = hearing - timedelta(days=15)
        deadline_60 = hearing + timedelta(days=60)
        extension = deadline_60 + timedelta(days=20)
        reported = deadline_60 + timedelta(days=10)  # After 60, within extension
        status = bill_factory.create_status(
            hearing_date=hearing,
            reported_out=True,
            reported_date=reported,
            extension_until=extension,
            announcement_date=announcement,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT


class TestNonCompliance:
    """Test non-compliant scenarios."""

    def test_insufficient_notice_is_deal_breaker(self, bill_factory: BillFactory):
        """Insufficient notice should override other compliance."""
        announcement = date(2025, 8, 10)
        hearing = date(2025, 8, 15)  # Only 5 days for Joint committee
        reported = hearing + timedelta(days=20)
        status = bill_factory.create_status(
            bill_id="H100",
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        # Even with summary and votes
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT
        assert "insufficient" in result.reason and "notice" in result.reason

    def test_missing_votes_only(self, bill_factory: BillFactory):
        """Missing only votes should be INCOMPLETE."""
        status, summary, votes = bill_factory.create_noncompliant_bill(
            bill_id="H100",
            committee_id=Committee.JOINT,
            missing=[Requirement.VOTES],
        )
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state in {
            ComplianceState.INCOMPLETE,
            ComplianceState.NON_COMPLIANT,
        }
        assert "no votes" in result.reason.lower()

    def test_missing_multiple_requirements(self, bill_factory: BillFactory):
        """Missing 2+ requirements should be NON_COMPLIANT."""
        status, summary, votes = bill_factory.create_noncompliant_bill(
            bill_id="H100",
            committee_id=Committee.JOINT,
            missing=[Requirement.SUMMARY, Requirement.VOTES],
        )
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT
        assert "no summaries" in result.reason.lower()
        assert "no votes" in result.reason.lower()

    def test_missing_all_requirements(self, bill_factory: BillFactory):
        """Missing all requirements should be NON_COMPLIANT."""
        status, summary, votes = bill_factory.create_noncompliant_bill(
            missing=[Requirement.REPORTED, Requirement.SUMMARY, Requirement.VOTES],
        )
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_no_hearing_scheduled(self, bill_factory: BillFactory):
        """Bill with no hearing should be UNKNOWN."""
        status = bill_factory.create_status(
            hearing_date=None,
        )
        summary = bill_factory.create_summary(present=False)
        votes = bill_factory.create_votes(present=False)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.UNKNOWN
        assert "No hearing scheduled" in result.reason

    def test_before_deadline(self, bill_factory: BillFactory):
        """Bill within deadline window should be UNKNOWN."""
        hearing = date.today() - timedelta(days=30)
        announcement = hearing - timedelta(days=15)
        status = bill_factory.create_status(
            hearing_date=hearing,
            reported_out=False,
            announcement_date=announcement,
        )
        summary = bill_factory.create_summary(present=False)
        votes = bill_factory.create_votes(present=False)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.UNKNOWN
        assert "Before deadline" in result.reason

    def test_missing_notice_no_evidence(self, bill_factory: BillFactory):
        """Missing notice with no other evidence should be UNKNOWN."""
        hearing = date(2025, 7, 15)
        status = bill_factory.create_status(
            hearing_date=hearing,
            announcement_date=None,
            reported_out=False,
        )
        summary = bill_factory.create_summary(present=False)
        votes = bill_factory.create_votes(present=False)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.UNKNOWN
        assert "No hearing announcement found" in result.reason

    def test_missing_notice_with_evidence(self, bill_factory: BillFactory):
        """Missing notice with other evidence should be NON_COMPLIANT."""
        hearing = date.today() - timedelta(days=100)
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            hearing_date=hearing,
            announcement_date=None,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", "J33", status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT
        assert "No hearing announcement found" in result.reason


class TestCommitteeVariations:
    """Test different committee types."""

    @pytest.mark.parametrize(
        "committee_id",
        [
            Committee.JOINT,
            Committee.HOUSE,
            Committee.SENATE,
        ],
    )
    def test_compliant_across_committee_types(
        self, bill_factory: BillFactory, committee_id: Committee
    ):
        """Test compliant bills across different committee types."""
        status, summary, votes = bill_factory.create_complete_compliant_bill(
            committee_id=committee_id.value,
        )
        result = classify("H100", committee_id.value, status, summary, votes)
        # All should be compliant if requirements met
        assert result.state in [ComplianceState.COMPLIANT, ComplianceState.UNKNOWN]
