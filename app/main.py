"""Web API and UI server.  Run with:  uvicorn app.main:app"""

import base64
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing import Literal

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .config import (BASE_PDF, DATA_DIR, RESUMES_DIR, ROOT, SECRETS, SETTINGS, import_legacy_files,
                     load_settings, save_settings)
from .drafts import (GmailError, attachment_pdf, gmail_login, read_gmail_draft, replace_draft,
                     send_application)
from .llm import PROVIDERS, REQUIRED, ask_llm
from .resumes import have_pdflatex, resume_pdf
from .runner import Busy, manager, start_scheduler
from .runtime import log
from .sources import SOURCES

logging.basicConfig(level=logging.INFO, format="%(message)s")
log.setLevel(logging.INFO)

STATIC_DIR = ROOT / "frontend" / "dist"
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


@asynccontextmanager
async def lifespan(_app):
    for attempt in range(30):  # the database container may still be starting
        try:
            db.init()
            break
        except psycopg2.OperationalError as e:
            if attempt == 29 or "password authentication failed" in str(e):
                raise RuntimeError(
                    f"Cannot connect to the database: {e}\nThe database password is fixed when "
                    "its volume is first created; restore the old APPLYBOT_DB_PASSWORD or reset "
                    "the database with `docker compose down -v` (deletes all data).") from e
            log.info(f"Waiting for the database ({str(e).strip().splitlines()[0]})")
            time.sleep(2)
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    with db.connection() as conn:
        imported = import_legacy_files(conn)
    if imported:
        log.info(f"Imported {', '.join(imported)} from {DATA_DIR}")
    start_scheduler()
    yield


