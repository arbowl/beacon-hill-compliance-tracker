#!/usr/bin/env python3
"""
Generate four visualizations for Committee Compliance Typology research dataset.

This script reads JSON compliance data and creates:
1. Four-Quadrant Compliance Matrix
2. Radar/Spider Charts per Committee
3. Compliance Gap Heatmap
4. Bill Topic Compliance Analysis

Dependencies:
    pip install matplotlib numpy seaborn

Usage:
    python generate_committee_visualizations.py
"""

import json
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.patches import Rectangle

# Try to import seaborn for better styling, but don't fail if not available
try:
    import seaborn as sns
    sns.set_palette("husl")
    try:
        plt.style.use('seaborn-v0_8-darkgrid')
    except OSError:
        try:
            plt.style.use('seaborn-darkgrid')
        except OSError:
            plt.style.use('default')
except ImportError:
    plt.style.use('default')
    print("Note: seaborn not available, using default matplotlib style")


def parse_committee_id(filename: str) -> Optional[str]:
    """Extract committee ID from filename like 'basic_J14.json' -> 'J14'"""
    match = re.search(r'basic_([JH]\d+)\.json', filename)
    return match.group(1) if match else None


def parse_report_out_compliance(reason: str) -> Optional[bool]:
    """
    Parse reason field to determine if bill was reported out.
    Returns True if compliant, False if non-compliant, None if unknown/pending.
    """
    if not reason:
        return None

    reason_lower = reason.lower()

    if "all requirements met" in reason_lower and "reported out" in reason_lower:
        return True

    if "not reported out" in reason_lower:
        return False

    if "before deadline" in reason_lower:
        return None

    if "reported out" in reason_lower and "not" not in reason_lower:
        return True

    return None


def load_committee_data(json_dir: Path) -> Dict[str, Dict]:
    """
    Load all JSON files and aggregate data by committee.
    Returns dict: {committee_id: {metrics, bills}}
    """
    committees = {}

    for json_file in json_dir.glob("basic_J*.json"):
        committee_id = parse_committee_id(json_file.name)
        if not committee_id:
            continue

        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        bills = data.get('bills', [])
        if not bills:
            continue

        # Initialize metrics
        total_bills = 0
        notice_total = 0
        notice_in_range = 0
        notice_days_sum = 0
        votes_present_count = 0
        summary_present_count = 0
        report_out_compliant = 0
        report_out_total = 0

        bill_titles = []

        for bill in bills:
            if not bill.get('hearing_date'):
                continue

            total_bills += 1
            bill_titles.append(bill.get('bill_title', ''))

            # Notice compliance
            notice_status = bill.get("notice_status")
            notice_gap = bill.get("notice_gap_days")
            if notice_gap is not None:
                notice_days_sum += notice_gap
            if notice_status:
                notice_total += 1
                if notice_status.lower() == "in range":
                    notice_in_range += 1

            # Votes
            if bill.get('votes_present'):
                votes_present_count += 1

            # Summaries
            if bill.get('summary_present'):
                summary_present_count += 1

            # Report-out compliance
            reason = bill.get('reason', '')
            report_out_status = parse_report_out_compliance(reason)
            if report_out_status is not None:
                report_out_total += 1
                if report_out_status:
                    report_out_compliant += 1

        # Calculate averages and percentages
        avg_notice_days = notice_days_sum / total_bills if total_bills > 0 else 0
        notice_compliance_pct = (notice_in_range / notice_total * 100) if notice_total > 0 else 0
        vote_compliance_pct = (votes_present_count / total_bills * 100) if total_bills > 0 else 0
        summary_compliance_pct = (summary_present_count / total_bills * 100) if total_bills > 0 else 0
        report_out_compliance_pct = (report_out_compliant / report_out_total * 100) if report_out_total > 0 else 0

        committees[committee_id] = {
            'committee_id': committee_id,
            'total_bills': total_bills,
            'avg_notice_days': avg_notice_days,
            'notice_compliance_pct': notice_compliance_pct,
            'vote_compliance_pct': vote_compliance_pct,
            'summary_compliance_pct': summary_compliance_pct,
            'report_out_compliance_pct': report_out_compliance_pct,
            'bill_titles': bill_titles,
            'bills': bills
        }

    return committees


