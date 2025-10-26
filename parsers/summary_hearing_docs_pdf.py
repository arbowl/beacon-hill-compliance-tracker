"""A parser for when the summary is on the hearing's Documents tab."""

import io
import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import PyPDF2  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface

logger = logging.getLogger(__name__)

DL_PATH_RX = re.compile(r"/Events/DownloadDocument", re.I)
PDF_RX = re.compile(r"\.pdf($|\?)", re.I)


class SummaryHearingDocsPdfParser(ParserInterface):

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Hearing page Documents tab PDF"
    cost = 1

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
        #   - bill_id ("H96") appears in either the link text or the Title= param
        has_summary = bool(
            re.search(r"\bsummary\b", link_text, re.I) or
            re.search(r"\bsummary\b", title_param, re.I) or
            re.search(r"summary[_\-\s]", link_text, re.I) or
            re.search(r"summary[_\-\s]", title_param, re.I)
        )
        has_bill = (
            bill_id in cls._norm_bill_id(link_text) or
            bill_id in cls._norm_bill_id(title_param)
        )
        return has_summary and has_bill

    @staticmethod
    def _extract_pdf_text(pdf_url: str) -> Optional[str]:
        """Extract text content from a PDF URL."""
        try:
            content = ParserInterface._fetch_binary(pdf_url, timeout=30)

            # Read PDF from memory
            pdf_file = io.BytesIO(content)
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
            logger.warning("Could not extract text from PDF %s: %s", pdf_url, e)
            return None

        return None

    @classmethod
    def _find_bill_summary_in_pdf_text(
        cls, pdf_text: str, bill_id: str
    ) -> Optional[str]:
        """Find a bill summary in PDF text content using the format from the user's example."""  # noqa: E501
        # Look for lines that match the pattern: H.XXXX Summary_Description
        # This handles the specific format shown in the user's example
        lines = pdf_text.split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if this line contains the bill ID and "Summary"
            normalized_line = cls._norm_bill_id(line)
            normalized_bill_id = cls._norm_bill_id(bill_id)

            # Look for the pattern: bill_id + "Summary" (case insensitive)
            if (normalized_bill_id in normalized_line and
                    re.search(r'\bsummary\b', line, re.I)):
                return line

        return None

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """
        Probe the hearing 'Documents' tab for a Summary PDF that matches this bill.
        Returns {"preview","source_url","confidence"} or None.
        """
        logger.debug("Trying %s...", cls.__name__)
        # We rely on hearing_url (added in step 2 tweak)
        hearing_docs_url = bill.hearing_url  # docs are here (tabbed content)
        soup = cls._soup(hearing_docs_url)

        # First pass: Look for any link like /Events/DownloadDocument?...fileExtension=.pdf  # noqa: E501
        # This is the original logic that checks link text and title parameters
        for a in soup.find_all("a", href=True):
            if not hasattr(a, 'get'):
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

            bill_id = cls._norm_bill_id(bill.bill_id)  # "H96"
            
            # Debug logging for troubleshooting (only for specific bill patterns)
            if text and "summary" in text.lower() and bill.bill_id in ["H.2244", "H.2250", "H.2251"]:
                logger.debug(
                    "Found potential summary link for %s: text='%s', "
                    "title='%s', matches=%s",
                    bill.bill_id, text, title_param,
                    cls._looks_like_summary_for_bill(text, title_param, bill_id)
                )
            
            if cls._looks_like_summary_for_bill(text, title_param, bill_id):
                pdf_url = urljoin(base_url, href)
                preview = (f"Found '{title_param or text}' in hearing "
                        f"Documents for {bill.bill_id}")
                return ParserInterface.DiscoveryResult(
                    preview,
                    "",
                    pdf_url,
                    0.95
                )

        # Second pass: Fallback - Download and parse PDF content
        # This handles cases where the link text doesn't match but the PDF content does  # noqa: E501
        for a in soup.find_all("a", href=True):
            if not hasattr(a, 'get'):
                continue
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if not DL_PATH_RX.search(href):
                continue
            if not PDF_RX.search(href):
                continue

            # Check if this looks like it could be a summary document
            text = " ".join(a.get_text(strip=True).split())
            title_param = cls._title_from_href(href)

            # Look for any PDF that might contain summaries (less strict criteria)
            if (re.search(r"\bsummary\b", text, re.I) or
                    re.search(r"\bsummary\b", title_param, re.I) or
                    re.search(r"\breport\b", text, re.I) or
                    re.search(r"\breport\b", title_param, re.I)):

                if bill.bill_id in ["H.2244", "H.2250", "H.2251"]:
                    logger.debug(
                        "Second pass - Found potential summary PDF for %s: "
                        "text='%s', title='%s'",
                        bill.bill_id, text, title_param
                    )

                pdf_url = urljoin(base_url, href)

                # Download and parse the PDF content
                pdf_text = cls._extract_pdf_text(pdf_url)
                if pdf_text:
                    # Look for our specific bill in the PDF content
                    bill_summary_line = cls._find_bill_summary_in_pdf_text(
                        pdf_text, bill.bill_id)
                    if bill_summary_line:
                        preview = (f"Found summary in PDF content: "
                                f"'{bill_summary_line[:100]}...' "
                                f"for {bill.bill_id}")
                        return ParserInterface.DiscoveryResult(
                            preview,
                            pdf_text,
                            pdf_url,
                            0.85,  # Slightly lower confidence
                        )

        return None

    @staticmethod
    def parse(
        _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the summary."""
        # Nothing heavy yet; just return the stable link for the report/cache
        return {"source_url": candidate.source_url}
