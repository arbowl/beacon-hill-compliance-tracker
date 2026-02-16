"""Parser that downloads PDFs from hearing Documents tab and checks content."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote

from components.models import BillAtHearing
from components.interfaces import ParserInterface, DecayingUrlCache
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)

DL_PATH_RX = re.compile(r"/Events/DownloadDocument", re.I)
PDF_RX = re.compile(r"\.pdf($|\?)", re.I)

# Global cache for PDF content by hearing URL
_HEARING_PDF_CACHE = DecayingUrlCache()


class SummaryHearingDocsPdfContentParser(ParserInterface):
    """Parser for PDF summaries on the hearing's Documents tab."""

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Hearing page Documents tab PDF content"
    cost = 6
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

    @staticmethod
    def _extract_pdf_text(pdf_url: str, cache=None, config=None) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url, cache=cache, config=config, timeout=30
        )

    @classmethod
    def _pdf_contains_summary_for_bill(
        cls, pdf_text: str, bill_id: str
    ) -> Optional[str]:
        """Check if PDF contains summary content for the specific bill."""
        if not pdf_text:
            return None
        # Look for "Summary" keyword in the PDF content (case insensitive)
        if not re.search(r"\bsummary\b", pdf_text, re.I):
            return None
        # Normalize bill ID for comparison
        normalized_bill_id = cls._norm_bill_id(bill_id)
        # Check if the bill ID appears in the PDF content
        # Look for various formats: H.3444, H3444, H 3444, etc.
        bill_patterns = [
            re.escape(bill_id),  # Exact match (e.g., "H.3444")
            re.escape(normalized_bill_id),  # Normalized (e.g., "H3444")
            bill_id.replace(".", r"\.?\s*"),  # Flexible spacing/dots
            f"{bill_id[:1]}.{bill_id[1:]}",  # In case of missing dot
        ]
        bill_found = False
        for pattern in bill_patterns:
            if re.search(pattern, pdf_text, re.I):
                bill_found = True
                break
        if not bill_found:
            return None
        # Extract a relevant snippet containing both the bill ID and "summary"
        lines = pdf_text.split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            # Check if this line contains both bill ID and summary
            line_has_bill = any(
                re.search(pattern, line, re.I) for pattern in bill_patterns
            )
            line_has_summary = re.search(r"\bsummary\b", line, re.I)
            if line_has_bill and line_has_summary:
                # Return this line as the summary snippet
                return line
            if line_has_bill:
                # Check nearby lines for summary content
                context_lines = []
                start_idx = max(0, i - 2)
                end_idx = min(len(lines), i + 3)
                for j in range(start_idx, end_idx):
                    context_line = lines[j].strip()
                    if not context_line:
                        continue
                    context_lines.append(context_line)
                    if not re.search(r"\bsummary\b", context_line, re.I):
                        continue
                    # Found summary in context, return combined snippet
                    return " ".join(context_lines)

        # If we found both bill ID and summary but not in the same context,
        # return a generic confirmation
        return f"PDF contains summary content for {bill_id}"

    @classmethod
    def _download_hearing_pdfs(
        cls, hearing_docs_url: str, base_url: str, cache=None, config=None
    ) -> list[dict]:
        """Download all PDFs from a hearing and return their content."""
        soup = cls.soup(hearing_docs_url)
        # Find all PDF download links
        pdf_links = []
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
            pdf_url = urljoin(base_url, href)
            pdf_links.append(
                {"url": pdf_url, "text": text, "title": title_param, "href": href}
            )
        # Download and extract text from all PDFs
        cached_pdfs = []
        for pdf_info in pdf_links:
            pdf_url = pdf_info["url"]
            title_param = pdf_info["title"]
            text = pdf_info["text"]
            logger.debug("Downloading PDF: %s", title_param or text)
            # Download and parse the PDF content
            pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
            if not pdf_text:
                continue
            cached_pdfs.append(
                {
                    "url": pdf_url,
                    "text": pdf_text,
                    "title": title_param,
                    "link_text": text,
                }
            )
        return cached_pdfs

    @classmethod
    def _search_cached_pdfs_for_bill(
        cls, cached_pdfs: list[dict], bill_id: str
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Search cached PDF content for a specific bill."""
        # Sort PDFs: those matching the bill ID first, then others
        normalized_bill_id = cls._norm_bill_id(bill_id)

        def pdf_priority(pdf_info: dict[str, str]) -> int:
            title = pdf_info["title"]
            link_text = pdf_info["link_text"]
            # Higher priority (lower number) for PDFs that mention bill ID
            if normalized_bill_id in cls._norm_bill_id(
                title
            ) or normalized_bill_id in cls._norm_bill_id(link_text):
                return 0
            return 1

        cached_pdfs.sort(key=pdf_priority)
        # Search each PDF for summary content
        for pdf_info in cached_pdfs:
            pdf_url = pdf_info["url"]
            pdf_text = pdf_info["text"]
            title_param = pdf_info["title"]
            link_text = pdf_info["link_text"]

            logger.debug(
                "Searching cached PDF for %s: %s", bill_id, title_param or link_text
            )

            # Check if this PDF contains summary content for our bill
            summary_snippet = cls._pdf_contains_summary_for_bill(pdf_text, bill_id)
            if summary_snippet:
                preview = (
                    f"Found summary content in PDF "
                    f"'{title_param or link_text}': "
                    f"'{summary_snippet[:150]}...' for {bill_id}"
                )
                full_text = (
                    pdf_text[:2000] + "..." if len(pdf_text) > 2000 else pdf_text
                )
                return ParserInterface.DiscoveryResult(
                    preview,
                    full_text,
                    pdf_url,
                    0.80,  # Lower confidence
                )

        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Download and check PDF content from hearing Documents tab for
        summaries. Uses caching to avoid re-downloading PDFs for bills
        from the same hearing. Returns {"preview","source_url","confidence"}
        or None.
        """
        logger.debug("Trying %s...", cls.__name__)
        hearing_docs_url = str(bill.hearing_url)
        # Check if we've already processed this hearing
        if hearing_docs_url not in _HEARING_PDF_CACHE:
            logger.debug(
                "First time processing hearing %s - downloading all PDFs",
                hearing_docs_url,
            )
            _HEARING_PDF_CACHE[hearing_docs_url] = cls._download_hearing_pdfs(
                hearing_docs_url, base_url, cache, config  # type: ignore
            )
        else:
            logger.debug("Using cached PDFs for hearing %s", hearing_docs_url)

        # Search cached PDFs for this specific bill
        cached_pdfs = _HEARING_PDF_CACHE[hearing_docs_url]
        return cls._search_cached_pdfs_for_bill(
            cached_pdfs, bill.bill_id  # type: ignore
        )

    @staticmethod
    def parse(_base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the summary."""
        # Nothing heavy yet; just return the stable link for the report/cache
        return {"source_url": candidate.source_url}
