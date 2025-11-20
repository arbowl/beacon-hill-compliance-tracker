""" Pipeline for resolving the summary for a bill. """

from enum import IntEnum
import logging
from typing import Optional

from components.interfaces import ParserInterface, Config
from components.models import (
    BillAtHearing,
    SummaryInfo,
    VoteInfo,
    DeferredConfirmation,
    DeferredReviewSession
)
from components.utils import (
    Cache,
    ask_yes_no_with_llm_fallback,
    ask_yes_no_with_preview_and_llm_fallback,
    ask_llm_decision
)
from parsers.summary_bill_tab_text import SummaryBillTabTextParser
from parsers.summary_committee_pdf import SummaryCommitteePdfParser
from parsers.summary_hearing_docs_pdf import SummaryHearingDocsPdfParser
from parsers.summary_hearing_pdf import SummaryHearingPdfParser
from parsers.summary_committee_docx import SummaryCommitteeDocxParser
from parsers.summary_hearing_docs_pdf_content import (
    SummaryHearingDocsPdfContentParser
)
from parsers.summary_hearing_docs_docx import SummaryHearingDocsDocxParser
from parsers.votes_bill_embedded import VotesBillEmbeddedParser
from parsers.votes_bill_pdf import VotesBillPdfParser
from parsers.votes_committee_documents import VotesCommitteeDocumentsParser
from parsers.votes_docx import VotesDocxParser
from parsers.votes_hearing_committee import (
    VotesHearingCommitteeDocumentsParser
)
from parsers.votes_journal import VotesJournalPdfParser

logger = logging.getLogger(__name__)


class ParserTier(IntEnum):
    """Parser priority tiers for intelligent selection."""

    BILL_CACHED = 0      # This specific bill used this parser before
    COMMITTEE_PROVEN = 1  # Parser has proven track record for committee
    COST_FALLBACK = 2    # Trying parsers by cost (no committee history)


# Maps the cache module name to the actual module object
SUMMARY_REGISTRY: dict[str, type[ParserInterface]] = {
    module.__module__: module for module in [  # type: ignore
        SummaryBillTabTextParser,
        SummaryCommitteePdfParser,
        SummaryHearingDocsPdfParser,
        SummaryHearingPdfParser,
        SummaryHearingDocsPdfContentParser,
        SummaryCommitteeDocxParser,
        SummaryHearingDocsDocxParser,
    ]
}
VOTES_REGISTRY: dict[str, type[ParserInterface]] = {
    module.__module__: module for module in [  # type: ignore
        VotesBillEmbeddedParser,
        VotesBillPdfParser,
        VotesCommitteeDocumentsParser,
        VotesDocxParser,
        VotesHearingCommitteeDocumentsParser,
        VotesJournalPdfParser,
    ]
}


def should_use_llm_for_parser(
    parser_module: str,
    committee_id: str,
    parser_type: str,
    cache: Cache,
    tier: ParserTier,
    candidate: ParserInterface.DiscoveryResult
) -> bool:
    """
    Decide if we should consult the LLM for this parser.

    Phase-based strategy with parser confidence gate:
    - Learning phase (streak < 3 or count < 5): Always use LLM
    - Established phase (streak ≥ 3 AND count ≥ 5):
      * Skip LLM if parser confidence ≥ 0.5 (parser not worried)
      * Use LLM if parser confidence < 0.5 (parser suspicious - maybe change?)

    Special cases:
    - Tier 0 (bill-specific cache): Skip LLM unless parser is very suspicious
    - Tier 2 (cost fallback): Always use LLM (no history)

    Args:
        parser_module: Module name of the parser
        committee_id: Committee ID
        parser_type: "summary" or "votes"
        cache: Cache instance
        tier: Which tier this parser came from
        candidate: Discovery result with confidence score

    Returns:
        True if we should consult LLM, False to skip
    """
    # Get parser's confidence (default 0.5 if not specified)
    parser_conf = candidate.confidence if candidate.confidence else 0.5

    # Tier 0: Bill-specific cache - very high trust
    # Only validate if parser is very suspicious (< 0.3)
    if tier == ParserTier.BILL_CACHED:
        return parser_conf < 0.3

    # Tier 2: Cost fallback - no committee proof, always use LLM
    if tier == ParserTier.COST_FALLBACK:
        return True

    # Tier 1: Committee-proven - phase-based with confidence gate
    if tier == ParserTier.COMMITTEE_PROVEN:
        committee_data = cache.data.get("committee_parsers", {}).get(
            committee_id, {}
        )
        parser_stats = committee_data.get(parser_type, {}).get(
            parser_module, {}
        )
        if not parser_stats:
            # No stats? Use LLM (shouldn't happen in tier 1, but be safe)
            return True
        streak = parser_stats.get("current_streak", 0)
        count = parser_stats.get("count", 0)
        # Check if pattern is established
        pattern_established = (streak >= 3 and count >= 5)
        if pattern_established:
            # Established phase: Use parser confidence as gate
            # Skip LLM if parser isn't worried (≥ 0.5)
            # Use LLM if parser is suspicious (< 0.5)
            return parser_conf < 0.5
        return True
    # Default: use LLM
    return True


