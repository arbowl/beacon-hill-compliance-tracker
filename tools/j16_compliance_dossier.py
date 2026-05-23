#!/usr/bin/env python3
"""
J16 Compliance Dossier Generator
Joint Committee on Public Health — Session 194

Pulls all non-compliant / incomplete bills from J16, classifies them into
named failure anatomies, and emits a self-contained HTML report suitable
for cross-referencing by the committee, the Tracker team, or journalists.

Cross-references:
  - out/<latest>/basic_J16.json   — live compliance snapshot
  - bill_artifacts.db             — timeline actions, last DB action per bill

Usage:
    python tools/j16_compliance_dossier.py
    python tools/j16_compliance_dossier.py --input out/2026/05/23/basic_J16.json
    python tools/j16_compliance_dossier.py --input out/2026/05/23/basic_J16.json --output out/briefs/J16/

Outputs:
    j16_compliance_dossier.html   — main collaborative report
    j16_anatomy_summary.csv       — machine-readable per-bill classification
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def days_late(reported: Optional[date], deadline: Optional[date]) -> Optional[int]:
    if reported and deadline and reported > deadline:
        return (reported - deadline).days
    return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Tuple[List[Dict], str]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("bills", []), data.get("session", "194")


def load_db_actions(db_path: Path, bill_ids: List[str]) -> Dict[str, List[Tuple]]:
    """Return {bill_id: [(action_type, action_date, raw_text), ...]} sorted by date."""
    try:
        import duckdb
    except ImportError:
        return {}

    if not db_path.exists():
        return {}

    conn = duckdb.connect(str(db_path), read_only=True)
    placeholders = ",".join(["?" for _ in bill_ids])
    rows = conn.execute(f"""
        SELECT ba.bill_id, ta.action_type, ta.action_date, ta.raw_text
        FROM timeline_actions ta
        JOIN bill_artifacts ba ON ta.artifact_id = ba.artifact_id
        WHERE ba.committee_id = 'J16'
          AND ba.bill_id IN ({placeholders})
        ORDER BY ba.bill_id, ta.action_date, ta.action_type
    """, bill_ids).fetchall()
    conn.close()

    result: Dict[str, List] = defaultdict(list)
    for bid, atype, adate, raw in rows:
        result[bid].append((atype, adate, raw or ""))
    return dict(result)


# ---------------------------------------------------------------------------
# Bill enrichment & classification
# ---------------------------------------------------------------------------

ANATOMY_ORDER = [
    "late_report_out",
    "missing_votes",
    "missing_summary",
    "missing_both",
    "never_reported",
    "insufficient_notice",
    "no_hearing",
    "unknown",
]

ANATOMY_LABELS = {
    "late_report_out":      "A — Late Report-Out (Timing Violation)",
    "missing_votes":        "B — Missing Vote Record",
    "missing_summary":      "C — Missing Bill Summary",
    "missing_both":         "D — Missing Both Votes & Summary",
    "never_reported":       "E — Not Reported Out by Deadline",
    "insufficient_notice":  "F — Insufficient Hearing Notice",
    "no_hearing":           "G — No Hearing Found",
    "unknown":              "H — Unknown / Pending",
}

ANATOMY_DESC = {
    "late_report_out": (
        "Bills that were reported out of committee but after the 60-day statutory deadline "
        "(or effective extended deadline). The most common failure mode in J16. "
        "Subdivided by severity: Minor (1–30 days), Moderate (31–90 days), Severe (91+ days)."
    ),
    "missing_votes": (
        "Bills for which no committee vote record has been posted to the Legislature's website. "
        "Cross-listed with Section A when the bill is also late. "
        "Note: some of these bills were accompanied by a new draft; see Tracker Flag #1 below."
    ),
    "missing_summary": (
        "Bills reported out without a committee summary being posted. "
        "Summaries are required under Rule 194. Cross-listed with Section A when also late."
    ),
    "missing_both": (
        "Bills reported out with neither a vote record nor a summary posted — "
        "the most severe documentation failure short of non-reporting. "
        "Cross-listed with Section A when also late."
    ),
    "never_reported": (
        "Bills that were heard but never reported out before their effective deadline. "
        "The deadline has already passed; these remain in committee limbo."
    ),
    "insufficient_notice": (
        "Bills heard with fewer than the required 10 days' advance public notice. "
        "Constitutes a procedural violation independent of the 60-day report-out requirement."
    ),
    "no_hearing": (
        "Bills listed under J16 for which no hearing date can be determined. "
        "Cannot evaluate deadline compliance without a hearing anchor date."
    ),
    "unknown": (
        "Bills whose deadline had not yet passed as of the snapshot date, or for which "
        "compliance status cannot be determined. Not currently non-compliant."
    ),
}

SEVERITY_LABELS = {1: "Minor (1–30 days)", 2: "Moderate (31–90 days)", 3: "Severe (91+ days)"}


def lateness_severity(n: Optional[int]) -> int:
    if n is None or n <= 0:
        return 0
    if n <= 30:
        return 1
    if n <= 90:
        return 2
    return 3


def classify_bill(b: Dict, db_actions: List[Tuple]) -> Dict:
    """Enrich a bill dict with anatomy labels, lateness, DB context."""
    reason = b.get("reason", "")
    reported_out = b.get("reported_out", False)
    reported_date = parse_date(b.get("reported_out_date"))
    deadline = parse_date(b.get("effective_deadline"))
    has_votes = b.get("votes_present", False)
    has_summary = b.get("summary_present", False)
    state = b.get("state", "Unknown")

    late = days_late(reported_date, deadline)
    severity = lateness_severity(late)

    # Detect new-draft and study-order from DB
    db_action_types = {a[0] for a in db_actions}
    new_draft_ref = None
    study_order_ref = None
    last_action = db_actions[-1] if db_actions else None

    for atype, adate, raw in db_actions:
        if atype in ("ACCOMPANIED", "STUDY_ORDER"):
            if "new draft" in raw.lower() or "new bill" in raw.lower():
                new_draft_ref = raw
            if "study order" in raw.lower():
                study_order_ref = raw

    # --- anatomy assignment (can have multiple; primary is first) ---
    anatomies = []

    if state == "Compliant":
        pass  # no anatomy — these are in the report only for the cohort table
    elif state == "Unknown":
        anatomies.append("unknown")
    elif state == "Non-Compliant" or state == "Incomplete":
        no_votes_factor = not has_votes
        no_summary_factor = not has_summary
        late_factor = reported_out and late is not None and late > 0
        never_reported_factor = not reported_out and "not reported out by deadline" in reason.lower()
        notice_factor = "insufficient" in reason.lower()
        no_hearing_factor = reason.strip().lower().startswith("no hearing")

        if no_hearing_factor:
            anatomies.append("no_hearing")
        elif never_reported_factor:
            anatomies.append("never_reported")
        else:
            if late_factor:
                anatomies.append("late_report_out")
            if notice_factor:
                anatomies.append("insufficient_notice")

        # Doc failures are cross-cutting — append regardless of timing outcome
        if not no_hearing_factor and (state == "Non-Compliant" or state == "Incomplete"):
            if no_votes_factor and no_summary_factor:
                anatomies.append("missing_both")
            elif no_votes_factor:
                anatomies.append("missing_votes")
            elif no_summary_factor:
                anatomies.append("missing_summary")

        if not anatomies:
            anatomies.append("late_report_out")

    primary = anatomies[0] if anatomies else ("compliant" if state == "Compliant" else "unknown")
    return {
        **b,
        "anatomies": anatomies,
        "primary_anatomy": primary,
        "days_late": late,
        "severity": severity,
        "new_draft_ref": new_draft_ref,
        "study_order_ref": study_order_ref,
        "last_db_action": last_action,
        "db_action_types": db_action_types,
    }


# ---------------------------------------------------------------------------
# Interesting observations / potential tracker flags
# ---------------------------------------------------------------------------

def build_tracker_flags(enriched_bills: List[Dict]) -> List[Dict]:
    """Return a list of noteworthy findings that may indicate tracker inaccuracies."""
    flags = []

    # Flag 1: new-draft bills missing votes — may be a tracker follow-chain gap
    new_draft_no_votes = [
        b for b in enriched_bills
        if b.get("new_draft_ref") and not b.get("votes_present")
        and b["state"] == "Non-Compliant"
    ]
    if new_draft_no_votes:
        flags.append({
            "id": "F1",
            "title": "New-Draft Bills Flagged for Missing Votes",
            "severity": "medium",
            "count": len(new_draft_no_votes),
            "bill_ids": [b["bill_id"] for b in new_draft_no_votes],
            "detail": (
                "These bills were accompanied by a new draft (substitute bill). "
                "The Tracker flags the *original* bill as non-compliant for missing votes, "
                "but the committee vote and summary may be attached to the *new draft bill* "
                "rather than the originating bill number. "
                "Verify whether the new-draft bill has the vote record that should satisfy this requirement."
            ),
        })

    # Flag 2: bills with REPORTING_EXTENDED in DB but null extension_date in JSON
    ext_mismatch = [
        b for b in enriched_bills
        if "REPORTING_EXTENDED" in b.get("db_action_types", set())
        and not b.get("extension_date")
    ]
    if ext_mismatch:
        flags.append({
            "id": "F2",
            "title": "Reporting Extension in DB Not Reflected in JSON",
            "severity": "medium",
            "count": len(ext_mismatch),
            "bill_ids": [b["bill_id"] for b in ext_mismatch],
            "detail": (
                "The DB timeline shows a REPORTING_EXTENDED action for these bills, "
                "but the JSON snapshot has extension_date=null. "
                "If the extension moved the effective deadline forward, the Tracker may be "
                "computing the wrong deadline and wrongly classifying them as late."
            ),
        })

    # Flag 3: bills with study order in DB but marked Compliant in JSON
    compliant_study = [
        b for b in enriched_bills
        if b.get("study_order_ref") and b["state"] == "Compliant"
    ]
    if compliant_study:
        flags.append({
            "id": "F3",
            "title": "Compliant Bills Later Routed to Study Order",
            "severity": "low",
            "count": len(compliant_study),
            "bill_ids": [b["bill_id"] for b in compliant_study],
            "detail": (
                "These bills met the 60-day report-out requirement (correctly marked Compliant), "
                "but were subsequently accompanied into a study order. "
                "This is procedurally valid — the committee acted in time. "
                "However, the committee may dispute the 'Compliant' label if they believe "
                "the study-order outcome invalidates the earlier report-out."
            ),
        })

    # Flag 4: mass batch on 2026-03-16
    batch_date_bills = [b for b in enriched_bills if b.get("reported_out_date") == "2026-03-16"]
    if len(batch_date_bills) >= 10:
        flags.append({
            "id": "F4",
            "title": "Mass Batch Report-Out on 2026-03-16 (52 Bills)",
            "severity": "info",
            "count": len(batch_date_bills),
            "bill_ids": [b["bill_id"] for b in batch_date_bills],
            "detail": (
                f"{len(batch_date_bills)} bills were all reported out on the same date (2026-03-16). "
                "For bills heard on 2025-06-11 (deadline 2025-08-10), this is 218 days late. "
                "This pattern is consistent with a bulk study-order report-out event. "
                "Verify that the report-out dates recorded by the Tracker are correct for this batch "
                "and were not artifacts of a bulk data import."
            ),
        })

    # Flag 5: bills with no DB record at all
    no_db = [b for b in enriched_bills if not b.get("db_action_types")]
    if no_db:
        flags.append({
            "id": "F5",
            "title": "Bills With No Timeline Records in DB",
            "severity": "low",
            "count": len(no_db),
            "bill_ids": [b["bill_id"] for b in no_db],
            "detail": (
                "These bills appear in the JSON snapshot but have no entries in the "
                "timeline_actions table of bill_artifacts.db. "
                "This may mean the DB is stale relative to the JSON, or these bills were "
                "added to J16 after the last DB ingestion."
            ),
        })

    # Flag 6: notice-gap bills where gap is 0 or 1 day (extreme)
    extreme_notice = [
        b for b in enriched_bills
        if b.get("notice_gap_days") is not None
        and b["notice_gap_days"] < 3
        and b["state"] == "Non-Compliant"
    ]
    if extreme_notice:
        flags.append({
            "id": "F6",
            "title": "Extreme Notice Violations (< 3 Days)",
            "severity": "high",
            "count": len(extreme_notice),
            "bill_ids": [b["bill_id"] for b in extreme_notice],
            "detail": (
                "Bills with hearing notice given fewer than 3 days in advance — "
                "well below the 10-day requirement. "
                "Notice gaps of 0–1 days may indicate data-entry errors in the announcement date, "
                "or genuinely improper last-minute scheduling."
            ),
        })

    return flags


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    background: #f4f6f9;
    color: #1a1a2e;
    line-height: 1.5;
}
a { color: #1a56db; text-decoration: none; }
a:hover { text-decoration: underline; }

/* Layout */
.page-wrap { max-width: 1100px; margin: 0 auto; padding: 24px 20px; }

/* Header */
.report-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: #fff;
    padding: 32px 36px 28px;
    border-radius: 10px;
    margin-bottom: 28px;
}
.report-header h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
.report-header .subtitle { font-size: 13px; color: #a0aec0; }
.report-header .meta { font-size: 12px; color: #718096; margin-top: 10px; }

/* Summary cards */
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
}
.card {
    background: #fff;
    border-radius: 8px;
    padding: 16px 18px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
    text-align: center;
}
.card .num { font-size: 28px; font-weight: 700; }
.card .label { font-size: 11px; color: #718096; text-transform: uppercase; letter-spacing: .5px; }
.card.red .num { color: #c53030; }
.card.amber .num { color: #c05621; }
.card.green .num { color: #276749; }
.card.gray .num { color: #4a5568; }

/* Sections */
.section {
    background: #fff;
    border-radius: 8px;
    margin-bottom: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08);
    overflow: hidden;
}
.section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid #e2e8f0;
}
.section-header:hover { background: #f7fafc; }
.section-title { font-size: 15px; font-weight: 600; }
.section-badge {
    font-size: 12px;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 12px;
    min-width: 32px;
    text-align: center;
}
.badge-red { background: #fed7d7; color: #c53030; }
.badge-amber { background: #feebc8; color: #c05621; }
.badge-green { background: #c6f6d5; color: #276749; }
.badge-gray { background: #e2e8f0; color: #4a5568; }
.badge-blue { background: #bee3f8; color: #2b6cb0; }
.section-body { padding: 0; display: none; }
.section-body.open { display: block; }
.section-desc {
    padding: 12px 20px;
    font-size: 13px;
    color: #4a5568;
    background: #f7fafc;
    border-bottom: 1px solid #e2e8f0;
    font-style: italic;
}
.toggle-icon { font-size: 18px; color: #a0aec0; }

/* Bill table */
.bill-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.bill-table th {
    background: #f7fafc;
    padding: 9px 12px;
    text-align: left;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .4px;
    color: #718096;
    border-bottom: 1px solid #e2e8f0;
    white-space: nowrap;
}
.bill-table td {
    padding: 9px 12px;
    border-bottom: 1px solid #f0f4f8;
    vertical-align: top;
}
.bill-table tr:last-child td { border-bottom: none; }
.bill-table tr:hover td { background: #f7fafc; }
.bill-id { font-weight: 700; white-space: nowrap; }
.pill {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
    white-space: nowrap;
}
.pill-red { background: #fed7d7; color: #c53030; }
.pill-amber { background: #feebc8; color: #c05621; }
.pill-orange { background: #fefcbf; color: #975a16; }
.pill-green { background: #c6f6d5; color: #276749; }
.pill-gray { background: #e2e8f0; color: #4a5568; }
.pill-blue { background: #bee3f8; color: #2b6cb0; }
.pill-purple { background: #e9d8fd; color: #553c9a; }

/* Flags section */
.flags-wrap { padding: 16px 20px; }
.flag-card {
    border-left: 4px solid #e2e8f0;
    padding: 12px 16px;
    margin-bottom: 14px;
    border-radius: 0 6px 6px 0;
    background: #f7fafc;
}
.flag-card.high { border-color: #fc8181; background: #fff5f5; }
.flag-card.medium { border-color: #f6ad55; background: #fffaf0; }
.flag-card.low { border-color: #63b3ed; background: #ebf8ff; }
.flag-card.info { border-color: #9f7aea; background: #faf5ff; }
.flag-title { font-weight: 700; font-size: 13px; margin-bottom: 4px; }
.flag-detail { font-size: 12px; color: #4a5568; margin-bottom: 6px; }
.flag-bills { font-size: 11px; color: #718096; }

/* Cohort table */
.cohort-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cohort-table th, .cohort-table td {
    padding: 8px 14px;
    border-bottom: 1px solid #e2e8f0;
    text-align: left;
}
.cohort-table th { background: #f7fafc; font-weight: 600; font-size: 11px; text-transform: uppercase; color: #718096; }
.progress-bar-wrap { background: #e2e8f0; border-radius: 4px; height: 10px; width: 100px; overflow: hidden; display: inline-block; vertical-align: middle; }
.progress-bar-fill { height: 100%; border-radius: 4px; background: #fc8181; }

/* TOC */
.toc { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 20px;
       box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.toc h3 { font-size: 13px; font-weight: 700; margin-bottom: 10px; color: #4a5568; text-transform: uppercase; letter-spacing: .5px; }
.toc a { display: inline-block; margin-right: 10px; margin-bottom: 4px; font-size: 12px; }

/* Footer */
.footer { text-align: center; font-size: 11px; color: #a0aec0; margin-top: 32px; padding: 12px; }
"""

