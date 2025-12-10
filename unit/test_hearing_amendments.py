"""Test 72-hour notice requirement for hearing amendments.

Tests the new logic in get_committee_tenure() that distinguishes between:
- Date reschedules (require 10 days notice)
- Agenda amendments (require 3 days / 72 hours notice)
- Location/time changes (require 3 days / 72 hours notice)
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch

from collectors.bill_status_basic import get_committee_tenure, CommitteeTenure
from timeline.models import BillActionTimeline, ActionType
from unit.fixtures.timeline_factory import TimelineFactory


class MockBillURL:
    """Mock bill URLs for testing."""
    H100 = "https://malegislature.gov/Bills/194/H100"
    H200 = "https://malegislature.gov/Bills/194/H200"
    H300 = "https://malegislature.gov/Bills/194/H300"


@pytest.fixture
def committee_id():
    """Standard test committee ID."""
    return "J33"


@pytest.fixture
def mock_extract_timeline():
    """Fixture to mock timeline extraction.
    
    Returns a function that can be used to set up the mock with a specific timeline.
    """
    def _mock_with_timeline(timeline: BillActionTimeline):
        """Set up mock to return the given timeline."""
        return patch(
            'collectors.bill_status_basic.extract_timeline',
            return_value=timeline
        )
    return _mock_with_timeline


class TestInitialHearingNotice:
    """Test basic initial hearing notice scenarios."""
    
    def test_initial_hearing_adequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Initial hearing with 10+ days notice is compliant."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),  # 15 days before hearing
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert tenure.hearing_announcement_date == date(2025, 7, 5)
        assert tenure.hearing_date == hearing_date
        assert tenure.notice_days == 15
        assert len(tenure.all_hearings) == 1
        assert tenure.all_hearings[0]["is_compliant"] is True
    
    def test_initial_hearing_inadequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Initial hearing with <10 days notice is a violation."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 13),  # Only 7 days before hearing
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert tenure.hearing_announcement_date == date(2025, 7, 13)
        assert tenure.notice_days == 7
        assert tenure.all_hearings[0]["is_compliant"] is False
        assert tenure.all_hearings[0]["violation_type"] == "initial_hearing"


class TestDateRescheduleNotice:
    """Test date reschedule scenarios (10-day requirement)."""
    
    def test_date_reschedule_adequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Date reschedule with 10+ days notice is compliant."""
        referred_date = date(2025, 7, 1)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 20).isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 10),  # 15 days before new date
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 25).isoformat(),  # New date
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert tenure.hearing_date == date(2025, 7, 25)
        assert tenure.notice_days == 15
        assert len(tenure.all_hearings) == 2
        # Both should be compliant
        assert all(h["is_compliant"] for h in tenure.all_hearings)
    
    def test_date_reschedule_inadequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Date reschedule with <10 days notice is a violation."""
        referred_date = date(2025, 7, 1)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 20).isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),  # Only 7 days before new date
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 25).isoformat(),  # New date
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the violation (reschedule announcement)
        assert tenure.hearing_announcement_date == date(2025, 7, 18)
        assert tenure.notice_days == 7
        
        # Check violation details
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 1
        assert violations[0]["violation_type"] == "date_reschedule"
        assert violations[0]["required_days"] == 10


class TestAgendaAmendmentNotice:
    """Test non-date reschedule scenarios (3-day / 72-hour requirement)."""
    
    def test_agenda_change_adequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Agenda change (reschedule to same date) with 3+ days is compliant."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 15),  # 5 days before hearing
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),  # Same date
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the final hearing (all compliant)
        assert tenure.hearing_date == hearing_date
        assert tenure.notice_days == 5  # From the agenda change
        
        # Both should be compliant
        assert all(h["is_compliant"] for h in tenure.all_hearings)
        assert tenure.all_hearings[1]["violation_type"] == "agenda_change"
        assert tenure.all_hearings[1]["required_days"] == 3
    
    def test_agenda_change_inadequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Agenda change with <3 days notice is a violation."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),  # Only 2 days before hearing
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),  # Same date
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the violation
        assert tenure.hearing_announcement_date == date(2025, 7, 18)
        assert tenure.notice_days == 2
        
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 1
        assert violations[0]["violation_type"] == "agenda_change"
        assert violations[0]["required_days"] == 3


class TestLocationTimeChangeNotice:
    """Test location and time change scenarios (3-day / 72-hour requirement)."""
    
    def test_location_change_adequate_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Location change with 3+ days notice is compliant."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 15),  # 5 days before hearing
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
                # Note: no hearing_date, it's inferred
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert tenure.hearing_date == hearing_date
        assert tenure.notice_days == 5
        assert all(h["is_compliant"] for h in tenure.all_hearings)
    
    def test_location_change_within_72_hours(
        self, committee_id, mock_extract_timeline
    ):
        """Location change within 72 hours is a violation."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),  # Only 2 days before hearing
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the violation
        assert tenure.hearing_announcement_date == date(2025, 7, 18)
        assert tenure.notice_days == 2
        
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 1
        assert violations[0]["violation_type"] == "location_or_time_change"
    
    def test_time_change_within_72_hours(
        self, committee_id, mock_extract_timeline
    ):
        """Time change within 72 hours is a violation."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 19),  # Only 1 day before hearing
                ActionType.HEARING_TIME_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert tenure.hearing_announcement_date == date(2025, 7, 19)
        assert tenure.notice_days == 1
        
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 1
        assert violations[0]["violation_type"] == "location_or_time_change"
    
    def test_exactly_72_hours_notice(
        self, committee_id, mock_extract_timeline
    ):
        """Exactly 3 days (72 hours) notice is compliant."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 17),  # Exactly 3 days before hearing
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # All should be compliant (3 days meets the requirement)
        assert all(h["is_compliant"] for h in tenure.all_hearings)


