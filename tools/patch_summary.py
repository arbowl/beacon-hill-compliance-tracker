#!/usr/bin/env python3
"""Manually override a bill's summary URL in the cache (and optionally
existing snapshots).

Use this when the pipeline found the wrong document — e.g. a different
bill's summary appeared on the same hearing page.

Usage:
    python tools/patch_summary.py --bill-id S860 --url "https://..."
    python tools/patch_summary.py --bill-id S860 --url "https://..." --patch-snapshots
    python tools/patch_summary.py --bill-id S860 --show
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "cache" / "cache.json"
OUT_DIR = REPO_ROOT / "out"

VALID_PARSERS = [
    "parsers.summary_bill_tab_text",
    "parsers.summary_committee_docx",
    "parsers.summary_committee_pdf",
    "parsers.summary_hearing_docs_docx",
    "parsers.summary_hearing_docs_pdf",
    "parsers.summary_hearing_docs_pdf_content",
    "parsers.summary_hearing_pdf",
]

_PARSER_LOCATIONS = {
    "parsers.summary_bill_tab_text": "Bill tab text",
    "parsers.summary_committee_docx": "Committee page DOCX",
    "parsers.summary_committee_pdf": "Committee page PDF",
    "parsers.summary_hearing_docs_docx": "Hearing docs DOCX",
    "parsers.summary_hearing_docs_pdf": "Hearing docs PDF",
    "parsers.summary_hearing_docs_pdf_content": "Hearing docs PDF (content)",
    "parsers.summary_hearing_pdf": "Hearing page PDF",
}


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        sys.exit(f"Cache not found: {CACHE_PATH}")
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def save_cache(data: dict) -> None:
    CACHE_PATH.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


def show_summary(cache: dict, bill_id: str) -> None:
    slot = cache.get("bill_parsers", {}).get(bill_id, {})
    entry = slot.get("summary")
    if not entry:
        print(f"No summary cache entry for {bill_id}.")
        return
    confirmed = "confirmed" if entry.get("confirmed") else "unconfirmed"
    module = entry.get("module", "?")
    result = entry.get("result", {})
    url = result.get("source_url", "(none)")
    print(f"bill_id:    {bill_id}")
    print(f"module:     {module} ({confirmed})")
    print(f"source_url: {url}")
    print(f"updated_at: {entry.get('updated_at', '?')}")


def find_snapshots(bill_id: str) -> list[Path]:
    """Find all snapshot JSON files containing the given bill_id."""
    matches = []
    for json_file in sorted(OUT_DIR.rglob("basic_*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            bills = data if isinstance(data, list) else data.get("bills", [])
            if any(b.get("bill_id") == bill_id for b in bills):
                matches.append(json_file)
        except Exception:
            continue
    return matches


def patch_snapshots(bill_id: str, new_url: str, dry_run: bool) -> int:
    """Update summary_url in all snapshot files containing bill_id.
    Returns the number of files patched.
    """
    files = find_snapshots(bill_id)
    if not files:
        print("No snapshot files found containing this bill.")
        return 0
    patched = 0
    for json_file in files:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        is_list = isinstance(data, list)
        bills = data if is_list else data.get("bills", [])
        changed = False
        for bill in bills:
            if bill.get("bill_id") == bill_id:
                old_url = bill.get("summary_url")
                if old_url != new_url:
                    print(f"  {json_file.relative_to(REPO_ROOT)}")
                    print(f"    old: {old_url}")
                    print(f"    new: {new_url}")
                    if not dry_run:
                        bill["summary_url"] = new_url
                        bill["summary_present"] = True
                    changed = True
        if changed and not dry_run:
            json_file.write_text(
                json.dumps(data if is_list else data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            patched += 1
        elif changed:
            patched += 1
    return patched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bill-id", required=True, help="Bill ID (e.g. S860)")
    parser.add_argument("--url", help="Correct summary URL to store")
    parser.add_argument(
        "--parser",
        default=None,
        help=(
            "Parser module to record (default: keep existing). "
            f"Valid: {', '.join(VALID_PARSERS)}"
        ),
    )
    parser.add_argument(
        "--patch-snapshots",
        action="store_true",
        help="Also update summary_url in all existing snapshot JSON files",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show current cache entry and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing anything",
    )
    args = parser.parse_args()

    cache = load_cache()
    bill_id = args.bill_id

    if args.show:
        show_summary(cache, bill_id)
        return

    if not args.url:
        parser.error("--url is required unless using --show")

    if args.parser and args.parser not in VALID_PARSERS:
        sys.exit(
            f"Unknown parser '{args.parser}'.\nValid options:\n"
            + "\n".join(f"  {p}" for p in VALID_PARSERS)
        )

    slot = cache.setdefault("bill_parsers", {}).setdefault(bill_id, {})
    existing = slot.get("summary", {})
    old_url = existing.get("result", {}).get("source_url", "(none)")
    old_module = existing.get("module", "(none)")

    module = args.parser or old_module or "parsers.summary_hearing_pdf"
    location = _PARSER_LOCATIONS.get(module, "Manual override")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    new_entry = {
        "module": module,
        "confirmed": True,
        "result": {
            "present": True,
            "location": location,
            "needs_review": False,
            "source_url": args.url,
            "parser_module": module,
        },
        "updated_at": now,
    }

    print(f"Bill:       {bill_id}")
    print(f"Old URL:    {old_url}")
    print(f"New URL:    {args.url}")
    print(f"Parser:     {module}")
    print(f"Confirmed:  True")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
    else:
        slot["summary"] = new_entry
        save_cache(cache)
        print("\nCache updated.")

    if args.patch_snapshots:
        print("\nPatching snapshots...")
        n = patch_snapshots(bill_id, args.url, args.dry_run)
        label = "would patch" if args.dry_run else "patched"
        print(f"{n} snapshot file(s) {label}.")


if __name__ == "__main__":
    main()
