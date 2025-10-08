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
        # Check cache first - avoids redundant requests for same URL
        if url in _URL_CACHE:
            return BeautifulSoup(_URL_CACHE[url], "html.parser")
        
        # Fetch if not cached
        r = None
        for _ in range(5):  # Retry up to 5 times
            try:
                r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
                r.raise_for_status()
                break  # Success - exit retry loop
            except (requests.RequestException, requests.Timeout):
                continue
        
        # Cache the raw HTML if we got a successful response
        if r is not None:
            _URL_CACHE[url] = r.text
            return BeautifulSoup(r.text, "html.parser")
        else:
            # All retries failed - return empty soup
            return BeautifulSoup("", "html.parser")

    @abstractmethod
    def discover(
        self, base_url: str, row: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover potential documents for parsing.

        Args:
            base_url: Base URL for the legislature website
            row: BillAtHearing object containing bill information

        Returns:
            DiscoveryResult if a document is found, else None
        """

    @abstractmethod
    def parse(
        self, base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict[str, Any]:
        """Parse the discovered document.

        Args:
            base_url: Base URL for the legislature website
            candidate: DiscoveryResult with document information from discover()

        Returns:
            Dictionary with parsed document data
        """
