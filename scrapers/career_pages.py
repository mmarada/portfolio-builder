"""
Playwright-based scrapers:
  - Indeed (direct, no Apify needed)
  - Jobright.ai (direct)
  - Fortune 500, YC, and VC-backed company career pages
Extracts job listings using structured data (JSON-LD), Lever/Greenhouse embeds,
or plain-text fallback.
"""
import json
import re
import asyncio
import logging
from urllib.parse import urlencode
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from config import TARGET_ROLES, TARGET_LOCATIONS
from data.company_lists import FORTUNE500_CAREERS, VC_STARTUPS_CAREERS, fetch_yc_hiring_companies

log = logging.getLogger(__name__)

ROLE_KEYWORDS = [r.lower() for r in TARGET_ROLES]
LOCATION_KEYWORDS = [l.lower() for l in TARGET_LOCATIONS] + ["remote"]


def _is_relevant(title: str, location: str) -> bool:
    t = title.lower()
    l = location.lower()
    role_match = any(kw in t for kw in ROLE_KEYWORDS)
    loc_match = not LOCATION_KEYWORDS or any(kw in l for kw in LOCATION_KEYWORDS)
    return role_match and loc_match


_INTERN_KEYWORDS = {"intern", "internship", "co-op", "coop", "co op", "apprentice",
                    "trainee", "graduate program", "new grad", "early career"}

def _infer_job_type(title: str, employment_type: str = "") -> str:
    """Return 'intern' or 'full_time' based on title text and optional JSON-LD employmentType."""
    combined = (title + " " + employment_type).lower()
    if any(kw in combined for kw in _INTERN_KEYWORDS):
        return "intern"
    return "full_time"


async def _extract_jsonld_jobs(page: Page, company: str, source_url: str) -> list[dict]:
    """Extract JobPosting structured data embedded in the page."""
    jobs = []
    scripts = await page.locator("script[type='application/ld+json']").all()
    for s in scripts:
        try:
            raw = await s.inner_text()
            data = json.loads(raw)
            postings = [data] if isinstance(data, dict) else data
            for obj in postings:
                if obj.get("@type") == "JobPosting":
                    title = obj.get("title", "")
                    location = (
                        obj.get("jobLocation", {}).get("address", {}).get("addressLocality", "")
                        if isinstance(obj.get("jobLocation"), dict)
                        else ""
                    )
                    if _is_relevant(title, location):
                        emp_type = obj.get("employmentType", "")
                        jobs.append({
                            "source": "career_page",
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": obj.get("url", source_url),
                            "description": obj.get("description", ""),
                            "posted_date": obj.get("datePosted", ""),
                            "job_type": _infer_job_type(title, emp_type),
                        })
        except Exception:
            pass
    return jobs


async def _extract_lever_jobs(page: Page, company: str, source_url: str, default_source: str = "lever") -> list[dict]:
    """Extract from Lever-hosted job boards (jobs.lever.co/company). Always tags source as 'lever'."""
    jobs = []
    try:
        postings = await page.locator("div.posting").all()
        for posting in postings:
            title_el = posting.locator("h5")
            location_el = posting.locator(".location")
            link_el = posting.locator("a.posting-title")

            title = await title_el.inner_text() if await title_el.count() else ""
            location = await location_el.inner_text() if await location_el.count() else ""
            href = await link_el.get_attribute("href") if await link_el.count() else ""

            if title and _is_relevant(title, location):
                jobs.append({
                    "source": "lever",
                    "title": title.strip(),
                    "company": company,
                    "location": location.strip(),
                    "url": href or source_url,
                    "description": "",
                    "posted_date": "",
                    "job_type": _infer_job_type(title),
                })
    except Exception as e:
        log.debug("Lever extract error for %s: %s", company, e)
    return jobs


