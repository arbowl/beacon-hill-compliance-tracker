"""Test the votes pipeline."""

from collectors.bills_from_hearing import get_bills_for_committee
from components.pipeline import resolve_votes_for_bill
from components.utils import Cache
from components.utils import load_config


def test_step6_votes_pipeline() -> None:
    """Test the votes pipeline."""
    cfg = load_config()
    base_url = cfg["base_url"]
    committee_id = "J33"
    rows = get_bills_for_committee(base_url, committee_id, limit_hearings=1)
    if not rows:
        print("No bills found")
        return
    cache = Cache()
    for row in rows[:8]:
        vi = resolve_votes_for_bill(base_url, cfg, cache, row)
        print(
            f"{row.bill_id:<6} votes: {vi.present}  {vi.location:<12} "
            f"{vi.source_url or '—'} via {vi.parser_module or '—'}"
            f"{'  (needs review)' if vi.needs_review else ''}"
        )
