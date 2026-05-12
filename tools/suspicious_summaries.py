#!/usr/bin/env python3
"""Scan the cache for suspicious summary URL assignments.

Severity levels
---------------
CRITICAL  Same-type bill ID mismatch in URL (H->H or S->S different number)
HIGH      Cross-type mismatch (H<->S) where URL names a specific other bill
MEDIUM    URL is shared by many bills and looks like a hearing pack that the
          parser grabbed instead of a bill-specific document
LOW       Entry is unconfirmed/needs_review with no other red flag

Usage
-----
    python tools/suspicious_summaries.py
    python tools/suspicious_summaries.py --min-severity high
    python tools/suspicious_summaries.py --committee J24
    python tools/suspicious_summaries.py --csv > report.csv
    python tools/suspicious_summaries.py --fix-script > fixes.sh
"""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "cache" / "cache.json"

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# A URL shared by this many or more bills triggers MEDIUM
SHARED_URL_THRESHOLD = 5

# Regex matching H/S bill IDs: H860, H.860, S 2913
_BILL_RE = re.compile(r"\b([HS])\.?\s*(\d{3,4})\b", re.I)


def normalize(raw: str) -> str:
    m = re.match(r"([HS])\.?\s*(\d+)", raw, re.I)
    return (m.group(1).upper() + m.group(2)) if m else raw.upper()


def bill_ids_in(text: str) -> set[str]:
    return {normalize(m.group(0)) for m in _BILL_RE.finditer(text)}


def is_pack_title(title: str) -> bool:
    """Return True if the URL title looks like a multi-bill hearing pack."""
    low = title.lower()
    pack_signals = ["pack", "summaries", "summary pack", "hearing", "agenda"]
    if any(s in low for s in pack_signals):
        return True
    # Date-only titles like "9.16.25 ..."
    if re.match(r"^\d{1,2}[\.\-]\d{1,2}", title):
        return True
    return False


def extract_title(url: str) -> str:
    """Pull the Title= param from DownloadDocument URLs, or the filename."""
    decoded = unquote(url)
    m = re.search(r"[?&]Title=([^&]+)", decoded)
    if m:
        return m.group(1)
    # Fall back to the last path segment
    return decoded.rsplit("/", 1)[-1].split("?")[0]


@dataclass
class Finding:
    bill_id: str
    severity: str
    reason: str
    detail: str
    url: str
    wrong_ids: list[str] = field(default_factory=list)
    shared_with: list[str] = field(default_factory=list)
    committee_ids: list[str] = field(default_factory=list)


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        sys.exit(f"Cache not found: {CACHE_PATH}")
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def build_bill_to_committees(cache: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for comm_id, data in cache.get("committee_bills", {}).items():
        for bill in data.get("bills", []):
            result[bill].append(comm_id)
    return result


def scan(cache: dict) -> list[Finding]:
    bill_to_comms = build_bill_to_committees(cache)
    bill_parsers = cache.get("bill_parsers", {})

    # First pass: collect URL → [bill_id, ...] for shared-URL detection
    url_to_bills: dict[str, list[str]] = defaultdict(list)
    for bill_id, slot in bill_parsers.items():
        entry = slot.get("summary")
        if not isinstance(entry, dict):
            continue
        url = entry.get("result", {}).get("source_url", "")
        if url:
            url_to_bills[url].append(bill_id)

    findings: list[Finding] = []
    seen_medium_urls: set[str] = set()  # avoid duplicate MEDIUM rows per URL

    for bill_id, slot in bill_parsers.items():
        entry = slot.get("summary")
        if not isinstance(entry, dict):
            continue
        result = entry.get("result", {})
        url = result.get("source_url", "")
        confirmed = entry.get("confirmed", False)
        needs_review = result.get("needs_review", False)
        comms = sorted(bill_to_comms.get(bill_id, []))

        if not url:
            if not confirmed and needs_review:
                findings.append(
                    Finding(
                        bill_id=bill_id,
                        severity="LOW",
                        reason="No URL cached",
                        detail="summary_present=True but source_url is empty",
                        url="",
                        committee_ids=comms,
                    )
                )
            continue

        title = extract_title(url)
        decoded_url = unquote(url)
        found_ids = bill_ids_in(decoded_url)
        norm = normalize(bill_id)
        wrong_ids = sorted(found_ids - {norm})

        if wrong_ids:
            same_type = [w for w in wrong_ids if w[0] == norm[0]]
            cross_type = [w for w in wrong_ids if w[0] != norm[0]]

            if same_type:
                findings.append(
                    Finding(
                        bill_id=bill_id,
                        severity="CRITICAL",
                        reason=f"URL names a different {norm[0]}-bill",
                        detail=f"URL title contains {', '.join(same_type)}, not {norm}",
                        url=url,
                        wrong_ids=same_type,
                        committee_ids=comms,
                    )
                )
            if cross_type:
                findings.append(
                    Finding(
                        bill_id=bill_id,
                        severity="HIGH",
                        reason="URL names companion-type bill",
                        detail=(
                            f"URL title contains {', '.join(cross_type)} "
                            f"(may be companion bill, verify)"
                        ),
                        url=url,
                        wrong_ids=cross_type,
                        committee_ids=comms,
                    )
                )
            # Don't double-count as MEDIUM if already flagged above
            continue

        # No bill-ID mismatch — check for shared hearing-pack URL
        sharers = url_to_bills.get(url, [])
        if len(sharers) >= SHARED_URL_THRESHOLD and url not in seen_medium_urls:
            seen_medium_urls.add(url)
            pack_label = "hearing pack" if is_pack_title(title) else "shared document"
            findings.append(
                Finding(
                    bill_id="(shared)",
                    severity="MEDIUM",
                    reason=f"{pack_label} used by {len(sharers)} bills",
                    detail=f'Title: "{title}"',
                    url=url,
                    shared_with=sharers,
                    committee_ids=sorted({c for b in sharers for c in bill_to_comms.get(b, [])}),
                )
            )
            continue

        # LOW: unconfirmed and needs review
        if not confirmed and needs_review:
            findings.append(
                Finding(
                    bill_id=bill_id,
                    severity="LOW",
                    reason="Unconfirmed / needs review",
                    detail="Auto-accepted in headless mode, never user-validated",
                    url=url,
                    committee_ids=comms,
                )
            )

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.bill_id))
    return findings


