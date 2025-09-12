"""Collect the committee contact info from the committee page."""

import re
from urllib.parse import urljoin
from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import Committee, CommitteeContact

PHONE_RX = re.compile(r"\(\d{3}\)\s*\d{3}-\d{4}")
ROOM_RX = re.compile(r"\bRoom\s+[A-Za-z0-9\-]+", re.I)


def _soup(session: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = session.get(url, timeout=20, headers={
        "User-Agent": "legis-scraper/0.1"
    })
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def get_committee_contact(
    base_url: str, committee: Committee, cache=None
) -> CommitteeContact:
    """
    On the committee detail page, scrape both Senate and House Contact blocks
    (room, address, phone) for both chambers.
    """
    # Check cache first if available
    if cache:
        cached_contact = cache.get_committee_contact(committee.id)
        if cached_contact:
            print(f"Using cached contact info for committee {committee.id}")
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
            )

    print(f"Fetching contact info for committee {committee.id}")
    url = urljoin(base_url, f"/Committees/Detail/{committee.id}")
    with requests.Session() as s:
        soup = _soup(s, url)

        # Helper function to extract contact info from a section
        def extract_contact_info(
            section_text: str
        ) -> tuple[Optional[str], Optional[str], Optional[str]]:
            room_match = ROOM_RX.search(section_text)
            room = room_match.group(0) if room_match else None
            phone_match = PHONE_RX.search(section_text)
            phone = phone_match.group(0) if phone_match else None

            # Address line is usually "24 Beacon St. Room XXX Boston, MA 02133"
            address = None
            if "Boston" in section_text:
                m = re.search(
                    r"24 Beacon St\..+Boston,\s*MA\s*\d{5}", section_text
                )
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
                    senate_text = " ".join(
                        parent.get_text(" ", strip=True).split()
                    )
                    senate_room, senate_address, senate_phone = (
                        extract_contact_info(senate_text)
                    )
                break

        # Look for House Contact section
        house_room, house_address, house_phone = None, None, None
        for h in soup.find_all(["h3", "h4", "strong"]):
            if "House Contact" in h.get_text():
                parent = h.find_parent()
                if parent:
                    house_text = " ".join(
                        parent.get_text(" ", strip=True).split()
                    )
                    house_room, house_address, house_phone = (
                        extract_contact_info(house_text)
                    )
                break

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
    )

    # Cache the contact info if cache is available
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
        }
        cache.set_committee_contact(committee.id, contact_data)
        print(f"Cached contact info for committee {committee.id}")

    return contact
