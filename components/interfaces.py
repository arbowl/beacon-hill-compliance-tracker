"""Base interface for all parsers in the Massachusetts Legislature compliance
tracker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any
import sys
import time
import threading
import logging

from bs4 import BeautifulSoup
import requests  # type: ignore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from yaml import safe_load  # type: ignore

from components.models import BillAtHearing

# Setup logger
logger = logging.getLogger(__name__)


class DecayingUrlCache:
    """Smart cache with automatic garbage collection based on memory usage,
    access frequency, and recency.

    Implements dict-like interface for drop-in replacement of simple dict.
    Uses hybrid LRU+LFU eviction strategy:
    score = hit_count / time_since_access
    """

    # Configuration constants
    MAX_MEMORY_MB = 512
    EVICTION_THRESHOLD = 0.9  # Start evicting at 90% of max
    EVICTION_TARGET = 0.7     # Evict down to 70% of max

    @dataclass
    class _CacheEntry:
        """Internal cache entry with tracking metadata."""
        value: str
        hit_count: int
        last_access_time: float
        size_bytes: int

    def __init__(self) -> None:
        self._cache: dict[str, DecayingUrlCache._CacheEntry] = {}
        self._total_size_bytes: int = 0
        self._lock = threading.RLock()

    def _get_size(self, value: str) -> int:
        """Calculate size of a string in bytes."""
        return sys.getsizeof(value)

    @property
    def _max_bytes(self) -> int:
        """Maximum cache size in bytes."""
        return self.MAX_MEMORY_MB * 1024 * 1024

    @property
    def _eviction_threshold_bytes(self) -> int:
        """Byte threshold at which to trigger eviction."""
        return int(self._max_bytes * self.EVICTION_THRESHOLD)

    @property
    def _eviction_target_bytes(self) -> int:
        """Target size to evict down to."""
        return int(self._max_bytes * self.EVICTION_TARGET)

    def _should_evict(self) -> bool:
        """Check if we should trigger eviction."""
        return self._total_size_bytes >= self._eviction_threshold_bytes

    def _evict(self) -> None:
        """Evict entries until we're below target threshold.

        Uses hybrid LRU+LFU strategy: entries with low hit counts and
        distant last access times get evicted first.
        """
        if not self._cache:
            return
        current_time = time.time()
        scored_entries = [
            (
                key,
                entry.hit_count / (current_time - entry.last_access_time + 1),
                entry.size_bytes
            )
            for key, entry in self._cache.items()
        ]
        scored_entries.sort(key=lambda x: x[1])
        for key, _, size in scored_entries:
            if self._total_size_bytes <= self._eviction_target_bytes:
                break
            del self._cache[key]
            self._total_size_bytes -= size

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache (for 'in' operator)."""
        return key in self._cache

    def __getitem__(self, key: str) -> str:
        """Get value from cache, updating hit count and access time."""
        with self._lock:
            entry = self._cache[key]
            entry.hit_count += 1
            entry.last_access_time = time.time()
            return entry.value

    def __setitem__(self, key: str, value: str) -> None:
        """Set value in cache, triggering eviction if needed."""
        with self._lock:
            size = self._get_size(value)
            if key in self._cache:
                old_entry = self._cache[key]
                self._total_size_bytes -= old_entry.size_bytes
            self._cache[key] = DecayingUrlCache._CacheEntry(
                value=value,
                hit_count=1,
                last_access_time=time.time(),
                size_bytes=size
            )
            self._total_size_bytes += size
            if self._should_evict():
                self._evict()


_URL_CACHE = DecayingUrlCache()


_GLOBAL_SESSION: Optional[requests.Session] = None
_SESSION_LOCK = threading.Lock()


@dataclass
class _PendingRequest:
    """Tracks an in-flight HTTP request."""
    event: threading.Event
    result: Optional[str] = None
    error: Optional[Exception] = None


_PENDING_REQUESTS: dict[str, _PendingRequest] = {}
_PENDING_LOCK = threading.RLock()


