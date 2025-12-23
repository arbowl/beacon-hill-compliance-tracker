"""Test deadline calculation logic."""

from datetime import date, timedelta

from components.utils import compute_deadlines
from components.ruleset import Constants194


class TestDeadlineCalculation:
    """Test deadline computation for different scenarios."""

    def test_house_bill_standard_deadline(self):
        """House bill should get 60-day deadline."""
        hearing_date = date(2025, 2, 1)
        d60, d90, effective = compute_deadlines(
            hearing_date, extension_until=None, bill_id="H100", session="194"
        )
        assert d60 == hearing_date + timedelta(days=60)
        assert d90 == hearing_date + timedelta(days=90)
        assert effective == d60

    def test_house_bill_with_extension(self):
        """House bill with extension should use extension date."""
        hearing_date = date(2025, 2, 1)
        extension_date = date(2025, 5, 1)
        _, __, effective = compute_deadlines(
            hearing_date, extension_until=extension_date, bill_id="H100", session="194"
        )
        assert effective == extension_date

    def test_house_bill_near_session_end(self):
        """House bill near end of session should cap at March deadline."""
        c = Constants194()
        # Hearing less than 60 days before March deadline
        hearing_date = c.third_wednesday_march - timedelta(days=40)
        _, d90, __ = compute_deadlines(
            hearing_date, extension_until=None, bill_id="H100", session="194"
        )
        # 90-day deadline should be capped at March deadline
        assert d90 == c.third_wednesday_march

    def test_senate_bill_before_december(self):
        """Senate bill before December should use December deadline."""
        hearing_date = date(2025, 9, 1)
        d60, d90, _ = compute_deadlines(
            hearing_date, extension_until=None, bill_id="S100", session="194"
        )
        c = Constants194()
        assert d60 == c.first_wednesday_december
        assert d90 == c.first_wednesday_december + timedelta(days=30)

    def test_senate_bill_joint_committee_before_october(self):
        """Senate bill in joint committee referred before Oct 1 uses
        December deadline."""
        c = Constants194()
        hearing_date = date(2025, 9, 1)
        referred_date = date(2025, 8, 15)  # Before Oct 1
        d60, d90, _ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="S100",
            session="194",
            referred_date=referred_date,
            committee_id="J33",  # Joint committee
        )
        assert d60 == c.first_wednesday_december
        assert d90 == c.first_wednesday_december + timedelta(days=30)

    def test_senate_bill_joint_committee_on_october_1(self):
        """Senate bill in joint committee referred on Oct 1 uses
        60-day rule."""
        c = Constants194()
        hearing_date = date(2025, 10, 15)
        referred_date = c.senate_october_deadline  # Exactly Oct 1
        d60, d90, _ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="S100",
            session="194",
            referred_date=referred_date,
            committee_id="J33",  # Joint committee
        )
        # Should use 60 days from referral (Oct 1 + 60 = Nov 30)
        expected_deadline = referred_date + timedelta(days=60)
        assert d60 == expected_deadline
        assert d90 == expected_deadline  # No extension for this case

    def test_senate_bill_joint_committee_after_october(self):
        """Senate bill in joint committee referred after Oct 1 uses
        60-day rule."""
        referred_date = date(2025, 10, 15)  # After Oct 1
        hearing_date = date(2025, 10, 20)
        d60, d90, _ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="S100",
            session="194",
            referred_date=referred_date,
            committee_id="J33",  # Joint committee
        )
        # Should use 60 days from referral (Oct 15 + 60 = Dec 14)
        expected_deadline = referred_date + timedelta(days=60)
        assert d60 == expected_deadline
        assert d90 == expected_deadline  # No extension for this case

    def test_senate_bill_non_joint_committee_uses_default_rules(self):
        """Senate bill in non-joint committee uses default Senate rules."""
        c = Constants194()
        hearing_date = date(2025, 10, 15)
        referred_date = date(2025, 10, 10)  # After Oct 1, but...
        d60, d90, _ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="S100",
            session="194",
            referred_date=referred_date,
            committee_id="S33",  # Senate committee (not joint)
        )
        # Should still use December deadline (joint committee rule
        # doesn't apply)
        assert d60 == c.first_wednesday_december
        assert d90 == c.first_wednesday_december + timedelta(days=30)


