"""One buyer, across every surface they touch.

A human on the buying side was recorded in **five unlinked tables**, each with its own
name/email pair and nothing joining them:

    decision_makers     what enrichment found
    discovery_requests  who asked for a call
    meetings            who was on it
    meeting_proposals   who was offered times
    review_comments     who approved the work

So the same person asks for a call, takes it, and signs off the master as three
strangers — and the question the business actually has, *"who is this and what have we
done together"*, could not be asked at all.

**The identity is the email, and only the email.** Without one there is no canonical
person: `resolve_person` returns None rather than guess. Names are not identities — two
people are called John Smith; one person is "Priya Okonkwo", "P. Okonkwo" and "Priya".
A CRM that merges humans on a name eventually attributes one buyer's approval to
another, and these records are what a client signs against. A missing link is a gap; a
wrong link is a lie. Evidence or nothing.
"""

import importlib

import pytest

from chordential_oia.web import db as db_mod


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "b.db"))
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    c.execute("INSERT INTO opportunities (client, need) VALUES ('Northwind', 'Anthem')")
    c.execute("INSERT INTO projects (client, need) VALUES ('Northwind', 'Anthem')")
    c.commit()
    yield c
    c.close()


def _scatter_one_human(conn, email_variants=None):
    """The same person, as the five tables actually record her."""
    e = email_variants or ["  Priya@Northwind.com", "priya@northwind.com",
                           "PRIYA@NORTHWIND.COM", "priya@northwind.com "]
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO discovery_requests (opp_id, name, email, created_at) "
                 "VALUES (?,?,?,?)", (oid, "Priya", e[0], "2026-07-01T10:00:00Z"))
    conn.execute("INSERT INTO meetings (opp_id, client_name, client_email, start_at, status)"
                 " VALUES (?,?,?,?,?)",
                 (oid, "P. Okonkwo", e[1], "2026-07-03T15:00:00Z", "ingested"))
    conn.execute("INSERT INTO review_comments (project_id, author, email, body, created_at)"
                 " VALUES (?,?,?,?,?)",
                 (pid, "Priya O.", e[2], "Approved", "2026-07-20T09:00:00Z"))
    conn.execute("INSERT INTO decision_makers (agency_id, name, email, title, created_at)"
                 " VALUES (?,?,?,?,?)",
                 (1, "Priya Okonkwo", e[3], "Creative Director", "2026-06-01T00:00:00Z"))
    conn.commit()
    return oid, pid


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #
def test_one_human_across_five_tables_is_one_person(conn):
    """The whole point. Four rows, four spellings of her name, four casings and
    paddings of her email — one buyer."""
    _scatter_one_human(conn)
    result = db_mod.link_people(conn)
    assert result["people"] == 1, f"expected one buyer, got {result['people']}"
    assert result["linked"] == 4
    p = db_mod.find_person(conn, "priya@NORTHWIND.com ")
    assert p is not None
    assert p["email"] == "priya@northwind.com", "the email was not normalised"


def test_her_history_is_one_list(conn):
    """The question the five tables could not answer."""
    _scatter_one_human(conn)
    db_mod.link_people(conn)
    p = db_mod.find_person(conn, "priya@northwind.com")
    tp = db_mod.person_touchpoints(conn, p["id"])
    assert [t["what"] for t in tp] == [
        "reviewed the work", "on a call", "asked for a call", "known contact"], tp
    assert tp[0]["at"] > tp[-1]["at"], "not newest first"


def test_the_fullest_name_wins(conn):
    """Surfaces would otherwise show "Priya" or "P. Okonkwo" purely because of the
    order rows happened to be written in."""
    _scatter_one_human(conn)
    db_mod.link_people(conn)
    assert db_mod.find_person(conn, "priya@northwind.com")["name"] == "Priya Okonkwo"


def test_a_human_with_no_email_is_not_invented(conn):
    """The judgement this rests on. No email means no identity — NOT a person matched
    by name. Merging on a name is how one buyer's approval gets attributed to another,
    in records a client signs against."""
    assert db_mod.resolve_person(conn, "", "Someone from procurement") is None
    assert db_mod.resolve_person(conn, "   ", "Someone from procurement") is None
    assert db_mod.resolve_person(conn, "not-an-email", "Someone") is None
    assert conn.execute("SELECT COUNT(*) AS n FROM buyer_person").fetchone()["n"] == 0


