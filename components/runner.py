"""Runner module for basic compliance checking."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import threading
import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

import requests  # type: ignore

from components.pipeline import (
    resolve_summary_for_bill,
    resolve_votes_for_bill,
)
from components.committees import get_committees
from components.compliance import compute_notice_status
from components.ruleset import classify
from components.interfaces import Config
from components.report import write_basic_html
from components.utils import (
    Cache,
    get_date_output_dir,
    load_previous_committee_json,
    generate_diff_report,
    TimeInterval,
    extract_session_from_bill_url,
)
from components.templates import (
    generate_deterministic_analysis,
)
from components.models import (
    DeferredReviewSession,
    ExtensionOrder,
    BillAtHearing,
    BillStatus,
)
from components.review import conduct_batch_review, apply_review_results
from collectors.bills_from_hearing import get_bills_for_committee
from collectors.bills_from_committee_tab import get_all_committee_bills
from collectors.bill_status_basic import build_status_row
from collectors.bill_status_basic import get_bill_title
from collectors.committee_contact_info import get_committee_contact
from timeline.parser import extract_timeline
from timeline.models import BillActionTimeline
from history.composer import BillArtifactComposer
from history.repository import BillArtifactRepository

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-12s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _format_time_remaining(seconds: int) -> str:
    """Format time remaining in a human-readable way."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def _update_progress(current: int, total: int, bill_id: str, start_time: int) -> None:
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
        time_remaining_str = _format_time_remaining(round(estimated_remaining_seconds))
        speed_str = f"{bills_per_minute:.1f} bills/min"
    else:
        time_remaining_str = "calculating..."
        speed_str = "calculating..."
    bar_width = 20
    filled_width = int((current / total) * bar_width)
    loading_bar = "█" * filled_width + "░" * (bar_width - filled_width)
    progress_line = (
        f"[{loading_bar}] {current}/{total} ({percentage:.1f}%) | "
        f"Processing {bill_id} | {speed_str} | ETA: {time_remaining_str}"
    )
    logger.info(progress_line)


def _process_single_bill(
    base_url: str,
    cfg: Config,
    cache: Cache,
    row: BillAtHearing,
    extension_lookup: dict[str, list[ExtensionOrder]],
    deferred_session,
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
        extension_until = None
        if row.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[row.bill_id], key=lambda x: x.extension_date
            )
            if latest_extension.is_date_fallback:
                if row.hearing_date:
                    extension_until = row.hearing_date + timedelta(days=90)
                    logger.debug(
                        "  Using 30-day fallback extension: %s", extension_until
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
                                "  Using cached 30-day fallback: %s", extension_until
                            )
                    else:
                        extension_until = cached_date
                except (ValueError, KeyError):
                    extension_until = None
        status: BillStatus = build_status_row(base_url, row, extension_until)
        summary = resolve_summary_for_bill(base_url, cfg, cache, row, deferred_session)
        votes = resolve_votes_for_bill(base_url, cfg, cache, row, deferred_session)
        comp = classify(row.bill_id, row.committee_id, status, summary, votes)
        bill_title: Optional[str] = cache.get_title(row.bill_id)
        if bill_title is None:
            try:
                with requests.Session() as _:
                    bill_title = get_bill_title(row.bill_url)
                    if bill_title:
                        cache.set_title(row.bill_id, bill_title)
            except Exception:  # pylint: disable=broad-exception-caught
                bill_title = None
        if cfg.artifacts.enabled:
            timeline: BillActionTimeline = extract_timeline(row.bill_url, row.bill_id)
            artifact = BillArtifactComposer.compose_from_scrape(
                bill=row,
                status=status,
                summary=summary,
                votes=votes,
                timeline=timeline,
                extensions=extension_lookup.get(row.bill_id, []),
                compliance=comp,
                bill_title=bill_title,
                ruleset_version=cfg.artifacts.ruleset_version,
            )
            repo = BillArtifactRepository(cfg.artifacts.db_path)
            repo.save_artifact(artifact)
        hearing_str = str(status.hearing_date) if status.hearing_date else "N/A"
        d60_str = str(status.deadline_60) if status.deadline_60 else "N/A"
        eff_str = str(status.effective_deadline) if status.effective_deadline else "N/A"
        bill_info = (
            f"{row.bill_id:<6} heard {hearing_str} "
            f"→ D60 {d60_str} / Eff {eff_str} | "
            f"Reported: {'Y' if status.reported_out else 'N'} | "
            f"Summary: {'Y' if summary.present else 'N'} | "
            f"Votes: {'Y' if votes.present else 'N'} | "
            f"{comp.state.upper()} — {comp.reason}"
        )
        logger.info(bill_info)
        extension_order_url = None
        extension_date = None
        if row.bill_id in extension_lookup:
            latest_extension = max(
                extension_lookup[row.bill_id], key=lambda x: x.extension_date
            )
            extension_order_url = latest_extension.extension_order_url
            extension_date = latest_extension.extension_date
            logger.debug("  Found extension: %s", extension_date)
        elif not cfg.runner.check_extensions:
            cached_extension = cache.get_extension(row.bill_id)
            if cached_extension and "extension_url" in cached_extension:
                extension_order_url = cached_extension["extension_url"]
                extension_date = cached_extension["extension_date"]
                logger.debug("  Found cached extension: %s", extension_date)
            else:
                logger.debug("  No extension found for %s", row.bill_id)
        else:
            logger.debug("  No extension found for %s", row.bill_id)
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
            "reported_out": status.reported_out or (status.reported_date is not None),
            "reported_out_date": (
                str(status.reported_date) if status.reported_date else None
            ),
            "summary_present": summary.present,
            "summary_url": summary.source_url,
            "votes_present": votes.present,
            "votes_url": votes.source_url,
            "state": comp.state,
            "reason": comp.reason,
            "notice_status": notice_status,
            "notice_gap_days": gap_days,
            "announcement_date": (
                str(status.announcement_date) if status.announcement_date else None
            ),
            "scheduled_hearing_date": (
                str(status.scheduled_hearing_date)
                if status.scheduled_hearing_date
                else None
            ),
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error processing bill %s: %s", row.bill_id, e, exc_info=True)
        return {}


