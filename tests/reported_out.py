""" Test the deadlines and reported out status of the bills. """

import json
from pathlib import Path

from components.utils import load_config
from collectors.bills_from_hearing import get_bills_for_committee
from collectors.bill_status_basic import build_status_row


BILLS_TO_SAMPLE = 12


def test_step3_deadlines_and_reported_out():
    """ Test the deadlines and reported out status of the bills. """
    cfg = load_config()
    base_url = cfg["base_url"]
    committee_id = "J33"  # same example as before
    # Keep this light: just the first hearing so you can eyeball easily
    bill_rows = get_bills_for_committee(
        base_url, committee_id, limit_hearings=1
    )
    print(
        f"Found {len(bill_rows)} bill-hearing rows in first hearing for "
        f"{committee_id}"
    )
    statuses = [
        build_status_row(base_url, r) for r in bill_rows[:BILLS_TO_SAMPLE]
    ]
    for s in statuses:
        flag = "REPORTED" if s.reported_out else "NOT REPORTED"
        print(
            f"{s.bill_id:<6} heard {s.hearing_date} → d60 {s.deadline_60} / "
            f"d90 {s.deadline_90} | {flag} on {s.reported_date or '—'} | "
            f" effective {s.effective_deadline}"
        )
    outdir = Path("out")
    outdir.mkdir(exist_ok=True)
    Path(f"out/status_{committee_id}.json").write_text(
        json.dumps(
            [s.__dict__ for s in statuses],
            default=str,
            indent=2
        ),
        encoding="utf-8"
    )
    print(f"Wrote out/status_{committee_id}.json")
