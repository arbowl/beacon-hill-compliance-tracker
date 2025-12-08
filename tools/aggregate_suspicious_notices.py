"""Aggregate suspicious notices into groups for batch review.

This tool reads the suspicious_notices.jsonl log and organizes cases by
their pattern signatures, making it easier for domain experts to review
similar cases together and identify clerical patterns.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional
import sys

# Add parent directory to path to import components
sys.path.insert(0, str(Path(__file__).parent.parent))

from components.suspicious_notices import (
    SuspiciousHearingNotice,
    SuspiciousNoticeLogger,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SignatureGroup:
    """A group of cases with similar signatures."""
    
    def __init__(self, signature_key: str):
        self.signature_key = signature_key
        self.cases: list[SuspiciousHearingNotice] = []
        self.reviewed_count = 0
        self.clerical_count = 0
        self.violation_count = 0
    
    def add_case(self, notice: SuspiciousHearingNotice) -> None:
        """Add a case to this group."""
        self.cases.append(notice)
        if notice.reviewed:
            self.reviewed_count += 1
            if notice.is_clerical is True:
                self.clerical_count += 1
            elif notice.is_clerical is False:
                self.violation_count += 1
    
    @property
    def confidence_score(self) -> Optional[float]:
        """Calculate confidence that this pattern is clerical."""
        if self.reviewed_count == 0:
            return None
        return self.clerical_count / self.reviewed_count
    
    @property
    def pattern_description(self) -> str:
        """Generate a human-readable pattern description."""
        if not self.cases:
            return "Unknown pattern"
        
        # Use the first case's signature to describe the pattern
        sig = self.cases[0].signature
        
        desc_parts = []
        
        # Notice category
        notice_cat = sig.get("notice_category", "unknown")
        desc_parts.append(notice_cat.replace("_", " ").title())
        
        # Action type
        action = sig.get("action_type", "")
        if "RESCHEDULED" in action:
            desc_parts.append("rescheduled")
        elif "SCHEDULED" in action:
            desc_parts.append("scheduled")
        
        # Prior notice context
        if sig.get("had_prior_valid_notice"):
            prior_days = sig.get("prior_notice_days")
            if prior_days:
                desc_parts.append(f"(had prior {prior_days}-day notice)")
        
        # Time change indicator
        if sig.get("had_same_day_time_change"):
            desc_parts.append("+ same-day time change")
        
        return " ".join(desc_parts)
    
    @property
    def characteristics(self) -> dict:
        """Extract common characteristics from the group."""
        if not self.cases:
            return {}
        
        # Use first case's signature as representative
        sig = self.cases[0].signature
        
        return {
            "is_retroactive": sig.get("is_retroactive", False),
            "is_same_day": sig.get("is_same_day", False),
            "had_prior_valid_notice": sig.get("had_prior_valid_notice", False),
            "action_type": sig.get("action_type", ""),
            "notice_days": sig.get("notice_days", 0),
            "prior_notice_days": sig.get("prior_notice_days"),
            "had_same_day_time_change": sig.get("had_same_day_time_change", False),
            "text_contains_time": sig.get("text_contains_time", False),
            "text_contains_virtual": sig.get("text_contains_virtual", False),
        }
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON export."""
        return {
            "signature_id": self.signature_key,
            "pattern_description": self.pattern_description,
            "notice_days": self.cases[0].notice_days if self.cases else None,
            "characteristics": self.characteristics,
            "case_count": len(self.cases),
            "reviewed_count": self.reviewed_count,
            "clerical_count": self.clerical_count,
            "violation_count": self.violation_count,
            "confidence_score": self.confidence_score,
            "cases": [self._case_to_dict(c) for c in self.cases]
        }
    
    def _case_to_dict(self, notice: SuspiciousHearingNotice) -> dict:
        """Convert a case to dictionary with relevant fields."""
        result = {
            "bill_id": notice.bill_id,
            "committee_id": notice.committee_id,
            "committee_name": f"{notice.committee_id}",  # Could enhance with lookup
            "bill_url": notice.bill_url,
            "problematic_hearing": {
                "announcement_date": notice.announcement_date.isoformat(),
                "scheduled_hearing_date": notice.scheduled_hearing_date.isoformat(),
                "notice_days": notice.notice_days,
                "action_type": notice.action_type,
                "raw_text": notice.raw_action_text,
            },
            "timeline_summary": {
                "total_hearing_actions": len(notice.all_hearing_actions),
                "action_sequence": notice.all_hearing_actions,
            },
            "review_status": {
                "reviewed": notice.reviewed,
                "determination": "clerical" if notice.is_clerical is True else (
                    "violation" if notice.is_clerical is False else "pending"
                ),
                "reviewer_notes": notice.reviewer_notes,
            },
            "computed_signature": notice.signature.get("composite_key", "unknown"),
        }
        
        # Add prior announcement if exists
        if notice.had_prior_announcement and notice.prior_announcement_date:
            result["prior_announcement"] = {
                "announcement_date": notice.prior_announcement_date.isoformat(),
                "scheduled_hearing_date": notice.prior_scheduled_date.isoformat() if notice.prior_scheduled_date else None,
                "notice_days": notice.prior_best_notice_days,
                "action_type": "HEARING_SCHEDULED",  # Assumption
            }
        
        # Add evidence
        result["evidence"] = {
            "time_changed": notice.signature.get("had_same_day_time_change", False),
            "text_contains_virtual": notice.signature.get("text_contains_virtual", False),
        }
        
        # Add whitelist info if applicable
        if notice.whitelist_pattern_id:
            result["whitelist_pattern_id"] = notice.whitelist_pattern_id
        
        return result


