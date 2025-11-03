"""Interactive committee selection with various input options.

This file is ugly and needs guard clauses to clean the if-statements
up, but for now it's good enough.
"""

from os import getenv

from collectors.extension_orders import collect_all_extension_orders
from components.committees import get_committees
from components.runner import run_basic_compliance
from components.sender import IngestClient
from components.utils import Cache, Config, get_latest_output_dir
from version import __version__


def get_committee_selection(
    base_url: str, include_chambers: tuple[str]
) -> list[str]:
    """Interactive committee selection with various input options."""
    print("\n" + "="*60)
    print("COMMITTEE SELECTION")
    print("="*60)
    all_committees = get_committees(
        base_url,
        include_chambers
    )
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
        if ',' in selection or '-' in selection or selection.isalnum():
            if any(
                part.strip()
                in [c.id for c in all_committees]
                for part in selection.replace('-', ',').split(',')
            ):
                committee_ids = []
                for part in selection.split(','):
                    part = part.strip()
                    if '-' in part:
                        start, end = part.split('-', 1)
                        start = start.strip()
                        end = end.strip()
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
                print("No valid committee IDs found. Please try again.")
                continue
        try:
            committee_ids = []
            for part in selection.split(','):
                part = part.strip()
                if '-' in part:
                    start, end = part.split('-', 1)
                    start_idx = int(start.strip()) - 1
                    end_idx = int(end.strip()) - 1
                    if 0 <= start_idx <= end_idx < len(all_committees):
                        for i in range(start_idx, end_idx + 1):
                            committee_ids.append(all_committees[i].id)
                    else:
                        print(
                            f"Range {part} is out of bounds. Please try again."
                        )
                        break
                else:
                    idx = int(part) - 1
                    if 0 <= idx < len(all_committees):
                        committee_ids.append(all_committees[idx].id)
                    else:
                        print(
                            f"Number {part} is out of bounds. Please "
                            "try again."
                        )
                        break
            else:
                if committee_ids:
                    return committee_ids
        except ValueError:
            print("Invalid input format. Please try again.")
            continue


def get_hearing_limit() -> int:
    """Interactive hearing limit selection."""
    print("\n" + "="*60)
    print("HEARING LIMIT")
    print("="*60)
    print("Enter the number of hearings to process (useful for quick tests):")
    print("  - Enter a number (e.g., 5)")
    print("  - Leave blank to process all hearings")
    while True:
        limit_input = input(
            "\nNumber of hearings (or blank for all): "
        ).strip()
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


def get_extension_check_preference(cache: Cache) -> bool:
    """Interactive extension check preference with cache status."""
    print("\n" + "="*60)
    print("EXTENSION CHECKING")
    print("="*60)
    if cache.search_for_keyword('extensions'):
        print("✓ Cache contains extension data.")
        print(
            "You can skip this unless you want to use the latest data "
            "(it just takes a while)."
        )
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
    print("\n" + "="*60)
    print("CONFIGURATION SUMMARY")
    print("="*60)
    print(f"Committees: {', '.join(committee_ids)}")
    print(f"Hearing limit: {limit_hearings}")
    print(f"Check extensions: {check_extensions}")


def submit_data(
    committees: list[str], cache: Cache, auto_confirm: bool = False
) -> None:
    """Send collected data to the remote server.

    Args:
        committees: List of committee IDs to submit
        cache: Cache instance
        auto_confirm: If True, skip confirmation prompt and submit
            automatically
    """
    if not auto_confirm:
        if input(
            "Send data to remote server? (y/n)"
        ).strip().lower() not in ['y', 'yes']:
            return
    print("Sending data...")
    client = IngestClient(
        base_url="https://beacon-hill-tracker.onrender.com/",
        signing_key_id=getenv("SIGNING_ID", ""),
        signing_key_secret=getenv("SIGNING_SECRET", ""),
    )
    print(client.upload_file(str(cache.path), kind="cache"))
    print(client.upload_file(str(cache.path), kind="cache"))
    # Find the latest output directory
    latest_dir = get_latest_output_dir()
    if latest_dir is None:
        print(
            "No output directories found. "
            "Skipping committee data upload."
        )
        return

    print(f"Using latest output directory: {latest_dir}")
    for committee in committees:
        print("Sending committee:", committee)
        json_path = latest_dir / f"basic_{committee}.json"
        if json_path.exists():
            print(client.upload_file(str(json_path), kind="basic"))
        else:
            print(f"Warning: File not found: {json_path}")
    print("Data submission complete.")


