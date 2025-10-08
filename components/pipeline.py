""" Pipeline for resolving the summary for a bill. """

from typing import Any, Optional

from components.interfaces import ParserInterface
from components.models import BillAtHearing, SummaryInfo, VoteInfo, DeferredConfirmation, DeferredReviewSession
from components.utils import (
    Cache,
    ask_yes_no_with_llm_fallback,
    ask_yes_no_with_preview_and_llm_fallback
)
from parsers.summary_bill_tab_text import SummaryBillTabTextParser
from parsers.summary_committee_pdf import SummaryCommitteePdfParser
from parsers.summary_hearing_docs_pdf import SummaryHearingDocsPdfParser
from parsers.summary_hearing_pdf import SummaryHearingPdfParser
from parsers.summary_committee_docx import SummaryCommitteeDocxParser
from parsers.summary_hearing_docs_pdf_content import SummaryHearingDocsPdfContentParser
from parsers.votes_bill_embedded import VotesBillEmbeddedParser
from parsers.votes_bill_pdf import VotesBillPdfParser
from parsers.votes_committee_documents import VotesCommitteeDocumentsParser
from parsers.votes_docx import VotesDocxParser
from parsers.votes_hearing_committee import VotesHearingCommitteeDocumentsParser

# Maps the cache module name to the actual module object
SUMMARY_REGISTRY: dict[str, ParserInterface] = {
    module.__module__: module for module in [
        SummaryBillTabTextParser,
        SummaryCommitteePdfParser,
        SummaryHearingDocsPdfParser,
        SummaryHearingPdfParser,
        SummaryHearingDocsPdfContentParser,
        SummaryCommitteeDocxParser,
    ]
}
VOTES_REGISTRY: dict[str, ParserInterface] = {
    module.__module__: module for module in [
        VotesBillEmbeddedParser,
        VotesBillPdfParser,
        VotesCommitteeDocumentsParser,
        VotesDocxParser,
        VotesHearingCommitteeDocumentsParser,
    ]
}


