"""Tailor the base LaTeX resume to a job and compile it to a one-page PDF.

The LLM rewrites the resume keeping only what is relevant to the position. Every
resume is made to fill one full page: if it comes out short (or spills onto a
second page) the LLM is asked to add back relevant content from the original
resume (or trim) until it fits.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg2.extras

from .config import RESUMES_DIR
from .llm import ask_llm
from .runtime import log, sleep

TAILOR_PROMPT = """You are an expert resume writer. Below is a candidate's resume in LaTeX
and a job posting. Produce a tailored version of the resume for this position.

Rules:
- Keep the preamble, document class, packages, custom commands and overall
  layout exactly as in the original, so it compiles the same way.
- Keep only the content relevant to this position: drop or shorten unrelated
  projects, bullet points, skills and sections; reorder so the most relevant
  items come first; adjust the summary/objective (if any) to target this role.
- Never invent experience, skills, employers, dates, numbers or degrees. You may
  only rephrase, reorder, select or remove what is already in the resume.
- Keep personal/contact details and education unchanged.
- The result must fill exactly ONE full A4 page: not shorter, not longer. If
  removing unrelated content leaves the page short, keep more of the original
  content (most relevant first) and use fuller bullet points so the page is full.
- Escape LaTeX special characters (& % $ # _ {{ }}) in any text you write.
- Output ONLY the complete LaTeX source, from \\documentclass to \\end{{document}},
  with no explanation and no markdown fences.

Job title: {title}
Company: {company}
Matching skills: {matching}
Missing skills: {missing}

Job description:
{description}

Required skills:
{skills}

Original resume (LaTeX):
{resume}
"""


FIT_PROMPT = """Below is a tailored LaTeX resume for the position "{title}" at {company},
and the candidate's original full resume.

Problem: {problem}

Fix it: {action}
Rules:
- Never invent experience, skills, employers, dates, numbers or degrees. Use only
  content that exists in the original resume (rephrasing is fine).
- Do not change the preamble, packages, margins, font size or spacing commands.
- Keep the content relevant to the position and in the same order of relevance.
- Output ONLY the complete LaTeX source, from \\documentclass to \\end{{document}},
  with no explanation and no markdown fences.

Job description (for relevance):
{description}

Tailored resume (LaTeX) to fix:
{tex}

Original resume (LaTeX):
{resume}
"""

SIMILAR_PROMPT = """A candidate already has resumes tailored for the positions below. Decide
whether one of them can be sent unchanged for a new position because it is the same
kind of role: same role family and mostly the same key skills (e.g. two Python
developer roles, or two data analyst roles). Different roles (e.g. a QA role vs a web
developer role) need their own resume.

New position: {title} at {company}
Key skills: {skills}
Description:
{description}

Existing resumes:
{existing}

Respond with ONLY a JSON object: {{"id": <id of the existing resume to reuse, or null>}}
"""

MIN_FILL = 0.90      # one page must be at least this full
FIT_ROUNDS = 4       # LLM attempts to fix the page fill
LINE_PT = 13.6       # approx. height of one text line at 11pt


def have_pdflatex():
    return shutil.which("pdflatex") is not None


def slug(text, length=40):
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:length].strip("-") or "x"


def existing_resume(job_id):
    return next(RESUMES_DIR.glob(f"{job_id}_*.tex"), None)


def resume_pdf(job):
    """The PDF to send for a job: its own, or the one it reuses (resume_file)."""
    if job.get("resume_file") and (RESUMES_DIR / job["resume_file"]).exists():
        return RESUMES_DIR / job["resume_file"]
    return next(RESUMES_DIR.glob(f"{job['id']}_*.pdf"), None)


def set_resume_file(conn, job_id, pdf):
    with conn.cursor() as cur:
        cur.execute("UPDATE jobs SET resume_file = %s, updated_at = now() WHERE id = %s",
                    (pdf.name, job_id))


def tailored_resumes(conn):
    """Jobs that have their own tailored PDF: {id: job row}."""
    ids = [int(m[1]) for f in RESUMES_DIR.glob("*.pdf") if (m := re.match(r"(\d+)_", f.name))]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT id, title, company, matching_skills FROM jobs WHERE id = ANY(%s)",
                    (ids,))
        return {r["id"]: r for r in cur.fetchall()}


def norm_title(title):
    title = re.sub(r"\(.*?\)|\[.*?\]", " ", (title or "").lower())
    return " ".join(re.findall(r"[a-z0-9+#]+", title))


def find_similar(job, existing, cfg):
    """Id of an existing tailored resume for the same kind of role, or None."""
    others = [e for e in existing.values() if e["id"] != job["id"]]
    if not others:
        return None
    for e in others:  # identical title: no LLM call needed
        if norm_title(e["title"]) == norm_title(job["title"]):
            return e["id"]
    lines = "\n".join(f"{e['id']}: {e['title']} @ {e['company']} "
                      f"(skills: {', '.join((e['matching_skills'] or [])[:8]) or '-'})"
                      for e in others)
    answer = ask_llm(SIMILAR_PROMPT.format(
        title=job["title"], company=job["company"],
        skills=", ".join(job["matching_skills"] or []) or "-",
        description=(job["description"] or "")[:1500], existing=lines), cfg)
    try:
        jid = int(answer.get("id"))
    except (TypeError, ValueError):
        return None
    return jid if jid in existing and jid != job["id"] else None


def create_resume(job, cfg):
    """Tailor, fit to one page, save and compile; returns (tex path, pdf path or None)."""
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    resume_tex = cfg["resume_tex"]
    tex = tailor(job, resume_tex, cfg)
    tex, result = fit_page(tex, job, resume_tex, cfg)
    if result:
        log.info(f"  {describe(result)}")
    old = existing_resume(job["id"])
    if old:
        for f in RESUMES_DIR.glob(f"{old.stem}.*"):
            f.unlink()
    out = RESUMES_DIR / f"{job['id']}_{slug(job['company'])}_{slug(job['title'])}.tex"
    out.write_text(tex + "\n")
    log.info(f"  -> {out.name}")
    pdf = compile_pdf(out)
    if pdf:
        log.info(f"  -> {pdf.name}")
    return out, pdf


def clean_tex(tex):
    tex = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tex.strip())
    if "\\documentclass" not in tex or "\\end{document}" not in tex:
        raise RuntimeError("LLM did not return a complete LaTeX document")
    return tex


def measure(tex):
    """Compile in a temp dir; return (pages, fill of last page 0..1, page goal) or None."""
    if not have_pdflatex():
        return None
    marker = ("\\par\\typeout{APPLYBOT-FILL \\the\\value{page} "
              "\\the\\pagetotal\\space\\the\\pagegoal}\n\\end{document}")
    probe = tex.replace("\\end{document}", marker)
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "probe.tex").write_text(probe)
        try:
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "probe.tex"],
                           cwd=d, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            return None
        log_path = Path(d) / "probe.log"
        text = log_path.read_text(errors="ignore") if log_path.exists() else ""
    m = re.search(r"APPLYBOT-FILL (\d+) ([\d.]+)pt ([\d.]+)pt", text)
    if not m:
        return None
    pages, total, goal = int(m[1]), float(m[2]), float(m[3])
    # \pagegoal is \maxdimen (16383.99998pt) on an empty page
    fill = 0.0 if goal > 10000 else total / goal
    return pages, fill, goal


def fits(result):
    return result is None or (result[0] == 1 and result[1] >= MIN_FILL)


def describe(result):
    pages, fill, _ = result
    return f"{pages} page(s), last page {fill:.0%} full"


def fit_page(tex, job, resume_tex, cfg):
    """Ask the LLM to grow/shrink the resume until it fills exactly one page."""
    result = measure(tex)
    best = (tex, result)
    for _ in range(FIT_ROUNDS):
        if fits(result):
            return tex, result
        pages, fill, goal = result
        if pages == 1:
            lines = max(2, round((1 - fill) * goal / LINE_PT))
            problem = (f"it fills only {fill:.0%} of the page; about {lines} lines "
                       "at the bottom are empty.")
            action = (f"add roughly {lines} more lines of content so the page is completely "
                      "full, by bringing back relevant projects, bullet points, skills or "
                      "sections from the original resume and writing fuller bullet points. "
                      "It must still fit on ONE page.")
        else:
            # whole sections move to the next page together, so ask for a bit extra
            over = 2 * round(((pages - 2) * goal + fill * goal) / LINE_PT) + 2
            problem = (f"it is {pages} pages long; the last {over // 2 - 1} lines or so "
                       "spill onto page 2.")
            action = (f"cut about {over} lines in total so everything fits on ONE page: "
                      "shorten the longest project/experience descriptions (fewer words "
                      "per paragraph or bullet), merge short skill lines, or drop the least "
                      "relevant item. The page should still be nearly full.")
        log.info(f"  {describe(result)} -> asking LLM to fix")
        sleep(float(cfg["llm_delay"]))
        try:
            new = clean_tex(ask_llm(FIT_PROMPT.format(
                title=job["title"], company=job["company"], problem=problem, action=action,
                description=(job["description"] or "")[:3000], tex=tex, resume=resume_tex),
                cfg, json_mode=False))
        except Exception as e:
            log.info(f"  fix failed: {e}")
            break
        new_result = measure(new)
        if new_result is None:  # does not compile, keep the previous version
            log.info("  fixed version does not compile, discarded")
            continue
        tex, result = new, new_result
        if rank(result) > rank(best[1]):
            best = (tex, result)
    return tighten(*best)


def tighten(tex, result):
    """Last resort for a small spill onto page 2: reduce line spacing a little."""
    m = re.search(r"\\setstretch\{([\d.]+)\}", tex)
    if fits(result) or not m or result[0] != 2 or result[1] > 0.15:
        return tex, result
    for stretch in (0.98, 0.96, 0.94):
        new = tex[:m.start()] + f"\\setstretch{{{stretch * float(m[1]):.2f}}}" + tex[m.end():]
        new_result = measure(new)
        if new_result and new_result[0] == 1:
            log.info(f"  line spacing tightened to {stretch:.0%} to fit one page")
            return new, new_result
    return tex, result


def rank(result):
    """Higher is better: a full single page beats an overflow beats a short page."""
    if result is None:
        return -1
    pages, fill, _ = result
    if pages == 1:
        return 2 + fill if fill >= MIN_FILL else fill
    return 1 + 0.5 / pages - fill * 0.1


def tailor(job, resume_tex, cfg):
    prompt = TAILOR_PROMPT.format(
        title=job["title"],
        company=job["company"],
        matching=", ".join(job["matching_skills"] or []) or "-",
        missing=", ".join(job["missing_skills"] or []) or "-",
        description=(job["description"] or "")[:6000],
        skills=(job["skills"] or "")[:3000],
        resume=resume_tex,
    )
    return clean_tex(ask_llm(prompt, cfg, json_mode=False))


def compile_pdf(tex_path):
    """Compile with pdflatex next to the .tex; returns the PDF path or None."""
    if not have_pdflatex():
        return None
    try:
        r = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=tex_path.parent, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        log.info("  pdflatex timed out")
        return None
    for ext in (".aux", ".log", ".out"):
        if r.returncode == 0 or ext != ".log":  # keep the log when it fails
            tex_path.with_suffix(ext).unlink(missing_ok=True)
    if r.returncode != 0:
        log.info(f"  pdflatex failed, see {tex_path.with_suffix('.log').name}")
        return None
    return tex_path.with_suffix(".pdf")
