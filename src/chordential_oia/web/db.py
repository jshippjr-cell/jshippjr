"""SQLite persistence for the dashboard.

Opportunities are stored with both their raw facts and a cached evaluation
(qualification + score) so the inbox/lanes can filter and sort in SQL. The
cache is always produced by the existing engines (:mod:`evaluate`) — there is no
separate scoring logic here, per the build constraint. Detail pages reconstruct
the :class:`Opportunity` and re-run the engines for the full breakdown.

SQLite (stdlib) keeps the app self-contained and runnable with no external
service; the schema maps cleanly onto Postgres/Supabase later.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from ..invoicing import INVOICE_STATES, Invoice
from ..models import BuyerType, BuyerValue, MusicDiscipline, MusicRequirement, Opportunity
from ..proposals import PROPOSAL_STATES, Proposal
from ..strategic import assess_strategic_value
from ..talent import InviteStatus, ReviewStatus, Talent
from .evaluate import evaluate

DEFAULT_DB_PATH = os.environ.get("CHORDENTIAL_DB", "chordential.db")

# Human-managed pipeline states (distinct from the engine's qualification action).
PIPELINE_STATES = ["New", "Pursuing", "Submitted", "Won", "Lost", "Passed"]

# View-layer display labels for the stored pipeline states (ruling #2). The stored
# values above never change (no data migration); these are friendly labels shown to
# the user. Lost + Passed both read as "Closed".
STAGE_LABELS = {
    "New": "New",
    "Pursuing": "Reaching out",
    "Submitted": "Proposal out",
    "Won": "Won",
    "Lost": "Closed",
    "Passed": "Closed",
}


def stage_label(status: str) -> str:
    """Friendly display label for a raw pipeline status (falls back to the raw value)."""
    return STAGE_LABELS.get(status, status)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    need TEXT NOT NULL,
    description TEXT DEFAULT '',
    source TEXT DEFAULT 'unknown',
    source_tier INTEGER,
    url TEXT,
    buyer_type TEXT,
    music_requirement TEXT,
    budget_min REAL,
    budget_max REAL,
    location TEXT,
    tags TEXT,
    created_at TEXT,
    -- evaluation cache (always from the engines)
    qualified INTEGER,
    discipline TEXT,
    alignment REAL,
    action TEXT,
    confidence TEXT,
    needs_review INTEGER,
    score REAL,
    tier TEXT,
    win_probability TEXT,
    -- CMO Strategic-Value lens
    buyer_value TEXT DEFAULT 'unknown',
    marquee INTEGER DEFAULT 0,
    strategic_value REAL,
    strategic_tier TEXT,
    -- human pipeline
    status TEXT DEFAULT 'New',
    outcome_value REAL,
    notes TEXT DEFAULT '',
    -- Outreach-to-win layer
    contact_name TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    contact_role TEXT,
    contact_linkedin TEXT,
    next_action TEXT,
    next_action_due TEXT,
    last_contacted TEXT,
    delivery_doc_sent_at TEXT,
    doc_overrides TEXT
);

CREATE TABLE IF NOT EXISTS outreach_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id INTEGER NOT NULL,
    created_at TEXT,
    channel TEXT,
    direction TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS talent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    disciplines TEXT,            -- JSON list of MusicDiscipline values
    credits TEXT DEFAULT '',
    location TEXT,
    demo_reel_url TEXT,
    review_status TEXT DEFAULT 'Pending',
    invite_status TEXT DEFAULT 'Prospect',
    notes TEXT DEFAULT '',
    created_at TEXT,
    source TEXT,                 -- 'manual' | 'applicant' | source key
    source_url TEXT,
    rate REAL,                   -- founder-set pay rate (NULL = no rate set)
    rate_unit TEXT DEFAULT 'hourly'  -- 'hourly' | 'day' | 'project'
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opp_id INTEGER,
    client TEXT, need TEXT,
    budget_min REAL, budget_max REAL,
    deadline TEXT,
    status TEXT DEFAULT 'Active',
    roles TEXT,                  -- JSON list of required role names
    created_at TEXT,
    delivery_json TEXT,          -- Delivery OS (Phase 0) per-project state (JSON)
    share_token TEXT             -- token gating the client delivery portal
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    role TEXT,
    talent_id INTEGER,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT,
    status TEXT DEFAULT 'Pending',
    role TEXT,
    created_at TEXT,
    updated_at TEXT
);

-- Delivery OS Review Portal: timestamped feedback + approve/request-changes on the
-- version under review. kind: 'comment' (timecoded), 'approval', 'change_request'.
CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    version TEXT,
    t_seconds REAL,
    author TEXT,
    email TEXT,
    body TEXT,
    kind TEXT DEFAULT 'comment',
    created_at TEXT,
    -- IP2 (Frame.io review polish): per-comment resolve + one level of reply.
    resolved INTEGER DEFAULT 0,    -- 0 = open, 1 = resolved (toggled by reviewer)
    parent_id INTEGER,             -- a reply nests one level under its parent comment
    -- Verified-identity approval: 1 when posted from a verified reviewer's personal
    -- invite link (?r=) — name + email are the locked roster identity, not free text.
    verified INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    body TEXT,
    kind TEXT DEFAULT 'update',
    created_at TEXT
);

-- Company-level metadata (buyers are aggregated by client name; this table holds
-- the few attributes that belong to the company itself, not a single opportunity).
CREATE TABLE IF NOT EXISTS companies (
    client TEXT PRIMARY KEY,
    website TEXT,
    updated_at TEXT
);

-- Pursuit-brief checklist progress: which steps a human has ticked off per opp.
CREATE TABLE IF NOT EXISTS brief_progress (
    opp_id INTEGER NOT NULL,
    step_key TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    updated_at TEXT,
    PRIMARY KEY (opp_id, step_key)
);

-- Inbound leads from the public front-of-house site (questionnaire + book-a-call).
-- These are NOT opportunities: a human reviews and explicitly promotes a lead
-- into the pipeline (precision-bias rule), so they land in their own review queue.
CREATE TABLE IF NOT EXISTS inbound_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    contact_name TEXT,
    contact_email TEXT,
    phone TEXT,
    contact_linkedin TEXT,
    company TEXT,
    project_type TEXT,
    description TEXT DEFAULT '',
    budget_text TEXT,
    timeline TEXT,
    source TEXT DEFAULT 'questionnaire',   -- 'questionnaire' | 'book_call'
    status TEXT DEFAULT 'New',             -- New | Reviewed | Qualified | Dismissed
    linked_opp_id INTEGER,
    notes TEXT DEFAULT '',
    -- Indicative price band shown to the client at intake (the estimator's
    -- output). Captured so we can later compare what we quoted vs what we won.
    shown_price_low REAL,
    shown_price_high REAL
);

-- Human-gated discovery crawler: proposed places to look, awaiting Jon's
-- approval. Nothing is fetched until a target is Approved ("machine proposes,
-- Jon disposes"). Serves both the talent (supply) and opportunity (demand) sides.
CREATE TABLE IF NOT EXISTS crawl_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                    -- 'talent' | 'opportunity'
    label TEXT,                            -- human-readable description of the target
    query TEXT,                            -- the search terms/keywords used
    url TEXT,                              -- the exact URL that would be fetched
    source_key TEXT,                       -- which proposer/provider produced it
    rationale TEXT,                        -- why this target was suggested
    status TEXT DEFAULT 'Proposed',        -- Proposed | Approved | Fetched | Dismissed
    result_count INTEGER,                  -- how many records the fetch yielded
    proposed_at TEXT,
    decided_at TEXT,
    fetched_at TEXT,
    notes TEXT DEFAULT '',
    last_outcome TEXT                      -- why the last fetch returned what it did
);

-- Proposals — deterministic paperwork generated from the estimator. Payment
-- execution (Stripe) is a separate later step; this stores the document + status.
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    opp_id INTEGER,
    created_at TEXT,
    status TEXT DEFAULT 'Draft',           -- Draft | Sent | Accepted | Declined
    deposit_pct REAL,
    deposit_amount REAL,
    total_price REAL,
    balance_due REAL,
    line_items TEXT,                        -- JSON [{role,hours,rate,cost}]
    terms TEXT,                             -- JSON [str]
    notes TEXT DEFAULT ''
);

-- Invoices — deposit + final, reconciling to the proposal total. external_ref /
-- paid_at exist from the start so the later Stripe wire-up needs no schema change.
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    proposal_id INTEGER,
    created_at TEXT,
    kind TEXT,                              -- 'Deposit' | 'Final'
    status TEXT DEFAULT 'Draft',            -- Draft | Issued | Paid
    amount REAL,
    note TEXT DEFAULT '',
    external_ref TEXT,                      -- payment-provider id (Stripe, later)
    paid_at TEXT
);

-- "My chips" — reusable support descriptors Jon types once and keeps. Global
-- (not per-deal): a phrase written for one client is available on every doc.
CREATE TABLE IF NOT EXISTS custom_chips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family TEXT,                            -- craft | aesthetic | deliverable | assurance
    label TEXT,                            -- short label shown in the rail
    sentence TEXT,                         -- the sentence inserted into the doc
    created_at TEXT
);
"""

PROJECT_STATES = ["Active", "Delivered"]
MILESTONE_STATES = ["Pending", "In progress", "Done"]
# Front-of-house inbound-lead review states (human qualifies before the pipeline).
INBOUND_STATES = ["New", "Reviewed", "Qualified", "Dismissed"]

# Columns added to inbound_leads after the table first shipped — migrated onto an
# existing DB (e.g. one already running Cycle 1.2) the same way _OUTREACH_COLUMNS is.
_INBOUND_COLUMNS = {
    "shown_price_low": "REAL",
    "shown_price_high": "REAL",
    "phone": "TEXT",
    "contact_linkedin": "TEXT",
}

# Delivery OS (Phase 0) columns added to projects after the table first shipped —
# migrated onto an existing DB the same idempotent way the others are.
_PROJECT_COLUMNS = {
    # The thin per-project Delivery OS state, a JSON blob (see get_delivery for the
    # shape). Display/workflow data only — never queried relationally — so an
    # untouched project renders exactly as before.
    "delivery_json": "TEXT",
    # Unguessable per-project share token gating the client delivery portal
    # (?k=<token>), mirroring the opportunities.share_token first-touch pattern.
    "share_token": "TEXT",
}

# Provenance columns on talent — migrated onto an existing roster the same way.
_TALENT_COLUMNS = {
    "source": "TEXT",
    "source_url": "TEXT",
    "rate": "REAL",
    "rate_unit": "TEXT DEFAULT 'hourly'",
}

# Columns added by the Outreach layer — applied to pre-existing databases via an
# idempotent migration so an older chordential.db keeps working after a pull.
_OUTREACH_COLUMNS = {
    "contact_name": "TEXT",
    "contact_email": "TEXT",
    "contact_phone": "TEXT",
    "contact_role": "TEXT",
    "contact_linkedin": "TEXT",
    "contact_handle": "TEXT",      # poster's handle (e.g. reddit author) for DM deep-links
    "next_action": "TEXT",
    "next_action_due": "TEXT",
    "last_contacted": "TEXT",
    "delivery_doc_sent_at": "TEXT",
    # Editable client-document per-deal overrides (JSON blob). Display data only,
    # never queried relationally — the builder reads it on top of the generated
    # defaults so an un-touched deal renders exactly as before.
    "doc_overrides": "TEXT",
    # First-touch tailored page (Phase 2/3): an unguessable per-opp share token
    # gates the public page (?k=<token>); the view counters are the engagement
    # signal that decides whether Option C is ever worth building (Phase 3).
    "share_token": "TEXT",
    "first_touch_views": "INTEGER",
    "first_touch_viewed_at": "TEXT",
}


