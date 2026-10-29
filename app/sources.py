"""Job listing scrapers for technopark.in and infopark.in."""

import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .runtime import log, sleep

BASE = "https://technopark.in"
INFOPARK = "https://infopark.in"
# Infopark job ids overlap Technopark's, so they are stored as this offset + their id.
INFOPARK_ID_OFFSET = 10_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)


def get(url, **kw):
    """GET with simple retry on rate limiting / transient errors."""
    for attempt in range(5):
        r = session.get(url, timeout=30, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            wait = int(r.headers.get("Retry-After", 10 * (attempt + 1)))
            log.info(f"  site returned {r.status_code}, waiting {wait}s")
            sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()


def fetch_job_pages(max_pages=None, search="", job_type=""):
    """Yield one list of job summaries per page of technopark.in/api/paginated-jobs."""
    page = 1
    while True:
        r = get(
            f"{BASE}/api/paginated-jobs",
            params={"page": page, "search": search, "type": job_type},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                     "Referer": f"{BASE}/job-search"},
        )
        data = r.json()
        log.info(f"Technopark page {data['current_page']}/{data['last_page']} "
                 f"({len(data['data'])} jobs)")
        yield [{"id": j["id"], "job_title": j["job_title"], "company": j["company"]["company"],
                "closing_date": j.get("closing_date"), "url": f"{BASE}/job-details/{j['id']}"}
               for j in data["data"]]
        if not data.get("next_page_url") or (max_pages and page >= max_pages):
            break
        page += 1
        sleep(1)


def html_to_text(fragment):
    if not fragment:
        return ""
    text = BeautifulSoup(fragment, "html.parser").get_text("\n")
    text = text.replace("\xa0", " ")
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def fetch_job_details(job_id):
    """Fetch /job-details/<id> and parse the Inertia `data-page` JSON."""
    r = get(f"{BASE}/job-details/{job_id}", headers={"Accept": "text/html"})
    soup = BeautifulSoup(r.text, "html.parser")
    app = soup.find(id="app")
    if not app or not app.get("data-page"):
        raise ValueError(f"no data-page found for job {job_id}")
    page = json.loads(app["data-page"])  # BeautifulSoup already decodes &quot; etc.
    job = page["props"]["jobListing"]
    company = job.get("company") or {}
    return {
        "id": job["id"],
        "job_listing_id": job.get("job_listing_id"),
        "title": job.get("job_title"),
        "company": company.get("company"),
        "company_website": company.get("website"),
        "contact_email": job.get("contact_email"),
        "posted_date": job.get("posted_date"),
        "closing_date": job.get("closing_date"),
        "is_walk_in": bool(job.get("is_walk_in")),
        "walk_in_address": html_to_text(job.get("walk_in_address")),
        "description": html_to_text(job.get("job_description")),
        "skills": html_to_text(job.get("preferred_skills")),
        "url": f"{BASE}/job-details/{job['id']}",
        "source": "technopark",
    }


def parse_date(text, fmt):
    try:
        return datetime.strptime(text.strip(), fmt).date().isoformat()
    except ValueError:
        return None


def fetch_infopark_pages(max_pages=None, search="", job_type=""):
    """Yield one list of job summaries per page of infopark.in/companies-job (newest first)."""
    page = 1
    while True:
        r = get(f"{INFOPARK}/companies-job", params={"page": page, "search": search},
                headers={"Accept": "*/*", "X-Requested-With": "XMLHttpRequest",
                         "Referer": f"{INFOPARK}/companies-job"})
        data = r.json()
        soup = BeautifulSoup(data["all_jobs"], "html.parser")
        jobs = []
        for row in soup.select("tbody tr"):
            cells = row.find_all("td")
            link = row.find("a", href=True)
            m = link and re.search(r"/details/\d+/(\d+)", link["href"])
            if len(cells) < 4 or not m:
                continue
            jobs.append({
                "id": INFOPARK_ID_OFFSET + int(m.group(1)),
                "job_title": cells[1].get_text(strip=True),
                "company": cells[2].get_text(strip=True),
                "posted_date": parse_date(cells[0].get_text(), "%d-%m-%Y"),
                "closing_date": parse_date(cells[3].get_text(), "%d %b %Y"),
                "url": link["href"],
            })
        last = max([page] + [int(n) for n in re.findall(r"page=(\d+)", data.get("pagination", ""))])
        log.info(f"Infopark page {page}/{last} ({len(jobs)} jobs)")
        yield jobs
        if not soup.select_one('a[rel="next"]') or (max_pages and page >= max_pages):
            break
        page += 1
        sleep(1)


def fetch_infopark_details(summary):
    """Fetch an Infopark job page; /company-jobs/details/... redirects to /jobs/<company>/<slug>."""
    r = get(summary["url"], headers={"Accept": "text/html"})
    soup = BeautifulSoup(r.text, "html.parser")
    box = soup.select_one(".comp-job-deatiil .deatil-box")  # (sic) the site's class name
    if not box:
        raise ValueError(f"no job description found at {r.url}")
    company = soup.select_one(".logo-con .con h4")
    mailto = box.select_one('a[href^="mailto:"]')
    text = box.get_text(" ")
    company_text = " ".join(s.get_text() for s in soup.select(".logo-con .con span"))
    if mailto:
        email = mailto["href"][len("mailto:"):].split("?")[0].strip()
    else:  # fall back to an address in the posting, then the company's general one
        found = (re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
                 or re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", company_text))
        email = found.group(0) if found else None
    if box.h4:
        box.h4.extract()  # the title, kept separately
    return {
        "id": summary["id"],
        "job_listing_id": f"infopark-{summary['id'] - INFOPARK_ID_OFFSET}",
        "title": summary["job_title"],
        "company": company.get_text(strip=True) if company else summary["company"],
        "company_website": None,
        "contact_email": email,
        "posted_date": summary.get("posted_date"),
        "closing_date": summary.get("closing_date"),
        "is_walk_in": bool(re.search(r"walk[\s-]?in", text, re.I)),
        "walk_in_address": "",
        "description": html_to_text(box.decode_contents()),
        "skills": "",
        "url": r.url,
        "source": "infopark",
    }


# name -> (yield pages of job summaries, fetch full job from a summary)
SOURCES = {
    "technopark": (fetch_job_pages, lambda s: fetch_job_details(s["id"])),
    "infopark": (fetch_infopark_pages, fetch_infopark_details),
}
