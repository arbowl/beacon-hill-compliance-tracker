""" Data models for the Massachusetts Legislature website.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, List, TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from components.interfaces import ParserInterface


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
    announcement_date: Optional[date] = None  # when hearing was announced
    scheduled_hearing_date: Optional[date] = None  # hearing date from announce


@dataclass(frozen=True)
class SummaryInfo:
    """A summary of a bill in the Massachusetts Legislature."""
    present: bool                 # True if we found/confirmed a summary
    location: str                 # e.g., "hearing_pdf"
    source_url: Optional[str]     # direct link to the PDF or tab
    parser_module: Optional[str]  # which parser landed
    needs_review: bool = False    # if we auto-accepted in headless mode

    def to_dict(self) -> dict:
        """Convert to dictionary, omitting None values."""
        result = {
            "present": self.present,
            "location": self.location,
            "needs_review": self.needs_review,
        }
        if self.source_url is not None:
            result["source_url"] = self.source_url
        if self.parser_module is not None:
            result["parser_module"] = self.parser_module
        return result

    def from_dict(data: dict) -> 'SummaryInfo':
        """Create SummaryInfo from a dictionary."""
        return SummaryInfo(
            present=data.get("present", False),
            location=data.get("location", "unknown"),
            source_url=data.get("source_url"),
            parser_module=data.get("parser_module"),
            needs_review=data.get("needs_review", False),
        )


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

    def to_dict(self) -> dict:
        """Convert to dictionary, omitting None values."""
        result = {
            "present": self.present,
            "location": self.location,
            "needs_review": self.needs_review,
        }
        if self.source_url is not None:
            result["source_url"] = self.source_url
        if self.parser_module is not None:
            result["parser_module"] = self.parser_module
        if self.motion is not None:
            result["motion"] = self.motion
        if self.date is not None:
            result["date"] = self.date
        if self.tallies is not None:
            result["tallies"] = self.tallies
        if self.records is not None:
            result["records"] = (
                [{"member": r.member, "vote": r.vote} for r in self.records] if self.records else None
            )
        return result

    def from_dict(data: dict) -> VoteInfo:
        """Create VoteInfo from a dictionary."""
        records_data = data.get("records")
        records = (
            [VoteRecord(member=r["member"], vote=r["vote"]) for r in records_data]
            if records_data else None
        )
        return VoteInfo(
            present=data.get("present", False),
            location=data.get("location", "unknown"),
            source_url=data.get("source_url"),
            parser_module=data.get("parser_module"),
            motion=data.get("motion"),
            date=data.get("date"),
            tallies=data.get("tallies"),
            records=records,
            needs_review=data.get("needs_review", False),
        )


@dataclass(frozen=True)
class ExtensionOrder:
    """An extension order for a bill in the Massachusetts Legislature."""

    bill_id: str
    committee_id: str
    extension_date: date
    extension_order_url: str
    order_type: str  # "Extension Order", "Committee Extension Order", etc.
    discovered_at: datetime
    is_fallback: bool = False  # True if created as fallback when regex failed
    is_date_fallback: bool = False  # True if extension date is a fallback


@dataclass(frozen=True)
class CommitteeContact:  # pylint: disable=too-many-instance-attributes
    """A committee contact in the Massachusetts Legislature."""
    committee_id: str
    name: str
    chamber: str
    url: str
    # House contact details
    house_room: Optional[str] = None   # e.g., "Room 130"
    house_address: Optional[str] = None  # Address format example
    house_phone: Optional[str] = None  # "(617) 722-2130"
    # Senate contact details
    senate_room: Optional[str] = None   # e.g., "Room 507"
    senate_address: Optional[str] = None  # Address format example
    senate_phone: Optional[str] = None  # "(617) 722-1643"
    # Chair and Vice-Chair information
    senate_chair_name: str = ""
    senate_chair_email: str = ""
    senate_vice_chair_name: str = ""
    senate_vice_chair_email: str = ""
    house_chair_name: str = ""
    house_chair_email: str = ""
    house_vice_chair_name: str = ""
    house_vice_chair_email: str = ""


@dataclass
class DeferredConfirmation:
    """Represents a parser confirmation that needs review."""
    confirmation_id: str
    bill_id: str
    parser_type: str  # "summary" or "votes"
    parser_module: str
    candidate: ParserInterface.DiscoveryResult  # The discovered candidate data
    preview_text: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Generate confirmation ID if not provided."""
        if not self.confirmation_id:
            object.__setattr__(self, 'confirmation_id', str(uuid.uuid4())[:8])


@dataclass
class DeferredReviewSession:
    """Collection of all deferred confirmations for batch review."""
    session_id: str
    committee_id: str
    confirmations: List[DeferredConfirmation] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        """Generate session ID if not provided."""
        if not self.session_id:
            object.__setattr__(self, 'session_id', str(uuid.uuid4())[:8])
    
    def add_confirmation(self, confirmation: DeferredConfirmation) -> None:
        """Add a confirmation to the session."""
        self.confirmations.append(confirmation)
    
    def get_summary_count(self) -> int:
        """Get count of summary confirmations."""
        return len([c for c in self.confirmations if c.parser_type == "summary"])
    
    def get_votes_count(self) -> int:
        """Get count of vote confirmations."""
        return len([c for c in self.confirmations if c.parser_type == "votes"])
    
    def get_bill_ids(self) -> List[str]:
        """Get unique list of bill IDs in this session."""
        return list(set(c.bill_id for c in self.confirmations))
