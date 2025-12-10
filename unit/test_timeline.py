"""Test timeline extraction and parsing."""

from datetime import date, timedelta

from timeline.models import ActionType, BillActionTimeline
from unit.fixtures.timeline_factory import TimelineFactory


class TestTimelineConstruction:
    """Test creating timelines with factory."""

    def test_simple_timeline(self, timeline_factory: TimelineFactory):
        """Test creating a simple timeline."""
        timeline = timeline_factory.create_simple_timeline(
            bill_id="H100",
            committee_id="J33",
        )
        assert len(timeline) >= 2
        # Check actions using ActionType enum
        referrals = timeline.get_actions_by_type(ActionType.REFERRED)
        assert len(referrals) == 1
        hearings = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
        assert len(hearings) == 1
    
    def test_complex_timeline_multiple_committees(self, timeline_factory):
        """Test timeline with multiple committee transitions."""
        base_date = date.today() - timedelta(days=120)
        transitions = [
            ("J33", base_date, base_date + timedelta(days=40)),
            ("J10", base_date + timedelta(days=40), base_date + timedelta(days=80)),
        ]
        
        timeline = timeline_factory.create_complex_timeline(
            bill_id="H100",
            committee_transitions=transitions,
        )
        
        # Should have 2 referrals
        referrals = timeline.get_actions_by_type(ActionType.REFERRED)
        assert len(referrals) == 2
        
        # Should have 2 reported actions
        reported = timeline.get_actions_by_type(ActionType.REPORTED)
        assert len(reported) == 2
        
        # Should have 2 hearings
        hearings = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
        assert len(hearings) == 2
    
    def test_action_creation_with_types(self, timeline_factory):
        """Test creating individual actions with ActionType enum."""
        action_date = date(2025, 1, 15)
        
        # Test various action types
        for action_type in [
            ActionType.REFERRED,
            ActionType.REPORTED,
            ActionType.DISCHARGED,
            ActionType.HEARING_SCHEDULED,
            ActionType.REPORTING_EXTENDED,
        ]:
            action = timeline_factory.create_action(
                action_date,
                action_type,
                committee_id="J33",
            )
            
            assert action.action_type == action_type
            assert action.date == action_date
    
    def test_timeline_with_reported_date(self, timeline_factory):
        """Test timeline that includes report-out."""
        base_date = date(2025, 1, 1)
        reported_date = base_date + timedelta(days=40)
        
        timeline = timeline_factory.create_simple_timeline(
            bill_id="H100",
            committee_id="J33",
            referred_date=base_date,
            reported_date=reported_date,
        )
        
        # Should have reported action
        reported = timeline.get_actions_by_type(ActionType.REPORTED)
        assert len(reported) == 1
        assert reported[0].date == reported_date


class TestTimelineQuerying:
    """Test querying timeline data."""
    
    def test_get_actions_by_type(self, timeline_factory):
        """Test filtering by action type."""
        timeline = timeline_factory.create_simple_timeline()
        
        # Using ActionType enum for querying
        referrals = timeline.get_actions_by_type(ActionType.REFERRED)
        assert all(a.action_type == ActionType.REFERRED for a in referrals)
        
        hearings = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
        assert all(a.action_type == ActionType.HEARING_SCHEDULED for a in hearings)
    
    def test_get_reported_date(self, timeline_factory):
        """Test getting reported date for a committee."""
        base_date = date(2025, 1, 1)
        reported_date = base_date + timedelta(days=40)
        
        timeline = timeline_factory.create_simple_timeline(
            committee_id="J33",
            referred_date=base_date,
            reported_date=reported_date,
        )
        
        result = timeline.get_reported_date("J33")
        assert result == reported_date
    
    def test_has_reported(self, timeline_factory):
        """Test checking if bill was reported."""
        timeline = timeline_factory.create_simple_timeline(
            committee_id="J33",
            reported_date=date(2025, 2, 1),
        )
        
        assert timeline.has_reported("J33")
    
    def test_has_not_reported(self, timeline_factory):
        """Test checking if bill was not reported."""
        timeline = timeline_factory.create_simple_timeline(
            committee_id="J33",
            reported_date=None,
        )
        
        assert not timeline.has_reported("J33")
    
    def test_get_hearings(self, timeline_factory):
        """Test getting hearing actions."""
        timeline = timeline_factory.create_simple_timeline()
        
        hearings = timeline.get_hearings()
        assert len(hearings) >= 1
        assert all(
            a.action_type in [
                ActionType.HEARING_SCHEDULED,
                ActionType.HEARING_RESCHEDULED,
                ActionType.HEARING_LOCATION_CHANGED,
            ]
            for a in hearings
        )
    
    def test_infer_missing_committee_ids(self, timeline_factory):
        """Test committee ID inference for hearings."""
        base_date = date(2025, 1, 1)
        
        # Create actions manually
        actions = [
            timeline_factory.create_action(
                base_date,
                ActionType.REFERRED,
                committee_id="J33",
            ),
            # Hearing without explicit committee_id
            timeline_factory.create_action(
                base_date + timedelta(days=10),
                ActionType.HEARING_SCHEDULED,
                committee_id=None,  # Will be inferred
                hearing_date=(base_date + timedelta(days=20)).isoformat(),
            ),
        ]
        
        timeline = BillActionTimeline(actions)
        timeline.infer_missing_committee_ids()
        
        # Check that committee was inferred
        hearings = timeline.get_actions_by_type(ActionType.HEARING_SCHEDULED)
        assert len(hearings) == 1
        assert hearings[0].extracted_data.get("committee_id") == "J33"
        assert hearings[0].extracted_data.get("committee_id_inferred") is True


class TestTimelineChronology:
    """Test timeline ordering and date handling."""
    
    def test_actions_sorted_by_date(self, timeline_factory):
        """Timeline actions should be sorted by date."""
        timeline = timeline_factory.create_simple_timeline()
        
        dates = [action.date for action in timeline.actions]
        assert dates == sorted(dates)
    
    def test_get_actions_in_range(self, timeline_factory):
        """Test filtering actions by date range."""
        base_date = date(2025, 1, 1)
        timeline = timeline_factory.create_simple_timeline(
            referred_date=base_date,
            hearing_date=base_date + timedelta(days=30),
            reported_date=base_date + timedelta(days=60),
        )
        
        # Get actions in middle 20 days
        start = base_date + timedelta(days=20)
        end = base_date + timedelta(days=40)
        
        actions_in_range = timeline.get_actions_in_range(start, end)
        
        assert all(start <= a.date <= end for a in actions_in_range)