def create_quadrant_matrix(committees: Dict[str, Dict], output_path: Path):
    """Create four-quadrant compliance matrix visualization."""
    fig, ax = plt.subplots(figsize=(12, 10))

    transparency_scores = []
    process_scores = []
    committee_ids = []

    for cid, data in committees.items():
        transparency = (data['vote_compliance_pct'] + data['summary_compliance_pct']) / 2
        process = (data['notice_compliance_pct'] + data['report_out_compliance_pct']) / 2

        transparency_scores.append(transparency)
        process_scores.append(process)
        committee_ids.append(cid)

    scatter = ax.scatter(transparency_scores, process_scores,
                        s=200, alpha=0.7, c=range(len(committee_ids)),
                        cmap='viridis', edgecolors='black', linewidths=2)

    for i, cid in enumerate(committee_ids):
        ax.annotate(cid, (transparency_scores[i], process_scores[i]),
                    xytext=(5, 5), textcoords='offset points', fontsize=10, fontweight='bold')

    ax.axvline(x=50, color='gray', linestyle='--', linewidth=1, alpha=0.5)
    ax.axhline(y=50, color='gray', linestyle='--', linewidth=1, alpha=0.5)

    ax.text(75, 75, 'High Performers\n(High Transparency,\nHigh Process)',
            ha='center', va='center', fontsize=11,
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.3))
    ax.text(25, 75, 'Fast but Opaque\n(Low Transparency,\nHigh Process)',
            ha='center', va='center', fontsize=11,
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.3))
    ax.text(75, 25, 'Slow but Transparent\n(High Transparency,\nLow Process)',
            ha='center', va='center', fontsize=11,
            bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.3))
    ax.text(25, 25, 'Systemic Issues\n(Low Transparency,\nLow Process)',
            ha='center', va='center', fontsize=11,
            bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.3))

    ax.set_xlabel('Transparency Score\n(Average of Vote% + Summary%)',
                  fontsize=12, fontweight='bold')
    ax.set_ylabel('Process Compliance Score\n(Average of Notice% + Report-Out%)',
                  fontsize=12, fontweight='bold')
    ax.set_title('Committee Compliance Typology Matrix', fontsize=16, fontweight='bold', pad=20)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[OK] Created quadrant matrix: {output_path}")


def create_radar_charts(committees: Dict[str, Dict], output_path: Path):
    """Create radar/spider charts for each committee."""
    n_committees = len(committees)
    cols = min(3, n_committees)
    rows = (n_committees + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(6*cols, 6*rows),
                             subplot_kw=dict(projection='polar'))
    if n_committees == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    categories = ['Notice\nCompliance', 'Vote\nCompliance',
                  'Summary\nCompliance', 'Report-Out\nCompliance']
    n_categories = len(categories)
    angles = np.linspace(0, 2 * np.pi, n_categories, endpoint=False).tolist()
    angles += angles[:1]

    colors = plt.cm.tab10(np.linspace(0, 1, n_committees))

    for idx, (cid, data) in enumerate(committees.items()):
        ax = axes[idx]
        values = [
            data['notice_compliance_pct'],
            data['vote_compliance_pct'],
            data['summary_compliance_pct'],
            data['report_out_compliance_pct']
        ]
        values += values[:1]

        ax.plot(angles, values, 'o-', linewidth=2, label=cid, color=colors[idx])
        ax.fill(angles, values, alpha=0.25, color=colors[idx])

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, fontsize=10)
        ax.set_ylim(0, 100)
        ax.set_yticks([25, 50, 75, 100])
        ax.set_yticklabels(['25%', '50%', '75%', '100%'], fontsize=8)
        ax.grid(True)
        ax.set_title(f'Committee {cid}', fontsize=12, fontweight='bold', pad=20)

    for idx in range(n_committees, len(axes)):
        axes[idx].set_visible(False)

    plt.suptitle('Committee Compliance Profiles (Radar Charts)',
                 fontsize=16, fontweight='bold', y=0.995)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[OK] Created radar charts: {output_path}")


