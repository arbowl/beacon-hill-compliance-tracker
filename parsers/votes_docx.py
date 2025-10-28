"""A parser for DOCX files containing vote records."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from docx import Document

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)

class VotesDocxParser(ParserInterface):
    """Parser for DOCX files containing vote records."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page Word document"
    cost = 4

    @staticmethod
    def _extract_docx_text(docx_url: str) -> Optional[str]:
        """Extract text content from a DOCX URL."""
        try:
            content = ParserInterface._fetch_binary(docx_url, timeout=30)
            docx_file = io.BytesIO(content)
            doc = Document(docx_file)
            text_content = []
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text.strip())
            if text_content:
                full_text = "\n".join(text_content)
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                return full_text
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Could not extract text from DOCX %s: %s", docx_url, e)
            return None
        return None

    @staticmethod
    def _find_docx_files(soup: BeautifulSoup, base_url: str) -> list[str]:
        """Find all DOCX files on the page."""
        docx_urls = []
        for a in soup.find_all("a", href=True):
            if not hasattr(a, 'get'):
                continue
            try:
                href = a.get("href", "")
                if not isinstance(href, str):
                    continue
                if re.search(r"\.docx($|\?)", href, re.I):
                    if re.search(r"/Download/DownloadDocument/", href, re.I):
                        docx_urls.append(urljoin(base_url, href))
            except (AttributeError, TypeError):
                continue
        return docx_urls

    @staticmethod
    def _looks_like_vote_docx(docx_text: str, bill_id: str) -> bool:
        """Check if DOCX content looks like it contains vote records."""
        if not docx_text:
            return False
        text_lower = docx_text.lower()
        vote_keywords = [
            'vote', 'voting', 'yea', 'nay', 'yes', 'no', 'abstain', 'present',
            'roll call', 'recorded vote', 'committee vote', 'member vote',
            'favorable', 'unfavorable', 'passed', 'failed', 'reported out'
        ]
        has_vote_keywords = any(keyword in text_lower for keyword in vote_keywords)
        has_bill_id = bill_id.lower() in text_lower
        return has_vote_keywords and has_bill_id

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover vote DOCX files."""
        logger.debug("Trying %s...", cls.__name__)
        locations_to_check = [
            f"{base_url}/Committees/Detail/{bill.committee_id}/194/Documents",
            bill.bill_url,
            bill.hearing_url
        ]
        for location in locations_to_check:
            try:
                soup = cls.soup(location)
                docx_urls = cls._find_docx_files(soup, base_url)
                for docx_url in docx_urls:
                    docx_text = cls._extract_docx_text(docx_url)
                    if docx_text and cls._looks_like_vote_docx(docx_text, bill.bill_id):
                        preview = f"Found vote DOCX for {bill.bill_id}"
                        if len(docx_text) > 200:
                            preview += f"\n\nDOCX Content Preview:\n{docx_text[:500]}..."
                        else:
                            preview += f"\n\nDOCX Content:\n{docx_text}"
                        return ParserInterface.DiscoveryResult(
                            preview,
                            docx_text,
                            docx_url,
                            0.85,
                        )
            except Exception:  # pylint: disable=broad-exception-caught
                continue
        return None

    @classmethod
    def parse(
        cls, _base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the vote DOCX."""
        return {
            "location": cls.location,
            "source_url": candidate.source_url
        }
