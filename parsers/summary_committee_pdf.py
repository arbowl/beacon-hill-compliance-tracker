"""A parser for PDF files in the Committee Summary tab."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)


class SummaryCommitteePdfParser(ParserInterface):
    """Parser for PDF files in the Committee Summary tab."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "committee page PDF"
    cost = 4
    file_format = "pdf"

    @staticmethod
    def _find_committee_summary_pdf(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Find the Committee Summary PDF link."""
        for a in soup.find_all("a", href=True):
            if not hasattr(a, "get"):
                continue
            try:
                href = a.get("href", "")
                if not isinstance(href, str):
                    continue
                if not re.search(r"\.pdf($|\?)", href, re.I):
                    continue
                if re.search(r"/Download/DownloadDocument/", href, re.I):
                    return urljoin(base_url, href)
                text = a.get_text(strip=True).lower()
                if re.search(
                    r"committee.*summary|summary.*committee", text, re.I
                ) or re.search(r"committee.*summary|summary.*committee", href, re.I):
                    return urljoin(base_url, href)
            except (AttributeError, TypeError):
                continue
        return None

    @staticmethod
    def _extract_pdf_text(pdf_url: str, cache=None, config=None) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url, cache=cache, config=config, timeout=30
        )

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the Committee Summary PDF."""
        logger.debug("Trying %s...", cls.__name__)
        committee_summary_url = f"{bill.bill_url}/CommitteeSummary"
        soup = cls.soup(committee_summary_url)
        pdf_url = cls._find_committee_summary_pdf(soup, base_url)
        if not pdf_url:
            return None
        # Extraction service handles caching automatically
        pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
        if pdf_text:
            preview = pdf_text[:500] + ("..." if len(pdf_text) > 500 else "")
            return ParserInterface.DiscoveryResult(
                preview,
                pdf_text,
                pdf_url,
                0.9,
            )
        else:
            preview = (
                f"Found Committee Summary PDF for {bill.bill_id} "
                "(text extraction failed)"
            )
            return ParserInterface.DiscoveryResult(
                preview,
                "",
                pdf_url,
                0.8,
            )

    @staticmethod
    def parse(_base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the Committee Summary PDF."""
        return {"source_url": candidate.source_url}
