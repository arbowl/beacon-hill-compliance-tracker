"""Factory for creating test timelines."""

from datetime import date, timedelta
from typing import Optional

from timeline.models import BillAction, BillActionTimeline, ActionType


class TimelineFactory:
    """Factory for creating test timelines."""
    
    @staticmethod
    def create_action(
        action_date: date,
        action_type: ActionType,
        branch: str = "House",
        raw_text: str = "",
        committee_id: Optional[str] = None,
        hearing_date: Optional[str] = None,
        **kwargs
    ) -> BillAction:
        """Create a single BillAction.
        
        Args:
            action_type: Use ActionType enum (e.g., ActionType.REFERRED)
        """
        extracted_data = {}
        if committee_id:
            extracted_data["committee_id"] = committee_id
        if hearing_date:
            extracted_data["hearing_date"] = hearing_date
        extracted_data.update(kwargs.get("extracted_data", {}))
        
        return BillAction(
            date=action_date,
            branch=branch,
            action_type=action_type,
            category=kwargs.get("category", "other"),
            raw_text=raw_text or f"{action_type.value} action",
            extracted_data=extracted_data,
            confidence=kwargs.get("confidence", 1.0),
        )
    
    @staticmethod
    def create_simple_timeline(
        bill_id: str = "H100",
        committee_id: str = "J33",
        referred_date: Optional[date] = None,
        hearing_date: Optional[date] = None,
        reported_date: Optional[date] = None,
    ) -> BillActionTimeline:
        """Create a simple timeline with common actions."""
        if referred_date is None:
            referred_date = date.today() - timedelta(days=60)
        if hearing_date is None:
            hearing_date = referred_date + timedelta(days=20)
        
        actions = [
            TimelineFactory.create_action(
                referred_date,
                ActionType.REFERRED,
                committee_id=committee_id,
                raw_text=f"Referred to the committee on {committee_id}",
            ),
            TimelineFactory.create_action(
                hearing_date - timedelta(days=10),
                ActionType.HEARING_SCHEDULED,
                committee_id=committee_id,
                hearing_date=hearing_date.isoformat(),
                raw_text=f"Hearing scheduled for {hearing_date}",
            ),
        ]
        
        if reported_date:
            actions.append(
                TimelineFactory.create_action(
                    reported_date,
                    ActionType.REPORTED,
                    committee_id=committee_id,
                    raw_text=f"Reported favorably by committee {committee_id}",
                )
            )
        
        return BillActionTimeline(actions, bill_id=bill_id)
    
    @staticmethod
    def create_complex_timeline(
        bill_id: str = "H100",
        committee_transitions: Optional[list[tuple[str, date, date]]] = None,
    ) -> BillActionTimeline:
        """Create a complex timeline with multiple committee referrals.
        
        Args:
            committee_transitions: List of (committee_id, referred_date, reported_date)
        """
        if committee_transitions is None:
            base_date = date.today() - timedelta(days=120)
            committee_transitions = [
                ("J33", base_date, base_date + timedelta(days=40)),
                ("J10", base_date + timedelta(days=40), base_date + timedelta(days=80)),
            ]
        
        actions = []
        for committee_id, referred, reported in committee_transitions:
            actions.append(
                TimelineFactory.create_action(
                    referred,
                    ActionType.REFERRED,
                    committee_id=committee_id,
                )
            )
            # Add hearing
            hearing = referred + timedelta(days=15)
            actions.append(
                TimelineFactory.create_action(
                    hearing - timedelta(days=10),
                    ActionType.HEARING_SCHEDULED,
                    committee_id=committee_id,
                    hearing_date=hearing.isoformat(),
                )
            )
            # Add report
            actions.append(
                TimelineFactory.create_action(
                    reported,
                    ActionType.REPORTED,
                    committee_id=committee_id,
                )
            )
        
        return BillActionTimeline(actions, bill_id=bill_id)