def aggregate_notices(
    log_path: str = "out/suspicious_notices.jsonl",
    output_path: str = "review/pending_notices.json",
) -> dict:
    """Aggregate suspicious notices by signature for review.
    
    Args:
        log_path: Path to the suspicious notices log
        output_path: Path to save the aggregated review dataset
    
    Returns:
        Dictionary with aggregated data
    """
    logger.info(f"Loading suspicious notices from {log_path}")
    
    # Load all notices
    notice_logger = SuspiciousNoticeLogger(log_path)
    all_notices = notice_logger.load_all()
    
    if not all_notices:
        logger.warning("No suspicious notices found")
        return {
            "metadata": {
                "generated_at": datetime.now().isoformat(),
                "total_cases": 0,
                "signature_groups": 0,
            },
            "signature_groups": [],
            "outliers": [],
        }
    
    logger.info(f"Loaded {len(all_notices)} notices")
    
    # Group by signature
    groups: dict[str, SignatureGroup] = defaultdict(lambda: SignatureGroup(""))
    
    for notice in all_notices:
        composite_key = notice.signature.get("composite_key", "unknown")
        if composite_key not in groups:
            groups[composite_key] = SignatureGroup(composite_key)
        groups[composite_key].add_case(notice)
    
    logger.info(f"Organized into {len(groups)} signature groups")
    
    # Sort groups by case count (most common first)
    sorted_groups = sorted(
        groups.values(),
        key=lambda g: (g.case_count, g.reviewed_count),
        reverse=True
    )
    
    # Identify outliers (groups with only 1-2 cases)
    regular_groups = [g for g in sorted_groups if len(g.cases) > 2]
    outlier_groups = [g for g in sorted_groups if len(g.cases) <= 2]
    
    # Collect statistics
    sessions = set(n.session for n in all_notices)
    committees = set(n.committee_id for n in all_notices)
    total_reviewed = sum(n.reviewed for n in all_notices)
    
    # Build output structure
    result = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "total_cases": len(all_notices),
            "signature_groups": len(regular_groups),
            "outlier_groups": len(outlier_groups),
            "sessions_covered": sorted(sessions),
            "committees_affected": sorted(committees),
            "unreviewed_count": len(all_notices) - total_reviewed,
            "reviewed_count": total_reviewed,
        },
        "signature_groups": [g.to_dict() for g in regular_groups],
        "outliers": [
            case
            for group in outlier_groups
            for case in [group._case_to_dict(c) for c in group.cases]
        ],
    }
    
    # Save to file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    
    logger.info(f"Saved aggregated dataset to {output_path}")
    logger.info(f"  - {len(regular_groups)} signature groups")
    logger.info(f"  - {len(outlier_groups)} outlier groups")
    logger.info(f"  - {total_reviewed}/{len(all_notices)} cases reviewed")
    
    return result


def print_summary(data: dict) -> None:
    """Print a summary of the aggregated data."""
    meta = data["metadata"]
    
    print("\n" + "="*70)
    print("SUSPICIOUS HEARING NOTICES SUMMARY")
    print("="*70)
    print(f"Generated: {meta['generated_at']}")
    print(f"Total cases: {meta['total_cases']}")
    print(f"Reviewed: {meta['reviewed_count']} ({meta['reviewed_count']/meta['total_cases']*100:.1f}%)")
    print(f"Pending review: {meta['unreviewed_count']}")
    print(f"\nSignature groups: {meta['signature_groups']}")
    print(f"Outlier cases: {len(data['outliers'])}")
    print(f"\nSessions: {', '.join(meta['sessions_covered'])}")
    print(f"Committees: {', '.join(meta['committees_affected'][:5])}", end="")
    if len(meta['committees_affected']) > 5:
        print(f" + {len(meta['committees_affected']) - 5} more")
    else:
        print()
    
    print("\n" + "-"*70)
    print("TOP 5 MOST COMMON PATTERNS:")
    print("-"*70)
    
    for i, group in enumerate(data["signature_groups"][:5], 1):
        conf = group.get("confidence_score")
        conf_str = f"{conf:.1%}" if conf is not None else "N/A"
        print(f"{i}. {group['pattern_description']}")
        print(f"   Cases: {group['case_count']} | "
              f"Reviewed: {group['reviewed_count']} | "
              f"Confidence: {conf_str}")
        if group['reviewed_count'] > 0:
            print(f"   Determinations: {group['clerical_count']} clerical, "
                  f"{group['violation_count']} violation")
        print()
    
    print("="*70 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Aggregate suspicious hearing notices for review"
    )
    parser.add_argument(
        "--log",
        default="out/suspicious_notices.jsonl",
        help="Path to suspicious notices log (default: out/suspicious_notices.jsonl)"
    )
    parser.add_argument(
        "--output",
        default="review/pending_notices.json",
        help="Path to save aggregated dataset (default: review/pending_notices.json)"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary after aggregation"
    )
    
    args = parser.parse_args()
    
    try:
        result = aggregate_notices(args.log, args.output)
        
        if args.summary or not args.output:
            print_summary(result)
        
        return 0
    except Exception as e:
        logger.error(f"Failed to aggregate notices: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

