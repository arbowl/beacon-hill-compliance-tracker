# io/report_html.py
from pathlib import Path
from datetime import datetime
from typing import List

def write_basic_html(comm_name: str, committee_id: str, rows: List[dict], outpath: Path) -> None:
    """
    rows: list of dicts with fields:
      bill_id, hearing_date, deadline_60, effective_deadline, reported_out,
      summary_present, votes_present, state, reason, bill_url, summary_url, votes_url
    """
    css = """
    body { font-family: system-ui, sans-serif; margin: 24px; }
    h1 { font-size: 20px; margin: 0 0 12px; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
    th { background: #f6f8fa; text-align: left; }
    .ok { color: #137333; font-weight: 600; }
    .bad { color: #b00020; font-weight: 600; }
    .warn { color: #b26a00; font-weight: 600; }
    a { text-decoration: none; }
    """
    def cls(state: str) -> str:
        return "ok" if state=="compliant" else ("bad" if state=="non-compliant" else "warn")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "<!doctype html><meta charset='utf-8'>",
        f"<style>{css}</style>",
        f"<h1>Basic Compliance — {comm_name} [{committee_id}]</h1>",
        f"<p>Generated {now}</p>",
        "<table>",
        "<tr><th>Bill</th><th>Hearing</th><th>D60</th><th>Eff. Deadline</th><th>Reported?</th>"
        "<th>Summary</th><th>Votes</th><th>State</th><th>Reason</th></tr>"
    ]
    for r in rows:
        sum_link = (
            f"<a href='{r['summary_url']}' target='_blank'>Yes</a>"
            if r['summary_present'] and r.get('summary_url')
            else ("Yes" if r['summary_present'] else "—")
        )

        vote_link = (
            f"<a href='{r['votes_url']}' target='_blank'>Yes</a>"
            if r['votes_present'] and r.get('votes_url')
            else ("Yes" if r['votes_present'] else "—")
        )
        rep = "Yes" if r['reported_out'] else "No"
        lines.append(
            f"<tr>"
            f"<td><a href='{r['bill_url']}' target='_blank'>{r['bill_id']}</a></td>"
            f"<td>{r['hearing_date']}</td>"
            f"<td>{r['deadline_60']}</td>"
            f"<td>{r['effective_deadline']}</td>"
            f"<td>{rep}</td>"
            f"<td>{sum_link}</td>"
            f"<td>{vote_link}</td>"
            f"<td class='{cls(r['state'])}'>{r['state']}</td>"
            f"<td>{r['reason']}</td>"
            f"</tr>"
        )
    lines.append("</table>")
    outpath.write_text("\n".join(lines), encoding="utf-8")
