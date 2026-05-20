"""Migrate cache/cache.json → cache/cache.db + cache/docs.db.

Run once after upgrading to the SQLite-backed cache:

    python tools/migrate_cache.py

The original cache.json is left untouched. After verifying the app works
correctly with the new databases, you can remove cache.json manually.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path when run directly
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from components.cache import CacheDB  # noqa: E402


def migrate(
    json_path: Path,
    db_path: Path,
    docs_db_path: Path,
    *,
    verbose: bool = False,
) -> None:
    print(f"Reading {json_path} ...")
    data = json.loads(json_path.read_text(encoding="utf-8"))

    db = CacheDB(path=db_path, docs_path=docs_db_path)
    # Batch all inserts in explicit transactions for performance
    db._conn.execute("BEGIN")
    db._docs_conn.execute("BEGIN")
    counts: dict[str, int] = {}

    # --- session ---
    session = data.get("session")
    if session:
        db._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('session', ?)",
            (session,),
        )
        counts["session"] = 1

    # --- bill_parsers (multi-table) ---
    bill_parsers = data.get("bill_parsers", {})
    n_bills = 0
    for bill_id, slot in bill_parsers.items():
        if not isinstance(slot, dict):
            continue
        n_bills += 1

        # bill_meta: bill_url + title
        bill_url = slot.get("bill_url")
        title_entry = slot.get("title")
        title = title_updated_at = None
        if isinstance(title_entry, str):
            title = title_entry
        elif isinstance(title_entry, dict):
            title = title_entry.get("value")
            title_updated_at = title_entry.get("updated_at")
        if bill_url or title:
            db._conn.execute(
                "INSERT INTO bill_meta(bill_id, bill_url, title, title_updated_at)"
                " VALUES(?, ?, ?, ?)"
                " ON CONFLICT(bill_id) DO UPDATE SET"
                "   bill_url=COALESCE(excluded.bill_url, bill_url),"
                "   title=COALESCE(excluded.title, title),"
                "   title_updated_at=COALESCE(excluded.title_updated_at, title_updated_at)",
                (bill_id, bill_url, title, title_updated_at),
            )

        # extensions
        ext = slot.get("extensions")
        if isinstance(ext, dict):
            if ext.get("is_fallback"):
                db._conn.execute(
                    "INSERT OR IGNORE INTO bill_extensions"
                    " (bill_id, is_fallback, updated_at) VALUES(?, 1, ?)",
                    (bill_id, ext.get("updated_at", "")),
                )
            elif ext.get("extension_date"):
                db._conn.execute(
                    "INSERT OR REPLACE INTO bill_extensions"
                    " (bill_id, extension_date, extension_url, is_fallback, updated_at)"
                    " VALUES(?, ?, ?, 0, ?)",
                    (
                        bill_id,
                        ext.get("extension_date"),
                        ext.get("extension_url"),
                        ext.get("updated_at", ""),
                    ),
                )

        # hearing_announcement
        ha = slot.get("hearing_announcement")
        if isinstance(ha, dict):
            db._conn.execute(
                "INSERT OR REPLACE INTO bill_hearings"
                " (bill_id, announcement_date, scheduled_hearing_date, updated_at)"
                " VALUES(?, ?, ?, ?)",
                (
                    bill_id,
                    ha.get("announcement_date"),
                    ha.get("scheduled_hearing_date"),
                    ha.get("updated_at", ""),
                ),
            )

        # summary / votes (bill-level)
        for kind in ("summary", "votes"):
            entry = slot.get(kind)
            if isinstance(entry, str):
                # Old plain-string format -- just a module name
                db._conn.execute(
                    "INSERT OR REPLACE INTO bill_parsers"
                    " (bill_id, kind, module, confirmed, updated_at)"
                    " VALUES(?, ?, ?, 0, '')",
                    (bill_id, kind, entry),
                )
            elif isinstance(entry, dict):
                module = entry.get("module")
                if not module:
                    continue
                result_json = (
                    json.dumps(entry["result"])
                    if isinstance(entry.get("result"), dict)
                    else None
                )
                db._conn.execute(
                    "INSERT OR REPLACE INTO bill_parsers"
                    " (bill_id, kind, module, confirmed, result_json, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        bill_id,
                        kind,
                        module,
                        int(bool(entry.get("confirmed"))),
                        result_json,
                        entry.get("updated_at", ""),
                    ),
                )

        # votes_by_committee
        vbc = slot.get("votes_by_committee")
        if isinstance(vbc, dict):
            for committee_id, comm_data in vbc.items():
                if not isinstance(comm_data, dict):
                    continue
                votes_entry = comm_data.get("votes")
                if not isinstance(votes_entry, dict):
                    continue
                module = votes_entry.get("module")
                if not module:
                    continue
                result_json = (
                    json.dumps(votes_entry["result"])
                    if isinstance(votes_entry.get("result"), dict)
                    else None
                )
                db._conn.execute(
                    "INSERT OR REPLACE INTO bill_votes_by_committee"
                    " (bill_id, committee_id, module, confirmed, result_json, updated_at)"
                    " VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        bill_id,
                        committee_id,
                        module,
                        int(bool(votes_entry.get("confirmed"))),
                        result_json,
                        votes_entry.get("updated_at", ""),
                    ),
                )

    counts["bill_parsers"] = n_bills
    if verbose:
        print(f"  Migrated {n_bills} bill entries")

    # --- committee_contacts ---
    for committee_id, contact in data.get("committee_contacts", {}).items():
        if not isinstance(contact, dict):
            continue
        updated_at = contact.get("updated_at", "")
        db._conn.execute(
            "INSERT OR REPLACE INTO committee_contacts"
            " (committee_id, contact_json, updated_at) VALUES(?, ?, ?)",
            (committee_id, json.dumps(contact), updated_at),
        )
    counts["committee_contacts"] = len(data.get("committee_contacts", {}))

    # --- committee_bills ---
    n_cb = 0
    for committee_id, cb_data in data.get("committee_bills", {}).items():
        if not isinstance(cb_data, dict):
            continue
        bills = cb_data.get("bills", [])
        if isinstance(bills, dict):
            bills = list(bills.keys())
        for bill_id in bills:
            db._conn.execute(
                "INSERT OR IGNORE INTO committee_bills(committee_id, bill_id)"
                " VALUES(?, ?)",
                (committee_id, bill_id),
            )
            n_cb += 1
    counts["committee_bills"] = n_cb

    # --- committee_parsers ---
    n_cp = 0
    for committee_id, cid_data in data.get("committee_parsers", {}).items():
        if not isinstance(cid_data, dict):
            continue
        for parser_type, ptype_data in cid_data.items():
            if not isinstance(ptype_data, dict) or parser_type.endswith("_last_parser"):
                continue
            last_parser_key = f"{parser_type}_last_parser"
            last_parser = cid_data.get(last_parser_key)
            for module_name, stats in ptype_data.items():
                if not isinstance(stats, dict):
                    continue
                is_last = int(module_name == last_parser)
                db._conn.execute(
                    "INSERT OR REPLACE INTO committee_parsers"
                    " (committee_id, parser_type, module_name, count, current_streak,"
                    "  first_seen, last_used, is_last_parser)"
                    " VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        committee_id,
                        parser_type,
                        module_name,
                        stats.get("count", 0),
                        stats.get("current_streak", 0),
                        stats.get("first_seen", ""),
                        stats.get("last_used", ""),
                        is_last,
                    ),
                )
                n_cp += 1
    counts["committee_parsers"] = n_cp

    # --- document_cache ---
    doc_cache = data.get("document_cache", {})
    by_url = doc_cache.get("by_url", {})
    n_docs = 0
    for url, entry in by_url.items():
        if not isinstance(entry, dict):
            continue
        bill_ids = entry.get("bill_ids", [])
        if isinstance(bill_ids, dict):
            bill_ids = list(bill_ids.keys())
        db._docs_conn.execute(
            "INSERT OR REPLACE INTO document_cache"
            " (url, content_hash, content_type, file_size_bytes, cached_file_path,"
            "  first_downloaded, last_accessed, last_validated, access_count,"
            "  etag, last_modified, bill_ids_json, document_purpose)"
            " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                entry.get("content_hash", ""),
                entry.get("content_type"),
                entry.get("file_size_bytes"),
                entry.get("cached_file_path"),
                entry.get("first_downloaded"),
                entry.get("last_accessed"),
                entry.get("last_validated"),
                entry.get("access_count", 0),
                entry.get("etag"),
                entry.get("last_modified"),
                json.dumps(bill_ids),
                entry.get("document_purpose"),
            ),
        )
        n_docs += 1
    counts["document_cache"] = n_docs
    if verbose:
        print(f"  Migrated {n_docs} document cache entries")

    # Commit both transactions, then rebuild the in-memory membership cache
    db._conn.execute("COMMIT")
    db._docs_conn.execute("COMMIT")
    db._load_committee_bills_cache()

    print("Migration complete.")
    print(f"  session             : {counts.get('session', 0)}")
    print(f"  bill entries        : {counts.get('bill_parsers', 0)}")
    print(f"  committee contacts  : {counts.get('committee_contacts', 0)}")
    print(f"  committee-bill links: {counts.get('committee_bills', 0)}")
    print(f"  committee parsers   : {counts.get('committee_parsers', 0)}")
    print(f"  document cache      : {counts.get('document_cache', 0)}")
    print(f"\nOutput: {db_path}  ({db_path.stat().st_size // 1024} KB)")
    print(f"        {docs_db_path}  ({docs_db_path.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        default=str(REPO_ROOT / "cache" / "cache.json"),
        help="Path to source cache.json (default: cache/cache.json)",
    )
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "cache" / "cache.db"),
        help="Path for cache.db output (default: cache/cache.db)",
    )
    parser.add_argument(
        "--docs-db",
        default=str(REPO_ROOT / "cache" / "docs.db"),
        help="Path for docs.db output (default: cache/docs.db)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"Error: {json_path} not found.", file=sys.stderr)
        sys.exit(1)

    migrate(
        json_path=json_path,
        db_path=Path(args.db),
        docs_db_path=Path(args.docs_db),
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
