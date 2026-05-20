#!/usr/bin/env python3
"""
Generate compliance cost report: committee chairs, stipends, and compliance records.

Usage:
    python tools/stipends/generate_report.py
    python tools/stipends/generate_report.py --output path/to/report.html
    python tools/stipends/generate_report.py --date 2026-04-14  (use specific report date)

Reads from:
  - tools/stipends/profiles/*.json     (Beacon Hill Stipends data)
  - cache/cache.json                   (committee contacts / chairs)
  - out/YYYY/MM/DD/basic_*.json        (compliance reports, latest by default)

Outputs:
  - tools/stipends/compliance_cost_report.html (default)
"""

import argparse
import glob
import json
import pathlib
import unicodedata
from datetime import date, datetime


# ── Name-matching overrides ──────────────────────────────────────────────────
# Maps exact cache chair_name strings → profile member_id.
# Needed when the name stored in cache can't be normalized to match the profile
# (double-encoded Unicode, compound last names, non-abbreviated middle names).
MEMBER_ID_OVERRIDES: dict[str, str] = {
    "Jack Patrick Lewis": "JPL1",    # profile uses "Jack Lewis"
    "Cynthia Stone Creem": "CSC0",   # profile uses "Cynthia Creem"
}

# Correct display names for profiles whose JSON has double-encoded UTF-8.
DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    "A_G0": "Adam Gómez",
    "H_G1": "Homar Gómez",
    "C_G1": "Carlos González",
    "S_M1": "Samantha Montaño",
}

# The cache stores Gómez/González names with a broken code point; catch them
# by testing for the garbled fragment rather than a literal key comparison.
_GOMEZ_FRAGMENT = "G�mez"


# ── Data loading ─────────────────────────────────────────────────────────────

def load_stipend_profiles(profiles_dir: pathlib.Path) -> dict[str, dict]:
    """Returns {member_id: profile_dict} for all profiles in profiles_dir."""
    profiles: dict[str, dict] = {}
    for path in profiles_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles[data["member_id"]] = data
    return profiles


def build_name_index(profiles: dict[str, dict]) -> dict[str, str]:
    """Returns {normalized_name: member_id} for fuzzy-matching by name."""
    index: dict[str, str] = {}
    for member_id, data in profiles.items():
        norm = _normalize(data["name"])
        index[norm] = member_id
    return index


def load_cache(cache_path: pathlib.Path) -> dict:
    return json.loads(cache_path.read_text(encoding="utf-8"))


def find_latest_report_date(out_dir: pathlib.Path) -> str:
    """Returns latest YYYY/MM/DD path string under out_dir."""
    dates = set()
    for f in out_dir.rglob("basic_*.json"):
        parts = f.relative_to(out_dir).parts
        if len(parts) >= 4:
            dates.add("/".join(parts[:3]))
    if not dates:
        raise FileNotFoundError("No compliance reports found under out/")
    return sorted(dates)[-1]


def load_compliance_reports(out_dir: pathlib.Path, date_path: str) -> dict[str, dict]:
    """Returns {committee_id: report_dict} for all reports on date_path."""
    reports: dict[str, dict] = {}
    dir_path = out_dir / date_path.replace("/", "\\")
    for f in dir_path.glob("basic_*.json"):
        committee_id = f.stem.replace("basic_", "")
        reports[committee_id] = json.loads(f.read_text(encoding="utf-8"))
    return reports


# ── Name normalization ────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Lower-case, strip accents, remove middle initials and name suffixes."""
    # Decompose accents then strip combining marks
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    name = name.lower().strip()
    for suffix in (", iii", ", jr.", ", jr", ", sr.", ", sr"):
        name = name.replace(suffix, "")
    # Remove tokens that look like middle initials (single alpha letter + period)
    parts = [p for p in name.split() if not (len(p) == 2 and p[1] == ".")]
    return " ".join(parts)


def resolve_chair(
    raw_name: str,
    name_index: dict[str, str],
    profiles: dict[str, dict],
) -> tuple[str | None, dict | None]:
    """Return (member_id, profile) for a raw cache chair name, or (None, None)."""
    if not raw_name:
        return None, None

    # Explicit overrides first
    if raw_name in MEMBER_ID_OVERRIDES:
        mid = MEMBER_ID_OVERRIDES[raw_name]
        return mid, profiles.get(mid)

    # Catch double-encoded Gómez
    if _GOMEZ_FRAGMENT in raw_name:
        first = raw_name.split()[0].lower()
        for mid, p in profiles.items():
            if "gomez" in _normalize(p["name"]) and p["name"].lower().startswith(first):
                return mid, p
        return None, None

    norm = _normalize(raw_name)
    mid = name_index.get(norm)
    if mid:
        return mid, profiles[mid]

    return None, None


