"""The daily run: new jobs -> title screen -> evaluation -> resume -> Gmail draft.

1. Scans each enabled site from the newest job down and stops at the first page
   with no new jobs, so only jobs posted since the last run are fetched. If one
   site fails, the others are still scanned.
2. New jobs are screened by title in one LLM call per page; only the ones that
   pass are fetched and fully evaluated against the resume.
3. Every applicable job that is still open, has a contact email and has not been
   drafted or sent yet gets a resume: an existing tailored resume for the same
   kind of role is reused, otherwise a new one is tailored (or the uploaded base
   PDF is used when there is no LaTeX resume). Then a cover letter is written and
   saved to Gmail Drafts with the resume attached. Nothing is sent.
"""

import psycopg2.extras

from .config import BASE_PDF
from .drafts import draft_job, gmail_login, load_jobs
from .llm import LLMConfigError, check_config
from .matcher import evaluate, row_to_job, save_job, scan
from .resumes import (create_resume, find_similar, have_pdflatex, resume_pdf, set_resume_file,
                      tailored_resumes)
from .runtime import Cancelled, check_cancelled, log, sleep


class SetupError(RuntimeError):
    """Something the user has to configure in Settings first."""


def require(cfg, drafts=False, dry_run=False):
    if not cfg["resume_text"].strip():
        raise SetupError("Add your resume text in Settings -> Profile first")
    try:
        check_config(cfg)
    except LLMConfigError as e:
        raise SetupError(str(e)) from e
    if drafts and not dry_run and not (cfg["gmail_address"] and cfg["gmail_app_password"]):
        raise SetupError("Set your Gmail address and App Password in Settings -> Gmail, "
                         "or use a dry run")


def no_email_jobs(conn, min_score):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, title, company, closing_date, url FROM jobs "
                    "WHERE applicable = true AND coalesce(score, 0) >= %s "
                    "AND coalesce(contact_email, '') = '' AND email_sent IS NOT TRUE "
                    "AND (closing_date IS NULL OR closing_date >= current_date) "
                    "ORDER BY closing_date", (min_score,))
        return cur.fetchall()


def pick_resume(conn, cfg, job, existing, force_new=False):
    """PDF to attach for a job, tailoring a new one when needed. Returns (pdf, how) or (None, why)."""
    if not cfg["resume_tex"].strip() or not have_pdflatex():
        if BASE_PDF.exists():
            log.info("  resume: base PDF (no LaTeX resume to tailor)")
            return BASE_PDF, "base"
        return None, "no LaTeX resume or base PDF in Settings -> Profile"
    pdf = None if force_new else resume_pdf(job)
    if pdf:
        log.info(f"  resume: {pdf.name}")
        return pdf, "existing"
    similar = None
    if cfg["reuse_resumes"] and not force_new:
        try:
            similar = find_similar(job, existing, cfg)
        except Cancelled:
            raise
        except Exception as e:
            log.info(f"  similarity check failed ({e}), tailoring a new resume")
        sleep(float(cfg["llm_delay"]))
    pdf = similar and resume_pdf(existing[similar])
    if pdf:
        log.info(f"  resume: reusing {pdf.name} (same kind of role)")
        set_resume_file(conn, job["id"], pdf)
        return pdf, "reused"
    log.info("  resume: tailoring a new one")
    try:
        _, pdf = create_resume(job, cfg)
    except Cancelled:
        raise
    except Exception as e:
        return None, str(e)
    if not pdf:
        return None, "the tailored resume did not compile"
    existing[job["id"]] = job
    set_resume_file(conn, job["id"], pdf)
    sleep(float(cfg["llm_delay"]))
    return pdf, "created"


