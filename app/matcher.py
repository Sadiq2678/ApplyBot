"""Scan job listings, screen titles and score each job against the resume with the LLM.

Results are stored in the PostgreSQL table `jobs`.
"""

import time

import psycopg2.extras
from psycopg2 import sql

from .config import save_settings
from .llm import LLMConfigError, ask_llm
from .runtime import Cancelled, log, sleep
from .sources import SOURCES

PROMPT = """You are an experienced technical recruiter. Decide whether the candidate
should apply for this job, based only on the resume and job posting below.

Consider: required years of experience vs. candidate's experience, core technical
skills, domain, education, and role type (e.g. a developer should not be marked fit
for a sales role unless the resume supports it). Be honest and strict: "applicable"
means the candidate meets most must-have requirements or is a reasonable stretch.
{internships}{preferences}
Respond with ONLY a JSON object in this exact shape:
{{
  "applicable": true or false,
  "score": integer 0-100 (how well the candidate fits),
  "experience_required": "e.g. 3-6 years, or unknown",
  "matching_skills": ["..."],
  "missing_skills": ["..."],
  "reason": "2-3 sentence explanation"
}}

=== RESUME ===
{resume}

=== JOB ===
Title: {title}
Company: {company}
Description:
{description}

Skills / Requirements:
{skills}
"""

INTERNSHIPS = """
The candidate is happy to take internships. For internship, intern, trainee and
fresher roles, be lenient: tools the posting says will be learned, or asks only
"basic knowledge" of, are nice-to-have, not must-haves. Mark such a role applicable
(score 60 or more) when the candidate's education and general software skills fit
the role family, even if a few specific tools are missing from the resume.
"""

PREFERENCES = """
The candidate's own preferences (target role families, things to favour or avoid).
Treat target role families as the candidate's own field, and count related resume
experience toward them:
{text}
"""

PROFILE_PROMPT = """Summarize this resume in 2-3 sentences for a recruiter who will
screen job titles for this candidate: their field, core skills, years of experience,
and the kinds of roles they are targeting. Plain text only, no preamble.

{resume}
"""

TITLE_PROMPT = """You are screening job titles for a candidate before reading the full
postings. Candidate profile:
{profile}
{preferences}
For each job below answer true if the role could plausibly fit this candidate (same
field or role family, even as a stretch), or false if it is clearly a different
profession (e.g. sales, marketing, design, HR for a software engineer).{internships}
Roles in the candidate's target role families are in their field: answer true.
If unsure, answer true.

Respond with ONLY a JSON object mapping each job id to true or false,
e.g. {{"123": true, "456": false}}.

Jobs:
{jobs}
"""


def preference_text(cfg):
    text = cfg["preferences"].strip()
    return PREFERENCES.format(text=text) if text else ""


def load_profile(conn, cfg):
    """Short candidate summary used for title screening; generated once, editable in Settings."""
    if cfg["profile"].strip():
        return cfg["profile"].strip()
    log.info("Generating a short profile summary for title screening...")
    profile = ask_llm(PROFILE_PROMPT.format(resume=cfg["resume_text"]), cfg, json_mode=False)
    save_settings(conn, {"profile": profile})
    cfg["profile"] = profile
    log.info(f"  {profile}\n")
    return profile


def screen_titles(jobs, profile, cfg):
    """One cheap call per page: {job_id: True/False} based on title only."""
    lines = "\n".join(f"{j['id']}: {j['job_title']}" for j in jobs)
    internships = (" Internships and trainee roles in the candidate's field also fit."
                   if cfg["open_to_internships"] else "")
    answer = ask_llm(TITLE_PROMPT.format(profile=profile, preferences=preference_text(cfg),
                                         internships=internships, jobs=lines), cfg)
    return {j["id"]: bool(answer.get(str(j["id"]), True)) for j in jobs}


def evaluate(job, cfg):
    prompt = PROMPT.format(
        internships=INTERNSHIPS if cfg["open_to_internships"] else "",
        preferences=preference_text(cfg),
        resume=cfg["resume_text"],
        title=job["title"],
        company=job["company"],
        description=job["description"][:6000],
        skills=job["skills"][:4000],
    )
    return ask_llm(prompt, cfg)


# -------------------------------------------------------------- database ----

JOB_COLUMNS = ["id", "job_listing_id", "title", "company", "company_website", "contact_email",
               "posted_date", "closing_date", "is_walk_in", "walk_in_address", "description",
               "skills", "url", "title_screen_passed", "applicable", "score",
               "experience_required", "matching_skills", "missing_skills", "reason", "source"]