JS = """
function toggleSection(id) {
    const body = document.getElementById('body-' + id);
    const icon = document.getElementById('icon-' + id);
    if (body.classList.contains('open')) {
        body.classList.remove('open');
        icon.textContent = '+';
    } else {
        body.classList.add('open');
        icon.textContent = '−';
    }
}
function expandAll() {
    document.querySelectorAll('.section-body').forEach(el => el.classList.add('open'));
    document.querySelectorAll('.toggle-icon').forEach(el => el.textContent = '−');
}
function collapseAll() {
    document.querySelectorAll('.section-body').forEach(el => el.classList.remove('open'));
    document.querySelectorAll('.toggle-icon').forEach(el => el.textContent = '+');
}
"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _bill_link(bid: str, url: Optional[str]) -> str:
    if url:
        return f'<a href="{_esc(url)}" target="_blank">{_esc(bid)}</a>'
    return _esc(bid)


def _doc_link(label: str, url: Optional[str]) -> str:
    if url:
        return f'<a href="{_esc(url)}" target="_blank">{_esc(label)}</a>'
    return f'<span style="color:#a0aec0">{_esc(label)}</span>'


def _severity_pill(severity: int, days: Optional[int]) -> str:
    if days is None:
        return ""
    if severity == 1:
        cls = "pill-amber"
    elif severity == 2:
        cls = "pill-orange"
    else:
        cls = "pill-red"
    return f'<span class="pill {cls}">{days}d late</span>'


def _anatomy_badge(key: str, count: int) -> str:
    if "never" in key or "missing_both" in key or "no_hearing" in key:
        cls = "badge-red"
    elif "late" in key or "missing" in key or "notice" in key:
        cls = "badge-amber"
    elif "unknown" in key:
        cls = "badge-gray"
    else:
        cls = "badge-blue"
    return f'<span class="section-badge {cls}">{count}</span>'


def _flag_severity_label(s: str) -> str:
    m = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW", "info": "INFO"}
    return m.get(s, s.upper())


def build_bill_table(bills: List[Dict], show_cols: List[str]) -> str:
    """Build an HTML table for a list of enriched bills."""
    col_headers = {
        "bill_id": "Bill",
        "title": "Title",
        "hearing_date": "Hearing",
        "deadline": "Deadline",
        "reported_out_date": "Reported Out",
        "lateness": "Lateness",
        "votes": "Votes",
        "summary": "Summary",
        "notice": "Notice",
        "last_action": "Last DB Action",
        "new_draft": "New Draft",
        "factors": "Factors",
    }

    headers = "".join(f"<th>{col_headers.get(c, c)}</th>" for c in show_cols)
    rows_html = []

    for b in bills:
        cells = []
        for col in show_cols:
            if col == "bill_id":
                cells.append(f'<td class="bill-id">{_bill_link(b["bill_id"], b.get("bill_url"))}</td>')
            elif col == "title":
                title = b.get("bill_title", "")
                cells.append(f"<td>{_esc(title[:80])}{'…' if len(title) > 80 else ''}</td>")
            elif col == "hearing_date":
                cells.append(f'<td>{b.get("hearing_date") or ""}</td>')
            elif col == "deadline":
                cells.append(f'<td>{b.get("effective_deadline") or ""}</td>')
            elif col == "reported_out_date":
                d = b.get("reported_out_date")
                cells.append(f'<td>{d or "<em>—</em>"}</td>')
            elif col == "lateness":
                cells.append(f'<td>{_severity_pill(b["severity"], b["days_late"])}</td>')
            elif col == "votes":
                if b.get("votes_present"):
                    cells.append(f'<td>{_doc_link("Yes", b.get("votes_url"))}</td>')
                else:
                    cells.append('<td><span class="pill pill-red">No</span></td>')
            elif col == "summary":
                if b.get("summary_present"):
                    cells.append(f'<td>{_doc_link("Yes", b.get("summary_url"))}</td>')
                else:
                    cells.append('<td><span class="pill pill-red">No</span></td>')
            elif col == "notice":
                gap = b.get("notice_gap_days")
                if gap is None:
                    cells.append("<td>—</td>")
                elif gap < 10:
                    cells.append(f'<td><span class="pill pill-red">{gap}d</span></td>')
                else:
                    cells.append(f'<td><span class="pill pill-green">{gap}d</span></td>')
            elif col == "last_action":
                la = b.get("last_db_action")
                if la:
                    atype, adate, raw = la
                    cells.append(f'<td><strong>{_esc(atype)}</strong> <small style="color:#718096">{adate}</small><br><small>{_esc(raw[:80])}{"…" if len(raw) > 80 else ""}</small></td>')
                else:
                    cells.append("<td>—</td>")
            elif col == "new_draft":
                nd = b.get("new_draft_ref")
                if nd:
                    cells.append(f'<td><span class="pill pill-purple">Yes</span> <small style="color:#718096">{_esc(nd[nd.rfind("see ")+4:])}</small></td>')
                else:
                    cells.append("<td>—</td>")
            elif col == "factors":
                cells.append(f'<td style="font-size:11px;color:#4a5568">{_esc(b.get("reason",""))}</td>')
            else:
                cells.append(f"<td></td>")
        rows_html.append("<tr>" + "".join(cells) + "</tr>")

    if not rows_html:
        ncols = len(show_cols)
        return f'<table class="bill-table"><tbody><tr><td colspan="{ncols}" style="text-align:center;color:#a0aec0;padding:20px">No bills in this category</td></tr></tbody></table>'

    return (
        '<div style="overflow-x:auto">'
        f'<table class="bill-table"><thead><tr>{headers}</tr></thead><tbody>'
        + "".join(rows_html)
        + "</tbody></table></div>"
    )


def build_cohort_table(enriched_bills: List[Dict]) -> str:
    cohorts: Dict[str, List] = defaultdict(list)
    for b in enriched_bills:
        hd = b.get("hearing_date") or "Unknown"
        cohorts[hd].append(b)

    rows = []
    for hd in sorted(cohorts.keys()):
        bills = cohorts[hd]
        n = len(bills)
        nc = sum(1 for b in bills if b["state"] == "Non-Compliant")
        comp = sum(1 for b in bills if b["state"] == "Compliant")
        unk = sum(1 for b in bills if b["state"] == "Unknown")
        deadline = bills[0].get("effective_deadline") or "—"
        pct = int(nc / n * 100) if n > 0 else 0
        bar = f'<div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:{pct}%"></div></div>'
        rows.append(
            f"<tr><td>{hd}</td><td>{n}</td><td>{deadline}</td>"
            f'<td><span class="pill pill-red">{nc}</span></td>'
            f'<td><span class="pill pill-green">{comp}</span></td>'
            f'<td><span class="pill pill-gray">{unk}</span></td>'
            f"<td>{bar} {pct}%</td></tr>"
        )

    return (
        '<div style="overflow-x:auto"><table class="cohort-table">'
        "<thead><tr><th>Hearing Date</th><th>Bills</th><th>Deadline</th>"
        "<th>Non-Compliant</th><th>Compliant</th><th>Unknown</th><th>NC Rate</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def render_html(
    enriched_bills: List[Dict],
    flags: List[Dict],
    snapshot_path: Path,
    session: str,
    generated_date: str,
) -> str:
    total = len(enriched_bills)
    nc_count = sum(1 for b in enriched_bills if b["state"] == "Non-Compliant")
    comp_count = sum(1 for b in enriched_bills if b["state"] == "Compliant")
    unk_count = sum(1 for b in enriched_bills if b["state"] == "Unknown")
    nc_pct = f"{nc_count / total * 100:.1f}" if total else "0"

    # Group by ALL anatomies so bills appear in every relevant section.
    # A bill that is both late AND missing votes will appear in Section A (late)
    # and Section B (missing votes), enabling true cross-diagnosis.
    seen: Dict[str, set] = defaultdict(set)
    by_anatomy: Dict[str, List[Dict]] = defaultdict(list)
    for b in enriched_bills:
        for anatomy in b.get("anatomies", [b["primary_anatomy"]]):
            bid = b["bill_id"]
            if bid not in seen[anatomy]:
                seen[anatomy].add(bid)
                by_anatomy[anatomy].append(b)

    # Summary cards
    cards = f"""
