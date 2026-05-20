"""Utility functions for the Massachusetts Legislature website."""

from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from enum import IntEnum
import json
import logging
from pathlib import Path
import re
import textwrap
import tkinter as tk
from tkinter import messagebox, scrolledtext
from typing import Optional, Any, Literal
import webbrowser
from zoneinfo import ZoneInfo

from components.llm import LLMParser
from components.interfaces import Config
from collectors.extension_orders import collect_all_extension_orders
from version import __version__

from components.cache import CacheDB as Cache  # noqa: E402 -- re-exported

logger = logging.getLogger(__name__)


_DEFAULT_PATH = Path("cache/cache.db")
SESSION_WEDNESDAY_DEADLINES: defaultdict[Optional[str], date] = defaultdict(
    lambda: date(2025, 12, 3)
)
SESSION_WEDNESDAY_DEADLINES["194"] = date(2025, 12, 3)


def extract_session_from_bill_url(bill_url: str) -> Optional[str]:
    """Extract session number from a bill URL.

    Args:
        bill_url: URL like "https://malegislature.gov/Bills/194/H73"

    Returns:
        Session number as string (e.g., "194") or None if not found
    """
    match = re.search(r"/Bills/(\d+)/(?:H|S)\d+", bill_url, re.I)
    if match:
        return match.group(1)
    return None


class TimeInterval(IntEnum):
    """Time intervals for compliance delta calculations."""

    DAILY = 1
    WEEKLY = 7
    MONTHLY = 30


def compute_deadlines(
    hearing_date: Optional[date],
    extension_until: Optional[date] = None,
    bill_id: Optional[str] = None,
    session: Optional[str] = None,
    referred_date: Optional[date] = None,
    committee_id: Optional[str] = None,
) -> tuple[Optional[date], Optional[date], Optional[date]]:
    """Return (deadline_60, deadline_90, effective_deadline).

    Args:
        hearing_date: Date of the hearing (None if no hearing scheduled)
        extension_until: Optional extension date
        bill_id: Bill identifier (e.g., "H73", "S197") - used to determine
                 if Senate bill rules apply
        session: Optional session number (e.g., "194") - used to look up
                 session-specific Wednesday deadlines
        referred_date: Date bill was referred to committee (for Senate bill
                       referral-based deadlines per Joint Rule 10)
        committee_id: Committee identifier (e.g., "J33") - used to determine
                      if joint committee rules apply

    Returns:
        Tuple of (deadline_60, deadline_90, effective_deadline)
        Returns (None, None, None) if no hearing_date provided

    Rules:
        - House bills: 60 days from hearing + optional 30-day extension
          (90 max, capped at March deadline for late-session hearings)
        - Senate bills in joint committees (Joint Rule 10):
          * Referred before Oct 1: First Wednesday in December deadline
          * Referred on/after Oct 1: 60 days from referral date
        - Senate bills in other committees: Session-specific Wednesday deadline
    """
    if hearing_date is None:
        return None, None, None
    is_house_bill = bill_id and bill_id.upper().startswith("H")
    if is_house_bill:
        from components.ruleset import Constants194

        c = Constants194()
        d60 = hearing_date + timedelta(days=60)
        d90 = hearing_date + timedelta(days=90)
        if hearing_date >= c.third_wednesday_december:
            if d90 > c.third_wednesday_march:
                d90 = c.third_wednesday_march
    else:
        from components.ruleset import Constants194

        c = Constants194()
        if committee_id == "J24":
            if referred_date and referred_date < c.hcf_december_deadline:
                d60 = c.last_wednesday_january
                d90 = d60
            elif referred_date:
                d60 = referred_date + timedelta(days=60)
                d90 = d60
            else:
                d60 = c.last_wednesday_january
                d90 = d60
        else:
            is_joint_committee = committee_id and committee_id.upper().startswith("J")
            if is_joint_committee and referred_date:
                if referred_date >= c.senate_october_deadline:
                    d60 = referred_date + timedelta(days=60)
                    d90 = d60
                else:
                    d60 = SESSION_WEDNESDAY_DEADLINES[session]
                    d90 = d60 + timedelta(days=30)
            else:
                d60 = SESSION_WEDNESDAY_DEADLINES[session]
                d90 = d60 + timedelta(days=30)
    if not extension_until:
        return d60, d90, d60
    is_hcf_committee = committee_id == "J24"
    if is_hcf_committee:
        return d60, d90, d60
    if is_house_bill:
        effective = min(extension_until, d90)
        effective = max(effective, d60)
    else:
        effective = max(extension_until, d60)
    return d60, d90, effective


