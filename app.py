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


class Cfg(str, Enum):
    """Light config API with needed values"""

    BASE_URL = "base_url"
    FITLTERS = "filters"
    INCLUDE_CHAMBERS = "include_chambers"
    RUNNER = "runner"
    COMMITTEE_IDS = "committee_ids"
    LIMIT_HEARINGS = "limit_hearings"
    CHECK_EXTENSIONS = "check_extensions"


def main():
    """Entry point for the compliance pipeline"""
    cfg = load_config()
    base_url = cfg[Cfg.BASE_URL]
    include_chambers = cfg[Cfg.FITLTERS][Cfg.INCLUDE_CHAMBERS]
    
    # Get interactive inputs
    committee_ids = get_committee_selection(base_url, include_chambers)
    limit_hearings = get_hearing_limit()
    check_extensions = get_extension_check_preference()
    print_options_summary(
        committee_ids,
        limit_hearings,
        check_extensions
    )
    confirm = input("\nProceed with these settings? (y/n): ").strip().lower()
    if confirm not in ['y', 'yes']:
        print("Aborted.")
        return
    
    # Update config with user choices
    cfg[Cfg.RUNNER] = {
        Cfg.COMMITTEE_IDS: committee_ids,
        Cfg.LIMIT_HEARINGS: limit_hearings,
        Cfg.CHECK_EXTENSIONS: check_extensions
    }

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
            write_json=True
        )
    input("Collection complete! Press Enter to exit.")


if __name__ == "__main__":
    main()
