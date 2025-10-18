"""A parser for when the summary is on the bill's Summary tab."""

import re
from typing import Optional
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import BillAtHearing
from components.interfaces import ParserInterface


class SummaryBillTabTextParser(ParserInterface):

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Bill page summary tab"
    cost = 2

    @staticmethod
    def _find_summary_tab_link(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Find the summary tab link."""
        for a in soup.select("a[href]"):
            if re.search(r"\bsummary\b", a.get_text(strip=True), re.I):
                return str(urljoin(base_url, str(a["href"])))
        return None

    @staticmethod
    def _extract_summary_content(text: str) -> Optional[str]:
        """Extract the actual summary content from the page text."""
        summary_patterns = [
            (r"Bill Section by Section Summary[^–]*–\s*(.+?)"
            r"(?=\n\n|\n[A-Z]+\s*:|$)"),
            r"Summary[^–]*–\s*(.+?)(?=\n\n|\n[A-Z]+\s*:|$)",
            r"Bill Summary[^–]*–\s*(.+?)(?=\n\n|\n[A-Z]+\s*:|$)",
        ]
        for pattern in summary_patterns:
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                summary_text = match.group(1).strip()
                summary_text = re.sub(r'\s+', ' ', summary_text)
                nav_pattern = (r'(Skip to Content|Menu Toggle|Sign in|'
                            r'MyLegislature).*?(?=Bill|Summary)')
                summary_text = re.sub(nav_pattern, '', summary_text,
                                    flags=re.DOTALL | re.IGNORECASE)
                if len(summary_text) > 50:
                    return summary_text
        headers = ["Bill Section by Section Summary", "Summary", "Bill Summary"]
        for header in headers:
            if header in text:
                start = text.find(header)
                content_start = start + len(header)
                while (content_start < len(text) and
                        text[content_start] in "–-: "):
                    content_start += 1
                remaining_text = text[content_start:]
                end_patterns = [
                    r'\n[A-Z][A-Z\s]+\s*:',
                    r'\n\n[A-Z][A-Z\s]+$',
                    r'\n\s*$',
                ]
                end_pos = len(remaining_text)
                for pattern in end_patterns:
                    match = re.search(pattern, remaining_text, re.MULTILINE)
                    if match:
                        end_pos = min(end_pos, match.start())
                summary_text = remaining_text[:end_pos].strip()
                summary_text = re.sub(r'\s+', ' ', summary_text)
                if len(summary_text) > 50:
                    return summary_text
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the summary."""
        print(f"Trying {cls.__name__}...")
        bill_url = bill.bill_url
        with requests.Session() as s:
            soup = cls._soup(s, f"{bill_url}/PrimarySponsorSummary")
            tab_panel = soup.find("div", attrs={
                "aria-labelledby": re.compile("PrimarySponsorSummary",
                                              re.I)
            })
            if tab_panel:
                text = " ".join(tab_panel.get_text(" ", strip=True).split())
                if text:
                    # Extract actual summary content, not just tab text
                    full_text = cls._extract_summary_content(text)
                    if full_text:
                        preview = (full_text[:500] +
                                   ("..." if len(full_text) > 500 else ""))
                        return ParserInterface.DiscoveryResult(
                            preview,
                            full_text,
                            f"{bill_url}/PrimarySponsorSummary",
                            0.95,
                        )
            summary_div = soup.find(
                id=re.compile("Summary", re.I)
            ) or soup.find(
                "div", class_=re.compile("Summary", re.I)
            )
            if summary_div:
                text = " ".join(summary_div.get_text(" ", strip=True).split())
                if text:
                    full_text = cls._extract_summary_content(text)
                    if full_text:
                        preview = (full_text[:500] +
                                   ("..." if len(full_text) > 500 else ""))
                        return ParserInterface.DiscoveryResult(
                            preview,
                            full_text,
                            f"{bill_url}/PrimarySponsorSummary",
                            0.7,
                        )
            tab_link = cls._find_summary_tab_link(soup, base_url)
            if tab_link:
                tab_soup = cls._soup(s, tab_link)
                text = " ".join(tab_soup.get_text(" ", strip=True).split())
                if text:
                    full_text = cls._extract_summary_content(text)
                    if full_text:
                        preview = (full_text[:500] +
                                   ("..." if len(full_text) > 500 else ""))
                        return ParserInterface.DiscoveryResult(
                            preview,
                            full_text,
                            tab_link,
                            0.6,
                        )
        return None

    @staticmethod
    def parse(
        _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the summary."""
        return {"source_url": candidate.source_url}
