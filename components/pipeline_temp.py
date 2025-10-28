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

logger = logging.getLogger(__name__)


class ParserTier(IntEnum):
    """Parser priority tiers for intelligent selection."""
    BILL_CACHED = 0      # This specific bill used this parser before
    COMMITTEE_PROVEN = 1  # Parser has proven track record for committee
    COST_FALLBACK = 2    # Trying parsers by cost (no committee history)


# Maps the cache module name to the actual module object
SUMMARY_REGISTRY: dict[str, ParserInterface] = {
    module.__module__: module for module in [
        SummaryBillTabTextParser,
        SummaryCommitteePdfParser,
        SummaryHearingDocsPdfParser,
        SummaryHearingPdfParser,
        SummaryHearingDocsPdfContentParser,
        SummaryCommitteeDocxParser,
        SummaryHearingDocsDocxParser,
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
    parser_conf = candidate.confidence if candidate.confidence else 0.5
    if tier == ParserTier.BILL_CACHED:
        return parser_conf < 0.3
    if tier == ParserTier.COST_FALLBACK:
        return True
    if tier == ParserTier.COMMITTEE_PROVEN:
        committee_data = cache.data.get("committee_parsers", {}).get(
            committee_id, {}
        )
        parser_stats = committee_data.get(parser_type, {}).get(
            parser_module, {}
        )
        if not parser_stats:
            return True
        streak = parser_stats.get("current_streak", 0)
        count = parser_stats.get("count", 0)
        pattern_established = (streak >= 3 and count >= 5)
        if pattern_established:
            return parser_conf < 0.5
        else:
            return True
    return True


def try_llm_decision(
    candidate: ParserInterface.DiscoveryResult,
    bill_id: str,
    doc_type: str,
    config: dict
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
            cache.record_committee_parser(
                row.committee_id,
                ParserInterface.ParserType.SUMMARY.value,
                summary_has_parser
            )
            return result
    all_parsers: list[ParserInterface] = [
        parser
        for parser in SUMMARY_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.SUMMARY
    ]
    all_parsers.sort(key=lambda p: p.cost)
    parser_sequence: list[tuple[ParserInterface, ParserTier, str]] = []
    added_parsers = set()
    if summary_has_parser and summary_has_parser in SUMMARY_REGISTRY:
        parser = SUMMARY_REGISTRY[summary_has_parser]
        parser_sequence.append((parser, ParserTier.BILL_CACHED, summary_has_parser))
        added_parsers.add(parser)
    committee_parsers = cache.get_committee_parsers(
        row.committee_id,
        ParserInterface.ParserType.SUMMARY.value
    )
    for module_name in committee_parsers:
        if module_name in SUMMARY_REGISTRY:
            parser = SUMMARY_REGISTRY[module_name]
            if parser not in added_parsers:
                parser_sequence.append((parser, ParserTier.COMMITTEE_PROVEN, module_name))
                added_parsers.add(parser)
    for parser in all_parsers:
        if parser not in added_parsers:
            module_name = parser.__module__
            parser_sequence.append((parser, ParserTier.COST_FALLBACK, module_name))
            added_parsers.add(parser)
    for p, tier, modname in parser_sequence:
        candidate = p.discover(base_url, row, cache, cfg)
        if not candidate:
            continue
        accepted = True
        needs_review = False
        if cfg.review_mode == "deferred" and deferred_session is not None:
            should_use_llm = should_use_llm_for_parser(
                modname,
                row.committee_id,
                ParserInterface.ParserType.SUMMARY.value,
                cache,
                tier,
                candidate
            )
            if should_use_llm:
                llm_decision = try_llm_decision(
                    candidate,
                    row.bill_id,
                    ParserInterface.ParserType.SUMMARY.value,
                    cfg
                )
                if llm_decision == "yes":
                    accepted = True
                    needs_review = False
                elif llm_decision == "no":
                    continue
                else:
                    preview_text = (
                        candidate.full_text if candidate.full_text
                        else candidate.preview
                    )
                    confidence = (
                        candidate.confidence if candidate.confidence else 0.5
                    )
                    if confidence >= cfg.deferred_review.auto_accept_high_confidence:
                        accepted = True
                        needs_review = False
                    else:
                        confirmation = DeferredConfirmation(
                            confirmation_id="",
                            bill_id=row.bill_id,
                            parser_type=ParserInterface.ParserType.SUMMARY.value,
                            parser_module=modname,
                            candidate=candidate,
                            preview_text=preview_text,
                            confidence=confidence
                        )
                        deferred_session.add_confirmation(confirmation)
                        accepted = True
                        needs_review = True
            else:
                accepted = True
                needs_review = False
        elif cfg.review_mode == "on":
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
        else:
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
            cache.record_committee_parser(
                row.committee_id,
                ParserInterface.ParserType.VOTES.value,
                votes_has_parser
            )
            return result
    all_votes_parsers: list[ParserInterface] = [
        parser
        for parser in VOTES_REGISTRY.values()
        if parser.parser_type == ParserInterface.ParserType.VOTES
    ]
    all_votes_parsers.sort(key=lambda p: p.cost)
    votes_sequence: list[tuple[ParserInterface, ParserTier, str]] = []
    added_votes_parsers = set()
    if votes_has_parser and votes_has_parser in VOTES_REGISTRY:
        parser = VOTES_REGISTRY[votes_has_parser]
        votes_sequence.append((parser, ParserTier.BILL_CACHED, votes_has_parser))
        added_votes_parsers.add(parser)
    committee_votes_parsers = cache.get_committee_parsers(
        row.committee_id,
        ParserInterface.ParserType.VOTES.value
    )
    for module_name in committee_votes_parsers:
        if module_name in VOTES_REGISTRY:
            parser = VOTES_REGISTRY[module_name]
            if parser not in added_votes_parsers:
                votes_sequence.append((parser, ParserTier.COMMITTEE_PROVEN, module_name))
                added_votes_parsers.add(parser)
    for parser in all_votes_parsers:
        if parser not in added_votes_parsers:
            module_name = parser.__module__
            votes_sequence.append((parser, ParserTier.COST_FALLBACK, module_name))
            added_votes_parsers.add(parser)
    for p, tier, modname in votes_sequence:
        candidate = p.discover(base_url, row, cache, cfg)
        if not candidate:
            continue
        accepted = True
        needs_review = False
        if cfg.review_mode == "deferred" and deferred_session is not None:
            should_use_llm = should_use_llm_for_parser(
                modname,
                row.committee_id,
                ParserInterface.ParserType.VOTES.value,
                cache,
                tier,
                candidate
            )
            if should_use_llm:
                llm_decision = try_llm_decision(
                    candidate,
                    row.bill_id,
                    ParserInterface.ParserType.VOTES.value,
                    cfg
                )
                if llm_decision == "yes":
                    accepted = True
                    needs_review = False
                elif llm_decision == "no":
                    continue
                else:
                    preview_text = (
                        candidate.full_text if candidate.full_text
                        else candidate.preview
                    )
                    confidence = (
                        candidate.confidence if candidate.confidence else 0.5
                    )
                    if confidence >= cfg.deferred_review.auto_accept_high_confidence:
                        accepted = True
                        needs_review = False
                    else:
                        confirmation = DeferredConfirmation(
                            confirmation_id="",
                            bill_id=row.bill_id,
                            parser_type=ParserInterface.ParserType.VOTES.value,
                            parser_module=modname,
                            candidate=candidate,
                            preview_text=preview_text,
                            confidence=confidence
                        )
                        deferred_session.add_confirmation(confirmation)
                        accepted = True
                        needs_review = True
            else:
                accepted = True
                needs_review = False
        elif cfg.review_mode == "on":
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
        else:
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
        cache.set_result(
            row.bill_id,
            ParserInterface.ParserType.VOTES.value,
            modname,
            result.to_dict(),
            confirmed=cfg.review_mode == "on" and not needs_review
        )
        cache.record_committee_parser(
            row.committee_id,
            ParserInterface.ParserType.VOTES.value,
            modname
        )
        return result
    return VoteInfo(
        present=False,
        location="unknown",
        source_url=None,
        parser_module=None,
        needs_review=False,
    )
