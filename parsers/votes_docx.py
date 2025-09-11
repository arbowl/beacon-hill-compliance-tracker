"""A parser for DOCX files containing vote records."""

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
            
            # Read DOCX from memory
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
                
            # Check if it's a DOCX file
            if re.search(r"\.docx($|\?)", href, re.I):
                # Check if it's a download document
                if re.search(r"/Download/DownloadDocument/", href, re.I):
                    docx_urls.append(urljoin(base_url, href))
                    
        except (AttributeError, TypeError):
            continue
    
    return docx_urls


def _looks_like_vote_docx(docx_text: str, bill_id: str) -> bool:
    """Check if DOCX content looks like it contains vote records."""
    if not docx_text:
        return False
    
    text_lower = docx_text.lower()
    
    # Look for vote-related keywords
    vote_keywords = [
        'vote', 'voting', 'yea', 'nay', 'yes', 'no', 'abstain', 'present',
        'roll call', 'recorded vote', 'committee vote', 'member vote',
        'favorable', 'unfavorable', 'passed', 'failed', 'reported out'
    ]
    
    has_vote_keywords = any(keyword in text_lower for keyword in vote_keywords)
    
    # Look for the specific bill ID
    has_bill_id = bill_id.lower() in text_lower
    
    return has_vote_keywords and has_bill_id


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover vote DOCX files."""
    # Try multiple locations where vote DOCX files might be found
    
    locations_to_check = [
        # Committee Documents tab
        f"{base_url}/Committees/Detail/{bill.committee_id}/194/Documents",
        # Bill page
        bill.bill_url,
        # Hearing page
        bill.hearing_url
    ]
    
    with requests.Session() as s:
        for location in locations_to_check:
            try:
                soup = _soup(s, location)
                docx_urls = _find_docx_files(soup, base_url)
                
                for docx_url in docx_urls:
                    # Extract text from DOCX
                    docx_text = _extract_docx_text(docx_url)
                    
                    if docx_text and _looks_like_vote_docx(docx_text, bill.bill_id):
                        # Create preview with DOCX content
                        preview = f"Found vote DOCX for {bill.bill_id}"
                        if len(docx_text) > 200:
                            preview += f"\n\nDOCX Content Preview:\n{docx_text[:500]}..."
                        else:
                            preview += f"\n\nDOCX Content:\n{docx_text}"
                        
                        return {
                            "preview": preview,
                            "source_url": docx_url,
                            "confidence": 0.85,
                            "full_text": docx_text  # For the preview dialog
                        }
                        
            except Exception as e:
                # If we can't access this location, continue to the next one
                continue
    
    return None


def parse(_base_url: str, candidate: dict) -> dict:
    """Parse the vote DOCX."""
    return {
        "location": "docx_vote",
        "source_url": candidate["source_url"]
    }
