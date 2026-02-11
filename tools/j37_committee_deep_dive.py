#!/usr/bin/env python3
"""
J37 Deep-Dive: Visualization Scheme & Data Brief

Structural analysis of the Joint Committee on Telecommunications, Utilities,
and Energy (J37) compliance patterns in session 194. Generates five charts
and a summary CSV for watchdogs and journalists.

Charts:
    1. Compliance Funnel — Requirement attrition waterfall
    2. Hearing-to-Action Timeline — When bills were (or weren't) acted on
    3. Requirement Heatmap — Per-cohort compliance rates
    4. Lateness Profile — Distribution of days past deadline
    5. Vote Gap — Selective transparency pattern

Dependencies:
    pip install matplotlib numpy

Usage:
    python tools/j37_committee_deep_dive.py
    python tools/j37_committee_deep_dive.py --input out/2025/02/10/basic_J37.json
    python tools/j37_committee_deep_dive.py --input out/2025/02/10/basic_J37.json --output out/briefs/J37/
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ---------------------------------------------------------------------------
# Matplotlib global config (matches existing tools)
# ---------------------------------------------------------------------------
matplotlib.rcParams["font.family"] = "DejaVu Sans"
matplotlib.rcParams["axes.titlesize"] = 14
matplotlib.rcParams["axes.labelsize"] = 12
matplotlib.rcParams["xtick.labelsize"] = 10
matplotlib.rcParams["ytick.labelsize"] = 10


# ---------------------------------------------------------------------------
# Helpers (reused patterns from compliance_decay_analysis.py)
# ---------------------------------------------------------------------------

def parse_date(date_str: str) -> Optional[date]:
    """Parse date string in YYYY-MM-DD format."""
    if not date_str or date_str == "None":
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def analyze_failure_reasons(reason: str) -> Dict[str, bool]:
    """Parse the reason field to identify which requirements failed."""
    failures = {
        "missed_deadline": False,
        "no_votes": False,
        "no_summary": False,
        "insufficient_notice": False,
    }
    if not reason:
        return failures

    reason_lower = reason.lower()

    if "not reported out" in reason_lower or "reported out late" in reason_lower:
        failures["missed_deadline"] = True
    if "no votes" in reason_lower:
        failures["no_votes"] = True
    if "no summar" in reason_lower:
        failures["no_summary"] = True
    if "insufficient notice" in reason_lower:
        failures["insufficient_notice"] = True

    return failures


def is_notice_exempt(reason: str) -> bool:
    """Check if a bill is exempt from the notice requirement."""
    if not reason:
        return False
    return "exempt from notice requirement" in reason.lower()


def _spine_cleanup(ax, keep_bottom=True):
    """Remove top/right/left spines, style bottom."""
    for spine in ["top", "right", "left"]:
        ax.spines[spine].set_visible(False)
    if keep_bottom:
        ax.spines["bottom"].set_color("#bbbbbb")
    else:
        ax.spines["bottom"].set_visible(False)


# ---------------------------------------------------------------------------
# Data loading & analysis
# ---------------------------------------------------------------------------

def load_j37_data(input_path: Path) -> List[Dict]:
    """Load and enrich bill records from basic_J37.json."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    bills = []
    for bill in data.get("bills", []):
        hearing_date = parse_date(bill.get("hearing_date"))
        if not hearing_date:
            continue

        effective_deadline = parse_date(bill.get("effective_deadline"))
        reported_out_date = parse_date(bill.get("reported_out_date"))
        reason = bill.get("reason", "")
        failures = analyze_failure_reasons(reason)

        # Determine report-out timeliness
        reported_out = bill.get("reported_out", False)
        reported_on_time = False
        reported_late = False
        days_late = None

        if reported_out and reported_out_date and effective_deadline:
            if reported_out_date <= effective_deadline:
                reported_on_time = True
            else:
                reported_late = True
                days_late = (reported_out_date - effective_deadline).days

        bills.append({
            "bill_id": bill.get("bill_id"),
            "hearing_date": hearing_date,
            "effective_deadline": effective_deadline,
            "reported_out": reported_out,
            "reported_out_date": reported_out_date,
            "reported_on_time": reported_on_time,
            "reported_late": reported_late,
            "days_late": days_late,
            "summary_present": bill.get("summary_present", False),
            "votes_present": bill.get("votes_present", False),
            "state": bill.get("state", "Unknown"),
            "reason": reason,
            "failures": failures,
            "notice_exempt": is_notice_exempt(reason),
            "notice_gap_days": bill.get("notice_gap_days"),
        })

    return bills


