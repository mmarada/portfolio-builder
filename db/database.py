"""
Dual-mode database layer.
  - DATABASE_URL not set → SQLite  (local scraping, development)
  - DATABASE_URL set     → PostgreSQL  (Vercel production)
"""
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

_PG_URL = os.getenv("DATABASE_URL", "")


def _pg() -> bool:
    return bool(_PG_URL)


# ── Schemas ───────────────────────────────────────────────────────────────────

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    url         TEXT UNIQUE,
    description TEXT,
    posted_date TEXT,
    scraped_at  TEXT DEFAULT (datetime('now')),
    match_score REAL DEFAULT 0,
    dismissed   INTEGER DEFAULT 0,
    applied     INTEGER DEFAULT 0,
    digest_sent INTEGER DEFAULT 0,
    job_type    TEXT DEFAULT 'full_time'
);
CREATE TABLE IF NOT EXISTS contacts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER REFERENCES jobs(id),
    name         TEXT,
    title        TEXT,
    company      TEXT,
    linkedin_url TEXT,
    email        TEXT,
    found_at     TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS drafts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         INTEGER REFERENCES jobs(id),
    contact_id     INTEGER REFERENCES contacts(id),
    subject        TEXT,
    body           TEXT,
    gmail_draft_id TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    sent           INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(match_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source  ON jobs(source);
"""

_SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS jobs (
    id          SERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    url         TEXT UNIQUE,
    description TEXT,
    posted_date TEXT,
    scraped_at  TIMESTAMPTZ DEFAULT NOW(),
    match_score REAL DEFAULT 0,
    dismissed   INTEGER DEFAULT 0,
    applied     INTEGER DEFAULT 0,
    digest_sent INTEGER DEFAULT 0,
    job_type    TEXT DEFAULT 'full_time'
);
CREATE TABLE IF NOT EXISTS contacts (
    id           SERIAL PRIMARY KEY,
    job_id       INTEGER REFERENCES jobs(id),
    name         TEXT,
    title        TEXT,
    company      TEXT,
    linkedin_url TEXT,
    email        TEXT,
    found_at     TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS drafts (
    id             SERIAL PRIMARY KEY,
    job_id         INTEGER REFERENCES jobs(id),
    contact_id     INTEGER REFERENCES contacts(id),
    subject        TEXT,
    body           TEXT,
    gmail_draft_id TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    sent           INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_score   ON jobs(match_score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_source  ON jobs(source);
"""

_MIGRATIONS_SQLITE = [
    "ALTER TABLE jobs ADD COLUMN digest_sent INTEGER DEFAULT 0",
    "ALTER TABLE jobs ADD COLUMN job_type TEXT DEFAULT 'full_time'",
]

# ── Connection context managers ───────────────────────────────────────────────

@contextmanager
def get_conn():
    if _pg():
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(_PG_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        from config import DB_PATH
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row or psycopg2 RealDictRow to a plain dict."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


# ── Init ─────────────────────────────────────────────────────────────────────

def init_db():
    if _pg():
        import psycopg2
        with get_conn() as conn:
            cur = conn.cursor()
            for stmt in _SCHEMA_PG.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cur.execute(stmt)
                    except Exception:
                        conn.rollback()
    else:
        with get_conn() as conn:
            conn.executescript(_SCHEMA_SQLITE)
            for sql in _MIGRATIONS_SQLITE:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass


# ── Writes ────────────────────────────────────────────────────────────────────

def upsert_job(source, title, company, location, url, description, posted_date,
               job_type="full_time") -> int | None:
    """Insert job; skip if URL already exists. Returns row id or None."""
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO jobs (source,title,company,location,url,description,posted_date,job_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (url) DO NOTHING
                   RETURNING id""",
                (source, title, company, location, url, description, posted_date, job_type),
            )
            row = cur.fetchone()
            return row["id"] if row else None
        else:
            try:
                cur = conn.execute(
                    """INSERT INTO jobs (source,title,company,location,url,description,posted_date,job_type)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (source, title, company, location, url, description, posted_date, job_type),
                )
                return cur.lastrowid
            except sqlite3.IntegrityError:
                return None


def update_match_score(job_id: int, score: float):
    ph = "%s" if _pg() else "?"
    with get_conn() as conn:
        if _pg():
            conn.cursor().execute(f"UPDATE jobs SET match_score={ph} WHERE id={ph}", (score, job_id))
        else:
            conn.execute(f"UPDATE jobs SET match_score={ph} WHERE id={ph}", (score, job_id))


def insert_contact(job_id, name, title, company, linkedin_url, email="") -> int:
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO contacts (job_id,name,title,company,linkedin_url,email)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (job_id, name, title, company, linkedin_url, email),
            )
            return cur.fetchone()["id"]
        else:
            cur = conn.execute(
                """INSERT INTO contacts (job_id,name,title,company,linkedin_url,email)
                   VALUES (?,?,?,?,?,?)""",
                (job_id, name, title, company, linkedin_url, email),
            )
            return cur.lastrowid


def insert_draft(job_id, contact_id, subject, body, gmail_draft_id="") -> int:
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO drafts (job_id,contact_id,subject,body,gmail_draft_id)
                   VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                (job_id, contact_id, subject, body, gmail_draft_id),
            )
            return cur.fetchone()["id"]
        else:
            cur = conn.execute(
                """INSERT INTO drafts (job_id,contact_id,subject,body,gmail_draft_id)
                   VALUES (?,?,?,?,?)""",
                (job_id, contact_id, subject, body, gmail_draft_id),
            )
            return cur.lastrowid


