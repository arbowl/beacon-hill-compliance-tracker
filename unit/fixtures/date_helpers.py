"""Date utilities for creating test scenarios."""

from datetime import date, timedelta
from typing import Optional

from components.ruleset import Constants194


class DateScenarios:
    """Pre-configured date scenarios for testing."""
    
    @staticmethod
    def before_notice_requirement() -> tuple[date, date]:
        """Hearing announced before 2025-06-26 (exempt from notice)."""
        c = Constants194()
        announcement = c.notice_requirement_start_date - timedelta(days=30)
        hearing = announcement + timedelta(days=5)  # Only 5 days notice
        return announcement, hearing
    
    @staticmethod
    def adequate_joint_notice() -> tuple[date, date]:
        """10+ days notice for Joint committee."""
        announcement = date(2025, 7, 1)
        hearing = date(2025, 7, 15)  # 14 days
        return announcement, hearing
    
    @staticmethod
    def inadequate_joint_notice() -> tuple[date, date]:
        """< 10 days notice for Joint committee."""
        announcement = date(2025, 7, 10)
        hearing = date(2025, 7, 15)  # Only 5 days
        return announcement, hearing
    
    @staticmethod
    def adequate_senate_notice() -> tuple[date, date]:
        """5+ days notice for Senate committee."""
        announcement = date(2025, 7, 1)
        hearing = date(2025, 7, 10)  # 9 days
        return announcement, hearing
    
    @staticmethod
    def house_hearing_dates() -> tuple[date, date]:
        """Hearing for House committee (no notice requirement)."""
        announcement = date(2025, 7, 14)
        hearing = date(2025, 7, 15)  # 1 day is OK
        return announcement, hearing
    
    @staticmethod
    def within_60_day_deadline() -> tuple[date, date, date]:
        """Hearing, reported date within 60 days."""
        hearing = date(2025, 1, 15)
        reported = date(2025, 3, 1)  # 45 days later
        deadline = hearing + timedelta(days=60)
        return hearing, reported, deadline
    
    @staticmethod
    def after_60_day_deadline() -> tuple[date, date, date]:
        """Hearing, reported date after 60 days."""
        hearing = date(2025, 1, 15)
        deadline = hearing + timedelta(days=60)
        reported = deadline + timedelta(days=10)  # 10 days late
        return hearing, reported, deadline
    
    @staticmethod
    def before_deadline_not_yet_reported() -> tuple[date, date]:
        """Hearing in past, but still within deadline window."""
        today = date.today()
        hearing = today - timedelta(days=30)  # 30 days ago
        # Deadline is 60 days from hearing, so 30 days from now
        return hearing, hearing + timedelta(days=60)
    
    @staticmethod
    def health_care_financing_dates() -> tuple[date, date]:
        """Dates for J24 Health Care Financing committee."""
        c = Constants194()
        hearing = c.hcf_december_deadline - timedelta(days=30)
        # Special deadline: last Wednesday of January
        return hearing, c.last_wednesday_january