def ask_yes_no(
    prompt: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
) -> bool:
    """
    Pop a minimal Tkinter yes/no dialog.
    Returns True for Yes, False for No. If Tkinter is unavailable (headless),
    we default to True but expect the caller to mark needs_review=True.
    """
    if bill_id:
        context = f"Looking for: {doc_type.title()} -- For bill: {bill_id}\n\n"
    else:
        context = f"Looking for: {doc_type.title()}\n\n"
    text = context + (prompt if not url else f"{prompt}\n\n{url}")
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        result = messagebox.askyesno(f"Confirm {doc_type} match", text)
        root.destroy()
        return bool(result)
    except Exception:  # pylint: disable=broad-exception-caught
        return True


def ask_yes_no_console(
    prompt: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
) -> bool:
    """
    Console-based yes/no confirmation dialog.
    Returns True for Yes, False for No.
    """
    header = "=" * 64
    if bill_id:
        title = f"PARSER CONFIRMATION - Bill {bill_id}"
    else:
        title = "PARSER CONFIRMATION"
    print(f"\n{header}")
    print(f"{title}")
    print(f"{header}")
    print(f"Looking for: {doc_type.title()}")
    print()
    print(prompt)
    if url:
        print(f"\nURL: {url}")
    print(f"{header}")
    while True:
        try:
            choice = input("Use this? (y/n): ").strip().lower()
            if choice in ["y", "yes"]:
                return True
            elif choice in ["n", "no"]:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False


def ask_yes_no_with_preview_console(
    title: str,
    heading: str,
    preview_text: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
) -> bool:
    """
    Console-based yes/no confirmation with text preview.
    """
    header = "=" * 64
    if bill_id:
        full_title = f"PARSER CONFIRMATION - Bill {bill_id}"
    else:
        full_title = title
    print(f"\n{header}")
    print(f"{full_title}")
    print(f"{header}")
    print(f"Looking for: {doc_type.title()}")
    print()
    print(heading)
    if url:
        print(f"\nURL: {url}")
    print("\nPreview:")
    print("-" * 64)
    wrapped_lines = []
    for line in preview_text.split("\n"):
        if line.strip():
            wrapped_lines.extend(textwrap.wrap(line, width=80))
        else:
            wrapped_lines.append("")
    display_lines = wrapped_lines[:20]
    for line in display_lines:
        print(line)
    if len(wrapped_lines) > 20:
        print(f"\n... ({len(wrapped_lines) - 20} more lines)")
    print("-" * 64)
    print(f"{header}")
    while True:
        try:
            choice = input("Use this? (y/n): ").strip().lower()
            if choice in ["y", "yes"]:
                return True
            elif choice in ["n", "no"]:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False


def ask_llm_decision(
    content: str, doc_type: str, bill_id: str, config: Config
) -> Optional[Literal["yes", "no", "unsure"]]:
    """
    Ask LLM to make a decision about document matching.

    Args:
        content: The content string to analyze
        doc_type: Type of document (e.g., "summary", "vote record")
        bill_id: The bill ID
        config: Configuration dictionary containing LLM settings

    Returns:
        "yes", "no", "unsure", or None if LLM is unavailable
    """
    # Always create parser if audit logging is enabled, even if LLM is disabled
    if config.llm.enabled:
        llm_parser = LLMParser(config)
        if llm_parser is None:
            return None
        return llm_parser.make_decision(content, doc_type, bill_id)
    return None


