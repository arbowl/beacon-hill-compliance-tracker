""" Fetches committee data from the Massachusetts Legislature website.
"""

from components.runner import run_basic_compliance
from components.interfaces import Config
from components.options import (
    get_committee_selection,
    get_hearing_limit,
    get_extension_check_preference,
    print_options_summary,
    submit_data
)
from collectors.extension_orders import collect_all_extension_orders
from components.utils import Cache


def main():
    """Entry point for the compliance pipeline"""
    cache = Cache()
    config = Config("config.yaml")
    if config.collect_input:
        # Get interactive inputs
        committee_ids = get_committee_selection(
            config.base_url, config.include_chambers
        )
        limit_hearings = get_hearing_limit()
        check_extensions = get_extension_check_preference(cache)
        print_options_summary(
            committee_ids,
            limit_hearings,
            check_extensions
        )
        confirm = input("\nProceed with these settings? (y/n): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("Aborted.")
            return
    else:
        print_options_summary(
            config.runner.committee_ids,
            config.runner.limit_hearings,
            config.runner.check_extensions
        )
    
    # Collect all extension orders once at the beginning if enabled
    extension_lookup: dict[str, list] = {}
    if check_extensions:
        print("Collecting all extension orders...")
        all_extension_orders = collect_all_extension_orders(
            config.base_url, cache
        )
        print(f"Found {len(all_extension_orders)} total extension orders")

        # Create lookup dictionary for quick access
        for eo in all_extension_orders:
            if eo.bill_id not in extension_lookup:
                extension_lookup[eo.bill_id] = []
            extension_lookup[eo.bill_id].append(eo)
    else:
        print("Extension checking disabled - using cached data only")

    # Process each committee
    for committee_id in committee_ids:
        print(f"\n{'='*60}")
        print(f"Processing Committee: {committee_id}")
        print(f"{'='*60}")
        run_basic_compliance(
            base_url=config.base_url,
            include_chambers=config.include_chambers,
            committee_id=committee_id,
            limit_hearings=limit_hearings,
            cfg=config,
            cache=cache,
            extension_lookup=extension_lookup,
            write_json=True
        )
    submit_data(committee_ids)
    input("Collection complete! Press Enter to exit.")


if __name__ == "__main__":
    main()
