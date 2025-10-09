""" Fetches committee data from the Massachusetts Legislature website.
"""

from enum import Enum
from components.utils import load_config
from components.runner import run_basic_compliance
from components.options import (
    get_committee_selection,
    get_hearing_limit,
    get_extension_check_preference,
    print_options_summary
)
from collectors.extension_orders import collect_all_extension_orders
from components.utils import Cache


class Cfg(str, Enum):
    """Light config API with needed values"""

    BASE_URL = "base_url"
    FITLTERS = "filters"
    INCLUDE_CHAMBERS = "include_chambers"
    RUNNER = "runner"
    COMMITTEE_IDS = "committee_ids"
    LIMIT_HEARINGS = "limit_hearings"
    CHECK_EXTENSIONS = "check_extensions"
    COLLECT_INPUT = "collect_input"


def main():
    """Entry point for the compliance pipeline"""
    cfg = load_config()
    base_url = cfg[Cfg.BASE_URL]
    include_chambers = cfg[Cfg.FITLTERS][Cfg.INCLUDE_CHAMBERS]
    cache = Cache()
    
    if cfg[Cfg.COLLECT_INPUT]:
        # Get interactive inputs
        committee_ids = get_committee_selection(base_url, include_chambers)
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
        cfg[Cfg.RUNNER] = {
            Cfg.COMMITTEE_IDS: committee_ids,
            Cfg.LIMIT_HEARINGS: limit_hearings,
            Cfg.CHECK_EXTENSIONS: check_extensions
        }
    else:
        # Load from config
        committee_ids = cfg[Cfg.RUNNER][Cfg.COMMITTEE_IDS]
        limit_hearings = cfg[Cfg.RUNNER][Cfg.LIMIT_HEARINGS]
        check_extensions = cfg[Cfg.RUNNER][Cfg.CHECK_EXTENSIONS]
        print_options_summary(
            committee_ids,
            limit_hearings,
            check_extensions
        )
    
    # Collect all extension orders once at the beginning if enabled
    extension_lookup: dict[str, list] = {}
    if check_extensions:
        print("Collecting all extension orders...")
        all_extension_orders = collect_all_extension_orders(base_url, cache)
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
            base_url=base_url,
            include_chambers=include_chambers,
            committee_id=committee_id,
            limit_hearings=limit_hearings,
            cfg=cfg,
            cache=cache,
            extension_lookup=extension_lookup,
            write_json=True
        )
    input("Collection complete! Press Enter to exit.")


if __name__ == "__main__":
    main()
