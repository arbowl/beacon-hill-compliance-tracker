"""Collect extension orders from the Massachusetts Legislature website."""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Optional, TYPE_CHECKING
from urllib.parse import urljoin

from bs4 import BeautifulSoup  # type: ignore

from components.committees import get_committees
from components.interfaces import _fetch_html
from components.models import ExtensionOrder, Committee
if TYPE_CHECKING:
    from components.utils import Cache
    from components.interfaces import Config


def _extract_extension_date(text: str) -> Optional[date]:
    """Extract extension date from extension order text."""
    # Common date patterns in extension orders
    date_patterns = [
        # "Wednesday, December 3, 2025"
        (
            r'\b([A-Za-z]+day,?\s+[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b',
            '%A, %B %d, %Y'
        ),
        (
            r'\b([A-Za-z]+day,?\s+[A-Za-z]+\s+\d{1,2}\s+\d{4})\b',
            '%A, %B %d %Y'
        ),
        # "December 3, 2025"
        (r'\b([A-Za-z]+\s+\d{1,2},?\s+\d{4})\b', '%B %d, %Y'),
        (r'\b([A-Za-z]+\s+\d{1,2}\s+\d{4})\b', '%B %d %Y'),
        # "12/3/2025" or "12/03/2025"
        (r'\b(\d{1,2}/\d{1,2}/\d{4})\b', '%m/%d/%Y'),
        # "2025-12-03"
        (r'\b(\d{4}-\d{1,2}-\d{1,2})\b', '%Y-%m-%d'),
    ]
    for pattern, fmt in date_patterns:
        matches = re.findall(pattern, text, re.I)
        for match in matches:
            try:
                return datetime.strptime(match, fmt).date()
            except ValueError:
                continue
    return None


def _extract_committee_from_text(
    text: str,
    base_url: str,
) -> Optional[str]:
    """Extract committee ID from extension order text."""
    # Look for committee patterns in the text
    committee_patterns = [
        r'committee on ([^,\n]+)',
        r'Joint Committee on ([^,\n]+)',
        r'Committee on ([^,\n]+)',
    ]
    committees: list[Committee] = get_committees(
        base_url,
        ("House", "Joint", "Senate")
    )
    committee_mapping = {
        committee.name: committee.id for committee in committees
    }
    for pattern in committee_patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        committee_name = match.group(1).strip()
        return committee_mapping.get(committee_name)
    return None


def _extract_bill_id_from_order_url(order_url: str) -> Optional[str]:
    """Extract bill ID from extension order URL as fallback.
    URLs are typically in format: /Bills/2025/H1234/House/Order/Text
    We need to extract the bill ID (H1234) from this pattern.
    """
    # Pattern to match the bill ID in the order URL
    # /Bills/YYYY/H1234/House/Order/Text or /Bills/YYYY/S1234/Senate/Order/Text
    bill_pattern = r"/Bills/\d+/([HS]\d+)/(?:House|Senate)/Order/Text"
    match = re.search(bill_pattern, order_url)
    if match:
        return match.group(1)
    return None


def _extract_bill_numbers_from_text(text: str) -> list[str]:
    """Extract bill numbers from extension order text.
    Looks for patterns like:
    - "House document numbered 357" -> "H357"
    - "Senate document numbered 43" -> "S43"
    - "Joint document numbered 12" -> "J12"
    """
    bill_numbers = []
    # Pattern to match chamber + document number(s)
    patterns = [
        # Single document: "House document numbered 357"
        r"(House|Senate|Joint)\s+document\s+numbered\s+(\d+)",
        r"(House|Senate|Joint)\s+document\s+No\.?\s*(\d+)",
        r"(House|Senate|Joint)\s+document\s+#(\d+)",
        r"current\s+(House|Senate|Joint)\s+document\s+numbered\s+(\d+)",
        r"current\s+(House|Senate|Joint)\s+document\s+No\.?\s*(\d+)",
        # Multiple documents: "current House documents numbered 2065, 2080,..."
        r"current\s+(House|Senate|Joint)\s+documents\s+"
        r"numbered\s+([\d,\s\sand]+)",
    ]
    for pattern in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            chamber = match.group(1).lower()
            doc_numbers_str = match.group(2)
            # Map chamber to prefix
            if chamber == "house":
                prefix = "H"
            elif chamber == "senate":
                prefix = "S"
            elif chamber == "joint":
                prefix = "J"
            else:
                continue
            # Handle document numbers (comma-separated, possibly with "and")
            if "," in doc_numbers_str or " and " in doc_numbers_str:
                # Split by comma and "and", then clean up each number
                parts = re.split(r",\s*|\s+and\s+", doc_numbers_str)
                doc_numbers = [
                    num.strip() for num in parts if num.strip().isdigit()
                ]
            else:
                # Single document number
                doc_numbers = [doc_numbers_str.strip()]
            # Create bill IDs for each document number
            for doc_number in doc_numbers:
                if not doc_number.isdigit():
                    continue
                bill_id = f"{prefix}{doc_number}"
                bill_numbers.append(bill_id)
    return bill_numbers


