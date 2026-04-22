#!/usr/bin/env python3
"""Prune specific axes from a bill's entry in cache/cache.json.

Useful for resetting incorrectly attributed documents so the next run
can re-discover the correct parser.
"""
import argparse
import json
import sys
from pathlib import Path


def show_entry(slot: dict, bill_id: str) -> None:
    if not slot:
        print(f"  (no cache entry for {bill_id})")
        return
    for key, val in slot.items():
        if isinstance(val, dict) and "module" in val:
            flag = "confirmed" if val.get("confirmed") else "unconfirmed"
            print(f"  {key}: {val['module']} ({flag})")
        elif key == "votes_by_committee" and isinstance(val, dict):
            for comm_id, comm_data in val.items():
                ventry = comm_data.get("votes", {}) if isinstance(comm_data, dict) else {}
                flag = "confirmed" if ventry.get("confirmed") else "unconfirmed"
                print(f"  votes_by_committee[{comm_id}]: {ventry.get('module', '?')} ({flag})")
        else:
            print(f"  {key}: {val!r}")


def clear_axes(slot: dict, axes: set, votes_committee: str | None) -> list[str]:
    cleared = []
    for axis in sorted(axes):
        if axis == "summary":
            if "summary" in slot:
                del slot["summary"]
                cleared.append("summary")
        elif axis == "votes":
            if votes_committee:
                vbc = slot.get("votes_by_committee", {})
                if votes_committee in vbc:
                    del vbc[votes_committee]
                    cleared.append(f"votes_by_committee[{votes_committee}]")
                    if not vbc:
                        del slot["votes_by_committee"]
            else:
                for key in ("votes", "votes_by_committee"):
                    if key in slot:
                        del slot[key]
                        cleared.append(key)
        elif axis == "extensions" and "extensions" in slot:
            del slot["extensions"]
            cleared.append("extensions")
        elif axis == "hearing" and "hearing_announcement" in slot:
            del slot["hearing_announcement"]
            cleared.append("hearing_announcement")
        elif axis == "title" and "title" in slot:
            del slot["title"]
            cleared.append("title")
        elif axis == "bill_url" and "bill_url" in slot:
            del slot["bill_url"]
            cleared.append("bill_url")
    return cleared


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune a bill's cache entry on specific axes so the next run re-discovers it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
axes:
  --summary          parser + result for the committee report/summary
  --votes            votes parser + result (all committees, or one with --votes-committee)
  --votes-committee  restrict --votes to a single committee slot (e.g. J37)
  --extensions       extension order data
  --hearing          hearing announcement date data
  --title            cached bill title
  --bill-url         cached bill page URL
  --all              remove the entire bill entry

examples:
  python tools/cache_prune.py H1234 --summary
  python tools/cache_prune.py H1234 --votes
  python tools/cache_prune.py H1234 --votes --votes-committee J37
  python tools/cache_prune.py H1234 --summary --votes --yes
  python tools/cache_prune.py H1234 --all
""",
    )
    parser.add_argument("bill_id", help="Bill ID (e.g. H1234 or S567)")
    parser.add_argument("--summary", action="store_true", help="Clear summary parser/result")
    parser.add_argument("--votes", action="store_true", help="Clear votes parser/result")
    parser.add_argument(
        "--votes-committee",
        metavar="COMMITTEE_ID",
        help="With --votes: restrict clearing to one committee's slot",
    )
    parser.add_argument("--extensions", action="store_true", help="Clear extension data")
    parser.add_argument("--hearing", action="store_true", help="Clear hearing announcement data")
    parser.add_argument("--title", action="store_true", help="Clear cached title")
    parser.add_argument("--bill-url", action="store_true", help="Clear cached bill URL")
    parser.add_argument(
        "--all",
        dest="clear_all",
        action="store_true",
        help="Remove the entire bill entry from the cache",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--cache",
        default="cache/cache.json",
        metavar="PATH",
        help="Path to cache file (default: cache/cache.json)",
    )
    args = parser.parse_args()

    axes: set = set()
    if args.clear_all:
        axes.add("all")
    else:
        if args.summary:
            axes.add("summary")
        if args.votes:
            axes.add("votes")
        if args.extensions:
            axes.add("extensions")
        if args.hearing:
            axes.add("hearing")
        if args.title:
            axes.add("title")
        if args.bill_url:
            axes.add("bill_url")

    if not axes:
        parser.error(
            "Specify at least one axis to clear: "
            "--summary --votes --extensions --hearing --title --bill-url --all"
        )

    cache_path = Path(args.cache)
    if not cache_path.exists():
        print(f"Cache not found: {cache_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(cache_path.read_text(encoding="utf-8"))
    bill_id = args.bill_id.upper()
    bill_parsers: dict = data.setdefault("bill_parsers", {})

    print(f"\nCurrent cache entry for {bill_id}:")
    show_entry(bill_parsers.get(bill_id, {}), bill_id)

    if "all" in axes:
        axes_desc = "entire entry"
    else:
        axes_desc = ", ".join(sorted(axes))
        if args.votes_committee and "votes" in axes:
            axes_desc += f" (votes restricted to committee {args.votes_committee})"

    if not args.yes:
        confirm = input(f"\nClear {axes_desc} for {bill_id}? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    if "all" in axes:
        if bill_id in bill_parsers:
            del bill_parsers[bill_id]
            cleared = ["entire entry"]
        else:
            cleared = []
    else:
        slot = bill_parsers.get(bill_id)
        if slot is None:
            print(f"\nNothing to clear — {bill_id} has no cache entry.")
            sys.exit(0)
        cleared = clear_axes(slot, axes, args.votes_committee)

    if not cleared:
        print("\nNothing was cleared (none of the requested keys were present).")
        sys.exit(0)

    cache_path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    print(f"\nCleared: {', '.join(cleared)}")
    print(f"\nRemaining cache entry for {bill_id}:")
    show_entry(bill_parsers.get(bill_id, {}), bill_id)


if __name__ == "__main__":
    main()
