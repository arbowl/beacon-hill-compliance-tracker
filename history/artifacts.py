"""Bill artifact models for reconstructable compliance tracking."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class DocumentType(str, Enum):
    """Type of document discovered in the bill."""

    SUMMARY = "summary"
    VOTES = "votes"


class MetadataKey(str, Enum):
    """Key for metadata in the bill artifact."""

    TITLE = "title"
    BILL_URL = "bill_url"
    BILL_LABEL = "bill_label"
    CACHED_AT = "cached_at"
    SOURCE = "source"
    DEADLINE_60 = "deadline_60"
    DEADLINE_90 = "deadline_90"
    EFFECTIVE_DEADLINE = "effective_deadline"
    REPORTED_OUT = "reported_out"
    REPORTED_DATE = "reported_date"
    NOTICE_GAP_DAYS = "notice_gap_days"


@dataclass
class BillArtifact:
    """Reconstructable bill model containing all source data."""

    artifact_id: str
    bill_id: str
    session: str
    committee_id: str
    created_at: datetime
    bill_metadata: dict[str, Any] = field(default_factory=dict)
    hearing_records: list[HearingRecord] = field(default_factory=list)
    timeline_actions: list[TimelineAction] = field(default_factory=list)
    document_artifacts: list[DocumentArtifact] = field(default_factory=list)
    extension_records: list[ExtensionRecord] = field(default_factory=list)
    snapshots: list[ArtifactSnapshot] = field(default_factory=list)

    @staticmethod
    def new(bill_id: str, session: str, committee_id: str) -> BillArtifact:
        """Create a new bill artifact."""
        return BillArtifact(
            artifact_id=str(uuid.uuid4()),
            bill_id=bill_id,
            session=session,
            committee_id=committee_id,
            created_at=datetime.utcnow(),
        )


@dataclass
class HearingRecord:
    """A hearing record for a bill."""

    record_id: str
    hearing_id: Optional[str] = None
    hearing_date: Optional[date] = None
    hearing_url: Optional[str] = None
    announcement_date: Optional[date] = None
    scheduled_hearing_date: Optional[date] = None
    announcement_metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new() -> HearingRecord:
        """Create a new hearing record."""
        return HearingRecord(record_id=str(uuid.uuid4()))


@dataclass
class TimelineAction:
    """A single action from bill history."""

    action_id: str
    action_date: date
    branch: str
    action_type: str
    category: str
    raw_text: str
    extracted_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    @staticmethod
    def new(
        action_date: date, branch: str, action_type: str, category: str, raw_text: str
    ) -> TimelineAction:
        """Create a new timeline action."""
        return TimelineAction(
            action_id=str(uuid.uuid4()),
            action_date=action_date,
            branch=branch,
            action_type=action_type,
            category=category,
            raw_text=raw_text,
        )


@dataclass
class DocumentArtifact:
    """A discovered compliance document (summary or votes)."""

    document_id: str
    document_type: DocumentType
    discovered_at: datetime
    location: str
    source_url: Optional[str] = None
    parser_module: Optional[str] = None
    parser_version: Optional[str] = None
    confidence: Optional[float] = None
    content_hash: Optional[str] = None
    content_preview: Optional[str] = None
    full_content: Optional[dict[str, Any]] = None
    needs_review: bool = False

    @staticmethod
    def new(document_type: DocumentType, location: str) -> DocumentArtifact:
        """Create a new document artifact."""
        return DocumentArtifact(
            document_id=str(uuid.uuid4()),
            document_type=document_type,
            discovered_at=datetime.utcnow(),
            location=location,
        )

    @staticmethod
    def hash_content(content: str) -> str:
        """Hash the content of the document."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class ExtensionRecord:
    """An extension order for deadline."""

    extension_id: str
    extension_date: date
    extension_until: Optional[date] = None
    order_url: Optional[str] = None
    order_type: str = ""
    is_fallback: bool = False

    @staticmethod
    def new(extension_date: date) -> ExtensionRecord:
        """Create a new extension record."""
        return ExtensionRecord(
            extension_id=str(uuid.uuid4()),
            extension_date=extension_date,
        )


@dataclass
class ArtifactSnapshot:
    """A computed compliance snapshot at a specific time."""

    snapshot_id: str
    snapshot_date: datetime
    ruleset_version: str
    computed_state: str
    computed_reason: str
    computation_metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new(
        ruleset_version: str, computed_state: str, computed_reason: str
    ) -> ArtifactSnapshot:
        """Create a new artifact snapshot."""
        return ArtifactSnapshot(
            snapshot_id=str(uuid.uuid4()),
            snapshot_date=datetime.utcnow(),
            ruleset_version=ruleset_version,
            computed_state=computed_state,
            computed_reason=computed_reason,
        )
