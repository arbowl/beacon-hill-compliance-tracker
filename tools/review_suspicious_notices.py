"""Interactive review tool for suspicious hearing notices.

This tool provides a terminal-based interface for domain experts to quickly
review and classify suspicious hearing notices as either clerical corrections
or actual violations.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("Warning: 'rich' library not available. Install with: pip install rich")
    print("Falling back to basic console interface.\n")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReviewDecision:
    """Represents a review decision."""
    
    def __init__(
        self,
        bill_id: str,
        determination: str,  # "clerical" or "violation"
        notes: str = "",
        apply_to_group: bool = False,
        reviewer: str = "analyst",
    ):
        self.bill_id = bill_id
        self.determination = determination
        self.notes = notes
        self.apply_to_group = apply_to_group
        self.reviewer = reviewer
        self.timestamp = datetime.now()
    
    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "bill_id": self.bill_id,
            "determination": self.determination,
            "notes": self.notes,
            "apply_to_group": self.apply_to_group,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp.isoformat(),
        }


class SuspiciousNoticeReviewer:
    """Interactive review tool for suspicious hearing notices."""
    
    def __init__(
        self,
        dataset_path: str,
        output_path: str = "review/completed_reviews.jsonl",
        reviewer_name: str = "analyst",
    ):
        """Initialize reviewer.
        
        Args:
            dataset_path: Path to aggregated dataset JSON
            output_path: Path to save completed reviews
            reviewer_name: Name/ID of the reviewer
        """
        self.dataset_path = Path(dataset_path)
        self.output_path = Path(output_path)
        self.reviewer_name = reviewer_name
        
        # Load dataset
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)
        
        self.groups = self.dataset.get("signature_groups", [])
        self.current_group_idx = 0
        self.current_case_idx = 0
        
        # Setup output
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Setup console
        if RICH_AVAILABLE:
            self.console = Console()
        else:
            self.console = None
    
    def has_pending_cases(self) -> bool:
        """Check if there are pending cases to review."""
        for group in self.groups[self.current_group_idx:]:
            pending = [c for c in group["cases"] if c["review_status"]["determination"] == "pending"]
            if pending:
                return True
        return False
    
    def get_current_case(self) -> Optional[dict]:
        """Get the current case to review."""
        if self.current_group_idx >= len(self.groups):
            return None
        
        group = self.groups[self.current_group_idx]
        pending_cases = [
            c for c in group["cases"]
            if c["review_status"]["determination"] == "pending"
        ]
        
        if self.current_case_idx >= len(pending_cases):
            # Move to next group
            self.current_group_idx += 1
            self.current_case_idx = 0
            return self.get_current_case()
        
        return pending_cases[self.current_case_idx]
    
    def get_current_group(self) -> Optional[dict]:
        """Get the current signature group."""
        if self.current_group_idx >= len(self.groups):
            return None
        return self.groups[self.current_group_idx]
    
    def display_case(self, case: dict, group: dict) -> None:
        """Display a case for review."""
        if RICH_AVAILABLE:
            self._display_case_rich(case, group)
        else:
            self._display_case_basic(case, group)
    
    def _display_case_rich(self, case: dict, group: dict) -> None:
        """Display case using rich formatting."""
        self.console.clear()
        
        # Header
        meta = self.dataset["metadata"]
        progress = f"{meta['reviewed_count']}/{meta['total_cases']} reviewed ({meta['reviewed_count']/meta['total_cases']*100:.0f}%)"
        
        self.console.print(Panel(
            f"[bold]Suspicious Hearing Notice Review Tool[/bold]\n\n"
            f"Progress: {progress} | "
            f"Group {self.current_group_idx + 1}/{len(self.groups)}",
            style="cyan"
        ))
        
        # Group info
        pending_in_group = len([c for c in group["cases"] if c["review_status"]["determination"] == "pending"])
        conf = group.get("confidence_score")
        conf_str = f"{conf:.0%}" if conf is not None else "N/A"
        
        self.console.print(f"\n[yellow]GROUP {self.current_group_idx + 1}:[/yellow] {group['pattern_description']}")
        self.console.print(
            f"Cases: {group['case_count']} | "
            f"Reviewed: {group['reviewed_count']} ({conf_str} clerical) | "
            f"Pending: {pending_in_group}"
        )
        
        # Bill details
        self.console.print(f"\n[bold cyan]BILL DETAILS[/bold cyan]")
        bill_table = Table(show_header=False, box=None, padding=(0, 2))
        bill_table.add_row("Bill ID:", f"[bold]{case['bill_id']}[/bold]")
        bill_table.add_row("Committee:", f"{case['committee_id']} - {case['committee_name']}")
        bill_table.add_row("URL:", case['bill_url'])
        self.console.print(bill_table)
        
        # Timeline
        self.console.print(f"\n[bold cyan]TIMELINE OF HEARING ACTIONS[/bold cyan]")
        timeline_table = Table(show_header=True, box=None)
        timeline_table.add_column("Date", style="cyan")
        timeline_table.add_column("Action", style="white")
        timeline_table.add_column("Notice", style="yellow")
        
        # Add prior announcement if exists
        if "prior_announcement" in case:
            prior = case["prior_announcement"]
            timeline_table.add_row(
                prior["announcement_date"],
                "SCHEDULED ✓",
                f"{prior['notice_days']} days"
            )
        
        # Add action sequence
        for action in case["timeline_summary"]["action_sequence"]:
            notice_str = f"{action['notice_days']} days"
            if action['notice_days'] < 0:
                notice_str += " ⚠️"
            elif action['notice_days'] == 0:
                notice_str += " ⚠️"
            
            timeline_table.add_row(
                action["announcement_date"],
                action["action_type"],
                notice_str
            )
        
        self.console.print(timeline_table)
        
        # Problematic hearing highlight
        prob = case["problematic_hearing"]
        self.console.print(f"\n[red bold]⚠️  FLAGGED ACTION:[/red bold]")
        self.console.print(f'  "{prob["raw_text"]}"')
        self.console.print(f"  Notice: [red]{prob['notice_days']} days[/red]")
        
        # Analysis
        self.console.print(f"\n[bold cyan]ANALYSIS[/bold cyan]")
        analysis_points = []
        
        if "prior_announcement" in case:
            analysis_points.append(f"✓ Prior valid notice existed ({case['prior_announcement']['notice_days']} days)")
        else:
            analysis_points.append("✗ No prior valid notice found")
        
        if case["evidence"].get("time_changed"):
            analysis_points.append("✓ Same-day time change detected")
        
        if case["evidence"].get("text_contains_virtual"):
            analysis_points.append("✓ Virtual option mentioned")
        
        if prob["notice_days"] < 0:
            days_after = abs(prob["notice_days"])
            analysis_points.append(f"✗ Retroactive: recorded {days_after} day(s) AFTER hearing")
        elif prob["notice_days"] == 0:
            analysis_points.append("✗ Same-day: announced day of hearing")
        
        for point in analysis_points:
            self.console.print(f"  {point}")
        
        # Likely scenario
        if "prior_announcement" in case and case["evidence"].get("time_changed"):
            self.console.print(
                f"\n[dim]Likely scenario: Staff corrected the record after hearing "
                f"to reflect actual time/details.[/dim]"
            )
        
        # Whitelist info
        if case.get("whitelist_pattern_id"):
            self.console.print(
                f"\n[green]Note: Matches whitelist pattern {case['whitelist_pattern_id']}[/green]"
            )
    
    def _display_case_basic(self, case: dict, group: dict) -> None:
        """Display case using basic text formatting."""
        print("\n" + "="*70)
        print(f"GROUP {self.current_group_idx + 1}: {group['pattern_description']}")
        print(f"Cases: {group['case_count']} | Reviewed: {group['reviewed_count']}")
        print("="*70)
        
        print(f"\nBill: {case['bill_id']}")
        print(f"Committee: {case['committee_id']}")
        print(f"URL: {case['bill_url']}")
        
        print("\nTIMELINE:")
        if "prior_announcement" in case:
            prior = case["prior_announcement"]
            print(f"  {prior['announcement_date']} | SCHEDULED | {prior['notice_days']} days")
        
        for action in case["timeline_summary"]["action_sequence"]:
            warning = " ⚠️" if action['notice_days'] <= 0 else ""
            print(f"  {action['announcement_date']} | {action['action_type']} | {action['notice_days']} days{warning}")
        
        prob = case["problematic_hearing"]
        print(f"\nFLAGGED: {prob['raw_text']}")
        print(f"Notice: {prob['notice_days']} days")
        print("-"*70)
    
    def get_user_decision(self) -> Optional[ReviewDecision]:
        """Get user's decision for current case."""
        case = self.get_current_case()
        group = self.get_current_group()
        
        if not case or not group:
            return None
        
        if RICH_AVAILABLE:
            self.console.print(f"\n[bold green]Is this a CLERICAL correction or actual VIOLATION?[/bold green]\n")
            self.console.print("[C] Clerical - Mark as clerical (not a violation)")
            self.console.print("[V] Violation - Mark as actual compliance violation")
            self.console.print("[S] Skip - Skip for now, review later")
            self.console.print("[N] Note - Add a note before deciding")
            self.console.print("[G] Group - Apply decision to ALL remaining in this group")
            self.console.print("[Q] Quit - Save progress and exit")
            self.console.print("[?] Help - Show detailed help\n")
            
            choice = Prompt.ask("Your choice", choices=["c", "C", "v", "V", "s", "S", "n", "N", "g", "G", "q", "Q", "?"])
        else:
            print("\n[C]lerical | [V]iolation | [S]kip | [N]ote | [G]roup | [Q]uit")
            choice = input("Your choice: ").strip().lower()
        
        choice = choice.lower()
        
        if choice == "?":
            self._show_help()
            return self.get_user_decision()
        
        if choice == "q":
            if RICH_AVAILABLE:
                self.console.print("[yellow]Saving progress and exiting...[/yellow]")
            else:
                print("Saving progress and exiting...")
            return None
        
        if choice == "s":
            # Skip - move to next case
            self.current_case_idx += 1
            return self.get_user_decision()
        
        if choice == "n":
            # Add note
            if RICH_AVAILABLE:
                note = Prompt.ask("Enter note")
            else:
                note = input("Enter note: ").strip()
            # Continue to get decision
            return self.get_user_decision()
        
        determination = None
        apply_to_group = False
        
        if choice == "c":
            determination = "clerical"
        elif choice == "v":
            determination = "violation"
        elif choice == "g":
            # Group decision
            if RICH_AVAILABLE:
                group_choice = Prompt.ask(
                    "Apply [C]lerical or [V]iolation to all remaining?",
                    choices=["c", "C", "v", "V"]
                )
            else:
                group_choice = input("Apply [C]lerical or [V]iolation to all? ").strip().lower()
            
            determination = "clerical" if group_choice.lower() == "c" else "violation"
            apply_to_group = True
        else:
            if RICH_AVAILABLE:
                self.console.print("[red]Invalid choice. Please try again.[/red]")
            else:
                print("Invalid choice. Please try again.")
            return self.get_user_decision()
        
        # Optional note
        note = ""
        if RICH_AVAILABLE and not apply_to_group:
            if Prompt.ask("Add a note?", choices=["y", "n"], default="n") == "y":
                note = Prompt.ask("Note")
        
        return ReviewDecision(
            bill_id=case["bill_id"],
            determination=determination,
            notes=note,
            apply_to_group=apply_to_group,
            reviewer=self.reviewer_name,
        )
    
    def _show_help(self) -> None:
        """Display detailed help."""
        if RICH_AVAILABLE:
            self.console.print(Panel(
                "[bold]Review Tool Help[/bold]\n\n"
                "[C]lerical: The notice issue is a clerical correction, not a violation.\n"
                "  Example: Time shortened on day-of, record updated retroactively\n\n"
                "[V]iolation: This is an actual compliance violation.\n"
                "  Example: Hearing genuinely rescheduled without proper notice\n\n"
                "[S]kip: Skip this case for now, come back later\n\n"
                "[N]ote: Add a note about this case\n\n"
                "[G]roup: Apply your decision to ALL remaining cases in this group\n"
                "  Use when you've reviewed enough to be confident about the pattern\n\n"
                "[Q]uit: Save your progress and exit\n\n"
                "Your reviews are saved immediately to completed_reviews.jsonl",
                style="cyan"
            ))
        else:
            print("\n" + "="*70)
            print("HELP")
            print("="*70)
            print("[C]lerical: The notice is a clerical correction")
            print("[V]iolation: This is an actual compliance violation")
            print("[S]kip: Skip for now")
            print("[N]ote: Add a note")
            print("[G]roup: Apply decision to all remaining in group")
            print("[Q]uit: Save and exit")
            print("="*70)
        
        input("\nPress Enter to continue...")
    
    def apply_decision(self, decision: ReviewDecision) -> None:
        """Apply a review decision and save it."""
        group = self.get_current_group()
        
        if decision.apply_to_group:
            # Apply to all pending cases in group
            pending_cases = [
                c for c in group["cases"]
                if c["review_status"]["determination"] == "pending"
            ]
            
            for case in pending_cases:
                case_decision = ReviewDecision(
                    bill_id=case["bill_id"],
                    determination=decision.determination,
                    notes=decision.notes,
                    apply_to_group=True,
                    reviewer=decision.reviewer,
                )
                self._save_decision(case_decision)
                case["review_status"]["determination"] = decision.determination
                case["review_status"]["reviewed"] = True
            
            # Move to next group
            self.current_group_idx += 1
            self.current_case_idx = 0
            
            # Update metadata
            self.dataset["metadata"]["reviewed_count"] += len(pending_cases)
            self.dataset["metadata"]["unreviewed_count"] -= len(pending_cases)
            
            if RICH_AVAILABLE:
                self.console.print(
                    f"[green]Applied {decision.determination} to {len(pending_cases)} cases[/green]"
                )
            else:
                print(f"Applied {decision.determination} to {len(pending_cases)} cases")
        else:
            # Apply to current case only
            case = self.get_current_case()
            self._save_decision(decision)
            case["review_status"]["determination"] = decision.determination
            case["review_status"]["reviewed"] = True
            
            # Move to next case
            self.current_case_idx += 1
            
            # Update metadata
            self.dataset["metadata"]["reviewed_count"] += 1
            self.dataset["metadata"]["unreviewed_count"] -= 1
    
    def _save_decision(self, decision: ReviewDecision) -> None:
        """Save a decision to the output file."""
        with open(self.output_path, "a", encoding="utf-8") as f:
            json.dump(decision.to_dict(), f)
            f.write("\n")
        
        logger.debug(f"Saved decision for {decision.bill_id}: {decision.determination}")
    
    def run(self) -> None:
        """Main review loop."""
        if RICH_AVAILABLE:
            self.console.print(
                Panel(
                    "[bold cyan]Welcome to the Suspicious Notice Review Tool[/bold cyan]\n\n"
                    f"Loaded {self.dataset['metadata']['total_cases']} cases in "
                    f"{len(self.groups)} groups\n\n"
                    "Press Enter to begin review...",
                    style="green"
                )
            )
        else:
            print("\n" + "="*70)
            print("SUSPICIOUS NOTICE REVIEW TOOL")
            print("="*70)
            print(f"Loaded {self.dataset['metadata']['total_cases']} cases")
            print("="*70)
        
        input()
        
        while self.has_pending_cases():
            case = self.get_current_case()
            group = self.get_current_group()
            
            if not case or not group:
                break
            
            self.display_case(case, group)
            decision = self.get_user_decision()
            
            if decision is None:
                # User quit
                break
            
            self.apply_decision(decision)
        
        self.show_summary()
    
    def show_summary(self) -> None:
        """Show final summary."""
        meta = self.dataset["metadata"]
        
        if RICH_AVAILABLE:
            self.console.print(
                Panel(
                    f"[bold green]Review Session Complete[/bold green]\n\n"
                    f"Reviewed: {meta['reviewed_count']}/{meta['total_cases']} cases\n"
                    f"Remaining: {meta['unreviewed_count']} cases\n\n"
                    f"Decisions saved to: {self.output_path}",
                    style="cyan"
                )
            )
        else:
            print("\n" + "="*70)
            print("REVIEW COMPLETE")
            print("="*70)
            print(f"Reviewed: {meta['reviewed_count']}/{meta['total_cases']}")
            print(f"Remaining: {meta['unreviewed_count']}")
            print(f"Saved to: {self.output_path}")
            print("="*70 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Interactive review tool for suspicious hearing notices"
    )
    parser.add_argument(
        "--dataset",
        default="review/pending_notices.json",
        help="Path to aggregated dataset (default: review/pending_notices.json)"
    )
    parser.add_argument(
        "--output",
        default="review/completed_reviews.jsonl",
        help="Path to save reviews (default: review/completed_reviews.jsonl)"
    )
    parser.add_argument(
        "--reviewer",
        default="analyst",
        help="Reviewer name/ID (default: analyst)"
    )
    
    args = parser.parse_args()
    
    try:
        reviewer = SuspiciousNoticeReviewer(
            dataset_path=args.dataset,
            output_path=args.output,
            reviewer_name=args.reviewer,
        )
        reviewer.run()
        return 0
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Progress has been saved.")
        return 0
    except Exception as e:
        logger.error(f"Review failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