EVAL_COLUMNS = ["applicable", "score", "experience_required", "matching_skills",
                "missing_skills", "reason"]


def row_to_job(row):
    job = {k: row[k] for k in JOB_COLUMNS if k not in EVAL_COLUMNS and k != "title_screen_passed"}
    for k in ("posted_date", "closing_date"):
        if job[k]:
            job[k] = job[k].isoformat()
    if row["title_screen_passed"] is False:
        job["prefilter"] = False
    if row["applicable"] is not None:
        job["evaluation"] = {k: row[k] for k in EVAL_COLUMNS}
    if row["description"] is None:
        del job["description"]  # not scraped yet
    return job


def load_results(conn):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM jobs")
        return {r["id"]: row_to_job(r) for r in cur.fetchall()}


def save_job(conn, job):
    """Insert or update one job; never touches email_sent."""
    e = job.get("evaluation") or {}
    passed = False if job.get("prefilter") is False else (True if e else None)
    values = {k: job.get(k) for k in JOB_COLUMNS}
    values.update({k: e.get(k) for k in EVAL_COLUMNS})
    values["title_screen_passed"] = passed
    for k in ("posted_date", "closing_date"):
        values[k] = values[k] or None
    updates = sql.SQL(", ").join(
        sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(k)) for k in JOB_COLUMNS if k != "id")
    query = sql.SQL(
        "INSERT INTO jobs ({cols}) VALUES ({vals}) "
        "ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now()"
    ).format(
        cols=sql.SQL(", ").join(map(sql.Identifier, JOB_COLUMNS)),
        vals=sql.SQL(", ").join(sql.Placeholder(k) for k in JOB_COLUMNS),
        updates=updates,
    )
    with conn.cursor() as cur:
        cur.execute(query, values)


def scan(conn, cfg, source, pages=None, search="", rescore=False, prefilter=True,
         new_only=False):
    """Fetch one site's listings, title-screen and evaluate jobs not seen before.

    Both sites list the newest jobs first, so with new_only the scan stops at the
    first page on which every job is already in the database. Returns
    (jobs evaluated, of which applicable).
    """
    fetch_pages, fetch_details = SOURCES[source]
    results = load_results(conn)
    today = time.strftime("%Y-%m-%d")
    delay = float(cfg["llm_delay"])
    profile = load_profile(conn, cfg) if prefilter else None
    evaluated = applicable = 0

    for page in fetch_pages(pages, search):
        closed = lambda s: s.get("closing_date") and s["closing_date"] < today
        if new_only and not rescore and all(s["id"] in results or closed(s) for s in page):
            log.info("  no new jobs on this page, stopping (older pages were already scanned)")
            break
        todo = []
        for summary in page:
            prev = results.get(summary["id"], {})
            if closed(summary):
                continue
            if not rescore and (prev.get("evaluation") or prev.get("prefilter") is False):
                continue
            todo.append(summary)

        if todo and profile:
            try:
                verdicts = screen_titles(todo, profile, cfg)
            except Exception as e:
                log.info(f"  ! title screening failed ({e}); evaluating all jobs on this page")
                verdicts = {}
            sleep(delay)
            for summary in todo:
                if verdicts.get(summary["id"], True):
                    continue
                jid = summary["id"]
                log.info(f"- [{jid}] {summary['job_title']}  -> skipped by title")
                results[jid] = {
                    "id": jid,
                    "title": summary["job_title"],
                    "company": summary["company"],
                    "closing_date": summary.get("closing_date"),
                    "url": summary["url"],
                    "source": source,
                    "prefilter": False,
                }
                save_job(conn, results[jid])
            todo = [s for s in todo if verdicts.get(s["id"], True)]

        for summary in todo:
            jid = summary["id"]
            log.info(f"- [{jid}] {summary['job_title']} @ {summary['company']}")
            try:
                job = results.get(jid)
                if not job or "description" not in job:
                    job = fetch_details(summary)
                    sleep(1)
                job.pop("prefilter", None)
                job["evaluation"] = evaluate(job, cfg)
            except (Cancelled, LLMConfigError):
                raise
            except Exception as e:  # keep going on a single bad job
                log.info(f"  ! failed: {e}")
                continue

            results[jid] = job
            save_job(conn, job)
            e = job["evaluation"]
            evaluated += 1
            match = e.get("applicable") and (e.get("score") or 0) >= cfg["min_score"]
            applicable += bool(match)
            log.info(f"  {'MATCH' if match else 'skip'}  score={e.get('score')}  "
                     f"{(e.get('reason') or '')[:140]}")
            sleep(delay)
    return evaluated, applicable
