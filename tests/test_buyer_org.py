"""One organisation, across every surface that names one.

ADR-0050 made the *person* canonical and said plainly that organisations were not.
This is that half. A company is `agencies.id` in Agency Intelligence and a bare name
string in `opportunities.client`, `projects.client`, `companies.client` and
`client_procurement_history.client`, and nothing joined them — which is why the product
grew two relationship systems over the same companies, each blind to the other's
evidence.

The identity is the normalised NAME, which is a weaker rule than the person half's and
is asserted here rather than assumed: an org with no website still has to be canonical,
and `match_agency_by_name` already threaded `agency_id` on exactly this basis. What the
rule must never do is merge two different companies, so the tests below pin the match to
exact-after-normalisation and pin the domain to corroboration only.
"""

import importlib

import pytest

from chordential_oia.web import db as db_mod


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "o.db"))
    importlib.reload(db_mod)
    c = db_mod.connect()
    db_mod.init_db(c)
    yield c
    c.close()


def _opp(conn, client, need="A spot"):
    cur = conn.execute(
        "INSERT INTO opportunities (client, need, created_at) VALUES (?,?,?)",
        (client, need, "2026-01-01T00:00:00+00:00"))
    conn.commit()
    return int(cur.lastrowid)


def _agency(conn, company, website=""):
    cur = conn.execute(
        "INSERT INTO agencies (source, dedup_key, company, website, created_at) "
        "VALUES (?,?,?,?,?)",
        ("test", company, company, website, "2026-01-01T00:00:00+00:00"))
    conn.commit()
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# The identity rule
# --------------------------------------------------------------------------- #
def test_one_company_written_four_ways_is_one_organisation(conn):
    """The defect, reduced: the same company arrives with different casing, padding
    and internal spacing from four different surfaces, and must be ONE org."""
    ids = {
        db_mod.resolve_org(conn, "Northwind Agency"),
        db_mod.resolve_org(conn, "northwind agency"),
        db_mod.resolve_org(conn, "  Northwind   Agency  "),
        db_mod.resolve_org(conn, "NORTHWIND AGENCY"),
    }
    assert len(ids) == 1, ids


def test_two_different_companies_are_never_merged(conn):
    """The failure that matters. Merging two organisations merges their deal history
    and their clearance record, which is a lie in a document a client signs against."""
    a = db_mod.resolve_org(conn, "Acme Marketing")
    b = db_mod.resolve_org(conn, "Acme Films")
    c = db_mod.resolve_org(conn, "Acme")
    assert len({a, b, c}) == 3


def test_a_nameless_row_gets_no_organisation(conn):
    """Evidence or nothing — the same contract as `resolve_person`. An invented
    "Unknown" org would put every nameless row into one relationship."""
    assert db_mod.resolve_org(conn, "") is None
    assert db_mod.resolve_org(conn, "   ") is None
    assert db_mod.resolve_org(conn, None) is None


def test_the_database_refuses_a_second_row_for_one_name(conn):
    """Enforced by the index, not by the resolver being careful: it is called from
    request threads and from the boot backfill at the same time."""
    db_mod.resolve_org(conn, "Northwind Agency")
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO buyer_org (name, name_key, first_seen_at, last_seen_at) "
            "VALUES (?,?,?,?)",
            ("Northwind Agency", "northwind agency", "x", "x"))
        conn.commit()


# --------------------------------------------------------------------------- #
# Domain — corroboration, never a merge key
# --------------------------------------------------------------------------- #
def test_a_domain_is_recorded_but_does_not_decide_identity(conn):
    a = db_mod.resolve_org(conn, "Northwind Agency", domain="https://www.northwind.com/about")
    assert db_mod.get_org(conn, a)["domain"] == "northwind.com"
    # Same domain, different company — a holding group and its subsidiary share one.
    b = db_mod.resolve_org(conn, "Northwind Films", domain="https://northwind.com")
    assert a != b, "two companies were merged because they share a website"


def test_a_second_different_domain_does_not_overwrite_the_first(conn):
    oid = db_mod.resolve_org(conn, "Northwind Agency", domain="northwind.com")
    db_mod.resolve_org(conn, "Northwind Agency", domain="northwind.co.uk")
    assert db_mod.get_org(conn, oid)["domain"] == "northwind.com"