async def _extract_greenhouse_jobs(page: Page, company: str, source_url: str, default_source: str = "greenhouse") -> list[dict]:
    """Extract from Greenhouse-hosted boards. Always tags source as 'greenhouse'."""
    jobs = []
    try:
        sections = await page.locator(".opening").all()
        for sec in sections:
            link_el = sec.locator("a")
            location_el = sec.locator(".location")
            title = await link_el.inner_text() if await link_el.count() else ""
            location = await location_el.inner_text() if await location_el.count() else ""
            href = await link_el.get_attribute("href") if await link_el.count() else ""
            if href and not href.startswith("http"):
                href = "https://boards.greenhouse.io" + href
            if title and _is_relevant(title, location):
                jobs.append({
                    "source": "greenhouse",
                    "title": title.strip(),
                    "company": company,
                    "location": location.strip(),
                    "url": href or source_url,
                    "description": "",
                    "posted_date": "",
                    "job_type": _infer_job_type(title),
                })
    except Exception as e:
        log.debug("Greenhouse extract error for %s: %s", company, e)
    return jobs


async def _extract_generic_jobs(page: Page, company: str, source_url: str, default_source: str = "career_page") -> list[dict]:
    """
    Fallback: look for <a> tags whose text matches role keywords.
    Uses the caller-supplied default_source so YC/S&P 500 jobs keep their category label.
    """
    jobs = []
    try:
        links = await page.locator("a").all()
        for link in links[:300]:
            text = (await link.inner_text()).strip()
            if len(text) < 5 or len(text) > 120:
                continue
            if _is_relevant(text, ""):
                href = await link.get_attribute("href") or source_url
                if not href.startswith("http"):
                    base = source_url.rstrip("/")
                    href = base + ("" if href.startswith("/") else "/") + href
                jobs.append({
                    "source": default_source,
                    "title": text,
                    "company": company,
                    "location": "",
                    "url": href,
                    "description": "",
                    "posted_date": "",
                    "job_type": _infer_job_type(text),
                })
    except Exception as e:
        log.debug("Generic extract error for %s: %s", company, e)
    return jobs[:20]


async def _scrape_one(page: Page, company: str, career_url: str, default_source: str = "career_page") -> list[dict]:
    try:
        await page.goto(career_url, wait_until="networkidle", timeout=20000)
    except Exception as e:
        log.warning("Could not load %s (%s): %s", company, career_url, e)
        return []

    # Lever and Greenhouse are always labelled by platform, not category.
    # JSON-LD and generic fallbacks use default_source (yc / sp500 / career_page).
    jobs = await _extract_jsonld_jobs(page, company, career_url)
    # Override source on JSON-LD results to the passed-in category
    for j in jobs:
        j["source"] = default_source

    if not jobs:
        jobs = await _extract_lever_jobs(page, company, career_url, default_source)
    if not jobs:
        jobs = await _extract_greenhouse_jobs(page, company, career_url, default_source)
    if not jobs:
        jobs = await _extract_generic_jobs(page, company, career_url, default_source)

    log.info("  %s — %d matching jobs [source=%s]", company, len(jobs), default_source)
    return jobs


