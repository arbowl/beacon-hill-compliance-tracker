#!/usr/bin/env python3
"""
Analyze compliance decay timeline: when and how bills fail compliance.

This script reads JSON compliance data and explores:
1. When bills "go bad" - timing of compliance failures after hearings
2. Which requirements fail most often and when
3. Hazard curves showing probability of failure over time
4. Early warning indicators for at-risk bills

Dependencies:
    pip install matplotlib numpy pandas

Usage:
    python tools/compliance_decay_analysis.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.gridspec import GridSpec

# Try to import pandas
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Note: pandas not available, using basic data structures")


def parse_committee_id(filename: str) -> Optional[str]:
    """Extract committee ID from filename like 'basic_J14.json' -> 'J14'"""
    match = re.search(r"basic_([A-Z]\d+)\.json", filename)
    return match.group(1) if match else None


def parse_date(date_str: str) -> Optional[date]:
    """Parse date string in YYYY-MM-DD format"""
    if not date_str or date_str == "None":
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def analyze_failure_reasons(reason: str) -> Dict[str, bool]:
    """
    Parse the reason field to identify which requirements failed.
    
    Returns dict with failure flags:
    - missed_deadline: Bill not reported out by deadline or reported late
    - no_votes: Votes not posted
    - no_summary: Summary not posted
    - insufficient_notice: Less than 10 days notice
    """
    failures = {
        'missed_deadline': False,
        'no_votes': False,
        'no_summary': False,
        'insufficient_notice': False
    }
    
    if not reason:
        return failures
    
    reason_lower = reason.lower()
    
    # Check for deadline failures
    if 'not reported out' in reason_lower or 'reported out late' in reason_lower:
        failures['missed_deadline'] = True
    
    # Check for votes
    if 'no votes' in reason_lower:
        failures['no_votes'] = True
    
    # Check for summary (though this is less common in your data)
    if 'no summar' in reason_lower:
        failures['no_summary'] = True
    
    # Check for notice
    if 'insufficient notice' in reason_lower or 'notice:' in reason_lower:
        # Extract the actual notice days if mentioned
        if 'insufficient notice:' in reason_lower:
            failures['insufficient_notice'] = True
    
    return failures


def load_bill_lifecycle_data(json_dir: Path) -> List[Dict]:
    """
    Load all bills with their lifecycle events and failure points.
    
    Returns list of bill records with timeline information.
    """
    bills = []
    
    json_files = list(json_dir.glob("basic_*.json"))
    print(f"Found {len(json_files)} committee JSON files")
    
    for json_file in json_files:
        committee_id = parse_committee_id(json_file.name)
        if not committee_id:
            continue
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                committee_bills = data.get('bills', [])
                
                for bill in committee_bills:
                    hearing_date = parse_date(bill.get('hearing_date'))
                    if not hearing_date:
                        continue
                    
                    deadline_60 = parse_date(bill.get('deadline_60'))
                    effective_deadline = parse_date(bill.get('effective_deadline'))
                    reported_out_date = parse_date(bill.get('reported_out_date'))
                    
                    state = bill.get('state', 'Unknown')
                    reason = bill.get('reason', '')
                    
                    # Skip unknown/pending bills for decay analysis
                    if state == 'Unknown':
                        continue
                    
                    # Analyze what failed
                    failures = analyze_failure_reasons(reason)
                    
                    # Calculate timeline metrics
                    bill_record = {
                        'bill_id': bill.get('bill_id'),
                        'committee_id': committee_id,
                        'hearing_date': hearing_date,
                        'deadline_60': deadline_60,
                        'effective_deadline': effective_deadline,
                        'reported_out_date': reported_out_date,
                        'reported_out': bill.get('reported_out', False),
                        'summary_present': bill.get('summary_present', False),
                        'votes_present': bill.get('votes_present', False),
                        'notice_gap_days': bill.get('notice_gap_days'),
                        'state': state,
                        'reason': reason,
                        'failures': failures
                    }
                    
                    # Calculate days until failure event
                    if state == 'Non-Compliant':
                        # Determine when failure occurred
                        failure_date = None
                        failure_type = None
                        
                        # Notice failure happens at hearing time (day 0)
                        if failures['insufficient_notice']:
                            failure_date = hearing_date
                            failure_type = 'insufficient_notice'
                        
                        # Deadline failure: happens at the deadline
                        elif failures['missed_deadline'] and effective_deadline:
                            if reported_out_date and reported_out_date > effective_deadline:
                                # Late report-out
                                failure_date = reported_out_date
                                failure_type = 'late_report'
                            else:
                                # Never reported out - failure at deadline
                                failure_date = effective_deadline
                                failure_type = 'missed_deadline'
                        
                        # Documentation failures: harder to pinpoint exactly when
                        # Use reported_out_date if available, otherwise deadline
                        elif failures['no_votes'] or failures['no_summary']:
                            if reported_out_date:
                                failure_date = reported_out_date
                            elif effective_deadline:
                                failure_date = effective_deadline
                            failure_type = 'no_documentation'
                        
                        if failure_date:
                            days_to_failure = (failure_date - hearing_date).days
                            bill_record['days_to_failure'] = days_to_failure
                            bill_record['failure_date'] = failure_date
                            bill_record['failure_type'] = failure_type
                    
                    bills.append(bill_record)
        
        except Exception as e:
            print(f"  Error loading {json_file.name}: {e}")
    
    print(f"Loaded {len(bills)} bills with lifecycle data")
    return bills


def calculate_decay_metrics(bills: List[Dict]) -> Dict:
    """
    Calculate compliance decay metrics and survival curves.
    """
    metrics = {
        'compliant_bills': [],
        'non_compliant_bills': [],
        'failure_times': [],
        'failure_types': Counter(),
        'failure_combinations': Counter()
    }
    
    for bill in bills:
        if bill['state'] == 'Compliant':
            metrics['compliant_bills'].append(bill)
        elif bill['state'] == 'Non-Compliant':
            metrics['non_compliant_bills'].append(bill)
            
            if 'days_to_failure' in bill:
                metrics['failure_times'].append(bill['days_to_failure'])
                metrics['failure_types'][bill.get('failure_type', 'unknown')] += 1
            
            # Track failure combinations
            failures = bill['failures']
            failure_combo = tuple(sorted([k for k, v in failures.items() if v]))
            if failure_combo:
                metrics['failure_combinations'][failure_combo] += 1
    
    return metrics


def plot_survival_curve(bills: List[Dict], metrics: Dict, output_dir: Path):
    """
    Chart 1: Survival curve showing probability of remaining compliant over time
    """
    non_compliant = metrics['non_compliant_bills']
    
    if not non_compliant:
        print("No non-compliant bills to analyze")
        return
    
    # Get all failure times
    failure_times = [b['days_to_failure'] for b in non_compliant if 'days_to_failure' in b]
    
    if not failure_times:
        print("No failure time data available")
        return
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    
    # Chart 1a: Survival curve
    max_days = max(failure_times)
    days = np.arange(0, max_days + 1)
    
    # Calculate survival probability at each day
    total_bills = len(metrics['compliant_bills']) + len(non_compliant)
    survival_prob = []
    
    for day in days:
        failures_by_day = sum(1 for t in failure_times if t <= day)
        survival = (total_bills - failures_by_day) / total_bills * 100
        survival_prob.append(survival)
    
    ax1.plot(days, survival_prob, linewidth=3, color='darkblue', label='Survival Probability')
    ax1.fill_between(days, survival_prob, alpha=0.3, color='lightblue')
    
    # Add key milestones
    ax1.axvline(x=60, color='red', linestyle='--', linewidth=2, alpha=0.7, label='60-Day Deadline')
    ax1.axvline(x=90, color='orange', linestyle='--', linewidth=2, alpha=0.7, label='90-Day Extension')
    
    ax1.set_xlabel('Days After Hearing', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Probability of Remaining Compliant (%)', fontsize=12, fontweight='bold')
    ax1.set_title(
        'Bill Compliance Survival Curve\nHow long do bills stay compliant?',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax1.legend(loc='lower left', fontsize=11)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 105)
    
    # Add annotations for key points
    survival_at_60 = survival_prob[60] if len(survival_prob) > 60 else survival_prob[-1]
    ax1.annotate(
        f'{survival_at_60:.1f}% survive to 60 days',
        xy=(60, survival_at_60),
        xytext=(70, survival_at_60 + 10),
        fontsize=10,
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
        arrowprops=dict(arrowstyle='->', color='red', lw=1.5)
    )
    
    # Chart 1b: Hazard rate (failure density)
    bin_width = 7  # Weekly bins
    bins = np.arange(0, max_days + bin_width, bin_width)
    
    counts, edges = np.histogram(failure_times, bins=bins)
    # Normalize to get failure rate
    total_at_risk = len(failure_times)
    failure_rate = (counts / total_at_risk) * 100
    
    bin_centers = (edges[:-1] + edges[1:]) / 2
    
    ax2.bar(bin_centers, failure_rate, width=bin_width * 0.8, 
            alpha=0.7, color='coral', edgecolor='black')
    
    ax2.axvline(x=60, color='red', linestyle='--', linewidth=2, alpha=0.7, label='60-Day Deadline')
    ax2.axvline(x=90, color='orange', linestyle='--', linewidth=2, alpha=0.7, label='90-Day Extension')
    
    ax2.set_xlabel('Days After Hearing', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Failure Rate (% of non-compliant bills)', fontsize=12, fontweight='bold')
    ax2.set_title(
        'Compliance Failure Hazard Rate\nWhen do bills fail compliance?',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax2.legend(loc='upper right', fontsize=11)
    ax2.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    output_file = output_dir / "chart1_compliance_survival_curve.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_failure_types(metrics: Dict, output_dir: Path):
    """
    Chart 2: Breakdown of failure types and combinations
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    
    # Chart 2a: Primary failure types
    failure_types = metrics['failure_types']
    
    if failure_types:
        types = []
        counts = []
        labels_map = {
            'insufficient_notice': 'Insufficient Notice\n(<10 days)',
            'missed_deadline': 'Missed Deadline\n(Not reported out)',
            'late_report': 'Late Report-Out\n(After deadline)',
            'no_documentation': 'Missing Documentation\n(Votes/Summary)',
            'unknown': 'Unknown'
        }
        
        for failure_type, count in failure_types.most_common():
            types.append(labels_map.get(failure_type, failure_type))
            counts.append(count)
        
        colors = ['#ff6b6b', '#ee5a6f', '#c44569', '#f97c7c', '#cccccc']
        bars = ax1.barh(range(len(types)), counts, alpha=0.8, 
                       color=colors[:len(types)], edgecolor='black')
        
        ax1.set_yticks(range(len(types)))
        ax1.set_yticklabels(types, fontsize=10)
        ax1.set_xlabel('Number of Bills', fontsize=12, fontweight='bold')
        ax1.set_title(
            'Primary Failure Types\nWhat causes bills to fail first?',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        ax1.grid(axis='x', alpha=0.3)
        
        # Add value labels
        for i, count in enumerate(counts):
            pct = count / sum(counts) * 100
            ax1.text(count + max(counts) * 0.02, i, f'{count} ({pct:.1f}%)',
                    va='center', fontsize=10, fontweight='bold')
    
    # Chart 2b: Failure combinations (which requirements fail together)
    failure_combos = metrics['failure_combinations']
    
    if failure_combos:
        combos = []
        combo_counts = []
        
        combo_labels = {
            'missed_deadline': 'Deadline',
            'no_votes': 'Votes',
            'no_summary': 'Summary',
            'insufficient_notice': 'Notice'
        }
        
        for combo, count in failure_combos.most_common(10):
            if combo:  # Skip empty tuples
                combo_label = '\n+ '.join([combo_labels.get(f, f) for f in combo])
                combos.append(combo_label)
                combo_counts.append(count)
        
        if combos:
            colors_combo = plt.cm.Reds(np.linspace(0.4, 0.9, len(combos)))
            bars = ax2.barh(range(len(combos)), combo_counts, alpha=0.8,
                           color=colors_combo, edgecolor='black')
            
            ax2.set_yticks(range(len(combos)))
            ax2.set_yticklabels(combos, fontsize=9)
            ax2.set_xlabel('Number of Bills', fontsize=12, fontweight='bold')
            ax2.set_title(
                'Failure Combinations\nWhich requirements fail together?',
                fontsize=14,
                fontweight='bold',
                pad=20
            )
            ax2.grid(axis='x', alpha=0.3)
            
            # Add value labels
            for i, count in enumerate(combo_counts):
                pct = count / sum(combo_counts) * 100
                ax2.text(count + max(combo_counts) * 0.02, i, f'{count} ({pct:.1f}%)',
                        va='center', fontsize=9, fontweight='bold')
    
    plt.tight_layout()
    output_file = output_dir / "chart2_failure_types.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_failure_timeline_by_type(bills: List[Dict], metrics: Dict, output_dir: Path):
    """
    Chart 3: When different types of failures occur
    """
    non_compliant = metrics['non_compliant_bills']
    
    # Group failures by type with timing
    failure_data = defaultdict(list)
    
    for bill in non_compliant:
        if 'days_to_failure' in bill:
            failure_type = bill.get('failure_type', 'unknown')
            days = bill['days_to_failure']
            failure_data[failure_type].append(days)
    
    if not failure_data:
        print("No failure timeline data")
        return
    
    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(3, 1, figure=fig, hspace=0.3)
    
    # Chart 3a: Cumulative failures by type over time
    ax1 = fig.add_subplot(gs[0:2, :])
    
    max_days = max(max(times) for times in failure_data.values() if times)
    days = np.arange(0, min(max_days + 1, 200))  # Cap at 200 days for visibility
    
    type_labels = {
        'insufficient_notice': 'Insufficient Notice',
        'missed_deadline': 'Missed Deadline',
        'late_report': 'Late Report-Out',
        'no_documentation': 'Missing Documentation',
        'unknown': 'Unknown'
    }
    
    colors = {
        'insufficient_notice': '#e74c3c',
        'missed_deadline': '#e67e22',
        'late_report': '#f39c12',
        'no_documentation': '#3498db',
        'unknown': '#95a5a6'
    }
    
    for failure_type, times in sorted(failure_data.items()):
        cumulative = []
        for day in days:
            cum_count = sum(1 for t in times if t <= day)
            cumulative.append(cum_count)
        
        label = type_labels.get(failure_type, failure_type)
        color = colors.get(failure_type, '#95a5a6')
        
        ax1.plot(days, cumulative, linewidth=2.5, label=label, color=color, alpha=0.8)
    
    # Add milestone lines
    ax1.axvline(x=60, color='red', linestyle='--', linewidth=2, alpha=0.5, label='60-Day Deadline')
    ax1.axvline(x=90, color='orange', linestyle='--', linewidth=2, alpha=0.5, label='90-Day Extension')
    
    ax1.set_xlabel('Days After Hearing', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Cumulative Failures', fontsize=12, fontweight='bold')
    ax1.set_title(
        'Cumulative Compliance Failures by Type Over Time\nWhen do different failure types occur?',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax1.legend(loc='upper left', fontsize=11, ncol=2)
    ax1.grid(True, alpha=0.3)
    
    # Chart 3b: Box plot of failure timing by type
    ax2 = fig.add_subplot(gs[2, :])
    
    box_data = []
    box_labels = []
    box_colors = []
    
    for failure_type in sorted(failure_data.keys()):
        times = failure_data[failure_type]
        if times:
            box_data.append(times)
            box_labels.append(type_labels.get(failure_type, failure_type))
            box_colors.append(colors.get(failure_type, '#95a5a6'))
    
    bp = ax2.boxplot(box_data, labels=box_labels, vert=False, patch_artist=True,
                     showmeans=True, meanline=True)
    
    # Color the boxes
    for patch, color in zip(bp['boxes'], box_colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    # Add milestone lines
    ax2.axvline(x=60, color='red', linestyle='--', linewidth=2, alpha=0.5)
    ax2.axvline(x=90, color='orange', linestyle='--', linewidth=2, alpha=0.5)
    
    ax2.set_xlabel('Days After Hearing', fontsize=12, fontweight='bold')
    ax2.set_title(
        'Failure Timing Distribution by Type\n(box = IQR, line = median, diamond = mean)',
        fontsize=13,
        fontweight='bold',
        pad=15
    )
    ax2.grid(axis='x', alpha=0.3)
    
    plt.suptitle('Compliance Failure Timeline Analysis', fontsize=16, fontweight='bold', y=0.995)
    
    output_file = output_dir / "chart3_failure_timeline_by_type.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def print_summary_statistics(bills: List[Dict], metrics: Dict):
    """
    Print comprehensive summary statistics
    """
    print("\n" + "="*80)
    print("COMPLIANCE DECAY ANALYSIS SUMMARY")
    print("="*80)
    
    compliant = metrics['compliant_bills']
    non_compliant = metrics['non_compliant_bills']
    
    total = len(compliant) + len(non_compliant)
    
    print(f"\nOverall Statistics:")
    print(f"  Total Bills Analyzed: {total}")
    print(f"  Compliant Bills: {len(compliant)} ({len(compliant)/total*100:.1f}%)")
    print(f"  Non-Compliant Bills: {len(non_compliant)} ({len(non_compliant)/total*100:.1f}%)")
    
    # Failure timing statistics
    failure_times = metrics['failure_times']
    
    if failure_times:
        print(f"\nFailure Timing:")
        print(f"  Average Days to Failure: {np.mean(failure_times):.1f}")
        print(f"  Median Days to Failure: {np.median(failure_times):.1f}")
        print(f"  Earliest Failure: Day {min(failure_times)} (hearing day = 0)")
        print(f"  Latest Failure: Day {max(failure_times)}")
        
        # Key milestones
        before_60 = sum(1 for t in failure_times if t <= 60)
        between_60_90 = sum(1 for t in failure_times if 60 < t <= 90)
        after_90 = sum(1 for t in failure_times if t > 90)
        
        print(f"\nFailure Distribution by Milestone:")
        print(f"  Before 60-day deadline: {before_60} ({before_60/len(failure_times)*100:.1f}%)")
        print(f"  Between 60-90 days: {between_60_90} ({between_60_90/len(failure_times)*100:.1f}%)")
        print(f"  After 90 days: {after_90} ({after_90/len(failure_times)*100:.1f}%)")
    
    # Failure types
    print(f"\n{'='*80}")
    print("FAILURE TYPE BREAKDOWN")
    print("="*80)
    
    failure_types = metrics['failure_types']
    total_failures = sum(failure_types.values())
    
    for failure_type, count in failure_types.most_common():
        pct = count / total_failures * 100 if total_failures > 0 else 0
        print(f"  {failure_type:.<30} {count:>5} ({pct:>5.1f}%)")
    
    # Failure combinations
    print(f"\n{'='*80}")
    print("COMMON FAILURE COMBINATIONS")
    print("="*80)
    
    failure_combos = metrics['failure_combinations']
    
    if failure_combos:
        print(f"{'Failures':<50} {'Count':<10} {'%':<10}")
        print("-"*80)
        
        total_combos = sum(failure_combos.values())
        for combo, count in failure_combos.most_common(10):
            if combo:
                combo_str = ' + '.join(combo)
                pct = count / total_combos * 100
                print(f"{combo_str:<50} {count:<10} {pct:>8.1f}%")
    
    # Early warning indicators
    print(f"\n{'='*80}")
    print("EARLY WARNING INDICATORS")
    print("="*80)
    
    print("\nCritical Intervention Windows:")
    
    # When do most failures happen?
    if failure_times:
        failure_times_sorted = sorted(failure_times)
        p25 = failure_times_sorted[len(failure_times_sorted)//4]
        p50 = failure_times_sorted[len(failure_times_sorted)//2]
        p75 = failure_times_sorted[3*len(failure_times_sorted)//4]
        
        print(f"  25% of failures occur by day {p25}")
        print(f"  50% of failures occur by day {p50}")
        print(f"  75% of failures occur by day {p75}")
        
        print(f"\nRecommended Check-in Points:")
        print(f"  >> Day {p25}: First check-in (catch early failures)")
        print(f"  >> Day {p50}: Mid-point review (catch half of potential failures)")
        print(f"  >> Day 55-60: Pre-deadline review (last chance before deadline)")
        print(f"  >> Day 85-90: Extension deadline review")
    
    print("\n" + "="*80)


def save_detailed_csv(bills: List[Dict], metrics: Dict, output_dir: Path):
    """
    Save detailed failure timeline data to CSV
    """
    output_file = output_dir / "compliance_decay_detailed.csv"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Header
        f.write("bill_id,committee_id,hearing_date,state,days_to_failure,failure_type,")
        f.write("missed_deadline,no_votes,no_summary,insufficient_notice\n")
        
        # Data
        for bill in bills:
            if bill['state'] == 'Non-Compliant':
                days = bill.get('days_to_failure', '')
                failure_type = bill.get('failure_type', '')
                failures = bill['failures']
                
                f.write(f"{bill['bill_id']},{bill['committee_id']},")
                f.write(f"{bill['hearing_date']},{bill['state']},")
                f.write(f"{days},{failure_type},")
                f.write(f"{int(failures['missed_deadline'])},")
                f.write(f"{int(failures['no_votes'])},")
                f.write(f"{int(failures['no_summary'])},")
                f.write(f"{int(failures['insufficient_notice'])}\n")
    
    print(f"\nSaved detailed CSV: {output_file}")


def main():
    """Main execution function"""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    json_dir = project_root / "out" / "2025" / "12" / "06"
    output_dir = project_root / "out"
    
    print("="*80)
    print("COMPLIANCE DECAY TIMELINE ANALYSIS")
    print("="*80)
    print(f"\nReading data from: {json_dir}")
    print(f"Output directory: {output_dir}")
    
    # Load bill lifecycle data
    print("\nLoading bill lifecycle data...")
    bills = load_bill_lifecycle_data(json_dir)
    
    if not bills:
        print("\nNo bill data found!")
        return
    
    # Calculate decay metrics
    print("\nCalculating compliance decay metrics...")
    metrics = calculate_decay_metrics(bills)
    
    # Generate visualizations
    print("\nGenerating visualizations...")
    plot_survival_curve(bills, metrics, output_dir)
    plot_failure_types(metrics, output_dir)
    plot_failure_timeline_by_type(bills, metrics, output_dir)
    
    # Save CSV
    save_detailed_csv(bills, metrics, output_dir)
    
    # Print summary
    print_summary_statistics(bills, metrics)
    
    print(f"\n[OK] Analysis complete!")
    print(f"\nGenerated files:")
    print(f"  - {output_dir / 'chart1_compliance_survival_curve.png'}")
    print(f"  - {output_dir / 'chart2_failure_types.png'}")
    print(f"  - {output_dir / 'chart3_failure_timeline_by_type.png'}")
    print(f"  - {output_dir / 'compliance_decay_detailed.csv'}")


if __name__ == "__main__":
    main()

