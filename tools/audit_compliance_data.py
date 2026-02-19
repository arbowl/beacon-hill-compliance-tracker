#!/usr/bin/env python3
"""
Compliance Data Audit Tool

This tool simulates the dashboard's compliance calculations on JSON files
before they are ingested into production. It helps audit data to catch
unexpected changes in compliance rates or bill counts.

Usage:
    python audit_compliance_data.py

The tool will:
1. Read all JSON files from the OUTPUT_FOLDER
2. Calculate global statistics (same logic as backend)
3. Provide an interactive prompt to view individual committee stats
"""

import json
import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Tuple

# Fix Windows console encoding for emoji support
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        # Python < 3.7
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")


# ============================================================================
# CONFIGURATION
# ============================================================================

# Folder containing JSON files in "basic" format (not cache format)
# Each file should be named like: committee_id.json
# Format: {"committee_id": "XXX", "bills": [...]}
OUTPUT_FOLDER = "../out/2026/02/18/"


# ============================================================================
# DATA LOADING
# ============================================================================


def load_committee_data(folder_path: str) -> Dict[str, Dict[str, Any]]:
    """
    Load all committee JSON files from the specified folder.

    Returns:
        Dictionary mapping committee_id to committee data
    """
    folder = Path(folder_path)
    if not folder.exists():
        print(f"❌ Error: Folder '{folder_path}' does not exist")
        print(f"   Please create it and add JSON files in the format:")
        print(f"   {{'committee_id': 'XXX', 'bills': [...]}}")
        return {}

    committee_data = {}
    json_files = list(folder.glob("*.json"))

    if not json_files:
        print(f"⚠️  Warning: No JSON files found in '{folder_path}'")
        return {}

    print(f"📂 Loading data from '{folder_path}'...")
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate structure
            if not isinstance(data, dict):
                print(f"⚠️  Skipping {json_file.name}: Not a JSON object")
                continue

            committee_id = json_file.name.split("_")[1].replace(".json", "")
            bills = data.get("bills", [])

            if not committee_id:
                print(f"⚠️  Skipping {json_file.name}: Missing 'committee_id'")
                continue

            if not isinstance(bills, list):
                print(f"⚠️  Skipping {json_file.name}: 'bills' is not an array")
                continue

            committee_data[committee_id] = data
            print(f"   ✓ Loaded {committee_id}: {len(bills)} bills")

        except json.JSONDecodeError as e:
            print(f"⚠️  Skipping {json_file.name}: Invalid JSON - {e}")
        except Exception as e:
            print(f"⚠️  Skipping {json_file.name}: Error - {e}")

    print(f"✅ Loaded {len(committee_data)} committees\n")
    return committee_data


# ============================================================================
# STATISTICS CALCULATION (mirrors backend logic)
# ============================================================================


