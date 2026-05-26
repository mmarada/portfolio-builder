"""
Apify-based scrapers for LinkedIn Jobs.
Indeed + Jobright use direct Playwright scraping (see career_pages.py).
Uses apify-client v3 — call() blocks until completion, run is a typed Run model.
"""
import logging
from urllib.parse import urlencode
from apify_client import ApifyClient
from config import APIFY_TOKEN, TARGET_ROLES, TARGET_LOCATIONS

log = logging.getLogger(__name__)

_client: ApifyClient | None = None


def _get_client() -> ApifyClient:
    global _client
    if _client is None:
        _client = ApifyClient(APIFY_TOKEN)
    return _client


def _get_items(run) -> list[dict]:
    """Extract dataset items from a completed Run object (apify-client v3)."""
    if run is None:
        return []
    status = str(getattr(run, "status", ""))
    if "SUCCEEDED" not in status:
        log.warning("Run finished with status: %s", status)
    dataset_id = getattr(run, "default_dataset_id", None)
    if not dataset_id:
        return []
    try:
        page = _get_client().dataset(dataset_id).list_items()
        return list(getattr(page, "items", []))
    except Exception as e:
        log.error("Dataset fetch error: %s", e)
        return []


def _normalize(source: str, item: dict) -> dict:
    from scrapers.career_pages import _infer_job_type
    title = (item.get("title") or item.get("jobTitle") or item.get("positionName") or "").strip()
    emp_type = (item.get("employmentType") or item.get("jobType") or "").strip()
    return {
        "source": source,
        "title": title,
        "company": (item.get("company") or item.get("companyName") or "").strip(),
        "location": (item.get("location") or item.get("jobLocation") or "").strip(),
        "url": (item.get("url") or item.get("jobUrl") or item.get("link") or "").strip(),
        "description": (item.get("description") or item.get("jobDescription") or item.get("descriptionHtml") or "").strip(),
        "posted_date": (item.get("postedAt") or item.get("datePosted") or item.get("date") or "").strip(),
        "job_type": _infer_job_type(title, emp_type),
    }


def _build_linkedin_url(query: str, location: str) -> str:
    """Build a public LinkedIn jobs search URL (no login required)."""
    params = {"keywords": query, "location": location, "f_TPR": "r86400", "sortBy": "DD"}
    return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


# ── LinkedIn ──────────────────────────────────────────────────────────────────

def scrape_linkedin(count_per_search: int = 50) -> list[dict]:
    """
    Uses curious_coder/linkedin-jobs-scraper ($1/1000 results, pay-per-use).
    Input: list of LinkedIn jobs search URLs.
    """
    client = _get_client()
    jobs: list[dict] = []

    urls = [
        _build_linkedin_url(role, location)
        for role in TARGET_ROLES[:4]
        for location in TARGET_LOCATIONS[:3]
    ]

    try:
        log.info("LinkedIn: submitting %d search URLs", len(urls))
        run = client.actor("curious_coder/linkedin-jobs-scraper").call(
            run_input={
                "urls": urls,             # plain list of URL strings
                "count": count_per_search,
                "scrapeCompany": False,   # faster, skip company detail page
            }
        )
        for item in _get_items(run):
            j = _normalize("linkedin", item)
            if j["url"]:
                jobs.append(j)
    except Exception as e:
        log.error("LinkedIn scrape error: %s", e)

    log.info("LinkedIn: %d jobs scraped", len(jobs))
    return jobs


# ── LinkedIn people search (for contact finder) ───────────────────────────────

def search_linkedin_people(company: str, title_query: str, max_results: int = 3) -> list[dict]:
    """Find hiring contacts via Apify people search."""
    client = _get_client()
    contacts: list[dict] = []
    try:
        run = client.actor("curious_coder/linkedin-people-search").call(
            run_input={
                "queries": [f"{title_query} at {company}"],
                "maxResults": max_results,
                "proxy": {"useApifyProxy": True},
            }
        )
        for item in _get_items(run):
            name = (item.get("fullName") or item.get("name") or "").strip()
            profile_url = (item.get("profileUrl") or item.get("url") or "").strip()
            person_title = (item.get("headline") or item.get("title") or "").strip()
            if name and profile_url:
                contacts.append({
                    "name": name, "title": person_title,
                    "company": company, "linkedin_url": profile_url, "email": "",
                })
    except Exception as e:
        log.error("LinkedIn people search error for %s: %s", company, e)
    return contacts