def ask_yes_no_with_llm_fallback(
    prompt: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
    config: Optional[Config] = None,
) -> bool:
    """
    Ask for yes/no confirmation with LLM fallback.

    First tries to use LLM if enabled and available.
    If LLM returns "unsure", "no", or is unavailable (None),
    falls back to human dialog.  # noqa: E501

    Args:
        prompt: The prompt text to show
        url: Optional URL to display
        doc_type: Type of document (e.g., "summary", "vote record")
        bill_id: The bill ID
        config: Configuration dictionary containing LLM settings

    Returns:
        True for Yes, False for No
    """
    if config and bill_id:
        content = prompt if not url else f"{prompt}\n\n{url}"
        llm_decision = ask_llm_decision(content, doc_type, bill_id, config)
        if llm_decision == "yes":
            return True
        if llm_decision == "no":
            return False
        if llm_decision in ["unsure", None]:
            if llm_decision is None:
                print(
                    f"LLM unavailable for {doc_type} {bill_id}, "
                    "falling back to manual review"
                )
            use_popups = config.popup_review
            if use_popups:
                return ask_yes_no(prompt, url, doc_type, bill_id)
            else:
                return ask_yes_no_console(prompt, url, doc_type, bill_id)
    use_popups = config.popup_review if config else True
    if use_popups:
        return ask_yes_no(prompt, url, doc_type, bill_id)
    else:
        return ask_yes_no_console(prompt, url, doc_type, bill_id)


# pylint: disable=too-many-positional-arguments
def ask_yes_no_with_preview_and_llm_fallback(
    title: str,
    heading: str,
    preview_text: str,
    url: str | None = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
    config: Optional[Config] = None,
) -> bool:
    """
    Ask for yes/no confirmation with preview and LLM fallback.

    First tries to use LLM if enabled and available.
    If LLM returns "unsure", "no", or is unavailable (None),
    falls back to human dialog.  # noqa: E501

    Args:
        title: Dialog title
        heading: Dialog heading text
        preview_text: Text content to preview
        url: Optional URL to display
        doc_type: Type of document (e.g., "summary", "vote record")
        bill_id: The bill ID
        config: Configuration dictionary containing LLM settings

    Returns:
        True for Yes, False for No
    """
    if config and bill_id:
        content = preview_text
        llm_decision = ask_llm_decision(content, doc_type, bill_id, config)
        if llm_decision == "yes":
            return True
        if llm_decision == "no":
            return False
        # For "unsure", or None (unavailable), fall back to manual review
        if llm_decision in ["unsure", None]:
            if llm_decision is None:
                print(
                    f"LLM unavailable for {doc_type} {bill_id}, "
                    "falling back to manual review"
                )
            # Route to appropriate UI based on popup_review setting
            use_popups = config.popup_review
            if use_popups:
                return ask_yes_no_with_preview(
                    title, heading, preview_text, url, doc_type, bill_id
                )
            else:
                return ask_yes_no_with_preview_console(
                    title, heading, preview_text, url, doc_type, bill_id
                )
    use_popups = config.popup_review if config else True
    if use_popups:
        return ask_yes_no_with_preview(
            title, heading, preview_text, url, doc_type, bill_id
        )
    else:
        return ask_yes_no_with_preview_console(
            title, heading, preview_text, url, doc_type, bill_id
        )