def create_heatmap(committees: Dict[str, Dict], output_path: Path):
    """Create compliance gap heatmap."""
    committee_ids = sorted(committees.keys())
    requirements = ['Notice', 'Votes', 'Summaries', 'Report-Out']

    data_matrix = []
    for cid in committee_ids:
        data = committees[cid]
        row = [
            data['notice_compliance_pct'],
            data['vote_compliance_pct'],
            data['summary_compliance_pct'],
            data['report_out_compliance_pct']
        ]
        data_matrix.append(row)

    data_array = np.array(data_matrix)

    fig, ax = plt.subplots(figsize=(10, max(6, len(committee_ids) * 0.5)))
    im = ax.imshow(data_array, cmap='RdYlGn', aspect='auto', vmin=0, vmax=100)

    ax.set_xticks(np.arange(len(requirements)))
    ax.set_yticks(np.arange(len(committee_ids)))
    ax.set_xticklabels(requirements, fontsize=11, fontweight='bold')
    ax.set_yticklabels(committee_ids, fontsize=10)

    for i in range(len(committee_ids)):
        for j in range(len(requirements)):
            ax.text(j, i, f'{data_array[i, j]:.0f}%',
                    ha="center", va="center", color="black", fontsize=9, fontweight='bold')

    cbar = plt.colorbar(im, ax=ax, label='Compliance Percentage', shrink=0.8)
    cbar.set_label('Compliance Percentage', fontsize=11, fontweight='bold')

    ax.set_title('Compliance Gap Analysis by Committee',
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xlabel('Compliance Requirements', fontsize=12, fontweight='bold')
    ax.set_ylabel('Committees', fontsize=12, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[OK] Created heatmap: {output_path}")


def extract_topic_keywords(title: str) -> List[str]:
    """Extract topic keywords from bill title."""
    if not title:
        return []

    topics = {
        'education': ['education', 'school', 'student', 'teacher', 'curriculum', 'academic'],
        'healthcare': ['health', 'medical', 'hospital', 'doctor', 'patient', 'medicare', 'medicaid'],
        'environment': ['environment', 'climate', 'energy', 'renewable', 'pollution', 'emission'],
        'housing': ['housing', 'rent', 'tenant', 'landlord', 'affordable housing'],
        'transportation': ['transportation', 'transit', 'highway', 'road', 'traffic', 'public transit'],
        'criminal justice': ['criminal', 'prison', 'sentencing', 'police', 'law enforcement'],
        'tax': ['tax', 'revenue', 'taxation', 'income tax'],
        'labor': ['labor', 'employment', 'worker', 'wage', 'union', 'workplace'],
        'municipal': ['municipal', 'town', 'city', 'local', 'municipality'],
        'budget': ['budget', 'appropriation', 'funding', 'finance']
    }

    title_lower = title.lower()
    found_topics = []

    for topic, keywords in topics.items():
        if any(keyword in title_lower for keyword in keywords):
            found_topics.append(topic)

    if not found_topics:
        found_topics = ['other']

    return found_topics


def create_topic_analysis(committees: Dict[str, Dict], output_path: Path):
    """Create bill topic compliance analysis."""
    topic_bills = defaultdict(list)

    for cid, data in committees.items():
        for bill in data['bills']:
            if not bill.get('hearing_date'):
                continue

            title = bill.get('bill_title', '')
            topics = extract_topic_keywords(title)
            is_compliant = bill.get('state') == 'Compliant'

            for topic in topics:
                topic_bills[topic].append({
                    'compliant': is_compliant,
                    'title': title
                })

    topic_stats = {}
    for topic, bills in topic_bills.items():
        if len(bills) < 3:
            continue
        compliant_count = sum(1 for b in bills if b['compliant'])
        compliance_rate = (compliant_count / len(bills)) * 100
        topic_stats[topic] = {'rate': compliance_rate, 'count': len(bills)}

    sorted_topics = sorted(topic_stats.items(), key=lambda x: x[1]['rate'], reverse=True)

    if not sorted_topics:
        print("[WARNING] No topic data available for analysis")
        return

    topics = [t[0].title() for t in sorted_topics]
    rates = [t[1]['rate'] for t in sorted_topics]
    counts = [t[1]['count'] for t in sorted_topics]

    fig, ax = plt.subplots(figsize=(12, 8))
    colors = ['green' if r >= 70 else 'orange' if r >= 50 else 'red' for r in rates]
    bars = ax.barh(topics, rates, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)

    for i, (rate, count) in enumerate(zip(rates, counts)):
        ax.text(rate + 1, i, f'{rate:.1f}% (n={count})',
                va='center', fontsize=9, fontweight='bold')

    ax.set_xlabel('Compliance Rate (%)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Bill Topic Category', fontsize=12, fontweight='bold')
    ax.set_title('Compliance Rates by Bill Topic', fontsize=14, fontweight='bold', pad=20)
    ax.set_xlim(0, 100)
    ax.grid(axis='x', alpha=0.3)

    legend_elements = [
        mpatches.Patch(facecolor='green', alpha=0.7, label='High (≥70%)'),
        mpatches.Patch(facecolor='orange', alpha=0.7, label='Medium (50-69%)'),
        mpatches.Patch(facecolor='red', alpha=0.7, label='Low (<50%)')
    ]
    ax.legend(handles=legend_elements, loc='lower right', fontsize=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"[OK] Created topic analysis: {output_path}")


def main():
    """Main function to generate all visualizations."""
    script_dir = Path(__file__).parent.parent
    json_dir = script_dir / "out" / "2025" / "12" / "04"
    output_dir = script_dir / "out" / "visualizations"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not json_dir.exists():
        print(f"[ERROR] JSON directory not found: {json_dir}")
        return

    print(f"Loading data from: {json_dir}")
    committees = load_committee_data(json_dir)

    if not committees:
        print("[ERROR] No committee data found")
        return

    print(f"Found {len(committees)} committees: {', '.join(sorted(committees.keys()))}")

    print("\nGenerating visualizations...")

    create_quadrant_matrix(committees, output_dir / "visualization_1_quadrant_matrix.png")
    create_radar_charts(committees, output_dir / "visualization_2_radar_charts.png")
    create_heatmap(committees, output_dir / "visualization_3_heatmap.png")
    create_topic_analysis(committees, output_dir / "visualization_4_topic_analysis.png")

    print(f"\n[SUCCESS] All visualizations saved to: {output_dir}")


if __name__ == "__main__":
    main()