def deduplicate_bills(
    committee_data: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Deduplicate bills by (bill_id, committee_id), keeping the most recent entry.
    This mirrors the backend's ROW_NUMBER() OVER (PARTITION BY bill_id, committee_id) logic.

    Since we're working with files (not time-series database), we assume each file
    represents the latest state for that committee.
    """
    deduplicated = []

    for committee_id, data in committee_data.items():
        bills = data.get("bills", [])
        # Track bills we've seen for this committee (dedup within committee)
        seen_bills = {}

        for bill in bills:
            bill_id = bill.get("bill_id")
            if not bill_id:
                continue

            # Create a key for deduplication
            key = (bill_id, committee_id)

            # For file-based audit, we just take the bill as-is
            # (assuming file contains latest state)
            if key not in seen_bills:
                # Add committee_id to bill for tracking
                bill_copy = bill.copy()
                bill_copy["committee_id"] = committee_id
                seen_bills[key] = bill_copy

        deduplicated.extend(seen_bills.values())

    return deduplicated


def calculate_global_stats(committee_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate global statistics across all committees.
    Mirrors the backend's _calculate_stats_from_db() function.
    """
    # Deduplicate bills
    all_bills = deduplicate_bills(committee_data)

    # Count bills by state
    total_committees = len(committee_data)
    total_bills = len(all_bills)
    compliant_bills = 0
    incomplete_bills = 0
    non_compliant_bills = 0
    unknown_bills = 0

    for bill in all_bills:
        state = bill.get("state", "Unknown").lower()

        if state == "compliant":
            compliant_bills += 1
        elif state == "incomplete":
            incomplete_bills += 1
        elif state == "non-compliant":
            non_compliant_bills += 1
        elif state in ("unknown", ""):
            unknown_bills += 1
        else:
            # Unknown state variant
            unknown_bills += 1

    # Backend merges incomplete into non_compliant
    actual_non_compliant = non_compliant_bills + incomplete_bills

    # Calculate compliance rate: (compliant + unknown) / total * 100
    if total_bills > 0:
        overall_compliance_rate = round(
            ((compliant_bills + unknown_bills) / total_bills) * 100, 2
        )
    else:
        overall_compliance_rate = 0

    return {
        "total_committees": total_committees,
        "total_bills": total_bills,
        "compliant_bills": compliant_bills,
        "incomplete_bills": 0,  # Backend always returns 0 (merged into non_compliant)
        "non_compliant_bills": actual_non_compliant,
        "unknown_bills": unknown_bills,
        "overall_compliance_rate": overall_compliance_rate,
    }


def calculate_committee_stats(
    committee_id: str, bills: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Calculate statistics for a specific committee.
    """
    total_bills = len(bills)
    compliant_bills = 0
    incomplete_bills = 0
    non_compliant_bills = 0
    unknown_bills = 0

    for bill in bills:
        state = bill.get("state", "Unknown").lower()

        if state == "compliant":
            compliant_bills += 1
        elif state == "incomplete":
            incomplete_bills += 1
        elif state == "non-compliant":
            non_compliant_bills += 1
        elif state in ("unknown", ""):
            unknown_bills += 1
        else:
            unknown_bills += 1

    # Backend merges incomplete into non_compliant
    actual_non_compliant = non_compliant_bills + incomplete_bills

    # Calculate compliance rate
    if total_bills > 0:
        compliance_rate = round(
            ((compliant_bills + unknown_bills) / total_bills) * 100, 2
        )
    else:
        compliance_rate = 0

    return {
        "committee_id": committee_id,
        "total_bills": total_bills,
        "compliant_bills": compliant_bills,
        "non_compliant_bills": actual_non_compliant,
        "unknown_bills": unknown_bills,
        "overall_compliance_rate": compliance_rate,
    }


# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================


def display_global_stats(stats: Dict[str, Any]):
    """Display global statistics in a dashboard-like format."""
    print("=" * 80)
    print("📊 GLOBAL STATISTICS (All Committees)")
    print("=" * 80)
    print(f"Total Committees:      {stats['total_committees']}")
    print(f"Total Bills:           {stats['total_bills']}")
    print(
        f"├─ ✅ Compliant:        {stats['compliant_bills']} ({_percentage(stats['compliant_bills'], stats['total_bills'])}%)"
    )
    print(
        f"├─ ❌ Non-Compliant:    {stats['non_compliant_bills']} ({_percentage(stats['non_compliant_bills'], stats['total_bills'])}%)"
    )
    print(
        f"└─ ❓ Unknown:          {stats['unknown_bills']} ({_percentage(stats['unknown_bills'], stats['total_bills'])}%)"
    )
    print()
    print(f"📈 Overall Compliance Rate: {stats['overall_compliance_rate']}%")
    print(f"   (Includes Compliant + Unknown bills)")
    print("=" * 80)
    print()


def display_committee_stats(
    committee_id: str, stats: Dict[str, Any], committee_name: str = None
):
    """Display committee statistics in a dashboard-like format."""
    title = committee_name or committee_id
    print("=" * 80)
    print(f"📋 COMMITTEE: {title}")
    print("=" * 80)
    print(f"Total Bills:           {stats['total_bills']}")
    print(
        f"├─ ✅ Compliant:        {stats['compliant_bills']} ({_percentage(stats['compliant_bills'], stats['total_bills'])}%)"
    )
    print(
        f"├─ ❌ Non-Compliant:    {stats['non_compliant_bills']} ({_percentage(stats['non_compliant_bills'], stats['total_bills'])}%)"
    )
    print(
        f"└─ ❓ Unknown:          {stats['unknown_bills']} ({_percentage(stats['unknown_bills'], stats['total_bills'])}%)"
    )
    print()
    print(f"📈 Compliance Rate: {stats['overall_compliance_rate']}%")
    print("=" * 80)
    print()


def display_bill_details(bills: List[Dict[str, Any]], show_limit: int = 999):
    """Display detailed bill information."""
    if not bills:
        print("No bills to display.\n")
        return

    print(
        f"📄 Bill Details (showing first {min(show_limit, len(bills))} of {len(bills)}):"
    )
    print("-" * 80)

    for i, bill in enumerate(bills[:show_limit], 1):
        state = bill.get("state", "Unknown")
        state_icon = {
            "compliant": "✅",
            "non-compliant": "❌",
            "incomplete": "⚠️",
            "unknown": "❓",
        }.get(state.lower(), "❓")

        print(f"{i}. {state_icon} {bill.get('bill_id', 'N/A')} - {state}")
        print(f"   Title: {bill.get('bill_title', 'N/A')[:70]}...")
        print(
            f"   Hearing: {bill.get('hearing_date', 'N/A')} | Deadline: {bill.get('effective_deadline', 'N/A')}"
        )
        print(
            f"   Reported Out: {'Yes' if bill.get('reported_out') else 'No'} | "
            f"Summary: {'Yes' if bill.get('summary_present') else 'No'} | "
            f"Votes: {'Yes' if bill.get('votes_present') else 'No'}"
        )
        if bill.get("reason"):
            print(f"   Reason: {bill.get('reason')[:70]}...")
        print()

    if len(bills) > show_limit:
        print(f"... and {len(bills) - show_limit} more bills")
        print()


def _percentage(numerator: int, denominator: int) -> str:
    """Calculate percentage and return as formatted string."""
    if denominator == 0:
        return "0.00"
    return f"{(numerator / denominator * 100):.2f}"


# ============================================================================
# INTERACTIVE MENU
# ============================================================================


def interactive_menu(
    committee_data: Dict[str, Dict[str, Any]], global_stats: Dict[str, Any]
):
    """
    Interactive menu to explore committee statistics.
    """
    while True:
        print("\n" + "=" * 80)
        print("🔍 AUDIT MENU")
        print("=" * 80)
        print("1. Show Global Statistics")
        print("2. Show Committee Statistics")
        print("3. List All Committees")
        print("4. Show Bill Details for a Committee")
        print("5. Compare Before/After (if you have reference data)")
        print("0. Exit")
        print("=" * 80)

        choice = input("Select an option: ").strip()

        if choice == "0":
            print("\n👋 Goodbye!")
            break

        elif choice == "1":
            display_global_stats(global_stats)

        elif choice == "2":
            committee_id = input("Enter committee ID (e.g., J1): ").strip()
            if committee_id in committee_data:
                bills = committee_data[committee_id].get("bills", [])
                stats = calculate_committee_stats(committee_id, bills)
                display_committee_stats(committee_id, stats)
            else:
                print(f"❌ Committee '{committee_id}' not found.\n")

        elif choice == "3":
            print("\n📋 All Committees:")
            print("-" * 80)
            for i, (committee_id, data) in enumerate(sorted(committee_data.items()), 1):
                bills = data.get("bills", [])
                stats = calculate_committee_stats(committee_id, bills)
                print(
                    f"{i}. {committee_id}: {stats['total_bills']} bills, "
                    f"{stats['overall_compliance_rate']}% compliant"
                )
            print()

        elif choice == "4":
            committee_id = input("Enter committee ID: ").strip()
            if committee_id in committee_data:
                bills = committee_data[committee_id].get("bills", [])
                display_bill_details(bills)
            else:
                print(f"❌ Committee '{committee_id}' not found.\n")

        elif choice == "5":
            print("\n📊 Before/After Comparison")
            print("-" * 80)
            print("To compare before/after:")
            print("1. Run this tool on your current production data")
            print("2. Save the global stats output")
            print("3. Run again on your new test data")
            print("4. Compare the compliance rates manually")
            print()
            print("Future enhancement: Add automatic comparison feature")
            print()

        else:
            print("❌ Invalid option. Please try again.\n")


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Main entry point."""
    import sys

    # Check for test mode
    test_mode = "--test" in sys.argv or "--dry-run" in sys.argv

    print("\n" + "=" * 80)
    print("🔍 COMPLIANCE DATA AUDIT TOOL")
    print("=" * 80)
    print(f"📂 Reading data from: {OUTPUT_FOLDER}")
    if test_mode:
        print("🧪 Running in TEST MODE (non-interactive)")
    print("=" * 80)
    print()

    # Load committee data
    committee_data = load_committee_data(OUTPUT_FOLDER)

    if not committee_data:
        print("\n❌ No data loaded. Exiting.")
        print(f"\n💡 Tip: Create '{OUTPUT_FOLDER}' folder and add JSON files like:")
        print(
            """
{
  "committee_id": "J1",
  "bills": [
    {
      "bill_id": "H1234",
      "bill_title": "An Act relative to...",
      "bill_url": "https://...",
      "hearing_date": "2024-01-15",
      "deadline_60": "2024-03-15",
      "effective_deadline": "2024-03-15",
      "reported_out": true,
      "summary_present": true,
      "votes_present": true,
      "state": "Compliant",
      "reason": "All requirements met"
    }
  ]
}
        """
        )
        return

    # Calculate global statistics
    print("🔢 Calculating global statistics...")
    global_stats = calculate_global_stats(committee_data)
    print("✅ Calculations complete\n")

    # Display global stats immediately
    display_global_stats(global_stats)

    # In test mode, show all committee stats and exit
    if test_mode:
        print("\n📋 All Committee Statistics:")
        print("=" * 80)
        for committee_id, data in sorted(committee_data.items()):
            bills = data.get("bills", [])
            stats = calculate_committee_stats(committee_id, bills)
            display_committee_stats(committee_id, stats)

        print("✅ Test complete! Run without --test for interactive mode.\n")
        return

    # Enter interactive menu
    try:
        interactive_menu(committee_data, global_stats)
    except (EOFError, KeyboardInterrupt):
        print("\n\n👋 Goodbye!")
        return


if __name__ == "__main__":
    main()
