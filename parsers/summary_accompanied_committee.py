"""A parser for bill-specific documents on an accompanied bill's Committee Summary tab."""

import re
import logging
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)

_ACCOMPANIED_PATTERNS = [
    re.compile(
        r"Accompanied\s+a\s+(?:study\s+order)[,\s]+see\s+(?P<bill>[HS]\d+)",
        re.I,
    ),
    re.compile(
        r"Accompanied\s+(?:by\s+)?(?P<bill>[HS]\d+)",
        re.I,
    ),
]


class SummaryAccompaniedCommitteeParser(ParserInterface):
    """Parser for bill-specific documents on an accompanied bill's CommitteeSummary tab.

    When bill H1374 is accompanied by study order H5234, H5234's /CommitteeSummary
    page may list individual PDF or DOCX files for each accompanied bill. This parser
    finds the one associated with the original bill by matching its ID against three
    locations in priority order: the download href (filename), the link text, or the
    enclosing table row.
    """

    parser_type = ParserInterface.ParserType.SUMMARY
    location = "Accompanied bill Committee Summary document"
    cost = 4
    file_format = "document"

    @staticmethod
    def _find_bill_specific_doc(
        soup: BeautifulSoup, bill_id: str, base_url: str
    ) -> Optional[str]:
        """Find a PDF or DOCX download link associated with bill_id.

        Checks (in order): the href/filename, the link text, the enclosing <tr>.
        """
        bill_pattern = re.compile(re.escape(bill_id), re.I)
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not isinstance(href, str):
                continue
            if not re.search(r"\.(docx|pdf)($|\?)", href, re.I):
                continue
            if not re.search(r"/Download/DownloadDocument/", href, re.I):
                continue
            # Bill ID in the filename portion of the download URL
            if bill_pattern.search(href):
                return urljoin(base_url, href)
            # Bill ID in the visible link text
            if bill_pattern.search(a.get_text(strip=True)):
                return urljoin(base_url, href)
            # Bill ID anywhere in the enclosing table row
            row = a.find_parent("tr")
            if row and bill_pattern.search(row.get_text(" ", strip=True)):
                return urljoin(base_url, href)
        return None

    @classmethod
    def discover(
        cls, base_url: str, bill: BillAtHearing, cache=None, config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover a bill-specific committee summary DOCX on an accompanied bill's page."""
        logger.debug("Trying %s for %s...", cls.__name__, bill.bill_id)
        soup = cls.soup(bill.bill_url, cache=cache, config=config)

        for row in soup.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            action_text = cells[2].get_text(" ", strip=True)

            related_bill_id = None
            for pat in _ACCOMPANIED_PATTERNS:
                m = pat.search(action_text)
                if m:
                    related_bill_id = m.group("bill")
                    break
            if not related_bill_id:
                continue

            related_url = None
            for a_tag in cells[2].find_all("a", href=True):
                href = a_tag["href"]
                if related_bill_id in href:
                    if href.startswith("/"):
                        related_url = f"{base_url}{href}"
                    elif href.startswith("http"):
                        related_url = href
                    break
            if not related_url:
                related_url = f"{base_url}/Bills/194/{related_bill_id}"

            committee_summary_url = f"{related_url.rstrip('/')}/CommitteeSummary"
            cs_soup = cls.soup(committee_summary_url, cache=cache, config=config)

            docx_url = cls._find_bill_specific_doc(cs_soup, bill.bill_id, base_url)
            if not docx_url:
                logger.debug(
                    "No document for %s on %s CommitteeSummary",
                    bill.bill_id,
                    related_bill_id,
                )
                continue

            docx_text = DocumentExtractionService.extract_text(
                url=docx_url, cache=cache, config=config, timeout=30
            )
            if docx_text:
                preview = (
                    f"Found committee summary DOCX for {bill.bill_id} "
                    f"on accompanied bill {related_bill_id}\n\n"
                    f"{docx_text[:500]}{'...' if len(docx_text) > 500 else ''}"
                )
                return ParserInterface.DiscoveryResult(
                    preview, docx_text, docx_url, 0.90
                )
            else:
                preview = (
                    f"Found committee summary DOCX for {bill.bill_id} "
                    f"on accompanied bill {related_bill_id} "
                    f"(text extraction failed)"
                )
                return ParserInterface.DiscoveryResult(
                    preview, "", docx_url, 0.75
                )

        return None

    @staticmethod
    def parse(_base_url: str, candidate: ParserInterface.DiscoveryResult) -> dict:
        """Parse the summary."""
        return {"source_url": candidate.source_url}
