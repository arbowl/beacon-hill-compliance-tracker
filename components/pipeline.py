""" Pipeline for resolving the summary for a bill. """

import importlib
from typing import Any, Optional

from components.utils import Cache
from components.models import BillAtHearing, SummaryInfo, VoteInfo, DeferredConfirmation, DeferredReviewSession
from components.utils import (
    ask_yes_no_with_llm_fallback,
    ask_yes_no_with_preview_and_llm_fallback
)


def _load_parsers(config: dict[str, Any]) -> list[dict[str, Any]]:
    """ Load the parsers from the config. """
    parsers = (config.get("parsers", {}) or {}).get("summary", [])
    # sort by cost asc
    return sorted(parsers, key=lambda p: p.get("cost", 999))


def resolve_summary_for_bill(
    base_url: str, cfg: dict, cache: Cache, row: BillAtHearing,
    deferred_session: Optional[DeferredReviewSession] = None
) -> SummaryInfo:
    """Resolve the summary for a bill."""
    review_mode: str = cfg.get("review_mode", "on").lower()
    # 1) If we have a confirmed parser, run it silently and return.
    cached: Optional[str] = cache.get_parser(row.bill_id, "summary")
    if cached and cache.is_confirmed(row.bill_id, "summary"):
        mod = importlib.import_module(cached)
        candidate: Optional[dict] = mod.discover(base_url, row)
        if candidate:
            parsed: dict = mod.parse(base_url, candidate)
            return SummaryInfo(
                present=True,
                location="hearing_pdf",  # or infer from module if you want
                source_url=parsed.get("source_url"),
                parser_module=cached,
                needs_review=False,
            )
        # If the source vanished, fall through to normal sequence.
    # 2) Otherwise, try cached first (unconfirmed), then others by cost
    parser_sequence: list[dict] = _load_parsers(cfg)
    if cached:
        parser_sequence = (
            [{"module": cached, "cost": 0}] +
            [p for p in parser_sequence if p["module"] != cached]
        )
    for p in parser_sequence:
        modname = p["module"]
        try:
            mod = importlib.import_module(modname)
        # pylint: disable=broad-exception-caught
        except Exception:
            continue
        candidate = mod.discover(base_url, row)
        if not candidate:
            continue
        # If we're here via an unconfirmed cache OR a new parser:
        accepted = True
        needs_review = False
        
        if review_mode == "deferred" and deferred_session is not None:
            # Collect for deferred review instead of asking now
            preview_text = candidate.get("full_text", candidate.get("preview", ""))
            confidence = candidate.get("confidence", 0.5)
            
            # Check if we should auto-accept based on confidence
            auto_accept_threshold = cfg.get("deferred_review", {}).get("auto_accept_high_confidence", 0.9)
            if confidence >= auto_accept_threshold:
                accepted = True
                needs_review = False
            else:
                # Add to deferred session for later review
                confirmation = DeferredConfirmation(
                    confirmation_id="",  # Will be auto-generated
                    bill_id=row.bill_id,
                    parser_type="summary",
                    parser_module=modname,
                    candidate=candidate,
                    preview_text=preview_text,
                    confidence=confidence
                )
                deferred_session.add_confirmation(confirmation)
                accepted = True  # Tentatively accept for now
                needs_review = True
        elif review_mode == "on":
            # show dialog only when not previously confirmed
            # Use full_text if available, otherwise fall back to preview
            preview_text = candidate.get(
                "full_text", candidate.get("preview", "")
            )
            if len(preview_text) > 140:
                accepted = ask_yes_no_with_preview_and_llm_fallback(
                    title="Confirm summary",
                    heading=f"Use this summary for {row.bill_id}?",
                    preview_text=preview_text,
                    url=candidate.get("source_url"),
                    doc_type="summary",
                    bill_id=row.bill_id,
                    config=cfg
                )
            else:
                accepted = ask_yes_no_with_llm_fallback(
                    preview_text or "Use this summary?",
                    candidate.get("source_url"),
                    doc_type="summary",
                    bill_id=row.bill_id,
                    config=cfg
                )
        else:  # review_mode == "off"
            needs_review = True

        if accepted:
            parsed = mod.parse(base_url, candidate)
            # mark confirmed if we actually asked; otherwise keep unconfirmed
            cache.set_parser(row.bill_id, "summary", modname, confirmed=(
                review_mode == "on" and not needs_review
            ))
            return SummaryInfo(
                present=True,
                location=(
                    "hearing_pdf" if "hearing" in modname else "bill_tab"
                ),
                source_url=parsed.get("source_url"),
                parser_module=modname,
                needs_review=needs_review,
            )
    return SummaryInfo(
        present=False,
        location="unknown",
        source_url=None,
        parser_module=None,
        needs_review=False
    )


def _load_votes_parsers(config: dict) -> list[dict]:
    """Load the votes parsers from the config."""
    parsers = (config.get("parsers", {}) or {}).get("votes", [])
    return sorted(parsers, key=lambda p: p.get("cost", 999))


