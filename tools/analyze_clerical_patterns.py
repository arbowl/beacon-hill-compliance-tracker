"""Analyze reviewed cases to identify clerical patterns.

This tool reads completed reviews and identifies patterns where cases
are consistently marked as clerical. It generates whitelist patterns
that can be used to auto-classify similar future cases.
"""

import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from components.suspicious_notices import ClericalPattern

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_reviews(review_path: str) -> list[dict]:
    """Load completed reviews from JSONL file.
    
    Args:
        review_path: Path to completed_reviews.jsonl
    
    Returns:
        List of review records
    """
    reviews = []
    path = Path(review_path)
    
    if not path.exists():
        logger.warning(f"Review file not found: {review_path}")
        return reviews
    
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    reviews.append(json.loads(line))
                except Exception as e:
                    logger.error(f"Failed to parse review line: {e}")
    
    logger.info(f"Loaded {len(reviews)} reviews")
    return reviews


def apply_reviews_to_dataset(
    dataset_path: str,
    reviews: list[dict]
) -> dict:
    """Apply review decisions to the aggregated dataset.
    
    Args:
        dataset_path: Path to pending_notices.json
        reviews: List of review records
    
    Returns:
        Updated dataset
    """
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    
    # Create lookup by bill_id
    review_lookup = {r["bill_id"]: r for r in reviews}
    
    # Apply reviews to cases
    for group in dataset.get("signature_groups", []):
        for case in group.get("cases", []):
            bill_id = case["bill_id"]
            if bill_id in review_lookup:
                review = review_lookup[bill_id]
                case["review_status"]["reviewed"] = True
                case["review_status"]["determination"] = review["determination"]
                case["review_status"]["reviewer_notes"] = review.get("notes", "")
    
    return dataset


def analyze_patterns(
    dataset: dict,
    min_sample_size: int = 5,
    min_confidence: float = 0.85,
) -> list[ClericalPattern]:
    """Analyze reviewed cases to identify clerical patterns.
    
    Args:
        dataset: Dataset with reviewed cases
        min_sample_size: Minimum number of reviewed cases to consider a pattern
        min_confidence: Minimum confidence threshold (0.0-1.0)
    
    Returns:
        List of identified clerical patterns
    """
    patterns = []
    pattern_id_counter = 1
    
    for group in dataset.get("signature_groups", []):
        # Count reviews in this group
        reviewed_cases = [
            c for c in group["cases"]
            if c["review_status"]["reviewed"]
        ]
        
        if len(reviewed_cases) < min_sample_size:
            continue
        
        # Count determinations
        clerical_count = len([
            c for c in reviewed_cases
            if c["review_status"]["determination"] == "clerical"
        ])
        violation_count = len([
            c for c in reviewed_cases
            if c["review_status"]["determination"] == "violation"
        ])
        
        # Calculate confidence
        confidence = clerical_count / len(reviewed_cases)
        
        if confidence < min_confidence:
            continue
        
        # This is a strong clerical pattern!
        logger.info(
            f"Found clerical pattern: {group['pattern_description']} "
            f"({confidence:.1%} confident, n={len(reviewed_cases)})"
        )
        
        # Extract criteria from characteristics
        chars = group["characteristics"]
        criteria = {}
        
        # Notice days range
        notice_days = group.get("notice_days", 0)
        if chars.get("is_retroactive"):
            # Allow range for retroactive (e.g., -2 to 0)
            criteria["notice_days"] = {"min": notice_days - 1, "max": 0}
        else:
            criteria["notice_days"] = {"min": 0, "max": notice_days + 1}
        
        # Action type
        if chars.get("action_type"):
            criteria["action_type"] = [chars["action_type"]]
        
        # Prior valid notice requirement
        if chars.get("had_prior_valid_notice"):
            criteria["had_prior_valid_notice"] = True
            if chars.get("prior_notice_days"):
                # Require at least this much prior notice
                criteria["prior_notice_days"] = {"min": max(10, chars["prior_notice_days"] - 2)}
        
        # Time change indicator
        if chars.get("had_same_day_time_change"):
            criteria["had_same_day_time_change"] = True
        
        # Virtual option
        if chars.get("text_contains_virtual"):
            criteria["text_contains_virtual"] = True
        
        # Time-related text
        if chars.get("text_contains_time"):
            criteria["text_contains_time"] = True
        
        # Temporal constraints for retroactive
        if chars.get("is_retroactive"):
            # Only allow retroactive within a few days
            criteria["time_between_hearing_and_action"] = {"min": 0, "max": 3}
        
        # Collect example bills
        example_bills = [c["bill_id"] for c in reviewed_cases[:5]]
        
        # Collect reviewer notes for description
        notes = [
            c["review_status"]["reviewer_notes"]
            for c in reviewed_cases
            if c["review_status"]["reviewer_notes"]
        ]
        combined_notes = " | ".join(notes[:3]) if notes else ""
        
        pattern = ClericalPattern(
            id=f"pattern_{pattern_id_counter:03d}",
            name=group["pattern_description"],
            confidence=confidence,
            sample_size=len(reviewed_cases),
            enabled=True,
            criteria=criteria,
            description=_generate_description(group, chars),
            reviewer_notes=combined_notes,
            example_bills=example_bills,
        )
        
        patterns.append(pattern)
        pattern_id_counter += 1
    
    logger.info(f"Identified {len(patterns)} clerical patterns")
    return patterns


