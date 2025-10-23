"""Runner module for basic compliance checking."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import threading
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(threadName)-12s] %(levelname)-8s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


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
    """Update progress indicator."""
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
    logger.info(progress_line)


def _process_single_bill(
    base_url: str,
    cfg: Config,
    cache: Cache,
    row,
    extension_lookup: dict[str, list[ExtensionOrder]],
    deferred_session
) -> dict:
    """Process a single bill (thread-safe).
    
    Args:
        base_url: Base URL for the legislature website
        cfg: Configuration object
        cache: Thread-safe cache instance
        row: BillAtHearing instance
        extension_lookup: Dictionary of extension orders
        deferred_session: Deferred review session (thread-safe)
        
    Returns:
        Dictionary with bill processing results
    """
    try:
        cache.add_bill_to_committee(row.committee_id, row.bill_id)
        
        # Determine extension date
        extension_until = None
        if row.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[row.bill_id], key=lambda x: x.extension_date
            )
            if latest_extension.is_date_fallback:
                if row.hearing_date:
                    extension_until = row.hearing_date + timedelta(days=90)
                    logger.debug(
                        f"  Using 30-day fallback extension: {extension_until}"
                    )
            else:
                extension_until = latest_extension.extension_date
        elif not cfg.runner.check_extensions:
            cached_extension = cache.get_extension(row.bill_id)
            if cached_extension:
                try:
                    cached_date = datetime.fromisoformat(
                        cached_extension["extension_date"]
                    ).date()
                    if cached_date == date(1900, 1, 1):
                        if row.hearing_date:
                            extension_until = row.hearing_date + timedelta(days=90)
                            logger.debug(
                                f"  Using cached 30-day fallback: {extension_until}"
                            )
                    else:
                        extension_until = cached_date
                except (ValueError, KeyError):
                    extension_until = None
        
        # Process bill
        status = build_status_row(base_url, row, cache, extension_until)
        summary = resolve_summary_for_bill(base_url, cfg, cache, row, deferred_session)
        votes = resolve_votes_for_bill(base_url, cfg, cache, row, deferred_session)
        comp = classify(row.bill_id, row.committee_id, status, summary, votes)
        
        # Fetch bill title
        bill_title = cache.get_title(row.bill_id)
        if bill_title is None:
            try:
                with requests.Session() as sess:
                    bill_title = get_bill_title(sess, row.bill_url)
                    if bill_title:
                        cache.set_title(row.bill_id, bill_title)
            except Exception:  # pylint: disable=broad-exception-caught
                bill_title = None
        
        # Log status
        hearing_str = str(status.hearing_date) if status.hearing_date else "N/A"
        d60_str = str(status.deadline_60) if status.deadline_60 else "N/A"
        eff_str = str(status.effective_deadline) if status.effective_deadline else "N/A"
        logger.info(
            f"{row.bill_id:<6} heard {hearing_str} "
            f"→ D60 {d60_str} / Eff {eff_str} | "
            f"Reported: {'Y' if status.reported_out else 'N'} | "
            f"Summary: {'Y' if summary.present else 'N'} | "
            f"Votes: {'Y' if votes.present else 'N'} | "
            f"{comp.state.upper()} — {comp.reason}"
        )
        
        # Extension info
        extension_order_url = None
        extension_date = None
        if row.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[row.bill_id], key=lambda x: x.extension_date
            )
            extension_order_url = latest_extension.extension_order_url
            extension_date = latest_extension.extension_date
            logger.debug(f"  Found extension: {extension_date}")
        elif not cfg.runner.check_extensions:
            cached_extension = cache.get_extension(row.bill_id)
            if cached_extension:
                extension_order_url = cached_extension["extension_url"]
                extension_date = cached_extension["extension_date"]
                logger.debug(f"  Found cached extension: {extension_date}")
            else:
                logger.debug(f"  No extension found for {row.bill_id}")
        else:
            logger.debug(f"  No extension found for {row.bill_id}")
        
        # Build result
        notice_status, gap_days = compute_notice_status(status)
        return {
            "bill_id": row.bill_id,
            "bill_title": bill_title,
            "bill_url": row.bill_url,
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
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error processing bill {row.bill_id}: {e}", exc_info=True)
        return None


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
        logger.warning(
            f"Committee {committee_id} not found among "
            f"{len(committees)} committees"
        )
        return

    logger.info(
        f"Running basic compliance for {committee.name} "
        f"[{committee.id}]..."
    )

    # 1.5) get committee contact info
    logger.info("Collecting committee contact information...")
    contact = get_committee_contact(base_url, committee, cache)
    logger.info("Phase 1: Collecting bills from Hearings tab...")
    hearing_bills = get_bills_for_committee(
        base_url, committee.id, limit_hearings=limit_hearings
    )
    logger.info(f"Found {len(hearing_bills)} bills with hearings")
    logger.info("Phase 2: Collecting all bills from Bills tab...")
    all_bills = get_all_committee_bills(base_url, committee.id)
    logger.info(f"Found {len(all_bills)} total bills assigned to committee")
    hearing_bill_ids = {b.bill_id for b in hearing_bills}
    non_hearing_bills = [
        b for b in all_bills if b.bill_id not in hearing_bill_ids
    ]
    logger.info(f"Found {len(non_hearing_bills)} bills without hearings")
    rows = hearing_bills + non_hearing_bills
    if not rows:
        logger.warning("No bills found")
        return
    logger.info(f"Processing {len(rows)} total bills...")
    logger.info(f"  - {len(hearing_bills)} with hearings")
    logger.info(f"  - {len(non_hearing_bills)} without hearings")

    # 3) Initialize deferred review session if needed
    deferred_session = None
    if cfg.review_mode == "deferred":
        deferred_session = DeferredReviewSession(
            session_id="",
            committee_id=committee_id
        )
        logger.info(
            "Deferred review mode enabled - "
            "confirmations will be collected for batch review."
        )

    # 4) per-bill: status → summary → votes → classify
    results = []
    total_bills = len(rows)
    start_time = time.time()

    logger.info(f"Processing {total_bills} bills...")

    # Determine thread count (force single-threaded if interactive review is on)
    max_workers = cfg.threading.max_workers
    if cfg.review_mode == "on":
        logger.info(
            "Interactive review mode enabled - forcing single-threaded execution"
        )
        max_workers = 1
    
    # Use threading if max_workers > 1
    if max_workers > 1:
        logger.info(f"Using {max_workers} worker threads for bill processing")
        results_lock = threading.Lock()
        processed_count = [0]  # Mutable container for progress tracking
        
        def process_and_track(row):
            """Process bill and update progress."""
            result = _process_single_bill(
                base_url, cfg, cache, row, extension_lookup, deferred_session
            )
            with results_lock:
                processed_count[0] += 1
                _update_progress(
                    processed_count[0], total_bills, row.bill_id, start_time
                )
            return result
        
        # Process bills in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_bill = {
                executor.submit(process_and_track, row): row
                for row in rows
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_bill):
                row = future_to_bill[future]
                try:
                    result = future.result()
                    if result:
                        with results_lock:
                            results.append(result)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(
                        f"Exception processing {row.bill_id}: {e}",
                        exc_info=True
                    )
    else:
        # Sequential processing (single-threaded)
        logger.info("Using single-threaded sequential processing")
        for i, row in enumerate(rows, 1):
            _update_progress(i - 1, total_bills, row.bill_id, start_time)
            result = _process_single_bill(
                base_url, cfg, cache, row, extension_lookup, deferred_session
            )
            if result:
                results.append(result)
        _update_progress(total_bills, total_bills, "Complete", start_time)
    if (cfg.review_mode == "deferred" and deferred_session and
            deferred_session.confirmations):
        logger.info("Processing complete. Conducting batch review...")
        review_results = conduct_batch_review(
            deferred_session, cfg, cache
        )
        apply_review_results(review_results, deferred_session, cache)
        if cfg.deferred_review.reprocess_after_review:
            logger.info("Re-processing bills with confirmed parsers...")
            logger.info(
                "Re-processing skipped - using tentative results "
                "with confirmed cache entries."
            )
    elif cfg.review_mode == "deferred":
        logger.info(
            "No confirmations needed - all parsers were "
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
        logger.info(f"Wrote {json_path}")
        logger.info(f"Wrote {html_path}")

    return results