def dismiss_job(job_id: int):
    ph = "%s" if _pg() else "?"
    with get_conn() as conn:
        if _pg():
            conn.cursor().execute(f"UPDATE jobs SET dismissed=1 WHERE id={ph}", (job_id,))
        else:
            conn.execute(f"UPDATE jobs SET dismissed=1 WHERE id={ph}", (job_id,))


def mark_applied(job_id: int):
    ph = "%s" if _pg() else "?"
    with get_conn() as conn:
        if _pg():
            conn.cursor().execute(f"UPDATE jobs SET applied=1 WHERE id={ph}", (job_id,))
        else:
            conn.execute(f"UPDATE jobs SET applied=1 WHERE id={ph}", (job_id,))


def mark_digest_sent(job_ids: list[int]):
    if not job_ids:
        return
    with get_conn() as conn:
        if _pg():
            conn.cursor().execute("UPDATE jobs SET digest_sent=1 WHERE id = ANY(%s)", (job_ids,))
        else:
            placeholders = ",".join("?" * len(job_ids))
            conn.execute(f"UPDATE jobs SET digest_sent=1 WHERE id IN ({placeholders})", job_ids)


# ── Reads ─────────────────────────────────────────────────────────────────────

def get_top_jobs(
    limit: int = 20,
    min_score: float = 0.0,
    source: Optional[str] = None,
    job_type: Optional[str] = None,
    unsent_only: bool = False,
) -> list[dict]:
    clauses = ["j.dismissed = 0", "j.match_score >= %s" if _pg() else "j.match_score >= ?"]
    params: list = [min_score]
    ph = "%s" if _pg() else "?"

    if source:
        clauses.append(f"j.source = {ph}")
        params.append(source)
    if job_type:
        clauses.append(f"j.job_type = {ph}")
        params.append(job_type)
    if unsent_only:
        clauses.append("j.digest_sent = 0")

    where = " AND ".join(clauses)
    params.append(limit)

    if _pg():
        agg = "STRING_AGG(c.name||'|'||c.title||'|'||c.linkedin_url||'|'||c.email, ';;')"
        order = "j.scraped_at::date DESC, j.match_score DESC"
    else:
        agg = "GROUP_CONCAT(c.name||'|'||c.title||'|'||c.linkedin_url||'|'||c.email, ';;')"
        order = "DATE(j.scraped_at) DESC, j.match_score DESC"

    sql = f"""
        SELECT j.*, {agg} AS contacts
        FROM jobs j
        LEFT JOIN contacts c ON c.job_id = j.id
        WHERE {where}
        GROUP BY j.id
        ORDER BY {order}
        LIMIT {ph}
    """

    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        else:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]


def get_distinct_sources() -> list[str]:
    sql = "SELECT DISTINCT source FROM jobs WHERE dismissed=0 ORDER BY source"
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(sql)
            return [r["source"] for r in cur.fetchall()]
        else:
            return [r["source"] for r in conn.execute(sql).fetchall()]


def get_job(job_id: int) -> dict | None:
    ph = "%s" if _pg() else "?"
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(f"SELECT * FROM jobs WHERE id={ph}", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            row = conn.execute(f"SELECT * FROM jobs WHERE id={ph}", (job_id,)).fetchone()
            return dict(row) if row else None


def get_draft(job_id: int) -> dict | None:
    ph = "%s" if _pg() else "?"
    sql = f"SELECT * FROM drafts WHERE job_id={ph} ORDER BY created_at DESC LIMIT 1"
    with get_conn() as conn:
        if _pg():
            cur = conn.cursor()
            cur.execute(sql, (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            row = conn.execute(sql, (job_id,)).fetchone()
            return dict(row) if row else None


# ── Postgres sync (called after local scrape) ─────────────────────────────────

def sync_sqlite_to_postgres(pg_url: str):
    """
    Push all local SQLite jobs to a PostgreSQL database.
    Called from main.py after each scrape run when POSTGRES_SYNC_URL is set.
    """
    import psycopg2
    import psycopg2.extras

    from config import DB_PATH
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    jobs = sqlite_conn.execute("SELECT * FROM jobs").fetchall()
    contacts = sqlite_conn.execute("SELECT * FROM contacts").fetchall()
    sqlite_conn.close()

    pg = psycopg2.connect(pg_url, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = pg.cursor()

    # Ensure schema exists
    for stmt in _SCHEMA_PG.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception:
                pg.rollback()

    synced = 0
    for job in jobs:
        j = dict(job)
        try:
            cur.execute(
                """INSERT INTO jobs (source,title,company,location,url,description,
                   posted_date,match_score,dismissed,applied,digest_sent,job_type)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (url) DO UPDATE SET
                     match_score=EXCLUDED.match_score,
                     description=COALESCE(EXCLUDED.description, jobs.description),
                     digest_sent=EXCLUDED.digest_sent,
                     dismissed=EXCLUDED.dismissed,
                     applied=EXCLUDED.applied""",
                (j["source"], j["title"], j["company"], j["location"], j["url"],
                 j["description"], j["posted_date"], j["match_score"],
                 j["dismissed"], j["applied"], j["digest_sent"], j.get("job_type","full_time")),
            )
            synced += 1
        except Exception:
            pg.rollback()

    pg.commit()
    pg.close()
    return synced