# ── Compliance calculation ────────────────────────────────────────────────────

def compute_compliance_stats(bills: list[dict], report_date_str: str) -> dict:
    """
    Compute compliance stats for a list of bill records.

    Only counts bills whose effective_deadline has passed (decided bills).
    Unknown/pending bills (no deadline or future deadline) are excluded.
    """
    report_dt = date.fromisoformat(report_date_str)

    decided = [
        b for b in bills
        if b.get("effective_deadline")
        and b["effective_deadline"] != "None"
        and b["effective_deadline"] is not None
        and date.fromisoformat(b["effective_deadline"]) <= report_dt
    ]

    total = len(bills)
    decided_count = len(decided)
    compliant = sum(1 for b in decided if b["state"] == "Compliant")
    non_compliant = sum(1 for b in decided if b["state"] == "Non-Compliant")
    incomplete = sum(1 for b in decided if b["state"] == "Incomplete")

    compliance_rate = (compliant / decided_count * 100) if decided_count > 0 else None

    return {
        "total_bills": total,
        "decided_bills": decided_count,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "incomplete": incomplete,
        "compliance_rate": compliance_rate,
    }


# ── Row building ─────────────────────────────────────────────────────────────

def get_chair_stipend(profile: dict) -> int | None:
    """Per-position committee chair stipend: first paid breakdown entry whose
    role_code ends with _CHAIR (excluding _VICE_CHAIR and leadership roles)."""
    _EXCLUDE = ("_VICE_CHAIR", "_LEADER", "_PRESIDENT", "_SPEAKER", "_WHIP")
    for comp in profile.get("compensation", {}).get("components", []):
        if "9B" in comp.get("label", "") or "Stipend" in comp.get("label", ""):
            for entry in comp.get("details", {}).get("breakdown", []):
                rc = entry.get("role_code", "")
                if (rc.endswith("_CHAIR")
                        and not any(rc.endswith(x) for x in _EXCLUDE)
                        and entry.get("paid", False)):
                    return entry["adjusted_amount"]
    return None


def get_total_pay(profile: dict) -> int | None:
    """Total compensation (base + stipends + travel)."""
    return profile.get("compensation", {}).get("total")


def build_rows(
    cache: dict,
    reports: dict[str, dict],
    profiles: dict[str, dict],
    name_index: dict[str, str],
    report_date: str,
) -> list[dict]:
    """Build one row per (committee, chair_chamber) pair, joint committees only."""
    contacts = cache.get("committee_contacts", {})
    rows = []

    for committee_id, report in reports.items():
        if not committee_id.startswith("J"):
            continue

        contact = contacts.get(committee_id, {})
        committee_name = contact.get("name", committee_id)
        stats = compute_compliance_stats(report.get("bills", []), report_date)

        chair_slots = [
            ("House", contact.get("house_chair_name", "")),
            ("Senate", contact.get("senate_chair_name", "")),
        ]

        for chamber, raw_name in chair_slots:
            if not raw_name:
                continue
            member_id, profile = resolve_chair(raw_name, name_index, profiles)
            chair_stipend = get_chair_stipend(profile) if profile else None
            total_pay = get_total_pay(profile) if profile else None
            if member_id and member_id in DISPLAY_NAME_OVERRIDES:
                display_name = DISPLAY_NAME_OVERRIDES[member_id]
            elif profile:
                display_name = profile["name"]
            else:
                display_name = raw_name

            if stats["decided_bills"] == 0:
                continue

            rows.append({
                "chair": display_name,
                "chamber": chamber,
                "committee_id": committee_id,
                "committee_name": committee_name,
                "member_id": member_id,
                "chair_stipend": chair_stipend,
                "total_pay": total_pay,
                "stats": stats,
            })

    # Sort by compliance ascending (worst first), then total_pay descending as tiebreaker.
    def sort_key(r):
        cr = r["stats"]["compliance_rate"] if r["stats"]["compliance_rate"] is not None else 200
        tp = r["total_pay"] if r["total_pay"] is not None else 0
        return (cr, -tp)

    rows.sort(key=sort_key)
    return rows


