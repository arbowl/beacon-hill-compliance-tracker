"""Composer for creating bill artifacts from scraped data."""

from typing import Optional

from history.artifacts import (
    ArtifactSnapshot,
    BillArtifact,
    DocumentArtifact,
    DocumentType,
    ExtensionRecord,
    HearingRecord,
    MetadataKey,
    TimelineAction,
)
from components.compliance import BillCompliance
from components.models import (
    BillAtHearing,
    BillStatus,
    ExtensionOrder,
    SummaryInfo,
    VoteInfo,
)
from components.utils import extract_session_from_bill_url
from timeline.models import BillActionTimeline


class BillArtifactComposer:
    """Compose bill artifacts from scraped data."""

    @staticmethod
    def compose_from_scrape(
        bill: BillAtHearing,
        status: BillStatus,
        summary: SummaryInfo,
        votes: VoteInfo,
        timeline: BillActionTimeline,
        extensions: list[ExtensionOrder],
        compliance: BillCompliance,
        bill_title: Optional[str] = None,
        ruleset_version: str = "194.v1"
    ) -> BillArtifact:
        """Compose a bill artifact from scraped data."""
        session = extract_session_from_bill_url(bill.bill_url) or "194"
        artifact = BillArtifact.new(
            bill_id=bill.bill_id,
            session=session,
            committee_id=bill.committee_id,
        )
        artifact.bill_metadata = {
            MetadataKey.TITLE.value: bill_title or "",
            MetadataKey.BILL_URL.value: bill.bill_url,
            MetadataKey.BILL_LABEL.value: bill.bill_label,
        }
        if bill.hearing_date:
            hearing_record = HearingRecord.new()
            hearing_record.hearing_id = bill.hearing_id
            hearing_record.hearing_date = bill.hearing_date
            hearing_record.hearing_url = bill.hearing_url
            hearing_record.announcement_date = status.announcement_date
            hearing_record.scheduled_hearing_date = status.\
                scheduled_hearing_date
            hearing_record.announcement_metadata = {
                MetadataKey.SOURCE.value: "cache.json"
                if status.announcement_date
                else "scraped",
            }
            artifact.hearing_records.append(hearing_record)
        for action in timeline.actions:
            timeline_action = TimelineAction.new(
                action_date=action.date,
                branch=action.branch,
                action_type=action.action_type,
                category=action.category,
                raw_text=action.raw_text,
            )
            timeline_action.extracted_data = action.extracted_data
            timeline_action.confidence = action.confidence
            artifact.timeline_actions.append(timeline_action)
        if summary.present:
            doc = DocumentArtifact.new(DocumentType.SUMMARY, summary.location)
            doc.source_url = summary.source_url
            doc.parser_module = summary.parser_module
            doc.parser_version = BillArtifactComposer._get_parser_version(
                summary.parser_module
            )
            doc.needs_review = summary.needs_review
            artifact.document_artifacts.append(doc)
        if votes.present:
            vote_content = {
                "motion": votes.motion,
                "date": votes.date,
                "tallies": votes.tallies,
                "records": [
                    {"member": r.member, "vote": r.vote}
                    for r in (votes.records or [])
                ]
            }
            doc = DocumentArtifact.new(DocumentType.VOTES, votes.location)
            doc.source_url = votes.source_url
            doc.parser_module = votes.parser_module
            doc.parser_version = BillArtifactComposer._get_parser_version(
                votes.parser_module
            )
            doc.full_content = vote_content
            doc.needs_review = votes.needs_review
            artifact.document_artifacts.append(doc)
        for ext in extensions:
            extension_record = ExtensionRecord.new(ext.extension_date)
            extension_record.extension_until = ext.extension_date
            extension_record.order_url = ext.extension_order_url
            extension_record.order_type = ext.order_type
            extension_record.is_fallback = ext.is_fallback
            artifact.extension_records.append(extension_record)
        snapshot = ArtifactSnapshot.new(
            ruleset_version=ruleset_version,
            computed_state=compliance.state,
            computed_reason=compliance.reason or "",
        )
        snapshot.computation_metadata = {
            MetadataKey.DEADLINE_60.value: str(
                status.deadline_60
            ) if status.deadline_60 else None,
            MetadataKey.DEADLINE_90.value: str(
                status.deadline_90
            ) if status.deadline_90 else None,
            MetadataKey.EFFECTIVE_DEADLINE.value: str(
                status.effective_deadline
            ) if status.effective_deadline else None,
            MetadataKey.REPORTED_OUT.value: status.reported_out,
            MetadataKey.REPORTED_DATE.value: str(
                status.reported_date
            ) if status.reported_date else None,
            MetadataKey.NOTICE_GAP_DAYS.value: (
                (status.scheduled_hearing_date - status.announcement_date).days
                if status.announcement_date and status.scheduled_hearing_date
                else None
            ),
        }
        artifact.snapshots.append(snapshot)
        return artifact

    @staticmethod
    def _get_parser_version(parser_module: Optional[str]) -> Optional[str]:
        if not parser_module:
            return None
        return "194.v1"
