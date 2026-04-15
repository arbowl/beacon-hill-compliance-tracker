"""chart.py — Horizontal bar chart of compliance violations from the latest run.

Violation categories:
  • Hearing notice
  • Reporting deadlines (late)
  • Reporting deadlines (missed)
  • Summary violations
  • Vote violations

Bars are sorted smallest-at-top → largest-at-bottom.

Usage:
    python chart.py              # latest date dir
    python chart.py 2026-04-05   # specific date
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Re-use all data loading and classification logic from printout.py
from tools.printout import (
    find_latest_date_dir,
    date_dir_for,
    load_bills,
    is_notice_violation,
    is_deadline_late,
    is_deadline_unreported,
    is_summary_violation,
    is_vote_violation,
)

try:
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
except ImportError:
    print("Error: matplotlib is required.  Run:  pip install matplotlib", file=sys.stderr)
    sys.exit(1)


# ── palette ────────────────────────────────────────────────────────────────────
COLORS = {
    "Hearing notice":              "#4C72B0",
    "Reporting deadlines (late)":  "#DD8452",
    "Reporting deadlines (missed)":"#C44E52",
    "Summary violations":          "#55A868",
    "Vote violations":             "#8172B2",
}


def build_counts(bills: list[dict]) -> dict[str, int]:
    return {
        "Hearing notice":               sum(1 for b in bills if is_notice_violation(b)),
        "Reporting deadlines (late)":   sum(1 for b in bills if is_deadline_late(b)),
        "Reporting deadlines (missed)": sum(1 for b in bills if is_deadline_unreported(b)),
        "Summary violations":           sum(1 for b in bills if is_summary_violation(b)),
        "Vote violations":              sum(1 for b in bills if is_vote_violation(b)),
    }


def main() -> None:
    # ── resolve date directory ──────────────────────────────────────────────────
    if len(sys.argv) > 1:
        try:
            target = date.fromisoformat(sys.argv[1])
            date_dir = date_dir_for(target)
            data_date = target
        except ValueError:
            print(f"Error: invalid date '{sys.argv[1]}' — expected YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)
    else:
        date_dir, data_date = find_latest_date_dir()

    if date_dir is None or not date_dir.exists():
        print("Error: no output data found.", file=sys.stderr)
        sys.exit(1)

    bills = load_bills(date_dir)
    counts = build_counts(bills)

    # ── sort: largest at bottom (last in barh = visually bottom) ───────────────
    # matplotlib barh draws first item at bottom, so reverse-sort so largest ends up at bottom
    sorted_items = sorted(counts.items(), key=lambda x: x[1])  # ascending → smallest first → smallest at top in barh

    labels = [item[0] for item in sorted_items]
    values = [item[1] for item in sorted_items]
    bar_colors = [COLORS[label] for label in labels]

    # ── draw ───────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 4.5))

    bars = ax.barh(labels, values, color=bar_colors, height=0.55, edgecolor="white", linewidth=0.8)

    # Value labels at the end of each bar
    for bar, val in zip(bars, values):
        x_pos = bar.get_width()
        ax.text(
            x_pos + max(values) * 0.012,
            bar.get_y() + bar.get_height() / 2,
            str(val),
            va="center",
            ha="left",
            fontsize=10,
            color="#333333",
        )

    ax.set_xlabel("Number of bills", fontsize=10, labelpad=8)
    ax.set_title(
        f"Beacon Hill Compliance — Violation Summary\nData date: {data_date}",
        fontsize=12,
        fontweight="bold",
        pad=14,
    )

    ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_xlim(0, max(values) * 1.15 if values else 10)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(axis="y", labelsize=10)
    ax.tick_params(axis="x", labelsize=9)

    fig.tight_layout()
    plt.show()


if __name__ == "__main__":
    main()
