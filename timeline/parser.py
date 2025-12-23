"""Main parsing logic for extracting bill action timelines."""

import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Add parent directory to path to import from components
sys.path.insert(0, str(Path(__file__).parent.parent))

from components.interfaces import ParserInterface
from timeline.models import BillAction, BillActionTimeline, ActionNode, ActionType
from timeline.nodes import ACTION_NODES


# Date parsing patterns
DATE_FORMATS = [
    ("%m/%d/%Y", r"\d{1,2}/\d{1,2}/\d{4}"),  # 8/11/2025
    ("%B %d, %Y", r"[A-Za-z]+ \d{1,2}, \d{4}"),  # August 11, 2025
]


def parse_date(date_text: str) -> Optional[date]:
    """Parse a date string into a date object.

    Args:
        date_text: Date string to parse

    Returns:
        Parsed date, or None if parsing fails
    """
    for fmt, _ in DATE_FORMATS:
        try:
            return datetime.strptime(date_text.strip(), fmt).date()
        except ValueError:
            continue
    return None


class ActionExtractor:
    """Extracts structured action timeline from bill pages."""

    def __init__(self, action_nodes: Optional[list[ActionNode]] = None):
        """Initialize extractor.

        Args:
            action_nodes: List of ActionNode definitions (uses default if None)
        """
        self.nodes = action_nodes or ACTION_NODES
        # Sort by priority (lower = higher priority)
        self.nodes = sorted(self.nodes, key=lambda n: n.priority)

    def extract_actions(
        self, bill_url: str, bill_id: Optional[str] = None
    ) -> list[BillAction]:
        """Extract all actions from a bill's history page.

        Args:
            bill_url: URL of the bill page
            bill_id: Optional bill identifier for reference

        Returns:
            List of BillAction objects (sorted by date)
        """
        soup = ParserInterface.soup(bill_url)
        actions = []

        # Find the action history table
        # Structure: <tr><td>Date</td><td>Branch</td><td>Action</td></tr>
        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            # Extract raw data from table cells
            date_text = cells[0].get_text(" ", strip=True)
            branch_text = cells[1].get_text(" ", strip=True)
            action_text = cells[2].get_text(" ", strip=True)
            # Skip header rows
            if "Date" in date_text or "Branch" in branch_text:
                continue
            # Parse date
            action_date = parse_date(date_text)
            if not action_date:
                continue
            # Match against action nodes (can return multiple actions for compounds)
            matched_actions = self._match_actions(action_date, branch_text, action_text)
            actions.extend(matched_actions)
        # Sort by date
        return sorted(actions, key=lambda a: a.date)

    def _match_actions(
        self, action_date: date, branch: str, action_text: str
    ) -> list[BillAction]:
        """Match action text against ALL node patterns.

        A single action text can match multiple patterns (e.g., compound
        "reported and referred" actions). All matches are returned.

        Args:
            action_date: Date of the action
            branch: Branch (House/Senate/Joint/Executive)
            action_text: Raw action text

        Returns:
            List of BillAction objects (at least one, UNKNOWN if no matches)
        """
        actions = []
        for node in self.nodes:
            match = node.match(action_text)
            if match:
                extracted_data = node.extract_data(match)
                confidence = node.calculate_confidence(match)
                actions.append(
                    BillAction(
                        date=action_date,
                        branch=branch,
                        action_type=node.action_type.value,
                        category=node.category,
                        raw_text=action_text,
                        extracted_data=extracted_data,
                        confidence=confidence,
                    )
                )
        if not actions:
            actions.append(
                BillAction(
                    date=action_date,
                    branch=branch,
                    action_type=ActionType.UNKNOWN,
                    category="other",
                    raw_text=action_text,
                    extracted_data={},
                    confidence=0.0,
                )
            )
        return actions


def extract_timeline(
    bill_url: str, bill_id: Optional[str] = None
) -> BillActionTimeline:
    """Extract full action timeline for a bill.

    This is the main entry point for timeline extraction.

    Args:
        bill_url: URL of the bill page
        bill_id: Optional bill identifier for reference

    Returns:
        BillActionTimeline with all extracted actions
    """
    extractor = ActionExtractor()
    actions = extractor.extract_actions(bill_url, bill_id)
    timeline = BillActionTimeline(actions, bill_id)

    # Infer committee IDs for hearings that don't explicitly mention them
    timeline.infer_missing_committee_ids()

    return timeline