def submit_changelog(auto_confirm: bool = False) -> None:
    """Send changelog and version information to the remote server.

    This function can be called standalone or integrated into your
    deployment workflow to update the server with the current version.

    Args:
        auto_confirm: If True, skip confirmation prompt and submit
            automatically

    Environment Variables:
        SIGNING_ID: API signing key ID
        SIGNING_SECRET: API signing key secret
    """
    if not auto_confirm:
        if input(
            "Send changelog to remote server? (y/n): "
        ).strip().lower() not in ['y', 'yes']:
            print("Changelog submission skipped.")
            return
    print("Sending changelog...")
    client = IngestClient(
        base_url="https://beacon-hill-tracker.onrender.com/",
        signing_key_id=getenv("SIGNING_ID", ""),
        signing_key_secret=getenv("SIGNING_SECRET", ""),
    )
    result = client.upload_changelog()
    print("Response:", result)
    if result.get("results") and result["results"][0].get("ok"):
        print("[OK] Changelog sent successfully!")
    else:
        print("[FAIL] Failed to send changelog.")
        print("  Check your API credentials and network connection.")


def runner_loop(config: Config, cache: Cache) -> None:
    """Runs a simple collection and submission loop"""
    while True:
        print()
        print(f"Beacon Hill Compliance Tracker v{__version__}")
        print()
        submit_data(
            [committee.id for committee in get_committees(
                config.base_url, tuple(config.include_chambers)
            )],
            cache
        )
        submit_changelog()
        check_extensions = config.runner.check_extensions
        if config.collect_input:
            committee_ids = get_committee_selection(
                config.base_url, tuple(config.include_chambers)  # type: ignore
            )
            limit_hearings: int = get_hearing_limit()
            check_extensions = get_extension_check_preference(cache)
            print_options_summary(
                committee_ids,
                limit_hearings,
                check_extensions
            )
            prompt = "\nProceed with these settings? (y/n): "
            confirm = input(prompt).strip().lower()
            if confirm not in ['y', 'yes']:
                print("Aborted.")
                return
        else:
            print_options_summary(
                config.runner.committee_ids,
                config.runner.limit_hearings,
                config.runner.check_extensions
            )
        extension_lookup: dict[str, list] = {}
        if check_extensions:
            print("Collecting all extension orders...")
            all_extension_orders = collect_all_extension_orders(
                config.base_url, cache
            )
            print(f"Found {len(all_extension_orders)} total extension orders")
            for eo in all_extension_orders:
                if eo.bill_id not in extension_lookup:
                    extension_lookup[eo.bill_id] = []
                extension_lookup[eo.bill_id].append(eo)
            cache.force_save()
            print("Cache saved after extension order collection")
        else:
            print("Extension checking disabled - using cached data only")
        for committee_id in committee_ids:
            print(f"\n{'='*60}")
            print(f"Processing Committee: {committee_id}")
            print(f"{'='*60}")
            run_basic_compliance(
                base_url=config.base_url,
                include_chambers=tuple(
                    config.include_chambers   # type: ignore
                ),
                committee_id=committee_id,
                limit_hearings=limit_hearings,
                cfg=config,
                cache=cache,
                extension_lookup=extension_lookup,
                write_json=True
            )
            cache.force_save()
            print(f"Cache saved after processing committee {committee_id}")
        cache.force_save()
        print("Final cache save completed")
        input("Collection complete! Press Enter to continue.")