# --------------------------------------------------------------------------- #
# Backend abstraction — SQLite (dev/tests) OR Postgres (production).
#
# Production runs on managed Postgres so the web service has NO persistent disk,
# which is what unlocks Render's zero-downtime (blue-green) deploys. The 100+
# query functions below are written once in SQLite dialect; a thin shim adapts
# them to Postgres so nothing else changes. Selected by CHORDENTIAL_DB: a path
# → SQLite, a postgres(ql):// URL → Postgres.
# --------------------------------------------------------------------------- #
def _is_pg_url(s: str) -> bool:
    return s.startswith("postgres://") or s.startswith("postgresql://")


def _pg_translate(sql: str) -> str:
    """SQLite dialect → Postgres for a single statement."""
    # DDL: SQLite autoincrement PK → Postgres SERIAL.
    sql = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "SERIAL PRIMARY KEY", sql, flags=re.I)
    sql = re.sub(r"\s+AUTOINCREMENT\b", "", sql, flags=re.I)
    # Functions. Two-arg scalar MAX/MIN (a comma inside, no nested parens) are
    # GREATEST/LEAST in Postgres; the no-comma aggregate MAX(col)/MIN(col) is left alone.
    sql = re.sub(r"\bMAX\(([^()]*,[^()]*)\)", r"GREATEST(\1)", sql, flags=re.I)
    sql = re.sub(r"\bMIN\(([^()]*,[^()]*)\)", r"LEAST(\1)", sql, flags=re.I)
    sql = re.sub(r"\bIFNULL\s*\(", "COALESCE(", sql, flags=re.I)
    sql = re.sub(r"\bGROUP_CONCAT\s*\(\s*(DISTINCT\s+)?(.+?)\s*\)",
                 lambda m: f"string_agg({m.group(1) or ''}{m.group(2)}, ',')", sql, flags=re.I)
    # Schema introspection used by _ensure_schema.
    sql = re.sub(r"PRAGMA\s+table_info\s*\(\s*(\w+)\s*\)",
                 r"SELECT column_name AS name FROM information_schema.columns WHERE table_name = '\1'",
                 sql, flags=re.I)
    # Placeholders (queries use SQLite '?'; no '?' appears in string literals here).
    sql = sql.replace("?", "%s")
    return sql


class _PgRow:
    """sqlite3.Row-compatible: supports row["col"] AND row[0], keys(), get()."""
    __slots__ = ("_v", "_m")

    def __init__(self, cols, values):
        self._v = values
        self._m = {c: i for i, c in enumerate(cols)}

    def __getitem__(self, k):
        return self._v[self._m[k]] if isinstance(k, str) else self._v[k]

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return len(self._v)

    def keys(self):
        return list(self._m.keys())

    def get(self, k, default=None):
        i = self._m.get(k)
        return self._v[i] if i is not None else default

    def __contains__(self, k):
        return k in self._m


def _pg_row_factory(cur):
    cols = [d.name for d in (cur.description or [])]
    return lambda values: _PgRow(cols, values)


class _PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    @property
    def rowcount(self):
        return self._cur.rowcount


class _PgConn:
    """Adapts a psycopg connection to the sqlite3.Connection API the app uses."""

    # Tables whose PK column is `id` — an INSERT into one needs `RETURNING id` so
    # the shim can expose `cursor.lastrowid` (psycopg has none). Derived once from
    # the live catalog (covers tables created in _SCHEMA *and* _ensure_schema).
    _id_tables_cache = None

    def __init__(self, conn):
        self._conn = conn

    def _id_tables(self):
        if _PgConn._id_tables_cache is None:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT table_name FROM information_schema.columns "
                "WHERE column_name = 'id' AND table_schema = 'public' "
                "AND data_type IN ('integer', 'bigint')"
            )
            _PgConn._id_tables_cache = {r[0].lower() for r in cur.fetchall()}
        return _PgConn._id_tables_cache

    def execute(self, sql: str, params=()):
        q = _pg_translate(sql)
        add_id = False
        head = q.lstrip()[:6].upper()
        if head == "INSERT" and "RETURNING" not in q.upper() and "ON CONFLICT" not in q.upper():
            m = re.match(r"\s*INSERT\s+INTO\s+\"?(\w+)\"?", q, re.I)
            if m and m.group(1).lower() in self._id_tables():
                q = q.rstrip().rstrip(";") + " RETURNING id"
                add_id = True
        cur = self._conn.cursor()
        cur.execute(q, tuple(params) if params else None)
        last = None
        if add_id:
            row = cur.fetchone()
            last = row[0] if row is not None else None
        return _PgCursor(cur, last)

    def executescript(self, sql: str):
        # Strip `-- …` line comments first: a ';' inside a comment would otherwise
        # break the statement split. (String literals here contain no ';'.)
        no_comments = re.sub(r"--[^\n]*", "", sql)
        cur = self._conn.cursor()
        for stmt in _pg_translate(no_comments).split(";"):
            if stmt.strip():
                cur.execute(stmt)

    def executemany(self, sql: str, seq):
        self._conn.cursor().executemany(_pg_translate(sql), [tuple(s) for s in seq])

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self._conn.commit() if exc_type is None else self._conn.rollback()
        return False


def connect(db_path: str = DEFAULT_DB_PATH):
    if _is_pg_url(db_path):
        import psycopg  # lazy: only production/Postgres needs the driver
        url = db_path.replace("postgres://", "postgresql://", 1)
        return _PgConn(psycopg.connect(url, autocommit=False, row_factory=_pg_row_factory))
    # SQLite (dev + tests). Ensure the parent dir exists for a mounted-disk path.
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # The background auto-fetcher writes from a worker thread while request
    # handlers also write; wait out brief lock contention instead of erroring.
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    _ensure_schema(conn)
    conn.commit()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Idempotently bring an older database up to the current schema.

    Fresh DBs already have everything from ``_SCHEMA``; this only matters for a
    ``chordential.db`` created before the Outreach layer existed — it adds the
    missing columns (and the events table) without touching existing data.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(opportunities)")}
    for name, decl in _OUTREACH_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            created_at TEXT, channel TEXT, direction TEXT, note TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS talent (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT, disciplines TEXT,
            credits TEXT DEFAULT '', location TEXT, demo_reel_url TEXT,
            review_status TEXT DEFAULT 'Pending',
            invite_status TEXT DEFAULT 'Prospect',
            notes TEXT DEFAULT '', created_at TEXT
        )"""
    )
    talent_cols = {r["name"] for r in conn.execute("PRAGMA table_info(talent)")}
    for name, decl in _TALENT_COLUMNS.items():
        if name not in talent_cols:
            conn.execute(f"ALTER TABLE talent ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER, client TEXT, need TEXT,
            budget_min REAL, budget_max REAL, deadline TEXT,
            status TEXT DEFAULT 'Active', roles TEXT, created_at TEXT,
            delivery_json TEXT, share_token TEXT
        )"""
    )
    project_cols = {r["name"] for r in conn.execute("PRAGMA table_info(projects)")}
    for name, decl in _PROJECT_COLUMNS.items():
        if name not in project_cols:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, role TEXT, talent_id INTEGER, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, title TEXT, status TEXT DEFAULT 'Pending',
            role TEXT, created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL, body TEXT,
            kind TEXT DEFAULT 'update', created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS companies (
            client TEXT PRIMARY KEY, website TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS brief_progress (
            opp_id INTEGER NOT NULL, step_key TEXT NOT NULL,
            done INTEGER DEFAULT 0, updated_at TEXT,
            PRIMARY KEY (opp_id, step_key)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS inbound_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
            contact_name TEXT, contact_email TEXT, company TEXT,
            project_type TEXT, description TEXT DEFAULT '', budget_text TEXT,
            timeline TEXT, source TEXT DEFAULT 'questionnaire',
            status TEXT DEFAULT 'New', linked_opp_id INTEGER, notes TEXT DEFAULT ''
        )"""
    )
    inbound_cols = {r["name"] for r in conn.execute("PRAGMA table_info(inbound_leads)")}
    for name, decl in _INBOUND_COLUMNS.items():
        if name not in inbound_cols:
            conn.execute(f"ALTER TABLE inbound_leads ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS crawl_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            label TEXT, query TEXT, url TEXT, source_key TEXT, rationale TEXT,
            status TEXT DEFAULT 'Proposed', result_count INTEGER,
            proposed_at TEXT, decided_at TEXT, fetched_at TEXT, notes TEXT DEFAULT '',
            last_outcome TEXT
        )"""
    )
    crawl_cols = {r["name"] for r in conn.execute("PRAGMA table_info(crawl_targets)")}
    if "last_outcome" not in crawl_cols:
        conn.execute("ALTER TABLE crawl_targets ADD COLUMN last_outcome TEXT")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS discovery_sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE, name TEXT, homepage TEXT, kind TEXT, category TEXT,
            recommended_by TEXT, rationale TEXT, status TEXT DEFAULT 'Suggested',
            added_at TEXT, decided_at TEXT, notes TEXT DEFAULT '', board_url TEXT,
            login_gated INTEGER DEFAULT 0
        )"""
    )
    site_cols = {r["name"] for r in conn.execute("PRAGMA table_info(discovery_sites)")}
    if "board_url" not in site_cols:
        conn.execute("ALTER TABLE discovery_sites ADD COLUMN board_url TEXT")
    if "login_gated" not in site_cols:
        conn.execute("ALTER TABLE discovery_sites ADD COLUMN login_gated INTEGER DEFAULT 0")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, source_weight INTEGER DEFAULT 5,
            external_ref TEXT, title TEXT, body TEXT DEFAULT '', url TEXT,
            budget_min REAL, budget_max REAL, score REAL, tier TEXT,
            posted_at TEXT, found_at TEXT, status TEXT DEFAULT 'New',
            linked_opp_id INTEGER, notes TEXT DEFAULT '',
            signal_type TEXT DEFAULT 'gig'
        )"""
    )
    sig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(signals)")}
    if "signal_type" not in sig_cols:
        conn.execute("ALTER TABLE signals ADD COLUMN signal_type TEXT DEFAULT 'gig'")
    if "contact_handle" not in sig_cols:   # poster's handle (e.g. reddit author)
        conn.execute("ALTER TABLE signals ADD COLUMN contact_handle TEXT")
    # Delivery OS IP1 (trust & coordination): attribute every review event to a
    # real email, not just a free-typed name. Older DBs predate the column.
    rc_cols = {r["name"] for r in conn.execute("PRAGMA table_info(review_comments)")}
    if "email" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN email TEXT")
    # Delivery OS IP2 (Frame.io review polish): per-comment resolve + one-level
    # reply. Older DBs predate both columns.
    if "resolved" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN resolved INTEGER DEFAULT 0")
    if "parent_id" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN parent_id INTEGER")
    # Verified-identity approval: an event posted from a verified reviewer's personal
    # invite link (?r=) is marked verified — its name + email came from the roster,
    # not free text. Older DBs predate the column.
    if "verified" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN verified INTEGER DEFAULT 0")
    # Web Push subscriptions — one row per browser/device that opted into native
    # phone alerts for the installed PWA. Deduped on the push endpoint.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint TEXT UNIQUE, p256dh TEXT, auth TEXT, created_at TEXT
        )"""
    )
    # Per-source subscription cost / notes (operator-entered) for the Source
    # Health table on the dashboard. Lead *activity* is derived live from signals.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS source_meta (
            source_key TEXT PRIMARY KEY, monthly_cost REAL,
            notes TEXT DEFAULT '', updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, opp_id INTEGER,
            created_at TEXT, status TEXT DEFAULT 'Draft', deposit_pct REAL,
            deposit_amount REAL, total_price REAL, balance_due REAL,
            line_items TEXT, terms TEXT, notes TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
            proposal_id INTEGER, created_at TEXT, kind TEXT,
            status TEXT DEFAULT 'Draft', amount REAL, note TEXT DEFAULT '',
            external_ref TEXT, paid_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS custom_chips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family TEXT, label TEXT, sentence TEXT, created_at TEXT
        )"""
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Mapping between Opportunity <-> row
# --------------------------------------------------------------------------- #
def _enum(value, enum_cls, default):
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def opportunity_from_row(row: sqlite3.Row) -> Opportunity:
    return Opportunity(
        client=row["client"],
        need=row["need"],
        description=row["description"] or "",
        source=row["source"] or "unknown",
        source_tier=row["source_tier"],
        url=row["url"],
        buyer_type=_enum(row["buyer_type"], BuyerType, BuyerType.UNKNOWN),
        music_requirement=_enum(
            row["music_requirement"], MusicRequirement, MusicRequirement.IMPLIED
        ),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        location=row["location"],
        tags=json.loads(row["tags"]) if row["tags"] else [],
        buyer_value=_enum(row["buyer_value"], BuyerValue, BuyerValue.UNKNOWN),
        marquee=bool(row["marquee"]),
    )


