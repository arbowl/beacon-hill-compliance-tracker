"""Core data models for the timeline system."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Callable, Optional


class ActionType(str, Enum):
    """Enumeration of all legislative action types."""

    REFERRED = "REFERRED"
    DISCHARGED = "DISCHARGED"
    REPORTED = "REPORTED"
    STUDY_ORDER = "STUDY_ORDER"
    ACCOMPANIED = "ACCOMPANIED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    HEARING_RESCHEDULED = "HEARING_RESCHEDULED"
    HEARING_LOCATION_CHANGED = "HEARING_LOCATION_CHANGED"
    HEARING_TIME_CHANGED = "HEARING_TIME_CHANGED"
    REPORTING_EXTENDED = "REPORTING_EXTENDED"
    READ = "READ"
    READ_SECOND = "READ_SECOND"
    READ_THIRD = "READ_THIRD"
    RULES_SUSPENDED = "RULES_SUSPENDED"
    CONCURRED = "CONCURRED"
    PASSED_TO_BE_ENGROSSED = "PASSED_TO_BE_ENGROSSED"
    ENACTED = "ENACTED"
    SIGNED = "SIGNED"
    PLACED_IN_ORDERS = "PLACED_IN_ORDERS"
    REFERRED_TO_BILLS_IN_THIRD_READING = "REFERRED_TO_BILLS_IN_THIRD_READING"
    STEERING_REFERRAL = "STEERING_REFERRAL"
    AMENDED = "AMENDED"
    TITLE_CHANGED = "TITLE_CHANGED"
    EMERGENCY_PREAMBLE = "EMERGENCY_PREAMBLE"
    UNKNOWN = "UNKNOWN"


TERMINAL_COMMITTEE_ACTIONS = {
    ActionType.REPORTED,
    ActionType.STUDY_ORDER,
    ActionType.ACCOMPANIED,
}


@dataclass
class BillAction:
    """A single action taken on a bill.

    Represents one row from the bill's action history table,
    parsed into structured data.
    """

    date: date
    branch: str  # "House", "Senate", "Joint"
    action_type: ActionType  # "REFERRED", "REPORTED", etc.
    category: str  # Category: "referral-committee", etc.
    raw_text: str  # Original action text from the website
    extracted_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 0.0 to 1.0, how confident we are in the match

    def __str__(self) -> str:
        """Human-readable representation."""
        return f"{self.date} [{self.branch}] {self.action_type}"

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"BillAction(date={self.date}, branch={self.branch}, "
            f"type={self.action_type}, category={self.category})"
        )


@dataclass
class ActionNode:
    """Definition of an action type with patterns and extractors.

    Each node represents one type of legislative action (e.g., "REFERRED",
    "REPORTED") with:
    - Multiple regex patterns that match variations of that action
    - Named field extractors to pull structured data from matches
    - Normalizers to clean/standardize extracted data
    - Priority for disambiguation when multiple patterns match
    """

    action_type: ActionType  # "REFERRED", "REPORTED", etc.
    category: str  # Category: "referral-committee", etc.
    patterns: list[re.Pattern]  # Compiled regex patterns
    extractors: dict[str, Callable] = field(default_factory=dict)
    normalizers: dict[str, Callable] = field(default_factory=dict)
    priority: int = 100  # Lower = higher priority
    metadata: dict[str, Any] = field(default_factory=dict)

    def match(self, action_text: str) -> Optional[re.Match]:
        """Try to match action text against this node's patterns.

        Args:
            action_text: Raw action text from bill history

        Returns:
            Match object if successful, None otherwise
        """
        for pattern in self.patterns:
            match = pattern.search(action_text)
            if match:
                return match
        return None

    def extract_data(self, match: re.Match) -> dict[str, Any]:
        """Extract structured data from a regex match.

        Args:
            match: Successful regex match object

        Returns:
            Dictionary of extracted field names to values
        """
        data = {}
        data.update(match.groupdict())
        for field_name, extractor in self.extractors.items():
            try:
                value = extractor(match, data)
                if value is not None:
                    data[field_name] = value
            except Exception:  # pylint: disable=broad-exception-caught
                # Extractors shouldn't break the whole process
                pass
        for field_name, normalizer in self.normalizers.items():
            if field_name in data:
                try:
                    data[field_name] = normalizer(data[field_name])
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
        return data

    def calculate_confidence(self, match: re.Match) -> float:
        """Calculate confidence score for this match.

        Args:
            match: Successful regex match object

        Returns:
            Confidence score from 0.0 to 1.0
        """
        num_groups = len(match.groupdict())
        base_confidence = min(0.7 + (num_groups * 0.1), 1.0)
        if "confidence" in self.metadata:
            return self.metadata["confidence"]
        return base_confidence


class BillActionTimeline:
    """Timeline of all actions for a bill, with query methods.

    Provides a structured interface to query bill actions by type,
    committee, date range, etc.
    """

    def __init__(
        self, actions: list[BillAction], bill_id: Optional[str] = None
    ) -> None:
        """Initialize timeline.

        Args:
            actions: List of BillAction objects (will be sorted by date)
            bill_id: Optional bill identifier for reference
        """
        self.actions = sorted(actions, key=lambda a: a.date)
        self.bill_id = bill_id

    def get_reported_date(self, committee_id: str) -> Optional[date]:
        """Get the date a bill was reported out from a committee.

        Args:
            committee_id: Committee ID (e.g., "J10", "H33")

        Returns:
            Date of report-out, or None if not reported
        """
        for action in reversed(self.actions):
            if action.action_type in TERMINAL_COMMITTEE_ACTIONS:
                action_committee = action.extracted_data.get("committee_id")
                if action_committee == committee_id:
                    return action.date
        return None

    def has_reported(self, committee_id: str) -> bool:
        """Check if bill was reported out from a committee.

        Args:
            committee_id: Committee ID (e.g., "J10", "H33")

        Returns:
            True if reported out, False otherwise
        """
        return self.get_reported_date(committee_id) is not None

    def get_referred_date(self, committee_id: str) -> Optional[date]:
        """Get the date a bill was referred to a committee.

        Args:
            committee_id: Committee ID (e.g., "J10", "H33")

        Returns:
            Date of referral, or None if not referred
        """
        # Get the first REFERRED action for this committee
        for action in self.actions:
            if action.action_type in {ActionType.REFERRED, ActionType.DISCHARGED}:
                action_committee = action.extracted_data.get("committee_id")
                if action_committee == committee_id:
                    return action.date
        return None

    def get_hearings(self, committee_id: Optional[str] = None) -> list[BillAction]:
        """Get all hearing-related actions.

        Args:
            committee_id: Optional committee ID to filter by

        Returns:
            List of hearing actions (scheduled, rescheduled, etc.)
        """
        hearing_types = {
            ActionType.HEARING_SCHEDULED,
            ActionType.HEARING_RESCHEDULED,
            ActionType.HEARING_LOCATION_CHANGED,
        }
        hearings = [a for a in self.actions if a.action_type in hearing_types]
        if committee_id:
            hearings = [
                h
                for h in hearings
                if h.extracted_data.get("committee_id") == committee_id
            ]
        return hearings

    def get_latest_hearing_date(
        self, committee_id: Optional[str] = None
    ) -> Optional[date]:
        """Get the most recent scheduled hearing date.

        Args:
            committee_id: Optional committee ID to filter by

        Returns:
            Date of latest hearing, or None if no hearings
        """
        hearings = self.get_hearings(committee_id)
        if not hearings:
            return None
        latest = None
        for hearing in hearings:
            hearing_date_str = hearing.extracted_data.get("hearing_date")
            if hearing_date_str:
                try:
                    hearing_date = date.fromisoformat(hearing_date_str)
                    if latest is None or hearing_date > latest:
                        latest = hearing_date
                except (ValueError, TypeError):
                    pass
        return latest

    def get_latest_deadline_extension(self) -> Optional[date]:
        """Get the most recent extended deadline.

        Returns:
            Extended deadline date, or None if no extensions
        """
        extensions = [
            a for a in self.actions if a.action_type == ActionType.REPORTING_EXTENDED
        ]
        if not extensions:
            return None
        latest_extension = extensions[-1]
        deadline_str = latest_extension.extracted_data.get("new_deadline")
        if deadline_str:
            try:
                return date.fromisoformat(deadline_str)
            except (ValueError, TypeError):
                pass
        return None

    def get_actions_by_type(self, *action_type: ActionType) -> list[BillAction]:
        """Get all actions of a specific type.

        Args:
            action_type: Action type to filter by

        Returns:
            List of matching actions
        """
        return [a for a in self.actions if a.action_type in action_type]

    def get_actions_by_category(self, category: str) -> list[BillAction]:
        """Get all actions in a specific category.

        Args:
            category: Category to filter by

        Returns:
            List of matching actions
        """
        return [a for a in self.actions if a.category == category]

    def get_actions_in_range(self, start: date, end: date) -> list[BillAction]:
        """Get actions within a date range.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of actions in range
        """
        return [a for a in self.actions if start <= a.date <= end]

    def get_unknown_actions(self) -> list[BillAction]:
        """Get all actions that couldn't be classified.

        Returns:
            List of UNKNOWN type actions
        """
        return self.get_actions_by_type(ActionType.UNKNOWN)

    def infer_missing_committee_ids(self) -> None:
        """Infer committee IDs for hearings that don't explicitly mention them.

        When a hearing action doesn't include the committee name, it's typically
        for the most recently referred committee that hasn't been discharged or
        reported out yet.

        This method modifies actions in-place by adding inferred committee_ids
        to the extracted_data. It uses a two-pass approach to handle same-date
        actions correctly.
        """
        # Don't process if already processed
        if hasattr(self, "_committee_ids_inferred"):
            return
        self._committee_ids_inferred = True

        # Track active committees as we process actions chronologically
        # We track committee lifecycle separately from hearing inference
        # to handle same-date actions correctly
        active_committees_at_time: dict[str, date] = {}  # committee_id -> referral_date

        for action in self.actions:
            action_type = action.action_type
            committee_id = action.extracted_data.get("committee_id")

            # Update active committees up to this date
            if action_type == ActionType.REFERRED:
                if committee_id:
                    active_committees_at_time[committee_id] = action.date

            elif action_type in (TERMINAL_COMMITTEE_ACTIONS | {ActionType.DISCHARGED}):
                # Committee is no longer active after discharge/report
                if committee_id and committee_id in active_committees_at_time:
                    del active_committees_at_time[committee_id]

            # Infer committee for hearings without explicit committee
            elif action_type in {
                ActionType.HEARING_SCHEDULED,
                ActionType.HEARING_RESCHEDULED,
                ActionType.HEARING_LOCATION_CHANGED,
                ActionType.HEARING_TIME_CHANGED,
            }:
                if not committee_id and active_committees_at_time:
                    # Use the most recently referred active committee
                    most_recent = max(
                        active_committees_at_time.items(), key=lambda item: item[1]
                    )
                    inferred_committee_id = most_recent[0]

                    # Mark if multiple active committees (ambiguous case)
                    if len(active_committees_at_time) > 1:
                        action.extracted_data["committee_id_ambiguous"] = True

                    action.extracted_data["committee_id"] = inferred_committee_id
                    action.extracted_data["committee_id_inferred"] = True

    def __len__(self) -> int:
        """Number of actions in timeline."""
        return len(self.actions)

    def __iter__(self):
        """Iterate over actions."""
        return iter(self.actions)

    def __getitem__(self, index: int) -> BillAction:
        """Get action by index."""
        return self.actions[index]
