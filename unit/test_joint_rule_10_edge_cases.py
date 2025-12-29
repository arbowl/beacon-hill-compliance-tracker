"""Test Joint Rule 10 edge cases based on the actual rule text.

These tests verify compliance with Joint Rule 10 requirements and document
known limitations/compromises in the implementation.
"""

from datetime import date, timedelta

import pytest

from components.ruleset import classify, Constants194
from components.compliance import ComplianceState
from unit.fixtures.bill_factory import BillFactory


class TestJointRule10FirstWednesdayDecemberDeadline:
    """Test 'first Wednesday in December' deadline for Senate bills in joint
    committees.

    Per Joint Rule 10: Joint committees shall make final report not later than
    the first Wednesday in December on all matters referred before Oct 1.
    """

    def test_senate_bill_referred_before_october_first_uses_december_deadline(
        self, bill_factory: BillFactory
    ):
        """Senate bill referred Sept 30 to joint committee must report by
        first Wed Dec.
        """
        c = Constants194()
        status = bill_factory.create_status(
            bill_id="S100",
            committee_id="J33",
            referred_date=c.senate_october_deadline - timedelta(days=1),
            hearing_date=date(2025, 9, 15),
            reported_date=c.first_wednesday_december,
            announcement_date=date(2025, 9, 1),
        )
        result = classify(
            "S100",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT
        status_late = bill_factory.create_status(
            bill_id="S100b",
            committee_id="J33",
            referred_date=c.senate_october_deadline - timedelta(days=1),
            hearing_date=date(2025, 9, 15),
            reported_date=c.first_wednesday_december + timedelta(days=1),
            announcement_date=date(2025, 9, 1),
        )
        result_late = classify(
            "S100b",
            "J33",
            status_late,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result_late.state == ComplianceState.NON_COMPLIANT

    def test_senate_bill_referred_on_october_first_uses_sixty_day_rule(
        self, bill_factory: BillFactory
    ):
        """Senate bill referred ON Oct 1 to joint committee uses 60-day rule.
        """
        c = Constants194()
        expected_deadline = c.senate_october_deadline + timedelta(days=60)
        status = bill_factory.create_status(
            bill_id="S101",
            committee_id="J33",
            referred_date=c.senate_october_deadline,
            hearing_date=date(2025, 10, 15),
            reported_date=expected_deadline,
            announcement_date=date(2025, 10, 1),
        )
        result = classify(
            "S101",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT
        status_late = bill_factory.create_status(
            bill_id="S101b",
            committee_id="J33",
            referred_date=c.senate_october_deadline,
            hearing_date=date(2025, 10, 15),
            reported_date=expected_deadline + timedelta(days=1),
            announcement_date=date(2025, 10, 1),
        )
        result_late = classify(
            "S101b",
            "J33",
            status_late,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result_late.state == ComplianceState.NON_COMPLIANT


class TestJointRule10HealthCareFinancingDeadlines:
    """Test special deadlines for J24 (Health Care Financing) committee.

    Per Joint Rule 10: Health Care Financing shall make final report not later
    than the last Wednesday of January on all matters referred on or before
    the fourth Wednesday of December.
    """

    @pytest.mark.xfail(
        reason=(
            "Known limitation: Model doesn't track tenure transitions leading "
            "up to HCF window"
        )
    )
    def test_hcf_bill_not_in_tenure_during_december_deadline(
        self, bill_factory: BillFactory
    ):
        """Bill referred to HCF after Dec 24 but hearing was before should use
        Jan deadline.

        This tests the known limitation: if a bill was referred to another
        committee before Dec 24, then re-referred to HCF after Dec 24, the
        model may not correctly apply the January deadline based on the
        original referral date.
        """
        c = Constants194()
        status = bill_factory.create_status(
            bill_id="S203",
            committee_id="J24",
            referred_date=c.hcf_december_deadline + timedelta(days=5),
            hearing_date=date(2025, 12, 1),
            reported_date=c.last_wednesday_january,
            announcement_date=date(2025, 11, 15),
        )
        result = classify(
            "S203",
            "J24",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT


class TestJointRule10ExtensionOrders:
    """Test extension order handling per Joint Rule 10.

    Joint Rule 10 allows for extensions but with limitations. House bills
    have a 30-day extension cap (60 days + 30 days = 90 days max).
    """

    def test_house_bill_with_thirty_day_extension(
        self, bill_factory: BillFactory
    ):
        """House bill can get 30-day extension per Joint Rule 10."""
        hearing = date(2025, 7, 15)
        deadline_60 = hearing + timedelta(days=60)
        extension_30 = deadline_60 + timedelta(days=30)
        status = bill_factory.create_status(
            bill_id="H300",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=extension_30,
            extension_until=extension_30,
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H300",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )

        assert result.state == ComplianceState.COMPLIANT

    @pytest.mark.xfail(
        reason=(
            "Known limitation: Model hard-caps House extensions at 90 days "
            "even when legally allowed to exceed"
        )
    )
    def test_house_bill_exceptional_extension_beyond_ninety_days(
        self, bill_factory: BillFactory
    ):
        """Some House bills can legally extend beyond 90 days in exceptional
        cases.

        The model simplifies by capping all House extensions at 90 days, but
        Joint Rule 10 can be suspended by 4/5 vote allowing longer extensions.
        """
        hearing = date(2025, 7, 15)
        exceptional_extension = hearing + timedelta(days=120)
        status = bill_factory.create_status(
            bill_id="H301",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=exceptional_extension,
            extension_until=exceptional_extension,
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H301",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT

    def test_senate_bill_extension_beyond_thirty_days_allowed(
        self, bill_factory: BillFactory
    ):
        """Senate bills can extend beyond 30 days (no cap like House bills)."""
        c = Constants194()
        hearing = date(2025, 9, 1)
        long_extension = c.first_wednesday_december + timedelta(days=60)
        status = bill_factory.create_status(
            bill_id="S300",
            committee_id="J33",
            referred_date=date(2025, 8, 15),
            hearing_date=hearing,
            reported_date=long_extension,
            extension_until=long_extension,
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "S300",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT


class TestJointRule10NoticeRequirements:
    """Test advance notice requirements.

    Joint Rule 10 doesn't directly specify notice requirements, but they were
    established by supplementary rules starting June 26, 2025.
    """

    def test_joint_committee_ten_day_notice_requirement(
        self, bill_factory: BillFactory
    ):
        """Joint committees require 10 days advance notice after June 26, 2025.
        """
        hearing = date(2025, 7, 15)
        announcement = hearing - timedelta(days=10)
        status = bill_factory.create_status(
            bill_id="H400",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=hearing + timedelta(days=30),
            announcement_date=announcement,
        )
        result = classify(
            "H400",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT

    def test_joint_committee_nine_days_notice_insufficient(
        self, bill_factory: BillFactory
    ):
        """Joint committee with only 9 days notice is non-compliant."""
        hearing = date(2025, 7, 15)
        announcement = hearing - timedelta(days=9)
        status = bill_factory.create_status(
            bill_id="H401",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=hearing + timedelta(days=30),
            announcement_date=announcement,
        )
        result = classify(
            "H401",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.NON_COMPLIANT

    def test_notice_requirement_starts_june_26_2025(
        self, bill_factory: BillFactory
    ):
        """Notice requirements start June 26, 2025. Earlier hearings are
        exempt.
        """
        c = Constants194()
        status_exempt = bill_factory.create_status(
            bill_id="H402",
            committee_id="J33",
            announcement_date=c.notice_requirement_start_date - timedelta(
                days=1
            ),
            hearing_date=c.notice_requirement_start_date,
            reported_date=c.notice_requirement_start_date + timedelta(days=30),
        )
        result_exempt = classify(
            "H402",
            "J33",
            status_exempt,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        status_required = bill_factory.create_status(
            bill_id="H403",
            committee_id="J33",
            announcement_date=c.notice_requirement_start_date,
            hearing_date=c.notice_requirement_start_date + timedelta(days=1),
            reported_date=c.notice_requirement_start_date + timedelta(days=30),
        )
        result_required = classify(
            "H403",
            "J33",
            status_required,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result_exempt.state == ComplianceState.COMPLIANT
        assert result_required.state == ComplianceState.NON_COMPLIANT


class TestJointRule10VoteRecordEvidence:
    """Test vote record as evidence of action.

    This tests a liberty the model takes: votes can confirm action even without
    a formal reported-out date. This is pragmatic but not explicitly in JR10.
    """

    def test_vote_record_confirms_action_without_reported_date(
        self, bill_factory: BillFactory
    ):
        """Vote record present confirms action occurred (model liberty)."""
        hearing = date(2025, 7, 15)

        status = bill_factory.create_status(
            bill_id="H500",
            committee_id="J33",
            hearing_date=hearing,
            reported_out=False,
            reported_date=None,
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H500",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT

    def test_vote_record_does_not_override_late_action_date(
        self, bill_factory: BillFactory
    ):
        """If we know action was late, votes don't make it compliant."""
        hearing = date(2025, 7, 15)
        deadline = hearing + timedelta(days=60)

        status = bill_factory.create_status(
            bill_id="H501",
            committee_id="J33",
            hearing_date=hearing,
            reported_out=True,
            reported_date=deadline + timedelta(days=10),
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H501",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.NON_COMPLIANT


class TestJointRule10MissingAnnouncementHandling:
    """Test how missing announcement dates are handled based on evidence."""

    def test_missing_announcement_with_other_compliance_evidence(
        self, bill_factory: BillFactory
    ):
        """Missing announcement + action evidence = non-compliant per model
        logic.
        """
        hearing = date(2025, 7, 15)
        status = bill_factory.create_status(
            bill_id="H600",
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=None,
            reported_date=hearing + timedelta(days=30),
        )
        result = classify(
            "H600",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.NON_COMPLIANT
        assert result.reason is not None
        assert "No hearing announcement" in result.reason

    def test_missing_announcement_without_evidence(
        self, bill_factory: BillFactory
    ):
        """Missing announcement + no evidence = unknown status."""
        hearing = date(2025, 7, 15)
        status = bill_factory.create_status(
            bill_id="H601",
            committee_id="J33",
            hearing_date=hearing,
            announcement_date=None,
            reported_out=False,
        )
        result = classify(
            "H601",
            "J33",
            status,
            bill_factory.create_summary(False),
            bill_factory.create_votes(False),
        )
        assert result.state == ComplianceState.UNKNOWN
        assert result.reason is not None
        assert "No hearing announcement" in result.reason


class TestJointRule10SessionBoundaries:
    """Test session-specific deadline boundaries mentioned in Joint Rule 10."""

    def test_third_wednesday_december_caps_house_extensions(
        self, bill_factory: BillFactory
    ):
        """House bills heard after 3rd Wed Dec have extensions capped at 3rd
        Wed March.
        """
        c = Constants194()
        hearing = c.third_wednesday_december + timedelta(days=1)
        reported = c.third_wednesday_march - timedelta(days=1)
        status = bill_factory.create_status(
            bill_id="H700",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=reported,
            extension_until=c.third_wednesday_march + timedelta(days=30),
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H700",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.COMPLIANT

    def test_house_bill_reported_after_third_wednesday_march_noncompliant(
        self, bill_factory: BillFactory
    ):
        """House bill reported after 3rd Wed March (even with extension) is
        non-compliant.
        """
        c = Constants194()
        hearing = date(2025, 1, 15)
        far_extension = c.third_wednesday_march + timedelta(days=30)
        status = bill_factory.create_status(
            bill_id="H701",
            committee_id="J33",
            hearing_date=hearing,
            reported_date=c.third_wednesday_march + timedelta(days=1),
            extension_until=far_extension,
            announcement_date=hearing - timedelta(days=15),
        )
        result = classify(
            "H701",
            "J33",
            status,
            bill_factory.create_summary(True),
            bill_factory.create_votes(True),
        )
        assert result.state == ComplianceState.NON_COMPLIANT
