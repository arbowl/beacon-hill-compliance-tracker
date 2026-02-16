"""A parser for when the summary is on the bill's Summary tab."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)


class SummaryBillTabTextParser(ParserInterface):
    """Parser for when the summary is on the bill's Summary tab."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Bill page summary tab"
    cost = 2
    file_format = "html"

    @staticmethod
    def _normalize_bill_url(bill_url: str) -> str:
        """
        Normalize bill URL by removing trailing /Bills/<chamber>/ patterns.

        Some bill URLs end with patterns like /Bills/Joint/, /Bills/House/, or
        /Bills/Senate/. These need to be stripped before appending paths like
        /PrimarySponsorSummary, otherwise the resulting URL will 404.

        Examples:
        - https://malegislature.gov/Bills/194/S404/Bills/Joint/
          -> https://malegislature.gov/Bills/194/S404/
        - https://malegislature.gov/Bills/194/H123/
          -> https://malegislature.gov/Bills/194/H123/
        """
        # Remove trailing /Bills/<chamber>/ patterns
        # Match: /Bills/Joint/, /Bills/House/, /Bills/Senate/ at the end
        normalized = re.sub(r"/Bills/(?:Joint|House|Senate)/?$", "", bill_url)
        # Remove trailing slashes to cleanly append /PrimarySponsorSummary
        return normalized.rstrip("/")

    @staticmethod
    def _find_summary_tab_link(soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find the summary tab link."""
        for a in soup.select("a[href]"):
            if re.search(r"\bsummary\b", a.get_text(strip=True), re.I):
                return str(urljoin(base_url, str(a["href"])))
        return None

    @staticmethod
    def _extract_summary_content(text: str) -> Optional[str]:
        """Extract the actual summary content from the page text."""
        # Common field labels that might appear after the summary
        field_label_pattern = (
            r"(?:Topic|Bill History|Cosponsor|Petitioners"
            r"|Status|Legislative History)\s*:"
        )
        summary_patterns = [
            (
                r"Bill Section by Section Summary[^–:]*[–:]\s*(.+?)"
                r"(?=\n\n|\n[A-Z]+\s*:|" + field_label_pattern + r"|$)"
            ),
            (
                r"Summary[^–:]*[–:]\s*(.+?)(?=\n\n|\n[A-Z]+\s*:|"
                + field_label_pattern
                + r"|$)"
            ),
            (
                r"Bill Summary[^–:]*[–:]\s*(.+?)(?=\n\n|\n[A-Z]+\s*:|"
                + field_label_pattern
                + r"|$)"
            ),
        ]
        for pattern in summary_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                summary_text = match.group(1).strip()
                summary_text = re.sub(r"\s+", " ", summary_text)
                nav_pattern = (
                    r"(Skip to Content|Menu Toggle|Sign in|"
                    r"MyLegislature).*?(?=Bill|Summary)"
                )
                summary_text = re.sub(
                    nav_pattern, "", summary_text, flags=re.DOTALL | re.IGNORECASE
                )
                if len(summary_text) > 50:
                    return summary_text
        headers = ["Bill Section by Section Summary", "Summary", "Bill Summary"]
        for header in headers:
            if header in text:
                start = text.find(header)
                content_start = start + len(header)
                while content_start < len(text) and text[content_start] in "–-: ":
                    content_start += 1
                remaining_text = text[content_start:]
                # Updated end patterns to work with flattened text
                end_patterns = [
                    r"\n[A-Z][A-Z\s]+\s*:",  # Newline + all caps label
                    r"\n\n[A-Z][A-Z\s]+$",  # Two newlines + all caps at end
                    r"\n\s*$",  # Newline + whitespace at end
                    field_label_pattern,  # Field labels
                    (
                        r"\s+(?:Topic|Bill History|Cosponsor|Petitioners|"
                        r"Status|Legislative History)\s*:"
                    ),  # Field labels with space
                ]
                end_pos = len(remaining_text)
                for pattern in end_patterns:
                    match = re.search(pattern, remaining_text, re.IGNORECASE)
                    if match:
                        end_pos = min(end_pos, match.start())
                summary_text = remaining_text[:end_pos].strip()
                summary_text = re.sub(r"\s+", " ", summary_text)
                if len(summary_text) > 50:
                    return summary_text
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the summary."""
        logger.debug("Trying %s...", cls.__name__)
        bill_url = cls._normalize_bill_url(bill.bill_url)
        soup = cls.soup(f"{bill_url}/PrimarySponsorSummary", cache=cache, config=config)
        tab_panel = soup.find(
            "div", attrs={"aria-labelledby": re.compile("PrimarySponsorSummary", re.I)}
        )
        if tab_panel:
            text = " ".join(tab_panel.get_text(" ", strip=True).split())
            if text:
                # Extract actual summary content, not just tab text
                full_text = cls._extract_summary_content(text)
                if full_text:
                    preview = full_text[:500] + ("..." if len(full_text) > 500 else "")
                    return ParserInterface.DiscoveryResult(
                        preview,
                        full_text,
                        f"{bill_url}/PrimarySponsorSummary",
                        0.95,
                    )
        summary_div = soup.find(id=re.compile("Summary", re.I)) or soup.find(
            "div", class_=re.compile("Summary", re.I)
        )
        if summary_div:
            text = " ".join(summary_div.get_text(" ", strip=True).split())
            if text:
                full_text = cls._extract_summary_content(text)
                if full_text:
                    preview = full_text[:500] + ("..." if len(full_text) > 500 else "")
                    return ParserInterface.DiscoveryResult(
                        preview,
                        full_text,
                        f"{bill_url}/PrimarySponsorSummary",
                        0.7,
                    )
        tab_link = cls._find_summary_tab_link(soup, base_url)
        if tab_link:
            tab_soup = cls.soup(tab_link, cache=cache, config=config)
            text = " ".join(tab_soup.get_text(" ", strip=True).split())
            if text:
                full_text = cls._extract_summary_content(text)
                if full_text:
                    preview = full_text[:500] + ("..." if len(full_text) > 500 else "")
                    return ParserInterface.DiscoveryResult(
                        preview,
                        full_text,
                        tab_link,
                        0.6,
                    )
        return None

    @staticmethod
    def parse(_base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the summary."""
        return {"source_url": candidate.source_url}
