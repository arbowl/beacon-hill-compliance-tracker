"""Parser for summary PDFs on hearing pages."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)


PDF_RX = re.compile(r"\.pdf($|\?)", re.I)
SUMMARY_HINTS = [
    r"\bcommittee summary\b",
    r"\bsummary\b",
    r"\bdocket summary\b",
]


class SummaryHearingPdfParser(ParserInterface):
    """Parser for summary PDFs on hearing pages."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Hearing page PDF"
    cost = 5

    @staticmethod
    def _find_candidate_pdf(soup: BeautifulSoup, base_url: str) -> Optional[str]:
        """Find a candidate PDF on the hearing page."""
        # Strategy: any <a> on the hearing page whose text or filename suggests
        # "summary" and is a PDF.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = " ".join(a.get_text(strip=True).split()).lower()
            if not PDF_RX.search(href):
                continue
            if any(re.search(rx, text, re.I) for rx in SUMMARY_HINTS):
                return urljoin(base_url, href)
            # fallback: filename has "summary"
            if re.search(r"summary", href, re.I):
                return urljoin(base_url, href)
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Quick probe. Return a Candidate
        or None if nothing plausible is found.
        """
        logger.debug("Trying %s...", cls.__name__)
        soup = cls.soup(str(bill.hearing_url))
        # Prefer the hearing detail page URL; derive it from known pattern:
        # we stored only IDs in BillAtHearing, so reconstruct if needed:
        hearing_url = f"{base_url}/Events/Hearings/Detail/{bill.hearing_id}"
        soup = cls.soup(hearing_url)

        pdf_url = cls._find_candidate_pdf(soup, base_url)
        if not pdf_url:
            return None

        preview = (
            "Possible summary PDF found on hearing documents" f"for {bill.bill_id}"
        )
        return ParserInterface.DiscoveryResult(preview, "", pdf_url, 0.8)

    @staticmethod
    def parse(base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """
        Second stage. We don't parse PDF text yet—just confirm a stable link.
        Return {"source_url": str}
        """
        return {"source_url": candidate.source_url}