def ask_yes_no_with_preview(
    title: str,
    heading: str,
    preview_text: str,
    url: str | None = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
) -> bool:
    """
    Ask for yes/no confirmation with preview.

    Args:
        title: Dialog title
        heading: Dialog heading text
        preview_text: Text content to preview
        url: Optional URL to display
        doc_type: Type of document (e.g., "summary", "vote record")
        bill_id: The bill ID
    """
    try:
        root = tk.Tk()
        root.title(title)
        root.geometry("680x420")
        root.attributes("-topmost", True)
        frm = tk.Frame(root, padx=10, pady=10)
        frm.pack(fill="both", expand=True)
        if bill_id:
            context_text = f"Looking for: {doc_type.title()} -- For bill: {bill_id}"
        else:
            context_text = f"Looking for: {doc_type.title()}"
        context_label = tk.Label(
            frm, text=context_text, fg="blue", font=("Arial", 9, "bold")
        )
        context_label.pack(anchor="w", pady=(0, 5))
        lbl = tk.Label(frm, text=heading, anchor="w", justify="left")
        lbl.pack(anchor="w")
        if url:
            link = tk.Label(frm, text=url, fg="blue", cursor="hand2")
            link.pack(anchor="w")

            def _open() -> None:
                """Open the URL in the default web browser."""
                webbrowser.open(url)

            link.bind("<Button-1>", lambda e: _open())
        txt = scrolledtext.ScrolledText(frm, wrap="word", height=16)
        txt.insert("1.0", preview_text)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, pady=(8, 8))
        btns = tk.Frame(frm)
        btns.pack(anchor="e")
        res = {"ok": False}
        tk.Button(
            btns,
            text="No",
            width=10,
            command=lambda: (res.update(ok=False), root.destroy()),  # type: ignore
        ).pack(side="right", padx=6)
        tk.Button(
            btns,
            text="Yes",
            width=10,
            command=lambda: (res.update(ok=True), root.destroy()),  # type: ignore
        ).pack(side="right")
        root.mainloop()
        return res["ok"]
    except Exception:  # pylint: disable=broad-exception-caught
        return True


# Extension Order Functions (with caching)


def get_extension_orders_for_bill(
    bill_id: str, cache: Optional[Cache] = None
) -> list[dict]:
    """Get extension orders for a specific bill, using cache if available."""
    # Check cache first if provided
    if cache:
        cached_extension = cache.get_extension(bill_id)
        if cached_extension:
            return [
                {
                    "bill_id": bill_id,
                    "extension_date": cached_extension["extension_date"],
                    "extension_order_url": cached_extension["extension_url"],
                    "cached": True,
                }
            ]

    # Scrape all extension orders and find ones for this bill
    extension_orders = collect_all_extension_orders("https://malegislature.gov", cache)

    # Filter for this specific bill
    bill_extensions = []
    for eo in extension_orders:
        if eo.bill_id == bill_id:
            bill_extensions.append(
                {
                    "bill_id": eo.bill_id,
                    "committee_id": eo.committee_id,
                    "extension_date": eo.extension_date.isoformat(),
                    "extension_order_url": eo.extension_order_url,
                    "order_type": eo.order_type,
                    "discovered_at": eo.discovered_at.isoformat(),
                }
            )

    # Extensions are now cached immediately during collection,
    # so no need to cache here

    return bill_extensions


def get_latest_extension_date(
    bill_id: str, cache: Optional[Cache] = None
) -> Optional[date]:
    """Get the latest extension date for a specific bill."""
    extensions = get_extension_orders_for_bill(bill_id, cache)
    if not extensions:
        return None

    # Find the latest extension date
    latest_date = None
    for ext in extensions:
        try:
            ext_date = datetime.fromisoformat(ext["extension_date"]).date()
            if latest_date is None or ext_date > latest_date:
                latest_date = ext_date
        except (ValueError, KeyError):
            continue

    return latest_date


def get_extension_order_url(
    bill_id: str, cache: Optional[Cache] = None
) -> Optional[str]:
    """Get the URL of the latest extension order for a specific bill."""
    extensions = get_extension_orders_for_bill(bill_id, cache)
    if not extensions:
        return None

    # Find the latest extension order URL
    latest_date = None
    latest_url = None
    for ext in extensions:
        try:
            ext_date = datetime.fromisoformat(ext["extension_date"]).date()
            if latest_date is None or ext_date > latest_date:
                latest_date = ext_date
                latest_url = ext.get("extension_order_url")
        except (ValueError, KeyError):
            continue

    return latest_url