def compute_statistics(bills: List[Dict]) -> Dict:
    """Compute all statistics needed for charts and console summary."""
    total = len(bills)
    summaries = sum(1 for b in bills if b["summary_present"])
    votes = sum(1 for b in bills if b["votes_present"])
    reported_out = sum(1 for b in bills if b["reported_out"])
    reported_on_time = sum(1 for b in bills if b["reported_on_time"])
    reported_late = sum(1 for b in bills if b["reported_late"])
    never_reported = total - reported_out
    notice_exempt = sum(1 for b in bills if b["notice_exempt"])
    compliant = sum(1 for b in bills if b["state"] == "Compliant")

    # Hearing cohorts
    cohorts = defaultdict(list)
    for b in bills:
        cohorts[b["hearing_date"]].append(b)

    # Report-out date clusters
    ro_date_counts = defaultdict(int)
    for b in bills:
        if b["reported_out_date"]:
            ro_date_counts[b["reported_out_date"]] += 1

    # Lateness distribution
    late_days = [b["days_late"] for b in bills if b["days_late"] is not None]

    return {
        "total": total,
        "summaries": summaries,
        "votes": votes,
        "reported_out": reported_out,
        "reported_on_time": reported_on_time,
        "reported_late": reported_late,
        "never_reported": never_reported,
        "notice_exempt": notice_exempt,
        "compliant": compliant,
        "cohorts": dict(sorted(cohorts.items())),
        "ro_date_counts": dict(sorted(ro_date_counts.items())),
        "late_days": sorted(late_days),
    }