def _infer_location_from_module(modname: str) -> str:
    """Infer the location from the module name."""
    if "embedded" in modname:
        return "bill_embedded"
    if "bill_pdf" in modname:
        return "bill_pdf"
    if "hearing" in modname:
        return "hearing_docs"
    if "committee" in modname:
        return "committee_docs"
    return "unknown"


def resolve_votes_for_bill(
    base_url: str, cfg: dict, cache: Cache, row: BillAtHearing,
    deferred_session: Optional[DeferredReviewSession] = None
) -> VoteInfo:
    """
    Votes pipeline with confirmed-cache short-circuit:
    - If a cached parser is marked confirmed, run it silently (no dialog).
      * If discover() still finds a candidate, return it.
      * If not, treat cache as stale and fall through to normal sequence.
    - Otherwise try cached (unconfirmed) first, then others by cost.
      * Only show a dialog when review_mode == 'on'.
      * Mark confirmed=True when a user explicitly accepts; False for headless
      auto-accept.
    """
    review_mode = cfg.get("review_mode", "on").lower()
    cached_mod = cache.get_parser(row.bill_id, "votes")
    # 1) Confirmed-cache fast path (silent)
    if cached_mod and cache.is_confirmed(row.bill_id, "votes"):
        try:
            mod = importlib.import_module(cached_mod)
            candidate = mod.discover(base_url, row)
            if candidate:
                parsed = mod.parse(base_url, candidate)
                return VoteInfo(
                    present=True,
                    location=(
                        parsed.get("location")
                        or _infer_location_from_module(cached_mod)
                    ),
                    source_url=parsed.get("source_url"),
                    parser_module=cached_mod,
                    needs_review=False,
                )
            # stale: fall through to normal flow
        # pylint: disable=broad-exception-caught
        except Exception:
            # module import or runtime issue -> fall through
            pass
    # 2) Build sequence: cached (if any) first, then by cost
    parser_sequence = _load_votes_parsers(cfg)
    if cached_mod:
        parser_sequence = (
            [{"module": cached_mod, "cost": 0}] +
            [p for p in parser_sequence if p["module"] != cached_mod]
        )
    # 3) Try parsers
    for p in parser_sequence:
        modname = p["module"]
        try:
            mod = importlib.import_module(modname)
        # pylint: disable=broad-exception-caught
        except Exception:
            continue
        candidate = mod.discover(base_url, row)
        if not candidate:
            continue
        # Decide whether to prompt
        accepted = True
        needs_review = False
        
        if review_mode == "deferred" and deferred_session is not None:
            # Collect for deferred review instead of asking now
            preview_text = candidate.get("full_text", candidate.get("preview", ""))
            confidence = candidate.get("confidence", 0.5)
            
            # Check if we should auto-accept based on confidence
            auto_accept_threshold = cfg.get("deferred_review", {}).get("auto_accept_high_confidence", 0.9)
            if confidence >= auto_accept_threshold:
                accepted = True
                needs_review = False
            else:
                # Add to deferred session for later review
                confirmation = DeferredConfirmation(
                    confirmation_id="",  # Will be auto-generated
                    bill_id=row.bill_id,
                    parser_type="votes",
                    parser_module=modname,
                    candidate=candidate,
                    preview_text=preview_text,
                    confidence=confidence
                )
                deferred_session.add_confirmation(confirmation)
                accepted = True  # Tentatively accept for now
                needs_review = True
        elif review_mode == "on":
            # Use full_text if available, otherwise fall back to preview
            preview_text = candidate.get(
                "full_text", candidate.get("preview", "")
            )
            if len(preview_text) > 140:
                accepted = ask_yes_no_with_preview_and_llm_fallback(
                    title="Confirm vote record",
                    heading=f"Use this vote record for {row.bill_id}?",
                    preview_text=preview_text,
                    url=candidate.get("source_url"),
                    doc_type="vote record",
                    bill_id=row.bill_id,
                    config=cfg
                )
            else:
                accepted = ask_yes_no_with_llm_fallback(
                    preview_text or "Use this vote source?",
                    candidate.get("source_url"),
                    doc_type="vote record",
                    bill_id=row.bill_id,
                    config=cfg
                )
        else:  # review_mode == "off"
            # auto-accept in headless mode; not "confirmed"
            needs_review = True
        if not accepted:
            continue

        parsed = mod.parse(base_url, candidate)

        # Mark confirmation status:
        # - review_mode ON -> confirmed True (user explicitly accepted)
        # - review_mode OFF -> confirmed False (auto-accepted; will ask once
        # in a future interactive run)
        cache.set_parser(
            row.bill_id, "votes", modname,
            confirmed=review_mode == "on" and not needs_review
        )

        return VoteInfo(
            present=True,
            location=(
                parsed.get("location") or _infer_location_from_module(modname)
            ),
            source_url=parsed.get("source_url"),
            parser_module=modname,
            needs_review=needs_review,
        )

    # 4) Nothing landed
    return VoteInfo(
        present=False, location="unknown", source_url=None, parser_module=None
    )
