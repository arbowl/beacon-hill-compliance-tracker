""" Test the summary with review. """

import json
from pathlib import Path

from collectors.bills_from_hearing import (
    extract_bills_from_hearing,
    list_committee_hearings,
)
from components.pipeline import resolve_summary_for_bill
from components.utils import Cache, load_config


BILLS_TO_SAMPLE = 20


def test_step4_summary_with_review():
    """ Test the summary with review. """
    cfg = load_config()
    base_url = cfg["base_url"]
    committee_id = "J33"
    # Pull hearings and find the specific one (5114)
    hearings = list_committee_hearings(base_url, committee_id)
    target = next((h for h in hearings if h.id == "5114"), None)
    if not target:
        print("Hearing 5114 not found")
        return
    bill_rows = extract_bills_from_hearing(base_url, target)
    cache = Cache()
    results = []
    for row in bill_rows[:6]:  # sample a few
        si = resolve_summary_for_bill(base_url, cfg, cache, row)
        results.append({"bill_id": row.bill_id, **si.__dict__})
        print(
            f"{row.bill_id:<6} summary: {si.present}  {si.location:<12}  "
            f"{si.source_url or '—'}  via {si.parser_module or '—'}"
            f"{'  (needs review)' if si.needs_review else ''}"
        )
    Path("out").mkdir(exist_ok=True)
    Path("out/summary_probe_5114.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