<div class="summary-grid">
  <div class="card"><div class="num">{total}</div><div class="label">Total Bills</div></div>
  <div class="card red"><div class="num">{nc_count}</div><div class="label">Non-Compliant</div></div>
  <div class="card green"><div class="num">{comp_count}</div><div class="label">Compliant</div></div>
  <div class="card gray"><div class="num">{unk_count}</div><div class="label">Unknown/Pending</div></div>
  <div class="card amber"><div class="num">{nc_pct}%</div><div class="label">NC Rate</div></div>
</div>"""

    # TOC
    toc_links = " ".join(
        f'<a href="#section-{key}">{ANATOMY_LABELS[key]} ({len(by_anatomy.get(key, []))})</a>'
        for key in ANATOMY_ORDER
    ) + ' <a href="#section-flags">Tracker Flags</a> <a href="#section-cohorts">Cohorts</a>'
    toc = f"""
<div class="toc">
  <h3>Jump to Section</h3>
  {toc_links}
  <div style="margin-top:10px">
    <button onclick="expandAll()" style="font-size:11px;padding:3px 8px;cursor:pointer;border:1px solid #e2e8f0;border-radius:4px;background:#fff">Expand All</button>
    <button onclick="collapseAll()" style="font-size:11px;padding:3px 8px;cursor:pointer;border:1px solid #e2e8f0;border-radius:4px;background:#fff;margin-left:6px">Collapse All</button>
  </div>