def parse_changelog(changelog_path: str = "CHANGELOG.md") -> dict[str, Any]:
    """
    Parse the CHANGELOG.md file and return structured data.

    Args:
        changelog_path: Path to the CHANGELOG.md file

    Returns:
        Dictionary containing:
        - current_version: The latest version number
        - changelog: List of version entries with changes

    Raises:
        FileNotFoundError: If CHANGELOG.md doesn't exist
    """
    changelog_file = Path(changelog_path)
    if not changelog_file.exists():
        raise FileNotFoundError(f"Changelog not found at {changelog_path}")

    content = changelog_file.read_text(encoding="utf-8")

    # Parse changelog entries
    # Pattern matches: ## [VERSION] - DATE
    version_pattern = r"## \[([^\]]+)\] - (\d{4}-\d{2}-\d{2})"

    versions = []
    current_version = None

    # Split content by version headers
    sections = re.split(version_pattern, content)

    # sections[0] is the header text before first version
    # Then it alternates: version, date, content, version, date, content, ...
    for i in range(1, len(sections), 3):
        if i + 2 <= len(sections):
            version = sections[i]
            release_date = sections[i + 1]
            changes_text = sections[i + 2]

            # Set current_version to the first (most recent) version
            if current_version is None:
                current_version = version

            # Parse the changes by category
            changes = parse_changelog_section(changes_text)

            versions.append(
                {"version": version, "date": release_date, "changes": changes}
            )

    return {"current_version": current_version or __version__, "changelog": versions}


def parse_changelog_section(section_text: str) -> dict[str, list[str]]:
    """
    Parse a changelog section to extract categorized changes.

    Args:
        section_text: The text content of a version section

    Returns:
        Dictionary with categories (added, changed, fixed, etc.) as keys
        and lists of change items as values
    """
    changes: dict[str, list[str]] = {}

    # Pattern matches: ### Category (Added, Changed, Fixed, etc.)
    category_pattern = r"### ([A-Z][a-z]+)"

    # Split by category headers
    parts = re.split(category_pattern, section_text)

    # parts[0] is any text before first category
    # Then it alternates: category, content, category, content, ...
    for i in range(1, len(parts), 2):
        if i + 1 <= len(parts):
            category = parts[i].lower()
            content = parts[i + 1].strip()

            # Extract bullet points (lines starting with -)
            items = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("-"):
                    # Remove the leading dash and whitespace
                    item = line[1:].strip()
                    if item:
                        items.append(item)

            if items:
                changes[category] = items

    return changes