def run_pipeline(conn, cfg, scan_jobs=True, drafts=True, full_scan=False, rescore=False,
                 dry_run=False, sources=None):
    """The everyday run. Returns a one-line summary."""
    require(cfg, drafts, dry_run)
    delay = float(cfg["llm_delay"])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), now() FROM jobs")
        known, started = cur.fetchone()

    new = new_ok = 0
    if scan_jobs:
        log.info("== 1. New jobs ==" if known else
                 "== 1. New jobs (first run: scanning all pages, this takes a while) ==")
        for source in sources or cfg["sources"]:
            log.info(f"-- {source} --")
            try:
                scan(conn, cfg, source, rescore=rescore, new_only=not full_scan)
            except (Cancelled, LLMConfigError):
                raise
            except Exception as e:  # one site being down shouldn't stop the run
                log.info(f"  ! {source} scan failed: {e}")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE applicable AND score >= %s) "
                        "FROM jobs WHERE created_at >= %s", (cfg["min_score"], started))
            new, new_ok = cur.fetchone()
        log.info(f"{new} new job(s), {new_ok} applicable\n")

    created = reused = drafted = failed = 0
    if drafts:
        log.info("== 2. Resumes and Gmail drafts ==")
        jobs = load_jobs(conn, cfg["min_score"])
        log.info(f"{len(jobs)} open, applicable job(s) not applied to yet")
        imap = folder = None
        if jobs and not dry_run:
            imap, folder = gmail_login(cfg)
        existing = tailored_resumes(conn)
        try:
            for job in jobs:
                check_cancelled()
                log.info(f"\n[{job['id']}] {job['title']} @ {job['company']} "
                         f"(closes {job['closing_date'] or '-'})")
                pdf, how = pick_resume(conn, cfg, job, existing)
                if not pdf:
                    log.info(f"  failed: {how}")
                    failed += 1
                    continue
                created += how == "created"
                reused += how == "reused"
                log.info(f"  draft -> {job['contact_email']}")
                if draft_job(conn, imap, folder, job, pdf, cfg):
                    drafted += 1
                else:
                    failed += 1
                sleep(delay)
        finally:
            if imap:
                imap.logout()

        manual = no_email_jobs(conn, cfg["min_score"])
        if manual:
            log.info(f"\n{len(manual)} applicable job(s) have no contact email, apply on the site:")
            for j in manual:
                log.info(f"  [{j['id']}] {j['title']} @ {j['company']}  "
                         f"closes {j['closing_date']}  {j['url']}")

    parts = []
    if scan_jobs:
        parts.append(f"{new} new job(s), {new_ok} applicable")
    if drafts:
        what = "letters previewed (dry run)" if dry_run else "drafts saved"
        parts.append(f"{created} resume(s) created, {reused} reused, {drafted} {what}, "
                     f"{failed} failed")
    summary = "; ".join(parts)
    log.info(f"\nDone: {summary}")
    return summary


def load_job(conn, job_id):
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    if not row:
        raise SetupError(f"Job {job_id} not found")
    return row


def job_action(conn, cfg, job_id, action, dry_run=False):
    """Run one step for one job: 'evaluate', 'resume' (tailor a new one) or 'draft'."""
    require(cfg, action == "draft", dry_run)
    row = load_job(conn, job_id)
    log.info(f"[{row['id']}] {row['title']} @ {row['company']}")

    if action == "evaluate":
        if not row["description"]:
            raise SetupError("This job was skipped by its title, so its details were never "
                             "fetched. Run a scan with 'rescore' to evaluate it.")
        job = row_to_job(row)
        job["evaluation"] = evaluate(job, cfg)
        save_job(conn, job)
        e = job["evaluation"]
        summary = f"score {e.get('score')}, {'applicable' if e.get('applicable') else 'not a fit'}"
        log.info(f"  {summary}: {e.get('reason', '')}")
        return summary

    if action == "resume":
        pdf, how = pick_resume(conn, cfg, row, tailored_resumes(conn), force_new=True)
        if not pdf:
            raise RuntimeError(how)
        return f"resume ready: {pdf.name}"

    if action == "draft":
        if not row["contact_email"]:
            raise SetupError("This job has no contact email; apply on the site instead")
        pdf, how = pick_resume(conn, cfg, row, tailored_resumes(conn))
        if not pdf:
            raise RuntimeError(how)
        imap = folder = None
        if not dry_run:
            imap, folder = gmail_login(cfg)
        try:
            ok = draft_job(conn, imap, folder, row, pdf, cfg)
        finally:
            if imap:
                imap.logout()
        if not ok:
            raise RuntimeError("could not create the draft")
        return "letter previewed (dry run)" if dry_run else "draft saved to Gmail"

    raise ValueError(f"unknown action {action!r}")