def try_llm_decision(
    candidate: ParserInterface.DiscoveryResult,
    bill_id: str,
    doc_type: str,
    config: Config
) -> Optional[str]:
    """
    Try to get an LLM decision for a candidate.

    Returns:
        "yes", "no", "unsure", or None if LLM is disabled/unavailable
    """
    preview_text = (
        candidate.full_text if candidate.full_text
        else candidate.preview
    )
    return ask_llm_decision(preview_text, doc_type, bill_id, config)


def resolve_summary_for_bill(
    base_url: str,
    cfg: Config,
    cache: Cache,
    row: BillAtHearing,
    deferred_session: Optional[DeferredReviewSession] = None
) -> SummaryInfo:
    """Resolve the summary for a bill."""
    cached_result = cache.get_result(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    )
    if cached_result and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    ):
        logger.debug("Found summary in cache; skipping summary search...")
        return SummaryInfo.from_dict(cached_result)
    # 1) If we have a confirmed parser, run it silently and return.
    summary_has_parser: Optional[str] = cache.get_parser(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    )
    if summary_has_parser and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.SUMMARY.value
    ):
        mod = SUMMARY_REGISTRY[summary_has_parser]
        candidate: Optional[ParserInterface.DiscoveryResult] = mod.discover(
            base_url, row, cache, cfg
        )
        if candidate:
            parsed: dict = mod.parse(base_url, candidate)
            result = SummaryInfo(
                present=True,
                location=mod.location,
                source_url=candidate.source_url,
                parser_module=summary_has_parser,
                needs_review=False,
            )
            cache.set_result(
                row.bill_id,
                ParserInterface.ParserType.SUMMARY.value,
                summary_has_parser,
                result.to_dict(),
                confirmed=True,
            )
            # Record success for committee-level learning
            cache.record_committee_parser(
                row.committee_id,
                ParserInterface.ParserType.SUMMARY.value,
                summary_has_parser
            )
            return result
        # If the source vanished, fall through to normal sequence.
    # 2) Build parser sequence with committee-aware prioritization
    all_parsers: list[type[ParserInterface]] = [
        parser
        for parser in SUMMARY_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.SUMMARY
    ]
    # Sort by cost (ascending) - cheaper parsers first
    all_parsers.sort(key=lambda p: p.cost)
    # Build tiered priority list with tier tracking
    # Each entry is (parser, tier, module_name)
    parser_sequence: list[tuple[type[ParserInterface], ParserTier, str]] = []
    added_parsers = set()
    # Tier 0: Bill-specific cache
    if summary_has_parser and summary_has_parser in SUMMARY_REGISTRY:
        parser = SUMMARY_REGISTRY[summary_has_parser]
        parser_sequence.append(
            (parser, ParserTier.BILL_CACHED, summary_has_parser)
        )
        added_parsers.add(parser)
    # Tier 1: Committee-proven parsers
    committee_parsers = cache.get_committee_parsers(
        row.committee_id,
        ParserInterface.ParserType.SUMMARY.value
    )
    for module_name in committee_parsers:
        if module_name in SUMMARY_REGISTRY:
            parser = SUMMARY_REGISTRY[module_name]
            if parser not in added_parsers:
                parser_sequence.append(
                    (parser, ParserTier.COMMITTEE_PROVEN, module_name)
                )
                added_parsers.add(parser)
    # Tier 2: Remaining parsers by cost
    for parser in all_parsers:
        if parser not in added_parsers:
            module_name = parser.__module__
            parser_sequence.append(
                (parser, ParserTier.COST_FALLBACK, module_name)
            )
            added_parsers.add(parser)
    for p, tier, modname in parser_sequence:
        candidate = p.discover(base_url, row, cache, cfg)
        if not candidate:
            continue
        # If we're here via an unconfirmed cache OR a new parser:
        accepted = True
        needs_review = False
        if cfg.review_mode == "deferred" and deferred_session is not None:
            # Decide if we should consult LLM based on pattern confidence
            should_use_llm = should_use_llm_for_parser(
                modname,
                row.committee_id,
                ParserInterface.ParserType.SUMMARY.value,
                cache,
                tier,
                candidate
            )
            if should_use_llm:
                # Pattern not established or parser is suspicious - use LLM
                llm_decision = try_llm_decision(
                    candidate,
                    row.bill_id,
                    ParserInterface.ParserType.SUMMARY.value,
                    cfg
                )
                if llm_decision == "yes":
                    # LLM confidently accepts
                    accepted = True
                    needs_review = False
                elif llm_decision == "no":
                    # LLM confidently rejects - skip this parser
                    continue
                else:
                    # LLM returned "unsure" or is unavailable
                    # Fall back to confidence threshold logic
                    preview_text = (
                        candidate.full_text if candidate.full_text
                        else candidate.preview
                    )
                    confidence = (
                        candidate.confidence if candidate.confidence else 0.5
                    )
                    auto_yes = cfg.deferred_review.auto_accept_high_confidence
                    if confidence >= auto_yes:
                        accepted = True
                        needs_review = False
                    else:
                        # Add to deferred session for later review
                        summary = ParserInterface.ParserType.SUMMARY.value
                        confirmation = DeferredConfirmation(
                            confirmation_id="",  # Will be auto-generated
                            bill_id=row.bill_id,
                            parser_type=summary,
                            parser_module=modname,
                            candidate=candidate,
                            preview_text=preview_text,
                            confidence=confidence
                        )
                        deferred_session.add_confirmation(confirmation)
                        accepted = True  # Tentatively accept for now
                        needs_review = True
            else:
                # Pattern confidence is high - trust it without LLM
                accepted = True
                needs_review = False
        elif cfg.review_mode == "on":
            # show dialog only when not previously confirmed
            # Use full_text if available, otherwise fall back to preview
            preview_text = (
                candidate.full_text
                if candidate.full_text
                else candidate.preview
            )
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
            result = SummaryInfo(
                present=True,
                location=p.location,
                source_url=parsed.get("source_url"),
                parser_module=modname,
                needs_review=needs_review,
            )
            cache.set_result(
                row.bill_id,
                ParserInterface.ParserType.SUMMARY.value,
                modname,
                result.to_dict(),
                confirmed=cfg.review_mode == "on" and not needs_review
            )
            # Record success for committee-level learning
            cache.record_committee_parser(
                row.committee_id,
                ParserInterface.ParserType.SUMMARY.value,
                modname
            )
            return result
    return SummaryInfo(
        present=False,
        location="unknown",
        source_url=None,
        parser_module=None,
        needs_review=False
    )


