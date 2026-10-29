"""Command-line access to the same runs the web UI starts.

Usage (inside Docker:  docker compose exec app python -m app.cli ...):
  python -m app.cli run                 # the daily pipeline: scan new jobs, resumes, drafts
  python -m app.cli run --dry-run       # print the letters instead of saving Gmail drafts
  python -m app.cli run --no-drafts     # only scan and score new jobs
  python -m app.cli run --full-scan     # check every listing page, not just the new ones
  python -m app.cli run --source infopark
  python -m app.cli job 1234 draft      # one job: evaluate | resume | draft
"""

import argparse
import logging
import sys

from . import db
from .config import load_settings
from .drafts import GmailError
from .llm import LLMConfigError
from .pipeline import SetupError, job_action, run_pipeline
from .sources import SOURCES


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="the daily pipeline")
    run.add_argument("--no-scan", action="store_true", help="skip looking for new jobs")
    run.add_argument("--no-drafts", action="store_true", help="skip resumes and Gmail drafts")
    run.add_argument("--full-scan", action="store_true",
                     help="check all listing pages instead of stopping at already seen jobs")
    run.add_argument("--rescore", action="store_true", help="re-evaluate jobs already scored")
    run.add_argument("--dry-run", action="store_true", help="print letters, do not touch Gmail")
    run.add_argument("--source", action="append", choices=SOURCES, help="site to scan (repeatable)")
    job = sub.add_parser("job", help="one step for one job")
    job.add_argument("job_id", type=int)
    job.add_argument("action", choices=["evaluate", "resume", "draft"])
    job.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db.init()
    with db.connection() as conn:
        cfg = load_settings(conn)
        try:
            if args.cmd == "run":
                run_pipeline(conn, cfg, scan_jobs=not args.no_scan, drafts=not args.no_drafts,
                             full_scan=args.full_scan, rescore=args.rescore,
                             dry_run=args.dry_run, sources=args.source)
            else:
                print(job_action(conn, cfg, args.job_id, args.action, args.dry_run))
        except (SetupError, LLMConfigError, GmailError) as e:
            sys.exit(str(e))


if __name__ == "__main__":
    main()
