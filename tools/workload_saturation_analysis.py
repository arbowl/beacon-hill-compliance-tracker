#!/usr/bin/env python3
"""
Analyze committee workload saturation and its impact on compliance.

This script reads JSON compliance data and explores:
1. How workload (bills heard per month) varies over time for each committee
2. Whether high workload periods correlate with lower compliance rates
3. Which committees handle surges better vs. worse
4. Identification of "saturation points" where performance degrades

Dependencies:
    pip install matplotlib numpy pandas

Usage:
    python tools/workload_saturation_analysis.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date
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


def get_month_key(d: date) -> str:
    """Convert date to YYYY-MM format for grouping"""
    return f"{d.year}-{d.month:02d}"


def load_committee_workload_data(json_dir: Path) -> Dict[str, Dict]:
    """
    Load all bills and organize by committee and hearing month.
    
    Returns:
        Dict mapping committee_id -> {
            'monthly_workload': {month_key: bill_count},
            'monthly_compliance': {month_key: {compliant: X, total: Y}},
            'bills_by_month': {month_key: [bill_data]},
            'total_bills': int
        }
    """
    committees = defaultdict(lambda: {
        'monthly_workload': defaultdict(int),
        'monthly_compliance': defaultdict(lambda: {'compliant': 0, 'non_compliant': 0, 'total': 0}),
        'bills_by_month': defaultdict(list),
        'total_bills': 0,
        'name': None
    })
    
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
                
                for bill in bills:
                    hearing_date_str = bill.get('hearing_date')
                    hearing_date = parse_date(hearing_date_str)
                    
                    if not hearing_date:
                        continue
                    
                    month_key = get_month_key(hearing_date)
                    
                    # Track workload
                    committees[committee_id]['monthly_workload'][month_key] += 1
                    committees[committee_id]['total_bills'] += 1
                    
                    # Track compliance
                    state = bill.get('state', 'Unknown')
                    committees[committee_id]['monthly_compliance'][month_key]['total'] += 1
                    
                    if state == 'Compliant':
                        committees[committee_id]['monthly_compliance'][month_key]['compliant'] += 1
                    elif state == 'Non-Compliant':
                        committees[committee_id]['monthly_compliance'][month_key]['non_compliant'] += 1
                    
                    # Store bill data
                    committees[committee_id]['bills_by_month'][month_key].append({
                        'bill_id': bill.get('bill_id'),
                        'state': state,
                        'hearing_date': hearing_date,
                        'reported_out': bill.get('reported_out', False),
                        'summary_present': bill.get('summary_present', False),
                        'votes_present': bill.get('votes_present', False)
                    })
                    
        except Exception as e:
            print(f"  Error loading {json_file.name}: {e}")
    
    print(f"Loaded data for {len(committees)} committees")
    return dict(committees)


def calculate_workload_metrics(committees: Dict) -> Dict:
    """
    Calculate various workload and saturation metrics.
    
    Returns:
        Dict with aggregated metrics for analysis
    """
    metrics = {
        'committee_stats': {},
        'global_monthly': defaultdict(lambda: {'workload': 0, 'compliant': 0, 'total': 0}),
        'workload_compliance_pairs': []  # For scatter plot
    }
    
    for committee_id, data in committees.items():
        monthly_workload = data['monthly_workload']
        monthly_compliance = data['monthly_compliance']
        
        if not monthly_workload:
            continue
        
        # Calculate committee-level statistics
        workloads = list(monthly_workload.values())
        
        stats = {
            'committee_id': committee_id,
            'total_bills': data['total_bills'],
            'active_months': len(monthly_workload),
            'avg_workload': np.mean(workloads),
            'max_workload': max(workloads),
            'min_workload': min(workloads),
            'std_workload': np.std(workloads),
            'monthly_data': []
        }
        
        # Calculate compliance rate for each workload level
        for month_key in sorted(monthly_workload.keys()):
            workload = monthly_workload[month_key]
            compliance_data = monthly_compliance[month_key]
            
            total = compliance_data['total']
            compliant = compliance_data['compliant']
            compliance_rate = (compliant / total) if total > 0 else 0
            
            month_stats = {
                'month': month_key,
                'workload': workload,
                'total': total,
                'compliant': compliant,
                'compliance_rate': compliance_rate
            }
            
            stats['monthly_data'].append(month_stats)
            
            # Add to scatter plot data
            metrics['workload_compliance_pairs'].append({
                'committee_id': committee_id,
                'month': month_key,
                'workload': workload,
                'compliance_rate': compliance_rate * 100,
                'total_bills': total
            })
            
            # Aggregate global monthly data
            metrics['global_monthly'][month_key]['workload'] += workload
            metrics['global_monthly'][month_key]['compliant'] += compliant
            metrics['global_monthly'][month_key]['total'] += total
        
        # Calculate overall compliance rate
        total_compliant = sum(m['compliant'] for m in stats['monthly_data'])
        total_bills = sum(m['total'] for m in stats['monthly_data'])
        stats['overall_compliance_rate'] = (total_compliant / total_bills) if total_bills > 0 else 0
        
        # Calculate correlation between workload and compliance
        if len(stats['monthly_data']) > 1:
            workloads_list = [m['workload'] for m in stats['monthly_data']]
            compliance_rates = [m['compliance_rate'] for m in stats['monthly_data']]
            correlation = np.corrcoef(workloads_list, compliance_rates)[0, 1]
            stats['workload_compliance_correlation'] = correlation if not np.isnan(correlation) else 0
        else:
            stats['workload_compliance_correlation'] = 0
        
        metrics['committee_stats'][committee_id] = stats
    
    return metrics


def plot_global_timeline(metrics: Dict, output_dir: Path):
    """
    Chart 1: Global timeline showing total workload and compliance over time
    """
    global_monthly = metrics['global_monthly']
    
    if not global_monthly:
        print("No timeline data to plot")
        return
    
    months = sorted(global_monthly.keys())
    workloads = [global_monthly[m]['workload'] for m in months]
    compliant = [global_monthly[m]['compliant'] for m in months]
    totals = [global_monthly[m]['total'] for m in months]
    compliance_rates = [(c / t * 100) if t > 0 else 0 for c, t in zip(compliant, totals)]
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10))
    
    # Chart 1a: Workload over time
    ax1.bar(range(len(months)), workloads, alpha=0.7, color='steelblue', edgecolor='black')
    ax1.set_xlabel('Month', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Total Bills Heard (All Committees)', fontsize=12, fontweight='bold')
    ax1.set_title(
        'Legislative Workload Timeline\nTotal bills heard across all committees per month',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax1.set_xticks(range(len(months)))
    ax1.set_xticklabels(months, rotation=45, ha='right', fontsize=9)
    ax1.grid(axis='y', alpha=0.3)
    
    # Add value labels on top of bars
    for i, (workload, total) in enumerate(zip(workloads, totals)):
        ax1.text(i, workload + max(workloads) * 0.01, str(workload),
                ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    # Chart 1b: Compliance rate over time
    line = ax2.plot(range(len(months)), compliance_rates, 
                    marker='o', linewidth=2, markersize=8, 
                    color='darkgreen', alpha=0.7, label='Compliance Rate')
    ax2.fill_between(range(len(months)), compliance_rates, alpha=0.3, color='lightgreen')
    
    ax2.set_xlabel('Month', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Compliance Rate (%)', fontsize=12, fontweight='bold')
    ax2.set_title(
        'Compliance Rate Timeline\nPercentage of compliant bills per month',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax2.set_xticks(range(len(months)))
    ax2.set_xticklabels(months, rotation=45, ha='right', fontsize=9)
    ax2.set_ylim(0, max(compliance_rates) * 1.2 if compliance_rates else 100)
    ax2.grid(True, alpha=0.3)
    
    # Add value labels on points
    for i, (rate, total) in enumerate(zip(compliance_rates, totals)):
        ax2.text(i, rate + 1, f'{rate:.1f}%\n(n={total})',
                ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    output_file = output_dir / "chart1_workload_timeline.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_workload_vs_compliance_scatter(metrics: Dict, output_dir: Path):
    """
    Chart 2: Scatter plot showing workload vs compliance rate
    """
    pairs = metrics['workload_compliance_pairs']
    
    if not pairs:
        print("No workload-compliance pairs to plot")
        return
    
    workloads = [p['workload'] for p in pairs]
    compliance_rates = [p['compliance_rate'] for p in pairs]
    sizes = [p['total_bills'] * 20 for p in pairs]  # Scale for visibility
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    
    # Chart 2a: All data points
    scatter = ax1.scatter(
        workloads, compliance_rates,
        s=sizes, alpha=0.5,
        c=compliance_rates, cmap='RdYlGn',
        edgecolors='black', linewidths=0.5
    )
    
    # Add trend line
    if len(workloads) > 1:
        z = np.polyfit(workloads, compliance_rates, 1)
        p = np.poly1d(z)
        x_trend = np.linspace(min(workloads), max(workloads), 100)
        ax1.plot(x_trend, p(x_trend), "r--", alpha=0.8, linewidth=2,
                label=f'Trend: y={z[0]:.2f}x+{z[1]:.1f}')
        
        # Calculate R-squared
        y_pred = p(workloads)
        ss_res = np.sum((np.array(compliance_rates) - y_pred) ** 2)
        ss_tot = np.sum((np.array(compliance_rates) - np.mean(compliance_rates)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        ax1.text(0.05, 0.95, f'R² = {r_squared:.3f}',
                transform=ax1.transAxes, fontsize=11,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    ax1.set_xlabel('Bills Heard in Month (Workload)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Compliance Rate (%)', fontsize=12, fontweight='bold')
    ax1.set_title(
        'Workload vs. Compliance Rate\n(bubble size = number of bills)',
        fontsize=14,
        fontweight='bold',
        pad=20
    )
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(-5, 105)
    
    # Add colorbar
    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label('Compliance Rate (%)', fontsize=10)
    
    # Chart 2b: Binned analysis (workload categories)
    # Create workload bins
    workload_bins = [0, 10, 20, 30, 50, 100, max(workloads) + 1]
    bin_labels = ['1-10', '11-20', '21-30', '31-50', '51-100', '100+']
    
    bin_data = defaultdict(lambda: {'rates': [], 'counts': []})
    
    for pair in pairs:
        workload = pair['workload']
        rate = pair['compliance_rate']
        
        for i, (low, high) in enumerate(zip(workload_bins[:-1], workload_bins[1:])):
            if low < workload <= high:
                bin_data[bin_labels[i]]['rates'].append(rate)
                bin_data[bin_labels[i]]['counts'].append(pair['total_bills'])
                break
    
    # Calculate statistics for each bin
    bin_means = []
    bin_stds = []
    bin_ns = []
    active_labels = []
    
    for label in bin_labels:
        if bin_data[label]['rates']:
            bin_means.append(np.mean(bin_data[label]['rates']))
            bin_stds.append(np.std(bin_data[label]['rates']))
            bin_ns.append(len(bin_data[label]['rates']))
            active_labels.append(label)
    
    if bin_means:
        x_pos = np.arange(len(active_labels))
        bars = ax2.bar(x_pos, bin_means, yerr=bin_stds, 
                      alpha=0.7, color='coral', edgecolor='black',
                      capsize=5, error_kw={'linewidth': 2})
        
        ax2.set_xlabel('Monthly Workload (Bills/Month)', fontsize=12, fontweight='bold')
        ax2.set_ylabel('Average Compliance Rate (%)', fontsize=12, fontweight='bold')
        ax2.set_title(
            'Compliance Rate by Workload Category\n(error bars = std dev)',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels(active_labels)
        ax2.set_ylim(0, max(bin_means) * 1.3 if bin_means else 100)
        ax2.grid(axis='y', alpha=0.3)
        
        # Add value labels and sample sizes
        for i, (mean, n) in enumerate(zip(bin_means, bin_ns)):
            ax2.text(i, mean + (bin_stds[i] if i < len(bin_stds) else 0) + 1,
                    f'{mean:.1f}%\n(n={n})',
                    ha='center', va='bottom', fontsize=9, fontweight='bold')
    
    plt.tight_layout()
    output_file = output_dir / "chart2_workload_vs_compliance.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def plot_committee_comparison(metrics: Dict, output_dir: Path):
    """
    Chart 3: Compare committees on workload handling and saturation resistance
    """
    committee_stats = metrics['committee_stats']
    
    # Filter committees with meaningful data (at least 10 bills and 2+ months)
    meaningful_committees = {
        cid: stats for cid, stats in committee_stats.items()
        if stats['total_bills'] >= 10 and stats['active_months'] >= 2
    }
    
    if len(meaningful_committees) < 3:
        print("Not enough committees with sufficient data for comparison")
        return
    
    fig = plt.figure(figsize=(16, 12))
    gs = GridSpec(3, 2, figure=fig, hspace=0.3, wspace=0.3)
    
    # Prepare data
    committees = []
    avg_workloads = []
    max_workloads = []
    std_workloads = []
    correlations = []
    compliance_rates = []
    
    for cid in sorted(meaningful_committees.keys()):
        stats = meaningful_committees[cid]
        committees.append(cid)
        avg_workloads.append(stats['avg_workload'])
        max_workloads.append(stats['max_workload'])
        std_workloads.append(stats['std_workload'])
        correlations.append(stats['workload_compliance_correlation'])
        compliance_rates.append(stats['overall_compliance_rate'] * 100)
    
    # Chart 3a: Average workload by committee
    ax1 = fig.add_subplot(gs[0, :])
    bars = ax1.barh(range(len(committees)), avg_workloads, alpha=0.7, 
                    color='steelblue', edgecolor='black')
    ax1.set_yticks(range(len(committees)))
    ax1.set_yticklabels(committees, fontsize=8)
    ax1.set_xlabel('Average Bills/Month', fontsize=11, fontweight='bold')
    ax1.set_title('Average Monthly Workload by Committee', fontsize=13, fontweight='bold', pad=15)
    ax1.grid(axis='x', alpha=0.3)
    
    for i, val in enumerate(avg_workloads):
        ax1.text(val + 0.5, i, f'{val:.1f}', va='center', fontsize=8)
    
    # Chart 3b: Workload variability (std dev)
    ax2 = fig.add_subplot(gs[1, 0])
    colors_std = ['green' if s < np.median(std_workloads) else 'orange' 
                  for s in std_workloads]
    ax2.barh(range(len(committees)), std_workloads, alpha=0.7, 
            color=colors_std, edgecolor='black')
    ax2.set_yticks(range(len(committees)))
    ax2.set_yticklabels(committees, fontsize=8)
    ax2.set_xlabel('Std Dev of Workload', fontsize=10, fontweight='bold')
    ax2.set_title('Workload Consistency\n(lower = more consistent)', 
                 fontsize=12, fontweight='bold', pad=10)
    ax2.grid(axis='x', alpha=0.3)
    
    # Chart 3c: Workload-Compliance correlation
    ax3 = fig.add_subplot(gs[1, 1])
    colors_corr = ['darkred' if c < -0.3 else 'orange' if c < 0 else 'lightgreen' if c < 0.3 else 'darkgreen'
                   for c in correlations]
    ax3.barh(range(len(committees)), correlations, alpha=0.7, 
            color=colors_corr, edgecolor='black')
    ax3.axvline(x=0, color='black', linestyle='-', linewidth=1)
    ax3.set_yticks(range(len(committees)))
    ax3.set_yticklabels(committees, fontsize=8)
    ax3.set_xlabel('Correlation Coefficient', fontsize=10, fontweight='bold')
    ax3.set_title('Workload-Compliance Correlation\n(negative = saturation effect)', 
                 fontsize=12, fontweight='bold', pad=10)
    ax3.grid(axis='x', alpha=0.3)
    ax3.set_xlim(-1, 1)
    
    for i, val in enumerate(correlations):
        x_pos = val + (0.05 if val >= 0 else -0.05)
        ha = 'left' if val >= 0 else 'right'
        ax3.text(x_pos, i, f'{val:.2f}', va='center', ha=ha, fontsize=7)
    
    # Chart 3d: Saturation resistance score (combination metric)
    ax4 = fig.add_subplot(gs[2, :])
    
    # Calculate "saturation resistance" score:
    # High score = handles high workload well (high compliance despite high workload)
    # Negative correlation penalized, high compliance rewarded, high workload capacity rewarded
    resistance_scores = []
    for i in range(len(committees)):
        # Penalize negative correlation (saturation effect)
        corr_score = max(0, correlations[i] + 0.5) / 1.5  # Normalize -0.5 to 1.0 -> 0 to 1
        # Reward compliance rate
        compliance_score = compliance_rates[i] / 100
        # Reward workload capacity
        workload_score = min(avg_workloads[i] / max(avg_workloads), 1.0)
        
        # Combined score (weighted)
        resistance = (corr_score * 0.4 + compliance_score * 0.4 + workload_score * 0.2) * 100
        resistance_scores.append(resistance)
    
    # Sort by resistance score
    sorted_indices = sorted(range(len(resistance_scores)), key=lambda i: resistance_scores[i], reverse=True)
    sorted_committees = [committees[i] for i in sorted_indices]
    sorted_scores = [resistance_scores[i] for i in sorted_indices]
    
    colors_resistance = ['darkgreen' if s > 66 else 'gold' if s > 33 else 'coral' 
                        for s in sorted_scores]
    
    ax4.barh(range(len(sorted_committees)), sorted_scores, alpha=0.7,
            color=colors_resistance, edgecolor='black')
    ax4.set_yticks(range(len(sorted_committees)))
    ax4.set_yticklabels(sorted_committees, fontsize=8)
    ax4.set_xlabel('Saturation Resistance Score (0-100)', fontsize=11, fontweight='bold')
    ax4.set_title(
        'Committee Saturation Resistance Ranking\nHigher score = handles high workload better without compliance drop',
        fontsize=13,
        fontweight='bold',
        pad=15
    )
    ax4.grid(axis='x', alpha=0.3)
    ax4.set_xlim(0, 105)
    
    for i, val in enumerate(sorted_scores):
        ax4.text(val + 1, i, f'{val:.1f}', va='center', fontsize=8)
    
    # Add legend for score colors
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='darkgreen', alpha=0.7, label='High (>66)'),
        Patch(facecolor='gold', alpha=0.7, label='Medium (33-66)'),
        Patch(facecolor='coral', alpha=0.7, label='Low (<33)')
    ]
    ax4.legend(handles=legend_elements, loc='lower right', title='Resistance Score')
    
    plt.suptitle('Committee Workload Management Comparison', 
                fontsize=16, fontweight='bold', y=0.995)
    
    output_file = output_dir / "chart3_committee_comparison.png"
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Saved: {output_file}")
    plt.close()


def print_summary_statistics(metrics: Dict):
    """
    Print comprehensive summary statistics
    """
    print("\n" + "="*80)
    print("WORKLOAD SATURATION ANALYSIS SUMMARY")
    print("="*80)
    
    # Global statistics
    committee_stats = metrics['committee_stats']
    workload_pairs = metrics['workload_compliance_pairs']
    
    total_committees = len(committee_stats)
    total_bills = sum(s['total_bills'] for s in committee_stats.values())
    
    print(f"\nGlobal Statistics:")
    print(f"  Committees Analyzed: {total_committees}")
    print(f"  Total Bills: {total_bills}")
    print(f"  Committee-Months Observed: {len(workload_pairs)}")
    
    # Workload statistics
    all_workloads = [p['workload'] for p in workload_pairs]
    if all_workloads:
        print(f"\nWorkload Distribution:")
        print(f"  Average Bills/Month: {np.mean(all_workloads):.1f}")
        print(f"  Median Bills/Month: {np.median(all_workloads):.1f}")
        print(f"  Max Bills/Month: {max(all_workloads)} (peak workload)")
        print(f"  Std Dev: {np.std(all_workloads):.1f}")
    
    # Correlation analysis
    correlations = [s['workload_compliance_correlation'] for s in committee_stats.values()
                   if s['total_bills'] >= 10]
    
    if correlations:
        negative_corr = sum(1 for c in correlations if c < -0.2)
        positive_corr = sum(1 for c in correlations if c > 0.2)
        
        print(f"\nWorkload-Compliance Correlation:")
        print(f"  Average Correlation: {np.mean(correlations):.3f}")
        print(f"  Committees with Negative Correlation: {negative_corr} ({negative_corr/len(correlations)*100:.1f}%)")
        print(f"  Committees with Positive Correlation: {positive_corr} ({positive_corr/len(correlations)*100:.1f}%)")
        print(f"  Interpretation: Negative = performance drops under load (saturation)")
        print(f"                  Positive = performance improves under load (focus effect)")
    
    # Find peak workload periods
    global_monthly = metrics['global_monthly']
    if global_monthly:
        months = sorted(global_monthly.keys())
        workloads_by_month = [(m, global_monthly[m]['workload']) for m in months]
        workloads_by_month.sort(key=lambda x: x[1], reverse=True)
        
        print(f"\n{'='*80}")
        print("PEAK WORKLOAD PERIODS")
        print("="*80)
        print(f"{'Month':<12} {'Total Bills':<15} {'Compliance Rate':<20}")
        print("-"*80)
        
        for month, workload in workloads_by_month[:5]:
            data = global_monthly[month]
            rate = (data['compliant'] / data['total'] * 100) if data['total'] > 0 else 0
            print(f"{month:<12} {workload:<15} {rate:>18.1f}%")
    
    # Committee performance under pressure
    print(f"\n{'='*80}")
    print("COMMITTEES UNDER PRESSURE")
    print("="*80)
    
    # Sort by max workload
    committees_by_max = sorted(
        committee_stats.items(),
        key=lambda x: x[1]['max_workload'],
        reverse=True
    )
    
    print("\nTop 5 Peak Workloads:")
    print(f"{'Committee':<12} {'Max Bills/Month':<18} {'Avg Compliance':<18}")
    print("-"*80)
    
    for cid, stats in committees_by_max[:5]:
        if stats['total_bills'] >= 5:
            print(f"{cid:<12} {stats['max_workload']:<18} {stats['overall_compliance_rate']*100:>16.1f}%")
    
    # Saturation victims (negative correlation + low compliance)
    print("\nCommittees Showing Saturation Effects:")
    print(f"{'Committee':<12} {'Correlation':<15} {'Avg Compliance':<18} {'Status':<20}")
    print("-"*80)
    
    saturation_victims = [
        (cid, stats) for cid, stats in committee_stats.items()
        if stats['workload_compliance_correlation'] < -0.2 and stats['total_bills'] >= 10
    ]
    saturation_victims.sort(key=lambda x: x[1]['workload_compliance_correlation'])
    
    if saturation_victims:
        for cid, stats in saturation_victims[:10]:
            corr = stats['workload_compliance_correlation']
            comp = stats['overall_compliance_rate'] * 100
            status = "HIGH RISK" if corr < -0.5 else "MODERATE"
            print(f"{cid:<12} {corr:>13.3f} {comp:>16.1f}% {status:<20}")
    else:
        print("  No clear saturation effects detected")
    
    # Resilient committees (positive/neutral correlation + high workload)
    print("\nResilient Committees (Handle High Workload Well):")
    print(f"{'Committee':<12} {'Avg Workload':<15} {'Correlation':<15} {'Compliance':<15}")
    print("-"*80)
    
    resilient = [
        (cid, stats) for cid, stats in committee_stats.items()
        if stats['workload_compliance_correlation'] > -0.1 
        and stats['avg_workload'] > np.median([s['avg_workload'] for s in committee_stats.values()])
        and stats['total_bills'] >= 10
    ]
    resilient.sort(key=lambda x: x[1]['overall_compliance_rate'], reverse=True)
    
    if resilient:
        for cid, stats in resilient[:10]:
            print(f"{cid:<12} {stats['avg_workload']:>13.1f} "
                  f"{stats['workload_compliance_correlation']:>13.3f} "
                  f"{stats['overall_compliance_rate']*100:>13.1f}%")
    else:
        print("  No clearly resilient committees identified")
    
    print("\n" + "="*80)


def save_detailed_csv(metrics: Dict, output_dir: Path):
    """
    Save detailed workload data to CSV
    """
    output_file = output_dir / "workload_saturation_detailed.csv"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Header
        f.write("committee_id,month,workload,compliant,total,compliance_rate\n")
        
        # Data from workload_compliance_pairs
        for pair in sorted(metrics['workload_compliance_pairs'], 
                          key=lambda x: (x['committee_id'], x['month'])):
            f.write(f"{pair['committee_id']},{pair['month']},{pair['workload']},")
            
            # Calculate compliant count from rate and total
            compliant = int(pair['compliance_rate'] * pair['total_bills'] / 100)
            f.write(f"{compliant},{pair['total_bills']},{pair['compliance_rate']:.2f}\n")
    
    print(f"\nSaved detailed CSV: {output_file}")


def main():
    """Main execution function"""
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    json_dir = project_root / "out" / "2025" / "12" / "06"
    output_dir = project_root / "out"
    
    print("="*80)
    print("WORKLOAD SATURATION ANALYSIS")
    print("="*80)
    print(f"\nReading data from: {json_dir}")
    print(f"Output directory: {output_dir}")
    
    # Load workload data
    print("\nLoading committee workload data...")
    committees = load_committee_workload_data(json_dir)
    
    if not committees:
        print("\nNo committee data found!")
        return
    
    # Calculate metrics
    print("\nCalculating workload saturation metrics...")
    metrics = calculate_workload_metrics(committees)
    
    # Generate visualizations
    print("\nGenerating visualizations...")
    plot_global_timeline(metrics, output_dir)
    plot_workload_vs_compliance_scatter(metrics, output_dir)
    plot_committee_comparison(metrics, output_dir)
    
    # Save CSV
    save_detailed_csv(metrics, output_dir)
    
    # Print summary
    print_summary_statistics(metrics)
    
    print(f"\n[OK] Analysis complete!")
    print(f"\nGenerated files:")
    print(f"  - {output_dir / 'chart1_workload_timeline.png'}")
    print(f"  - {output_dir / 'chart2_workload_vs_compliance.png'}")
    print(f"  - {output_dir / 'chart3_committee_comparison.png'}")
    print(f"  - {output_dir / 'workload_saturation_detailed.csv'}")


if __name__ == "__main__":
    main()

