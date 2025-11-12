"""Utility functions for the Massachusetts Legislature website."""

from datetime import date, timedelta, datetime, timezone
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import re
import textwrap
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext
from typing import Optional, Any, Literal
import webbrowser
from zoneinfo import ZoneInfo

from components.llm import LLMParser
from components.interfaces import Config
from collectors.extension_orders import collect_all_extension_orders
from version import __version__


_DEFAULT_PATH = Path("cache/cache.json")


class TimeInterval(IntEnum):
    """Time intervals for compliance delta calculations."""
    DAILY = 1
    WEEKLY = 7
    MONTHLY = 30


# pylint: disable=too-many-public-methods
# This mimics the structure of the YAML file, so the number of methods is
# just a consequence of the type of data we're working with.
class Cache:
    """Cache for the parser results."""

    def __init__(
        self, path: Path = _DEFAULT_PATH, auto_save: bool = True
    ) -> None:
        self.path: Path = path
        self.data: dict[str, Any] = {}
        self.auto_save: bool = auto_save
        self.unsaved_changes: bool = False
        self._committee_bills_cache: dict[str, set[str]] = {}
        # Reentrant lock for nested calls:
        self._lock: threading.RLock = threading.RLock()
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                comm_bills: dict[str, dict[str, list[str]]] = self.data.get(
                    "committee_bills", {}
                )
                for committee_id, data in comm_bills.items():
                    bills_list: list[str] = data.get("bills", [])
                    self._committee_bills_cache[committee_id] = set(bills_list)
            except Exception:  # pylint: disable=broad-exception-caught
                self.data = {}

    def save(self) -> None:
        """Save the cache to the file (respects auto_save flag)."""
        with self._lock:
            if self.auto_save:
                self._write_to_disk()
            else:
                self.unsaved_changes = True

    def force_save(self) -> None:
        """Force write cache to disk, regardless of auto_save setting."""
        with self._lock:
            if self.unsaved_changes or self.auto_save:
                self._write_to_disk()
                self.unsaved_changes = False

    def _write_to_disk(self) -> None:
        """Internal method to write cache data to disk."""
        # Use compact JSON (no indent) for faster writes with large cache
        # File size: ~2.3MB vs ~4.7MB, Write speed: 2x faster
        self.path.write_text(
            json.dumps(self.data, separators=(',', ':')), encoding="utf-8"
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
        with self._lock:
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
        with self._lock:
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
        return self.data.setdefault(
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
        with self._lock:
            slot = self._slot(bill_id)
            slot["extensions"] = {
                "extension_date": extension_date,
                "extension_url": extension_url,
                "updated_at": datetime.now(timezone.utc).isoformat(
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
        with self._lock:
            slot = self._slot(bill_id)
            if bill_url:
                slot["bill_url"] = bill_url
            slot["hearing_announcement"] = {
                "announcement_date": announcement_date,
                "scheduled_hearing_date": scheduled_hearing_date,
                "updated_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ) + "Z",
            }
            self.save()

    def clear_hearing_announcement(self, bill_id: str) -> None:
        """Clear cached hearing announcement data for a bill."""
        with self._lock:
            slot = self._slot(bill_id)
            if "hearing_announcement" in slot:
                del slot["hearing_announcement"]
                self.save()

    def get_bill_url(self, bill_id: str) -> Optional[str]:
        """Return cached bill URL for a bill (or None)."""
        return self._slot(bill_id).get("bill_url")

    def set_bill_url(self, bill_id: str, bill_url: str) -> None:
        """Set bill URL for a bill."""
        with self._lock:
            slot = self._slot(bill_id)
            slot["bill_url"] = bill_url
            self.save()

    def add_bill_with_extensions(self, bill_id: str) -> None:
        """Add a bill to cache with extensions field for fallback cases."""
        with self._lock:
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
        return self.data.get("committee_contacts", {}).get(committee_id)

    def set_committee_contact(
        self, committee_id: str, contact_data: dict
    ) -> None:
        """Set committee contact data in cache."""
        with self._lock:
            if "committee_contacts" not in self.data:
                self.data["committee_contacts"] = {}
            self.data["committee_contacts"][committee_id] = {
                **contact_data,
                "updated_at": datetime.utcnow().isoformat(
                    timespec="seconds"
                ) + "Z",
            }
            self.save()

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
        with self._lock:
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

    def add_bill_to_committee(
        self, committee_id: str, bill_id: str
    ) -> None:
        """Track which bills belong to each committee.

        Args:
            committee_id: Committee ID (e.g., "J37")
            bill_id: Bill ID (e.g., "H3444")
        """
        with self._lock:
            # Use in-memory set cache for O(1) lookups (avoids O(n²)
            # list scans)
            if committee_id not in self._committee_bills_cache:
                self._committee_bills_cache[committee_id] = set()
            # O(1) set lookup instead of O(n) list scan
            if bill_id not in self._committee_bills_cache[committee_id]:
                self._committee_bills_cache[committee_id].add(bill_id)
                committee_bills = self.data.setdefault("committee_bills", {})
                committee_data = committee_bills.setdefault(committee_id, {
                    "bills": [],
                    "bill_count": 0
                })
                committee_data["bills"].append(bill_id)
                committee_data["bill_count"] = len(committee_data["bills"])
                committee_data["last_updated"] = (
                    datetime.utcnow().isoformat(timespec="seconds") + "Z"
                )
                self.save()

    def get_committee_bills(self, committee_id: str) -> list[str]:
        """Get all bills for a committee.

        Args:
            committee_id: Committee ID (e.g., "J37")

        Returns:
            List of bill IDs
        """
        committee_bills = self.data.get("committee_bills", {})
        committee_data = committee_bills.get(committee_id, {})
        return committee_data.get("bills", [])

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
        committee_data = self.data.setdefault(
            "committee_parsers", {}
        ).get(committee_id, {})
        parser_stats = committee_data.get(parser_type, {})
        if not parser_stats:
            return []

        def _sort_key(item: tuple[str, dict]) -> tuple[int, int]:
            _, stats = item
            streak = stats.get("current_streak", 0)
            count = stats.get("count", 0)
            has_active_streak = 1 if streak >= 2 else 0
            return (has_active_streak, count)

        sorted_parsers = sorted(
            parser_stats.items(),
            key=_sort_key,
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
        with self._lock:
            committee_parsers = self.data.setdefault(
                "committee_parsers", {}
            )
            committee_data = committee_parsers.setdefault(committee_id, {})
            parser_type_data = committee_data.setdefault(parser_type, {})
            last_parser = committee_data.get(f"{parser_type}_last_parser")
            if module_name not in parser_type_data:
                parser_type_data[module_name] = {
                    "count": 0,
                    "current_streak": 0,
                    "first_seen": datetime.utcnow().isoformat(
                        timespec="seconds"
                    ) + "Z",
                }
            parser_type_data[module_name]["count"] += 1
            parser_type_data[module_name]["last_used"] = (
                datetime.utcnow().isoformat(timespec="seconds") + "Z"
            )
            if last_parser == module_name:
                parser_type_data[module_name]["current_streak"] += 1
            else:
                for parser_key in parser_type_data:
                    if isinstance(parser_type_data[parser_key], dict):
                        parser_type_data[parser_key]["current_streak"] = 0
                parser_type_data[module_name]["current_streak"] = 1
                committee_data[f"{parser_type}_last_parser"] = module_name
            self.save()

    def _ensure_document_cache_structure(self) -> None:
        """Ensure document cache structure exists in cache data."""
        if "document_cache" not in self.data:
            self.data["document_cache"] = {
                "by_url": {},
                "by_content_hash": {},
                "metadata": {
                    "total_documents": 0,
                    "total_size_bytes": 0,
                    "last_cleanup": datetime.utcnow().isoformat(
                        timespec="seconds"
                    ) + "Z"
                }
            }

    @staticmethod
    def _compute_content_hash(content: bytes) -> str:
        """Compute SHA256 hash of content."""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _get_file_extension(content_type: str, url: str) -> str:
        """Determine file extension from content type or URL."""
        if "pdf" in content_type.lower():
            return "pdf"
        elif (
            "wordprocessing" in content_type.lower()
            or "docx" in content_type.lower()
        ):
            return "docx"
        elif "msword" in content_type.lower() or "doc" in content_type.lower():
            return "doc"
        # Fallback: try to get extension from URL
        if url.lower().endswith(".pdf"):
            return "pdf"
        elif url.lower().endswith(".docx"):
            return "docx"
        elif url.lower().endswith(".doc"):
            return "doc"
        # Default fallback
        return "bin"

    def get_cached_document(
        self, url: str, config: Optional[Config] = None
    ) -> Optional[dict]:
        """Get cached document metadata if it exists and is valid."""
        if not config or not config.document_cache.enabled:
            return None
        self._ensure_document_cache_structure()
        cache_entry = self.data["document_cache"]["by_url"].get(url)
        if not cache_entry:
            return None
        cached_file_path = Path(cache_entry.get("cached_file_path", ""))
        if not cached_file_path.exists():
            return None
        last_validated = cache_entry.get("last_validated")
        if last_validated:
            try:
                last_validated_dt = datetime.fromisoformat(
                    last_validated.replace("Z", "+00:00")
                )
                age_days = (
                    datetime.now(timezone.utc) - last_validated_dt
                ).days
                if age_days > config.document_cache.validate_after_days:
                    return None
            except (ValueError, AttributeError):
                return None
        return cache_entry

    def cache_document(
        self,
        url: str,
        content: bytes,
        config: Config,
        content_type: str = "application/octet-stream",
        etag: Optional[str] = None,
        last_modified: Optional[str] = None,
        bill_id: Optional[str] = None,
        document_purpose: Optional[str] = None
    ) -> dict:
        """Cache a document with content-addressed storage."""
        with self._lock:
            self._ensure_document_cache_structure()
            content_hash = self._compute_content_hash(content)
            file_ext = self._get_file_extension(content_type, url)
            cache_dir = Path(config.document_cache.directory)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_file_path = cache_dir / f"{content_hash}.{file_ext}"
            if not cached_file_path.exists():
                cached_file_path.write_bytes(content)
            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            existing_entry = self.data["document_cache"]["by_url"].get(url)
            cache_entry = {
                "url": url,
                "content_hash": content_hash,
                "content_type": content_type,
                "file_size_bytes": len(content),
                "first_downloaded": (
                    existing_entry.get("first_downloaded", now)
                    if existing_entry else now
                ),
                "last_accessed": now,
                "last_validated": now,
                "access_count": (
                    existing_entry.get("access_count", 0) + 1
                    if existing_entry else 1
                ),
                "cached_file_path": str(cached_file_path),
                "etag": etag,
                "last_modified": last_modified,
                "bill_ids": (
                    existing_entry.get("bill_ids", [])
                    if existing_entry else []
                ),
                "document_purpose": document_purpose
            }
            if bill_id and bill_id not in cache_entry["bill_ids"]:
                cache_entry["bill_ids"].append(bill_id)
            self.data["document_cache"]["by_url"][url] = cache_entry
            if content_hash not in self.data[
                "document_cache"
            ]["by_content_hash"]:
                self.data[
                    "document_cache"
                ]["by_content_hash"][content_hash] = []
            if url not in self.data["document_cache"][
                "by_content_hash"
            ][content_hash]:
                self.data["document_cache"][
                    "by_content_hash"
                ][content_hash].append(url)
            self.data["document_cache"]["metadata"]["total_documents"] = len(
                self.data["document_cache"]["by_url"]
            )
            total_size = 0
            seen_hashes = set()
            for entry in self.data["document_cache"]["by_url"].values():
                ch = entry.get("content_hash")
                if ch and ch not in seen_hashes:
                    seen_hashes.add(ch)
                    total_size += entry.get("file_size_bytes", 0)
            self.data["document_cache"]["metadata"]["total_size_bytes"] = (
                total_size
            )
            self.save()
            return cache_entry

    def get_cached_document_content(
        self, url: str, config: Optional[Config] = None
    ) -> Optional[bytes]:
        """Get cached document content if available."""
        cache_entry = self.get_cached_document(url, config)
        if not cache_entry:
            return None
        cached_file_path = Path(cache_entry.get("cached_file_path", ""))
        if not cached_file_path.exists():
            return None
        with self._lock:
            cache_entry["last_accessed"] = (
                datetime.utcnow().isoformat(timespec="seconds") + "Z"
            )
            cache_entry["access_count"] = (
                cache_entry.get("access_count", 0)
                + 1
            )
            self.save()
        return cached_file_path.read_bytes()

    def cache_extracted_text(
        self,
        content_hash: str,
        extracted_text: str,
        config: Config
    ) -> None:
        """Cache extracted text from a document."""
        if not config.document_cache.store_extracted_text:
            return
        extracted_dir = Path(config.document_cache.extracted_text_directory)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        extracted_file_path = extracted_dir / f"{content_hash}.txt"
        extracted_file_path.write_text(extracted_text, encoding="utf-8")

    def get_cached_extracted_text(
        self,
        content_hash: str,
        config: Optional[Config] = None
    ) -> Optional[str]:
        """Get cached extracted text if available."""
        if not config or not config.document_cache.store_extracted_text:
            return None
        extracted_dir = Path(config.document_cache.extracted_text_directory)
        extracted_file_path = extracted_dir / f"{content_hash}.txt"
        if not extracted_file_path.exists():
            return None
        try:
            return extracted_file_path.read_text(encoding="utf-8")
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def cleanup_document_cache(
        self, config: Config, force: bool = False
    ) -> dict[str, int]:
        """Clean up old or oversized cache entries."""
        with self._lock:
            self._ensure_document_cache_structure()
            stats = {
                "documents_removed": 0,
                "bytes_freed": 0,
                "files_deleted": 0
            }
            last_cleanup = (
                self.data["document_cache"]["metadata"].get("last_cleanup")
            )
            if not force and last_cleanup:
                try:
                    last_cleanup_dt = datetime.fromisoformat(
                        last_cleanup.replace("Z", "+00:00")
                    )
                    if (datetime.now(timezone.utc) - last_cleanup_dt).days < 1:
                        return stats
                except (ValueError, AttributeError):
                    pass
            by_url = self.data["document_cache"]["by_url"]
            max_age_seconds = config.document_cache.max_age_days * 86400
            now = datetime.now(timezone.utc)
            urls_to_remove = []
            for url, entry in by_url.items():
                last_accessed = entry.get("last_accessed")
                if last_accessed:
                    try:
                        last_accessed_dt = datetime.fromisoformat(
                            last_accessed.replace("Z", "+00:00")
                        )
                        age_seconds = (now - last_accessed_dt).total_seconds()
                        if age_seconds > max_age_seconds:
                            urls_to_remove.append(url)
                    except (ValueError, AttributeError):
                        pass
            files_to_delete = set()
            for url in urls_to_remove:
                entry = by_url.pop(url)
                stats["documents_removed"] += 1
                stats["bytes_freed"] += entry.get("file_size_bytes", 0)
                cached_file_path = entry.get("cached_file_path")
                if cached_file_path:
                    files_to_delete.add(cached_file_path)
                content_hash = entry.get("content_hash")
                if content_hash in (
                    self.data["document_cache"]["by_content_hash"]
                ):
                    hash_urls = (
                        self.data["document_cache"]["by_content_hash"]
                        [content_hash]
                    )
                    if url in hash_urls:
                        hash_urls.remove(url)
                    if not hash_urls:
                        del self.data["document_cache"]["by_content_hash"][
                            content_hash
                        ]
            for file_path_str in files_to_delete:
                file_path = Path(file_path_str)
                content_hash_from_path = file_path.stem
                if content_hash_from_path not in (
                    self.data["document_cache"]["by_content_hash"]
                ):
                    if not file_path.exists():
                        continue
                    try:
                        file_path.unlink()
                        stats["files_deleted"] += 1
                    # pylint: disable=broad-exception-caught
                    except Exception:
                        pass
            self.data["document_cache"]["metadata"]["last_cleanup"] = (
                datetime.utcnow().isoformat(timespec="seconds") + "Z"
            )
            self.save()
            return stats


def get_next_first_wednesday_december(from_date: date) -> date:
    """Get the next first Wednesday in December from a given date.

    For Senate bills: Joint Rule 10 requires reports by the first
    Wednesday in December of the first annual session.

    Args:
        from_date: Reference date (typically the hearing date)

    Returns:
        The next first Wednesday in December (may be in current or next year)
    """
    # Start with December 1st of the current year
    year = from_date.year
    dec_first = date(year, 12, 1)

    # Find the first Wednesday (weekday 2 is Wednesday, 0=Monday)
    days_until_wednesday = (2 - dec_first.weekday()) % 7
    first_wednesday = dec_first + timedelta(days=days_until_wednesday)

    # If that date has already passed, go to next year's December
    if first_wednesday < from_date:
        dec_first_next = date(year + 1, 12, 1)
        days_until_wednesday = (2 - dec_first_next.weekday()) % 7
        first_wednesday = dec_first_next + timedelta(days=days_until_wednesday)

    return first_wednesday


def compute_deadlines(
    hearing_date: Optional[date],
    extension_until: Optional[date] = None,
    bill_id: Optional[str] = None
) -> tuple[Optional[date], Optional[date], Optional[date]]:
    """Return (deadline_60, deadline_90, effective_deadline).

    Args:
        hearing_date: Date of the hearing (None if no hearing scheduled)
        extension_until: Optional extension date
        bill_id: Bill identifier (e.g., "H73", "S197") - used to determine
                 if Senate bill rules apply

    Returns:
        Tuple of (deadline_60, deadline_90, effective_deadline)
        Returns (None, None, None) if no hearing_date provided

    Rules:
        - House bills: 60 days from hearing + optional 30-day extension
          (90 max)
        - Senate bills: First Wednesday in December + optional 30-day
          extension
    """
    if hearing_date is None:
        return None, None, None
    is_senate_bill = bill_id and bill_id.upper().startswith('S')
    if is_senate_bill:
        d60 = get_next_first_wednesday_december(hearing_date)
        d90 = d60 + timedelta(days=30)
    else:
        d60 = hearing_date + timedelta(days=60)
        d90 = hearing_date + timedelta(days=90)
    if not extension_until:
        return d60, d90, d60
    effective = min(extension_until, d90)
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
    for line in preview_text.split('\n'):
        if line.strip():
            wrapped_lines.extend(textwrap.wrap(line, width=80))
        else:
            wrapped_lines.append('')
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
    config: Config
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
    config: Optional[Config] = None
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
        llm_decision = ask_llm_decision(
            content, doc_type, bill_id, config
        )
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
    config: Optional[Config] = None
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


# Version and Changelog Functions


def get_user_agent() -> str:
    """
    Get the user-agent string for HTTP requests.

    Returns:
        User-agent string in format: "BeaconHillTracker/VERSION (EMAIL)"
    """
    email = "info@beaconhilltracker.org"
    return f"BeaconHillTracker/{__version__} ({email})"


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

            versions.append({
                "version": version,
                "date": release_date,
                "changes": changes
            })

    return {
        "current_version": current_version or __version__,
        "changelog": versions
    }


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
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith('-'):
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
        Path(base_dir) / str(today.year) /
        f"{today.month:02d}" / f"{today.day:02d}"
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
    base_dir: str = "out",
    target_days_ago: int = 1
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
    committee_id: str,
    base_dir: str = "out",
    days_ago: int = 1
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
            return data["bills"], previous_date
    except (json.JSONDecodeError, IOError):
        return None, previous_date


def generate_diff_report(
    current_bills: list[dict],
    previous_bills: Optional[list[dict]],
    current_date: date,
    previous_date: Optional[date]
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
            1 for b in bills_dict.values()
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
        bill_id for bill_id in current_by_id
        if bill_id not in previous_by_id
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
