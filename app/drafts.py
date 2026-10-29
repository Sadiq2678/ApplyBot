"""Write a cover letter with the LLM and save it as a Gmail draft with the resume attached.

Nothing is sent automatically: drafts land in the Gmail Drafts folder, where they can be
reviewed, edited and sent from the web UI (or from Gmail itself).
Needs a Gmail App Password (https://myaccount.google.com/apppasswords) and IMAP enabled.
"""

import email
import email.policy
import imaplib
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import psycopg2.extras

from .config import BASE_PDF, candidate_name
from .resumes import resume_pdf
from .llm import ask_llm
from .runtime import log

COVER_PROMPT = """You are writing a job application email on behalf of the candidate.
Using the resume and job posting below, write a short, specific cover letter that
will be the body of the email to the recruiter.

Rules:
- 180-260 words, 3-4 short paragraphs, plain text (no markdown, no placeholders
  like [Company Address]).
- Start with "Dear Hiring Manager," (or the recruiter's name if the posting gives it).
- Say which position you are applying for, then connect 2-3 concrete items from the
  resume (projects, internship, skills) to the main requirements of the job.
- Never invent experience, skills, numbers or qualifications not in the resume.
- Mention that the resume is attached.
- End with "Regards," followed by the candidate's name ({name}), phone (from the
  resume) and the email {email}, each on its own line. Use only {email} as the
  candidate's email, never an email address from the resume.
- Also write a concise email subject, e.g. "Application for <Job Title> - <Name>".

Respond with ONLY a JSON object: {{"subject": "...", "body": "..."}}

Job title: {title}
Company: {company}
Matching skills: {matching}

Job description:
{description}

Required skills:
{skills}

=== RESUME ===
{resume}
"""


class GmailError(RuntimeError):
    pass


def load_jobs(conn, min_score, job_ids=None, force=False):
    """Open, applicable jobs with a contact email that have not been drafted or sent yet."""
    query = ("SELECT id, title, company, contact_email, closing_date, description, skills, "
             "matching_skills, missing_skills, resume_file, draft_message_id FROM jobs "
             "WHERE applicable = true AND coalesce(score, 0) >= %s "
             "AND coalesce(contact_email, '') <> '' "
             "AND (closing_date IS NULL OR closing_date >= current_date)")
    params = [min_score]
    if not force:
        query += " AND email_drafted IS NOT TRUE AND email_sent IS NOT TRUE"
    if job_ids:
        query += " AND id = ANY(%s)"
        params.append(job_ids)
    query += " ORDER BY score DESC NULLS LAST"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def contact_email(cfg):
    return cfg["contact_email"] or cfg["gmail_address"]


def attachment_name(cfg):
    return re.sub(r"\W+", "_", candidate_name(cfg)).strip("_") + "_Resume.pdf"


def cover_letter(job, cfg):
    answer = ask_llm(COVER_PROMPT.format(
        title=job["title"],
        company=job["company"],
        matching=", ".join(job["matching_skills"] or []) or "-",
        description=(job["description"] or "")[:6000],
        skills=(job["skills"] or "")[:3000],
        resume=cfg["resume_text"],
        name=candidate_name(cfg),
        email=contact_email(cfg),
    ), cfg)
    if not answer.get("subject") or not answer.get("body"):
        raise RuntimeError("LLM did not return a subject and body")
    return answer["subject"].strip(), answer["body"].strip()


def build_message(sender, to, subject, body, pdf, attach_name):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                       filename=attach_name)
    return msg


def drafts_folder(imap):
    """Gmail's Drafts folder name depends on the account language; find it by flag."""
    _, folders = imap.list()
    for f in folders:
        line = f.decode()
        if "\\Drafts" in line:
            return line.rsplit(' "/" ', 1)[-1]
    return '"[Gmail]/Drafts"'


def gmail_login(cfg):
    """Returns (imap connection, drafts folder name); raises GmailError."""
    if not (cfg["gmail_address"] and cfg["gmail_app_password"]):
        raise GmailError("Set your Gmail address and App Password in Settings -> Gmail")
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(cfg["gmail_address"], cfg["gmail_app_password"])
    except imaplib.IMAP4.error as e:
        raise GmailError(f"Gmail login failed: {e}. Use an App Password (not your normal "
                         "password) and make sure IMAP is enabled in Gmail settings.") from e
    return imap, drafts_folder(imap)


def find_drafts(imap, folder, job):
    """UIDs of this job's Gmail draft: by Message-ID, or by recipient for older drafts."""
    imap.select(folder)
    if job.get("draft_message_id"):
        typ, data = imap.uid("SEARCH", None, "HEADER", "Message-ID",
                             f'"{job["draft_message_id"]}"')
    else:
        typ, data = imap.uid("SEARCH", None, "TO", f'"{job["contact_email"]}"')
    return data[0].split() if typ == "OK" and data and data[0] else []


