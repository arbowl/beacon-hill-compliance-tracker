"""A parser for when the votes are on the bill's PDF."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import PyPDF2

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)

PDF_RX = re.compile(r"\.pdf($|\?)", re.I)
VOTE_HINTS = [r"\bvote\b", r"\bvoting\b", r"\brecorded vote\b", r"\broll[- ]?call\b"]


class VotesBillPdfParser(ParserInterface):
    """Parser for when the votes are on the bill's PDF."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "Bill page PDF"
    cost = 5

    @staticmethod
    def _extract_pdf_text(pdf_url: str) -> Optional[str]:
        """Extract text content from a PDF URL."""
        try:
            content = ParserInterface._fetch_binary(
                pdf_url, timeout=30
            )
            pdf_file = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            text_content = []
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text_content.append(page_text)
            if text_content:
                full_text = "\n".join(text_content)
                full_text = re.sub(r'\s+', ' ', full_text).strip()
                return full_text
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Could not extract text from PDF %s: %s", pdf_url, e)
            return None
        return None

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover the votes."""
        logger.debug("Trying %s...", cls.__name__)
        soup = cls.soup(bill.bill_url)
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
                pdf_text = cls._extract_pdf_text(pdf_url)

                if pdf_text:
                    preview = f"Possible vote PDF on bill page: {text or href}"
                    if len(pdf_text) > 200:
                        preview += f"\n\nPDF Content Preview:\n{pdf_text[:500]}..."
                    else:
                        preview += f"\n\nPDF Content:\n{pdf_text}"
                    return ParserInterface.DiscoveryResult(
                        preview,
                        pdf_text,
                        pdf_url,
                        0.8,
                    )
                else:
                    preview = (
                        f"Possible vote PDF on bill page: "
                        f"{text or href} (text extraction failed)"
                    )
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
