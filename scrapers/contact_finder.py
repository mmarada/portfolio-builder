"""
Find relevant hiring contacts at a company.
Uses Apify LinkedIn people search + optional Hunter.io for work emails.
"""
import logging
import requests
from config import APIFY_TOKEN, HUNTER_API_KEY

log = logging.getLogger(__name__)


def find_contacts_for_job(company: str, job_title: str, max_contacts: int = 3) -> list[dict]:
    """
    Returns list of {name, title, company, linkedin_url, email}.
    """
    if not APIFY_TOKEN:
        log.warning("No Apify token — skipping contact search")
        return []

    from scrapers.apify_scraper import search_linkedin_people

    if any(kw in job_title.lower() for kw in ["pm", "product", "tpm", "program"]):
        search_titles = ["VP Product", "Director of Product", "Technical Recruiter"]
    else:
        search_titles = ["Engineering Manager", "VP Engineering", "Technical Recruiter"]

    contacts: list[dict] = []
    for title in search_titles[:2]:
        if len(contacts) >= max_contacts:
            break
        found = search_linkedin_people(company, title, max_results=max_contacts)
        contacts.extend(found)

    if HUNTER_API_KEY:
        contacts = _enrich_emails(contacts, company)

    log.info("Found %d contacts at %s", len(contacts), company)
    return contacts[:max_contacts]


def _enrich_emails(contacts: list[dict], company: str) -> list[dict]:
    try:
        domain = _guess_domain(company)
        if not domain:
            return contacts
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 20},
            timeout=10,
        )
        email_map: dict[str, str] = {}
        for entry in resp.json().get("data", {}).get("emails", []):
            first = (entry.get("first_name") or "").lower()
            last = (entry.get("last_name") or "").lower()
            if first and last:
                email_map[f"{first} {last}"] = entry.get("value", "")
        for contact in contacts:
            key = contact["name"].lower()
            if key in email_map:
                contact["email"] = email_map[key]
    except Exception as e:
        log.error("Hunter.io error: %s", e)
    return contacts


def _guess_domain(company: str) -> str:
    cleaned = (
        company.lower()
        .replace(",", "").replace(".", "").replace(" inc", "")
        .replace(" llc", "").replace(" corp", "").replace("the ", "")
        .strip().replace(" ", "")
    )
    return f"{cleaned}.com" if cleaned else ""