def print_console_summary(stats: Dict):
    """Print summary statistics to the console."""
    t = stats["total"]
    print("\n" + "=" * 72)
    print("J37 DEEP-DIVE: SUMMARY STATISTICS")
    print("Joint Committee on Telecommunications, Utilities, and Energy")
    print("=" * 72)

    print(f"\n  Total bills heard:            {t}")
    print(f"  Summaries posted:             {stats['summaries']}/{t} ({stats['summaries']/t*100:.1f}%)")
    print(f"  Votes posted:                 {stats['votes']}/{t} ({stats['votes']/t*100:.1f}%)")
    print(f"  Reported out:                 {stats['reported_out']}/{t} ({stats['reported_out']/t*100:.1f}%)")
    print(f"    - On time:                  {stats['reported_on_time']}")
    print(f"    - Late:                     {stats['reported_late']}")
    print(f"  Never reported out:           {stats['never_reported']}")
    print(f"  Notice-exempt (pre-6/26):     {stats['notice_exempt']}")
    print(f"  Fully compliant:              {stats['compliant']}")

    print(f"\n  Hearing dates ({len(stats['cohorts'])} cohorts):")
    for hd, cohort_bills in stats["cohorts"].items():
        print(f"    {hd.strftime('%Y-%m-%d')}:  {len(cohort_bills)} bills")

    if stats["ro_date_counts"]:
        print(f"\n  Report-out date clusters:")
        for rd, count in stats["ro_date_counts"].items():
            print(f"    {rd.strftime('%Y-%m-%d')}:  {count} bills")

    if stats["late_days"]:
        arr = np.array(stats["late_days"])
        print(f"\n  Lateness profile ({len(arr)} late bills):")
        print(f"    Min days late:   {arr.min()}")
        print(f"    Max days late:   {arr.max()}")
        print(f"    Median:          {np.median(arr):.0f}")
        print(f"    Mean:            {arr.mean():.1f}")

    print("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# Chart 1: Compliance Funnel — Requirement Attrition Waterfall
# ---------------------------------------------------------------------------

def plot_compliance_funnel(stats: Dict, output_dir: Path):
    """Horizontal waterfall showing 228 bills filtered through each requirement gate."""
    t = stats["total"]

    labels = [
        "Bills Heard",
        "Summaries Posted",
        "Reported Out",
        "Reported Out On Time",
        "Votes Posted",
        "Fully Compliant",
    ]
    values = [
        t,
        stats["summaries"],
        stats["reported_out"],
        stats["reported_on_time"],
        stats["votes"],
        stats["compliant"],
    ]
    pcts = [v / t * 100 for v in values]

    fig, ax = plt.subplots(figsize=(12, 6))

    # Color gradient: gray → progressively warmer reds
    colors = ["#8c96a0", "#6baed6", "#f4a460", "#e07850", "#d04545", "#b01030"]

    y_positions = list(range(len(labels) - 1, -1, -1))

    bars = ax.barh(y_positions, values, color=colors, edgecolor="white", height=0.65)

    # Annotations
    for i, (y, val, pct) in enumerate(zip(y_positions, values, pcts)):
        # Value + pct label to the right of bar
        label = f"  {val}  ({pct:.1f}%)"
        ax.text(val + t * 0.01, y, label, va="center", fontsize=11, fontweight="bold",
                color="#2d2d2d")

    # Attrition annotations between bars
    for i in range(len(values) - 1):
        drop = values[i] - values[i + 1]
        if drop > 0:
            mid_y = (y_positions[i] + y_positions[i + 1]) / 2
            ax.annotate(
                f"\u2193 {drop} lost",
                xy=(min(values[i], values[i + 1]) / 2, mid_y),
                fontsize=9, color="#888888", ha="center", va="center",
                style="italic",
            )

    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_xlim(0, t * 1.35)
    ax.set_xlabel("Number of Bills", fontsize=12, fontweight="bold")
    ax.set_title(
        "The Compliance Funnel: Requirement Attrition\n"
        "J37 — Joint Committee on Telecommunications, Utilities, and Energy",
        fontsize=14, fontweight="bold", pad=20,
    )

    _spine_cleanup(ax)
    ax.grid(axis="x", linestyle="--", linewidth=0.6, alpha=0.25)
    ax.tick_params(left=False)

    plt.tight_layout()
    out = output_dir / "chart1_compliance_funnel.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Chart 2: Hearing-to-Action Timeline
# ---------------------------------------------------------------------------

def plot_hearing_to_action_timeline(bills: List[Dict], stats: Dict, output_dir: Path):
    """Connected dot/strip plot showing hearing → report-out for every bill."""
    fig, ax = plt.subplots(figsize=(16, 9))

    cohorts = stats["cohorts"]
    hearing_dates_sorted = sorted(cohorts.keys())

    # For each hearing date, jitter bills vertically
    legend_handles = []
    legend_added = {"on_time": False, "late": False, "never": False, "deadline": False}

    for hearing_date in hearing_dates_sorted:
        cohort_bills = cohorts[hearing_date]
        n = len(cohort_bills)

        # Sort bills: reported-on-time first, then late, then never
        cohort_bills_sorted = sorted(
            cohort_bills,
            key=lambda b: (0 if b["reported_on_time"] else 1 if b["reported_late"] else 2),
        )

        for i, b in enumerate(cohort_bills_sorted):
            # Vertical jitter within each hearing date column
            y_offset = (i - n / 2) * 0.25

            h_num = matplotlib.dates.date2num(hearing_date)
            hearing_y = y_offset

            if b["reported_on_time"]:
                color = "#1f5f8b"  # dark blue
                marker_alpha = 0.9
                lbl = "Reported on time" if not legend_added["on_time"] else None
                legend_added["on_time"] = True
            elif b["reported_late"]:
                color = "#e6850e"  # warm amber
                marker_alpha = 0.8
                lbl = "Reported late" if not legend_added["late"] else None
                legend_added["late"] = True
            else:
                color = "#cccccc"  # light gray
                marker_alpha = 0.4
                lbl = "Never reported out" if not legend_added["never"] else None
                legend_added["never"] = True

            # Hearing dot
            ax.plot(hearing_date, hearing_y, "o", color=color, alpha=marker_alpha,
                    markersize=4, zorder=3, label=lbl)

            # Connect to report-out date if exists
            if b["reported_out_date"]:
                ax.plot(
                    [hearing_date, b["reported_out_date"]],
                    [hearing_y, hearing_y],
                    color=color, alpha=marker_alpha * 0.6, linewidth=0.7, zorder=2,
                )
                ax.plot(b["reported_out_date"], hearing_y, "s", color=color,
                        alpha=marker_alpha, markersize=3.5, zorder=3)

    # 60-day deadline lines for each cohort
    for hearing_date in hearing_dates_sorted:
        sample = cohorts[hearing_date][0]
        deadline = sample["effective_deadline"]
        if deadline:
            lbl = "60-day deadline" if not legend_added["deadline"] else None
            legend_added["deadline"] = True
            ax.axvline(
                deadline, color="#cc3333", linestyle=":", linewidth=0.8, alpha=0.4,
                label=lbl, zorder=1,
            )

    # Batch report-out date annotations
    ro_counts = stats["ro_date_counts"]
    for ro_date, count in ro_counts.items():
        if count >= 5:
            ax.annotate(
                f"{ro_date.strftime('%m/%d')}\n({count} bills)",
                xy=(ro_date, ax.get_ylim()[1] * 0.85),
                fontsize=8, ha="center", color="#b03020", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8),
            )

    ax.set_xlabel("Date (2025)", fontsize=12, fontweight="bold")
    ax.set_ylabel("Bills (jittered by hearing cohort)", fontsize=12, fontweight="bold")
    ax.set_title(
        "Hearing-to-Action Timeline: When Bills Were (or Weren't) Acted On\n"
        "J37 — Each dot is a bill; lines connect hearing to report-out date",
        fontsize=14, fontweight="bold", pad=20,
    )

    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator())
    ax.xaxis.set_minor_locator(matplotlib.dates.WeekdayLocator(byweekday=matplotlib.dates.MO))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    # De-duplicate legend
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc="upper left", fontsize=10,
              framealpha=0.9)

    ax.grid(axis="x", alpha=0.15)
    ax.tick_params(left=False)
    ax.set_yticklabels([])
    _spine_cleanup(ax, keep_bottom=True)

    plt.tight_layout()
    out = output_dir / "chart2_hearing_to_action_timeline.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Chart 3: Requirement Heatmap by Hearing Cohort
