"""
Comprehensive audit logging system for compliance tracking runs.

Provides structured logging artifacts for debugging, compliance, and analysis.
All logging is fail-safe and has zero impact on core functionality.

Artifacts generated per run:
- manifest.json: Run metadata and execution summary
- parser_analytics.json: Parser performance and selection statistics
- bill_processing.jsonl: Line-delimited JSON of each bill's journey
- errors.json: Structured error tracking with context
- performance.json: Timing and throughput metrics
- audit.jsonl: Event-based audit trail
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from version import __version__
if TYPE_CHECKING:
    from components.interfaces import Config
    from app import Mode


logger = logging.getLogger(__name__)


@dataclass
class LogContext:
    """Thread-local context for correlating log entries."""
    run_id: str
    thread_id: int
    committee_id: Optional[str] = None
    bill_id: Optional[str] = None
    parser_module: Optional[str] = None
    stage: Optional[str] = None  # "discovery", "parsing", "classification"


class _ContextManager:
    """Manages thread-local state for log correlation."""

    def __init__(self) -> None:
        self._local = threading.local()
        self._lock = threading.Lock()

    def set_context(self, context: LogContext) -> None:
        """Set the current thread's context."""
        self._local.context = context

    def get_context(self) -> Optional[LogContext]:
        """Get the current thread's context."""
        return getattr(self._local, "context", None)

    def update(self, **kwargs) -> None:
        """Update specific fields in the current context."""
        context = self.get_context()
        if context:
            for key, value in kwargs.items():
                if hasattr(context, key):
                    setattr(context, key, value)

    def clear(self) -> None:
        """Clear the current thread's context."""
        if hasattr(self._local, "context"):
            delattr(self._local, "context")


_context = _ContextManager()


@contextmanager
def bill_context(bill_id: str):
    """Context manager to track bill processing.

    Usage:
        with bill_context("H123"):
            # All logging here will be tagged with bill_id
            process_bill()
    """
    start_time = time.time()
    _context.update(bill_id=bill_id, stage="processing")
    try:
        yield
    finally:
        elapsed = time.time() - start_time
        _context.update(bill_id=None, stage=None)


@contextmanager
def committee_context(committee_id: str):
    """Context manager to track committee processing."""
    _context.update(committee_id=committee_id)
    try:
        yield
    finally:
        _context.update(committee_id=None)


@contextmanager
def parser_context(parser_module: str, stage: str):
    """Context manager to track parser operations."""
    _context.update(parser_module=parser_module, stage=stage)
    try:
        yield
    finally:
        _context.update(parser_module=None, stage=None)


@dataclass
class BillProcessingEntry:
    """Represents a bill's processing journey."""
    timestamp: str
    bill_id: str
    committee_id: str
    stage: str  # "started", "summary_discovery", "vote_discovery", "completed"
    duration_ms: Optional[int] = None
    parser_module: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ErrorEntry:
    """Structured error record."""
    timestamp: str
    error_type: str
    message: str
    context: dict
    stack_trace: Optional[str] = None
    bill_id: Optional[str] = None
    committee_id: Optional[str] = None
    recoverable: bool = True


@dataclass
class PerformanceMetric:
    """Performance measurement."""
    metric_name: str
    value: float
    unit: str  # "seconds", "milliseconds", "count", "bytes"
    timestamp: str
    context: dict = field(default_factory=dict)


@dataclass
class AuditEvent:
    """Audit trail event."""
    timestamp: str
    event_type: str  # "config_change", "cache_update", etc.
    description: str
    actor: str  # "system", "user", "llm"
    context: dict = field(default_factory=dict)


