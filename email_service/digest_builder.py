"""
Builds the daily morning HTML email digest.
"""
from datetime import date
from ai.hf_client import summarize


def _contact_html(contacts_raw: str) -> str:
    if not contacts_raw:
        return "<p style='color:#888;font-size:13px'>No contacts found yet.</p>"

    html = "<ul style='margin:6px 0;padding-left:20px;font-size:13px'>"
    for entry in contacts_raw.split(";;"):
        parts = entry.split("|")
        if len(parts) < 3:
            continue
        name, title, linkedin, email = parts[0], parts[1], parts[2], (parts[3] if len(parts) > 3 else "")
        linkedin_link = (
            f'<a href="{linkedin}" style="color:#0a66c2">LinkedIn ↗</a>' if linkedin else ""
        )
        email_link = (
            f'<a href="mailto:{email}" style="color:#0a66c2">Email</a>' if email else ""
        )
        links = " · ".join(filter(None, [linkedin_link, email_link]))
        html += f"<li><strong>{name}</strong>, {title} {f'({links})' if links else ''}</li>"
    html += "</ul>"
    return html


def _score_badge(score: float) -> str:
    pct = int(score * 100)
    color = "#16a34a" if pct >= 75 else "#ca8a04" if pct >= 55 else "#dc2626"
    return f'<span style="background:{color};color:#fff;font-size:11px;padding:2px 7px;border-radius:99px;font-weight:600">{pct}% match</span>'


def _job_card(job: dict, index: int, chat_base_url: str) -> str:
    title = job.get("title", "N/A")
    company = job.get("company", "N/A")
    location = job.get("location") or "Not specified"
    url = job.get("url", "#")
    source = job.get("source", "").capitalize()
    score = job.get("match_score", 0)
    contacts_raw = job.get("contacts") or ""
    job_id = job.get("id", "")

    desc = job.get("description", "")
    short_desc = summarize(desc, max_length=80, min_length=20) if len(desc) > 150 else desc[:200]

    chat_url = f"{chat_base_url}?job_id={job_id}" if chat_base_url else "#"

    return f"""
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:18px 20px;margin-bottom:16px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <h3 style="margin:0;font-size:16px;color:#111">{index}. {title}</h3>
    {_score_badge(score)}
    <span style="font-size:12px;color:#6b7280;background:#f3f4f6;padding:2px 8px;border-radius:99px">{source}</span>
  </div>
  <p style="margin:6px 0 4px;font-size:14px;color:#374151"><strong>{company}</strong> · {location}</p>
  <p style="margin:4px 0 10px;font-size:13px;color:#6b7280;line-height:1.5">{short_desc}</p>

  <div style="margin-bottom:10px">
    <p style="margin:0 0 4px;font-size:12px;font-weight:600;text-transform:uppercase;color:#6b7280;letter-spacing:.05em">Hiring Contacts</p>
    {_contact_html(contacts_raw)}
  </div>

  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
    <a href="{url}" style="background:#111;color:#fff;padding:7px 14px;border-radius:6px;font-size:13px;text-decoration:none;font-weight:500">View Job ↗</a>
    <a href="{chat_url}" style="background:#f3f4f6;color:#111;padding:7px 14px;border-radius:6px;font-size:13px;text-decoration:none;font-weight:500">Chat / Gap Analysis</a>
  </div>
</div>"""


def build_digest_html(jobs: list[dict], chat_base_url: str = "") -> str:
    if not chat_base_url:
        from config import CHAT_BASE_URL
        chat_base_url = CHAT_BASE_URL
    today = date.today().strftime("%B %d, %Y")
    total = len(jobs)

    cards = "\n".join(_job_card(j, i + 1, chat_base_url) for i, j in enumerate(jobs))

    draft_rows = ""
    for job in jobs:
        if job.get("draft_subject"):
            draft_rows += f"""
<tr>
  <td style="padding:8px 12px;font-size:13px;border-bottom:1px solid #f3f4f6">{job['company']}</td>
  <td style="padding:8px 12px;font-size:13px;border-bottom:1px solid #f3f4f6">{job.get('draft_subject','')}</td>
  <td style="padding:8px 12px;font-size:13px;border-bottom:1px solid #f3f4f6">
    <a href="https://mail.google.com/mail/u/0/#drafts" style="color:#0a66c2">Open in Gmail</a>
  </td>
</tr>"""

    drafts_section = ""
    if draft_rows:
        drafts_section = f"""
<h2 style="font-size:18px;color:#111;margin-top:36px">Draft Outreach Emails Ready in Gmail</h2>
<p style="color:#6b7280;font-size:13px;margin-bottom:16px">These drafts are saved in your Gmail. Open, review, and send when you're ready.</p>
<table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px">
  <thead>
    <tr style="background:#f9fafb">
      <th style="padding:10px 12px;text-align:left;font-size:12px;color:#6b7280">Company</th>
      <th style="padding:10px 12px;text-align:left;font-size:12px;color:#6b7280">Subject</th>
      <th style="padding:10px 12px;text-align:left;font-size:12px;color:#6b7280">Action</th>
    </tr>
  </thead>
  <tbody>{draft_rows}</tbody>
</table>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb">
<tr><td align="center" style="padding:32px 16px">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">

  <!-- Header -->
  <tr><td style="background:#111;border-radius:10px 10px 0 0;padding:24px 28px">
    <h1 style="margin:0;color:#fff;font-size:22px">Your Job Hunt Digest</h1>
    <p style="margin:6px 0 0;color:#9ca3af;font-size:14px">{today} · {total} matched jobs today</p>
  </td></tr>

  <!-- Body -->
  <tr><td style="background:#f9fafb;padding:24px 0">
    <h2 style="font-size:18px;color:#111;margin-top:0">Top Matches</h2>
    {cards}
    {drafts_section}

    <div style="margin-top:36px;padding:16px 20px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe">
      <p style="margin:0;font-size:13px;color:#1e40af">
        <strong>Chat with your jobs →</strong>
        Visit <a href="{chat_base_url}" style="color:#1d4ed8">{chat_base_url}</a>
        to ask questions about any job description or get a personalized gap analysis.
      </p>
    </div>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f3f4f6;border-radius:0 0 10px 10px;padding:16px 28px;text-align:center">
    <p style="margin:0;font-size:12px;color:#9ca3af">Job Hunter · Auto-generated digest · {today}</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def build_digest_subject(jobs: list[dict]) -> str:
    top = jobs[0] if jobs else {}
    company = top.get("company", "")
    count = len(jobs)
    return f"Job Digest: {count} matches today" + (f" — top: {company}" if company else "")
