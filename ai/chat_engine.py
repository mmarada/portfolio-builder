"""
Chat engine: answers questions about job descriptions and resume gaps.
Maintains a short conversation history per session.
"""
import logging
from ai.hf_client import generate, summarize
from ai.resume_parser import parse_resume
from config import RESUME_DIR

log = logging.getLogger(__name__)

_resume_text: str = ""
_conversation_history: list[dict] = []  # [{role, content}]


def load_resume():
    global _resume_text
    from ai.resume_parser import find_resume
    path = find_resume(RESUME_DIR)
    if path:
        _resume_text = parse_resume(path)
        log.info("Chat engine loaded resume: %s (%d chars)", path.name, len(_resume_text))
    else:
        log.warning("No resume found in %s — gap analysis disabled", RESUME_DIR)


def reset_conversation():
    global _conversation_history
    _conversation_history = []


def summarize_job(job: dict) -> str:
    """Return a 3-4 sentence summary of the job description."""
    desc = job.get("description", "")
    if not desc:
        return f"{job.get('title')} at {job.get('company')} — no description available."
    return summarize(desc, max_length=200, min_length=60)


def gap_analysis(job: dict) -> str:
    """Identify what's missing from the resume compared to the job requirements."""
    if not _resume_text:
        return "No resume loaded. Upload your resume to resume/ directory to enable gap analysis."

    desc = job.get("description", "")
    if not desc:
        return "No job description available for gap analysis."

    prompt = f"""[INST] You are a career coach. Compare this resume against the job description.
List ONLY the skills, experiences, or qualifications the applicant is MISSING or should STRENGTHEN.
Be specific and actionable. Max 5 bullet points.

Resume (excerpt):
{_resume_text[:1500]}

Job: {job.get('title')} at {job.get('company')}
Job Description:
{desc[:1500]}

Format your response as a bullet list starting with "Missing/Needs strengthening:".
[/INST]"""

    return generate(prompt, max_new_tokens=300, temperature=0.2)


def chat(user_message: str, job: dict | None = None) -> str:
    """
    Multi-turn chat. Answers questions about a job or the user's resume fit.
    `job` provides context if the user is asking about a specific posting.
    """
    _conversation_history.append({"role": "user", "content": user_message})

    # Build context section
    context_parts = []
    if _resume_text:
        context_parts.append(f"Candidate Resume (excerpt):\n{_resume_text[:1000]}")
    if job:
        context_parts.append(
            f"Job: {job.get('title')} at {job.get('company')}\n"
            f"Location: {job.get('location', '')}\n"
            f"Description:\n{job.get('description', '')[:1000]}"
        )
    context = "\n\n".join(context_parts)

    # Build conversation for prompt
    history_text = ""
    for msg in _conversation_history[-6:]:  # last 3 turns
        role = "User" if msg["role"] == "user" else "Assistant"
        history_text += f"{role}: {msg['content']}\n"

    prompt = f"""[INST] You are a helpful career advisor assistant. Use the provided context to answer questions.
Be concise, specific, and actionable.

{context}

Conversation:
{history_text}Assistant:[/INST]"""

    response = generate(prompt, max_new_tokens=400, temperature=0.4)
    _conversation_history.append({"role": "assistant", "content": response})
    return response
