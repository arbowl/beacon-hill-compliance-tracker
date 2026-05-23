"""SQLite3-backed cache -- drop-in replacement for the JSON-file Cache class.

Two databases:
  cache/cache.db  -- bill + committee data (frequent, small writes)
  cache/docs.db   -- document cache (large entries, pruned separately)
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from components.interfaces import Config

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("cache/cache.db")
_DEFAULT_DOCS_DB_PATH = Path("cache/docs.db")

_CACHE_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS bill_meta (
    bill_id          TEXT PRIMARY KEY,
    bill_url         TEXT,
    title            TEXT,
    title_updated_at TEXT
);

CREATE TABLE IF NOT EXISTS bill_parsers (
    bill_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    module      TEXT NOT NULL,
    confirmed   INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    updated_at  TEXT,
    PRIMARY KEY (bill_id, kind)
);

CREATE TABLE IF NOT EXISTS bill_votes_by_committee (
    bill_id      TEXT NOT NULL,
    committee_id TEXT NOT NULL,
    module       TEXT NOT NULL,
    confirmed    INTEGER NOT NULL DEFAULT 0,
    result_json  TEXT,
    updated_at   TEXT,
    PRIMARY KEY (bill_id, committee_id)
);

CREATE TABLE IF NOT EXISTS bill_extensions (
    bill_id        TEXT PRIMARY KEY,
    extension_date TEXT,
    extension_url  TEXT,
    is_fallback    INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT
);

CREATE TABLE IF NOT EXISTS bill_hearings (
    bill_id                  TEXT PRIMARY KEY,
    announcement_date        TEXT,
    scheduled_hearing_date   TEXT,
    updated_at               TEXT
);

CREATE TABLE IF NOT EXISTS committee_contacts (
    committee_id TEXT PRIMARY KEY,
    contact_json TEXT NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS committee_bills (
    committee_id TEXT NOT NULL,
    bill_id      TEXT NOT NULL,
    PRIMARY KEY (committee_id, bill_id)
);

CREATE INDEX IF NOT EXISTS idx_committee_bills_bill
    ON committee_bills(bill_id);

CREATE TABLE IF NOT EXISTS committee_parsers (
    committee_id   TEXT NOT NULL,
    parser_type    TEXT NOT NULL,
    module_name    TEXT NOT NULL,
    count          INTEGER NOT NULL DEFAULT 0,
    current_streak INTEGER NOT NULL DEFAULT 0,
    first_seen     TEXT,
    last_used      TEXT,
    is_last_parser INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (committee_id, parser_type, module_name)
);
"""

_DOCS_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS document_cache (
    url              TEXT PRIMARY KEY,
    content_hash     TEXT NOT NULL,
    content_type     TEXT,
    file_size_bytes  INTEGER,
    cached_file_path TEXT,
    first_downloaded TEXT,
    last_accessed    TEXT,
    last_validated   TEXT,
    access_count     INTEGER NOT NULL DEFAULT 0,
    etag             TEXT,
    last_modified    TEXT,
    bill_ids_json    TEXT,
    document_purpose TEXT
);

CREATE INDEX IF NOT EXISTS idx_doc_cache_hash
    ON document_cache(content_hash);
