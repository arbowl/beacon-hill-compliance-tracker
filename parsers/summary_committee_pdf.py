"""A parser for PDF files in the Committee Summary tab."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import PyPDF2
from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)


class SummaryCommitteePdfParser(ParserInterface):
    """Parser for PDF files in the Committee Summary tab."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "committee page PDF"
    cost = 4

    @staticmethod
    def _find_committee_summary_pdf(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Find the Committee Summary PDF link."""
        for a in soup.find_all("a", href=True):
            if not hasattr(a, 'get'):
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
                if (
                    re.search(
                        r"committee.*summary|summary.*committee",
                        text,
                        re.I
                    ) or
                    re.search(
                        r"committee.*summary|summary.*committee",
                        href,
                        re.I
                    )
                ):
                    return urljoin(base_url, href)
            except (AttributeError, TypeError):
                continue
        return None

    @staticmethod
    def _extract_pdf_text(
        pdf_url: str,
        cache=None,
        config=None
    ) -> Optional[str]:
        """Extract text content from a PDF URL."""
        try:
            content = ParserInterface._fetch_binary(
                pdf_url, timeout=30, cache=cache, config=config
            )
            pdf_file = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text_content = []
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
            if text_content:
                full_text = "\n".join(text_content)
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                return full_text
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Could not extract text from PDF %s: %s", pdf_url, e
            )
            return None
        return None

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the Committee Summary PDF."""
        logger.debug("Trying %s...", cls.__name__)
        committee_summary_url = f"{bill.bill_url}/CommitteeSummary"
        soup = cls.soup(committee_summary_url)
        pdf_url = cls._find_committee_summary_pdf(soup, base_url)
        if not pdf_url:
            return None
        pdf_text = None
        if cache and config:
            cached_doc = cache.get_cached_document(pdf_url, config)
            if cached_doc:
                content_hash = cached_doc.get("content_hash")
                if content_hash:
                    pdf_text = cache.get_cached_extracted_text(
                        content_hash, config
                    )
                    if pdf_text:
                        logger.debug(
                            "Using cached extracted text for %s", pdf_url
                        )
        if not pdf_text:
            pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
            if pdf_text and cache and config:
                cached_doc = cache.get_cached_document(pdf_url, config)
                if cached_doc:
                    content_hash = cached_doc.get("content_hash")
                    if content_hash:
                        cache.cache_extracted_text(
                            content_hash, pdf_text, config
                        )
                        logger.debug("Cached extracted text for %s", pdf_url)
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
    def parse(
        _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the Committee Summary PDF."""
        return {"source_url": candidate.source_url}
