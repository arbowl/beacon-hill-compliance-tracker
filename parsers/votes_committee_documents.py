"""A parser for vote documents in committee Documents tabs."""

import logging
import re
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)


class VotesCommitteeDocumentsParser(ParserInterface):
    """Parser for vote documents in committee Documents tabs."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Committee page Documents tab"
    cost = 3
    file_format = "pdf"
    _bill_vote_data: dict = {}

    @staticmethod
    def _extract_pdf_text(pdf_url: str, cache=None, config=None) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url, cache=cache, config=config, timeout=30
        )

    @staticmethod
    def _normalize_bill_id(bill_text: str) -> Optional[str]:
        """Normalize bill ID from various formats like 'House 475',
        'H.475', 'H475' to 'H475'.
        """
        if not bill_text:
            return None
        bill_text = bill_text.strip().upper()
        patterns = [
            r"HOUSE\s+(\d+)",  # "House 475" -> "H475"
            r"SENATE\s+(\d+)",  # "Senate 123" -> "S123"
            r"H\.?\s*(\d+)",  # "H.475" or "H 475" -> "H475"
            r"S\.?\s*(\d+)",  # "S.123" or "S 123" -> "S123"
            r"^([HS]\d+)$",  # Already normalized "H475", "S123"
        ]
        for pattern in patterns:
            match = re.search(pattern, bill_text)
            if match:
                number = match.group(1)
                prefix = "H" if "HOUSE" in bill_text or "H" in bill_text else "S"
                return f"{prefix}{number}"
        return None

    @classmethod
    def _parse_vote_table(cls, pdf_text: str) -> List[Dict[str, Any]]:
        """Parse vote table from PDF text to extract bill numbers and vote
        results.
        """
        if not pdf_text:
            return []
        lines = pdf_text.split("\n")
        vote_records = []
        header_line_idx = None
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(
                keyword in line_lower
                for keyword in ["bill number", "bill", "vote", "result", "status"]
            ):
                header_line_idx = i
                break
        if header_line_idx is None:
            return []
        for i in range(header_line_idx + 1, len(lines)):
            line = lines[i].strip()
            if not line:
                continue
            if any(
                keyword in line.lower()
                for keyword in [
                    "bill number",
                    "bill",
                    "vote",
                    "result",
                    "status",
                    "---",
                    "===",
                ]
            ):
                continue
            bill_match = re.search(r"([HS]\d+|HOUSE\s+\d+|SENATE\s+\d+)", line, re.I)
            if bill_match:
                bill_id = cls._normalize_bill_id(bill_match.group(1))
                if bill_id:
                    vote_result = cls._extract_vote_result(line)
                    vote_records.append(
                        {
                            "bill_id": bill_id,
                            "vote_result": vote_result,
                            "raw_line": line,
                        }
                    )
        return vote_records

    @staticmethod
    def _extract_vote_result(line: str) -> str:
        """Extract vote result from a line of text."""
        line_lower = line.lower()
        if any(word in line_lower for word in ["passed", "favorable", "yea", "yes"]):
            return "Passed"
        elif any(word in line_lower for word in ["failed", "unfavorable", "nay", "no"]):
            return "Failed"
        elif any(word in line_lower for word in ["reported", "reported out"]):
            return "Reported Out"
        elif any(word in line_lower for word in ["held", "study"]):
            return "Held"
        return "Unknown"

    @staticmethod
    def _find_committee_documents_pdf(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Find PDF documents in the committee Documents tab."""
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if not re.search(r"\.pdf($|\?)", href, re.I):
                continue
            if re.search(r"/Reports/", href, re.I):
                return urljoin(base_url, href)
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover vote documents in committee Documents tab."""
        logger.debug("Trying %s...", cls.__name__)
        # Construct committee Documents URL
        # Format: /Committees/Detail/{committee_id}/194/Documents
        committee_documents_url = (
            f"{base_url}/Committees/Detail/{bill.committee_id}/194/Documents"
        )
        soup = cls.soup(committee_documents_url)
        pdf_url = cls._find_committee_documents_pdf(soup, base_url)
        if not pdf_url:
            return None
        pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
        if not pdf_text:
            return None
        vote_records = cls._parse_vote_table(pdf_text)
        bill_vote_record = None
        for record in vote_records:
            if record["bill_id"] == bill.bill_id:
                bill_vote_record = record
                break
        if bill_vote_record:
            preview = (
                f"Found vote record for {bill.bill_id}: "
                f"{bill_vote_record['vote_result']}"
            )
            if len(pdf_text) > 200:
                preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
            else:
                preview += f"\n\nPDF Content:\n{pdf_text}"
            result = ParserInterface.DiscoveryResult(preview, pdf_text, pdf_url, 0.9)
            cls._bill_vote_data[preview] = bill_vote_record
            return result
        return None

    @classmethod
    def parse(cls, _base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the committee vote document."""
        vote_data: dict = VotesCommitteeDocumentsParser._bill_vote_data[
            candidate.preview
        ]
        return {
            "location": "committee_documents",
            "source_url": candidate.source_url,
            "motion": (f"Committee vote on {vote_data.get('bill_id', 'unknown bill')}"),
            "date": None,  # Could be extracted from PDF if available
            "tallies": {
                "passed": 1 if vote_data.get("vote_result") == "Passed" else 0,
                "failed": 1 if vote_data.get("vote_result") == "Failed" else 0,
            },
            "records": [],  # Indiv member votes not available in this format
        }