def run_basic_compliance(
    base_url: str,
    include_chambers: bool,
    committee_id: str,
    limit_hearings: int,
    cfg: Config,
    cache: Cache,
    extension_lookup: dict[str, list[ExtensionOrder]],
    write_json=True,
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
            "Committee %s not found among %d committees", committee_id, len(committees)
        )
        return
    logger.info("Running basic compliance for %s [%s]...", committee.name, committee.id)
    logger.info("Collecting committee contact information...")
    contact = get_committee_contact(base_url, committee, cache)
    logger.info("Phase 1: Collecting bills from Hearings tab...")
    hearing_bills = get_bills_for_committee(
        base_url, committee.id, limit_hearings=limit_hearings
    )
    logger.info("Found %d bills with hearings", len(hearing_bills))
    logger.info("Phase 2: Collecting all bills from Bills tab...")
    all_bills = get_all_committee_bills(base_url, committee.id)
    logger.info("Found %d total bills assigned to committee", len(all_bills))
    hearing_bill_ids = {b.bill_id for b in hearing_bills}
    non_hearing_bills = [b for b in all_bills if b.bill_id not in hearing_bill_ids]
    logger.info("Found %d bills without hearings", len(non_hearing_bills))
    rows = hearing_bills + non_hearing_bills
    if not rows:
        logger.warning("No bills found")
        return
    # Extract session from first bill URL and ensure cache is set correctly
    session = None
    for row in rows:
        if row.bill_url:
            session = extract_session_from_bill_url(row.bill_url)
            if session:
                cache.ensure_session(session)
                logger.info("Detected session: %s", session)
                break
    if not session:
        logger.warning("Could not extract session from bill URLs")
        # Try to get session from cache if available
        session = cache.get_session()
    logger.info("Processing %d total bills...", len(rows))
    logger.info("  - %d with hearings", len(hearing_bills))
    logger.info("  - %d without hearings", len(non_hearing_bills))
    deferred_session = None
    if cfg.review_mode == "deferred":
        deferred_session = DeferredReviewSession(
            session_id="", committee_id=committee_id
        )
        logger.info(
            "Deferred review mode enabled - "
            "confirmations will be collected for batch review."
        )
    results = []
    total_bills = len(rows)
    start_time = time.time()
    logger.info("Processing %d bills...", total_bills)
    max_workers = cfg.threading.max_workers
    if cfg.review_mode == "on":
        logger.info(
            "Interactive review mode enabled - forcing single-threaded " "execution"
        )
        max_workers = 1
    if max_workers > 1:
        logger.info("Using %d worker threads for bill processing", max_workers)
        results_lock = threading.Lock()
        processed_count = [0]

        def process_and_track(row: BillAtHearing) -> dict:
            """Process bill and update progress."""
            result = _process_single_bill(
                base_url, cfg, cache, row, extension_lookup, deferred_session
            )
            with results_lock:
                processed_count[0] += 1
                _update_progress(
                    processed_count[0],
                    total_bills,
                    row.bill_id,
                    int(start_time),
                )
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_bill = {
                executor.submit(process_and_track, row): row for row in rows
            }
            for future in as_completed(future_to_bill):
                row = future_to_bill[future]
                try:
                    result = future.result()
                    if result:
                        with results_lock:
                            results.append(result)
                # pylint: disable=broad-exception-caught
                except Exception as e:
                    logger.error(
                        "Exception processing %s: %s", row.bill_id, e, exc_info=True
                    )
    else:
        logger.info("Using single-threaded sequential processing")
        for i, row in enumerate(rows, 1):
            _update_progress(
                i - 1,
                total_bills,
                row.bill_id,
                int(start_time),
            )
            result = _process_single_bill(
                base_url, cfg, cache, row, extension_lookup, deferred_session
            )
            if result:
                results.append(result)
        _update_progress(
            total_bills,
            total_bills,
            "Complete",
            int(start_time),
        )
    if (
        cfg.review_mode == "deferred"
        and deferred_session
        and deferred_session.confirmations
    ):
        logger.info("Processing complete. Conducting batch review...")
        review_results = conduct_batch_review(deferred_session, cfg, cache)
        apply_review_results(review_results, deferred_session, cache)
        if cfg.deferred_review.reprocess_after_review:
            logger.info("Re-processing bills with confirmed parsers...")
            logger.info(
                "Re-processing skipped - using tentative results "
                "with confirmed cache entries."
            )
    elif cfg.review_mode == "deferred":
        logger.info(
            "No confirmations needed - all parsers were " "auto-accepted or cached."
        )
    if write_json:
        outdir = get_date_output_dir()
        json_path = outdir / f"basic_{committee.id}.json"
        html_path = outdir / f"basic_{committee.id}.html"
        # Generate diff reports by comparing with previous scans
        boston_tz = ZoneInfo("US/Eastern")
        current_date = datetime.now(boston_tz).date()
        # Daily diff report
        previous_bills_daily, previous_date_daily = load_previous_committee_json(
            committee.id, days_ago=TimeInterval.DAILY
        )
        diff_report_daily = None
        if previous_bills_daily is not None and previous_date_daily is not None:
            diff_report_daily = generate_diff_report(
                results, previous_bills_daily, current_date, previous_date_daily
            )
            if diff_report_daily is not None:
                analysis_daily = generate_deterministic_analysis(
                    diff_report_daily, results, previous_bills_daily, committee.name
                )
                diff_report_daily["analysis"] = analysis_daily
        # Weekly diff report
        previous_bills_weekly, previous_date_weekly = load_previous_committee_json(
            committee.id, days_ago=TimeInterval.WEEKLY
        )
        diff_report_weekly = None
        if previous_bills_weekly is not None and previous_date_weekly is not None:
            diff_report_weekly = generate_diff_report(
                results, previous_bills_weekly, current_date, previous_date_weekly
            )
            if diff_report_weekly is not None:
                analysis_weekly = generate_deterministic_analysis(
                    diff_report_weekly, results, previous_bills_weekly, committee.name
                )
                diff_report_weekly["analysis"] = analysis_weekly
        # Monthly diff report
        previous_bills_monthly, previous_date_monthly = load_previous_committee_json(
            committee.id, days_ago=TimeInterval.MONTHLY
        )
        diff_report_monthly = None
        if previous_bills_monthly is not None and previous_date_monthly is not None:
            diff_report_monthly = generate_diff_report(
                results, previous_bills_monthly, current_date, previous_date_monthly
            )
            if diff_report_monthly is not None:
                analysis_monthly = generate_deterministic_analysis(
                    diff_report_monthly, results, previous_bills_monthly, committee.name
                )
                diff_report_monthly["analysis"] = analysis_monthly
        # Create output structure with bills and diff_reports
        output_data = {
            "session": session if session else None,
            "bills": results,
            "diff_reports": {
                "daily": diff_report_daily,
                "weekly": diff_report_weekly,
                "monthly": diff_report_monthly,
            },
        }
        json_path.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
        write_basic_html(
            committee.name, committee.id, committee.url, contact, results, html_path
        )
        logger.info("Wrote %s", json_path)
        logger.info("Wrote %s", html_path)
    return results
