"""Repository for storing and retrieving bill artifacts from SQLite."""

import json
import sqlite3
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
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bill_artifacts (
                artifact_id TEXT PRIMARY KEY,
                bill_id TEXT NOT NULL,
                session TEXT NOT NULL,
                committee_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                bill_metadata JSON NOT NULL,
                UNIQUE(bill_id, session, committee_id)
            );

            CREATE TABLE IF NOT EXISTS hearing_records (
                record_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                hearing_id TEXT,
                hearing_date TEXT,
                hearing_url TEXT,
                announcement_date TEXT,
                scheduled_hearing_date TEXT,
                announcement_metadata JSON,
                FOREIGN KEY(artifact_id) REFERENCES bill_artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS timeline_actions (
                action_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                action_date TEXT NOT NULL,
                branch TEXT NOT NULL,
                action_type TEXT NOT NULL,
                category TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                extracted_data JSON,
                confidence REAL DEFAULT 1.0,
                FOREIGN KEY(artifact_id) REFERENCES bill_artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS document_artifacts (
                document_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                document_type TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                source_url TEXT,
                location TEXT NOT NULL,
                parser_module TEXT,
                parser_version TEXT,
                confidence REAL,
                content_hash TEXT,
                content_preview TEXT,
                full_content JSON,
                needs_review INTEGER DEFAULT 0,
                FOREIGN KEY(artifact_id) REFERENCES bill_artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS extension_records (
                extension_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                extension_date TEXT NOT NULL,
                extension_until TEXT,
                order_url TEXT,
                order_type TEXT,
                is_fallback INTEGER DEFAULT 0,
                FOREIGN KEY(artifact_id) REFERENCES bill_artifacts(artifact_id)
            );

            CREATE TABLE IF NOT EXISTS artifact_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                ruleset_version TEXT,
                computed_state TEXT,
                computed_reason TEXT,
                computation_metadata JSON,
                FOREIGN KEY(artifact_id) REFERENCES bill_artifacts(artifact_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bill_artifacts_bill_id ON bill_artifacts(bill_id);
            CREATE INDEX IF NOT EXISTS idx_bill_artifacts_committee ON bill_artifacts(committee_id);
            CREATE INDEX IF NOT EXISTS idx_hearing_records_artifact ON hearing_records(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_timeline_actions_artifact ON timeline_actions(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_timeline_actions_date ON timeline_actions(action_date);
            CREATE INDEX IF NOT EXISTS idx_document_artifacts_artifact ON document_artifacts(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_extension_records_artifact ON extension_records(artifact_id);
            CREATE INDEX IF NOT EXISTS idx_snapshots_artifact ON artifact_snapshots(artifact_id);
        """)
        conn.commit()
        conn.close()

    def save_artifact(self, artifact: BillArtifact) -> None:
        """Save a bill artifact to the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO bill_artifacts 
            (artifact_id, bill_id, session, committee_id, created_at, bill_metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.bill_id,
                artifact.session,
                artifact.committee_id,
                artifact.created_at.isoformat(),
                json.dumps(artifact.bill_metadata),
            ),
        )
        cursor.execute(
            "DELETE FROM hearing_records WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for hearing in artifact.hearing_records:
            cursor.execute(
                """
                INSERT INTO hearing_records 
                (record_id, artifact_id, hearing_id, hearing_date, hearing_url,
                 announcement_date, scheduled_hearing_date, announcement_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hearing.record_id,
                    artifact.artifact_id,
                    hearing.hearing_id,
                    hearing.hearing_date.isoformat() if hearing.hearing_date else None,
                    hearing.hearing_url,
                    hearing.announcement_date.isoformat() if hearing.announcement_date else None,
                    hearing.scheduled_hearing_date.isoformat() if hearing.scheduled_hearing_date else None,
                    json.dumps(hearing.announcement_metadata),
                ),
            )
        cursor.execute(
            "DELETE FROM timeline_actions WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for action in artifact.timeline_actions:
            cursor.execute(
                """
                INSERT INTO timeline_actions 
                (action_id, artifact_id, action_date, branch, action_type, 
                 category, raw_text, extracted_data, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id,
                    artifact.artifact_id,
                    action.action_date.isoformat(),
                    action.branch,
                    action.action_type,
                    action.category,
                    action.raw_text,
                    json.dumps(action.extracted_data),
                    action.confidence,
                ),
            )
        cursor.execute(
            "DELETE FROM document_artifacts WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for doc in artifact.document_artifacts:
            cursor.execute(
                """
                INSERT INTO document_artifacts 
                (document_id, artifact_id, document_type, discovered_at,
                 source_url, location, parser_module, parser_version,
                 confidence, content_hash, content_preview, full_content, needs_review)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                    json.dumps(doc.full_content) if doc.full_content else None,
                    1 if doc.needs_review else 0,
                ),
            )
        cursor.execute(
            "DELETE FROM extension_records WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for ext in artifact.extension_records:
            cursor.execute(
                """
                INSERT INTO extension_records 
                (extension_id, artifact_id, extension_date, extension_until,
                 order_url, order_type, is_fallback)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ext.extension_id,
                    artifact.artifact_id,
                    ext.extension_date.isoformat(),
                    ext.extension_until.isoformat() if ext.extension_until else None,
                    ext.order_url,
                    ext.order_type,
                    1 if ext.is_fallback else 0,
                ),
            )
        cursor.execute(
            "DELETE FROM artifact_snapshots WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for snapshot in artifact.snapshots:
            cursor.execute(
                """
                INSERT INTO artifact_snapshots 
                (snapshot_id, artifact_id, snapshot_date, ruleset_version,
                 computed_state, computed_reason, computation_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    artifact.artifact_id,
                    snapshot.snapshot_date.isoformat(),
                    snapshot.ruleset_version,
                    snapshot.computed_state,
                    snapshot.computed_reason,
                    json.dumps(snapshot.computation_metadata),
                ),
            )
        conn.commit()
        conn.close()

    def load_artifact(
        self,
        bill_id: str,
        committee_id: str,
        session: str = "194"
    ) -> Optional[BillArtifact]:
        """Load a bill artifact from the database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM bill_artifacts 
            WHERE bill_id = ? AND committee_id = ? AND session = ?
            """,
            (bill_id, committee_id, session)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        artifact = BillArtifact(
            artifact_id=row['artifact_id'],
            bill_id=row['bill_id'],
            session=row['session'],
            committee_id=row['committee_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            bill_metadata=json.loads(row['bill_metadata']),
        )
        cursor.execute(
            "SELECT * FROM hearing_records WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for row in cursor.fetchall():
            hearing = HearingRecord(
                record_id=row['record_id'],
                hearing_id=row['hearing_id'],
                hearing_date=date.fromisoformat(row['hearing_date']) if row['hearing_date'] else None,
                hearing_url=row['hearing_url'],
                announcement_date=date.fromisoformat(row['announcement_date']) if row['announcement_date'] else None,
                scheduled_hearing_date=date.fromisoformat(row['scheduled_hearing_date']) if row['scheduled_hearing_date'] else None,
                announcement_metadata=json.loads(row['announcement_metadata']),
            )
            artifact.hearing_records.append(hearing)
        cursor.execute(
            "SELECT * FROM timeline_actions WHERE artifact_id = ? ORDER BY action_date",
            (artifact.artifact_id,)
        )
        for row in cursor.fetchall():
            action = TimelineAction(
                action_id=row['action_id'],
                action_date=date.fromisoformat(row['action_date']),
                branch=row['branch'],
                action_type=row['action_type'],
                category=row['category'],
                raw_text=row['raw_text'],
                extracted_data=json.loads(row['extracted_data']),
                confidence=row['confidence'],
            )
            artifact.timeline_actions.append(action)
        cursor.execute(
            "SELECT * FROM document_artifacts WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for row in cursor.fetchall():
            doc = DocumentArtifact(
                document_id=row['document_id'],
                document_type=DocumentType(row['document_type']),
                discovered_at=datetime.fromisoformat(row['discovered_at']),
                source_url=row['source_url'],
                location=row['location'],
                parser_module=row['parser_module'],
                parser_version=row['parser_version'],
                confidence=row['confidence'],
                content_hash=row['content_hash'],
                content_preview=row['content_preview'],
                full_content=json.loads(row['full_content']) if row['full_content'] else None,
                needs_review=bool(row['needs_review']),
            )
            artifact.document_artifacts.append(doc)
        cursor.execute(
            "SELECT * FROM extension_records WHERE artifact_id = ?",
            (artifact.artifact_id,)
        )
        for row in cursor.fetchall():
            ext = ExtensionRecord(
                extension_id=row['extension_id'],
                extension_date=date.fromisoformat(row['extension_date']),
                extension_until=date.fromisoformat(row['extension_until']) if row['extension_until'] else None,
                order_url=row['order_url'],
                order_type=row['order_type'],
                is_fallback=bool(row['is_fallback']),
            )
            artifact.extension_records.append(ext)
        cursor.execute(
            "SELECT * FROM artifact_snapshots WHERE artifact_id = ? ORDER BY snapshot_date",
            (artifact.artifact_id,)
        )
        for row in cursor.fetchall():
            snapshot = ArtifactSnapshot(
                snapshot_id=row['snapshot_id'],
                snapshot_date=datetime.fromisoformat(row['snapshot_date']),
                ruleset_version=row['ruleset_version'],
                computed_state=row['computed_state'],
                computed_reason=row['computed_reason'],
                computation_metadata=json.loads(row['computation_metadata']),
            )
            artifact.snapshots.append(snapshot)
        conn.close()
        return artifact

    def get_all_bill_ids(
        self, committee_id: Optional[str] = None
    ) -> list[str]:
        """Get all bill IDs from the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        if committee_id:
            cursor.execute(
                "SELECT DISTINCT bill_id FROM bill_artifacts WHERE committee_id = ?",
                (committee_id,)
            )
        else:
            cursor.execute("SELECT DISTINCT bill_id FROM bill_artifacts")
        bill_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return bill_ids
