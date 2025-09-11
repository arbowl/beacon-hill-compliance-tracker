"""Runner module for basic compliance checking."""
from pathlib import Path
import json

from components.committees import get_committees
from components.utils import Cache
from components.compliance import classify
from components.report import write_basic_html
from collectors.bills_from_hearing import get_bills_for_committee
from collectors.bill_status_basic import build_status_row
from components.pipeline import (
    resolve_summary_for_bill,
    resolve_votes_for_bill,
)


def run_basic_compliance(
    base_url, include_chambers, committee_id, limit_hearings, cfg,
    write_json=True
):
    """Run basic compliance check for a committee.

    Args:
        base_url: Base URL for the legislature website
        include_chambers: List of chambers to include
        committee_id: ID of the committee to check
        limit_hearings: Maximum number of hearings to process
        cfg: Full configuration object
        write_json: Whether to write JSON output files
    """
    # 1) committee + contact (optional to show later)
    committees = get_committees(base_url, include_chambers)
    committee = next((c for c in committees if c.id == committee_id), None)
    if not committee:
        print(
            f"Committee {committee_id} not found among "
            f"{len(committees)} committees"
        )
        return

    print(
        f"Running basic compliance for {committee.name} "
        f"[{committee.id}]..."
    )

    # 2) bill rows from first N hearings
    rows = get_bills_for_committee(
        base_url, committee.id, limit_hearings=limit_hearings
    )
    if not rows:
        print("No bill-hearing rows found")
        return
    print(
        f"Found {len(rows)} bill-hearing rows "
        f"(first {limit_hearings} hearing(s))"
    )

    # 3) per-bill: status → summary → votes → classify
    cache = Cache()
    results = []
    for r in rows:
        status = build_status_row(base_url, r)
        summary = resolve_summary_for_bill(base_url, cfg, cache, r)
        votes = resolve_votes_for_bill(base_url, cfg, cache, r)
        comp = classify(r.bill_id, r.committee_id, status, summary, votes)

        # console line
        print(
            f"{r.bill_id:<6} heard {status.hearing_date} "
            f"→ D60 {status.deadline_60} / Eff {status.effective_deadline} | "
            f"Reported: {'Y' if status.reported_out else 'N'} | "
            f"Summary: {'Y' if summary.present else 'N'} | "
            f"Votes: {'Y' if votes.present else 'N'} | "
            f"{comp.state.upper()} — {comp.reason}"
        )

        # pack for artifacts
        results.append({
            "bill_id": r.bill_id,
            "bill_url": r.bill_url,
            "hearing_date": str(status.hearing_date),
            "deadline_60": str(status.deadline_60),
            "effective_deadline": str(status.effective_deadline),
            "reported_out": status.reported_out,
            "summary_present": summary.present,
            "summary_url": summary.source_url,
            "votes_present": votes.present,
            "votes_url": votes.source_url,
            "state": comp.state,
            "reason": comp.reason,
        })

    # 4) artifacts (JSON + HTML)
    if write_json:
        outdir = Path("out")
        outdir.mkdir(exist_ok=True)
        json_path = outdir / f"basic_{committee.id}.json"
        html_path = outdir / f"basic_{committee.id}.html"
        json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        write_basic_html(committee.name, committee.id, results, html_path)
        print(f"Wrote {json_path}")
        print(f"Wrote {html_path}")

    return results
