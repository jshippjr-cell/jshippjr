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

import atexit
import importlib.util
import contextlib
import json
import itertools
import os
import re
import secrets
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from ..invoicing import INVOICE_STATES, Invoice
from ..models import BuyerType, BuyerValue, MusicDiscipline, MusicRequirement, Opportunity
from ..proposals import PROPOSAL_STATES, Proposal
from .. import compensation, reviewers
from ..strategic import assess_strategic_value
from ..talent import InviteStatus, ReviewStatus, Talent, normalize_url
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


# Letters and digits only — deliberately NOT ``secrets.token_urlsafe``.
#
# Every token minted here ends up in a URL that a human receives in an email, pastes
# into a chat, or reads off a screen. ``token_urlsafe`` draws from base64url, which
# includes ``-`` and ``_``, so about one link in thirty ends in punctuation. Mail and
# messaging clients that linkify plain text treat a trailing ``-`` as the end of a
# sentence and trim it, and the recipient gets a 404 from a link that is correct.
# A composer's portal link did exactly that (token ``ouLvIvWMxli-zHT-``): it opened on
# a desktop and 404'd from the phone. Dropping two characters from the alphabet costs
# ~0.05 bits each and removes the whole class.
#
# EXISTING tokens are left alone. Re-minting them would break every link already in
# somebody's inbox — a worse failure than the one being fixed, and not ours to spend.
_TOKEN_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def public_token(length: int = 16) -> str:
    """An unguessable token safe to put in a link. 62^16 ≈ 95 bits at the default."""
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(length))

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
    doc_overrides TEXT,
    -- Buyer link: the Agency/Company Intelligence record this opportunity is for, so
    -- the whole lineage (opp → project → campaign) can reach the agency's intelligence
    -- instead of only a client NAME. See docs/architecture/DISCOVERY_INTELLIGENCE_LINEAGE.md.
    agency_id INTEGER
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
    rate_unit TEXT DEFAULT 'hourly',  -- 'hourly' | 'day' | 'project'
    publisher TEXT               -- their publishing entity (ADR-0061); blank = house holds their share
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
    share_token TEXT,            -- token gating the client delivery portal
    agency_id INTEGER            -- buyer link threaded from the opportunity
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

-- Talent payouts — the collaborator-pay ledger. Generated (Owed) when a client
-- invoice is marked Paid; Jon pays each off-platform (Zelle/ACH/Wise) and marks it
-- Paid with a reference. A W-9 must be on file (talent.w9_received_at) before a
-- payout can be marked Paid. UNIQUE makes generation idempotent (one row per
-- assignment-role). Off-platform by design — no in-app payout rails (Stripe Connect
-- deferred); this ledger is the discipline that every collaborator is tracked + paid.
CREATE TABLE IF NOT EXISTS talent_payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER,
    talent_id INTEGER,
    role TEXT,
    rate REAL,                              -- snapshot of the talent rate at creation
    rate_unit TEXT,                         -- hourly | day | project
    qty REAL,                              -- hours/days worked (1 for project-flat)
    amount REAL,                            -- amount owed (rate × qty), editable
    status TEXT DEFAULT 'Owed',             -- Owed | Paid
    reference TEXT,                         -- off-platform payment reference
    paid_at TEXT,
    created_at TEXT,
    UNIQUE(project_id, talent_id, role)
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
    # ADR-0039: when that link was last rotated. Blank = never (original link).
    "share_token_rotated_at": "TEXT",
    # Buyer link threaded from the opportunity (see DISCOVERY_INTELLIGENCE_LINEAGE.md).
    "agency_id": "INTEGER",
    # ADR-0018 Phase 4: the Kickoff→Production gate. A project created by a client's
    # Commercial approval sits in KICKOFF until the operator confirms "Start production"
    # (this stamp). Existing/legacy projects have no approved review, so they skip Kickoff
    # entirely and read as Production — this column staying null never regresses them.
    "kickoff_completed_at": "TEXT",
}

# Buyer link migrated onto older opportunities / campaigns the same idempotent way.
# agency_id threads Opportunity → Project → Campaign so downstream modules reach the
# Agency/Company Intelligence record instead of only a client name.
_OPPORTUNITY_LINK_COLUMNS = {
    "agency_id": "INTEGER",
    # ADR-0039: when the client link was last rotated, so the console can say so.
    # Blank means "never rotated — this is the original link".
    "share_token_rotated_at": "TEXT",
}
_CAMPAIGN_COLUMNS = {"agency_id": "INTEGER"}

# Company Enrichment Engine state, migrated onto an existing agencies table the
# same idempotent way. A single JSON blob (see get_agency_enrichment for the
# shape): the normalized Agency Profile + the resumable per-agent checkpoint.
# Display/workflow data only — never queried relationally — so an un-enriched
# agency row renders exactly as before.
_AGENCY_COLUMNS = {
    "enrichment_json": "TEXT",
    # Decision Maker Discovery marker: a small JSON blob {status, found, total,
    # last_run} so the batch/auto-run knows an agency has been processed and the
    # queue advances (an agency where 0 people were found isn't re-tried forever).
    "dm_json": "TEXT",
    # Company Intelligence Profile: the structured, evidence-backed intelligence
    # the engine derives from the enriched profile + decision makers (see
    # get_agency_intel for the shape). Carries its own 'status' so the batch /
    # auto-run queue advances exactly like enrichment and decision makers.
    "intel_json": "TEXT",
    # Signal Detection snapshot: {fingerprint, baselined, seen: {dedup_key: 1},
    # last_scan}. The "seen" set is how change detection works — a signal whose key
    # is already seen isn't re-emitted, so re-scanning only surfaces NEW changes.
    "signals_json": "TEXT",
    # When this agency was last scanned for signals (rotates the scan queue so the
    # background pass works through the whole DB rather than the same first N).
    "signals_scanned_at": "TEXT",
    # Music Opportunity Engine output. The headline number/tier/movement are real
    # columns so Top Movers / sort-by-score are efficient; the full explainable
    # breakdown (sub-scores + evidence + recommendation + history) is the JSON blob.
    "opportunity_score": "INTEGER",
    "opportunity_tier": "TEXT",
    "score_movement": "INTEGER DEFAULT 0",
    "scored_at": "TEXT",
    "opportunity_score_json": "TEXT",
}

# Decision-maker columns added after the table first shipped — migrated onto an
# existing decision_makers table the same idempotent way.
_DM_COLUMNS = {
    # Press mentions found via the external search seam: JSON [{title, url}, ...].
    "press_json": "TEXT",
}

# Provenance columns on talent — migrated onto an existing roster the same way.
_TALENT_COLUMNS = {
    "source": "TEXT",
    "source_url": "TEXT",
    "rate": "REAL",
    "rate_unit": "TEXT DEFAULT 'hourly'",
    # ADR-0061 — the writer's own publishing entity. Publishing is split 50/50 with
    # writers, and a writer's half can only be PAID to an entity registered at a PRO.
    # Blank means the house holds their share and owes it to them, which is a debt the
    # console names rather than a silent forfeit.
    "publisher": "TEXT",
    # Per-creator unguessable token that gates the composer portal (/creator/<token>)
    # — a qualified creator's only credential, mirroring projects.share_token. No
    # password: the token IS the access control (validated in the route).
    "portal_token": "TEXT",
    # W-9 status for the payout ledger: collected before a first payout can be
    # marked Paid. Stored as an ISO date (when received) — null = not on file.
    "w9_received_at": "TEXT",
    # Standing Composer Agreement (ADR-0024, the supply-side floor): the executed
    # work-assignment + rights-conveyance instrument this creator works under.
    # ISO date when executed — null = not on file. Together with a rate, this
    # gates assignment: the rights chain the client-facing certificate warrants
    # begins here, so no agreement + rate → no assignment (machine-enforced).
    "agreement_executed_at": "TEXT",
    "agreement_ref": "TEXT",              # where the signed instrument lives (file/DocuSign ref)
    # Performing-rights organisation this writer is affiliated with (ASCAP / BMI /
    # SESAC / PRS / …). A cue sheet names the PRO **per writer** — it was a module
    # constant, so every writer on every sheet was filed as BMI regardless of who
    # they actually are. Blank is honest: the coordinator fills it or asks.
    "pro": "TEXT",
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
    # Types SQLite accepts that Postgres has never heard of. BLOB is the one that
    # matters: `media_blob` holds the DB mirror of every uploaded master, and
    # without this the table cannot be CREATEd at all — the cutover would fail on
    # the first boot, after the disk was already gone. Found by building the real
    # schema against a real Postgres 16 (ADR-0045).
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql, flags=re.I)
    # COLLATE NOCASE is SQLite's case-insensitive sort. Postgres has no collation
    # by that name, so `ORDER BY company COLLATE NOCASE` is a hard error — the
    # agencies list, the decision-maker list and the roster all use it. LOWER() is
    # the faithful equivalent for ordering.
    sql = re.sub(r"(\w+)\s+COLLATE\s+NOCASE\b", r"LOWER(\1)", sql, flags=re.I)
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
    """Adapts a psycopg connection to the sqlite3.Connection API the app uses.

    ``pool`` is set when the connection was borrowed rather than opened; ``close()``
    then hands it back instead of tearing down a TCP session the next call will only
    have to rebuild.
    """

    # Tables whose PK column is `id` — an INSERT into one needs `RETURNING id` so
    # the shim can expose `cursor.lastrowid` (psycopg has none). Derived once from
    # the live catalog (covers tables created in _SCHEMA *and* _ensure_schema).
    _id_tables_cache = None

    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool

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
        """Hand the connection back, or shut it if it was never borrowed.

        The rollback is not belt-and-braces. Today `close()` on an uncommitted
        connection discards the work — every caller commits explicitly — and a pooled
        connection must reach the next borrower in exactly that state, not carrying an
        open snapshot and whatever locks came with it. So the semantics are preserved
        by making them explicit rather than by trusting the pool to guess.
        """
        pool, self._pool = self._pool, None        # never return the same one twice
        if pool is None:
            self._conn.close()
            return
        try:
            self._conn.rollback()
            pool.putconn(self._conn)
        except Exception:                          # noqa: BLE001 — a poisoned connection
            try: self._conn.close()                # must not poison the pool with it
            except Exception: pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self._conn.commit() if exc_type is None else self._conn.rollback()
        return False


# --------------------------------------------------------------------------- #
# The connection pool
# --------------------------------------------------------------------------- #
# `connect()` is called 254 times across the web layer — a connection per handler,
# several per page — and each one is closed immediately. On SQLite that is a file
# open and genuinely cheap. On Postgres it is a TCP connect, a TLS handshake and an
# auth round trip, to a host across the network, before a single row is read. The
# cutover turns the cheapest operation in the system into one of the most expensive
# without changing a line of calling code.
#
# So the pool goes BEHIND `connect()`, not in front of it: every existing call site
# keeps working unchanged, `close()` returns the connection instead of dropping it,
# and SQLite is untouched (its connections are cheap, and sharing one across threads
# is a hazard, not an optimisation).
#
# `psycopg_pool` is an optional package, and this repo has already lost data to a
# declared dependency that production never installed — `render.yaml` carried the
# `s3` extra while Render built from its stored dashboard command, so uploads landed
# with zero copies while the boot line announced durability (ADR-0043, amended). The
# lesson is applied here: a missing pool degrades to exactly today's behaviour, and
# SAYS SO at boot. It must never be possible to believe pooling is on when it isn't.
_POOL = None
_POOL_URL = ""
_POOL_LOCK = threading.Lock()
_POOL_SPEC = None


def pool_available() -> bool:
    """Is `psycopg_pool` importable? Memoised — a deploy cannot gain a package
    without a restart, and this sits on the per-connection path."""
    global _POOL_SPEC
    if _POOL_SPEC is None:
        _POOL_SPEC = importlib.util.find_spec("psycopg_pool") is not None
    return _POOL_SPEC


def pool_enabled() -> bool:
    return os.environ.get("CHORDENTIAL_DB_POOL", "1").strip().lower() not in (
        "0", "false", "no", "off")


def _pool_size() -> tuple:
    def _int(name, default):
        try:
            return max(0, int(os.environ.get(name, default)))
        except ValueError:
            return default
    # Modest by default. Render's managed Postgres caps connections, the scheduler
    # shares this pool with the web workers, and a pool larger than the server allows
    # fails at the worst possible moment rather than the most obvious one.
    return _int("CHORDENTIAL_DB_POOL_MIN", 1), _int("CHORDENTIAL_DB_POOL_MAX", 10)


def _get_pool(url: str):
    """The process-wide pool for ``url``, or None if pooling is off/unavailable."""
    global _POOL, _POOL_URL
    if not (pool_enabled() and pool_available()):
        return None
    if _POOL is not None and _POOL_URL == url:
        return _POOL
    with _POOL_LOCK:
        if _POOL is not None and _POOL_URL == url:
            return _POOL
        if _POOL is not None:                      # the DSN changed (tests do this)
            try: _POOL.close()
            except Exception: pass
            _POOL = None
        try:
            from psycopg_pool import ConnectionPool
            lo, hi = _pool_size()
            _POOL = ConnectionPool(
                url, min_size=lo, max_size=hi, open=True, timeout=10,
                # A connection idle for hours behind a load balancer is often already
                # dead; recycling bounds how stale a borrowed one can be.
                max_idle=300, max_lifetime=1800,
                kwargs={"autocommit": False, "row_factory": _pg_row_factory},
            )
            _POOL_URL = url
        except Exception:                          # noqa: BLE001 — degrade, never fail
            _POOL = None
            _POOL_URL = ""
    return _POOL


def close_pool() -> None:
    """Drop the pool at shutdown so a draining instance releases its connections
    instead of holding them until the server times them out.

    Also registered with `atexit` below, which is not tidiness. Left to the garbage
    collector, `ConnectionPool.__del__` runs during interpreter finalization and tries
    to join its worker thread — which Python 3.14 refuses, printing a `Exception
    ignored … PythonFinalizationError` traceback. Observed on the live cutover, in the
    Render shell, immediately after `Migration complete.`: nothing was wrong, nothing
    was lost, and it looked exactly like a crash at the one moment an operator is
    deciding whether to trust a migration they cannot undo. `atexit` runs BEFORE
    finalization, where joining a thread is still legal, so the pool is already closed
    by the time `__del__` would have tried.
    """
    global _POOL, _POOL_URL
    with _POOL_LOCK:
        if _POOL is not None:
            try: _POOL.close()
            except Exception: pass
        _POOL, _POOL_URL = None, ""


# Close the pool while joining threads is still legal — see `close_pool`.
atexit.register(close_pool)


def pool_status(db_path: str = "") -> dict:
    """What is actually happening, for the boot line and the console. "We thought
    pooling was on" is precisely the belief this repo has been burned by before."""
    path = db_path or os.environ.get("CHORDENTIAL_DB", DEFAULT_DB_PATH)
    pg = _is_pg_url(path)
    lo, hi = _pool_size()
    return {
        "backend": "postgres" if pg else "sqlite",
        "requested": pool_enabled(),
        "available": pool_available(),
        "active": bool(pg and pool_enabled() and pool_available() and _POOL is not None),
        "applicable": pg,
        "min": lo, "max": hi,
    }


