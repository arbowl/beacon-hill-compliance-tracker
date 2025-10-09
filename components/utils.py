""" Utility functions for the Massachusetts Legislature website. """

import json
from datetime import date, timedelta, datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, scrolledtext
from typing import Optional, Any, Literal
import webbrowser

import yaml  # type: ignore

from components.llm import create_llm_parser
from collectors.extension_orders import collect_all_extension_orders

DEFAULT_CONFIG = {
    "base_url": "https://malegislature.gov",
    "filters": {"include_chambers": ["House", "Joint"]},
}
_DEFAULT_PATH = Path("cache.json")


class Cache:
    """Cache for the parser results."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self.path = path
        self._data: dict[str, Any] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # pylint: disable=broad-exception-caught
                self._data = {}

    def save(self) -> None:
        """Save the cache to the file."""
        self.path.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )

    def get_parser(self, bill_id: str, kind: str) -> Optional[str]:
        """Return cached module name (or None). Handles old string entries
        gracefully.
        """
        entry = self._slot(bill_id).get(kind)
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("module")
        return None

    def is_confirmed(self, bill_id: str, kind: str) -> bool:
        """Return True if we recorded a user-confirmed parser for this
        bill/kind.
        """
        entry = self._slot(bill_id).get(kind)
        if isinstance(entry, dict):
            return bool(entry.get("confirmed"))
        return False

    def set_parser(
        self, bill_id: str, kind: str, module_name: str, *, confirmed: bool
    ) -> None:
        """Set module + confirmation flag in the new schema."""
        slot = self._slot(bill_id)
        slot[kind] = {
            "module": module_name,
            "confirmed": bool(confirmed),
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    def get_result(self, bill_id: str, kind: str) -> Optional[dict]:
        """Return cached result data for a bill/kind (or None)."""
        entry = self._slot(bill_id).get(kind)
        if isinstance(entry, dict):
            return entry.get("result")
        return None

    def set_result(
        self,
        bill_id: str,
        kind: str,
        module_name: str,
        result_data: dict,
        *,
        confirmed: bool
    ) -> None:
        """Set result data + module + confirmation flag in the new schema."""
        slot = self._slot(bill_id)
        slot[kind] = {
            "module": module_name,
            "confirmed": bool(confirmed),
            "result": result_data,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    def _slot(self, bill_id: str) -> dict[str, Any]:
        return self._data.setdefault(
            "bill_parsers", {}
        ).setdefault(bill_id, {})

    def get_extension(self, bill_id: str) -> Optional[dict]:
        """Return cached extension data for a bill (or None)."""
        entry = self._slot(bill_id).get("extensions")
        if isinstance(entry, dict):
            return entry
        return None

    def set_extension(
        self, bill_id: str, extension_date: str, extension_url: str
    ) -> None:
        """Set extension data for a bill."""
        slot = self._slot(bill_id)
        slot["extensions"] = {
            "extension_date": extension_date,
            "extension_url": extension_url,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    def get_hearing_announcement(self, bill_id: str) -> Optional[dict]:
        """Return cached hearing announcement data for a bill (or None)."""
        entry = self._slot(bill_id).get("hearing_announcement")
        if isinstance(entry, dict):
            return entry
        return None

    def set_hearing_announcement(
        self, 
        bill_id: str, 
        announcement_date: Optional[str], 
        scheduled_hearing_date: Optional[str],
        bill_url: Optional[str] = None
    ) -> None:
        """Set hearing announcement data for a bill."""
        slot = self._slot(bill_id)
        
        # Set bill_url as top-level field if provided
        if bill_url:
            slot["bill_url"] = bill_url
            
        slot["hearing_announcement"] = {
            "announcement_date": announcement_date,
            "scheduled_hearing_date": scheduled_hearing_date,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    def clear_hearing_announcement(self, bill_id: str) -> None:
        """Clear cached hearing announcement data for a bill."""
        slot = self._slot(bill_id)
        if "hearing_announcement" in slot:
            del slot["hearing_announcement"]
            self.save()

    def get_bill_url(self, bill_id: str) -> Optional[str]:
        """Return cached bill URL for a bill (or None)."""
        return self._slot(bill_id).get("bill_url")

    def set_bill_url(self, bill_id: str, bill_url: str) -> None:
        """Set bill URL for a bill."""
        slot = self._slot(bill_id)
        slot["bill_url"] = bill_url
        self.save()

    def add_bill_with_extensions(self, bill_id: str) -> None:
        """Add a bill to cache with extensions field for fallback cases."""
        slot = self._slot(bill_id)
        slot["extensions"] = {
            "is_fallback": True,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    def get_committee_contact(self, committee_id: str) -> Optional[dict]:
        """Return cached committee contact info (or None)."""
        return self._data.get("committee_contacts", {}).get(committee_id)

    def set_committee_contact(
        self, committee_id: str, contact_data: dict
    ) -> None:
        """Set committee contact data in cache."""
        if "committee_contacts" not in self._data:
            self._data["committee_contacts"] = {}
        self._data["committee_contacts"][committee_id] = {
            **contact_data,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }
        self.save()

    # ---------------------------------------------------------------------
    # Bill title helpers
    # ---------------------------------------------------------------------

    def get_title(self, bill_id: str) -> Optional[str]:
        """Return cached bill title (or None)."""
        entry = self._slot(bill_id).get("title")
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            return entry.get("value")
        return None

    def set_title(self, bill_id: str, title: str) -> None:
        """Cache the given title for a bill."""
        slot = self._slot(bill_id)
        slot["title"] = {
            "value": title,
            "updated_at": (
                datetime.utcnow().isoformat(timespec="seconds") + "Z"
            ),
        }
        self.save()

    @staticmethod
    def _wrap_mod(module_name: str) -> dict[str, Any]:
        return {
            "module": module_name,
            "confirmed": False,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }

    def search_for_keyword(self, keyword: str) -> bool:
        """Check if a keyword appears anywhere in the cache file."""
        if not self.path.exists():
            return False
        content = self.path.read_text(encoding="utf-8")
        return keyword.lower() in content.lower()

    # ---------------------------------------------------------------------
    # Committee-level parser tracking
    # ---------------------------------------------------------------------

    def get_committee_parsers(
        self, committee_id: str, parser_type: str
    ) -> list[str]:
        """Return list of parser modules that have worked for this committee.
        
        Returns them ordered by:
        1. Recent streak (if >= 2 consecutive successes)
        2. Total success count
        
        This allows the system to detect when a committee shifts their
        document practices to a new parser.
        """
        committee_data = self._data.setdefault(
            "committee_parsers", {}
        ).get(committee_id, {})
        
        parser_stats = committee_data.get(parser_type, {})
        if not parser_stats:
            return []
        
        # Sort by:
        # Primary: has active streak >= 2 (recent pattern)
        # Secondary: total count (historical success)
        def sort_key(item):
            module_name, stats = item
            streak = stats.get("current_streak", 0)
            count = stats.get("count", 0)
            # Parsers with streak >= 2 get priority boost
            has_active_streak = 1 if streak >= 2 else 0
            return (has_active_streak, count)
        
        sorted_parsers = sorted(
            parser_stats.items(),
            key=sort_key,
            reverse=True
        )
        return [module_name for module_name, _ in sorted_parsers]

    def record_committee_parser(
        self, committee_id: str, parser_type: str, module_name: str
    ) -> None:
        """Record that a parser successfully worked for a committee.
        
        Tracks success count, streak, and timestamps. Streaks detect when
        a committee shifts to consistently using a different parser.
        """
        committee_parsers = self._data.setdefault(
            "committee_parsers", {}
        )
        committee_data = committee_parsers.setdefault(committee_id, {})
        parser_type_data = committee_data.setdefault(parser_type, {})
        
        # Get the last successful parser for this committee+type
        last_parser = committee_data.get(f"{parser_type}_last_parser")
        
        # Initialize entry if new
        if module_name not in parser_type_data:
            parser_type_data[module_name] = {
                "count": 0,
                "current_streak": 0,
                "first_seen": datetime.utcnow().isoformat(
                    timespec="seconds"
                ) + "Z",
            }
        
        # Update count and timestamp
        parser_type_data[module_name]["count"] += 1
        parser_type_data[module_name]["last_used"] = (
            datetime.utcnow().isoformat(timespec="seconds") + "Z"
        )
        
        # Update streaks:
        # - If same as last parser, increment its streak
        # - If different, reset all other parsers' streaks
        if last_parser == module_name:
            # Continue the streak
            parser_type_data[module_name]["current_streak"] += 1
        else:
            # New parser - reset all streaks and start fresh
            for parser_key in parser_type_data:
                if isinstance(parser_type_data[parser_key], dict):
                    parser_type_data[parser_key]["current_streak"] = 0
            parser_type_data[module_name]["current_streak"] = 1
            # Remember this as the new last parser
            committee_data[f"{parser_type}_last_parser"] = module_name
        
        self.save()


def load_config() -> dict:
    """ Load the configuration from the config.yaml file. """
    cfg_path = Path("config.yaml")
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or DEFAULT_CONFIG
    return DEFAULT_CONFIG


def compute_deadlines(
    hearing_date: date, extension_until: Optional[date] = None
) -> tuple[date, date, date]:
    """Return (deadline_60, deadline_90, effective_deadline)."""
    d60 = hearing_date + timedelta(days=60)
    d90 = hearing_date + timedelta(days=90)
    if not extension_until:
        return d60, d90, d60
    # Extension cannot exceed 30 days beyond d60 and never beyond 90 total.
    effective = min(extension_until, d90)
    # Guard against bogus early dates; if earlier than 60, keep 60.
    effective = max(effective, d60)
    return d60, d90, effective


def ask_yes_no(
    prompt: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None
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
    bill_id: Optional[str] = None
) -> bool:
    """
    Console-based yes/no confirmation dialog.
    Returns True for Yes, False for No.
    """
    # Create header
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
    
    # Get user input with validation
    while True:
        try:
            choice = input("Use this? (y/n): ").strip().lower()
            if choice in ['y', 'yes']:
                return True
            elif choice in ['n', 'no']:
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
    bill_id: Optional[str] = None
) -> bool:
    """
    Console-based yes/no confirmation with text preview.
    """
    # Create header
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
    
    # Display preview with proper wrapping
    print("\nPreview:")
    print("-" * 64)
    
    # Wrap text to 80 columns for better readability
    import textwrap
    wrapped_lines = []
    for line in preview_text.split('\n'):
        if line.strip():
            wrapped_lines.extend(textwrap.wrap(line, width=80))
        else:
            wrapped_lines.append('')
    
    # Show first 20 lines to avoid overwhelming the console
    display_lines = wrapped_lines[:20]
    for line in display_lines:
        print(line)
    
    if len(wrapped_lines) > 20:
        print(f"\n... ({len(wrapped_lines) - 20} more lines)")
    
    print("-" * 64)
    print(f"{header}")
    
    # Get user input with validation
    while True:
        try:
            choice = input("Use this? (y/n): ").strip().lower()
            if choice in ['y', 'yes']:
                return True
            elif choice in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            return False


def ask_llm_decision(
    content: str,
    doc_type: str,
    bill_id: str,
    config: dict
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
    llm_config = config.get("llm", {})
    # Always create parser if audit logging is enabled, even if LLM is disabled
    if llm_config.get("audit_log", {}).get(
        "enabled", False
    ) or llm_config.get("enabled", False):
        llm_parser = create_llm_parser(llm_config)
        if llm_parser is None:
            return None
        return llm_parser.make_decision(content, doc_type, bill_id)
    return None


def ask_yes_no_with_llm_fallback(
    prompt: str,
    url: Optional[str] = None,
    doc_type: str = "document",
    bill_id: Optional[str] = None,
    config: Optional[dict] = None
) -> bool:
    """
    Ask for yes/no confirmation with LLM fallback.

    First tries to use LLM if enabled and available.
    If LLM returns "unsure", "no", or is unavailable (None), falls back to human dialog.  # noqa: E501

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
        # For "unsure", or None (unavailable), fall back to manual review
        if llm_decision in ["unsure", None]:
            if llm_decision is None:
                print(
                    f"LLM unavailable for {doc_type} {bill_id}, "
                    "falling back to manual review"
                )
            # Route to appropriate UI based on popup_review setting
            use_popups = config.get("popup_review", True)
            if use_popups:
                return ask_yes_no(prompt, url, doc_type, bill_id)
            else:
                return ask_yes_no_console(prompt, url, doc_type, bill_id)
    
    # Route to appropriate UI based on popup_review setting
    use_popups = config.get("popup_review", True) if config else True
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
    config: Optional[dict] = None
) -> bool:
    """
    Ask for yes/no confirmation with preview and LLM fallback.

    First tries to use LLM if enabled and available.
    If LLM returns "unsure", "no", or is unavailable (None), falls back to human dialog.  # noqa: E501

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
        llm_decision = ask_llm_decision(
            content, doc_type, bill_id, config
        )
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
            use_popups = config.get("popup_review", True)
            if use_popups:
                return ask_yes_no_with_preview(
                    title, heading, preview_text, url, doc_type, bill_id
                )
            else:
                return ask_yes_no_with_preview_console(
                    title, heading, preview_text, url, doc_type, bill_id
                )
    
    # Route to appropriate UI based on popup_review setting
    use_popups = config.get("popup_review", True) if config else True
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
    bill_id: Optional[str] = None
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
            context_text = (
                f"Looking for: {doc_type.title()} -- For bill: {bill_id}"
            )
        else:
            context_text = f"Looking for: {doc_type.title()}"
        context_label = tk.Label(
            frm,
            text=context_text,
            fg="blue",
            font=("Arial", 9, "bold")
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
            command=lambda: (res.update(ok=False),
                             root.destroy())  # type: ignore
        ).pack(side="right", padx=6)
        tk.Button(
            btns,
            text="Yes",
            width=10,
            command=lambda: (res.update(ok=True),
                             root.destroy())  # type: ignore
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
            return [{
                "bill_id": bill_id,
                "extension_date": cached_extension["extension_date"],
                "extension_order_url": cached_extension["extension_url"],
                "cached": True
            }]

    # Scrape all extension orders and find ones for this bill
    extension_orders = collect_all_extension_orders(
        "https://malegislature.gov", cache
    )

    # Filter for this specific bill
    bill_extensions = []
    for eo in extension_orders:
        if eo.bill_id == bill_id:
            bill_extensions.append({
                "bill_id": eo.bill_id,
                "committee_id": eo.committee_id,
                "extension_date": eo.extension_date.isoformat(),
                "extension_order_url": eo.extension_order_url,
                "order_type": eo.order_type,
                "discovered_at": eo.discovered_at.isoformat()
            })

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