</div>"""

    # Anatomy sections
    def make_section(key: str) -> str:
        bills = by_anatomy.get(key, [])
        label = ANATOMY_LABELS[key]
        desc = ANATOMY_DESC[key]
        badge = _anatomy_badge(key, len(bills))
        badge_cls = "badge-red" if "badge-red" in badge else "badge-amber" if "badge-amber" in badge else "badge-gray"

        if key == "late_report_out":
            # Subdivide by severity
            minor = sorted([b for b in bills if b["severity"] == 1], key=lambda b: b["days_late"] or 0)
            moderate = sorted([b for b in bills if b["severity"] == 2], key=lambda b: b["days_late"] or 0, reverse=True)
            severe = sorted([b for b in bills if b["severity"] == 3], key=lambda b: b["days_late"] or 0, reverse=True)
            cols = ["bill_id", "title", "hearing_date", "deadline", "reported_out_date", "lateness", "votes", "summary", "last_action"]
            inner = ""
            for sev_label, sev_bills in [("Severe (91+ days late)", severe), ("Moderate (31–90 days late)", moderate), ("Minor (1–30 days late)", minor)]:
                if sev_bills:
                    pill_cls = "pill-red" if "Severe" in sev_label else "pill-orange" if "Moderate" in sev_label else "pill-amber"
                    inner += f'<div style="padding:10px 20px 4px"><strong><span class="pill {pill_cls}">{sev_label}</span> — {len(sev_bills)} bills</strong></div>'
                    inner += build_bill_table(sev_bills, cols)
        elif key == "missing_both":
            cols = ["bill_id", "title", "hearing_date", "deadline", "reported_out_date", "lateness", "votes", "summary", "new_draft", "last_action"]
            inner = build_bill_table(sorted(bills, key=lambda b: b.get("reported_out_date") or ""), cols)
        elif key in ("missing_votes", "missing_summary"):
            cols = ["bill_id", "title", "hearing_date", "deadline", "reported_out_date", "lateness", "votes", "summary", "new_draft", "last_action"]
            inner = build_bill_table(sorted(bills, key=lambda b: b.get("reported_out_date") or ""), cols)
        elif key == "never_reported":
            cols = ["bill_id", "title", "hearing_date", "deadline", "votes", "summary", "last_action", "factors"]
            inner = build_bill_table(bills, cols)
        elif key == "insufficient_notice":
            cols = ["bill_id", "title", "hearing_date", "deadline", "reported_out_date", "lateness", "notice", "votes", "summary", "factors"]
            inner = build_bill_table(bills, cols)
        elif key == "no_hearing":
            cols = ["bill_id", "title", "factors", "last_action"]
            inner = build_bill_table(bills, cols)
        elif key == "unknown":
            cols = ["bill_id", "title", "hearing_date", "deadline", "factors"]
            inner = build_bill_table(bills, cols)
        else:
            cols = ["bill_id", "title", "hearing_date", "deadline", "reported_out_date", "lateness", "votes", "summary", "factors"]
            inner = build_bill_table(bills, cols)

        return f"""
