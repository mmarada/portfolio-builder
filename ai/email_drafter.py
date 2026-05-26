"""
Draft networking / outreach emails using HuggingFace generation model.
"""
from ai.hf_client import generate


SENDER_CONTEXT = """
The sender is Mohan Vamshi Marada — a Technical PM with 6 years at Oracle (shipped cloud-native products on OCI/Kubernetes),
Founding Engineer at Ansemble AI (0-to-1 AI music OS, $500k seed), and current Foster MBA student (PM & Finance, UW, 2027).
Strong CS engineering background (Python, Node.js, Java) combined with full PM lifecycle experience.
Particularly strong in AI/LLM product design, enterprise B2B, and developer tools.
"""


def draft_networking_email(
    contact_name: str,
    contact_title: str,
    company: str,
    job_title: str,
    job_url: str,
    resume_summary: str,
) -> tuple[str, str]:
    """
    Returns (subject, body) for a cold outreach email.
    """
    first_name = contact_name.split()[0] if contact_name else "there"

    prompt = f"""[INST] You are a professional writing cold outreach emails for job seekers.
Write a concise, genuine, non-generic cold outreach email to {contact_name} ({contact_title} at {company}).
The sender is applying for the "{job_title}" role ({job_url}).
{SENDER_CONTEXT}
Additional context: {resume_summary[:200]}

Rules:
- Subject line: 10 words or fewer, specific, not salesy
- Body: 3 short paragraphs max (intro, value, ask)
- Warm but professional tone — not sycophantic
- Reference something specific about the company/role, not generic
- End with a specific, low-friction ask (15-min call, quick question)
- Do NOT use "I hope this email finds you well" or any filler opener

Format your response exactly as:
SUBJECT: <subject line>
BODY:
<email body>
[/INST]"""

    response = generate(prompt, max_new_tokens=400, temperature=0.3)

    subject = ""
    body = ""
    if "SUBJECT:" in response and "BODY:" in response:
        parts = response.split("BODY:", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()
    else:
        lines = response.strip().split("\n")
        subject = f"Re: {job_title} at {company}"
        body = "\n".join(lines)

    return subject, body


def draft_application_email(
    hiring_manager: str,
    company: str,
    job_title: str,
    resume_summary: str,
    key_requirements: str,
) -> tuple[str, str]:
    """Draft a direct application / cover email."""
    first_name = hiring_manager.split()[0] if hiring_manager else "Hiring Team"

    prompt = f"""[INST] Write a brief, compelling job application email for a {job_title} role at {company}.
Recipient: {hiring_manager}
Applicant background: {resume_summary[:300]}
Key job requirements: {key_requirements[:200]}

Format:
SUBJECT: <subject>
BODY:
<email body — max 200 words, 3 paragraphs>
[/INST]"""

    response = generate(prompt, max_new_tokens=350, temperature=0.3)

    subject = f"Application: {job_title} at {company}"
    body = response.strip()

    if "SUBJECT:" in response and "BODY:" in response:
        parts = response.split("BODY:", 1)
        subject = parts[0].replace("SUBJECT:", "").strip()
        body = parts[1].strip()

    return subject, body


def summarize_resume_for_email(resume_text: str) -> str:
    """Produce a 2-sentence professional summary from full resume text."""
    prompt = f"""[INST] Summarize this resume in exactly 2 sentences for use in a professional email.
Focus on: years of experience, key roles, top skills, and notable achievements.
Resume:
{resume_text[:2000]}
[/INST]"""
    return generate(prompt, max_new_tokens=100, temperature=0.2)