# ---------------------------------------------------------------------------

def plot_requirement_heatmap(stats: Dict, output_dir: Path):
    """Heatmap grid: hearing dates as rows, requirements as columns."""
    cohorts = stats["cohorts"]
    hearing_dates = sorted(cohorts.keys())

    columns = ["Summary\nPosted", "Reported\nOut", "Reported Out\nOn Time", "Votes\nPosted"]
    data_matrix = []

    for hd in hearing_dates:
        cohort_bills = cohorts[hd]
        n = len(cohort_bills)
        row = [
            sum(1 for b in cohort_bills if b["summary_present"]) / n * 100,
            sum(1 for b in cohort_bills if b["reported_out"]) / n * 100,
            sum(1 for b in cohort_bills if b["reported_on_time"]) / n * 100,
            sum(1 for b in cohort_bills if b["votes_present"]) / n * 100,
        ]
        data_matrix.append(row)

    data_array = np.array(data_matrix)
    row_labels = [f"{hd.strftime('%b %d')} (n={len(cohorts[hd])})" for hd in hearing_dates]

    fig, ax = plt.subplots(figsize=(10, max(6, len(hearing_dates) * 0.55)))

    im = ax.imshow(data_array, cmap="RdYlGn", aspect="auto", vmin=0, vmax=100)

    ax.set_xticks(np.arange(len(columns)))
    ax.set_yticks(np.arange(len(hearing_dates)))
    ax.set_xticklabels(columns, fontsize=11, fontweight="bold")
    ax.set_yticklabels(row_labels, fontsize=10)

    # Cell annotations
    for i in range(len(hearing_dates)):
        for j in range(len(columns)):
            val = data_array[i, j]
            text_color = "white" if val < 30 or val > 85 else "black"
            ax.text(j, i, f"{val:.0f}%", ha="center", va="center",
                    color=text_color, fontsize=10, fontweight="bold")

    cbar = plt.colorbar(im, ax=ax, shrink=0.8, label="Compliance Rate (%)")
    cbar.set_label("Compliance Rate (%)", fontsize=11, fontweight="bold")

    ax.set_title(
        "Requirement Compliance by Hearing Cohort\n"
        "J37 — Green = high compliance, Red = low compliance",
        fontsize=14, fontweight="bold", pad=20,
    )
    ax.set_xlabel("Requirement", fontsize=12, fontweight="bold")
    ax.set_ylabel("Hearing Date", fontsize=12, fontweight="bold")

    plt.tight_layout()
    out = output_dir / "chart3_requirement_heatmap.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Chart 4: Lateness Profile — How Late Were the Late Report-Outs?
