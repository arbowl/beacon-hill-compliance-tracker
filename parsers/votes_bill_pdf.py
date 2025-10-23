"""A parser for when the votes are on the bill's PDF."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import PyPDF2
import requests  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)

PDF_RX = re.compile(r"\.pdf($|\?)", re.I)
VOTE_HINTS = [r"\bvote\b", r"\bvoting\b", r"\brecorded vote\b", r"\broll[- ]?call\b"]


class VotesBillPdfParser(ParserInterface):

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page PDF"
    cost = 5

    @staticmethod
    def _extract_pdf_text(pdf_url: str) -> Optional[str]:
        """Extract text content from a PDF URL."""
        try:
            with requests.Session() as s:
                response = s.get(pdf_url, timeout=30, headers={"User-Agent": "legis-scraper/0.1"})
                response.raise_for_status()
                
                # Read PDF from memory
                pdf_file = io.BytesIO(response.content)
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
            logger.warning("Could not extract text from PDF %s: %s", pdf_url, e)
            return None
        
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the votes."""
        logger.debug("Trying %s...", cls.__name__)
        with requests.Session() as s:
            soup = cls._soup(s, bill.bill_url)
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = " ".join(a.get_text(strip=True).split())
                if not PDF_RX.search(href):
                    continue
                looks_vote = any(
                    re.search(rx, text, re.I) for rx in VOTE_HINTS
                ) or re.search(r"vote", href, re.I)
                if looks_vote:
                    pdf_url = urljoin(base_url, href)
                    
                    # Try to extract text from the PDF for preview
                    pdf_text = cls._extract_pdf_text(pdf_url)
                    
                    if pdf_text:
                        # Create preview with PDF content
                        preview = f"Possible vote PDF on bill page: {text or href}"
                        if len(pdf_text) > 200:
                            preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
                        else:
                            preview += f"\n\nPDF Content:\n{pdf_text}"
                        
                        return ParserInterface.DiscoveryResult(
                            preview,
                            pdf_text,
                            pdf_url,
                            0.8,  # Higher confidence with text extraction
                        )
                    else:
                        # Fallback to simple preview if text extraction fails
                        preview = f"Possible vote PDF on bill page: {text or href} (text extraction failed)"
                        return ParserInterface.DiscoveryResult(
                            preview,
                            "",
                            pdf_url,
                            0.75,
                        )
        return None

    @classmethod
    def parse(
        cls, base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the votes."""
        return {"location": cls.location, "source_url": candidate.source_url}
