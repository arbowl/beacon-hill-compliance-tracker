"""Batch review session manager for deferred confirmations."""

import textwrap

from components.interfaces import Config
from components.models import DeferredReviewSession, DeferredConfirmation
from components.utils import Cache


def conduct_batch_review(
    session: DeferredReviewSession,
    config: Config,
    cache: Cache
) -> dict[str, bool]:
    """
    Present all deferred confirmations for batch review.
    Returns dict mapping confirmation_id -> accepted (bool)
    """
    if not session.confirmations:
        print("No confirmations needed for review.")
        return {}
    print(f"\n{'='*64}")
    print(f"BATCH REVIEW SESSION - Committee {session.committee_id}")
    print(f"{'='*64}")
    display_confirmation_summary(session)
    try:
        proceed = input(
            "\nPress Enter to begin review, or 'q' to quit: "
        ).strip().lower()
        if proceed == 'q':
            print("Review session cancelled.")
            return {}
    except (KeyboardInterrupt, EOFError):
        print("\nReview session cancelled.")
        return {}
    results = {}
    total = len(session.confirmations)
    confirmations = session.confirmations
    if config.deferred_review.group_by_bill:
        confirmations = sorted(confirmations, key=lambda c: c.bill_id)
    for i, confirmation in enumerate(confirmations, 1):
        try:
            result = review_single_confirmation(
                confirmation, i, total, config
            )
            results[confirmation.confirmation_id] = result
            if result:
                cache.set_parser(
                    confirmation.bill_id,
                    confirmation.parser_type,
                    confirmation.parser_module,
                    confirmed=True
                )
        except (KeyboardInterrupt, EOFError):
            print(
                f"\nReview session interrupted. Processed "
                f"{i-1} of {total} confirmations."
            )
            break
    return results


def display_confirmation_summary(session: DeferredReviewSession) -> None:
    """Show overview of all pending confirmations."""
    summary_count = session.get_summary_count()
    votes_count = session.get_votes_count()
    bill_count = len(session.get_bill_ids())
    print(
        f"Found {len(session.confirmations)} parser confirmations "
        "requiring review:"
    )
    if summary_count > 0:
        print(f"  - {summary_count} summaries ({bill_count} bills)")
    if votes_count > 0:
        print(f"  - {votes_count} vote records ({bill_count} bills)")
    bill_ids = session.get_bill_ids()
    if len(bill_ids) <= 10:
        print(f"\nBills: {', '.join(sorted(bill_ids))}")
    else:
        print(
            f"\nBills: {', '.join(sorted(bill_ids[:10]))} ..."
            f" and {len(bill_ids)-10} more"
        )


def review_single_confirmation(
    confirmation: DeferredConfirmation,
    index: int,
    total: int,
    config: Config
) -> bool:
    """
    Review one confirmation with context.
    Returns True if accepted, False if rejected.
    """
    print(f"\n{'='*64}")
    print(
        f"CONFIRMATION {index} of {total} - Bill "
        f"{confirmation.bill_id} ({confirmation.parser_type.title()})"
    )
    print(f"{'='*64}")
    print(f"Parser: {confirmation.parser_module}")
    if (
        config.deferred_review.show_confidence
        and confirmation.confidence is not None
    ):
        confidence_pct = int(confirmation.confidence * 100)
        confidence_label: str = (
            "High" if confirmation.confidence >= 0.8
            else "Medium" if confirmation.confidence >= 0.5
            else "Low"
        )
        print(f"Confidence: {confidence_label} ({confidence_pct}%)")
    source_url = confirmation.candidate.source_url
    if source_url:
        print(f"URL: {source_url}")
    if confirmation.preview_text:
        print("\nPreview:")
        print("-" * 64)
        wrapped_lines = []
        for line in confirmation.preview_text.split('\n'):
            if line.strip():
                wrapped_lines.extend(textwrap.wrap(line, width=80))
            else:
                wrapped_lines.append('')
        display_lines = wrapped_lines[:15]
        for line in display_lines:
            print(line)
        if len(wrapped_lines) > 15:
            print(f"\n... ({len(wrapped_lines) - 15} more lines)")
        print("-" * 64)
    print(f"{'='*64}")
    print("Options:")
    print("  [y] Accept this parser")
    print("  [n] Reject this parser")
    print("  [s] Skip (decide later)")
    print("  [a] Accept all remaining for this bill")
    print("  [q] Quit review session")
    print()
    while True:
        choice = input("Choice (y/n/s/a/q): ").strip().lower()
        if choice in ['y', 'yes']:
            return True
        elif choice in ['n', 'no']:
            return False
        elif choice in ['s', 'skip']:
            print("Skipped - will remain unconfirmed.")
            return False
        elif choice in ['a', 'all']:
            print(
                f"Accepting all remaining confirmations for bill "
                f"{confirmation.bill_id}"
            )
            return True
        elif choice in ['q', 'quit']:
            raise KeyboardInterrupt()
        else:
            print(
                "Please enter 'y' for yes, 'n' for no, 's' "
                "to skip, 'a' for accept all, or 'q' to quit."
            )


def apply_review_results(
    results: dict[str, bool],
    session: DeferredReviewSession,
    cache: Cache
) -> None:
    """Apply the review results to the cache system."""
    accepted_count = 0
    rejected_count = 0
    for confirmation in session.confirmations:
        confirmation_id = confirmation.confirmation_id
        if confirmation_id in results:
            accepted = results[confirmation_id]
            if accepted:
                cache.set_parser(
                    confirmation.bill_id,
                    confirmation.parser_type,
                    confirmation.parser_module,
                    confirmed=True
                )
                accepted_count += 1
            else:
                rejected_count += 1
    print("\nReview session complete:")
    print(f"  - Accepted: {accepted_count}")
    print(f"  - Rejected: {rejected_count}")
    print(
        f"  - Skipped: "
        f"{len(session.confirmations) - accepted_count - rejected_count}"
    )
