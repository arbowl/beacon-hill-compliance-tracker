#!/usr/bin/env python3
"""
Analyze hearing notice profiles by committee.

This script reads JSON compliance data and creates visualizations exploring:
1. Mean, median, mode hearing notice by committee
2. Hearing notice compliance rates (insufficient vs in range)
3. Superlatives: most noncompliant, best/worst performers, changes before/after June 26 rule change

Dependencies:
    pip install matplotlib numpy pandas

Usage:
    python tools/hearing_notice_analysis.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import matplotlib.pyplot as plt
import numpy as np
import statistics

# Try to import pandas for easier data manipulation
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    print("Note: pandas not available, using basic data structures")


# Date threshold for rule change
RULE_CHANGE_DATE = datetime(2025, 6, 26)


def parse_committee_id(filename: str) -> Optional[str]:
    """Extract committee ID from filename like 'basic_J14.json' -> 'J14'"""
    match = re.search(r'basic_([A-Z]\d+)\.json', filename)
    return match.group(1) if match else None


def load_committee_data(json_dir: Path) -> Dict[str, List[Dict]]:
    """
    Load all JSON files from the specified directory.
    
    Returns:
        Dict mapping committee_id -> list of bill records
    """
    committee_data = {}
    
    json_files = list(json_dir.glob("basic_*.json"))
    print(f"Found {len(json_files)} committee JSON files")
    
    for json_file in json_files:
        committee_id = parse_committee_id(json_file.name)
        if not committee_id:
            continue
            
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                bills = data.get('bills', [])
                committee_data[committee_id] = bills
                print(f"  Loaded {committee_id}: {len(bills)} bills")
        except Exception as e:
            print(f"  Error loading {json_file.name}: {e}")
    
    return committee_data


def analyze_notice_gaps(committee_data: Dict[str, List[Dict]]) -> Dict[str, Dict]:
    """
    Analyze notice gap statistics for each committee based on RAW behavior.
    
    We count how many hearings had <10 days notice vs >=10 days notice,
    regardless of exemption status, to see actual behavioral changes.
    
    Returns:
        Dict mapping committee_id -> {
            'gaps': list of notice_gap_days values,
            'mean': mean gap,
            'median': median gap,
            'mode': mode gap,
            'short_notice_count': count of gaps < 10 days,
            'adequate_notice_count': count of gaps >= 10 days,
            'missing_count': count of missing notices,
            'total_with_hearings': total bills with hearings,
            'before_rule_change': {...},  # same stats for bills announced before June 26
            'after_rule_change': {...},   # same stats for bills announced after June 26
        }
    """
    committee_stats = {}
    
    for committee_id, bills in committee_data.items():
        gaps = []
        short_notice_count = 0  # < 10 days
        adequate_notice_count = 0  # >= 10 days
        missing_count = 0
        total_with_hearings = 0
        
        # Split by rule change date
        before_change = {'gaps': [], 'short': 0, 'adequate': 0, 'missing': 0, 'total': 0}
        after_change = {'gaps': [], 'short': 0, 'adequate': 0, 'missing': 0, 'total': 0}
        
        for bill in bills:
            # Only consider bills with hearings
            if bill.get('hearing_date') and bill['hearing_date'] != 'None':
                total_with_hearings += 1
                
                notice_gap = bill.get('notice_gap_days')
                announcement_date_str = bill.get('announcement_date')
                
                # Determine if before or after rule change
                bucket = None
                if announcement_date_str:
                    try:
                        announcement_date = datetime.strptime(announcement_date_str, '%Y-%m-%d')
                        bucket = before_change if announcement_date < RULE_CHANGE_DATE else after_change
                        bucket['total'] += 1
                    except ValueError:
                        pass
                
                # Track based on RAW notice gap (regardless of exemption)
                if notice_gap is not None:
                    gaps.append(notice_gap)
                    if bucket:
                        bucket['gaps'].append(notice_gap)
                    
                    # Count short vs adequate notice based on raw gap
                    if notice_gap < 10:
                        short_notice_count += 1
                        if bucket:
                            bucket['short'] += 1
                    else:  # >= 10
                        adequate_notice_count += 1
                        if bucket:
                            bucket['adequate'] += 1
                else:
                    # No announcement found
                    missing_count += 1
                    if bucket:
                        bucket['missing'] += 1
        
        # Calculate statistics
        stats = {
            'gaps': gaps,
            'total_with_hearings': total_with_hearings,
            'short_notice_count': short_notice_count,
            'adequate_notice_count': adequate_notice_count,
            'missing_count': missing_count,
        }
        
        if gaps:
            stats['mean'] = statistics.mean(gaps)
            stats['median'] = statistics.median(gaps)
            try:
                stats['mode'] = statistics.mode(gaps)
            except statistics.StatisticsError:
                # No unique mode
                stats['mode'] = None
            stats['min'] = min(gaps)
            stats['max'] = max(gaps)
        else:
            stats['mean'] = None
            stats['median'] = None
            stats['mode'] = None
            stats['min'] = None
            stats['max'] = None
        
        # Calculate adequate notice rate (behavioral, not compliance status)
        if total_with_hearings > 0:
            stats['adequate_notice_rate'] = adequate_notice_count / total_with_hearings
            stats['short_notice_rate'] = short_notice_count / total_with_hearings
        else:
            stats['adequate_notice_rate'] = None
            stats['short_notice_rate'] = None
        
        # Calculate stats for before/after rule change
        for period, period_data in [('before_rule_change', before_change), 
                                     ('after_rule_change', after_change)]:
            period_stats = {}
            if period_data['gaps']:
                period_stats['mean'] = statistics.mean(period_data['gaps'])
                period_stats['median'] = statistics.median(period_data['gaps'])
                try:
                    period_stats['mode'] = statistics.mode(period_data['gaps'])
                except statistics.StatisticsError:
                    period_stats['mode'] = None
            else:
                period_stats['mean'] = None
                period_stats['median'] = None
                period_stats['mode'] = None
            
            period_stats['total'] = period_data['total']
            period_stats['short_notice_count'] = period_data['short']
            period_stats['adequate_notice_count'] = period_data['adequate']
            period_stats['missing_count'] = period_data['missing']
            
            if period_data['total'] > 0:
                period_stats['adequate_notice_rate'] = period_data['adequate'] / period_data['total']
                period_stats['short_notice_rate'] = period_data['short'] / period_data['total']
            else:
                period_stats['adequate_notice_rate'] = None
                period_stats['short_notice_rate'] = None
            
            stats[period] = period_stats
        
        committee_stats[committee_id] = stats
    
    return committee_stats


def calculate_superlatives(committee_stats: Dict[str, Dict]) -> Dict[str, any]:
    """
    Calculate superlatives: best/worst performers, biggest changes, etc.
    """
    superlatives = {}
    
    # Filter committees with data
    committees_with_data = {
        cid: stats for cid, stats in committee_stats.items()
        if stats['total_with_hearings'] > 0 and stats['mean'] is not None
    }
    
    if not committees_with_data:
        return superlatives
    
    # Best average notice (highest mean gap)
    best_avg_notice = max(committees_with_data.items(), 
                          key=lambda x: x[1]['mean'])
    superlatives['best_avg_notice'] = (best_avg_notice[0], best_avg_notice[1]['mean'])
    
    # Worst average notice (lowest mean gap)
    worst_avg_notice = min(committees_with_data.items(), 
                           key=lambda x: x[1]['mean'])
    superlatives['worst_avg_notice'] = (worst_avg_notice[0], worst_avg_notice[1]['mean'])
    
    # Highest adequate notice rate
    committees_with_rates = {
        cid: stats for cid, stats in committees_with_data.items()
        if stats['adequate_notice_rate'] is not None
    }
    if committees_with_rates:
        best_notice_rate = max(committees_with_rates.items(), 
                              key=lambda x: x[1]['adequate_notice_rate'])
        superlatives['best_adequate_rate'] = (best_notice_rate[0], best_notice_rate[1]['adequate_notice_rate'])
        
        # Worst adequate notice rate
        worst_notice_rate = min(committees_with_rates.items(), 
                               key=lambda x: x[1]['adequate_notice_rate'])
        superlatives['worst_adequate_rate'] = (worst_notice_rate[0], worst_notice_rate[1]['adequate_notice_rate'])
    
    # Most short notice hearings (absolute count)
    most_short_notice = max(committees_with_data.items(), 
                           key=lambda x: x[1]['short_notice_count'])
    superlatives['most_short_notice_hearings'] = (most_short_notice[0], most_short_notice[1]['short_notice_count'])
    
    # Biggest improvement after rule change
    improvements = []
    for cid, stats in committees_with_data.items():
        before = stats['before_rule_change']
        after = stats['after_rule_change']
        
        if (before['adequate_notice_rate'] is not None and 
            after['adequate_notice_rate'] is not None and
            before['total'] >= 3 and after['total'] >= 3):  # Require at least 3 bills in each period
            improvement = after['adequate_notice_rate'] - before['adequate_notice_rate']
            improvements.append((cid, improvement, before['adequate_notice_rate'], after['adequate_notice_rate']))
    
    if improvements:
        improvements.sort(key=lambda x: x[1], reverse=True)
        superlatives['biggest_improvement'] = improvements[0]
        superlatives['biggest_decline'] = improvements[-1]
        superlatives['all_changes'] = improvements
    
    return superlatives


def plot_notice_statistics(committee_stats: Dict[str, Dict], output_dir: Path):
    """
    Create Chart 1: Committee notice statistics (mean, median, compliance rate)
    """
    # Filter committees with data and sort numerically by committee ID
    committees_with_data = [
        (cid, stats) for cid, stats in committee_stats.items()
        if stats['total_with_hearings'] > 0 and stats['mean'] is not None
    ]
    
    # Sort numerically: extract letter prefix and number
    def sort_key(item):
        cid = item[0]
        # Extract letter prefix (H, J, S) and number
        import re
        match = re.match(r'([A-Z])(\d+)', cid)
        if match:
            letter, number = match.groups()
            return (letter, int(number))
        return (cid, 0)
    
    committees_with_data.sort(key=sort_key)
    
    if not committees_with_data:
        print("No data to plot")
        return
    
    committee_ids = [cid for cid, _ in committees_with_data]
    means = [stats['mean'] for _, stats in committees_with_data]
    medians = [stats['median'] for _, stats in committees_with_data]
    adequate_rates = [stats['adequate_notice_rate'] * 100 if stats['adequate_notice_rate'] is not None else 0 
                     for _, stats in committees_with_data]
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 10))
    
    # Chart 1a: Mean and Median Notice Days
    x = np.arange(len(committee_ids))
    width = 0.35
    
    bars1 = ax1.barh(x - width/2, means, width, label='Mean', alpha=0.8, color='steelblue')
    bars2 = ax1.barh(x + width/2, medians, width, label='Median', alpha=0.8, color='coral')
    
    # Add vertical line at 10 days (the requirement)
    ax1.axvline(x=10, color='red', linestyle='--', linewidth=2, label='10-Day Requirement')
    
    ax1.set_yticks(x)
    ax1.set_yticklabels(committee_ids, fontsize=8)
    ax1.set_xlabel('Notice Days', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Committee', fontsize=12, fontweight='bold')
    ax1.set_title('Mean and Median Hearing Notice by Committee', fontsize=14, fontweight='bold', pad=20)
    ax1.legend(loc='lower right')
    ax1.grid(axis='x', alpha=0.3)
    
    # Add value labels on bars
    for i, (mean_val, median_val) in enumerate(zip(means, medians)):
        ax1.text(mean_val + 0.5, i - width/2, f'{mean_val:.1f}', 
                va='center', fontsize=7, fontweight='bold')
        ax1.text(median_val + 0.5, i + width/2, f'{median_val:.1f}', 
                va='center', fontsize=7, fontweight='bold')
    
    # Chart 1b: Adequate Notice Rates (>=10 days)
    colors = ['green' if rate >= 90 else 'orange' if rate >= 70 else 'red' 
             for rate in adequate_rates]
    bars3 = ax2.barh(x, adequate_rates, alpha=0.8, color=colors)
    
    ax2.set_yticks(x)
    ax2.set_yticklabels(committee_ids, fontsize=8)
    ax2.set_xlabel('Adequate Notice Rate (≥10 days) %', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Committee', fontsize=12, fontweight='bold')
    ax2.set_title('Adequate Hearing Notice Rate by Committee', fontsize=14, fontweight='bold', pad=20)
    ax2.set_xlim(0, 105)
    ax2.grid(axis='x', alpha=0.3)
    
    # Add value labels on bars
    for i, rate in enumerate(adequate_rates):
        ax2.text(rate + 1, i, f'{rate:.1f}%', va='center', fontsize=7, fontweight='bold')
    
    # Add legend for color coding
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='green', alpha=0.8, label='≥90% (Excellent)'),
        Patch(facecolor='orange', alpha=0.8, label='70-89% (Fair)'),
        Patch(facecolor='red', alpha=0.8, label='<70% (Poor)')
    ]
    ax2.legend(handles=legend_elements, loc='lower right')
    
    plt.tight_layout()
    output_file = output_dir / 'chart1_notice_statistics.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_before_after_rule_change(committee_stats: Dict[str, Dict], output_dir: Path):
    """
    Create Chart 2: Compliance rates before and after June 26 rule change
    """
    # Filter committees with data in both periods
    committees_with_both = []
    for cid, stats in committee_stats.items():
        before = stats['before_rule_change']
        after = stats['after_rule_change']
        
        if (before['total'] >= 3 and after['total'] >= 3 and
            before['adequate_notice_rate'] is not None and 
            after['adequate_notice_rate'] is not None):
            
            change = after['adequate_notice_rate'] - before['adequate_notice_rate']
            committees_with_both.append((cid, stats, change))
    
    if not committees_with_both:
        print("Not enough data for before/after comparison")
        return
    
    # Sort numerically by committee ID
    def sort_key(item):
        cid = item[0]
        import re
        match = re.match(r'([A-Z])(\d+)', cid)
        if match:
            letter, number = match.groups()
            return (letter, int(number))
        return (cid, 0)
    
    committees_with_both.sort(key=sort_key)
    
    committee_ids = [cid for cid, _, _ in committees_with_both]
    before_rates = [stats['before_rule_change']['adequate_notice_rate'] * 100 
                   for _, stats, _ in committees_with_both]
    after_rates = [stats['after_rule_change']['adequate_notice_rate'] * 100 
                  for _, stats, _ in committees_with_both]
    changes = [change * 100 for _, _, change in committees_with_both]
    
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 10))
    
    # Chart 2a: Before vs After compliance rates
    x = np.arange(len(committee_ids))
    width = 0.35
    
    bars1 = ax1.barh(x - width/2, before_rates, width, 
                     label='Before June 26', alpha=0.8, color='lightcoral')
    bars2 = ax1.barh(x + width/2, after_rates, width, 
                     label='After June 26', alpha=0.8, color='lightgreen')
    
    ax1.set_yticks(x)
    ax1.set_yticklabels(committee_ids, fontsize=9)
    ax1.set_xlabel('Adequate Notice Rate (≥10 days) %', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Committee', fontsize=12, fontweight='bold')
    ax1.set_title('Adequate Notice Rate: Before vs After June 26 Rule Change', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.legend(loc='lower right')
    ax1.set_xlim(0, 105)
    ax1.grid(axis='x', alpha=0.3)
    
    # Add value labels
    for i, (before, after) in enumerate(zip(before_rates, after_rates)):
        ax1.text(before + 1, i - width/2, f'{before:.0f}%', 
                va='center', fontsize=7, fontweight='bold')
        ax1.text(after + 1, i + width/2, f'{after:.0f}%', 
                va='center', fontsize=7, fontweight='bold')
    
    # Chart 2b: Change in compliance rate
    colors = ['green' if change >= 0 else 'red' for change in changes]
    bars3 = ax2.barh(x, changes, alpha=0.8, color=colors)
    
    ax2.axvline(x=0, color='black', linestyle='-', linewidth=1)
    ax2.set_yticks(x)
    ax2.set_yticklabels(committee_ids, fontsize=9)
    ax2.set_xlabel('Change in Adequate Notice Rate (percentage points)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Committee', fontsize=12, fontweight='bold')
    ax2.set_title('Change in Adequate Notice After Rule Change', fontsize=14, fontweight='bold', pad=20)
    ax2.grid(axis='x', alpha=0.3)
    
    # Add value labels
    for i, change in enumerate(changes):
        x_pos = change + (1 if change >= 0 else -1)
        ha = 'left' if change >= 0 else 'right'
        ax2.text(x_pos, i, f'{change:+.1f}pp', 
                va='center', ha=ha, fontsize=7, fontweight='bold')
    
    plt.tight_layout()
    output_file = output_dir / 'chart2_before_after_rule_change.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_notice_distribution(committee_stats: Dict[str, Dict], output_dir: Path):
    """
    Create Chart 3: Distribution of notice gaps across all committees
    """
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
    
    # Collect all gaps
    all_gaps = []
    for stats in committee_stats.values():
        all_gaps.extend(stats['gaps'])
    
    if not all_gaps:
        print("No gap data to plot")
        return
    
    # Chart 3a: Histogram of all notice gaps
    bins = range(0, max(all_gaps) + 2, 1)
    ax1.hist(all_gaps, bins=bins, alpha=0.7, color='steelblue', edgecolor='black')
    ax1.axvline(x=10, color='red', linestyle='--', linewidth=2, label='10-Day Requirement')
    ax1.set_xlabel('Notice Days', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Number of Hearings', fontsize=12, fontweight='bold')
    ax1.set_title('Distribution of Hearing Notice Gaps (All Committees)', 
                  fontsize=14, fontweight='bold', pad=20)
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)
    
    # Add statistics text
    stats_text = f'Mean: {statistics.mean(all_gaps):.1f} days\n'
    stats_text += f'Median: {statistics.median(all_gaps):.1f} days\n'
    try:
        stats_text += f'Mode: {statistics.mode(all_gaps):.0f} days\n'
    except statistics.StatisticsError:
        stats_text += 'Mode: No unique mode\n'
    
    insufficient = sum(1 for gap in all_gaps if gap < 10)
    stats_text += f'\nInsufficient Notice: {insufficient} ({insufficient/len(all_gaps)*100:.1f}%)\n'
    stats_text += f'Adequate Notice: {len(all_gaps)-insufficient} ({(len(all_gaps)-insufficient)/len(all_gaps)*100:.1f}%)'
    
    ax1.text(0.98, 0.97, stats_text, transform=ax1.transAxes,
            verticalalignment='top', horizontalalignment='right',
            bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8),
            fontsize=10, family='monospace')
    
    # Chart 3b: Box plot by committee (sorted numerically, top 20 by volume)
    committees_by_volume = sorted(
        [(cid, stats) for cid, stats in committee_stats.items() if stats['gaps']],
        key=lambda x: len(x[1]['gaps']),
        reverse=True
    )[:20]
    
    # Re-sort these top 20 numerically for display
    def sort_key(item):
        cid = item[0]
        import re
        match = re.match(r'([A-Z])(\d+)', cid)
        if match:
            letter, number = match.groups()
            return (letter, int(number))
        return (cid, 0)
    
    committees_by_volume.sort(key=sort_key)
    
    if committees_by_volume:
        box_data = [stats['gaps'] for _, stats in committees_by_volume]
        box_labels = [cid for cid, _ in committees_by_volume]
        
        bp = ax2.boxplot(box_data, tick_labels=box_labels, vert=False, patch_artist=True)
        
        # Color boxes
        for patch in bp['boxes']:
            patch.set_facecolor('lightblue')
            patch.set_alpha(0.7)
        
        ax2.axvline(x=10, color='red', linestyle='--', linewidth=2, label='10-Day Requirement')
        ax2.set_xlabel('Notice Days', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Committee', fontsize=12, fontweight='bold')
        ax2.set_title('Notice Gap Distribution by Committee (Top 20 by Volume)', 
                      fontsize=14, fontweight='bold', pad=20)
        ax2.legend()
        ax2.grid(axis='x', alpha=0.3)
    
    plt.tight_layout()
    output_file = output_dir / 'chart3_notice_distribution.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def print_summary_statistics(committee_stats: Dict[str, Dict], superlatives: Dict):
    """
    Print summary statistics and superlatives to console.
    """
    print("\n" + "="*80)
    print("HEARING NOTICE ANALYSIS SUMMARY")
    print("="*80)
    
    # Overall statistics
    total_committees = len(committee_stats)
    committees_with_hearings = sum(1 for stats in committee_stats.values() 
                                   if stats['total_with_hearings'] > 0)
    total_hearings = sum(stats['total_with_hearings'] for stats in committee_stats.values())
    total_short_notice = sum(stats['short_notice_count'] for stats in committee_stats.values())
    total_adequate_notice = sum(stats['adequate_notice_count'] for stats in committee_stats.values())
    
    print(f"\nOverall Statistics:")
    print(f"  Total Committees: {total_committees}")
    print(f"  Committees with Hearings: {committees_with_hearings}")
    print(f"  Total Hearings: {total_hearings}")
    print(f"  Short Notice (<10 days): {total_short_notice} ({total_short_notice/total_hearings*100:.1f}%)")
    print(f"  Adequate Notice (≥10 days): {total_adequate_notice} ({total_adequate_notice/total_hearings*100:.1f}%)")
    
    # Superlatives
    print(f"\n{'='*80}")
    print("SUPERLATIVES")
    print("="*80)
    
    if 'best_avg_notice' in superlatives:
        cid, mean_val = superlatives['best_avg_notice']
        print(f"\n🏆 Best Average Notice: {cid} ({mean_val:.1f} days)")
    
    if 'worst_avg_notice' in superlatives:
        cid, mean_val = superlatives['worst_avg_notice']
        print(f"⚠️  Worst Average Notice: {cid} ({mean_val:.1f} days)")
    
    if 'best_adequate_rate' in superlatives:
        cid, rate = superlatives['best_adequate_rate']
        print(f"\n✅ Best Adequate Notice Rate: {cid} ({rate*100:.1f}%)")
    
    if 'worst_adequate_rate' in superlatives:
        cid, rate = superlatives['worst_adequate_rate']
        print(f"❌ Worst Adequate Notice Rate: {cid} ({rate*100:.1f}%)")
    
    if 'most_short_notice_hearings' in superlatives:
        cid, count = superlatives['most_short_notice_hearings']
        print(f"\n📊 Most Short Notice Hearings: {cid} ({count} hearings)")
    
    # Before/after rule change
    if 'biggest_improvement' in superlatives:
        cid, improvement, before, after = superlatives['biggest_improvement']
        print(f"\n📈 Biggest Improvement After Rule Change: {cid}")
        print(f"   Before: {before*100:.1f}% → After: {after*100:.1f}% (change: {improvement*100:+.1f}pp)")
    
    if 'biggest_decline' in superlatives:
        cid, decline, before, after = superlatives['biggest_decline']
        print(f"\n📉 Biggest Decline After Rule Change: {cid}")
        print(f"   Before: {before*100:.1f}% → After: {after*100:.1f}% (change: {decline*100:+.1f}pp)")
    
    # Top changers
    if 'all_changes' in superlatives:
        print(f"\n{'='*80}")
        print("TOP 10 CHANGES AFTER RULE CHANGE (June 26, 2025)")
        print("="*80)
        print(f"{'Committee':<12} {'Before':>10} {'After':>10} {'Change':>10}")
        print("-"*80)
        
        for cid, change, before, after in superlatives['all_changes'][:10]:
            print(f"{cid:<12} {before*100:>9.1f}% {after*100:>9.1f}% {change*100:>9.1f}pp")
    
    print("\n" + "="*80)


def save_csv_report(committee_stats: Dict[str, Dict], output_dir: Path):
    """
    Save detailed statistics to CSV file.
    """
    output_file = output_dir / 'hearing_notice_statistics.csv'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Header
        f.write("committee_id,total_hearings,mean_gap,median_gap,mode_gap,min_gap,max_gap,")
        f.write("short_notice_count,adequate_notice_count,missing_count,adequate_notice_rate,")
        f.write("before_total,before_mean,before_short,before_adequate,before_adequate_rate,")
        f.write("after_total,after_mean,after_short,after_adequate,after_adequate_rate,")
        f.write("adequate_rate_change\n")
        
        # Data
        for cid in sorted(committee_stats.keys()):
            stats = committee_stats[cid]
            before = stats['before_rule_change']
            after = stats['after_rule_change']
            
            rate_change = None
            if before['adequate_notice_rate'] is not None and after['adequate_notice_rate'] is not None:
                rate_change = after['adequate_notice_rate'] - before['adequate_notice_rate']
            
            f.write(f"{cid},")
            f.write(f"{stats['total_with_hearings']},")
            f.write(f"{stats['mean']:.2f}," if stats['mean'] is not None else ",")
            f.write(f"{stats['median']:.2f}," if stats['median'] is not None else ",")
            f.write(f"{stats['mode']}," if stats['mode'] is not None else ",")
            f.write(f"{stats['min']}," if stats['min'] is not None else ",")
            f.write(f"{stats['max']}," if stats['max'] is not None else ",")
            f.write(f"{stats['short_notice_count']},")
            f.write(f"{stats['adequate_notice_count']},")
            f.write(f"{stats['missing_count']},")
            f.write(f"{stats['adequate_notice_rate']:.4f}," if stats['adequate_notice_rate'] is not None else ",")
            f.write(f"{before['total']},")
            f.write(f"{before['mean']:.2f}," if before['mean'] is not None else ",")
            f.write(f"{before['short_notice_count']},")
            f.write(f"{before['adequate_notice_count']},")
            f.write(f"{before['adequate_notice_rate']:.4f}," if before['adequate_notice_rate'] is not None else ",")
            f.write(f"{after['total']},")
            f.write(f"{after['mean']:.2f}," if after['mean'] is not None else ",")
            f.write(f"{after['short_notice_count']},")
            f.write(f"{after['adequate_notice_count']},")
            f.write(f"{after['adequate_notice_rate']:.4f}," if after['adequate_notice_rate'] is not None else ",")
            f.write(f"{rate_change:.4f}\n" if rate_change is not None else "\n")
    
    print(f"\nSaved detailed statistics: {output_file}")


def main():
    """Main execution function."""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    json_dir = project_root / 'out' / '2025' / '12' / '06'
    output_dir = project_root / 'out'
    
    print("="*80)
    print("HEARING NOTICE PROFILE ANALYSIS")
    print("="*80)
    print(f"\nReading data from: {json_dir}")
    print(f"Output directory: {output_dir}")
    
    # Load data
    committee_data = load_committee_data(json_dir)
    
    if not committee_data:
        print("\nNo data found!")
        return
    
    # Analyze notice gaps
    print("\nAnalyzing notice gaps...")
    committee_stats = analyze_notice_gaps(committee_data)
    
    # Calculate superlatives
    print("Calculating superlatives...")
    superlatives = calculate_superlatives(committee_stats)
    
    # Generate visualizations
    print("\nGenerating visualizations...")
    plot_notice_statistics(committee_stats, output_dir)
    plot_before_after_rule_change(committee_stats, output_dir)
    plot_notice_distribution(committee_stats, output_dir)
    
    # Save CSV report
    save_csv_report(committee_stats, output_dir)
    
    # Print summary
    print_summary_statistics(committee_stats, superlatives)
    
    print(f"\n✅ Analysis complete!")
    print(f"\nGenerated files:")
    print(f"  - {output_dir / 'chart1_notice_statistics.png'}")
    print(f"  - {output_dir / 'chart2_before_after_rule_change.png'}")
    print(f"  - {output_dir / 'chart3_notice_distribution.png'}")
    print(f"  - {output_dir / 'hearing_notice_statistics.csv'}")


if __name__ == '__main__':
    main()

