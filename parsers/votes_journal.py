"""A parser for votes found in House and Senate Journal PDFs."""

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from components.models import BillAtHearing
from components.interfaces import ParserInterface
from components.extraction import DocumentExtractionService

logger = logging.getLogger(__name__)

# Regex pattern to find votes in journal PDFs
# Pattern matches:
# "By (Ms.|Mr.) [Name], for the committee on [Committee],
# on (Senate|House), Nos. [numbers],
#  an Order relative to authorizing the joint committee on
# [Committee] ... (Senate, No. [number]) [optional]"
VOTE_PATTERN = re.compile(
    r"By\s+(Ms\.|Mr\.)\s+[A-Z][a-z]+, for the committee on\s+([A-Za-z& ]+),"
    r"\s*on\s+(Senate|House),\s*Nos?\.\s*([0-9, ]+),"
    r"\s*an Order relative to authorizing the joint committee "
    r"on\s+([A-Za-z& ]+)"
    r".*?\(Senate, No\.\s*([0-9]+)\)(?:\s*\[([^\]]+)\])?",
    re.DOTALL | re.MULTILINE | re.IGNORECASE
)

PDF_RX = re.compile(r"\.pdf($|\?)", re.I)


class VotesJournalParser(ParserInterface):
    """Parser for votes found in House and Senate Journal PDFs."""

    parser_type = ParserInterface.ParserType.VOTES
    location = "House/Senate Journal PDFs"
    cost = 7  # Higher cost due to multiple PDF downloads

    # Cache for downloaded journal PDFs (by URL)
    _journal_pdf_cache: dict[str, str] = {}

    @staticmethod
    def _extract_pdf_text(
        pdf_url: str,
        cache=None,
        config=None
    ) -> Optional[str]:
        """Extract text content from a PDF URL using extraction service."""
        return DocumentExtractionService.extract_text(
            url=pdf_url,
            cache=cache,
            config=config,
            timeout=30
        )

    @staticmethod
    def _normalize_bill_id(
        bill_text: str, chamber: Optional[str] = None
    ) -> Optional[str]:
        """Normalize bill ID from various formats.

        Args:
            bill_text: Bill text like "House, No. 73" or "73"
            chamber: "House" or "Senate" to determine prefix

        Returns:
            Normalized bill ID like "H73" or "S197", or None if invalid
        """
        if not bill_text:
            return None
        # Clean up the text
        bill_text = bill_text.strip().replace(",", "").replace(".", "")
        # Extract numbers
        numbers = re.findall(r'\d+', bill_text)
        if not numbers:
            return None
        # Determine prefix
        if chamber:
            prefix = "H" if chamber.lower() == "house" else "S"
        else:
            # Try to infer from text
            if "house" in bill_text.lower() or "h" in bill_text.lower():
                prefix = "H"
            elif "senate" in bill_text.lower() or "s" in bill_text.lower():
                prefix = "S"
            else:
                # Default to House if unclear
                prefix = "H"
        # Use first number found
        number = numbers[0]
        return f"{prefix}{number}"

    @classmethod
    def _get_house_journal_pdf_urls(
        cls,
        base_url: str,
        session: str = "194",
        year: str = "2025"
    ) -> list[str]:
        """Get House journal PDF URLs.

        Args:
            base_url: Base URL for the legislature website
            session: Session number (e.g., "194")
            year: Year (e.g., "2025")

        Returns:
            List of PDF URLs
        """
        house_journal_url = (
            f"{base_url}/Journal/House/{session}/{year}/Journal"
        )
        pdf_urls = []
        try:
            # Try to scrape the page for PDF links first
            logger.debug("Scraping House journal page: %s", house_journal_url)
            soup = cls.soup(house_journal_url)
            # Find all PDF links on the page
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if not isinstance(href, str):
                    continue
                # Check if it's a PDF link
                if not PDF_RX.search(href):
                    continue
                # Check if it's a journal PDF
                if "/Journal/House/" in href or "/Journal/" in href:
                    full_url = urljoin(base_url, href)
                    if full_url not in pdf_urls:
                        pdf_urls.append(full_url)
                        logger.debug("Found House journal PDF: %s", full_url)
            # If no PDF links found, assume the URL itself is a
            # direct PDF download
            if not pdf_urls:
                logger.debug(
                    "No PDF links found on House journal page, "
                    "treating URL as direct PDF: %s", house_journal_url
                )
                pdf_urls.append(house_journal_url)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(
                "Failed to scrape House journal page %s: %s. "
                "Treating as direct PDF download.",
                house_journal_url, e
            )
            # Fallback: treat as direct PDF download
            pdf_urls.append(house_journal_url)
        return pdf_urls

    @classmethod
    def _get_senate_journal_pdf_urls(
        cls,
        base_url: str,
        session: str = "194"
    ) -> list[str]:
        """Get Senate journal PDF URLs by scraping month pages.

        Args:
            base_url: Base URL for the legislature website
            session: Session number (e.g., "194")

        Returns:
            List of PDF URLs
        """
        pdf_urls = []
        # Iterate through months 01-11 (January through November)
        for month in range(1, 12):
            month_str = f"{month:02d}"
            # Format: https://malegislature.gov/Journal/Senate/194/01-01-2025
            month_url = (
                f"{base_url}/Journal/Senate/{session}/{month_str}-01-2025"
            )
            try:
                logger.debug(
                    "Scraping Senate journal month page: %s",
                    month_url
                )
                soup = cls.soup(month_url)
                # Find all PDF links on the page
                for a in soup.find_all("a", href=True):
                    href = a.get("href", "")
                    if not isinstance(href, str):
                        continue
                    # Check if it's a PDF link
                    if not PDF_RX.search(href):
                        continue
                    # Check if it matches the journal PDF pattern
                    # e.g., /Journal/Senate/194/952/sj02032025_1100AM.pdf
                    if "/Journal/Senate/" in href:
                        full_url = urljoin(base_url, href)
                        if full_url not in pdf_urls:
                            pdf_urls.append(full_url)
                            logger.debug(
                                "Found Senate journal PDF: %s",
                                full_url
                            )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to scrape Senate journal month page %s: %s",
                    month_url, e
                )
                continue
        return pdf_urls

    @classmethod
    def _download_and_cache_journal_pdfs(
        cls,
        base_url: str,
        cache=None,
        config=None
    ) -> list[dict[str, str]]:
        """Download and cache all journal PDFs.

        Args:
            base_url: Base URL for the legislature website
            cache: Optional cache instance
            config: Optional config instance

        Returns:
            List of dicts with "url" and "text" keys
        """
        cached_pdfs = []
        # Get House journal PDFs
        logger.debug("Downloading House journal PDFs...")
        house_urls = cls._get_house_journal_pdf_urls(base_url)
        for pdf_url in house_urls:
            # Check cache first
            if pdf_url in cls._journal_pdf_cache:
                logger.debug("Using cached House journal PDF: %s", pdf_url)
                cached_pdfs.append({
                    "url": pdf_url,
                    "text": cls._journal_pdf_cache[pdf_url]
                })
            else:
                pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
                if pdf_text:
                    cls._journal_pdf_cache[pdf_url] = pdf_text
                    cached_pdfs.append({
                        "url": pdf_url,
                        "text": pdf_text
                    })
                    logger.debug(
                        "Downloaded and cached House journal PDF: %s",
                        pdf_url
                    )
        # Get Senate journal PDFs
        logger.debug("Downloading Senate journal PDFs...")
        senate_urls = cls._get_senate_journal_pdf_urls(base_url)
        for pdf_url in senate_urls:
            # Check cache first
            if pdf_url in cls._journal_pdf_cache:
                logger.debug("Using cached Senate journal PDF: %s", pdf_url)
                cached_pdfs.append({
                    "url": pdf_url,
                    "text": cls._journal_pdf_cache[pdf_url]
                })
            else:
                pdf_text = cls._extract_pdf_text(pdf_url, cache, config)
                if pdf_text:
                    cls._journal_pdf_cache[pdf_url] = pdf_text
                    cached_pdfs.append({
                        "url": pdf_url,
                        "text": pdf_text
                    })
                    logger.debug(
                        "Downloaded and cached Senate journal PDF: %s",
                        pdf_url
                    )
        return cached_pdfs

    @classmethod
    def _search_journals_for_bill(
        cls,
        cached_pdfs: list[dict[str, str]],
        bill: BillAtHearing
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Search journal PDFs for the given bill.

        Args:
            cached_pdfs: List of dicts with "url" and "text" keys
            bill: Bill to search for

        Returns:
            DiscoveryResult if bill is found, None otherwise
        """
        # Normalize the bill ID for matching
        bill_id_normalized = bill.bill_id.upper()
        for pdf_info in cached_pdfs:
            pdf_text = pdf_info["text"]
            pdf_url = pdf_info["url"]
            # Search for votes using the regex pattern
            matches = VOTE_PATTERN.finditer(pdf_text)
            for match in matches:
                # Extract bill numbers from the match
                # Group 3: "Senate" or "House"
                chamber = match.group(3)
                # Group 4: Bill numbers like "73" or "73, 74, 75"
                bill_numbers_str = match.group(4)
                # Group 6: Senate bill number (if present)
                senate_bill_num = match.group(6) if match.group(6) else None
                # Parse bill numbers from group 4 (e.g., "73, 74" or "197")
                bill_numbers = []
                if bill_numbers_str:
                    # Split by comma and extract numbers
                    numbers = re.findall(r'\d+', bill_numbers_str)
                    for num in numbers:
                        normalized = cls._normalize_bill_id(num, chamber)
                        if normalized:
                            bill_numbers.append(normalized)
                            logger.debug(
                                "Extracted bill number %s from chamber %s: %s",
                                num, chamber, normalized
                            )
                # Also check the Senate bill number if present (group 6)
                if senate_bill_num:
                    senate_normalized = cls._normalize_bill_id(
                        senate_bill_num,
                        "Senate"
                    )
                    if senate_normalized:
                        bill_numbers.append(senate_normalized)
                        logger.debug(
                            "Extracted Senate bill number: %s",
                            senate_normalized
                        )
                # Check if our bill is in the list
                bill_numbers_upper = [b.upper() for b in bill_numbers]
                logger.debug(
                    "Checking if bill %s is in extracted bill numbers: %s",
                    bill_id_normalized, bill_numbers_upper
                )
                if bill_id_normalized in bill_numbers_upper:
                    # Found the bill!
                    match_text = match.group(0)
                    preview = (
                        f"Found vote record for {bill.bill_id} "
                        f"in journal PDF\n"
                        f"Chamber: {chamber}\n"
                        f"Committee: {match.group(2)}\n"
                        f"Match preview:\n{match_text[:500]}..."
                    )
                    return ParserInterface.DiscoveryResult(
                        preview=preview,
                        full_text=match_text,
                        source_url=pdf_url,
                        confidence=0.9
                    )
        return None

    @classmethod
    def discover(
        cls,
        base_url: str,
        bill: BillAtHearing,
        cache=None,
        config=None
    ) -> Optional[ParserInterface.DiscoveryResult]:
        """Discover votes in House and Senate journal PDFs."""
        logger.debug("Trying %s for bill %s...", cls.__name__, bill.bill_id)
        # Download and cache all journal PDFs
        cached_pdfs = cls._download_and_cache_journal_pdfs(
            base_url, cache, config
        )
        if not cached_pdfs:
            logger.debug("No journal PDFs found or downloaded")
            return None
        # Search for the bill in the cached PDFs
        result = cls._search_journals_for_bill(cached_pdfs, bill)
        if result:
            logger.debug("Found bill %s in journal PDFs", bill.bill_id)
        else:
            logger.debug("Bill %s not found in journal PDFs", bill.bill_id)
        return result

    @classmethod
    def parse(
        cls, _base_url: str, candidate: ParserInterface.DiscoveryResult
    ) -> dict:
        """Parse the journal vote document."""
        return {
            "location": cls.location,
            "source_url": candidate.source_url,
            "motion": "Journal vote record",
            "date": None,  # Could be extracted from PDF if available
            "tallies": None,  # Not available in this format
            "records": []  # Individual member votes not available
        }
