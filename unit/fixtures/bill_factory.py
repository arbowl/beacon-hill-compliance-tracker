"""Factory for creating test bill structures."""

from datetime import date, timedelta
from typing import Optional

from components.models import (
    BillAtHearing,
    BillStatus,
    SummaryInfo,
    VoteInfo,
    VoteRecord,
)
from unit.fixtures import Requirement


class BillFactory:
    """Factory for creating test bills with various configurations."""

    @staticmethod
    def create_bill_at_hearing(
        bill_id: str = "H100",
        committee_id: str = "J33",
        hearing_date: Optional[date] = None,
        **kwargs,
    ) -> BillAtHearing:
        """Create a basic BillAtHearing structure."""
        if hearing_date is None:
            hearing_date = date.today() - timedelta(days=30)

        defaults = {
            "bill_label": f"Bill {bill_id}",
            "bill_url": f"https://malegislature.gov/Bills/194/{bill_id}",
            "hearing_id": "1234",
            "hearing_url": "https://malegislature.gov/Events/Hearings/Detail/1234",
        }
        defaults.update(kwargs)

        return BillAtHearing(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=hearing_date,
            **defaults,
        )

    @staticmethod
    def create_status(
        bill_id: str = "H100",
        committee_id: str = "J33",
        hearing_date: Optional[date] = None,
        reported_out: bool = False,
        reported_date: Optional[date] = None,
        announcement_date: Optional[date] = None,
        extension_until: Optional[date] = None,
        **kwargs,
    ) -> BillStatus:
        """Create a BillStatus with automatic deadline calculation."""
        # Auto-calculate deadlines
        deadline_60: Optional[date] = None
        deadline_90: Optional[date] = None
        if hearing_date is not None:
            deadline_60 = hearing_date + timedelta(days=60)
            deadline_90 = hearing_date + timedelta(days=90)
        effective_deadline = extension_until or deadline_60
        return BillStatus(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=hearing_date,
            deadline_60=deadline_60,
            deadline_90=deadline_90,
            reported_out=reported_out,
            reported_date=reported_date,
            extension_until=extension_until,
            effective_deadline=effective_deadline,
            announcement_date=announcement_date,
            scheduled_hearing_date=hearing_date,
            **kwargs,
        )

    @staticmethod
    def create_summary(
        present: bool = True,
        location: str = "hearing_pdf",
        source_url: Optional[str] = None,
        parser_module: Optional[str] = "parsers.summary_hearing_docs_pdf",
    ) -> SummaryInfo:
        """Create a SummaryInfo."""
        return SummaryInfo(
            present=present,
            location=location,
            source_url=source_url,
            parser_module=parser_module,
        )

    @staticmethod
    def create_votes(
        present: bool = True,
        location: str = "bill_embedded",
        source_url: Optional[str] = None,
        parser_module: Optional[str] = "parsers.votes_bill_embedded",
        motion: Optional[str] = "Ought to pass",
        tallies: Optional[dict] = None,
        records: Optional[list[VoteRecord]] = None,
    ) -> VoteInfo:
        """Create a VoteInfo."""
        if tallies is None and present:
            tallies = {"yea": 10, "nay": 2}
        return VoteInfo(
            present=present,
            location=location,
            source_url=source_url,
            parser_module=parser_module,
            motion=motion,
            tallies=tallies,
            records=records,
        )

    @staticmethod
    def create_complete_compliant_bill(
        bill_id: str = "H100",
        committee_id: str = "J33",
        hearing_date: Optional[date] = None,
    ) -> tuple[BillStatus, SummaryInfo, VoteInfo]:
        """Create a fully compliant bill (all requirements met)."""
        if hearing_date is None:
            hearing_date = date.today() - timedelta(days=30)
        announcement = hearing_date - timedelta(days=15)
        reported_date = hearing_date + timedelta(days=20)
        status = BillFactory.create_status(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=hearing_date,
            reported_out=True,
            reported_date=reported_date,
            announcement_date=announcement,
        )
        summary = BillFactory.create_summary(present=True)
        votes = BillFactory.create_votes(present=True)
        return status, summary, votes

    @staticmethod
    def create_noncompliant_bill(
        bill_id: str = "H100",
        committee_id: str = "J33",
        missing: Optional[list[Requirement]] = None,
    ) -> tuple[BillStatus, SummaryInfo, VoteInfo]:
        """Create a non-compliant bill.

        Args:
            missing: List of requirements to make missing
                     (use Requirement enum values)
        """
        if missing is None:
            missing = [Requirement.REPORTED, Requirement.SUMMARY]
        hearing_date = date.today() - timedelta(days=100)  # Past deadline
        announcement = hearing_date - timedelta(days=10)
        status = BillFactory.create_status(
            bill_id=bill_id,
            committee_id=committee_id,
            hearing_date=hearing_date,
            reported_out=Requirement.REPORTED not in missing,
            reported_date=None,
            announcement_date=announcement,
        )
        summary = BillFactory.create_summary(present=Requirement.SUMMARY not in missing)
        votes = BillFactory.create_votes(present=Requirement.VOTES not in missing)
        return status, summary, votes
