"""A parser for committee member vote documents on hearing pages."""

import re
from typing import Optional
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup
import PyPDF2
import io

from components.models import BillAtHearing
from components.interfaces import ParserInterface

VOTE_DOC_PATTERNS = [
    r"committee.*members.*votes",
    r"house.*committee.*members.*votes",
    r"senate.*committee.*members.*votes",
    r"votes.*committee.*members",
    r"committee.*vote.*record",
    r"roll.*call.*vote"
]

class VotesHearingCommitteeDocumentsParser(ParserInterface):

    parser_type = ParserInterface.ParserType.VOTES
    location = "Hearing page Documents tab"
    cost = 2

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
            print(f"Warning: Could not extract text from PDF {pdf_url}: {e}")
            return None
        
        return None

    @staticmethod
    def _looks_like_vote_document(link_text: str, title_param: str) -> bool:
        """Check if a document link looks like a committee vote document."""
        text = f"{link_text} {title_param}".lower()

        # Check for vote-related patterns
        for pattern in VOTE_DOC_PATTERNS:
            if re.search(pattern, text, re.I):
                return True

        # Also check for specific bill number patterns in vote documents
        if re.search(r"votes.*\b(h|s)\d+\b", text, re.I):
            return True

        return False

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover committee vote documents on the hearing page."""
        print(f"Trying {cls.__name__}...")
        with requests.Session() as s:
            # Get the hearing page
            soup = cls._soup(s, bill.hearing_url)

            # Look for document links in the Documents section
            # Based on the hearing page structure, documents are in a table
            document_links = soup.find_all("a", href=True)

            for link in document_links:
                if not hasattr(link, 'get'):
                    continue
                href = link.get("href", "")
                if not isinstance(href, str):
                    continue
                link_text = " ".join(link.get_text(strip=True).split())

                # Check if this looks like a PDF document
                if not re.search(r"\.pdf($|\?)", href, re.I):
                    continue

                # Get the title parameter if it exists
                title_param = ""
                if "Title=" in href:
                    # Extract title from URL parameter
                    title_match = re.search(r"Title=([^&]+)", href)
                    if title_match:
                        title_param = title_match.group(1)

                # Check if this looks like a vote document for our bill
                if cls._looks_like_vote_document(link_text, title_param):
                    # Check if it's specifically for our bill
                    full_text = f"{link_text} {title_param}".lower()
                    bill_pattern = re.escape(bill.bill_id.lower())
                    if re.search(bill_pattern, full_text):
                        pdf_url = urljoin(base_url, href)
                        
                        # Try to extract text from the PDF for preview
                        pdf_text = cls._extract_pdf_text(pdf_url)
                        
                        if pdf_text:
                            # Create preview with PDF content
                            preview = (f"Committee vote document found for "
                                    f"{bill.bill_id}: {link_text or title_param}")
                            if len(pdf_text) > 200:
                                preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
                            else:
                                preview += f"\n\nPDF Content:\n{pdf_text}"
                            
                            return ParserInterface.DiscoveryResult(
                                preview,
                                pdf_text,
                                pdf_url,
                                0.95,  # High confidence with bill match and text extraction
                            )
                        else:
                            # Fallback to simple preview if text extraction fails
                            preview = (f"Committee vote document found for "
                                    f"{bill.bill_id}: {link_text or title_param} (text extraction failed)")
                            return ParserInterface.DiscoveryResult(
                                preview,
                                "",
                                pdf_url,
                                0.9,
                            )

        return None

    @classmethod
    def parse(
        cls, _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the committee vote document."""
        return {
            "location": cls.location,
            "source_url": candidate.source_url
        }