def _parse_extension_order_page(
    _base_url: str, order_url: str, html_text: Optional[str] = None,
    cache: Optional["Cache"] = None, config: Optional["Config"] = None
) -> list[ExtensionOrder]:
    """Parse a single extension order page to extract details for all bills
    mentioned.

    Args:
        _base_url: Base URL for the legislature website
        order_url: URL of the extension order page
        html_text: Optional pre-fetched HTML text (avoids re-fetching)
        cache: Optional cache instance for persistent storage
        config: Optional configuration (required if cache is provided)
    """
    try:
        # Use provided HTML text if available, otherwise fetch with cache
        if html_text is None:
            if cache and config:
                html_text = _fetch_html(
                    order_url,
                    timeout=10,
                    cache=cache,
                    config=config
                )
            else:
                # Fallback to non-cached fetch if no cache provided
                html_text = _fetch_html(order_url, timeout=10)
        soup = BeautifulSoup(html_text, "html.parser")
        text = soup.get_text(" ", strip=True)
        # Extract extension date
        extension_date = _extract_extension_date(text)
        is_date_fallback = False
        if not extension_date:
            # If no specific date found, we'll use a fallback date of 0
            # This will be handled later when we have the hearing date
            extension_date = date(1900, 1, 1)  # Placeholder date
            is_date_fallback = True
        # Extract committee ID
        committee_id = _extract_committee_from_text(text, _base_url)
        if not committee_id:
            # Default to unknown committee if we can't determine it
            committee_id = "UNKNOWN"
        # Determine order type from the page title or content
        order_type = "Extension Order"
        if "Committee Extension Order" in text:
            order_type = "Committee Extension Order"
        elif "Joint Committee" in text:
            order_type = "Joint Committee Extension Order"
        # Extract all bill numbers mentioned in the text
        bill_numbers = _extract_bill_numbers_from_text(text)
        if not bill_numbers:
            print(
                f"No bill numbers found in extension order text: {order_url}"
            )
            # Fallback: extract bill ID from the order URL itself
            bill_id_from_url = _extract_bill_id_from_order_url(order_url)
            if bill_id_from_url:
                print(
                    f"  Fallback: Using bill ID from URL: {bill_id_from_url}"
                )
                bill_numbers = [bill_id_from_url]
                # Mark this as a fallback case
                is_fallback = True
            else:
                print(f"  Could not extract bill ID from URL: {order_url}")
                return []
        else:
            is_fallback = False
        # Create ExtensionOrder objects for each bill mentioned
        extension_orders = []
        for bill_id in bill_numbers:
            extension_orders.append(ExtensionOrder(
                bill_id=bill_id,
                committee_id=committee_id,
                extension_date=extension_date,
                extension_order_url=order_url,
                order_type=order_type,
                discovered_at=datetime.now(),
                is_fallback=is_fallback,
                is_date_fallback=is_date_fallback
            ))
        return extension_orders
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Error parsing extension order {order_url}: {e}")
        return []