app = FastAPI(title="ApplyBot", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional HTTP basic auth (any username) when APP_PASSWORD is set."""
    if APP_PASSWORD and request.url.path != "/api/health":
        header = request.headers.get("authorization", "")
        password = ""
        if header.lower().startswith("basic "):
            try:
                password = base64.b64decode(header[6:]).decode().split(":", 1)[1]
            except (ValueError, IndexError):
                pass
        if not secrets.compare_digest(password.encode(), APP_PASSWORD.encode()):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ApplyBot"'})
    return await call_next(request)


def query(sql, params=(), one=False):
    with db.connection() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchone() if one else cur.fetchall()


def settings():
    with db.connection() as conn:
        return load_settings(conn)


@app.get("/api/health")
def health():
    return {"ok": True}


# -------------------------------------------------------------- settings ----

@app.get("/api/settings")
def get_settings():
    cfg = settings()
    values = {k: ("" if k in SECRETS else v) for k, v in cfg.items()}
    return {
        "values": values,
        "secrets_set": {k: bool(cfg[k]) for k in SECRETS},
        "options": {"providers": list(PROVIDERS), "sources": list(SOURCES)},
        "system": {"pdflatex": have_pdflatex(), "base_pdf": BASE_PDF.exists(),
                   "auth": bool(APP_PASSWORD)},
    }


def validate(values):
    errors = {}
    if "llm_provider" in values and values["llm_provider"] not in PROVIDERS:
        errors["llm_provider"] = "Unknown provider"
    if "sources" in values and (not isinstance(values["sources"], list)
                                or not set(values["sources"]) <= set(SOURCES)):
        errors["sources"] = "Unknown source"
    if "min_score" in values and not (isinstance(values["min_score"], int)
                                      and 0 <= values["min_score"] <= 100):
        errors["min_score"] = "Must be a whole number from 0 to 100"
    if "llm_delay" in values and not (isinstance(values["llm_delay"], (int, float))
                                      and 0 <= values["llm_delay"] <= 120):
        errors["llm_delay"] = "Must be between 0 and 120 seconds"
    if "schedule_time" in values and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d",
                                                      str(values["schedule_time"])):
        errors["schedule_time"] = "Use 24-hour HH:MM"
    for key in ("gmail_address", "contact_email"):
        if values.get(key) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values[key]):
            errors[key] = "Not a valid email address"
    if errors:
        raise HTTPException(422, {"errors": errors})


@app.put("/api/settings")
def put_settings(values: dict):
    """Save settings. Secret fields set to null are left unchanged."""
    values = {k: v for k, v in values.items()
              if k in SETTINGS and k != "last_scheduled_run" and not (k in SECRETS and v is None)}
    validate(values)
    with db.connection() as conn:
        old = load_settings(conn)
        if "resume_text" in values and values["resume_text"] != old["resume_text"] \
                and "profile" not in values:
            values["profile"] = ""  # regenerated from the new resume on the next scan
        save_settings(conn, values)
    return get_settings()


@app.post("/api/settings/base-pdf")
async def upload_base_pdf(file: UploadFile):
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "That is not a PDF file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "PDF is larger than 10 MB")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BASE_PDF.write_bytes(data)
    return {"ok": True}


@app.get("/api/settings/base-pdf")
def get_base_pdf():
    if not BASE_PDF.exists():
        raise HTTPException(404, "No base PDF uploaded")
    return FileResponse(BASE_PDF, media_type="application/pdf")


@app.delete("/api/settings/base-pdf")
def delete_base_pdf():
    BASE_PDF.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/settings/test-llm")
def test_llm():
    cfg = settings()
    try:
        answer = ask_llm('Reply with exactly this JSON: {"ok": true}', cfg)
    except Exception as e:
        return {"ok": False, "message": str(e)[:400]}
    return {"ok": bool(answer.get("ok")), "message": f"{cfg['llm_provider']} is working"}


@app.post("/api/settings/test-gmail")
def test_gmail():
    try:
        imap, folder = gmail_login(settings())
        imap.logout()
    except (GmailError, OSError) as e:
        return {"ok": False, "message": str(e)[:400]}
    return {"ok": True, "message": f"Logged in; drafts go to {folder}"}


# ------------------------------------------------------------------ jobs ----

STATUS_SQL = """CASE WHEN email_sent THEN 'applied'
     WHEN email_drafted THEN 'drafted'
     WHEN applicable AND coalesce(score, 0) >= %(min)s THEN 'match'
     WHEN applicable IS NOT NULL THEN 'not_fit'
     WHEN title_screen_passed = false THEN 'screened_out'
     ELSE 'pending' END"""

LIST_COLUMNS = ("id, title, company, source, contact_email, posted_date, closing_date, score, "
                "applicable, url, is_walk_in, created_at, resume_file, "
                "(closing_date IS NULL OR closing_date >= current_date) AS is_open")

SORTS = {
    "score": "score DESC NULLS LAST, created_at DESC",
    "newest": "created_at DESC, id DESC",
    "closing": "closing_date ASC NULLS LAST, score DESC NULLS LAST",
}


@app.get("/api/jobs")
def list_jobs(status: Literal["all", "match", "drafted", "applied", "not_fit",
                              "screened_out", "pending"] = "match",
              q: str = "", source: str = "", open_only: bool = True,
              sort: Literal["score", "newest", "closing"] = "score",
              limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    params = {"min": settings()["min_score"], "q": f"%{q.strip()}%", "source": source,
              "limit": limit, "offset": offset}
    where = ["(%(q)s = '%%' OR title ILIKE %(q)s OR company ILIKE %(q)s)"]
    if source:
        where.append("source = %(source)s")
    if open_only:
        where.append("(closing_date IS NULL OR closing_date >= current_date)")
    if status != "all":
        params["status"] = status
        where.append(f"({STATUS_SQL}) = %(status)s")
    cond = " AND ".join(where)
    rows = query(f"SELECT {LIST_COLUMNS}, {STATUS_SQL} AS status, count(*) OVER () AS total "
                 f"FROM jobs WHERE {cond} ORDER BY {SORTS[sort]} "
                 f"LIMIT %(limit)s OFFSET %(offset)s", params)
    total = rows[0]["total"] if rows else 0
    for r in rows:
        del r["total"]
    return {"items": rows, "total": total}


def job_or_404(job_id):
    row = query(f"SELECT *, {STATUS_SQL} AS status, "
                "(closing_date IS NULL OR closing_date >= current_date) AS is_open "
                "FROM jobs WHERE id = %(id)s", {"id": job_id, "min": settings()["min_score"]},
                one=True)
    if not row:
        raise HTTPException(404, "Job not found")
    return row


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    row = job_or_404(job_id)
    pdf = resume_pdf(row)
    row["resume_pdf"] = pdf.name if pdf else None
    return row


class JobPatch(BaseModel):
    email_sent: bool | None = None
    email_drafted: bool | None = None


@app.patch("/api/jobs/{job_id}")
def patch_job(job_id: int, patch: JobPatch):
    job_or_404(job_id)
    changes = patch.model_dump(exclude_none=True)
    if changes:
        sets = ", ".join(f"{k} = %({k})s" for k in changes)
        query(f"UPDATE jobs SET {sets}, updated_at = now() WHERE id = %(id)s RETURNING id",
              {**changes, "id": job_id}, one=True)
    return get_job(job_id)


class Letter(BaseModel):
    subject: str
    body: str


def draft_response(job):
    pdf = attachment_pdf(job)
    return {"to": job["contact_email"], "subject": job["draft_subject"] or "",
            "body": job["draft_body"] or "", "attachment": pdf.name if pdf else None,
            "sent": bool(job["email_sent"]), "sent_at": job["sent_at"]}


def gmail_call(fn, *args):
    try:
        fn(*args)
    except (GmailError, OSError) as e:
        raise HTTPException(502, str(e)[:400]) from e


@app.get("/api/jobs/{job_id}/draft")
def get_draft(job_id: int):
    """The application email: stored with the job, or read once from older Gmail drafts."""
    job = job_or_404(job_id)
    if job["draft_body"] is None:
        if not job["email_drafted"] or job["email_sent"]:
            raise HTTPException(404, "No email drafted for this job")
        try:
            with db.connection() as conn:
                found = read_gmail_draft(conn, settings(), job)
        except (GmailError, OSError) as e:
            raise HTTPException(502, str(e)[:400]) from e
        if not found:
            raise HTTPException(404, "The draft is no longer in Gmail; it may have been sent "
                                     "or deleted there")
    return draft_response(job)


def editable_draft(job_id, letter):
    job = job_or_404(job_id)
    if job["email_sent"]:
        raise HTTPException(409, "This application was already sent")
    if not job["email_drafted"] or not job["contact_email"]:
        raise HTTPException(409, "Create a draft for this job first")
    if not letter.subject.strip() or not letter.body.strip():
        raise HTTPException(422, {"errors": {"body": "Subject and message cannot be empty"}})
    return job


@app.put("/api/jobs/{job_id}/draft")
def put_draft(job_id: int, letter: Letter):
    job = editable_draft(job_id, letter)
    with db.connection() as conn:
        gmail_call(replace_draft, conn, settings(), job, letter.subject.strip(), letter.body.strip())
    return draft_response(job_or_404(job_id))


@app.post("/api/jobs/{job_id}/send")
def send_draft(job_id: int, letter: Letter):
    job = editable_draft(job_id, letter)
    with db.connection() as conn:
        gmail_call(send_application, conn, settings(), job, letter.subject.strip(),
                   letter.body.strip())
    return get_job(job_id)


@app.get("/api/jobs/{job_id}/resume.pdf")
def job_resume(job_id: int):
    pdf = resume_pdf(job_or_404(job_id))
    if not pdf:
        raise HTTPException(404, "No tailored resume for this job yet")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name,
                        content_disposition_type="inline")


@app.get("/api/stats")
def stats():
    cfg = settings()
    row = query(f"""SELECT count(*) AS total,
        count(*) FILTER (WHERE status = 'match' AND is_open) AS matches,
        count(*) FILTER (WHERE status = 'match' AND is_open AND coalesce(contact_email, '') = '')
            AS manual,
        count(*) FILTER (WHERE status = 'drafted') AS drafted,
        count(*) FILTER (WHERE status = 'applied') AS applied,
        count(*) FILTER (WHERE created_at >= now() - interval '7 days') AS new_week,
        max(created_at) AS last_new
        FROM (SELECT *, {STATUS_SQL} AS status,
              (closing_date IS NULL OR closing_date >= current_date) AS is_open FROM jobs) j""",
                {"min": cfg["min_score"]}, one=True)
    llm_ready = bool(cfg[REQUIRED.get(cfg["llm_provider"], "gemini_api_key")])
    row["setup"] = {
        "resume": bool(cfg["resume_text"].strip()),
        "llm": llm_ready,
        "attachment": bool(cfg["resume_tex"].strip() and have_pdflatex()) or BASE_PDF.exists(),
        "gmail": bool(cfg["gmail_address"] and cfg["gmail_app_password"]),
    }
    row["schedule"] = {"enabled": cfg["schedule_enabled"], "time": cfg["schedule_time"]}
    row["min_score"] = cfg["min_score"]
    row["active_run"] = manager.active_id()
    return row


# ------------------------------------------------------------------ runs ----

class RunRequest(BaseModel):
    kind: Literal["pipeline", "job"]
    options: dict = {}


@app.post("/api/runs", status_code=201)
def start_run(req: RunRequest):
    if req.kind == "job" and req.options.get("action") not in ("evaluate", "resume", "draft"):
        raise HTTPException(422, "options.action must be evaluate, resume or draft")
    try:
        run_id = manager.start(req.kind, req.options)
    except Busy as e:
        raise HTTPException(409, str(e)) from e
    return {"id": run_id}


@app.get("/api/runs")
def list_runs(limit: int = Query(30, ge=1, le=200)):
    return query("SELECT id, kind, options, trigger, status, summary, started_at, finished_at "
                 "FROM runs ORDER BY id DESC LIMIT %s", (limit,))


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    row = query("SELECT * FROM runs WHERE id = %s", (run_id,), one=True)
    if not row:
        raise HTTPException(404, "Run not found")
    live = manager.live_log(run_id)
    if live is not None:
        row["log"] = live
    return row


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: int):
    if not manager.cancel(run_id):
        raise HTTPException(409, "That run is not in progress")
    return {"ok": True}


# -------------------------------------------------------------------- UI ----

@app.exception_handler(HTTPException)
async def http_error(_request, exc):
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": exc.detail}
    return JSONResponse(detail, status_code=exc.status_code, headers=exc.headers)


if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    file = STATIC_DIR / path
    if path and file.is_file() and STATIC_DIR in file.resolve().parents:
        return FileResponse(file)
    if not (STATIC_DIR / "index.html").exists():
        return JSONResponse({"message": "UI not built. Run `npm run build` in frontend/ "
                                        "or use Docker."}, status_code=503)
    return FileResponse(STATIC_DIR / "index.html")

