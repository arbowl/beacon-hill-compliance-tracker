"""A parser for when the votes are on the bill's PDF."""

import re
from typing import Optional
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup
import PyPDF2
import io

from components.models import BillAtHearing

PDF_RX = re.compile(r"\.pdf($|\?)", re.I)
VOTE_HINTS = [r"\bvote\b", r"\bvoting\b", r"\brecorded vote\b", r"\broll[- ]?call\b"]


def _soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


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


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover the votes."""
    with requests.Session() as s:
        soup = _soup(s, bill.bill_url)
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
                pdf_text = _extract_pdf_text(pdf_url)
                
                if pdf_text:
                    # Create preview with PDF content
                    preview = f"Possible vote PDF on bill page: {text or href}"
                    if len(pdf_text) > 200:
                        preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
                    else:
                        preview += f"\n\nPDF Content:\n{pdf_text}"
                    
                    return {
                        "preview": preview,
                        "source_url": pdf_url,
                        "confidence": 0.8,  # Higher confidence with text extraction
                        "full_text": pdf_text  # For the preview dialog
                    }
                else:
                    # Fallback to simple preview if text extraction fails
                    preview = f"Possible vote PDF on bill page: {text or href} (text extraction failed)"
                    return {
                        "preview": preview,
                        "source_url": pdf_url,
                        "confidence": 0.75,
                    }
    return None


def parse(base_url: str, candidate: dict) -> dict:
    """Parse the votes."""
    return {"location": "bill_pdf", "source_url": candidate["source_url"]}
