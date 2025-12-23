"""Collect the committee contact info from the committee page."""

import re
import logging
from urllib.parse import urljoin
from typing import Optional

from components.models import Committee, CommitteeContact
from components.interfaces import ParserInterface
from components.utils import Cache

PHONE_RX = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}")
ROOM_RX = re.compile(r"\bRoom\s+[A-Za-z0-9\-]+", re.I)
EMAIL_RX = re.compile(r"[a-zA-Z0-9._%+-]+@(?:masenate|mahouse)\.gov", re.I)


def _validate_email_domain(email: str) -> bool:
    """Validate that email has expected Massachusetts legislature domain."""
    if not email:
        return False
    email = email.lower().strip()
    valid_domains = ["@masenate.gov", "@mahouse.gov"]
    for domain in valid_domains:
        if email.endswith(domain):
            return True
    return False


def _get_legislator_email(url: str) -> str:
    """Extract email from legislator profile page."""
    try:
        soup = ParserInterface.soup(url)
        email_links = soup.find_all("a", href=re.compile(r"mailto:", re.I))
        for link in email_links:
            if hasattr(link, "get"):
                href = link.get("href", "")
                if isinstance(href, str) and href.startswith("mailto:"):
                    email = href.replace("mailto:", "").strip()
                    if EMAIL_RX.match(email) and _validate_email_domain(email):
                        return email
        for selector in ["div", "p", "span", "td"]:
            elements = soup.find_all(selector)
            for elem in elements:
                text = elem.get_text(strip=True)
                email_match = EMAIL_RX.search(text)
                if email_match:
                    email = email_match.group(0)
                    if _validate_email_domain(email):
                        return email
        page_text = soup.get_text()
        email_match = EMAIL_RX.search(page_text)
        if email_match:
            email = email_match.group(0)
            if _validate_email_domain(email):
                return email
        return ""
    except Exception:  # pylint: disable=broad-exception-caught
        return ""


