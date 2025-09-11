"""A parser for vote documents in committee Documents tabs."""

import re
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

import requests  # type: ignore
from bs4 import BeautifulSoup
import PyPDF2
import io

from components.models import BillAtHearing, VoteRecord


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
                return full_text
                
    except Exception as e:
        print(f"Warning: Could not extract text from PDF {pdf_url}: {e}")
        return None
    
    return None


def _normalize_bill_id(bill_text: str) -> Optional[str]:
    """Normalize bill ID from various formats like 'House 475', 'H.475', 'H475' to 'H475'."""
    if not bill_text:
        return None
    
    # Clean up the text
    bill_text = bill_text.strip().upper()
    
    # Handle patterns like "House 475", "Senate 123", "H.475", "S.123"
    patterns = [
        r'HOUSE\s+(\d+)',  # "House 475" -> "H475"
        r'SENATE\s+(\d+)', # "Senate 123" -> "S123"
        r'H\.?\s*(\d+)',   # "H.475" or "H 475" -> "H475"
        r'S\.?\s*(\d+)',   # "S.123" or "S 123" -> "S123"
        r'^([HS]\d+)$',    # Already normalized "H475", "S123"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, bill_text)
        if match:
            number = match.group(1)
            prefix = 'H' if 'HOUSE' in bill_text or 'H' in bill_text else 'S'
            return f"{prefix}{number}"
    
    return None


def _parse_vote_table(pdf_text: str) -> List[Dict[str, Any]]:
    """Parse vote table from PDF text to extract bill numbers and vote results."""
    if not pdf_text:
        return []
    
    # Split into lines for processing
    lines = pdf_text.split('\n')
    
    # Look for table-like structures
    # Common patterns: "Bill Number", "Bill", "Vote", "Result", "Status"
    vote_records = []
    
    # Find lines that look like table headers
    header_line_idx = None
    for i, line in enumerate(lines):
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in ['bill number', 'bill', 'vote', 'result', 'status']):
            header_line_idx = i
            break
    
    if header_line_idx is None:
        return []
    
    # Process lines after the header
    for i in range(header_line_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
            
        # Skip lines that look like headers or separators
        if any(keyword in line.lower() for keyword in ['bill number', 'bill', 'vote', 'result', 'status', '---', '===']):
            continue
        
        # Try to extract bill number and vote result
        # Look for patterns like "H475" or "House 475" followed by vote info
        bill_match = re.search(r'([HS]\d+|HOUSE\s+\d+|SENATE\s+\d+)', line, re.I)
        if bill_match:
            bill_id = _normalize_bill_id(bill_match.group(1))
            if bill_id:
                # Look for vote result in the same line
                vote_result = _extract_vote_result(line)
                
                vote_records.append({
                    'bill_id': bill_id,
                    'vote_result': vote_result,
                    'raw_line': line
                })
    
    return vote_records


def _extract_vote_result(line: str) -> str:
    """Extract vote result from a line of text."""
    line_lower = line.lower()
    
    # Common vote result patterns
    if any(word in line_lower for word in ['passed', 'favorable', 'yea', 'yes']):
        return 'Passed'
    elif any(word in line_lower for word in ['failed', 'unfavorable', 'nay', 'no']):
        return 'Failed'
    elif any(word in line_lower for word in ['reported', 'reported out']):
        return 'Reported Out'
    elif any(word in line_lower for word in ['held', 'study']):
        return 'Held'
    else:
        return 'Unknown'


def _find_committee_documents_pdf(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find PDF documents in the committee Documents tab."""
    # Look for PDF links in the Documents table
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not isinstance(href, str):
            continue
            
        # Check if it's a PDF file
        if not re.search(r"\.pdf($|\?)", href, re.I):
            continue
            
        # Check if it's a report document (typical pattern for committee documents)
        if re.search(r"/Reports/", href, re.I):
            return urljoin(base_url, href)
    
    return None


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """Discover vote documents in committee Documents tab."""
    # Construct committee Documents URL
    # Format: /Committees/Detail/{committee_id}/194/Documents
    committee_documents_url = f"{base_url}/Committees/Detail/{bill.committee_id}/194/Documents"
    
    with requests.Session() as s:
        soup = _soup(s, committee_documents_url)
        
        pdf_url = _find_committee_documents_pdf(soup, base_url)
        if not pdf_url:
            return None
        
        # Extract text from PDF to check if it contains our bill
        pdf_text = _extract_pdf_text(pdf_url)
        if not pdf_text:
            return None
        
        # Parse vote table to see if our bill is mentioned
        vote_records = _parse_vote_table(pdf_text)
        
        # Look for our specific bill
        bill_vote_record = None
        for record in vote_records:
            if record['bill_id'] == bill.bill_id:
                bill_vote_record = record
                break
        
        if bill_vote_record:
            # Create a preview with the vote result and some context
            preview = f"Found vote record for {bill.bill_id}: {bill_vote_record['vote_result']}"
            if len(pdf_text) > 200:
                preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
            else:
                preview += f"\n\nPDF Content:\n{pdf_text}"
            
            return {
                "preview": preview,
                "source_url": pdf_url,
                "confidence": 0.9,
                "vote_data": bill_vote_record,
                "full_text": pdf_text  # For the preview dialog
            }
    
    return None


def parse(_base_url: str, candidate: dict) -> dict:
    """Parse the committee vote document."""
    vote_data = candidate.get("vote_data", {})
    
    return {
        "location": "committee_documents",
        "source_url": candidate["source_url"],
        "motion": f"Committee vote on {vote_data.get('bill_id', 'unknown bill')}",
        "date": None,  # Could be extracted from PDF if available
        "tallies": {
            "passed": 1 if vote_data.get('vote_result') == 'Passed' else 0,
            "failed": 1 if vote_data.get('vote_result') == 'Failed' else 0
        },
        "records": []  # Individual member votes not available in this format
    }
