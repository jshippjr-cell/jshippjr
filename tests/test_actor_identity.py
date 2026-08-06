"""Every state change is attributable.

The product's central law is *"the machine proposes, Jon disposes"* — and the disposal
had no signature. Dozens of routes are decision buttons (qualify, assign, approve,
release, publish, unlock), and the actor recorded on them was a hardcoded string:
`"Studio"`, `"ChordOS"`, or nothing. With one operator that is untidy. The moment there
is a second, every past decision is unattributable and every future one ambiguous —
which is why the launch review calls multi-user auth the precondition for a first hire.

This is the bottom of that work, deliberately done before any login change: it is
additive, it cannot lock anyone out, and accounts are worth nothing without it.

**It records a ROLE, not a name.** The admin gate is one shared passphrase, so the
system genuinely does not know which human is behind it, and writing "Jon" into an audit
trail on the strength of a shared secret would be a lie in the one record that exists to
be trusted. It writes which door the request came through. When accounts arrive the
actor gains a name and no call site changes.

Recorded in the gate middleware rather than at each route, because stamping forty
decision routes by hand would miss the forty-first — and the one it misses is the one
someone disputes.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import actor  # noqa: E402
from chordential_oia.web import db as db_mod  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "a.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def _log(where=""):
    conn = db_mod.connect()
    rows = conn.execute("SELECT * FROM decision_log ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows if not where or where in (r["path"] or "")]


# --------------------------------------------------------------------------- #
# What gets recorded
# --------------------------------------------------------------------------- #
def test_a_decision_is_recorded_with_who_what_and_which_record(client):
    conn = db_mod.connect()
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    conn.close()
    client.post(f"/opportunity/{oid}/status", data={"status": "Pursuing"},
                follow_redirects=False)
    rows = _log(f"/opportunity/{oid}/status")
    assert rows, "the decision was not recorded at all"
    r = rows[-1]
    assert r["method"] == "POST"
    assert r["subject_type"] == "opportunity" and r["subject_id"] == oid
    assert r["actor_kind"] in (actor.OPERATOR, actor.PUBLIC)
    assert r["at"], "no timestamp"


def test_a_page_view_is_not_a_decision(client):
    """Logging every GET would bury the record this exists to keep."""
    before = len(_log())
    client.get("/dashboard")
    client.get("/projects")
    assert len(_log()) == before


def test_a_failed_request_is_recorded_too(client):
    """The attempt is the interesting part. An audit trail that only holds successes
    cannot answer "who tried"."""
    client.post("/opportunity/999999/status", data={"status": "Won"},
                follow_redirects=False)
    rows = _log("/opportunity/999999/status")
    assert rows, "a failed decision left no trace"
    assert rows[-1]["status"] >= 200


# --------------------------------------------------------------------------- #
# Who
# --------------------------------------------------------------------------- #
def test_a_client_acting_on_a_share_link_is_not_the_operator(client):
    """The distinction the log exists for: a client approving their own master and the
    studio approving it are different acts by different people, and they used to be
    written down identically."""
    conn = db_mod.connect()
    row = conn.execute("SELECT id, share_token FROM projects "
                       "WHERE share_token IS NOT NULL AND share_token <> '' "
                       "LIMIT 1").fetchone()
    conn.close()
    if row is None:
        pytest.skip("no seeded project with a share token")
    client.post(f"/project/{row['id']}/review/comment?k={row['share_token']}",
                data={"body": "Sounds great", "author": "Priya", "email": "p@n.com"},
                follow_redirects=False)
    rows = _log(f"/project/{row['id']}/review/comment")
    assert rows, "a client action was not recorded"
    assert rows[-1]["actor_kind"] == actor.CLIENT
    assert rows[-1]["subject_type"] == "project"


def test_the_token_itself_is_never_written_down(client):
    """A share token in a log is a credential in a log. The fingerprint tells two
    clients apart and is useless to whoever reads it."""
    conn = db_mod.connect()
    row = conn.execute("SELECT id, share_token FROM projects "
                       "WHERE share_token IS NOT NULL AND share_token <> '' "
                       "LIMIT 1").fetchone()
    conn.close()
    if row is None:
        pytest.skip("no seeded project with a share token")
    token = row["share_token"]
    client.post(f"/project/{row['id']}/review/comment?k={token}",
                data={"body": "hi", "author": "P", "email": "p@n.com"},
                follow_redirects=False)
    for r in _log():
        assert token not in (r["actor_ref"] or ""), "the raw token was logged"
        assert token not in (r["path"] or ""), "the raw token was logged in the path"


def test_the_same_client_is_recognisable_across_visits():
    """Without this the log is a list of anonymous events; with it you can follow one
    reviewer through a campaign."""
    a = actor._fingerprint("token-abc")
    b = actor._fingerprint("token-abc")
    c = actor._fingerprint("token-xyz")
    assert a == b and a != c and len(a) == 12


def test_the_operator_is_a_role_because_that_is_all_we_know(monkeypatch):
    """The honesty call. One shared passphrase means the system cannot know WHICH
    human, and an audit trail that names one anyway is worse than one that admits it
    does not know."""
    class Req:
        class url: path = "/dashboard"
        query_params = {}
    monkeypatch.setattr("chordential_oia.web.shell.admin_authed", lambda r: True)
    who = actor.identify(Req())
    assert who["kind"] == actor.OPERATOR
    assert who["label"] == "the operator"
    assert "Jon" not in who["label"], "a name we do not have must not be asserted"


def test_a_creator_portal_link_is_its_own_actor(monkeypatch):
    class Req:
        class url: path = "/creator/abc123/project/7/deliverable"
        query_params = {}
    monkeypatch.setattr("chordential_oia.web.shell.admin_authed", lambda r: False)
    who = actor.identify(Req())
    assert who["kind"] == actor.CREATOR
    assert who["ref"] == actor._fingerprint("abc123")


# --------------------------------------------------------------------------- #
# It must never be the thing that breaks a request
# --------------------------------------------------------------------------- #
def test_a_broken_log_never_breaks_the_decision(client, monkeypatch):
    """An audit trail that can 500 a client's approval is worse than no audit trail.
    The write it was recording has already happened by then."""
    conn = db_mod.connect()
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    conn.close()
    monkeypatch.setattr(actor, "record",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log is down")))
    r = client.post(f"/opportunity/{oid}/status", data={"status": "Pursuing"},
                    follow_redirects=False)
    assert r.status_code in (200, 303), "a failing audit log broke the decision"
    conn = db_mod.connect()
    got = conn.execute("SELECT status FROM opportunities WHERE id = ?", (oid,)).fetchone()
    conn.close()
    assert got["status"] == "Pursuing", "the decision itself was lost"


def test_identify_never_raises_on_a_hostile_request():
    class Req:
        def __getattr__(self, k): raise RuntimeError("nope")
    who = actor.identify(Req())
    assert who["kind"] == actor.PUBLIC


# --------------------------------------------------------------------------- #
# The subject
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,expected", [
    ("/project/12/delivery/release", ("project", 12)),
    ("/opportunity/7/status", ("opportunity", 7)),
    ("/invoice/3/status", ("invoice", 3)),
    ("/dashboard", (None, None)),
    ("/project/not-a-number/x", (None, None)),
])
def test_the_subject_is_pulled_out_of_the_url(path, expected):
    """So "what happened to this project" is a query rather than a string-parsing
    exercise someone does later, badly."""
    assert actor.subject_of(path) == expected