_METRICS = {
    "cache_hits": 0,
    "cache_misses": 0,
    "dedup_waits": 0,
    "fetches": 0,
}
_METRICS_LOCK = threading.Lock()


def _get_global_session() -> requests.Session:
    """Get or create the global HTTP session with connection pooling."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is None:
        with _SESSION_LOCK:
            if _GLOBAL_SESSION is None:
                session = requests.Session()
                retry_strategy = Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504],
                    allowed_methods=["GET", "POST"]
                )
                adapter = HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=20,
                    max_retries=retry_strategy,
                    pool_block=False
                )
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                session.headers.update({
                    "User-Agent": "legis-scraper/0.1"
                })
                _GLOBAL_SESSION = session
                logger.debug("Created global HTTP session")
    return _GLOBAL_SESSION


def _fetch_with_deduplication(url: str, timeout: int = 20) -> str:
    """Fetch URL with request deduplication."""
    if url in _URL_CACHE:
        with _METRICS_LOCK:
            _METRICS["cache_hits"] += 1
        logger.debug(f"Cache hit: {url}")
        return _URL_CACHE[url]
    with _METRICS_LOCK:
        _METRICS["cache_misses"] += 1
    pending_request = None
    should_fetch = False
    with _PENDING_LOCK:
        if url in _PENDING_REQUESTS:
            pending_request = _PENDING_REQUESTS[url]
            with _METRICS_LOCK:
                _METRICS["dedup_waits"] += 1
            logger.debug(f"Dedup wait: {url} (another thread fetching)")
        else:
            pending_request = _PendingRequest(event=threading.Event())
            _PENDING_REQUESTS[url] = pending_request
            should_fetch = True
    if not should_fetch:
        pending_request.event.wait(timeout=timeout + 5)
        if pending_request.error:
            raise pending_request.error
        if pending_request.result:
            return pending_request.result
        should_fetch = True
    if should_fetch:
        try:
            session = _get_global_session()
            logger.debug(f"Fetching: {url}")
            response = None
            for attempt in range(5):
                try:
                    response = session.get(url, timeout=timeout)
                    response.raise_for_status()
                    break
                except (requests.RequestException, requests.Timeout) as e:
                    if attempt == 4:
                        raise
                    logger.debug(f"Retry {attempt + 1}/5 for {url}: {e}")
                    continue
            if response is None:
                raise requests.RequestException(
                    f"Failed to fetch {url} after 5 attempts"
                )
            result = response.text
            _URL_CACHE[url] = result
            with _METRICS_LOCK:
                _METRICS["fetches"] += 1
            with _PENDING_LOCK:
                if url in _PENDING_REQUESTS:
                    pending_request = _PENDING_REQUESTS.pop(url)
                    pending_request.result = result
                    pending_request.event.set()
            return result
        except Exception as e:
            with _PENDING_LOCK:
                if url in _PENDING_REQUESTS:
                    pending_request = _PENDING_REQUESTS.pop(url)
                    pending_request.error = e
                    pending_request.event.set()
            raise


def _fetch_binary(url: str, timeout: int = 30) -> bytes:
    """Fetch binary content (PDFs, images) via global session."""
    session = _get_global_session()
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def get_metrics() -> dict[str, int]:
    """Get connection pool metrics."""
    with _METRICS_LOCK:
        return _METRICS.copy()


def reset_metrics() -> None:
    """Reset metrics."""
    with _METRICS_LOCK:
        for key in _METRICS:
            _METRICS[key] = 0


def cleanup_session() -> None:
    """Close the global session."""
    global _GLOBAL_SESSION
    with _SESSION_LOCK:
        if _GLOBAL_SESSION:
            _GLOBAL_SESSION.close()
            _GLOBAL_SESSION = None
            logger.debug("Closed global HTTP session")


class ParserInterface(ABC):
    """Base interface that all parsers must implement."""

    # Helper classes for standardized return types:
    class ParserType(str, Enum):
        """Determines when to use a given parser"""

        SUMMARY = "summary"
        VOTES = "votes"

    @dataclass(frozen=True)
    class DiscoveryResult:
        """Result of the discover() method."""

        preview: str
        full_text: str
        source_url: str
        confidence: float

    # Mandatory fields for each implementation of this interface:
    parser_type: ParserType
    """Must declare what kind of information this looks for"""
    location: str
    """Plaintext, human-readable description of where this parser looks"""
    cost: int
    """Relative cost of running this parser (higher = more expensive)"""

    def __init_subclass__(cls, **kwargs):
        """Ensures each subclass sets required class attributes at startup"""
        super().__init_subclass__()
        if not hasattr(cls, "parser_type"):
            raise TypeError(
                f"{cls.__name__} must set class attribute 'parser_type'"
            )
        if not isinstance(
            getattr(cls, "parser_type"), ParserInterface.ParserType
        ):
            raise TypeError(
                f"{cls.__name__}.parser_type must be a ParserType enum value"
            )
        if not hasattr(cls, "cost"):
            raise TypeError(f"{cls.__name__} must set class attribute 'cost'")
        if not isinstance(getattr(cls, "cost"), int):
            raise TypeError(f"{cls.__name__}.cost must be an int")
        if not hasattr(cls, "location"):
            raise TypeError(
                f"{cls.__name__} must set class attribute 'location'"
            )
        if not isinstance(getattr(cls, "location"), str):
            raise TypeError(f"{cls.__name__}.location must be a str")

    @staticmethod
    def _soup(url: str) -> BeautifulSoup:
        """Get the soup of the page (cached by URL with deduplication)."""
        try:
            html = _fetch_with_deduplication(url, timeout=20)
            return BeautifulSoup(html, "html.parser")
        except Exception as e:
            logger.debug(f"Failed to fetch {url}: {e}")
            return BeautifulSoup("", "html.parser")

    @staticmethod
    def _fetch_binary(url: str, timeout: int = 30) -> bytes:
        """Fetch binary content (PDFs, images) via global session."""
        return _fetch_binary(url, timeout)

    @classmethod
    @abstractmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover potential documents for parsing.

        Args:
            base_url: Base URL for the legislature website
            row: BillAtHearing object containing bill information

        Returns:
            DiscoveryResult if a document is found, else None
        """

    @classmethod
    @abstractmethod
    def parse(
        cls, base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict[str, Any]:
        """Parse the discovered document.

        Args:
            base_url: Base URL for the legislature website
            candidate: DiscoveryResult with document info from discover()

        Returns:
            Dictionary with parsed document data
        """


class Config:
    """Provides an interface and safe defaults for config.yaml values."""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config: dict[str, str | dict[str, str]] = safe_load(f)

    @property
    def base_url(self) -> str:
        """Base URL for the legislature website."""
        return str(self.config.get("base_url", "https://malegislature.gov"))

    @property
    def collect_input(self) -> bool:
        """Whether to let the user select committees interactively."""
        return bool(self.config.get("collect_input", True))

    @property
    def include_chambers(self) -> list[str]:
        """Which chambers to include when collecting committees."""
        return list(self.config.get("include_chambers", ["House", "Joint"]))

    class Runner:
        """Runner configuration."""

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.runner = config.get("runner", {})

        @property
        def committee_ids(self) -> list[str]:
            """The committee IDs to include."""
            return list(self.runner.get("committee_ids", ["all"]))

        @property
        def limit_hearings(self) -> int:
            """The maximum number of hearings to process."""
            return int(self.runner.get("limit_hearings", 999))

        @property
        def check_extensions(self) -> bool:
            """Whether to check for bill extensions."""
            return bool(self.runner.get("check_extensions", False))

    @property
    def runner(self) -> Config.Runner:
        """Runner configuration."""
        return Config.Runner(self.config)

    @property
    def review_mode(self) -> bool:
        """The review mode."""
        return bool(self.config.get("review_mode", True))

    @property
    def popup_review(self) -> bool:
        """Whether to use popup review."""
        return bool(self.config.get("popup_review", False))

    class DeferredReview:
        """Deferred review configuration."""

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.deferred_review = config.get("deferred_review", {})

        @property
        def reprocess_after_review(self) -> bool:
            """Whether to reprocess after review."""
            return bool(
                self.deferred_review.get("reprocess_after_review", True)
            )

        @property
        def show_confidence(self) -> bool:
            """Whether to show the confidence score."""
            return bool(self.deferred_review.get("show_confidence", True))

        @property
        def group_by_bill(self) -> bool:
            """Whether to group by bill or chronological."""
            return bool(self.deferred_review.get("group_by_bill", False))

        @property
        def auto_accept_high_confidence(self) -> bool:
            """Whether to auto-accept high confidence parsers."""
            return bool(
                self.deferred_review.get("auto_accept_high_confidence", False)
                )

    @property
    def deferred_review(self) -> Config.DeferredReview:
        """Deferred review configuration."""
        return Config.DeferredReview(self.config)

    class Llm:

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.llm = config.get("llm", {})

        @property
        def enabled(self) -> bool:
            """Whether to enable the LLM."""
            return bool(self.llm.get("enabled", False))

        @property
        def host(self) -> str:
            """The host of the LLM."""
            return str(self.llm.get("host", "localhost"))

        @property
        def port(self) -> int:
            """The port of the LLM."""
            return int(self.llm.get("port", 11434))

        @property
        def model(self) -> str:
            """The model of the LLM."""
            return str(self.llm.get("model", "qwen3:4b"))

        @property
        def prompt(self) -> str:
            """The prompt for the LLM."""
            prompt = str(self.llm.get("prompt", """
bill_id: {bill_id}
    doc_type: {doc_type}
    content: \"\"\"{content}\"\"\"

    Answer one word (yes/no/unsure) using these rules:
    - Bill id massively increases confidence if present
      (H or S + number, with/without dot/space)
    - Wrong bill id is a strong negative indicator
    - summary → must have:
        • "Summary" near it (case insensitive), OR
        • a malegislature.gov link whose filename/title has
          bill id + "Summary", OR
        • policy/topic-style prose (not navigation, login,
          or site boilerplate).
    - vote record → look for ("vote"|"yea"|"nay"|"favorable"|
      "recommendation"|"committee")
    - Ignore boilerplate.
    Output exactly: yes|no|unsure."""))
            return prompt.strip()

        @property
        def timeout(self) -> int:
            """The timeout for the LLM request."""
            return int(self.llm.get("timeout", 120))

    @property
    def llm(self) -> Config.Llm:
        """LLM configuration."""
        return Config.Llm(self.config)

    class AuditLog:
        """Audit log for LLM decisions."""

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.audit_log = config.get("audit_log", {})

        @property
        def enabled(self) -> bool:
            """Whether to enable audit logging."""
            return bool(self.audit_log.get("enabled", True))

        @property
        def file(self) -> str:
            """The file to write the audit log to."""
            return str(self.audit_log.get("file", "out/llm_audit.log"))

        @property
        def include_timestamps(self) -> bool:
            """Include timestamps in the audit log."""
            return bool(self.audit_log.get("include_timestamps", True))

        @property
        def include_model_info(self) -> bool:
            """Include internal model info in the audit log."""
            return bool(self.audit_log.get("include_model_info", True))

    @property
    def audit_log(self) -> Config.AuditLog:
        """LLM records decisions here."""
        return Config.AuditLog(self.config)

    class Threading:
        """Threading configuration."""

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.threading = config.get("threading", {})

        @property
        def max_workers(self) -> int:
            """Number of concurrent threads for bill processing."""
            return int(self.threading.get("max_workers", 8))

    @property
    def threading(self) -> Config.Threading:
        """Threading configuration."""
        return Config.Threading(self.config)
