"""How long a client's access lasts, and who they can hand it to.

A verified reviewer's personal link was four fields::

    {"token": "FwSd7R4HH7oq", "name": "Dana Whitfield",
     "email": "dana@aurora.com", "role": "Business affairs"}

Measured on the engine before this: no expiry, so a link mailed once works for ever;
no record of use, so nobody can tell a live link from one in a two-year-old thread; no
revocation, only deletion, which erases the fact access was ever granted; no record of
who issued it; and no statement of what it may DO — which mattered the moment signing
arrived (ADR-0059), because every link could sign.

And a client had no way to give a colleague access at all, so in practice the link gets
forwarded: the real access model was "whoever has the URL" while the records said one
named person. **Delegation here is not a new hole — it is that hole, bounded.**

The two properties everything else serves:
`test_a_delegate_cannot_sign_or_approve` and `test_delegation_does_not_chain`.
"""

import importlib
from datetime import date, timedelta

import pytest

from chordential_oia import reviewers
from chordential_oia.web import db as db_mod

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


# --------------------------------------------------------------------------- #
# The policy
# --------------------------------------------------------------------------- #
def test_a_link_now_states_its_whole_lifecycle():
    rv = reviewers.new_reviewer(token="t", name="Dana Whitfield", email="d@a.com")
    for field in ("created_at", "expires_at", "last_used_at", "revoked_at",
                  "invited_by", "can_sign", "can_approve", "can_delegate"):
        assert field in rv, field


def test_a_delegate_cannot_sign_or_approve():
    """Signing and approving bind the deal (ADR-0020, ADR-0059). They stay with
    someone the OPERATOR named, or a forwarded invite chain ends in a signature
    nobody at Chordential ever authorised."""
    operator_invited = reviewers.new_reviewer(token="a", name="Dana")
    delegate = reviewers.new_reviewer(token="b", name="Sam", invited_by="Dana")
    assert reviewers.capabilities(operator_invited) == {
        "sign": True, "approve": True, "delegate": True}
    assert reviewers.capabilities(delegate) == {
        "sign": False, "approve": False, "delegate": False}


def test_delegation_does_not_chain():
    """Chains are how a link ends up somewhere nobody intended."""
    delegate = reviewers.new_reviewer(token="b", name="Sam", invited_by="Dana")
    assert reviewers.capabilities(delegate)["delegate"] is False


def test_a_delegates_access_cannot_outlive_its_inviters():
    """Access handed on must not outlast the access it came from."""
    d = reviewers.new_reviewer(token="b", name="Sam", invited_by="Dana",
                               inviter_expiry=_day(3))
    assert d["expires_at"] == _day(3)


def test_a_delegate_of_a_never_expiring_link_still_expires():
    """The cap is a ceiling, not a licence: an inviter with no expiry must not mint
    colleagues with no expiry."""
    d = reviewers.new_reviewer(token="b", name="Sam", invited_by="Dana",
                               inviter_expiry="")
    assert d["expires_at"] == _day(reviewers.DEFAULT_DELEGATE_DAYS)


def test_expiry_is_never_applied_retroactively():
    """A roster entry written before these fields existed keeps working exactly as it
    did. Adding an expiry to links already in the wild would cut off live clients
    mid-review to make a refactor tidy."""
    legacy = {"token": "old", "name": "Dana", "email": "d@a.com", "role": "BA"}
    assert reviewers.state_of(legacy) == reviewers.ACTIVE
    assert reviewers.capabilities(legacy) == {
        "sign": True, "approve": True, "delegate": True}


def test_the_states_are_distinguished():
    assert reviewers.state_of({"expires_at": _day(-1)}) == reviewers.EXPIRED
    assert reviewers.state_of({"expires_at": _day(1)}) == reviewers.ACTIVE
    assert reviewers.state_of({"revoked_at": "2026-01-01"}) == reviewers.REVOKED
    # Revocation beats a future expiry — withdrawn is withdrawn.
    assert reviewers.state_of(
        {"revoked_at": "2026-01-01", "expires_at": _day(9)}) == reviewers.REVOKED


def test_an_expired_link_gets_an_explanation_not_a_shrug():
    """The person holding it is a real client who really was invited. "Not found"
    sends them back to their inbox to check they clicked the right thing."""
    note = reviewers.access_note(reviewers.EXPIRED, {"expires_at": "2026-01-01"})
    assert "expired on 2026-01-01" in note and "nothing is lost" in note
    assert "withdrawn" in reviewers.access_note(reviewers.REVOKED).lower()