class TestDeadlineEdgeCases:
    """Test edge cases in deadline calculation."""

    def test_extension_cannot_exceed_90_day_limit(self):
        """Extension should be capped at 90-day deadline for House bills."""
        hearing_date = date(2025, 1, 1)
        # Try to extend beyond 90 days
        far_extension = hearing_date + timedelta(days=120)
        _, d90, effective = compute_deadlines(
            hearing_date, extension_until=far_extension, bill_id="H100", session="194"
        )
        # Should be capped at 90-day limit for House bills
        assert effective == d90
        assert effective < far_extension

    def test_extension_cannot_be_before_60_day_deadline(self):
        """Extension before 60-day deadline should use 60-day deadline."""
        hearing_date = date(2025, 1, 1)
        # Extension date before 60 days
        early_extension = hearing_date + timedelta(days=30)
        d60, _, effective = compute_deadlines(
            hearing_date, extension_until=early_extension, bill_id="H100", session="194"
        )
        # Should use 60-day deadline as minimum
        assert effective >= d60


class TestSenateExtensions:
    """Test Senate bill extension behavior - no 30-day cap."""

    def test_senate_bill_extension_beyond_30_days(self):
        """Senate bill can be extended beyond 30 days (no cap)."""
        c = Constants194()
        hearing_date = date(2025, 9, 1)
        extension_date = c.first_wednesday_december + timedelta(days=60)
        _, __, effective = compute_deadlines(
            hearing_date, extension_until=extension_date, bill_id="S100", session="194"
        )
        assert effective == extension_date

    def test_senate_bill_extension_far_future(self):
        """Senate bill can be extended far into the future."""
        c = Constants194()
        hearing_date = date(2025, 9, 1)
        extension_date = c.first_wednesday_december + timedelta(days=180)
        _, __, effective = compute_deadlines(
            hearing_date, extension_until=extension_date, bill_id="S100", session="194"
        )
        assert effective == extension_date

    def test_senate_bill_extension_before_d60_floors_at_d60(self):
        """Senate bill extension before d60 should floor at d60."""
        c = Constants194()
        hearing_date = date(2025, 9, 1)
        early_extension = c.first_wednesday_december - timedelta(days=10)
        d60, _, effective = compute_deadlines(
            hearing_date, extension_until=early_extension, bill_id="S100", session="194"
        )
        assert effective == d60
        assert effective > early_extension

    def test_senate_bill_j24_hcf_extension_respects_special_rules(self):
        """Senate bill in J24 (HCF) committee - special rules
        override."""
        c = Constants194()
        hearing_date = date(2025, 11, 1)
        far_extension = c.last_wednesday_january + timedelta(days=90)
        d60, d90, effective = compute_deadlines(
            hearing_date,
            extension_until=far_extension,
            bill_id="S100",
            session="194",
            committee_id="J24",
        )
        assert d60 == c.last_wednesday_january
        assert d90 == c.last_wednesday_january
        assert effective == d60

    def test_senate_bill_joint_committee_after_oct_no_extension_cap(self):
        """Senate bill referred after Oct 1 with extension - no cap."""
        referred_date = date(2025, 10, 15)
        hearing_date = date(2025, 10, 20)
        base_deadline = referred_date + timedelta(days=60)
        extension_date = base_deadline + timedelta(days=90)
        d60, d90, effective = compute_deadlines(
            hearing_date,
            extension_until=extension_date,
            bill_id="S100",
            session="194",
            referred_date=referred_date,
            committee_id="J33",
        )
        assert effective == extension_date
        assert d60 == d90
        assert effective > d60
