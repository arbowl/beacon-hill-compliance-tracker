"""Runner module for basic compliance checking."""

from pathlib import Path
import json
import time
from datetime import datetime, date, timedelta

import requests

from components.pipeline import (
    resolve_summary_for_bill,
    resolve_votes_for_bill,
)
from components.committees import get_committees
from components.compliance import classify, compute_notice_status
from components.interfaces import Config
from components.report import write_basic_html
from components.utils import Cache
from components.models import DeferredReviewSession, ExtensionOrder
from components.review import conduct_batch_review, apply_review_results
from collectors.bills_from_hearing import get_bills_for_committee
from collectors.bills_from_committee_tab import get_all_committee_bills
from collectors.bill_status_basic import build_status_row
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
    percentage = (current / total) * 100
    elapsed_time = time.time() - start_time
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
    bar_width = 20
    filled_width = int((current / total) * bar_width)
    bar = "█" * filled_width + "░" * (bar_width - filled_width)
    progress_line = (
        f"[{bar}] {current}/{total} ({percentage:.1f}%) | "
        f"Processing {bill_id} | {speed_str} | ETA: {time_remaining_str}"
    )
    print(progress_line)


def run_basic_compliance(
    base_url: str,
    include_chambers: bool,
    committee_id: str,
    limit_hearings: bool,
    cfg: Config,
    cache: Cache,
    extension_lookup: dict[str, list[ExtensionOrder]],
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

    # 1.5) get committee contact info
    print("Collecting committee contact information...")
    contact = get_committee_contact(base_url, committee, cache)
    print("\nPhase 1: Collecting bills from Hearings tab...")
    hearing_bills = get_bills_for_committee(
        base_url, committee.id, limit_hearings=limit_hearings
    )
    print(f"Found {len(hearing_bills)} bills with hearings")
    print("\nPhase 2: Collecting all bills from Bills tab...")
    all_bills = get_all_committee_bills(base_url, committee.id)
    print(f"Found {len(all_bills)} total bills assigned to committee")
    hearing_bill_ids = {b.bill_id for b in hearing_bills}
    non_hearing_bills = [
        b for b in all_bills if b.bill_id not in hearing_bill_ids
    ]
    print(f"Found {len(non_hearing_bills)} bills without hearings")
    rows = hearing_bills + non_hearing_bills
    if not rows:
        print("No bills found")
        return
    print(f"\nProcessing {len(rows)} total bills...")
    print(f"  - {len(hearing_bills)} with hearings")
    print(f"  - {len(non_hearing_bills)} without hearings")

    # 3) Initialize deferred review session if needed
    deferred_session = None
    if cfg.review_mode == "deferred":
        deferred_session = DeferredReviewSession(
            session_id="",
            committee_id=committee_id
        )
        print(
            "Deferred review mode enabled - "
            "confirmations will be collected for batch review."
        )

    # 4) per-bill: status → summary → votes → classify
    results = []
    total_bills = len(rows)
    start_time = time.time()

    print(f"\nProcessing {total_bills} bills...")

    for i, r in enumerate(rows, 1):
        _update_progress(i - 1, total_bills, r.bill_id, start_time)
        cache.add_bill_to_committee(r.committee_id, r.bill_id)
        extension_until = None
        if r.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[r.bill_id], key=lambda x: x.extension_date
            )
            if latest_extension.is_date_fallback:
                if r.hearing_date:
                    extension_until = r.hearing_date + timedelta(days=90)
                    print(
                        f"  Using 30-day fallback extension: "
                        f"{extension_until}"
                    )
            else:
                extension_until = latest_extension.extension_date
        elif not cfg.runner.check_extensions:
            # If extension checking is disabled, check cache for previously
            # discovered data
            cached_extension = cache.get_extension(r.bill_id)
            if cached_extension:
                try:
                    cached_date = datetime.fromisoformat(
                        cached_extension["extension_date"]
                    ).date()
                    if cached_date == date(1900, 1, 1):
                        if r.hearing_date:
                            extension_until = (
                                r.hearing_date + timedelta(days=90)
                            )
                            print(
                                f"  Using cached 30-day fallback: "
                                f"{extension_until}"
                            )
                    else:
                        extension_until = cached_date
                except (ValueError, KeyError):
                    extension_until = None

        status = build_status_row(base_url, r, cache, extension_until)
        summary = resolve_summary_for_bill(
            base_url, cfg, cache, r, deferred_session
        )
        votes = resolve_votes_for_bill(
            base_url, cfg, cache, r, deferred_session
        )
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

        hearing_str = (
            str(status.hearing_date) if status.hearing_date else "N/A"
        )
        d60_str = str(status.deadline_60) if status.deadline_60 else "N/A"
        eff_str = (
            str(status.effective_deadline)
            if status.effective_deadline else "N/A"
        )
        print(
            f"\n{r.bill_id:<6} heard {hearing_str} "
            f"→ D60 {d60_str} / Eff {eff_str} | "
            f"Reported: {'Y' if status.reported_out else 'N'} | "
            f"Summary: {'Y' if summary.present else 'N'} | "
            f"Votes: {'Y' if votes.present else 'N'} | "
            f"{comp.state.upper()} — {comp.reason}"
        )

        extension_order_url = None
        extension_date = None
        if r.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[r.bill_id], key=lambda x: x.extension_date
            )
            extension_order_url = latest_extension.extension_order_url
            extension_date = latest_extension.extension_date
            print(f"  Found extension: {extension_date}")
        elif not cfg.runner.check_extensions:
            cached_extension = cache.get_extension(r.bill_id)
            if cached_extension and "extension_url" in cached_extension:
                extension_order_url = cached_extension["extension_url"]
                extension_date = cached_extension["extension_date"]
                print(f"  Found cached extension: {extension_date}")
            else:
                print(f"  No extension found for {r.bill_id}")
        else:
            print(f"  No extension found for {r.bill_id}")
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
            "announcement_date": (
                str(status.announcement_date)
                if status.announcement_date else None
            ),
            "scheduled_hearing_date": (
                str(status.scheduled_hearing_date)
                if status.scheduled_hearing_date else None
            ),
        })
    _update_progress(total_bills, total_bills, "Complete", start_time)
    print()
    if (cfg.review_mode == "deferred" and deferred_session and
            deferred_session.confirmations):
        print("\nProcessing complete. Conducting batch review...")
        review_results = conduct_batch_review(
            deferred_session, cfg, cache
        )
        apply_review_results(review_results, deferred_session, cache)
        if cfg.deferred_review.reprocess_after_review:
            print("\nRe-processing bills with confirmed parsers...")
            print(
                "Re-processing skipped - using tentative results "
                "with confirmed cache entries."
            )
    elif cfg.review_mode == "deferred":
        print(
            "\nNo confirmations needed - all parsers were "
            "auto-accepted or cached."
        )

    # 5) artifacts (JSON + HTML)
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
