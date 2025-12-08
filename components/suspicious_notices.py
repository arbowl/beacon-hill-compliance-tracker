"""Data models and utilities for tracking suspicious hearing notices.

This module handles detection, logging, and analysis of same-day and retroactive
hearing reschedules that may be clerical corrections vs. actual violations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class SuspiciousHearingNotice:
    """Record of a hearing notice that may be clerical vs. actual violation.
    
    These cases occur when a hearing is announced with insufficient notice
    (same-day or retroactively), but it's unclear whether this represents:
    - A clerical correction (staff updating records after the fact)
    - An actual compliance violation (genuinely rescheduled without notice)
    """
    
    # Identity
    bill_id: str
    committee_id: str
    session: str
    bill_url: str
    
    # The problematic hearing
    announcement_date: date          # When the action was recorded
    scheduled_hearing_date: date     # When hearing was scheduled for
    notice_days: int                 # Can be 0 or negative
    action_type: str                 # "HEARING_SCHEDULED" or "HEARING_RESCHEDULED"
    raw_action_text: str             # Original text from website
    
    # Context
    all_hearing_actions: list[dict] = field(default_factory=list)
    had_prior_announcement: bool = False
    prior_best_notice_days: Optional[int] = None
    prior_announcement_date: Optional[date] = None
    prior_scheduled_date: Optional[date] = None
    
    # Timeline position
    action_date: date = field(default_factory=date.today)
    hearing_actually_occurred: Optional[bool] = None
    days_between_action_and_hearing: int = 0
    
    # Signature data for pattern matching
    signature: dict = field(default_factory=dict)
    
    # Metadata
    detected_at: datetime = field(default_factory=datetime.now)
    reviewed: bool = False
    is_clerical: Optional[bool] = None
    reviewer_notes: str = ""
    whitelist_pattern_id: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert date/datetime objects to strings
        for key, value in data.items():
            if isinstance(value, (date, datetime)):
                data[key] = value.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SuspiciousHearingNotice:
        """Create from dictionary (deserialize from JSON)."""
        # Convert ISO strings back to date/datetime
        date_fields = [
            'announcement_date', 'scheduled_hearing_date', 'action_date',
            'prior_announcement_date', 'prior_scheduled_date'
        ]
        for field_name in date_fields:
            if field_name in data and data[field_name]:
                if isinstance(data[field_name], str):
                    data[field_name] = date.fromisoformat(data[field_name])
        
        if 'detected_at' in data and isinstance(data['detected_at'], str):
            data['detected_at'] = datetime.fromisoformat(data['detected_at'])
        
        return cls(**data)


@dataclass
class ClericalPattern:
    """A pattern that identifies likely clerical corrections."""
    
    id: str
    name: str
    confidence: float  # 0.0 to 1.0
    sample_size: int
    enabled: bool = True
    
    criteria: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    reviewer_notes: str = ""
    example_bills: list[str] = field(default_factory=list)
    
    def matches(self, signature: dict[str, Any]) -> bool:
        """Check if a case signature matches this pattern."""
        for key, criterion in self.criteria.items():
            if key not in signature:
                return False
            
            value = signature[key]
            
            # Handle different criterion types
            if isinstance(criterion, dict):
                # Range check (e.g., {"min": 10, "max": 20})
                if "min" in criterion and value < criterion["min"]:
                    return False
                if "max" in criterion and value > criterion["max"]:
                    return False
            elif isinstance(criterion, list):
                # Must be in list
                if value not in criterion:
                    return False
            else:
                # Exact match
                if value != criterion:
                    return False
        
        return True
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClericalPattern:
        """Create from dictionary."""
        return cls(**data)


class SuspiciousNoticeLogger:
    """Handles logging of suspicious hearing notices."""
    
    def __init__(self, log_path: str = "out/suspicious_notices.jsonl"):
        """Initialize logger.
        
        Args:
            log_path: Path to JSONL log file
        """
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
    
    def log(self, notice: SuspiciousHearingNotice) -> None:
        """Append a suspicious notice to the log.
        
        Args:
            notice: The suspicious notice to log
        """
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                json.dump(notice.to_dict(), f)
                f.write("\n")
            logger.debug(f"Logged suspicious notice for {notice.bill_id}")
        except Exception as e:
            logger.error(f"Failed to log suspicious notice: {e}")
    
    def load_all(self) -> list[SuspiciousHearingNotice]:
        """Load all logged notices.
        
        Returns:
            List of all suspicious notices from the log
        """
        if not self.log_path.exists():
            return []
        
        notices = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        notices.append(SuspiciousHearingNotice.from_dict(data))
                    except Exception as e:
                        logger.error(f"Failed to parse log line: {e}")
        
        return notices
    
    def clear_log(self) -> None:
        """Clear the log file (use with caution!)."""
        if self.log_path.exists():
            self.log_path.unlink()
            logger.info(f"Cleared suspicious notice log: {self.log_path}")


def compute_signature(notice: SuspiciousHearingNotice) -> dict[str, Any]:
    """Compute pattern signature for a suspicious notice.
    
    The signature captures key characteristics that help identify similar cases
    and enable pattern-based whitelisting.
    
    Args:
        notice: The suspicious notice to analyze
    
    Returns:
        Dictionary of signature characteristics
    """
    def categorize_notice(days: Optional[int]) -> str:
        """Categorize notice days into buckets."""
        if days is None:
            return "unknown"
        if days < -5:
            return "retroactive_6plus_days"
        if days < 0:
            return f"retroactive_{abs(days)}_day{'s' if abs(days) > 1 else ''}"
        if days == 0:
            return "same_day"
        if days < 3:
            return f"{days}_day{'s' if days > 1 else ''}"
        if days < 10:
            return f"{days}_days"
        return "10plus_days"
    
    sig: dict[str, Any] = {
        # Notice characteristics
        "notice_days": notice.notice_days,
        "notice_category": categorize_notice(notice.notice_days),
        
        # Action characteristics
        "action_type": notice.action_type,
        "is_retroactive": notice.notice_days < 0,
        "is_same_day": notice.notice_days == 0,
        
        # Prior context
        "had_prior_valid_notice": notice.had_prior_announcement,
        "prior_notice_category": categorize_notice(notice.prior_best_notice_days) if notice.had_prior_announcement else None,
        "prior_notice_days": notice.prior_best_notice_days,
        
        # Timeline pattern
        "time_between_hearing_and_action": notice.days_between_action_and_hearing,
        "had_same_day_time_change": any(
            a.get("action_type") == "HEARING_TIME_CHANGED" and 
            (a.get("hearing_date") == notice.scheduled_hearing_date.isoformat() if isinstance(notice.scheduled_hearing_date, date) else True)
            for a in notice.all_hearing_actions
        ),
        "total_hearing_actions": len(notice.all_hearing_actions),
        
        # Text patterns
        "text_contains_time": "time" in notice.raw_action_text.lower(),
        "text_contains_virtual": "virtual" in notice.raw_action_text.lower(),
        "text_contains_location": any(word in notice.raw_action_text.lower() for word in ["room", "a-2", "a-1", "gardner"]),
        
        # Committee characteristics
        "committee_id": notice.committee_id,
        "committee_type": notice.committee_id[0] if notice.committee_id else "?",
        
        # Temporal patterns
        "day_of_week_announced": notice.announcement_date.strftime("%A") if notice.announcement_date else None,
        "day_of_week_hearing": notice.scheduled_hearing_date.strftime("%A") if notice.scheduled_hearing_date else None,
        "month": notice.announcement_date.month if notice.announcement_date else None,
    }
    
    # Composite key for grouping
    prior_cat = sig['prior_notice_category'] or "none"
    time_change = "timechange" if sig['had_same_day_time_change'] else "notimechange"
    sig["composite_key"] = f"{sig['notice_category']}_{sig['action_type']}_prior_{prior_cat}_{time_change}"
    
    return sig


def load_clerical_patterns(config_path: str = "config/clerical_patterns.json") -> list[ClericalPattern]:
    """Load clerical patterns from configuration file.
    
    Args:
        config_path: Path to patterns configuration file
    
    Returns:
        List of clerical patterns
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Clerical patterns config not found: {config_path}")
        return []
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        patterns = []
        for pattern_data in config.get("patterns", []):
            patterns.append(ClericalPattern.from_dict(pattern_data))
        
        logger.info(f"Loaded {len(patterns)} clerical patterns")
        return patterns
    except Exception as e:
        logger.error(f"Failed to load clerical patterns: {e}")
        return []