def test_two_people_sharing_a_name_stay_two_people(conn):
    """The failure a name-based match would produce, stated directly."""
    a = db_mod.resolve_person(conn, "j.smith@northwind.com", "John Smith")
    b = db_mod.resolve_person(conn, "john.smith@vance.com", "John Smith")
    assert a != b
    assert conn.execute("SELECT COUNT(*) AS n FROM buyer_person").fetchone()["n"] == 2


def test_one_email_can_never_become_two_rows(conn):
    """Enforced by the database, not by the resolver being careful — the resolver is
    called from request threads and a backfill at boot."""
    db_mod.resolve_person(conn, "priya@northwind.com", "Priya")
    with pytest.raises(Exception):
        conn.execute("INSERT INTO buyer_person (email, name) VALUES (?,?)",
                     ("priya@northwind.com", "Impostor"))
        conn.commit()


# --------------------------------------------------------------------------- #
# The backfill
# --------------------------------------------------------------------------- #
def test_linking_is_idempotent(conn):
    """It runs at every boot. A second pass must link nothing and change nothing."""
    _scatter_one_human(conn)
    first = db_mod.link_people(conn)
    second = db_mod.link_people(conn)
    assert first["linked"] == 4
    assert second["linked"] == 0, "it re-linked rows that were already linked"
    assert second["people"] == 1


def test_rows_that_can_never_be_linked_are_not_re_read_for_ever(conn):
    """They are excluded by the QUERY, not skipped in the loop. With 38,924 decision
    makers, re-reading every email-less row on every boot for ever is the kind of quiet
    waste that only shows up at scale."""
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    for i in range(5):
        conn.execute("INSERT INTO discovery_requests (opp_id, name, email) VALUES (?,?,?)",
                     (oid, f"Anon {i}", ""))
    conn.commit()
    out = db_mod.link_people(conn)
    assert out["linked"] == 0
    assert out["no_email"] >= 5, "the gap is not reported, so nobody knows it exists"


def test_the_backfill_does_not_commit_per_row(conn):
    """A commit per row turns a one-off pass over tens of thousands of rows into tens
    of thousands of fsyncs — a boot becomes an outage."""
    commits = {"n": 0}
    real = conn.commit

    class Counting:
        def __getattr__(self, k): return getattr(conn, k)
        def commit(self): commits["n"] += 1; return real()

    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    for i in range(40):
        conn.execute("INSERT INTO discovery_requests (opp_id, name, email) VALUES (?,?,?)",
                     (oid, f"P{i}", f"p{i}@northwind.com"))
    conn.commit()
    commits["n"] = 0
    out = db_mod.link_people(Counting())
    assert out["linked"] == 40
    assert commits["n"] <= len(db_mod._PERSON_SURFACES) + 1, (
        f"{commits['n']} commits for 40 rows — it is committing per row")


def test_new_rows_are_picked_up_by_the_next_pass(conn):
    """Nothing writes `person_id` at insert time yet, so the boot pass is what keeps
    this current. If it stopped catching new rows the whole thing would rot silently."""
    _scatter_one_human(conn)
    db_mod.link_people(conn)
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO review_comments (project_id, author, email, body, created_at)"
                 " VALUES (?,?,?,?,?)",
                 (pid, "Priya", "priya@northwind.com", "One more note", "2026-08-01T00:00:00Z"))
    conn.commit()
    assert db_mod.link_people(conn)["linked"] == 1
    p = db_mod.find_person(conn, "priya@northwind.com")
    assert len(db_mod.person_touchpoints(conn, p["id"])) == 5


def test_people_are_ranked_by_how_much_history_they_have(conn):
    """A buyer we have actually worked with, versus a row we happen to hold."""
    _scatter_one_human(conn)
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO discovery_requests (opp_id, name, email) VALUES (?,?,?)",
                 (oid, "Barely Known", "someone@elsewhere.com"))
    conn.commit()
    db_mod.link_people(conn)
    ranked = db_mod.people_with_history(conn)
    assert ranked[0]["email"] == "priya@northwind.com"
    assert ranked[0]["touchpoints"] == 4
    assert "reviewed the work" in ranked[0]["surfaces"]
    assert ranked[-1]["touchpoints"] == 1


def test_a_boot_on_a_database_without_the_columns_does_not_crash(conn):
    """`_ensure_person_links` runs at the END of the migration on purpose — several of
    these tables are created further down than `buyer_person` is, and an ALTER against
    a table that does not exist yet takes the whole boot down. It did, once."""
    db_mod._ensure_person_links(conn)        # again, on a database that already has them
    db_mod._ensure_person_links(conn)
    for table, _e, _n, _l, _w in db_mod._PERSON_SURFACES:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert "person_id" in cols, table