def connect(db_path: str = DEFAULT_DB_PATH):
    if _is_pg_url(db_path):
        import psycopg  # lazy: only production/Postgres needs the driver
        url = db_path.replace("postgres://", "postgresql://", 1)
        pool = _get_pool(url)
        if pool is not None:
            try:
                return _PgConn(pool.getconn(), pool=pool)
            except Exception:              # noqa: BLE001 — an exhausted or wedged pool
                pass                       # must degrade to a direct connection, not 500
        return _PgConn(psycopg.connect(url, autocommit=False, row_factory=_pg_row_factory))
    # SQLite (dev + tests). Ensure the parent dir exists for a mounted-disk path.
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Journal mode. WAL lets readers and the single writer proceed concurrently, but
    # it relies on a shared-memory (-shm) file and POSIX locking that are NOT reliable
    # on network-attached storage (e.g. a Render persistent disk) — there it can hang
    # every DB open, which looks like the whole site down while /healthz (no DB) still
    # passes. So WAL is OPT-IN (CHORDENTIAL_SQLITE_WAL=1) for local/fast-disk use;
    # by default we use the rollback journal, which is what ran reliably in prod.
    #
    # journal_mode is PERSISTED in the DB file, so if WAL was ever set we must
    # actively switch back to DELETE here (and that checkpoints + removes the stale
    # -wal/-shm files left on the disk). Best-effort: never fail the open over this.
    want_wal = os.environ.get("CHORDENTIAL_SQLITE_WAL", "0").strip().lower() in (
        "1", "true", "yes", "on")
    try:
        if want_wal:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        else:
            conn.execute("PRAGMA journal_mode=DELETE")   # undo any persisted WAL
    except sqlite3.OperationalError:
        pass
    # Still wait out brief writer-vs-writer contention instead of erroring.
    conn.execute("PRAGMA busy_timeout=10000")
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
    for name, decl in _OPPORTUNITY_LINK_COLUMNS.items():   # buyer link (agency_id)
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
    # Session Room (EP review P0-1): the composer's "mark addressed" is COMPOSER
    # state, never the client's resolved flag — the publish-gate principle applied
    # to note state. And a composer's question/reply is INTERNAL (composer↔studio):
    # it must never render on the client portal.
    if "composer_addressed" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN composer_addressed INTEGER DEFAULT 0")
    if "internal" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN internal INTEGER DEFAULT 0")
    # Phase 2 (EP review): the operator classifies each note's SPECIES — a
    # revision (counts against rounds) or a conform (caused by a picture change,
    # free). The scope-bearing decision, recorded where the note lives.
    if "conform" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN conform INTEGER DEFAULT 0")
    # Phase 4 (range/span notes): a note may cover a stretch of the picture, not
    # just a point — its end timecode. NULL keeps the classic single-point pin.
    if "t_end" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN t_end REAL")
    # ADR-0069 — the note DISPOSITION. "Request changes" cost a round and a note cost
    # nothing, yet both reached the composer and both got worked on: an unpriced revision
    # channel sitting next to a counter that said "Round 1 of 2". Every client note is now
    # classified by a human before it becomes work — conform (picture moved, free),
    # revision (counts a round), or out_of_scope (quoted separately, never actioned free).
    # Blank means UNDISPOSITIONED: in the operator's queue, invisible to the composer.
    if "disposition" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN disposition TEXT DEFAULT ''")
    # WHO SPOKE — as a role, not just a name. The room shows every note to everyone in
    # it, and a client reading "Ada Cheng · 'the low brass is fighting the VO'" now knows
    # the name of the person we hired, what we hired them for, and that the mix had a
    # problem. None of that is theirs. Recorded at the write, because it cannot be
    # recovered from a name afterwards. Blank on the rows written before this column
    # existed; `_creator_feedback` infers those from evidence rather than guessing.
    if "author_role" not in rc_cols:
        conn.execute("ALTER TABLE review_comments ADD COLUMN author_role TEXT DEFAULT ''")
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
    # AI spend ledger (ADR-0023): estimated Anthropic API cost per month, so the app can
    # ENFORCE a hard monthly cap itself (never silently drain the operator's credit).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_spend (
            month TEXT PRIMARY KEY, est_cost REAL DEFAULT 0, calls INTEGER DEFAULT 0,
            in_tokens INTEGER DEFAULT 0, out_tokens INTEGER DEFAULT 0, updated_at TEXT
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
    # Harvested agency directory records (AdForum, Cannes Lions, 4A's, Awwwards,
    # DesignRush, The Drum, …). One row per agency per source; duplicates within a
    # source are collapsed on (source, dedup_key) so a re-run / resume never piles
    # up copies. ``dedup_key`` is a normalized website host (or name+location).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, dedup_key TEXT,
            company TEXT, website TEXT, employees TEXT, location TEXT,
            description TEXT, industries TEXT, source_url TEXT,
            enrichment_json TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(source, dedup_key)
        )"""
    )
    agency_cols = {r["name"] for r in conn.execute("PRAGMA table_info(agencies)")}
    for name, decl in _AGENCY_COLUMNS.items():
        if name not in agency_cols:
            conn.execute(f"ALTER TABLE agencies ADD COLUMN {name} {decl}")
    # Per-source crawl checkpoint: lets a directory agent resume exactly where it
    # left off after an interruption, and powers the live progress read-out.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS crawl_state (
            source_key TEXT PRIMARY KEY,
            status TEXT DEFAULT 'idle',
            next_page INTEGER DEFAULT 1,
            total_pages INTEGER,
            pages_done INTEGER DEFAULT 0,
            records_new INTEGER DEFAULT 0,
            records_seen INTEGER DEFAULT 0,
            last_url TEXT, detail TEXT DEFAULT '', updated_at TEXT
        )"""
    )
    # Decision Maker Discovery Engine output: the people worth contacting at each
    # agency, one row per person per agency (collapsed on (agency_id, dedup_key) so
    # a re-run never piles up copies). Every column is a fact pulled from a public
    # page or a deterministic classification of one — nothing invented.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS decision_makers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, dedup_key TEXT,
            name TEXT, title TEXT,
            department TEXT, office TEXT, reports_to TEXT,
            bio TEXT, photo_url TEXT,
            linkedin TEXT, email TEXT, phone TEXT,
            social_json TEXT, source_urls_json TEXT, press_json TEXT,
            role_category TEXT, priority TEXT,
            music_relevance TEXT, relevance_reason TEXT,
            confidence INTEGER DEFAULT 0,
            linkedin_verified INTEGER DEFAULT 0,
            classified_by TEXT DEFAULT 'rules',
            last_verified TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(agency_id, dedup_key)
        )"""
    )
    dm_cols = {r["name"] for r in conn.execute("PRAGMA table_info(decision_makers)")}
    for name, decl in _DM_COLUMNS.items():
        if name not in dm_cols:
            conn.execute(f"ALTER TABLE decision_makers ADD COLUMN {name} {decl}")
    # The self-expanding title taxonomy: the learned cache that lets the Role
    # Classification agent answer from rules without re-deciding. Seeded keyword
    # rules live in code; this table accumulates one row per normalized title the
    # system has confidently classified (by rule or, for the unknowns, by LLM —
    # ``source`` records which), so a repeat title is a cheap lookup, never an
    # LLM call. ``hits`` counts how often the title has been seen.
    # Opportunity Timeline: the chronological stream of normalized opportunity
    # SIGNALS the Signal Detection Framework emits (one row per detected event,
    # collapsed on (agency_id, dedup_key) so the same change is never stored
    # twice). The engine stores verified signals only — it does NOT score them.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS opportunity_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, dedup_key TEXT,
            event_type TEXT, category TEXT,
            importance TEXT, music_relevance TEXT, confidence INTEGER DEFAULT 0,
            summary TEXT, source TEXT, source_url TEXT,
            evidence_json TEXT,
            event_date TEXT, detected_at TEXT, expires_at TEXT,
            created_at TEXT,
            UNIQUE(agency_id, dedup_key)
        )"""
    )
    # Relationship history / previous outreach to an agency — the interaction log
    # the Opportunity Engine reads for Relationship Readiness and the Relationship
    # Management Platform reads for stage + timeline. One row per touch.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agency_outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, kind TEXT, direction TEXT DEFAULT 'out',
            occurred_at TEXT, responded INTEGER DEFAULT 0,
            contact TEXT DEFAULT '', note TEXT DEFAULT '', created_at TEXT
        )"""
    )
    # Relationship Management Platform — everything belongs to the RELATIONSHIP,
    # not the agency. The lifecycle stage (one row per agency; auto-derived unless
    # overridden), follow-up tasks, relationship memory (institutional knowledge),
    # and documents. The platform consumes the engines' outputs; it doesn't crawl.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS relationships (
            agency_id INTEGER PRIMARY KEY,
            stage TEXT, stage_overridden INTEGER DEFAULT 0,
            owner TEXT DEFAULT '', note TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agency_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, title TEXT, kind TEXT DEFAULT 'task',
            due_at TEXT, status TEXT DEFAULT 'open', source TEXT DEFAULT 'manual',
            created_at TEXT, done_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agency_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, contact TEXT DEFAULT '', fact TEXT,
            source TEXT DEFAULT 'manual', created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS agency_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER, title TEXT, url TEXT DEFAULT '',
            note TEXT DEFAULT '', created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS title_taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_norm TEXT UNIQUE,
            role_category TEXT, department TEXT, priority TEXT,
            music_relevance TEXT, relevance_reason TEXT,
            source TEXT DEFAULT 'rules', rationale TEXT DEFAULT '',
            confidence INTEGER DEFAULT 0, hits INTEGER DEFAULT 0,
            created_at TEXT, updated_at TEXT
        )"""
    )
    # Campaign Workspace (Creative OS) — the campaign is the workspace root that
    # elevates a project into "one screen, one campaign, everything." Created lazily
    # per project (compat link `project_id`) so there is no bulk migration; the
    # existing delivery/review machinery keeps running per-project underneath.
    # See docs/campaign-workspace-prd.md.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,           -- compat link to the existing project
            opp_id INTEGER,
            agency_id INTEGER,            -- buyer link threaded from the opportunity
            title TEXT, brand TEXT DEFAULT '', agency_client TEXT DEFAULT '',
            phase TEXT DEFAULT 'Briefing',
            budget_min REAL, budget_max REAL, deadline TEXT,
            contracted_revisions INTEGER,
            status TEXT DEFAULT 'Active',
            share_token TEXT, creative_json TEXT,
            created_at TEXT, updated_at TEXT, archived_at TEXT
        )"""
    )
    camp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(campaigns)")}
    for name, decl in _CAMPAIGN_COLUMNS.items():           # migrate increment-1 rows
        if name not in camp_cols:
            conn.execute(f"ALTER TABLE campaigns ADD COLUMN {name} {decl}")
    # Campaign Intelligence (Creative OS) — the canonical, LIVING per-engagement record.
    # A stable spine that every module inherits from and contributes back to via one
    # provenance model. The root holds identity + links; the FACTS live in _field (one
    # row per fact, so each carries its own {kind, sources[], status} — the only shape
    # that renders the provenance card); _event is the append-only enrichment log (the
    # institutional-memory + moat feed). See docs/architecture/CAMPAIGN_INTELLIGENCE.md.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS campaign_intelligence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER, opp_id INTEGER, agency_id INTEGER, project_id INTEGER,
            title TEXT, brand TEXT DEFAULT '', agency_client TEXT DEFAULT '',
            state TEXT DEFAULT 'seeded',   -- seeded | active | delivered | archived
            created_at TEXT, updated_at TEXT, archived_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS campaign_intelligence_field (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ci_id INTEGER NOT NULL,
            facet TEXT NOT NULL,           -- engagement|buyer|direction|commercial|relationship|outcome
            key TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'fact',  -- fact|insight|recommendation|open_question
            value TEXT DEFAULT '', value_json TEXT,
            sources TEXT DEFAULT '[]',     -- JSON list of provenance sources (the card's ✓ list)
            status TEXT DEFAULT 'needs_review',
            origin TEXT DEFAULT '', confidence INTEGER,
            is_concern INTEGER DEFAULT 0,  -- a risk the producer flagged
            contributed_by TEXT DEFAULT '', updated_at TEXT,
            human_value INTEGER DEFAULT 0,  -- 1 = a human authored/confirmed this value; machine never clobbers it
            proposed_value TEXT,            -- a machine value that DISAGREES with a human_value field (a conflict)
            proposed_source TEXT,           -- who proposed the conflicting value
            capture_id INTEGER,             -- the Capture (raw evidence) that last proposed/changed this value
            UNIQUE(ci_id, facet, key, kind)  -- a fact + an insight can coexist on one key
        )"""
    )
    # ADR-0013: human edits are authoritative; a disagreeing machine value lands as a
    # surfaced conflict. ADR-0014: every field carries the Capture (raw evidence) it came
    # from. Migrate existing CI-field rows to carry the new columns.
    cif_cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(campaign_intelligence_field)")}
    for name, decl in {"human_value": "INTEGER DEFAULT 0",
                       "proposed_value": "TEXT", "proposed_source": "TEXT",
                       "capture_id": "INTEGER"}.items():
        if name not in cif_cols:
            conn.execute(
                f"ALTER TABLE campaign_intelligence_field ADD COLUMN {name} {decl}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS campaign_intelligence_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ci_id INTEGER NOT NULL,
            actor TEXT, verb TEXT, facet TEXT, key TEXT, kind TEXT,
            from_value TEXT, to_value TEXT, source TEXT, created_at TEXT,
            capture_id INTEGER              -- the raw-evidence Capture behind this event (ADR-0014)
        )"""
    )
    evt_cols = {r["name"] for r in conn.execute(
        "PRAGMA table_info(campaign_intelligence_event)")}
    if "capture_id" not in evt_cols:
        conn.execute("ALTER TABLE campaign_intelligence_event ADD COLUMN capture_id INTEGER")
    # Producer Learning ledger (ADR-0021): every operator disposition of a proposed field is
    # training data. "The machine proposes, Jon disposes, and the machine learns from the
    # disposition." Rolls up into per-field priors that tune the next extraction — not
    # fine-tuning, not vector memory: an auditable, count-based learning record.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS producer_learning_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ci_id INTEGER, opp_id INTEGER,
            facet TEXT, key TEXT, kind TEXT DEFAULT 'fact',
            action TEXT,                    -- confirmed|rejected|edited|added
            ai_value TEXT,                  -- the machine's original proposal ('' when added-from-nothing)
            final_value TEXT,               -- the operator's confirmed/edited value
            edit_distance REAL DEFAULT 0,   -- 0 = accepted verbatim, 1 = rejected/wholesale change
            confidence_before INTEGER,      -- the AI's confidence on the proposal
            transcript_fragment TEXT,       -- the raw-evidence citation, when known
            capture_id INTEGER,
            created_at TEXT
        )"""
    )
    # Procurement Intelligence (ADR-0022): ChordOS prepares clients for procurement — it does
    # NOT integrate with procurement systems. Requirements are DISCOVERED from conversation
    # (never hardcoded per client); the Company Profile is entered once and feeds every
    # generated document; client history makes onboarding compound across campaigns.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS company_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            data TEXT DEFAULT '{}', updated_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS procurement_requirement (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            req_key TEXT NOT NULL,           -- canonical vocabulary key (w9, coi, vendor_portal…)
            label TEXT, category TEXT,
            owner TEXT DEFAULT 'chordential',-- chordential|client|shared
            status TEXT DEFAULT 'needed',    -- needed|requested|generated|uploaded|complete|na
            confidence INTEGER, source TEXT, evidence TEXT,
            owner_note TEXT, due_date TEXT, notes TEXT,
            generatable INTEGER DEFAULT 0,
            artifact_ref TEXT, artifact_text TEXT,
            created_at TEXT, updated_at TEXT,
            UNIQUE(opp_id, req_key)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS procurement_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL, verb TEXT, detail TEXT, created_at TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS client_procurement_history (
            client TEXT PRIMARY KEY, data TEXT DEFAULT '{}', updated_at TEXT
        )"""
    )
    # Durable media storage: uploaded audio/files live on LOCAL disk (UPLOAD_DIR), which is
    # ephemeral on most deploys (every redeploy wipes it) — so a published version's file
    # vanished while its metadata survived, and the review player 404'd. Mirror every upload's
    # bytes into the DB (which IS durable — Postgres or the persistent SQLite), and serve from
    # here when the disk copy is gone. The real object-store cutover (S3/R2) can replace this
    # later behind the same seam; until then the DB is the durable backstop.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS media_blob (
            name TEXT PRIMARY KEY, content BLOB, content_type TEXT, size INTEGER,
            created_at TEXT
        )"""
    )
    # The Disposition Queue's snooze (the queue of ADR-0029, made clearable). A card has
    # no row of its own — it is computed — so the snooze is keyed by the card's stable
    # identity (kind:url) and EXPIRES. Nothing is deleted and nothing is hidden for ever:
    # a decision that still needs making comes back, which is the only way a "waiting on
    # you" list stays trustworthy after you have cleared it.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS queue_snooze (
            key TEXT PRIMARY KEY, until_at TEXT, snoozed_at TEXT, actor TEXT
        )"""
    )
    # One scheduler across every instance (see `acquire_lease`). The blue-green cutover
    # deliberately runs two of them for a few minutes; without this, both run the engines.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS scheduler_lease (
            name TEXT PRIMARY KEY, owner TEXT, expires_at TEXT, acquired_at TEXT
        )"""
    )
    # Real accounts and real sessions (ADR-0054), ADDITIVELY — the shared passphrase
    # keeps working as break-glass, because a change that can lock the operator out of
    # the system running their business is not worth any amount of tidiness.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT, name TEXT,
            password_hash TEXT,       -- scrypt$n$r$p$salt$hash — parameters travel with it
            role TEXT DEFAULT 'operator',
            created_at TEXT, last_login_at TEXT, disabled_at TEXT
        )"""
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_account_email "
                 "ON user_account(email)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT,          -- SHA-256 of the cookie; the token is never stored
            user_id INTEGER,
            created_at TEXT, expires_at TEXT, last_seen_at TEXT, revoked_at TEXT,
            user_agent TEXT
        )"""
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_session_token "
                 "ON user_session(token_hash)")
    # WHO did this (ADR-0053). Every state change, attributed. Today there is one
    # operator and a shared passphrase, so the actor is a ROLE rather than a name — and
    # recording a name we do not have would be a lie in an audit trail. What the system
    # genuinely knows is which door the request came through, and that is what it
    # records; when real accounts arrive the actor gains a name and nothing else moves.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS decision_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT,
            actor_kind TEXT,          -- operator | client | creator | public
            actor_label TEXT,         -- the best identification we actually have
            actor_ref TEXT,           -- token fingerprint / person id, never the token
            method TEXT, path TEXT,   -- what was done, in the product's own URLs
            subject_type TEXT, subject_id INTEGER,
            status INTEGER
        )"""
    )
    # ONE buyer, across every surface they touch (ADR-0050). A human on the buying side
    # is currently recorded in SIX unlinked places — `decision_makers` (what enrichment
    # found), `discovery_requests` (who asked for a call), `meetings` and
    # `meeting_proposals` (who was on it), `review_comments` (who approved the work) —
    # each with its own name/email pair and nothing joining them. The same person asks
    # for a call, takes it, and signs off the master as three strangers.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS buyer_person (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,                  -- normalised (lowercased, trimmed); the identity
            name TEXT,                   -- the best name seen so far; never the identity
            first_seen_at TEXT, last_seen_at TEXT
        )"""
    )
    # Enforced, not merely intended: two rows for one email is the bug this exists to end.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_buyer_person_email "
                 "ON buyer_person(email)")
    # ONE organisation, across every surface that names one (ADR-0056) — the half
    # ADR-0050 deferred. A company is `agencies.id` in Agency Intelligence and a bare
    # name string in `opportunities.client`, `projects.client`, `companies.client` and
    # `client_procurement_history.client`, with nothing joining them. `name_key` is the
    # identity (see resolve_org for why, and for what that costs); `domain` corroborates
    # and never merges; `agency_id` is how the string world reaches the integer one.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS buyer_org (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,                   -- as first written; for display
            name_key TEXT,               -- normalised; the identity
            domain TEXT DEFAULT '',      -- corroborating evidence, never a merge key
            agency_id INTEGER,           -- the Agency Intelligence record, when there is one
            first_seen_at TEXT, last_seen_at TEXT
        )"""
    )
    # Enforced by the server, not by the resolver being careful: it is called from
    # request threads and from a boot backfill at the same time.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_buyer_org_name_key "
                 "ON buyer_org(name_key)")
    # Signatures bound to what was signed (ADR-0059). A row here is EVIDENCE — it is
    # appended and never updated, because a signature you can edit is not one. The
    # digest is of the exact document text at signing; verification rebuilds the
    # document and compares, so a term changed afterwards reads as superseded rather
    # than as a signature that still appears to cover it.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS signature (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            doc_kind TEXT,
            digest TEXT,                 -- SHA-256 of the signed document text
            signer_name TEXT, signer_email TEXT, typed_name TEXT,
            consent_text TEXT,           -- verbatim, not a version reference
            signed_at TEXT,
            actor TEXT,                  -- authenticated identity, when there is one
            ip_fingerprint TEXT,         -- SHA-256 prefix; never the address itself
            user_agent TEXT,
            token_fingerprint TEXT,
            certified_version TEXT,
            terms_json TEXT,             -- what the document said, for legibility
            voided_at TEXT, voided_by TEXT, void_reason TEXT,
            opportunity_id INTEGER DEFAULT 0,  -- the subject when no project exists yet
            drawn_mark TEXT,                   -- the drawn signature, PNG data URL
            talent_id INTEGER DEFAULT 0,       -- the subject for a supply-side agreement
            contributor_id INTEGER DEFAULT 0   -- …or one session player's release
        )"""
    )
    # Everyone who is not the composer: session players, vocalists, programmers,
    # co-writers. Named BY the composer against a project, each with their own
    # unguessable token — they are not users of this system and never will be, so the
    # link is the whole credential (same model as the client workspace).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contributors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            talent_id INTEGER,               -- the composer who named and booked them
            name TEXT, email TEXT, role TEXT,
            work TEXT,                       -- what they played on, in plain words
            booked_by TEXT,                  -- the composer's name, frozen at naming
            token TEXT,                      -- their release link; the credential
            sent_at TEXT,
            created_at TEXT
        )"""
    )
    # The Discovery Summary & Proposal is signed BEFORE a project exists, so it is stamped
    # with the opportunity instead. Existing databases predate the column.
    sig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(signature)")}
    for _name, _decl in (("opportunity_id", "INTEGER DEFAULT 0"), ("drawn_mark", "TEXT"),
                         ("talent_id", "INTEGER DEFAULT 0"),
                         ("contributor_id", "INTEGER DEFAULT 0")):
        if _name not in sig_cols:
            conn.execute(f"ALTER TABLE signature ADD COLUMN {_name} {_decl}")
    # Campaign Intake — a Capture is an IMMUTABLE evidence record (one per input): the raw
    # source + what the pipeline extracted from it. Every intake LANE (discovery call, notes,
    # transcript, debrief, RFP, email, brief, …) normalizes to this one envelope, and CI
    # fields cite the capture they came from — raw evidence is permanent (ADR-0014). Captures
    # feed Campaign Intelligence (the synthesis); the raw evidence is never mutated.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ci_id INTEGER, campaign_id INTEGER, opp_id INTEGER,
            lane TEXT,                -- the intake lane (registry key): meeting_notes|discovery_call|…
            stance TEXT,      -- objective | debrief
            modality TEXT,    -- notes | transcript | voice | rfp | email | document
            provenance_source TEXT,   -- the source token stamped on every field it contributes
            raw_text TEXT,
            artifact_ref TEXT,        -- pointer to the stored source file / recording (evidence)
            external_ref TEXT,        -- provider id (Zoom meeting id, Recall bot id, …)
            metadata_json TEXT,       -- speakers[], timestamps, duration, participants, …
            extraction_json TEXT,   -- the candidates extracted (the evidence trail)
            status TEXT DEFAULT 'ready',  -- received|transcribing|ready|ingested|failed
            created_by TEXT, created_at TEXT
        )"""
    )
    # ADR-0014: the Capture envelope — migrate existing captures rows to the lane fields.
    cap_cols = {r["name"] for r in conn.execute("PRAGMA table_info(captures)")}
    for name, decl in {"opp_id": "INTEGER", "lane": "TEXT",
                       "provenance_source": "TEXT", "artifact_ref": "TEXT",
                       "external_ref": "TEXT", "metadata_json": "TEXT",
                       "status": "TEXT DEFAULT 'ready'"}.items():
        if name not in cap_cols:
            conn.execute(f"ALTER TABLE captures ADD COLUMN {name} {decl}")
    # Structured creative direction — the composer's brief as checklist-able sections
    # (emotional arc, reference playlist, agency/producer notes, brand history,
    # previous campaigns). One row per (campaign, section).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS campaign_direction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            section TEXT NOT NULL,
            body TEXT DEFAULT '',
            complete INTEGER DEFAULT 0,
            source TEXT DEFAULT 'manual',
            updated_at TEXT,
            UNIQUE(campaign_id, section)
        )"""
    )
    # Discovery meetings — a meeting is tied to its Opportunity BEFORE it begins (ADR-0014
    # §4.2). The schedule-time association the async transcript flow depends on; also the
    # backing for the opportunity's contextual "Upcoming Discovery" panel. Provider fields
    # (Zoom/Recall) stay null in the manual interim and fill in when the seams are configured.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER, ci_id INTEGER,
            provider TEXT DEFAULT 'manual',      -- manual | zoom | meet | teams
            external_meeting_id TEXT, join_url TEXT,
            start_at TEXT, duration_min INTEGER DEFAULT 20, timezone TEXT,
            attendees_json TEXT,
            notetaker_provider TEXT DEFAULT '',  -- '' = not connected | recall | zoom_ai | …
            bot_id TEXT, consent_recorded INTEGER DEFAULT 1,
            status TEXT DEFAULT 'scheduled',     -- scheduled|bot_invited|in_progress|
                                                 --   transcript_ready|ingested|failed|canceled
            transcript_capture_id INTEGER,
            error TEXT, scheduled_by TEXT, created_at TEXT, updated_at TEXT,
            meeting_type TEXT DEFAULT 'zoom',    -- zoom | phone (phone never arms Recall)
            request_id INTEGER,                  -- the Discovery Request this fulfils (or null)
            client_name TEXT, client_email TEXT,
            calendar_event_id TEXT,              -- the calendar event (for reschedule/cancel)
            manage_token TEXT,                   -- unguessable token for client reschedule/cancel
            initiated_by TEXT DEFAULT 'operator', -- client_request | operator
            poll_attempts INTEGER DEFAULT 0,     -- transcript polls made (backoff + give-up)
            last_polled_at TEXT,
            bot_armed_at TEXT,                   -- when the capture bot was booked
            ical_sequence INTEGER DEFAULT 0,     -- SEQUENCE of the invite last sent
            confirmations_json TEXT              -- where each confirmation went, and what happened
        )"""
    )
    # ADR-0016: clients REQUEST, the operator SCHEDULES. Migrate existing meetings rows.
    mtg_cols = {r["name"] for r in conn.execute("PRAGMA table_info(meetings)")}
    for name, decl in {"meeting_type": "TEXT DEFAULT 'zoom'", "request_id": "INTEGER",
                       "client_name": "TEXT", "client_email": "TEXT",
                       "calendar_event_id": "TEXT", "manage_token": "TEXT",
                       "initiated_by": "TEXT DEFAULT 'operator'",
                       # Poll bookkeeping: without it the transcript poller has no way to
                       # back off or to stop, and a bot that finishes without a transcript
                       # is re-asked every 30s forever (see `poll_and_ingest`).
                       "poll_attempts": "INTEGER DEFAULT 0",
                       "last_polled_at": "TEXT",
                       # WHEN the capture bot was booked. A bot armed at booking time is
                       # an ad-hoc bot: it joins immediately, sits in an empty room and
                       # BILLS for the wait. This stamps the moment we armed, so a bot
                       # armed far from its call can be recognised as one of those and
                       # replaced instead of trusted.
                       "bot_armed_at": "TEXT",
                       # The iCalendar SEQUENCE of the invitation we last sent for this
                       # meeting. Every calendar client IGNORES an update whose SEQUENCE
                       # is not higher than the one it already holds, so a fixed number
                       # means the FIRST reschedule moves the block and no later one
                       # does — the invite is sent, accepted by the server, and silently
                       # discarded by the calendar.
                       "ical_sequence": "INTEGER DEFAULT 0",
                       # WHERE each confirmation went and WHAT the mailer said about it.
                       # Without this there is no answer anywhere to "did my invitation
                       # actually go out": the send status was returned and dropped on the
                       # floor, so a booking with no mail provider, a booking whose SMTP
                       # errored, and a booking that worked all looked identical — a page
                       # that simply reloaded.
                       "confirmations_json": "TEXT"}.items():
        if name not in mtg_cols:
            conn.execute(f"ALTER TABLE meetings ADD COLUMN {name} {decl}")
    # A Discovery Request is the client's ASK (ADR-0016) — it schedules nothing; the operator
    # reviews it and drives the Meeting Scheduler. One row per request, attached to the opp.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS discovery_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            name TEXT, email TEXT, company TEXT,
            preferred_type TEXT DEFAULT 'zoom',  -- zoom | phone
            message TEXT,
            status TEXT DEFAULT 'new',           -- new | scheduled | declined
            meeting_id INTEGER,                  -- set once the operator schedules it
            created_at TEXT, updated_at TEXT
        )"""
    )
    # A Meeting Proposal is the OPERATOR's offer of up to three times (ADR-0016 extended):
    # the client picks one, the pick books through the Meeting Scheduler, the other options
    # expire. slots_json is the per-record JSON state blob (house pattern): a list of
    # ISO-UTC strings. status: draft → sent → booked | expired | canceled.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS meeting_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            token TEXT,                          -- unguessable client link token
            slots_json TEXT DEFAULT '[]',        -- up to 3 ISO-UTC start times
            meeting_type TEXT DEFAULT 'zoom',    -- zoom | phone
            duration_min INTEGER DEFAULT 30,
            client_name TEXT, client_email TEXT,
            message TEXT,                        -- operator note woven into the email
            join_url TEXT,                       -- optional operator-pasted link
            request_id INTEGER,                  -- Discovery Request this answers (or null)
            status TEXT DEFAULT 'draft',         -- draft | sent | booked | expired | canceled
            chosen_slot TEXT,                    -- the ISO-UTC slot the client picked
            meeting_id INTEGER,                  -- the Meeting created by the pick
            subject_override TEXT DEFAULT '',    -- operator-edited subject ('' = use generated)
            body_override TEXT DEFAULT '',       -- operator-edited body   ('' = use generated)
            created_at TEXT, updated_at TEXT
        )"""
    )
    # "Review before it sends" means it's editable: the operator can rewrite the exact subject +
    # body the client will receive. Migrate existing proposal rows to carry the two override cols.
    mp_cols = {r["name"] for r in conn.execute("PRAGMA table_info(meeting_proposals)")}
    for name, decl in {"subject_override": "TEXT DEFAULT ''",
                       "body_override": "TEXT DEFAULT ''"}.items():
        if name not in mp_cols:
            conn.execute(f"ALTER TABLE meeting_proposals ADD COLUMN {name} {decl}")
    # Brief snapshots (ADR-0017): sending the Campaign Brief freezes the rendered doc —
    # the client opens what the operator approved, never a later re-render.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS brief_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            doc_json TEXT,
            created_at TEXT
        )"""
    )
    # Commercial Reviews (ADR-0018, Phase 1): the formal agreement, generated from Campaign
    # Intelligence and FROZEN at release (doc_json), so the client approves a stable version
    # and the approval binds to exactly what was shown. Re-release supersedes + bumps version.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS commercial_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            version INTEGER DEFAULT 1,
            doc_json TEXT,                       -- the frozen Review (the agreement record)
            status TEXT DEFAULT 'released',      -- released | superseded | approved | withdrawn
            released_by TEXT, released_at TEXT,
            created_at TEXT
        )"""
    )
    # Commercial approvals (ADR-0018): the client's electronic approval of a specific frozen
    # Review — the audit record and the primary award trigger. Phase 1 captures the essentials;
    # Phase 3 enriches (itemized approved scope/pricing/terms, DocuSign seam).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS commercial_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id INTEGER NOT NULL,
            review_id INTEGER NOT NULL,
            approver_name TEXT, approver_email TEXT,
            ip TEXT, user_agent TEXT,
            scope_ok INTEGER DEFAULT 0, pricing_ok INTEGER DEFAULT 0, terms_ok INTEGER DEFAULT 0,
            timeline_ok INTEGER DEFAULT 0,
            approved_at TEXT, created_at TEXT
        )"""
    )
    ca_cols = {r["name"] for r in conn.execute("PRAGMA table_info(commercial_approvals)")}
    if "timeline_ok" not in ca_cols:
        conn.execute("ALTER TABLE commercial_approvals ADD COLUMN timeline_ok INTEGER DEFAULT 0")
    # The objection library — the durable memory behind the Discovery Call Simulator.
    # Seeded from the five call simulations (docs/sales-simulations); GROWS from real
    # calls: objections harvested from transcripts land as status='proposed' with the
    # capture_id they came from (provenance), and the human confirms or retires them —
    # machine proposes, Jon disposes, same as Campaign Intelligence.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS objections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family TEXT NOT NULL,                -- trust_incumbency | cheap_alternatives |
                                                 --   guarantee_skepticism | delivery_risk |
                                                 --   money_process
            objection TEXT NOT NULL,
            context TEXT DEFAULT '',             -- when/why this comes up
            response_pattern TEXT DEFAULT '',    -- what works (playbook-derived)
            result TEXT DEFAULT 'untested',      -- yes | partial | no | untested
            source TEXT DEFAULT 'manual',        -- simulation | transcript | manual
            status TEXT DEFAULT 'confirmed',     -- proposed | confirmed | retired
            capture_id INTEGER,                  -- provenance when harvested from a call
            times_seen INTEGER DEFAULT 1,
            created_at TEXT, last_seen_at TEXT
        )"""
    )
    # Simulator practice sessions — one row per practice call; the transcript is a
    # per-record JSON blob (same pattern as projects.delivery_json) and the scorecard
    # is computed deterministically at end-of-call by simulator.grade().
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sim_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            persona TEXT NOT NULL,               -- key into simulator.PERSONAS
            mode TEXT DEFAULT 'scripted',        -- scripted (no LLM) | ai (Anthropic seam)
            status TEXT DEFAULT 'live',          -- live | ended
            transcript_json TEXT DEFAULT '[]',   -- [{"who":"buyer"|"seller","text":...}, ...]
            scorecard_json TEXT DEFAULT '',
            objections_used TEXT DEFAULT '[]',   -- objection ids already raised this session
            started_at TEXT, ended_at TEXT
        )"""
    )
    # Session Room (Living OS P5) — the ONE project event bus, append-only.
    # Every meaningful delivery act becomes an event; `audience` is the
    # server-side role filter (council ruling: filtering happens in the query,
    # never in the client). Roles: operator | client | talent.
    conn.execute(
        """CREATE TABLE IF NOT EXISTS project_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            kind TEXT NOT NULL,                  -- comment | version | approval | ...
            actor_role TEXT DEFAULT '',
            actor_name TEXT DEFAULT '',
            body TEXT DEFAULT '',
            audience TEXT DEFAULT 'operator,client,talent',
            created_at TEXT
        )"""
    )
    _ensure_person_links(conn)      # AFTER every table above exists
    _ensure_org_links(conn)         # likewise — several of its surfaces are created above
    _ensure_indexes(conn)
    conn.commit()


# --------------------------------------------------------------------------- #
# Indexes
# --------------------------------------------------------------------------- #
# There were none. Not "a few missing" — `CREATE INDEX` appeared **zero** times
# across 53 tables, so every lookup that was not by primary key read the whole
# table. Measured on a seeded database with EXPLAIN QUERY PLAN, 13 of 16 hot
# queries full-scanned, including both client-facing token lookups; the three that
# did not were covered by accident, through autoindexes SQLite creates for UNIQUE
# constraints, which is not a design.
#
# SQLite over a local file hid this: a scan of 200 rows in page cache is free, and
# the row counts here are small. Postgres over a network is a different machine —
# the scan is the same shape but every page of it crosses a socket, and it happens
# on a connection that was itself just opened. This is why the cutover is the
# moment it starts to matter, and why it belongs in front of the cutover.
#
# The set is DECLARED, not scattered: one list, so what is indexed can be read in
# one place and a new access path is a visible addition rather than a habit. Every
# entry is a real access path in the code, not a guess about future queries — an
# index nothing reads is pure write cost.
_INDEXES = (
    # Client-facing token lookups. Every review-portal and first-touch page load
    # begins with one of these, and they are the two most exposed queries we have.
    ("idx_projects_share_token", "projects(share_token)"),
    ("idx_opportunities_share_token", "opportunities(share_token)"),

    # Parent → children. These back the detail pages: open one project and the
    # console fans out into every one of these tables.
    ("idx_projects_opp", "projects(opp_id)"),
    ("idx_proposals_project", "proposals(project_id)"),
    ("idx_proposals_opp", "proposals(opp_id)"),
    ("idx_assignments_project", "assignments(project_id)"),
    ("idx_assignments_talent", "assignments(talent_id)"),
    ("idx_review_comments_project", "review_comments(project_id)"),
    ("idx_invoices_project", "invoices(project_id)"),
    ("idx_milestones_project", "milestones(project_id)"),
    ("idx_project_events_project", "project_events(project_id)"),
    ("idx_project_updates_project", "project_updates(project_id)"),
    ("idx_talent_payouts_talent", "talent_payouts(talent_id)"),
    ("idx_outreach_events_opp", "outreach_events(opp_id)"),
    ("idx_meetings_opp", "meetings(opp_id)"),
    ("idx_discovery_requests_opp", "discovery_requests(opp_id)"),
    ("idx_meeting_proposals_opp", "meeting_proposals(opp_id)"),
    ("idx_procurement_event_opp", "procurement_event(opp_id)"),
    ("idx_procurement_requirement_opp", "procurement_requirement(opp_id)"),
    ("idx_brief_progress_opp", "brief_progress(opp_id)"),
    ("idx_brief_snapshots_opp", "brief_snapshots(opp_id)"),
    ("idx_commercial_reviews_opp", "commercial_reviews(opp_id)"),
    ("idx_commercial_approvals_opp", "commercial_approvals(opp_id)"),
    ("idx_agency_outreach_agency", "agency_outreach(agency_id)"),
    ("idx_agency_memory_agency", "agency_memory(agency_id)"),
    ("idx_agency_tasks_agency", "agency_tasks(agency_id)"),
    ("idx_agency_documents_agency", "agency_documents(agency_id)"),
    ("idx_relationships_agency", "relationships(agency_id)"),
    ("idx_opportunity_signals_agency", "opportunity_signals(agency_id)"),
    ("idx_campaigns_project", "campaigns(project_id)"),
    ("idx_campaigns_opp", "campaigns(opp_id)"),
    ("idx_campaign_direction_campaign", "campaign_direction(campaign_id)"),
    ("idx_campaign_intelligence_opp", "campaign_intelligence(opp_id)"),
    ("idx_campaign_intelligence_campaign", "campaign_intelligence(campaign_id)"),
    ("idx_captures_ci", "captures(ci_id)"),
    ("idx_ci_event_ci", "campaign_intelligence_event(ci_id)"),
    ("idx_producer_learning_ci", "producer_learning_event(ci_id)"),

    # List filters. These drive the pipeline, the queue and the money pages, which
    # are the screens the operator lives on.
    ("idx_opportunities_status", "opportunities(status)"),
    ("idx_opportunities_qualified", "opportunities(qualified)"),
    ("idx_opportunities_action", "opportunities(action)"),
    ("idx_opportunities_agency", "opportunities(agency_id)"),
    ("idx_projects_status", "projects(status)"),
    ("idx_invoices_status", "invoices(status)"),
    ("idx_proposals_status", "proposals(status)"),
    ("idx_signals_status", "signals(status)"),
    ("idx_signals_type", "signals(signal_type)"),
    ("idx_signals_linked_opp", "signals(linked_opp_id)"),
    ("idx_inbound_leads_status", "inbound_leads(status)"),
    ("idx_crawl_targets_status", "crawl_targets(status)"),
    ("idx_talent_review_status", "talent(review_status)"),
    ("idx_agency_tasks_status", "agency_tasks(status)"),

    # Buyer identity (ADR-0050): `person_touchpoints` asks each of these "what has this
    # human done", which is a scan of every one of them without these.
    ("idx_decision_makers_person", "decision_makers(person_id)"),
    ("idx_discovery_requests_person", "discovery_requests(person_id)"),
    ("idx_meetings_person", "meetings(person_id)"),
    ("idx_meeting_proposals_person", "meeting_proposals(person_id)"),
    ("idx_review_comments_person", "review_comments(person_id)"),

    # The decision log (ADR-0053) is written on every state change and read by
    # subject — "what happened to this project" must not be a table scan of every
    # decision ever made.
    ("idx_decision_log_subject", "decision_log(subject_type, subject_id)"),
    ("idx_decision_log_at", "decision_log(at)"),
    ("idx_user_session_user", "user_session(user_id)"),
    # ADR-0056 — the org link is read per surface on every relationship view, and the
    # backfill scans for the un-linked ones on every boot.
    ("idx_opportunities_org", "opportunities(org_id)"),
    ("idx_projects_org", "projects(org_id)"),
    ("idx_agencies_org", "agencies(org_id)"),
    ("idx_buyer_org_agency", "buyer_org(agency_id)"),
    # ADR-0059 — every delivery page asks "is this signed, and does it still match".
    ("idx_signature_project", "signature(project_id, doc_kind)"),
    ("idx_signature_opportunity", "signature(opportunity_id, doc_kind)"),
    ("idx_signature_talent", "signature(talent_id, doc_kind)"),
    ("idx_signature_contributor", "signature(contributor_id, doc_kind)"),
    ("idx_contributors_project", "contributors(project_id)"),
)


def _ensure_person_links(conn) -> None:
    """Stamp the canonical-person column on every surface that names a human.

    Runs at the END of the migration on purpose: several of these tables are created
    further down `_ensure_schema` than the buyer_person table is, and an ALTER against
    a table that does not exist yet takes the whole boot down (it did).
    """
    for table, _e, _n, _l, _w in _PERSON_SURFACES:
        try:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except Exception:                   # noqa: BLE001 — not in this database
            continue
        if cols and "person_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN person_id INTEGER")


def _ensure_org_links(conn) -> None:
    """Stamp the canonical-organisation column on every surface that names one.

    Runs at the end of the migration for the same reason `_ensure_person_links` does:
    an ALTER against a table created further down takes the whole boot down.
    """
    for table, _pk, _n, _d, _l, _w in _ORG_SURFACES:
        try:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except Exception:                   # noqa: BLE001 — not in this database
            continue
        if cols and "org_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER")


def _ensure_indexes(conn) -> None:
    """Create every declared index, idempotently, on both backends.

    Best-effort per index: a table that does not exist on some older database must
    not stop the other forty from being created, and an index is never worth failing
    a boot over.
    """
    for name, target in _INDEXES:
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {target}")
        except Exception:                   # noqa: BLE001 — see docstring
            try: conn.rollback()
            except Exception: pass


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


def apply_intelligence_to_opportunity(
        conn: sqlite3.Connection, opp_id: int, *, need: Optional[str] = None,
        client: Optional[str] = None, budget_min: Optional[float] = None,
        budget_max: Optional[float] = None) -> None:
    """Write confirmed Campaign Intelligence engagement facts back to the opportunity's
    OWN columns and RE-EVALUATE (ADR-0013). Because qualification/estimate/brief/outreach
    all read the opportunity, this is what makes them recompute from one source — no
    separate 'refresh', no divergent copy. Only provided fields change."""
    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    if row is None:
        return
    opp = opportunity_from_row(row)
    if need is not None and need.strip():
        opp.need = need.strip()
    if client is not None and client.strip():
        opp.client = client.strip()
    if budget_min is not None:
        opp.budget_min = budget_min
    if budget_max is not None:
        opp.budget_max = budget_max
    q, s = evaluate(opp)
    sv = assess_strategic_value(opp)
    conn.execute(
        """UPDATE opportunities
           SET need = ?, client = ?, budget_min = ?, budget_max = ?,
               qualified = ?, discipline = ?, alignment = ?, action = ?, confidence = ?,
               needs_review = ?, score = ?, tier = ?, win_probability = ?,
               strategic_value = ?, strategic_tier = ?
           WHERE id = ?""",
        (opp.need, opp.client, opp.budget_min, opp.budget_max,
         int(q.qualified), q.discipline.value, q.alignment_pct,
         q.recommended_action.value, q.confidence.value, int(q.needs_human_review),
         s.score, s.tier.value, s.win_probability.value, sv.score, sv.tier, opp_id))
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
    if status == "open":
        # "In flight" — the SAME states the open-pipeline number counts (ADR-0030),
        # so the dashboard KPI and the list it links to cannot disagree. The KPI used
        # to link to the kanban, which showed every deal including Won and Closed.
        clauses.append("status IN (%s)" % ",".join("?" for _ in OPEN_PIPELINE_STATES))
        params.extend(OPEN_PIPELINE_STATES)
    elif status:
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
    # COALESCE, not a bare assignment: most callers move the stage without carrying a
    # value (the board and the stepper post status alone), and a bare assignment wrote
    # NULL over the recorded number — marking a deal Won erased what it was worth.
    # Only an explicitly supplied value overwrites.
    conn.execute(
        "UPDATE opportunities SET status = ?, outcome_value = COALESCE(?, outcome_value) "
        "WHERE id = ?",
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
    token = public_token(13)
    conn.execute(
        "UPDATE opportunities SET share_token = ? WHERE id = ?", (token, opp_id)
    )
    conn.commit()
    return token


def rotate_share_token(conn: sqlite3.Connection, *, opp_id=None, project_id=None) -> Optional[str]:
    """Mint a fresh client link for a deal and kill the old one. Returns the new token.

    **Rotates BOTH records.** A deal can carry two live credentials — the
    opportunity's (the brief / first-touch page) and the project's (the delivery
    portal) — and ADR-0018 has them share one value on the normal award path. Left
    to one, the other keeps opening the same work: rotating half a credential is
    not rotating it. Pass either id; the linked record is found and rotated too.

    Returns ``None`` when neither id resolves. Reviewer ``?r=`` links are a separate
    credential with their own revocation (:func:`remove_delivery_reviewer`) and are
    deliberately untouched — revoking one person is not the same act as cutting a
    leaked link, and conflating them would make the safe action destructive.
    """
    if opp_id is None and project_id is None:
        return None
    if opp_id is None:
        prow = conn.execute(
            "SELECT opp_id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if prow is None:
            return None
        opp_id = prow["opp_id"]
    if project_id is None and opp_id is not None:
        prow = conn.execute(
            "SELECT id FROM projects WHERE opp_id = ?", (opp_id,)).fetchone()
        project_id = prow["id"] if prow is not None else None
    if opp_id is None and project_id is None:
        return None

    token = public_token(13)
    stamp = datetime.now(timezone.utc).isoformat()
    touched = 0
    if opp_id is not None:
        touched += conn.execute(
            "UPDATE opportunities SET share_token = ?, share_token_rotated_at = ? "
            "WHERE id = ?", (token, stamp, opp_id)).rowcount
    if project_id is not None:
        touched += conn.execute(
            "UPDATE projects SET share_token = ?, share_token_rotated_at = ? "
            "WHERE id = ?", (token, stamp, project_id)).rowcount
    if not touched:
        return None
    conn.commit()
    return token


def opportunity_by_share_token(conn: sqlite3.Connection, token: str):
    """Resolve the opportunity that owns a workspace/share token (ADR-0018). The token is
    the durable Client Workspace key — minted on the opp, inherited by its project."""
    if not (token or "").strip():
        return None
    return conn.execute(
        "SELECT * FROM opportunities WHERE share_token = ? LIMIT 1", (token,)).fetchone()


def project_by_share_token(conn: sqlite3.Connection, token: str):
    """Resolve a project by its share token. A project created from an opportunity inherits
    the opp's token, so this and :func:`opportunity_by_share_token` resolve the same deal."""
    if not (token or "").strip():
        return None
    return conn.execute(
        "SELECT * FROM projects WHERE share_token = ? LIMIT 1", (token,)).fetchone()


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
    blank = value is None or (isinstance(value, str) and not value.strip())
    # Same one-statement merge as `update_delivery`, for the same reason: this is the
    # client-facing document, edited field by field, and a read-modify-write drops
    # whichever edit lost the race with no error on either side.
    merge_json_key(conn, "opportunities", opp_id, "doc_overrides", key,
                   None if blank else value)
    return get_doc_overrides(conn, opp_id)


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
    """One aggregated row per buyer for the Buyer Graph directory.

    `org_id` rides along (ADR-0056) so the caller can reach the same company's Agency
    Intelligence record and its outreach log — the evidence this query cannot see, and
    the reason this page and /relationships used to disagree.
    """
    return conn.execute(
        """
        SELECT
            o.client AS client,
            MAX(o.org_id) AS org_id,
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


# --------------------------------------------------------------------------- #
# Harvested agencies + per-source crawl checkpoint (directory agents)
# --------------------------------------------------------------------------- #
def upsert_agency(conn: sqlite3.Connection, source: str, rec: Dict) -> bool:
    """Insert an agency, or refresh it if (source, dedup_key) already exists.
    Returns True if a NEW row was created, False if an existing one was updated —
    so a crawl can report new-vs-duplicate without piling up copies."""
    key = (rec.get("dedup_key") or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    exists = conn.execute(
        "SELECT id FROM agencies WHERE source = ? AND dedup_key = ?", (source, key)
    ).fetchone()
    cols = ("company", "website", "employees", "location", "description",
            "industries", "source_url")
    vals = [rec.get(c) or "" for c in cols]
    if exists:
        conn.execute(
            f"UPDATE agencies SET {', '.join(f'{c}=?' for c in cols)}, updated_at=? "
            "WHERE id=?", (*vals, now, exists["id"]),
        )
        return False
    conn.execute(
        f"INSERT INTO agencies (source, dedup_key, {', '.join(cols)}, created_at, updated_at) "
        f"VALUES (?,?,{','.join('?' * len(cols))},?,?)",
        (source, key, *vals, now, now),
    )
    return True


def count_agencies(conn: sqlite3.Connection, source: Optional[str] = None) -> int:
    if source:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM agencies WHERE source = ?", (source,)
        ).fetchone()["n"]
    return conn.execute("SELECT COUNT(*) AS n FROM agencies").fetchone()["n"]


def list_agencies(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 1000,
    offset: int = 0
) -> List[sqlite3.Row]:
    clause = " WHERE source = ?" if source else ""
    tail = " ORDER BY company COLLATE NOCASE LIMIT ? OFFSET ?"
    params = ((source, limit, offset) if source else (limit, offset))
    return conn.execute(f"SELECT * FROM agencies{clause}{tail}", params).fetchall()


def get_crawl_state(conn: sqlite3.Connection, source_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM crawl_state WHERE source_key = ?", (source_key,)
    ).fetchone()


def save_crawl_state(conn: sqlite3.Connection, source_key: str, **fields) -> None:
    """Upsert a source's crawl checkpoint. Committed by the caller (the engine
    commits after every page so an interruption resumes from the next page)."""
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    if get_crawl_state(conn, source_key) is None:
        conn.execute("INSERT INTO crawl_state (source_key) VALUES (?)", (source_key,))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE crawl_state SET {sets} WHERE source_key=?",
            (*fields.values(), source_key),
        )


def reset_crawl_state(conn: sqlite3.Connection, source_key: str) -> None:
    """Start a source's crawl over from page 1 (clears the checkpoint counters)."""
    save_crawl_state(conn, source_key, status="idle", next_page=1, total_pages=None,
                     pages_done=0, records_new=0, records_seen=0, last_url="", detail="")


