"""A parser for when the summary is on the hearing's Documents tab."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)

DL_PATH_RX = re.compile(r"/Events/DownloadDocument", re.I)
PDF_RX = re.compile(r"\.pdf($|\?)", re.I)


class SummaryHearingDocsPdfParser(ParserInterface):
    """Parser for when the summary is on the hearing's Documents tab."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Hearing page Documents tab PDF"
    cost = 1
    file_format = "pdf"

    @staticmethod
    def _norm_bill_id(s: str) -> str:
        """Normalize the bill ID."""
        # "H. 96" -> "H96", "H96" -> "H96"
        s = s.upper().replace("\xa0", " ")
        s = re.sub(r"[.\s]", "", s)
        return s

    @staticmethod
    def _title_from_href(href: str) -> str:
        """Get the title from the href."""
        # Try to read the Title= param; fall back to basename-ish
        try:
            q = parse_qs(urlparse(href).query)
            t = q.get("Title", [""])[0]
            return unquote(t)
        except Exception:  # pylint: disable=broad-exception-caught
            return ""

    @classmethod
    def _looks_like_summary_for_bill(
        cls, link_text: str, title_param: str, bill_id: str
    ) -> bool:
        """Check if the link text looks like a summary for the bill."""
        # We accept if:
        #   - "summary" appears (with flexible word boundaries) AND
        #   - bill_id ("H96") appears in either the link text or the
        # Title= param
        has_summary = bool(
            re.search(r"\bsummary\b", link_text, re.I)
            or re.search(r"\bsummary\b", title_param, re.I)
            or re.search(r"summary[_\-\s]", link_text, re.I)
            or re.search(r"summary[_\-\s]", title_param, re.I)
        )
        has_bill = bill_id in cls._norm_bill_id(
            link_text
        ) or bill_id in cls._norm_bill_id(title_param)
        return has_summary and has_bill

    @staticmethod
    def _extract_pdf_text(pdf_url: str, cache=None, config=None) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url, cache=cache, config=config, timeout=30
        )

    @classmethod
    def _find_bill_summary_in_pdf_text(
        cls, pdf_text: str, bill_id: str
    ) -> Optional[str]:
        """Find a bill summary in PDF text content using
        the format from the user's example.
        """
        lines = pdf_text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            normalized_line = cls._norm_bill_id(line)
            normalized_bill_id = cls._norm_bill_id(bill_id)
            if normalized_bill_id in normalized_line and re.search(
                r"\bsummary\b", line, re.I
            ):
                return line
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """
        Probe the hearing 'Documents' tab for a Summary PDF that matches this
        bill.
        Returns {"preview","source_url","confidence"} or None.
        """
        logger.debug("Trying %s...", cls.__name__)
        hearing_docs_url = str(bill.hearing_url)
        soup = cls.soup(hearing_docs_url)
        for a in soup.find_all("a", href=True):
            if not hasattr(a, "get"):
                continue
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if not DL_PATH_RX.search(href):
                continue
            if not PDF_RX.search(href):
                continue

            text = " ".join(a.get_text(strip=True).split())
            title_param = cls._title_from_href(href)
            bill_id = cls._norm_bill_id(bill.bill_id)
            if (
                text
                and "summary" in text.lower()
                and bill.bill_id in ["H.2244", "H.2250", "H.2251"]
            ):
                logger.debug(
                    "Found potential summary link for %s: text='%s', "
                    "title='%s', matches=%s",
                    bill.bill_id,
                    text,
                    title_param,
                    cls._looks_like_summary_for_bill(text, title_param, bill_id),
                )
            if cls._looks_like_summary_for_bill(text, title_param, bill_id):
                pdf_url = urljoin(base_url, href)
                preview = (
                    f"Found '{title_param or text}' in hearing "
                    f"Documents for {bill.bill_id}"
                )
                return ParserInterface.DiscoveryResult(preview, "", pdf_url, 0.95)
        for a in soup.find_all("a", href=True):
            if not hasattr(a, "get"):
                continue
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if not DL_PATH_RX.search(href):
                continue
            if not PDF_RX.search(href):
                continue
            text = " ".join(a.get_text(strip=True).split())
            title_param = cls._title_from_href(href)
            if (
                re.search(r"\bsummary\b", text, re.I)
                or re.search(r"\bsummary\b", title_param, re.I)
                or re.search(r"\breport\b", text, re.I)
                or re.search(r"\breport\b", title_param, re.I)
            ):
                if bill.bill_id in ["H.2244", "H.2250", "H.2251"]:
                    logger.debug(
                        "Second pass - Found potential summary PDF for %s: "
                        "text='%s', title='%s'",
                        bill.bill_id,
                        text,
                        title_param,
                    )
                pdf_url = urljoin(base_url, href)
                pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
                if pdf_text:
                    bill_summary_line = cls._find_bill_summary_in_pdf_text(
                        pdf_text, bill.bill_id
                    )
                    if bill_summary_line:
                        preview = (
                            f"Found summary in PDF content: "
                            f"'{bill_summary_line[:100]}...' "
                            f"for {bill.bill_id}"
                        )
                        return ParserInterface.DiscoveryResult(
                            preview,
                            pdf_text,
                            pdf_url,
                            0.85,
                        )

        return None

    @staticmethod
    def parse(_base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the summary."""
        return {"source_url": candidate.source_url}