# ── HTML generation ───────────────────────────────────────────────────────────

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stipends &amp; Statutory Compliance -- Massachusetts Legislature</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --ink: #1a1a1a;
      --paper: #faf8f5;
      --accent: #8b2332;
      --muted: #6b6b6b;
      --rule: #d4d0c8;
      --highlight: #fff3cd;
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    body {{
      font-family: 'Source Sans 3', system-ui, sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.7;
      font-size: 16px;
    }}

    .container {{
      max-width: 980px;
      margin: 0 auto;
      padding: 2rem 1.5rem 4rem;
    }}

    /* ── Header ────────────────────────────────────────────────── */

    header {{
      text-align: center;
      padding: 3rem 0 2.5rem;
      border-bottom: 3px double var(--rule);
      margin-bottom: 2.5rem;
    }}

    .kicker {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.15em;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 0.75rem;
    }}

    h1 {{
      font-family: 'Libre Baskerville', Georgia, serif;
      font-size: clamp(1.7rem, 4vw, 2.4rem);
      font-weight: 700;
      line-height: 1.2;
      margin-bottom: 0.75rem;
      letter-spacing: -0.02em;
    }}

    .subtitle {{
      font-size: 1.1rem;
      color: var(--muted);
      font-style: italic;
      font-family: 'Libre Baskerville', Georgia, serif;
      max-width: 600px;
      margin: 0 auto 1.25rem;
    }}

    .byline {{
      font-size: 0.85rem;
      color: var(--muted);
    }}

    /* ── Intro ─────────────────────────────────────────────────── */

    .intro {{
      font-size: 1rem;
      color: var(--ink);
      margin-bottom: 1.5rem;
    }}

    .as-of-banner {{
      background: var(--highlight);
      border: 1px solid #e6c84a;
      padding: 0.6rem 1rem;
      border-radius: 3px;
      font-size: 0.85rem;
      margin-bottom: 1.5rem;
      color: #5a4a00;
      display: inline-block;
    }}

    /* ── Table ─────────────────────────────────────────────────── */

    .table-wrap {{
      overflow-x: auto;
      margin: 0 -1.5rem;
    }}

    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 0.875rem;
      background: white;
    }}

    thead th {{
      text-align: left;
      font-weight: 700;
      padding: 0.65rem 0.75rem;
      border-bottom: 2px solid var(--ink);
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--ink);
      white-space: nowrap;
    }}

    thead th.num {{ text-align: right; }}

    tbody tr {{ border-bottom: 1px solid var(--rule); }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #f5f2ee; }}

    td {{
      padding: 0.55rem 0.75rem;
      vertical-align: middle;
    }}

    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}

    .chair-name {{
      font-weight: 600;
      color: var(--ink);
    }}

    .chamber-badge {{
      display: inline-block;
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 1px 5px;
      border-radius: 2px;
      background: #e8e4dc;
      color: var(--muted);
    }}

    .chamber-badge.senate {{ background: #e3eaf5; color: #3a5a8c; }}
    .chamber-badge.house  {{ background: #e8f0e4; color: #3a6a2a; }}

    .committee-name {{ color: #444; }}

    .stipend-val {{
      font-variant-numeric: tabular-nums;
      font-weight: 600;
    }}

    .stipend-none {{ color: #bbb; }}

    /* compliance bar */
    .compliance-cell {{
      display: flex;
      align-items: center;
      gap: 8px;
      justify-content: flex-end;
    }}

    .bar-track {{
      width: 64px;
      height: 6px;
      background: #e8e4dc;
      border-radius: 3px;
      overflow: hidden;
      flex-shrink: 0;
    }}

    .bar-fill {{
      display: block;
      height: 100%;
      border-radius: 3px;
      background: var(--accent);
    }}

    .pct-label {{
      font-variant-numeric: tabular-nums;
      min-width: 38px;
      text-align: right;
      font-size: 0.82rem;
    }}

    .no-data {{ color: #bbb; }}

    /* ── Methodology ───────────────────────────────────────────── */

    .methodology-box {{
      background: #f0ece4;
      padding: 1.5rem;
      margin: 2.5rem 0 0;
      border-radius: 4px;
      font-size: 0.85rem;
      line-height: 1.65;
    }}

    .methodology-box h3 {{
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      margin-bottom: 1rem;
      color: var(--muted);
      font-weight: 700;
    }}

    .methodology-box p {{
      margin-bottom: 0.5rem;
      color: var(--muted);
    }}

    .methodology-box p:last-child {{ margin-bottom: 0; }}

    .methodology-box a {{ color: var(--accent); text-decoration: none; }}
    .methodology-box a:hover {{ text-decoration: underline; }}

    /* ── Footer ────────────────────────────────────────────────── */

    footer {{
      margin-top: 2.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid var(--rule);
      font-size: 0.85rem;
      color: var(--muted);
    }}

    footer p {{ margin-bottom: 0.4rem; }}
    footer a {{ color: var(--accent); text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}

    @media (max-width: 640px) {{
      .table-wrap {{ margin: 0 -1rem; }}
      .bar-track {{ width: 40px; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <header>
    <div class="kicker">Massachusetts Legislative Analysis &middot; 194th General Court</div>
    <h1>Stipends &amp; Statutory Compliance</h1>
    <p class="subtitle">What committee chairs are paid, and how often their committees meet the rules&rsquo;s requirements</p>
    <p class="byline">Beacon Hill Compliance Tracker &nbsp;&middot;&nbsp; Beacon Hill Stipends</p>
  </header>

  <p class="intro">
    Committee chairs receive annual stipends under M.G.L. c.3 §9B for their
    leadership roles. Joint Rules require committees to hold public hearings
    and report bills out within statutory deadlines. The table below shows each
    chair&rsquo;s stipend alongside their committee&rsquo;s compliance record,
    sorted by chair stipend.
  </p>

  <div class="as-of-banner">Data as of <strong>{report_date_display}</strong></div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Chair</th>
          <th>Chmb.</th>
          <th>Committee</th>
          <th class="num">Chair Stipend&sup2;</th>
          <th class="num">Total Pay&sup3;</th>
          <th class="num">Compliance</th>
          <th class="num">Bills&sup1;</th>
          <th class="num">Violations</th>
        </tr>
      </thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>

  <div class="methodology-box">
    <h3>Methodology &amp; Notes</h3>
    <p>&sup1; <strong>Bills evaluated</strong> = bills with complete compliance milestones; bills still in progress with incomplete records were excluded. &ldquo;Violations&rdquo; = bills classified Non-Compliant (missed one or more statutory requirements).</p>
    <p>&sup2; <strong>Chair Stipend</strong> = the Section 9B stipend for one committee chair position (M.G.L. c.3 §9B). Legislators who chair multiple committees receive this amount per qualifying position, subject to a two-position cap under Senate Rule 11E.</p>
    <p>&sup3; <strong>Total Pay</strong> = base salary + all Section 9B stipends + travel allowance (M.G.L. c.3 §§9B&ndash;9C). Joint committee chairs appear once per chamber.</p>
    <p><strong>Sources:</strong> Stipend data from <a href="https://beaconhillstipends.org/">Beacon Hill Stipends</a> &middot; Compliance data from <a href="https://beaconhilltracker.org/">Beacon Hill Compliance Tracker</a> &middot; Full methodology: <a href="https://github.com/arbowl/beacon-hill-compliance-tracker/blob/main/METHODOLOGY.md">METHODOLOGY.md</a></p>
  </div>

  <footer>
    <p>Beacon Hill Compliance Tracker &nbsp;&middot;&nbsp; beaconhilltracker.org</p>
    <p>Beacon Hill Stipends &nbsp;&middot;&nbsp; beaconhillstipends.org</p>
  </footer>

</div>
</body>
</html>
"""


def _fmt_currency(amount: int) -> str:
    return f"${amount:,}"


def _row_html(row: dict, _stripe: bool) -> str:
    stats = row["stats"]
    chamber = row["chamber"]

    # Chair cell
    chair_html = f'<span class="chair-name">{row["chair"]}</span>'

    # Chamber badge
    badge_cls = "senate" if chamber == "Senate" else "house"
    chamber_html = f'<span class="chamber-badge {badge_cls}">{chamber[:1]}</span>'

    # Committee name (strip "Joint Committee on" prefix to save space)
    cname = row["committee_name"]
    for prefix in ("Joint Committee on ", "Joint Committee on the ",
                   "House Committee on ", "Senate Committee on "):
        if cname.startswith(prefix):
            cname = cname[len(prefix):]
            break

    # Chair stipend (per-position)
    if row["chair_stipend"] is not None:
        chair_stipend_html = f'<span class="stipend-val">{_fmt_currency(row["chair_stipend"])}</span>'
    else:
        chair_stipend_html = '<span class="stipend-none">&mdash;</span>'

    # Total pay
    if row["total_pay"] is not None:
        total_pay_html = f'<span class="stipend-val">{_fmt_currency(row["total_pay"])}</span>'
    else:
        total_pay_html = '<span class="stipend-none">&mdash;</span>'

    # Compliance bar
    cr = stats["compliance_rate"]
    if cr is not None and stats["decided_bills"] > 0:
        pct_str = f"{cr:.1f}%"
        compliance_html = (
            f'<div class="compliance-cell">'
            f'<span class="bar-track"><span class="bar-fill" style="width:{cr:.1f}%"></span></span>'
            f'<span class="pct-label">{pct_str}</span>'
            f"</div>"
        )
    else:
        compliance_html = '<span class="no-data">&mdash;</span>'

    # Bills evaluated
    bills_html = (
        str(stats["decided_bills"]) if stats["decided_bills"] > 0
        else '<span class="no-data">&mdash;</span>'
    )

    # Violations (non-compliant)
    nc = stats["non_compliant"]
    violations_html = str(nc) if stats["decided_bills"] > 0 else '<span class="no-data">&mdash;</span>'

    return (
        f"        <tr>\n"
        f"          <td>{chair_html}</td>\n"
        f"          <td>{chamber_html}</td>\n"
        f'          <td class="committee-name">{cname}</td>\n'
        f'          <td class="num">{chair_stipend_html}</td>\n'
        f'          <td class="num">{total_pay_html}</td>\n'
        f'          <td class="num">{compliance_html}</td>\n'
        f'          <td class="num">{bills_html}</td>\n'
        f'          <td class="num">{violations_html}</td>\n'
        f"        </tr>"
    )


def generate_html(rows: list[dict], report_date: str) -> str:
    dt = date.fromisoformat(report_date)
    display = dt.strftime("%B %d, %Y").replace(" 0", " ")

    rows_html = "\n".join(_row_html(r, i % 2 == 1) for i, r in enumerate(rows))
    return _HTML_TEMPLATE.format(
        report_date_display=display,
        rows=rows_html,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", default="tools/stipends/compliance_cost_report.html",
                        help="Output HTML path (default: tools/stipends/compliance_cost_report.html)")
    parser.add_argument("--date", default=None,
                        help="Report date YYYY/MM/DD (default: latest available)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    repo_root = pathlib.Path(__file__).parent.parent.parent
    profiles_dir = repo_root / "tools" / "stipends" / "profiles"
    cache_path = repo_root / "cache" / "cache.json"
    out_dir = repo_root / "out"

    print("Loading stipend profiles…")
    profiles = load_stipend_profiles(profiles_dir)
    name_index = build_name_index(profiles)
    print(f"  {len(profiles)} profiles loaded")

    print("Loading cache…")
    cache = load_cache(cache_path)

    report_date_path = args.date or find_latest_report_date(out_dir)
    report_date = report_date_path.replace("/", "-").replace("\\", "-")
    print(f"Loading compliance reports for {report_date_path}…")
    reports = load_compliance_reports(out_dir, report_date_path)
    print(f"  {len(reports)} committee reports loaded")

    print("Building rows…")
    rows = build_rows(cache, reports, profiles, name_index, report_date)

    if args.verbose:
        unmatched = [r for r in rows if r["member_id"] is None]
        if unmatched:
            print(f"\n  ⚠ {len(unmatched)} unmatched chair(s):")
            for r in unmatched:
                print(f"    [{r['committee_id']} {r['chamber']}] {r['chair']!r}")
        matched = [r for r in rows if r["chair_stipend"] is None and r["member_id"] is not None]
        if matched:
            print(f"\n  ℹ {len(matched)} chairs matched but stipend component not found")

    html = generate_html(rows, report_date)

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"\nReport written to {out_path}")
    print(f"  {len(rows)} rows ({sum(1 for r in rows if r['chair_stipend'] is not None)} with stipend data)")


if __name__ == "__main__":
    main()