def get_agency(conn: sqlite3.Connection, agency_id: int) -> Optional[sqlite3.Row]:
    """One harvested agency by id — the Company Enrichment Engine's input record."""
    return conn.execute(
        "SELECT * FROM agencies WHERE id = ?", (agency_id,)
    ).fetchone()


def get_agency_enrichment(conn: sqlite3.Connection, agency_id: int) -> dict:
    """The agency's enrichment state blob (agencies.enrichment_json), or {}.

    Shape (written by the Company Enrichment Engine):
      {"status": str, "steps_done": [str], "detail": str,
       "links": [[url, anchor, concept], ...],   # discovered page map
       "profile": {...AgencyProfile.to_dict()}}
    Committing after each micro-agent is what makes enrichment resumable."""
    row = conn.execute(
        "SELECT enrichment_json FROM agencies WHERE id = ?", (agency_id,)
    ).fetchone()
    if not row or not row["enrichment_json"]:
        return {}
    try:
        return json.loads(row["enrichment_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def save_agency_enrichment(
    conn: sqlite3.Connection, agency_id: int, state: dict
) -> None:
    """Persist the agency's enrichment state. The caller commits (the engine
    commits after every micro-agent so an interruption resumes mid-pipeline)."""
    conn.execute(
        "UPDATE agencies SET enrichment_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state), datetime.now(timezone.utc).isoformat(), agency_id),
    )


def reset_agency_enrichment(conn: sqlite3.Connection, agency_id: int) -> None:
    """Clear an agency's enrichment so the next run starts from the homepage."""
    save_agency_enrichment(conn, agency_id, {})


# --------------------------------------------------------------------------- #
# Decision makers — the people worth contacting at each agency
# --------------------------------------------------------------------------- #
def upsert_decision_maker(conn: sqlite3.Connection, agency_id: int, rec: Dict) -> bool:
    """Insert a decision maker, or refresh it if (agency_id, dedup_key) exists.
    Returns True if a NEW row was created. List/dict fields (social, source_urls)
    are passed through as already-serialized JSON strings by the caller."""
    key = (rec.get("dedup_key") or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    cols = ("name", "title", "department", "office", "reports_to", "bio",
            "photo_url", "linkedin", "email", "phone", "social_json",
            "source_urls_json", "press_json", "role_category", "priority",
            "music_relevance", "relevance_reason", "confidence",
            "linkedin_verified", "classified_by", "last_verified")
    vals = [rec.get(c) if rec.get(c) is not None else "" for c in cols]
    exists = conn.execute(
        "SELECT id FROM decision_makers WHERE agency_id = ? AND dedup_key = ?",
        (agency_id, key)).fetchone()
    if exists:
        conn.execute(
            f"UPDATE decision_makers SET {', '.join(f'{c}=?' for c in cols)}, "
            "updated_at=? WHERE id=?", (*vals, now, exists["id"]))
        return False
    conn.execute(
        f"INSERT INTO decision_makers (agency_id, dedup_key, {', '.join(cols)}, "
        f"created_at, updated_at) VALUES (?,?,{','.join('?' * len(cols))},?,?)",
        (agency_id, key, *vals, now, now))
    return True


def list_decision_makers(
    conn: sqlite3.Connection, agency_id: int
) -> List[sqlite3.Row]:
    """An agency's decision makers, most relevant first (priority then confidence).
    The scoring engine decides who matters; this is just a sensible default order."""
    return conn.execute(
        """SELECT * FROM decision_makers WHERE agency_id = ?
           ORDER BY CASE priority
                      WHEN 'Very High' THEN 0 WHEN 'High' THEN 1
                      WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3
                      WHEN 'Very Low' THEN 4 ELSE 5 END,
                    confidence DESC, name COLLATE NOCASE""",
        (agency_id,)).fetchall()


def count_decision_makers(
    conn: sqlite3.Connection, agency_id: Optional[int] = None
) -> int:
    if agency_id is None:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM decision_makers").fetchone()["n"]
    return conn.execute(
        "SELECT COUNT(*) AS n FROM decision_makers WHERE agency_id = ?",
        (agency_id,)).fetchone()["n"]


def delete_decision_makers(conn: sqlite3.Connection, agency_id: int) -> None:
    """Clear an agency's decision makers so a discovery run starts clean (reset)."""
    conn.execute("DELETE FROM decision_makers WHERE agency_id = ?", (agency_id,))


def get_agency_dm(conn: sqlite3.Connection, agency_id: int) -> dict:
    """The agency's decision-maker discovery marker (agencies.dm_json), or {}.
    Shape: {"status": str, "found": int, "total": int, "last_run": iso}."""
    row = conn.execute(
        "SELECT dm_json FROM agencies WHERE id = ?", (agency_id,)).fetchone()
    if not row or not row["dm_json"]:
        return {}
    try:
        return json.loads(row["dm_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def save_agency_dm(conn: sqlite3.Connection, agency_id: int, state: dict) -> None:
    """Persist the agency's decision-maker discovery marker. Caller commits."""
    conn.execute(
        "UPDATE agencies SET dm_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state), datetime.now(timezone.utc).isoformat(), agency_id))


def get_agency_intel(conn: sqlite3.Connection, agency_id: int) -> dict:
    """The agency's Company Intelligence Profile (agencies.intel_json), or {}.
    Shape: each intelligence field is {"value", "evidence": [str], "confidence"}
    plus "overall_confidence", "status", "generated_at" — see intelligence.py."""
    row = conn.execute(
        "SELECT intel_json FROM agencies WHERE id = ?", (agency_id,)).fetchone()
    if not row or not row["intel_json"]:
        return {}
    try:
        return json.loads(row["intel_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def save_agency_intel(conn: sqlite3.Connection, agency_id: int, state: dict) -> None:
    """Persist the agency's Company Intelligence Profile. Caller commits."""
    conn.execute(
        "UPDATE agencies SET intel_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state), datetime.now(timezone.utc).isoformat(), agency_id))


def agencies_needing_intelligence(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 100000
) -> List[sqlite3.Row]:
    """Agencies ready for an intelligence pass: enrichment has completed (the
    engine consumes the enriched profile) and intelligence isn't done yet. Gating
    on enrichment keeps the chain in order: crawl → enrich → decision makers →
    intelligence, each advancing its own queue."""
    # Filter in SQL (mirrors count_needing_intelligence) instead of scanning the
    # whole table and JSON-parsing every blob in Python: enrichment complete AND
    # intelligence not complete. The LIKE markers match the stored blob format and
    # are portable across the SQLite/Postgres backends (same as the count funcs).
    src, sp = _src(source)
    return conn.execute(
        "SELECT * FROM agencies WHERE COALESCE(enrichment_json,'') LIKE ? "
        "AND COALESCE(intel_json,'') NOT LIKE ?" + src + " ORDER BY id LIMIT ?",
        (_DONE, _DONE, *sp, limit)).fetchall()


# --------------------------------------------------------------------------- #
# Opportunity signals — the change-detected timeline + its baseline snapshot
# --------------------------------------------------------------------------- #
def get_agency_signal_snapshot(conn: sqlite3.Connection, agency_id: int) -> dict:
    """The agency's Signal Detection snapshot (agencies.signals_json), or {}."""
    row = conn.execute(
        "SELECT signals_json FROM agencies WHERE id = ?", (agency_id,)).fetchone()
    if not row or not row["signals_json"]:
        return {}
    try:
        return json.loads(row["signals_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def save_agency_signal_snapshot(
    conn: sqlite3.Connection, agency_id: int, snapshot: dict
) -> None:
    """Persist the snapshot and stamp signals_scanned_at (rotates the scan queue)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE agencies SET signals_json = ?, signals_scanned_at = ?, updated_at = ? "
        "WHERE id = ?", (json.dumps(snapshot), now, now, agency_id))


def insert_opportunity_signal(conn: sqlite3.Connection, agency_id: int, sig: dict) -> bool:
    """Insert one signal; ignore it if (agency_id, dedup_key) already exists (the
    timeline never stores the same change twice). Returns True if newly inserted."""
    key = (sig.get("dedup_key") or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    if conn.execute("SELECT 1 FROM opportunity_signals WHERE agency_id=? AND dedup_key=?",
                    (agency_id, key)).fetchone():
        return False
    conn.execute(
        """INSERT INTO opportunity_signals
           (agency_id, dedup_key, event_type, category, importance, music_relevance,
            confidence, summary, source, source_url, evidence_json,
            event_date, detected_at, expires_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (agency_id, key, sig.get("event_type", ""), sig.get("category", ""),
         sig.get("importance", ""), sig.get("music_relevance", ""),
         int(sig.get("confidence") or 0), sig.get("summary", ""),
         sig.get("source", ""), sig.get("source_url", ""),
         json.dumps(sig.get("evidence") or []),
         sig.get("event_date") or now, sig.get("detected_at") or now,
         sig.get("expires_at") or "", now))
    return True


def list_opportunity_signals(
    conn: sqlite3.Connection, agency_id: int, *, active_only: bool = False
) -> List[sqlite3.Row]:
    """An agency's opportunity timeline, newest first. ``active_only`` hides signals
    whose expiry has passed (a stale signal isn't a live opportunity)."""
    rows = conn.execute(
        "SELECT * FROM opportunity_signals WHERE agency_id = ? "
        "ORDER BY detected_at DESC, id DESC", (agency_id,)).fetchall()
    if not active_only:
        return rows
    now = datetime.now(timezone.utc).isoformat()
    return [r for r in rows if not r["expires_at"] or r["expires_at"] >= now]


def count_opportunity_signals(
    conn: sqlite3.Connection, agency_id: Optional[int] = None, *, active_only: bool = False
) -> int:
    where, params = [], []
    if agency_id is not None:
        where.append("agency_id = ?"); params.append(agency_id)
    if active_only:
        where.append("(expires_at = '' OR expires_at >= ?)")
        params.append(datetime.now(timezone.utc).isoformat())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM opportunity_signals{clause}", params).fetchone()["n"]


def recent_opportunity_signals(
    conn: sqlite3.Connection, *, limit: int = 100, active_only: bool = True
) -> List[sqlite3.Row]:
    """The freshest signals across ALL agencies — the cross-agency feed."""
    rows = conn.execute(
        """SELECT s.*, a.company AS agency_name FROM opportunity_signals s
           JOIN agencies a ON a.id = s.agency_id
           ORDER BY s.detected_at DESC, s.id DESC LIMIT ?""", (limit * 4,)).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    if active_only:
        rows = [r for r in rows if not r["expires_at"] or r["expires_at"] >= now]
    return rows[:limit]


def agencies_for_signal_scan(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 100
) -> List[sqlite3.Row]:
    """Enriched agencies due for a signal scan, least-recently-scanned first (so a
    bounded background pass rotates through the whole DB). Signal detection re-runs
    over time — a cheap fingerprint check skips anything that hasn't changed."""
    # Filter in SQL (enrichment complete) instead of scanning + parsing every blob;
    # least-recently-scanned first so a bounded pass still rotates the whole DB.
    src, sp = _src(source)
    return conn.execute(
        "SELECT * FROM agencies WHERE COALESCE(enrichment_json,'') LIKE ?" + src +
        " ORDER BY signals_scanned_at IS NULL DESC, signals_scanned_at ASC, id LIMIT ?",
        (_DONE, *sp, limit)).fetchall()


# --------------------------------------------------------------------------- #
# Relationship history / outreach to an agency
# --------------------------------------------------------------------------- #
def log_agency_outreach(
    conn: sqlite3.Connection, agency_id: int, *, kind: str = "email",
    direction: str = "out", responded: bool = False, contact: str = "",
    note: str = "", occurred_at: Optional[str] = None
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO agency_outreach
           (agency_id, kind, direction, occurred_at, responded, contact, note, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (agency_id, kind, direction, occurred_at or now, 1 if responded else 0,
         contact, note, now))


def list_agency_outreach(conn: sqlite3.Connection, agency_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM agency_outreach WHERE agency_id = ? ORDER BY occurred_at DESC",
        (agency_id,)).fetchall()


def last_agency_outreach(
    conn: sqlite3.Connection, agency_id: int, direction: str = "out"
) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM agency_outreach WHERE agency_id = ? AND direction = ? "
        "ORDER BY occurred_at DESC LIMIT 1", (agency_id, direction)).fetchone()


def outreach_aggregate(conn: sqlite3.Connection, agency_ids) -> dict:
    """Per-agency outreach rollup — {agency_id: {last_touch, responded, count}} — in
    ONE GROUP BY query for the whole set, instead of a SELECT per agency. Powers the
    /relationships pipeline's stage derivation at O(1) queries."""
    ids = [int(a) for a in agency_ids]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict = {}
    for r in conn.execute(
            f"""SELECT agency_id, MAX(occurred_at) AS last_touch,
                       MAX(responded) AS any_responded, COUNT(*) AS n
                FROM agency_outreach WHERE agency_id IN ({marks})
                GROUP BY agency_id""", tuple(ids)):
        out[r["agency_id"]] = {
            "last_touch": r["last_touch"],
            "responded": bool(r["any_responded"]),
            "count": r["n"],
        }
    return out


def relationships_by_ids(conn: sqlite3.Connection, agency_ids) -> dict:
    """{agency_id: relationship_row} for a set of agencies in ONE query (vs a
    get_relationship per agency)."""
    ids = [int(a) for a in agency_ids]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["agency_id"]: r for r in conn.execute(
        f"SELECT * FROM relationships WHERE agency_id IN ({marks})", tuple(ids))}


# --------------------------------------------------------------------------- #
# Relationship Management Platform — stage, tasks, memory, documents
# --------------------------------------------------------------------------- #
def get_relationship(conn: sqlite3.Connection, agency_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM relationships WHERE agency_id = ?", (agency_id,)).fetchone()


def upsert_relationship(conn: sqlite3.Connection, agency_id: int, **fields) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if get_relationship(conn, agency_id) is None:
        conn.execute(
            "INSERT INTO relationships (agency_id, created_at, updated_at) VALUES (?,?,?)",
            (agency_id, now, now))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE relationships SET {sets}, updated_at=? WHERE agency_id=?",
                     (*fields.values(), now, agency_id))


def cache_relationship_stage(conn: sqlite3.Connection, agency_id: int, stage: str,
                             *, exists: bool) -> None:
    """Write the derived stage when the caller ALREADY knows whether the row is there.

    `upsert_relationship` asks — a SELECT per call — which is right when you have one
    agency and wrong on `/relationships`, where the batch has just fetched every
    relationship row in one query and then paid for a lookup per agency anyway. Same
    write, without re-asking a question already answered.
    """
    now = datetime.now(timezone.utc).isoformat()
    if not exists:
        conn.execute(
            "INSERT INTO relationships (agency_id, created_at, updated_at) VALUES (?,?,?)",
            (agency_id, now, now))
    conn.execute("UPDATE relationships SET stage=?, updated_at=? WHERE agency_id=?",
                 (stage, now, agency_id))


def add_agency_task(conn: sqlite3.Connection, agency_id: int, *, title: str,
                    kind: str = "task", due_at: str = "", source: str = "manual") -> None:
    conn.execute(
        """INSERT INTO agency_tasks (agency_id, title, kind, due_at, status, source, created_at)
           VALUES (?,?,?,?,'open',?,?)""",
        (agency_id, title, kind, due_at, source,
         datetime.now(timezone.utc).isoformat()))


def list_agency_tasks(conn: sqlite3.Connection, agency_id: int,
                      status: Optional[str] = None) -> List[sqlite3.Row]:
    clause = " AND status = ?" if status else ""
    params = ((agency_id, status) if status else (agency_id,))
    return conn.execute(
        f"SELECT * FROM agency_tasks WHERE agency_id = ?{clause} "
        "ORDER BY (due_at = '') ASC, due_at ASC, id DESC", params).fetchall()


def complete_agency_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE agency_tasks SET status='done', done_at=? WHERE id=?",
                 (datetime.now(timezone.utc).isoformat(), task_id))


def has_open_followup(conn: sqlite3.Connection, agency_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM agency_tasks WHERE agency_id=? AND kind='followup' AND status='open'",
        (agency_id,)).fetchone() is not None


def overdue_tasks(conn: sqlite3.Connection, limit: int = 100) -> List[sqlite3.Row]:
    now = datetime.now(timezone.utc).isoformat()
    return conn.execute(
        """SELECT t.*, a.company AS agency_name FROM agency_tasks t
           JOIN agencies a ON a.id = t.agency_id
           WHERE t.status='open' AND t.due_at != '' AND t.due_at < ?
           ORDER BY t.due_at ASC LIMIT ?""", (now, limit)).fetchall()


def upcoming_tasks(conn: sqlite3.Connection, limit: int = 100) -> List[sqlite3.Row]:
    return conn.execute(
        """SELECT t.*, a.company AS agency_name FROM agency_tasks t
           JOIN agencies a ON a.id = t.agency_id
           WHERE t.status='open'
           ORDER BY (t.due_at = '') ASC, t.due_at ASC LIMIT ?""", (limit,)).fetchall()


def count_open_tasks(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM agency_tasks WHERE status='open'").fetchone()["n"]


def add_agency_memory(conn: sqlite3.Connection, agency_id: int, *, fact: str,
                      contact: str = "", source: str = "manual") -> bool:
    """Add a relationship-memory fact, skipping an exact duplicate (so auto-seeded
    facts aren't re-added on every view). Returns True if newly added."""
    if conn.execute("SELECT 1 FROM agency_memory WHERE agency_id=? AND fact=?",
                    (agency_id, fact)).fetchone():
        return False
    conn.execute(
        "INSERT INTO agency_memory (agency_id, contact, fact, source, created_at) "
        "VALUES (?,?,?,?,?)",
        (agency_id, contact, fact, source, datetime.now(timezone.utc).isoformat()))
    return True


def list_agency_memory(conn: sqlite3.Connection, agency_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM agency_memory WHERE agency_id = ? ORDER BY created_at DESC",
        (agency_id,)).fetchall()


def add_agency_document(conn: sqlite3.Connection, agency_id: int, *, title: str,
                        url: str = "", note: str = "") -> None:
    conn.execute(
        "INSERT INTO agency_documents (agency_id, title, url, note, created_at) "
        "VALUES (?,?,?,?,?)",
        (agency_id, title, url, note, datetime.now(timezone.utc).isoformat()))


def list_agency_documents(conn: sqlite3.Connection, agency_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM agency_documents WHERE agency_id = ? ORDER BY created_at DESC",
        (agency_id,)).fetchall()


# --------------------------------------------------------------------------- #
# Music Opportunity Engine — the explainable score + its queue/rankings
# --------------------------------------------------------------------------- #
def save_agency_score(
    conn: sqlite3.Connection, agency_id: int, *, score: int, tier: str,
    movement: int, blob: dict
) -> None:
    """Persist the headline score columns (for ranking) + the full breakdown blob.
    Caller commits."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE agencies SET opportunity_score=?, opportunity_tier=?, "
        "score_movement=?, scored_at=?, opportunity_score_json=?, updated_at=? "
        "WHERE id=?",
        (int(score), tier, int(movement), now, json.dumps(blob), now, agency_id))


def get_agency_score(conn: sqlite3.Connection, agency_id: int) -> dict:
    """The agency's full Music Opportunity breakdown (opportunity_score_json), or {}."""
    row = conn.execute(
        "SELECT opportunity_score_json FROM agencies WHERE id = ?", (agency_id,)).fetchone()
    if not row or not row["opportunity_score_json"]:
        return {}
    try:
        return json.loads(row["opportunity_score_json"])
    except (json.JSONDecodeError, TypeError):
        return {}


def agencies_to_score(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 100
) -> List[sqlite3.Row]:
    """Agencies with a Company Intelligence profile, least-recently-scored first so
    a bounded pass rotates through the DB. Scoring re-runs over time (the score is
    alive) — gating on intelligence keeps the chain ordered."""
    # Filter in SQL (intelligence complete) instead of scanning + parsing every blob;
    # least-recently-scored first so a bounded pass still rotates the whole DB.
    src, sp = _src(source)
    return conn.execute(
        "SELECT * FROM agencies WHERE COALESCE(intel_json,'') LIKE ?" + src +
        " ORDER BY scored_at IS NULL DESC, scored_at ASC, id LIMIT ?",
        (_DONE, *sp, limit)).fetchall()


def top_opportunities(
    conn: sqlite3.Connection, *, limit: int = 25, source: Optional[str] = None
) -> List[sqlite3.Row]:
    """Highest-scoring agencies — the prioritized pursuit list."""
    clause = "WHERE opportunity_score IS NOT NULL"
    params: list = []
    if source:
        clause += " AND source = ?"; params.append(source)
    return conn.execute(
        f"SELECT * FROM agencies {clause} "
        "ORDER BY opportunity_score DESC, score_movement DESC LIMIT ?",
        (*params, limit)).fetchall()


def top_movers(
    conn: sqlite3.Connection, *, limit: int = 10, source: Optional[str] = None
) -> List[sqlite3.Row]:
    """Agencies whose score moved most since the previous run (the "what changed
    this week" feed) — biggest risers first."""
    clause = "WHERE score_movement IS NOT NULL AND score_movement != 0"
    params: list = []
    if source:
        clause += " AND source = ?"; params.append(source)
    return conn.execute(
        f"SELECT * FROM agencies {clause} ORDER BY score_movement DESC LIMIT ?",
        (*params, limit)).fetchall()


# --------------------------------------------------------------------------- #
# Cheap status counts — COUNT(*) with a JSON marker, NO blob loading and NO
# Python materialization, so the dashboard / status cards / page loads don't scan
# 12k full rows (with their large JSON columns) into memory on every request.
# --------------------------------------------------------------------------- #
_DONE = '%"status": "complete"%'
_ERR = '%"status": "error"%'


def _count(conn: sqlite3.Connection, where: str, params: tuple) -> int:
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM agencies WHERE {where}", params).fetchone()["n"]


def _src(source: Optional[str]) -> tuple:
    return (" AND source = ?", (source,)) if source else ("", ())


def count_needing_enrichment(conn, source: Optional[str] = None) -> int:
    s, p = _src(source)
    return _count(conn, "TRIM(COALESCE(website,'')) != '' "
                  "AND COALESCE(enrichment_json,'') NOT LIKE ? "
                  "AND COALESCE(enrichment_json,'') NOT LIKE ?" + s, (_DONE, _ERR, *p))


def count_needing_decision_makers(conn, source: Optional[str] = None) -> int:
    s, p = _src(source)
    return _count(conn, "TRIM(COALESCE(website,'')) != '' "
                  "AND COALESCE(dm_json,'') NOT LIKE ? "
                  "AND COALESCE(dm_json,'') NOT LIKE ?" + s, (_DONE, _ERR, *p))


def count_needing_intelligence(conn, source: Optional[str] = None) -> int:
    s, p = _src(source)
    return _count(conn, "COALESCE(enrichment_json,'') LIKE ? "
                  "AND COALESCE(intel_json,'') NOT LIKE ?" + s, (_DONE, _DONE, *p))


def agencies_due_for_reenrichment(
    conn: sqlite3.Connection, source: Optional[str] = None, stale_days: int = 7,
    limit: int = 1000
) -> List[sqlite3.Row]:
    """Enriched agencies whose data has gone stale (last_enriched older than
    ``stale_days``, or never timestamped). Iterates in id order and STOPS at
    ``limit`` (bounded memory — never materializes the whole table); as agencies
    are refreshed their stamp updates and they drop out, so the scan rotates."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
    # Push the 'enrichment complete' filter into SQL so only completed rows are
    # loaded + parsed (not the whole table); the staleness check reads last_enriched,
    # a nested JSON field, so it stays in Python (json_extract isn't portable to the
    # Postgres backend). LIMIT is applied after the staleness filter, so pull without
    # a SQL LIMIT and stop once we've collected enough.
    src, sp = _src(source)
    out: List[sqlite3.Row] = []
    for r in conn.execute(
            "SELECT * FROM agencies WHERE COALESCE(enrichment_json,'') LIKE ?" + src +
            " ORDER BY id", (_DONE, *sp)):
        try:
            state = json.loads(r["enrichment_json"]) or {}
        except (json.JSONDecodeError, TypeError):
            continue
        last = state.get("last_enriched") or ""
        if last and last >= cutoff:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def agencies_needing_decision_makers(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 100000
) -> List[sqlite3.Row]:
    """Agencies that can still have decision makers discovered: a website is on
    record and discovery hasn't completed (dm_json status != 'complete'). Mirrors
    agencies_needing_enrichment so the batch/auto-run advances instead of re-trying
    the same rows — an agency processed with 0 people found is marked complete and
    drops out."""
    # Filter in SQL (mirrors count_needing_decision_makers): a website on record and
    # dm discovery not complete/error — instead of scanning + parsing every blob.
    src, sp = _src(source)
    return conn.execute(
        "SELECT * FROM agencies WHERE TRIM(COALESCE(website,'')) != '' "
        "AND COALESCE(dm_json,'') NOT LIKE ? AND COALESCE(dm_json,'') NOT LIKE ?" +
        src + " ORDER BY id LIMIT ?", (_DONE, _ERR, *sp, limit)).fetchall()


# --------------------------------------------------------------------------- #
# Title taxonomy — the learned classification cache (grows over time)
# --------------------------------------------------------------------------- #
def taxonomy_get(
    conn: sqlite3.Connection, title_norm: str, *, bump: bool = False
) -> Optional[sqlite3.Row]:
    """A learned title classification, or None. With ``bump`` it also increments
    the hit counter (a cache read that records the title was seen again)."""
    row = conn.execute(
        "SELECT * FROM title_taxonomy WHERE title_norm = ?", (title_norm,)
    ).fetchone()
    if row and bump:
        conn.execute(
            "UPDATE title_taxonomy SET hits = hits + 1, updated_at = ? "
            "WHERE id = ?", (datetime.now(timezone.utc).isoformat(), row["id"]))
    return row


def taxonomy_put(conn: sqlite3.Connection, title_norm: str, **fields) -> None:
    """Learn (or refresh) a title classification. Upsert on title_norm; a new row
    starts at hits=1. The caller commits."""
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM title_taxonomy WHERE title_norm = ?", (title_norm,)
    ).fetchone()
    if existing:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE title_taxonomy SET {sets}, updated_at=? WHERE id=?",
                (*fields.values(), now, existing["id"]))
        return
    cols = list(fields.keys())
    conn.execute(
        f"INSERT INTO title_taxonomy (title_norm, {', '.join(cols)}, hits, "
        f"created_at, updated_at) VALUES (?,{','.join('?' * len(cols))},1,?,?)",
        (title_norm, *fields.values(), now, now))


def taxonomy_count(conn: sqlite3.Connection, source: Optional[str] = None) -> int:
    if source:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM title_taxonomy WHERE source = ?", (source,)
        ).fetchone()["n"]
    return conn.execute("SELECT COUNT(*) AS n FROM title_taxonomy").fetchone()["n"]


def list_taxonomy(conn: sqlite3.Connection, limit: int = 500) -> List[sqlite3.Row]:
    """The learned taxonomy, most-seen first — a window into what the system knows."""
    return conn.execute(
        "SELECT * FROM title_taxonomy ORDER BY hits DESC, title_norm LIMIT ?",
        (limit,)).fetchall()


def agencies_needing_enrichment(
    conn: sqlite3.Connection, source: Optional[str] = None, limit: int = 100000
) -> List[sqlite3.Row]:
    """Agency rows that can still be enriched, oldest first. "Can still be" means:
    a website is on record (no site → nothing to visit), and the enrichment isn't
    finished or terminally failed (status not in 'complete'/'error'). A 'blocked'
    row (scraping was off) IS retried — it becomes enrichable once scraping is on.

    This is what a resumable batch re-selects each run, so the queue actually
    advances: finished rows are skipped, and rows that can never enrich (no site,
    or already errored) don't clog the front of the line and starve the batch.
    Directories that list no outbound website (e.g. The Drum, Cannes Lions) thus
    don't count as 'awaiting' — they'd only ever error."""
    # Filter in SQL (mirrors count_needing_enrichment) instead of scanning the whole
    # table and JSON-parsing every blob in Python — this selector is called once PER
    # AGENCY inside a batch pass, so an O(table) Python scan per item was O(table×batch)
    # per pass. The LIKE markers match the stored blob format and are portable to the
    # Postgres backend (same markers the count functions use). A 'blocked' row (NOT
    # complete/error) is still retried, exactly as before.
    src, sp = _src(source)
    return conn.execute(
        "SELECT * FROM agencies WHERE TRIM(COALESCE(website,'')) != '' "
        "AND COALESCE(enrichment_json,'') NOT LIKE ? "
        "AND COALESCE(enrichment_json,'') NOT LIKE ?" + src +
        " ORDER BY id LIMIT ?", (_DONE, _ERR, *sp, limit)).fetchall()


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


def pending_submission_count(conn: sqlite3.Connection) -> int:
    """Everything waiting at the taste gate — the Queue nav badge.

    A creator's TAKE and a creator's DELIVERABLES both wait here and both need the same
    press, but only the take was counted — so a stem package could sit in the building
    with nothing anywhere saying so: *"The files have been uploaded for the studio to
    review.. but the dashboard doesnt tell me there are files to review"* (operator,
    2026-08-19). Counted per FILE, because twelve stems are twelve things to listen to.

    A composer uploaded a take and the whole system said so by email and by a card on a
    page nobody was looking at: *"the alert went out to approve which is great, no badge
    showed up in the dashboard letting me know something new happened."* (operator,
    2026-08-19). The taste gate is the one queue where nothing moves until the operator
    moves it, so it is the one that has to be visible from wherever they are standing.

    The LIKE narrows the scan to rows that have ever CARRIED a pending version before
    any JSON is parsed; this runs on every page render, and it is one query either way.
    """
    n = 0
    for row in conn.execute(
            "SELECT id, delivery_json FROM projects WHERE delivery_json LIKE ?"
            " OR delivery_json LIKE ? OR delivery_json LIKE ?",
            ("%pending_version%", "%pending_assets%", "%Delivered%")):
        try:
            d = json.loads(row["delivery_json"] or "{}") or {}
        except (ValueError, TypeError):
            continue                    # a malformed blob is not a submission
        if d.get("pending_version"):
            n += 1
        n += len(d.get("pending_assets") or [])
        # …and a finished delivery the client cannot be billed for. It is not a
        # submission, but it IS the same thing to the operator: nothing moves until
        # they press something, and nobody was telling them.
        if (d.get("state") or "") in ("Delivered", "Released"):
            from .billing import final_invoice_block
            try:
                # No healer here on purpose: a nav badge on every page render is the
                # wrong place to be writing proposal rows. It over-counts a healable
                # deal by one until the operator opens the page that heals it — a badge
                # pointing at real work either way.
                if final_invoice_block(conn, row["id"]):
                    n += 1
            except Exception:  # noqa: BLE001 — a badge never breaks a page render
                pass
    return n


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


def delete_inbound_lead(conn: sqlite3.Connection, lead_id: int) -> bool:
    """Permanently remove a lead — only once it's Dismissed (already
    addressed) and never promoted into the pipeline, so this can't be used
    to erase a real opportunity's paper trail. Returns False (no-op) if
    those conditions aren't met, rather than raising, since the only caller
    is a same-page form button that shouldn't need its own error page."""
    row = get_inbound_lead(conn, lead_id)
    if row is None or row["status"] != "Dismissed" or row["linked_opp_id"]:
        return False
    conn.execute("DELETE FROM inbound_leads WHERE id = ?", (lead_id,))
    conn.commit()
    return True


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


def update_proposal_price(
    conn: sqlite3.Connection, proposal_id: int, total_price: float, deposit_pct: float,
) -> None:
    """Override a proposal's price — for a hand-sold, custom-quoted deal where the
    number agreed with the client doesn't come from the estimator. Recomputes
    deposit_amount/balance_due from the new total; line items/terms are untouched
    (they document the scope/rationale, the footer carries the agreed price)."""
    deposit_amount = round(total_price * deposit_pct, 2)
    balance_due = round(total_price - deposit_amount, 2)
    conn.execute(
        """UPDATE proposals
           SET total_price=?, deposit_pct=?, deposit_amount=?, balance_due=?
           WHERE id=?""",
        (total_price, deposit_pct, deposit_amount, balance_due, proposal_id),
    )
    conn.commit()


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
        _SQL_INVOICES_BY_PROJECT, (project_id,)
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


# Deals still live: not yet won, lost or passed. "New" is excluded — an unworked
# lead is not pipeline until someone decides to pursue it.
OPEN_PIPELINE_STATES = ("Pursuing", "Submitted")


def open_pipeline(conn: sqlite3.Connection, statuses=None) -> dict:
    """THE open-pipeline number, and what it is made of.

    Three surfaces used to answer this with three different sums: the dashboard KPI
    added up ``budget_max`` (what the *client* said they'd spend), the Tentative
    column added up ``outcome_value`` (what *we* bid), and /revenue read the
    ``proposals`` table — which is written only once a project exists, i.e. only
    after a deal is WON, so open pipeline there was structurally always $0.

    One precedence, best evidence first:
      1. what we actually bid (``outcome_value``)
      2. the midpoint of the budget the client disclosed
      3. nothing — counted, but never guessed at

    Returns the total plus its composition, so a surface can say where the number
    came from instead of asserting a figure with no provenance.
    """
    states = tuple(statuses or OPEN_PIPELINE_STATES)
    placeholders = ",".join("?" for _ in states)
    rows = conn.execute(
        f"SELECT outcome_value, budget_min, budget_max FROM opportunities "
        f"WHERE status IN ({placeholders})", states
    ).fetchall()

    total = 0.0
    from_bids = from_budgets = unknown = 0
    for r in rows:
        bid = r["outcome_value"] or 0
        if bid > 0:
            total += bid
            from_bids += 1
            continue
        lo, hi = r["budget_min"] or 0, r["budget_max"] or 0
        if lo or hi:
            total += (lo + hi) / 2.0 if (lo and hi) else (lo or hi)
            from_budgets += 1
        else:
            unknown += 1
    return {"value": total, "deals": len(rows), "from_bids": from_bids,
            "from_budgets": from_budgets, "unknown": unknown}


def revenue_summary(conn: sqlite3.Connection) -> dict:
    """Company-wide revenue rollup for the dashboard — computed from data we already
    store (invoices, proposals, projects, opportunities). The CRO's home screen:
    cash collected (the number that matters), A/R, pipeline, and the funnel."""
    def _sum(sql, params=()):
        return conn.execute(sql, params).fetchone()[0] or 0

    collected = _sum("SELECT SUM(amount) FROM invoices WHERE status='Paid'")
    outstanding = _sum("SELECT SUM(amount) FROM invoices WHERE status='Issued'")
    deposits_paid = _sum(
        "SELECT SUM(amount) FROM invoices WHERE status='Paid' AND kind='Deposit'")
    finals_paid = _sum(
        "SELECT SUM(amount) FROM invoices WHERE status='Paid' AND kind='Final'")
    # Open pipeline: deals still live, valued by the shared precedence. It used to
    # read the proposals table, which is only written once a project exists — i.e.
    # after the deal is already WON — so this KPI could only ever show $0.
    pipe = open_pipeline(conn)
    # Proposals issued against real projects. Kept, but no longer mislabelled as
    # open pipeline: by the time one of these exists the deal has been awarded.
    proposed_sent = _sum(
        "SELECT SUM(total_price) FROM proposals WHERE status='Sent'")
    proposed_accepted = _sum(
        "SELECT SUM(total_price) FROM proposals WHERE status='Accepted'")
    # Conversion funnel counts.
    qualified = _sum("SELECT COUNT(*) FROM opportunities WHERE qualified=1")
    proposals_sent = _sum(
        "SELECT COUNT(*) FROM proposals WHERE status IN ('Sent','Accepted','Declined')")
    deposits_count = _sum(
        "SELECT COUNT(*) FROM invoices WHERE kind='Deposit' AND status='Paid'")
    delivered = _sum("SELECT COUNT(*) FROM projects WHERE status='Delivered'")
    # Paid-in-full projects (re-uses the same gate the downloads use).
    paid_in_full = sum(
        1 for p in conn.execute("SELECT id FROM projects").fetchall()
        if invoice_balance(conn, p["id"])["paid_in_full"]
    )
    return {
        "collected": collected,
        "outstanding": outstanding,            # A/R: earned but not yet collected
        "billed": collected + outstanding,
        "deposits_paid": deposits_paid,
        "finals_paid": finals_paid,
        "pipeline_open": pipe["value"],
        "pipeline_deals": pipe["deals"],
        "pipeline_from_bids": pipe["from_bids"],
        "pipeline_from_budgets": pipe["from_budgets"],
        "proposed_sent": proposed_sent,
        "proposed_accepted": proposed_accepted,
        "funnel": {
            "qualified": qualified,
            "proposals_sent": proposals_sent,
            "deposits_collected": deposits_count,
            "delivered": delivered,
            "paid_in_full": paid_in_full,
        },
    }


def list_outstanding_invoices(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    """Issued-but-unpaid invoices (the A/R worklist) with their project context."""
    return conn.execute(
        """SELECT i.*, p.client AS project_client, p.need AS project_need
           FROM invoices i LEFT JOIN projects p ON i.project_id = p.id
           WHERE i.status='Issued' ORDER BY i.created_at"""
    ).fetchall()


def recent_payments(conn: sqlite3.Connection, limit: int = 8) -> List[sqlite3.Row]:
    """The latest collected payments — proof the dollars are real, newest first."""
    return conn.execute(
        """SELECT i.*, p.client AS project_client, p.need AS project_need
           FROM invoices i LEFT JOIN projects p ON i.project_id = p.id
           WHERE i.status='Paid' ORDER BY i.paid_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def invoice_balance(conn: sqlite3.Connection, project_id: int) -> dict:
    """Payment status for a project's invoices — drives the deliverable download gate.

    ``billed``       = everything sent to the client (Issued + Paid)
    ``paid``         = settled
    ``outstanding``  = Issued but not yet Paid (Draft invoices aren't owed yet)
    ``paid_in_full`` = something was billed AND nothing is outstanding
    """
    rows = list_invoices(conn, project_id)
    paid = sum((r["amount"] or 0) for r in rows if r["status"] == "Paid")
    outstanding = sum((r["amount"] or 0) for r in rows if r["status"] == "Issued")
    billed = paid + outstanding
    return {
        "billed": billed,
        "paid": paid,
        "outstanding": outstanding,
        "paid_in_full": billed > 0 and outstanding == 0,
        "has_invoices": bool(rows),
    }


# --------------------------------------------------------------------------- #
# Talent payouts — the collaborator-pay ledger (Owed → Paid, off-platform)
# --------------------------------------------------------------------------- #
PAYOUT_STATES = ("Owed", "Paid")


def _writer_fee_per_head(conn: sqlite3.Connection, project_id: int, writers: int) -> float:
    """Each writer's share of the fee policy for this project, or 0.0 when it cannot
    be computed (no linked opportunity, nothing priced yet).

    Goes through `estimate_for` — the ONE quote authority (ADR-0033) — so the fee owed
    to a composer is derived from the same arithmetic as the price quoted to the client.
    Imported lazily because the estimate layer sits above this one; returns 0.0 rather
    than raising, since a missing estimate must never block a payout run.
    """
    if writers <= 0:
        return 0.0
    try:
        from .estimate import estimate_for                 # lazy: avoids a cycle
        row = get_project(conn, project_id)
        opp_id = row["opp_id"] if row is not None else None
        if opp_id is None:
            return 0.0
        opp_row = get_opportunity(conn, opp_id)
        if opp_row is None:
            return 0.0
        est = estimate_for(opportunity_from_row(opp_row), conn=conn,
                           project_id=project_id)
        fee = compensation.writer_fee(
            est.suggested_price, est.session_cost, writers=writers)
        return fee.per_writer
    except Exception:                        # noqa: BLE001 — never block a payout run
        return 0.0


def ensure_project_payouts(conn: sqlite3.Connection, project_id: int) -> int:
    """Generate Owed payout rows for a project's crew — idempotent.

    Called when a client invoice is marked Paid: every assignment gets one payout
    (one row per talent-role, enforced by the UNIQUE constraint, so re-running or a
    second invoice never double-creates). Amount is seeded from the talent's rate
    (qty defaults to 1 — Jon adjusts hours/days), or 0 when no rate is on file.
    Returns how many new payouts were created."""
    assignments = list_assignments(conn, project_id)
    # ADR-0061 — what a WRITER is owed comes from the fee policy, computed off the same
    # price the client was quoted, unless a rate was negotiated for them specifically.
    # Before this a writer with no rate on file was seeded at $0.00 and the number a
    # composer had been promised lived only in the conversation where it was said.
    writer_keys = {(a["talent_id"], (a["role"] or "").strip().lower())
                   for a in assignments if a["talent_id"] is not None
                   and (a["role"] or "").strip().lower() in compensation.WRITER_ROLE_NAMES}
    policy_each = _writer_fee_per_head(conn, project_id, len(writer_keys))

    created = 0
    for a in assignments:
        if a["talent_id"] is None:
            continue
        rate = a["talent_rate"] if "talent_rate" in a.keys() else None
        unit = (a["talent_rate_unit"] if "talent_rate_unit" in a.keys() else None) or "hourly"
        amount = float(rate) if rate is not None else 0.0
        is_writer = (a["talent_id"], (a["role"] or "").strip().lower()) in writer_keys
        if rate is None and is_writer and policy_each > 0:
            amount, unit = policy_each, "project"
        cur = conn.execute(
            """INSERT OR IGNORE INTO talent_payouts
               (project_id, talent_id, role, rate, rate_unit, qty, amount, status, created_at)
               VALUES (?,?,?,?,?,?,?,'Owed',?)""",
            (project_id, a["talent_id"], a["role"],
             float(rate) if rate is not None else None, unit, 1.0, amount,
             datetime.now(timezone.utc).isoformat()),
        )
        created += cur.rowcount or 0
    conn.commit()
    return created


def list_payouts(conn: sqlite3.Connection, status: Optional[str] = None) -> List[sqlite3.Row]:
    """Every payout joined to its creator (name, W-9 status) and project (need),
    newest first. Optionally filter by status (Owed | Paid)."""
    where, params = "", []
    if status in PAYOUT_STATES:
        where = " WHERE po.status = ?"
        params.append(status)
    return conn.execute(
        f"""SELECT po.*, t.name AS talent_name, t.email AS talent_email,
                   t.w9_received_at AS w9_received_at, t.portal_token AS portal_token,
                   p.need AS project_need, p.client AS project_client
            FROM talent_payouts po
            LEFT JOIN talent t ON po.talent_id = t.id
            LEFT JOIN projects p ON po.project_id = p.id
            {where}
            ORDER BY (po.status='Paid') ASC, po.created_at DESC""",
        params,
    ).fetchall()


def get_payout(conn: sqlite3.Connection, payout_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT po.*, t.name AS talent_name, t.w9_received_at AS w9_received_at
           FROM talent_payouts po LEFT JOIN talent t ON po.talent_id = t.id
           WHERE po.id = ?""",
        (payout_id,),
    ).fetchone()


def update_payout(
    conn: sqlite3.Connection, payout_id: int,
    qty: Optional[float], amount: Optional[float], reference: Optional[str],
) -> None:
    """Edit an Owed payout's quantity / amount / reference before it's paid."""
    conn.execute(
        "UPDATE talent_payouts SET qty=?, amount=?, reference=? WHERE id=?",
        (qty, amount, (reference or None), payout_id),
    )
    conn.commit()


def set_payout_paid(
    conn: sqlite3.Connection, payout_id: int, paid: bool,
    reference: Optional[str] = None,
) -> None:
    """Mark a payout Paid (stamp paid_at, keep the reference) or revert it to Owed.

    The W-9 gate is enforced in the route, not here — this is the storage write."""
    if paid:
        conn.execute(
            """UPDATE talent_payouts
               SET status='Paid', paid_at=?, reference=COALESCE(?, reference)
               WHERE id=?""",
            (datetime.now(timezone.utc).isoformat(), (reference or None), payout_id),
        )
    else:
        conn.execute(
            "UPDATE talent_payouts SET status='Owed', paid_at=NULL WHERE id=?",
            (payout_id,),
        )
    conn.commit()


def payout_totals(conn: sqlite3.Connection) -> dict:
    """Ledger KPIs: amount + count, split Owed vs Paid."""
    row = conn.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN status='Owed' THEN amount END),0) AS owed_amount,
             COALESCE(SUM(CASE WHEN status='Paid' THEN amount END),0) AS paid_amount,
             SUM(CASE WHEN status='Owed' THEN 1 ELSE 0 END) AS owed_count,
             SUM(CASE WHEN status='Paid' THEN 1 ELSE 0 END) AS paid_count
           FROM talent_payouts"""
    ).fetchone()
    return {
        "owed_amount": row["owed_amount"] or 0,
        "paid_amount": row["paid_amount"] or 0,
        "owed_count": row["owed_count"] or 0,
        "paid_count": row["paid_count"] or 0,
    }


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
        # Normalized on the way out too, not just on write — a row saved
        # before this fix existed (or written by any future caller that
        # forgets to normalize) still renders as a working absolute link
        # instead of a bare "chordential.com/reel" that resolves relative
        # to the current page and goes nowhere.
        demo_reel_url=normalize_url(row["demo_reel_url"]),
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
    pro: str = "",
    publisher: str = "",
) -> None:
    valid = [d for d in disciplines if d in {m.value for m in MusicDiscipline}]
    conn.execute(
        """UPDATE talent SET name=?, email=?, disciplines=?, credits=?, location=?,
           demo_reel_url=?, notes=?, rate=?, rate_unit=?, pro=?, publisher=?
           WHERE id=?""",
        (
            name, email or None, json.dumps(valid), credits, location or None,
            demo_reel_url or None, notes, rate, (rate_unit or "hourly"),
            (pro or "").strip() or None,
            (publisher or "").strip() or None, talent_id,
        ),
    )
    conn.commit()


def talent_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM talent").fetchone()[0]


# --- Composer portal access (per-creator token credential) ---------------- #
def ensure_talent_portal_token(conn: sqlite3.Connection, talent_id: int) -> Optional[str]:
    """Return the creator's portal token, minting one on first use.

    The creator's only credential for the composer portal (``/creator/<token>``):
    unguessable, not enumerable, no password. Mirrors
    :func:`ensure_project_share_token`. ``None`` only if the creator doesn't exist."""
    row = conn.execute(
        "SELECT portal_token FROM talent WHERE id = ?", (talent_id,)
    ).fetchone()
    if row is None:
        return None
    existing = row["portal_token"]
    if existing and str(existing).strip():
        return existing
    token = public_token(16)
    conn.execute(
        "UPDATE talent SET portal_token = ? WHERE id = ?", (token, talent_id)
    )
    conn.commit()
    return token


def get_talent_by_portal_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    """Resolve a creator from their portal token (the access check). Blank → None."""
    if not token or not str(token).strip():
        return None
    return conn.execute(
        "SELECT * FROM talent WHERE portal_token = ?", (str(token).strip(),)
    ).fetchone()


def set_talent_w9(conn: sqlite3.Connection, talent_id: int, received_at: Optional[str]) -> None:
    """Record (or clear) the W-9-on-file date — the payout-ledger compliance gate."""
    conn.execute(
        "UPDATE talent SET w9_received_at = ? WHERE id = ?", (received_at, talent_id)
    )
    conn.commit()


def set_talent_agreement(conn: sqlite3.Connection, talent_id: int,
                         executed_at: Optional[str], ref: str = "") -> None:
    """Record (or clear) the standing Composer Agreement (ADR-0024). ``executed_at``
    is the ISO date the instrument was signed; ``ref`` says where it lives. Clearing
    (None) also clears the ref — a dangling reference to a voided agreement is worse
    than none."""
    conn.execute(
        "UPDATE talent SET agreement_executed_at = ?, agreement_ref = ? WHERE id = ?",
        (executed_at, (ref or "").strip() if executed_at else "", talent_id),
    )
    conn.commit()


def talent_assignment_blockers(row) -> List[str]:
    """The A-3 gate (ADR-0024), computed: what stops this creator from being
    assigned. Returns [] when clear, else a list among {'agreement', 'rate'}.
    Pure read of a talent row — the assign routes refuse on a non-empty answer,
    mirroring how the payment gate refuses release. Enforced by the flow, not
    by convention (Constitution §10)."""
    blockers: List[str] = []
    if row is None:
        return ["agreement", "rate"]
    keys = row.keys()
    if not ((row["agreement_executed_at"] or "").strip()
            if "agreement_executed_at" in keys else ""):
        blockers.append("agreement")
    rate = row["rate"] if "rate" in keys else None
    if rate is None or float(rate or 0) <= 0:
        blockers.append("rate")
    return blockers


def list_talent_assignments(conn: sqlite3.Connection, talent_id: int) -> List[sqlite3.Row]:
    """Every project a creator is assigned to, newest first — the spine of the
    composer portal. Joins assignments → projects so the portal can show the role,
    brief, deadline, and delivery state for each engagement."""
    return conn.execute(
        """SELECT a.id AS assignment_id, a.role, a.created_at AS assigned_at,
                  p.id AS project_id, p.client, p.need, p.deadline, p.status,
                  p.delivery_json, p.share_token
           FROM assignments a JOIN projects p ON a.project_id = p.id
           WHERE a.talent_id = ? ORDER BY p.created_at DESC, a.role""",
        (talent_id,),
    ).fetchall()


def talent_is_assigned(conn: sqlite3.Connection, talent_id: int, project_id: int) -> bool:
    """Is this creator actually on this project? Guards composer-portal uploads so a
    creator can only submit work to a project they're assigned to."""
    return conn.execute(
        "SELECT 1 FROM assignments WHERE talent_id = ? AND project_id = ? LIMIT 1",
        (talent_id, project_id),
    ).fetchone() is not None


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
    *,
    agency_id: Optional[int] = None,
    share_token: Optional[str] = None,
) -> int:
    # ADR-0018: the project INHERITS the opportunity's workspace token, so the client's
    # one URL survives award (opportunity → project) unchanged.
    cur = conn.execute(
        """INSERT INTO projects
           (opp_id, client, need, budget_min, budget_max, deadline, status, roles,
            created_at, agency_id, share_token)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            opp_id, client, need, budget_min, budget_max, deadline, "Active",
            json.dumps(roles), datetime.now(timezone.utc).isoformat(), agency_id,
            share_token,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# Buyer link — thread agency_id from Opportunity → Project → Campaign so the
# lineage can reach the Agency/Company Intelligence record instead of only a
# client name (docs/architecture/DISCOVERY_INTELLIGENCE_LINEAGE.md). Step 1: the
# thread + its source (a name match). NOT the inheritance (the parent object /
# provenance model is designed next).
# --------------------------------------------------------------------------- #
def _norm_company(name: Optional[str]) -> str:
    """Normalize a company/client name for matching: lowercase, collapse whitespace."""
    return " ".join((name or "").strip().lower().split())


def match_agency_by_name(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    """Find the agency whose company name matches ``name`` (case/space-insensitive
    exact match). Deliberately exact, not fuzzy — a wrong link would attach the wrong
    buyer intelligence, which is worse than no link. Returns the agency row or None."""
    key = _norm_company(name)
    if not key:
        return None
    for r in conn.execute("SELECT * FROM agencies WHERE company IS NOT NULL"):
        if _norm_company(r["company"]) == key:
            return r
    return None


def set_opportunity_agency(conn: sqlite3.Connection, opp_id: int,
                           agency_id: Optional[int]) -> None:
    """Link (or unlink, with None) an opportunity to an Agency Intelligence record."""
    conn.execute("UPDATE opportunities SET agency_id = ? WHERE id = ?",
                 (agency_id, opp_id))
    conn.commit()


def set_campaign_agency(conn: sqlite3.Connection, campaign_id: int,
                        agency_id: Optional[int]) -> None:
    conn.execute("UPDATE campaigns SET agency_id = ?, updated_at = ? WHERE id = ?",
                 (agency_id, datetime.now(timezone.utc).isoformat(), campaign_id))
    conn.commit()


def resolve_opportunity_agency(conn: sqlite3.Connection, opp_row) -> Optional[int]:
    """The agency_id for an opportunity: the existing link if set, else a best-effort
    name match against the agencies table (which is ALSO recorded on the opp so it
    isn't recomputed). Returns the agency_id or None — never guesses beyond an exact
    name match. This is the SOURCE that makes the downstream thread non-empty."""
    if opp_row is None:
        return None
    existing = opp_row["agency_id"] if "agency_id" in opp_row.keys() else None
    if existing:
        return existing
    match = match_agency_by_name(conn, opp_row["client"])
    if match is not None:
        set_opportunity_agency(conn, opp_row["id"], match["id"])
        return match["id"]
    return None


def project_for_opp(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM projects WHERE opp_id = ? LIMIT 1", (opp_id,)
    ).fetchone()


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


# --------------------------------------------------------------------------- #
# Campaign Workspace (Creative OS) — the campaign is the workspace root that
# elevates a project. Created lazily per project (no bulk migration); the existing
# delivery/review machinery keeps running per-project underneath. See
# docs/campaign-workspace-prd.md.
# --------------------------------------------------------------------------- #
def get_campaign(conn: sqlite3.Connection, campaign_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()


def campaign_for_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaigns WHERE project_id = ? LIMIT 1", (project_id,)).fetchone()


def ensure_campaign_for_project(conn: sqlite3.Connection, project_id: int,
                                *, phase: str = "Briefing") -> Optional[sqlite3.Row]:
    """Get (or lazily create) the campaign that wraps a project — the compat bridge
    from the existing project record to the Creative OS workspace. Idempotent via the
    project_id link, so opening a project as a workspace never duplicates. Hydrates
    title/brand/agency/budget/deadline from the project. Returns None if no project."""
    existing = campaign_for_project(conn, project_id)
    if existing is not None:
        return existing
    proj = get_project(conn, project_id)
    if proj is None:
        return None
    # Carry the buyer link through: prefer the project's agency_id; if it wasn't set
    # (older project), fall back to the opportunity's resolved link, then a name match
    # — so an existing project still connects to the agency intelligence when possible.
    agency_id = proj["agency_id"] if "agency_id" in proj.keys() else None
    if not agency_id and proj["opp_id"]:
        opp = get_opportunity(conn, proj["opp_id"])
        if opp is not None:
            agency_id = resolve_opportunity_agency(conn, opp)
    if not agency_id:
        m = match_agency_by_name(conn, proj["client"])
        if m is not None:
            agency_id = m["id"]
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO campaigns
           (project_id, opp_id, agency_id, title, brand, agency_client, phase,
            budget_min, budget_max, deadline, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, proj["opp_id"], agency_id, proj["need"] or "Untitled campaign",
         proj["client"] or "", proj["client"] or "", phase,
         proj["budget_min"], proj["budget_max"], proj["deadline"], "Active", now, now))
    conn.commit()
    return get_campaign(conn, int(cur.lastrowid))


def list_campaigns(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaigns WHERE status != 'Archived' ORDER BY updated_at DESC, id DESC"
    ).fetchall()


def set_campaign_phase(conn: sqlite3.Connection, campaign_id: int, phase: str) -> None:
    conn.execute(
        "UPDATE campaigns SET phase = ?, updated_at = ? WHERE id = ?",
        (phase, datetime.now(timezone.utc).isoformat(), campaign_id))
    conn.commit()


def get_campaign_direction(conn: sqlite3.Connection, campaign_id: int) -> dict:
    """All direction sections for a campaign as {section: row}."""
    return {r["section"]: r for r in conn.execute(
        "SELECT * FROM campaign_direction WHERE campaign_id = ?", (campaign_id,))}


def update_campaign_direction(conn: sqlite3.Connection, campaign_id: int, section: str,
                              *, body: Optional[str] = None,
                              complete: Optional[bool] = None,
                              source: str = "manual") -> None:
    """Upsert one direction section (merge-one-field, mirroring the doc_overrides
    pattern). Only the provided fields change; the row is created if absent."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT * FROM campaign_direction WHERE campaign_id = ? AND section = ?",
        (campaign_id, section)).fetchone()
    if row is None:
        conn.execute(
            """INSERT INTO campaign_direction
               (campaign_id, section, body, complete, source, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (campaign_id, section, body or "",
             1 if complete else 0, source, now))
    else:
        new_body = row["body"] if body is None else body
        new_complete = row["complete"] if complete is None else (1 if complete else 0)
        conn.execute(
            "UPDATE campaign_direction SET body = ?, complete = ?, updated_at = ? "
            "WHERE campaign_id = ? AND section = ?",
            (new_body, new_complete, now, campaign_id, section))
    conn.execute("UPDATE campaigns SET updated_at = ? WHERE id = ?", (now, campaign_id))
    conn.commit()


# --------------------------------------------------------------------------- #
# Campaign Intelligence (Creative OS) — the canonical, LIVING per-engagement record.
# Storage only; the domain model (facets/keys/kinds, provenance rules, seeding) lives
# in campaign_intelligence.py. See docs/architecture/CAMPAIGN_INTELLIGENCE.md.
# --------------------------------------------------------------------------- #
def get_campaign_intelligence(conn: sqlite3.Connection, ci_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaign_intelligence WHERE id = ?", (ci_id,)).fetchone()


def ci_for_campaign(conn: sqlite3.Connection, campaign_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaign_intelligence WHERE campaign_id = ? LIMIT 1",
        (campaign_id,)).fetchone()


def create_campaign_intelligence(conn: sqlite3.Connection, *, campaign_id, opp_id,
                                 agency_id, project_id, title, brand, agency_client) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO campaign_intelligence
           (campaign_id, opp_id, agency_id, project_id, title, brand, agency_client,
            state, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (campaign_id, opp_id, agency_id, project_id, title, brand or "",
         agency_client or "", "seeded", now, now))
    conn.commit()
    return int(cur.lastrowid)


def list_ci_fields(conn: sqlite3.Connection, ci_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE ci_id = ? "
        "ORDER BY facet, key, kind", (ci_id,)).fetchall()


def get_ci_field(conn: sqlite3.Connection, field_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE id = ?", (field_id,)).fetchone()


def upsert_ci_field(conn: sqlite3.Connection, ci_id: int, facet: str, key: str,
                    kind: str, *, value: str = "", value_json=None, source: str = "",
                    status: Optional[str] = None, origin: str = "",
                    confidence: Optional[int] = None, is_concern: bool = False,
                    contributed_by: str = "", capture_id: Optional[int] = None) -> int:
    """Upsert one canonical fact on (ci_id, facet, key, kind). Merges the new
    ``source`` into the field's provenance list; sets status/value when provided; stamps the
    originating ``capture_id`` (raw evidence, ADR-0014). The domain layer
    (campaign_intelligence.py) decides status per kind and logs the event — this is the
    storage primitive. Returns the field id."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE ci_id=? AND facet=? AND key=? AND kind=?",
        (ci_id, facet, key, kind)).fetchone()
    srcs = []
    if row is not None:
        try:
            srcs = json.loads(row["sources"]) or []
        except (json.JSONDecodeError, TypeError):
            srcs = []
    if source and source not in srcs:
        srcs.append(source)
    vj = json.dumps(value_json) if value_json is not None else (
        row["value_json"] if row is not None else None)
    if row is None:
        cur = conn.execute(
            """INSERT INTO campaign_intelligence_field
               (ci_id, facet, key, kind, value, value_json, sources, status, origin,
                confidence, is_concern, contributed_by, capture_id, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ci_id, facet, key, kind, value, vj, json.dumps(srcs),
             status or "needs_review", origin, confidence,
             1 if is_concern else 0, contributed_by, capture_id, now))
        fid = int(cur.lastrowid)
    else:
        conn.execute(
            """UPDATE campaign_intelligence_field
               SET value=?, value_json=?, sources=?, status=?, origin=?, confidence=?,
                   is_concern=?, contributed_by=?, capture_id=?, updated_at=? WHERE id=?""",
            (value if value else row["value"], vj, json.dumps(srcs),
             status or row["status"], origin or row["origin"],
             confidence if confidence is not None else row["confidence"],
             1 if is_concern else (row["is_concern"] or 0),
             contributed_by or row["contributed_by"],
             capture_id if capture_id is not None else row["capture_id"], now, row["id"]))
        fid = int(row["id"])
    conn.execute("UPDATE campaign_intelligence SET updated_at=? WHERE id=?", (now, ci_id))
    conn.commit()
    return fid


def set_ci_field_status(conn: sqlite3.Connection, field_id: int, status: str) -> None:
    conn.execute(
        "UPDATE campaign_intelligence_field SET status=?, updated_at=? WHERE id=?",
        (status, datetime.now(timezone.utc).isoformat(), field_id))
    conn.commit()


def add_ci_event(conn: sqlite3.Connection, ci_id: int, *, actor: str, verb: str,
                 facet: str = "", key: str = "", kind: str = "",
                 from_value: str = "", to_value: str = "", source: str = "",
                 capture_id: Optional[int] = None) -> None:
    conn.execute(
        """INSERT INTO campaign_intelligence_event
           (ci_id, actor, verb, facet, key, kind, from_value, to_value, source,
            capture_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (ci_id, actor, verb, facet, key, kind, from_value, to_value, source,
         capture_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def insert_capture(conn: sqlite3.Connection, *, ci_id: int,
                   campaign_id: Optional[int] = None, opp_id: Optional[int] = None,
                   lane: str = "", stance: str, modality: str,
                   provenance_source: str = "", raw_text: str, extraction,
                   artifact_ref: str = "", external_ref: str = "",
                   metadata: Optional[dict] = None, status: str = "ready",
                   created_by: str = "operator") -> int:
    """Store an immutable Capture — the normalized envelope every intake LANE produces
    (ADR-0014): raw source + provenance + provider refs + metadata + extraction. Raw
    evidence is permanent; a capture is never mutated after ingest."""
    cur = conn.execute(
        """INSERT INTO captures
           (ci_id, campaign_id, opp_id, lane, stance, modality, provenance_source,
            raw_text, artifact_ref, external_ref, metadata_json, extraction_json,
            status, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ci_id, campaign_id, opp_id, lane, stance, modality, provenance_source,
         raw_text, artifact_ref, external_ref,
         json.dumps(metadata or {}), json.dumps(extraction or []),
         status, created_by, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return int(cur.lastrowid)


def get_capture(conn: sqlite3.Connection, capture_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM captures WHERE id = ?", (capture_id,)).fetchone()


def update_capture(conn: sqlite3.Connection, capture_id: int, *,
                   extraction=None, metadata=None) -> None:
    """Re-record what a capture YIELDED, never what it said. raw_text is permanent
    evidence and is not writable here: a re-read may change the reading, and must not be
    able to change the thing that was read."""
    sets, vals = [], []
    if extraction is not None:
        sets.append("extraction_json = ?")
        vals.append(json.dumps(extraction))
    if metadata is not None:
        sets.append("metadata_json = ?")
        vals.append(json.dumps(metadata))
    if not sets:
        return
    vals.append(capture_id)
    conn.execute(f"UPDATE captures SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def list_captures(conn: sqlite3.Connection, ci_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM captures WHERE ci_id = ? ORDER BY created_at DESC, id DESC",
        (ci_id,)).fetchall()


def fields_by_capture(conn: sqlite3.Connection, capture_id: int) -> List[sqlite3.Row]:
    """The CI fields a given Capture last proposed/changed — the raw material of a review
    batch ("what did this capture change, and why?"). ADR-0014."""
    return conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE capture_id = ? "
        "ORDER BY facet, key, kind", (capture_id,)).fetchall()


def list_captures_for_opp(conn: sqlite3.Connection, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM captures WHERE opp_id = ? ORDER BY created_at DESC, id DESC",
        (opp_id,)).fetchall()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Procurement Intelligence (ADR-0022) — Company Profile, requirements, audit, history.
# --------------------------------------------------------------------------- #
def get_company_profile(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT data FROM company_profile WHERE id = 1").fetchone()
    if row is None or not row["data"]:
        return {}
    try:
        return json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return {}


def save_company_profile(conn: sqlite3.Connection, data: dict) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO company_profile (id, data, updated_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (json.dumps(data), now))
    conn.commit()


def list_procurement_requirements(conn: sqlite3.Connection, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM procurement_requirement WHERE opp_id = ? ORDER BY category, id",
        (opp_id,)).fetchall()


def get_procurement_requirement(conn, opp_id: int, req_key: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM procurement_requirement WHERE opp_id = ? AND req_key = ?",
        (opp_id, req_key)).fetchone()


def get_procurement_requirement_by_id(conn, rid: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM procurement_requirement WHERE id = ?", (rid,)).fetchone()


def add_procurement_requirement(conn, *, opp_id, req_key, label="", category="", owner="chordential",
                                status="needed", source="", evidence="", confidence=None,
                                generatable=0) -> int:
    now = _now()
    cur = conn.execute(
        """INSERT INTO procurement_requirement
           (opp_id, req_key, label, category, owner, status, source, evidence, confidence,
            generatable, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(opp_id, req_key) DO NOTHING""",
        (opp_id, req_key, label, category, owner, status, source, evidence, confidence,
         generatable, now, now))
    conn.commit()
    r = get_procurement_requirement(conn, opp_id, req_key)
    return r["id"] if r else cur.lastrowid


def update_procurement_requirement(conn, rid: int, **fields) -> None:
    allowed = {"status", "owner", "confidence", "source", "evidence", "due_date", "notes",
               "owner_note", "artifact_ref", "artifact_text", "label", "category", "generatable"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?"); vals.append(v)
    if not sets:
        return
    sets.append("updated_at = ?"); vals.append(_now()); vals.append(rid)
    conn.execute(f"UPDATE procurement_requirement SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def save_procurement_artifact(conn, opp_id: int, req_key: str, text: str, *, artifact_ref: str):
    r = get_procurement_requirement(conn, opp_id, req_key)
    if r is not None:
        update_procurement_requirement(conn, r["id"], artifact_text=text, artifact_ref=artifact_ref)


def delete_procurement_requirement(conn, rid: int) -> None:
    conn.execute("DELETE FROM procurement_requirement WHERE id = ?", (rid,))
    conn.commit()


def add_procurement_event(conn, opp_id: int, verb: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO procurement_event (opp_id, verb, detail, created_at) VALUES (?,?,?,?)",
        (opp_id, verb, detail, _now()))
    conn.commit()


def list_procurement_events(conn, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM procurement_event WHERE opp_id = ? ORDER BY id DESC", (opp_id,)).fetchall()


def first_procurement_event_at(conn, opp_id: int) -> str:
    row = conn.execute(
        "SELECT created_at FROM procurement_event WHERE opp_id = ? ORDER BY id ASC LIMIT 1",
        (opp_id,)).fetchone()
    return row["created_at"] if row else ""


def save_client_procurement_history(conn, client: str, data: dict) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO client_procurement_history (client, data, updated_at) VALUES (?,?,?) "
        "ON CONFLICT(client) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
        (client, json.dumps(data), now))
    conn.commit()


def get_client_procurement_history(conn, client: str) -> dict:
    row = conn.execute(
        "SELECT data FROM client_procurement_history WHERE client = ?", (client,)).fetchone()
    if row is None or not row["data"]:
        return {}
    try:
        return json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return {}


# --------------------------------------------------------------------------- #
# One scheduler at a time
# --------------------------------------------------------------------------- #
# The background engines coordinate entirely in-process today — a `threading.Lock`
# and module-level timers — on the stated assumption of a single instance. The
# blue-green cutover breaks that assumption ON PURPOSE: for the minutes the old and
# new services overlap, BOTH run the loop, so outreach sends twice, meeting bots are
# polled twice, and two enrichment batches fight for one CPU. Nothing in the system
# would report it.
#
# NOT `pg_try_advisory_lock`, despite the review calling it that. Advisory locks live
# on a SESSION, and this codebase opens a connection per call and closes it (254 call
# sites) — a lock taken that way is released microseconds later. Holding one would
# need a dedicated long-lived connection, and would still leave SQLite (which is what
# production runs today, and every test) with no protection at all.
#
# A lease row is the portable primitive: one atomic UPDATE decides the winner, the
# holder renews it every tick, and an expiry means a killed process hands over by
# itself rather than deadlocking the engines forever.
_LEASE_TS = "%Y-%m-%dT%H:%M:%SZ"       # FIXED width — these are compared as strings


def _lease_now() -> str:
    return datetime.now(timezone.utc).strftime(_LEASE_TS)


def _lease_at(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(_LEASE_TS)


_SAVEPOINT_N = itertools.count(1)


@contextlib.contextmanager
def best_effort(conn, label: str = "be"):
    """Run advisory database work that must never take its caller down.

    ``except Exception: pass`` around a DB call is safe on SQLite and a live grenade on
    Postgres: a failed statement puts the transaction in an aborted state, and EVERY
    later command raises ``InFailedSqlTransaction`` until someone rolls back. So a
    swallowed failure in some optional bookkeeping doesn't stay optional — it takes down
    the write the caller actually cared about, with an error naming neither.

    That is exactly how a discovery transcript came back from Recall and then failed to
    file: three advisory blocks run before the capture is inserted, and any one of them
    failing quietly poisoned the insert.

    A SAVEPOINT makes the swallow honest. The advisory work is undone; everything the
    caller did before it survives.
    """
    sp = "be_%d" % next(_SAVEPOINT_N)
    try:
        conn.execute("SAVEPOINT %s" % sp)
    except Exception:                    # noqa: BLE001 — no savepoint here; swallow plainly
        try:
            yield
        except Exception:                # noqa: BLE001
            pass
        return
    try:
        yield
    except Exception:                    # noqa: BLE001 — the whole point
        # The savepoint may be GONE: almost every db helper commits internally, and a
        # COMMIT discards every savepoint in the transaction. Asking to roll back to one
        # that no longer exists raises, and THAT raise aborts the transaction — the exact
        # poisoning this helper exists to prevent. It cost a client-facing 500 on the
        # "accept this meeting time" link before it was caught.
        try:
            conn.execute("ROLLBACK TO SAVEPOINT %s" % sp)
        except Exception:                # noqa: BLE001
            try:
                conn.rollback()          # clear the aborted state; the inner work committed
            except Exception:            # noqa: BLE001
                pass
    # No RELEASE on success, deliberately. A savepoint is released by the next COMMIT
    # anyway, so releasing buys nothing — and if the wrapped code already committed, the
    # RELEASE fails and poisons the transaction for everything after it.


def snooze_queue_card(conn, key: str, days: int, actor: str = "operator") -> None:
    """Hide one Disposition Queue card until ``days`` from now. Upsert: snoozing an
    already-snoozed card re-sets the clock rather than failing on the primary key."""
    from datetime import datetime, timedelta, timezone
    key = (key or "").strip()
    if not key:
        return
    now = datetime.now(timezone.utc)
    until = (now + timedelta(days=max(1, int(days or 1)))).isoformat()
    cur = conn.execute(
        "UPDATE queue_snooze SET until_at = ?, snoozed_at = ?, actor = ? WHERE key = ?",
        (until, now.isoformat(), actor, key))
    if not cur.rowcount:
        conn.execute(
            "INSERT INTO queue_snooze (key, until_at, snoozed_at, actor) VALUES (?,?,?,?)",
            (key, until, now.isoformat(), actor))
    conn.commit()


def snoozed_queue_keys(conn) -> set:
    """The card keys still inside their snooze window. Expired rows are dropped as we
    read, so the table stays the size of what is actually hidden right now."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("DELETE FROM queue_snooze WHERE until_at <= ?", (now,))
        conn.commit()
        rows = conn.execute(
            "SELECT key FROM queue_snooze WHERE until_at > ?", (now,)).fetchall()
    except Exception:            # noqa: BLE001 — a queue that cannot read its snoozes
        return set()             # shows everything, which is the safe direction
    return {r["key"] for r in rows}


def clear_queue_snoozes(conn) -> int:
    """Un-snooze everything (the "show all" escape hatch)."""
    cur = conn.execute("DELETE FROM queue_snooze")
    conn.commit()
    return cur.rowcount or 0


def acquire_lease(conn, name: str, owner: str, ttl_seconds: int = 90) -> bool:
    """Claim or renew the named lease for ``owner``. True if this process holds it.

    Two statements, each atomic on its own, and in this order: renew-or-steal first
    (the common path, once a holder exists), then a first-time insert. A racing
    insert loses on the primary key and is reported as "not ours" rather than raised.
    """
    now, expires = _lease_now(), _lease_at(ttl_seconds)
    try:
        cur = conn.execute(
            "UPDATE scheduler_lease SET owner = ?, expires_at = ?, "
            "acquired_at = CASE WHEN owner = ? THEN acquired_at ELSE ? END "
            "WHERE name = ? AND (owner = ? OR expires_at <= ?)",
            (owner, expires, owner, now, name, owner, now))
        if cur.rowcount:
            conn.commit()
            return True
    except Exception:                       # noqa: BLE001 — never take the loop down
        try: conn.rollback()
        except Exception: pass
        return False
    try:
        conn.execute(
            "INSERT INTO scheduler_lease (name, owner, expires_at, acquired_at) "
            "VALUES (?,?,?,?)", (name, owner, expires, now))
        conn.commit()
        return True
    except Exception:                       # noqa: BLE001 — another instance got there
        try: conn.rollback()
        except Exception: pass
        return False


def release_lease(conn, name: str, owner: str) -> None:
    """Give the lease up at shutdown so the incoming instance starts in seconds
    instead of waiting out the TTL. Only the holder can release it."""
    try:
        conn.execute("DELETE FROM scheduler_lease WHERE name = ? AND owner = ?",
                     (name, owner))
        conn.commit()
    except Exception:                       # noqa: BLE001
        try: conn.rollback()
        except Exception: pass


def lease_holder(conn, name: str):
    """``{owner, expires_at, acquired_at, expired}`` or None — so "this instance is
    not running the engines" is a visible state rather than an invisible one."""
    try:
        row = conn.execute(
            "SELECT owner, expires_at, acquired_at FROM scheduler_lease WHERE name = ?",
            (name,)).fetchone()
    except Exception:                       # noqa: BLE001
        return None
    if row is None:
        return None
    return {"owner": row["owner"], "expires_at": row["expires_at"],
            "acquired_at": row["acquired_at"],
            "expired": str(row["expires_at"]) <= _lease_now()}


# --------------------------------------------------------------------------- #
# One buyer, across every surface they touch
# --------------------------------------------------------------------------- #
# A human on the buying side is recorded in six unlinked places: `decision_makers`
# (what enrichment found), `discovery_requests` (who asked for a call), `meetings` and
# `meeting_proposals` (who was on it), `review_comments` (who approved the work). Each
# carries its own name/email pair and nothing joins them, so the same person asks for a
# call, takes it, and signs off a master as three strangers — and the question the
# business actually has, "who is this and what have we done together", cannot be asked.
#
# THE IDENTITY IS THE EMAIL, AND ONLY THE EMAIL. Without one there is no canonical
# person: `resolve_person` returns None rather than guess. Names are not identities —
# two people are called John Smith, one person is Priya Okonkwo and Priya O'Konkwo and
# "priya (Northwind)", and a CRM that merges humans on a name eventually attributes one
# buyer's approval to another. A missing link is a gap; a wrong link is a lie in a
# record the client signs against. So the rule is evidence or nothing.
def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def resolve_person(conn, email: str = "", name: str = "", *, commit: bool = True) -> Optional[int]:
    """The canonical id for this human, creating them on first sight. None without an
    email — see above. ``name`` only ever improves the label, never decides identity.

    ``commit=False`` is for the backfill: committing per row turns a one-off pass over
    38,924 decision makers into tens of thousands of fsyncs, which is the difference
    between a boot and an outage.
    """
    key = _norm_email(email)
    if not key or "@" not in key:
        return None
    now = _now()
    row = conn.execute("SELECT id, name FROM buyer_person WHERE email = ?",
                       (key,)).fetchone()
    if row is not None:
        # Keep the fullest name we have seen: surfaces show "P.O." otherwise, purely
        # because that is how one form happened to be filled in.
        better = (name or "").strip()
        if better and len(better) > len((row["name"] or "")):
            conn.execute("UPDATE buyer_person SET name = ?, last_seen_at = ? WHERE id = ?",
                         (better, now, row["id"]))
        else:
            conn.execute("UPDATE buyer_person SET last_seen_at = ? WHERE id = ?",
                         (now, row["id"]))
        if commit:
            conn.commit()
        return int(row["id"])
    conn.execute("INSERT INTO buyer_person (email, name, first_seen_at, last_seen_at) "
                 "VALUES (?,?,?,?)", (key, (name or "").strip(), now, now))
    if commit:
        conn.commit()
    got = conn.execute("SELECT id FROM buyer_person WHERE email = ?", (key,)).fetchone()
    return int(got["id"]) if got is not None else None


def get_person(conn, person_id: int):
    return conn.execute("SELECT * FROM buyer_person WHERE id = ?", (person_id,)).fetchone()


def find_person(conn, email: str):
    key = _norm_email(email)
    if not key:
        return None
    return conn.execute("SELECT * FROM buyer_person WHERE email = ?", (key,)).fetchone()


# Where a person can appear, and what each appearance is called in the product. Kept as
# data so a new surface is one line here rather than a new branch in three functions.
_PERSON_SURFACES = (
    ("decision_makers", "email", "name", "known contact", "created_at"),
    ("discovery_requests", "email", "name", "asked for a call", "created_at"),
    ("meetings", "client_email", "client_name", "on a call", "start_at"),
    ("meeting_proposals", "client_email", "client_name", "offered times", "created_at"),
    ("review_comments", "email", "author", "reviewed the work", "created_at"),
)


def link_people(conn) -> dict:
    """Give every row that names a human its canonical person, and report what happened.

    Idempotent, so it can run at boot and after any import. Rows without an email are
    left unlinked ON PURPOSE — they are the ones we cannot identify without guessing.
    """
    linked, no_email = 0, 0
    for table, email_col, name_col, _label, _when in _PERSON_SURFACES:
        try:
            # Rows with no email are excluded by the QUERY, not skipped in the loop: they
            # can never be linked, and re-reading all of them on every boot for ever is
            # the kind of quiet waste that only shows up at 38,924 rows.
            rows = conn.execute(
                f"SELECT id, {email_col} AS e, {name_col} AS n FROM {table} "
                f"WHERE person_id IS NULL AND {email_col} IS NOT NULL "
                f"AND TRIM({email_col}) <> ''").fetchall()
            no_email += conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE person_id IS NULL "
                f"AND (({email_col} IS NULL) OR TRIM({email_col}) = '')").fetchone()["n"]
        except Exception:                       # noqa: BLE001 — table not in this DB yet
            continue
        for r in rows:
            pid = resolve_person(conn, r["e"] or "", r["n"] or "", commit=False)
            if pid is None:
                continue
            conn.execute(f"UPDATE {table} SET person_id = ? WHERE id = ?", (pid, r["id"]))
            linked += 1
        conn.commit()
    total = conn.execute("SELECT COUNT(*) AS n FROM buyer_person").fetchone()["n"]
    return {"linked": linked, "no_email": no_email, "people": total}


def person_touchpoints(conn, person_id: int) -> List[dict]:
    """Everything this human has done with us, in one list, newest first.

    This is the question the six tables could not answer: the buyer who approved a
    master last month is the same buyer who requested the first call, and until now
    nothing could say so.
    """
    out = []
    for table, _email_col, _name_col, label, when_col in _PERSON_SURFACES:
        try:
            rows = conn.execute(
                f"SELECT id, {when_col} AS at FROM {table} WHERE person_id = ?",
                (person_id,)).fetchall()
        except Exception:                       # noqa: BLE001
            continue
        for r in rows:
            out.append({"what": label, "table": table, "row_id": r["id"],
                        "at": r["at"] or ""})
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)


def people_with_history(conn, limit: int = 200) -> List[dict]:
    """Canonical buyers, most touchpoints first — the ones we actually have a
    relationship with, as opposed to the ones we merely have a row for."""
    people = conn.execute(
        "SELECT * FROM buyer_person ORDER BY last_seen_at DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for p in people:
        tp = person_touchpoints(conn, p["id"])
        out.append({"id": p["id"], "email": p["email"], "name": p["name"],
                    "touchpoints": len(tp), "surfaces": sorted({t["what"] for t in tp}),
                    "last_seen_at": p["last_seen_at"]})
    return sorted(out, key=lambda x: x["touchpoints"], reverse=True)


# --------------------------------------------------------------------------- #
# One organisation, across every surface that names one
# --------------------------------------------------------------------------- #
# The other half of ADR-0050, which did the person and said plainly that organisations
# were not canonical yet. They are recorded in five unlinked places, in two different
# shapes: `agencies.id` (an integer key, what Agency Intelligence works on) and a bare
# name string in `opportunities.client`, `projects.client`, `companies.client` and
# `client_procurement_history.client`. Nothing joins them, which is why the product
# grew TWO relationship systems over the same companies — the Buyer Graph (`/buyers`,
# keyed on the string) and Relationship Management (`/relationships`, keyed on the
# integer) — each blind to the other's evidence.
#
# **The identity is the normalised name.** That is a weaker rule than the person half's
# and it is stated rather than hidden: a person has an email, which is unambiguous and
# usually present; an organisation has a name and sometimes a website, and an
# organisation with no website still has to be canonical or the layer is useless. It is
# also the rule the codebase already committed to — `match_agency_by_name` has threaded
# `agency_id` onto opportunities by exact normalised name since the lineage work — so
# this makes an existing decision explicit instead of adding a second one.
#
# What it costs, said out loud: a renamed company becomes a second organisation, and so
# does a typo. Those are gaps, and a gap is recoverable. What it must never do is MERGE
# two different companies, which is why the match is exact-after-normalisation and never
# fuzzy, and why a second, different domain under one name is REPORTED as a conflict
# rather than quietly overwritten.
def _norm_org(name: Optional[str]) -> str:
    """The org identity key: lowercased, whitespace-collapsed. Nothing else — every
    further 'helpful' rule (dropping Ltd, stripping punctuation) is a rule that
    eventually merges two real companies."""
    return " ".join((name or "").strip().lower().split())


def _norm_domain(url: Optional[str]) -> str:
    """The bare host from a website, for corroboration only — never a merge key."""
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    raw = raw.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return raw[4:] if raw.startswith("www.") else raw


def resolve_org(conn, name: str = "", *, domain: str = "", agency_id: Optional[int] = None,
                commit: bool = True) -> Optional[int]:
    """The canonical id for this organisation, creating it on first sight.

    None without a name — there is nothing to be canonical about, and inventing an
    "Unknown" org would put every nameless row in one relationship.

    ``domain`` and ``agency_id`` only ever ENRICH the row: the first non-empty value
    wins and a later disagreement is left alone, so the org that Agency Intelligence
    knows and the org an opportunity names converge on one record without either being
    able to overwrite the other. ``commit=False`` is for the backfill (see link_people).
    """
    key = _norm_org(name)
    if not key:
        return None
    now = _now()
    host = _norm_domain(domain)
    row = conn.execute(
        "SELECT id, name, domain, agency_id FROM buyer_org WHERE name_key = ?",
        (key,)).fetchone()
    if row is not None:
        sets, args = ["last_seen_at = ?"], [now]
        if host and not (row["domain"] or ""):
            sets.append("domain = ?"); args.append(host)
        if agency_id and not row["agency_id"]:
            sets.append("agency_id = ?"); args.append(int(agency_id))
        args.append(row["id"])
        conn.execute(f"UPDATE buyer_org SET {', '.join(sets)} WHERE id = ?", tuple(args))
        if commit:
            conn.commit()
        return int(row["id"])
    conn.execute(
        "INSERT INTO buyer_org (name, name_key, domain, agency_id, first_seen_at, "
        "last_seen_at) VALUES (?,?,?,?,?,?)",
        ((name or "").strip(), key, host, agency_id, now, now))
    if commit:
        conn.commit()
    got = conn.execute("SELECT id FROM buyer_org WHERE name_key = ?", (key,)).fetchone()
    return int(got["id"]) if got is not None else None


def get_org(conn, org_id: int):
    return conn.execute("SELECT * FROM buyer_org WHERE id = ?", (org_id,)).fetchone()


def find_org(conn, name: str):
    key = _norm_org(name)
    if not key:
        return None
    return conn.execute("SELECT * FROM buyer_org WHERE name_key = ?", (key,)).fetchone()


def org_for_agency(conn, agency_id: int):
    return conn.execute("SELECT * FROM buyer_org WHERE agency_id = ?",
                        (agency_id,)).fetchone()


# Where an organisation can appear: (table, primary key, name column, domain column or
# None, what the appearance is called, timestamp column). Data rather than branches, so
# a new surface is one line here instead of a new case in three functions. Two of these
# are keyed by the client NAME rather than an integer id, which is the defect itself.
_ORG_SURFACES = (
    ("opportunities", "id", "client", None, "an opportunity", "created_at"),
    ("projects", "id", "client", None, "a project", "created_at"),
    ("agencies", "id", "company", "website", "an agency record", "created_at"),
    ("companies", "client", "client", "website", "a company record", "updated_at"),
    ("client_procurement_history", "client", "client", None,
     "procurement history", "updated_at"),
)


def link_orgs(conn) -> dict:
    """Give every row that names an organisation its canonical org, and report what
    happened. Idempotent, so it runs at boot and after any import.

    Rows with no name are left unlinked on purpose and counted, not hidden — the same
    contract as `link_people`'s `no_email`. A name that carries a website contributes
    the domain; a SECOND, different domain under one name is counted as a conflict
    rather than overwriting the first, because that is the shape a wrong merge would
    take and it should be visible when it happens.
    """
    linked, no_name, conflicts = 0, 0, 0
    for table, pk, name_col, domain_col, _label, _when in _ORG_SURFACES:
        cols = f"{pk} AS pk, {name_col} AS nm" + (f", {domain_col} AS dm" if domain_col else "")
        try:
            # Nameless rows are excluded by the QUERY: they can never be linked, and
            # re-reading them on every boot for ever is the waste ADR-0050 called out.
            rows = conn.execute(
                f"SELECT {cols} FROM {table} WHERE org_id IS NULL "
                f"AND {name_col} IS NOT NULL AND TRIM({name_col}) <> ''").fetchall()
            no_name += conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE org_id IS NULL "
                f"AND (({name_col} IS NULL) OR TRIM({name_col}) = '')").fetchone()["n"]
        except Exception:                       # noqa: BLE001 — table not in this DB yet
            continue
        for r in rows:
            host = _norm_domain(r["dm"]) if domain_col else ""
            agency = int(r["pk"]) if table == "agencies" else None
            # Read the org BEFORE resolving only when this row carries a domain to
            # conflict with — otherwise it is a second SELECT per row for an answer
            # that can never differ, which over tens of thousands of rows is the exact
            # waste ADR-0050 was written about. Only `agencies` and `companies` have a
            # domain column, and both are small.
            before = find_org(conn, r["nm"] or "") if host else None
            oid = resolve_org(conn, r["nm"] or "", domain=host, agency_id=agency,
                              commit=False)
            if oid is None:
                continue
            if before is not None and (before["domain"] or "") \
                    and before["domain"] != host:
                conflicts += 1
            conn.execute(f"UPDATE {table} SET org_id = ? WHERE {pk} = ?", (oid, r["pk"]))
            linked += 1
        conn.commit()
    total = conn.execute("SELECT COUNT(*) AS n FROM buyer_org").fetchone()["n"]
    return {"linked": linked, "no_name": no_name, "orgs": total,
            "domain_conflicts": conflicts}


def orgs_for_agencies(conn, agency_ids) -> dict:
    """{agency_id: org_row} in ONE query — how the Relationship Management side
    reaches the deals, which live under a client NAME it never had."""
    ids = [int(a) for a in agency_ids if a]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["agency_id"]: r for r in conn.execute(
        f"SELECT * FROM buyer_org WHERE agency_id IN ({marks})", tuple(ids))}


def orgs_by_ids(conn, org_ids) -> dict:
    """{org_id: org_row} in ONE query — how the Buyer Graph side reaches the agency
    record, and through it the outreach log it never had."""
    ids = [int(o) for o in org_ids if o]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["id"]: r for r in conn.execute(
        f"SELECT * FROM buyer_org WHERE id IN ({marks})", tuple(ids))}


def org_deal_rollup(conn, org_ids) -> dict:
    """Per-organisation deal rollup — {org_id: {opps, qualified, won, lost,
    open_pursuits, touches, last_contacted, strategic_value}} — in ONE GROUP BY for the
    whole set. `all_buyers` by another key: this is the same evidence, reachable from
    the agency side, which is what the two relationship engines never had between them.
    """
    ids = [int(o) for o in org_ids if o]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    out: dict = {}
    for r in conn.execute(
            f"""SELECT o.org_id AS org_id,
                       COUNT(*) AS opps,
                       SUM(o.qualified) AS qualified,
                       SUM(CASE WHEN o.status = 'Won' THEN 1 ELSE 0 END) AS won,
                       SUM(CASE WHEN o.status = 'Lost' THEN 1 ELSE 0 END) AS lost,
                       SUM(CASE WHEN o.status IN ('Pursuing','Submitted')
                                THEN 1 ELSE 0 END) AS open_pursuits,
                       MAX(o.strategic_value) AS strategic_value,
                       MAX(o.last_contacted) AS last_contacted
                FROM opportunities o WHERE o.org_id IN ({marks})
                GROUP BY o.org_id""", tuple(ids)):
        out[r["org_id"]] = {
            "opps": r["opps"], "qualified": r["qualified"] or 0,
            "won": r["won"] or 0, "lost": r["lost"] or 0,
            "open_pursuits": r["open_pursuits"] or 0,
            "strategic_value": r["strategic_value"],
            "last_contacted": r["last_contacted"], "touches": 0,
        }
    for r in conn.execute(
            f"""SELECT o.org_id AS org_id, COUNT(*) AS n, MAX(e.created_at) AS last_at
                FROM outreach_events e JOIN opportunities o ON e.opp_id = o.id
                WHERE o.org_id IN ({marks}) GROUP BY o.org_id""", tuple(ids)):
        row = out.get(r["org_id"])
        if row is not None:
            row["touches"] = r["n"]
            if r["last_at"] and (not row["last_contacted"]
                                 or r["last_at"] > row["last_contacted"]):
                row["last_contacted"] = r["last_at"]
    return out


# --------------------------------------------------------------------------- #
# Signatures (ADR-0059) — append-only evidence
# --------------------------------------------------------------------------- #
def record_signature(conn, sig) -> int:
    """Store a `signing.Signature`. Append-only: there is no update path on purpose.

    A signature you can edit is not a signature. Withdrawing one is `void_signature`,
    which marks the row and leaves it in place — the fact that something was signed and
    later withdrawn is itself the record.
    """
    cur = conn.execute(
        """INSERT INTO signature (project_id, doc_kind, digest, signer_name,
               signer_email, typed_name, consent_text, signed_at, actor,
               ip_fingerprint, user_agent, token_fingerprint, certified_version,
               terms_json, opportunity_id, drawn_mark, talent_id, contributor_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sig.project_id, sig.doc_kind, sig.digest, sig.signer_name, sig.signer_email,
         sig.typed_name, sig.consent_text, sig.signed_at, sig.actor,
         sig.ip_fingerprint, sig.user_agent, sig.token_fingerprint,
         sig.certified_version, json.dumps(sig.terms_snapshot, sort_keys=True),
         getattr(sig, "opportunity_id", 0) or 0, getattr(sig, "drawn_mark", "") or "",
         getattr(sig, "talent_id", 0) or 0, getattr(sig, "contributor_id", 0) or 0))
    conn.commit()
    return int(cur.lastrowid)


def list_signatures(conn, project_id: int, doc_kind: str = "") -> List[sqlite3.Row]:
    """Every signature on a project, newest first — including voided ones, which are
    part of the history rather than an embarrassment to hide."""
    if doc_kind:
        return conn.execute(
            "SELECT * FROM signature WHERE project_id = ? AND doc_kind = ? "
            "ORDER BY signed_at DESC", (project_id, doc_kind)).fetchall()
    return conn.execute(
        "SELECT * FROM signature WHERE project_id = ? ORDER BY signed_at DESC",
        (project_id,)).fetchall()


def latest_signature(conn, project_id: int, doc_kind: str):
    """The signature in force: newest, not voided. None when nothing is signed."""
    return conn.execute(
        "SELECT * FROM signature WHERE project_id = ? AND doc_kind = ? "
        "AND voided_at IS NULL ORDER BY signed_at DESC LIMIT 1",
        (project_id, doc_kind)).fetchone()


def latest_opportunity_signature(conn, opp_id: int, doc_kind: str):
    """The signature in force on an OPPORTUNITY's document — the proposal, signed before
    any project exists. Same rule as `latest_signature`: newest, not voided, None when
    nothing is signed. `project_id` is never consulted, so a signature that later gains a
    project cannot be found twice under two subjects."""
    return conn.execute(
        "SELECT * FROM signature WHERE opportunity_id = ? AND doc_kind = ? "
        "AND voided_at IS NULL ORDER BY signed_at DESC LIMIT 1",
        (int(opp_id), doc_kind)).fetchone()


def list_opportunity_signatures(conn, opp_id: int, doc_kind: str = "") -> List[sqlite3.Row]:
    """Every signature on an opportunity, newest first — voided ones included, which are
    part of the history rather than an embarrassment to hide."""
    if doc_kind:
        return conn.execute(
            "SELECT * FROM signature WHERE opportunity_id = ? AND doc_kind = ? "
            "ORDER BY signed_at DESC", (int(opp_id), doc_kind)).fetchall()
    return conn.execute(
        "SELECT * FROM signature WHERE opportunity_id = ? ORDER BY signed_at DESC",
        (int(opp_id),)).fetchall()


def latest_talent_signature(conn, talent_id: int, doc_kind: str):
    """The signature in force on a WRITER's document — the standing Composer Agreement.
    Same rule as the other two: newest, not voided, None when nothing is signed."""
    return conn.execute(
        "SELECT * FROM signature WHERE talent_id = ? AND doc_kind = ? "
        "AND voided_at IS NULL ORDER BY signed_at DESC LIMIT 1",
        (int(talent_id), doc_kind)).fetchone()


def list_talent_signatures(conn, talent_id: int, doc_kind: str = "") -> List[sqlite3.Row]:
    """Every signature on a writer, newest first — voided ones included, because a
    withdrawn agreement is part of the record rather than an embarrassment to hide."""
    if doc_kind:
        return conn.execute(
            "SELECT * FROM signature WHERE talent_id = ? AND doc_kind = ? "
            "ORDER BY signed_at DESC", (int(talent_id), doc_kind)).fetchall()
    return conn.execute(
        "SELECT * FROM signature WHERE talent_id = ? ORDER BY signed_at DESC",
        (int(talent_id),)).fetchall()


def latest_contributor_signature(conn, contributor_id: int, doc_kind: str):
    """The release in force for one contributor. Newest, not voided, None when unsigned."""
    return conn.execute(
        "SELECT * FROM signature WHERE contributor_id = ? AND doc_kind = ? "
        "AND voided_at IS NULL ORDER BY signed_at DESC LIMIT 1",
        (int(contributor_id), doc_kind)).fetchone()


def add_contributor(conn, *, project_id: int, name: str, role: str, email: str = "",
                    work: str = "", booked_by: str = "", talent_id: int = 0) -> int:
    """Name one person the composer worked with. Returns the contributor id."""
    import secrets
    cur = conn.execute(
        "INSERT INTO contributors (project_id, talent_id, name, email, role, work, "
        "booked_by, token, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (int(project_id), int(talent_id or 0), (name or "").strip(),
         (email or "").strip(), (role or "Performer").strip(), (work or "").strip(),
         (booked_by or "").strip(), public_token(16), _now()))
    conn.commit()
    return int(cur.lastrowid)


def list_contributors(conn, project_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM contributors WHERE project_id = ? ORDER BY id",
        (int(project_id),)).fetchall()


def contributor_by_token(conn, token: str):
    if not (token or "").strip():
        return None
    return conn.execute(
        "SELECT * FROM contributors WHERE token = ?", (token.strip(),)).fetchone()


def get_contributor(conn, contributor_id: int):
    return conn.execute(
        "SELECT * FROM contributors WHERE id = ?", (int(contributor_id),)).fetchone()


def mark_contributor_sent(conn, contributor_id: int) -> None:
    conn.execute("UPDATE contributors SET sent_at = ? WHERE id = ?",
                 (_now(), int(contributor_id)))
    conn.commit()


def remove_contributor(conn, contributor_id: int) -> bool:
    """Only while unsigned. A signed release is evidence and is never deleted — the
    same rule the signature table follows."""
    from .. import signing as _signing
    if latest_contributor_signature(
            conn, contributor_id, _signing.DOC_CONTRIBUTOR_RELEASE) is not None:
        return False
    conn.execute("DELETE FROM contributors WHERE id = ?", (int(contributor_id),))
    conn.commit()
    return True


def contributor_release_gaps(conn, project_id: int) -> List[dict]:
    """Everyone named on this project who has NOT signed their release.

    The clearance certificate's whole claim is that nothing in the work needs anyone
    else's permission. This is the list of people who could make that false, and it is
    the answer to "is the chain of title actually complete" — a question the certificate
    could not previously ask, because it was built from operator records rather than
    from anything anyone signed.
    """
    from .. import signing as _signing
    out: List[dict] = []
    for row in list_contributors(conn, project_id):
        if latest_contributor_signature(
                conn, row["id"], _signing.DOC_CONTRIBUTOR_RELEASE) is None:
            out.append({"id": row["id"], "name": row["name"], "role": row["role"],
                        "email": row["email"] or "", "sent_at": row["sent_at"] or ""})
    return out


def void_signature(conn, signature_id: int, *, by: str, reason: str) -> bool:
    """Withdraw a signature, keeping the row. Refuses to void an already-void one, so
    the audit trail cannot be rewritten by voiding twice with a different reason."""
    row = conn.execute("SELECT voided_at FROM signature WHERE id = ?",
                       (signature_id,)).fetchone()
    if row is None or row["voided_at"]:
        return False
    conn.execute(
        "UPDATE signature SET voided_at = ?, voided_by = ?, void_reason = ? WHERE id = ?",
        (_now(), (by or "").strip(), (reason or "").strip(), signature_id))
    conn.commit()
    return True


def org_touchpoints(conn, org_id: int) -> List[dict]:
    """Everything one organisation has with us, in one list, newest first — the
    question the five tables could not answer between them."""
    out = []
    for table, pk, _name_col, _domain_col, label, when_col in _ORG_SURFACES:
        try:
            rows = conn.execute(
                f"SELECT {pk} AS pk, {when_col} AS at FROM {table} WHERE org_id = ?",
                (org_id,)).fetchall()
        except Exception:                       # noqa: BLE001
            continue
        for r in rows:
            out.append({"what": label, "table": table, "row_id": r["pk"],
                        "at": r["at"] or ""})
    return sorted(out, key=lambda x: x["at"] or "", reverse=True)


# --------------------------------------------------------------------------- #
# Asking the same question twice in one render
# --------------------------------------------------------------------------- #
# The dashboard composes several cards from the same rows, and each card was built by
# an aggregator that fetched them for itself. Measured on the seeded demo — FOUR
# projects — one render cost **71 queries**, of which `SELECT delivery_json FROM
# projects WHERE id = ?` ran nine times, the projects list four times and the invoice
# lookup once per project. It is not a bug in any one of them: `next_action.compute`
# and `compute_queue` are each correct alone, and each re-reads what the handler had
# already read.
#
# On SQLite over a local file this was invisible. On Postgres every one of those is a
# network round trip, and the count grows with the number of projects — four projects
# cost 71, forty would cost hundreds, on the screen that is meant to open first.
#
# So: a memo, scoped to ONE request and thrown away with it, never a process-wide
# cache with a lifetime nobody can reason about. It memoises SELECT results by
# (sql, params) — and **any non-SELECT clears it**, so a handler that reads, writes and
# reads again cannot be served a stale row. Only a handler that opts in gets one.
class _MemoCursor:
    """A cursor's worth of already-fetched rows, replayable. Necessary because a real
    cursor is consumed by the first `fetchall`, and a memo that handed the same
    exhausted cursor to the second caller would return nothing at all."""

    __slots__ = ("_rows",)

    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)

    @property
    def rowcount(self):
        return len(self._rows)


class _ReadMemo:
    """Wraps a connection for the life of one read-only render."""

    def __init__(self, conn):
        self._conn = conn
        self._memo = {}
        self.hits = 0
        self.misses = 0

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        head = str(sql).lstrip()[:6].upper()
        if head != "SELECT":
            self._memo.clear()          # a write invalidates everything we remembered
            return self._conn.execute(sql, params)
        try:
            key = (str(sql), tuple(params))
        except TypeError:               # unhashable params — just do the query
            return self._conn.execute(sql, params)
        if key in self._memo:
            self.hits += 1
            return _MemoCursor(self._memo[key])
        self.misses += 1
        rows = self._conn.execute(sql, params).fetchall()
        self._memo[key] = rows
        return _MemoCursor(rows)


    def remember(self, sql, params, rows) -> None:
        """Seed an answer this render is about to ask for. Used by the priming helpers
        so one batched query can satisfy a hundred per-row ones."""
        try:
            self._memo[(str(sql), tuple(params))] = rows
        except TypeError:
            pass


def read_memo(conn) -> "_ReadMemo":
    """A connection that answers a repeated SELECT from memory for this request.

    For read-only handlers that compose several views of the same rows. Explicit and
    opt-in: a cache you have to ask for cannot surprise a handler that did not.
    """
    return _ReadMemo(conn)


# The two statements the dashboard asks once per project. Named so the batched
# primer below and the per-row helper cannot drift apart into two different strings.
_SQL_DELIVERY_BY_ID = "SELECT delivery_json FROM projects WHERE id = ?"
_SQL_INVOICES_BY_PROJECT = "SELECT * FROM invoices WHERE project_id = ? ORDER BY id"


def prime_project_reads(memo, project_ids) -> int:
    """Answer, in two queries, what the render would otherwise ask twice per project.

    The N+1 is not a mistake in any one function: `get_delivery` and the invoice lookup
    are per-project by nature, and the aggregators that call them are each correct
    alone. Rather than restructure them — which would mean threading batched data
    through `next_action` and `compute_queue` and every future caller — the answers are
    fetched in bulk and handed to the memo BEFORE the loop runs. The per-row code is
    untouched and simply never reaches the database.

    Returns the number of rows primed. A no-op on a plain connection.
    """
    ids = [int(i) for i in project_ids if i is not None]
    if not ids or not hasattr(memo, "remember"):
        return 0
    marks = ",".join("?" for _ in ids)
    primed = 0
    rows = memo.execute(
        f"SELECT id, delivery_json FROM projects WHERE id IN ({marks})", tuple(ids)
    ).fetchall()
    seen = set()
    for r in rows:
        memo.remember(_SQL_DELIVERY_BY_ID, (r["id"],), [r])
        seen.add(int(r["id"]))
        primed += 1
    for i in ids:                       # a project with no row still must not re-ask
        if i not in seen:
            memo.remember(_SQL_DELIVERY_BY_ID, (i,), [])

    inv = memo.execute(
        f"SELECT * FROM invoices WHERE project_id IN ({marks}) ORDER BY id", tuple(ids)
    ).fetchall()
    by_project = {i: [] for i in ids}
    for r in inv:
        by_project.setdefault(int(r["project_id"]), []).append(r)
        primed += 1
    for pid, rs in by_project.items():
        memo.remember(_SQL_INVOICES_BY_PROJECT, (pid,), rs)
    return primed


def save_media_blob(conn, name: str, content: bytes, content_type: str = "") -> None:
    """Mirror an uploaded file's bytes into the DB (durable across redeploys). Keyed by the
    same basename the /uploads route serves; best-effort (never blocks the upload)."""
    try:
        conn.execute(
            "INSERT INTO media_blob (name, content, content_type, size, created_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET content=excluded.content, "
            "content_type=excluded.content_type, size=excluded.size",
            (name, sqlite3.Binary(content), content_type, len(content), _now()))
        conn.commit()
    except sqlite3.Error:
        pass


def get_media_blob(conn, name: str):
    """Return (content_bytes, content_type) for a stored upload, or None."""
    row = conn.execute(
        "SELECT content, content_type FROM media_blob WHERE name = ?", (name,)).fetchone()
    if row is None or row["content"] is None:
        return None
    return bytes(row["content"]), (row["content_type"] or "")


def delete_media_blob(conn, name: str) -> None:
    try:
        conn.execute("DELETE FROM media_blob WHERE name = ?", (name,))
        conn.commit()
    except sqlite3.Error:
        pass


def delete_opportunity(conn: sqlite3.Connection, opp_id: int) -> dict:
    """Permanently delete an opportunity and EVERYTHING anchored to it — the whole account:
    its projects (+ assignments, milestones, review comments, updates, invoices, payouts,
    project events, proposals), its Campaign Intelligence (+ fields, events, captures,
    learning events), meetings + discovery requests + proposals, procurement, brief snapshots,
    commercial reviews/approvals, and the opportunity row itself. Built for clearing demo
    accounts; irreversible. Returns a small summary of what was removed.

    Client-scoped tables (companies, client_procurement_history) are NOT touched — a client
    name can span several opportunities, so deleting one deal must not wipe the buyer."""
    row = conn.execute("SELECT client, need FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    if row is None:
        return {"deleted": False}
    project_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM projects WHERE opp_id = ?", (opp_id,)).fetchall()]
    ci_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM campaign_intelligence WHERE opp_id = ?", (opp_id,)).fetchall()]

    def _del(sql, params):
        try:
            conn.execute(sql, params)
        except sqlite3.OperationalError:
            pass  # a table that doesn't exist in an older DB — skip, best-effort

    # Project-scoped children first.
    for pid in project_ids:
        for t in ("assignments", "milestones", "review_comments", "project_updates",
                  "invoices", "talent_payouts", "project_events"):
            _del(f"DELETE FROM {t} WHERE project_id = ?", (pid,))
    # CI-scoped children.
    for cid in ci_ids:
        for t in ("campaign_intelligence_field", "campaign_intelligence_event"):
            _del(f"DELETE FROM {t} WHERE ci_id = ?", (cid,))
    # Opp-scoped rows (proposals is opp_id-scoped; projects covers the rest).
    for t in ("outreach_events", "brief_progress", "proposals", "campaigns",
              "campaign_intelligence", "producer_learning_event", "procurement_requirement",
              "procurement_event", "captures", "meetings", "discovery_requests",
              "meeting_proposals", "brief_snapshots", "commercial_reviews",
              "commercial_approvals", "projects"):
        _del(f"DELETE FROM {t} WHERE opp_id = ?", (opp_id,))
    conn.execute("DELETE FROM opportunities WHERE id = ?", (opp_id,))
    conn.commit()
    return {"deleted": True, "client": row["client"], "need": row["need"],
            "projects": len(project_ids)}


# --- Discovery meetings (ADR-0014 §4.2) — tied to the opportunity before they begin ---- #
_MEETING_OPEN_STATUSES = ("scheduled", "bot_invited", "in_progress",
                          "transcript_ready", "ingested")


def create_meeting(conn: sqlite3.Connection, *, opp_id: int, ci_id: Optional[int] = None,
                   start_at: str = "", join_url: str = "", duration_min: int = 20,
                   provider: str = "manual", notetaker_provider: str = "",
                   scheduled_by: str = "operator", status: str = "scheduled",
                   meeting_type: str = "zoom", request_id: Optional[int] = None,
                   client_name: str = "", client_email: str = "",
                   external_meeting_id: str = "", calendar_event_id: str = "",
                   manage_token: str = "", bot_id: str = "",
                   initiated_by: str = "operator", bot_armed_at: str = "") -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO meetings
           (opp_id, ci_id, provider, join_url, external_meeting_id, start_at, duration_min,
            notetaker_provider, bot_id, status, scheduled_by, meeting_type, request_id,
            client_name, client_email, calendar_event_id, manage_token, initiated_by,
            bot_armed_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (opp_id, ci_id, provider, join_url, external_meeting_id, start_at, duration_min,
         notetaker_provider, bot_id, status, scheduled_by, meeting_type, request_id,
         client_name, client_email, calendar_event_id, manage_token, initiated_by,
         bot_armed_at, now, now))
    conn.commit()
    return int(cur.lastrowid)


# --- Discovery Requests (ADR-0016) — the client's ASK, before any scheduling ---------- #
def create_discovery_request(conn: sqlite3.Connection, *, opp_id: int, name: str = "",
                             email: str = "", company: str = "",
                             preferred_type: str = "zoom", message: str = "") -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO discovery_requests
           (opp_id, name, email, company, preferred_type, message, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (opp_id, name, email, company,
         "phone" if preferred_type == "phone" else "zoom", message, "new", now, now))
    conn.commit()
    return int(cur.lastrowid)


def get_discovery_request(conn: sqlite3.Connection, req_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM discovery_requests WHERE id = ?", (req_id,)).fetchone()


def list_discovery_requests(conn: sqlite3.Connection, opp_id: Optional[int] = None,
                            status: str = "") -> List[sqlite3.Row]:
    q = "SELECT * FROM discovery_requests"
    where, args = [], []
    if opp_id is not None:
        where.append("opp_id = ?"); args.append(opp_id)
    if status:
        where.append("status = ?"); args.append(status)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created_at DESC, id DESC"
    return conn.execute(q, args).fetchall()


def set_discovery_request_status(conn: sqlite3.Connection, req_id: int, status: str,
                                 meeting_id: Optional[int] = None) -> None:
    conn.execute(
        "UPDATE discovery_requests SET status = ?, meeting_id = COALESCE(?, meeting_id), "
        "updated_at = ? WHERE id = ?",
        (status, meeting_id, datetime.now(timezone.utc).isoformat(), req_id))
    conn.commit()


def pending_discovery_request_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) c FROM discovery_requests WHERE status = 'new'").fetchone()["c"])


# --- Brief snapshots (ADR-0017) — the sent document, frozen at send time ---------------- #
def create_brief_snapshot(conn: sqlite3.Connection, opp_id: int, doc_json: str) -> int:
    cur = conn.execute(
        "INSERT INTO brief_snapshots (opp_id, doc_json, created_at) VALUES (?,?,?)",
        (opp_id, doc_json, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return int(cur.lastrowid)


def get_brief_snapshot(conn: sqlite3.Connection, sid: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM brief_snapshots WHERE id = ?", (sid,)).fetchone()


def latest_brief_snapshot(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM brief_snapshots WHERE opp_id = ? ORDER BY id DESC LIMIT 1",
        (opp_id,)).fetchone()


# --- Commercial Reviews (ADR-0018) — the frozen agreement + its approval audit record --- #
def next_commercial_version(conn: sqlite3.Connection, opp_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(version) m FROM commercial_reviews WHERE opp_id = ?", (opp_id,)).fetchone()
    return int((row["m"] or 0)) + 1


def release_commercial_review(conn: sqlite3.Connection, opp_id: int, version: int,
                              doc_json: str, released_by: str = "operator") -> int:
    """Freeze + release a Review. Any prior still-'released' review for this opp is superseded
    (only one live offer at a time)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE commercial_reviews SET status='superseded' "
        "WHERE opp_id=? AND status='released'", (opp_id,))
    cur = conn.execute(
        """INSERT INTO commercial_reviews
           (opp_id, version, doc_json, status, released_by, released_at, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (opp_id, version, doc_json, "released", released_by, now, now))
    conn.commit()
    return int(cur.lastrowid)


def get_commercial_review(conn: sqlite3.Connection, rid: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM commercial_reviews WHERE id = ?", (rid,)).fetchone()


def current_commercial_review(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    """The live agreement for this opp: the most recent released-or-approved Review."""
    return conn.execute(
        "SELECT * FROM commercial_reviews WHERE opp_id=? AND status IN ('released','approved') "
        "ORDER BY version DESC, id DESC LIMIT 1", (opp_id,)).fetchone()


def set_commercial_review_status(conn: sqlite3.Connection, rid: int, status: str) -> None:
    conn.execute(
        "UPDATE commercial_reviews SET status=? WHERE id=?", (status, rid))
    conn.commit()


def create_commercial_approval(conn: sqlite3.Connection, *, opp_id: int, review_id: int,
                               approver_name: str = "", approver_email: str = "", ip: str = "",
                               user_agent: str = "", scope_ok: bool = False,
                               pricing_ok: bool = False, terms_ok: bool = False,
                               timeline_ok: bool = False) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO commercial_approvals
           (opp_id, review_id, approver_name, approver_email, ip, user_agent,
            scope_ok, pricing_ok, terms_ok, timeline_ok, approved_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (opp_id, review_id, approver_name, approver_email, ip, user_agent,
         int(scope_ok), int(pricing_ok), int(terms_ok), int(timeline_ok), now, now))
    conn.commit()
    return int(cur.lastrowid)


def approval_for_opp(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM commercial_approvals WHERE opp_id=? ORDER BY id DESC LIMIT 1",
        (opp_id,)).fetchone()


# --- Meeting Proposals — the operator's offer of times; the client's pick books it ------ #
def create_meeting_proposal(conn: sqlite3.Connection, *, opp_id: int, token: str,
                            slots: List[str], meeting_type: str = "zoom",
                            duration_min: int = 30, client_name: str = "",
                            client_email: str = "", message: str = "", join_url: str = "",
                            request_id: Optional[int] = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO meeting_proposals
           (opp_id, token, slots_json, meeting_type, duration_min, client_name, client_email,
            message, join_url, request_id, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (opp_id, token, json.dumps(list(slots)[:3]),
         "phone" if meeting_type == "phone" else "zoom", duration_min, client_name,
         client_email, message, join_url, request_id, "draft", now, now))
    conn.commit()
    return int(cur.lastrowid)


def get_meeting_proposal(conn: sqlite3.Connection, pid: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM meeting_proposals WHERE id = ?", (pid,)).fetchone()


def meeting_proposal_by_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    if not (token or "").strip():
        return None
    return conn.execute(
        "SELECT * FROM meeting_proposals WHERE token = ? LIMIT 1", (token,)).fetchone()


def list_meeting_proposals(conn: sqlite3.Connection, opp_id: int,
                           status: str = "") -> List[sqlite3.Row]:
    q, args = "SELECT * FROM meeting_proposals WHERE opp_id = ?", [opp_id]
    if status:
        q += " AND status = ?"; args.append(status)
    return conn.execute(q + " ORDER BY created_at DESC, id DESC", args).fetchall()


def update_meeting_proposal(conn: sqlite3.Connection, pid: int, **fields) -> None:
    allowed = {"status", "chosen_slot", "meeting_id", "slots_json", "client_name",
               "client_email", "message", "join_url", "meeting_type", "duration_min",
               "subject_override", "body_override"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?"); args.append(v)
    if not sets:
        return
    sets.append("updated_at = ?"); args.append(datetime.now(timezone.utc).isoformat())
    args.append(pid)
    conn.execute(f"UPDATE meeting_proposals SET {', '.join(sets)} WHERE id = ?", args)
    conn.commit()


def meeting_by_manage_token(conn: sqlite3.Connection, token: str) -> Optional[sqlite3.Row]:
    if not (token or "").strip():
        return None
    return conn.execute(
        "SELECT * FROM meetings WHERE manage_token = ? LIMIT 1", (token,)).fetchone()


def get_meeting(conn: sqlite3.Connection, meeting_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()


def record_confirmations(conn: sqlite3.Connection, meeting_id: int, entries: list) -> None:
    """Record where this meeting's confirmations went and what the mailer said.

    The whole point is that it is READABLE afterwards — "no mail provider configured"
    and "sent, and their calendar ignored it" are different problems with different
    fixes, and until this existed the product could not tell them apart."""
    try:
        conn.execute("UPDATE meetings SET confirmations_json = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(list(entries or [])),
                      datetime.now(timezone.utc).isoformat(), meeting_id))
        conn.commit()
    except Exception:  # noqa: BLE001 — bookkeeping never blocks a booking
        logger.exception("Could not record confirmations for meeting %s", meeting_id)


def confirmations(meeting) -> list:
    """The recorded confirmations for a meeting row, or ``[]``."""
    try:
        return list(json.loads(meeting["confirmations_json"] or "[]"))
    except Exception:  # noqa: BLE001
        return []


def bump_ical_sequence(conn: sqlite3.Connection, meeting_id: int) -> int:
    """Advance this meeting's invitation SEQUENCE and return the new value.

    Incremented in ONE statement rather than read-modify-written in Python, for the same
    reason `merge_json_key` is (ADR-0049): two updates racing must not both hand out the
    same number. A repeated SEQUENCE is not a cosmetic collision — every calendar client
    drops an update that does not exceed the sequence it already holds, so the second
    change to a meeting would vanish without an error anywhere.
    """
    conn.execute(
        "UPDATE meetings SET ical_sequence = COALESCE(ical_sequence, 0) + 1 WHERE id = ?",
        (meeting_id,))
    conn.commit()
    row = conn.execute("SELECT ical_sequence FROM meetings WHERE id = ?",
                       (meeting_id,)).fetchone()
    return int((row["ical_sequence"] if row is not None else 0) or 0)


def meeting_for_opp(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    """The opportunity's current (non-canceled) discovery meeting — what the contextual
    'Upcoming Discovery' panel renders. The most recent live one wins."""
    ph = ",".join("?" for _ in _MEETING_OPEN_STATUSES)
    return conn.execute(
        f"SELECT * FROM meetings WHERE opp_id = ? AND status IN ({ph}) "
        "ORDER BY start_at IS NULL, start_at, id DESC LIMIT 1",
        (opp_id, *_MEETING_OPEN_STATUSES)).fetchone()


def list_meetings(conn: sqlite3.Connection, opp_id: int) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM meetings WHERE opp_id = ? ORDER BY created_at DESC, id DESC",
        (opp_id,)).fetchall()


def meeting_by_external(conn: sqlite3.Connection, bot_id: str) -> Optional[sqlite3.Row]:
    """Correlate a capture-provider webhook back to its Meeting by the bot/session id."""
    if not bot_id:
        return None
    return conn.execute(
        "SELECT * FROM meetings WHERE bot_id = ? ORDER BY id DESC LIMIT 1", (bot_id,)).fetchone()


def meetings_awaiting_bot(conn, *, until_iso: str, now_iso: str) -> List[sqlite3.Row]:
    """Calls starting between now and ``until_iso`` that still need a capture bot booked.

    Two kinds. A call with no bot at all (the normal case now that arming is deferred),
    and a call whose bot was armed LONG before it — one of the old ad-hoc bots, which
    joined an empty room the day it was booked and is spent by the time the call comes
    round. Both want a bot booked for the real start time."""
    return conn.execute(
        "SELECT * FROM meetings "
        " WHERE status IN ('scheduled', 'bot_invited') "
        "   AND COALESCE(join_url, '') <> '' "
        "   AND COALESCE(start_at, '') <> '' "
        "   AND start_at <= ? AND start_at >= ? "
        "   AND (COALESCE(bot_id, '') = '' OR COALESCE(bot_armed_at, '') = '') "
        " ORDER BY start_at", (until_iso, now_iso)).fetchall()


def meetings_by_status(conn: sqlite3.Connection, status: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM meetings WHERE status = ? ORDER BY id", (status,)).fetchall()


def update_meeting(conn: sqlite3.Connection, meeting_id: int, **fields) -> None:
    """Patch a meeting (start_at, join_url, status, bot_id, transcript_capture_id, …).

    An unknown field RAISES. It used to be dropped in silence, which is a trap the
    poller walked straight into: `poll_attempts` was not on this list, so the backoff
    wrote nothing, every meeting stayed on attempt 0, and the fix would have shipped
    looking correct while changing nothing at all. A caller naming a column that does
    not exist has a bug either way; the only question is whether they find out.
    """
    allowed = {"start_at", "join_url", "duration_min", "status", "provider",
               "notetaker_provider", "bot_id", "external_meeting_id",
               "transcript_capture_id", "error", "poll_attempts", "last_polled_at",
               "bot_armed_at", "ical_sequence", "confirmations_json"}
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise ValueError(f"update_meeting: no such meeting field(s): {unknown}")
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    vals.append(datetime.now(timezone.utc).isoformat())
    vals.append(meeting_id)
    conn.execute(f"UPDATE meetings SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


# --- ADR-0013: CI anchored on the opportunity; adopted by the campaign at Won ------ #
def ci_for_opportunity(conn: sqlite3.Connection, opp_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM campaign_intelligence WHERE opp_id = ? ORDER BY id LIMIT 1",
        (opp_id,)).fetchone()


def attach_ci_to_campaign(conn: sqlite3.Connection, ci_id: int, *, campaign_id: int,
                          project_id: Optional[int] = None,
                          agency_id: Optional[int] = None) -> None:
    """Adopt an opportunity-born CI into a campaign IN PLACE — set the campaign/project
    links on the same row (never a second CI). The anti-recreation contract (ADR-0013)."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE campaign_intelligence
           SET campaign_id = ?, project_id = COALESCE(?, project_id),
               agency_id = COALESCE(?, agency_id), state = 'active', updated_at = ?
           WHERE id = ?""",
        (campaign_id, project_id, agency_id, now, ci_id))
    conn.commit()


def set_ci_field(conn: sqlite3.Connection, field_id: int, *, value: Optional[str] = None,
                 status: Optional[str] = None, human_value: Optional[bool] = None,
                 add_source: Optional[str] = None, is_concern: Optional[bool] = None,
                 proposed_value: Optional[str] = None, proposed_source: Optional[str] = None,
                 clear_proposed: bool = False) -> Optional[sqlite3.Row]:
    """By-id field updater for the edit / conflict paths (upsert_ci_field is the by-key
    contribute path). Only provided fields change; ``add_source`` merges into sources[];
    ``clear_proposed`` wipes a resolved conflict. Bumps both updated_at stamps."""
    row = conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE id = ?", (field_id,)).fetchone()
    if row is None:
        return None
    now = datetime.now(timezone.utc).isoformat()
    srcs = []
    try:
        srcs = json.loads(row["sources"]) or []
    except (json.JSONDecodeError, TypeError):
        srcs = []
    if add_source and add_source not in srcs:
        srcs.append(add_source)
    conn.execute(
        """UPDATE campaign_intelligence_field
           SET value = ?, status = ?, human_value = ?, sources = ?, is_concern = ?,
               proposed_value = ?, proposed_source = ?, updated_at = ?
           WHERE id = ?""",
        (row["value"] if value is None else value,
         row["status"] if status is None else status,
         row["human_value"] if human_value is None else (1 if human_value else 0),
         json.dumps(srcs),
         row["is_concern"] if is_concern is None else (1 if is_concern else 0),
         None if clear_proposed else (proposed_value if proposed_value is not None
                                      else row["proposed_value"]),
         None if clear_proposed else (proposed_source if proposed_source is not None
                                      else row["proposed_source"]),
         now, field_id))
    conn.execute("UPDATE campaign_intelligence SET updated_at = ? WHERE id = ?",
                 (now, row["ci_id"]))
    conn.commit()
    return conn.execute(
        "SELECT * FROM campaign_intelligence_field WHERE id = ?", (field_id,)).fetchone()


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
# --------------------------------------------------------------------------- #
# Merging one key of a JSON column, without losing the other writer
# --------------------------------------------------------------------------- #
# The per-record JSON blob is a deliberate pattern here (CLAUDE.md: "mirror this for
# new per-record editable state"), and it is a good one — `delivery_json` carries
# state that is genuinely per-project and genuinely shapeless. What was not good was
# how a single key got merged into it:
#
#     delivery = get_delivery(...)       # read the whole blob
#     delivery[key] = value              # modify in Python
#     save_delivery(...)                 # write the whole blob back
#
# Two writers overlapping in that window and the later write carries a blob read
# BEFORE the earlier one — so the earlier change is gone. Nothing raises, both callers
# are told they succeeded. Reproduced with two threads: a client approving an asset in
# the portal while the operator published a version in the console. **The client's
# approval vanished.** Not a rare interleaving either — publishing a version fires
# several `update_delivery` calls in a row, and the review portal is open on someone
# else's screen the whole time.
#
# The fix is not a lock around the read-modify-write; it is to stop doing a
# read-modify-write. Both backends can merge one key into a JSON document in a single
# statement, and a single statement cannot interleave with itself:
#
#     SQLite      json_set(doc, '$."key"', json(?))   /  json_remove(doc, '$."key"')
#     Postgres    doc::jsonb || ?::jsonb              /  doc::jsonb - ?
#
# This protects EVERY key, which promoting `versions` and `asset_approvals` to their
# own tables (the launch review's suggestion) would not have: `state`, `license`,
# `cues`, `pending_version` and `delivery_zip` race exactly the same way, and two of
# them decide what a client is looking at.
def _is_pg(conn) -> bool:
    return conn.__class__.__name__ == "_PgConn"


def merge_json_key(conn, table: str, row_id: int, column: str, key: str, value) -> None:
    """Set (or, with ``value=None``, remove) one key of a JSON text column, atomically.

    One statement, so a concurrent merge of a DIFFERENT key cannot erase this one. A
    concurrent merge of the SAME key is still last-write-wins, which is what "set this
    key" means and is the behaviour every caller already expects.
    """
    if not key or '"' in key:              # the key is interpolated into a JSON path
        raise ValueError(f"unsupported JSON key: {key!r}")
    if _is_pg(conn):
        if value is None:
            sql = (f"UPDATE {table} SET {column} = "
                   f"(COALESCE(NULLIF({column}, '')::jsonb, '{{}}'::jsonb) - ?)::text "
                   f"WHERE id = ?")
            params = (key, row_id)
        else:
            sql = (f"UPDATE {table} SET {column} = "
                   f"(COALESCE(NULLIF({column}, '')::jsonb, '{{}}'::jsonb) || ?::jsonb)::text "
                   f"WHERE id = ?")
            params = (json.dumps({key: value}), row_id)
    else:
        doc = f"COALESCE(NULLIF({column}, ''), '{{}}')"
        if value is None:
            sql = f"UPDATE {table} SET {column} = json_remove({doc}, ?) WHERE id = ?"
            params = (f'$."{key}"', row_id)
        else:
            sql = f"UPDATE {table} SET {column} = json_set({doc}, ?, json(?)) WHERE id = ?"
            params = (f'$."{key}"', json.dumps(value), row_id)
    try:
        conn.execute(sql, params)
        conn.commit()
    except Exception:                       # noqa: BLE001
        # The column already holds something that is not JSON. Both engines refuse to
        # merge into that, where the old read-modify-write silently reset it — so fall
        # back to exactly that, rather than turning a rescuable blob into a 500 on a
        # client's page. Racy, but only for a row that is already broken.
        try: conn.rollback()
        except Exception: pass
        _merge_json_key_by_rewrite(conn, table, row_id, column, key, value)


def _merge_json_key_by_rewrite(conn, table: str, row_id: int, column: str,
                               key: str, value) -> None:
    """Last resort for a column whose contents are not valid JSON — see above."""
    row = conn.execute(f"SELECT {column} AS c FROM {table} WHERE id = ?",
                       (row_id,)).fetchone()
    if row is None:
        return
    try:
        doc = json.loads(row["c"]) if row["c"] else {}
        if not isinstance(doc, dict):
            doc = {}
    except (ValueError, TypeError):
        doc = {}
    if value is None:
        doc.pop(key, None)
    else:
        doc[key] = value
    conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?",
                 (json.dumps(doc) if doc else None, row_id))
    conn.commit()


def get_delivery(conn: sqlite3.Connection, project_id: int) -> dict:
    """The project's Delivery OS state as a dict ({} when none/blank)."""
    row = conn.execute(
        _SQL_DELIVERY_BY_ID, (project_id,)
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
    """Merge a single delivery key (None removes it). Returns the updated dict.

    A `state` outside `DELIVERY_STATES` RAISES. The lifecycle was written as bare string
    literals at eighteen call sites, and the declared list had already drifted out of
    sync with them — `"Approved"` was being written and compared while not being a
    declared state at all. A typo here produces a delivery no template branch matches
    and no engine recognises, and nothing anywhere would say so.
    """
    if key == "state" and value not in (None, ""):
        from ..delivery import DELIVERY_STATES
        if value not in DELIVERY_STATES:
            raise ValueError(
                f"{value!r} is not a delivery state; expected one of {DELIVERY_STATES}")
    merge_json_key(conn, "projects", project_id, "delivery_json", key, value)
    return get_delivery(conn, project_id)


# --------------------------------------------------------------------------- #
# The Cue Layer (Phase 3, ADR-0027) — cues + hits as a per-project list on
# delivery_json['cues'], mirroring the references/pending_assets blob pattern
# (CLAUDE.md: "mirror this for new per-record editable state"). A cue is a named,
# timed span the composer scores; a hit is a moment inside the picture the music
# must honor. Cues carry their own state (open → take → published → approved) and
# map to the existing per-deliverable approval. Fail-soft: no cues → the room is
# the audio-and-notes room, unchanged.
#
# Cue shape:   {id, code, name, t_in, t_out, direction, state, approved_at}
# Hit shape:   {id, t, name}  (stored on the owning cue as cue['hits'])
CUE_STATES = ("open", "take", "published", "approved")
_CUE_STATES = CUE_STATES  # internal alias (kept for existing call sites)


def cues_touched_by_cut(conn: sqlite3.Connection, project_id: int,
                        cut_in=None, cut_out=None) -> list:
    """Which cues a picture change lands under (Phase 3 conform surfacing:
    'picture changed under m02'). With no window given, every cue is considered
    touched (a whole-timeline recut). Returns the affected cue codes."""
    ci, co = _num_or_none(cut_in), _num_or_none(cut_out)
    out = []
    for c in get_cues(conn, project_id):
        ti = c.get("t_in") if c.get("t_in") is not None else 0.0
        to = c.get("t_out") if c.get("t_out") is not None else ti
        if ci is None or co is None:
            out.append(c.get("code") or "")
        elif not (to < ci or ti > co):        # spans overlap
            out.append(c.get("code") or "")
    return [code for code in out if code]


# A generous ceiling on a stored timecode (24h) — a fat-fingered "99:99:99" is
# almost certainly a typo, not a real cue at hour 100 (eng P2).
_MAX_TIMECODE_SECONDS = 24 * 3600


def get_cues(conn: sqlite3.Connection, project_id: int) -> list:
    """The project's cue list (time-sorted), or [] — never raises."""
    cues = list(get_delivery(conn, project_id).get("cues") or [])
    cues.sort(key=lambda c: (c.get("t_in") if c.get("t_in") is not None else 1e9))
    return cues


def _mutate_cues(conn, project_id: int, fn):
    """Atomic read-modify-write of ``delivery_json['cues']`` (eng P0). Concurrent
    cue writers (two tabs, a double-click, a retried POST) otherwise race on the
    read → mutate → blind-UPDATE cycle and silently lose writes — worst case a
    human 'approve' lands on whatever content raced into that id. We take an
    IMMEDIATE write lock so the read and the write are one critical section;
    ``busy_timeout`` already makes the loser wait rather than error.

    ``fn(cues)`` mutates the list in place and returns the call's result."""
    import sqlite3 as _sq
    native = getattr(conn, "_conn", conn)          # unwrap the _PgConn shim if present
    is_sqlite = isinstance(native, _sq.Connection)
    if is_sqlite:
        native.execute("BEGIN IMMEDIATE")
    try:
        delivery = get_delivery(conn, project_id)
        cues = list(delivery.get("cues") or [])
        result = fn(cues)
        delivery["cues"] = cues
        # save_delivery commits, closing the IMMEDIATE transaction.
        save_delivery(conn, project_id, delivery)
        return result
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise


def _next_cue_id(cues: list) -> int:
    return (max((int(c.get("id") or 0) for c in cues), default=0) + 1)


def add_cue(conn: sqlite3.Connection, project_id: int, *, code: str = "",
            name: str = "", t_in=None, t_out=None, direction: str = "") -> dict:
    """Append a cue. ``code`` defaults to m01/m02… by position. Returns the cue."""
    box = {}

    def _do(cues):
        cue = {
            "id": _next_cue_id(cues),
            "code": (code or "").strip() or f"m{len(cues) + 1:02d}",
            "name": (name or "").strip(),
            "t_in": _num_or_none(t_in),
            "t_out": _num_or_none(t_out),
            "direction": (direction or "").strip(),
            "state": "open",
            "hits": [],
        }
        cues.append(cue)
        box["cue"] = cue
    _mutate_cues(conn, project_id, _do)
    return box["cue"]


def update_cue(conn: sqlite3.Connection, project_id: int, cue_id: int,
               **fields) -> Optional[dict]:
    """Merge fields into one cue (by id). Returns the cue, or None if not found."""
    box = {"cue": None}

    def _do(cues):
        for c in cues:
            if int(c.get("id") or 0) == int(cue_id):
                for k, v in fields.items():
                    if k in ("t_in", "t_out"):
                        v = _num_or_none(v)
                    c[k] = v
                box["cue"] = c
                return
    _mutate_cues(conn, project_id, _do)
    return box["cue"]


def set_cue_state(conn: sqlite3.Connection, project_id: int, cue_id: int,
                  state: str) -> Optional[dict]:
    """Advance/reset a cue's state (open|take|published|approved). Stamps
    ``approved_at`` when it lands on approved (cleared otherwise). Project-scoped."""
    if state not in _CUE_STATES:
        return None
    box = {"cue": None}

    def _do(cues):
        for c in cues:
            if int(c.get("id") or 0) == int(cue_id):
                c["state"] = state
                c["approved_at"] = _utc_now_iso() if state == "approved" else None
                box["cue"] = c
                return
    _mutate_cues(conn, project_id, _do)
    return box["cue"]


def delete_cue(conn: sqlite3.Connection, project_id: int, cue_id: int) -> bool:
    """Remove a cue by id. Returns True if one was removed."""
    box = {"ok": False}

    def _do(cues):
        kept = [c for c in cues if int(c.get("id") or 0) != int(cue_id)]
        box["ok"] = len(kept) != len(cues)
        cues[:] = kept
    _mutate_cues(conn, project_id, _do)
    return box["ok"]


def add_hit(conn: sqlite3.Connection, project_id: int, cue_id: int, *,
            t=None, name: str = "") -> Optional[dict]:
    """Add a hit (a moment the music must honor) to a cue. Returns the hit."""
    box = {"hit": None}

    def _do(cues):
        for c in cues:
            if int(c.get("id") or 0) == int(cue_id):
                hits = list(c.get("hits") or [])
                hit = {"id": (max((int(h.get("id") or 0) for h in hits), default=0) + 1),
                       "t": _num_or_none(t), "name": (name or "").strip()}
                hits.append(hit)
                hits.sort(key=lambda h: (h.get("t") if h.get("t") is not None else 1e9))
                c["hits"] = hits
                box["hit"] = hit
                return
    _mutate_cues(conn, project_id, _do)
    return box["hit"]


def delete_hit(conn: sqlite3.Connection, project_id: int, cue_id: int,
               hit_id: int) -> bool:
    """Remove a hit from a cue. Returns True if one was removed."""
    box = {"ok": False}

    def _do(cues):
        for c in cues:
            if int(c.get("id") or 0) == int(cue_id):
                hits = list(c.get("hits") or [])
                kept = [h for h in hits if int(h.get("id") or 0) != int(hit_id)]
                box["ok"] = len(kept) != len(hits)
                c["hits"] = kept
                return
    _mutate_cues(conn, project_id, _do)
    return box["ok"]


_CAPTURE_SHELF_MAX = 200


def add_capture(conn: sqlite3.Connection, project_id: int, text: str,
                by: str = "") -> Optional[dict]:
    """Append a private composer capture (Phase 4 §13): a jotted idea/motif that
    lands on the room's own shelf, timestamped. Stored on
    ``delivery_json['composer_shelf']`` — the composer's PRIVATE shelf, NEVER
    rendered on the client portal (the spec's "never visible to the client"). The
    shelf keeps the most recent ``_CAPTURE_SHELF_MAX`` entries so a self-serve,
    no-review write path can't grow the row unbounded (eng P2). Returns the entry."""
    body = (text or "").strip()[:600]
    if not body:
        return None
    delivery = get_delivery(conn, project_id)
    shelf = list(delivery.get("composer_shelf") or [])
    entry = {"id": (max((int(e.get("id") or 0) for e in shelf), default=0) + 1),
             "text": body, "by": (by or "").strip(), "at": _utc_now_iso()}
    shelf.append(entry)
    if len(shelf) > _CAPTURE_SHELF_MAX:
        shelf = shelf[-_CAPTURE_SHELF_MAX:]
    update_delivery(conn, project_id, "composer_shelf", shelf)
    return entry


def get_captures(conn: sqlite3.Connection, project_id: int) -> list:
    """The room's private composer shelf (newest first), or []."""
    shelf = list(get_delivery(conn, project_id).get("composer_shelf") or [])
    shelf.reverse()
    return shelf


def cue_for_time(cues: list, t) -> Optional[str]:
    """The code of the cue a timecode falls under (or None) — ties a client's
    timecoded note to the cue it lands in, so conform classification is anchored
    to the cue that actually changed (EP P0). First matching span wins."""
    tv = _num_or_none(t)
    if tv is None:
        return None
    for c in cues:
        ti = c.get("t_in")
        if ti is None:
            continue
        to = c.get("t_out")
        if to is None:
            if abs(tv - ti) < 0.5:
                return c.get("code")
        elif ti <= tv <= to:
            return c.get("code")
    return None


def cues_for_note(cues: list, t, t_end=None) -> Optional[str]:
    """The cue label a note is anchored to. For a point note it's the single cue
    under it; for a RANGE note it's every cue the span overlaps, joined ('m01–m02')
    — so the operator scoping conform-vs-revision sees a section note touches a
    section, not just its first frame (EP P0, Phase 4)."""
    te = _num_or_none(t_end)
    if te is None:
        return cue_for_time(cues, t)
    tv = _num_or_none(t)
    if tv is None:
        return None
    codes = []
    for c in cues:
        ti = c.get("t_in")
        if ti is None:
            continue
        to = c.get("t_out")
        to = ti if to is None else to
        if not (to < tv or ti > te):            # spans overlap
            code = c.get("code")
            if code and code not in codes:
                codes.append(code)
    if not codes:
        return None
    return codes[0] if len(codes) == 1 else (codes[0] + "–" + codes[-1])


def _num_or_none(v):
    """Parse a timecode to a non-negative finite float (seconds), else None.

    Accepts raw seconds ("14", "14.5") and clock form ("0:14", "1:23", "1:02:03")
    so the operator can type cues the way they read a timeline."""
    if v is None:
        return None
    import math as _m
    s = str(v).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        secs = 0.0
        for p in nums:                       # h:m:s or m:s, left-to-right
            secs = secs * 60 + p
    else:
        try:
            secs = float(s)
        except ValueError:
            return None
    if not _m.isfinite(secs) or secs < 0 or secs > _MAX_TIMECODE_SECONDS:
        return None                              # reject fat-fingered "99:99:99" (eng P2)
    return secs


def _utc_now_iso() -> str:
    from datetime import datetime as _dt, timezone as _tz
    return _dt.now(_tz.utc).isoformat()


def add_review_comment(
    conn: sqlite3.Connection, project_id: int, *, version: str = "", t_seconds=None,
    author: str = "", email: str = "", body: str = "", kind: str = "comment",
    parent_id=None, verified: bool = False, internal: bool = False, t_end=None,
    author_role: str = "",
) -> int:
    """Append a review-portal event: a timecoded comment, an approval, or a
    change request. Attributed to the reviewer's name + email. Returns the new id.

    ``parent_id`` (IP2) threads a reply one level under an existing comment — a
    reply answers its parent so it carries no timecode of its own.

    ``verified`` marks the event as posted from a verified reviewer's personal
    invite link (``?r=``) — its name + email are the locked roster identity.

    ``t_end`` (Phase 4) makes the note a RANGE — it covers t_seconds…t_end on the
    picture, rendered as a span, not a point. Only kept when it's a valid end past
    the start; otherwise the note stays a single-point pin."""
    te = _num_or_none(t_end)
    if te is not None and (t_seconds is None or te <= float(t_seconds)):
        te = None                                # a span must end after it starts
    cur = conn.execute(
        """INSERT INTO review_comments
           (project_id, version, t_seconds, t_end, author, email, body, kind, created_at,
            resolved, parent_id, verified, internal, author_role)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (project_id, version or "", t_seconds, te, author or "Anonymous",
         (email or "").strip() or None, body or "", kind,
         datetime.now(timezone.utc).isoformat(),
         0, int(parent_id) if parent_id not in (None, "") else None,
         1 if verified else 0, 1 if internal else 0,
         (author_role or "").strip()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_review_comments(
    conn: sqlite3.Connection, project_id: int, include_internal: bool = True
) -> List[sqlite3.Row]:
    """All review events for a project, oldest first (the campaign's feedback tape).

    ``include_internal=False`` is the CLIENT-portal view: composer↔studio internal
    replies never render there (the publish-gate principle applied to words)."""
    q = "SELECT * FROM review_comments WHERE project_id = ?"
    if not include_internal:
        q += " AND COALESCE(internal, 0) = 0"
    return conn.execute(q + " ORDER BY created_at ASC, id ASC", (project_id,)).fetchall()


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


DISPOSITIONS = ("conform", "revision", "out_of_scope")


def set_comment_disposition(conn, project_id: int, comment_id: int, how: str):
    """Classify one note. Returns the previous disposition, or None if there is no such
    note. An unknown value RAISES — a typo must not silently leave a note unpriced."""
    how = (how or "").strip().lower()
    if how and how not in DISPOSITIONS:
        raise ValueError(f"unknown disposition {how!r}")
    row = conn.execute(
        "SELECT disposition FROM review_comments WHERE id = ? AND project_id = ?",
        (comment_id, project_id)).fetchone()
    if row is None:
        return None
    was = (row["disposition"] or "")
    conn.execute("UPDATE review_comments SET disposition = ? WHERE id = ?",
                 (how, comment_id))
    # A conform is free by definition, and the two columns must not disagree — the room
    # and the console both read `conform` for the per-note "free" tag.
    conn.execute("UPDATE review_comments SET conform = ? WHERE id = ?",
                 (1 if how == "conform" else 0, comment_id))
    conn.commit()
    return was


def undispositioned_notes(conn, project_id: int) -> list:
    """Client notes waiting on a human. Top-level only — a reply rides its parent."""
    return conn.execute(
        "SELECT * FROM review_comments WHERE project_id = ? AND parent_id IS NULL"
        " AND IFNULL(disposition,'') = '' AND IFNULL(internal,0) = 0"
        " AND kind IN ('comment','change_request') ORDER BY id ASC",
        (project_id,)).fetchall()


def toggle_comment_conform(
    conn: sqlite3.Connection, project_id: int, comment_id: int
) -> Optional[int]:
    """Flip a note's species between revision (0) and conform (1) — the operator's
    scope classification (conforms never count against rounds). Project-scoped."""
    row = conn.execute(
        "SELECT COALESCE(conform, 0) AS cf FROM review_comments "
        "WHERE id = ? AND project_id = ?", (comment_id, project_id)).fetchone()
    if row is None:
        return None
    new_val = 0 if (row["cf"] or 0) else 1
    # The species toggle IS a disposition — the older, two-valued form of the same
    # decision (ADR-0069). Setting only `conform` left the note undispositioned, so the
    # operator classified it and the composer still could not see it.
    conn.execute(
        "UPDATE review_comments SET conform = ?, disposition = ? "
        "WHERE id = ? AND project_id = ?",
        (new_val, "conform" if new_val else "revision", comment_id, project_id))
    conn.commit()
    return new_val


def toggle_comment_addressed(
    conn: sqlite3.Connection, project_id: int, comment_id: int
) -> Optional[int]:
    """Flip the COMPOSER's addressed flag on a note — composer-side working state,
    entirely separate from the client's ``resolved`` (EP review P0-1: a composer
    marking their own work done must never change what the client sees as open).
    Scoped to the project; returns the new value, or None if not this project's."""
    row = conn.execute(
        "SELECT COALESCE(composer_addressed, 0) AS ca FROM review_comments "
        "WHERE id = ? AND project_id = ?",
        (comment_id, project_id),
    ).fetchone()
    if row is None:
        return None
    new_val = 0 if (row["ca"] or 0) else 1
    conn.execute(
        "UPDATE review_comments SET composer_addressed = ? WHERE id = ? AND project_id = ?",
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
    role: str = "", invited_by: str = "", inviter_expiry: str = "",
    days: Optional[int] = None,
) -> Optional[dict]:
    """Mint a verified reviewer + their personal access token, append to the roster.

    Returns the new reviewer dict (or None when the project is gone or no name was
    given). The token gates Approve — a verified reviewer link is required to lock
    FINAL + build the ZIP (a generic ``?k=`` share link can only view + comment as a
    guest) — and now gates Sign too (ADR-0059).

    ``invited_by`` names the CLIENT-side reviewer who delegated this access (ADR-0060).
    The entry it produces is weaker in three ways at once — shorter, capped at the
    inviter's expiry, and unable to sign, approve or delegate on — because access
    handed on must not outlive or outrank the access it came from.
    """
    name = (name or "").strip()
    if get_project(conn, project_id) is None or not name:
        return None
    roster = list_delivery_reviewers(conn, project_id)
    reviewer = reviewers.new_reviewer(
        token=public_token(13), name=name, email=email, role=role,
        invited_by=invited_by, inviter_expiry=inviter_expiry, days=days)
    roster.append(reviewer)
    update_delivery(conn, project_id, "reviewers", roster)
    return reviewer


def revoke_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, token: str, *, by: str = "",
) -> bool:
    """Withdraw a reviewer's link, KEEPING the roster entry (ADR-0060).

    The old behaviour deleted the row, which erased the fact that access had ever been
    granted — and with it any way to answer "who could see this in March". A revoked
    entry stops working immediately and stays visible in the console. Refuses to
    re-revoke, so the record cannot be rewritten with a later hand.
    """
    token = (token or "").strip()
    if not token:
        return False
    roster = list_delivery_reviewers(conn, project_id)
    changed = False
    for rv in roster:
        if (rv.get("token") or "") == token and not rv.get("revoked_at"):
            rv["revoked_at"] = _now()
            rv["revoked_by"] = (by or "").strip()
            changed = True
    if changed:
        update_delivery(conn, project_id, "reviewers", roster)
    return changed


def remove_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, token: str
) -> bool:
    """Drop a reviewer from the roster entirely. Kept for the case where an entry was
    created in error and should leave no trace; ``revoke_delivery_reviewer`` is the
    right call for withdrawing access from someone who really had it."""
    token = (token or "").strip()
    if not token:
        return False
    roster = list_delivery_reviewers(conn, project_id)
    kept = [r for r in roster if (r.get("token") or "") != token]
    if len(kept) == len(roster):
        return False
    update_delivery(conn, project_id, "reviewers", kept)
    return True


def extend_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, token: str, *, days: int,
) -> bool:
    """Push a link's expiry out from today. The operator's answer to "it expired and
    they still need it" — which must not be "delete and remint", because that changes
    the URL in a thread the client is already reading."""
    token = (token or "").strip()
    roster = list_delivery_reviewers(conn, project_id)
    changed = False
    for rv in roster:
        if (rv.get("token") or "") == token and not rv.get("revoked_at"):
            rv["expires_at"] = reviewers.expiry_after(days)
            changed = True
    if changed:
        update_delivery(conn, project_id, "reviewers", roster)
    return changed


def touch_delivery_reviewer(
    conn: sqlite3.Connection, project_id: int, token: str
) -> bool:
    """Record that a link was used today. At most ONE write per link per day — this
    is on the read path of a page clients leave open while listening."""
    roster = list_delivery_reviewers(conn, project_id)
    changed = False
    for i, rv in enumerate(roster):
        if (rv.get("token") or "") == token:
            roster[i], did = reviewers.touch(rv)
            changed = changed or did
    if changed:
        update_delivery(conn, project_id, "reviewers", roster)
    return changed


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
    token = public_token(13)
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
                  t.rate AS talent_rate, t.rate_unit AS talent_rate_unit,
                  t.pro AS talent_pro, t.publisher AS talent_publisher
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
    # One definition, shared with /revenue and the pipeline columns. This used to
    # sum budget_max — the client's stated ceiling — and call it pipeline.
    pipeline = open_pipeline(conn)
    pipeline_value = pipeline["value"]
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


# --------------------------------------------------------------------------- #
# Objection library + Discovery Call Simulator (see simulator.py)
# --------------------------------------------------------------------------- #
def _norm_objection(text: str) -> str:
    """Dedup key: lowercase, collapse whitespace/punctuation-light."""
    import re as _re
    out = _re.sub(r"[^a-z0-9 ]+", "", text.lower())
    return _re.sub(r"\s+", " ", out).strip()


def upsert_objection(conn: sqlite3.Connection, *, family: str, objection: str,
                     context: str = "", response_pattern: str = "",
                     result: str = "untested", source: str = "manual",
                     status: str = "confirmed", capture_id: Optional[int] = None) -> int:
    """Insert an objection, or — if an equivalent one exists — bump times_seen.

    The library LEARNS by repetition: the same objection harvested again from a
    new call raises its count instead of duplicating, so the simulator can weight
    personas toward what buyers actually keep saying."""
    now = datetime.now(timezone.utc).isoformat()
    key = _norm_objection(objection)
    for row in conn.execute("SELECT id, objection FROM objections"):
        if _norm_objection(row["objection"]) == key:
            conn.execute(
                "UPDATE objections SET times_seen = times_seen + 1, last_seen_at = ? WHERE id = ?",
                (now, row["id"]))
            conn.commit()
            return int(row["id"])
    cur = conn.execute(
        """INSERT INTO objections
           (family, objection, context, response_pattern, result, source, status,
            capture_id, times_seen, created_at, last_seen_at)
           VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
        (family, objection, context, response_pattern, result, source, status,
         capture_id, now, now))
    conn.commit()
    return int(cur.lastrowid)


def list_objections(conn: sqlite3.Connection, *, status: Optional[str] = None,
                    family: Optional[str] = None) -> list:
    q = "SELECT * FROM objections"
    conds, args = [], []
    if status:
        conds.append("status = ?"); args.append(status)
    if family:
        conds.append("family = ?"); args.append(family)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY family, times_seen DESC, id"
    return conn.execute(q, args).fetchall()


def get_objection(conn: sqlite3.Connection, objection_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM objections WHERE id = ?", (objection_id,)).fetchone()


def set_objection_status(conn: sqlite3.Connection, objection_id: int, status: str) -> None:
    if status not in ("proposed", "confirmed", "retired"):
        return
    conn.execute("UPDATE objections SET status = ? WHERE id = ?", (status, objection_id))
    conn.commit()


def create_sim_session(conn: sqlite3.Connection, *, persona: str, mode: str = "scripted") -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """INSERT INTO sim_sessions (persona, mode, status, transcript_json,
           objections_used, started_at) VALUES (?,?, 'live', '[]', '[]', ?)""",
        (persona, mode, now))
    conn.commit()
    return int(cur.lastrowid)


def get_sim_session(conn: sqlite3.Connection, session_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM sim_sessions WHERE id = ?", (session_id,)).fetchone()


def list_sim_sessions(conn: sqlite3.Connection, limit: int = 30) -> list:
    return conn.execute(
        "SELECT * FROM sim_sessions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def update_sim_session(conn: sqlite3.Connection, session_id: int, **fields) -> None:
    allowed = {"status", "transcript_json", "scorecard_json", "objections_used", "ended_at"}
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?"); args.append(v)
    if not sets:
        return
    args.append(session_id)
    conn.execute(f"UPDATE sim_sessions SET {', '.join(sets)} WHERE id = ?", args)
    conn.commit()


# --------------------------------------------------------------------------- #
# Session Room (Living OS P5) — project event bus helpers. Append-only; the
# audience column is the trust boundary, enforced here in SQL.
# --------------------------------------------------------------------------- #
def add_project_event(conn: sqlite3.Connection, project_id: int, kind: str, *,
                      actor_role: str = "", actor_name: str = "", body: str = "",
                      audience: str = "operator,client,talent") -> int:
    cur = conn.execute(
        "INSERT INTO project_events (project_id, kind, actor_role, actor_name,"
        " body, audience, created_at) VALUES (?,?,?,?,?,?,?)",
        (project_id, kind, actor_role, actor_name, body, audience,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_project_events(conn: sqlite3.Connection, project_id: int, *, role: str,
                        after_id: int = 0, limit: int = 50) -> list:
    """Events this ROLE is allowed to see, oldest-first after ``after_id``.
    The filter is server-side SQL — a client can never widen its own audience."""
    return conn.execute(
        "SELECT * FROM project_events WHERE project_id = ? AND id > ?"
        " AND (',' || audience || ',') LIKE ? ORDER BY id ASC LIMIT ?",
        (project_id, after_id, f"%,{role},%", limit),
    ).fetchall()


# --------------------------------------------------------------------------- #
# AI spend ledger (ADR-0023) — durable monthly estimate so the app can cap spend.
# --------------------------------------------------------------------------- #
def add_ai_spend(conn: sqlite3.Connection, month: str, est_cost: float,
                 *, calls: int = 0, in_tokens: int = 0, out_tokens: int = 0) -> None:
    """Accumulate this month's estimated Anthropic API spend (idempotent upsert)."""
    conn.execute(
        """INSERT INTO ai_spend (month, est_cost, calls, in_tokens, out_tokens, updated_at)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(month) DO UPDATE SET
             est_cost = est_cost + excluded.est_cost,
             calls = calls + excluded.calls,
             in_tokens = in_tokens + excluded.in_tokens,
             out_tokens = out_tokens + excluded.out_tokens,
             updated_at = excluded.updated_at""",
        (month, est_cost or 0, calls or 0, in_tokens or 0, out_tokens or 0,
         datetime.now(timezone.utc).isoformat()))
    conn.commit()


def ai_spend_month(conn: sqlite3.Connection, month: str) -> dict:
    """This month's ledger row as a plain dict (zeros when the month has no spend yet)."""
    row = conn.execute("SELECT * FROM ai_spend WHERE month = ?", (month,)).fetchone()
    if row is None:
        return {"month": month, "est_cost": 0.0, "calls": 0, "in_tokens": 0, "out_tokens": 0}
    return {"month": month, "est_cost": row["est_cost"] or 0.0, "calls": row["calls"] or 0,
            "in_tokens": row["in_tokens"] or 0, "out_tokens": row["out_tokens"] or 0}


def refile_ci_fields_to_canonical_slots(conn: sqlite3.Connection) -> int:
    """Move already-captured facts onto the canonical slot their key names. Returns how many.

    A repair, run once at boot, for the calls that were read correctly BEFORE the facet was
    derived rather than accepted (ADR-0064). A live discovery call's budget — "roughly 25.
    No, no, 30,000, all in including any licensing" — was extracted perfectly and filed as
    `commercial/budget_band`, one column away from the `engagement/budget_band` slot the
    Budget field, the estimate, the brief and the proposal all read. Fixing the intake only
    helps the NEXT call; this is what puts the answer already sitting in the database into
    the field that was empty above it.

    Deliberately conservative, because a repair that loses a human's work is worse than the
    bug: it moves a row ONLY when the canonical slot has no row of its own, so a value the
    operator typed or confirmed is never overwritten. A collision is left alone — both rows
    stay visible, and a person decides.
    """
    from . import campaign_intelligence as _ci
    moved = 0
    rows = conn.execute(
        "SELECT id, ci_id, facet, key, kind FROM campaign_intelligence_field "
        "WHERE kind = 'fact'").fetchall()
    taken = {(r["ci_id"], r["facet"], r["key"], r["kind"]) for r in rows}
    for r in rows:
        want_facet, want_key, want_kind = _ci.canonical_slot(r["facet"], r["key"], r["kind"])
        if (want_facet, want_key) == (r["facet"], r["key"]):
            continue
        target = (r["ci_id"], want_facet, want_key, want_kind)
        if target in taken:
            continue                     # a real value already lives there — leave both
        conn.execute(
            "UPDATE campaign_intelligence_field SET facet=?, key=?, updated_at=? WHERE id=?",
            (want_facet, want_key, datetime.now(timezone.utc).isoformat(), r["id"]))
        taken.discard((r["ci_id"], r["facet"], r["key"], r["kind"]))
        taken.add(target)
        moved += 1
    if moved:
        conn.commit()
    return moved