def collect_all_extension_orders(
    base_url: str,
    cache: Optional["Cache"] = None,
    config: Optional["Config"] = None
) -> list[ExtensionOrder]:
    """Collect all extension orders from the Massachusetts Legislature website.

    Uses cached HTML fetching for improved performance and reduced server load.
    """
    extension_orders = []
    # Process only Bills search pages
    search_types = ["Bills"]
    for search_type in search_types:
        print(f"Scraping {search_type} extension orders...")
        page = 1
        max_pages = 10  # Reduced safety limit
        previous_first_10_links = None
        duplicate_page_count = 0
        while page <= max_pages:
            # Construct URL with page parameter
            url = f"{base_url}/Bills/Search"
            params = {"searchTerms": "extension order", "page": page}
            print(f"Scraping {search_type} page {page}...")
            try:
                # Use cached HTML fetching
                html_text = _fetch_html(
                    url,
                    timeout=20,
                    cache=cache,
                    config=config,
                    params=params,
                    headers={"User-Agent": "legis-scraper/0.1"}
                )
                soup = BeautifulSoup(html_text, "html.parser")
                # Find all bill links on this page that might have
                # extension orders
                # We'll check each bill for extension orders
                bill_links = soup.find_all(
                    "a", href=re.compile(r"/Bills/\d+/(H|S)\d+")
                )
                if not bill_links:
                    print(
                        f"No more bill links found on {search_type} page "
                        f"{page}"
                    )
                    break
                print(
                    f"Found {len(bill_links)} total bill links on "
                    f"{search_type} page {page}"
                )
                # Get the first 10 bill links for duplicate detection
                current_first_10_links = [
                    link.get("href", "") for link in bill_links[:10]
                ]
                # Check if we're getting duplicate content (first 10 links
                # are the same)
                if (
                    current_first_10_links == previous_first_10_links
                    and page > 1
                ):
                    duplicate_page_count += 1
                    if duplicate_page_count >= 1:
                        print(
                            f"Detected duplicate content on {search_type} "
                            f"page {page} (first 10 entries match), "
                            f"stopping pagination"
                        )
                        break
                else:
                    duplicate_page_count = 0
                previous_first_10_links = current_first_10_links
                for link in bill_links:
                    if hasattr(link, 'get'):
                        href = link.get("href", "")
                    else:
                        href = ""
                    if not href:
                        continue
                    bill_url = urljoin(base_url, href)
                    # Extract bill ID from URL to determine chamber
                    bill_match = re.search(r"/Bills/\d+/([HS]\d+)", href)
                    if not bill_match:
                        continue
                    bill_id = bill_match.group(1)
                    chamber = (
                        "House" if bill_id.startswith("H") else "Senate"
                    )
                    # Construct the Order/Text URL
                    order_url = f"{bill_url}/{chamber}/Order/Text"
                    # Check if this extension order exists by trying to
                    # fetch it (use cached fetching)
                    try:
                        # Fetch the HTML once - it will be cached and reused
                        html_text = _fetch_html(
                            order_url,
                            timeout=10,
                            cache=cache,
                            config=config
                        )
                    # pylint: disable=broad-exception-caught
                    except Exception:
                        # If fetch fails, the extension order doesn't exist
                        continue
                    # Parse the extension order page using the fetched HTML
                    # This avoids double-fetching and ensures persistent
                    # caching
                    order_results = _parse_extension_order_page(
                        base_url, order_url, html_text=html_text,
                        cache=cache, config=config
                    )
                    for extension_order in order_results:
                        extension_orders.append(extension_order)
                        if extension_order.is_fallback:
                            print(
                                f"Found fallback extension order: "
                                f"{extension_order.bill_id} -> "
                                f"{extension_order.extension_date}"
                            )
                        else:
                            print(
                                f"Found extension order: "
                                f"{extension_order.bill_id} -> "
                                f"{extension_order.extension_date}"
                            )
                        # Cache the extension immediately if cache is
                        # provided for non-fallback cases
                        if cache:
                            cache.set_extension(
                                extension_order.bill_id,
                                extension_order.extension_date.isoformat(),
                                extension_order.extension_order_url
                            )
                            print(
                                f"  Cached extension for "
                                f"{extension_order.bill_id}"
                            )
                            # For fallback cases, also add the bill to
                            # cache with extensions field
                            if extension_order.is_fallback:
                                cache.add_bill_with_extensions(
                                    extension_order.bill_id
                                )
                page += 1
            # pylint: disable=broad-exception-caught
            except Exception as e:
                print(f"Error processing {search_type} page {page}: {e}")
                break
    print(f"Collected {len(extension_orders)} extension orders total")
    return extension_orders


def get_extension_orders_for_bill(
    extension_orders: list[ExtensionOrder], bill_id: str
) -> list[ExtensionOrder]:
    """Get all extension orders for a specific bill."""
    return [eo for eo in extension_orders if eo.bill_id == bill_id]


def get_latest_extension_date(
    extension_orders: list[ExtensionOrder], bill_id: str
) -> Optional[date]:
    """Get the latest extension date for a specific bill."""
    bill_extensions = get_extension_orders_for_bill(extension_orders, bill_id)
    if not bill_extensions:
        return None
    return max(eo.extension_date for eo in bill_extensions)
