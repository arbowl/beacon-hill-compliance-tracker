"""Collect all bills from the committee's Bills tab (with pagination)."""

import re
from typing import Optional
from urllib.parse import urljoin

from components.models import BillAtHearing
from components.interfaces import ParserInterface

HREF_BILL_RE = re.compile(r"/Bills/(\d+)/(H|S)(\d+)", re.I)


def get_all_committee_bills(
    base_url: str, committee_id: str, session: str = "194"
) -> list[BillAtHearing]:
    """
    Scrape all bills from the committee's Bills tab.
    Handles pagination across multiple pages.
    """
    bills: list[BillAtHearing] = []
    seen_bill_ids = set()
    page_num = 1
    while True:
        if page_num == 1:
            path = f"/Committees/Detail/{committee_id}/Bills"
            url = urljoin(base_url, path)
        else:
            path = (
                f"/Committees/Detail/{committee_id}/{session}/"
                f"Bills/asc/EntityNumber/"
                f"?current=True&pageNumber={page_num}"
            )
            url = urljoin(base_url, path)
        soup = ParserInterface.soup(url)
        found_bills_on_page = False
        for a in soup.select('a[href*="/Bills/"]'):
            href = a.get("href", "")
            m: Optional[re.Match] = HREF_BILL_RE.search(href)
            if not m:
                continue
            bill_id = f"{m.group(2)}{m.group(3)}"
            if bill_id in seen_bill_ids:
                continue
            seen_bill_ids.add(bill_id)
            bill_url = urljoin(base_url, href)
            label = " ".join(a.get_text(strip=True).split())
            bills.append(
                BillAtHearing(
                    bill_id=bill_id,
                    bill_label=label,
                    bill_url=bill_url,
                    committee_id=committee_id,
                    hearing_id=None,
                    hearing_date=None,
                    hearing_url=None,
                )
            )
            found_bills_on_page = True
        if not found_bills_on_page:
            break
        pagination = soup.find("ul", class_="pagination")
        if not pagination:
            break
        active_li = pagination.find("li", class_="active")
        if active_li:
            next_li = active_li.find_next_sibling("li")
            if not next_li or "disabled" in next_li.get("class", []):
                break
        page_num += 1
    bills.sort(key=lambda b: b.bill_id)
    return bills
