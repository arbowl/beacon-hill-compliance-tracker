"""A parser for PDF files in the Committee Summary tab."""

import re
from typing import Optional
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup
import PyPDF2
import io

from components.models import BillAtHearing


def _soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


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
        # If PDF extraction fails, return None
        print(f"Warning: Could not extract text from PDF {pdf_url}: {e}")
        return None
    
    return None


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover the Committee Summary PDF."""
    # Navigate to the Committee Summary tab
    committee_summary_url = f"{bill.bill_url}/CommitteeSummary"

    with requests.Session() as s:
        soup = _soup(s, committee_summary_url)

        pdf_url = _find_committee_summary_pdf(soup, base_url)
        if not pdf_url:
            return None

        # Try to extract text from the PDF for preview
        pdf_text = _extract_pdf_text(pdf_url)
        
        if pdf_text:
            # Use the extracted text as preview, truncated if too long
            preview = pdf_text[:500] + ("..." if len(pdf_text) > 500 else "")
            return {
                "preview": preview,
                "full_text": pdf_text,  # Full text for the preview dialog
                "source_url": pdf_url,
                "confidence": 0.9,
            }
        else:
            # Fallback to simple preview if text extraction fails
            preview = f"Found Committee Summary PDF for {bill.bill_id} (text extraction failed)"
            return {
                "preview": preview,
                "source_url": pdf_url,
                "confidence": 0.8,  # Lower confidence if we can't extract text
            }


def parse(_base_url: str, candidate: dict) -> dict:
    """Parse the Committee Summary PDF."""
    # For now, just return the URL we confirmed
    # Later we can add actual PDF text extraction if needed
    return {"source_url": candidate["source_url"]}