def print_text(findings: list[Finding], min_sev: str) -> None:
    cutoff = SEVERITY_ORDER[min_sev.upper()]
    shown = [f for f in findings if SEVERITY_ORDER[f.severity] <= cutoff]

    counts = defaultdict(int)
    for f in shown:
        counts[f.severity] += 1

    print(f"{'='*72}")
    print(f"Suspicious Summary Scan  —  {len(shown)} findings")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if counts[sev]:
            print(f"  {sev}: {counts[sev]}")
    print(f"{'='*72}\n")

    current_sev = None
    for f in shown:
        if f.severity != current_sev:
            current_sev = f.severity
            print(f"── {f.severity} {'─'*(66 - len(f.severity))}")
        if f.bill_id == "(shared)":
            bills_preview = ", ".join(f.shared_with[:6])
            if len(f.shared_with) > 6:
                bills_preview += f", … (+{len(f.shared_with)-6} more)"
            print(f"  [SHARED]  {f.reason}")
            print(f"  Bills:    {bills_preview}")
            print(f"  Detail:   {f.detail}")
        else:
            comms = ", ".join(f.committee_ids) or "?"
            print(f"  {f.bill_id:<10} [{comms}]  {f.reason}")
            if f.wrong_ids:
                print(f"             Clashes with: {', '.join(f.wrong_ids)}")
            print(f"             {f.detail}")
        print(f"             {f.url[:90]}")
        print()


def print_csv(findings: list[Finding], min_sev: str) -> None:
    cutoff = SEVERITY_ORDER[min_sev.upper()]
    shown = [f for f in findings if SEVERITY_ORDER[f.severity] <= cutoff]
    writer = csv.writer(sys.stdout)
    writer.writerow(
        ["severity", "bill_id", "committees", "reason", "detail", "wrong_ids", "url"]
    )
    for f in shown:
        writer.writerow(
            [
                f.severity,
                f.bill_id,
                "|".join(f.committee_ids),
                f.reason,
                f.detail,
                "|".join(f.wrong_ids) if f.wrong_ids else "",
                f.url,
            ]
        )


def print_fix_script(findings: list[Finding], min_sev: str) -> None:
    cutoff = SEVERITY_ORDER[min_sev.upper()]
    shown = [
        f for f in findings
        if SEVERITY_ORDER[f.severity] <= cutoff and f.bill_id != "(shared)"
    ]
    print("#!/usr/bin/env bash")
    print("# Auto-generated by suspicious_summaries.py")
    print("# Fill in the correct --url for each bill, then run.\n")
    for f in shown:
        print(f"# {f.severity}: {f.reason}")
        print(f"# Current URL: {f.url[:100]}")
        if f.wrong_ids:
            print(f"# Clashes with: {', '.join(f.wrong_ids)}")
        print(
            f"python tools/patch_summary.py "
            f"--bill-id {f.bill_id} "
            f'--url "CORRECT_URL_HERE" '
            f"--patch-snapshots"
        )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-severity",
        default="high",
        choices=["critical", "high", "medium", "low"],
        help="Minimum severity to show (default: high)",
    )
    parser.add_argument(
        "--committee",
        help="Filter to a specific committee ID (e.g. J24)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Output as CSV instead of human-readable text",
    )
    parser.add_argument(
        "--fix-script",
        action="store_true",
        help="Output a shell script of patch_summary.py commands",
    )
    args = parser.parse_args()

    cache = load_cache()
    findings = scan(cache)

    if args.committee:
        comm = args.committee.upper()
        findings = [f for f in findings if comm in f.committee_ids or f.bill_id == "(shared)"]

    if args.fix_script:
        print_fix_script(findings, args.min_severity)
    elif args.csv:
        print_csv(findings, args.min_severity)
    else:
        print_text(findings, args.min_severity)


if __name__ == "__main__":
    main()
