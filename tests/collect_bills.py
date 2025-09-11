""" Test the collection of bills from the hearings. """

from pathlib import Path
import json
import sys

from components.utils import load_config
from components.committees import get_committees
from collectors.bills_from_hearing import get_bills_for_committee

BILLS_TO_SAMPLE = 12


def test_step2_collect_bills():
    """ Test the collection of bills from the hearings. """
    cfg = load_config()
    base_url = cfg["base_url"]
    include = cfg["filters"]["include_chambers"]
    committees = get_committees(base_url, include)
    # Use J33 unless you change it in config.yaml later
    target_id = "J33"
    target = next((c for c in committees if c.id == target_id), None)
    if not target:
        print(f"Committee {target_id} not found")
        sys.exit(2)
    # Keep it light on first run; limit to first 2 hearings
    bills = get_bills_for_committee(base_url, target.id, limit_hearings=2)
    print(
        f"Collected {len(bills)} bill-hearing rows for {target.id} "
        f"({target.name})"
    )
    for b in bills[:BILLS_TO_SAMPLE]:
        print(
            f"  {b.hearing_date}  {b.bill_id:<6}  {b.bill_label:<10}  "
            f"{b.bill_url}"
        )
    # Write artifact
    outdir = Path("out")
    outdir.mkdir(exist_ok=True)
    payload = [b.__dict__ for b in bills]
    (outdir / f"bills_{target.id}.json").write_text(
        json.dumps(
            payload,
            default=str,
            indent=2
        ),
        encoding="utf-8"
    )
    print(f"Wrote out/bills_{target.id}.json")