def test_use_is_recorded_at_most_once_a_day():
    """Per-request would be a JSON merge write on every refresh of a page clients
    leave open while a mix plays."""
    rv = reviewers.new_reviewer(token="t", name="Dana")
    once, changed = reviewers.touch(rv)
    assert changed and once["last_used_at"] == date.today().isoformat()
    _, changed_again = reviewers.touch(once)
    assert not changed_again


def test_the_link_lifetime_is_a_dial(monkeypatch):
    monkeypatch.setenv(reviewers.LINK_DAYS_ENV, "7")
    assert reviewers.new_reviewer(token="t", name="D")["expires_at"] == _day(7)
    monkeypatch.setenv(reviewers.LINK_DAYS_ENV, "0")       # 0 = never
    assert reviewers.new_reviewer(token="t", name="D")["expires_at"] == ""
    monkeypatch.setenv(reviewers.LINK_DAYS_ENV, "not-a-number")
    assert reviewers.new_reviewer(token="t", name="D")["expires_at"] == \
        _day(reviewers.DEFAULT_LINK_DAYS)


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _project(conn):
    return conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]


def test_withdrawing_keeps_the_entry(app_mod):
    """Deleting it erased the fact that access had ever been granted — and with it
    any way to answer "who could see this in March"."""
    conn = db_mod.connect()
    pid = _project(conn)
    rv = db_mod.add_delivery_reviewer(conn, pid, name="Dana", email="d@a.com")
    assert db_mod.revoke_delivery_reviewer(conn, pid, rv["token"], by="Jon Shipp")
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    assert len(roster) == 1
    assert roster[0]["revoked_by"] == "Jon Shipp"
    assert reviewers.state_of(roster[0]) == reviewers.REVOKED


def test_a_withdrawal_cannot_be_rewritten_by_a_later_hand(app_mod):
    conn = db_mod.connect()
    pid = _project(conn)
    rv = db_mod.add_delivery_reviewer(conn, pid, name="Dana")
    assert db_mod.revoke_delivery_reviewer(conn, pid, rv["token"], by="Jon")
    assert not db_mod.revoke_delivery_reviewer(conn, pid, rv["token"], by="Someone")
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    assert roster[0]["revoked_by"] == "Jon"


def test_extending_keeps_the_same_url(app_mod):
    """"It expired and they still need it" must not be answered by delete-and-remint:
    that changes the URL in a thread the client is already reading."""
    conn = db_mod.connect()
    pid = _project(conn)
    rv = db_mod.add_delivery_reviewer(conn, pid, name="Dana", days=1)
    before = rv["token"]
    assert db_mod.extend_delivery_reviewer(conn, pid, before, days=120)
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    assert roster[0]["token"] == before
    assert roster[0]["expires_at"] == _day(120)


def test_a_revoked_link_cannot_be_extended_back_to_life(app_mod):
    conn = db_mod.connect()
    pid = _project(conn)
    rv = db_mod.add_delivery_reviewer(conn, pid, name="Dana")
    db_mod.revoke_delivery_reviewer(conn, pid, rv["token"], by="Jon")
    assert not db_mod.extend_delivery_reviewer(conn, pid, rv["token"], days=90)
    conn.close()


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #
def _roster_project(conn, **kw):
    pid = _project(conn)
    db_mod.update_delivery(conn, pid, "license_confirmed",
                           {"by": "Jon Shipp", "date": "2026-08-01"})
    rv = db_mod.add_delivery_reviewer(conn, pid, name="Dana Whitfield",
                                      email="dana@aurora.com", **kw)
    return pid, rv


def test_an_expired_link_is_told_what_happened(app_mod):
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    db_mod.extend_delivery_reviewer(conn, pid, rv["token"], days=1)
    roster = db_mod.list_delivery_reviewers(conn, pid)
    roster[0]["expires_at"] = _day(-1)
    db_mod.update_delivery(conn, pid, "reviewers", roster)
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.get(f"/project/{pid}/delivery-portal?r={rv['token']}")
        assert r.status_code == 410, "an expired link 404d as if it never existed"
        assert "expired" in r.text.lower()


def test_a_revoked_link_stops_working_immediately(app_mod):
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    db_mod.revoke_delivery_reviewer(conn, pid, rv["token"], by="Jon")
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.get(f"/project/{pid}/delivery-portal?r={rv['token']}")
        assert r.status_code == 410
        assert "withdrawn" in r.text.lower()


