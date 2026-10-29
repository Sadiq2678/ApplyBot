"""Runs long jobs (scans, resumes, drafts) in a background thread, one at a time.

Each run is a row in the `runs` table; its log is captured from the `applybot`
logger, kept in memory while it runs and saved when it finishes. A scheduler
thread starts the daily pipeline at the time set in Settings.
"""

import logging
import threading
import time
from datetime import datetime

from psycopg2.extras import Json

from . import db
from .config import load_settings, save_settings
from .drafts import GmailError
from .llm import LLMConfigError
from .pipeline import SetupError, job_action, run_pipeline
from .runtime import Cancelled, clear_cancel, log, request_cancel

KINDS = {"pipeline", "job"}


class Busy(RuntimeError):
    pass


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class RunManager:
    def __init__(self):
        self._lock = threading.Lock()
        self.current = None      # (run id, _Capture) while a run is active

    def active_id(self):
        cur = self.current
        return cur[0] if cur else None

    def live_log(self, run_id):
        cur = self.current
        if cur and cur[0] == run_id:
            return "\n".join(cur[1].lines)
        return None

    def start(self, kind, options, trigger="manual"):
        if kind not in KINDS:
            raise ValueError(f"unknown run kind {kind!r}")
        with self._lock:
            if self.current:
                raise Busy(f"Run #{self.current[0]} is still in progress")
            with db.connection() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO runs (kind, options, trigger, status) "
                            "VALUES (%s, %s, %s, 'running') RETURNING id",
                            (kind, Json(options), trigger))
                run_id = cur.fetchone()[0]
            capture = _Capture()
            self.current = (run_id, capture)
        clear_cancel()
        threading.Thread(target=self._run, args=(run_id, kind, options, capture),
                         name=f"run-{run_id}", daemon=True).start()
        return run_id

    def cancel(self, run_id):
        if self.active_id() != run_id:
            return False
        request_cancel()
        return True

    def _run(self, run_id, kind, options, capture):
        log.addHandler(capture)
        status, summary = "succeeded", ""
        try:
            with db.connection() as conn:
                cfg = load_settings(conn)
                if kind == "pipeline":
                    summary = run_pipeline(
                        conn, cfg,
                        scan_jobs=options.get("scan", True),
                        drafts=options.get("drafts", True),
                        full_scan=options.get("full_scan", False),
                        rescore=options.get("rescore", False),
                        dry_run=options.get("dry_run", False),
                        sources=options.get("sources") or None)
                else:
                    summary = job_action(conn, cfg, int(options["job_id"]), options["action"],
                                         dry_run=options.get("dry_run", False))
        except Cancelled:
            status, summary = "cancelled", "Cancelled"
            log.info("\nCancelled.")
        except (SetupError, LLMConfigError, GmailError) as e:
            status, summary = "failed", str(e)
            log.info(f"\n{e}" if capture.lines else str(e))
        except Exception as e:
            status, summary = "failed", f"{type(e).__name__}: {e}"
            log.exception("Run failed")
            capture.lines.append(f"\n{type(e).__name__}: {e}")
        finally:
            log.removeHandler(capture)
            with db.connection() as conn, conn.cursor() as cur:
                cur.execute("UPDATE runs SET status = %s, summary = %s, log = %s, "
                            "finished_at = now() WHERE id = %s",
                            (status, summary, "\n".join(capture.lines), run_id))
            with self._lock:
                self.current = None


manager = RunManager()


def scheduler_loop(interval=30):
    """Start the daily pipeline once a day at the configured time (container local time)."""
    while True:
        time.sleep(interval)
        try:
            with db.connection() as conn:
                cfg = load_settings(conn)
                if not cfg["schedule_enabled"]:
                    continue
                now = datetime.now()
                today = now.date().isoformat()
                due = now.strftime("%H:%M") >= cfg["schedule_time"]
                if due and cfg["last_scheduled_run"] != today and not manager.active_id():
                    save_settings(conn, {"last_scheduled_run": today})
                    manager.start("pipeline", {}, trigger="schedule")
        except Exception:
            log.exception("scheduler error")


def start_scheduler():
    threading.Thread(target=scheduler_loop, name="scheduler", daemon=True).start()