def test_the_agency_link_is_recorded_from_whichever_side_arrives_first(conn):
    """The whole point: the string world reaches the integer one. An opportunity may
    name the company before Agency Intelligence has a row for it, or after."""
    oid = db_mod.resolve_org(conn, "Northwind Agency")           # from an opportunity
    assert db_mod.get_org(conn, oid)["agency_id"] is None
    db_mod.resolve_org(conn, "Northwind Agency", agency_id=42)   # later, from agencies
    assert db_mod.get_org(conn, oid)["agency_id"] == 42
    assert db_mod.org_for_agency(conn, 42)["id"] == oid


# --------------------------------------------------------------------------- #
# The backfill
# --------------------------------------------------------------------------- #
def test_the_backfill_links_every_surface_to_one_organisation(conn):
    """The question none of the five tables could answer between them."""
    aid = _agency(conn, "Northwind Agency", "https://northwind.com")
    oid_row = _opp(conn, "northwind agency")
    conn.execute("INSERT INTO projects (client, need, created_at) VALUES (?,?,?)",
                 ("NORTHWIND AGENCY", "A spot", "2026-01-02T00:00:00+00:00"))
    db_mod.set_company_website(conn, "Northwind  Agency", "northwind.com")
    conn.execute("INSERT INTO client_procurement_history (client, data, updated_at) "
                 "VALUES (?,?,?)", ("Northwind Agency", "{}", "2026-01-03"))
    conn.commit()

    report = db_mod.link_orgs(conn)
    assert report["orgs"] == 1, "five spellings of one company made more than one org"
    assert report["linked"] == 5

    org = db_mod.find_org(conn, "northwind agency")
    assert org["agency_id"] == aid
    assert org["domain"] == "northwind.com"
    assert len(db_mod.org_touchpoints(conn, org["id"])) == 5
    assert {t["table"] for t in db_mod.org_touchpoints(conn, org["id"])} == {
        "opportunities", "projects", "agencies", "companies",
        "client_procurement_history"}
    assert any(t["row_id"] == oid_row for t in db_mod.org_touchpoints(conn, org["id"]))


def test_the_backfill_is_idempotent(conn):
    """It runs at boot. A second boot must link nothing and create nothing."""
    _opp(conn, "Northwind Agency")
    _agency(conn, "Northwind Agency")
    first = db_mod.link_orgs(conn)
    second = db_mod.link_orgs(conn)
    assert first["linked"] == 2
    assert second["linked"] == 0, "the second boot re-linked rows it had already linked"
    assert second["orgs"] == first["orgs"] == 1


def test_rows_that_can_never_be_linked_are_not_re_read_for_ever(conn):
    """ADR-0050's lesson, kept: a nameless row is excluded by the QUERY, so it is
    counted and skipped rather than fetched and looped over on every boot."""
    conn.execute("INSERT INTO opportunities (client, need, created_at) VALUES (?,?,?)",
                 ("", "A spot", "2026-01-01"))
    conn.commit()
    report = db_mod.link_orgs(conn)
    assert report["no_name"] >= 1
    assert report["linked"] == 0


def test_a_domain_conflict_is_reported_not_hidden(conn):
    """Two websites under one name is the shape a wrong merge would take. It is
    counted so it can be looked at, rather than silently resolved by write order."""
    _agency(conn, "Northwind Agency", "https://northwind.com")
    _agency(conn, "northwind agency", "https://northwind.co.uk")
    report = db_mod.link_orgs(conn)
    assert report["orgs"] == 1
    assert report["domain_conflicts"] == 1


def test_the_backfill_does_not_commit_per_row(conn):
    """A commit per row turns a one-off pass over tens of thousands of rows into tens
    of thousands of fsyncs, which is the difference between a boot and an outage."""
    for i in range(40):
        _opp(conn, f"Company {i}")
    commits = {"n": 0}
    real = conn.commit

    class Counting:
        def __getattr__(self, k): return getattr(conn, k)
        def commit(self): commits["n"] += 1; return real()

    out = db_mod.link_orgs(Counting())
    assert out["linked"] == 40
    assert commits["n"] <= len(db_mod._ORG_SURFACES) + 1, (
        f"{commits['n']} commits for 40 rows — it is committing per row")


def test_the_boot_links_organisations(tmp_path, monkeypatch):
    """Wired, not merely written — the linking has to actually run at boot."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "b.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    c = db_mod.connect()
    try:
        orgs = c.execute("SELECT COUNT(*) AS n FROM buyer_org").fetchone()["n"]
        unlinked = c.execute(
            "SELECT COUNT(*) AS n FROM opportunities WHERE org_id IS NULL "
            "AND TRIM(client) <> ''").fetchone()["n"]
    finally:
        c.close()
    assert orgs > 0, "no organisations were resolved at boot"
    assert unlinked == 0, f"{unlinked} named opportunities left without an organisation"
