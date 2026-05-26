"""
Main orchestrator — runs the full scrape → match → contact-find → email pipeline.
Usage:
  python main.py            # full run
  python main.py --scrape   # scrape only (no email)
  python main.py --email    # send digest from today's already-scraped jobs
  python main.py --chat     # start chat server only
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("main")


def run_scrape() -> list[dict]:
    """Scrape all sources and persist to DB. Returns list of new job dicts."""
    from db.database import init_db, upsert_job
    from scrapers.apify_scraper import scrape_linkedin
    from scrapers.career_pages import scrape_indeed, scrape_jobright, scrape_career_pages, scrape_yc_career_pages, scrape_sp500_career_pages
    from ai.job_matcher import score_jobs_batch
    from db.database import update_match_score

    init_db()

    log.info("=== Starting scrape ===")
    all_jobs: list[dict] = []

    # ── LinkedIn via Apify (pay-per-use, $1/1000 results) ─────────────────────
    if _has_apify():
        log.info("Scraping LinkedIn via Apify...")
        all_jobs += scrape_linkedin()
    else:
        log.warning("No APIFY_API_TOKEN — skipping LinkedIn")

    # ── Indeed + Jobright: direct Playwright (no Apify needed) ────────────────
    log.info("Scraping Indeed (direct)...")
    all_jobs += scrape_indeed()

    log.info("Scraping Jobright (direct)...")
    all_jobs += scrape_jobright()

    # ── Playwright: company career pages ──────────────────────────────────────
    log.info("Scraping Fortune 500 + VC startup career pages...")
    all_jobs += scrape_career_pages()

    log.info("Scraping YC hiring companies...")
    all_jobs += scrape_yc_career_pages()

    log.info("Scraping S&P 500 career pages...")
    all_jobs += scrape_sp500_career_pages()

    log.info("Total raw jobs scraped: %d", len(all_jobs))

    # ── Deduplicate + score ────────────────────────────────────────────────────
    _load_resume_for_matching()
    scored = score_jobs_batch(all_jobs)

    new_jobs: list[dict] = []
    for job in scored:
        job_id = upsert_job(
            source=job.get("source", ""),
            title=job.get("title", ""),
            company=job.get("company", ""),
            location=job.get("location", ""),
            url=job.get("url", ""),
            description=job.get("description", ""),
            posted_date=job.get("posted_date", ""),
            job_type=job.get("job_type", "full_time"),
        )
        if job_id:  # None = duplicate
            update_match_score(job_id, job.get("match_score", 0))
            job["id"] = job_id
            new_jobs.append(job)
        # Note: job_type is set at upsert time; no update needed here

    log.info("New unique jobs persisted: %d", len(new_jobs))

    # ── Backfill descriptions for jobs that don't have them ───────────────────
    _backfill_missing_descriptions(new_jobs)

    # ── Sync to PostgreSQL for Vercel (if configured) ─────────────────────────
    _sync_to_postgres_if_configured()

    return new_jobs


def _backfill_missing_descriptions(jobs: list[dict]):
    """Fetch and store job descriptions for any jobs with empty description field."""
    from scrapers.career_pages import backfill_descriptions
    from db.database import get_conn

    # Also backfill older DB jobs in this run (union of new + existing empties)
    try:
        from db.database import get_top_jobs
        all_db_jobs = get_top_jobs(limit=200)
        to_backfill = [j for j in all_db_jobs if not j.get("description")]
        if not to_backfill:
            log.info("All jobs already have descriptions — skipping backfill")
            return

        descriptions = backfill_descriptions(to_backfill)
        if not descriptions:
            return

        with get_conn() as conn:
            for job_id, desc in descriptions.items():
                conn.execute("UPDATE jobs SET description=? WHERE id=?", (desc, job_id))
        log.info("Saved %d descriptions to DB", len(descriptions))
    except Exception as e:
        log.error("Description backfill error: %s", e)


def run_contact_find(jobs: list[dict]):
    """Find hiring contacts for top jobs and persist to DB."""
    from config import MIN_MATCH_SCORE
    from scrapers.contact_finder import find_contacts_for_job
    from db.database import insert_contact

    top_jobs = [j for j in jobs if j.get("match_score", 0) >= MIN_MATCH_SCORE][:15]
    log.info("Finding contacts for %d top jobs...", len(top_jobs))

    for job in top_jobs:
        contacts = find_contacts_for_job(
            company=job.get("company", ""),
            job_title=job.get("title", ""),
        )
        for c in contacts:
            contact_id = insert_contact(
                job_id=job["id"],
                name=c["name"],
                title=c["title"],
                company=c["company"],
                linkedin_url=c["linkedin_url"],
                email=c.get("email", ""),
            )
            c["id"] = contact_id

        job["_contacts"] = contacts


def run_draft_emails(jobs: list[dict]):
    """Draft outreach emails for top jobs and save as Gmail drafts."""
    from config import MIN_MATCH_SCORE, DIGEST_RECIPIENT
    from ai.email_drafter import draft_networking_email, summarize_resume_for_email
    from ai.resume_parser import parse_resume, find_resume
    from email_service.gmail_sender import create_draft
    from db.database import insert_draft

    resume_path = find_resume(Path("resume"))
    resume_text = parse_resume(resume_path) if resume_path else ""
    resume_summary = summarize_resume_for_email(resume_text) if resume_text else ""

    top_jobs = [j for j in jobs if j.get("match_score", 0) >= MIN_MATCH_SCORE][:10]

    for job in top_jobs:
        contacts = job.get("_contacts", [])
        if not contacts:
            continue

        contact = contacts[0]
        subject, body = draft_networking_email(
            contact_name=contact["name"],
            contact_title=contact["title"],
            company=job.get("company", ""),
            job_title=job.get("title", ""),
            job_url=job.get("url", ""),
            resume_summary=resume_summary,
        )

        to = contact.get("email") or DIGEST_RECIPIENT
        gmail_draft_id = create_draft(to=to, subject=subject, html_body=f"<pre style='font-family:inherit'>{body}</pre>")

        insert_draft(
            job_id=job["id"],
            contact_id=contact.get("id"),
            subject=subject,
            body=body,
            gmail_draft_id=gmail_draft_id,
        )

        job["draft_subject"] = subject
        log.info("Draft created for %s @ %s", job.get("title"), job.get("company"))


def run_send_digest():
    """Fetch unsent scored jobs and send the morning digest. Marks jobs as sent after."""
    from config import MIN_MATCH_SCORE, DIGEST_RECIPIENT
    from db.database import get_top_jobs, mark_digest_sent
    from email_service.digest_builder import build_digest_html, build_digest_subject
    from email_service.gmail_sender import send_email
    from email_service.smtp_sender import send_email as smtp_send

    if not DIGEST_RECIPIENT:
        log.error("DIGEST_RECIPIENT not set in .env — cannot send digest")
        return

    # Only jobs never included in a previous digest
    jobs = get_top_jobs(limit=20, min_score=MIN_MATCH_SCORE, unsent_only=True)
    if not jobs:
        log.warning("No new jobs to send (all already sent or none meet min_score=%.2f)", MIN_MATCH_SCORE)
        return

    html = build_digest_html(jobs)
    subject = build_digest_subject(jobs)

    sent = send_email(to=DIGEST_RECIPIENT, subject=subject, html_body=html)
    if not sent:
        log.warning("Gmail send failed; trying SMTP fallback...")
        smtp_send(to=DIGEST_RECIPIENT, subject=subject, html_body=html)

    # Mark these jobs so they won't be re-sent tomorrow
    mark_digest_sent([j["id"] for j in jobs])
    log.info("Digest sent: %d new jobs (marked as sent)", len(jobs))


def _sync_to_postgres_if_configured():
    """Push all local SQLite jobs to PostgreSQL for the Vercel deployment."""
    from config import POSTGRES_SYNC_URL
    if not POSTGRES_SYNC_URL:
        return
    try:
        from db.database import sync_sqlite_to_postgres
        synced = sync_sqlite_to_postgres(POSTGRES_SYNC_URL)
        log.info("Synced %d jobs to PostgreSQL", synced)
    except Exception as e:
        log.error("PostgreSQL sync failed (non-fatal): %s", e)


def _has_apify() -> bool:
    from config import APIFY_TOKEN
    return bool(APIFY_TOKEN)


def _load_resume_for_matching():
    from ai.resume_parser import parse_resume
    from ai.job_matcher import set_resume
    from config import RESUME_DIR

    resume_dir = RESUME_DIR
    loaded = 0
    for path in resume_dir.glob("*.pdf"):
        name_lower = path.stem.lower()
        kind = "sde" if any(k in name_lower for k in ["sde", "engineer", "mba", "foster"]) else "pm"
        text = parse_resume(path)
        if text:
            set_resume(text, kind=kind)
            log.info("Resume loaded: %s → kind=%s", path.name, kind)
            loaded += 1
    if loaded == 0:
        log.warning("No resumes in resume/ — using keyword-only scoring")


def main():
    parser = argparse.ArgumentParser(description="Job Hunter pipeline")
    parser.add_argument("--scrape", action="store_true", help="Scrape only")
    parser.add_argument("--email",  action="store_true", help="Send digest from existing jobs")
    parser.add_argument("--chat",   action="store_true", help="Start chat server")
    args = parser.parse_args()

    if args.chat:
        import uvicorn
        uvicorn.run("chat.app:app", host="0.0.0.0", port=8080, reload=False)
        return

    if args.email:
        run_send_digest()
        return

    # Full pipeline
    new_jobs = run_scrape()
    run_contact_find(new_jobs)
    run_draft_emails(new_jobs)
    run_send_digest()
    log.info("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
