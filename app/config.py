"""Paths and user settings.

Infrastructure (database, data dir) comes from environment variables. Everything
about the user (resume, preferences, API keys, Gmail) is a *setting*: stored in
the `settings` table and edited from the web UI. A setting that has never been
saved falls back to its environment variable, then to its default, so an
existing .env keeps working.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=ROOT / ".env"):
    """Minimal .env loader for running outside Docker (compose loads it itself)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env()

DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data")).resolve()
RESUMES_DIR = DATA_DIR / "resumes"
BASE_PDF = DATA_DIR / "base_resume.pdf"   # used when there is no LaTeX resume


@dataclass(frozen=True)
class Setting:
    default: object = ""
    env: str | None = None
    secret: bool = False


SETTINGS = {
    # candidate
    "candidate_name": Setting("", "CANDIDATE_NAME"),
    "contact_email": Setting("", "CONTACT_EMAIL"),
    "resume_text": Setting(""),
    "resume_tex": Setting(""),
    "profile": Setting(""),               # short summary for title screening, auto-generated
    "preferences": Setting(""),           # target roles, things to favour or avoid
    "open_to_internships": Setting(True),
    # LLM
    "llm_provider": Setting("gemini", "LLM_PROVIDER"),
    "gemini_api_key": Setting("", "GEMINI_API_KEY", secret=True),
    "gemini_model": Setting("gemini-3.5-flash-lite", "GEMINI_MODEL"),
    "groq_api_key": Setting("", "GROQ_API_KEY", secret=True),
    "groq_model": Setting("llama-3.3-70b-versatile", "GROQ_MODEL"),
    "openai_base_url": Setting("https://api.openai.com/v1", "OPENAI_BASE_URL"),
    "openai_api_key": Setting("", "OPENAI_API_KEY", secret=True),
    "openai_model": Setting("gpt-4o-mini", "OPENAI_MODEL"),
    "llm_delay": Setting(6.0, "LLM_DELAY"),
    # Gmail
    "gmail_address": Setting("", "GMAIL_ADDRESS"),
    "gmail_app_password": Setting("", "GMAIL_APP_PASSWORD", secret=True),
    # pipeline
    "sources": Setting(["technopark", "infopark"]),
    "min_score": Setting(60),
    "reuse_resumes": Setting(True),
    "schedule_enabled": Setting(False),
    "schedule_time": Setting("08:00"),
    "last_scheduled_run": Setting(""),
}

SECRETS = [k for k, s in SETTINGS.items() if s.secret]


def _coerce(value, default):
    """Env vars are strings; convert them to the default's type."""
    if isinstance(value, str) and not isinstance(default, str):
        if isinstance(default, bool):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, (int, float)):
            try:
                return type(default)(value)
            except ValueError:
                return default
        if isinstance(default, list):
            return [v.strip() for v in value.split(",") if v.strip()]
    return value


def load_settings(conn):
    """All settings as a dict: stored value, else env var, else default."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM settings")
        stored = dict(cur.fetchall())
    cfg = {}
    for key, s in SETTINGS.items():
        if key in stored and stored[key] not in ("", None):
            cfg[key] = stored[key]
        elif s.env and os.environ.get(s.env):
            cfg[key] = _coerce(os.environ[s.env], s.default)
        else:
            cfg[key] = s.default
    if cfg["gmail_app_password"]:
        cfg["gmail_app_password"] = cfg["gmail_app_password"].replace(" ", "")
    return cfg


def save_settings(conn, values):
    from psycopg2.extras import Json

    with conn.cursor() as cur:
        for key, value in values.items():
            if key not in SETTINGS:
                continue
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                (key, Json(value)))


def candidate_name(cfg):
    if cfg["candidate_name"]:
        return cfg["candidate_name"].strip()
    lines = cfg["resume_text"].strip().splitlines()
    return lines[0].strip() if lines else "Candidate"


def import_legacy_files(conn):
    """First start only: pick up resume.txt / latex.txt / profile.txt / preferences.txt
    placed in the data dir by the old command-line version."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM settings WHERE key IN ('resume_text', 'resume_tex')")
        if cur.fetchone()[0]:
            return []
    found = {}
    for key, name in [("resume_text", "resume.txt"), ("resume_tex", "latex.txt"),
                      ("resume_tex", "resume.tex"), ("profile", "profile.txt"),
                      ("preferences", "preferences.txt")]:
        path = DATA_DIR / name
        if key not in found and path.exists() and path.read_text().strip():
            found[key] = path.read_text().strip()
    if found:
        save_settings(conn, found)
    return sorted(found)
