"""Collect the bills from the Hearings page."""

import re
from datetime import datetime, date
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from components.models import Hearing, BillAtHearing
from components.interfaces import ParserInterface


HREF_HEARING_RE = re.compile(r"/Events/Hearings/Detail/(\d+)$", re.I)
HREF_BILL_RE = re.compile(r"/Bills/\d+/(H|S)\d+", re.I)


def _parse_event_date(soup: BeautifulSoup) -> date | None:
    """Parse the event date from the soup."""
    # Hearing pages include an "Event Date:" field; fallback to parse any
    # date-like text near it.
    # Example structure confirmed on real pages:
    # contentReference[oaicite:0]{index=0}
    label = soup.find(string=re.compile(r"Event Date:", re.I))
    if label:
        # The date string is typically in the next sibling/element
        # e.g., "Wednesday, April 9, 2025"
        text = " ".join(label.find_parent().get_text(" ", strip=True).split())
        m = re.search(
            r"Event Date:\s+([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4})",
            text
        )
        if m:
            return datetime.strptime(m.group(1), "%A, %B %d, %Y").date()
    # Fallback: scan whole doc
    m = re.search(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),"
        r"\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}",
        soup.get_text(" ", strip=True)
    )
    if m:
        return datetime.strptime(m.group(0), "%A, %B %d, %Y").date()
    return None


def _normalize_bill_id(label: str) -> str:
    # Keep it predictable: "H. 73" -> "H73"; "S.197 C" -> "S197"
    s = label.upper().replace("\xa0", " ")
    s = re.sub(r"[.\s]", "", s)          # remove dots/spaces
    s = re.sub(r"(H|S)(\d+)[A-Z]*$", r"\1\2", s)  # drop trailing letters like 'C'
    return s


def list_committee_hearings(  # pylint: disable=too-many-locals
    base_url: str, committee_id: str
) -> List[Hearing]:
    """
    Scrape the committee's Hearings tab and return Hearing objects.
    Example target page shape validated on J33 hearings tab.
    :contentReference[oaicite:1]{index=1}
    """
    url = urljoin(base_url, f"/Committees/Detail/{committee_id}/Hearings")
    out: List[Hearing] = []
    soup = ParserInterface.soup(url)
    # Any link to an event detail looks like /Events/Hearings/Detail/<id>
    for a in soup.select('a[href*="/Events/Hearings/Detail/"]'):
        href = a.get("href", "")
        m = HREF_HEARING_RE.search(href)
        if not m:
            continue
        hid = m.group(1)
        row = a.find_parent()  # nearby elements contain date/time/status
        # Pull a short title/label (best-effort)
        title = " ".join(a.get_text(strip=True).split())
        # Find the whole row text to detect status + nearest date
        status = " ".join(row.get_text(" ", strip=True).split()) if row else ""
        # Visit the detail page to get the canonical date and bill list
        detail_url = urljoin(base_url, f"/Events/Hearings/Detail/{hid}")
        detail = ParserInterface.soup(detail_url)
        dt = _parse_event_date(detail)
        # crude status extraction from list page row text
        status_flag = (
            "Confirmed"
            if re.search(r"\bConfirmed\b", status, re.I)
            else ("Completed" if re.search(r"\bCompleted\b", status, re.I) else "")
        )
        out.append(Hearing(
            id=hid,
            committee_id=committee_id,
            url=detail_url,
            date=dt or datetime.min.date(),
            status=status_flag,
            title=title
        ))
    # Sort oldest → newest (you can flip later)
    out.sort(key=lambda h: (h.date, h.id))
    return out


def extract_bills_from_hearing(
    base_url: str, hearing: Hearing
) -> List[BillAtHearing]:
    """
    Given a Hearing, parse its docket table and return BillAtHearing rows.
    Structure validated on real hearing detail pages (bill table + bill links).
    :contentReference[oaicite:3]{index=3}
    """
    soup = ParserInterface.soup(hearing.url)
    bills: List[BillAtHearing] = []
    # Any anchor that links to /Bills/<session>/<H|S><number>
    for a in soup.select('a[href*="/Bills/"]'):
        href = a.get("href", "")
        if not HREF_BILL_RE.search(href):
            continue
        label = " ".join(a.get_text(strip=True).split())
        bill_url = urljoin(base_url, href)
        bill_id = _normalize_bill_id(label)
        bills.append(BillAtHearing(
            bill_id=bill_id,
            bill_label=label,
            bill_url=bill_url,
            committee_id=hearing.committee_id,
            hearing_id=hearing.id,
            hearing_date=hearing.date,
            hearing_url=hearing.url
        ))
    # De-dupe within a single hearing in case a bill appears twice
    seen = set()
    deduped: List[BillAtHearing] = []
    for b in bills:
        if (b.bill_id, b.hearing_id) in seen:
            continue
        seen.add((b.bill_id, b.hearing_id))
        deduped.append(b)
    return deduped


def get_bills_for_committee(
    base_url: str, committee_id: str, limit_hearings: int | None = None
) -> List[BillAtHearing]:
    """Get the bills for a committee.
    """
    hearings = list_committee_hearings(base_url, committee_id)
    if limit_hearings:
        hearings = hearings[:limit_hearings]
    out: List[BillAtHearing] = []
    for h in hearings:
        out.extend(extract_bills_from_hearing(base_url, h))
    # optional: stable sort
    out.sort(key=lambda b: (b.hearing_date, b.hearing_id, b.bill_id))
    return out
