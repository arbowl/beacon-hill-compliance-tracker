"""Test the committee summary DOCX parser."""

from collectors.bills_from_hearing import get_bills_for_committee
from components.pipeline import resolve_summary_for_bill
from components.utils import Cache, load_config
from components.models import BillAtHearing
from datetime import date
from parsers.summary_committee_docx import discover, parse


BILLS_TO_SAMPLE = 6


def test_committee_summary_docx_parser() -> None:
    """Test the committee summary DOCX parser."""
    cfg = load_config()
    base_url = cfg["base_url"]
    committee_id = "J46"  # Aging and Independence committee

    # Find bills that might have Committee Summary DOCX files
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


def test_specific_bill_h760() -> None:
    """Test specifically with H760 which has a Committee Summary DOCX."""

    # Create a mock BillAtHearing for H760
    bill = BillAtHearing(
        bill_id="H760",
        bill_label="H.760",
        bill_url="https://malegislature.gov/Bills/194/H760",
        hearing_id="5114",  # Example hearing ID
        hearing_date=date(2025, 1, 15),  # Example date
        committee_id="J46",
        hearing_url="https://malegislature.gov/Events/Hearings/Detail/5114"
    )

    base_url = "https://malegislature.gov"

    # Test discovery
    candidate = discover(base_url, bill)
    if candidate:
        print(f"Found candidate: {candidate}")

        # Test parsing
        result = parse(base_url, candidate)
        print(f"Parse result: {result}")
    else:
        print("No Committee Summary DOCX found for H760")
