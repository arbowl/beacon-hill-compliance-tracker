"""Write the basic compliance HTML report."""

from pathlib import Path
from datetime import datetime
from typing import List

from components.models import CommitteeContact


# pylint: disable=too-many-locals, too-many-arguments
# pylint: disable=too-many-positional-arguments
def write_basic_html(
    comm_name: str,
    committee_id: str,
    committee_url: str,
    contact: CommitteeContact,
    rows: List[dict],
    outpath: Path,
) -> None:
    """
    rows: list of dicts with fields:
      bill_id, hearing_date, deadline_60, effective_deadline,
      extension_order_url, reported_out, summary_present,
      votes_present, state, reason, bill_url,
      summary_url, votes_url, notice_status, notice_gap_days,
      announcement_date, scheduled_hearing_date
    """
    css = """
    body { font-family: system-ui, sans-serif; margin: 24px; }
    h1 { font-size: 20px; margin: 0 0 12px; }
    .contact-info {
        background: #f8f9fa;
        border: 1px solid #e1e4e8;
        border-radius: 6px;
        padding: 16px;
        margin: 16px 0;
        display: flex;
        gap: 32px;
    }
    .contact-section { flex: 1; }
    .contact-section h3 { margin: 0 0 8px; font-size: 16px; color: #24292e; }
    .contact-section p { margin: 4px 0; font-size: 14px; color: #586069; }
    .contact-section strong { color: #24292e; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ddd; padding: 8px; font-size: 14px; }
    th { background: #f6f8fa; text-align: left; }
    .ok { color: #137333; font-weight: 600; }
    .bad { color: #b00020; font-weight: 600; }
    .warn { color: #b26a00; font-weight: 600; }
    a { text-decoration: none; }
    """

    def cls(state: str) -> str:
        return (
            "ok"
            if state == "compliant"
            else ("bad" if state == "non-compliant" else "warn")
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # Generate contact information HTML
    contact_html = ""
    if contact and (contact.senate_phone or contact.house_phone):
        contact_html = '<div class="contact-info">'
        # Senate contact section
        if contact.senate_phone or contact.senate_room:
            contact_html += '<div class="contact-section">'
            contact_html += "<h3>Senate Contact</h3>"
            if contact.senate_address:
                contact_html += (
                    f"<p><strong>Address:</strong> " f"{contact.senate_address}</p>"
                )
            elif contact.senate_room:
                contact_html += (
                    f"<p><strong>Room:</strong> " f"{contact.senate_room}</p>"
                )
            if contact.senate_phone:
                contact_html += (
                    f"<p><strong>Phone:</strong> " f"{contact.senate_phone}</p>"
                )
            # Add Senate Chair and Vice Chair information
            if contact.senate_chair_name:
                chair_info = (
                    f"<p><strong>Chair:</strong> " f"{contact.senate_chair_name}"
                )
                if contact.senate_chair_email:
                    chair_info += f" ({contact.senate_chair_email})"
                chair_info += "</p>"
                contact_html += chair_info
            if contact.senate_vice_chair_name:
                vice_chair_info = (
                    f"<p><strong>Vice Chair:</strong> "
                    f"{contact.senate_vice_chair_name}"
                )
                if contact.senate_vice_chair_email:
                    vice_chair_info += f" ({contact.senate_vice_chair_email})"
                vice_chair_info += "</p>"
                contact_html += vice_chair_info
            contact_html += "</div>"
        # House contact section
        if contact.house_phone or contact.house_room:
            contact_html += '<div class="contact-section">'
            contact_html += "<h3>House Contact</h3>"
            if contact.house_address:
                contact_html += (
                    f"<p><strong>Address:</strong> {contact.house_address}</p>"
                )
            elif contact.house_room:
                contact_html += (
                    f"<p><strong>Room:</strong> " f"{contact.house_room}</p>"
                )
            if contact.house_phone:
                contact_html += (
                    f"<p><strong>Phone:</strong> " f"{contact.house_phone}</p>"
                )
            # Add House Chair and Vice Chair information
            if contact.house_chair_name:
                chair_info = (
                    f"<p><strong>Chair:</strong> " f"{contact.house_chair_name}"
                )
                if contact.house_chair_email:
                    chair_info += f" ({contact.house_chair_email})"
                chair_info += "</p>"
                contact_html += chair_info
            if contact.house_vice_chair_name:
                vice_chair_info = (
                    f"<p><strong>Vice Chair:</strong> "
                    f"{contact.house_vice_chair_name}"
                )
                if contact.house_vice_chair_email:
                    vice_chair_info += f" ({contact.house_vice_chair_email})"
                vice_chair_info += "</p>"
                contact_html += vice_chair_info
            contact_html += "</div>"
        contact_html += "</div>"
    lines = [
        "<!doctype html><meta charset='utf-8'>",
        f"<style>{css}</style>",
        f"<h1>Basic Compliance — <a href='{committee_url}' target='_blank'>"
        f"{comm_name} [{committee_id}]</a></h1>",
        f"<p>Generated {now}</p>",
        contact_html,
        "<table>",
        (
            "<tr>"
            "<th>Bill</th><th>Title</th><th>Hearing</th>"
            "<th>D60</th><th>Eff. Deadline</th><th>Notice Gap</th>"
            "<th>Reported?</th><th>Summary</th><th>Votes</th>"
            "<th>State</th><th>Reason</th>"
            "</tr>"
        ),
    ]
    r: dict[str, str]
    for r in rows:
        sum_link = (
            f"<a href='{r['summary_url']}' target='_blank'>Yes</a>"
            if r["summary_present"] and r.get("summary_url")
            else ("Yes" if r["summary_present"] else "—")
        )
        vote_link = (
            f"<a href='{r['votes_url']}' target='_blank'>Yes</a>"
            if r["votes_present"] and r.get("votes_url")
            else ("Yes" if r["votes_present"] else "—")
        )
        hearing_date = r["hearing_date"] if r["hearing_date"] else "N/A"
        deadline_60 = r["deadline_60"] if r["deadline_60"] else "N/A"
        effective_deadline = (
            r["effective_deadline"] if r["effective_deadline"] else "N/A"
        )
        if r.get("extension_order_url") and r["effective_deadline"]:
            effective_deadline = (
                f"<a href='{r['extension_order_url']}' target='_blank'>"
                f"{r['effective_deadline']}</a>"
            )
        rep = "Yes" if r["reported_out"] else "No"
        notice_gap = "—"
        notice_class = ""
        if r.get("notice_gap_days") is not None:
            gap_days = r["notice_gap_days"]
            notice_status = r.get("notice_status", "missing")
            if notice_status == "in_range":
                notice_gap = f"{gap_days} days"
                notice_class = "ok"
            elif notice_status == "out_of_range":
                notice_gap = f"{gap_days} days"
                notice_class = "bad"
        elif r.get("notice_status", "").lower() == "missing":
            notice_gap = "Missing"
            notice_class = "warn"
        lines.append(
            f"<tr>"
            f"<td><a href='{r['bill_url']}' target='_blank'>{r['bill_id']}</a>"
            f"</td>"
            f"<td>{r.get('bill_title','—')}</td>"
            f"<td>{hearing_date}</td>"
            f"<td>{deadline_60}</td>"
            f"<td>{effective_deadline}</td>"
            f"<td class='{notice_class}'>{notice_gap}</td>"
            f"<td>{rep}</td>"
            f"<td>{sum_link}</td>"
            f"<td>{vote_link}</td>"
            f"<td class='{cls(r['state'])}'>{r['state']}</td>"
            f"<td>{r['reason']}</td>"
            f"</tr>"
        )
    lines.append("</table>")
    outpath.write_text("\n".join(lines), encoding="utf-8")