def insert_opportunity(conn: sqlite3.Connection, opp: Opportunity) -> int:
    """Evaluate (qualify + score + strategic value) and store. Returns row id."""
    q, s = evaluate(opp)
    sv = assess_strategic_value(opp)
    cur = conn.execute(
        """
        INSERT INTO opportunities (
            client, need, description, source, source_tier, url, buyer_type,
            music_requirement, budget_min, budget_max, location, tags, created_at,
            qualified, discipline, alignment, action, confidence, needs_review,
            score, tier, win_probability, buyer_value, marquee, strategic_value,
            strategic_tier, status, outcome_value, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            opp.client, opp.need, opp.description, opp.source, opp.source_tier,
            opp.url, opp.buyer_type.value, opp.music_requirement.value,
            opp.budget_min, opp.budget_max, opp.location, json.dumps(opp.tags),
            datetime.now(timezone.utc).isoformat(),
            int(q.qualified), q.discipline.value, q.alignment_pct,
            q.recommended_action.value, q.confidence.value, int(q.needs_human_review),
            s.score, s.tier.value, s.win_probability.value,
            opp.buyer_value.value, int(opp.marquee), sv.score, sv.tier,
            "Passed" if not q.qualified else "New", None, "",
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_strategic_inputs(
    conn: sqlite3.Connection, opp_id: int, buyer_value: str, marquee: bool
) -> None:
    """Persist human-set buyer value + marquee flag and recompute strategic value."""
    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    if row is None:
        return
    opp = opportunity_from_row(row)
    opp.buyer_value = _enum(buyer_value, BuyerValue, BuyerValue.UNKNOWN)
    opp.marquee = bool(marquee)
    sv = assess_strategic_value(opp)
    conn.execute(
        """UPDATE opportunities
           SET buyer_value = ?, marquee = ?, strategic_value = ?, strategic_tier = ?
           WHERE id = ?""",
        (opp.buyer_value.value, int(opp.marquee), sv.score, sv.tier, opp_id),
    )
    conn.commit()


def opportunity_exists(conn: sqlite3.Connection, client: str, need: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM opportunities WHERE client=? AND need=? LIMIT 1",
        (client, need),
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #
def list_opportunities(
    conn: sqlite3.Connection,
    q: Optional[str] = None,
    action: Optional[str] = None,
    tier: Optional[str] = None,
    discipline: Optional[str] = None,
    buyer_type: Optional[str] = None,
    status: Optional[str] = None,
    min_alignment: Optional[float] = None,
    order_by: str = "alignment",
) -> List[sqlite3.Row]:
    clauses: List[str] = []
    params: List = []
    if q:
        clauses.append("(client LIKE ? OR need LIKE ? OR description LIKE ? OR location LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like, like]
    if action:
        clauses.append("action = ?")
        params.append(action)
    if tier:
        clauses.append("tier = ?")
        params.append(tier)
    if discipline:
        clauses.append("discipline = ?")
        params.append(discipline)
    if buyer_type:
        clauses.append("buyer_type = ?")
        params.append(buyer_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if min_alignment is not None:
        clauses.append("alignment >= ?")
        params.append(min_alignment)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order_cols = {
        "alignment": "alignment DESC",
        "score": "score DESC",
        "strategic": "strategic_value DESC",
        "budget": "COALESCE(budget_max, budget_min, 0) DESC",
        "client": "client ASC",
        "created": "created_at DESC",
    }
    order = order_cols.get(order_by, "alignment DESC")
    sql = f"SELECT * FROM opportunities{where} ORDER BY {order}"
    return conn.execute(sql, params).fetchall()


def get_opportunity(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE id = ?", (opp_id,)
    ).fetchone()


def update_status(
    conn: sqlite3.Connection,
    opp_id: int,
    status: str,
    outcome_value: Optional[float] = None,
) -> None:
    if status not in PIPELINE_STATES:
        raise ValueError(f"Unknown status {status!r}")
    conn.execute(
        "UPDATE opportunities SET status = ?, outcome_value = ? WHERE id = ?",
        (status, outcome_value, opp_id),
    )
    conn.commit()


def update_notes(conn: sqlite3.Connection, opp_id: int, notes: str) -> None:
    conn.execute("UPDATE opportunities SET notes = ? WHERE id = ?", (notes, opp_id))
    conn.commit()


# --------------------------------------------------------------------------- #
# First-touch tailored page — per-opp share token + engagement measurement
# --------------------------------------------------------------------------- #
def ensure_share_token(conn: sqlite3.Connection, opp_id: int) -> Optional[str]:
    """Return the opp's unguessable share token, minting one on first use.

    The token gates the public first-touch page (``?k=<token>``) so the page is
    shareable with an external recipient but not enumerable. Returns ``None`` only
    when the opportunity doesn't exist."""
    row = conn.execute(
        "SELECT share_token FROM opportunities WHERE id = ?", (opp_id,)
    ).fetchone()
    if row is None:
        return None
    existing = row["share_token"]
    if existing and str(existing).strip():
        return existing
    token = secrets.token_urlsafe(9)
    conn.execute(
        "UPDATE opportunities SET share_token = ? WHERE id = ?", (token, opp_id)
    )
    conn.commit()
    return token


def record_first_touch_view(conn: sqlite3.Connection, opp_id: int) -> None:
    """Increment the first-touch page view counter and stamp the last-viewed time.

    Called only when the page loads with a VALID token — this is the Phase 3
    engagement signal surfaced on the outreach view (does the buyer click?)."""
    conn.execute(
        """UPDATE opportunities
           SET first_touch_views = COALESCE(first_touch_views, 0) + 1,
               first_touch_viewed_at = ?
           WHERE id = ?""",
        (datetime.now(timezone.utc).isoformat(), opp_id),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Editable client-document — per-deal overrides + reusable "My chips"
# --------------------------------------------------------------------------- #
def get_doc_overrides(conn: sqlite3.Connection, opp_id: int) -> dict:
    """The per-deal client-document overrides as a dict ({} when none/blank).

    Keys (all optional): ``client``, ``understanding``, ``delivery_template``,
    ``delivery_assumptions``, ``support_chips`` (section → list of
    {label, sentence}), ``relevant_links`` (list of {label, url}),
    ``relevant_uploads`` (list of {label, url, filename}),
    ``deliverable_overrides`` (optional list replacing generated deliverables)."""
    row = conn.execute(
        "SELECT doc_overrides FROM opportunities WHERE id = ?", (opp_id,)
    ).fetchone()
    if row is None:
        return {}
    raw = row["doc_overrides"]
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_doc_overrides(conn: sqlite3.Connection, opp_id: int, overrides: dict) -> None:
    """Write the full overrides dict back as JSON (empty dict clears the column)."""
    blob = json.dumps(overrides) if overrides else None
    conn.execute(
        "UPDATE opportunities SET doc_overrides = ? WHERE id = ?", (blob, opp_id)
    )
    conn.commit()


def update_doc_override(conn: sqlite3.Connection, opp_id: int, key: str, value) -> dict:
    """Merge a single override key. A blank/None value *removes* the key so the
    field falls back to the generated default ("reset to generated"). Returns the
    updated overrides dict."""
    overrides = get_doc_overrides(conn, opp_id)
    blank = value is None or (isinstance(value, str) and not value.strip())
    if blank:
        overrides.pop(key, None)
    else:
        overrides[key] = value
    save_doc_overrides(conn, opp_id, overrides)
    return overrides


def list_custom_chips(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """All saved "My chips" (reusable across every deal), newest first."""
    return conn.execute(
        "SELECT * FROM custom_chips ORDER BY created_at DESC, id DESC"
    ).fetchall()


def add_custom_chip(
    conn: sqlite3.Connection, family: str, label: str, sentence: str
) -> Optional[int]:
    """Save a reusable custom chip. Requires a label + sentence; returns its id."""
    label = (label or "").strip()
    sentence = (sentence or "").strip()
    if not label or not sentence:
        return None
    cur = conn.execute(
        """INSERT INTO custom_chips (family, label, sentence, created_at)
           VALUES (?,?,?,?)""",
        ((family or "").strip() or None, label, sentence,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# Outreach-to-win
# --------------------------------------------------------------------------- #
def update_outreach(
    conn: sqlite3.Connection,
    opp_id: int,
    contact_name: str = "",
    contact_email: str = "",
    contact_role: str = "",
    next_action: str = "",
    next_action_due: str = "",
    contact_linkedin: str = "",
    contact_phone: str = "",
) -> None:
    """Persist the human-managed outreach fields (contact + the single next action).

    ``contact_linkedin`` is normalized to a working URL (a bare handle/host gains
    an ``https://`` scheme) so the profile link is always clickable.
    """
    conn.execute(
        """UPDATE opportunities
           SET contact_name = ?, contact_email = ?, contact_phone = ?, contact_role = ?,
               contact_linkedin = ?, next_action = ?, next_action_due = ?
           WHERE id = ?""",
        (
            contact_name or None, contact_email or None, contact_phone or None,
            contact_role or None,
            _normalize_url(contact_linkedin), next_action or None,
            next_action_due or None, opp_id,
        ),
    )
    conn.commit()


def set_opp_contact(
    conn: sqlite3.Connection,
    opp_id: int,
    contact_name: str = "",
    contact_email: str = "",
    contact_phone: str = "",
    contact_linkedin: str = "",
) -> None:
    """Best-effort: stamp contact fields onto an opportunity (carried over on promote).

    Only overwrites a column when a non-empty value is supplied, so this never
    clears contact details a human has already entered.
    """
    sets, params = [], []
    if contact_name:
        sets.append("contact_name = ?"); params.append(contact_name)
    if contact_email:
        sets.append("contact_email = ?"); params.append(contact_email)
    if contact_phone:
        sets.append("contact_phone = ?"); params.append(contact_phone)
    if contact_linkedin:
        sets.append("contact_linkedin = ?"); params.append(_normalize_url(contact_linkedin))
    if not sets:
        return
    params.append(opp_id)
    conn.execute(
        f"UPDATE opportunities SET {', '.join(sets)} WHERE id = ?", params
    )
    conn.commit()


def mark_delivery_doc_sent(conn: sqlite3.Connection, opp_id: int) -> None:
    """Stamp the 'Delivery doc sent' milestone with the current UTC time."""
    conn.execute(
        "UPDATE opportunities SET delivery_doc_sent_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), opp_id),
    )
    conn.commit()


def set_contact_handle(conn: sqlite3.Connection, opp_id: int, handle: str) -> None:
    """Stamp the poster's handle (e.g. reddit author) carried over on promote."""
    if not handle:
        return
    conn.execute(
        "UPDATE opportunities SET contact_handle = ? WHERE id = ?", (handle, opp_id))
    conn.commit()


def add_outreach_event(
    conn: sqlite3.Connection,
    opp_id: int,
    channel: str,
    direction: str,
    note: str,
) -> None:
    """Append one logged touch and stamp ``last_contacted`` on the opportunity."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO outreach_events (opp_id, created_at, channel, direction, note)
           VALUES (?,?,?,?,?)""",
        (opp_id, now, channel, direction, note),
    )
    conn.execute(
        "UPDATE opportunities SET last_contacted = ? WHERE id = ?", (now, opp_id)
    )
    conn.commit()


def list_outreach_events(conn: sqlite3.Connection, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM outreach_events WHERE opp_id = ? ORDER BY created_at DESC",
        (opp_id,),
    ).fetchall()


def followups_due(conn: sqlite3.Connection, limit: int = 8) -> List[sqlite3.Row]:
    """Open opportunities whose next action is due on/before today (the follow-up queue)."""
    today = date.today().isoformat()
    return conn.execute(
        """SELECT * FROM opportunities
           WHERE next_action_due IS NOT NULL AND next_action_due != ''
             AND next_action_due <= ?
             AND status NOT IN ('Won','Lost','Passed')
           ORDER BY next_action_due ASC
           LIMIT ?""",
        (today, limit),
    ).fetchall()


def buyer_opportunities(conn: sqlite3.Connection, client: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM opportunities WHERE client = ? ORDER BY created_at DESC",
        (client,),
    ).fetchall()


def all_buyers(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """One aggregated row per buyer for the Buyer Graph directory."""
    return conn.execute(
        """
        SELECT
            o.client AS client,
            MIN(o.buyer_type) AS buyer_type,
            COUNT(*) AS opps,
            SUM(o.qualified) AS qualified,
            SUM(CASE WHEN o.status = 'Won' THEN 1 ELSE 0 END) AS won,
            SUM(CASE WHEN o.status = 'Lost' THEN 1 ELSE 0 END) AS lost,
            SUM(CASE WHEN o.status IN ('Pursuing','Submitted') THEN 1 ELSE 0 END) AS open_pursuits,
            MAX(o.strategic_value) AS strategic_value,
            AVG(o.alignment) AS avg_alignment,
            MAX(o.last_contacted) AS last_contacted,
            (SELECT COUNT(*) FROM outreach_events e
                JOIN opportunities oi ON e.opp_id = oi.id
                WHERE oi.client = o.client) AS touches
        FROM opportunities o
        GROUP BY o.client
        """
    ).fetchall()


def buyer_touch_summary(conn: sqlite3.Connection, client: str) -> sqlite3.Row:
    """Total logged outreach touches and the most recent timestamp for a buyer."""
    return conn.execute(
        """SELECT COUNT(*) AS touches, MAX(e.created_at) AS last_contacted
           FROM outreach_events e JOIN opportunities o ON e.opp_id = o.id
           WHERE o.client = ?""",
        (client,),
    ).fetchone()


# --------------------------------------------------------------------------- #
# Company-level metadata (website, …)
# --------------------------------------------------------------------------- #
def _normalize_url(raw: Optional[str]) -> Optional[str]:
    """Tidy a hand-entered website into a linkable URL (None when blank).

    Adds an ``https://`` scheme when the user typed a bare host so the stored
    value is always a working link.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    return raw


def get_company(conn: sqlite3.Connection, client: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM companies WHERE client = ?", (client,)
    ).fetchone()


def company_website(conn: sqlite3.Connection, client: str) -> Optional[str]:
    row = get_company(conn, client)
    return row["website"] if row else None


def set_company_website(conn: sqlite3.Connection, client: str, website: str) -> None:
    """Upsert the company's website (normalized; blank clears it)."""
    conn.execute(
        """INSERT INTO companies (client, website, updated_at) VALUES (?,?,?)
           ON CONFLICT(client) DO UPDATE SET
               website = excluded.website, updated_at = excluded.updated_at""",
        (client, _normalize_url(website), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Pursuit-brief checklist progress
# --------------------------------------------------------------------------- #
def brief_done_keys(conn: sqlite3.Connection, opp_id: int) -> set:
    """The set of checklist step keys ticked off for an opportunity."""
    rows = conn.execute(
        "SELECT step_key FROM brief_progress WHERE opp_id = ? AND done = 1", (opp_id,)
    ).fetchall()
    return {r["step_key"] for r in rows}


def set_brief_step(
    conn: sqlite3.Connection, opp_id: int, step_key: str, done: bool
) -> None:
    """Toggle one checklist step done/undone (upsert)."""
    conn.execute(
        """INSERT INTO brief_progress (opp_id, step_key, done, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(opp_id, step_key) DO UPDATE SET
               done = excluded.done, updated_at = excluded.updated_at""",
        (opp_id, step_key, 1 if done else 0, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def buyer_contacts(conn: sqlite3.Connection, client: str) -> List[sqlite3.Row]:
    """Distinct known contacts captured across a buyer's opportunities."""
    return conn.execute(
        """SELECT DISTINCT contact_name, contact_email, contact_role
           FROM opportunities
           WHERE client = ?
             AND (contact_name IS NOT NULL OR contact_email IS NOT NULL)
           ORDER BY contact_name""",
        (client,),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Inbound leads (front-of-house) — a review queue, not the opportunity pipeline
# --------------------------------------------------------------------------- #
def insert_inbound_lead(
    conn: sqlite3.Connection,
    contact_name: str,
    contact_email: str = "",
    company: str = "",
    project_type: str = "",
    description: str = "",
    budget_text: str = "",
    timeline: str = "",
    source: str = "questionnaire",
    shown_price_low: Optional[float] = None,
    shown_price_high: Optional[float] = None,
    phone: str = "",
    contact_linkedin: str = "",
) -> int:
    """Store a public submission as a New lead. No evaluation happens here —
    a human qualifies and promotes it later (precision-bias rule).

    ``shown_price_*`` records the indicative band the client was shown (from the
    estimator) so the eventual win/loss can be compared against what we quoted.
    """
    cur = conn.execute(
        """INSERT INTO inbound_leads
           (created_at, contact_name, contact_email, phone, contact_linkedin,
            company, project_type, description, budget_text, timeline, source,
            status, shown_price_low, shown_price_high)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,'New',?,?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            contact_name or None, contact_email or None, phone or None,
            contact_linkedin or None, company or None,
            project_type or None, description or "", budget_text or None,
            timeline or None, source, shown_price_low, shown_price_high,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def inbound_lead_exists(
    conn: sqlite3.Connection, company: str, project_type: str, source: str
) -> bool:
    """Dedupe discovered leads so a recurring crawl re-scan of the same board
    doesn't pile up duplicate leads (matched on source + company + project_type)."""
    row = conn.execute(
        """SELECT 1 FROM inbound_leads
           WHERE source = ? AND IFNULL(company, '') = ? AND IFNULL(project_type, '') = ?
           LIMIT 1""",
        (source, company or "", project_type or ""),
    ).fetchone()
    return row is not None


def list_inbound_leads(
    conn: sqlite3.Connection, status: Optional[str] = None
) -> List[sqlite3.Row]:
    """Leads for the review queue. Open leads (New/Reviewed) surface first."""
    clause = " WHERE status = ?" if status else ""
    params = (status,) if status else ()
    return conn.execute(
        f"""SELECT * FROM inbound_leads{clause}
            ORDER BY
              CASE status WHEN 'New' THEN 0 WHEN 'Reviewed' THEN 1
                          WHEN 'Qualified' THEN 2 ELSE 3 END,
              created_at DESC""",
        params,
    ).fetchall()


def _lead_source_chip(source: Optional[str]) -> str:
    """Short, human source label for the unified Incoming queue."""
    s = (source or "").strip().lower()
    if s == "crawl":
        return "Crawler"
    if s in ("email", "paste"):
        return "Email"
    # questionnaire, book_call, and anything else from the public site
    return "Website"


def list_incoming(conn: sqlite3.Connection) -> List[Dict]:
    """Unified read-model over the two intake stores (a UNION at the view layer,
    NOT a table merge): OPEN inbound leads (New/Reviewed) + open signals
    (New/Reviewed, gigs only — indicators excluded). Each row is normalized into
    one plain dict so the Incoming queue renders both alike. Newest first."""
    out: List[Dict] = []

    lead_rows = conn.execute(
        "SELECT * FROM inbound_leads WHERE status IN ('New','Reviewed') "
        "ORDER BY created_at DESC"
    ).fetchall()
    for l in lead_rows:
        title = (l["project_type"] or l["company"] or l["contact_name"] or "Inbound lead")
        sub_bits = []
        if l["company"]:
            sub_bits.append(l["company"])
        if l["contact_email"]:
            sub_bits.append(l["contact_email"])
        if "phone" in l.keys() and l["phone"]:
            sub_bits.append(l["phone"])
        out.append({
            "kind": "lead",
            "id": l["id"],
            "source_chip": _lead_source_chip(l["source"]),
            "title": title,
            "subtitle": " · ".join(sub_bits),
            "contact": l["contact_email"] or l["contact_name"] or "",
            "created_at": l["created_at"],
            "status": l["status"],
            "score": None,
            "tier": None,
            "url": "/leads",
            "promote_url": f"/leads/{l['id']}/promote",
            "dismiss_url": f"/leads/{l['id']}/status",
        })

    sig_rows = conn.execute(
        "SELECT * FROM signals WHERE status IN ('New','Reviewed') "
        "AND IFNULL(signal_type, 'gig') != 'indicator' "
        "ORDER BY found_at DESC"
    ).fetchall()
    for s in sig_rows:
        body = (s["body"] or "").strip().replace("\n", " ")
        snippet = body[:120] + ("…" if len(body) > 120 else "")
        if not snippet and s["budget_min"]:
            snippet = f"${int(s['budget_min'])}"
            if s["budget_max"]:
                snippet += f"–${int(s['budget_max'])}"
        out.append({
            "kind": "signal",
            "id": s["id"],
            "source_chip": "Signal",
            "title": s["title"] or "Detected opportunity",
            "subtitle": snippet,
            "contact": (s["contact_handle"] if "contact_handle" in s.keys() else None) or "",
            "created_at": s["found_at"],
            "status": s["status"],
            "score": s["score"],
            "tier": s["tier"],
            "url": "/signals",
            "promote_url": f"/signals/{s['id']}/promote",
            "dismiss_url": f"/signals/{s['id']}/status",
        })

    out.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return out


def incoming_unactioned_count(conn: sqlite3.Connection) -> int:
    """The unified nav badge: inbound 'New' leads + 'New' signal gigs (indicators
    excluded). 'Needs me' = everything that just arrived and hasn't been touched."""
    leads = conn.execute(
        "SELECT COUNT(*) FROM inbound_leads WHERE status = 'New'"
    ).fetchone()[0]
    return leads + new_signal_count(conn)


def get_inbound_lead(conn: sqlite3.Connection, lead_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM inbound_leads WHERE id = ?", (lead_id,)
    ).fetchone()


def update_inbound_lead_status(
    conn: sqlite3.Connection, lead_id: int, status: str
) -> None:
    if status not in INBOUND_STATES:
        raise ValueError(f"Unknown inbound status {status!r}")
    conn.execute(
        "UPDATE inbound_leads SET status = ? WHERE id = ?", (status, lead_id)
    )
    conn.commit()


def link_inbound_to_opp(
    conn: sqlite3.Connection, lead_id: int, opp_id: int
) -> None:
    """Mark a lead promoted: link it to the created opportunity and qualify it."""
    conn.execute(
        "UPDATE inbound_leads SET linked_opp_id = ?, status = 'Qualified' WHERE id = ?",
        (opp_id, lead_id),
    )
    conn.commit()


def inbound_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Per-status counts for the review-queue badges (always includes 'open')."""
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM inbound_leads GROUP BY status"
    ).fetchall()
    counts = {s: 0 for s in INBOUND_STATES}
    for r in rows:
        counts[r["status"]] = r["n"]
    counts["open"] = counts["New"] + counts["Reviewed"]
    counts["total"] = sum(r["n"] for r in rows)
    return counts


# --------------------------------------------------------------------------- #
# Discovery crawler — human-gated targets ("machine proposes, Jon disposes")
# --------------------------------------------------------------------------- #
CRAWL_KINDS = ["talent", "opportunity"]
CRAWL_STATES = ["Proposed", "Approved", "Fetched", "Dismissed"]

# Discovery sites (the curated industry catalog) approval lifecycle. Established +
# Approved are active (crawlable); Suggested awaits Jon; Rejected is parked.
SITE_STATES = ["Established", "Suggested", "Approved", "Rejected"]
ACTIVE_SITE_STATES = ("Established", "Approved")


def upsert_discovery_site(
    conn: sqlite3.Connection,
    key: str,
    name: str,
    homepage: str,
    kind: str,
    category: str,
    recommended_by: str,
    rationale: str,
    status: str,
    board_url: Optional[str] = None,
    login_gated: bool = False,
) -> None:
    """Insert a site if new; never overwrite Jon's status decision on an existing
    one (re-seeding preserves approvals/rejections). The ``login_gated`` flag IS
    synced (sticky-True) — it's a catalog/detection fact, not a user decision, so
    a source known/found to need a login moves to manual-assist and stays there.
    ``board_url`` is set for Jon-added custom sites (catalog sites build URLs)."""
    conn.execute(
        """INSERT INTO discovery_sites
           (key, name, homepage, kind, category, recommended_by, rationale,
            status, added_at, board_url, login_gated)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET
             login_gated = MAX(discovery_sites.login_gated, excluded.login_gated)""",
        (
            key, name, homepage, kind, category, recommended_by, rationale,
            status, datetime.now(timezone.utc).isoformat(), board_url,
            1 if login_gated else 0,
        ),
    )
    conn.commit()


SIGNAL_STATES = ["New", "Reviewed", "Promoted", "Dismissed"]


def signal_exists(conn: sqlite3.Connection, external_ref: str) -> bool:
    if not external_ref:
        return False
    return conn.execute(
        "SELECT 1 FROM signals WHERE external_ref = ? LIMIT 1", (external_ref,)
    ).fetchone() is not None


def insert_signal(
    conn: sqlite3.Connection, *, source: str, source_weight: int, title: str,
    body: str = "", url: str = "", external_ref: str = "",
    budget_min: Optional[float] = None, budget_max: Optional[float] = None,
    score: Optional[float] = None, tier: Optional[str] = None,
    posted_at: Optional[str] = None, signal_type: str = "gig",
    contact_handle: Optional[str] = None,
) -> Optional[int]:
    """Record a detected signal (the tape). Deduped on external_ref. found_at is
    stamped now; posted_at is when the opportunity went live (feed value or now).
    signal_type is 'gig' (a live posting) or 'indicator' (music-spend-incoming).
    contact_handle is the poster's handle (e.g. reddit author) when known."""
    if signal_exists(conn, external_ref):
        return None
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO signals
           (source, source_weight, external_ref, title, body, url,
            budget_min, budget_max, score, tier, posted_at, found_at, status,
            signal_type, contact_handle)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'New',?,?)""",
        (source, source_weight, external_ref, title, body, url,
         budget_min, budget_max, score, tier, posted_at or now, now,
         signal_type, contact_handle),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_signals(
    conn: sqlite3.Connection, status: Optional[str] = None
) -> List[sqlite3.Row]:
    """Open signals (New/Reviewed) by default — the live tape."""
    if status:
        return conn.execute("SELECT * FROM signals WHERE status = ?", (status,)).fetchall()
    return conn.execute(
        "SELECT * FROM signals WHERE status IN ('New','Reviewed')"
    ).fetchall()


def get_signal(conn: sqlite3.Connection, signal_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()


def new_signal_count(conn: sqlite3.Connection) -> int:
    """Count of New (unactioned) live gigs — drives the nav badge."""
    return conn.execute(
        "SELECT COUNT(*) FROM signals WHERE status = 'New' "
        "AND IFNULL(signal_type, 'gig') != 'indicator'"
    ).fetchone()[0]


# --------------------------------------------------------------------------- #
# Source Health — live lead activity per source + operator-entered cost.
# --------------------------------------------------------------------------- #
def source_activity(conn: sqlite3.Connection, since_iso: str) -> List[sqlite3.Row]:
    """Per raw-source: last lead time, total count, count since ``since_iso``.
    The caller buckets raw sources (reddit-forhire, mandy, …) into canonical
    sources."""
    return conn.execute(
        """SELECT source,
                  MAX(found_at)                                   AS last_found,
                  COUNT(*)                                        AS total,
                  SUM(CASE WHEN found_at >= ? THEN 1 ELSE 0 END)  AS recent
           FROM signals GROUP BY source""",
        (since_iso,),
    ).fetchall()


def get_source_costs(conn: sqlite3.Connection) -> Dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM source_meta").fetchall()
    return {r["source_key"]: r for r in rows}


def set_source_cost(
    conn: sqlite3.Connection, source_key: str,
    monthly_cost: Optional[float], notes: str = "",
) -> None:
    """Upsert an operator's monthly subscription cost (and notes) for a source."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO source_meta (source_key, monthly_cost, notes, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(source_key) DO UPDATE SET
             monthly_cost=excluded.monthly_cost, notes=excluded.notes,
             updated_at=excluded.updated_at""",
        (source_key, monthly_cost, notes, now),
    )
    conn.commit()


def insert_test_signal(conn: sqlite3.Connection, source_key: str, label: str) -> int:
    """Inject a clearly-marked test lead for a source so the Source Health table's
    'last lead' visibly updates — proves the per-source wiring end to end."""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO signals
           (source, source_weight, external_ref, title, body, url, score, tier,
            posted_at, found_at, status, signal_type, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,'New','gig','source-test')""",
        (source_key, 5, f"sourcetest:{source_key}:{now}",
         f"[TEST] lead from {label}", "Source Health wiring test.", "",
         50.0, "Watch", now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def clear_test_signals(conn: sqlite3.Connection) -> int:
    """Delete the [TEST] leads injected by the Source Health tester."""
    cur = conn.execute("DELETE FROM signals WHERE notes = 'source-test'")
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
# Web Push subscriptions — devices opted into native phone alerts (the PWA).
# --------------------------------------------------------------------------- #
def add_push_subscription(
    conn: sqlite3.Connection, *, endpoint: str, p256dh: str, auth: str
) -> None:
    """Store (or refresh) a browser push subscription, deduped on its endpoint."""
    if not endpoint:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at)
           VALUES (?,?,?,?)
           ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh,
               auth=excluded.auth""",
        (endpoint, p256dh, auth, now),
    )
    conn.commit()


def list_push_subscriptions(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT * FROM push_subscriptions").fetchall()


def delete_push_subscription(conn: sqlite3.Connection, endpoint: str) -> None:
    """Drop a subscription (called when the push service reports it expired/gone)."""
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()


def push_subscription_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


def set_signal_status(conn: sqlite3.Connection, signal_id: int, status: str) -> None:
    if status not in SIGNAL_STATES:
        raise ValueError(f"Unknown signal status {status!r}")
    conn.execute("UPDATE signals SET status = ? WHERE id = ?", (status, signal_id))
    conn.commit()


def link_signal_to_opp(conn: sqlite3.Connection, signal_id: int, opp_id: int) -> None:
    conn.execute(
        "UPDATE signals SET status = 'Promoted', linked_opp_id = ? WHERE id = ?",
        (opp_id, signal_id),
    )
    conn.commit()


def clear_signals(conn: sqlite3.Connection, only_open: bool = True) -> int:
    """Wipe the radar. By default only clears open (New/Reviewed) signals so
    promoted ones keep their link; pass only_open=False to delete everything."""
    if only_open:
        cur = conn.execute("DELETE FROM signals WHERE status IN ('New','Reviewed')")
    else:
        cur = conn.execute("DELETE FROM signals")
    conn.commit()
    return cur.rowcount


def remove_discovery_site(conn: sqlite3.Connection, key: str) -> None:
    """Delete a source and its crawl targets (used to retire catalog sources)."""
    conn.execute("DELETE FROM crawl_targets WHERE source_key = ?", (key,))
    conn.execute("DELETE FROM discovery_sites WHERE key = ?", (key,))
    conn.commit()


def get_discovery_site_by_key(
    conn: sqlite3.Connection, key: str
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM discovery_sites WHERE key = ?", (key,)
    ).fetchone()


def list_discovery_sites(
    conn: sqlite3.Connection,
    kind: Optional[str] = None,
    status: Optional[str] = None,
) -> List[sqlite3.Row]:
    clauses, params = [], []
    if kind:
        clauses.append("(kind = ? OR kind = 'both')")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"""SELECT * FROM discovery_sites{where}
            ORDER BY
              CASE status WHEN 'Suggested' THEN 0 WHEN 'Established' THEN 1
                          WHEN 'Approved' THEN 2 ELSE 3 END,
              name ASC""",
        params,
    ).fetchall()


def get_discovery_site(conn: sqlite3.Connection, site_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM discovery_sites WHERE id = ?", (site_id,)
    ).fetchone()


def update_discovery_site_status(
    conn: sqlite3.Connection, site_id: int, status: str
) -> None:
    if status not in SITE_STATES:
        raise ValueError(f"Unknown site status {status!r}")
    conn.execute(
        "UPDATE discovery_sites SET status = ?, decided_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), site_id),
    )
    conn.commit()


def active_discovery_site_keys(conn: sqlite3.Connection, gen_kind: str) -> List[str]:
    """Site keys eligible to propose targets for a kind — active sites only."""
    rows = conn.execute(
        f"""SELECT key FROM discovery_sites
            WHERE status IN ({','.join('?' * len(ACTIVE_SITE_STATES))})
              AND (kind = ? OR kind = 'both')""",
        (*ACTIVE_SITE_STATES, gen_kind),
    ).fetchall()
    return [r["key"] for r in rows]


def discovery_site_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM discovery_sites GROUP BY status"
    ).fetchall()
    counts = {s: 0 for s in SITE_STATES}
    for r in rows:
        counts[r["status"]] = r["n"]
    counts["active"] = counts["Established"] + counts["Approved"]
    counts["total"] = sum(r["n"] for r in rows)
    return counts


def discovery_site_activity(conn: sqlite3.Connection) -> Dict[str, dict]:
    """Per-source fetch activity, aggregated from its crawl targets (keyed by
    source_key). Powers the Discovery console's "Activity" column: when a source
    was last fetched, how many targets have been fetched, and total leads found."""
    rows = conn.execute(
        """SELECT source_key,
                  MAX(fetched_at) AS last_fetched,
                  COALESCE(SUM(result_count), 0) AS found,
                  SUM(CASE WHEN status = 'Fetched' THEN 1 ELSE 0 END) AS fetched_targets,
                  SUM(CASE WHEN status = 'Approved' THEN 1 ELSE 0 END) AS approved_targets,
                  (SELECT t2.last_outcome FROM crawl_targets t2
                    WHERE t2.source_key = t.source_key AND t2.fetched_at IS NOT NULL
                    ORDER BY t2.fetched_at DESC LIMIT 1) AS last_outcome
           FROM crawl_targets t
           WHERE source_key IS NOT NULL AND source_key != ''
           GROUP BY source_key"""
    ).fetchall()
    return {
        r["source_key"]: {
            "last_fetched": r["last_fetched"],
            "found": r["found"] or 0,
            "fetched_targets": r["fetched_targets"] or 0,
            "approved_targets": r["approved_targets"] or 0,
            "last_outcome": r["last_outcome"],
        }
        for r in rows
    }


def _attribution_source_label(source: Optional[str]) -> str:
    """Normalize a raw inbound-lead source into a channel label for attribution.

    questionnaire/book_call → "Website"; crawl → "Crawler";
    email/paste → "Email"; anything else → the raw source string."""
    s = (source or "").strip().lower()
    if s in ("questionnaire", "book_call"):
        return "Website"
    if s == "crawl":
        return "Crawler"
    if s in ("email", "paste"):
        return "Email"
    return (source or "").strip() or "Other"


def source_attribution(conn: sqlite3.Connection) -> List[Dict]:
    """Source→won rollup so the founder can judge which channel earns its keep.

    Per normalized channel: ``leads_in`` (everything that came in), ``promoted``
    (linked to an opportunity), and ``won`` (linked opp now status='Won').
    Inbound leads are bucketed by :func:`_attribution_source_label`; every signal
    rolls up into one "Signal" bucket. Merged and sorted by won desc, leads_in desc."""
    buckets: Dict[str, Dict] = {}

    def _bump(label: str, promoted: bool, won: bool) -> None:
        b = buckets.setdefault(
            label, {"source": label, "leads_in": 0, "promoted": 0, "won": 0}
        )
        b["leads_in"] += 1
        if promoted:
            b["promoted"] += 1
        if won:
            b["won"] += 1

    lead_rows = conn.execute(
        """SELECT l.source AS source, l.linked_opp_id AS opp_id, o.status AS opp_status
           FROM inbound_leads l
           LEFT JOIN opportunities o ON o.id = l.linked_opp_id"""
    ).fetchall()
    for r in lead_rows:
        promoted = r["opp_id"] is not None
        won = promoted and (r["opp_status"] == "Won")
        _bump(_attribution_source_label(r["source"]), promoted, won)

    sig_rows = conn.execute(
        """SELECT s.linked_opp_id AS opp_id, o.status AS opp_status
           FROM signals s
           LEFT JOIN opportunities o ON o.id = s.linked_opp_id"""
    ).fetchall()
    for r in sig_rows:
        promoted = r["opp_id"] is not None
        won = promoted and (r["opp_status"] == "Won")
        _bump("Signal", promoted, won)

    return sorted(
        buckets.values(),
        key=lambda b: (b["won"], b["leads_in"]),
        reverse=True,
    )


def crawl_target_exists(conn: sqlite3.Connection, kind: str, url: str) -> bool:
    """Dedupe proposals so re-running the generator doesn't pile up duplicates."""
    row = conn.execute(
        "SELECT 1 FROM crawl_targets WHERE kind = ? AND url = ? LIMIT 1",
        (kind, url),
    ).fetchone()
    return row is not None


def insert_crawl_target(
    conn: sqlite3.Connection,
    kind: str,
    label: str,
    query: str,
    url: str,
    source_key: str,
    rationale: str,
) -> Optional[int]:
    """Record a proposed target (status Proposed). Returns None if it already
    exists (deduped on kind+url). Nothing here fetches anything."""
    if kind not in CRAWL_KINDS:
        raise ValueError(f"Unknown crawl kind {kind!r}")
    if crawl_target_exists(conn, kind, url):
        return None
    cur = conn.execute(
        """INSERT INTO crawl_targets
           (kind, label, query, url, source_key, rationale, status, proposed_at)
           VALUES (?,?,?,?,?,?,'Proposed',?)""",
        (
            kind, label, query, url, source_key, rationale,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_crawl_targets(
    conn: sqlite3.Connection,
    kind: Optional[str] = None,
    status: Optional[str] = None,
) -> List[sqlite3.Row]:
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"""SELECT * FROM crawl_targets{where}
            ORDER BY
              CASE status WHEN 'Proposed' THEN 0 WHEN 'Approved' THEN 1
                          WHEN 'Fetched' THEN 2 ELSE 3 END,
              proposed_at DESC""",
        params,
    ).fetchall()


def get_crawl_target(conn: sqlite3.Connection, target_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_targets WHERE id = ?", (target_id,)
    ).fetchone()


def autofetch_due_targets(
    conn: sqlite3.Connection, refetch_before: str, limit: int = 5
) -> List[sqlite3.Row]:
    """Targets the background auto-fetcher may pull this cycle: on an active (On),
    non-gated source, and either newly **Approved** (the backlog) or a **Fetched**
    target last scanned before ``refetch_before`` (a recurring re-scan).

    The human gate is preserved end-to-end — only approved-lineage targets on
    active, non-login-gated sources are ever returned; Proposed/Dismissed targets
    and login-gated sources are never auto-fetched. Approved backlog comes first,
    then the stalest re-scans."""
    placeholders = ",".join("?" * len(ACTIVE_SITE_STATES))
    return conn.execute(
        f"""SELECT t.* FROM crawl_targets t
            JOIN discovery_sites s ON s.key = t.source_key
            WHERE s.status IN ({placeholders})
              AND IFNULL(s.login_gated, 0) = 0
              AND (
                    t.status = 'Approved'
                 OR (t.status = 'Fetched'
                     AND (t.fetched_at IS NULL OR t.fetched_at < ?))
                  )
            ORDER BY (t.status = 'Fetched'), t.fetched_at ASC
            LIMIT ?""",
        (*ACTIVE_SITE_STATES, refetch_before, limit),
    ).fetchall()


def update_crawl_target_status(
    conn: sqlite3.Connection, target_id: int, status: str
) -> None:
    """Approve or dismiss a target. Approval is Jon's explicit go-ahead; only
    Approved targets are ever eligible to be fetched."""
    if status not in CRAWL_STATES:
        raise ValueError(f"Unknown crawl status {status!r}")
    conn.execute(
        "UPDATE crawl_targets SET status = ?, decided_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), target_id),
    )
    conn.commit()


def mark_crawl_target_fetched(
    conn: sqlite3.Connection, target_id: int, result_count: int,
    outcome: Optional[str] = None,
) -> None:
    conn.execute(
        """UPDATE crawl_targets
           SET status = 'Fetched', result_count = ?, fetched_at = ?, last_outcome = ?
           WHERE id = ?""",
        (result_count, datetime.now(timezone.utc).isoformat(), outcome, target_id),
    )
    conn.commit()


def set_site_login_gated(conn: sqlite3.Connection, source_key: str, gated: bool = True) -> None:
    """Flag a source as login-gated (→ manual-assist, never auto-fetched). Used by
    the fetch diagnostics when a login wall is detected at runtime."""
    conn.execute(
        "UPDATE discovery_sites SET login_gated = ? WHERE key = ?",
        (1 if gated else 0, source_key),
    )
    conn.commit()


def crawl_counts(conn: sqlite3.Connection, kind: Optional[str] = None) -> Dict[str, int]:
    clause = " WHERE kind = ?" if kind else ""
    params = (kind,) if kind else ()
    rows = conn.execute(
        f"SELECT status, COUNT(*) AS n FROM crawl_targets{clause} GROUP BY status",
        params,
    ).fetchall()
    counts = {s: 0 for s in CRAWL_STATES}
    for r in rows:
        counts[r["status"]] = r["n"]
    counts["total"] = sum(r["n"] for r in rows)
    return counts


# --------------------------------------------------------------------------- #
# Proposals — deterministic paperwork from the estimator
# --------------------------------------------------------------------------- #
def insert_proposal(
    conn: sqlite3.Connection,
    project_id: Optional[int],
    opp_id: Optional[int],
    proposal: Proposal,
) -> int:
    cur = conn.execute(
        """INSERT INTO proposals
           (project_id, opp_id, created_at, status, deposit_pct, deposit_amount,
            total_price, balance_due, line_items, terms)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            project_id, opp_id, datetime.now(timezone.utc).isoformat(), "Draft",
            proposal.deposit_pct, proposal.deposit_amount, proposal.total_price,
            proposal.balance_due,
            json.dumps([
                {"role": l.role, "hours": l.hours, "rate": l.rate, "cost": l.cost,
                 "unit": l.unit, "qty_label": l.qty_label, "rate_label": l.rate_label}
                for l in proposal.lines
            ]),
            json.dumps(proposal.terms),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()


def proposal_for_project(
    conn: sqlite3.Connection, project_id: int
) -> Optional[sqlite3.Row]:
    """The most recent proposal for a project (None if none generated yet)."""
    return conn.execute(
        "SELECT * FROM proposals WHERE project_id = ? ORDER BY id DESC LIMIT 1",
        (project_id,),
    ).fetchone()


def update_proposal_status(
    conn: sqlite3.Connection, proposal_id: int, status: str
) -> None:
    if status not in PROPOSAL_STATES:
        raise ValueError(f"Unknown proposal status {status!r}")
    conn.execute(
        "UPDATE proposals SET status = ? WHERE id = ?", (status, proposal_id)
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Invoices — deterministic; reconcile to the proposal total
# --------------------------------------------------------------------------- #
def insert_invoice(
    conn: sqlite3.Connection,
    project_id: Optional[int],
    proposal_id: Optional[int],
    invoice: Invoice,
) -> int:
    cur = conn.execute(
        """INSERT INTO invoices
           (project_id, proposal_id, created_at, kind, status, amount, note)
           VALUES (?,?,?,?,'Draft',?,?)""",
        (
            project_id, proposal_id, datetime.now(timezone.utc).isoformat(),
            invoice.kind, invoice.amount, invoice.note,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_invoices(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM invoices WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()


def get_invoice(conn: sqlite3.Connection, invoice_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
    ).fetchone()


def has_invoice(conn: sqlite3.Connection, project_id: int, kind: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM invoices WHERE project_id = ? AND kind = ? LIMIT 1",
        (project_id, kind),
    ).fetchone()
    return row is not None


def update_invoice_status(
    conn: sqlite3.Connection,
    invoice_id: int,
    status: str,
    external_ref: Optional[str] = None,
) -> None:
    """Set invoice status. Marking Paid stamps paid_at; external_ref is the
    payment-provider reference (populated by the Stripe layer later)."""
    if status not in INVOICE_STATES:
        raise ValueError(f"Unknown invoice status {status!r}")
    paid_at = datetime.now(timezone.utc).isoformat() if status == "Paid" else None
    conn.execute(
        """UPDATE invoices
           SET status = ?,
               paid_at = COALESCE(?, paid_at),
               external_ref = COALESCE(?, external_ref)
           WHERE id = ?""",
        (status, paid_at, external_ref, invoice_id),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Match Board — staffable opportunities (assignment flows through projects)
# --------------------------------------------------------------------------- #
def staffable_opportunities(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """Qualified, still-open opportunities worth staffing (not Lost/Passed)."""
    return conn.execute(
        """SELECT * FROM opportunities
           WHERE qualified = 1 AND status NOT IN ('Lost','Passed')
           ORDER BY tier ASC, alignment DESC, created_at DESC"""
    ).fetchall()


# --------------------------------------------------------------------------- #
# Talent (supply side)
# --------------------------------------------------------------------------- #
REVIEW_STATES = [s.value for s in ReviewStatus]
INVITE_STATES = [s.value for s in InviteStatus]


def _disciplines_from_json(raw: Optional[str]) -> List[MusicDiscipline]:
    out: List[MusicDiscipline] = []
    for v in (json.loads(raw) if raw else []):
        try:
            out.append(MusicDiscipline(v))
        except ValueError:
            continue
    return out


def talent_from_row(row: sqlite3.Row) -> Talent:
    return Talent(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        disciplines=_disciplines_from_json(row["disciplines"]),
        credits=row["credits"] or "",
        location=row["location"],
        demo_reel_url=row["demo_reel_url"],
        review_status=_enum(row["review_status"], ReviewStatus, ReviewStatus.PENDING),
        invite_status=_enum(row["invite_status"], InviteStatus, InviteStatus.PROSPECT),
        notes=row["notes"] or "",
        source=row["source"],
        source_url=row["source_url"],
        rate=(row["rate"] if "rate" in row.keys() else None),
        rate_unit=((row["rate_unit"] if "rate_unit" in row.keys() else None) or "hourly"),
    )


def insert_talent(conn: sqlite3.Connection, t: Talent) -> int:
    cur = conn.execute(
        """INSERT INTO talent
           (name, email, disciplines, credits, location, demo_reel_url,
            review_status, invite_status, notes, created_at, source, source_url,
            rate, rate_unit)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            t.name, t.email, json.dumps([d.value for d in t.disciplines]),
            t.credits, t.location, t.demo_reel_url,
            t.review_status.value, t.invite_status.value, t.notes,
            datetime.now(timezone.utc).isoformat(),
            (t.source or "manual"), t.source_url,
            t.rate, (t.rate_unit or "hourly"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def talent_exists(
    conn: sqlite3.Connection, name: str, email: Optional[str] = None
) -> bool:
    """Dedupe check for ingest — match on name, narrowed by email when present."""
    if email:
        row = conn.execute(
            "SELECT 1 FROM talent WHERE name = ? AND email = ? LIMIT 1",
            (name, email),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM talent WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
    return row is not None


def list_talent(
    conn: sqlite3.Connection,
    discipline: Optional[str] = None,
    review: Optional[str] = None,
    invite: Optional[str] = None,
) -> List[sqlite3.Row]:
    clauses, params = [], []
    if discipline:
        clauses.append("disciplines LIKE ?")
        params.append(f'%"{discipline}"%')
    if review:
        clauses.append("review_status = ?")
        params.append(review)
    if invite:
        clauses.append("invite_status = ?")
        params.append(invite)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"SELECT * FROM talent{where} ORDER BY name ASC", params
    ).fetchall()


def get_talent(conn: sqlite3.Connection, talent_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM talent WHERE id = ?", (talent_id,)).fetchone()


def update_talent_review(conn: sqlite3.Connection, talent_id: int, review_status: str) -> None:
    if review_status not in REVIEW_STATES:
        raise ValueError(f"Unknown review status {review_status!r}")
    conn.execute(
        "UPDATE talent SET review_status = ? WHERE id = ?", (review_status, talent_id)
    )
    conn.commit()


def update_talent_invite(conn: sqlite3.Connection, talent_id: int, invite_status: str) -> None:
    if invite_status not in INVITE_STATES:
        raise ValueError(f"Unknown invite status {invite_status!r}")
    conn.execute(
        "UPDATE talent SET invite_status = ? WHERE id = ?", (invite_status, talent_id)
    )
    conn.commit()


def update_talent_profile(
    conn: sqlite3.Connection,
    talent_id: int,
    name: str,
    email: str,
    disciplines: List[str],
    credits: str,
    location: str,
    demo_reel_url: str,
    notes: str,
    rate: Optional[float] = None,
    rate_unit: str = "hourly",
) -> None:
    valid = [d for d in disciplines if d in {m.value for m in MusicDiscipline}]
    conn.execute(
        """UPDATE talent SET name=?, email=?, disciplines=?, credits=?, location=?,
           demo_reel_url=?, notes=?, rate=?, rate_unit=? WHERE id=?""",
        (
            name, email or None, json.dumps(valid), credits, location or None,
            demo_reel_url or None, notes, rate, (rate_unit or "hourly"), talent_id,
        ),
    )
    conn.commit()


def talent_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM talent").fetchone()[0]


def load_talent(conn: sqlite3.Connection) -> List[Talent]:
    """All talent as domain objects (for the matcher)."""
    return [talent_from_row(r) for r in conn.execute("SELECT * FROM talent ORDER BY name")]


# --------------------------------------------------------------------------- #
# Projects + assignments (supply side — Jon assigns; nothing auto-assigns)
# --------------------------------------------------------------------------- #
def insert_project(
    conn: sqlite3.Connection,
    opp_id: Optional[int],
    client: str,
    need: str,
    budget_min: Optional[float],
    budget_max: Optional[float],
    roles: List[str],
    deadline: Optional[str] = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO projects
           (opp_id, client, need, budget_min, budget_max, deadline, status, roles, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            opp_id, client, need, budget_min, budget_max, deadline, "Active",
            json.dumps(roles), datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def project_for_opp(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM projects WHERE opp_id = ? LIMIT 1", (opp_id,)
    ).fetchone()


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


# --------------------------------------------------------------------------- #
# Delivery OS (Phase 0) — thin per-project state on projects.delivery_json
#
# A single JSON blob, edited the same way doc_overrides is (merge one key at a
# time): the deterministic engine + a few logged human calls (license terms,
# approvals, release). Shape (all optional):
#   state         : "In production" | "In review" | "Delivered" | "Released"
#   version_state : "v1 Concept" | "v2 Direction-lock" | "v3 FINAL"
#   revisions_used: int (rounds logged)
#   license       : {type, territory, term, exclusivity, content_id}
#   approvals     : [{asset, approver, date}]
#   released_at   : ISO date stamp set on release
#   assets        : [{label, url, filename, kind}]  (kind: "audio" | "file")
#   share_token   : the client-portal token (mirrors opportunities.share_token)
# --------------------------------------------------------------------------- #
def get_delivery(conn: sqlite3.Connection, project_id: int) -> dict:
    """The project's Delivery OS state as a dict ({} when none/blank)."""
    row = conn.execute(
        "SELECT delivery_json FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return {}
    raw = row["delivery_json"]
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_delivery(conn: sqlite3.Connection, project_id: int, delivery: dict) -> None:
    """Write the full delivery dict back as JSON (empty dict clears the column)."""
    blob = json.dumps(delivery) if delivery else None
    conn.execute(
        "UPDATE projects SET delivery_json = ? WHERE id = ?", (blob, project_id)
    )
    conn.commit()


def update_delivery(conn: sqlite3.Connection, project_id: int, key: str, value) -> dict:
    """Merge a single delivery key (None removes it). Returns the updated dict."""
    delivery = get_delivery(conn, project_id)
    if value is None:
        delivery.pop(key, None)
    else:
        delivery[key] = value
    save_delivery(conn, project_id, delivery)
    return delivery


def add_review_comment(
    conn: sqlite3.Connection, project_id: int, *, version: str = "", t_seconds=None,
    author: str = "", email: str = "", body: str = "", kind: str = "comment",
    parent_id=None, verified: bool = False,
) -> int:
    """Append a review-portal event: a timecoded comment, an approval, or a
    change request. Attributed to the reviewer's name + email. Returns the new id.

    ``parent_id`` (IP2) threads a reply one level under an existing comment — a
    reply answers its parent so it carries no timecode of its own.

    ``verified`` marks the event as posted from a verified reviewer's personal
    invite link (``?r=``) — its name + email are the locked roster identity."""
    cur = conn.execute(
        """INSERT INTO review_comments
           (project_id, version, t_seconds, author, email, body, kind, created_at,
            resolved, parent_id, verified)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, version or "", t_seconds, author or "Anonymous",
         (email or "").strip() or None, body or "", kind,
         datetime.now(timezone.utc).isoformat(),
         0, int(parent_id) if parent_id not in (None, "") else None,
         1 if verified else 0),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_review_comments(
    conn: sqlite3.Connection, project_id: int
) -> List[sqlite3.Row]:
    """All review events for a project, oldest first (the campaign's feedback tape)."""
    return conn.execute(
        "SELECT * FROM review_comments WHERE project_id = ? ORDER BY created_at ASC, id ASC",
        (project_id,),
    ).fetchall()


def get_review_comment(
    conn: sqlite3.Connection, comment_id: int
) -> Optional[sqlite3.Row]:
    """One review-comment row by id (None when it doesn't exist)."""
    return conn.execute(
        "SELECT * FROM review_comments WHERE id = ?", (comment_id,)
    ).fetchone()


def toggle_comment_resolved(
    conn: sqlite3.Connection, project_id: int, comment_id: int
) -> Optional[int]:
    """Flip a comment's resolved flag (IP2). Scoped to the project so a token for
    one campaign can't toggle another's. Returns the new resolved value (0/1), or
    None if the comment doesn't belong to the project."""
    row = conn.execute(
        "SELECT resolved FROM review_comments WHERE id = ? AND project_id = ?",
        (comment_id, project_id),
    ).fetchone()
    if row is None:
        return None
    new_val = 0 if (row["resolved"] or 0) else 1
    conn.execute(
        "UPDATE review_comments SET resolved = ? WHERE id = ? AND project_id = ?",
        (new_val, comment_id, project_id),
    )
    conn.commit()
    return new_val


def list_delivery_reviewers(conn: sqlite3.Connection, project_id: int) -> List[dict]:
    """The verified-reviewer roster for a project (``delivery_json['reviewers']``).

    Each entry is ``{token, name, email, role}`` — the operator invites named
    reviewers and each gets a unique personal link (``?r=<token>``). Returns ``[]``
    when none."""
    delivery = get_delivery(conn, project_id)
    roster = delivery.get("reviewers")
    return roster if isinstance(roster, list) else []


def add_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, *, name: str, email: str = "",
    role: str = "",
) -> Optional[dict]:
    """Mint a verified reviewer + their personal access token, append to the roster.

    Returns the new reviewer dict ``{token, name, email, role}`` (or None when the
    project is gone or no name was given). The token gates Approve — a verified
    reviewer link is required to lock FINAL + build the ZIP (a generic ``?k=`` share
    link can only view + comment as a guest)."""
    name = (name or "").strip()
    if get_project(conn, project_id) is None or not name:
        return None
    roster = list_delivery_reviewers(conn, project_id)
    reviewer = {
        "token": secrets.token_urlsafe(9),
        "name": name,
        "email": (email or "").strip(),
        "role": (role or "").strip(),
    }
    roster.append(reviewer)
    update_delivery(conn, project_id, "reviewers", roster)
    return reviewer


def remove_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, token: str
) -> bool:
    """Drop a reviewer from the roster by their token. Returns True if one was
    removed (their personal link stops working)."""
    token = (token or "").strip()
    if not token:
        return False
    roster = list_delivery_reviewers(conn, project_id)
    kept = [r for r in roster if (r.get("token") or "") != token]
    if len(kept) == len(roster):
        return False
    update_delivery(conn, project_id, "reviewers", kept)
    return True


# --------------------------------------------------------------------------- #
# Per-asset approval — granular sign-off (the :60 master approved while the :30
# cutdown still awaits), not just the whole-version Approve. Stored on
# ``delivery_json['asset_approvals']`` keyed by the asset's stable id (its
# filename, or a slug of its label when the filename is blank) →
# ``{status, by, email, date, version}`` with status in ASSET_APPROVAL_STATES.
# --------------------------------------------------------------------------- #
ASSET_APPROVAL_STATES = ["Pending", "Approved", "Changes requested"]


def asset_key(asset: dict) -> str:
    """A stable id for an asset's per-asset approval record: its filename, or a
    slug of its label when the filename is blank (referenced-only assets). Empty
    only when the asset has neither — those can't carry a per-asset status."""
    if not isinstance(asset, dict):
        return ""
    fname = (asset.get("filename") or "").strip()
    if fname:
        return fname
    label = (asset.get("label") or "").strip()
    if not label:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return f"label:{slug}" if slug else ""


def get_asset_approval(delivery: dict, asset: dict) -> dict:
    """The per-asset approval record for an asset (``{status, by, email, date,
    version}``), defaulting to a Pending record when none is stored."""
    key = asset_key(asset)
    store = (delivery or {}).get("asset_approvals") or {}
    rec = store.get(key) if key else None
    if not isinstance(rec, dict):
        return {"status": ASSET_APPROVAL_STATES[0], "by": "", "email": "",
                "date": "", "version": ""}
    out = {"status": rec.get("status") or ASSET_APPROVAL_STATES[0],
           "by": rec.get("by") or "", "email": rec.get("email") or "",
           "date": rec.get("date") or "", "version": rec.get("version") or ""}
    return out


def set_asset_approval(
    conn: sqlite3.Connection, project_id: int, asset_key_value: str, *,
    status: str, by: str = "", email: str = "", version: str = "",
) -> Optional[dict]:
    """Record a per-asset approval/change-request. ``asset_key_value`` is the asset's
    stable id (see :func:`asset_key`). Returns the stored record, or None when the
    key is blank or the status is unknown."""
    key = (asset_key_value or "").strip()
    if not key or status not in ASSET_APPROVAL_STATES:
        return None
    delivery = get_delivery(conn, project_id)
    store = dict(delivery.get("asset_approvals") or {})
    rec = {
        "status": status,
        "by": (by or "").strip(),
        "email": (email or "").strip(),
        "date": date.today().isoformat(),
        "version": str(version or ""),
    }
    store[key] = rec
    update_delivery(conn, project_id, "asset_approvals", store or None)
    return rec


def asset_approval_rollup(delivery: dict, assets: Optional[List[dict]] = None) -> dict:
    """Roll up per-asset approval across a project's deliverable assets:
    ``{approved, changes, pending, total}``. ``assets`` defaults to the delivery's
    own asset list; only assets that can carry a status (a non-blank key) count."""
    assets = assets if assets is not None else ((delivery or {}).get("assets") or [])
    approved = changes = pending = 0
    total = 0
    for a in assets:
        if not asset_key(a):
            continue
        total += 1
        status = get_asset_approval(delivery, a)["status"]
        if status == "Approved":
            approved += 1
        elif status == "Changes requested":
            changes += 1
        else:
            pending += 1
    return {"approved": approved, "changes": changes, "pending": pending,
            "total": total}


def ensure_project_share_token(conn: sqlite3.Connection, project_id: int) -> Optional[str]:
    """Return the project's share token, minting one on first use.

    Gates the client-facing delivery portal (``?k=<token>``) so the page is
    shareable with the client but not enumerable. Mirrors :func:`ensure_share_token`.
    Returns ``None`` only when the project doesn't exist."""
    row = conn.execute(
        "SELECT share_token FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return None
    existing = row["share_token"]
    if existing and str(existing).strip():
        return existing
    token = secrets.token_urlsafe(9)
    conn.execute(
        "UPDATE projects SET share_token = ? WHERE id = ?", (token, project_id)
    )
    conn.commit()
    return token


def list_projects(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM assignments a WHERE a.project_id = p.id) AS assigned,
                  (SELECT COUNT(*) FROM milestones m WHERE m.project_id = p.id) AS ms_total,
                  (SELECT COUNT(*) FROM milestones m WHERE m.project_id = p.id AND m.status='Done') AS ms_done
           FROM projects p ORDER BY p.created_at DESC"""
    ).fetchall()


def update_project_status(conn: sqlite3.Connection, project_id: int, status: str) -> None:
    if status not in PROJECT_STATES:
        raise ValueError(f"Unknown project status {status!r}")
    conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
    conn.commit()


def add_assignment(
    conn: sqlite3.Connection, project_id: int, role: str, talent_id: int
) -> None:
    """Assign a creator to a role. Called only from the explicit Assign action."""
    conn.execute(
        """INSERT INTO assignments (project_id, role, talent_id, created_at)
           VALUES (?,?,?,?)""",
        (project_id, role, talent_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def remove_assignment(conn: sqlite3.Connection, assignment_id: int) -> None:
    conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    conn.commit()


def list_assignments(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, t.name AS talent_name, t.email AS talent_email,
                  t.rate AS talent_rate, t.rate_unit AS talent_rate_unit
           FROM assignments a LEFT JOIN talent t ON a.talent_id = t.id
           WHERE a.project_id = ? ORDER BY a.role, a.created_at""",
        (project_id,),
    ).fetchall()


def assigned_rate_overrides(conn: sqlite3.Connection, project_id: int) -> dict:
    """Build the estimate's ``rate_overrides`` map for a project from its
    assignments: {role: {"rate", "unit", "talent_name"}} for each role whose
    assigned talent has a non-null rate. First talent with a rate wins per role.
    """
    overrides: dict = {}
    for a in list_assignments(conn, project_id):
        role = a["role"]
        rate = a["talent_rate"] if "talent_rate" in a.keys() else None
        if role in overrides or rate is None:
            continue
        unit = (a["talent_rate_unit"] if "talent_rate_unit" in a.keys() else None) or "hourly"
        overrides[role] = {
            "rate": float(rate),
            "unit": unit,
            "talent_name": a["talent_name"],
        }
    return overrides


# --- Milestones (delivery progress) --------------------------------------- #
def add_milestone(
    conn: sqlite3.Connection, project_id: int, title: str, role: Optional[str] = None
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO milestones (project_id, title, status, role, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        (project_id, title, "Pending", role, now, now),
    )
    conn.commit()
    return int(cur.lastrowid)


def seed_default_milestones(
    conn: sqlite3.Connection, project_id: int, roles: List[str]
) -> None:
    """Give a new project one deliverable milestone per scoped role."""
    for role in roles:
        add_milestone(conn, project_id, f"{role} deliverable", role)


def list_milestones(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM milestones WHERE project_id = ? ORDER BY id", (project_id,)
    ).fetchall()


def update_milestone_status(conn: sqlite3.Connection, milestone_id: int, status: str) -> None:
    if status not in MILESTONE_STATES:
        raise ValueError(f"Unknown milestone status {status!r}")
    conn.execute(
        "UPDATE milestones SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), milestone_id),
    )
    conn.commit()


def remove_milestone(conn: sqlite3.Connection, milestone_id: int) -> None:
    conn.execute("DELETE FROM milestones WHERE id = ?", (milestone_id,))
    conn.commit()


def get_milestone(conn: sqlite3.Connection, milestone_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM milestones WHERE id = ?", (milestone_id,)
    ).fetchone()


def get_assignment(conn: sqlite3.Connection, assignment_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT a.*, t.name AS talent_name
           FROM assignments a LEFT JOIN talent t ON a.talent_id = t.id
           WHERE a.id = ?""",
        (assignment_id,),
    ).fetchone()


# --- Project activity feed (broadcast to the assigned crew) ---------------- #
def add_update(
    conn: sqlite3.Connection, project_id: int, body: str, kind: str = "update"
) -> int:
    cur = conn.execute(
        """INSERT INTO project_updates (project_id, body, kind, created_at)
           VALUES (?,?,?,?)""",
        (project_id, body, kind, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_updates(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM project_updates WHERE project_id = ? ORDER BY created_at DESC, id DESC",
        (project_id,),
    ).fetchall()


def project_crew(conn: sqlite3.Connection, project_id: int) -> List[sqlite3.Row]:
    """Distinct assigned creators — the recipients a broadcast reaches."""
    return conn.execute(
        """SELECT DISTINCT t.id, t.name, t.email
           FROM assignments a JOIN talent t ON a.talent_id = t.id
           WHERE a.project_id = ? ORDER BY t.name""",
        (project_id,),
    ).fetchall()


def milestone_progress(conn: sqlite3.Connection, project_id: int) -> Dict[str, int]:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done
           FROM milestones WHERE project_id = ?""",
        (project_id,),
    ).fetchone()
    total = row["total"] or 0
    done = row["done"] or 0
    pct = round(done / total * 100) if total else 0
    return {"total": total, "done": done, "pct": pct}


def distinct_values(conn: sqlite3.Connection, column: str) -> List[str]:
    allowed = {"action", "tier", "discipline", "buyer_type", "status"}
    if column not in allowed:
        raise ValueError(column)
    rows = conn.execute(
        f"SELECT DISTINCT {column} AS v FROM opportunities WHERE {column} IS NOT NULL ORDER BY v"
    ).fetchall()
    return [r["v"] for r in rows]


def lane_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        "SELECT action, COUNT(*) AS n FROM opportunities GROUP BY action"
    ).fetchall()
    return {r["action"]: r["n"] for r in rows}


def strategic_spotlight(conn: sqlite3.Connection, limit: int = 5) -> List[sqlite3.Row]:
    """Small-but-strategic opportunities: high strategic value, modest budget.

    This is the CMO's headline — the '$2k agency beats $10k municipal' surface.
    """
    return conn.execute(
        """
        SELECT * FROM opportunities
        WHERE qualified = 1
          AND strategic_value >= 65
          AND (COALESCE(budget_max, budget_min, 0) < 5000 OR budget_min IS NULL)
        ORDER BY strategic_value DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Executive-summary pipeline columns (Top targets → Tentative → Won)
# --------------------------------------------------------------------------- #
def pursue_targets(conn: sqlite3.Connection, limit: int = 8) -> List[sqlite3.Row]:
    """Qualified opportunities worth chasing that we haven't bid on yet.

    The top of the funnel: still ``New``/``Pursuing`` (no bid out), ranked by
    tier then fit so the strongest targets surface first.
    """
    return conn.execute(
        """SELECT * FROM opportunities
           WHERE qualified = 1 AND status IN ('New','Pursuing')
           ORDER BY tier ASC, alignment DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def tentative_bids(conn: sqlite3.Connection, limit: int = 12) -> List[sqlite3.Row]:
    """Bids that are out the door awaiting the buyer's decision (``Submitted``)."""
    return conn.execute(
        """SELECT * FROM opportunities
           WHERE status = 'Submitted'
           ORDER BY COALESCE(next_action_due, '9999-12-31') ASC, created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def won_deals(conn: sqlite3.Connection, limit: int = 12) -> List[sqlite3.Row]:
    """Closed-won deals with their linked project id and assigned crew names.

    ``crew`` is a comma-joined list of the talent assigned to the deal's project
    (NULL when no project exists yet or nobody is assigned) so the dashboard can
    show the team on each win without a second query.
    """
    return conn.execute(
        """SELECT o.*, p.id AS project_id,
                  (SELECT GROUP_CONCAT(DISTINCT t.name)
                     FROM assignments a JOIN talent t ON a.talent_id = t.id
                     WHERE a.project_id = p.id) AS crew
           FROM opportunities o
           LEFT JOIN projects p ON p.opp_id = o.id
           WHERE o.status = 'Won'
           ORDER BY o.created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()


def exec_metrics(conn: sqlite3.Connection) -> Dict:
    """Aggregate numbers for the executive summary dashboard."""
    def scalar(sql: str, params=()) -> float:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row and row[0] is not None else 0

    total = scalar("SELECT COUNT(*) FROM opportunities")
    qualified = scalar("SELECT COUNT(*) FROM opportunities WHERE qualified = 1")
    pursue = scalar("SELECT COUNT(*) FROM opportunities WHERE action = 'Pursue'")
    review = scalar("SELECT COUNT(*) FROM opportunities WHERE action = 'Review'")
    won = scalar("SELECT COUNT(*) FROM opportunities WHERE status = 'Won'")
    lost = scalar("SELECT COUNT(*) FROM opportunities WHERE status = 'Lost'")
    pursuing = scalar(
        "SELECT COUNT(*) FROM opportunities WHERE status IN ('Pursuing','Submitted')"
    )
    won_value = scalar("SELECT SUM(outcome_value) FROM opportunities WHERE status = 'Won'")
    pipeline_value = scalar(
        """SELECT SUM(COALESCE(budget_max, budget_min, 0))
           FROM opportunities WHERE status IN ('Pursuing','Submitted')"""
    )
    decided = won + lost
    win_rate = (won / decided * 100.0) if decided else 0.0
    avg_alignment = scalar("SELECT AVG(alignment) FROM opportunities WHERE qualified = 1")

    by_discipline = conn.execute(
        """SELECT discipline, COUNT(*) AS n FROM opportunities
           WHERE qualified = 1 GROUP BY discipline ORDER BY n DESC"""
    ).fetchall()

    return {
        "total": int(total),
        "qualified": int(qualified),
        "pursue": int(pursue),
        "review": int(review),
        "won": int(won),
        "lost": int(lost),
        "pursuing": int(pursuing),
        "won_value": won_value,
        "pipeline_value": pipeline_value,
        "win_rate": win_rate,
        "avg_alignment": avg_alignment,
        "by_discipline": [(r["discipline"], r["n"]) for r in by_discipline],
    }
