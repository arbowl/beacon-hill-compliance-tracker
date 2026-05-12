#!/usr/bin/env python3
"""Write a CSV of unique Senate bills in Joint committees that were reported out
exactly one day late, have "study order" anywhere in their bill history, and
have no votes present.

Output: tools/out/late_study_order.csv

Usage:
    python tools/late_reported_s_bills.py
    python tools/late_reported_s_bills.py --date 2026/04/29
    python tools/late_reported_s_bills.py --outdir /tmp
"""

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"
DB_PATH = REPO_ROOT / "bill_artifacts.db"
DEFAULT_OUTDIR = Path(__file__).resolve().parent / "out"

BILL_URL = "https://malegislature.gov/Bills/194/{bill_id}"

CSV_FIELDS = [
    "bill_id",
    "committee_id",
    "effective_deadline",
    "reported_date",
    "bill_title",
    "bill_url",
]


def find_latest_snapshot_dir() -> Path:
    candidates = sorted(OUT_DIR.rglob("basic_J*.json"))
    if not candidates:
        sys.exit("No Joint committee snapshot files found under out/.")
    return candidates[-1].parent


def load_snapshots(snapshot_dir: Path, glob: str = "basic_J*.json") -> list[dict]:
    """Return flat bill list from snapshot files matching glob in snapshot_dir."""
    bills = []
    for json_file in sorted(snapshot_dir.glob(glob)):
        committee_id = json_file.stem.split("_", 1)[1]
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        raw = data if isinstance(data, list) else data.get("bills", [])
        for bill in raw:
            b = dict(bill)
            b["committee_id"] = committee_id
            bills.append(b)
    return bills


def fetch_terminal_actions() -> dict[tuple[str, str], date]:
    """Return {(bill_id, committee_id): earliest_terminal_action_date} from DB."""
    if not DB_PATH.exists():
        return {}
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    rows = conn.execute("""
        WITH ranked AS (
            SELECT
                ba.bill_id,
                ba.committee_id,
                ta.action_date,
                ROW_NUMBER() OVER (
                    PARTITION BY ba.bill_id, ba.committee_id
                    ORDER BY ta.action_date
                ) AS rn
            FROM timeline_actions ta
            JOIN bill_artifacts ba ON ta.artifact_id = ba.artifact_id
            WHERE ta.action_type IN ('REPORTED', 'STUDY_ORDER', 'ACCOMPANIED')
              AND ba.bill_id LIKE 'S%'
              AND ba.committee_id LIKE 'J%'
        )
        SELECT bill_id, committee_id, action_date
        FROM ranked
        WHERE rn = 1
    """).fetchall()
    conn.close()
    return {(row[0], row[1]): date.fromisoformat(row[2]) for row in rows}


def fetch_study_order_pairs() -> set[tuple[str, str]]:
    """Return (bill_id, committee_id) pairs with 'study order' anywhere in raw history."""
    if not DB_PATH.exists():
        return set()
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    rows = conn.execute("""
        SELECT DISTINCT ba.bill_id, ba.committee_id
        FROM timeline_actions ta
        JOIN bill_artifacts ba ON ta.artifact_id = ba.artifact_id
        WHERE lower(ta.raw_text) LIKE '%study order%'
          AND ba.bill_id LIKE 'S%'
          AND ba.committee_id LIKE 'J%'
    """).fetchall()
    conn.close()
    return {(row[0], row[1]) for row in rows}


def fetch_all_study_order_pairs() -> set[tuple[str, str]]:
    """Return all (bill_id, committee_id) pairs with 'study order' in any raw history text."""
    if not DB_PATH.exists():
        return set()
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    rows = conn.execute("""
        SELECT DISTINCT ba.bill_id, ba.committee_id
        FROM timeline_actions ta
        JOIN bill_artifacts ba ON ta.artifact_id = ba.artifact_id
        WHERE lower(ta.raw_text) LIKE '%study order%'
    """).fetchall()
    conn.close()
    return {(row[0], row[1]) for row in rows}


