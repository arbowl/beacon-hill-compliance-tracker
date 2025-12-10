"""Test deadline calculation logic."""

from datetime import date, timedelta

import pytest

from components.utils import compute_deadlines
from components.ruleset import Constants194


class TestDeadlineCalculation:
    """Test deadline computation for different scenarios."""

    def test_house_bill_standard_deadline(self):
        """House bill should get 60-day deadline."""
        hearing_date = date(2025, 2, 1)
        d60, d90, effective = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="H100",
            session="194"
        )
        assert d60 == hearing_date + timedelta(days=60)
        assert d90 == hearing_date + timedelta(days=90)
        assert effective == d60

    def test_house_bill_with_extension(self):
        """House bill with extension should use extension date."""
        hearing_date = date(2025, 2, 1)
        extension_date = date(2025, 5, 1)
        _, __, effective = compute_deadlines(
            hearing_date,
            extension_until=extension_date,
            bill_id="H100",
            session="194"
        )
        assert effective == extension_date

    @pytest.mark.xfail  # Referral tracking not implemented yet
    def test_house_bill_near_session_end(self):
        """House bill near end of session should cap at March deadline."""
        c = Constants194()
        # Hearing less than 60 days before March deadline
        hearing_date = c.third_wednesday_march - timedelta(days=40)
        _, d90, __ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="H100",
            session="194"
        )
        # 90-day deadline should be capped at March deadline
        assert d90 == c.third_wednesday_march

    def test_senate_bill_before_december(self):
        """Senate bill before December should use December deadline."""
        hearing_date = date(2025, 9, 1)
        d60, d90, _ = compute_deadlines(
            hearing_date,
            extension_until=None,
            bill_id="S100",
            session="194"
        )
        c = Constants194()
        assert d60 == c.first_wednesday_december
        assert d90 == c.first_wednesday_december + timedelta(days=30)


class TestDeadlineEdgeCases:
    """Test edge cases in deadline calculation."""

    def test_extension_cannot_exceed_90_day_limit(self):
        """Extension should be capped at 90-day deadline."""
        hearing_date = date(2025, 1, 1)
        # Try to extend beyond 90 days
        far_extension = hearing_date + timedelta(days=120)
        _, d90, effective = compute_deadlines(
            hearing_date,
            extension_until=far_extension,
            bill_id="H100",
            session="194"
        )
        # Should be capped at 90-day limit
        assert effective <= d90

    def test_extension_cannot_be_before_60_day_deadline(self):
        """Extension before 60-day deadline should use 60-day deadline."""
        hearing_date = date(2025, 1, 1)
        # Extension date before 60 days
        early_extension = hearing_date + timedelta(days=30)
        d60, _, effective = compute_deadlines(
            hearing_date,
            extension_until=early_extension,
            bill_id="H100",
            session="194"
        )
        # Should use 60-day deadline as minimum
        assert effective >= d60
