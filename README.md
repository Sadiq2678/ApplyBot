# ApplyBot

ApplyBot finds jobs on **[Technopark](https://technopark.in)** and **[Infopark](https://infopark.in)** that fit your resume. It scores each one with an AI model, tailors a one-page resume for each match, and saves a ready-to-review application (cover letter with the resume attached) to your **Gmail Drafts**. Nothing is sent automatically: you review, edit and send each one yourself.

It runs on your own computer with Docker. You don't need Python, Node, LaTeX or PostgreSQL installed, and it works the same on Linux, macOS and Windows.

## Features

- **Daily pipeline**: scans only jobs posted since the last run, screens them by title, then scores the rest against your resume.
- **Tailored resumes**: rewrites your LaTeX resume for each role and fits it to exactly one page. If you don't use LaTeX, it attaches your PDF as is.
- **Cover letters**: writes a specific letter for each job and saves it to Gmail Drafts with the resume attached.
- **Review, edit and send**: open a drafted job to read the email, edit the subject or text (the Gmail draft is updated), and send it. Sent jobs move to *Applied*.
- **Web dashboard**: lets you search and filter jobs, see why each one fits, start runs, watch live logs, and mark jobs as applied.
- **Any AI provider**: Google Gemini or Groq (both have free tiers), or any OpenAI-compatible API, including a local Ollama.
- **Schedule**: optional automatic daily run.

## Quick start

1. Install [Docker Desktop](https://docs.docker.com/get-docker/) (on Linux, Docker Engine with the compose plugin).
2. Get the code and start it:

   ```bash
   git clone <this repo> applybot && cd applybot
   cp .env.example .env        # optional: change APPLYBOT_DB_PASSWORD before the first start
   docker compose up -d --build
   ```

3. Open **http://localhost:8000** and follow the setup checklist:
   - **Settings → Profile & resume**: paste your resume text, say what roles you want, and add a LaTeX resume or upload a PDF.
   - **Settings → AI provider**: paste an API key, e.g. a free [Gemini key](https://aistudio.google.com/apikey), then click *Test connection*.
   - **Settings → Gmail**: your address and an [App Password](https://myaccount.google.com/apppasswords). Enable IMAP in Gmail settings.
4. Click **Run now**. The first run checks every listing page, so it takes a while. Later runs only look at new jobs.

To update: `git pull && docker compose up -d --build`. To stop: `docker compose down`. Your data is kept in Docker volumes.

## Your data and secrets

- API keys, the Gmail App Password and your resume are stored in the local PostgreSQL database, inside a Docker volume on your machine. The UI never shows saved secrets back, only whether they are set.
- The web UI only listens on `127.0.0.1` by default. To open it to your network, set `APPLYBOT_BIND=0.0.0.0` **and** `APP_PASSWORD=...` in `.env`. The UI has no other login.
- The database is only reachable from inside Docker.
- `.env`, `data/`, resumes, PDFs and `.tex` files are git-ignored. **Never commit `.env`.**
- Backup: `docker compose exec db pg_dump -U applybot applybot > backup.sql` (also git-ignored).

## Configuration

Everything about *you* is set in the UI. `.env` only holds Docker options; see [`.env.example`](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `APPLYBOT_DB_PASSWORD` | `applybot` | Password of the bundled database. Fixed when the volume is first created. |
| `APPLYBOT_PORT` | `8000` | Port of the web UI on your computer |
| `APPLYBOT_BIND` | `127.0.0.1` | Interface to listen on |
| `APP_PASSWORD` | *(none)* | Turns on a password prompt for the UI |
| `TZ` | `Asia/Kolkata` | Time zone for the daily schedule |

Settings variables such as `GEMINI_API_KEY` or `GMAIL_ADDRESS` in `.env` are used as defaults until you save that setting in the UI.

### Local AI with Ollama

Choose **OpenAI-compatible** and use base URL `http://host.docker.internal:11434/v1` with a model you have pulled, e.g. `llama3.1`. Leave the API key empty.

## Command line

The same runs are available from the terminal, e.g. for cron:

```bash
docker compose exec app python -m app.cli run              # daily pipeline
docker compose exec app python -m app.cli run --dry-run    # preview letters, no Gmail
docker compose exec app python -m app.cli run --no-drafts  # only scan and score
docker compose exec app python -m app.cli job 1234 draft   # one job: evaluate | resume | draft
```

## Migrating from the old scripts

If you used the earlier command-line version (`japplay.py`, `daily.py`, ...):

```bash
docker compose up -d --build
# 1. resume files: copied into the data volume and imported on the next start
for f in resume.txt latex.txt profile.txt preferences.txt; do
  [ -f "data/$f" ] && docker compose cp "data/$f" app:/data/$f
done
docker compose cp data/resumes/. app:/data/resumes/
# 2. jobs database (replace the connection details with your old ones)
pg_dump -h localhost -U <old user> -d <old db> --data-only -t jobs | docker compose exec -T db psql -U applybot -d applybot
docker compose restart app
```

## Development

```bash
# backend (needs PostgreSQL; set DB_* in .env)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend, with hot reload, proxies /api to :8000
cd frontend && npm install && npm run dev     # http://localhost:5173
```

API docs are at `/api/docs` while it runs.

```
app/
  main.py       FastAPI routes + serves the built UI
  pipeline.py   daily run and single-job actions
  matcher.py    title screening, scoring, job storage
  sources.py    Technopark / Infopark scrapers
  resumes.py    LaTeX tailoring and one-page fitting
  drafts.py     cover letters and Gmail drafts (IMAP)
  llm.py        Gemini / Groq / OpenAI-compatible clients
  runner.py     background runs, live logs, daily scheduler
  config.py     settings (DB, then env, then defaults)
  db.py         connection pool and schema
  cli.py        command-line entry point
frontend/       React + TypeScript + Tailwind UI
```

## Troubleshooting

- **"password authentication failed" on start**: `APPLYBOT_DB_PASSWORD` changed after the database was created. Put the old value back, or reset everything with `docker compose down -v` (this deletes all data).
- **Gmail login failed**: use an App Password, not your normal password, and enable IMAP.
- **LaTeX resume does not compile**: open the run log. Packages outside `texlive-latex-extra` need adding to the `Dockerfile`.
- **Rate limits (429)**: ApplyBot waits and retries. Raise *Delay between AI calls* in Settings if it keeps happening.