# ---------------------------------------------------------------------------

def plot_lateness_profile(bills: List[Dict], stats: Dict, output_dir: Path):
    """Histogram + strip overlay for days past deadline."""
    late_bills = [b for b in bills if b["days_late"] is not None and b["days_late"] > 0]

    if not late_bills:
        print("[WARNING] No late bills to plot for lateness profile")
        return

    days_late = np.array([b["days_late"] for b in late_bills])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), height_ratios=[3, 1],
                                    gridspec_kw={"hspace": 0.35})

    # --- Top: histogram ---
    bin_width = 5
    bins = np.arange(0, days_late.max() + bin_width + 1, bin_width)

    counts, edges, patches = ax1.hist(
        days_late, bins=bins, color="#e07850", edgecolor="white",
        alpha=0.85, zorder=3,
    )

    # Color bins by cluster
    for patch, left_edge in zip(patches, edges[:-1]):
        if left_edge < 20:
            patch.set_facecolor("#f4a460")  # near-miss amber
        else:
            patch.set_facecolor("#c0392b")  # deep red for very late

    # 30-day extension window reference
    ax1.axvline(30, color="#333333", linestyle="--", linewidth=1.5, alpha=0.6,
                label="30-day max extension window", zorder=4)

    # Cluster annotations
    near_miss = days_late[days_late <= 20]
    very_late = days_late[days_late > 20]

    if len(near_miss) > 0:
        ax1.annotate(
            f"Near-miss cluster\n{len(near_miss)} bills, {near_miss.min()}\u2013{near_miss.max()} days late\n"
            f"(Senate batch processing)",
            xy=(near_miss.mean(), counts[:int(20 / bin_width)].max() if int(20 / bin_width) < len(counts) else counts.max()),
            xytext=(near_miss.mean() + 15, counts.max() * 0.85),
            fontsize=9, ha="left",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow", alpha=0.9),
            arrowprops=dict(arrowstyle="->", color="#888", lw=1.2),
        )

    if len(very_late) > 0:
        peak_bin_idx = np.argmax(counts[int(20 / bin_width):]) + int(20 / bin_width) if int(20 / bin_width) < len(counts) else np.argmax(counts)
        ax1.annotate(
            f"Deep-late cluster\n{len(very_late)} bills, {very_late.min()}\u2013{very_late.max()} days late\n"
            f"(House & late-session batch)",
            xy=(very_late.mean(), counts[min(peak_bin_idx, len(counts)-1)]),
            xytext=(very_late.mean() + 15, counts.max() * 0.65),
            fontsize=9, ha="left",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#fde0d0", alpha=0.9),
            arrowprops=dict(arrowstyle="->", color="#888", lw=1.2),
        )

    ax1.set_xlabel("Days Past Effective Deadline", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Number of Bills", fontsize=12, fontweight="bold")
    ax1.set_title(
        f"Lateness Profile: How Late Were the {len(late_bills)} Late Report-Outs?\n"
        "J37 — Distribution of days past statutory deadline",
        fontsize=14, fontweight="bold", pad=20,
    )
    ax1.legend(loc="upper right", fontsize=10)
    ax1.grid(axis="y", alpha=0.2)
    _spine_cleanup(ax1)

    # --- Bottom: strip/jitter plot ---
    jitter = np.random.default_rng(42).normal(0, 0.08, size=len(days_late))

    for b in late_bills:
        color = "#f4a460" if b["days_late"] <= 20 else "#c0392b"
        ax2.plot(b["days_late"], jitter[late_bills.index(b)], "o",
                 color=color, alpha=0.6, markersize=5, zorder=3)

    ax2.axvline(30, color="#333333", linestyle="--", linewidth=1.5, alpha=0.6)

    ax2.set_xlabel("Days Past Effective Deadline", fontsize=12, fontweight="bold")
    ax2.set_yticks([])
    ax2.set_ylabel("Individual Bills", fontsize=10)
    ax2.set_title("Each dot is one bill", fontsize=11, fontweight="bold")
    ax2.grid(axis="x", alpha=0.15)
    _spine_cleanup(ax2, keep_bottom=True)

    plt.tight_layout()
    out = output_dir / "chart4_lateness_profile.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Chart 5: The Vote Gap — Selective Transparency Pattern
# ---------------------------------------------------------------------------

def plot_vote_gap(stats: Dict, output_dir: Path):
    """Grouped bar chart: summaries vs votes per hearing cohort."""
    cohorts = stats["cohorts"]
    hearing_dates = sorted(cohorts.keys())

    labels = [hd.strftime("%b %d") for hd in hearing_dates]
    summary_counts = []
    vote_counts = []
    reportout_rates = []

    for hd in hearing_dates:
        cohort_bills = cohorts[hd]
        n = len(cohort_bills)
        summary_counts.append(sum(1 for b in cohort_bills if b["summary_present"]))
        vote_counts.append(sum(1 for b in cohort_bills if b["votes_present"]))
        reportout_rates.append(
            sum(1 for b in cohort_bills if b["reported_out"]) / n * 100
        )

    x = np.arange(len(labels))
    bar_width = 0.35

    fig, ax1 = plt.subplots(figsize=(14, 7))

    bars_s = ax1.bar(x - bar_width / 2, summary_counts, bar_width,
                     label="Summaries Present", color="#2e86ab", edgecolor="white",
                     alpha=0.85, zorder=3)
    bars_v = ax1.bar(x + bar_width / 2, vote_counts, bar_width,
                     label="Votes Present", color="#e6850e", edgecolor="white",
                     alpha=0.85, zorder=3)

    # Value labels on bars
    for bar in bars_s:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.5, str(int(h)),
                     ha="center", va="bottom", fontsize=8, fontweight="bold",
                     color="#2e86ab")
    for bar in bars_v:
        h = bar.get_height()
        if h > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.5, str(int(h)),
                     ha="center", va="bottom", fontsize=8, fontweight="bold",
                     color="#e6850e")

    # Report-out rate overlay
    ax2 = ax1.twinx()
    ax2.plot(x, reportout_rates, "D-", color="#555555", alpha=0.6, markersize=5,
             linewidth=1.5, label="Report-Out Rate (%)", zorder=4)
    ax2.set_ylabel("Report-Out Rate (%)", fontsize=11, color="#555555")
    ax2.set_ylim(0, 105)
    ax2.tick_params(axis="y", colors="#555555")

    # Overall gap annotation
    total_summaries = stats["summaries"]
    total_votes = stats["votes"]
    gap_pct = (total_summaries - total_votes) / stats["total"] * 100
    ax1.annotate(
        f"Transparency deficit: {total_summaries - total_votes} bills\n"
        f"have summaries but no votes ({gap_pct:.0f}% of all bills)",
        xy=(len(x) * 0.6, max(summary_counts) * 0.85),
        fontsize=10, ha="center",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.9,
                  edgecolor="#cccccc"),
    )

    ax1.set_xlabel("Hearing Date (2025)", fontsize=12, fontweight="bold")
    ax1.set_ylabel("Number of Bills", fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=10)
    ax1.set_title(
        "The Vote Gap: Selective Transparency Pattern\n"
        "J37 — Summaries posted consistently; votes omitted systematically",
        fontsize=14, fontweight="bold", pad=20,
    )

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10,
               framealpha=0.9)

    ax1.grid(axis="y", alpha=0.15)
    _spine_cleanup(ax1)

    plt.tight_layout()
    out = output_dir / "chart5_vote_gap.png"
    plt.savefig(out, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Summary CSV
# ---------------------------------------------------------------------------

def save_summary_csv(bills: List[Dict], stats: Dict, output_dir: Path):
    """Save per-cohort summary statistics to CSV."""
    out = output_dir / "j37_summary_statistics.csv"

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "hearing_date", "bill_count",
            "summaries_present", "summary_pct",
            "reported_out", "reported_out_pct",
            "reported_on_time", "on_time_pct",
            "reported_late", "late_pct",
            "never_reported", "never_reported_pct",
            "votes_present", "votes_pct",
            "notice_exempt_count",
        ])

        for hd in sorted(stats["cohorts"].keys()):
            cohort_bills = stats["cohorts"][hd]
            n = len(cohort_bills)
            summaries = sum(1 for b in cohort_bills if b["summary_present"])
            ro = sum(1 for b in cohort_bills if b["reported_out"])
            on_time = sum(1 for b in cohort_bills if b["reported_on_time"])
            late = sum(1 for b in cohort_bills if b["reported_late"])
            never = n - ro
            votes = sum(1 for b in cohort_bills if b["votes_present"])
            exempt = sum(1 for b in cohort_bills if b["notice_exempt"])

            writer.writerow([
                hd.strftime("%Y-%m-%d"), n,
                summaries, f"{summaries/n*100:.1f}",
                ro, f"{ro/n*100:.1f}",
                on_time, f"{on_time/n*100:.1f}",
                late, f"{late/n*100:.1f}",
                never, f"{never/n*100:.1f}",
                votes, f"{votes/n*100:.1f}",
                exempt,
            ])

    print(f"[OK] Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def find_default_input() -> Optional[Path]:
    """Search for the most recent basic_J37.json in the out/ directory tree."""
    project_root = Path(__file__).parent.parent
    out_dir = project_root / "out"
    candidates = sorted(out_dir.glob("**/basic_J37.json"), reverse=True)
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description="J37 Deep-Dive: Compliance visualization & data brief"
    )
    parser.add_argument(
        "--input", "-i", type=Path, default=None,
        help="Path to basic_J37.json (auto-detected if omitted)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output directory (default: out/briefs/J37/)",
    )
    args = parser.parse_args()

    # Resolve input
    input_path = args.input
    if input_path is None:
        input_path = find_default_input()
        if input_path is None:
            print("[ERROR] No basic_J37.json found. Use --input to specify the path.")
            return
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}")
        return

    # Resolve output
    project_root = Path(__file__).parent.parent
    output_dir = args.output or (project_root / "out" / "briefs" / "J37")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("J37 DEEP-DIVE: VISUALIZATION & DATA BRIEF")
    print("=" * 72)
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_dir}")

    # Load & analyze
    bills = load_j37_data(input_path)
    if not bills:
        print("[ERROR] No bill data found in input file")
        return

    stats = compute_statistics(bills)
    print_console_summary(stats)

    # Generate charts
    print("\nGenerating charts...")
    plot_compliance_funnel(stats, output_dir)
    plot_hearing_to_action_timeline(bills, stats, output_dir)
    plot_requirement_heatmap(stats, output_dir)
    plot_lateness_profile(bills, stats, output_dir)
    plot_vote_gap(stats, output_dir)

    # CSV
    save_summary_csv(bills, stats, output_dir)

    print(f"\n{'=' * 72}")
    print(f"[OK] All outputs saved to: {output_dir}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