def delete_drafts(imap, folder, job):
    if not job.get("draft_message_id"):  # never guess by recipient: it may be another job's
        return
    uids = find_drafts(imap, folder, job)
    if uids:
        imap.uid("STORE", b",".join(uids), "+FLAGS", "(\\Deleted)")
        imap.expunge()


def draft_job(conn, imap, folder, job, pdf, cfg):
    """Write the cover letter and save it as a Gmail draft (imap None = dry run).

    Returns True on success; failures are logged.
    """
    attach_name = attachment_name(cfg)
    try:
        subject, body = cover_letter(job, cfg)
    except Exception as e:
        log.info(f"  failed: {e}")
        return False
    if imap is None:
        log.info(f"  Subject: {subject}\n  Attach: {pdf.name} as {attach_name}\n\n{body}\n")
        return True
    msg = build_message(cfg["gmail_address"], job["contact_email"], subject, body,
                        pdf, attach_name)
    typ, data = imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()),
                            msg.as_bytes())
    if typ != "OK":
        log.info(f"  Gmail refused the draft: {data}")
        return False
    if job.get("draft_message_id"):  # drafting again: remove the previous draft
        delete_drafts(imap, folder, job)
    save_letter(conn, job["id"], subject, body, msg["Message-ID"])
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET email_drafted = true, drafted_at = now(), "
                    "updated_at = now() WHERE id = %s", (job["id"],))
    log.info(f"  saved to Gmail Drafts: {subject}")
    return True


# ------------------------------------------- review, edit and send from the UI ----

def save_letter(conn, job_id, subject, body, message_id):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET draft_subject = %s, draft_body = %s, draft_message_id = %s, "
                    "updated_at = now() WHERE id = %s", (subject, body, message_id, job_id))


def attachment_pdf(job):
    """The PDF a draft carries: the job's tailored resume, else the base PDF."""
    return resume_pdf(job) or (BASE_PDF if BASE_PDF.exists() else None)


def read_gmail_draft(conn, cfg, job):
    """Fetch the subject and body of a draft made before letters were stored, and store them.

    Returns False when the draft is no longer in Gmail (sent or deleted there).
    """
    imap, folder = gmail_login(cfg)
    try:
        uids = find_drafts(imap, folder, job)
        if not uids:
            return False
        typ, data = imap.uid("FETCH", uids[-1], "(RFC822)")
    finally:
        imap.logout()
    if typ != "OK" or not data or not isinstance(data[0], tuple):
        return False
    msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
    part = msg.get_body(("plain",))
    body = part.get_content().strip() if part else ""
    job.update(draft_subject=str(msg["Subject"] or ""), draft_body=body,
               draft_message_id=msg["Message-ID"])
    save_letter(conn, job["id"], job["draft_subject"], body, job["draft_message_id"])
    return True


def replace_draft(conn, cfg, job, subject, body):
    """Save an edited letter: a new Gmail draft replaces the old one."""
    pdf = attachment_pdf(job)
    if not pdf:
        raise GmailError("No resume PDF to attach; tailor a resume or upload a base PDF")
    msg = build_message(cfg["gmail_address"], job["contact_email"], subject, body,
                        pdf, attachment_name(cfg))
    imap, folder = gmail_login(cfg)
    try:
        typ, data = imap.append(folder, "\\Draft", imaplib.Time2Internaldate(time.time()),
                                msg.as_bytes())
        if typ != "OK":
            raise GmailError(f"Gmail refused the draft: {data}")
        delete_drafts(imap, folder, job)
    finally:
        imap.logout()
    save_letter(conn, job["id"], subject, body, msg["Message-ID"])


def send_application(conn, cfg, job, subject, body):
    """Send the letter with the resume over Gmail SMTP, remove the draft, mark as applied."""
    pdf = attachment_pdf(job)
    if not pdf:
        raise GmailError("No resume PDF to attach; tailor a resume or upload a base PDF")
    if not (cfg["gmail_address"] and cfg["gmail_app_password"]):
        raise GmailError("Set your Gmail address and App Password in Settings -> Gmail")
    msg = build_message(cfg["gmail_address"], job["contact_email"], subject, body,
                        pdf, attachment_name(cfg))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
            smtp.login(cfg["gmail_address"], cfg["gmail_app_password"])
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise GmailError("Gmail login failed. Use an App Password, not your normal "
                         "password.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise GmailError(f"Sending failed: {e}") from e
    with conn.cursor() as cur:  # it is sent: record that before tidying up Gmail
        cur.execute("UPDATE jobs SET email_sent = true, sent_at = now(), draft_subject = %s, "
                    "draft_body = %s, updated_at = now() WHERE id = %s",
                    (subject, body, job["id"]))
    try:
        imap, folder = gmail_login(cfg)
        try:
            delete_drafts(imap, folder, job)
        finally:
            imap.logout()
    except (GmailError, imaplib.IMAP4.error, OSError) as e:
        log.info(f"Sent, but could not remove the Gmail draft for job {job['id']}: {e}")