def _generate_description(group: dict, chars: dict) -> str:
    """Generate a human-readable description of a pattern."""
    parts = []
    
    # Base description
    parts.append(f"Hearing {chars['action_type'].lower().replace('_', ' ')}")
    
    # Notice context
    if chars.get("had_prior_valid_notice"):
        prior_days = chars.get("prior_notice_days", "10+")
        parts.append(f"with prior valid notice ({prior_days} days)")
    
    # Characteristics
    if chars.get("is_retroactive"):
        parts.append("recorded retroactively (after hearing occurred)")
    elif chars.get("is_same_day"):
        parts.append("announced same day as hearing")
    
    if chars.get("had_same_day_time_change"):
        parts.append("with same-day time change")
    
    if chars.get("text_contains_virtual"):
        parts.append("adding virtual option")
    
    # Pattern explanation
    parts.append(
        "Consistently classified as clerical correction rather than violation "
        "based on domain expert review."
    )
    
    return ". ".join(parts) + "."


def save_patterns(
    patterns: list[ClericalPattern],
    output_path: str = "config/clerical_patterns.json",
    merge_with_existing: bool = True,
) -> None:
    """Save clerical patterns to configuration file.
    
    Args:
        patterns: List of patterns to save
        output_path: Path to save patterns
        merge_with_existing: If True, merge with existing patterns
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    existing_patterns = []
    if merge_with_existing and output_file.exists():
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                existing_config = json.load(f)
            existing_patterns = [
                ClericalPattern.from_dict(p)
                for p in existing_config.get("patterns", [])
            ]
            logger.info(f"Loaded {len(existing_patterns)} existing patterns")
        except Exception as e:
            logger.error(f"Failed to load existing patterns: {e}")
    
    # Merge patterns (prefer new over existing by ID)
    pattern_map = {p.id: p for p in existing_patterns}
    for pattern in patterns:
        pattern_map[pattern.id] = pattern
    
    all_patterns = sorted(
        pattern_map.values(),
        key=lambda p: (p.confidence, p.sample_size),
        reverse=True
    )
    
    # Build config structure
    config = {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "patterns": [p.to_dict() for p in all_patterns],
        "application_rules": {
            "minimum_confidence": 0.85,
            "require_prior_valid_notice": True,
            "max_retroactive_days": 7,
            "human_review_threshold": 0.75,
        }
    }
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    
    logger.info(f"Saved {len(all_patterns)} patterns to {output_path}")


def print_patterns_summary(patterns: list[ClericalPattern]) -> None:
    """Print a summary of identified patterns."""
    print("\n" + "="*70)
    print("IDENTIFIED CLERICAL PATTERNS")
    print("="*70)
    print(f"Total patterns: {len(patterns)}\n")
    
    for i, pattern in enumerate(patterns, 1):
        print(f"{i}. {pattern.name}")
        print(f"   ID: {pattern.id}")
        print(f"   Confidence: {pattern.confidence:.1%} (n={pattern.sample_size})")
        print(f"   Status: {'Enabled' if pattern.enabled else 'Disabled'}")
        print(f"   Examples: {', '.join(pattern.example_bills[:3])}")
        if pattern.reviewer_notes:
            notes_preview = pattern.reviewer_notes[:100]
            if len(pattern.reviewer_notes) > 100:
                notes_preview += "..."
            print(f"   Notes: {notes_preview}")
        print()
    
    print("="*70 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Analyze reviews to identify clerical patterns"
    )
    parser.add_argument(
        "--dataset",
        default="review/pending_notices.json",
        help="Path to aggregated dataset (default: review/pending_notices.json)"
    )
    parser.add_argument(
        "--reviews",
        default="review/completed_reviews.jsonl",
        help="Path to completed reviews (default: review/completed_reviews.jsonl)"
    )
    parser.add_argument(
        "--output",
        default="config/clerical_patterns.json",
        help="Path to save patterns (default: config/clerical_patterns.json)"
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.85,
        help="Minimum confidence threshold (default: 0.85)"
    )
    parser.add_argument(
        "--min-sample-size",
        type=int,
        default=5,
        help="Minimum sample size for pattern (default: 5)"
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Don't merge with existing patterns (replace)"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary of identified patterns"
    )
    
    args = parser.parse_args()
    
    try:
        # Load reviews
        reviews = load_reviews(args.reviews)
        
        if not reviews:
            logger.error("No reviews found. Complete some reviews first.")
            return 1
        
        # Apply reviews to dataset
        dataset = apply_reviews_to_dataset(args.dataset, reviews)
        
        # Analyze patterns
        patterns = analyze_patterns(
            dataset,
            min_sample_size=args.min_sample_size,
            min_confidence=args.min_confidence,
        )
        
        if not patterns:
            logger.warning("No patterns met the criteria")
            return 0
        
        # Save patterns
        save_patterns(
            patterns,
            output_path=args.output,
            merge_with_existing=not args.no_merge,
        )
        
        if args.summary:
            print_patterns_summary(patterns)
        
        logger.info("Pattern analysis complete!")
        return 0
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

