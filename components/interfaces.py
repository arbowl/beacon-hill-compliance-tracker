"""Base interface for all parsers in the Massachusetts Legislature compliance
tracker.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any

from bs4 import BeautifulSoup
import requests
from yaml import safe_load

from components.models import BillAtHearing


# Module-level cache for URL responses (cleared between runs)
_URL_CACHE: dict[str, str] = {}


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
            raise TypeError(f"{cls.__name__} must set class attribute 'parser_type'")
        if not isinstance(getattr(cls, "parser_type"), ParserInterface.ParserType):
            raise TypeError(f"{cls.__name__}.parser_type must be a ParserType enum value")
        if not hasattr(cls, "cost"):
            raise TypeError(f"{cls.__name__} must set class attribute 'cost'")
        if not isinstance(getattr(cls, "cost"), int):
            raise TypeError(f"{cls.__name__}.cost must be an int")
        if not hasattr(cls, "location"):
            raise TypeError(f"{cls.__name__} must set class attribute 'location'")
        if not isinstance(getattr(cls, "location"), str):
            raise TypeError(f"{cls.__name__}.location must be a str")

    @staticmethod
    def _soup(s: requests.Session, url: str) -> BeautifulSoup:
        """Get the soup of the page (cached by URL)."""
        if url in _URL_CACHE:
            return BeautifulSoup(_URL_CACHE[url], "html.parser")
        r = None
        for _ in range(5):
            try:
                r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
                r.raise_for_status()
                break
            except (requests.RequestException, requests.Timeout):
                continue
        if r is not None:
            _URL_CACHE[url] = r.text
            return BeautifulSoup(r.text, "html.parser")
        else:
            return BeautifulSoup("", "html.parser")

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
            candidate: DiscoveryResult with document information from discover()

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
        return self.config.get("base_url", "https://malegislature.gov")

    @property
    def collect_input(self) -> bool:
        """Whether to let the user select committees interactively."""
        return self.config.get("collect_input", True)

    @property
    def include_chambers(self) -> list[str]:
        """Which chambers to include when collecting committees."""
        return self.config.get("include_chambers", ["House", "Joint"])

    class Runner:

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.runner = config.get("runner", {})

        @property
        def committee_ids(self) -> list[str]:
            return self.runner.get("committee_ids", ["all"])
    
        @property
        def limit_hearings(self) -> int:
            return self.runner.get("limit_hearings", 999)
        
        @property
        def check_extensions(self) -> bool:
            return self.runner.get("check_extensions", False)

    @property
    def runner(self) -> Config.Runner:
        return Config.Runner(self.config)

    @property
    def review_mode(self) -> bool:
        return self.config.get("review_mode", True)

    @property
    def popup_review(self) -> bool:
        return self.config.get("popup_review", False)

    class DeferredReview:

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.deferred_review = config.get("deferred_review", {})

        @property
        def reprocess_after_review(self) -> int:
            return self.deferred_review.get("reprocess_after_review", 5)

        @property
        def show_confidence(self) -> bool:
            return self.deferred_review.get("show_confidence", True)
    
        @property
        def group_by_bill(self) -> bool:
            return self.deferred_review.get("group_by_bill", False)
    
        @property
        def auto_accept_high_confidence(self) -> bool:
            return self.deferred_review.get("auto_accept_high_confidence", False)

    @property
    def deferred_review(self) -> Config.DeferredReview:
        return Config.DeferredReview(self.config)

    class Llm:

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.llm = config.get("llm", {})

        @property
        def enabled(self) -> bool:
            return self.llm.get("enabled", False)
    
        @property
        def host(self) -> str:
            return self.llm.get("host", "localhost")
    
        @property
        def port(self) -> int:
            return self.llm.get("port", 11434)
    
        @property
        def model(self) -> str:
            return self.llm.get("model", "qwen3:4b")
    
        @property
        def prompt(self) -> str:
            prompt = self.llm.get("prompt", """
bill_id: {bill_id}
    doc_type: {doc_type}
    content: \"\"\"{content}\"\"\"

    Answer one word (yes/no/unsure) using these rules:
    - Bill id massively increases confidence if present (H or S + number, with/without dot/space)
    - Wrong bill id is a strong negative indicator
    - summary → must have:
        • "Summary" near it (case insensitive), OR
        • a malegislature.gov link whose filename/title has bill id + "Summary", OR
        • policy/topic-style prose (not navigation, login, or site boilerplate).
    - vote record → look for ("vote"|"yea"|"nay"|"favorable"|"recommendation"|"committee")
    - Ignore boilerplate.
    Output exactly: yes|no|unsure.""")
            return prompt.strip()
        
        @property
        def timeout(self) -> int:
            return self.llm.get("timeout", 120)
    
    @property
    def llm(self) -> Config.Llm:
        return Config.Llm(self.config)

    class AuditLog:

        def __init__(self, config: dict[str, str | dict[str, str]]) -> None:
            self.audit_log = config.get("audit_log", {})

        @property
        def enabled(self) -> bool:
            return self.audit_log.get("enabled", True)
    
        @property
        def file(self) -> str:
            return self.audit_log.get("file", "out/llm_audit.log")
    
        @property
        def include_timestamps(self) -> bool:
            return self.audit_log.get("include_timestamps", True)
    
        @property
        def include_model_info(self) -> bool:
            return self.audit_log.get("include_model_info", True)
    
    @property
    def audit_log(self) -> Config.AuditLog:
        return Config.AuditLog(self.config)
