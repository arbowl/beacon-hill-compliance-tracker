"""A parser for DOCX files in the Committee Summary tab."""

import re
from typing import Optional
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup
from docx import Document
import io

from components.models import BillAtHearing


def _soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _extract_docx_text(docx_url: str) -> Optional[str]:
    """Extract text content from a DOCX URL."""
    try:
        with requests.Session() as s:
            response = s.get(docx_url, timeout=30, headers={"User-Agent": "legis-scraper/0.1"})
            response.raise_for_status()
            
            # Read DOCX from memory - let python-docx handle the format detection
            docx_file = io.BytesIO(response.content)
            doc = Document(docx_file)
            
            # Extract text from all paragraphs
            text_content = []
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text.strip())
            
            if text_content:
                full_text = "\n".join(text_content)
                # Clean up the text - remove excessive whitespace
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                return full_text
                
    except Exception as e:
        print(f"Warning: Could not extract text from DOCX {docx_url}: {e}")
        return None
    
    return None


def _find_committee_summary_docx(
    soup: BeautifulSoup, base_url: str
) -> Optional[str]:
    """Find the Committee Summary DOCX link."""
    # Look for any DOCX file on the page - Committee Summary pages typically
    # have only one DOCX file which is the summary
    for a in soup.find_all("a", href=True):
        if not hasattr(a, 'get'):
            continue
        try:
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
                
            # Check if it's a DOCX file
            if not re.search(r"\.docx($|\?)", href, re.I):
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


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover the Committee Summary DOCX."""
    # Navigate to the Committee Summary tab
    committee_summary_url = f"{bill.bill_url}/CommitteeSummary"

    with requests.Session() as s:
        soup = _soup(s, committee_summary_url)

        docx_url = _find_committee_summary_docx(soup, base_url)
        if not docx_url:
            return None

        # Try to extract text from the DOCX for preview
        docx_text = _extract_docx_text(docx_url)
        
        if docx_text:
            # Use the extracted text as preview, truncated if too long
            preview = f"Found Committee Summary DOCX for {bill.bill_id}"
            if len(docx_text) > 200:
                preview += f"\n\nDOCX Content Preview:\n{docx_text[:500]}..."
            else:
                preview += f"\n\nDOCX Content:\n{docx_text}"
            
            return {
                "preview": preview,
                "source_url": docx_url,
                "confidence": 0.9,
                "full_text": docx_text  # Full text for the preview dialog
            }
        else:
            # Fallback to simple preview if text extraction fails
            preview = f"Found Committee Summary DOCX for {bill.bill_id} (text extraction failed)"
            return {
                "preview": preview,
                "source_url": docx_url,
                "confidence": 0.8,  # Lower confidence if we can't extract text
            }


def parse(_base_url: str, candidate: dict) -> dict:
    """Parse the Committee Summary DOCX."""
    # For now, just return the URL we confirmed
    # Later we can add actual DOCX text extraction if needed
    return {"source_url": candidate["source_url"]}
