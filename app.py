""" Fetches committee data from the Massachusetts Legislature website.
"""

from enum import Enum
from components.utils import load_config
from components.runner import run_basic_compliance


class Cfg(str, Enum):
    """Light config API with needed values"""

    BASE_URL = "base_url"
    FITLTERS = "filters"
    INCLUDE_CHAMBERS = "include_chambers"
    RUNNER = "runner"
    COMMITTEE_IDS = "committee_ids"
    LIMIT_HEARINGS = "limit_hearings"


def main():
    """Entry point for the compliance pipeline"""
    cfg = load_config()
    base_url = cfg[Cfg.BASE_URL]
    include_chambers = cfg[Cfg.FITLTERS][Cfg.INCLUDE_CHAMBERS]
    runner = cfg[Cfg.RUNNER]
    committee_ids = runner[Cfg.COMMITTEE_IDS]
    limit_hearings = runner[Cfg.LIMIT_HEARINGS]

    # Handle "all" case or unexpected values by processing all committees
    if not isinstance(committee_ids, list) or "all" in committee_ids:
        from components.committees import get_committees
        all_committees = get_committees(base_url, include_chambers)
        committee_ids = [c.id for c in all_committees]
        print(f"Processing all {len(committee_ids)} committees: "
              f"{', '.join(committee_ids)}")

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


if __name__ == "__main__":
    main()