def resolve_summary_for_bill(
    base_url: str,
    cfg: dict,
    cache: Cache,
    row: BillAtHearing,
    deferred_session: Optional[DeferredReviewSession] = None
) -> SummaryInfo:
    """Resolve the summary for a bill."""
    review_mode: str = cfg.get("review_mode", "on").lower()
    # 1) If we have a confirmed parser, run it silently and return.
    summary_has_parser: Optional[str] = cache.get_parser(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    )
    if summary_has_parser and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    ):
        mod = SUMMARY_REGISTRY[summary_has_parser]
        candidate: Optional[ParserInterface.DiscoveryResult] = mod.discover(
            base_url, row
        )
        if candidate:
            parsed: dict = mod.parse(base_url, candidate)
            return SummaryInfo(
                present=True,
                location=mod.location,
                source_url=candidate.source_url,
                parser_module=summary_has_parser,
                needs_review=False,
            )
        # If the source vanished, fall through to normal sequence.
    # 2) Otherwise, try cached first (unconfirmed), then others by cost
    parser_sequence: list[ParserInterface] = [
        parser
        for parser in SUMMARY_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.SUMMARY
    ]
    # If unconfirmed but suspected, move to the front of the line
    if summary_has_parser:
        parser_sequence.insert(
            0, parser_sequence.pop(
                parser_sequence.index(
                    SUMMARY_REGISTRY[summary_has_parser]
                )
            )
        )
    for p in parser_sequence:
        modname = p.__module__
        candidate = p.discover(base_url, row)
        if not candidate:
            continue
        # If we're here via an unconfirmed cache OR a new parser:
        accepted = True
        needs_review = False
        if review_mode == "deferred" and deferred_session is not None:
            # Collect for deferred review instead of asking now
            preview_text = candidate.full_text if candidate.full_text else candidate.preview
            confidence = candidate.confidence
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
            preview_text = candidate.full_text if candidate.full_text else candidate.preview
            if len(preview_text) > 140:
                accepted = ask_yes_no_with_preview_and_llm_fallback(
                    title="Confirm summary",
                    heading=f"Use this summary for {row.bill_id}?",
                    preview_text=preview_text,
                    url=candidate.source_url,
                    doc_type=ParserInterface.ParserType.SUMMARY.value,
                    bill_id=row.bill_id,
                    config=cfg
                )
            else:
                accepted = ask_yes_no_with_llm_fallback(
                    preview_text or "Use this summary?",
                    candidate.source_url,
                    doc_type=ParserInterface.ParserType.SUMMARY.value,
                    bill_id=row.bill_id,
                    config=cfg
                )
        else:  # review_mode == "off"
            needs_review = True

        if accepted:
            parsed = p.parse(base_url, candidate)
            # mark confirmed if we actually asked; otherwise keep unconfirmed
            cache.set_parser(
                row.bill_id,
                ParserInterface.ParserType.SUMMARY.value,
                modname,
                confirmed=(
                    review_mode == "on" and not needs_review
                )
            )
            return SummaryInfo(
                present=True,
                location=p.location,
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


def resolve_votes_for_bill(
    base_url: str,
    cfg: dict, 
    cache: Cache,
    row: BillAtHearing,
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
    votes_has_parser = cache.get_parser(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    )
    # 1) Confirmed-cache fast path (silent)
    if votes_has_parser and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    ):
        mod = VOTES_REGISTRY[votes_has_parser]
        candidate: Optional[ParserInterface.DiscoveryResult] = mod.discover(
            base_url, row
        )
        if candidate:
            parsed = mod.parse(base_url, candidate)
            return VoteInfo(
                present=True,
                location=mod.location,
                source_url=candidate.source_url,
                parser_module=votes_has_parser,
                needs_review=False,
            )
        # stale: fall through to normal flow
    # 2) Build sequence: cached (if any) first, then by cost
    votes_sequence: list[ParserInterface] = [
        parser
        for parser in VOTES_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.VOTES
    ]
    if votes_has_parser:
        votes_sequence.insert(
            0, votes_sequence.pop(
                votes_sequence.index(
                    VOTES_REGISTRY[votes_has_parser]
                )
            )
        )
    # 3) Try parsers
    for p in votes_sequence:
        modname = p.__module__
        candidate = p.discover(base_url, row)
        if not candidate:
            continue
        # Decide whether to prompt
        accepted = True
        needs_review = False
        if review_mode == "deferred" and deferred_session is not None:
            # Collect for deferred review instead of asking now
            preview_text = candidate.full_text if candidate.full_text else candidate.preview
            confidence = candidate.confidence if candidate.confidence else 0.5
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
                    parser_type=ParserInterface.ParserType.VOTES.value,
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
            preview_text = candidate.full_text if candidate.full_text else candidate.preview
            if len(preview_text) > 140:
                accepted = ask_yes_no_with_preview_and_llm_fallback(
                    title="Confirm vote record",
                    heading=f"Use this vote record for {row.bill_id}?",
                    preview_text=preview_text,
                    url=candidate.source_url,
                    doc_type=ParserInterface.ParserType.VOTES.value,
                    bill_id=row.bill_id,
                    config=cfg
                )
            else:
                accepted = ask_yes_no_with_llm_fallback(
                    preview_text or "Use this vote source?",
                    candidate.source_url,
                    doc_type=ParserInterface.ParserType.VOTES.value,
                    bill_id=row.bill_id,
                    config=cfg
                )
        else:  # review_mode == "off"
            # auto-accept in headless mode; not "confirmed"
            needs_review = True
        if not accepted:
            continue

        parsed = p.parse(base_url, candidate)

        # Mark confirmation status:
        # - review_mode ON -> confirmed True (user explicitly accepted)
        # - review_mode OFF -> confirmed False (auto-accepted; will ask once
        # in a future interactive run)
        cache.set_parser(
            row.bill_id,
            ParserInterface.ParserType.VOTES.value,
            modname,
            confirmed=review_mode == "on" and not needs_review
        )
        return VoteInfo(
            present=True,
            location=p.location,
            source_url=parsed.get("source_url"),
            parser_module=modname,
            needs_review=needs_review,
        )
    # 4) Nothing landed
    return VoteInfo(
        present=False, location="unknown", source_url=None, parser_module=None
    )