async def _scrape_batch(companies: list[dict], concurrency: int = 4, default_source: str = "career_page") -> list[dict]:
    all_jobs: list[dict] = []
    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        async def scrape_with_semaphore(company_dict: dict) -> list[dict]:
            async with semaphore:
                page = await context.new_page()
                try:
                    url = company_dict.get("career_url") or company_dict.get("url", "")
                    # Per-company source override takes priority if supplied
                    src = company_dict.get("source", default_source)
                    return await _scrape_one(page, company_dict["company"], url, src)
                finally:
                    await page.close()

        tasks = [scrape_with_semaphore(c) for c in companies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                all_jobs.extend(r)
            elif isinstance(r, Exception):
                log.error("Scrape task error: %s", r)

        await context.close()
        await browser.close()

    return all_jobs


# ── Indeed (direct Playwright) ────────────────────────────────────────────────

async def _scrape_indeed_async(roles: list[str], locations: list[str], max_per_query: int = 30) -> list[dict]:
    """Scrape Indeed job listings directly without Apify."""
    jobs: list[dict] = []
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        for role in roles[:4]:
            for location in locations[:3]:
                params = {"q": role, "l": location, "sort": "date", "fromage": "1"}
                url = f"https://www.indeed.com/jobs?{urlencode(params)}"
                try:
                    page = await context.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                    # Extract JSON-LD job postings
                    scripts = await page.locator("script[type='application/ld+json']").all()
                    for s in scripts:
                        try:
                            raw = await s.inner_text()
                            data = json.loads(raw)
                            items = data if isinstance(data, list) else [data]
                            for obj in items:
                                if obj.get("@type") == "JobPosting":
                                    title = obj.get("title", "")
                                    loc = obj.get("jobLocation", {})
                                    if isinstance(loc, dict):
                                        loc = loc.get("address", {}).get("addressLocality", "")
                                    if _is_relevant(title, str(loc)):
                                        jobs.append({
                                            "source": "indeed",
                                            "title": title,
                                            "company": obj.get("hiringOrganization", {}).get("name", "") if isinstance(obj.get("hiringOrganization"), dict) else "",
                                            "location": str(loc),
                                            "url": obj.get("url", url),
                                            "description": obj.get("description", ""),
                                            "posted_date": obj.get("datePosted", ""),
                                            "job_type": _infer_job_type(title, obj.get("employmentType", "")),
                                        })
                        except Exception:
                            pass

                    # Fallback: DOM card scraping
                    if not jobs:
                        cards = await page.locator("div[data-testid='slider_item'], .jobsearch-SerpJobCard, .job_seen_beacon").all()
                        for card in cards[:max_per_query]:
                            try:
                                title_el = card.locator("h2 a, .jobtitle a, [data-testid='job-snippet'] h2").first
                                company_el = card.locator("[data-testid='company-name'], .company").first
                                location_el = card.locator("[data-testid='text-location'], .location").first
                                link_el = card.locator("a").first
                                title = await title_el.inner_text() if await title_el.count() else ""
                                company = await company_el.inner_text() if await company_el.count() else ""
                                location_text = await location_el.inner_text() if await location_el.count() else ""
                                href = await link_el.get_attribute("href") if await link_el.count() else ""
                                if href and not href.startswith("http"):
                                    href = "https://www.indeed.com" + href
                                if title and _is_relevant(title, location_text):
                                    jobs.append({
                                        "source": "indeed", "title": title.strip(),
                                        "company": company.strip(), "location": location_text.strip(),
                                        "url": href or url, "description": "", "posted_date": "",
                                        "job_type": _infer_job_type(title),
                                    })
                            except Exception:
                                pass

                    await page.close()
                    log.info("  Indeed: '%s' @ '%s' → %d jobs so far", role, location, len(jobs))
                except Exception as e:
                    log.warning("Indeed error (%s @ %s): %s", role, location, e)

        await context.close()
        await browser.close()
    return jobs


def scrape_indeed() -> list[dict]:
    log.info("Scraping Indeed (direct Playwright)...")
    jobs = asyncio.run(_scrape_indeed_async(TARGET_ROLES, TARGET_LOCATIONS))
    log.info("Indeed: %d jobs scraped", len(jobs))
    return jobs


# ── Jobright (direct Playwright) ──────────────────────────────────────────────

async def _scrape_jobright_async(roles: list[str]) -> list[dict]:
    jobs: list[dict] = []
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)

        for role in roles[:3]:
            slug = role.lower().replace(" ", "-")
            url = f"https://jobright.ai/jobs/{slug}"
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=25000)

                # JSON-LD extraction
                scripts = await page.locator("script[type='application/ld+json']").all()
                for s in scripts:
                    try:
                        raw = await s.inner_text()
                        data = json.loads(raw)
                        items = data if isinstance(data, list) else [data]
                        for obj in items:
                            if obj.get("@type") == "JobPosting":
                                title = obj.get("title", "")
                                loc = obj.get("jobLocation", {})
                                if isinstance(loc, dict):
                                    loc = loc.get("address", {}).get("addressLocality", "")
                                jobs.append({
                                    "source": "jobright",
                                    "title": title,
                                    "company": obj.get("hiringOrganization", {}).get("name", "") if isinstance(obj.get("hiringOrganization"), dict) else "",
                                    "location": str(loc),
                                    "url": obj.get("url", url),
                                    "description": obj.get("description", ""),
                                    "posted_date": obj.get("datePosted", ""),
                                    "job_type": _infer_job_type(title, obj.get("employmentType", "")),
                                })
                    except Exception:
                        pass

                # Fallback: link text scan
                if not jobs:
                    links = await page.locator("a[href*='/jobs/']").all()
                    for link in links[:60]:
                        text = (await link.inner_text()).strip()
                        href = await link.get_attribute("href") or ""
                        if len(text) > 10 and _is_relevant(text, ""):
                            if not href.startswith("http"):
                                href = "https://jobright.ai" + href
                            jobs.append({
                                "source": "jobright", "title": text, "company": "",
                                "location": "", "url": href, "description": "", "posted_date": "",
                                "job_type": _infer_job_type(text),
                            })

                await page.close()
                log.info("  Jobright: '%s' → %d jobs so far", role, len(jobs))
            except Exception as e:
                log.warning("Jobright error (%s): %s", role, e)

        await context.close()
        await browser.close()
    return jobs


