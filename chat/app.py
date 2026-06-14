"""
FastAPI chat + job browser app.
Run: python main.py --chat
"""
import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

import ai.chat_engine as engine
from ai.job_matcher import set_resume
from ai.resume_parser import parse_resume
from db.database import init_db, get_top_jobs, get_distinct_sources, get_job, dismiss_job, mark_applied, get_stats
from config import RESUME_DIR

log = logging.getLogger(__name__)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    engine.load_resume()
    yield


app = FastAPI(title="Job Hunter", lifespan=lifespan)


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    job_id: Optional[int] = None,
    source: Optional[str] = None,
    job_type: Optional[str] = None,
):
    jobs = get_top_jobs(limit=50, source=source or None, job_type=job_type or None)
    selected_job = get_job(job_id) if job_id else (jobs[0] if jobs else None)
    sources = get_distinct_sources()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "jobs": jobs,
            "selected_job": selected_job,
            "sources": sources,
            "active_source": source or "",
            "active_job_type": job_type or "",
        },
    )


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    return get_stats()


@app.get("/api/jobs")
async def api_jobs(
    min_score: float = 0.0,
    limit: int = 50,
    source: Optional[str] = None,
    job_type: Optional[str] = None,
):
    return get_top_jobs(limit=limit, min_score=min_score, source=source or None, job_type=job_type or None)


@app.get("/api/sources")
async def api_sources():
    return get_distinct_sources()


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.post("/api/jobs/{job_id}/summarize")
async def api_summarize(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    try:
        summary = engine.summarize_job(job)
        if not summary:
            summary = "No description available to summarize."
        return {"summary": summary}
    except Exception as e:
        log.error("Summarize error: %s", e)
        raise HTTPException(500, f"AI error: {str(e)}")


@app.post("/api/jobs/{job_id}/gap-analysis")
async def api_gap(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    try:
        analysis = engine.gap_analysis(job)
        if not analysis:
            analysis = "Could not generate gap analysis. Make sure your resume is uploaded."
        return {"analysis": analysis}
    except Exception as e:
        log.error("Gap analysis error: %s", e)
        raise HTTPException(500, f"AI error: {str(e)}")


@app.post("/api/jobs/{job_id}/dismiss")
async def api_dismiss(job_id: int):
    dismiss_job(job_id)
    return {"status": "dismissed"}


@app.post("/api/jobs/{job_id}/applied")
async def api_applied(job_id: int):
    mark_applied(job_id)
    return {"status": "marked_applied"}


@app.post("/api/chat")
async def api_chat(
    message: str = Form(...),
    job_id: Optional[int] = Form(None),
):
    try:
        job = get_job(job_id) if job_id else None
        response = engine.chat(message, job=job)
        if not response:
            response = "I couldn't generate a response. Please try again."
        return {"response": response}
    except Exception as e:
        log.error("Chat error: %s", e)
        return {"response": f"Error: {str(e)}"}


@app.post("/api/chat/reset")
async def api_chat_reset():
    engine.reset_conversation()
    return {"status": "reset"}


@app.post("/api/resume/upload")
async def api_upload_resume(file: UploadFile = File(...)):
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUME_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    text = parse_resume(dest)
    if not text:
        raise HTTPException(400, "Could not extract text from resume file")
    kind = "sde" if any(k in file.filename.lower() for k in ["sde", "engineer", "mba", "foster"]) else "pm"
    set_resume(text, kind=kind)
    engine.load_resume()
    return {"status": "ok", "chars": len(text), "filename": file.filename, "kind": kind}
