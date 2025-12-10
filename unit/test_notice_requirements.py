"""Test notice requirement edge cases."""

from datetime import date, timedelta

from components.ruleset import classify
from components.compliance import ComplianceState
from unit.fixtures import Committee
from unit.fixtures.bill_factory import BillFactory
from unit.fixtures.date_helpers import DateScenarios


class TestNoticeRequirements:
    """Test notice requirement scenarios."""

    def test_joint_committee_adequate_notice(
        self, bill_factory: BillFactory, date_scenarios: DateScenarios
    ):
        """Joint committee with 10+ days notice."""
        announcement, hearing = date_scenarios.adequate_joint_notice()
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT

    def test_joint_committee_inadequate_notice(
        self, bill_factory: BillFactory, date_scenarios: DateScenarios
    ):
        """Joint committee with <10 days notice is NON_COMPLIANT."""
        announcement, hearing = date_scenarios.inadequate_joint_notice()
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT
        assert "insufficient" in result.reason and "notice" in result.reason

    def test_senate_committee_adequate_notice(
        self, bill_factory: BillFactory, date_scenarios: DateScenarios
    ):
        """Senate committee with 5+ days notice."""
        announcement, hearing = date_scenarios.adequate_senate_notice()
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.SENATE,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("S100", Committee.SENATE.value, status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT

    def test_house_committee_no_notice_requirement(
        self, bill_factory: BillFactory, date_scenarios: DateScenarios
    ):
        """House committee has no notice requirement."""
        announcement, hearing = date_scenarios.house_hearing_dates()
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.HOUSE,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.HOUSE.value, status, summary, votes)
        # House committees are exempt from notice requirement
        assert result.state == ComplianceState.COMPLIANT

    def test_exempt_before_requirement_date(
        self, bill_factory: BillFactory, date_scenarios: DateScenarios
    ):
        """Hearings before 2025-06-26 are exempt from notice requirement."""
        announcement, hearing = date_scenarios.before_notice_requirement()
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT
        assert "exempt" in result.reason.lower()

    def test_exact_10_day_notice(self, bill_factory: BillFactory):
        """Exactly 10 days notice should pass for Joint committee."""
        announcement = date(2025, 7, 1)
        hearing = date(2025, 7, 11)  # Exactly 10 days
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.COMPLIANT

    def test_nine_day_notice_fails(self, bill_factory: BillFactory):
        """9 days notice should fail for Joint committee."""
        announcement = date(2025, 7, 1)
        hearing = date(2025, 7, 10)  # Only 9 days
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=announcement,
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT


class TestNoticeEdgeCases:
    """Test edge cases in notice requirements."""

    def test_missing_announcement_date(self, bill_factory: BillFactory):
        """Missing announcement date with evidence should be NON_COMPLIANT."""
        hearing = date(2025, 7, 15)
        reported = hearing + timedelta(days=30)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=None,  # Missing
            reported_out=True,
            reported_date=reported,
        )
        summary = bill_factory.create_summary(present=True)
        votes = bill_factory.create_votes(present=True)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.NON_COMPLIANT
        assert "No hearing announcement" in result.reason

    def test_missing_announcement_no_evidence(self, bill_factory: BillFactory):
        """Missing announcement with no evidence should be UNKNOWN."""
        hearing = date(2025, 7, 15)
        status = bill_factory.create_status(
            committee_id=Committee.JOINT,
            hearing_date=hearing,
            announcement_date=None,  # Missing
            reported_out=False,
        )
        summary = bill_factory.create_summary(present=False)
        votes = bill_factory.create_votes(present=False)
        result = classify("H100", Committee.JOINT.value, status, summary, votes)
        assert result.state == ComplianceState.UNKNOWN
