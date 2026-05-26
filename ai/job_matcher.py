"""
Score jobs against the user's resume using semantic similarity.
Loads both PM and SDE resumes; uses whichever scores higher per job.
"""
import logging
from pathlib import Path
from ai.hf_client import get_embeddings, cosine_similarity
from config import TARGET_ROLES, TARGET_LOCATIONS

log = logging.getLogger(__name__)

# PM-track keywords in job title → use PM resume
PM_TITLE_KEYWORDS = ["product manager", "pm ", " pm", "tpm", "technical program", "product lead",
                     "head of product", "vp product", "director of product", "founding pm"]

# SDE-track keywords → use SDE resume
SDE_TITLE_KEYWORDS = ["engineer", "developer", "architect", "sde", "swe", "software", "backend",
                      "frontend", "fullstack", "full stack", "ml ", "machine learning", "ai engineer"]

_resume_embeddings: dict[str, list[float]] = {}   # {"pm": [...], "sde": [...]}
_resume_texts: dict[str, str] = {}


def set_resume(text: str, kind: str = "pm"):
    """Load a resume embedding. kind = 'pm' or 'sde'."""
    _resume_texts[kind] = text
    embeddings = get_embeddings([text[:512]])
    _resume_embeddings[kind] = embeddings[0] if embeddings else []
    log.info("Resume embedding computed: kind=%s (%d dims)", kind, len(_resume_embeddings[kind]))


def _pick_resume_kind(job_title: str) -> str:
    """Return 'pm' or 'sde' based on job title."""
    t = job_title.lower()
    if any(kw in t for kw in PM_TITLE_KEYWORDS):
        return "pm"
    if any(kw in t for kw in SDE_TITLE_KEYWORDS):
        return "sde"
    # Default to whichever we have; prefer PM
    return "pm" if "pm" in _resume_embeddings else "sde"


def score_job(job: dict) -> float:
    kind = _pick_resume_kind(job.get("title", ""))
    emb = _resume_embeddings.get(kind) or _resume_embeddings.get("pm") or _resume_embeddings.get("sde")
    if not emb:
        return _keyword_score(job)

    job_text = f"{job.get('title','')} {job.get('company','')} {job.get('description','')}".strip()[:512]
    job_embs = get_embeddings([job_text])
    if not job_embs or not job_embs[0]:
        return _keyword_score(job)

    semantic = cosine_similarity(emb, job_embs[0])
    keyword = _keyword_score(job)
    return round(0.7 * semantic + 0.3 * keyword, 4)


def score_jobs_batch(jobs: list[dict]) -> list[dict]:
    """Score a batch of jobs, routing each to the right resume."""
    if not jobs:
        return jobs

    if not _resume_embeddings:
        for job in jobs:
            job["match_score"] = _keyword_score(job)
        return jobs

    # Group by resume kind for batch embedding efficiency
    pm_jobs = [j for j in jobs if _pick_resume_kind(j.get("title","")) == "pm"]
    sde_jobs = [j for j in jobs if _pick_resume_kind(j.get("title","")) == "sde"]

    for group, kind in [(pm_jobs, "pm"), (sde_jobs, "sde")]:
        if not group:
            continue
        resume_emb = _resume_embeddings.get(kind) or _resume_embeddings.get("pm") or _resume_embeddings.get("sde")
        if not resume_emb:
            for job in group:
                job["match_score"] = _keyword_score(job)
            continue
        texts = [f"{j.get('title','')} {j.get('company','')} {j.get('description','')}".strip()[:512] for j in group]
        embeddings = get_embeddings(texts)
        for job, emb in zip(group, embeddings):
            semantic = cosine_similarity(resume_emb, emb) if emb else 0.0
            job["match_score"] = round(0.7 * semantic + 0.3 * _keyword_score(job), 4)

    return jobs


def _keyword_score(job: dict) -> float:
    title = (job.get("title") or "").lower()
    loc = (job.get("location") or "").lower()
    role_hit = sum(1 for r in TARGET_ROLES if r.lower() in title)
    loc_hit = any(l.lower() in loc or "remote" in loc for l in TARGET_LOCATIONS)
    return round(min(role_hit * 0.35, 0.7) + (0.3 if loc_hit else 0.0), 4)
