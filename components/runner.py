"""Runner module for basic compliance checking."""
from pathlib import Path
import json
import time
import sys
from datetime import datetime, date, timedelta

import requests  # Added for bill title fetch

from components.pipeline import (
    resolve_summary_for_bill,
    resolve_votes_for_bill,
)
from components.committees import get_committees
from components.utils import Cache
from components.compliance import classify
from components.report import write_basic_html
from collectors.extension_orders import collect_all_extension_orders
from collectors.bills_from_hearing import get_bills_for_committee
from collectors.bill_status_basic import build_status_row
# New: bill title helper
from collectors.bill_status_basic import get_bill_title
from collectors.committee_contact_info import get_committee_contact


def _format_time_remaining(seconds):
    """Format time remaining in a human-readable way."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def _update_progress(current, total, bill_id, start_time):
    """Update progress indicator on the same line."""
    if total == 0:
        return

    # Calculate progress metrics
    percentage = (current / total) * 100
    elapsed_time = time.time() - start_time

    # Calculate processing speed and time remaining
    if current > 0:
        bills_per_second = current / elapsed_time
        bills_per_minute = bills_per_second * 60
        remaining_bills = total - current
        estimated_remaining_seconds = (
            remaining_bills / bills_per_second if bills_per_second > 0 else 0
        )
        time_remaining_str = _format_time_remaining(
            estimated_remaining_seconds
        )
        speed_str = f"{bills_per_minute:.1f} bills/min"
    else:
        time_remaining_str = "calculating..."
        speed_str = "calculating..."

    # Create progress bar (20 characters wide)
    bar_width = 20
    filled_width = int((current / total) * bar_width)
    bar = "█" * filled_width + "░" * (bar_width - filled_width)

    # Format the progress line
    progress_line = (
        f"\r[{bar}] {current}/{total} ({percentage:.1f}%) | "
        f"Processing {bill_id} | {speed_str} | ETA: {time_remaining_str}"
    )

    # Write to stdout and flush immediately
    sys.stdout.write(progress_line)
    sys.stdout.flush()


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

    # Initialize cache early for reuse
    cache = Cache()

    # 1.5) get committee contact info
    print("Collecting committee contact information...")
    contact = get_committee_contact(base_url, committee, cache)

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

    # Collect all extension orders once at the beginning if enabled
    extension_lookup = {}
    if cfg.get("runner", {}).get("check_extensions", True):
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

    # 3) per-bill: status → summary → votes → classify
    results = []
    total_bills = len(rows)
    start_time = time.time()

    print(f"\nProcessing {total_bills} bills...")

    for i, r in enumerate(rows, 1):
        # Update progress indicator
        _update_progress(i - 1, total_bills, r.bill_id, start_time)
        # Get extension data for this bill if available
        extension_until = None
        if r.bill_id in extension_lookup:
            # Get the latest extension date for this bill
            latest_extension = max(
                extension_lookup[r.bill_id], key=lambda x: x.extension_date
            )
            if latest_extension.is_date_fallback:
                # If this is a date fallback, calculate 30 days from hearing
                extension_until = r.hearing_date + timedelta(days=90)  # 60+30
                print(f"  Using 30-day fallback extension: "
                      f"{extension_until}")
            else:
                extension_until = latest_extension.extension_date
        elif not cfg.get("runner", {}).get("check_extensions", True):
            # If extension checking is disabled, check cache for previously
            # discovered data
            cached_extension = cache.get_extension(r.bill_id)
            if cached_extension:
                try:
                    cached_date = datetime.fromisoformat(
                        cached_extension["extension_date"]
                    ).date()
                    # Check if this is a fallback date (1900-01-01)
                    if cached_date == date(1900, 1, 1):
                        # Use 30-day fallback
                        extension_until = (r.hearing_date +
                                           timedelta(days=90))  # 60+30
                        print(f"  Using cached 30-day fallback extension: "
                              f"{extension_until}")
                    else:
                        extension_until = cached_date
                except (ValueError, KeyError):
                    extension_until = None

        status = build_status_row(base_url, r, extension_until)
        summary = resolve_summary_for_bill(base_url, cfg, cache, r)
        votes = resolve_votes_for_bill(base_url, cfg, cache, r)
        comp = classify(r.bill_id, r.committee_id, status, summary, votes)

        # Fetch bill title (one request; tolerant to failure)
        bill_title: str | None = cache.get_title(r.bill_id)
        if bill_title is None:
            try:
                with requests.Session() as sess:
                    bill_title = get_bill_title(sess, r.bill_url)
                    if bill_title:
                        cache.set_title(r.bill_id, bill_title)
            except Exception:  # pylint: disable=broad-exception-caught
                bill_title = None

        # Update progress indicator with current bill
        _update_progress(i, total_bills, r.bill_id, start_time)

        # console line (moved after progress update)
        print(
            f"\n{r.bill_id:<6} heard {status.hearing_date} "
            f"→ D60 {status.deadline_60} / Eff {status.effective_deadline} | "
            f"Reported: {'Y' if status.reported_out else 'N'} | "
            f"Summary: {'Y' if summary.present else 'N'} | "
            f"Votes: {'Y' if votes.present else 'N'} | "
            f"{comp.state.upper()} — {comp.reason}"
        )

        # pack for artifacts
        extension_order_url = None
        extension_date = None

        # Use pre-collected extension data if available
        if r.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[r.bill_id], key=lambda x: x.extension_date
            )
            extension_order_url = latest_extension.extension_order_url
            extension_date = latest_extension.extension_date
            print(f"  Found extension: {extension_date}")
        elif not cfg.get("runner", {}).get("check_extensions", True):
            # If extension checking is disabled, use cached data if available
            cached_extension = cache.get_extension(r.bill_id)
            if cached_extension:
                extension_order_url = cached_extension["extension_url"]
                extension_date = cached_extension["extension_date"]
                print(f"  Found cached extension: {extension_date}")
            else:
                print(f"  No extension found for {r.bill_id}")
        else:
            print(f"  No extension found for {r.bill_id}")

        # Calculate notice gap for reporting
        from components.compliance import compute_notice_status
        notice_status, gap_days = compute_notice_status(status)
        
        results.append({
            "bill_id": r.bill_id,
            "bill_title": bill_title,
            "bill_url": r.bill_url,
            "hearing_date": str(status.hearing_date),
            "deadline_60": str(status.deadline_60),
            "effective_deadline": str(status.effective_deadline),
            "extension_order_url": extension_order_url,
            "extension_date": str(extension_date) if extension_date else None,
            "reported_out": status.reported_out,
            "summary_present": summary.present,
            "summary_url": summary.source_url,
            "votes_present": votes.present,
            "votes_url": votes.source_url,
            "state": comp.state,
            "reason": comp.reason,
            "notice_status": notice_status,
            "notice_gap_days": gap_days,
            "announcement_date": (str(status.announcement_date) 
                                  if status.announcement_date else None),
            "scheduled_hearing_date": (str(status.scheduled_hearing_date)
                                       if status.scheduled_hearing_date 
                                       else None),
        })

    # Final progress update and cleanup
    _update_progress(total_bills, total_bills, "Complete", start_time)
    print()  # Move to next line after progress indicator

    # 4) artifacts (JSON + HTML)
    if write_json:
        outdir = Path("out")
        outdir.mkdir(exist_ok=True)
        json_path = outdir / f"basic_{committee.id}.json"
        html_path = outdir / f"basic_{committee.id}.html"
        json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        write_basic_html(
            committee.name, committee.id, committee.url, contact, results,
            html_path
        )
        print(f"Wrote {json_path}")
        print(f"Wrote {html_path}")

    return results