def test_opening_the_portal_records_the_link_as_alive(app_mod):
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.get(f"/project/{pid}/delivery-portal?r={rv['token']}").status_code == 200
    conn = db_mod.connect()
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    assert roster[0]["last_used_at"] == date.today().isoformat()


def test_a_reviewer_can_bring_in_a_colleague(app_mod):
    """The delegation the product had no way to express, so the link got forwarded."""
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    conn.close()
    with TestClient(app_mod.app) as c:
        r = c.post(f"/project/{pid}/delivery/delegate",
                   data={"name": "Sam Reyes", "email": "sam@aurora.com",
                         "role": "Legal", "r": rv["token"]}, follow_redirects=False)
        assert r.status_code == 303, r.text[:300]
    conn = db_mod.connect()
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    sam = next(x for x in roster if x["name"] == "Sam Reyes")
    assert sam["invited_by"] == "Dana Whitfield"
    assert sam["token"] != rv["token"], "the colleague got a copy, not their own link"
    assert reviewers.capabilities(sam) == {"sign": False, "approve": False,
                                           "delegate": False}


def test_a_delegate_cannot_sign_the_certificate(app_mod):
    """End to end: the strongest act stays with someone the operator named."""
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    sam = db_mod.add_delivery_reviewer(conn, pid, name="Sam Reyes",
                                       invited_by="Dana Whitfield")
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.post(f"/project/{pid}/delivery/sign",
                      data={"typed_name": "Sam Reyes", "consent": "1",
                            "r": sam["token"]},
                      follow_redirects=False).status_code == 403
        # ...and the person the operator DID name still can.
        assert c.post(f"/project/{pid}/delivery/sign",
                      data={"typed_name": "Dana Whitfield", "consent": "1",
                            "r": rv["token"]},
                      follow_redirects=False).status_code == 303


def test_a_delegate_cannot_invite_anyone_else(app_mod):
    conn = db_mod.connect()
    pid, _rv = _roster_project(conn)
    sam = db_mod.add_delivery_reviewer(conn, pid, name="Sam Reyes",
                                       invited_by="Dana Whitfield")
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.post(f"/project/{pid}/delivery/delegate",
                      data={"name": "A Fourth Person", "r": sam["token"]},
                      follow_redirects=False).status_code == 403


def test_the_generic_share_link_cannot_invite_anyone(app_mod):
    """Otherwise a forwarded URL mints roster entries, which is the hole this was
    supposed to close rather than widen."""
    conn = db_mod.connect()
    pid, _rv = _roster_project(conn)
    tok = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.post(f"/project/{pid}/delivery/delegate",
                      data={"name": "Anyone", "r": ""},
                      follow_redirects=False).status_code == 403
        assert c.post(f"/project/{pid}/delivery/delegate",
                      data={"name": "Anyone", "r": tok},
                      follow_redirects=False).status_code == 403


def test_an_expired_reviewer_cannot_invite(app_mod):
    conn = db_mod.connect()
    pid, rv = _roster_project(conn)
    roster = db_mod.list_delivery_reviewers(conn, pid)
    roster[0]["expires_at"] = _day(-1)
    db_mod.update_delivery(conn, pid, "reviewers", roster)
    conn.close()
    with TestClient(app_mod.app) as c:
        assert c.post(f"/project/{pid}/delivery/delegate",
                      data={"name": "Sam", "r": rv["token"]},
                      follow_redirects=False).status_code == 403


def test_the_operator_controls_stay_behind_the_gate(tmp_path, monkeypatch):
    """Delegation is a CLIENT act and is exempt from the admin gate; withdrawing and
    extending are OPERATOR acts over the same roster and must not be."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "g.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "the-passphrase")
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app) as c:
        conn = db_mod.connect()
        pid, rv = _roster_project(conn)
        conn.close()
        assert c.post(f"/project/{pid}/delivery/delegate",
                      data={"name": "Sam", "r": rv["token"]},
                      follow_redirects=False).status_code == 303
        blocked = c.post(f"/project/{pid}/delivery/reviewer/revoke",
                         data={"token": rv["token"]}, follow_redirects=False)
        assert "/admin/login" in blocked.headers.get("location", ""), blocked.status_code
    # And it did not merely redirect — nothing was revoked.
    conn = db_mod.connect()
    roster = db_mod.list_delivery_reviewers(conn, pid)
    conn.close()
    assert reviewers.state_of(roster[0]) == reviewers.ACTIVE
