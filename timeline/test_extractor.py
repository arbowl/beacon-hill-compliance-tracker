"""Command-line test tool for timeline extraction.

This tool allows you to test the timeline extraction system on real bill URLs
and see the results in a formatted, human-readable output.

Usage:
    python -m timeline.test_extractor "https://malegislature.gov/Bills/194/H56"
    python -m timeline.test_extractor H56 --session 194
    python -m timeline.test_extractor --help
"""

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from timeline.parser import extract_timeline
from timeline.models import BillAction, BillActionTimeline
from timeline.normalizers import get_committee_name


def format_extracted_data(data: dict) -> str:
    """Format extracted data dictionary for display.
    
    Args:
        data: Dictionary of extracted fields
        
    Returns:
        Formatted string
    """
    if not data:
        return "[No extracted data]"
    
    lines = []
    for key, value in data.items():
        if value is None:
            continue
        
        # Format special fields
        if key == "committee_id":
            committee_name = get_committee_name(value)
            if committee_name:
                lines.append(f"Committee: {value} ({committee_name})")
            else:
                lines.append(f"Committee: {value}")
        elif key == "committee_name":
            # Skip if we already have committee_id
            if "committee_id" not in data:
                lines.append(f"Committee: {value} (not normalized)")
        elif key == "sections":
            lines.append(f"Sections: {value}")
        elif key == "hearing_date":
            lines.append(f"Hearing date: {value}")
        elif key == "time_range":
            lines.append(f"Time: {value}")
        elif key == "location":
            lines.append(f"Location: {value}")
        elif key == "new_deadline":
            lines.append(f"New deadline: {value}")
        elif key == "related_bill":
            lines.append(f"Related bill: {value}")
        elif key == "legislator":
            lines.append(f"Legislator: {value}")
        else:
            lines.append(f"{key}: {value}")
    
    if not lines:
        return "[No extracted data]"
    
    return "\n              │                     │ ".join(lines)


def print_timeline_table(timeline: BillActionTimeline) -> None:
    """Print timeline in a formatted table.
    
    Args:
        timeline: BillActionTimeline to display
    """
    if not timeline.actions:
        print("No actions found.")
        return
    
    print("\n" + "=" * 100)
    print(f"Bill Action Timeline - {len(timeline)} actions")
    print("=" * 100)
    
    # Simple table without Unicode box-drawing characters (Windows compatibility)
    print(f"{'Date':<12} | {'Branch':<8} | {'Type':<25} | {'Details':<40}")
    print("-" * 100)
    
    # Table rows
    for action in timeline.actions:
        date_str = action.date.strftime("%m/%d/%Y")
        branch = action.branch[:8]
        action_type = action.action_type[:25]
        
        # Format details
        details = format_extracted_data(action.extracted_data)
        confidence_str = f"Conf: {action.confidence:.2f}"
        
        # First line
        first_detail = details.split("\n")[0] if details else ""
        print(f"{date_str:<12} | {branch:<8} | {action_type:<25} | {first_detail[:40]}")
        
        # Additional detail lines
        detail_lines = details.split("\n")
        if len(detail_lines) > 1:
            for line in detail_lines[1:]:
                print(f"{'':12} | {'':8} | {'':25} | {line[:40]}")
        
        # Confidence line
        print(f"{'':12} | {'':8} | {'':25} | {confidence_str}")
        print("-" * 100)


def print_timeline_queries(timeline: BillActionTimeline, committee_id: Optional[str] = None) -> None:
    """Print results of common timeline queries.
    
    Args:
        timeline: BillActionTimeline to query
        committee_id: Optional committee ID to query for
    """
    print("\n" + "=" * 100)
    print("Timeline Queries")
    print("=" * 100)
    
    if committee_id:
        print(f"\nCommittee: {committee_id}")
        
        referred_date = timeline.get_referred_date(committee_id)
        print(f"  Referred date: {referred_date or 'Not found'}")
        
        reported_date = timeline.get_reported_date(committee_id)
        print(f"  Reported date: {reported_date or 'Not found'}")
        
        hearings = timeline.get_hearings(committee_id)
        if hearings:
            print(f"  Hearings: {len(hearings)}")
            for hearing in hearings:
                hearing_date = hearing.extracted_data.get("hearing_date")
                print(f"    - {hearing.action_type}: {hearing_date} ({hearing.date})")
        else:
            print("  Hearings: None found")
    
    # General queries
    extension_date = timeline.get_latest_deadline_extension()
    print(f"\nLatest extension deadline: {extension_date or 'None'}")
    
    unknown_actions = timeline.get_unknown_actions()
    print(f"Unknown actions: {len(unknown_actions)}")
    
    if unknown_actions:
        print("\nUnknown action types (need pattern definitions):")
        for action in unknown_actions[:5]:  # Show first 5
            print(f"  [{action.date}] {action.branch}: {action.raw_text[:60]}...")