<div class="section" id="section-{key}">
  <div class="section-header" onclick="toggleSection('{key}')">
    <div class="section-title">{_esc(label)}</div>
    <div style="display:flex;align-items:center;gap:10px">
      {badge}
      <span class="toggle-icon" id="icon-{key}">+</span>
    </div>
  </div>
  <div class="section-body" id="body-{key}">
    <div class="section-desc">{_esc(desc)}</div>
    {inner}
  </div>
</div>"""

    sections_html = "\n".join(make_section(key) for key in ANATOMY_ORDER)

    # Tracker flags section
    flags_inner = ""
    if flags:
        for flag in flags:
            sev_label = _flag_severity_label(flag["severity"])
            bill_list = ", ".join(flag["bill_ids"][:20])
            more = f" … and {len(flag['bill_ids']) - 20} more" if len(flag["bill_ids"]) > 20 else ""
            flags_inner += f"""
<div class="flag-card {flag['severity']}">
  <div class="flag-title">{flag['id']}: {_esc(flag['title'])}
    <span class="pill {'pill-red' if flag['severity'] == 'high' else 'pill-amber' if flag['severity'] == 'medium' else 'pill-blue' if flag['severity'] == 'low' else 'pill-purple'}" style="margin-left:8px;font-size:10px">{sev_label}</span>
    <span class="pill pill-gray" style="margin-left:4px;font-size:10px">{flag['count']} bill{'s' if flag['count'] != 1 else ''}</span>
  </div>
  <div class="flag-detail">{_esc(flag['detail'])}</div>
  <div class="flag-bills">Bills: {_esc(bill_list)}{_esc(more)}</div>