def resolve_votes_for_bill(
    base_url: str,
    cfg: Config,
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
    cached_result = cache.get_result(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    )
    if cached_result and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    ):
        logger.debug("Found votes in cache; skipping votes search...")
        return VoteInfo.from_dict(cached_result)
    votes_has_parser = cache.get_parser(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    )
    # 1) Confirmed-cache fast path (silent)
    if votes_has_parser and cache.is_confirmed(
        row.bill_id, ParserInterface.ParserType.VOTES.value
    ):
        mod = VOTES_REGISTRY[votes_has_parser]
        candidate: Optional[ParserInterface.DiscoveryResult] = mod.discover(
            base_url, row, cache, cfg
        )
        if candidate:
            parsed = mod.parse(base_url, candidate)
            result = VoteInfo(
                present=True,
                location=mod.location,
                source_url=candidate.source_url,
                parser_module=votes_has_parser,
                needs_review=False,
            )
            cache.set_result(
                row.bill_id,
                ParserInterface.ParserType.VOTES.value,
                votes_has_parser,
                result.to_dict(),
                confirmed=True,
            )
            # Record success for committee-level learning
            cache.record_committee_parser(
                row.committee_id,
                ParserInterface.ParserType.VOTES.value,
                votes_has_parser
            )
            return result
        # stale: fall through to normal flow
    # 2) Build parser sequence with committee-aware prioritization
    all_votes_parsers: list[type[ParserInterface]] = [
        parser
        for parser in VOTES_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.VOTES
    ]
    # Sort by cost (ascending) - cheaper parsers first
    all_votes_parsers.sort(key=lambda p: p.cost)
    # Build tiered priority list with tier tracking
    # Each entry is (parser, tier, module_name)
    votes_sequence: list[tuple[type[ParserInterface], ParserTier, str]] = []
    added_votes_parsers = set()
    # Tier 0: Bill-specific cache
    if votes_has_parser and votes_has_parser in VOTES_REGISTRY:
        parser = VOTES_REGISTRY[votes_has_parser]
        votes_sequence.append(
            (parser, ParserTier.BILL_CACHED, votes_has_parser)
        )
        added_votes_parsers.add(parser)
    # Tier 1: Committee-proven parsers
    committee_votes_parsers = cache.get_committee_parsers(
        row.committee_id,
        ParserInterface.ParserType.VOTES.value
    )
    for module_name in committee_votes_parsers:
        if module_name in VOTES_REGISTRY:
            parser = VOTES_REGISTRY[module_name]
            if parser not in added_votes_parsers:
                votes_sequence.append(
                    (parser, ParserTier.COMMITTEE_PROVEN, module_name)
                )
                added_votes_parsers.add(parser)
    # Tier 2: Remaining parsers by cost
    for parser in all_votes_parsers:
        if parser not in added_votes_parsers:
            module_name = parser.__module__
            votes_sequence.append(
                (parser, ParserTier.COST_FALLBACK, module_name)
            )
            added_votes_parsers.add(parser)
    # 3) Try parsers
    for p, tier, modname in votes_sequence:
        candidate = p.discover(base_url, row, cache, cfg)
        if not candidate:
            continue
        # Decide whether to prompt
        accepted = True
        needs_review = False
        if cfg.review_mode == "deferred" and deferred_session is not None:
            # Decide if we should consult LLM based on pattern confidence
            should_use_llm = should_use_llm_for_parser(
                modname,
                row.committee_id,
                ParserInterface.ParserType.VOTES.value,
                cache,
                tier,
                candidate
            )
            if should_use_llm:
                # Pattern not established or parser is suspicious - use LLM
                llm_decision = try_llm_decision(
                    candidate,
                    row.bill_id,
                    ParserInterface.ParserType.VOTES.value,
                    cfg
                )
                if llm_decision == "yes":
                    # LLM confidently accepts
                    accepted = True
                    needs_review = False
                elif llm_decision == "no":
                    # LLM confidently rejects - skip this parser
                    continue
                else:
                    # LLM returned "unsure" or is unavailable
                    # Fall back to confidence threshold logic
                    preview_text = (
                        candidate.full_text if candidate.full_text
                        else candidate.preview
                    )
                    confidence = (
                        candidate.confidence if candidate.confidence else 0.5
                    )
                    auto_yes = cfg.deferred_review.auto_accept_high_confidence
                    if confidence >= auto_yes:
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
            else:
                # Pattern confidence is high - trust it without LLM
                accepted = True
                needs_review = False
        elif cfg.review_mode == "on":
            # Use full_text if available, otherwise fall back to preview
            preview_text = (
                candidate.full_text
                if candidate.full_text
                else candidate.preview
            )
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
        result = VoteInfo(
            present=True,
            location=p.location,
            source_url=parsed.get("source_url"),
            parser_module=modname,
            needs_review=needs_review,
        )
        # Mark confirmation status:
        # - review_mode ON -> confirmed True (user explicitly accepted)
        # - review_mode OFF -> confirmed False (auto-accepted; will ask once
        # in a future interactive run)
        cache.set_result(
            row.bill_id,
            ParserInterface.ParserType.VOTES.value,
            modname,
            result.to_dict(),
            confirmed=cfg.review_mode == "on" and not needs_review
        )
        # Record success for committee-level learning
        cache.record_committee_parser(
            row.committee_id,
            ParserInterface.ParserType.VOTES.value,
            modname
        )
        return result
    # 4) Nothing landed
    return VoteInfo(
        present=False,
        location="unknown",
        source_url=None,
        parser_module=None,
        needs_review=False,
    )