def scrape_jobright() -> list[dict]:
    log.info("Scraping Jobright (direct Playwright)...")
    jobs = asyncio.run(_scrape_jobright_async(TARGET_ROLES))
    log.info("Jobright: %d jobs scraped", len(jobs))
    return jobs


# ── Career pages ──────────────────────────────────────────────────────────────

async def _fetch_description_async(url: str) -> str:
    """Visit a single job URL and extract its description text."""
    if not url or url.startswith("javascript"):
        return ""
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)

            # 1. Try JSON-LD description field
            for s in await page.locator("script[type='application/ld+json']").all():
                try:
                    data = json.loads(await s.inner_text())
                    if isinstance(data, dict) and data.get("description"):
                        return re.sub(r"<[^>]+>", " ", data["description"]).strip()[:4000]
                except Exception:
                    pass

            # 2. Platform-specific selectors
            selectors = [
                # Lever
                ".content-wrapper",
                # Greenhouse
                "#content .job-post-description",
                "#content",
                # Indeed
                "#jobDescriptionText",
                # Workday / generic
                "[data-automation-id='jobPostingDescription']",
                # Generic
                ".job-description", "#job-description", "[class*='job-description']",
                "[class*='jobDescription']", "[id*='jobDescription']",
                "article", ".posting-description", ".description",
            ]
            for sel in selectors:
                el = page.locator(sel).first
                if await el.count():
                    text = (await el.inner_text()).strip()
                    if len(text) > 80:
                        await context.close()
                        await browser.close()
                        return text[:4000]

            # 3. Fall back to <main> or largest <div>
            for sel in ["main", "body"]:
                el = page.locator(sel).first
                if await el.count():
                    text = (await el.inner_text()).strip()
                    if len(text) > 200:
                        await context.close()
                        await browser.close()
                        return text[:4000]

            await context.close()
            await browser.close()
    except Exception as e:
        log.debug("fetch_description error %s: %s", url, e)
    return ""


def fetch_job_description(url: str) -> str:
    """Synchronous wrapper around _fetch_description_async."""
    return asyncio.run(_fetch_description_async(url))


