"""Collect the committee contact info from the committee page."""

import re
from urllib.parse import urljoin

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
    base_url: str, committee: Committee
) -> CommitteeContact:
    """
    On the committee detail page, scrape only the House Contact block
    (room, address, phone). Skip Senate entirely.
    """
    url = urljoin(base_url, f"/Committees/Detail/{committee.id}")
    with requests.Session() as s:
        soup = _soup(s, url)
        # Look for the "House Contact" section
        block = None
        for h in soup.find_all(["h3", "h4", "strong"]):
            if "House Contact" in h.get_text():
                parent = h.find_parent()
                if parent:
                    block = " ".join(parent.get_text(" ", strip=True).split())
                break
        room = (
            ROOM_RX.search(block).group(0)
            if block and ROOM_RX.search(block)
            else None
        )
        phone = (
            PHONE_RX.search(block).group(0)
            if block and PHONE_RX.search(block)
            else None
        )
        # Address line is usually "24 Beacon St. Room 274 Boston, MA 02133"
        address = None
        if block and "Boston" in block:
            m = re.search(r"24 Beacon St\..+Boston,\s*MA\s*\d{5}", block)
            if m:
                address = m.group(0)
            elif room:
                address = f"24 Beacon St. {room} Boston, MA 02133"
    return CommitteeContact(
        committee_id=committee.id,
        name=committee.name,
        chamber=committee.chamber,
        url=committee.url,
        room=room,
        address=address,
        phone=phone,
    )
