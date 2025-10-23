"""Interactive committee selection with various input options.

This file is ugly and needs guard clauses to clean the if-statements
up, but for now it's good enough.
"""

from os import getenv

from components.utils import Cache
from components.committees import get_committees
from components.sender import IngestClient


def get_committee_selection(
    base_url: str, include_chambers: list[str]
) -> list[str]:
    """Interactive committee selection with various input options."""
    print("\n" + "="*60)
    print("COMMITTEE SELECTION")
    print("="*60)
    
    # Get all available committees
    all_committees = get_committees(base_url, include_chambers)
    print(f"\nAvailable committees ({len(all_committees)} total):")
    for i, committee in enumerate(all_committees, 1):
        print(f"  {i:2d}. {committee.id} - {committee.name}")
    
    print("\nSelection options:")
    print("  - Enter a single number (e.g., 1)")
    print("  - Enter comma-separated numbers (e.g., 1,3,5)")
    print("  - Enter a range with dash (e.g., 1-5)")
    print("  - Enter 'all' for all committees")
    print("  - Enter committee IDs directly (e.g., J10,J11)")
    
    while True:
        selection = input("\nEnter your selection: ").strip()
        if not selection:
            print("Please enter a selection.")
            continue
        if selection.lower() == 'all':
            return [c.id for c in all_committees]
        
        # Try to parse as committee IDs first
        if ',' in selection or '-' in selection or selection.isalnum():
            # Check if it looks like committee IDs
            if any(part.strip() in [c.id for c in all_committees] for part in selection.replace('-', ',').split(',')):
                # Parse committee IDs
                committee_ids = []
                for part in selection.split(','):
                    part = part.strip()
                    if '-' in part:
                        # Handle range
                        start, end = part.split('-', 1)
                        start = start.strip()
                        end = end.strip()
                        # Find start and end indices
                        start_idx = None
                        end_idx = None
                        for i, c in enumerate(all_committees):
                            if c.id == start:
                                start_idx = i
                            if c.id == end:
                                end_idx = i
                        if start_idx is not None and end_idx is not None:
                            for i in range(start_idx, end_idx + 1):
                                committee_ids.append(all_committees[i].id)
                    else:
                        if part in [c.id for c in all_committees]:
                            committee_ids.append(part)
                
                if committee_ids:
                    return committee_ids
                else:
                    print("No valid committee IDs found. Please try again.")
                    continue
        
        # Try to parse as numbers
        try:
            committee_ids = []
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    # Handle range
                    start, end = part.split('-', 1)
                    start_idx = int(start.strip()) - 1
                    end_idx = int(end.strip()) - 1
                    if 0 <= start_idx <= end_idx < len(all_committees):
                        for i in range(start_idx, end_idx + 1):
                            committee_ids.append(all_committees[i].id)
                    else:
                        print(f"Range {part} is out of bounds. Please try again.")
                        break
                else:
                    idx = int(part) - 1
                    if 0 <= idx < len(all_committees):
                        committee_ids.append(all_committees[idx].id)
                    else:
                        print(f"Number {part} is out of bounds. Please try again.")
                        break
            else:
                if committee_ids:
                    return committee_ids
        except ValueError:
            print("Invalid input format. Please try again.")
            continue


def get_hearing_limit():
    """Interactive hearing limit selection."""
    print("\n" + "="*60)
    print("HEARING LIMIT")
    print("="*60)
    print("Enter the number of hearings to process (useful for quick tests):")
    print("  - Enter a number (e.g., 5)")
    print("  - Leave blank to process all hearings")
    while True:
        limit_input = input("\nNumber of hearings (or blank for all): ").strip()
        
        if not limit_input:
            return 999
        try:
            limit = int(limit_input)
            if limit > 0:
                return limit
            else:
                print("Please enter a positive number.")
        except ValueError:
            print("Please enter a valid number.")


def get_extension_check_preference(cache: Cache) -> None:
    """Interactive extension check preference with cache status."""
    print("\n" + "="*60)
    print("EXTENSION CHECKING")
    print("="*60)
    if cache.search_for_keyword('extensions'):
        print("✓ Cache contains extension data.")
        print("You can skip this unless you want to use the latest data (it just takes a while).")
    else:
        print("⚠ Cache does not contain extension data.")
        print("You should run it once to collect extension data.")
    print("\nOptions:")
    print("  - Enter 'y' or 'yes' to check extensions")
    print("  - Enter 'n' or 'no' to skip extension checking")
    print("  - Leave blank to skip")
    while True:
        choice = input("\nCheck for bill extensions? (y/n): ").strip().lower()
        if not choice or choice in ['n', 'no']:
            return False
        elif choice in ['y', 'yes']:
            return True
        else:
            print("Please enter 'y' for yes or 'n' for no.")


def print_options_summary(
    committee_ids: list[str],
    limit_hearings: int,
    check_extensions: bool
) -> None:
    """Print the options summary."""
    print(f"\n" + "="*60)
    print("CONFIGURATION SUMMARY")
    print("="*60)
    print(f"Committees: {', '.join(committee_ids)}")
    print(f"Hearing limit: {limit_hearings}")
    print(f"Check extensions: {check_extensions}")


def submit_data(committees: list[str]) -> None:
    if input(
        "Send data to remote server? (y/n)"
    ).strip().lower() not in ['y', 'yes']:
        return
    print("Sending data...")
    client = IngestClient(
        base_url="https://beacon-hill-tracker.onrender.com/",
        signing_key_id=getenv("SIGNING_ID", ""),
        signing_key_secret=getenv("SIGNING_SECRET"),
    )
    print(client.upload_file("cache.json", kind="cache"))
    for committee in committees:
        print("Sending committee:", committee)
        print(client.upload_file(f"out/basic_{committee}.json", kind="basic"))
    print("Data submission complete.")
