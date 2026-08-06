"""Real accounts and real sessions — added without a way to lock anyone out.

The console had one shared passphrase, which cannot say WHICH human is behind it. That
is why the decision log (ADR-0053) had to record a role rather than a name, and it is
the thing standing between this system and a first hire.

**The invariant these tests exist for: the passphrase keeps working, always.** Accounts
are an addition, not a replacement. A change that could lock the operator out of the
system running their business is not worth any amount of tidiness, and the failure would
arrive at the worst possible moment — mid-deploy, with no way back in. Retiring the
passphrase is a decision to take later, deliberately, with an account already proven.

The rest is the boring security that is only boring when it is right: scrypt from the
stdlib (no new dependency — this repo has twice been bitten by ones production never
installed), session tokens stored as digests (a session table full of live tokens is a
table full of credentials), revocation checked on every request, and a sign-out that
revokes server-side rather than merely forgetting a cookie.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import accounts  # noqa: E402
from chordential_oia.web import db as db_mod  # noqa: E402

PASSPHRASE = "the-shared-passphrase"
PASSWORD = "a-real-password-123"


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "auth.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", PASSPHRASE)
    monkeypatch.delenv("CHORDENTIAL_FIRST_USER", raising=False)
    monkeypatch.delenv("CHORDENTIAL_SEED_DEMO", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass                                   # build the schema
    return mod


def _account(email="jon@chordential.com", name="Jon Shipp", password=PASSWORD):
    conn = db_mod.connect()
    uid = accounts.create_account(conn, email, name, password)
    conn.close()
    return uid


# --------------------------------------------------------------------------- #
# The thing that must never break
# --------------------------------------------------------------------------- #
def test_the_passphrase_still_works_with_no_accounts(app_mod):
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": PASSPHRASE},
                   follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/dashboard", follow_redirects=False).status_code == 200


def test_the_passphrase_STILL_works_once_accounts_exist(app_mod):
    """The break-glass. If accounts are broken, misconfigured, or the only account's
    password is lost, this is the way back into the system."""
    _account()
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": PASSPHRASE},
                   follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/dashboard", follow_redirects=False).status_code == 200


def test_a_wrong_passphrase_still_does_not_get_in(app_mod):
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": "nope"}, follow_redirects=False)
        assert r.status_code == 200            # re-rendered with an error, not a redirect
        assert c.get("/dashboard", follow_redirects=False).status_code == 303


def test_a_broken_session_lookup_does_not_lock_anyone_out(app_mod, monkeypatch):
    """The nightmare: session lookup fails and the gate refuses everyone, including the
    person who needs to get in and fix it. The passphrase path must not depend on it.

    The lookup is broken by MAKING IT RAISE, not by dropping the table — the first
    version of this test dropped `user_session` and then opened a TestClient whose
    lifespan ran `init_db` and recreated it, so it asserted nothing at all and passed
    for the wrong reason.
    """
    def boom(*a, **k):
        raise RuntimeError("session store is down")
    monkeypatch.setattr(accounts, "session_user", boom)
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login", data={"password": PASSPHRASE}, follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/dashboard", follow_redirects=False).status_code == 200


# --------------------------------------------------------------------------- #
# Signing in as a person
# --------------------------------------------------------------------------- #
def test_an_account_can_sign_in_and_is_named(app_mod):
    """The whole point: the decision log stops saying "the operator" and says who."""
    _account()
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login",
                   data={"email": "jon@chordential.com", "password": PASSWORD},
                   follow_redirects=False)
        assert r.status_code == 303
        assert accounts.SESSION_COOKIE in r.cookies
        assert c.get("/dashboard", follow_redirects=False).status_code == 200
        c.post("/opportunity/1/status", data={"status": "Pursuing"},
               follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT * FROM decision_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["actor_label"] == "Jon Shipp", row["actor_label"]
    assert row["actor_ref"].startswith("user:")


def test_the_passphrase_actor_is_still_honest_about_being_shared(app_mod):
    """It must not start claiming to be a person just because accounts now exist."""
    _account()
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"password": PASSPHRASE}, follow_redirects=False)
        c.post("/opportunity/1/status", data={"status": "Pursuing"},
               follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT * FROM decision_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert "shared passphrase" in row["actor_label"]
    assert "Jon" not in row["actor_label"]


def test_a_wrong_password_does_not_sign_in(app_mod):
    _account()
    with TestClient(app_mod.app) as c:
        r = c.post("/admin/login",
                   data={"email": "jon@chordential.com", "password": "wrong-password"},
                   follow_redirects=False)
        assert r.status_code == 200
        assert accounts.SESSION_COOKIE not in r.cookies


def test_signing_out_revokes_the_session_server_side(app_mod):
    """A sign-out that only clears the cookie leaves a token that still works for
    anyone who kept a copy."""
    _account()
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"email": "jon@chordential.com",
                                     "password": PASSWORD}, follow_redirects=False)
        token = c.cookies.get(accounts.SESSION_COOKIE)
        c.get("/admin/logout", follow_redirects=False)
    conn = db_mod.connect()
    assert accounts.session_user(conn, token) is None, "the token still authenticates"
    row = conn.execute("SELECT revoked_at FROM user_session ORDER BY id DESC "
                       "LIMIT 1").fetchone()
    conn.close()
    assert row["revoked_at"], "revoked, not deleted — otherwise there is no record of it"


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def test_the_same_password_never_produces_the_same_hash():
    """Unsalted hashes mean one rainbow table breaks every account at once."""
    a, b = accounts.hash_password(PASSWORD), accounts.hash_password(PASSWORD)
    assert a != b
    assert accounts.verify_password(PASSWORD, a)
    assert accounts.verify_password(PASSWORD, b)


def test_the_password_is_never_stored(app_mod):
    _account()
    conn = db_mod.connect()
    stored = conn.execute("SELECT password_hash FROM user_account").fetchone()[0]
    conn.close()
    assert PASSWORD not in stored
    assert stored.startswith("scrypt$")


def test_the_hash_carries_its_own_parameters():
    """So the cost can be raised later without invalidating every existing password."""
    parts = accounts.hash_password(PASSWORD).split("$")
    assert parts[0] == "scrypt" and len(parts) == 6
    assert int(parts[1]) >= 2 ** 14, "the work factor is too low to be worth doing"


def test_a_short_password_is_refused_with_a_reason(app_mod):
    conn = db_mod.connect()
    with pytest.raises(ValueError) as e:
        accounts.create_account(conn, "x@y.com", "X", "short")
    conn.close()
    assert "10 characters" in str(e.value), "the rule is not stated to the caller"


def test_a_corrupt_hash_fails_closed(app_mod):
    for junk in ("", "not-a-hash", "scrypt$x$y$z$q$r", None):
        assert accounts.verify_password(PASSWORD, junk) is False


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def test_the_session_token_is_never_stored(app_mod):
    """A session table full of live tokens is a table full of credentials — anyone who
    reads a backup could sign in as anyone."""
    uid = _account()
    conn = db_mod.connect()
    token = accounts.start_session(conn, uid, "pytest")
    rows = conn.execute("SELECT * FROM user_session").fetchall()
    conn.close()
    assert token not in str([dict(r) for r in rows])


def test_an_expired_session_stops_working(app_mod):
    uid = _account()
    conn = db_mod.connect()
    token = accounts.start_session(conn, uid)
    assert accounts.session_user(conn, token) is not None
    conn.execute("UPDATE user_session SET expires_at = ?", ("2000-01-01T00:00:00+00:00",))
    conn.commit()
    assert accounts.session_user(conn, token) is None
    conn.close()


def test_a_disabled_account_cannot_use_an_existing_session(app_mod):
    """Disabling someone has to end their access NOW, not in thirty days — that is the
    whole reason the check is on every request rather than at sign-in."""
    uid = _account()
    conn = db_mod.connect()
    token = accounts.start_session(conn, uid)
    conn.execute("UPDATE user_account SET disabled_at = ? WHERE id = ?",
                 ("2026-08-06T00:00:00+00:00", uid))
    conn.commit()
    assert accounts.session_user(conn, token) is None
    assert accounts.authenticate(conn, "jon@chordential.com", PASSWORD) is None
    conn.close()


def test_a_password_change_can_sign_out_everywhere(app_mod):
    """Otherwise changing a password protects nothing that is already logged in."""
    uid = _account()
    conn = db_mod.connect()
    a = accounts.start_session(conn, uid)
    b = accounts.start_session(conn, uid)
    assert accounts.revoke_all_for(conn, uid) == 2
    assert accounts.session_user(conn, a) is None
    assert accounts.session_user(conn, b) is None
    conn.close()


def test_a_forged_token_does_not_authenticate(app_mod):
    _account()
    conn = db_mod.connect()
    assert accounts.session_user(conn, "not-a-real-token") is None
    assert accounts.session_user(conn, "") is None
    conn.close()


# --------------------------------------------------------------------------- #
# The first account
# --------------------------------------------------------------------------- #
def test_the_first_account_can_be_created_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "b.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_FIRST_USER", "jon@chordential.com")
    monkeypatch.setenv("CHORDENTIAL_FIRST_PASSWORD", PASSWORD)
    monkeypatch.setenv("CHORDENTIAL_FIRST_NAME", "Jon Shipp")
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    conn = db_mod.connect()
    row = accounts.get_account(conn, "jon@chordential.com")
    conn.close()
    assert row is not None and row["name"] == "Jon Shipp"


def test_the_bootstrap_never_resets_an_existing_password(app_mod, monkeypatch):
    """Leaving the variables set must not silently overwrite the password on every
    deploy — which would also hand the account to whoever last edited the env."""
    _account()
    monkeypatch.setenv("CHORDENTIAL_FIRST_USER", "jon@chordential.com")
    monkeypatch.setenv("CHORDENTIAL_FIRST_PASSWORD", "a-different-password")
    conn = db_mod.connect()
    assert accounts.bootstrap_from_env(conn) is None
    assert accounts.authenticate(conn, "jon@chordential.com", PASSWORD) is not None
    conn.close()


def test_two_accounts_cannot_share_an_email(app_mod):
    assert _account() is not None
    assert _account(name="Impostor", password="another-password-1") is None
