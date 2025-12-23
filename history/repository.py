"""Repository for storing and retrieving bill artifacts from DuckDB."""

import json
import duckdb
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from history.artifacts import (
    ArtifactSnapshot,
    BillArtifact,
    DocumentArtifact,
    DocumentType,
    ExtensionRecord,
    HearingRecord,
    TimelineAction,
)


class BillArtifactRepository:
    """Repository for storing and retrieving bill artifacts."""

    def __init__(self, db_path: str = "bill_artifacts.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(self.db_path)

        # Create tables - DuckDB doesn't have executescript
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bill_artifacts (
                artifact_id VARCHAR PRIMARY KEY,
                bill_id VARCHAR NOT NULL,
                session VARCHAR NOT NULL,
                committee_id VARCHAR NOT NULL,
                created_at VARCHAR NOT NULL,
                bill_metadata VARCHAR NOT NULL,
                UNIQUE(bill_id, session, committee_id)
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hearing_records (
                record_id VARCHAR PRIMARY KEY,
                artifact_id VARCHAR NOT NULL,
                hearing_id VARCHAR,
                hearing_date VARCHAR,
                hearing_url VARCHAR,
                announcement_date VARCHAR,
                scheduled_hearing_date VARCHAR,
                announcement_metadata VARCHAR
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS timeline_actions (
                action_id VARCHAR PRIMARY KEY,
                artifact_id VARCHAR NOT NULL,
                action_date VARCHAR NOT NULL,
                branch VARCHAR NOT NULL,
                action_type VARCHAR NOT NULL,
                category VARCHAR NOT NULL,
                raw_text VARCHAR NOT NULL,
                extracted_data VARCHAR,
                confidence REAL DEFAULT 1.0
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS document_artifacts (
                document_id VARCHAR PRIMARY KEY,
                artifact_id VARCHAR NOT NULL,
                document_type VARCHAR NOT NULL,
                discovered_at VARCHAR NOT NULL,
                source_url VARCHAR,
                location VARCHAR NOT NULL,
                parser_module VARCHAR,
                parser_version VARCHAR,
                confidence REAL,
                content_hash VARCHAR,
                content_preview VARCHAR,
                full_content VARCHAR,
                needs_review INTEGER DEFAULT 0
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extension_records (
                extension_id VARCHAR PRIMARY KEY,
                artifact_id VARCHAR NOT NULL,
                extension_date VARCHAR NOT NULL,
                extension_until VARCHAR,
                order_url VARCHAR,
                order_type VARCHAR,
                is_fallback INTEGER DEFAULT 0
            )
        """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS artifact_snapshots (
                snapshot_id VARCHAR PRIMARY KEY,
                artifact_id VARCHAR NOT NULL,
                snapshot_date VARCHAR NOT NULL,
                ruleset_version VARCHAR,
                computed_state VARCHAR,
                computed_reason VARCHAR,
                computation_metadata VARCHAR
            )
        """
        )

        # Create indexes
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bill_artifacts_bill_id "
            "ON bill_artifacts(bill_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bill_artifacts_committee "
            "ON bill_artifacts(committee_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hearing_records_artifact "
            "ON hearing_records(artifact_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeline_actions_artifact "
            "ON timeline_actions(artifact_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_timeline_actions_date "
            "ON timeline_actions(action_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_document_artifacts_artifact "
            "ON document_artifacts(artifact_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_extension_records_artifact "
            "ON extension_records(artifact_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_artifact "
            "ON artifact_snapshots(artifact_id)"
        )

        conn.close()

    def save_artifact(self, artifact: BillArtifact) -> None:
        """Save a bill artifact to the database."""
        conn = duckdb.connect(self.db_path)

        # Delete existing artifact and related records first
        conn.execute(
            "DELETE FROM artifact_snapshots WHERE artifact_id = ?",
            [artifact.artifact_id],
        )
        conn.execute(
            "DELETE FROM extension_records WHERE artifact_id = ?",
            [artifact.artifact_id],
        )
        conn.execute(
            "DELETE FROM document_artifacts WHERE artifact_id = ?",
            [artifact.artifact_id],
        )
        conn.execute(
            "DELETE FROM timeline_actions WHERE artifact_id = ?", [artifact.artifact_id]
        )
        conn.execute(
            "DELETE FROM hearing_records WHERE artifact_id = ?", [artifact.artifact_id]
        )
        conn.execute(
            "DELETE FROM bill_artifacts WHERE artifact_id = ?", [artifact.artifact_id]
        )

        # Insert the main artifact
        conn.execute(
            """
            INSERT INTO bill_artifacts
            (artifact_id, bill_id, session, committee_id, created_at,
             bill_metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                artifact.artifact_id,
                artifact.bill_id,
                artifact.session,
                artifact.committee_id,
                artifact.created_at.isoformat(),
                json.dumps(artifact.bill_metadata),
            ],
        )

        # Insert hearing records
        for hearing in artifact.hearing_records:
            hearing_date_iso = (
                hearing.hearing_date.isoformat() if hearing.hearing_date else None
            )
            announcement_date_iso = (
                hearing.announcement_date.isoformat()
                if hearing.announcement_date
                else None
            )
            scheduled_date_iso = (
                hearing.scheduled_hearing_date.isoformat()
                if hearing.scheduled_hearing_date
                else None
            )

            conn.execute(
                """
                INSERT INTO hearing_records
                (record_id, artifact_id, hearing_id, hearing_date,
                 hearing_url, announcement_date, scheduled_hearing_date,
                 announcement_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    hearing.record_id,
                    artifact.artifact_id,
                    hearing.hearing_id,
                    hearing_date_iso,
                    hearing.hearing_url,
                    announcement_date_iso,
                    scheduled_date_iso,
                    json.dumps(hearing.announcement_metadata),
                ],
            )

        # Insert timeline actions
        for action in artifact.timeline_actions:
            conn.execute(
                """
                INSERT INTO timeline_actions
                (action_id, artifact_id, action_date, branch, action_type,
                 category, raw_text, extracted_data, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    action.action_id,
                    artifact.artifact_id,
                    action.action_date.isoformat(),
                    action.branch,
                    action.action_type,
                    action.category,
                    action.raw_text,
                    json.dumps(action.extracted_data),
                    action.confidence,
                ],
            )

        # Insert document artifacts
        for doc in artifact.document_artifacts:
            full_content_json = (
                json.dumps(doc.full_content) if doc.full_content else None
            )
            conn.execute(
                """
                INSERT INTO document_artifacts
                (document_id, artifact_id, document_type, discovered_at,
                 source_url, location, parser_module, parser_version,
                 confidence, content_hash, content_preview, full_content,
                 needs_review)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    doc.document_id,
                    artifact.artifact_id,
                    doc.document_type.value,
                    doc.discovered_at.isoformat(),
                    doc.source_url,
                    doc.location,
                    doc.parser_module,
                    doc.parser_version,
                    doc.confidence,
                    doc.content_hash,
                    doc.content_preview,
                    full_content_json,
                    1 if doc.needs_review else 0,
                ],
            )

        # Insert extension records
        for ext in artifact.extension_records:
            extension_until_iso = (
                ext.extension_until.isoformat() if ext.extension_until else None
            )
            conn.execute(
                """
                INSERT INTO extension_records
                (extension_id, artifact_id, extension_date, extension_until,
                 order_url, order_type, is_fallback)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ext.extension_id,
                    artifact.artifact_id,
                    ext.extension_date.isoformat(),
                    extension_until_iso,
                    ext.order_url,
                    ext.order_type,
                    1 if ext.is_fallback else 0,
                ],
            )

        # Insert artifact snapshots
        for snapshot in artifact.snapshots:
            conn.execute(
                """
                INSERT INTO artifact_snapshots
                (snapshot_id, artifact_id, snapshot_date, ruleset_version,
                 computed_state, computed_reason, computation_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    snapshot.snapshot_id,
                    artifact.artifact_id,
                    snapshot.snapshot_date.isoformat(),
                    snapshot.ruleset_version,
                    snapshot.computed_state,
                    snapshot.computed_reason,
                    json.dumps(snapshot.computation_metadata),
                ],
            )

        conn.close()

    def load_artifact(
        self, bill_id: str, committee_id: str, session: str = "194"
    ) -> Optional[BillArtifact]:
        """Load a bill artifact from the database."""
        conn = duckdb.connect(self.db_path)

        # Query for the main artifact
        result = conn.execute(
            """
            SELECT * FROM bill_artifacts
            WHERE bill_id = ? AND committee_id = ? AND session = ?
            """,
            [bill_id, committee_id, session],
        ).fetchdf()

        if result.empty:
            conn.close()
            return None

        row = result.iloc[0]
        artifact = BillArtifact(
            artifact_id=row["artifact_id"],
            bill_id=row["bill_id"],
            session=row["session"],
            committee_id=row["committee_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            bill_metadata=json.loads(row["bill_metadata"]),
        )

        # Load hearing records
        hearing_df = conn.execute(
            "SELECT * FROM hearing_records WHERE artifact_id = ?",
            [artifact.artifact_id],
        ).fetchdf()

        for _, row in hearing_df.iterrows():
            hearing_date = (
                date.fromisoformat(row["hearing_date"]) if row["hearing_date"] else None
            )
            announcement_date = (
                date.fromisoformat(row["announcement_date"])
                if row["announcement_date"]
                else None
            )
            scheduled_hearing_date = (
                date.fromisoformat(row["scheduled_hearing_date"])
                if row["scheduled_hearing_date"]
                else None
            )

            hearing = HearingRecord(
                record_id=row["record_id"],
                hearing_id=row["hearing_id"],
                hearing_date=hearing_date,
                hearing_url=row["hearing_url"],
                announcement_date=announcement_date,
                scheduled_hearing_date=scheduled_hearing_date,
                announcement_metadata=json.loads(row["announcement_metadata"]),
            )
            artifact.hearing_records.append(hearing)

        # Load timeline actions
        actions_df = conn.execute(
            """
            SELECT * FROM timeline_actions WHERE artifact_id = ?
            ORDER BY action_date
            """,
            [artifact.artifact_id],
        ).fetchdf()

        for _, row in actions_df.iterrows():
            action = TimelineAction(
                action_id=row["action_id"],
                action_date=date.fromisoformat(row["action_date"]),
                branch=row["branch"],
                action_type=row["action_type"],
                category=row["category"],
                raw_text=row["raw_text"],
                extracted_data=json.loads(row["extracted_data"]),
                confidence=row["confidence"],
            )
            artifact.timeline_actions.append(action)

        # Load document artifacts
        docs_df = conn.execute(
            "SELECT * FROM document_artifacts WHERE artifact_id = ?",
            [artifact.artifact_id],
        ).fetchdf()

        for _, row in docs_df.iterrows():
            full_content = (
                json.loads(row["full_content"]) if row["full_content"] else None
            )
            doc = DocumentArtifact(
                document_id=row["document_id"],
                document_type=DocumentType(row["document_type"]),
                discovered_at=datetime.fromisoformat(row["discovered_at"]),
                source_url=row["source_url"],
                location=row["location"],
                parser_module=row["parser_module"],
                parser_version=row["parser_version"],
                confidence=row["confidence"],
                content_hash=row["content_hash"],
                content_preview=row["content_preview"],
                full_content=full_content,
                needs_review=bool(row["needs_review"]),
            )
            artifact.document_artifacts.append(doc)

        # Load extension records
        ext_df = conn.execute(
            "SELECT * FROM extension_records WHERE artifact_id = ?",
            [artifact.artifact_id],
        ).fetchdf()

        for _, row in ext_df.iterrows():
            extension_until = (
                date.fromisoformat(row["extension_until"])
                if row["extension_until"]
                else None
            )
            ext = ExtensionRecord(
                extension_id=row["extension_id"],
                extension_date=date.fromisoformat(row["extension_date"]),
                extension_until=extension_until,
                order_url=row["order_url"],
                order_type=row["order_type"],
                is_fallback=bool(row["is_fallback"]),
            )
            artifact.extension_records.append(ext)

        # Load snapshots
        snapshots_df = conn.execute(
            """
            SELECT * FROM artifact_snapshots WHERE artifact_id = ?
            ORDER BY snapshot_date
            """,
            [artifact.artifact_id],
        ).fetchdf()

        for _, row in snapshots_df.iterrows():
            snapshot = ArtifactSnapshot(
                snapshot_id=row["snapshot_id"],
                snapshot_date=datetime.fromisoformat(row["snapshot_date"]),
                ruleset_version=row["ruleset_version"],
                computed_state=row["computed_state"],
                computed_reason=row["computed_reason"],
                computation_metadata=json.loads(row["computation_metadata"]),
            )
            artifact.snapshots.append(snapshot)

        conn.close()
        return artifact

    def get_all_bill_ids(self, committee_id: Optional[str] = None) -> list[str]:
        """Get all bill IDs from the database."""
        conn = duckdb.connect(self.db_path)

        if committee_id:
            result = conn.execute(
                """
                SELECT DISTINCT bill_id FROM bill_artifacts
                WHERE committee_id = ?
                """,
                [committee_id],
            ).fetchdf()
        else:
            result = conn.execute(
                "SELECT DISTINCT bill_id FROM bill_artifacts"
            ).fetchdf()

        bill_ids = result["bill_id"].tolist() if not result.empty else []
        conn.close()
        return bill_ids
