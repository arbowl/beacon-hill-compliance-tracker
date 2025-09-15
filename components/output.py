"""Hierarchical output controller for the Massachusetts Legislature compliance tracker."""

from typing import Any, Dict, List, Callable
from datetime import date, datetime
from enum import Enum
from dataclasses import dataclass

class OutputLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"

@dataclass
class OutputEvent:
    """Structured output event with hierarchical context."""
    domain: str          # e.g., "committee", "bill", "parser"
    category: str        # e.g., "contact", "processing", "status"
    subcategory: str     # e.g., "cached", "fetching", "found"
    level: OutputLevel
    message: str
    data: Dict[str, Any]
    timestamp: datetime

class OutputController:
    """Hierarchical output controller with subscription-based filtering."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.handlers = self._load_handlers(config)
        self.subscribers = self._load_subscribers(config)
    
    def _load_handlers(self, config: Dict[str, Any]) -> List[Callable]:
        """Load output handlers based on config."""
        handler_configs = config.get("output", {}).get("handlers", ["console"])
        handlers = []
        
        for handler_name in handler_configs:
            if handler_name == "console":
                try:
                    from controllers.console import ConsoleHandler
                    handlers.append(ConsoleHandler(config))
                except ImportError:
                    # Fallback to basic handler if console not available
                    handlers.append(BaseHandler(config))
            elif handler_name == "rich":
                # Future: from controllers.rich import RichHandler
                # handlers.append(RichHandler(config))
                pass
            elif handler_name == "web":
                # Future: from controllers.web import WebHandler
                # handlers.append(WebHandler(config))
                pass
            # ... extensible
        
        return handlers
    
    def _load_subscribers(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Load output subscribers/filters based on config."""
        return config.get("output", {}).get("subscribers", [])
    
    def _should_output(self, event: OutputEvent) -> bool:
        """Check if event should be output based on subscribers."""
        if not self.subscribers:
            return True  # No filters = output everything
        
        for subscriber in self.subscribers:
            if self._matches_subscriber(event, subscriber):
                return True
        
        return False
    
    def _matches_subscriber(self, event: OutputEvent, subscriber: Dict[str, Any]) -> bool:
        """Check if event matches subscriber criteria."""
        # Check domain
        if "domain" in subscriber:
            if not self._matches_pattern(event.domain, subscriber["domain"]):
                return False
        
        # Check category
        if "category" in subscriber:
            if not self._matches_pattern(event.category, subscriber["category"]):
                return False
        
        # Check subcategory
        if "subcategory" in subscriber:
            if not self._matches_pattern(event.subcategory, subscriber["subcategory"]):
                return False
        
        # Check level
        if "level" in subscriber:
            if event.level.value not in subscriber["level"]:
                return False
        
        return True
    
    def _matches_pattern(self, value: str, pattern: str) -> bool:
        """Check if value matches pattern (supports wildcards)."""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return value.startswith(pattern[:-1])
        if pattern.startswith("*"):
            return value.endswith(pattern[1:])
        return value == pattern
    
    def _emit(self, domain: str, category: str, subcategory: str, 
              level: OutputLevel, message: str, **data):
        """Emit an output event to all matching handlers."""
        event = OutputEvent(
            domain=domain,
            category=category,
            subcategory=subcategory,
            level=level,
            message=message,
            data=data,
            timestamp=datetime.now()
        )
        
        if self._should_output(event):
            for handler in self.handlers:
                handler.handle(event)
    
    # ============================================================================
    # HIERARCHICAL OUTPUT METHODS
    # ============================================================================
    
    # Application level
    def app(self, category: str, subcategory: str, message: str, **data):
        self._emit("app", category, subcategory, OutputLevel.INFO, message, **data)
    
    def app_start(self, committee_count: int, committee_ids: List[str]):
        self.app("start", "committees", 
                f"Processing all {committee_count} committees: {', '.join(committee_ids)}",
                committee_count=committee_count, committee_ids=committee_ids)
    
    def app_committee_separator(self, committee_id: str):
        self.app("processing", "separator", f"Processing Committee: {committee_id}", 
                committee_id=committee_id)
    
    # Committee level
    def committee(self, category: str, subcategory: str, message: str, **data):
        self._emit("committee", category, subcategory, OutputLevel.INFO, message, **data)
    
    def committee_not_found(self, committee_id: str, total_committees: int):
        self.committee("error", "not_found", 
                      f"Committee {committee_id} not found among {total_committees} committees",
                      committee_id=committee_id, total_committees=total_committees)
    
    def committee_start(self, committee_name: str, committee_id: str):
        self.committee("processing", "start", 
                      f"Running basic compliance for {committee_name} [{committee_id}]...",
                      committee_name=committee_name, committee_id=committee_id)
    
    # Committee contact subdomain
    def committee_contact(self, subcategory: str, message: str, **data):
        self._emit("committee", "contact", subcategory, OutputLevel.INFO, message, **data)
    
    def committee_contact_collecting(self):
        self.committee_contact("collecting", "Collecting committee contact information...")
    
    def committee_contact_cached(self, committee_id: str):
        self.committee_contact("cached", f"Using cached contact info for committee {committee_id}",
                              committee_id=committee_id)
    
    def committee_contact_fetching(self, committee_id: str):
        self.committee_contact("fetching", f"Fetching contact info for committee {committee_id}",
                              committee_id=committee_id)
    
    def committee_contact_cached_success(self, committee_id: str):
        self.committee_contact("cached_success", f"Cached contact info for committee {committee_id}",
                              committee_id=committee_id)
    
    # Committee bills subdomain
    def committee_bills(self, subcategory: str, message: str, **data):
        self._emit("committee", "bills", subcategory, OutputLevel.INFO, message, **data)
    
    def committee_bills_found(self, count: int, limit_hearings: int):
        self.committee_bills("found", f"Found {count} bill-hearing rows (first {limit_hearings} hearing(s))",
                            count=count, limit_hearings=limit_hearings)
    
    def committee_bills_none(self):
        self.committee_bills("none", "No bill-hearing rows found")
    
    # Extension orders domain
    def extension_orders(self, category: str, subcategory: str, message: str, **data):
        self._emit("extension_orders", category, subcategory, OutputLevel.INFO, message, **data)
    
    def extension_orders_collecting(self):
        self.extension_orders("processing", "collecting", "Collecting all extension orders...")
    
    def extension_orders_disabled(self):
        self.extension_orders("processing", "disabled", "Extension checking disabled - using cached data only")
    
    def extension_orders_found(self, count: int):
        self.extension_orders("processing", "found", f"Found {count} total extension orders",
                             count=count)
    
    def extension_orders_scraping(self, search_type: str):
        self.extension_orders("scraping", "start", f"Scraping {search_type} extension orders...",
                             search_type=search_type)
    
    def extension_orders_page(self, search_type: str, page: int):
        self.extension_orders("scraping", "page", f"Scraping {search_type} page {page}...",
                             search_type=search_type, page=page)
    
    def extension_orders_error(self, search_type: str, page: int, error: str):
        self.extension_orders("scraping", "error", f"Error processing {search_type} page {page}: {error}",
                             search_type=search_type, page=page, error=error)
    
    # Bill processing domain
    def bill(self, category: str, subcategory: str, message: str, **data):
        self._emit("bill", category, subcategory, OutputLevel.INFO, message, **data)
    
    def bill_processing_start(self, total_bills: int):
        self.bill("processing", "start", f"Processing {total_bills} bills...", total_bills=total_bills)
    
    def bill_progress(self, current: int, total: int, bill_id: str, start_time: float, **kwargs):
        self.bill("processing", "progress", f"Processing {bill_id}", 
                 current=current, total=total, bill_id=bill_id, start_time=start_time, **kwargs)
    
    def bill_status(self, bill_id: str, hearing_date: date, deadline_60: date, 
                   effective_deadline: date, reported_out: bool, summary_present: bool, 
                   votes_present: bool, compliance_state: str, reason: str):
        self.bill("status", "compliance", 
                 f"{bill_id} heard {hearing_date} → D60 {deadline_60} / Eff {effective_deadline} | "
                 f"Reported: {'Y' if reported_out else 'N'} | "
                 f"Summary: {'Y' if summary_present else 'N'} | "
                 f"Votes: {'Y' if votes_present else 'N'} | "
                 f"{compliance_state.upper()} — {reason}",
                 bill_id=bill_id, hearing_date=hearing_date, deadline_60=deadline_60,
                 effective_deadline=effective_deadline, reported_out=reported_out,
                 summary_present=summary_present, votes_present=votes_present,
                 compliance_state=compliance_state, reason=reason)
    
    # Extension subdomain under bill
    def bill_extension(self, subcategory: str, message: str, **data):
        self._emit("bill", "extension", subcategory, OutputLevel.INFO, message, **data)
    
    def bill_extension_fallback_used(self, bill_id: str, extension_date: date):
        self.bill_extension("fallback_used", f"Using 30-day fallback extension: {extension_date}",
                           bill_id=bill_id, extension_date=extension_date)
    
    def bill_extension_cached_fallback_used(self, bill_id: str, extension_date: date):
        self.bill_extension("cached_fallback_used", f"Using cached 30-day fallback extension: {extension_date}",
                           bill_id=bill_id, extension_date=extension_date)
    
    def bill_extension_found(self, bill_id: str, extension_date: date):
        self.bill_extension("found", f"Found extension: {extension_date}",
                           bill_id=bill_id, extension_date=extension_date)
    
    def bill_extension_cached_found(self, bill_id: str, extension_date: date):
        self.bill_extension("cached_found", f"Found cached extension: {extension_date}",
                           bill_id=bill_id, extension_date=extension_date)
    
    def bill_extension_not_found(self, bill_id: str):
        self.bill_extension("not_found", f"No extension found for {bill_id}", bill_id=bill_id)
    
    # Parser domain
    def parser(self, category: str, subcategory: str, message: str, **data):
        self._emit("parser", category, subcategory, OutputLevel.INFO, message, **data)
    
    def parser_warning(self, parser_type: str, message: str, **kwargs):
        self.parser("warning", parser_type, f"Warning: {message}", parser_type=parser_type, **kwargs)
    
    def parser_debug(self, bill_id: str, message: str, **kwargs):
        self.parser("debug", "general", f"DEBUG: {message}", bill_id=bill_id, **kwargs)
    
    def parser_llm_fallback(self, doc_type: str, bill_id: str):
        self.parser("llm", "fallback", f"LLM unavailable for {doc_type} {bill_id}, falling back to manual review",
                   doc_type=doc_type, bill_id=bill_id)
    
    # File output domain
    def file(self, category: str, subcategory: str, message: str, **data):
        self._emit("file", category, subcategory, OutputLevel.INFO, message, **data)
    
    def file_written(self, file_path: str, file_type: str = "output"):
        self.file("output", "written", f"Wrote {file_path}", file_path=file_path, file_type=file_type)
    
    def file_json_written(self, json_path: str):
        self.file("output", "json", f"Wrote {json_path}", file_path=json_path)
    
    def file_html_written(self, html_path: str):
        self.file("output", "html", f"Wrote {html_path}", file_path=html_path)
    
    # Generic methods for flexibility
    def info(self, domain: str, category: str, subcategory: str, message: str, **data):
        self._emit(domain, category, subcategory, OutputLevel.INFO, message, **data)
    
    def warning(self, domain: str, category: str, subcategory: str, message: str, **data):
        self._emit(domain, category, subcategory, OutputLevel.WARNING, message, **data)
    
    def error(self, domain: str, category: str, subcategory: str, message: str, **data):
        self._emit(domain, category, subcategory, OutputLevel.ERROR, message, **data)
    
    def debug(self, domain: str, category: str, subcategory: str, message: str, **data):
        self._emit(domain, category, subcategory, OutputLevel.DEBUG, message, **data)
    
    def success(self, domain: str, category: str, subcategory: str, message: str, **data):
        self._emit(domain, category, subcategory, OutputLevel.SUCCESS, message, **data)


# ============================================================================
# BASE HANDLER CLASS
# ============================================================================

class BaseHandler:
    """Base class for all output handlers."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
    
    def handle(self, event: OutputEvent):
        """Handle an output event."""
        # Default implementation - can be overridden
        print(f"[{event.domain}.{event.category}.{event.subcategory}] {event.message}")
