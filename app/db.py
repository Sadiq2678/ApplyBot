"""PostgreSQL connection pool and schema."""

import os
from contextlib import contextmanager

import psycopg2
import psycopg2.pool

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  integer PRIMARY KEY,
    job_listing_id      text,
    title               text NOT NULL,
    company             text,
    company_website     text,
    contact_email       text,
    posted_date         date,
    closing_date        date,
    is_walk_in          boolean,
    walk_in_address     text,
    description         text,
    skills              text,
    url                 text NOT NULL,
    title_screen_passed boolean,
    applicable          boolean,
    score               integer,
    experience_required text,
    matching_skills     text[],
    missing_skills      text[],
    reason              text,
    email_sent          boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS email_drafted boolean,
                 ADD COLUMN IF NOT EXISTS drafted_at timestamptz,
                 ADD COLUMN IF NOT EXISTS resume_file text,
                 ADD COLUMN IF NOT EXISTS source text DEFAULT 'technopark',
                 ADD COLUMN IF NOT EXISTS draft_subject text,
                 ADD COLUMN IF NOT EXISTS draft_body text,
                 ADD COLUMN IF NOT EXISTS draft_message_id text,
                 ADD COLUMN IF NOT EXISTS sent_at timestamptz;
CREATE INDEX IF NOT EXISTS jobs_match_idx ON jobs (applicable, score DESC);

CREATE TABLE IF NOT EXISTS settings (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id          serial PRIMARY KEY,
    kind        text NOT NULL,
    options     jsonb NOT NULL DEFAULT '{}',
    trigger     text NOT NULL DEFAULT 'manual',
    status      text NOT NULL,
    summary     text,
    log         text NOT NULL DEFAULT '',
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
"""

_pool = None


def dsn():
    return dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "applybot"),
        user=os.environ.get("DB_USER", "applybot"),
        password=os.environ.get("DB_PASSWORD", ""),
        connect_timeout=10,
    )


def init():
    """Create the pool and the schema; marks runs interrupted by a restart as failed."""
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, **dsn())
    with connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        cur.execute("UPDATE runs SET status = 'failed', finished_at = now(), "
                    "summary = 'Interrupted by a restart' WHERE status = 'running'")


@contextmanager
def connection():
    """An autocommit connection from the pool."""
    if _pool is None:
        init()
    conn = _pool.getconn()
    conn.autocommit = True
    try:
        yield conn
    finally:
        _pool.putconn(conn)