def print_raw_actions(timeline: BillActionTimeline, max_actions: int = 5) -> None:
    """Print raw action text for debugging.
    
    Args:
        timeline: BillActionTimeline to display
        max_actions: Maximum number of actions to show
    """
    print("\n" + "=" * 100)
    print(f"Raw Action Text (showing first {max_actions} actions)")
    print("=" * 100)
    
    for i, action in enumerate(timeline.actions[:max_actions]):
        print(f"\n[{action.date}] {action.branch} - {action.action_type}")
        print("-" * 100)
        print(action.raw_text)
        if action.extracted_data:
            print(f"Extracted data: {action.extracted_data}")
        print(f"Confidence: {action.confidence}")
        print("-" * 100)


def build_bill_url(bill_id: str, session: str = "194") -> str:
    """Build bill URL from bill ID.
    
    Args:
        bill_id: Bill identifier (e.g., "H56", "S197")
        session: Session number
        
    Returns:
        Full bill URL
    """
    base_url = "https://malegislature.gov"
    return f"{base_url}/Bills/{session}/{bill_id}"


def main():
    """Main entry point for test tool."""
    parser = argparse.ArgumentParser(
        description="Test timeline extraction on Massachusetts Legislature bills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with full URL
  python -m timeline.test_extractor "https://malegislature.gov/Bills/194/H56"
  
  # Test with bill ID (assumes session 194)
  python -m timeline.test_extractor H56
  
  # Test with bill ID and custom session
  python -m timeline.test_extractor H56 --session 193
  
  # Query specific committee
  python -m timeline.test_extractor H56 --committee J10
  
  # Show more raw actions
  python -m timeline.test_extractor H56 --raw 10
        """
    )
    
    parser.add_argument(
        "bill",
        help="Bill URL or bill ID (e.g., 'H56', 'S197')"
    )
    parser.add_argument(
        "--session",
        default="194",
        help="Legislative session number (default: 194)"
    )
    parser.add_argument(
        "--committee",
        help="Committee ID to query (e.g., 'J10', 'H33')"
    )
    parser.add_argument(
        "--raw",
        type=int,
        default=5,
        metavar="N",
        help="Show N raw actions for debugging (default: 5)"
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="Skip the formatted table output"
    )
    parser.add_argument(
        "--no-queries",
        action="store_true",
        help="Skip the query examples"
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Skip the raw action text"
    )
    
    args = parser.parse_args()
    
    # Determine if input is URL or bill ID
    if args.bill.startswith("http"):
        bill_url = args.bill
        # Try to extract bill ID from URL
        import re
        match = re.search(r"/Bills/\d+/([HS]\d+)", bill_url)
        bill_id = match.group(1) if match else None
    else:
        bill_id = args.bill.upper()
        bill_url = build_bill_url(bill_id, args.session)
    
    print(f"\nExtracting timeline from: {bill_url}")
    if bill_id:
        print(f"Bill ID: {bill_id}")
    
    try:
        # Extract timeline
        timeline = extract_timeline(bill_url, bill_id)
        
        # Display results
        if not args.no_table:
            print_timeline_table(timeline)
        
        if not args.no_queries:
            print_timeline_queries(timeline, args.committee)
        
        if not args.no_raw:
            print_raw_actions(timeline, args.raw)
        
        # Summary
        print("\n" + "=" * 100)
        print("Summary")
        print("=" * 100)
        print(f"Total actions: {len(timeline)}")
        print(f"Date range: {timeline.actions[0].date} to {timeline.actions[-1].date}")
        print(f"Branches: {', '.join(sorted(set(a.branch for a in timeline.actions)))}")
        print(f"Unknown actions: {len(timeline.get_unknown_actions())}")
        
        # Action type breakdown
        action_types = {}
        for action in timeline.actions:
            action_types[action.action_type] = action_types.get(action.action_type, 0) + 1
        
        print(f"\nAction types:")
        for action_type, count in sorted(action_types.items(), key=lambda x: -x[1]):
            print(f"  {action_type}: {count}")
        
        print("\n" + "=" * 100)
        print("✓ Extraction completed successfully")
        print("=" * 100)
        
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n✗ Error extracting timeline: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