"""


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _open_db(path: Path, schema: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None → autocommit; each execute() is immediately durable.
    # WAL mode + our RLock makes this safe under concurrent access.
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    return conn


class CacheDB:
    """SQLite-backed cache with identical public API to the legacy Cache class."""

    def __init__(
        self,
        path: Path = _DEFAULT_DB_PATH,
        auto_save: bool = True,  # accepted for API compatibility, not needed
        docs_path: Optional[Path] = None,
    ) -> None:
        self.path = path
        self._docs_path = docs_path or path.parent / "docs.db"
        self._lock: threading.RLock = threading.RLock()
        self._conn = _open_db(path, _CACHE_SCHEMA)
        self._docs_conn = _open_db(self._docs_path, _DOCS_SCHEMA)
        # Mirrors committee_bills in memory for hot-path O(1) membership checks
        self._committee_bills_cache: dict[str, set[str]] = {}
        self._load_committee_bills_cache()

    def _load_committee_bills_cache(self) -> None:
        for row in self._conn.execute(
            "SELECT committee_id, bill_id FROM committee_bills"
        ):
            cid = row["committee_id"]
            if cid not in self._committee_bills_cache:
                self._committee_bills_cache[cid] = set()
            self._committee_bills_cache[cid].add(row["bill_id"])

    # ------------------------------------------------------------------
    # save / force_save -- no-ops; SQLite writes are immediate per statement
    # ------------------------------------------------------------------

    def save(self) -> None:
        pass

    def force_save(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    def get_session(self) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='session'"
        ).fetchone()
        return row["value"] if row else None

    def _archive_cache(self, session: str) -> None:
        archive_dir = self.path.parent / "archive" / session
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.path, archive_dir / "cache.db")
        if self._docs_path.exists():
            shutil.copy2(self._docs_path, archive_dir / "docs.db")
        logger.info("Archived cache for session %s to %s", session, archive_dir)

    def ensure_session(self, current_session: str) -> None:
        with self._lock:
            stored = self.get_session()
            if stored is None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES('session', ?)",
                    (current_session,),
                )
                logger.info("Set cache session to %s", current_session)
            elif stored != current_session:
                logger.info(
                    "Session mismatch: cache has %s, current is %s. Archiving.",
                    stored,
                    current_session,
                )
                self._archive_cache(stored)
                for table in (
                    "meta",
                    "bill_meta",
                    "bill_parsers",
                    "bill_votes_by_committee",
                    "bill_extensions",
                    "bill_hearings",
                    "committee_contacts",
                    "committee_bills",
                    "committee_parsers",
                ):
                    self._conn.execute(f"DELETE FROM {table}")  # noqa: S608
                self._conn.execute(
                    "INSERT INTO meta(key, value) VALUES('session', ?)",
                    (current_session,),
                )
                self._committee_bills_cache.clear()
                logger.info("Started fresh cache for session %s", current_session)

    # ------------------------------------------------------------------
    # Bill-level parsers (summary / votes)
    # ------------------------------------------------------------------

    def get_parser(self, bill_id: str, kind: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT module FROM bill_parsers WHERE bill_id=? AND kind=?",
            (bill_id, kind),
        ).fetchone()
        return row["module"] if row else None

    def is_confirmed(self, bill_id: str, kind: str) -> bool:
        row = self._conn.execute(
            "SELECT confirmed FROM bill_parsers WHERE bill_id=? AND kind=?",
            (bill_id, kind),
        ).fetchone()
        return bool(row["confirmed"]) if row else False

    def set_parser(
        self, bill_id: str, kind: str, module_name: str, *, confirmed: bool
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_parsers(bill_id, kind, module, confirmed, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(bill_id, kind) DO UPDATE SET
                    module=excluded.module,
                    confirmed=excluded.confirmed,
                    updated_at=excluded.updated_at
                """,
                (bill_id, kind, module_name, int(confirmed), _now()),
            )

    def get_result(self, bill_id: str, kind: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT result_json FROM bill_parsers WHERE bill_id=? AND kind=?",
            (bill_id, kind),
        ).fetchone()
        if row and row["result_json"]:
            try:
                return json.loads(row["result_json"])
            except json.JSONDecodeError:
                return None
        return None

    def set_result(
        self,
        bill_id: str,
        kind: str,
        module_name: str,
        result_data: dict,
        *,
        confirmed: bool,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_parsers(bill_id, kind, module, confirmed, result_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(bill_id, kind) DO UPDATE SET
                    module=excluded.module,
                    confirmed=excluded.confirmed,
                    result_json=excluded.result_json,
                    updated_at=excluded.updated_at
                """,
                (bill_id, kind, module_name, int(confirmed), json.dumps(result_data), _now()),
            )

    # ------------------------------------------------------------------
    # Votes per committee (votes_by_committee)
    # ------------------------------------------------------------------

    def get_votes_parser(self, bill_id: str, committee_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT module FROM bill_votes_by_committee WHERE bill_id=? AND committee_id=?",
            (bill_id, committee_id),
        ).fetchone()
        if row:
            return row["module"]
        return self.get_parser(bill_id, "votes")

    def is_votes_confirmed(self, bill_id: str, committee_id: str) -> bool:
        row = self._conn.execute(
            "SELECT confirmed FROM bill_votes_by_committee WHERE bill_id=? AND committee_id=?",
            (bill_id, committee_id),
        ).fetchone()
        return bool(row["confirmed"]) if row else False

    def get_votes_result(self, bill_id: str, committee_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT result_json FROM bill_votes_by_committee WHERE bill_id=? AND committee_id=?",
            (bill_id, committee_id),
        ).fetchone()
        if row and row["result_json"]:
            try:
                return json.loads(row["result_json"])
            except json.JSONDecodeError:
                return None
        return self.get_result(bill_id, "votes")

    def set_votes_result(
        self,
        bill_id: str,
        committee_id: str,
        module_name: str,
        result_data: dict,
        *,
        confirmed: bool,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_votes_by_committee
                    (bill_id, committee_id, module, confirmed, result_json, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(bill_id, committee_id) DO UPDATE SET
                    module=excluded.module,
                    confirmed=excluded.confirmed,
                    result_json=excluded.result_json,
                    updated_at=excluded.updated_at
                """,
                (bill_id, committee_id, module_name, int(confirmed), json.dumps(result_data), _now()),
            )

    def set_votes_parser(
        self,
        bill_id: str,
        committee_id: str,
        module_name: str,
        *,
        confirmed: bool,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_votes_by_committee
                    (bill_id, committee_id, module, confirmed, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(bill_id, committee_id) DO UPDATE SET
                    module=excluded.module,
                    confirmed=excluded.confirmed,
                    updated_at=excluded.updated_at
                """,
                (bill_id, committee_id, module_name, int(confirmed), _now()),
            )

    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------

    def get_extension(self, bill_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT extension_date, extension_url, is_fallback, updated_at"
            " FROM bill_extensions WHERE bill_id=?",
            (bill_id,),
        ).fetchone()
        if not row:
            return None
        result: dict[str, Any] = {"updated_at": row["updated_at"] or ""}
        if row["is_fallback"]:
            result["is_fallback"] = True
        else:
            result["extension_date"] = row["extension_date"]
            result["extension_url"] = row["extension_url"]
        return result

    def set_extension(
        self, bill_id: str, extension_date: str, extension_url: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_extensions
                    (bill_id, extension_date, extension_url, is_fallback, updated_at)
                VALUES(?, ?, ?, 0, ?)
                ON CONFLICT(bill_id) DO UPDATE SET
                    extension_date=excluded.extension_date,
                    extension_url=excluded.extension_url,
                    is_fallback=0,
                    updated_at=excluded.updated_at
                """,
                (bill_id, extension_date, extension_url, _now()),
            )

    def add_bill_with_extensions(self, bill_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO bill_extensions(bill_id, is_fallback, updated_at)"
                " VALUES(?, 1, ?)",
                (bill_id, _now()),
            )

    # ------------------------------------------------------------------
    # Hearing announcements
    # ------------------------------------------------------------------

    def get_hearing_announcement(self, bill_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT announcement_date, scheduled_hearing_date, updated_at"
            " FROM bill_hearings WHERE bill_id=?",
            (bill_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "announcement_date": row["announcement_date"],
            "scheduled_hearing_date": row["scheduled_hearing_date"],
            "updated_at": row["updated_at"] or "",
        }

    def set_hearing_announcement(
        self,
        bill_id: str,
        announcement_date: Optional[str],
        scheduled_hearing_date: Optional[str],
        bill_url: Optional[str] = None,
    ) -> None:
        with self._lock:
            if bill_url:
                self._conn.execute(
                    "INSERT INTO bill_meta(bill_id, bill_url) VALUES(?, ?)"
                    " ON CONFLICT(bill_id) DO UPDATE SET bill_url=excluded.bill_url",
                    (bill_id, bill_url),
                )
            self._conn.execute(
                """
                INSERT INTO bill_hearings
                    (bill_id, announcement_date, scheduled_hearing_date, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(bill_id) DO UPDATE SET
                    announcement_date=excluded.announcement_date,
                    scheduled_hearing_date=excluded.scheduled_hearing_date,
                    updated_at=excluded.updated_at
                """,
                (bill_id, announcement_date, scheduled_hearing_date, _now()),
            )

    def clear_hearing_announcement(self, bill_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM bill_hearings WHERE bill_id=?", (bill_id,)
            )

    # ------------------------------------------------------------------
    # Bill URL and title
    # ------------------------------------------------------------------

    def get_bill_url(self, bill_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT bill_url FROM bill_meta WHERE bill_id=?", (bill_id,)
        ).fetchone()
        return row["bill_url"] if row else None

    def set_bill_url(self, bill_id: str, bill_url: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO bill_meta(bill_id, bill_url) VALUES(?, ?)"
                " ON CONFLICT(bill_id) DO UPDATE SET bill_url=excluded.bill_url",
                (bill_id, bill_url),
            )

    def get_title(self, bill_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT title FROM bill_meta WHERE bill_id=?", (bill_id,)
        ).fetchone()
        return row["title"] if row else None

    def set_title(self, bill_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bill_meta(bill_id, title, title_updated_at) VALUES(?, ?, ?)
                ON CONFLICT(bill_id) DO UPDATE SET
                    title=excluded.title,
                    title_updated_at=excluded.title_updated_at
                """,
                (bill_id, title, _now()),
            )

    # ------------------------------------------------------------------
    # Committee contacts
    # ------------------------------------------------------------------

    def get_committee_contact(self, committee_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT contact_json FROM committee_contacts WHERE committee_id=?",
            (committee_id,),
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["contact_json"])
        except json.JSONDecodeError:
            return None

    def set_committee_contact(self, committee_id: str, contact_data: dict) -> None:
        with self._lock:
            now = _now()
            merged = {**contact_data, "updated_at": now}
            self._conn.execute(
                """
                INSERT INTO committee_contacts(committee_id, contact_json, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(committee_id) DO UPDATE SET
                    contact_json=excluded.contact_json,
                    updated_at=excluded.updated_at
                """,
                (committee_id, json.dumps(merged), now),
            )

    # ------------------------------------------------------------------
    # Committee bills
    # ------------------------------------------------------------------

    def add_bill_to_committee(self, committee_id: str, bill_id: str) -> None:
        with self._lock:
            if committee_id not in self._committee_bills_cache:
                self._committee_bills_cache[committee_id] = set()
            if bill_id in self._committee_bills_cache[committee_id]:
                return
            self._committee_bills_cache[committee_id].add(bill_id)
            self._conn.execute(
                "INSERT OR IGNORE INTO committee_bills(committee_id, bill_id) VALUES(?, ?)",
                (committee_id, bill_id),
            )

    def get_committee_bills(self, committee_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT bill_id FROM committee_bills WHERE committee_id=?",
            (committee_id,),
        ).fetchall()
        return [row["bill_id"] for row in rows]

    # ------------------------------------------------------------------
    # Committee parsers
    # ------------------------------------------------------------------

    def get_committee_parsers(self, committee_id: str, parser_type: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT module_name
            FROM committee_parsers
            WHERE committee_id=? AND parser_type=?
            ORDER BY
                CASE WHEN current_streak >= 2 THEN 1 ELSE 0 END DESC,
                count DESC
            """,
            (committee_id, parser_type),
        ).fetchall()
        return [row["module_name"] for row in rows]

    def record_committee_parser(
        self, committee_id: str, parser_type: str, module_name: str
    ) -> None:
        with self._lock:
            now = _now()
            last_row = self._conn.execute(
                "SELECT module_name FROM committee_parsers"
                " WHERE committee_id=? AND parser_type=? AND is_last_parser=1",
                (committee_id, parser_type),
            ).fetchone()
            last_parser = last_row["module_name"] if last_row else None

            if last_parser != module_name:
                # New parser -- reset all streaks for this committee/type
                self._conn.execute(
                    "UPDATE committee_parsers SET current_streak=0, is_last_parser=0"
                    " WHERE committee_id=? AND parser_type=?",
                    (committee_id, parser_type),
                )

            # Upsert this parser.
            # In the DO UPDATE branch, `is_last_parser` refers to the row's
            # pre-update value: if it was 1, the streak was still active so
            # we increment; if 0 (just reset above), we restart at 1.
            self._conn.execute(
                """
                INSERT INTO committee_parsers
                    (committee_id, parser_type, module_name,
                     count, current_streak, first_seen, last_used, is_last_parser)
                VALUES(?, ?, ?, 1, 1, ?, ?, 1)
                ON CONFLICT(committee_id, parser_type, module_name) DO UPDATE SET
                    count=count+1,
                    current_streak=CASE WHEN is_last_parser=1
                                        THEN current_streak+1
                                        ELSE 1 END,
                    last_used=excluded.last_used,
                    is_last_parser=1
                """,
                (committee_id, parser_type, module_name, now, now),
            )

    # ------------------------------------------------------------------
    # Keyword search (used to detect whether extension data exists)
    # ------------------------------------------------------------------

    def search_for_keyword(self, keyword: str) -> bool:
        if "extension" in keyword.lower():
            row = self._conn.execute(
                "SELECT 1 FROM bill_extensions WHERE extension_date IS NOT NULL LIMIT 1"
            ).fetchone()
            return bool(row)
        kw = f"%{keyword.lower()}%"
        for table, col in [("bill_parsers", "module"), ("bill_meta", "bill_url")]:
            row = self._conn.execute(
                f"SELECT 1 FROM {table} WHERE lower({col}) LIKE ? LIMIT 1",  # noqa: S608
                (kw,),
            ).fetchone()
            if row:
                return True
        return False

    # ------------------------------------------------------------------
    # Document cache
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_content_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _get_file_extension(content_type: str, url: str) -> str:
        ct = content_type.lower()
        if "pdf" in ct:
            return "pdf"
        if "wordprocessing" in ct or "docx" in ct:
            return "docx"
        if "msword" in ct or "doc" in ct:
            return "doc"
        url_l = url.lower()
        if url_l.endswith(".pdf"):
            return "pdf"
        if url_l.endswith(".docx"):
            return "docx"
        if url_l.endswith(".doc"):
            return "doc"
        return "bin"

    def get_cached_document(
        self, url: str, config: Optional[Config] = None
    ) -> Optional[dict]:
        if not config or not config.document_cache.enabled:
            return None
        row = self._docs_conn.execute(
            "SELECT * FROM document_cache WHERE url=?", (url,)
        ).fetchone()
        if not row:
            return None
        cached_file_path = Path(row["cached_file_path"] or "")
        if not cached_file_path.exists():
            return None
        last_validated = row["last_validated"]
        if last_validated:
            try:
                lv_dt = datetime.fromisoformat(last_validated.replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - lv_dt).days > config.document_cache.validate_after_days:
                    return None
            except (ValueError, AttributeError):
                return None
        entry = dict(row)
        try:
            entry["bill_ids"] = json.loads(entry.pop("bill_ids_json") or "[]")
        except json.JSONDecodeError:
            entry["bill_ids"] = []
        return entry

    def cache_document(
        self,
        url: str,
        content: bytes,
        config: Config,
        content_type: str = "application/octet-stream",
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        bill_id: Optional[str] = None,
        document_purpose: Optional[str] = None,
    ) -> dict:
        with self._lock:
            content_hash = self._compute_content_hash(content)
            file_ext = self._get_file_extension(content_type, url)
            cache_dir = Path(config.document_cache.directory)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_file_path = cache_dir / f"{content_hash}.{file_ext}"
            if not cached_file_path.exists():
                cached_file_path.write_bytes(content)
            now = _now()
            existing = self._docs_conn.execute(
                "SELECT first_downloaded, access_count, bill_ids_json"
                " FROM document_cache WHERE url=?",
                (url,),
            ).fetchone()
            first_downloaded = existing["first_downloaded"] if existing else now
            access_count = (existing["access_count"] + 1) if existing else 1
            bill_ids: list[str] = []
            if existing and existing["bill_ids_json"]:
                try:
                    bill_ids = json.loads(existing["bill_ids_json"])
                except json.JSONDecodeError:
                    pass
            if bill_id and bill_id not in bill_ids:
                bill_ids.append(bill_id)
            self._docs_conn.execute(
                """
                INSERT INTO document_cache
                    (url, content_hash, content_type, file_size_bytes,
                     cached_file_path, first_downloaded, last_accessed, last_validated,
                     access_count, etag, last_modified, bill_ids_json, document_purpose)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    content_type=excluded.content_type,
                    file_size_bytes=excluded.file_size_bytes,
                    cached_file_path=excluded.cached_file_path,
                    last_accessed=excluded.last_accessed,
                    last_validated=excluded.last_validated,
                    access_count=excluded.access_count,
                    etag=excluded.etag,
                    last_modified=excluded.last_modified,
                    bill_ids_json=excluded.bill_ids_json,
                    document_purpose=excluded.document_purpose
                """,
                (
                    url, content_hash, content_type, len(content),
                    str(cached_file_path), first_downloaded, now, now,
                    access_count, etag, last_modified,
                    json.dumps(bill_ids), document_purpose,
                ),
            )
            return {
                "url": url,
                "content_hash": content_hash,
                "content_type": content_type,
                "file_size_bytes": len(content),
                "cached_file_path": str(cached_file_path),
                "first_downloaded": first_downloaded,
                "last_accessed": now,
                "last_validated": now,
                "access_count": access_count,
                "etag": etag,
                "last_modified": last_modified,
                "bill_ids": bill_ids,
                "document_purpose": document_purpose,
            }

    def get_cached_document_content(
        self, url: str, config: Optional[Config] = None
    ) -> Optional[bytes]:
        cache_entry = self.get_cached_document(url, config)
        if not cache_entry:
            return None
        cached_file_path = Path(cache_entry.get("cached_file_path", ""))
        if not cached_file_path.exists():
            return None
        with self._lock:
            self._docs_conn.execute(
                "UPDATE document_cache SET last_accessed=?, access_count=access_count+1"
                " WHERE url=?",
                (_now(), url),
            )
        return cached_file_path.read_bytes()

    def cache_extracted_text(
        self, content_hash: str, extracted_text: str, config: Config
    ) -> None:
        if not config.document_cache.store_extracted_text:
            return
        extracted_dir = Path(config.document_cache.extracted_text_directory)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        (extracted_dir / f"{content_hash}.txt").write_text(extracted_text, encoding="utf-8")

    def get_cached_extracted_text(
        self, content_hash: str, config: Optional[Config] = None
    ) -> Optional[str]:
        if not config or not config.document_cache.store_extracted_text:
            return None
        extracted_file = (
            Path(config.document_cache.extracted_text_directory) / f"{content_hash}.txt"
        )
        if not extracted_file.exists():
            return None
        try:
            return extracted_file.read_text(encoding="utf-8")
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def cleanup_document_cache(
        self, config: Config, force: bool = False
    ) -> dict[str, int]:
        with self._lock:
            stats: dict[str, int] = {
                "documents_removed": 0,
                "bytes_freed": 0,
                "files_deleted": 0,
            }
            if not force:
                last_row = self._docs_conn.execute(
                    "SELECT value FROM meta WHERE key='last_cleanup'"
                ).fetchone()
                if last_row:
                    try:
                        last_dt = datetime.fromisoformat(
                            last_row["value"].replace("Z", "+00:00")
                        )
                        if (datetime.now(timezone.utc) - last_dt).days < 1:
                            return stats
                    except (ValueError, AttributeError):
                        pass
            max_age_days = config.document_cache.max_age_days
            old_rows = self._docs_conn.execute(
                """
                SELECT url, content_hash, file_size_bytes, cached_file_path
                FROM document_cache
                WHERE last_accessed < datetime('now', ? || ' days')
                """,
                (f"-{max_age_days}",),
            ).fetchall()
            hashes_still_referenced: set[str] = set(
                row["content_hash"]
                for row in self._docs_conn.execute(
                    "SELECT DISTINCT content_hash FROM document_cache"
                    " WHERE last_accessed >= datetime('now', ? || ' days')",
                    (f"-{max_age_days}",),
                )
            )
            for row in old_rows:
                self._docs_conn.execute(
                    "DELETE FROM document_cache WHERE url=?", (row["url"],)
                )
                stats["documents_removed"] += 1
                stats["bytes_freed"] += row["file_size_bytes"] or 0
                h = row["content_hash"]
                if h not in hashes_still_referenced:
                    fp = Path(row["cached_file_path"] or "")
                    if fp.exists():
                        try:
                            fp.unlink()
                            stats["files_deleted"] += 1
                        except Exception:  # pylint: disable=broad-exception-caught
                            pass
            self._docs_conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('last_cleanup', ?)",
                (_now(),),
            )
            return stats

    # ------------------------------------------------------------------
    # API export: reconstruct legacy cache.json structure from SQLite
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire cache to a dict matching the legacy cache.json shape.

        Called only when uploading to the remote API -- not on the write path.
        """
        result: dict[str, Any] = {}

        session = self.get_session()
        if session:
            result["session"] = session

        # --- bill_parsers ---
        bill_parsers: dict[str, Any] = {}

        for row in self._conn.execute("SELECT * FROM bill_meta"):
            bid = row["bill_id"]
            slot = bill_parsers.setdefault(bid, {})
            if row["bill_url"]:
                slot["bill_url"] = row["bill_url"]
            if row["title"]:
                slot["title"] = {
                    "value": row["title"],
                    "updated_at": row["title_updated_at"] or "",
                }

        for row in self._conn.execute("SELECT * FROM bill_parsers"):
            bid = row["bill_id"]
            slot = bill_parsers.setdefault(bid, {})
            entry: dict[str, Any] = {
                "module": row["module"],
                "confirmed": bool(row["confirmed"]),
                "updated_at": row["updated_at"] or "",
            }
            if row["result_json"]:
                try:
                    entry["result"] = json.loads(row["result_json"])
                except json.JSONDecodeError:
                    pass
            slot[row["kind"]] = entry

        for row in self._conn.execute("SELECT * FROM bill_votes_by_committee"):
            bid = row["bill_id"]
            slot = bill_parsers.setdefault(bid, {})
            by_comm = slot.setdefault("votes_by_committee", {})
            entry = {
                "module": row["module"],
                "confirmed": bool(row["confirmed"]),
                "updated_at": row["updated_at"] or "",
            }
            if row["result_json"]:
                try:
                    entry["result"] = json.loads(row["result_json"])
                except json.JSONDecodeError:
                    pass
            by_comm[row["committee_id"]] = {"votes": entry}

        for row in self._conn.execute("SELECT * FROM bill_extensions"):
            bid = row["bill_id"]
            slot = bill_parsers.setdefault(bid, {})
            ext: dict[str, Any] = {"updated_at": row["updated_at"] or ""}
            if row["is_fallback"]:
                ext["is_fallback"] = True
            else:
                ext["extension_date"] = row["extension_date"]
                ext["extension_url"] = row["extension_url"]
            slot["extensions"] = ext

        for row in self._conn.execute("SELECT * FROM bill_hearings"):
            bid = row["bill_id"]
            slot = bill_parsers.setdefault(bid, {})
            slot["hearing_announcement"] = {
                "announcement_date": row["announcement_date"],
                "scheduled_hearing_date": row["scheduled_hearing_date"],
                "updated_at": row["updated_at"] or "",
            }

        result["bill_parsers"] = bill_parsers

        # --- committee_contacts ---
        contacts: dict[str, Any] = {}
        for row in self._conn.execute("SELECT * FROM committee_contacts"):
            try:
                contacts[row["committee_id"]] = json.loads(row["contact_json"])
            except json.JSONDecodeError:
                pass
        result["committee_contacts"] = contacts

        # --- committee_bills ---
        # Derive last_updated per committee from the most recently updated
        # bill_parsers row for any bill in that committee — mirrors the
        # timestamp the old JSON cache wrote on every add_bill_to_committee call.
        comm_last_updated: dict[str, str] = {}
        for row in self._conn.execute(
            """
            SELECT cb.committee_id, MAX(bp.updated_at) AS last_updated
            FROM committee_bills cb
            LEFT JOIN bill_parsers bp ON cb.bill_id = bp.bill_id
            GROUP BY cb.committee_id
            """
        ):
            comm_last_updated[row["committee_id"]] = row["last_updated"] or ""

        comm_bills: dict[str, Any] = {}
        for row in self._conn.execute(
            "SELECT committee_id, bill_id FROM committee_bills ORDER BY committee_id"
        ):
            cid = row["committee_id"]
            if cid not in comm_bills:
                comm_bills[cid] = {
                    "bills": [],
                    "bill_count": 0,
                    "last_updated": comm_last_updated.get(cid, ""),
                }
            comm_bills[cid]["bills"].append(row["bill_id"])
            comm_bills[cid]["bill_count"] += 1
        result["committee_bills"] = comm_bills

        # --- committee_parsers ---
        comm_parsers: dict[str, Any] = {}
        for row in self._conn.execute("SELECT * FROM committee_parsers"):
            cid = row["committee_id"]
            ptype = row["parser_type"]
            cid_data = comm_parsers.setdefault(cid, {})
            ptype_data = cid_data.setdefault(ptype, {})
            ptype_data[row["module_name"]] = {
                "count": row["count"],
                "current_streak": row["current_streak"],
                "first_seen": row["first_seen"] or "",
                "last_used": row["last_used"] or "",
            }
            if row["is_last_parser"]:
                cid_data[f"{ptype}_last_parser"] = row["module_name"]
        result["committee_parsers"] = comm_parsers

        # --- document_cache (from docs.db) ---
        by_url: dict[str, Any] = {}
        by_hash: dict[str, list[str]] = {}
        total_size = 0
        seen_hashes: set[str] = set()
        for row in self._docs_conn.execute("SELECT * FROM document_cache"):
            url = row["url"]
            entry = dict(row)
            try:
                entry["bill_ids"] = json.loads(entry.pop("bill_ids_json") or "[]")
            except json.JSONDecodeError:
                entry["bill_ids"] = []
                entry.pop("bill_ids_json", None)
            by_url[url] = entry
            h = row["content_hash"]
            by_hash.setdefault(h, []).append(url)
            if h not in seen_hashes:
                seen_hashes.add(h)
                total_size += row["file_size_bytes"] or 0
        cleanup_row = self._docs_conn.execute(
            "SELECT value FROM meta WHERE key='last_cleanup'"
        ).fetchone()
        result["document_cache"] = {
            "by_url": by_url,
            "by_content_hash": by_hash,
            "metadata": {
                "total_documents": len(by_url),
                "total_size_bytes": total_size,
                "last_cleanup": cleanup_row["value"] if cleanup_row else "",
            },
        }

        return result