async def _backfill_descriptions_async(jobs: list[dict], concurrency: int = 4) -> dict[int, str]:
    """Fetch descriptions for a batch of jobs concurrently. Returns {job_id: description}."""
    results: dict[int, str] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        async def fetch_one(job: dict):
            url = job.get("url", "")
            job_id = job["id"]
            if not url or url.startswith("javascript"):
                return
            async with semaphore:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    desc = ""

                    # JSON-LD first
                    for s in await page.locator("script[type='application/ld+json']").all():
                        try:
                            data = json.loads(await s.inner_text())
                            if isinstance(data, dict) and data.get("description"):
                                desc = re.sub(r"<[^>]+>", " ", data["description"]).strip()[:4000]
                                break
                        except Exception:
                            pass

                    if not desc:
                        for sel in [
                            ".content-wrapper", "#content .job-post-description", "#content",
                            "#jobDescriptionText", "[data-automation-id='jobPostingDescription']",
                            ".job-description", "#job-description", "[class*='job-description']",
                            "[class*='jobDescription']", "article", ".posting-description", "main",
                        ]:
                            el = page.locator(sel).first
                            if await el.count():
                                text = (await el.inner_text()).strip()
                                if len(text) > 80:
                                    desc = text[:4000]
                                    break

                    if desc:
                        results[job_id] = desc
                        log.debug("  backfilled description for job %d (%d chars)", job_id, len(desc))
                except Exception as e:
                    log.debug("  backfill error job %d: %s", job_id, e)
                finally:
                    await page.close()

        await asyncio.gather(*[fetch_one(j) for j in jobs])
        await context.close()
        await browser.close()

    return results


def backfill_descriptions(jobs: list[dict]) -> dict[int, str]:
    """Fetch and return descriptions for jobs that have empty description field."""
    missing = [j for j in jobs if not j.get("description")]
    if not missing:
        return {}
    log.info("Backfilling descriptions for %d jobs...", len(missing))
    results = asyncio.run(_backfill_descriptions_async(missing))
    log.info("Backfill complete: got descriptions for %d / %d jobs", len(results), len(missing))
    return results


def scrape_career_pages() -> list[dict]:
    """Scrape Fortune 500 + VC startups career pages. Source = lever/greenhouse/career_page."""
    all_companies = FORTUNE500_CAREERS + VC_STARTUPS_CAREERS
    log.info("Scraping %d career pages...", len(all_companies))
    return asyncio.run(_scrape_batch(all_companies, default_source="career_page"))


def scrape_yc_career_pages(batch: str = "") -> list[dict]:
    """Fetch hiring YC companies then scrape their career pages. Source = yc."""
    yc_companies = fetch_yc_hiring_companies(batch)
    log.info("Scraping %d YC company pages...", len(yc_companies))

    # First pass: find career page links from YC profile pages
    async def resolve_career_urls(companies: list[dict]) -> list[dict]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            resolved = []
            for company in companies[:100]:
                if company.get("career_url"):
                    resolved.append(company)
                    continue
                page = await context.new_page()
                try:
                    await page.goto(company["url"], wait_until="domcontentloaded", timeout=15000)
                    website_link = page.locator("a:has-text('Website')").first
                    if await website_link.count():
                        site = await website_link.get_attribute("href") or ""
                        if site:
                            company["career_url"] = site.rstrip("/") + "/careers"
                    resolved.append(company)
                except Exception:
                    resolved.append(company)
                finally:
                    await page.close()
            await context.close()
            await browser.close()
        return resolved

    resolved = asyncio.run(resolve_career_urls(yc_companies))
    valid = [c for c in resolved if c.get("career_url") or c.get("url")]
    return asyncio.run(_scrape_batch(valid, default_source="yc"))


def scrape_sp500_career_pages() -> list[dict]:
    """Scrape S&P 500 company career pages. Source = sp500."""
    from data.company_lists import SP500_CAREERS
    log.info("Scraping %d S&P 500 career pages...", len(SP500_CAREERS))
    return asyncio.run(_scrape_batch(SP500_CAREERS, default_source="sp500"))