def get_committee_contact(
    base_url: str, committee: Committee, cache: Optional[Cache] = None
) -> CommitteeContact:
    """
    On the committee detail page, scrape both Senate and House Contact blocks
    (room, address, phone) for both chambers.
    """
    # Check cache first if available
    if cache:
        cached_contact: Optional[dict[str, str]] = cache.get_committee_contact(
            committee.id
        )
        if cached_contact:
            logging.info("Using cached contact info for committee %s", committee.id)
            return CommitteeContact(
                committee_id=cached_contact["committee_id"],
                name=cached_contact["name"],
                chamber=cached_contact["chamber"],
                url=cached_contact["url"],
                house_room=cached_contact.get("house_room"),
                house_address=cached_contact.get("house_address"),
                house_phone=cached_contact.get("house_phone"),
                senate_room=cached_contact.get("senate_room"),
                senate_address=cached_contact.get("senate_address"),
                senate_phone=cached_contact.get("senate_phone"),
                senate_chair_name=cached_contact.get("senate_chair_name", ""),
                senate_chair_email=cached_contact.get("senate_chair_email", ""),
                senate_vice_chair_name=cached_contact.get("senate_vice_chair_name", ""),
                senate_vice_chair_email=cached_contact.get(
                    "senate_vice_chair_email", ""
                ),
                house_chair_name=cached_contact.get("house_chair_name", ""),
                house_chair_email=cached_contact.get("house_chair_email", ""),
                house_vice_chair_name=cached_contact.get("house_vice_chair_name", ""),
                house_vice_chair_email=cached_contact.get("house_vice_chair_email", ""),
            )

    logging.info("Fetching contact info for committee %s", committee.id)
    url = urljoin(base_url, f"/Committees/Detail/{committee.id}")
    soup = ParserInterface.soup(url)

    def extract_contact_info(
        section_text: str,
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        room_match = ROOM_RX.search(section_text)
        room = room_match.group(0) if room_match else None
        phone_match = PHONE_RX.search(section_text)
        phone = phone_match.group(0) if phone_match else None

        # Address line is usually "24 Beacon St. Room XXX Boston, MA 02133"
        address = None
        if "Boston" in section_text:
            m = re.search(r"24 Beacon St\..+Boston,\s*MA\s*\d{5}", section_text)
            if m:
                address = m.group(0)
            elif room:
                address = f"24 Beacon St. {room} Boston, MA 02133"

        return room, address, phone

    # Look for Senate Contact section
    senate_room, senate_address, senate_phone = None, None, None
    for h in soup.find_all(["h3", "h4", "strong"]):
        if "Senate Contact" in h.get_text():
            parent = h.find_parent()
            if parent:
                senate_text = " ".join(parent.get_text(" ", strip=True).split())
                senate_room, senate_address, senate_phone = extract_contact_info(
                    senate_text
                )
            break

    # Look for House Contact section
    house_room, house_address, house_phone = None, None, None
    for h in soup.find_all(["h3", "h4", "strong"]):
        if "House Contact" in h.get_text():
            parent = h.find_parent()
            if parent:
                house_text = " ".join(parent.get_text(" ", strip=True).split())
                house_room, house_address, house_phone = extract_contact_info(
                    house_text
                )
            break

    # Extract Chair and Vice Chair information
    senate_chair_name = ""
    senate_chair_url = ""
    senate_vice_chair_name = ""
    senate_vice_chair_url = ""
    house_chair_name = ""
    house_chair_url = ""
    house_vice_chair_name = ""
    house_vice_chair_url = ""

    # Look for Senate Members section
    senate_section = soup.find("h2", string="Senate Members")
    if senate_section:
        # Find the committee member list (ul.committeeMemberList)
        senate_container = senate_section.find_next("ul", class_="committeeMemberList")
        if not senate_container:
            # Fallback: find any div container
            senate_container = senate_section.find_next("div")
        if senate_container and hasattr(senate_container, "find_all"):
            # Look for Chair and Vice Chair patterns
            for elem in senate_container.find_all(["div", "p", "span", "li"]):
                text = elem.get_text(strip=True)
                if "Chair" in text and "Vice" not in text:
                    # Look for a link in this element or nearby
                    link = elem.find("a")
                    if not link:
                        link = elem.find_previous("a")
                    if not link:
                        link = elem.find_next("a")
                    if link:
                        senate_chair_name = link.get_text(strip=True)
                        senate_chair_url = urljoin(base_url, link.get("href", ""))
                elif "Vice" in text and "Chair" in text:
                    # For Vice Chair, link is typically in parent container
                    link = None
                    # First try the parent container (thumbnailGroup)
                    if elem.parent:
                        link = elem.parent.find("a")
                    # Fallback: try current element and siblings
                    if not link:
                        link = elem.find("a")
                    if not link:
                        link = elem.find_previous("a")
                    if not link:
                        link = elem.find_next("a")
                    if link:
                        senate_vice_chair_name = link.get_text(strip=True)
                        senate_vice_chair_url = urljoin(base_url, link.get("href", ""))

        # Look for House Members section
        house_section = soup.find("h2", string="House Members")
        if house_section:
            # Find the committee member list (ul.committeeMemberList)
            house_container = house_section.find_next(
                "ul", class_="committeeMemberList"
            )
            if not house_container:
                # Fallback: find any div container
                house_container = house_section.find_next("div")
            if house_container and hasattr(house_container, "find_all"):
                # Look for Chair and Vice Chair patterns
                for elem in house_container.find_all(["div", "p", "span", "li"]):
                    text = elem.get_text(strip=True)
                    if "Chair" in text and "Vice" not in text:
                        # Look for a link in this element or nearby
                        link = elem.find("a")
                        if not link:
                            link = elem.find_previous("a")
                        if not link:
                            link = elem.find_next("a")
                        if link:
                            house_chair_name = link.get_text(strip=True)
                            house_chair_url = urljoin(base_url, link.get("href", ""))
                    elif "Vice" in text and "Chair" in text:
                        # For Vice Chair, link is typically in parent container
                        link = None
                        # First try the parent container (thumbnailGroup)
                        if elem.parent:
                            link = elem.parent.find("a")
                        # Fallback: try current element and siblings
                        if not link:
                            link = elem.find("a")
                        if not link:
                            link = elem.find_previous("a")
                        if not link:
                            link = elem.find_next("a")
                        if link:
                            house_vice_chair_name = link.get_text(strip=True)
                            house_vice_chair_url = urljoin(
                                base_url, link.get("href", "")
                            )

    # Fetch emails from legislator profile pages
    senate_chair_email = ""
    senate_vice_chair_email = ""
    house_chair_email = ""
    house_vice_chair_email = ""
    if senate_chair_url:
        logging.info("Fetching email for Senate Chair: %s", senate_chair_name)
        senate_chair_email = _get_legislator_email(senate_chair_url)
    if senate_vice_chair_url:
        logging.info("Fetching email for Senate Vice Chair: %s", senate_vice_chair_name)
        senate_vice_chair_email = _get_legislator_email(senate_vice_chair_url)
    if house_chair_url:
        logging.info("Fetching email for House Chair: %s", house_chair_name)
        house_chair_email = _get_legislator_email(house_chair_url)
    if house_vice_chair_url:
        logging.info("Fetching email for House Vice Chair: %s", house_vice_chair_name)
        house_vice_chair_email = _get_legislator_email(house_vice_chair_url)
    contact = CommitteeContact(
        committee_id=committee.id,
        name=committee.name,
        chamber=committee.chamber,
        url=committee.url,
        house_room=house_room,
        house_address=house_address,
        house_phone=house_phone,
        senate_room=senate_room,
        senate_address=senate_address,
        senate_phone=senate_phone,
        senate_chair_name=senate_chair_name,
        senate_chair_email=senate_chair_email,
        senate_vice_chair_name=senate_vice_chair_name,
        senate_vice_chair_email=senate_vice_chair_email,
        house_chair_name=house_chair_name,
        house_chair_email=house_chair_email,
        house_vice_chair_name=house_vice_chair_name,
        house_vice_chair_email=house_vice_chair_email,
    )
    if cache:
        contact_data = {
            "committee_id": contact.committee_id,
            "name": contact.name,
            "chamber": contact.chamber,
            "url": contact.url,
            "house_room": contact.house_room,
            "house_address": contact.house_address,
            "house_phone": contact.house_phone,
            "senate_room": contact.senate_room,
            "senate_address": contact.senate_address,
            "senate_phone": contact.senate_phone,
            "senate_chair_name": contact.senate_chair_name,
            "senate_chair_email": contact.senate_chair_email,
            "senate_vice_chair_name": contact.senate_vice_chair_name,
            "senate_vice_chair_email": contact.senate_vice_chair_email,
            "house_chair_name": contact.house_chair_name,
            "house_chair_email": contact.house_chair_email,
            "house_vice_chair_name": contact.house_vice_chair_name,
            "house_vice_chair_email": contact.house_vice_chair_email,
        }
        cache.set_committee_contact(committee.id, contact_data)
        logging.info("Cached contact info for committee %s", committee.id)
    return contact