def should_whitelist_as_clerical(
    notice: SuspiciousHearingNotice,
    patterns: Optional[list[ClericalPattern]] = None,
    min_confidence: float = 0.85
) -> tuple[bool, Optional[str]]:
    """Determine if a case matches a known clerical pattern.
    
    Args:
        notice: The suspicious notice to check
        patterns: List of clerical patterns (loads from config if None)
        min_confidence: Minimum confidence threshold for auto-whitelisting
    
    Returns:
        Tuple of (should_whitelist, pattern_id)
    """
    if patterns is None:
        patterns = load_clerical_patterns()
    
    if not patterns:
        return False, None
    
    # Compute signature for this notice
    signature = compute_signature(notice)
    notice.signature = signature  # Store for reference
    
    for pattern in patterns:
        if not pattern.enabled:
            continue
        
        if pattern.matches(signature):
            if pattern.confidence >= min_confidence:
                logger.info(
                    f"Bill {notice.bill_id}: Matched clerical pattern '{pattern.name}' "
                    f"(confidence: {pattern.confidence:.2%})"
                )
                return True, pattern.id
            elif pattern.confidence >= 0.75:
                # Flag for quick human review with suggested determination
                logger.info(
                    f"Bill {notice.bill_id}: Possible clerical pattern '{pattern.name}' "
                    f"(confidence: {pattern.confidence:.2%}, below threshold)"
                )
                return False, f"suggested_clerical:{pattern.id}"
    
    return False, None

