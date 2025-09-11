"""Test the summary tab parser."""

from collectors.bills_from_hearing import get_bills_for_committee
from components.pipeline import resolve_summary_for_bill
from components.utils import Cache, load_config


BILLS_TO_SAMPLE = 6


def test_step5_summary_tab_parser() -> None:
    """Test the summary tab parser."""
    cfg = load_config()
    base_url = cfg["base_url"]
    committee_id = "J46"

    # Find bills that *don’t* have summary PDFs but do have Summary tab
    bill_rows = get_bills_for_committee(
        base_url, committee_id, limit_hearings=2
    )
    cache = Cache()

    for row in bill_rows[:BILLS_TO_SAMPLE]:
        si = resolve_summary_for_bill(base_url, cfg, cache, row)
        print(
            f"{row.bill_id:<6} summary: {si.present}  {si.location:<12}  "
            f"{si.source_url or '—'}  via {si.parser_module or '—'}"
        )