def one_run_mode(config: Config, cache: Cache, check_extensions: bool) -> None:
    """Run a single end-to-end compliance check for all committees.

    Args:
        config: Configuration object
        cache: Cache instance
        check_extensions: Whether to check for bill extensions
    """
    print()
    print(f"Beacon Hill Compliance Tracker v{__version__}")
    print()
    print("="*60)
    print("ONE-RUN MODE")
    print("="*60)

    # Get all committees
    all_committees = get_committees(
        config.base_url, tuple(config.include_chambers)
    )
    committee_ids = [committee.id for committee in all_committees]
    limit_hearings = 999  # Process all hearings

    print_options_summary(committee_ids, limit_hearings, check_extensions)

    # Collect extension orders if needed
    extension_lookup: dict[str, list] = {}
    if check_extensions:
        print("Collecting all extension orders...")
        all_extension_orders = collect_all_extension_orders(
            config.base_url, cache
        )
        print(f"Found {len(all_extension_orders)} total extension orders")
        for eo in all_extension_orders:
            if eo.bill_id not in extension_lookup:
                extension_lookup[eo.bill_id] = []
            extension_lookup[eo.bill_id].append(eo)
        cache.force_save()
        print("Cache saved after extension order collection")
    else:
        print("Extension checking disabled - using cached data only")

    # Process all committees
    for committee_id in committee_ids:
        print(f"\n{'='*60}")
        print(f"Processing Committee: {committee_id}")
        print(f"{'='*60}")
        run_basic_compliance(
            base_url=config.base_url,
            include_chambers=tuple(config.include_chambers),  # type: ignore
            committee_id=committee_id,
            limit_hearings=limit_hearings,
            cfg=config,
            cache=cache,
            extension_lookup=extension_lookup,
            write_json=True
        )
        cache.force_save()
        print(f"Cache saved after processing committee {committee_id}")

    cache.force_save()
    print("Final cache save completed")

    # Automatically submit data and changelog at the end
    print("\n" + "="*60)
    print("SUBMITTING DATA")
    print("="*60)
    submit_data(committee_ids, cache, auto_confirm=True)

    print("\n" + "="*60)
    print("SUBMITTING CHANGELOG")
    print("="*60)
    submit_changelog(auto_confirm=True)

    print("\nOne-run mode complete!")


def scheduled_mode(
    config: Config, cache: Cache, at_time: str, check_extensions: bool
) -> None:
    """Run one_run_mode on a schedule (daily at specified time).

    Args:
        config: Configuration object
        cache: Cache instance
        at_time: Time string in HH:MM format (e.g., "02:00", "14:30")
        check_extensions: Whether to check for bill extensions
    """
    import schedule
    import time
    from datetime import datetime

    # Parse and normalize time string
    time_str = at_time.strip()
    # Handle both "2:00" and "02:00" formats
    if ":" not in time_str:
        raise ValueError(
            f"Invalid time format: '{at_time}'. Expected HH:MM format "
            "(e.g., '02:00' or '14:30')"
        )

    # Validate time format by trying to parse it
    try:
        # Try parsing to validate format
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError("Time must be in HH:MM format")
        hours = int(parts[0])
        minutes = int(parts[1])
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError("Hours must be 0-23, minutes must be 0-59")
        # Normalize to HH:MM format
        normalized_time = f"{hours:02d}:{minutes:02d}"
    except (ValueError, IndexError) as e:
        raise ValueError(
            f"Invalid time format: '{at_time}'. Expected HH:MM format "
            "(e.g., '02:00' or '14:30'). Error: {e}"
        ) from e

    # Define the job function
    def run_scheduled_task() -> None:
        """Run one_run_mode as a scheduled task."""
        print("\n" + "="*60)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"SCHEDULED RUN STARTED at {timestamp}")
        print("="*60)
        try:
            one_run_mode(config, cache, check_extensions)
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"\n[ERROR] Scheduled run failed: {e}")
            print("Will continue with next scheduled run.")
        print("\n" + "="*60)
        print("SCHEDULED RUN COMPLETED")
        print("="*60)

    # Schedule the job
    schedule.every().day.at(normalized_time).do(run_scheduled_task)

    # Show startup info
    print()
    print("="*60)
    print("SCHEDULED MODE")
    print("="*60)
    print(f"Scheduled: daily at {normalized_time}")
    print(f"Check extensions: {check_extensions}")
    next_run = schedule.next_run()
    if next_run:
        next_run_str = next_run.strftime("%Y-%m-%d %H:%M:%S")
        print(f"Next run: {next_run_str}")
    print("Press Ctrl+C to stop")
    print("="*60)
    print()

    # Main scheduling loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\n\nScheduled mode stopped by user.")
        print("Gracefully shutting down...")
