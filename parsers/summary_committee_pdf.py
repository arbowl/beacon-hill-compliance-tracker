"""A parser for PDF files in the Committee Summary tab."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import PyPDF2
from bs4 import BeautifulSoup

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)


class SummaryCommitteePdfParser(ParserInterface):

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "committee page PDF"
    cost = 4

    @staticmethod
    def _find_committee_summary_pdf(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Find the Committee Summary PDF link."""
        # Look for any PDF file on the page - Committee Summary pages typically
        # have only one PDF file which is the summary
        for a in soup.find_all("a", href=True):
            if not hasattr(a, 'get'):
                continue
            try:
                href = a.get("href", "")
                if not isinstance(href, str):
                    continue
                    
                # Check if it's a PDF file
                if not re.search(r"\.pdf($|\?)", href, re.I):
                    continue
                    
                # Check if it's a download document (typical pattern for summaries)
                if re.search(r"/Download/DownloadDocument/", href, re.I):
                    return urljoin(base_url, href)
                    
                # Also check for committee summary patterns in text or href
                text = a.get_text(strip=True).lower()
                if (re.search(r"committee.*summary|summary.*committee", text, re.I) or
                    re.search(r"committee.*summary|summary.*committee", href, re.I)):
                    return urljoin(base_url, href)
                    
            except (AttributeError, TypeError):
                continue

        return None

    @staticmethod
    def _extract_pdf_text(pdf_url: str) -> Optional[str]:
        """Extract text content from a PDF URL."""
        try:
            content = ParserInterface._fetch_binary(pdf_url, timeout=30)
            
            # Read PDF from memory
            pdf_file = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            # Extract text from all pages
            text_content = []
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
            
            if text_content:
                full_text = "\n".join(text_content)
                # Clean up the text - remove excessive whitespace
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                return full_text
                
        except Exception as e:
            # If PDF extraction fails, return None
            logger.warning("Could not extract text from PDF %s: %s", pdf_url, e)
            return None
        
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the Committee Summary PDF."""
        logger.debug("Trying %s...", cls.__name__)
        # Navigate to the Committee Summary tab
        committee_summary_url = f"{bill.bill_url}/CommitteeSummary"

        soup = cls._soup(committee_summary_url)

        pdf_url = cls._find_committee_summary_pdf(soup, base_url)
        if not pdf_url:
            return None

        # Try to extract text from the PDF for preview
        pdf_text = cls._extract_pdf_text(pdf_url)
        
        if pdf_text:
            # Use the extracted text as preview, truncated if too long
            preview = pdf_text[:500] + ("..." if len(pdf_text) > 500 else "")
            return ParserInterface.DiscoveryResult(
                preview,
                pdf_text,  # Full text for the preview dialog
                pdf_url,
                0.9,
            )
        else:
            # Fallback to simple preview if text extraction fails
            preview = f"Found Committee Summary PDF for {bill.bill_id} (text extraction failed)"
            return ParserInterface.DiscoveryResult(
                preview,
                "",
                pdf_url,
                0.8,  # Lower confidence if we can't extract text
            )


    def parse(
        _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the Committee Summary PDF."""
        # For now, just return the URL we confirmed
        # Later we can add actual PDF text extraction if needed
        return {"source_url": candidate.source_url}