class ManifestWriter:
    """Writes run manifest (manifest.json)."""

    def __init__(self, run_dir: Path, config: Config, mode: Mode):
        self.run_dir = run_dir
        self.config = config
        self.mode = mode
        self.start_time = datetime.utcnow()
        self.committees_processed: list[str] = []
        self.bills_processed = 0
        self.bills_succeeded = 0
        self.bills_failed = 0
        self.errors_count = 0
        self.warnings_count = 0

    def record_committee(self, committee_id: str) -> None:
        """Record that a committee was processed."""
        if committee_id not in self.committees_processed:
            self.committees_processed.append(committee_id)

    def record_bill_result(self, success: bool) -> None:
        """Record a bill processing result."""
        self.bills_processed += 1
        if success:
            self.bills_succeeded += 1
        else:
            self.bills_failed += 1

    def record_error(self, is_warning: bool = False) -> None:
        """Record an error or warning."""
        if is_warning:
            self.warnings_count += 1
        else:
            self.errors_count += 1

    def finalize(self) -> dict:
        """Generate the final manifest."""
        end_time = datetime.utcnow()
        duration_seconds = (end_time - self.start_time).total_seconds()

        manifest = {
            "run_metadata": {
                "run_id": self.run_dir.name,
                "version": __version__,
                "start_time": self.start_time.isoformat() + "Z",
                "end_time": end_time.isoformat() + "Z",
                "duration_seconds": round(duration_seconds, 2),
                "mode": {
                    "manual": self.mode.manual,
                    "one_run": self.mode.one_run,
                    "scheduled": self.mode.scheduled,
                    "check_extensions": self.mode.check_extensions,
                },
            },
            "configuration_snapshot": {
                "base_url": self.config.base_url,
                "review_mode": self.config.review_mode,
                "threading_max_workers": self.config.threading.max_workers,
                "llm_enabled": self.config.llm.enabled,
                "check_extensions": self.config.runner.check_extensions,
            },
            "execution_summary": {
                "committees_processed": self.committees_processed,
                "total_committees": len(self.committees_processed),
                "bills_processed": self.bills_processed,
                "bills_succeeded": self.bills_succeeded,
                "bills_failed": self.bills_failed,
                "success_rate": (
                    round(self.bills_succeeded / self.bills_processed * 100, 2)
                    if self.bills_processed > 0 else 0.0
                ),
            },
            "errors_and_warnings": {
                "errors": self.errors_count,
                "warnings": self.warnings_count,
            },
        }

        return manifest

    def write(self) -> None:
        """Write the manifest to disk."""
        try:
            manifest = self.finalize()
            manifest_path = self.run_dir / "manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            logger.debug("Wrote manifest: %s", manifest_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write manifest: %s", e)


