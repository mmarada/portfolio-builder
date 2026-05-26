"""
Runs the full job-hunter pipeline on a daily schedule.
Usage: python scheduler.py
       DIGEST_SEND_TIME=08:30 python scheduler.py
"""
import logging
import sys
import time
import schedule

from config import DIGEST_SEND_TIME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scheduler")


def daily_job():
    log.info("=== Scheduled run triggered ===")
    try:
        from main import run_scrape, run_contact_find, run_draft_emails, run_send_digest
        new_jobs = run_scrape()
        run_contact_find(new_jobs)
        run_draft_emails(new_jobs)
        run_send_digest()
        log.info("=== Scheduled run complete ===")
    except Exception as e:
        log.exception("Scheduled run failed: %s", e)


def main():
    log.info("Scheduler started — daily run at %s", DIGEST_SEND_TIME)
    schedule.every().day.at(DIGEST_SEND_TIME).do(daily_job)

    # Also run immediately on startup so you don't wait until tomorrow
    log.info("Running initial job now...")
    daily_job()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
