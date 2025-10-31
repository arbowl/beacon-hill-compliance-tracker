"""Base interface for all parsers in the Massachusetts Legislature compliance
tracker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Any, TYPE_CHECKING
import sys
import time
import threading
import logging
from datetime import datetime

from bs4 import BeautifulSoup
import requests  # type: ignore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from yaml import safe_load  # type: ignore

from components.models import BillAtHearing
if TYPE_CHECKING:
    from components.utils import Cache

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


class _SessionManager:
    """Manages HTTP session lifecycle without global keyword."""

    def __init__(self) -> None:
        self._session: Optional[requests.Session] = None
        self._lock = threading.Lock()

    def get_session(self) -> requests.Session:
        """Get or create the HTTP session with connection pooling."""
        if self._session is None:
            with self._lock:
                if self._session is None:
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
                    self._session = session
                    logger.debug("Created global HTTP session")
        return self._session

    def cleanup(self) -> None:
        """Close the session."""
        with self._lock:
            if self._session:
                self._session.close()
                self._session = None
                logger.debug("Closed global HTTP session")


_SESSION_MANAGER = _SessionManager()


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


def _fetch_with_deduplication(url: str, timeout: int = 20) -> str:
    """Fetch URL with request deduplication."""
    if url in _URL_CACHE:
        with _METRICS_LOCK:
            _METRICS["cache_hits"] += 1
        logger.debug("Cache hit: %s", url)
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
            logger.debug("Dedup wait: %s (another thread fetching)", url)
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
            session = _SESSION_MANAGER.get_session()
            logger.debug("Fetching: %s", url)
            response = None
            for attempt in range(5):
                try:
                    response = session.get(url, timeout=timeout)
                    response.raise_for_status()
                    break
                except (requests.RequestException, requests.Timeout) as e:
                    if attempt == 4:
                        raise
                    logger.debug("Retry %d/5 for %s: %s", attempt + 1, url, e)
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
    raise RuntimeError("Unexpected state in _fetch_with_deduplication")


def _fetch_binary(
    url: str,
    timeout: int = 30,
    cache: Optional[Cache] = None,
    config: Optional[Config] = None
) -> bytes:
    """Fetch binary content (PDFs, images) via global session with caching."""
    if cache and config:
        cached_content = cache.get_cached_document_content(url, config)
        if cached_content:
            logger.debug("Using cached document: %s", url)
            return cached_content
        cached_entry = cache.get_cached_document(url, config)
        if cached_entry:
            session = _SESSION_MANAGER.get_session()
            headers = {}
            if cached_entry.get("etag"):
                headers["If-None-Match"] = cached_entry["etag"]
            if cached_entry.get("last_modified"):
                headers["If-Modified-Since"] = cached_entry["last_modified"]
            if headers:
                try:
                    response = session.get(url, timeout=timeout, headers=headers)
                    if response.status_code == 304:
                        logger.debug("Document not modified (304): %s", url)
                        cache_entry = cache.data["document_cache"]["by_url"][url]
                        cache_entry["last_validated"] = (
                            datetime.utcnow().isoformat(timespec="seconds") + "Z"
                        )
                        cache.save()
                        cached_file_path = Path(cached_entry["cached_file_path"])
                        return cached_file_path.read_bytes()
                    elif response.status_code == 200:
                        logger.debug("Document modified, updating cache: %s", url)
                        content = response.content
                        cache.cache_document(
                            url=url,
                            content=content,
                            config=config,
                            content_type=response.headers.get(
                                "Content-Type", "application/octet-stream"
                            ),
                            etag=response.headers.get("ETag"),
                            last_modified=response.headers.get("Last-Modified")
                        )
                        return content
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("Conditional request failed: %s, fetching normally", e)
    session = _SESSION_MANAGER.get_session()
    logger.debug("Fetching document: %s", url)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    content = response.content
    if cache and config and config.document_cache.enabled:
        try:
            cache.cache_document(
                url=url,
                content=content,
                config=config,
                content_type=response.headers.get(
                    "Content-Type", "application/octet-stream"
                ),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified")
            )
            logger.debug("Cached document: %s", url)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to cache document %s: %s", url, e)
    return content


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
    _SESSION_MANAGER.cleanup()


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
    def soup(url: str) -> BeautifulSoup:
        """Get the soup of the page (cached by URL with deduplication)."""
        try:
            html = _fetch_with_deduplication(url, timeout=20)
            return BeautifulSoup(html, "html.parser")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to fetch %s: %s", url, e)
            return BeautifulSoup("", "html.parser")

    @staticmethod
    def _fetch_binary(
        url: str,
        timeout: int = 30,
        cache: Optional[Any] = None,
        config: Optional[Any] = None
    ) -> bytes:
        """Fetch binary content (PDFs, images) via global session with caching."""
        return _fetch_binary(url, timeout, cache, config)

    @classmethod
    @abstractmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache: Optional[Any] = None,
        config: Optional[Any] = None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover potential documents for parsing."""

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
        """LLM configuration."""

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
        def diff_report_analysis_prompt(self) -> str:
            """The prompt for diff report analysis."""
            default_prompt = """You are a legislative data analyst generating a daily operational brief for the Massachusetts Beacon Hill Compliance Tracker.

**Massachusetts Legislative Committee Compliance Analysis**
**Committee:** {committee_name}
**Period:** {previous_date} to {current_date} ({time_interval} ago)

**Reported Metrics**
- Compliance delta: {compliance_delta} percentage points
- New bills: {new_bills_count}
- Bills with new hearings: {bills_with_new_hearings_count}
- Bills reported out of committee: {bills_reported_out_count}
- Bills with new summaries: {bills_with_new_summaries_count}

**New Bills**
{new_bills_details}

**Bills with New Hearings**
{bills_with_new_hearings_details}

**Bills Reported Out**
{bills_reported_out_details}

**Bills with New Summaries**
{bills_with_new_summaries_details}

**Legislative Transparency Context**
In 2025, the Massachusetts Legislature strengthened its joint rules to improve public visibility: hearings must be publicly noticed at least ten days in advance, committee votes and attendance must be posted, and plain-language summaries must be available before or soon after hearings.  
Your analysis should interpret changes in light of these obligations.

**IMPORTANT: Committee Scope**
This analysis focuses specifically on the {committee_name} committee. The dataset you are commenting on belongs to this committee alone, not the whole Massachusetts Legislature. The tracker monitors approximately 35 committees, but this report reflects changes only for {committee_name}. Daily changes typically reflect a small number of committee postings for this specific committee, not system-wide policy shifts.
You aren't seeing all the bills analyzed in this dataset--you're just seeing day-to-day differences, so don't make too many assumptions about the relationship between what's new and what's required. New items generally need time to have documentation posted.

**Your Task**
Write a concise 3–4 sentence brief that:

1. States whether compliance rose, fell, or remained stable — quantify the change.  
2. Identifies which activities (hearings, reports, summaries) most affected the shift.  
3. Notes any behavior that aligns with or deviates from transparency requirements (e.g., delayed postings, clustering before deadlines). 

Tone: neutral, factual, and concise.  
Avoid adjectives such as "promising," "concerning," or "disappointing."  
Use analytic verbs — "rose," "declined," "remained," "corresponded," "reflected."  
Each sentence should deliver a verifiable observation, not interpretation."""
            prompt = str(
                self.llm.get("diff_report_analysis_prompt", default_prompt)
            )
            return prompt.strip()

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

    class DocumentCache:
        """Document cache configuration."""

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.document_cache = config.get("document_cache", {})

        @property
        def enabled(self) -> bool:
            """Whether to enable document caching."""
            return bool(self.document_cache.get("enabled", True))

        @property
        def directory(self) -> str:
            """Directory for cached documents."""
            return str(self.document_cache.get("directory", "cache/documents"))

        @property
        def extracted_text_directory(self) -> str:
            """Directory for extracted text."""
            return str(
                self.document_cache.get(
                    "extracted_text_directory", "cache/extracted"
                )
            )

        @property
        def max_size_mb(self) -> int:
            """Maximum cache size in MB."""
            return int(self.document_cache.get("max_size_mb", 5120))

        @property
        def max_age_days(self) -> int:
            """Maximum age of cached documents in days."""
            return int(self.document_cache.get("max_age_days", 180))

        @property
        def validate_after_days(self) -> int:
            """Validate cached documents after N days."""
            return int(self.document_cache.get("validate_after_days", 7))

        @property
        def store_extracted_text(self) -> bool:
            """Store extracted text from PDFs/DOCX."""
            return bool(self.document_cache.get("store_extracted_text", True))

    @property
    def document_cache(self) -> Config.DocumentCache:
        """Document cache configuration."""
        return Config.DocumentCache(self.config)
