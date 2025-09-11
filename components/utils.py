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

    def _slot(self, bill_id: str) -> dict[str, Any]:
        return self._data.setdefault(
            "bill_parsers", {}
        ).setdefault(bill_id, {})

    @staticmethod
    def _wrap_mod(module_name: str) -> dict[str, Any]:
        return {
            "module": module_name,
            "confirmed": False,
            "updated_at": datetime.utcnow().isoformat(
                timespec="seconds"
            ) + "Z",
        }


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
    If LLM returns "unsure" or is unavailable, falls back to human dialog.

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
    return ask_yes_no(prompt, url, doc_type, bill_id)


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
    If LLM returns "unsure" or is unavailable, falls back to human dialog.

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
    return ask_yes_no_with_preview(
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