class ParserAnalyticsWriter:
    """Writes parser performance data (parser_analytics.json)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.parser_attempts: dict[str, dict] = {}
        self.lock = threading.Lock()

    def record_attempt(
        self,
        parser_module: str,
        parser_type: str,  # "summary" or "votes"
        tier: int,  # 0=cached, 1=proven, 2=fallback
        success: bool,
        confidence: Optional[float] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Record a parser attempt."""
        with self.lock:
            if parser_module not in self.parser_attempts:
                self.parser_attempts[parser_module] = {
                    "parser_module": parser_module,
                    "parser_type": parser_type,
                    "total_attempts": 0,
                    "successful_attempts": 0,
                    "failed_attempts": 0,
                    "tier_usage": {"cached": 0, "proven": 0, "fallback": 0},
                    "avg_confidence": 0.0,
                    "confidence_samples": [],
                    "avg_duration_ms": 0.0,
                    "duration_samples": [],
                }

            stats = self.parser_attempts[parser_module]
            stats["total_attempts"] += 1

            if success:
                stats["successful_attempts"] += 1
            else:
                stats["failed_attempts"] += 1

            # Record tier usage
            tier_names = {0: "cached", 1: "proven", 2: "fallback"}
            if tier in tier_names:
                stats["tier_usage"][tier_names[tier]] += 1

            # Track confidence scores
            if confidence is not None:
                stats["confidence_samples"].append(confidence)
                stats["avg_confidence"] = sum(
                    stats["confidence_samples"]
                ) / len(
                    stats["confidence_samples"]
                )

            # Track duration
            if duration_ms is not None:
                stats["duration_samples"].append(duration_ms)
                stats["avg_duration_ms"] = sum(
                    stats["duration_samples"]
                ) / len(
                    stats["duration_samples"]
                )

    def finalize(self) -> dict:
        """Generate the final analytics."""
        with self.lock:
            # Clean up samples (don't need full history in output)
            for stats in self.parser_attempts.values():
                del stats["confidence_samples"]
                del stats["duration_samples"]

            analytics = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "parser_statistics": list(self.parser_attempts.values()),
                "summary": {
                    "total_parsers_used": len(self.parser_attempts),
                    "total_attempts": sum(
                        p["total_attempts"]
                        for p in self.parser_attempts.values()
                    ),
                    "total_successes": sum(
                        p["successful_attempts"]
                        for p in self.parser_attempts.values()
                    ),
                    "total_failures": sum(
                        p["failed_attempts"]
                        for p in self.parser_attempts.values()
                    ),
                },
            }

            return analytics

    def write(self) -> None:
        """Write parser analytics to disk."""
        try:
            analytics = self.finalize()
            analytics_path = self.run_dir / "parser_analytics.json"
            with open(analytics_path, "w", encoding="utf-8") as f:
                json.dump(analytics, f, indent=2)
            logger.debug("Wrote parser analytics: %s", analytics_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write parser analytics: %s", e)


class BillProcessingWriter:
    """Writes bill-by-bill log (bill_processing.jsonl)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.log_path = run_dir / "bill_processing.jsonl"
        self.lock = threading.Lock()
        # Open file in append mode for streaming writes
        self.file_handle = None

    def open(self) -> None:
        """Open the log file for writing."""
        try:
            self.file_handle = open(
                self.log_path, "w", encoding="utf-8", buffering=1
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to open bill processing log: %s", e)

    def log_entry(self, entry: BillProcessingEntry) -> None:
        """Log a bill processing entry."""
        if not self.file_handle:
            return

        try:
            with self.lock:
                entry_dict = asdict(entry)
                json.dump(entry_dict, self.file_handle)
                self.file_handle.write("\n")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write bill processing entry: %s", e)

    def close(self) -> None:
        """Close the log file."""
        if self.file_handle:
            try:
                self.file_handle.close()
                logger.debug("Wrote bill processing log: %s", self.log_path)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to close bill processing log: %s", e)


class ErrorLedgerWriter:
    """Writes structured errors (errors.json)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.errors: list[ErrorEntry] = []
        self.lock = threading.Lock()

    def record_error(
        self,
        error_type: str,
        message: str,
        context: dict,
        exception: Optional[Exception] = None,
        recoverable: bool = True,
    ) -> None:
        """Record an error."""
        with self.lock:
            ctx = _context.get_context()
            error_entry = ErrorEntry(
                timestamp=datetime.utcnow().isoformat() + "Z",
                error_type=error_type,
                message=message,
                context=context,
                stack_trace=(
                    "".join(
                        traceback.format_exception(
                            type(exception), exception, exception.__traceback__
                        )
                    )
                    if exception
                    else None
                ),
                bill_id=ctx.bill_id if ctx else None,
                committee_id=ctx.committee_id if ctx else None,
                recoverable=recoverable,
            )
            self.errors.append(error_entry)

    def finalize(self) -> dict:
        """Generate the final error ledger."""
        with self.lock:
            ledger = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "total_errors": len(self.errors),
                "recoverable_errors": sum(
                    1 for e in self.errors if e.recoverable
                ),
                "fatal_errors": sum(
                    1 for e in self.errors if not e.recoverable
                ),
                "errors": [asdict(e) for e in self.errors],
            }
            return ledger

    def write(self) -> None:
        """Write error ledger to disk."""
        try:
            ledger = self.finalize()
            ledger_path = self.run_dir / "errors.json"
            with open(ledger_path, "w", encoding="utf-8") as f:
                json.dump(ledger, f, indent=2)
            logger.debug("Wrote error ledger: %s", ledger_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write error ledger: %s", e)


class PerformanceWriter:
    """Writes performance metrics (performance.json)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.metrics: list[PerformanceMetric] = []
        self.lock = threading.Lock()
        self.timers: dict[str, float] = {}

    def start_timer(self, timer_name: str) -> None:
        """Start a named timer."""
        with self.lock:
            self.timers[timer_name] = time.time()

    def end_timer(
        self, timer_name: str, context: Optional[dict] = None
    ) -> None:
        """End a named timer and record the metric."""
        with self.lock:
            if timer_name not in self.timers:
                return

            elapsed = time.time() - self.timers[timer_name]
            del self.timers[timer_name]

            metric = PerformanceMetric(
                metric_name=timer_name,
                value=round(elapsed, 3),
                unit="seconds",
                timestamp=datetime.utcnow().isoformat() + "Z",
                context=context or {},
            )
            self.metrics.append(metric)

    def record_metric(
        self,
        metric_name: str,
        value: float,
        unit: str,
        context: Optional[dict] = None,
    ) -> None:
        """Record a metric directly."""
        with self.lock:
            metric = PerformanceMetric(
                metric_name=metric_name,
                value=value,
                unit=unit,
                timestamp=datetime.utcnow().isoformat() + "Z",
                context=context or {},
            )
            self.metrics.append(metric)

    def finalize(self) -> dict:
        """Generate the final performance report."""
        with self.lock:
            # Group metrics by name for summary statistics
            grouped: dict[str, list[float]] = {}
            for metric in self.metrics:
                if metric.metric_name not in grouped:
                    grouped[metric.metric_name] = []
                grouped[metric.metric_name].append(metric.value)

            summary = {}
            for name, values in grouped.items():
                summary[name] = {
                    "count": len(values),
                    "min": round(min(values), 3),
                    "max": round(max(values), 3),
                    "avg": round(sum(values) / len(values), 3),
                    "total": round(sum(values), 3),
                }

            performance = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "summary": summary,
                "detailed_metrics": [asdict(m) for m in self.metrics],
            }

            return performance

    def write(self) -> None:
        """Write performance metrics to disk."""
        try:
            performance = self.finalize()
            perf_path = self.run_dir / "performance.json"
            with open(perf_path, "w", encoding="utf-8") as f:
                json.dump(performance, f, indent=2)
            logger.debug("Wrote performance metrics: %s", perf_path)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write performance metrics: %s", e)


class AuditTrailWriter:
    """Writes event audit trail (audit.jsonl)."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.log_path = run_dir / "audit.jsonl"
        self.lock = threading.Lock()
        self.file_handle = None

    def open(self) -> None:
        """Open the audit log file."""
        try:
            self.file_handle = open(
                self.log_path, "w", encoding="utf-8", buffering=1
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to open audit log: %s", e)

    def log_event(
        self,
        event_type: str,
        description: str,
        actor: str = "system",
        context: Optional[dict] = None,
    ) -> None:
        """Log an audit event."""
        if not self.file_handle:
            return

        try:
            with self.lock:
                event = AuditEvent(
                    timestamp=datetime.utcnow().isoformat() + "Z",
                    event_type=event_type,
                    description=description,
                    actor=actor,
                    context=context or {},
                )
                json.dump(asdict(event), self.file_handle)
                self.file_handle.write("\n")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to write audit event: %s", e)

    def close(self) -> None:
        """Close the audit log."""
        if self.file_handle:
            try:
                self.file_handle.close()
                logger.debug("Wrote audit trail: %s", self.log_path)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to close audit log: %s", e)


class RunLogger:
    """
    Main logging orchestrator - use as context manager.

    Usage:
        with RunLogger(config, mode) as run_logger:
            # Your code runs here
            # All logging happens automatically

    This class:
    - Creates a unique run directory
    - Initializes all log writers
    - Hooks into Python's logging system
    - Captures metrics and errors
    - Writes all artifacts on exit
    """

    def __init__(self, config: Config, mode: Mode):
        self.config = config
        self.mode = mode
        self.enabled = config.logging.enabled
        self.run_dir: Optional[Path] = None
        self.run_id: Optional[str] = None

        # Writers (initialized in __enter__)
        self.manifest_writer: Optional[ManifestWriter] = None
        self.parser_analytics_writer: Optional[ParserAnalyticsWriter] = None
        self.bill_processing_writer: Optional[BillProcessingWriter] = None
        self.error_ledger_writer: Optional[ErrorLedgerWriter] = None
        self.performance_writer: Optional[PerformanceWriter] = None
        self.audit_trail_writer: Optional[AuditTrailWriter] = None

        # Logging handler
        self.log_handler: Optional[logging.Handler] = None

    def __enter__(self) -> "RunLogger":
        """Initialize logging system."""
        if not self.enabled:
            logger.info("Audit logging disabled in configuration")
            return self

        try:
            # Create run directory with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            mode_str = "manual"
            if self.mode.one_run:
                mode_str = "one-run"
            elif self.mode.scheduled:
                mode_str = "scheduled"

            # Include committee IDs in directory name if applicable
            committee_ids = self.config.runner.committee_ids
            if committee_ids and committee_ids != ["all"]:
                committees_str = "_".join(committee_ids[:3])
                if len(committee_ids) > 3:
                    committees_str += f"_plus{len(committee_ids) - 3}"
                self.run_id = f"{timestamp}_{mode_str}_{committees_str}"
            else:
                self.run_id = f"{timestamp}_{mode_str}_all"

            self.run_dir = Path(self.config.logging.output_dir) / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Audit logging enabled: %s", self.run_dir)

            # Initialize context
            _context.set_context(
                LogContext(
                    run_id=self.run_id,
                    thread_id=threading.get_ident(),
                )
            )

            # Initialize writers based on configuration
            if self.config.logging.components.manifest:
                self.manifest_writer = ManifestWriter(
                    self.run_dir, self.config, self.mode
                )

            if self.config.logging.components.parser_analytics:
                self.parser_analytics_writer = ParserAnalyticsWriter(
                    self.run_dir
                )

            if self.config.logging.components.bill_processing:
                self.bill_processing_writer = BillProcessingWriter(
                    self.run_dir
                )
                self.bill_processing_writer.open()

            if self.config.logging.components.errors:
                self.error_ledger_writer = ErrorLedgerWriter(self.run_dir)

            if self.config.logging.components.performance:
                self.performance_writer = PerformanceWriter(self.run_dir)
                self.performance_writer.start_timer("total_run_time")

            if self.config.logging.components.audit:
                self.audit_trail_writer = AuditTrailWriter(self.run_dir)
                self.audit_trail_writer.open()
                self.audit_trail_writer.log_event(
                    "run_started",
                    f"Compliance run started in {mode_str} mode",
                    context={"committees": committee_ids},
                )

            # Hook into Python logging to capture all log messages
            self._install_log_handler()

            logger.info("Audit logging system initialized successfully")

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to initialize audit logging: %s", e, exc_info=True)
            self.enabled = False

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Finalize and write all logs."""
        if not self.enabled or not self.run_dir:
            return False

        try:
            # Log any exception that occurred
            if exc_type is not None and self.error_ledger_writer:
                self.error_ledger_writer.record_error(
                    error_type=exc_type.__name__,
                    message=str(exc_val),
                    context={"traceback": traceback.format_tb(exc_tb)},
                    exception=exc_val,
                    recoverable=False,
                )

            # Stop performance timer
            if self.performance_writer:
                self.performance_writer.end_timer("total_run_time")

            # Log completion
            if self.audit_trail_writer:
                self.audit_trail_writer.log_event(
                    "run_completed",
                    "Compliance run completed",
                    context={"success": exc_type is None},
                )

            # Close streaming logs
            if self.bill_processing_writer:
                self.bill_processing_writer.close()

            if self.audit_trail_writer:
                self.audit_trail_writer.close()

            # Write final artifacts
            if self.manifest_writer:
                self.manifest_writer.write()

            if self.parser_analytics_writer:
                self.parser_analytics_writer.write()

            if self.error_ledger_writer:
                self.error_ledger_writer.write()

            if self.performance_writer:
                self.performance_writer.write()

            # Remove log handler
            self._remove_log_handler()

            # Cleanup old runs if retention is configured
            self._cleanup_old_runs()

            logger.info("Audit artifacts written to: %s", self.run_dir)

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to finalize audit logging: %s", e, exc_info=True)

        finally:
            _context.clear()

        # Don't suppress exceptions
        return False

    def _install_log_handler(self) -> None:
        """Install a handler to capture Python logging output."""

        class AuditLogHandler(logging.Handler):
            """Captures log records for audit trail."""

            def __init__(self, run_logger: RunLogger):
                super().__init__()
                self.run_logger = run_logger

            def emit(self, record: logging.LogRecord):
                try:
                    # Record errors in error ledger
                    if (
                        record.levelno >= logging.ERROR
                        and self.run_logger.error_ledger_writer
                    ):
                        self.run_logger.error_ledger_writer.record_error(
                            error_type=record.levelname,
                            message=record.getMessage(),
                            context={
                                "logger": record.name,
                                "module": record.module,
                                "function": record.funcName,
                                "line": record.lineno,
                            },
                            recoverable=record.levelno < logging.CRITICAL,
                        )

                        # Update manifest error count
                        if self.run_logger.manifest_writer:
                            self.run_logger.manifest_writer.record_error(
                                is_warning=(record.levelno == logging.WARNING)
                            )

                except Exception:
                    # Don't let logging errors break the application
                    pass

        try:
            self.log_handler = AuditLogHandler(self)
            self.log_handler.setLevel(logging.WARNING)
            logging.root.addHandler(self.log_handler)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to install log handler: %s", e)

    def _remove_log_handler(self) -> None:
        """Remove the audit log handler."""
        if self.log_handler:
            try:
                logging.root.removeHandler(self.log_handler)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to remove log handler: %s", e)

    def _cleanup_old_runs(self) -> None:
        """Remove old run directories based on retention policy."""
        if self.config.logging.retention_days <= 0:
            return  # Keep forever

        try:
            runs_dir = Path(self.config.logging.output_dir)
            if not runs_dir.exists():
                return

            cutoff_time = time.time() - (
                self.config.logging.retention_days * 86400
            )

            for run_dir in runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue

                # Check if directory is older than retention period
                if run_dir.stat().st_mtime < cutoff_time:
                    try:
                        # Remove directory and all contents
                        import shutil

                        shutil.rmtree(run_dir)
                        logger.debug("Removed old run directory: %s", run_dir)
                    # pylint: disable=broad-exception-caught
                    except Exception as e:
                        logger.warning(
                            "Failed to remove old run %s: %s",
                            run_dir,
                            e,
                        )

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to cleanup old runs: %s", e)

# These are module-level functions that provide easy access to logging
# functionality from other modules without needing to pass RunLogger around

def get_current_logger() -> Optional[RunLogger]:
    """Get the current RunLogger instance if available."""
    # This would require storing the instance globally, which we'll skip
    # for now to keep the design simple. If needed, we can add this later.
    return None


def log_bill_started(bill_id: str, committee_id: str) -> None:
    """Log that bill processing started."""
    # Access writers through context if needed


def log_parser_attempt(
    parser_module: str,
    parser_type: str,
    tier: int,
    success: bool,
    confidence: Optional[float] = None,
) -> None:
    """Log a parser attempt."""
    # This would need access to the ParserAnalyticsWriter

# For now, these are stubs. The main usage pattern is through the
# RunLogger context manager, which is sufficient for MVP.