def get_date_output_dir(base_dir: str = "out") -> Path:
    """Get the date-based output directory path for today (Boston time).

    Creates a path in the format: out/YYYY/MM/DD

    Args:
        base_dir: Base directory name (default: "out")

    Returns:
        Path object pointing to the date-based output directory
    """
    # Get current date in Boston timezone
    # US/Eastern handles EST/EDT automatically
    boston_tz = ZoneInfo("US/Eastern")
    today = datetime.now(boston_tz).date()

    # Create path: out/YYYY/MM/DD
    outdir = (
        Path(base_dir) / str(today.year) / f"{today.month:02d}" / f"{today.day:02d}"
    )
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def get_latest_output_dir(base_dir: str = "out") -> Optional[Path]:
    """Find the most recent date-based output directory.

    Scans the base directory structure (out/YYYY/MM/DD) and returns
    the path to the most recent date folder.

    Args:
        base_dir: Base directory name (default: "out")

    Returns:
        Path to the latest date directory, or None if no dirs exist
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return None

    latest_date = None
    latest_path = None

    # Scan for year directories
    for year_dir in base_path.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue

        try:
            year = int(year_dir.name)
        except ValueError:
            continue

        # Scan for month directories
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue

            try:
                month = int(month_dir.name)
            except ValueError:
                continue

            # Scan for day directories
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue

                try:
                    day = int(day_dir.name)
                    # Create date object for comparison
                    dir_date = date(year, month, day)

                    # Check if this is the latest date found so far
                    if latest_date is None or dir_date > latest_date:
                        latest_date = dir_date
                        latest_path = day_dir
                except (ValueError, OverflowError):
                    # Invalid date (e.g., month 13 or day 32)
                    continue

    return latest_path


def get_previous_output_dir(
    base_dir: str = "out", target_days_ago: int = 1
) -> Optional[Path]:
    """Find a date-based output directory closest to the target days ago.

    Similar to get_latest_output_dir, but excludes today's directory.
    Finds the directory closest to (today - target_days_ago).

    Args:
        base_dir: Base directory name (default: "out")
        target_days_ago: Target number of days ago (default: 1 for daily)

    Returns:
        Path to the closest date directory, or None if none exist
    """
    boston_tz = ZoneInfo("US/Eastern")
    today = datetime.now(boston_tz).date()
    target_date = today - timedelta(days=target_days_ago)
    base_path = Path(base_dir)
    if not base_path.exists():
        return None
    best_path = None
    min_days_diff = None
    for year_dir in base_path.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        try:
            year = int(year_dir.name)
        except ValueError:
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            try:
                month = int(month_dir.name)
            except ValueError:
                continue
            for day_dir in month_dir.iterdir():
                if not day_dir.is_dir() or not day_dir.name.isdigit():
                    continue
                try:
                    day = int(day_dir.name)
                    dir_date = date(year, month, day)
                    if dir_date >= today:
                        continue
                    days_diff = abs((target_date - dir_date).days)
                    if min_days_diff is None or days_diff < min_days_diff:
                        min_days_diff = days_diff
                        best_path = day_dir
                except (ValueError, OverflowError):
                    continue
    return best_path


def get_date_from_output_dir(output_dir: Path) -> Optional[date]:
    """Extract the date from an output directory path.

    Args:
        output_dir: Path to a date-based output directory
                   (e.g., Path("out/2025/01/15"))

    Returns:
        Date object, or None if path format is invalid
    """
    try:
        parts = output_dir.parts
        if len(parts) < 3:
            return None
        year = int(parts[-3])
        month = int(parts[-2])
        day = int(parts[-1])
        return date(year, month, day)
    except (ValueError, IndexError):
        pass
    return None


def load_previous_committee_json(
    committee_id: str, base_dir: str = "out", days_ago: int = 1
) -> tuple[Optional[list[dict]], Optional[date]]:
    """Load previous JSON data for a committee from a specific time interval.

    Args:
        committee_id: Committee ID (e.g., "J50")
        base_dir: Base directory name (default: "out")
        days_ago: Number of days ago to look for data (default: 1 for daily)

    Returns:
        Tuple of (list of bill dictionaries, previous date),
        or (None, None) if not found
    """
    previous_dir = get_previous_output_dir(base_dir, target_days_ago=days_ago)
    if previous_dir is None:
        return None, None
    previous_date = get_date_from_output_dir(previous_dir)
    if previous_date is None:
        return None, None
    json_path = previous_dir / f"basic_{committee_id}.json"
    if not json_path.exists():
        return None, previous_date
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Handle both old format (list) and new format
            # (dict with "bills" key)
            if isinstance(data, list):
                # Old format: data is directly a list of bills
                return data, previous_date
            elif isinstance(data, dict) and "bills" in data:
                # New format: data is a dict with "bills" key
                return data["bills"], previous_date
            else:
                # Invalid format
                logger.warning(
                    "Invalid JSON format in %s: expected list or "
                    "dict with 'bills' key",
                    json_path,
                )
                return None, previous_date
    except (json.JSONDecodeError, IOError, KeyError) as e:
        logger.warning("Error loading previous JSON from %s: %s", json_path, e)
        return None, previous_date


def generate_diff_report(
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
    current_date: date,
    previous_date: Optional[date],
) -> Optional[dict]:
    """Generate a diff report comparing current and previous scans.

    Args:
        current_bills: List of current bill dictionaries
        previous_bills: List of previous bill dictionaries (or None)
        current_date: Current scan date
        previous_date: Previous scan date (or None)

    Returns:
        Dictionary with diff report, or None if no previous data
    """
    if previous_bills is None or previous_date is None:
        return None
    # Deduplicate by bill_id (keep last occurrence, matching server behavior)
    current_by_id = {bill["bill_id"]: bill for bill in current_bills}
    previous_by_id = {bill["bill_id"]: bill for bill in previous_bills}

    def count_compliant(bills_dict: dict[str, dict]) -> int:
        """Count compliant bills from deduplicated dictionary."""
        return sum(
            1
            for b in bills_dict.values()
            if b.get("state", "").lower() in ("compliant", "unknown")
        )

    # Count from deduplicated dictionaries, not original lists
    prev_compliant = count_compliant(previous_by_id)
    curr_compliant = count_compliant(current_by_id)
    prev_total = len(previous_by_id)
    curr_total = len(current_by_id)
    # Round compliance rates to 2 decimal places (matching server behavior)
    prev_compliant_pct = round(
        (prev_compliant / prev_total * 100) if prev_total > 0 else 0, 2
    )
    curr_compliant_pct = round(
        (curr_compliant / curr_total * 100) if curr_total > 0 else 0, 2
    )
    # Calculate delta from rounded rates, round to 1 decimal (matching server)
    compliance_delta = round(curr_compliant_pct - prev_compliant_pct, 1)
    new_bill_ids = [
        bill_id for bill_id in current_by_id if bill_id not in previous_by_id
    ]
    bills_with_new_hearings = []
    for bill_id, curr_bill in current_by_id.items():
        if bill_id not in previous_by_id:
            continue
        prev_bill = previous_by_id[bill_id]
        prev_announced = prev_bill.get("announcement_date") is not None
        curr_announced = curr_bill.get("announcement_date") is not None
        if not prev_announced and curr_announced:
            bills_with_new_hearings.append(bill_id)
    bills_reported_out = []
    for bill_id, curr_bill in current_by_id.items():
        if bill_id not in previous_by_id:
            continue
        prev_bill = previous_by_id[bill_id]
        if not prev_bill.get("reported_out", False) and curr_bill.get(
            "reported_out", False
        ):
            bills_reported_out.append(bill_id)
    bills_with_new_summaries = []
    for bill_id, curr_bill in current_by_id.items():
        if bill_id not in previous_by_id:
            continue
        prev_bill = previous_by_id[bill_id]
        if not prev_bill.get("summary_present", False) and curr_bill.get(
            "summary_present", False
        ):
            bills_with_new_summaries.append(bill_id)
    bills_with_new_votes = []
    for bill_id, curr_bill in current_by_id.items():
        if bill_id not in previous_by_id:
            continue
        prev_bill = previous_by_id[bill_id]
        if not prev_bill.get("votes_present", False) and curr_bill.get(
            "votes_present", False
        ):
            bills_with_new_votes.append(bill_id)
    time_delta = current_date - previous_date
    days_ago = time_delta.days
    if days_ago == 1:
        time_interval = "1 day"
    else:
        time_interval = f"{days_ago} days"
    return {
        "time_interval": time_interval,
        "previous_date": str(previous_date),
        "current_date": str(current_date),
        "compliance_delta": compliance_delta,  # Rounded to 1 decimal above
        "new_bills_count": len(new_bill_ids),
        "new_bills": new_bill_ids,
        "bills_with_new_hearings": bills_with_new_hearings,
        "bills_reported_out": bills_reported_out,
        "bills_with_new_summaries": bills_with_new_summaries,
        "bills_with_new_votes": bills_with_new_votes,
    }
