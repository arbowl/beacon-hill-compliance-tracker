"""Field extraction utilities for parsing action text.

Right now, they all have the same call signature, so some arguments aren't
used. Not sure if I'll stick with that decision, but that's the rationale.
"""

import re
from datetime import datetime
from typing import Any, Optional


def extract_date(match: re.Match, data: dict[str, Any]) -> Optional[str]:
    """Extract and parse a date field from a match.

    Handles multiple date formats commonly found in MA Legislature actions.
    Returns ISO format date string (YYYY-MM-DD) for consistency.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        ISO format date string, or None if not found/parseable
    """
    date_text = data.get("date") or data.get("hearing_date")
    if not date_text:
        return None
    formats = [
        "%m/%d/%Y",  # 09/09/2025
        "%B %d, %Y",  # September 9, 2025
        "%b %d, %Y",  # Sep 9, 2025
        "%A, %B %d, %Y",  # Wednesday, September 9, 2025
    ]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_text.strip(), fmt).date()
            return parsed.isoformat()
        except ValueError:
            continue
    return None


def extract_committee_name(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract committee name from match.
    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Raw committee name, or None if not found
    """
    committee = data.get("committee")
    if committee:
        return committee.strip()
    return None


def extract_bill_id(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract and normalize a bill ID.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Normalized bill ID (e.g., "H73", "S197"), or None
    """
    bill_id = data.get("related_bill") or data.get("bill_id")
    if not bill_id:
        return None
    normalized = bill_id.upper().replace(".", "").replace(" ", "")
    m = re.match(r"([HS])(\d+)", normalized)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    return normalized


def extract_sections(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract section references from action text.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Section range string, or None
    """
    sections = data.get("sections")
    if sections:
        return sections.strip()
    # Try to find section references in the full match
    full_text = match.group(0)
    section_pattern = re.compile(
        r"sections? (\d+(?:\s+to\s+\d+)?(?:,\s*(?:inclusive,?\s*)?(?:and\s+)?\d+(?:\s+to\s+\d+)?)*)",
        re.I
    )
    m = section_pattern.search(full_text)
    if m:
        return m.group(1).strip()
    return None


def extract_time_range(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract time range from hearing actions.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Time range string (e.g., "01:00 PM-05:00 PM"), or None
    """
    time_start = data.get("time_start")
    time_end = data.get("time_end")
    if time_start and time_end:
        return f"{time_start}-{time_end}"
    if time_start:
        return time_start
    return None


def extract_location(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract hearing location.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Location string, or None
    """
    location = data.get("location")
    if location:
        return location.strip()
    return None


def extract_legislator_name(
    match: re.Match, data: dict[str, Any]
) -> Optional[str]:
    """Extract legislator name from actions (e.g., amendments).

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Legislator name, or None
    """
    legislator = data.get("legislator")
    if legislator:
        return legislator.strip()
    return None


def extract_vote_counts(
    match: re.Match, data: dict[str, Any]
) -> Optional[dict[str, int]]:
    """Extract vote counts from action text.

    Args:
        match: Regex match object
        data: Dictionary of already-extracted data

    Returns:
        Dictionary with 'yeas' and 'nays' counts, or None
    """
    yes_votes = data.get("yes_votes")
    no_votes = data.get("no_votes")
    if yes_votes and no_votes:
        try:
            return {
                "yeas": int(yes_votes),
                "nays": int(no_votes),
            }
        except ValueError:
            pass
    return None
