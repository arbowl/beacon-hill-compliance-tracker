"""printout.py — Compliance statistics report from the latest run data.

Prints a formatted summary of violations across all tracked committees:
  1. Hearing notice violations (10-day / 5-day requirement)
  2. Bill summary violations
  3. Committee vote violations + favorable vs. study-order breakdown
  4. Reporting deadline violations (unreported vs. late)

Usage:
    python printout.py              # latest date dir
    python printout.py 2026-04-05   # specific date
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

# ── paths ──────────────────────────────────────────────────────────────────────
OUT_DIR = Path("out")
DB_PATH = Path("bill_artifacts.db")

TODAY_STR = date.today().isoformat()
VIOLATION_STATES = {"Non-Compliant", "Incomplete"}


# ── data loading ───────────────────────────────────────────────────────────────

def find_latest_date_dir() -> tuple[Optional[Path], Optional[date]]:
    """Return (path, date) for the most recent date directory in out/."""
    latest_path: Optional[Path] = None
    latest_date: Optional[date] = None
    for year_dir in sorted(OUT_DIR.iterdir()):
        if not year_dir.is_dir():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir():
                continue
            for day_dir in sorted(month_dir.iterdir()):
                if not day_dir.is_dir():
                    continue
                json_files = list(day_dir.glob("basic_*.json"))
                if not json_files:
                    continue
                # Skip dirs where all JSON files have empty bill lists
                has_bills = any(
                    json.loads(f.read_text()).get("bills")
                    for f in json_files
                )
                if not has_bills:
                    continue
                try:
                    dt = date(int(year_dir.name), int(month_dir.name), int(day_dir.name))
                except ValueError:
                    continue
                if latest_date is None or dt > latest_date:
                    latest_date = dt
                    latest_path = day_dir
    return latest_path, latest_date


def date_dir_for(dt: date) -> Path:
    return OUT_DIR / str(dt.year) / f"{dt.month:02d}" / f"{dt.day:02d}"


def load_committee_names(date_dir: Path) -> dict[str, str]:
    """Extract committee names from HTML files in the date directory."""
    names: dict[str, str] = {}
    for html_file in date_dir.glob("basic_*.html"):
        committee_id = html_file.stem.removeprefix("basic_")
        text = html_file.read_text(encoding="utf-8", errors="ignore")
        # Pattern: >COMMITTEE NAME [J10]</a>
        m = re.search(
            r">([^<]+?)\s*\[" + re.escape(committee_id) + r"\]</a>",
            text,
            re.IGNORECASE,
        )
        names[committee_id] = m.group(1).strip() if m else committee_id
    return names


def load_bills(date_dir: Path) -> list[dict]:
    """Load all bills from JSON files, injecting committee_id into each bill."""
    bills: list[dict] = []
    for json_file in sorted(date_dir.glob("basic_*.json")):
        committee_id = json_file.stem.removeprefix("basic_")
        data = json.loads(json_file.read_text())
        for bill in data.get("bills", []):
            bill["committee_id"] = committee_id
            bills.append(bill)
    return bills


def load_vote_outcomes() -> dict[tuple[str, str], str]:
    """Query bill_artifacts.db for terminal committee action type per (bill_id, committee_id).

    Returns a dict mapping (bill_id, committee_id) -> "Favorable" | "Study Order".

    Replicates the inference logic from collectors/bill_status_basic.py:
    REPORTED/STUDY_ORDER actions without an explicit committee_id are attributed
    to the most recent prior referral's committee.
    """
    if not DB_PATH.exists():
        return {}
    try:
        import duckdb  # type: ignore  # noqa: F401
    except ImportError:
        return {}

    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)

        # Load all relevant timeline actions grouped by artifact
        rows = conn.execute(
            """
            SELECT ba.artifact_id, ba.bill_id, ba.committee_id,
                   ta.action_type, ta.action_date, ta.extracted_data
            FROM bill_artifacts ba
            JOIN timeline_actions ta ON ba.artifact_id = ta.artifact_id
            WHERE ta.action_type IN (
                'REFERRED', 'DISCHARGED',
                'REPORTED', 'STUDY_ORDER', 'ACCOMPANIED'
            )
            ORDER BY ba.artifact_id, ta.action_date
            """
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    TERMINAL = {"REPORTED", "STUDY_ORDER", "ACCOMPANIED"}
    REFERRAL = {"REFERRED", "DISCHARGED"}

    # Group actions by artifact
    from collections import defaultdict as _dd
    by_artifact: dict[str, list] = _dd(list)
    artifact_meta: dict[str, tuple[str, str]] = {}
    for artifact_id, bill_id, committee_id, action_type, action_date, extracted_json in rows:
        try:
            extracted = json.loads(extracted_json) if extracted_json else {}
        except (json.JSONDecodeError, TypeError):
            extracted = {}
        by_artifact[artifact_id].append(
            (action_date, action_type, extracted)
        )
        artifact_meta[artifact_id] = (bill_id, committee_id)

    outcomes: dict[tuple[str, str], str] = {}

    for artifact_id, actions in by_artifact.items():
        bill_id, committee_id = artifact_meta[artifact_id]
        actions_sorted = sorted(actions, key=lambda x: x[0])

        # Find tenure start: first REFERRED/DISCHARGED action for this committee
        tenure_start = None
        for action_date, action_type, extracted in actions_sorted:
            if action_type in REFERRAL and extracted.get("committee_id") == committee_id:
                tenure_start = action_date
                break
        if tenure_start is None:
            continue

        # Find the terminal action for this committee using same inference as collector
        referrals_before = [
            (d, t, e) for d, t, e in actions_sorted
            if t in REFERRAL
        ]
        for action_date, action_type, extracted in actions_sorted:
            if action_type not in TERMINAL:
                continue
            if action_date < tenure_start:
                continue
            action_committee = extracted.get("committee_id")
            if not action_committee:
                # Infer from most recent prior referral
                prior = [(d, t, e) for d, t, e in referrals_before if d < action_date]
                if prior:
                    latest = max(prior, key=lambda x: x[0])
                    action_committee = latest[2].get("committee_id")
            if action_committee == committee_id:
                key = (bill_id, committee_id)
                outcomes[key] = "Favorable" if action_type == "REPORTED" else "Study Order"
                break  # Take the first terminal action after tenure start

    return outcomes


# ── classifiers ────────────────────────────────────────────────────────────────

def bill_chamber(bill_id: str) -> str:
    return "House" if bill_id.upper().startswith("H") else "Senate"


def committee_type(committee_id: str) -> str:
    prefix = committee_id.upper()[0]
    return {"H": "House", "S": "Senate"}.get(prefix, "Joint")


def is_violation(bill: dict) -> bool:
    return bill.get("state") in VIOLATION_STATES


def is_notice_violation(bill: dict) -> bool:
    return bill.get("notice_status") == "Out of range"


def is_summary_violation(bill: dict) -> bool:
    return not bill.get("summary_present") and is_violation(bill)


def is_vote_violation(bill: dict) -> bool:
    return not bill.get("votes_present") and is_violation(bill)


def is_deadline_late(bill: dict) -> bool:
    """Reported out AFTER the effective deadline."""
    rod = bill.get("reported_out_date")
    eff = bill.get("effective_deadline")
    if not rod or not eff:
        return False
    return rod > eff


def is_deadline_unreported(bill: dict) -> bool:
    """Deadline has passed and the bill was never reported out."""
    if bill.get("reported_out"):
        return False
    eff = bill.get("effective_deadline")
    return bool(eff and eff < TODAY_STR and is_violation(bill))


# ── formatting helpers ─────────────────────────────────────────────────────────

def pct(n: int, total: int) -> str:
    if total == 0:
        return "n/a"
    return f"{n / total * 100:.1f}%"


def fmt_committee(committee_id: str, names: dict[str, str]) -> str:
    name = names.get(committee_id, committee_id)
    return f"{committee_id} - {name}" if name != committee_id else committee_id


def print_by_chamber(bills: list[dict]) -> None:
    house = sum(1 for b in bills if bill_chamber(b["bill_id"]) == "House")
    senate = len(bills) - house
    print(f"     House bills:   {house:4d}")
    print(f"     Senate bills:  {senate:4d}")


def print_by_committee(
    bills: list[dict], names: dict[str, str], indent: int = 5
) -> None:
    counts: dict[str, int] = defaultdict(int)
    for b in bills:
        counts[b["committee_id"]] += 1
    pad = " " * indent
    for cid, count in sorted(counts.items(), key=lambda x: -x[1]):
        label = fmt_committee(cid, names)
        print(f"{pad}{count:4d}  {label}")


# ── report sections ────────────────────────────────────────────────────────────

def section_notice(bills: list[dict], names: dict[str, str]) -> None:
    violations = [b for b in bills if is_notice_violation(b)]
    print(f"  Total: {len(violations)} bills\n")

    if not violations:
        return

    print("  By chamber (bill):")
    print_by_chamber(violations)

    # Notice requirement is per committee type (H=0 days, J=10 days, S=5 days)
    by_type: dict[str, list] = defaultdict(list)
    for b in violations:
        by_type[committee_type(b["committee_id"])].append(b)
    print("\n  By committee type:")
    for ctype in ("Joint", "Senate", "House"):
        cnt = len(by_type.get(ctype, []))
        req = {"Joint": "10-day", "Senate": "5-day", "House": "no"}[ctype]
        print(f"     {ctype:7s} ({req} notice requirement):  {cnt:4d}")

    print("\n  By committee:")
    print_by_committee(violations, names)


def section_summaries(bills: list[dict], names: dict[str, str]) -> None:
    violations = [b for b in bills if is_summary_violation(b)]
    print(f"  Total: {len(violations)} bills\n")

    if not violations:
        return

    print("  By chamber (bill):")
    print_by_chamber(violations)

    print("\n  By committee:")
    print_by_committee(violations, names)


def section_votes(
    bills: list[dict], names: dict[str, str], outcomes: dict[tuple, str]
) -> None:
    violations = [b for b in bills if is_vote_violation(b)]
    print(f"  Total: {len(violations)} bills missing vote records\n")

    if violations:
        print("  By chamber (bill):")
        print_by_chamber(violations)
        print("\n  By committee:")
        print_by_committee(violations, names)

    # Outcome breakdown for bills that DO have votes
    with_votes = [b for b in bills if b.get("votes_present")]
    n_favorable = 0
    n_study = 0
    n_unknown = 0
    for b in with_votes:
        key = (b["bill_id"], b["committee_id"])
        outcome = outcomes.get(key)
        if outcome == "Favorable":
            n_favorable += 1
        elif outcome == "Study Order":
            n_study += 1
        else:
            n_unknown += 1

    n_known = n_favorable + n_study
    print(f"\n  Vote outcomes ({len(with_votes)} bills with vote records):")
    print(f"     Favorable (reported out):  {n_favorable:4d}  ({pct(n_favorable, n_known)} of classified)")
    print(f"     Study Order / Accompanied: {n_study:4d}  ({pct(n_study, n_known)} of classified)")
    if n_unknown:
        print(f"     Outcome unknown:           {n_unknown:4d}")

    if n_known == 0:
        return

    # Outcome by bill chamber
    print("\n  Vote outcomes by chamber (bill):")
    for chamber in ("House", "Senate"):
        chamber_bills = [b for b in with_votes if bill_chamber(b["bill_id"]) == chamber]
        fav = sum(1 for b in chamber_bills if outcomes.get((b["bill_id"], b["committee_id"])) == "Favorable")
        stu = sum(1 for b in chamber_bills if outcomes.get((b["bill_id"], b["committee_id"])) == "Study Order")
        total = fav + stu
        print(f"     {chamber:7s}: Favorable {fav:4d} ({pct(fav, total)}),  Study Order {stu:4d} ({pct(stu, total)})")


def section_deadlines(bills: list[dict], names: dict[str, str]) -> None:
    late_bills = [b for b in bills if is_deadline_late(b)]
    unreported_bills = [b for b in bills if is_deadline_unreported(b)]
    total = len(late_bills) + len(unreported_bills)

    print(f"  Total: {total} bills\n")
    print(f"  Unreported (deadline passed, no action): {len(unreported_bills):4d}")
    print(f"  Late (reported after deadline):          {len(late_bills):4d}\n")

    if total == 0:
        return

    # By chamber
    print("  By chamber (bill):")
    for chamber in ("House", "Senate"):
        u = sum(1 for b in unreported_bills if bill_chamber(b["bill_id"]) == chamber)
        la = sum(1 for b in late_bills if bill_chamber(b["bill_id"]) == chamber)
        print(f"     {chamber:7s}: {u + la:4d}  ({u} unreported, {la} late)")

    # By committee
    print("\n  By committee:")
    counts: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
    for b in unreported_bills:
        u, la = counts[b["committee_id"]]
        counts[b["committee_id"]] = (u + 1, la)
    for b in late_bills:
        u, la = counts[b["committee_id"]]
        counts[b["committee_id"]] = (u, la + 1)

    pad = "     "
    for cid, (u, la) in sorted(counts.items(), key=lambda x: -(x[1][0] + x[1][1])):
        label = fmt_committee(cid, names)
        detail = f"({u} unreported, {la} late)"
        print(f"{pad}{u + la:4d}  {label}  {detail}")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Resolve date directory
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
            date_dir = date_dir_for(target)
            data_date = target
        except ValueError:
            print(f"Error: invalid date '{sys.argv[1]}' — expected YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        date_dir, data_date = find_latest_date_dir()

    if date_dir is None or not date_dir.exists():
        print("Error: no output data found.", file=sys.stderr)
        sys.exit(1)

    names = load_committee_names(date_dir)
    bills = load_bills(date_dir)
    outcomes = load_vote_outcomes()

    n_committees = len(names)
    n_bills = len(bills)

    divider = "=" * 60
    thin = "-" * 60

    print(f"\n{divider}")
    print("  BEACON HILL COMPLIANCE STATISTICS")
    print(f"  Data date:  {data_date}")
    print(f"  Generated:  {TODAY_STR}")
    print(f"  Scope:      {n_committees} committees, {n_bills} bills")
    print(f"{divider}\n")

    print("1. HEARING NOTICE VIOLATIONS")
    print(thin)
    section_notice(bills, names)

    print(f"\n{thin}\n2. BILL SUMMARY VIOLATIONS")
    print(thin)
    section_summaries(bills, names)

    print(f"\n{thin}\n3. COMMITTEE VOTE VIOLATIONS")
    print(thin)
    section_votes(bills, names, outcomes)

    print(f"\n{thin}\n4. REPORTING DEADLINE VIOLATIONS")
    print(thin)
    section_deadlines(bills, names)

    print(f"\n{divider}\n")


if __name__ == "__main__":
    main()
