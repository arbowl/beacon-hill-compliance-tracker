""" Data models for the Massachusetts Legislature website.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Committee:
    """A committee in the Massachusetts Legislature."""

    id: str        # e.g., "J33", "H33"
    name: str      # visible title on the site
    chamber: str   # "Joint" or "House"
    url: str       # absolute detail URL


@dataclass(frozen=True)
class Hearing:
    """A hearing in the Massachusetts Legislature."""

    id: str              # e.g., "5114" from /Events/Hearings/Detail/5114
    committee_id: str    # e.g., "J33"
    url: str
    date: date
    status: str          # "Completed"/"Confirmed"/etc (best-effort)
    title: str           # short topic/label from committee hearings list


@dataclass(frozen=True)
class BillAtHearing:
    """A bill at a hearing in the Massachusetts Legislature."""

    bill_id: str         # canonical like "H73", "S197"
    bill_label: str      # display label as shown (e.g., "H. 73", "S.197 C")
    bill_url: str
    hearing_id: str
    hearing_date: date
    committee_id: str
    hearing_url: str


@dataclass(frozen=True)
class BillStatus:  # pylint: disable=too-many-instance-attributes
    """A bill status in the Massachusetts Legislature."""

    bill_id: str
    committee_id: str
    hearing_date: date
    deadline_60: date
    deadline_90: date
    reported_out: bool
    reported_date: Optional[date]  # when we can parse it
    extension_until: Optional[date]  # None for now; we’ll fill later
    effective_deadline: date  # min(90, extension_until or 60)


@dataclass(frozen=True)
class SummaryInfo:
    """A summary of a bill in the Massachusetts Legislature."""
    present: bool                 # True if we found/confirmed a summary
    location: str                 # e.g., "hearing_pdf"
    source_url: Optional[str]     # direct link to the PDF or tab
    parser_module: Optional[str]  # which parser landed
    needs_review: bool = False    # if we auto-accepted in headless mode


@dataclass(frozen=True)
class VoteRecord:
    """A vote record in the Massachusetts Legislature."""

    member: str
    vote: str  # "Yea", "Nay", "Present", etc.


@dataclass(frozen=True)
class VoteInfo:  # pylint: disable=too-many-instance-attributes
    """A vote info in the Massachusetts Legislature."""

    present: bool                   # did we find confirmed vote info?
    location: str                   # "bill_embedded", "bill_pdf", etc.
    source_url: Optional[str]       # where we found it
    parser_module: Optional[str]    # which parser landed
    motion: Optional[str] = None
    date: Optional[str] = None      # ISO/human date if we can parse it cheaply
    tallies: Optional[dict] = None  # {"yea": 10, "nay": 3, ...}
    records: Optional[list[VoteRecord]] = None
    needs_review: bool = False


@dataclass(frozen=True)
class CommitteeContact:
    """A committee contact in the Massachusetts Legislature."""
    committee_id: str
    name: str
    chamber: str
    url: str
    room: Optional[str]   # e.g., "Room 274"
    address: Optional[str]  # "24 Beacon St. Room 274 Boston, MA 02133"
    phone: Optional[str]  # "(617) 722-2676"