class TestMultipleViolations:
    """Test worst violation tracking with multiple changes."""
    
    def test_multiple_violations_reports_worst(
        self, committee_id, mock_extract_timeline
    ):
        """With multiple violations, report the one with fewest days notice."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),  # 2 days notice
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 19),  # 1 day notice - WORST
                ActionType.HEARING_TIME_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the worst violation (1 day)
        assert tenure.hearing_announcement_date == date(2025, 7, 19)
        assert tenure.notice_days == 1
        
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 2  # Two violations total
    
    def test_one_violation_among_compliant_changes(
        self, committee_id, mock_extract_timeline
    ):
        """One violation among many compliant changes is reported."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 10),  # 10 days notice - compliant
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 12),  # 8 days notice - compliant
                ActionType.HEARING_TIME_CHANGED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),  # 2 days notice - VIOLATION
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 14),  # 6 days notice - compliant
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the only violation
        assert tenure.hearing_announcement_date == date(2025, 7, 18)
        assert tenure.notice_days == 2
        
        violations = [h for h in tenure.all_hearings if not h["is_compliant"]]
        assert len(violations) == 1


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_location_change_without_prior_hearing(
        self, committee_id, mock_extract_timeline
    ):
        """Location change before any scheduled hearing is ignored."""
        referred_date = date(2025, 7, 1)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
                # No prior hearing to reference
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # No hearing should be recorded (location change was ignored)
        assert len(tenure.all_hearings) == 0
        assert tenure.hearing_date is None
    
    def test_changes_outside_committee_tenure(
        self, committee_id, mock_extract_timeline
    ):
        """Changes after committee tenure ends are ignored."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        reported_date = date(2025, 7, 30)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                reported_date,
                ActionType.REPORTED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 8, 5),  # After tenure ended
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Only the initial hearing should be recorded
        assert len(tenure.all_hearings) == 1
        assert tenure.reported_date == reported_date
    
    def test_changes_for_different_committee(
        self, committee_id, mock_extract_timeline
    ):
        """Changes for a different committee are ignored."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 18),
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id="J10",  # Different committee
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Only the initial hearing for J33 should be recorded
        assert len(tenure.all_hearings) == 1
        assert tenure.all_hearings[0]["is_compliant"] is True
    
    def test_all_compliant_reports_final_hearing(
        self, committee_id, mock_extract_timeline
    ):
        """When all changes are compliant, report the final hearing."""
        referred_date = date(2025, 7, 1)
        hearing_date = date(2025, 7, 20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 10),
                ActionType.HEARING_LOCATION_CHANGED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 12),
                ActionType.HEARING_TIME_CHANGED,
                committee_id=committee_id,
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        # Should report the final change (time change on day 12)
        assert tenure.hearing_announcement_date == date(2025, 7, 12)
        assert tenure.notice_days == 8
        assert all(h["is_compliant"] for h in tenure.all_hearings)
    
    def test_multiple_date_reschedules(
        self, committee_id, mock_extract_timeline
    ):
        """Multiple date reschedules are all tracked."""
        referred_date = date(2025, 7, 1)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
            ),
            TimelineFactory.create_action(
                date(2025, 7, 5),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 20).isoformat(),
            ),
            TimelineFactory.create_action(
                date(2025, 7, 10),
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 25).isoformat(),  # New date
            ),
            TimelineFactory.create_action(
                date(2025, 7, 15),
                ActionType.HEARING_RESCHEDULED,
                committee_id=committee_id,
                hearing_date=date(2025, 7, 30).isoformat(),  # Another new date
            ),
        ]
        timeline = BillActionTimeline(actions, bill_id="H100")
        
        with mock_extract_timeline(timeline):
            tenure = get_committee_tenure(MockBillURL.H100, committee_id)
        
        assert tenure is not None
        assert len(tenure.all_hearings) == 3
        # All should be compliant
        assert all(h["is_compliant"] for h in tenure.all_hearings)
        # Final hearing should be reported
        assert tenure.hearing_date == date(2025, 7, 30)

