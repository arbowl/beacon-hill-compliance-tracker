""" Parser for summary PDFs on hearing pages. """

import re
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from components.models import BillAtHearing


PDF_RX = re.compile(r"\.pdf($|\?)", re.I)
SUMMARY_HINTS = [
    r"\bcommittee summary\b",
    r"\bsummary\b",
    r"\bdocket summary\b",
]


def _soup(session: requests.Session, url: str) -> BeautifulSoup:
    """ Get the soup of the page. """
    r = session.get(url, timeout=30, headers={
        "User-Agent": "legis-scraper/0.1"
    })
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _find_candidate_pdf(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """ Find a candidate PDF on the hearing page. """
    # Strategy: any <a> on the hearing page whose text or filename suggests
    # "summary" and is a PDF.
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = " ".join(a.get_text(strip=True).split()).lower()
        if not PDF_RX.search(href):
            continue
        if any(re.search(rx, text, re.I) for rx in SUMMARY_HINTS):
            return urljoin(base_url, href)
        # fallback: filename has "summary"
        if re.search(r"summary", href, re.I):
            return urljoin(base_url, href)
    return None


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """
    Quick probe. Return a Candidate dict:
    {"preview": str, "source_url": str, "confidence": float}
    or None if nothing plausible is found.
    """
    with requests.Session() as s:
        soup = _soup(s, bill.hearing_url)
        # Prefer the hearing detail page URL; derive it from known pattern:
        # we stored only IDs in BillAtHearing, so reconstruct if needed:
        hearing_url = f"{base_url}/Events/Hearings/Detail/{bill.hearing_id}"
        soup = _soup(s, hearing_url)

        pdf_url = _find_candidate_pdf(soup, base_url)
        if not pdf_url:
            return None

        preview = f"Possible summary PDF found on hearing documents for {
            bill.bill_id
        }"
        return {"preview": preview, "source_url": pdf_url, "confidence": 0.8}


def parse(base_url: str, candidate: dict) -> dict:
    """
    Second stage. We don't parse PDF text yet—just confirm a stable link.
    Return {"source_url": str}
    """
    return {"source_url": candidate["source_url"]}