</div>"""
    else:
        flags_inner = '<p style="padding:16px 20px;color:#a0aec0">No tracker flags identified.</p>'

    flags_section = f"""
<div class="section" id="section-flags">
  <div class="section-header" onclick="toggleSection('flags')">
    <div class="section-title">Tracker Flags &amp; Methodology Notes</div>
    <div style="display:flex;align-items:center;gap:10px">
      <span class="section-badge badge-blue">{len(flags)}</span>
      <span class="toggle-icon" id="icon-flags">+</span>
    </div>
  </div>
  <div class="section-body" id="body-flags">
    <div class="section-desc">Potential data accuracy gaps, methodology questions, and noteworthy patterns
    identified during analysis. These are items to verify — not assertions of error.</div>
    <div class="flags-wrap">{flags_inner}</div>
  </div>
</div>"""

    # Cohort breakdown section
    cohort_section = f"""
<div class="section" id="section-cohorts">
  <div class="section-header" onclick="toggleSection('cohorts')">
    <div class="section-title">Hearing Cohort Breakdown</div>
    <div style="display:flex;align-items:center;gap:10px">
      <span class="toggle-icon" id="icon-cohorts">+</span>
    </div>
  </div>
  <div class="section-body" id="body-cohorts">
    <div class="section-desc">Non-compliance rate broken down by hearing date.
    Bills heard in the same session share the same 60-day deadline window.</div>
    <div style="padding:16px 20px">{build_cohort_table(enriched_bills)}</div>
  </div>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J16 Compliance Dossier — Session {_esc(session)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-wrap">
  <div class="report-header">
    <h1>J16 — Joint Committee on Public Health</h1>
    <div class="subtitle">Session {_esc(session)} Compliance Dossier — Non-Compliance Anatomy Report</div>
    <div class="meta">
      Generated: {_esc(generated_date)} &nbsp;|&nbsp;
      Snapshot: {_esc(str(snapshot_path))} &nbsp;|&nbsp;
      Purpose: Cross-diagnosis of compliance failure modes for internal review and committee response
    </div>
  </div>

  {cards}
  {toc}
  {sections_html}
  {flags_section}
  {cohort_section}

  <div class="footer">
    Beacon Hill Compliance Tracker — Session {_esc(session)} — J16 Dossier<br>
    This document does not assume absolute truth. All findings are subject to verification against primary sources.
  </div>
</div>
<script>{JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def save_csv(enriched_bills: List[Dict], out_path: Path):
    fieldnames = [
        "bill_id", "bill_title", "state", "primary_anatomy", "anatomies",
        "hearing_date", "effective_deadline", "reported_out", "reported_out_date",
        "days_late", "severity_label", "votes_present", "summary_present",
        "notice_gap_days", "new_draft_ref", "study_order_ref",
        "last_db_action_type", "last_db_action_date", "reason",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for b in enriched_bills:
            la = b.get("last_db_action")
            row = {
                **b,
                "anatomies": "|".join(b.get("anatomies", [])),
                "severity_label": SEVERITY_LABELS.get(b.get("severity", 0), ""),
                "last_db_action_type": la[0] if la else "",
                "last_db_action_date": la[1] if la else "",
            }
            w.writerow(row)
    print(f"[OK] Saved: {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def find_latest_json(project_root: Path) -> Optional[Path]:
    candidates = sorted((project_root / "out").glob("**/basic_J16.json"), reverse=True)
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(
        description="J16 Compliance Dossier — Non-Compliance Anatomy Report"
    )
    parser.add_argument("--input", "-i", type=Path, default=None,
                        help="Path to basic_J16.json (auto-detected if omitted)")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output directory (default: out/briefs/J16/)")
    parser.add_argument("--no-db", action="store_true",
                        help="Skip DB cross-reference even if bill_artifacts.db is present")
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent

    input_path = args.input
    if input_path is None:
        input_path = find_latest_json(project_root)
        if input_path is None:
            print("[ERROR] No basic_J16.json found. Use --input to specify the path.")
            sys.exit(1)
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_path}")
        sys.exit(1)

    output_dir = args.output or (project_root / "out" / "briefs" / "J16")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("J16 COMPLIANCE DOSSIER")
    print("Joint Committee on Public Health — Session 194")
    print("=" * 72)
    print(f"  Input:  {input_path}")
    print(f"  Output: {output_dir}")

    bills, session = load_json(input_path)
    print(f"  Bills loaded: {len(bills)}")

    # DB cross-reference
    db_actions: Dict[str, List] = {}
    if not args.no_db:
        db_path = project_root / "bill_artifacts.db"
        if db_path.exists():
            print(f"  DB: {db_path}")
            all_ids = [b["bill_id"] for b in bills]
            db_actions = load_db_actions(db_path, all_ids)
            print(f"  DB records found for: {len(db_actions)} bills")
        else:
            print("  [WARN] bill_artifacts.db not found — skipping DB cross-reference")

    # Enrich & classify
    enriched = [classify_bill(b, db_actions.get(b["bill_id"], [])) for b in bills]

    # Flags
    flags = build_tracker_flags(enriched)
    print(f"  Tracker flags: {len(flags)}")

    # Console summary (multi-anatomy: a bill may appear in several categories)
    nc = [b for b in enriched if b["state"] == "Non-Compliant"]
    from collections import Counter
    anat_counts: Counter = Counter()
    for b in nc:
        for a in b.get("anatomies", [b["primary_anatomy"]]):
            anat_counts[a] += 1
    print()
    print("  Non-Compliant anatomy breakdown (bills may appear in multiple categories):")
    for key in ANATOMY_ORDER:
        n = anat_counts.get(key, 0)
        if n:
            print(f"    {ANATOMY_LABELS[key]}: {n}")

    # Generate outputs
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(enriched, flags, input_path, session, generated)

    html_path = output_dir / "j16_compliance_dossier.html"
    html_path.write_text(html, encoding="utf-8")
    print(f"\n[OK] Saved: {html_path}")

    csv_path = output_dir / "j16_anatomy_summary.csv"
    save_csv(enriched, csv_path)

    print(f"\n{'=' * 72}")
    print(f"  Done. Open in a browser:")
    print(f"  {html_path}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
