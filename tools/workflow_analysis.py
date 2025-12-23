import re
import json
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

FILENAME_RE = re.compile(r"^basic_(J\d+)\.json$", re.IGNORECASE)


def committee_num(code):
    """
    'J11' -> 11
    """
    try:
        return int(code.upper().lstrip("J"))
    except Exception:
        return np.nan


def parse_date(s):
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_committee_rows(folder):
    folder = Path(folder)
    rows = []

    for p in folder.iterdir():
        if not p.is_file():
            continue
        m = FILENAME_RE.match(p.name)
        if not m:
            continue

        committee = m.group(1).upper()
        data = json.loads(p.read_text(encoding="utf-8"))
        bills = data.get("bills") or []

        for b in bills:
            state = b.get("state")
            if state == "Unknown":
                continue
            bill_id = b.get("bill_id")
            if not bill_id:
                continue

            scheduled_hearing_date = parse_date(
                b.get("scheduled_hearing_date")
            ) or parse_date(b.get("hearing_date"))
            reported_out_date = parse_date(b.get("reported_out_date"))

            rows.append(
                {
                    "committee": committee,
                    "bill_id": str(bill_id).strip(),
                    "notice_gap_days": b.get("notice_gap_days"),
                    "scheduled_hearing_date": scheduled_hearing_date,
                    "reported_out": bool(b.get("reported_out")),
                    "reported_out_date": reported_out_date,
                    "summary_present": bool(b.get("summary_present")),
                    "votes_present": bool(b.get("votes_present")),
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError(
            "No files matched basic_J*.json or no bills found inside them."
        )
    return df


def compute_metrics(df):
    # Per-committee dedupe: (committee, bill_id)
    df = df.drop_duplicates(subset=["committee", "bill_id"], keep="first").copy()

    # Days from hearing to reported-out (only where reported out + dates exist)
    def hearing_to_reported_days(r):
        if not r["reported_out"]:
            return np.nan
        hd, rd = r["scheduled_hearing_date"], r["reported_out_date"]
        if hd is None or rd is None:
            return np.nan
        return (rd - hd).days

    df["days_hearing_to_reported_out"] = df.apply(hearing_to_reported_days, axis=1)

    g = df.groupby("committee", dropna=False)

    out = pd.DataFrame(
        {
            "committee": g.size().index,
            "n_bills": g.size().values,
            "avg_notice_gap_days": g["notice_gap_days"].mean(numeric_only=True).values,
            "avg_days_hearing_to_reported_out": g["days_hearing_to_reported_out"]
            .mean(numeric_only=True)
            .values,
            "summary_rate": g["summary_present"].mean().values,
            "votes_rate": g["votes_present"].mean().values,
            "reported_out_rate": g["reported_out"].mean().values,
        }
    )
    out["committee_num"] = out["committee"].apply(committee_num)
    return out


def zscore(col):
    x = col.astype(float).to_numpy()
    mu = np.nanmean(x)
    sd = np.nanstd(x)
    if not np.isfinite(sd) or sd == 0:
        return np.zeros_like(x, dtype=float)
    return (x - mu) / sd


def export_heatmap(metrics_df, out_png, sort_by="avg_days_hearing_to_reported_out"):
    df = metrics_df.copy()

    if sort_by in df.columns:
        df = df.sort_values("committee_num", ascending=True, na_position="last")

    cols = [
        ("avg_notice_gap_days", "Hearing notice (avg days)"),
        ("avg_days_hearing_to_reported_out", "Hearing→Reported out (avg days)"),
        ("summary_rate", "Summary posted (%)"),
        ("votes_rate", "Votes posted (%)"),
        ("reported_out_rate", "Reported out (%)"),
    ]

    color_mat = np.column_stack([zscore(df[c]) for c, _ in cols])

    ann = []
    for _, r in df.iterrows():
        row_ann = []
        for c, _ in cols:
            v = r[c]
            if pd.isna(v):
                row_ann.append("—")
            elif c.endswith("_rate"):
                row_ann.append(f"{v*100:.0f}%")
            else:
                row_ann.append(f"{v:.1f}")
        ann.append(row_ann)
    ann = np.array(ann)

    fig_w = 12
    fig_h = max(6, 0.35 * len(df) + 2.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(color_mat, aspect="auto")

    ax.set_xticks(np.arange(len(cols)))
    ax.set_xticklabels([lab for _, lab in cols], rotation=20, ha="right")

    ax.set_yticks(np.arange(len(df)))
    ax.set_yticklabels([f"{c} (n={n})" for c, n in zip(df["committee"], df["n_bills"])])

    for i in range(color_mat.shape[0]):
        for j in range(color_mat.shape[1]):
            ax.text(j, i, ann[i, j], ha="center", va="center", fontsize=9)

    ax.set_title("Committee workflow profiles (relative color; exact values annotated)")
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("Relative vs other committees (z-score)")

    fig.tight_layout()
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    FOLDER = Path("out/2025/12/21")
    OUT_PNG = "committee_workflow_profiles.png"

    raw = load_committee_rows(FOLDER)
    metrics = compute_metrics(raw)
    export_heatmap(metrics, OUT_PNG, sort_by="avg_days_hearing_to_reported_out")

    print(f"Wrote {OUT_PNG}")
