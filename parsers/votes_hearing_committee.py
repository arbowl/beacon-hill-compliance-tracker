"""A parser for committee member vote documents on hearing pages."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)

VOTE_DOC_PATTERNS = [
    r"committee.*members?.*votes",
    r"house.*committee.*members?.*votes",
    r"senate.*committee.*members?.*votes",
    r"votes.*committee.*members?",
    r"committee.*vote.*record",
    r"roll.*call.*vote",
]


class VotesHearingCommitteeDocumentsParser(ParserInterface):
    """Parser for committee member vote documents on hearing pages."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Hearing page Documents tab"
    cost = 2

    @staticmethod
    def _extract_pdf_text(pdf_url: str, cache=None, config=None) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url, cache=cache, config=config, timeout=30
        )

    @staticmethod
    def _looks_like_vote_document(link_text: str, title_param: str) -> bool:
        """Check if a document link looks like a committee vote document."""
        text = f"{link_text} {title_param}".lower()
        for pattern in VOTE_DOC_PATTERNS:
            if re.search(pattern, text, re.I):
                return True
        if re.search(r"votes.*\b(h|s)\d+\b", text, re.I):
            return True
        return False

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover committee vote documents on the hearing page."""
        logger.debug("Trying %s...", cls.__name__)
        soup = cls.soup(str(bill.hearing_url))
        document_links = soup.find_all("a", href=True)
        for link in document_links:
            if not hasattr(link, "get"):
                continue
            href = link.get("href", "")
            if not isinstance(href, str):
                continue
            link_text = " ".join(link.get_text(strip=True).split())
            if not re.search(r"\.pdf($|\?)", href, re.I):
                continue
            title_param = ""
            if "Title=" in href:
                title_match = re.search(r"Title=([^&]+)", href)
                if title_match:
                    title_param = title_match.group(1)
            if cls._looks_like_vote_document(link_text, title_param):
                full_text = f"{link_text} {title_param}".lower()
                bill_pattern = re.escape(bill.bill_id.lower())
                if re.search(bill_pattern, full_text):
                    pdf_url = urljoin(base_url, href)
                    pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
                    if pdf_text:
                        preview = (
                            f"Committee vote document found for "
                            f"{bill.bill_id}: {link_text or title_param}"
                        )
                        if len(pdf_text) > 200:
                            preview += (
                                f"\n\nPDF Content Preview:\n" f"{pdf_text[:500]}..."
                            )
                        else:
                            preview += f"\n\nPDF Content:\n{pdf_text}"
                        return ParserInterface.DiscoveryResult(
                            preview,
                            pdf_text,
                            pdf_url,
                            0.95,
                        )
                    else:
                        preview = (
                            f"Committee vote document found for "
                            f"{bill.bill_id}: "
                            f"{link_text or title_param} "
                            "(text extraction failed)"
                        )
                        return ParserInterface.DiscoveryResult(
                            preview,
                            "",
                            pdf_url,
                            0.9,
                        )

        return None

    @classmethod
    def parse(cls, _base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the committee vote document."""
        return {"location": cls.location, "source_url": candidate.source_url}

