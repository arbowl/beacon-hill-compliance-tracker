"""Evaluator for reconstituting and recomputing compliance from artifacts."""

from datetime import date
from typing import Optional

from history.artifacts import BillArtifact, DocumentType
from components.compliance import BillCompliance
from components.models import BillStatus, SummaryInfo, VoteInfo, VoteRecord
from components.ruleset import classify
from timeline.models import ActionType


class BillArtifactEvaluator:
    """Evaluate bill artifacts using current or historical rulesets."""

    @staticmethod
    def reconstitute_to_status(artifact: BillArtifact) -> BillStatus:
        """Reconstitute the status of a bill from an artifact."""
        hearing = artifact.hearing_records[0] if artifact.hearing_records else None
        reported_date: Optional[date] = None
        for action in artifact.timeline_actions:
            if action.action_type == ActionType.REPORTED:
                if action.extracted_data.get("committee_id") == artifact.committee_id:
                    reported_date = action.action_date
                    break
        extension_until = None
        if artifact.extension_records:
            extension_until = artifact.extension_records[-1].extension_until
        return BillStatus(
            bill_id=artifact.bill_id,
            committee_id=artifact.committee_id,
            hearing_date=hearing.hearing_date if hearing else None,
            deadline_60=None,
            deadline_90=None,
            reported_out=reported_date is not None,
            reported_date=reported_date,
            extension_until=extension_until,
            effective_deadline=None,
            announcement_date=hearing.announcement_date if hearing else None,
            scheduled_hearing_date=(
                hearing.scheduled_hearing_date if hearing else None
            ),
        )

    @staticmethod
    def reconstitute_documents(artifact: BillArtifact) -> tuple[SummaryInfo, VoteInfo]:
        """Reconstitute the documents of a bill from an artifact."""
        summary_docs = [
            d
            for d in artifact.document_artifacts
            if d.document_type == DocumentType.SUMMARY
        ]
        vote_docs = [
            d
            for d in artifact.document_artifacts
            if d.document_type == DocumentType.VOTES
        ]
        if summary_docs:
            s = summary_docs[0]
            summary = SummaryInfo(
                present=True,
                location=s.location,
                source_url=s.source_url,
                parser_module=s.parser_module,
                needs_review=s.needs_review,
            )
        else:
            summary = SummaryInfo(
                present=False, location="", source_url=None, parser_module=None
            )
        if vote_docs:
            v = vote_docs[0]
            vote_content = v.full_content or {}
            records = [
                VoteRecord(member=r["member"], vote=r["vote"])
                for r in vote_content.get("records", [])
            ]
            votes = VoteInfo(
                present=True,
                location=v.location,
                source_url=v.source_url,
                parser_module=v.parser_module,
                motion=vote_content.get("motion"),
                date=vote_content.get("date"),
                tallies=vote_content.get("tallies"),
                records=records if records else None,
                needs_review=v.needs_review,
            )
        else:
            votes = VoteInfo(
                present=False, location="", source_url=None, parser_module=None
            )
        return summary, votes

    @staticmethod
    def recompute_compliance(
        artifact: BillArtifact, _ruleset_version: str = "194.v1"
    ) -> BillCompliance:
        """Recompute the compliance of a bill from an artifact."""
        status = BillArtifactEvaluator.reconstitute_to_status(artifact)
        summary, votes = BillArtifactEvaluator.reconstitute_documents(artifact)
        compliance = classify(
            bill_id=artifact.bill_id,
            committee_id=artifact.committee_id,
            status=status,
            summary=summary,
            votes=votes,
        )
        return compliance