def fetch_jr10_bills() -> list[dict]:
    """Return all bills with '(under JR10)' in any timeline action, with titles from DB."""
    if not DB_PATH.exists():
        return []
    conn = duckdb.connect(str(DB_PATH), read_only=True)
    rows = conn.execute("""
        SELECT DISTINCT ba.bill_id, ba.committee_id, ba.bill_metadata
        FROM timeline_actions ta
        JOIN bill_artifacts ba ON ta.artifact_id = ba.artifact_id
        WHERE ta.raw_text LIKE '%(under JR10)%'
        ORDER BY ba.bill_id, ba.committee_id
    """).fetchall()
    conn.close()
    results = []
    seen: set[str] = set()
    for bill_id, committee_id, metadata_json in rows:
        if bill_id in seen:
            continue
        seen.add(bill_id)
        meta = json.loads(metadata_json) if metadata_json else {}
        results.append({
            "bill_id": bill_id,
            "committee_id": committee_id,
            "bill_title": meta.get("title", ""),
            "bill_url": BILL_URL.format(bill_id=bill_id),
        })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        metavar="YYYY/MM/DD",
        help="Snapshot date to use (default: latest available)",
    )
    parser.add_argument(
        "--outdir",
        metavar="DIR",
        default=str(DEFAULT_OUTDIR),
        help=f"Directory to write the CSV into (default: {DEFAULT_OUTDIR})",
    )
    args = parser.parse_args()

    if args.date:
        snapshot_dir = OUT_DIR / args.date
        if not snapshot_dir.exists():
            sys.exit(f"Snapshot directory not found: {snapshot_dir}")
    else:
        snapshot_dir = find_latest_snapshot_dir()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"Snapshot: {snapshot_dir.relative_to(REPO_ROOT)}", file=sys.stderr)

    # Candidates: S-bills in Joint committees, reported out, no votes
    candidates: dict[tuple[str, str], dict] = {}
    for bill in load_snapshots(snapshot_dir):
        bill_id = bill.get("bill_id", "")
        committee_id = bill.get("committee_id", "")
        if (
            not bill_id.upper().startswith("S")
            or not bill.get("reported_out")
            or bill.get("votes_present")
            or not bill.get("effective_deadline")
        ):
            continue
        candidates.setdefault((bill_id, committee_id), bill)

    print(f"{len(candidates)} reported-out S-bill/committee pairs (no votes); querying DB...", file=sys.stderr)

    terminal_actions = fetch_terminal_actions()
    study_order_pairs = fetch_study_order_pairs()

    results: list[dict] = []
    seen_bill_ids: set[str] = set()

    for (bill_id, committee_id), bill in sorted(candidates.items()):
        # Must have "study order" in raw history
        if (bill_id, committee_id) not in study_order_pairs:
            continue
        # Must be exactly one day late
        reported_date = terminal_actions.get((bill_id, committee_id))
        if reported_date is None:
            continue
        effective_deadline = date.fromisoformat(bill["effective_deadline"])
        if (reported_date - effective_deadline).days != 1:
            continue
        if bill_id in seen_bill_ids:
            continue
        seen_bill_ids.add(bill_id)
        results.append({
            "bill_id": bill_id,
            "committee_id": committee_id,
            "effective_deadline": bill["effective_deadline"],
            "reported_date": reported_date.isoformat(),
            "bill_title": bill.get("bill_title", ""),
            "bill_url": BILL_URL.format(bill_id=bill_id),
        })

    out_path = outdir / "late_study_order.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    print(f"{len(results):>4} bills  →  {out_path}")

    jr10_fields = ["bill_id", "committee_id", "bill_title", "bill_url"]
    jr10_bills = fetch_jr10_bills()
    jr10_path = outdir / "jr10_bills.csv"
    with jr10_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=jr10_fields)
        writer.writeheader()
        writer.writerows(jr10_bills)
    print(f"{len(jr10_bills):>4} bills  →  {jr10_path}")

    # All bills (any committee) with study order in history and no votes in snapshot
    all_study_order = fetch_all_study_order_pairs()
    no_vote_fields = ["bill_id", "committee_id", "bill_title", "bill_url"]
    no_vote_rows: list[dict] = []
    seen_no_vote: set[str] = set()
    for bill in sorted(load_snapshots(snapshot_dir, glob="basic_*.json"), key=lambda b: b.get("bill_id", "")):
        bill_id = bill.get("bill_id", "")
        committee_id = bill.get("committee_id", "")
        if bill.get("votes_present") or bill_id in seen_no_vote:
            continue
        if (bill_id, committee_id) not in all_study_order:
            continue
        seen_no_vote.add(bill_id)
        no_vote_rows.append({
            "bill_id": bill_id,
            "committee_id": committee_id,
            "bill_title": bill.get("bill_title", ""),
            "bill_url": BILL_URL.format(bill_id=bill_id),
        })
    no_vote_path = outdir / "study_order_no_votes.csv"
    with no_vote_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=no_vote_fields)
        writer.writeheader()
        writer.writerows(no_vote_rows)
    print(f"{len(no_vote_rows):>4} bills  →  {no_vote_path}")


if __name__ == "__main__":
    main()
