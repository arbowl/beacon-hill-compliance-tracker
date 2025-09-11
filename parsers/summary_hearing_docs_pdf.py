"""A parser for when the summary is on the hearing's Documents tab."""

import re
from typing import Optional
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import requests  # type: ignore
from bs4 import BeautifulSoup

from components.models import BillAtHearing

DL_PATH_RX = re.compile(r"/Events/DownloadDocument", re.I)
PDF_RX = re.compile(r"\.pdf($|\?)", re.I)


def _soup(s: requests.Session, url: str) -> BeautifulSoup:
    """Get the soup of the page."""
    r = s.get(url, timeout=20, headers={"User-Agent": "legis-scraper/0.1"})
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _norm_bill_id(s: str) -> str:
    """Normalize the bill ID."""
    # "H. 96" -> "H96", "H96" -> "H96"
    s = s.upper().replace("\xa0", " ")
    s = re.sub(r"[.\s]", "", s)
    return s


def _title_from_href(href: str) -> str:
    """Get the title from the href."""
    # Try to read the Title= param; fall back to basename-ish
    try:
        q = parse_qs(urlparse(href).query)
        t = q.get("Title", [""])[0]
        return unquote(t)
    except Exception:  # pylint: disable=broad-exception-caught
        return ""


def _looks_like_summary_for_bill(link_text: str, title_param: str, bill_id: str) -> bool:
    """Check if the link text looks like a summary for the bill."""
    # We accept if:
    #   - "summary" appears AND
    #   - bill_id ("H96") appears in either the link text or the Title= param
    has_summary = bool(
        re.search(
            r"\bsummary\b", link_text, re.I
        ) or re.search(r"\bsummary\b", title_param, re.I)
    )
    has_bill = (
        bill_id in _norm_bill_id(link_text)
    ) or (bill_id in _norm_bill_id(title_param))
    return has_summary and has_bill


def discover(base_url: str, bill: BillAtHearing) -> Optional[dict]:
    """
    Probe the hearing 'Documents' tab for a Summary PDF that matches this bill (e.g., H96 Summary).
    Returns {"preview","source_url","confidence"} or None.
    """
    # We rely on hearing_url (added in step 2 tweak)
    hearing_docs_url = bill.hearing_url  # docs are here (tabbed content)
    with requests.Session() as s:
        soup = _soup(s, hearing_docs_url)

        # Look for any link like /Events/DownloadDocument?...fileExtension=.pdf
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not DL_PATH_RX.search(href):
                continue
            if not PDF_RX.search(href):
                continue

            text = " ".join(a.get_text(strip=True).split())
            title_param = _title_from_href(href)

            bill_id = _norm_bill_id(bill.bill_id)  # "H96"
            if _looks_like_summary_for_bill(text, title_param, bill_id):
                pdf_url = urljoin(base_url, href)
                preview = f"Found '{title_param or text}' in hearing Documents "\
                    f"for {bill.bill_id}"
                return {
                    "preview": preview,
                    "source_url": pdf_url,
                    "confidence": 0.95
                }
    return None


def parse(base_url: str, candidate: dict) -> dict:
    """Parse the summary."""
    # Nothing heavy yet; just return the stable link for the report/cache
    return {"source_url": candidate["source_url"]}
