"""Console output handler for the Massachusetts Legislature compliance tracker."""

import sys
import time
from typing import Any, Dict
from datetime import date, datetime

from components.output import OutputEvent, BaseHandler


class ConsoleHandler(BaseHandler):
    """Console output handler that reproduces current behavior exactly."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._progress_start_time = None
        self._progress_total = 0
    
    def handle(self, event: OutputEvent):
        """Handle console output with current formatting."""
        if event.domain == "app" and event.category == "start":
            print(f"Processing all {event.data['committee_count']} committees: {', '.join(event.data['committee_ids'])}")
        elif event.domain == "app" and event.category == "processing":
            if event.subcategory == "separator":
                print(f"\n{'='*60}")
                print(f"Processing Committee: {event.data['committee_id']}")
                print(f"{'='*60}")
        elif event.domain == "committee" and event.category == "error":
            print(f"Committee {event.data['committee_id']} not found among {event.data['total_committees']} committees")
        elif event.domain == "committee" and event.category == "processing":
            if event.subcategory == "start":
                print(f"Running basic compliance for {event.data['committee_name']} [{event.data['committee_id']}]...")
        elif event.domain == "committee" and event.category == "contact":
            if event.subcategory == "collecting":
                print("Collecting committee contact information...")
            elif event.subcategory == "cached":
                print(f"Using cached contact info for committee {event.data['committee_id']}")
            elif event.subcategory == "fetching":
                print(f"Fetching contact info for committee {event.data['committee_id']}")
            elif event.subcategory == "cached_success":
                print(f"Cached contact info for committee {event.data['committee_id']}")
        elif event.domain == "committee" and event.category == "bills":
            if event.subcategory == "found":
                print(f"Found {event.data['count']} bill-hearing rows (first {event.data['limit_hearings']} hearing(s))")
            elif event.subcategory == "none":
                print("No bill-hearing rows found")
        elif event.domain == "extension_orders" and event.category == "processing":
            if event.subcategory == "collecting":
                print("Collecting all extension orders...")
            elif event.subcategory == "disabled":
                print("Extension checking disabled - using cached data only")
            elif event.subcategory == "found":
                print(f"Found {event.data['count']} total extension orders")
        elif event.domain == "bill" and event.category == "processing":
            if event.subcategory == "start":
                print(f"\nProcessing {event.data['total_bills']} bills...")
                self._progress_total = event.data['total_bills']
                self._progress_start_time = time.time()
            elif event.subcategory == "progress":
                self._handle_progress(event)
        elif event.domain == "bill" and event.category == "status":
            if event.subcategory == "compliance":
                data = event.data
                print(f"\n{data['bill_id']:<6} heard {data['hearing_date']} "
                      f"→ D60 {data['deadline_60']} / Eff {data['effective_deadline']} | "
                      f"Reported: {'Y' if data['reported_out'] else 'N'} | "
                      f"Summary: {'Y' if data['summary_present'] else 'N'} | "
                      f"Votes: {'Y' if data['votes_present'] else 'N'} | "
                      f"{data['compliance_state'].upper()} — {data['reason']}")
        elif event.domain == "bill" and event.category == "extension":
            if event.subcategory == "fallback_used":
                print(f"  Using 30-day fallback extension: {event.data['extension_date']}")
            elif event.subcategory == "cached_fallback_used":
                print(f"  Using cached 30-day fallback extension: {event.data['extension_date']}")
            elif event.subcategory == "found":
                print(f"  Found extension: {event.data['extension_date']}")
            elif event.subcategory == "cached_found":
                print(f"  Found cached extension: {event.data['extension_date']}")
            elif event.subcategory == "not_found":
                print(f"  No extension found for {event.data['bill_id']}")
        elif event.domain == "file" and event.category == "output":
            print(f"Wrote {event.data['file_path']}")
        elif event.domain == "parser" and event.category == "warning":
            print(f"Warning: {event.message}")
        elif event.domain == "parser" and event.category == "debug":
            print(f"DEBUG: {event.message}")
        elif event.domain == "parser" and event.category == "llm":
            print(f"LLM unavailable for {event.data['doc_type']} {event.data['bill_id']}, falling back to manual review")
        else:
            # Fallback for unhandled events
            print(f"[{event.domain}.{event.category}.{event.subcategory}] {event.message}")
    
    def _handle_progress(self, event: OutputEvent):
        """Handle progress bar output (reproduces current behavior)."""
        current = event.data.get('current', 0)
        total = event.data.get('total', 0)
        bill_id = event.data.get('bill_id', '')
        start_time = event.data.get('start_time', time.time())
        
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
            time_remaining_str = self._format_time_remaining(estimated_remaining_seconds)
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
    
    def _format_time_remaining(self, seconds: float) -> str:
        """Format time remaining in a human-readable way."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"
